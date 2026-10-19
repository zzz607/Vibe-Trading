"""Unit tests for the ashare F10 text-block accessor.

A miniature ashare directory is built in ``tmp_path`` (one parquet per category),
so the real duckdb read path runs offline. The parsing cases use verbatim
fragments of the 通达信 text, including the awkward parts: the section header
declared twice, ``万`` magnitudes living in the column header rather than the
cell, and ``---`` standing in for a missing target price.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from backtest.loaders import ashare_f10
from backtest.loaders.ashare_f10 import (
    AshareF10,
    MAX_AGE_DAYS,
    is_fresh,
    parse_forecast_details,
    parse_forecast_table,
    parse_announcements,
    parse_fund_flow,
    parse_media,
    parse_margin,
    parse_rating_stats,
    sections,
    to_number,
)

_RESEARCH = """研报评级☆ ◇600685 中船防务 更新日期：◇ 通达信沪深京F10
★本栏包括【1.投资评级统计】【2.盈利预测统计】【3.盈利预测明细】
          【5.机构调研】

【1.投资评级统计】最新评级日期:2026-09-08
时间段   买入评级次数   增持评级次数   中性评级次数   减持评级次数   卖出评级次数   评级次数合计
────────────────────────────────────────────────
2月内               1              0              0              0              0              1
6月内               3              0              0              0              0              3
────────────────────────────────────────────────

【2.盈利预测统计】(近6个月)
┌──────────┬─────┬─────┬─────┬─────┐
│财务指标            │  2025年│2026年预测│2027年预测│
├──────────┼─────┼─────┼─────┤
│每股收益(元)        │   0.71│   1.19│   1.59│
│营业收入(百万元)    │ 20547.30│ 23000.00│ 25850.00│
└──────────┴─────┴─────┴─────┘

【3.盈利预测明细】(近6个月)
日期           评级       评级变化       目标价    2026EPS    2027EPS    2028EPS       研究机构
────────────────────────────────────────────────
2026-09-08     买入       维持              ---       1.18       1.71       2.75       浙商证券
2026-09-01     增持       维持            32.43       2.19       2.47       2.69       广发证券
────────────────────────────────────────────────

【5.机构调研】 暂无数据
"""

_CAPITAL_FLOW = """资金动向☆ ◇002352 顺丰控股 更新日期：◇ 通达信沪深京F10
★本栏包括【1.交易龙虎榜】【2.大宗交易】【3.融资融券】【4.资金流向】

【1.交易龙虎榜】
 最近1年内该股未能登上龙虎榜。

【2.大宗交易】 暂无数据

【3.融资融券】
截止2026-10-16，可充抵保证金最高折算率为65.00%
2026-10-15融资融券信息：融资偿还额4170.55万元，融资净买额-613.45万元
交易日期         融资余额(万)   融资买入额(万)     融券余额(万)   融券卖出量(万) 融资融券余额(万)
─────────────────────────────────────────────────
2026-10-16          705731.80          5107.57           141.21             0.58        707143.90
2026-10-15          703787.30          4402.53           204.95             0.29        705836.80
─────────────────────────────────────────────────

【4.资金流向】
─────┬──────────┬──────────┬──────────┬──────────
          │      主力净额      │    超大单净买入    │     大单净买入     │      主买净额
   日期   ├─────┬────┼─────┬────┼─────┬────┼─────┬────
          │ 金额(元) │ 占比(%)│ 金额(元) │ 占比(%)│ 金额(元) │ 占比(%)│ 金额(元) │ 占比(%)
─────┼─────┼────┼─────┼────┼─────┼────┼─────┼────
2026-10-16│ 2591.64万│    3.98│ 1516.68万│    2.33│ 1074.97万│    1.65│ 5477.77万│    8.41
2026-10-15│-2000.63万│   -3.36│-1445.16万│   -2.43│ -555.46万│   -0.93│ 5873.42万│    9.88
─────┴─────┴────┴─────┴────┴─────┴────┴─────┴────

〖免责条款〗
 1、本公司力求但不保证提供的任何信息的真实性、准确性、完整性及原创性等，投资者使
 用前请自行予以核实。
"""


_ANNOUNCEMENTS = """公司公告☆ ◇002352 顺丰控股 更新日期：◇ 通达信沪深京F10
★本栏包括【1.公告列表】【2.财报链接】

【1.公告列表】
┌─────────┬──────────────────────────────────────────────┐
│2026-10-16 19:07  │顺丰控股（002352）：H股公告-董事会会议召开日期              │
├─────────┼──────────────────────────────────────────────┤
│2026-10-10 00:00  │顺丰控股（002352）：关于投资者热线电话临时变更的公告        │
└─────────┴──────────────────────────────────────────────┘
─────────┬────────────────────────────────────────────────
  2026-10-16 19:07│顺丰控股（002352）：H股公告-董事会会议召开日期
─────────┴────────────────────────────────────────────────
    董事会宣布，本公司将于2026年10月28日举行董事会会议。
"""

_MEDIA = """公司报道☆ ◇002352 顺丰控股 更新日期：◇ 通达信沪深京F10

─────────┬────────────────────────────────────────────────
  2026-09-18 20:27│顺丰控股(002352)：8月速运物流业务收入184.06亿元
─────────┴────────────────────────────────────────────────
    智通财经APP讯，顺丰控股发布公告，公司2026年8月速运物流业务收入184.06亿元。
http://www.zhitongcaijing.com/content/detail/1498235.html

─────────┬────────────────────────────────────────────────
  2026-09-14 20:00│顺丰控股(002352)投资者关系活动主要内容
─────────┴────────────────────────────────────────────────
    Q1：公司每年在中转场的自动化投入多少？
    答：资产类资本开支占收入比维持在4%以内。
"""


def _write_category(root, code, index, content, updated, ingested=None):
    import duckdb

    path = root / "f10" / "year=2026" / "month=10" / f"part-{code}-{index}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "code": code,
                "exchange": "SH" if code.startswith("6") else "SZ",
                "category_index": index,
                "category_name": ashare_f10.CATEGORY_NAMES[index],
                "filename": f"{code}.txt",
                "file_start": 0,
                "file_length": len(content),
                "content": content,
                "content_hash": "x" * 32,
                "server_update_date": updated,
                "_ingested_at": ingested or pd.Timestamp("2026-10-17 18:00"),
                "_source": "test",
            }
        ]
    )
    con = duckdb.connect()
    try:
        con.register("src", frame)
        con.execute(f"COPY (SELECT * FROM src) TO '{path}' (FORMAT PARQUET)")
    finally:
        con.close()


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "ashare-data"
    (root / "f10").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "backtest.loaders.ashare_loader._data_dir", lambda: root
    )
    return root


def _seed(root, code="600685", updated=None):
    updated = updated or date.today() - timedelta(days=1)
    _write_category(root, code, 15, _RESEARCH, updated)
    _write_category(root, code, 8, _CAPITAL_FLOW, updated)
    _write_category(root, code, 11, _ANNOUNCEMENTS, updated)
    _write_category(root, code, 12, _MEDIA, updated)
    return root


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def test_sections_body_overrides_header_declaration():
    """The header lists every section as a bare stub; the body must win."""
    blocks = sections(_RESEARCH)
    assert "投资评级统计" in blocks
    # The stub in the ★本栏包括 line is 0 chars; the real body is not.
    assert "最新评级日期" in blocks["投资评级统计"]
    assert blocks["机构调研"].strip() == "暂无数据"


def test_sections_drops_the_disclaimer():
    blocks = sections(_CAPITAL_FLOW)
    assert all("免责条款" not in body for body in blocks.values())


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("2591.64万", 25_916_400.0),
        ("-2000.63万", -20_006_300.0),
        ("3.5亿", 350_000_000.0),
        ("355894.97", 355_894.97),
        ("---", None),
        ("-", None),
        ("", None),
        ("暂无", None),
        (None, None),
        ("1,234.5", 1234.5),
    ],
)
def test_to_number_handles_units_and_nulls(token, expected):
    assert to_number(token) == expected


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def test_parse_rating_stats():
    stats = parse_rating_stats(sections(_RESEARCH)["投资评级统计"])
    assert stats["latest_rating_date"] == "2026-09-08"
    windows = {row["window"]: row for row in stats["windows"]}
    assert windows["2月内"]["buy"] == 1
    assert windows["6月内"]["buy"] == 3
    assert windows["6月内"]["total"] == 3


def test_parse_forecast_table_feeds_consensus_eps():
    table = parse_forecast_table(sections(_RESEARCH)["盈利预测统计"])
    assert table["metrics"]["每股收益(元)"]["2026年预测"] == 1.19
    # Only columns whose header says 预测 become consensus rows.
    assert table["consensus_eps"] == [
        {"fiscal_year": "2026", "consensus_eps": 1.19},
        {"fiscal_year": "2027", "consensus_eps": 1.59},
    ]


def test_parse_forecast_details_keeps_brokerage_clean():
    """A ``---`` target price is None, and brokerage must not absorb the EPS."""
    rows = parse_forecast_details(sections(_RESEARCH)["盈利预测明细"])
    assert len(rows) == 2
    first = rows[0]
    assert first["brokerage"] == "浙商证券"
    assert first["target_price"] is None
    assert first["eps_forecast"] == {
        "this_year": 1.18,
        "next_year": 1.71,
        "year_after": 2.75,
    }
    assert rows[1]["target_price"] == 32.43
    assert rows[1]["rating_change"] == "维持"


def test_parse_margin_scales_wan_columns_to_base_units():
    """The 万 magnitude is in the header, so every cell must be scaled."""
    parsed = parse_margin(sections(_CAPITAL_FLOW)["融资融券"])
    assert parsed["margin_ratio"] == 65.0
    assert parsed["latest_financing_repay"] == 41_705_500.0
    newest = parsed["rows"][0]
    assert newest["trade_date"] == "2026-10-16"
    assert newest["financing_balance"] == 7_057_318_000.0
    assert newest["short_sell_volume"] == 5800.0


def test_parse_margin_names_short_sell_volume_by_its_real_meaning():
    """F10's 融券卖出量 is not Eastmoney's RQYL (outstanding), so no aliasing."""
    newest = parse_margin(sections(_CAPITAL_FLOW)["融资融券"])["rows"][0]
    assert "short_sell_volume" in newest
    assert "short_volume" not in newest
    assert "financing_repay" not in newest


# ---------------------------------------------------------------------------
# Freshness gate
# ---------------------------------------------------------------------------


def test_is_fresh_boundary():
    today = date.today()
    assert is_fresh(today - timedelta(days=MAX_AGE_DAYS)) is True
    assert is_fresh(today - timedelta(days=MAX_AGE_DAYS + 1)) is False


def test_is_fresh_rejects_undated():
    """An undated block cannot be proven fresh, so it must not be served."""
    assert is_fresh(None) is False


# ---------------------------------------------------------------------------
# Accessor over a real (miniature) parquet store
# ---------------------------------------------------------------------------


def test_research_reads_the_local_store(data_dir):
    _seed(data_dir)
    payload = AshareF10().research("600685.SH")
    assert payload is not None
    assert payload["latest_rating_date"] == "2026-09-08"
    assert len(payload["details"]) == 2


def test_margin_reads_the_local_store(data_dir):
    _seed(data_dir)
    payload = AshareF10().margin("600685.SH", days=5)
    assert payload is not None
    assert len(payload["rows"]) == 2
    assert payload["margin_ratio"] == 65.0


def test_stale_snapshot_is_ignored(data_dir):
    """A snapshot past the age limit must report no data, not stale numbers."""
    _seed(data_dir, updated=date.today() - timedelta(days=MAX_AGE_DAYS + 1))
    assert AshareF10().research("600685.SH") is None
    assert AshareF10().margin("600685.SH") is None


def test_missing_code_returns_none(data_dir):
    _seed(data_dir)
    assert AshareF10().research("000001.SZ") is None


def test_non_a_share_symbol_raises(data_dir):
    _seed(data_dir)
    with pytest.raises(ValueError, match="A-share only"):
        AshareF10().research("AAPL.US")


# ---------------------------------------------------------------------------
# Capital flow — four groups, not Eastmoney's five buckets
# ---------------------------------------------------------------------------


def test_parse_fund_flow_four_groups():
    rows = parse_fund_flow(sections(_CAPITAL_FLOW)["资金流向"])
    assert len(rows) == 2
    newest = rows[0]
    assert newest["trade_date"] == "2026-10-16"
    assert newest["main_net"] == 25_916_400.0
    assert newest["main_ratio"] == 3.98
    assert newest["active_buy_net"] == 54_777_700.0
    # Negative flows must survive the parse.
    assert rows[1]["main_net"] == -20_006_300.0
    assert rows[1]["main_ratio"] == -3.36


def test_parse_fund_flow_does_not_invent_five_buckets():
    """No small/medium exist locally, so the five-bucket names must not appear."""
    newest = parse_fund_flow(sections(_CAPITAL_FLOW)["资金流向"])[0]
    for absent in ("main", "small", "medium", "large", "super_large"):
        assert absent not in newest


def test_fund_flow_accessor_reads_the_store(data_dir):
    _seed(data_dir)
    rows = AshareF10().fund_flow("600685.SH", days=5)
    assert rows is not None and len(rows) == 2


# ---------------------------------------------------------------------------
# News — announcements (table) + coverage (flat article stream)
# ---------------------------------------------------------------------------


def test_parse_announcements_ignores_the_body_block():
    """The table holds the headlines; the prose below it must not become rows."""
    rows = parse_announcements(sections(_ANNOUNCEMENTS)["公告列表"])
    assert len(rows) == 2
    assert rows[0]["publish_time"] == "2026-10-16 19:07"
    assert "董事会会议召开日期" in rows[0]["title"]
    assert all(row["kind"] == "announcement" for row in rows)
    assert not any("董事会宣布" in (row["title"] or "") for row in rows)


def test_parse_media_extracts_title_body_and_url():
    rows = parse_media(_MEDIA)
    assert len(rows) == 2
    first = rows[0]
    assert first["publish_time"] == "2026-09-18 20:27"
    assert "8月速运物流业务收入184.06亿元" in first["title"]
    assert first["kind"] == "media"
    assert first["url"] == "http://www.zhitongcaijing.com/content/detail/1498235.html"
    # The URL must be pulled out of the excerpt, not left inside it.
    assert "zhitongcaijing" not in first["snippet"]
    assert "智通财经APP讯" in first["snippet"]


def test_media_body_without_url_is_still_parsed():
    rows = parse_media(_MEDIA)
    assert rows[1]["url"] is None
    assert "资本开支" in rows[1]["snippet"]


def test_news_merges_both_kinds_newest_first(data_dir):
    _seed(data_dir)
    rows = AshareF10().news("600685.SH", limit=10)
    assert rows is not None
    kinds = {row["kind"] for row in rows}
    assert kinds == {"announcement", "media"}
    times = [row["publish_time"] for row in rows]
    assert times == sorted(times, reverse=True)
