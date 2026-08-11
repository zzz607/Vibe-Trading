"""Hikyuu backtest data loader tests (local data dir, faked here).

The real ``hikyuu`` package is an optional dependency that may be absent or
broken (e.g. a missing ``sqlalchemy``). The loader lazy-imports it, so tests
inject a fake ``hikyuu`` module via ``sys.modules`` and exercise symbol
resolution, interval mapping, the frame contract, lazy init via
``load_hikyuu()``, and graceful degradation (absent package → unavailable →
registry fallback engages).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

import backtest.loaders.hikyuu_loader as hikyuu_loader
from backtest.loaders.hikyuu_loader import DataLoader

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fake hikyuu module                                                           #
# --------------------------------------------------------------------------- #


class _FakeKRecord(SimpleNamespace):
    """Mimics a hikyuu KRecord: datetime + OHLCV."""


class _FakeKData:
    """Mimics hikyuu KData: a sized, iterable container of KRecords."""

    def __init__(self, records: list[Any]) -> None:
        self._records = records

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self):
        return iter(self._records)


class _FakeStock:
    def __init__(self, market_code: str, records: list[Any]) -> None:
        self.market_code = market_code
        self._records = records
        self.kdata_calls: list[tuple[Any, ...]] = []

    def get_kdata(self, *args: Any, **kwargs: Any) -> _FakeKData:
        self.kdata_calls.append((args, kwargs))
        return _FakeKData(self._records)


class _FakeStockManager:
    """Mimics hikyuu StockManager.instance() -> get_stock()."""

    def __init__(self, stocks: dict[str, _FakeStock]) -> None:
        self._stocks = stocks

    def get_stock(self, market_code: str) -> _FakeStock | None:
        return self._stocks.get(market_code)


class _FakeQuery:
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    NO_RECOVER = "NO_RECOVER"
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"

    def __init__(self, start: Any = None, end: Any = None, **kwargs: Any) -> None:
        self.start = start
        self.end = end
        self.kwargs = kwargs


class _FakeDatetime:
    """Mimics hikyuu Datetime; constructed from an ISO date string."""

    def __init__(self, value: Any) -> None:
        self.value = value


class _FakeHikyuuModule:
    """Mimics the ``hikyuu`` package surface the loader uses."""

    def __init__(self) -> None:
        self.Query = _FakeQuery
        self.Datetime = _FakeDatetime
        self.StockManager = SimpleNamespace(instance=lambda: self._sm)
        self._sm = _FakeStockManager({})
        self.load_hikyuu_calls: int = 0

    def load_hikyuu(self, *args: Any, **kwargs: Any) -> None:
        self.load_hikyuu_calls += 1

    def set_stock(self, market_code: str, records: list[Any]) -> _FakeStock:
        stock = _FakeStock(market_code, records)
        self._sm._stocks[market_code] = stock
        return stock


class _FakeHkuDatetime:
    """Mimics a hikyuu Datetime: holds an ISO string, exposes .datetime()."""

    def __init__(self, value: str) -> None:
        self.value = value

    def datetime(self):
        from datetime import datetime as _py_datetime

        return _py_datetime.strptime(self.value, "%Y-%m-%d")


def _records(start_year: int = 2024, n: int = 3) -> list[Any]:
    return [
        _FakeKRecord(
            datetime=_FakeHkuDatetime(f"2024-01-0{i + 1}"),
            open=10.0 + i,
            high=12.0 + i,
            low=9.0 + i,
            close=11.0 + i,
            volume=1000 + i,
        )
        for i in range(n)
    ]


@pytest.fixture
def fake_mod(monkeypatch: pytest.MonkeyPatch) -> _FakeHikyuuModule:
    fake = _FakeHikyuuModule()
    monkeypatch.setitem(sys.modules, "hikyuu", fake)
    monkeypatch.setattr(hikyuu_loader, "DataLoader", DataLoader)
    return fake


# --------------------------------------------------------------------------- #
# Symbol resolution                                                            #
# --------------------------------------------------------------------------- #


class TestSymbolResolution:
    @pytest.mark.parametrize(
        ("code", "market_code"),
        [
            ("600000.SH", "sh600000"),
            ("000001.SZ", "sz000001"),
            ("600000", "sh600000"),
            ("000001", "sz000001"),
        ],
    )
    def test_a_share_symbols_map_to_hikyuu_market_code(
        self, fake_mod: _FakeHikyuuModule, code: str, market_code: str
    ) -> None:
        stock = fake_mod.set_stock(market_code, _records())
        loader = DataLoader()
        frames = loader.fetch([code], "2024-01-01", "2024-12-31")
        assert stock.market_code == market_code
        assert code in frames  # keyed by the ORIGINAL input code

    def test_non_a_share_symbols_skipped(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600000", _records())
        loader = DataLoader()
        frames = loader.fetch(["AAPL.US", "600000.SH"], "2024-01-01", "2024-12-31")
        assert "AAPL.US" not in frames
        assert "600000.SH" in frames  # one bad symbol never poisons the batch


# --------------------------------------------------------------------------- #
# Intervals + frame contract                                                   #
# --------------------------------------------------------------------------- #


class TestIntervalsAndFrames:
    def test_interval_mapping(self, fake_mod: _FakeHikyuuModule) -> None:
        stock = fake_mod.set_stock("sh600000", _records())
        loader = DataLoader()
        loader.fetch(["600000.SH"], "2024-01-01", "2024-12-31", interval="1W")
        query = stock.kdata_calls[-1][0][0]  # Query passed to getKData
        assert query.kwargs["ktype"] == "WEEK"
        assert query.kwargs["recover_type"] == "FORWARD"  # 前复权
        assert query.start.value == "2024-01-01"
        assert query.end.value == "2024-12-31"

    @pytest.mark.parametrize("interval", ["1D", "1W", "1M"])
    def test_supported_intervals(self, fake_mod: _FakeHikyuuModule, interval: str) -> None:
        fake_mod.set_stock("sh600000", _records())
        loader = DataLoader()
        frames = loader.fetch(["600000.SH"], "2024-01-01", "2024-12-31", interval=interval)
        assert "600000.SH" in frames

    @pytest.mark.parametrize("interval", ["1m", "5m", "15m", "30m", "1H", "4H"])
    def test_unsupported_intraday_intervals_rejected(
        self, fake_mod: _FakeHikyuuModule, interval: str
    ) -> None:
        loader = DataLoader()
        frames = loader.fetch(["600000.SH"], "2024-01-01", "2024-12-31", interval=interval)
        assert frames == {}

    def test_frame_contract(self, fake_mod: _FakeHikyuuModule) -> None:
        fake_mod.set_stock("sh600000", _records(n=3))
        loader = DataLoader()
        frames = loader.fetch(["600000.SH"], "2024-01-01", "2024-12-31")
        frame = frames["600000.SH"]
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index.name == "trade_date"
        assert frame["close"].tolist() == [11.0, 12.0, 13.0]


# --------------------------------------------------------------------------- #
# Availability + lazy init                                                     #
# --------------------------------------------------------------------------- #


class TestAvailability:
    def test_available_when_package_imports(self, fake_mod: _FakeHikyuuModule) -> None:
        assert DataLoader().is_available() is True

    def test_missing_package_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "hikyuu", None)
        assert DataLoader().is_available() is False

    def test_load_hikyuu_called_once_lazily(self, fake_mod: _FakeHikyuuModule) -> None:
        loader = DataLoader()
        assert fake_mod.load_hikyuu_calls == 0  # registration never boots Hikyuu
        loader.fetch(["600000.SH"], "2024-01-01", "2024-12-31")
        assert fake_mod.load_hikyuu_calls == 1
        # Second fetch reuses the cached StockManager — no re-init.
        loader.fetch(["600000.SH"], "2024-01-01", "2024-12-31")
        assert fake_mod.load_hikyuu_calls == 1

    def test_init_failure_returns_empty_and_falls_back(self, fake_mod: _FakeHikyuuModule) -> None:
        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("no local hikyuu data dir")

        fake_mod.load_hikyuu = _boom
        loader = DataLoader()
        frames = loader.fetch(["600000.SH"], "2024-01-01", "2024-12-31")
        assert frames == {}


# --------------------------------------------------------------------------- #
# Registry + routing                                                           #
# --------------------------------------------------------------------------- #


class TestRegistryWiring:
    def test_hikyuu_in_valid_sources(self) -> None:
        from backtest.loaders.registry import VALID_SOURCES

        assert "hikyuu" in VALID_SOURCES

    def test_hikyuu_registered(self) -> None:
        from backtest.loaders.registry import LOADER_REGISTRY, _ensure_registered

        _ensure_registered()
        assert "hikyuu" in LOADER_REGISTRY

    def test_hikyuu_heads_a_share_chain(self) -> None:
        from backtest.loaders.registry import FALLBACK_CHAINS

        assert FALLBACK_CHAINS["a_share"][0] == "hikyuu"
        assert "baostock" in FALLBACK_CHAINS["a_share"]  # degradation path intact
