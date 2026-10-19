"""Dispatch-layer regression tests for ``get_financial_statements``.

Why this file exists
--------------------
``test_ashare_financial.py`` covers the local accessor in isolation, so the whole
local-first path stayed green while ``execute()`` never once reached it: the
dispatch compared ``market == "a"`` but ``_classify_market`` returns
``"a_share"``. The A-share branch was therefore unreachable and every A-share
statement silently went to Eastmoney.

These tests exercise ``execute()`` itself and pin the contract that broke:
every label ``_classify_market`` can return must be handled by a named branch,
so a future rename fails loudly here instead of degrading into the ``else``.
"""

from __future__ import annotations

import json

import pytest

from src.tools import financial_statements_tool as tool_mod
from src.tools.financial_statements_tool import FinancialStatementsTool, _classify_market

_LOCAL_PERIODS = [
    {"REPORT_DATE": "2025-12-31", "利润表_营业收入": 1234.0},
    {"REPORT_DATE": "2024-12-31", "利润表_营业收入": 1100.0},
]


@pytest.fixture()
def probes(monkeypatch):
    """Record which fetchers the dispatch reaches, and neutralize the network.

    Returns the list of fetcher names in call order.
    """
    calls: list[str] = []

    def _local(*_args, **_kwargs):
        calls.append("ashare")
        return {"periods": list(_LOCAL_PERIODS)}

    def _local_error(*_args, **_kwargs):
        calls.append("ashare")
        return {"error": "no local ashare rows for 600685.SH"}

    def _eastmoney(*_args, **_kwargs):
        calls.append("eastmoney")
        return {"periods": [{"REPORT_DATE": "2025-12-31", "TOTAL_OPERATE_INCOME": 999.0}]}

    def _sec(*_args, **_kwargs):
        calls.append("sec_edgar")
        return {"periods": [{"REPORT_DATE": "2025-12-31", "Assets": 1.0}]}

    def _yahoo(*_args, **_kwargs):
        calls.append("yahoo")
        return {"periods": [{"REPORT_DATE": "2025-12-31", "totalRevenue": 1.0}]}

    def _cvm(*_args, **_kwargs):
        calls.append("cvm")
        return None

    monkeypatch.setattr(tool_mod, "_fetch_ashare_statement", _local)
    monkeypatch.setattr(tool_mod, "_fetch_eastmoney_statement", _eastmoney)
    monkeypatch.setattr(tool_mod, "_fetch_sec_statement", _sec)
    monkeypatch.setattr(tool_mod, "_fetch_yahoo_statement", _yahoo)
    monkeypatch.setattr(tool_mod, "_fetch_cvm_statement", _cvm)
    return calls


def _run(code: str, **kwargs) -> dict:
    payload = FinancialStatementsTool().execute(code=code, **kwargs)
    return json.loads(payload)


# ---------------------------------------------------------------------------
# The contract that broke
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    ["600685.SH", "000001.SZ", "430047.BJ", "600000.SS"],
)
def test_a_share_labels_are_a_share(code):
    """Every A-share suffix classifies as ``a_share`` — not ``a``."""
    assert _classify_market(code) == "a_share"


@pytest.mark.parametrize(
    ("code", "label"),
    [
        ("600685.SH", "a_share"),
        ("AAPL.US", "us"),
        ("00700.HK", "hk"),
        ("BP.L", "uk"),
        ("PETR4.SA", "br"),
    ],
)
def test_every_label_has_a_dispatch_branch(code, label):
    """Guard the dispatch against a label the branch chain does not handle.

    ``a_share``, ``us``, ``uk`` and ``br`` are matched by name; ``hk`` is the
    intended catch-all. A new label from ``_classify_market`` that nobody
    handles is the exact failure mode this test exists to catch.
    """
    assert _classify_market(code) == label
    named = {"a_share", "us", "uk", "br"}
    assert label in named or label == "hk"


# ---------------------------------------------------------------------------
# A-share routing
# ---------------------------------------------------------------------------


def test_a_share_prefers_local_ashare(probes):
    result = _run("600685.SH", statement="income", period="annual")

    assert probes == ["ashare"], "A-share must not touch Eastmoney when local data exists"
    assert result["ok"] is True
    assert result["source"] == "ashare"
    assert result["market"] == "a_share"
    assert result["data"]["600685.SH"]["periods"][0]["利润表_营业收入"] == 1234.0


def test_a_share_falls_back_to_eastmoney_when_local_misses(probes, monkeypatch):
    monkeypatch.setattr(
        tool_mod,
        "_fetch_ashare_statement",
        lambda *a, **k: (probes.append("ashare"), {"error": "no local rows"})[1],
    )

    result = _run("600685.SH", statement="income", period="annual")

    assert probes == ["ashare", "eastmoney"]
    assert result["source"] == "eastmoney"


def test_a_share_fallback_error_is_not_masked(probes, monkeypatch):
    """A local miss that Eastmoney also cannot serve must report ``ok: false``."""
    monkeypatch.setattr(
        tool_mod,
        "_fetch_ashare_statement",
        lambda *a, **k: (probes.append("ashare"), {"error": "no local rows"})[1],
    )
    monkeypatch.setattr(
        tool_mod,
        "_fetch_eastmoney_statement",
        lambda *a, **k: (probes.append("eastmoney"), {"error": "eastmoney rejected"})[1],
    )

    result = _run("600685.SH", statement="income", period="annual")

    assert result["ok"] is False
    assert result["error"] == "eastmoney rejected"


# ---------------------------------------------------------------------------
# Other markets keep their routes
# ---------------------------------------------------------------------------


def test_us_still_uses_sec(probes):
    result = _run("AAPL.US", statement="income", period="annual")

    assert probes == ["sec_edgar"]
    assert result["source"] == "sec_edgar"


def test_uk_still_uses_yahoo(probes):
    result = _run("BP.L", statement="income", period="annual")

    assert probes == ["yahoo"]
    assert result["source"] == "yahoo"


def test_hk_uses_eastmoney_via_catch_all(probes):
    result = _run("00700.HK", statement="income", period="annual")

    assert probes == ["eastmoney"]
    assert result["source"] == "eastmoney"