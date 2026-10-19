"""ashare F10 text-block accessor (local Parquet store).

Companion to :mod:`backtest.loaders.ashare_loader` (OHLCV) and
:mod:`backtest.loaders.ashare_financial` (history_finance). This one reads the
ashare ``f10`` dataset: one row per ``(code, category)``, where ``content`` is
the 通达信-format 东财 F10 text for that category (16 categories, index 0-15).

Inside a category the text is delimited by ``【N.小节名】`` and each section is
one of three shapes — space-aligned table, box-drawing table, or an inline
sentence (``暂无数据``). The parsers below are therefore section-specific; there
is deliberately no general table engine, because the column layout differs per
section and a generic parser would silently mis-align them.

Freshness: F10 is a periodic snapshot, not a live feed. Every read is gated on
``server_update_date`` being within :data:`MAX_AGE_DAYS`; a stale (or undated)
snapshot makes the accessor report no data, so the caller falls back to the live
provider instead of serving stale numbers that look authoritative.

Lazy initialization: ``is_available()`` only probes duckdb + the directory; the
category text is read on first use, so importing this module never touches disk.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from backtest.loaders.ashare_loader import _split_symbol

logger = logging.getLogger(__name__)

_DATASET = "f10"

#: A F10 snapshot older than this is treated as absent. Seven days matches the
#: weekly refresh cadence of the collector; beyond it the live provider wins.
MAX_AGE_DAYS = 7

#: ``category_index`` -> category name. The index is the stable key — the text
#: for index 8/9/15 carries two different names across ingest vintages.
CATEGORY_NAMES: Dict[int, str] = {
    0: "最新提示",
    1: "公司概况",
    2: "财务分析",
    3: "股本结构",
    4: "股东研究",
    5: "机构持股",
    6: "分红融资",
    7: "高管治理",
    8: "资金动向",
    9: "资本运作",
    10: "热点题材",
    11: "公司公告",
    12: "公司报道",
    13: "经营分析",
    14: "行业分析",
    15: "研报评级",
}

IDX_CAPITAL_FLOW = 8
IDX_RESEARCH = 15
IDX_ANNOUNCEMENTS = 11
IDX_MEDIA = 12

#: Per-section heading, e.g. ``【3.融资融券】``.
_SECTION_RE = re.compile(r"【(\d+)\.([^】]+)】")
_DISCLAIMER = "〖免责条款〗"
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

#: Chinese magnitude suffixes used by the F10 numeric cells.
_UNIT_SCALES = (("万", 1e4), ("亿", 1e8))
_NULL_TOKENS = frozenset({"", "-", "--", "---", "—", "暂无", "暂无数据", "N/A"})


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """True when duckdb imports and the data directory holds ``f10/``."""
    try:
        import duckdb  # noqa: F401
    except Exception:  # noqa: BLE001 - any import breakage = unavailable
        return False
    from backtest.loaders.ashare_loader import _data_dir

    return (_data_dir() / _DATASET).is_dir()


def read_category(code6: str, index: int) -> Optional[Tuple[str, Optional[date]]]:
    """Read one ``(code, category)`` text block, newest ingest winning.

    Args:
        code6: Six-digit ticker (no exchange suffix — the dataset has none).
        index: ``category_index`` (0-15); see :data:`CATEGORY_NAMES`.

    Returns:
        ``(content, server_update_date)`` or ``None`` when the store has no row
        for that pair.
    """
    try:
        import duckdb
    except Exception as exc:  # noqa: BLE001
        logger.warning("ashare f10: duckdb unavailable: %s", exc)
        return None

    from backtest.loaders.ashare_loader import _data_dir

    directory = _data_dir() / _DATASET
    if not directory.is_dir():
        return None

    # No ``filename = true`` here: the dataset carries its own ``filename``
    # column (the source .txt), and asking duckdb to add one collides with it.
    sql = (
        "SELECT content, server_update_date"
        " FROM read_parquet(?, hive_partitioning = true, union_by_name = true)"
        " WHERE code = ? AND category_index = ?"
        " ORDER BY _ingested_at DESC, filename DESC"
        " LIMIT 1"
    )
    con = duckdb.connect()
    try:
        row = con.execute(sql, [str(directory / "**" / "*.parquet"), code6, int(index)]).fetchone()
    except Exception as exc:  # noqa: BLE001 - missing partition/column -> no data
        logger.warning("ashare f10 query failed for %s cat=%s: %s", code6, index, exc)
        return None
    finally:
        con.close()

    if not row:
        return None
    content, updated = row[0], row[1]
    return content or "", _as_date(updated)


def read_categories(
    code6: str, indices: Tuple[int, ...]
) -> Dict[int, Tuple[str, Optional[date]]]:
    """Read several categories in a single scan.

    The store is one ~1 GB parquet, and row-group statistics only prune it for
    some codes: a code whose data sits in a wide value range costs ~1.5 s per
    query regardless of how small its rows are. Fetching N categories in one
    statement therefore roughly halves the wall time versus N separate reads.

    Args:
        code6: Six-digit ticker.
        indices: ``category_index`` values to fetch.

    Returns:
        ``{index: (content, server_update_date)}`` for whichever indices exist;
        missing ones are absent from the mapping. When the store holds several
        ingests of one category, the newest wins.
    """
    try:
        import duckdb
    except Exception as exc:  # noqa: BLE001
        logger.warning("ashare f10: duckdb unavailable: %s", exc)
        return {}

    from backtest.loaders.ashare_loader import _data_dir

    directory = _data_dir() / _DATASET
    if not directory.is_dir() or not indices:
        return {}

    placeholders = ", ".join("?" for _ in indices)
    sql = (
        "SELECT category_index, content, server_update_date"
        " FROM read_parquet(?, hive_partitioning = true, union_by_name = true)"
        f" WHERE code = ? AND category_index IN ({placeholders})"
        " ORDER BY category_index, _ingested_at DESC, filename DESC"
    )
    con = duckdb.connect()
    try:
        rows = con.execute(
            sql, [str(directory / "**" / "*.parquet"), code6, *indices]
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - missing partition/column -> no data
        logger.warning("ashare f10 multi-query failed for %s: %s", code6, exc)
        return {}
    finally:
        con.close()

    out: Dict[int, Tuple[str, Optional[date]]] = {}
    for index, content, updated in rows:
        if index in out:  # already took the newest ingest
            continue
        out[index] = (content or "", _as_date(updated))
    return out


def _as_date(value: Any) -> Optional[date]:
    """Coerce a provider date cell to :class:`datetime.date`."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def is_fresh(updated: Optional[date], max_age_days: int = MAX_AGE_DAYS) -> bool:
    """Whether a snapshot date is recent enough to serve.

    An undated block counts as stale: the collector writes
    ``server_update_date`` whenever the text carries one, so a NULL means the
    freshness of that block cannot be established.
    """
    if updated is None:
        return False
    return (date.today() - updated).days <= max_age_days


# ---------------------------------------------------------------------------
# Parsing primitives
# ---------------------------------------------------------------------------


def sections(text: str) -> Dict[str, str]:
    """Split a category body into ``{section name: body}``.

    The header line lists every section once as ``【N.名称】`` with no content,
    and the body repeats each heading with real content, so a later duplicate
    must overwrite the earlier stub.
    """
    body = text.split(_DISCLAIMER, 1)[0]
    matches = list(_SECTION_RE.finditer(body))
    out: Dict[str, str] = {}
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(body)
        out[match.group(2).strip()] = body[match.end():end]
    return out


def to_number(token: Any) -> Optional[float]:
    """Parse an F10 numeric cell, applying ``万`` / ``亿`` and dropping nulls."""
    if token is None:
        return None
    text = str(token).strip().replace(",", "")
    if text in _NULL_TOKENS:
        return None
    scale = 1.0
    for suffix, factor in _UNIT_SCALES:
        if text.endswith(suffix):
            scale = factor
            text = text[: -len(suffix)]
            break
    try:
        return float(text) * scale
    except (TypeError, ValueError):
        return None


def _wan(token: Any) -> Optional[float]:
    """Parse a cell whose column header states 万 (10k) into the base unit.

    The magnitude lives in the header, not in the cell, so :func:`to_number`
    alone would return 万元/万股 and understate every figure by 10,000×.
    """
    value = to_number(token)
    # round() strips the binary-float tail (355894.97 * 1e4 = 3558949699.9999995).
    return None if value is None else round(value * 1e4, 2)


def _space_rows(block: str) -> List[List[str]]:
    """Whitespace-separated data rows, skipping rule/header lines.

    A rule line is one made only of box-drawing characters; a data row is any
    line with at least two tokens.
    """
    rows: List[List[str]] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or set(stripped) <= set("─━-— "):
            continue
        if stripped.startswith(("┌", "├", "└", "│")):
            continue
        tokens = stripped.split()
        if len(tokens) >= 2:
            rows.append(tokens)
    return rows


def _box_rows(block: str) -> List[List[str]]:
    """Cells of a box-drawing table, one list per ``│…│`` line."""
    rows: List[List[str]] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("│"):
            continue
        cells = [cell.strip() for cell in stripped.strip("│").split("│")]
        if any(cells):
            rows.append(cells)
    return rows


def _dated_rows(block: str) -> List[List[str]]:
    """Rows whose first token is an ISO date (``YYYY-MM-DD``)."""
    rows: List[List[str]] = []
    for line in block.splitlines():
        tokens = line.split()
        if tokens and _DATE_ONLY_RE.match(tokens[0]):
            rows.append(tokens)
    return rows


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def parse_rating_stats(block: str) -> Dict[str, Any]:
    """Parse ``【1.投资评级统计】``.

    Returns:
        ``{"latest_rating_date": str | None, "windows": [{"window", "buy",
        "overweight", "neutral", "underweight", "sell", "total"}]}``.
    """
    result: Dict[str, Any] = {"latest_rating_date": None, "windows": []}
    match = re.search(r"最新评级日期[:：]\s*(\d{4}-\d{2}-\d{2})", block)
    if match:
        result["latest_rating_date"] = match.group(1)

    keys = ("buy", "overweight", "neutral", "underweight", "sell", "total")
    for tokens in _space_rows(block):
        head = tokens[0]
        if not head.endswith(("月内", "年内")):
            continue
        numbers = [to_number(token) for token in tokens[1:]]
        if len(numbers) < len(keys):
            continue
        entry: Dict[str, Any] = {"window": head}
        for key, value in zip(keys, numbers):
            entry[key] = int(value) if value is not None else None
        result["windows"].append(entry)
    return result


def parse_forecast_table(block: str) -> Dict[str, Any]:
    """Parse ``【2.盈利预测统计】`` (box table, one row per financial metric).

    Returns:
        ``{"years": [column headers], "metrics": {metric: {year: value}},
        "consensus_eps": [{"fiscal_year", "consensus_eps"}]}``. Only columns
        whose header marks a forecast (``…预测``) feed ``consensus_eps``.
    """
    rows = _box_rows(block)
    if not rows:
        return {"years": [], "metrics": {}, "consensus_eps": []}

    header = rows[0]
    years = header[1:]
    metrics: Dict[str, Dict[str, Optional[float]]] = {}
    for cells in rows[1:]:
        if len(cells) < 2:
            continue
        metric = cells[0]
        if not metric or metric in ("财务指标",):
            continue
        metrics[metric] = {
            year: to_number(value) for year, value in zip(years, cells[1:])
        }

    consensus: List[Dict[str, Any]] = []
    eps_row = next((name for name in metrics if "每股收益" in name), None)
    if eps_row:
        for year, value in metrics[eps_row].items():
            if "预测" not in year or value is None:
                continue
            digits = re.sub(r"\D", "", year)
            if digits:
                consensus.append({"fiscal_year": digits, "consensus_eps": value})
    consensus.sort(key=lambda item: item["fiscal_year"])
    return {"years": years, "metrics": metrics, "consensus_eps": consensus}


def parse_forecast_details(block: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Parse ``【3.盈利预测明细】`` — one sell-side forecast per row.

    Columns: 日期 / 评级 / 评级变化 / 目标价 / 2026EPS / 2027EPS / 2028EPS / 研究机构.
    Trailing extra tokens (an institution name containing a space) are rejoined
    so the field count stays stable.
    """
    out: List[Dict[str, Any]] = []
    for tokens in _dated_rows(block):
        # 8 columns: date / rating / change / target / EPS×3 / institution.
        if len(tokens) < 8:
            continue
        out.append(
            {
                "publish_date": tokens[0],
                "rating": tokens[1],
                "rating_change": tokens[2],
                "target_price": to_number(tokens[3]),
                "eps_forecast": {
                    "this_year": to_number(tokens[4]),
                    "next_year": to_number(tokens[5]),
                    "year_after": to_number(tokens[6]),
                },
                # Rejoin from index 7: an institution name may contain a space.
                "brokerage": " ".join(tokens[7:]) or None,
            }
        )
        if len(out) >= limit:
            break
    return out


def parse_margin(block: str, days: int = 30) -> Dict[str, Any]:
    """Parse ``【3.融资融券】``.

    F10's columns are 交易日期 / 融资余额(万) / 融资买入额(万) / 融券余额(万) /
    融券卖出量(万) / 融资融券余额(万). Note ``融券卖出量`` is the day's *sold*
    volume, which is **not** Eastmoney's ``RQYL`` (outstanding short volume), so
    it is named ``short_sell_volume`` rather than reusing ``short_volume``.
    ``financing_repay`` has no column at all — only the newest day states it in
    prose, which is surfaced separately as ``latest_financing_repay``.

    Returns:
        ``{"margin_ratio": float | None, "latest_financing_repay": float | None,
        "rows": [ ... newest first ... ]}``. Every monetary/volume value is
        converted to base units (元 / 股) so it matches Eastmoney's scale.
    """
    ratio_match = re.search(r"可充抵保证金最高折算率为\s*([\d.]+)\s*%", block)
    repay_match = re.search(r"融资偿还额\s*(-?[\d.]+)\s*万元", block)

    rows: List[Dict[str, Any]] = []
    for tokens in _dated_rows(block):
        if len(tokens) < 6:
            continue
        rows.append(
            {
                "trade_date": tokens[0],
                "financing_balance": _wan(tokens[1]),
                "financing_buy": _wan(tokens[2]),
                "short_balance": _wan(tokens[3]),
                "short_sell_volume": _wan(tokens[4]),
                "margin_total_balance": _wan(tokens[5]),
            }
        )

    return {
        "margin_ratio": to_number(ratio_match.group(1)) if ratio_match else None,
        "latest_financing_repay": (
            float(repay_match.group(1)) * 1e4 if repay_match else None
        ),
        "rows": rows[:days],
    }


def parse_fund_flow(block: str, days: int = 30) -> List[Dict[str, Any]]:
    """Parse ``【4.资金流向】``.

    The table has a two-level header (four groups × amount/ratio) and its data
    rows start with the date rather than ``│``, so it cannot go through
    :func:`_box_rows`.

    Eastmoney reports five buckets (main / small / medium / large / super_large)
    while F10 reports four groups — 主力净额, 超大单净买入, 大单净买入, 主买净额.
    There is no small/medium breakdown, so the keys are named after what F10
    actually measures (``main_net``, ``super_large_net`` …) instead of reusing
    the five-bucket names with two of them silently missing.

    Returns:
        Newest-first rows of ``{trade_date, main_net, main_ratio,
        super_large_net, super_large_ratio, large_net, large_ratio,
        active_buy_net, active_buy_ratio}``; amounts in 元, ratios in percent.
    """
    rows: List[Dict[str, Any]] = []
    for line in block.splitlines():
        if "│" not in line:
            continue
        cells = [cell.strip() for cell in line.split("│")]
        if not cells or not _DATE_ONLY_RE.match(cells[0]):
            continue
        # round(): 5477.77万 * 1e4 lands on 54777700.00000001 otherwise.
        values = [
            None if (parsed := to_number(cell)) is None else round(parsed, 2)
            for cell in cells[1:]
        ]
        if len(values) < 8:
            continue
        rows.append(
            {
                "trade_date": cells[0],
                "main_net": values[0],
                "main_ratio": values[1],
                "super_large_net": values[2],
                "super_large_ratio": values[3],
                "large_net": values[4],
                "large_ratio": values[5],
                "active_buy_net": values[6],
                "active_buy_ratio": values[7],
            }
        )
        if len(rows) >= days:
            break
    return rows


def parse_announcements(block: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Parse ``【1.公告列表】`` from the 公司公告 category.

    Two-column box table (``时间`` / ``标题``). The announcement bodies follow
    the table under a separate rule-line block and are deliberately ignored —
    this accessor backs a headline tool.
    """
    out: List[Dict[str, Any]] = []
    for cells in _box_rows(block):
        if len(cells) < 2 or not _DATE_PREFIX_RE.match(cells[0]):
            continue
        out.append(
            {
                "publish_time": cells[0],
                "title": cells[1],
                "kind": "announcement",
                "snippet": None,
                "url": None,
            }
        )
        if len(out) >= limit:
            break
    return out


def parse_media(block: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Parse the 公司报道 category, which has no ``【N.】`` headings.

    Each entry is a rule line, a ``时间│标题`` header, a closing rule line, then
    the article body (which may end with a bare URL). F10 stores the full body,
    so ``snippet`` is real prose rather than a truncated headline.
    """
    out: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    in_body = False

    def flush() -> None:
        if current is None or not current.get("title"):
            return
        body = " ".join(current.pop("body", [])).strip()
        url = None
        found = re.search(r"https?://\S+", body)
        if found:
            url = found.group(0)
            body = body.replace(url, "").strip()
        current.update(kind="media", snippet=body[:400] or None, url=url)
        out.append(current)

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "┬" in stripped and not set(stripped) - set("─┬ "):
            flush()
            current, in_body = {"publish_time": None, "title": None, "body": []}, False
            continue
        if current is None:
            continue
        if "┴" in stripped and not set(stripped) - set("─┴ "):
            in_body = True
            continue
        if not in_body:
            if "│" in stripped:
                stamp, _, title = stripped.partition("│")
                current["publish_time"] = stamp.strip() or None
                current["title"] = title.strip() or None
            continue
        current["body"].append(stripped)
        if len(out) >= limit:
            break
    flush()
    return out[:limit]


# ---------------------------------------------------------------------------
# Accessor
# ---------------------------------------------------------------------------


class AshareF10:
    """Accessor for the local ashare F10 text store."""

    def _body(self, code: str, index: int) -> Optional[str]:
        """Full category text, or ``None`` when absent/stale.

        Used directly for categories that carry no ``【N.】`` headings (公司报道
        is one flat article stream); everything else goes through
        :meth:`_sections`.
        """
        parsed = _split_symbol(code)
        if parsed is None:
            raise ValueError(f"ashare f10 is A-share only; got '{code}'")
        code6, _exchange = parsed

        got = read_category(code6, index)
        if got is None:
            return None
        content, updated = got
        if not is_fresh(updated):
            logger.info(
                "ashare f10: %s cat=%s snapshot dated %s is stale (limit %d days), skipping",
                code,
                index,
                updated,
                MAX_AGE_DAYS,
            )
            return None
        return content

    def _sections(self, code: str, index: int) -> Optional[Dict[str, str]]:
        """Parsed sections of one category, or ``None`` when absent/stale."""
        content = self._body(code, index)
        return None if content is None else sections(content)

    def research(self, code: str, *, limit: int = 20) -> Optional[Dict[str, Any]]:
        """Return sell-side ratings, forecast table and per-broker detail rows.

        Args:
            code: A-share symbol, e.g. ``"600685.SH"``.
            limit: Cap on ``details`` rows.

        Returns:
            ``{"snapshot_date", "latest_rating_date", "ratings",
            "forecast", "consensus_eps", "details"}``, or ``None`` when the
            local store has nothing fresh for ``code``.
        """
        blocks = self._sections(code, IDX_RESEARCH)
        if blocks is None:
            return None

        ratings = parse_rating_stats(blocks.get("投资评级统计") or "")
        forecast = parse_forecast_table(blocks.get("盈利预测统计") or "")
        details = parse_forecast_details(blocks.get("盈利预测明细") or "", limit)

        if not ratings["windows"] and not forecast["metrics"] and not details:
            return None
        return {
            "latest_rating_date": ratings["latest_rating_date"],
            "ratings": ratings["windows"],
            "forecast": forecast["metrics"],
            "consensus_eps": forecast["consensus_eps"],
            "details": details,
        }

    def margin(self, code: str, *, days: int = 30) -> Optional[Dict[str, Any]]:
        """Return daily margin-financing balances for ``code``.

        Args:
            code: A-share symbol, e.g. ``"002352.SZ"``.
            days: Most-recent trading-day count cap.

        Returns:
            The :func:`parse_margin` payload, or ``None`` when absent/stale.
        """
        blocks = self._sections(code, IDX_CAPITAL_FLOW)
        if blocks is None:
            return None
        payload = parse_margin(blocks.get("融资融券") or "", days)
        if not payload["rows"]:
            return None
        return payload

    def fund_flow(self, code: str, *, days: int = 30) -> Optional[List[Dict[str, Any]]]:
        """Return daily capital-flow rows for ``code``.

        Args:
            code: A-share symbol, e.g. ``"002352.SZ"``.
            days: Most-recent trading-day count cap.

        Returns:
            :func:`parse_fund_flow` rows, or ``None`` when absent/stale.
        """
        blocks = self._sections(code, IDX_CAPITAL_FLOW)
        if blocks is None:
            return None
        rows = parse_fund_flow(blocks.get("资金流向") or "", days)
        return rows or None

    def news(self, code: str, *, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Return company announcements and press coverage, newest first.

        Announcements come from 公司公告 (``【1.公告列表】``, titles only) and
        coverage from 公司报道 (full article bodies with URLs). The two are
        merged and sorted by ``publish_time`` descending.

        Args:
            code: A-share symbol, e.g. ``"002352.SZ"``.
            limit: Cap on the merged list.

        Returns:
            Rows of ``{publish_time, title, kind, snippet, url}`` where ``kind``
            is ``"announcement"`` or ``"media"``, or ``None`` when both are
            absent/stale.
        """
        parsed = _split_symbol(code)
        if parsed is None:
            raise ValueError(f"ashare f10 is A-share only; got '{code}'")
        code6, _exchange = parsed

        # One scan for both categories: each separate query costs ~1.5 s on a
        # code whose rows sit in a wide row-group range.
        blocks = read_categories(code6, (IDX_ANNOUNCEMENTS, IDX_MEDIA))

        announcements: List[Dict[str, Any]] = []
        got = blocks.get(IDX_ANNOUNCEMENTS)
        if got is not None and is_fresh(got[1]):
            announcements = parse_announcements(
                sections(got[0]).get("公告列表") or "", limit
            )

        media: List[Dict[str, Any]] = []
        got = blocks.get(IDX_MEDIA)
        if got is not None and is_fresh(got[1]):
            media = parse_media(got[0], limit)

        merged = announcements + media
        if not merged:
            return None
        # publish_time is "YYYY-MM-DD HH:MM" for both kinds; None sorts last.
        merged.sort(key=lambda row: row.get("publish_time") or "", reverse=True)
        return merged[:limit]
