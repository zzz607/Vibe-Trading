"""ashare-backed A-share shareholder-count accessor (local Parquet directory).

Companion to :mod:`backtest.loaders.ashare_loader` (OHLCV). It exposes the
shareholder slice of ashare's ``history_finance`` dataset so
``get_shareholder_count`` can answer without a network call and fall back to
Eastmoney only when the local directory has nothing.

Per report period it yields the same shape as the hikyuu precedent:
``holder_count`` (股本股东_股东人数), ``avg_hold_shares`` (period float A-shares
÷ period holder count), ``total_market_cap`` (period total shares × that
period's close) and the change against the chronologically previous period. All
figures stay aligned to the *same* report period, so the series is directly
comparable with Eastmoney's datacenter report.

A report date that is not itself a trading day resolves to the next session
within ten calendar days, else the previous one — the period-end valuation
convention the hikyuu precedent used.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd

from backtest.loaders.ashare_financial import (
    _cell,
    _quote,
    field_map,
    is_available as _financial_available,
    query_history,
)
from backtest.loaders.ashare_loader import _data_dir, _is_a_share, _split_symbol

logger = logging.getLogger(__name__)

_FIELD_HOLDER = "股本股东_股东人数"
_FIELD_FLOAT_A = "股本股东_已上市流通A股"
_FIELD_TOTAL = "股本股东_总股本"
_FIELDS = (_FIELD_HOLDER, _FIELD_FLOAT_A, _FIELD_TOTAL)

# Hard cap on returned periods, matching the Eastmoney tool.
_MAX_PERIODS = 24

# How far a report date may sit from a bar when it is not itself a trading day.
_CLOSE_SEARCH_DAYS = 10


def is_available() -> bool:
    """True when duckdb imports and the data directory holds history_finance/."""
    return _financial_available()


class AshareShareholder:
    """Accessor for the local ashare shareholder-count slice."""

    def fetch(self, code: str, max_periods: int = _MAX_PERIODS) -> Optional[List[dict]]:
        """Return per-report-period shareholder records for an A-share symbol.

        Args:
            code: A-share symbol, e.g. ``"600519.SH"``.
            max_periods: Most-recent period count cap.

        Returns:
            ``list[dict]`` newest-first, or ``None`` when the local directory has
            no shareholder disclosure for ``code`` (so the caller falls back to
            Eastmoney).

        Raises:
            ValueError: If ``code`` is not an A-share symbol.
        """
        if not _is_a_share(code):
            raise ValueError(f"ashare shareholder count is A-share only; got '{code}'")
        parsed = _split_symbol(code)
        if parsed is None:
            raise ValueError(f"could not resolve A-share symbol '{code}'")
        symbol, exchange = parsed

        root = _data_dir()
        if not (root / "history_finance").is_dir():
            return None
        mapping = field_map()
        if mapping is None:
            return None
        missing = [name for name in _FIELDS if name not in mapping]
        if missing:
            logger.warning("ashare shareholder: schema lacks %s", missing)
            return None
        columns = {name: mapping[name] for name in _FIELDS}

        try:
            import duckdb
        except Exception as exc:  # noqa: BLE001
            logger.warning("ashare shareholder: duckdb unavailable: %s", exc)
            return None

        con = duckdb.connect()
        try:
            frame = query_history(con, root, symbol, list(columns.values()))
            if frame is None or frame.empty:
                logger.info(
                    "ashare shareholder: %s has no disclosure in the local directory (will fall back)",
                    code,
                )
                return None
            first_report = frame["report_date"].min()
            last_report = frame["report_date"].max()
            closes = _query_closes(
                con,
                root,
                symbol,
                exchange,
                pd.Timestamp(first_report),
                pd.Timestamp(last_report) + timedelta(days=_CLOSE_SEARCH_DAYS),
            )
        except Exception as exc:  # noqa: BLE001 - any query failure -> fall back
            logger.warning("ashare shareholder query failed for %s: %s", code, exc)
            return None
        finally:
            con.close()

        periods = _build_periods(frame, closes, columns)
        if not periods:
            return None
        logger.info(
            "ashare shareholder: %s -> %d report period(s) from the local directory",
            code,
            min(len(periods), max_periods),
        )
        return periods[:max_periods]


def _build_periods(frame: pd.DataFrame, closes: Optional[pd.Series], columns: dict) -> List[dict]:
    """Convert history rows into aligned, newest-first period dicts.

    A period contributes only when both the report date and the holder count are
    usable; the derived per-account figures use that period's own share counts
    and that period's close, so nothing is borrowed from a later report.
    """
    holder_column = columns[_FIELD_HOLDER]
    float_column = columns[_FIELD_FLOAT_A]
    total_column = columns[_FIELD_TOTAL]

    rows: List[dict] = []
    for record in frame.to_dict("records"):
        report_date = pd.Timestamp(record["report_date"])
        holder_count = _cell(record.get(holder_column))
        if holder_count is None or holder_count <= 0:
            continue

        float_shares = _cell(record.get(float_column))
        total_shares = _cell(record.get(total_column))
        close = _close_on(closes, report_date)
        total_market_cap = round(total_shares * close, 2) if total_shares is not None and close is not None else None

        rows.append(
            {
                "end_date": report_date.strftime("%Y-%m-%d"),
                "holder_count": holder_count,
                "holder_count_change": None,  # filled below, vs prior period
                "holder_count_change_pct": None,
                "avg_hold_shares": (round(float_shares / holder_count, 2) if float_shares is not None else None),
                "avg_hold_amount": (
                    round(total_market_cap / holder_count, 2) if total_market_cap is not None else None
                ),
                "total_market_cap": total_market_cap,
            }
        )

    rows.sort(key=lambda row: row["end_date"], reverse=True)
    for index, row in enumerate(rows):
        previous = rows[index + 1] if index + 1 < len(rows) else None
        if previous is None or previous["holder_count"] in (None, 0):
            continue
        diff = row["holder_count"] - previous["holder_count"]
        row["holder_count_change"] = diff
        row["holder_count_change_pct"] = round(diff / previous["holder_count"] * 100.0, 2)
    return rows


def _query_closes(
    con: Any,
    root: Path,
    code: str,
    exchange: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> Optional[pd.Series]:
    """Raw closes for ``code`` over ``[start, end]``, deduped by (code, date).

    Raw prices are what the period-end market cap must use: the adjusted series
    would move the level by every later corporate action.
    """
    directory = root / "kline_day"
    if not directory.is_dir():
        return None
    sql = (
        "SELECT date, close FROM ("
        "  SELECT date, close, _ingested_at, filename, row_number() OVER ("
        "    PARTITION BY code, date"
        "    ORDER BY _ingested_at DESC, filename DESC) AS _rn"
        f"  FROM read_parquet({_quote(str(directory / '**' / '*.parquet'))},"
        " hive_partitioning = true, union_by_name = true, filename = true)"
        f"  WHERE code = {_quote(code)} AND exchange = {_quote(exchange)}"
        f"  AND date BETWEEN CAST({_quote(start.date().isoformat())} AS DATE)"
        f"  AND CAST({_quote(end.date().isoformat())} AS DATE)) t"
        " WHERE _rn = 1 ORDER BY date"
    )
    frame = con.execute(sql).df()
    if frame.empty:
        return None
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"])
    return frame.set_index("date")["close"]


def _close_on(closes: Optional[pd.Series], report_date: pd.Timestamp) -> Optional[float]:
    """Close on or nearest ``report_date`` (next session first, then previous)."""
    if closes is None or closes.empty:
        return None
    position = int(closes.index.searchsorted(report_date))
    if position < len(closes):
        candidate = closes.index[position]
        if candidate == report_date or (candidate - report_date).days <= _CLOSE_SEARCH_DAYS:
            return float(closes.iloc[position])
    if position > 0:
        candidate = closes.index[position - 1]
        if (report_date - candidate).days <= _CLOSE_SEARCH_DAYS:
            return float(closes.iloc[position - 1])
    return None
