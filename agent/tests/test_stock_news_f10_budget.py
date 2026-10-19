"""Budget guard for the F10-backed ``get_stock_news`` envelope.

F10 excerpts are far longer than Eastmoney headlines, so a full page of them can
render past the runtime's 10,000-character truncation cap. Truncation happens on
the already-serialized string, which cuts the JSON mid-token and leaves the model
with an unparseable result — so the tool must trim *before* returning.

These tests assert the trim keeps the envelope (a) under the cap and (b) valid
JSON, without needing the real data store.
"""

from __future__ import annotations

import json

from src.config.limits import TOOL_RESULT_LIMIT, truncate_tool_result
from src.tools.stock_news_tool import _ARTICLE_BUDGET, _fit_articles


def _article(index: int, snippet_len: int = 400) -> dict:
    return {
        "publish_time": f"2026-09-{index:02d} 10:00",
        "title": f"中船防务(600685)：第{index}条报道标题",
        "kind": "media",
        "snippet": "讯，" * (snippet_len // 2),
        "url": "https://example.com/a/rb2026" + str(index),
    }


def _render(articles: list[dict], code: str = "600685.SH") -> str:
    return json.dumps(
        {
            "ok": True,
            "market": "a_share",
            "source": "ashare_f10",
            "data": {"scope": "stock", "code": code, "articles": articles},
        },
        ensure_ascii=False,
    )


def test_trimmed_envelope_stays_under_the_cap():
    articles = [_article(i) for i in range(30)]

    kept = _fit_articles(articles, "600685.SH")

    assert len(_render(kept)) <= _ARTICLE_BUDGET < TOOL_RESULT_LIMIT


def test_trimmed_envelope_is_not_truncated_by_the_runtime():
    """The real failure mode: a 10k cut leaves invalid JSON, not a short list."""
    articles = [_article(i) for i in range(40)]

    rendered = _render(_fit_articles(articles, "000001.SZ"))
    survived = truncate_tool_result(rendered)

    assert len(survived) == len(rendered), "runtime must not need to truncate"
    json.loads(survived)  # parses => the model can actually read it


def test_trim_drops_oldest_first_and_keeps_at_least_one():
    articles = [_article(i) for i in range(40)]

    kept = _fit_articles(articles, "600685.SH")

    assert len(articles) < 40, "some articles must be dropped"
    assert kept, "never trim down to nothing"
    # The tail is dropped, so the oldest surviving entry is still from the head.
    assert kept == articles[: len(kept)]


def test_small_payload_is_left_untouched():
    articles = [_article(1, snippet_len=40), _article(2, snippet_len=40)]

    assert _fit_articles(articles, "600685.SH") == articles
