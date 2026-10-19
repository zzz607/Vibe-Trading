"""Bocha (博查) provider for ``web_search``.

Bocha is an official JSON API (Bearer auth, ``data.webPages.value[]``), unlike
the ddgs engines which scrape HTML. These tests pin the parts that differ from
the existing Aliyun IQS provider:

* no key configured -> ``None`` (not an error, so the provider chain moves on)
* ``summary`` wins over ``snippet`` when both are present
* a 200 response carrying a non-200 body ``code`` must raise, not return []
* the provider chain falls through to Bocha when IQS is unconfigured
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.tools import web_search_tool
from src.tools.web_search_tool import _bocha_search


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body


def _config(*, bocha: str = "test-key", iqs: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        data=SimpleNamespace(bocha_api_key=bocha, aliyun_iqs_api_key=iqs),
        agent_tuning=SimpleNamespace(
            vibe_trading_search_backends="",
            vibe_trading_search_proxy="",
            vibe_trading_search_bing_fallback=False,
        ),
    )


@pytest.fixture()
def no_network(monkeypatch):
    """Fail loudly if anything actually dials out during a test."""

    def _boom(*_args, **_kwargs):
        raise AssertionError("unexpected network call")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    return _boom


def test_returns_none_when_key_missing(monkeypatch, no_network):
    monkeypatch.setattr(web_search_tool, "get_env_config", lambda: _config(bocha=""))
    assert _bocha_search("中船防务", max_results=5) is None


def test_parses_webpages_value_and_prefers_summary(monkeypatch):
    payload = {
        "code": 200,
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "中船防务2026半年报",
                        "url": "https://example.com/a",
                        "snippet": "短摘要",
                        "summary": "更长的模型摘要，含营收 111.20 亿元",
                        "siteName": "东方财富",
                    },
                    {
                        "name": "无摘要的条目",
                        "url": "https://example.com/b",
                        "snippet": "只有 snippet",
                    },
                ]
            }
        },
    }
    monkeypatch.setattr(web_search_tool, "get_env_config", lambda: _config())
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(payload))

    rows = _bocha_search("中船防务", max_results=5)

    assert rows is not None and len(rows) == 2
    assert rows[0]["title"] == "中船防务2026半年报"
    assert rows[0]["href"] == "https://example.com/a"
    assert rows[0]["body"] == "更长的模型摘要，含营收 111.20 亿元"
    # Falls back to snippet when summary is absent.
    assert rows[1]["body"] == "只有 snippet"


def test_raises_on_non_200_body_code(monkeypatch):
    """A 200 HTTP response can still carry an API-level error."""
    payload = {"code": 403, "message": "quota exceeded"}
    monkeypatch.setattr(web_search_tool, "get_env_config", lambda: _config())
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(payload))

    with pytest.raises(RuntimeError, match="quota exceeded"):
        _bocha_search("中船防务", max_results=5)


def test_empty_pages_returns_empty_list(monkeypatch):
    """An answered-but-empty query is [] (configured), not None (unconfigured)."""
    payload = {"code": 200, "data": {"webPages": {"value": []}}}
    monkeypatch.setattr(web_search_tool, "get_env_config", lambda: _config())
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(payload))

    assert _bocha_search("no-such-thing", max_results=5) == []


def test_missing_webpages_key_is_tolerated(monkeypatch):
    payload = {"code": 200, "data": {}}
    monkeypatch.setattr(web_search_tool, "get_env_config", lambda: _config())
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(payload))

    assert _bocha_search("query", max_results=5) == []


def test_result_cap_is_applied(monkeypatch):
    pages = [
        {"name": f"r{i}", "url": f"https://example.com/{i}", "snippet": "s"}
        for i in range(10)
    ]
    payload = {"code": 200, "data": {"webPages": {"value": pages}}}
    monkeypatch.setattr(web_search_tool, "get_env_config", lambda: _config())
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(payload))

    assert len(_bocha_search("query", max_results=3)) == 3


# ---------------------------------------------------------------------------
# Provider chain
# ---------------------------------------------------------------------------


def test_chain_falls_through_iqs_to_bocha(monkeypatch):
    """IQS unconfigured must not block Bocha, and `backends` names the winner."""
    monkeypatch.setattr(web_search_tool, "get_env_config", lambda: _config(iqs=""))
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(
        {
            "code": 200,
            "data": {"webPages": {"value": [
                {"name": "标题", "url": "https://example.com/x", "summary": "摘要"}
            ]}},
        }
    ))

    payload = json.loads(web_search_tool.WebSearchTool().execute(query="中船防务", max_results=3))

    assert payload["status"] == "ok"
    assert payload["backends"] == "bocha"
    assert payload["results"][0]["url"] == "https://example.com/x"


def test_chain_survives_a_failing_bocha_and_reaches_ddgs(monkeypatch):
    """A provider error must degrade to the next layer, never fail the tool."""
    monkeypatch.setattr(web_search_tool, "get_env_config", lambda: _config(iqs=""))
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("connection refused")),
    )

    class _FakeDDGS:
        def __init__(self, *args, **kwargs): ...
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def text(self, *args, **kwargs):
            return [{"title": "ddgs 结果", "href": "https://example.com/d", "body": "b"}]

    monkeypatch.setitem(__import__("sys").modules, "ddgs", SimpleNamespace(DDGS=_FakeDDGS))
    monkeypatch.setitem(
        __import__("sys").modules, "duckduckgo_search", SimpleNamespace(DDGS=_FakeDDGS)
    )

    payload = json.loads(web_search_tool.WebSearchTool().execute(query="q", max_results=3))

    assert payload["status"] == "ok"
    assert payload["results"][0]["title"] == "ddgs 结果"
