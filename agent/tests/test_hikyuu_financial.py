"""Tests for the Hikyuu financial-statement accessor (local data dir, faked).

The real ``hikyuu`` package is optional and lazy-imported; tests inject a fake
module via ``sys.modules`` to exercise statement->prefix mapping, annual/quarter
period filtering, per-period REPORT_DATE alignment, and graceful
unavailability.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

import backtest.loaders.hikyuu_financial as hk_fin
from backtest.loaders.hikyuu_financial import HikyuuFinancial, is_available

pytestmark = pytest.mark.unit


class _FakeDatetime:
    def __init__(self, value: str) -> None:
        self.value = value

    def datetime(self):
        from datetime import datetime as _py

        return _py.strptime(self.value, "%Y-%m-%d")


class _FakeStock:
    def __init__(self, history: list[tuple[Any, Any, list[float]]], field_names: list[str]) -> None:
        self._history = history
        self._field_names = field_names

    def get_history_finance(self) -> list[tuple[Any, Any, list[float]]]:
        return self._history


class _FakeStockManager:
    def __init__(self, stocks: dict[str, _FakeStock], field_names: list[str]) -> None:
        self._stocks = stocks
        self._field_names = field_names

    def get_stock(self, market_code: str) -> _FakeStock | None:
        return self._stocks.get(market_code)

    def get_history_finance_all_fields(self):
        return list(enumerate(self._field_names))


class _FakeHikyuuModule:
    def __init__(self) -> None:
        self._field_names = [
            "基本每股收益",
            "净资产收益率",
            "利润表_营业收入",
            "利润表_净利润",
            "资产负债表_资产总计",
            "现金流量表_经营活动产生的现金流量净额",
        ]
        # Stable StockManager instance (instance() must be idempotent, as in
        # real hikyuu) so set_stock() and fetch() see the same store.
        self._sm = _FakeStockManager({}, self._field_names)
        self.StockManager = SimpleNamespace(instance=lambda: self._sm)
        self.load_calls = 0

    def load_hikyuu(self, *args: Any, **kwargs: Any) -> None:
        self.load_calls += 1

    def set_stock(self, market_code: str, history: list[tuple[str, str, list[float]]]) -> None:
        rows = [
            (_FakeDatetime(d), _FakeDatetime(a), fields)
            for (d, a, fields) in history
        ]
        self._sm._stocks[market_code] = _FakeStock(rows, self._field_names)


@pytest.fixture
def fake_mod(monkeypatch: pytest.MonkeyPatch) -> _FakeHikyuuModule:
    fake = _FakeHikyuuModule()
    monkeypatch.setitem(sys.modules, "hikyuu", fake)
    monkeypatch.setattr(hk_fin, "_field_index_map", None)  # reset cached index map
    return fake


# (report, announce, [基本每股收益, 净资产收益率, 营业收入, 净利润, 资产总计, 经营现金流])
_FULL_YEAR = ("2024-12-31", "2025-04-30", [10.0, 0.25, 1000.0, 300.0, 2000.0, 400.0])
_QUARTER = ("2024-03-31", "2024-04-30", [2.5, 0.06, 250.0, 75.0, 1900.0, 90.0])


class TestAvailability:
    def test_available_when_package_imports(self, fake_mod: _FakeHikyuuModule) -> None:
        assert is_available() is True

    def test_missing_package_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "hikyuu", None)
        assert is_available() is False

    def test_load_hikyuu_called_once_lazily(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", [_FULL_YEAR])
        accessor = HikyuuFinancial()
        assert fake_mod.load_calls == 0
        accessor.fetch("600519.SH", statement="income", period="annual")
        assert fake_mod.load_calls == 1
        accessor.fetch("600519.SH", statement="income", period="annual")
        assert fake_mod.load_calls == 1


class TestStatementMapping:
    def test_income_collects_income_fields(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", [_FULL_YEAR])
        rows = HikyuuFinancial().fetch("600519.SH", statement="income", period="annual")
        assert rows[0]["REPORT_DATE"] == "2024-12-31"
        assert rows[0]["利润表_营业收入"] == 1000.0
        assert rows[0]["利润表_净利润"] == 300.0
        # balance/cashflow fields must NOT leak into income rows
        assert "资产负债表_资产总计" not in rows[0]
        assert "现金流量表_经营活动产生的现金流量净额" not in rows[0]

    def test_balance_collects_balance_fields(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", [_FULL_YEAR])
        rows = HikyuuFinancial().fetch("600519.SH", statement="balance", period="annual")
        assert rows[0]["资产负债表_资产总计"] == 2000.0

    def test_cashflow_collects_cashflow_fields(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", [_FULL_YEAR])
        rows = HikyuuFinancial().fetch("600519.SH", statement="cashflow", period="annual")
        assert rows[0]["现金流量表_经营活动产生的现金流量净额"] == 400.0

    def test_indicators_collects_per_share_and_ratio_groups(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", [_FULL_YEAR])
        rows = HikyuuFinancial().fetch("600519.SH", statement="indicators", period="annual")
        assert rows[0]["基本每股收益"] == 10.0
        assert rows[0]["净资产收益率"] == 0.25
        # report prefixes excluded from indicators
        assert "利润表_营业收入" not in rows[0]


class TestPeriodFiltering:
    def test_annual_keeps_only_fiscal_year_end(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", [_QUARTER, _FULL_YEAR])
        rows = HikyuuFinancial().fetch("600519.SH", statement="income", period="annual")
        assert [r["REPORT_DATE"] for r in rows] == ["2024-12-31"]

    def test_quarter_returns_full_series(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600519", [_QUARTER, _FULL_YEAR])
        rows = HikyuuFinancial().fetch("600519.SH", statement="income", period="quarter")
        assert [r["REPORT_DATE"] for r in rows] == ["2024-12-31", "2024-03-31"]


class TestValidation:
    def test_unknown_stock_returns_none(self, fake_mod: _FakeHikyuuModule) -> None:
        assert HikyuuFinancial().fetch("600519.SH", statement="income") is None

    def test_non_a_share_raises(self, fake_mod: _FakeHikyuuModule) -> None:
        with pytest.raises(ValueError):
            HikyuuFinancial().fetch("AAPL.US", statement="income")

    def test_invalid_statement_raises(self, fake_mod: _FakeHikyuuModule) -> None:
        with pytest.raises(ValueError):
            HikyuuFinancial().fetch("600519.SH", statement="nope")
