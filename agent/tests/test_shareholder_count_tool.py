"""Tests for get_shareholder_count: success + error envelopes, HTTP mocked.

The Eastmoney datacenter call is mocked at ``get_json`` (imported into the tool
module) and the Hikyuu accessor is mocked at ``_fetch_hikyuu``, so no test
reaches a live endpoint and the routing (hikyuu preferred, falls back to
Eastmoney) is exercised deterministically regardless of the local environment.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.tools import shareholder_count_tool as sct
from src.tools.shareholder_count_tool import ShareholderCountTool

# A minimal hikyuu-style period record returned by the faked accessor.
_HIKYUU_PERIODS = [
    {
        "end_date": "2024-03-31",
        "holder_count": 188000.0,
        "holder_count_change": -2000.0,
        "holder_count_change_pct": -1.05,
        "avg_hold_shares": 6680.0,
        "avg_hold_amount": 12345678.0,
        "total_market_cap": 2.1e12,
    },
    {
        "end_date": "2023-12-31",
        "holder_count": 190000.0,
        "holder_count_change": 1500.0,
        "holder_count_change_pct": 0.80,
        "avg_hold_shares": 6610.0,
        "avg_hold_amount": 12000000.0,
        "total_market_cap": 2.0e12,
    },
]

_SAMPLE_PAYLOAD = {
    "result": {
        "data": [
            {
                "SECUCODE": "600519.SH",
                "END_DATE": "2024-03-31 00:00:00",
                "HOLDER_NUM": 188000,
                "HOLDER_NUM_CHANGE": -2000,
                "HOLDER_NUM_RATIO": -1.05,
                "AVG_HOLD_NUM": 6680.0,
                "AVG_HOLD_AMT": 12345678.0,
                "TOTAL_MARKET_CAP": 2.1e12,
            },
            {
                "SECUCODE": "600519.SH",
                "END_DATE": "2023-12-31 00:00:00",
                "HOLDER_NUM": 190000,
                "HOLDER_NUM_CHANGE": 1500,
                "HOLDER_NUM_RATIO": 0.80,
                "AVG_HOLD_NUM": 6610.0,
                "AVG_HOLD_AMT": 12000000.0,
                "TOTAL_MARKET_CAP": 2.0e12,
            },
        ]
    }
}


# --------------------------------------------------------------------------- #
# Eastmoney path (hikyuu mocked as unavailable -> tool falls through)          #
# --------------------------------------------------------------------------- #


def test_success_envelope_parses_periods_newest_first():
    with patch.object(sct, "_fetch_hikyuu", return_value=None):
        with patch.object(sct, "get_json", return_value=_SAMPLE_PAYLOAD) as mock_get:
            out = ShareholderCountTool().execute(code="600519.SH")

    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["market"] == "CN"
    assert payload["source"] == "eastmoney"
    assert payload["data"]["code"] == "600519.SH"

    periods = payload["data"]["periods"]
    assert len(periods) == 2
    assert periods[0] == {
        "end_date": "2024-03-31",
        "holder_count": 188000.0,
        "holder_count_change": -2000.0,
        "holder_count_change_pct": -1.05,
        "avg_hold_shares": 6680.0,
        "avg_hold_amount": 12345678.0,
        "total_market_cap": 2.1e12,
    }

    # SECUCODE filter flows through to the datacenter request.
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["filter"] == '(SECUCODE="600519.SH")'


def test_max_periods_caps_returned_rows():
    with patch.object(sct, "_fetch_hikyuu", return_value=None):
        with patch.object(sct, "get_json", return_value=_SAMPLE_PAYLOAD):
            out = ShareholderCountTool().execute(code="600519.SH", max_periods=1)
    payload = json.loads(out)
    assert len(payload["data"]["periods"]) == 1


def test_empty_disclosure_returns_error_envelope():
    with patch.object(sct, "_fetch_hikyuu", return_value=None):
        with patch.object(sct, "get_json", return_value={"result": {"data": []}}):
            out = ShareholderCountTool().execute(code="600519.SH")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "no shareholder-count" in payload["error"]


def test_request_failure_is_caught_as_error_envelope():
    with patch.object(sct, "_fetch_hikyuu", return_value=None):
        with patch.object(sct, "get_json", side_effect=RuntimeError("HTTP 429")):
            out = ShareholderCountTool().execute(code="600519.SH")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "429" in payload["error"]


# --------------------------------------------------------------------------- #
# Hikyuu routing (hikyuu preferred, falls back to Eastmoney)                   #
# --------------------------------------------------------------------------- #


def test_prefers_hikyuu_and_skips_eastmoney():
    with patch.object(sct, "_fetch_hikyuu", return_value=_HIKYUU_PERIODS) as mock_hk:
        with patch.object(sct, "get_json", side_effect=AssertionError("eastmoney must not be hit")) as mock_em:
            out = ShareholderCountTool().execute(code="600519.SH")

    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["source"] == "hikyuu"
    assert len(payload["data"]["periods"]) == 2
    mock_hk.assert_called_once_with("600519.SH", 24)
    mock_em.assert_not_called()


def test_falls_back_to_eastmoney_when_hikyuu_empty():
    with patch.object(sct, "_fetch_hikyuu", return_value=None):
        with patch.object(sct, "get_json", return_value=_SAMPLE_PAYLOAD) as mock_em:
            out = ShareholderCountTool().execute(code="600519.SH")

    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["source"] == "eastmoney"
    mock_em.assert_called_once()


# --------------------------------------------------------------------------- #
# Validation                                                                   #
# --------------------------------------------------------------------------- #


def test_non_a_share_returns_error_envelope():
    out = ShareholderCountTool().execute(code="AAPL.US")
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "A-share" in payload["error"]


def test_missing_code_returns_error_envelope():
    out = ShareholderCountTool().execute()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "required" in payload["error"]


def test_tool_has_no_source_parameter():
    """The tool must NOT expose a source param; routing stays internal."""
    assert "source" not in ShareholderCountTool.parameters["properties"]
