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

# statement -> list of Hikyuu field names to collect (order = output order).
#
# Each entry is an *exact* Hikyuu account field name (verified against
# ``StockManager.get_history_finance_all_fields()``). Collecting an explicit
# core-field whitelist (rather than every field under a ``_``-suffixed prefix)
# keeps each period small enough that the full period series fits under the
# tool's character limit without paging. balance/income/cashflow use their
# corresponding report-prefixed names; indicators mixes bare per-share fields
# (no prefix) with a curated set of ratio-group fields.
_STATEMENT_PREFIXES: dict[str, List[str]] = {
    "balance": [
        "资产负债表_货币资金",
        "资产负债表_应收票据",
        "资产负债表_应收账款",
        "资产负债表_预付款项",
        "资产负债表_其他应收款",
        "资产负债表_存货",
        "资产负债表_流动资产合计",
        "资产负债表_固定资产",
        "资产负债表_在建工程",
        "资产负债表_无形资产",
        "资产负债表_商誉",
        "资产负债表_资产总计",
        "资产负债表_应付票据",
        "资产负债表_应付账款",
        "资产负债表_其他应付款",
        "资产负债表_短期借款",
        "资产负债表_长期借款",
        "资产负债表_应付债券",
        "资产负债表_流动负债合计",
        "资产负债表_负债合计",
        "资产负债表_所有者权益（或股东权益）合计",
        "资产负债表_未分配利润",
        "资产负债表_实收资本（或股本）",
    ],
    "income": [
        "利润表_营业收入",
        "利润表_营业成本",
        "利润表_营业税金及附加",
        "利润表_销售费用",
        "利润表_管理费用",
        "利润表_财务费用",
        "利润表_研发费用",
        "利润表_营业利润",
        "利润表_利润总额",
        "利润表_净利润",
        "利润表_归属于母公司所有者的净利润",
        "利润表_稀释每股收益",
    ],
    "cashflow": [
        "现金流量表_销售商品、提供劳务收到的现金",
        "现金流量表_经营活动产生的现金流量净额",
        "现金流量表_投资活动产生的现金流量净额",
        "现金流量表_购建固定资产、无形资产和其他长期资产支付的现金",
        "现金流量表_筹资活动产生的现金流量净额",
        "现金流量表_分配股利、利润或偿付利息支付的现金",
        "现金流量表_现金及现金等价物净增加额",
    ],
    # indicators = per-share metrics + financial-ratio groups. The per-share
    # fields have no underscore prefix (index < 7), so they are listed as
    # exact names; the ratio groups are collected by exact field name.
    "indicators": [
        "基本每股收益",
        "扣除非经常性损益每股收益",
        "每股未分配利润",
        "每股净资产",
        "每股资本公积金",
        "净资产收益率",
        "每股经营现金流量",
        "盈利能力_销售毛利率",
        "盈利能力_销售净利率",
        "盈利能力_总资产报酬率",
        "盈利能力_扣除非经常性损益后的净利润",
        "成长能力_营业收入增长率",
        "成长能力_净利润增长率",
        "偿债能力_流动比率",
        "偿债能力_速动比率",
        "资本结构_资产负债率",
        "营运能力_总资产周转率",
        "营运能力_存货周转率",
        "现金能力_每股经营性现金流",
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
    name ending in ``_`` matches every field starting with it; a bare name
    matches the exact field name. ``_STATEMENT_PREFIXES`` now supplies exact
    core-field names, so each period carries only the whitelisted accounts.
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
