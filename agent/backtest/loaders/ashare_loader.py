"""ashare loader: local A-share OHLCV from an ashare Parquet data directory.

ashare collects A-share data over the TDX protocol and writes hive-partitioned
Parquet files. This loader reads them with duckdb — the query engine this repo
already ships — so it needs no extra dependency and makes no network call. It is
the head of the A-share fallback chain whenever the data directory is present.

Data contract (ashare ``docs/prd.md``):
  * ``kline_day/`` — stock daily bars, unadjusted, volume in lots (手);
  * ``index_day/`` — index daily bars (market and board indices);
  * ``xdxr/`` — corporate-action events (dividend / bonus / rights, per 10 shares).

Files are append-only: a corrected row lands in a new file, so reads dedup
``(code, date)`` by ``_ingested_at`` — the same rule as ashare's own
``data/_views.sql``. When a code appears in both bar datasets the stock bar wins
(``kline_day`` before ``index_day``).

Prices are served forward-adjusted (前复权). ashare stores unadjusted bars plus
the raw events, and the multiplicative ratio is computed here at query time —
the same shape as the retired hikyuu loader's ``Query.FORWARD``. The ratio is
anchored at the last bar of the requested window (the ``cn_adjust.apply_qfq``
convention): absolute levels depend on the range, returns do not. A window that
ends at the dataset's latest bar therefore equals anchoring at the latest date.
Volume is divided by the same ratio so share counts and VWAP stay on one basis.

Scope: daily bars of A-share stocks and indices. ashare does not collect fund /
ETF quotes, so such symbols are simply absent and the registry chain falls
through to tencent; minute-bar requests return ``{}`` for the same reason and
``market_data._fetch_via_chain`` walks on to eastmoney/tushare.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from backtest.loaders.base import (
    cached_loader_fetch,
    validate_date_range,
    validate_ohlc,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_DAILY_INTERVALS = frozenset({"1d", "d", "day", "daily"})
_DEFAULT_DATA_DIR = Path.home() / ".vibe-trading" / "ashare" / "data"

# Read in this order; a (code, date) present in both is served by the earlier one.
_BAR_DATASETS = ("kline_day", "index_day")
_EVENT_DATASET = "xdxr"

_OHLCV = ("open", "high", "low", "close", "volume")
_PRICE_COLUMNS = ("open", "high", "low", "close")


def _data_dir() -> Path:
    """Configured ashare data directory (``VIBE_ASHARE_DATA_DIR`` or the default).

    Read through the config layer — no raw ``os.getenv`` outside ``src/config/``.
    """
    from src.config.accessor import get_env_config

    configured = get_env_config().data.vibe_ashare_data_dir
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser()
    return _DEFAULT_DATA_DIR


def _sql_str(value: Any) -> str:
    """Quote a value as a SQL string literal (paths cannot be bound parameters)."""
    return "'" + str(value).replace("'", "''") + "'"


def _split_symbol(code: str) -> Optional[Tuple[str, str]]:
    """Map a repository symbol to ``(code6, exchange)``.

    ``600000.SH`` -> ``("600000", "SH")``; a bare 6-digit ticker infers the
    exchange from its prefix (5/6/9 -> SH, 4/8 -> BJ, else SZ). Returns ``None``
    for anything that is not an A-share symbol.
    """
    upper = str(code).strip().upper()
    if "." in upper:
        body, _, suffix = upper.rpartition(".")
        if suffix in ("SH", "SZ", "BJ") and len(body) == 6 and body.isdigit():
            return body, suffix
        return None
    if len(upper) == 6 and upper.isdigit():
        if upper[0] in ("5", "6", "9"):
            return upper, "SH"
        if upper[0] in ("4", "8"):
            return upper, "BJ"
        return upper, "SZ"
    return None


def _is_a_share(code: str) -> bool:
    """Whether ``code`` is an A-share symbol this source can serve."""
    return _split_symbol(code) is not None


def _query_bars(
    con: Any, root: Path, code: str, exchange: str, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """Read and dedup the raw daily bars of one symbol over a date window."""
    branches: List[str] = []
    for priority, dataset in enumerate(_BAR_DATASETS):
        directory = root / dataset
        if not directory.is_dir():
            continue
        # An empty dataset directory (created but not yet compacted) would make
        # the glob raise; skip it so the other dataset can still serve.
        if next(directory.rglob("*.parquet"), None) is None:
            continue
        branches.append(
            "SELECT code, exchange, date, open, high, low, close, volume,"
            f" _ingested_at, filename, {priority} AS _ds"
            f" FROM read_parquet({_sql_str(str(directory / '**' / '*.parquet'))},"
            " hive_partitioning = true, union_by_name = true, filename = true)"
            f" WHERE code = {_sql_str(code)}"
            f" AND exchange = {_sql_str(exchange)}"
            f" AND date BETWEEN CAST({_sql_str(start_date)} AS DATE)"
            f" AND CAST({_sql_str(end_date)} AS DATE)"
        )
    if not branches:
        return None

    sql = (
        f"WITH bars AS ({' UNION ALL '.join(branches)})"
        " SELECT date, open, high, low, close, volume FROM ("
        "   SELECT *, row_number() OVER ("
        "     PARTITION BY code, date"
        "     ORDER BY _ds, _ingested_at DESC, filename DESC) AS _rn"
        "   FROM bars) t"
        " WHERE _rn = 1 ORDER BY date"
    )
    frame = con.execute(sql).df()
    if frame.empty:
        return None
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date").rename_axis("trade_date")


def _query_events(
    con: Any, root: Path, code: str, exchange: str, start_date: str, end_date: str
) -> Optional[pd.DataFrame]:
    """Read and dedup the corporate-action events of one symbol in the window.

    Only events strictly after ``start_date`` can affect an in-window bar, so the
    query is bounded by the window; an event on the window's first bar is
    harmlessly skipped later (it has no earlier bar to scale).
    """
    directory = root / _EVENT_DATASET
    if not directory.is_dir():
        return None
    sql = (
        "WITH ev AS ("
        " SELECT code, date, fenhong, peigujia, songzhuangu, peigu,"
        " _ingested_at, filename"
        f" FROM read_parquet({_sql_str(str(directory / '**' / '*.parquet'))},"
        " hive_partitioning = true, union_by_name = true, filename = true)"
        f" WHERE code = {_sql_str(code)}"
        f" AND exchange = {_sql_str(exchange)}"
        f" AND date BETWEEN CAST({_sql_str(start_date)} AS DATE)"
        f" AND CAST({_sql_str(end_date)} AS DATE))"
        " SELECT date, fenhong, peigujia, songzhuangu, peigu FROM ("
        "   SELECT *, row_number() OVER ("
        "     PARTITION BY code, date"
        "     ORDER BY _ingested_at DESC, filename DESC) AS _rn"
        "   FROM ev) t"
        " WHERE _rn = 1 ORDER BY date"
    )
    frame = con.execute(sql).df()
    if frame.empty:
        return None
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def _as_float(value: Any) -> float:
    """Coerce an event cell to float, treating missing values as zero."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _apply_forward_adjustment(bars: pd.DataFrame, events: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Scale raw bars onto the forward-adjusted (前复权) ratio basis.

    Each event contributes ``factor = theoretical_ex_price / prev_close`` where
    ``prev_close`` is the raw close of the last bar before the ex-date and
    ``theoretical_ex_price`` folds the per-10-share dividend, bonus and rights
    terms into one reference price. Every bar before an ex-date is multiplied by
    that event's factor, so the cumulative product is anchored at the window's
    last bar.

    A factor that cannot be formed (no earlier bar in the window, a
    non-positive theoretical price, or a missing/zero event) is skipped with a
    log line rather than producing a bad price. Frames with nothing to apply and
    indices (which carry no events) are returned unchanged.
    """
    if bars.empty or events is None or events.empty:
        return bars

    ratios = pd.Series(1.0, index=bars.index, dtype="float64")
    applied = False
    for event in events.sort_values("date").to_dict("records"):
        ex_date = pd.Timestamp(event["date"])
        prior = bars.index < ex_date
        if not prior.any():
            logger.debug(
                "ashare: xdxr event %s precedes every bar in the window; skipped",
                ex_date.date(),
            )
            continue
        prev_close = float(bars.loc[prior, "close"].iloc[-1])
        if not math.isfinite(prev_close) or prev_close <= 0:
            continue

        dividend = _as_float(event.get("fenhong")) / 10.0
        rights_price = _as_float(event.get("peigujia"))
        bonus_ratio = _as_float(event.get("songzhuangu")) / 10.0
        rights_ratio = _as_float(event.get("peigu")) / 10.0
        theoretical = (prev_close - dividend + rights_price * rights_ratio) / (1.0 + bonus_ratio + rights_ratio)
        if not math.isfinite(theoretical) or theoretical <= 0:
            logger.warning(
                "ashare: xdxr event %s yields a non-positive theoretical ex price; skipped",
                ex_date.date(),
            )
            continue

        factor = theoretical / prev_close
        if abs(factor - 1.0) < 1e-12:
            continue
        ratios[prior] = ratios[prior] * factor
        applied = True

    if not applied:
        return bars

    out = bars.copy()
    for column in _PRICE_COLUMNS:
        out[column] = out[column] * ratios
    if "volume" in out.columns:
        out["volume"] = out["volume"] / ratios
    out.attrs["adjustment"] = "split_dividend"
    return out


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    """Hold a frame to the loader output contract.

    ``validate_ohlc`` returns a new frame, so the provenance attrs (notably
    ``adjustment``) are carried across explicitly — dropping them would make the
    caliber read as ``unknown`` downstream.
    """
    attrs = dict(frame.attrs)
    for column in _OHLCV:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(_OHLCV)).sort_index()
    frame = validate_ohlc(frame)
    frame.index.name = "trade_date"
    frame.attrs.update(attrs)
    return frame


@register
class DataLoader:
    """ashare-backed A-share OHLCV loader (local, offline, no auth)."""

    name = "ashare"
    markets = {"a_share"}
    # ashare writes kline_day volume in lots (手), like the tencent A-share feed.
    volume_units = {"a_share": "lots"}
    requires_auth = False

    def is_available(self) -> bool:
        """Available when duckdb imports and a bar dataset directory exists.

        A cheap path probe only: no file is read and no network is touched, so an
        absent or half-synced directory reports unavailable and the registry
        walks on to the next source.
        """
        try:
            import duckdb  # noqa: F401
        except Exception:  # noqa: BLE001 - any import breakage = unavailable
            return False
        root = _data_dir()
        return any((root / dataset).is_dir() for dataset in _BAR_DATASETS)

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch forward-adjusted daily bars.

        Args:
            codes: Symbols, e.g. ``["600037.SH", "000300.SH"]``. Non-A-share
                symbols are skipped.
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
            interval: Daily aliases only; anything else warns and returns ``{}``
                so the caller's chain proceeds to a minute-capable source.
            fields: Ignored.

        Returns:
            Mapping symbol -> OHLCV DataFrame indexed by ``trade_date``,
            forward-adjusted when the symbol has corporate actions in the window.
        """
        validate_date_range(start_date, end_date)
        del fields

        if interval.strip().lower() not in _DAILY_INTERVALS:
            logger.warning("ashare serves daily bars only; rejecting interval=%r", interval)
            return {}

        root = _data_dir()
        if not any((root / dataset).is_dir() for dataset in _BAR_DATASETS):
            logger.warning("ashare: no bar dataset under %s", root)
            return {}

        try:
            import duckdb
        except Exception as exc:  # noqa: BLE001 - duckdb is a base dependency
            logger.warning("ashare: duckdb unavailable: %s", exc)
            return {}

        result: Dict[str, pd.DataFrame] = {}
        con = duckdb.connect()
        try:
            for code in codes:
                parsed = _split_symbol(code)
                if parsed is None:
                    logger.debug("ashare: skipping non-A-share symbol %s", code)
                    continue
                try:
                    frame = cached_loader_fetch(
                        source=self.name,
                        symbol=code,
                        timeframe=interval,
                        start_date=start_date,
                        end_date=end_date,
                        fields=None,
                        fetch=lambda code=code, parsed=parsed: self._fetch_one(
                            con, root, code, parsed, start_date, end_date
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - per-symbol isolation
                    logger.warning("ashare failed for %s: %s", code, exc)
                    continue
                if frame is not None and not frame.empty:
                    result[code] = frame
        finally:
            con.close()

        logger.info(
            "ashare: %d/%d symbol(s) served from %s",
            len(result),
            len(codes),
            root,
        )
        return result

    def _fetch_one(
        self,
        con: Any,
        root: Path,
        code: str,
        parsed: Tuple[str, str],
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Read, adjust and normalize one symbol; ``None`` when it has no bars."""
        symbol, exchange = parsed
        bars = _query_bars(con, root, symbol, exchange, start_date, end_date)
        if bars is None or bars.empty:
            logger.debug("ashare: no bars for %s in %s..%s", code, start_date, end_date)
            return None
        events = _query_events(con, root, symbol, exchange, start_date, end_date)
        return _normalize(_apply_forward_adjustment(bars, events))
