"""Unit tests for the ashare financial-statement accessor.

A miniature ashare directory (history_finance partitions + the schema file that
maps ``fNNNN`` columns to Chinese account names) is built in ``tmp_path``, so the
real duckdb read path and the real field mapping are exercised offline.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from backtest.loaders import ashare_financial
from backtest.loaders.ashare_financial import AshareFinancial, field_map, is_available

_INGESTED = pd.Timestamp("2024-07-01")

_SCHEMA = {
    "columns": [
        {"name": "f0073", "desc": "利润表_营业收入"},
        {"name": "f0090", "desc": "利润表_净利润"},
        {"name": "f0001", "desc": "股本股东_股东人数"},
        {"name": "f0583", "desc": "索引 582 未定名"},
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


def _row(code: str, report_date, revenue: float, profit: float, ingested=_INGESTED):
    return {
        "code": code,
        "report_date": report_date,
        "f0073": revenue,
        "f0090": profit,
        "_ingested_at": ingested,
    }


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Build a fake ashare directory and point both modules at it."""
    root = tmp_path / "ashare-data"
    monkeypatch.setattr(ashare_financial, "_data_dir", lambda: root)
    monkeypatch.setattr(ashare_financial, "_field_map_cache", None)
    schema_path = root / "_meta" / "schemas" / "history_finance.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text(json.dumps(_SCHEMA, ensure_ascii=False), encoding="utf-8")
    (root / "history_finance").mkdir(parents=True, exist_ok=True)
    return root


def _write_period(root, report="20231231", rows=None, part=0):
    rows = rows or []
    _write_parquet(root / "history_finance" / f"report={report}" / f"part-{part}.parquet", rows)


def test_is_available_requires_history_finance(data_dir):
    assert is_available() is True


def test_field_map_reads_the_schema_file(data_dir):
    mapping = field_map()
    assert mapping is not None
    assert mapping["利润表_营业收入"] == "f0073"


def test_field_map_missing_file(tmp_path, monkeypatch):
    root = tmp_path / "empty"
    monkeypatch.setattr(ashare_financial, "_data_dir", lambda: root)
    monkeypatch.setattr(ashare_financial, "_field_map_cache", None)
    assert field_map() is None


def test_annual_and_quarter_selection(data_dir):
    _write_period(
        data_dir,
        "20231231",
        [_row("600519", pd.Timestamp("2023-12-31").date(), 1000.0, 100.0)],
    )
    _write_period(
        data_dir,
        "20230930",
        [_row("600519", pd.Timestamp("2023-09-30").date(), 700.0, 70.0)],
    )
    _write_period(
        data_dir,
        "20221231",
        [_row("600519", pd.Timestamp("2022-12-31").date(), 900.0, 90.0, pd.Timestamp("2023-07-01"))],
    )

    annual = AshareFinancial().fetch("600519.SH", statement="income", period="annual")
    assert annual is not None
    assert [row["REPORT_DATE"] for row in annual] == ["2023-12-31", "2022-12-31"]
    assert annual[0]["利润表_营业收入"] == pytest.approx(1000.0)
    assert annual[0]["利润表_净利润"] == pytest.approx(100.0)

    quarter = AshareFinancial().fetch("600519.SH", statement="income", period="quarter")
    assert quarter is not None
    assert len(quarter) == 3


def test_period_cap_and_order(data_dir):
    for day in ("20201231", "20211231", "20221231", "20231231"):
        year = day[:4]
        _write_period(
            data_dir,
            day,
            [_row("600519", pd.Timestamp(f"{year}-12-31").date(), float(year), 1.0)],
        )
    rows = AshareFinancial().fetch("600519.SH", statement="income", period="annual", max_periods=2)
    assert rows is not None
    assert [row["REPORT_DATE"] for row in rows] == ["2023-12-31", "2022-12-31"]


def test_zero_cells_read_as_missing(data_dir):
    _write_period(
        data_dir,
        "20231231",
        [_row("600519", pd.Timestamp("2023-12-31").date(), 1000.0, 0.0)],
    )
    rows = AshareFinancial().fetch("600519.SH", statement="income", period="annual")
    assert rows is not None
    assert rows[0]["利润表_净利润"] is None


def test_unknown_symbol_returns_none(data_dir):
    _write_period(
        data_dir,
        "20231231",
        [_row("600519", pd.Timestamp("2023-12-31").date(), 1000.0, 100.0)],
    )
    assert AshareFinancial().fetch("000001.SZ", statement="income") is None


def test_dedup_keeps_newest_ingested_row(data_dir):
    day = pd.Timestamp("2023-12-31").date()
    _write_period(data_dir, "20231231", [_row("600519", day, 1.0, 1.0)], part=0)
    _write_period(
        data_dir,
        "20231231",
        [_row("600519", day, 2.0, 2.0, pd.Timestamp("2024-08-01"))],
        part=1,
    )
    rows = AshareFinancial().fetch("600519.SH", statement="income", period="annual")
    assert rows is not None
    assert len(rows) == 1
    assert rows[0]["利润表_营业收入"] == pytest.approx(2.0)


def test_rejects_non_a_share_symbol(data_dir):
    with pytest.raises(ValueError):
        AshareFinancial().fetch("AAPL.US")


def test_rejects_unknown_statement(data_dir):
    with pytest.raises(ValueError):
        AshareFinancial().fetch("600519.SH", statement="nope")
