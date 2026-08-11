"""Hikyuu loader: local A-share (SH/SZ) OHLCV from a Hikyuu data directory.

Hikyuu (https://hikyuu.org) is a local-first C++ quant library that serves
OHLCV from a user-maintained data directory (imported via the Hikyuu data
import tool). It needs no API token and is fully offline once the data is
imported — ideal as the *head* of the A-share fallback chain when a local
data store is present.

Lazy-initialization contract:
  * ``is_available()`` only probes whether ``hikyuu`` can be imported. The
    heavy ``load_hikyuu()`` bootstrap is deferred to the first ``fetch()``
    call, so merely registering the loader never pays the Hikyuu startup
    cost. If Hikyuu is absent/broken (e.g. a missing optional dependency),
    ``is_available()`` returns ``False`` and the registry falls through to
    the rest of the A-share chain (tencent/mootdx/...).

Scope: A-shares (SH/SZ) only, matching the repository symbol convention
``NNNNNN.SH`` / ``NNNNNN.SZ``. Hikyuu's market prefixes are ``sh``/``sz``.
Only ``DAY`` / ``WEEK`` / ``MONTH`` bars are supported.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import cached_loader_fetch, validate_date_range
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

# Interval -> Hikyuu Query ktype constant name. Hikyuu exposes these as
# ``Query.DAY`` / ``Query.WEEK`` / ``Query.MONTH``.
_INTERVAL_KTYPE: dict[str, str] = {
    "1D": "DAY",
    "1W": "WEEK",
    "1M": "MONTH",
}


def _is_a_share(code: str) -> bool:
    """Accept explicit ``.SH/.SZ`` suffix (or bare 6-digit ticker)."""
    upper = code.upper()
    if upper.endswith((".SH", ".SZ")):
        return True
    return len(code) == 6 and code.isdigit()


def _split_symbol(code: str) -> tuple[str, str] | None:
    """Map a repository symbol to ``(market_prefix, code6)``.

    Returns ``("sh", "600000")`` for ``600000.SH`` and ``("sz", "000001")``
    for ``000001.SZ``; ``None`` for non-A-share / unsupported suffixes.
    """
    upper = code.upper()
    if upper.endswith(".SH"):
        return "sh", upper[:6]
    if upper.endswith(".SZ"):
        return "sz", upper[:6]
    if len(code) == 6 and code.isdigit():
        # Bare 6-digit ticker: 6xxxxx/5xxxxx/9xxxxx -> sh, others -> sz.
        prefix = "sh" if code[0] in ("5", "6", "9") else "sz"
        return prefix, code
    return None


@register
class DataLoader:
    """Hikyuu-backed A-share OHLCV loader (local, offline, no auth)."""

    name = "hikyuu"
    markets = {"a_share"}
    requires_auth = False

    def __init__(self) -> None:
        self._sm = None  # StockManager instance, bootstrapped lazily

    def is_available(self) -> bool:
        """Available if ``hikyuu`` imports cleanly.

        Only probes importability — the heavy ``load_hikyuu`` bootstrap is
        deferred to the first ``fetch()`` (see module docstring). Any import
        failure (package absent, broken optional dep) reports unavailable so
        the registry walks on.
        """
        try:
            import hikyuu  # noqa: F401
            return True
        except Exception:  # noqa: BLE001 — any import breakage = unavailable
            return False

    def _ensure_initialized(self):
        """Bootstrap Hikyuu once, lazily, on first use.

        Calls Hikyuu's ``load_hikyuu()`` initializer exactly once, then caches
        the ``StockManager`` for subsequent fetches. If initialization fails
        (e.g. no local data directory), raises so the caller logs the failure
        and the registry falls back.
        """
        if self._sm is not None:
            return self._sm

        try:
            from hikyuu import Datetime, Query, StockManager, load_hikyuu
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"hikyuu import failed: {exc}") from exc

        logger.info("[hikyuu] calling hikyuu.load_hikyuu() (one-time bootstrap)")
        try:
            load_hikyuu()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"hikyuu load_hikyuu() failed: {exc}") from exc

        logger.info("[hikyuu] calling StockManager.instance()")
        self._sm = StockManager.instance()
        self._Query = Query
        self._Datetime = Datetime
        return self._sm

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch A-share OHLCV via Hikyuu.

        Args:
            codes: Symbol list (e.g. ``["600000.SH", "000001.SZ"]``). Bare
                6-digit tickers are accepted; non-A-share symbols are skipped.
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
            interval: Bar size. Supports ``1D`` / ``1W`` / ``1M`` only.
            fields: Ignored.

        Returns:
            Mapping symbol -> OHLCV DataFrame.
        """
        validate_date_range(start_date, end_date)

        # Daily/weekly/monthly only; do not silently return day bars for a
        # 1H/4H/1m request. Warn and return empty so the caller's fallback
        # chain proceeds to a same-market source.
        if interval not in _INTERVAL_KTYPE:
            logger.warning(
                "hikyuu supports DAY/WEEK/MONTH bars only; rejecting interval=%r",
                interval,
            )
            return {}

        try:
            sm = self._ensure_initialized()
        except Exception as exc:  # noqa: BLE001 — init failure -> fall back
            logger.warning("hikyuu init failed: %s", exc)
            return {}

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            if not _is_a_share(code):
                logger.debug("hikyuu: skipping non-A-share symbol %s", code)
                continue
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe=interval,
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda code=code: self._fetch_one(
                        sm, code, start_date, end_date, interval,
                    ),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:
                logger.warning("hikyuu failed for %s: %s", code, exc)
        logger.info(
            "[hikyuu] OHLCV fetch interval=%s -> %d symbol(s) served from local store",
            interval, len(result),
        )
        return result

    def _fetch_one(
        self, sm, code: str, start_date: str, end_date: str, interval: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single A-share symbol from Hikyuu's local store."""
        parsed = _split_symbol(code)
        if parsed is None:
            return None
        market_prefix, symbol = parsed

        logger.info("[hikyuu] calling StockManager.get_stock('%s%s')", market_prefix, symbol)
        stock = sm.get_stock(f"{market_prefix}{symbol}")
        if stock is None:
            logger.warning("[hikyuu] StockManager.get_stock(%s) -> None (unknown stock)", code)
            return None

        Query = self._Query
        Datetime = self._Datetime
        ktype = getattr(Query, _INTERVAL_KTYPE[interval])
        # ``Query.FORWARD`` returns forward-adjusted (前复权) bars, so historical
        # prices reflect splits/dividends relative to the latest quote.
        logger.info(
            "[hikyuu] calling Stock.get_kdata(Query.%s, FORWARD) for %s [%s, %s]",
            _INTERVAL_KTYPE[interval], code, start_date, end_date,
        )
        kdata = stock.get_kdata(
            Query(
                Datetime(start_date),
                Datetime(end_date),
                ktype=ktype,
                recover_type=Query.FORWARD,
            )
        )
        if kdata is None or len(kdata) == 0:
            return None

        rows = []
        for k in kdata:
            # k.datetime is a hikyuu Datetime; .datetime() yields a Python
            # datetime that pandas can index.
            trade_date = k.datetime.datetime()
            rows.append(
                {
                    "trade_date": trade_date,
                    "open": k.open,
                    "high": k.high,
                    "low": k.low,
                    "close": k.close,
                    "volume": k.volume,
                }
            )
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.set_index("trade_date").sort_index()
        df = df[["open", "high", "low", "close", "volume"]].dropna(
            subset=["open", "high", "low", "close"]
        )
        return df if not df.empty else None
