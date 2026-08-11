"""Tests for the Hikyuu shareholder-count accessor (local data dir, faked here).

The real ``hikyuu`` package is optional and lazy-imported; tests inject a fake
module via ``sys.modules`` to exercise symbol resolution, per-report-period
alignment of avg-hold/market-cap, QoQ change computation, the period cap, and
graceful unavailability.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

import backtest.loaders.hikyuu_shareholder as hk_share
from backtest.loaders.hikyuu_shareholder import HikyuuShareholder, is_available

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fake hikyuu module                                                           #
# --------------------------------------------------------------------------- #


class _FakeDatetime:
    def __init__(self, value: Any) -> None:
        self.value = str(value)

    def datetime(self):
        from datetime import datetime as _py

        return _py.strptime(self.value, "%Y-%m-%d")

    def next_day(self) -> "_FakeDatetime":
        from datetime import datetime as _py
        from datetime import timedelta

        d = _py.strptime(self.value, "%Y-%m-%d") + timedelta(days=1)
        return _FakeDatetime(d.strftime("%Y-%m-%d"))


class _FakeKData:
    def __init__(self, closes: list[float]) -> None:
        self._closes = closes

    def __len__(self) -> int:
        return len(self._closes)

    def __getitem__(self, i: int) -> Any:
        return SimpleNamespace(close=self._closes[i])


class _FakeStock:
    def __init__(self, history: list[tuple[Any, Any, list[float]]], closes: list[float]) -> None:
        self._history = history
        self._closes = closes

    def get_history_finance(self) -> list[tuple[Any, Any, list[float]]]:
        return self._history

    def get_kdata(self, *args: Any, **kwargs: Any) -> _FakeKData:
        return _FakeKData(self._closes)


class _FakeStockManager:
    def __init__(self, stocks: dict[str, _FakeStock]) -> None:
        self._stocks = stocks
        self._fields = {
            "股本股东_股东人数": 0,
            "股本股东_已上市流通A股": 1,
            "股本股东_总股本": 2,
        }

    def get_stock(self, market_code: str) -> _FakeStock | None:
        return self._stocks.get(market_code)

    def get_history_finance_field_index(self, name: str) -> int:
        return self._fields[name]


class _FakeQuery:
    DAY = "DAY"
    FORWARD = "FORWARD"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


class _FakeHikyuuModule:
    """Mimics the ``hikyuu`` package surface the accessor uses."""

    def __init__(self) -> None:
        self.Datetime = _FakeDatetime
        self.Query = _FakeQuery
        self.StockManager = SimpleNamespace(instance=lambda: self._sm)
        self._sm = _FakeStockManager({})
        self.load_calls = 0

    def load_hikyuu(self, *args: Any, **kwargs: Any) -> None:
        self.load_calls += 1

    def set_stock(self, market_code: str, history: list[tuple[str, str, list[float]]]) -> _FakeStock:
        rows = [
            (_FakeDatetime(d), _FakeDatetime(a), fields)
            for (d, a, fields) in history
        ]
        closes = [1300.0] * len(history)
        stock = _FakeStock(rows, closes)
        self._sm._stocks[market_code] = stock
        return stock


@pytest.fixture
def fake_mod(monkeypatch: pytest.MonkeyPatch) -> _FakeHikyuuModule:
    fake = _FakeHikyuuModule()
    monkeypatch.setitem(sys.modules, "hikyuu", fake)
    # Ensure a fresh accessor per test (no cached StockManager bleed).
    monkeypatch.setattr(hk_share, "HikyuuShareholder", HikyuuShareholder)
    return fake


# history: (report_date, announce_date, [holder, liutong, zongguben]) newest-first
_SAMPLE_HISTORY = [
    ("2024-03-31", "2024-04-30", [188000.0, 1250081562.5, 1250081562.5]),
    ("2023-12-31", "2024-01-31", [190000.0, 1240000000.0, 1240000000.0]),
    ("2023-09-30", "2023-10-31", [200000.0, 1230000000.0, 1230000000.0]),
]


# --------------------------------------------------------------------------- #
# Availability + lazy init                                                     #
# --------------------------------------------------------------------------- #


class TestAvailability:
    def test_available_when_package_imports(self, fake_mod: _FakeHikyuuModule) -> None:
        assert is_available() is True

    def test_missing_package_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "hikyuu", None)
        assert is_available() is False

    def test_load_hikyuu_called_once_lazily(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", _SAMPLE_HISTORY)
        accessor = HikyuuShareholder()
        assert fake_mod.load_calls == 0  # registration never boots Hikyuu
        accessor.fetch("600519.SH", max_periods=3)
        assert fake_mod.load_calls == 1
        accessor.fetch("600519.SH", max_periods=3)  # cached, no re-init
        assert fake_mod.load_calls == 1


# --------------------------------------------------------------------------- #
# Symbol resolution + validation                                               #
# --------------------------------------------------------------------------- #


class TestSymbolResolution:
    def test_unknown_stock_returns_none(self, fake_mod: _FakeHikyuuModule) -> None:
        accessor = HikyuuShareholder()
        assert accessor.fetch("600519.SH") is None

    def test_non_a_share_raises(self, fake_mod: _FakeHikyuuModule) -> None:
        with pytest.raises(ValueError):
            HikyuuShareholder().fetch("AAPL.US")

    def test_bj_suffix_raises(self, fake_mod: _FakeHikyuuModule) -> None:
        # hikyuu shareholder store is SH/SZ only; .BJ is unsupported.
        with pytest.raises(ValueError):
            HikyuuShareholder().fetch("830799.BJ")


# --------------------------------------------------------------------------- #
# Per-period alignment + QoQ                                                   #
# --------------------------------------------------------------------------- #


class TestPeriodAlignment:
    def test_periods_aligned_and_newest_first(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", _SAMPLE_HISTORY)
        periods = HikyuuShareholder().fetch("600519.SH", max_periods=3)

        assert periods is not None
        assert [p["end_date"] for p in periods] == ["2024-03-31", "2023-12-31", "2023-09-30"]

        first = periods[0]
        # avg_hold_shares uses THIS period's 流通A股 ÷ THIS period's 股东户数
        assert first["avg_hold_shares"] == pytest.approx(1250081562.5 / 188000.0)
        # total_market_cap uses THIS period's 总股本 × END_DATE close
        assert first["total_market_cap"] == pytest.approx(1250081562.5 * 1300.0)

    def test_qoq_change_computed_from_prior_period(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", _SAMPLE_HISTORY)
        periods = HikyuuShareholder().fetch("600519.SH", max_periods=3)

        assert periods[0]["holder_count_change"] == pytest.approx(188000.0 - 190000.0)
        assert periods[0]["holder_count_change_pct"] == pytest.approx(-1.05)  # rounded to 2dp
        # latest period has a change; the oldest has no prior to diff against.
        assert periods[-1]["holder_count_change"] is None

    def test_max_periods_caps(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", _SAMPLE_HISTORY)
        periods = HikyuuShareholder().fetch("600519.SH", max_periods=2)
        assert len(periods) == 2


# --------------------------------------------------------------------------- #
# Registry / tool wiring                                                        #
# --------------------------------------------------------------------------- #


class TestWiring:
    def test_fetch_hikyuu_returns_none_without_package(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "hikyuu", None)
        from src.tools.shareholder_count_tool import _fetch_hikyuu

        assert _fetch_hikyuu("600519.SH", 24) is None
