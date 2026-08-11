"""Hikyuu-backed A-share shareholder-count accessor (local data directory).

Companion to :mod:`backtest.loaders.hikyuu_loader` (OHLCV). This module exposes
the *shareholder disclosure* slice of Hikyuu's local financial store so the
``get_shareholder_count`` tool can serve shareholder-count data without any
network call, and fall back to Eastmoney only when Hikyuu has no local data.

Scope & data:
  * A-shares only (SH/SZ, matching ``NNNNNN.SH`` / ``NNNNNN.SZ``).
  * Per report period (``END_DATE``) it yields:
      - ``holder_count``: 股东户数 (field ``股本股东_股东人数``)
      - ``avg_hold_shares``: 户均持股 = 当期流通A股 ÷ 当期股东户数
      - ``total_market_cap``: 总市值 = 当期总股本 × 报告期当日收盘价
      - ``holder_count_change`` / ``holder_count_change_pct``: vs the prior period
  All three core figures are aligned to the *same* report period, not to the
  latest quote, so the output is directly comparable to Eastmoney's datacenter
  report.

Lazy initialization mirrors ``hikyuu_loader``: ``is_available()`` only probes
``import hikyuu``; the heavy ``load_hikyuu()`` bootstrap runs on first use.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from backtest.loaders.hikyuu_loader import _is_a_share, _split_symbol

logger = logging.getLogger(__name__)

# Hikyuu historical-finance field indices (0-based), located at import time via
# ``StockManager.get_history_finance_field_index``.
_FIELD_HOLDER = "股本股东_股东人数"
_FIELD_LIUTONG = "股本股东_已上市流通A股"
_FIELD_ZONGGUBEN = "股本股东_总股本"
_FIELD_INDICES = (_FIELD_HOLDER, _FIELD_LIUTONG, _FIELD_ZONGGUBEN)

# Hard cap on returned periods, matching the Eastmoney tool.
_MAX_PERIODS = 24


def is_available() -> bool:
    """True when ``hikyuu`` imports cleanly (local data directory present)."""
    try:
        import hikyuu  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - any import breakage = unavailable
        return False


class HikyuuShareholder:
    """Lazily-bootstrapped accessor for Hikyuu shareholder-count data."""

    def __init__(self) -> None:
        self._sm = None
        self._field_index: dict[str, int] | None = None

    # -- bootstrap --------------------------------------------------------- #

    def _ensure_initialized(self):
        """Run ``load_hikyuu()`` once and cache StockManager + field indices."""
        if self._sm is not None:
            return self._sm
        try:
            from hikyuu import Query, StockManager, load_hikyuu
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"hikyuu import failed: {exc}") from exc

        logger.info("[hikyuu] calling hikyuu.load_hikyuu() (one-time bootstrap)")
        load_hikyuu()
        logger.info("[hikyuu] calling StockManager.instance()")
        sm = StockManager.instance()
        # Cache the field indices so we don't re-query them per fetch.
        logger.info(
            "[hikyuu] calling StockManager.get_history_finance_field_index() for %d field(s)",
            len(_FIELD_INDICES),
        )
        self._field_index = {
            name: sm.get_history_finance_field_index(name)
            for name in _FIELD_INDICES
        }
        self._Query = Query
        self._sm = sm
        return sm

    # -- public API -------------------------------------------------------- #

    def fetch(
        self, code: str, max_periods: int = _MAX_PERIODS
    ) -> Optional[List[dict]]:
        """Return per-report-period shareholder records for an A-share symbol.

        Args:
            code: A-share symbol, e.g. ``"600519.SH"`` / ``"000001.SZ"``.
            max_periods: Most-recent period count cap.

        Returns:
            ``list[dict]`` newest-first, or ``None`` when the symbol has no
            shareholder disclosure in the local Hikyuu store. Raises when
            Hikyuu is unavailable or initialization fails (so the caller can
            fall back to Eastmoney).

        Raises:
            RuntimeError: If Hikyuu cannot be imported or initialized.
            ValueError: If ``code`` is not an A-share symbol.
        """
        if not _is_a_share(code):
            raise ValueError(
                f"hikyuu shareholder count is A-share only; got '{code}'"
            )
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

        periods = self._build_periods(code, stock, history)
        if not periods:
            logger.info("[hikyuu] %s: no shareholder data in local store (will fall back)", code)
            return None
        logger.info(
            "[hikyuu] %s shareholder-count -> %d report period(s) from local store",
            code, min(len(periods), max_periods),
        )
        return periods[:max_periods]

    # -- internals --------------------------------------------------------- #

    def _build_periods(self, code: str, stock: Any, history: Any) -> List[dict]:
        """Convert raw history rows into aligned, newest-first period dicts.

        A period contributes only when the report date and holder count are both
        usable; ``avg_hold_shares`` and ``total_market_cap`` derive from *that*
        period's own share counts and END_DATE price, so they stay aligned.
        """
        holder_idx = self._field_index[_FIELD_HOLDER]
        liutong_idx = self._field_index[_FIELD_LIUTONG]
        zongguben_idx = self._field_index[_FIELD_ZONGGUBEN]

        rows: List[dict] = []
        for item in history:
            fields = item[2]
            end_date = _report_date(item[0])
            holder_count = _num(fields, holder_idx)
            if end_date is None or holder_count is None:
                continue

            liutong = _num(fields, liutong_idx)
            zongguben = _num(fields, zongguben_idx)
            avg_hold_shares = (
                round(liutong / holder_count, 2)
                if liutong is not None and holder_count
                else None
            )
            total_market_cap = self._market_cap(stock, end_date, zongguben)

            rows.append(
                {
                    "end_date": end_date,
                    "holder_count": holder_count,
                    "holder_count_change": None,  # filled below, vs prior period
                    "holder_count_change_pct": None,
                    "avg_hold_shares": avg_hold_shares,
                    "avg_hold_amount": (
                        round(total_market_cap / holder_count, 2)
                        if total_market_cap is not None and holder_count
                        else None
                    ),
                    "total_market_cap": total_market_cap,
                }
            )

        rows.sort(key=lambda r: r["end_date"], reverse=True)
        # Compute QoQ change from the chronologically-previous period.
        for i, row in enumerate(rows):
            prev = rows[i + 1] if i + 1 < len(rows) else None
            if prev is None or row["holder_count"] is None or prev["holder_count"] in (None, 0):
                continue
            diff = row["holder_count"] - prev["holder_count"]
            row["holder_count_change"] = diff
            row["holder_count_change_pct"] = round(diff / prev["holder_count"] * 100.0, 2)
        return rows

    def _market_cap(self, stock: Any, end_date: str, zongguben: Optional[float]) -> Optional[float]:
        """Total market cap = period total shares x END_DATE close price."""
        if zongguben is None:
            return None
        price = self._close_on(stock, end_date)
        if price is None:
            return None
        return round(zongguben * price, 2)

    def _close_on(self, stock: Any, end_date: str) -> Optional[float]:
        """Closing price on the report date (``end_date``).

        Hikyuu's ``Query`` is a half-open interval ``[start, end)``: querying
        ``[end_date, next_day)`` yields the report date's own bar (if it is a
        trading day) or the next session.
        """
        try:
            from hikyuu import Datetime  # noqa: PLC0415 - lazy
        except Exception:  # noqa: BLE001
            return None
        start = Datetime(end_date)
        logger.debug(
            "[hikyuu] calling Stock.get_kdata(Query.DAY, FORWARD) for %s close price",
            end_date,
        )
        kdata = stock.get_kdata(
            self._Query(
                start,
                start.next_day(),
                ktype=self._Query.DAY,
                recover_type=self._Query.FORWARD,
            )
        )
        if kdata is None or len(kdata) == 0:
            return None
        return float(kdata[0].close)


def _report_date(value: Any) -> Optional[str]:
    """Extract ``YYYY-MM-DD`` from a hikyuu report Datetime."""
    try:
        return value.datetime().strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return None


def _num(fields: Any, index: int) -> Optional[float]:
    """Read a numeric field from the raw history row, or ``None``."""
    try:
        value = fields[index]
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError, IndexError):
        return None
