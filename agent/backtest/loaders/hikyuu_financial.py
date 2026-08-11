"""Hikyuu-backed A-share financial-statement accessor (local data directory).

Companion to :mod:`backtest.loaders.hikyuu_loader` (OHLCV). This module exposes
the per-report-period financial statements Hikyuu keeps in its local store, so
the ``get_financial_statements`` tool can serve A-share balance/income/cashflow
and key indicators without any network call, falling back to Eastmoney only
when Hikyuu has no local data.

Design notes:
  * Field keys are Hikyuu's *Chinese* account names (e.g. ``利润表_营业收入``,
    ``资产负债表_资产总计``). This mirrors how the same tool already returns
    SEC's us-gaap concept names for US equities: each market/data-source keeps
    its own field vocabulary, which the LLM reads directly. No English-mapping
    table is maintained (and none is required — nothing in the codebase looks
    up these keys; the periods dict is passed through to the LLM).
  * Output periods are aligned to the report date (``REPORT_DATE``) exactly as
    the Eastmoney path is, with the same ``annual``/``quarter`` period filter.
  * Lazy initialization: ``is_available()`` only probes ``import hikyuu``; the
    heavy ``load_hikyuu()`` bootstrap runs on the first ``fetch()``.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from backtest.loaders.hikyuu_loader import _is_a_share, _split_symbol

logger = logging.getLogger(__name__)

# Hard cap on returned periods, matching the Eastmoney tool's _MAX_PERIODS.
_MAX_PERIODS = 40

# statement -> list of Hikyuu field prefixes to collect (order = output order).
# balance/income/cashflow map to the corresponding report prefix.
_STATEMENT_PREFIXES: dict[str, List[str]] = {
    "balance": ["资产负债表_"],
    "income": ["利润表_"],
    "cashflow": ["现金流量表_"],
    # indicators = per-share metrics + financial-ratio groups. The per-share
    # fields have no underscore prefix (index < 7), so they are listed as
    # exact names; the ratio groups are collected by prefix.
    "indicators": [
        "基本每股收益",
        "扣除非经常性损益每股收益",
        "每股未分配利润",
        "每股净资产",
        "每股资本公积金",
        "净资产收益率",
        "每股经营现金流量",
        "盈利能力_",
        "成长能力_",
        "偿债能力_",
        "营运能力_",
        "资本结构_",
        "现金能力_",
    ],
}

# The four statement values accepted by the tool.
_VALID_STATEMENTS = tuple(_STATEMENT_PREFIXES.keys())


def is_available() -> bool:
    """True when ``hikyuu`` imports cleanly (local data directory present)."""
    try:
        import hikyuu  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - any import breakage = unavailable
        return False


class HikyuuFinancial:
    """Lazily-bootstrapped accessor for Hikyuu financial statements."""

    def __init__(self) -> None:
        self._sm = None

    def _ensure_initialized(self):
        """Run ``load_hikyuu()`` once and cache the StockManager."""
        if self._sm is not None:
            return self._sm
        try:
            from hikyuu import StockManager, load_hikyuu
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"hikyuu import failed: {exc}") from exc
        logger.info("[hikyuu] calling hikyuu.load_hikyuu() (one-time bootstrap)")
        load_hikyuu()
        logger.info("[hikyuu] calling StockManager.instance()")
        self._sm = StockManager.instance()
        return self._sm

    def fetch(
        self,
        code: str,
        statement: str = "indicators",
        period: str = "annual",
        max_periods: int = _MAX_PERIODS,
    ) -> Optional[List[dict]]:
        """Return per-report-period financial rows for an A-share symbol.

        Args:
            code: A-share symbol, e.g. ``"600519.SH"`` / ``"000001.SZ"``.
            statement: ``balance`` / ``income`` / ``cashflow`` / ``indicators``.
            period: ``annual`` (keep fiscal year-end rows only) or ``quarter``
                (full series).
            max_periods: Most-recent period count cap.

        Returns:
            ``list[dict]`` newest-first, each with ``REPORT_DATE`` plus Hikyuu
            Chinese account fields; or ``None`` when Hikyuu is unavailable,
            cannot be initialized, or has no data for ``code`` (so the caller
            can fall back to Eastmoney).

        Raises:
            ValueError: If ``code`` is not A-share or ``statement`` is invalid.
        """
        if statement not in _VALID_STATEMENTS:
            raise ValueError(
                f"hikyuu financial: unsupported statement {statement!r}; "
                f"choose from {list(_VALID_STATEMENTS)}"
            )
        if not _is_a_share(code):
            raise ValueError(f"hikyuu financial is A-share only; got '{code}'")
        parsed = _split_symbol(code)
        if parsed is None:
            raise ValueError(f"could not resolve A-share symbol '{code}'")
        market_prefix, symbol = parsed

        sm = self._ensure_initialized()
        logger.info("[hikyuu] calling StockManager.get_stock('%s%s')", market_prefix, symbol)
        stock = sm.get_stock(f"{market_prefix}{symbol}")
        if stock is None:
            logger.warning("[hikyuu] StockManager.get_stock(%s) -> None (unknown stock)", code)
            return None

        logger.info("[hikyuu] calling Stock.get_history_finance() for %s", code)
        try:
            history = stock.get_history_finance()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[hikyuu] Stock.get_history_finance() failed for %s: %s", code, exc)
            return None

        prefixes = _STATEMENT_PREFIXES[statement]
        rows: List[dict] = []
        for item in history:
            end_date = _report_date(item[0])
            if end_date is None:
                continue
            if period == "annual" and not end_date.endswith("-12-31"):
                continue
            row = {"REPORT_DATE": end_date}
            row.update(_collect_fields(item[2], prefixes))
            rows.append(row)

        rows.sort(key=lambda r: r["REPORT_DATE"], reverse=True)
        if not rows:
            logger.info("[hikyuu] %s: no %s/%s rows in local store (will fall back)", code, statement, period)
            return None
        logger.info(
            "[hikyuu] %s statement=%s period=%s -> %d report period(s) from local store",
            code, statement, period, min(len(rows), max_periods),
        )
        return rows[:max_periods]


def _report_date(value: Any) -> Optional[str]:
    """Extract ``YYYY-MM-DD`` from a hikyuu report Datetime."""
    try:
        return value.datetime().strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return None


def _collect_fields(fields: Any, prefixes: List[str]) -> dict:
    """Map the raw 584-field row to a dict keyed by Hikyuu Chinese account names.

    Fields are collected in ``prefixes`` order so output is deterministic. A
    prefix ending in ``_`` matches any field name starting with it; a bare
    prefix matches the exact field name (used for the per-share indicators).
    """
    out: dict[str, Any] = {}
    for prefix in prefixes:
        for idx, name in _indexed_names(fields, prefix):
            out[name] = _field_value(fields, idx)
    return out


# The field-name -> index map is resolved once per process from the StockManager.
_field_index_map: Optional[dict[str, int]] = None


def _indexed_names(fields: Any, prefix: str):
    """Yield ``(index, name)`` for every field matching ``prefix``.

    ``fields`` is the raw 584-length row; its indices align with
    ``StockManager.get_history_finance_all_fields()``.
    """
    global _field_index_map
    if _field_index_map is None:
        from hikyuu import StockManager  # noqa: PLC0415 - lazy
        logger.info("[hikyuu] calling StockManager.get_history_finance_all_fields() (one-time cache)")
        _field_index_map = {
            name: idx for idx, name in StockManager.instance().get_history_finance_all_fields()
        }
    if prefix.endswith("_"):
        for name, idx in _field_index_map.items():
            if name.startswith(prefix):
                yield idx, name
    else:
        idx = _field_index_map.get(prefix)
        if idx is not None:
            yield idx, prefix


def _field_value(fields: Any, index: int) -> Optional[float]:
    """Read a numeric field from the raw row, or ``None`` for missing/zero."""
    try:
        value = fields[index]
        if value is None or value == "":
            return None
        value = float(value)
        return value if value != 0.0 else None
    except (TypeError, ValueError, IndexError):
        return None
