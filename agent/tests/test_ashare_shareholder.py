"""Unit tests for the ashare shareholder-count accessor.

Builds a miniature ashare directory (history_finance rows for the three 股本股东
accounts plus kline_day closes) in ``tmp_path`` so the real read path, the
period alignment and the derived per-account figures are exercised offline.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest.loaders import ashare_financial, ashare_shareholder
from backtest.loaders.ashare_shareholder import AshareShareholder, is_available

_INGESTED = pd.Timestamp("2024-07-01")

_SCHEMA = {
    "columns": [
        {"name": "f0001", "desc": "股本股东_股东人数"},
        {"name": "f0002", "desc": "股本股东_已上市流通A股"},
        {"name": "f0003", "desc": "股本股东_总股本"},
    ]
}


def _write_parquet(path, rows) -> None:
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.register("src", pd.DataFrame(rows))
        con.execute(f"COPY (SELECT * FROM src) TO '{path}' (FORMAT PARQUET)")
    finally:
        con.close()


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "ashare-data"
    monkeypatch.setattr(ashare_financial, "_data_dir", lambda: root)
    monkeypatch.setattr(ashare_shareholder, "_data_dir", lambda: root)
    monkeypatch.setattr(ashare_financial, "_field_map_cache", None)
    schema_path = root / "_meta" / "schemas" / "history_finance.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(json.dumps(_SCHEMA, ensure_ascii=False), encoding="utf-8")
    (root / "history_finance").mkdir(parents=True, exist_ok=True)
    return root


def _period(root, report, holders, *, float_shares=1.0e9, total_shares=2.0e9, part=0):
    row = {
        "code": "600519",
        "report_date": pd.Timestamp(report).date(),
        "f0001": float(holders),
        "f0002": float_shares,
        "f0003": total_shares,
        "_ingested_at": _INGESTED,
    }
    _write_parquet(root / "history_finance" / f"report={report}" / f"part-{part}.parquet", [row])


def _bars(root, rows):
    _write_parquet(root / "kline_day" / "year=2023" / "month=06" / "part-0.parquet", rows)


def _bar(day, close):
    return {
        "code": "600519",
        "exchange": "SH",
        "date": pd.Timestamp(day).date(),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000.0,
        "_ingested_at": _INGESTED,
    }


def test_is_available(data_dir):
    assert is_available() is True


def test_period_figures_and_change(data_dir):
    _period(data_dir, "20230630", 100_000)
    _period(data_dir, "20230331", 120_000)
    _bars(data_dir, [_bar("2023-06-30", 10.0), _bar("2023-03-31", 8.0)])

    periods = AshareShareholder().fetch("600519.SH")
    assert periods is not None
    assert [row["end_date"] for row in periods] == ["2023-06-30", "2023-03-31"]

    newest = periods[0]
    assert newest["holder_count"] == pytest.approx(100_000.0)
    assert newest["total_market_cap"] == pytest.approx(2.0e9 * 10.0)
    assert newest["avg_hold_shares"] == pytest.approx(1.0e9 / 100_000)
    assert newest["avg_hold_amount"] == pytest.approx(2.0e9 * 10.0 / 100_000)
    assert newest["holder_count_change"] == pytest.approx(-20_000.0)
    assert newest["holder_count_change_pct"] == pytest.approx(-16.67, abs=0.01)
    assert periods[-1]["holder_count_change"] is None


def test_report_date_off_market_uses_next_session(data_dir):
    """2023-07-01 is a Saturday: the close comes from Monday's bar."""
    _period(data_dir, "20230630", 100_000)
    _bars(data_dir, [_bar("2023-06-30", 10.0), _bar("2023-07-03", 12.0)])
    # Report on 07-01 (non-trading) must resolve forward to 07-03.
    _period(data_dir, "20230701", 100_000)
    periods = AshareShareholder().fetch("600519.SH")
    assert periods is not None
    by_date = {row["end_date"]: row for row in periods}
    assert by_date["2023-07-01"]["total_market_cap"] == pytest.approx(2.0e9 * 12.0)


def test_market_cap_missing_without_bars(data_dir):
    _period(data_dir, "20230630", 100_000)
    periods = AshareShareholder().fetch("600519.SH")
    assert periods is not None
    assert periods[0]["total_market_cap"] is None
    assert periods[0]["avg_hold_amount"] is None
    assert periods[0]["avg_hold_shares"] == pytest.approx(1.0e9 / 100_000)


def test_period_cap(data_dir):
    for report, holders in (
        ("20211231", 200_000),
        ("20221231", 150_000),
        ("20230630", 100_000),
    ):
        _period(data_dir, report, holders)
    periods = AshareShareholder().fetch("600519.SH", max_periods=2)
    assert periods is not None
    assert [row["end_date"] for row in periods] == ["2023-06-30", "2022-12-31"]


def test_rows_without_holder_count_are_dropped(data_dir):
    _period(data_dir, "20230630", 0)
    assert AshareShareholder().fetch("600519.SH") is None


def test_unknown_symbol_returns_none(data_dir):
    _period(data_dir, "20230630", 100_000)
    assert AshareShareholder().fetch("000001.SZ") is None


def test_rejects_non_a_share_symbol(data_dir):
    with pytest.raises(ValueError):
        AshareShareholder().fetch("AAPL.US")
