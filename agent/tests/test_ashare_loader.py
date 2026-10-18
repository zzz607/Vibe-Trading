"""Unit tests for the local ashare loader (no real data directory, no network).

Every test builds a miniature ashare directory in ``tmp_path`` with duckdb, so
the suite exercises the real read path (hive partitions, dedup, forward
adjustment) without pyarrow and without touching the collector's store.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from backtest.loaders import ashare_loader
from backtest.loaders.ashare_loader import DataLoader, _split_symbol
from tests.loader_contract import assert_loader_contract

_INGESTED = pd.Timestamp("2024-07-01 00:00:00")


def _write_parquet(path, rows) -> None:
    """Write rows to ``path`` as Parquet through duckdb (no pyarrow needed)."""
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.register("src", pd.DataFrame(rows))
        con.execute(f"COPY (SELECT * FROM src) TO '{path}' (FORMAT PARQUET)")
    finally:
        con.close()


def _bar(
    date: dt.date,
    close: float,
    *,
    code: str = "600519",
    exchange: str = "SH",
    volume: float = 1000.0,
    ingested: pd.Timestamp = _INGESTED,
):
    """One raw daily bar row shaped like ashare's kline_day."""
    return {
        "code": code,
        "exchange": exchange,
        "date": date,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
        "_ingested_at": ingested,
    }


def _event(
    date: dt.date,
    *,
    code: str = "600519",
    exchange: str = "SH",
    fenhong: float = 0.0,
    peigujia: float = 0.0,
    songzhuangu: float = 0.0,
    peigu: float = 0.0,
    ingested: pd.Timestamp = _INGESTED,
):
    """One corporate-action row shaped like ashare's xdxr."""
    return {
        "code": code,
        "exchange": exchange,
        "date": date,
        "fenhong": fenhong,
        "peigujia": peigujia,
        "songzhuangu": songzhuangu,
        "peigu": peigu,
        "_ingested_at": ingested,
    }


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point the loader at an empty tmp data directory and disable caching."""
    root = tmp_path / "ashare-data"
    monkeypatch.setattr(ashare_loader, "_data_dir", lambda: root)
    monkeypatch.setattr("backtest.loaders.base.loader_cache_enabled", lambda: False)
    return root


def _write_bars(root, rows, dataset="kline_day", year=2024, month=6, part=0):
    _write_parquet(root / dataset / f"year={year}" / f"month={month:02d}" / f"part-{part}.parquet", rows)


def _write_events(root, rows, year=2024):
    _write_parquet(root / "xdxr" / f"year={year}" / "part-0.parquet", rows)


# ---------------------------------------------------------------------------
# Symbol handling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("600519.SH", ("600519", "SH")),
        ("000001.sz", ("000001", "SZ")),
        ("830799.BJ", ("830799", "BJ")),
        ("600519", ("600519", "SH")),
        ("000001", ("000001", "SZ")),
        ("430139", ("430139", "BJ")),
    ],
)
def test_split_symbol_maps_a_share_tickers(code, expected):
    assert _split_symbol(code) == expected


@pytest.mark.parametrize("code", ["AAPL.US", "00700.HK", "BTC-USDT", "", "SH600519"])
def test_split_symbol_rejects_non_a_share(code):
    assert _split_symbol(code) is None


# ---------------------------------------------------------------------------
# Availability + interval gate
# ---------------------------------------------------------------------------


def test_is_available_requires_kline_day(data_dir):
    loader = DataLoader()
    assert loader.is_available() is False
    (data_dir / "kline_day").mkdir(parents=True)
    assert loader.is_available() is True


def test_non_daily_interval_is_rejected(data_dir):
    _write_bars(data_dir, [_bar(dt.date(2024, 6, 11), 100.0)])
    loader = DataLoader()
    for interval in ("1m", "5m", "1h"):
        assert loader.fetch(["600519.SH"], "2024-06-01", "2024-06-30", interval=interval) == {}


def test_missing_symbol_is_absent_from_result(data_dir):
    _write_bars(data_dir, [_bar(dt.date(2024, 6, 11), 100.0)])
    out = DataLoader().fetch(["510050.SH"], "2024-06-01", "2024-06-30")
    assert out == {}


# ---------------------------------------------------------------------------
# Read path: partitions, dedup, dataset priority, window
# ---------------------------------------------------------------------------


def test_fetch_returns_contract_frame(data_dir):
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 6, 11), 100.0, volume=1234.0),
            _bar(dt.date(2024, 6, 12), 101.0),
        ],
    )
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    assert_loader_contract(frame, context="ashare daily")
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame.index.name == "trade_date"
    assert len(frame) == 2
    assert frame.index[0] == pd.Timestamp("2024-06-11")
    assert frame["close"].iloc[-1] == pytest.approx(101.0)


def test_dedup_keeps_newest_ingested_row(data_dir):
    stale = pd.Timestamp("2024-07-01")
    newer = pd.Timestamp("2024-08-01")
    _write_bars(data_dir, [_bar(dt.date(2024, 6, 11), 100.0, ingested=stale)], part=0)
    _write_bars(data_dir, [_bar(dt.date(2024, 6, 11), 111.0, ingested=newer)], part=1)
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    assert len(frame) == 1
    assert frame["close"].iloc[0] == pytest.approx(111.0)


def test_index_day_serves_when_stock_bar_absent(data_dir):
    _write_bars(
        data_dir,
        [
            {
                **_bar(dt.date(2024, 6, 11), 3600.0, code="000300", exchange="SH"),
                "up_count": 2000,
                "down_count": 2500,
            }
        ],
        dataset="index_day",
    )
    frame = DataLoader().fetch(["000300.SH"], "2024-06-01", "2024-06-30")["000300.SH"]
    assert frame["close"].iloc[0] == pytest.approx(3600.0)


def test_stock_dataset_wins_when_both_carry_the_date(data_dir):
    _write_bars(data_dir, [_bar(dt.date(2024, 6, 11), 100.0)])
    _write_bars(
        data_dir,
        [_bar(dt.date(2024, 6, 11), 999.0)],
        dataset="index_day",
    )
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    assert frame["close"].iloc[0] == pytest.approx(100.0)


def test_window_filters_bars(data_dir):
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 5, 31), 90.0),
            _bar(dt.date(2024, 6, 11), 100.0),
            _bar(dt.date(2024, 7, 1), 110.0),
        ],
    )
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    assert list(frame.index) == [pd.Timestamp("2024-06-11")]


def test_single_symbol_failure_does_not_abort_batch(data_dir, monkeypatch):
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 6, 11), 100.0),
            _bar(dt.date(2024, 6, 11), 20.0, code="000001", exchange="SZ"),
        ],
    )
    original = ashare_loader._query_bars

    def flaky(con, root, code, exchange, start_date, end_date):
        if code == "000001":
            raise RuntimeError("boom")
        return original(con, root, code, exchange, start_date, end_date)

    monkeypatch.setattr(ashare_loader, "_query_bars", flaky)
    out = DataLoader().fetch(["600519.SH", "000001.SZ"], "2024-06-01", "2024-06-30")
    assert list(out) == ["600519.SH"]


# ---------------------------------------------------------------------------
# Forward adjustment (10派5 / 10送10 / 10配3 / combined)
# ---------------------------------------------------------------------------


def test_cash_dividend_scales_prior_bars(data_dir):
    """10派5 on 06-12: prev close 100 -> theo 99.5, factor 0.995 on 06-11."""
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 6, 11), 100.0, volume=1000.0),
            _bar(dt.date(2024, 6, 12), 95.0),
        ],
    )
    _write_events(data_dir, [_event(dt.date(2024, 6, 12), fenhong=5.0)])
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    assert frame["close"].iloc[0] == pytest.approx(99.5)
    assert frame["close"].iloc[1] == pytest.approx(95.0)  # ex-date bar is already ex
    assert frame["volume"].iloc[0] == pytest.approx(1000.0 / 0.995)
    assert frame.attrs["adjustment"] == "split_dividend"


def test_bonus_shares_halve_prior_bars(data_dir):
    """10送10 on 06-12: factor 100 / (100 + 100) = 0.5."""
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 6, 11), 100.0),
            _bar(dt.date(2024, 6, 12), 50.0),
        ],
    )
    _write_events(data_dir, [_event(dt.date(2024, 6, 12), songzhuangu=10.0)])
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    assert frame["close"].iloc[0] == pytest.approx(50.0)


def test_rights_issue_uses_subscription_price(data_dir):
    """10配3 at 5 yuan on 06-12: theo = (100 + 5*0.3) / 1.3."""
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 6, 11), 100.0),
            _bar(dt.date(2024, 6, 12), 75.0),
        ],
    )
    _write_events(data_dir, [_event(dt.date(2024, 6, 12), peigu=3.0, peigujia=5.0)])
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    expected = 100.0 * ((100.0 + 5.0 * 0.3) / 1.3) / 100.0
    assert frame["close"].iloc[0] == pytest.approx(expected)


def test_combined_event_folds_all_terms(data_dir):
    """10派5 + 10送5 + 10配2 at 8 yuan on 06-12."""
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 6, 11), 100.0),
            _bar(dt.date(2024, 6, 12), 60.0),
        ],
    )
    _write_events(
        data_dir,
        [
            _event(
                dt.date(2024, 6, 12),
                fenhong=5.0,
                songzhuangu=5.0,
                peigu=2.0,
                peigujia=8.0,
            )
        ],
    )
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    theo = (100.0 - 0.5 + 8.0 * 0.2) / (1.0 + 0.5 + 0.2)
    assert frame["close"].iloc[0] == pytest.approx(theo)


def test_no_events_leaves_frame_raw(data_dir):
    _write_bars(data_dir, [_bar(dt.date(2024, 6, 11), 100.0)])
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    assert frame["close"].iloc[0] == pytest.approx(100.0)
    assert frame.attrs.get("adjustment") is None


def test_event_on_first_bar_is_skipped(data_dir):
    """An event with no earlier bar in the window cannot scale anything."""
    _write_bars(data_dir, [_bar(dt.date(2024, 6, 12), 95.0)])
    _write_events(data_dir, [_event(dt.date(2024, 6, 12), fenhong=5.0)])
    frame = DataLoader().fetch(["600519.SH"], "2024-06-12", "2024-06-30")["600519.SH"]
    assert frame["close"].iloc[0] == pytest.approx(95.0)


def test_non_positive_theoretical_price_is_skipped(data_dir):
    """A dividend larger than the price yields no factor, never a negative one."""
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 6, 11), 1.0),
            _bar(dt.date(2024, 6, 12), 1.0),
        ],
    )
    _write_events(data_dir, [_event(dt.date(2024, 6, 12), fenhong=20.0)])
    frame = DataLoader().fetch(["600519.SH"], "2024-06-01", "2024-06-30")["600519.SH"]
    assert (frame["close"] > 0).all()
    assert frame["close"].iloc[0] == pytest.approx(1.0)


def test_multiple_events_compound(data_dir):
    """Two dividends compound: 03-01 absorbs both, 06-11 only the later one."""
    _write_bars(
        data_dir,
        [
            _bar(dt.date(2024, 3, 1), 100.0),
            _bar(dt.date(2024, 6, 11), 100.0),
            _bar(dt.date(2024, 6, 12), 95.0),
        ],
    )
    _write_events(
        data_dir,
        [
            _event(dt.date(2024, 4, 1), fenhong=10.0),  # 10派10 -> factor 0.99
            _event(dt.date(2024, 6, 12), fenhong=5.0),  # 10派5  -> factor 0.995
        ],
    )
    frame = DataLoader().fetch(["600519.SH"], "2024-01-01", "2024-06-30")["600519.SH"]
    assert frame["close"].iloc[0] == pytest.approx(100.0 * 0.99 * 0.995)
    assert frame["close"].iloc[1] == pytest.approx(100.0 * 0.995)


def test_index_symbols_are_not_adjusted(data_dir):
    """Indices carry no xdxr rows, so the frame stays raw."""
    _write_bars(
        data_dir,
        [{**_bar(dt.date(2024, 6, 11), 3600.0, code="000300")}],
        dataset="index_day",
    )
    _write_events(data_dir, [_event(dt.date(2024, 6, 11), code="000300", fenhong=5.0)])
    frame = DataLoader().fetch(["000300.SH"], "2024-06-01", "2024-06-30")["000300.SH"]
    assert frame["close"].iloc[0] == pytest.approx(3600.0)
