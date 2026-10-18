"""ashare-backed A-share financial-statement accessor (local Parquet directory).

Companion to :mod:`backtest.loaders.ashare_loader` (OHLCV). It reads the ashare
``history_finance`` dataset — one Parquet partition per report period, 584
``fNNNN`` columns — so ``get_financial_statements`` can serve A-share balance /
income / cashflow / indicator panels without a network call, falling back to
Eastmoney only when the local directory has nothing.

Column naming: ashare stores hikyuu's ``HistoryFinanceField`` table verbatim, so
the Chinese account names used by the hikyuu precedent (e.g.
``利润表_营业收入``) are recovered through the data directory's own
``_meta/schemas/history_finance.json`` (``desc`` -> ``name``). Nothing is
hard-coded per column beyond the curated whitelist below, which keeps each
period small enough for the tool's character limit. ``f0581``-``f0583`` carry no
name in that schema and are never requested.

Lazy initialization: ``is_available()`` only probes duckdb + the directory, and
the schema file is read on first use, so importing this module never touches
disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from backtest.loaders.ashare_loader import _data_dir, _is_a_share, _split_symbol

logger = logging.getLogger(__name__)

# Hard cap on returned periods, matching the Eastmoney tool's _MAX_PERIODS.
_MAX_PERIODS = 40

_DATASET = "history_finance"
_SCHEMA_FILE = Path("_meta") / "schemas" / "history_finance.json"

# statement -> curated core accounts (Chinese names from hikyuu's
# HistoryFinanceField table). Order = output order.
_STATEMENT_FIELDS: Dict[str, List[str]] = {
    "balance": [
        "资产负债表_货币资金",
        "资产负债表_应收票据",
        "资产负债表_应收账款",
        "资产负债表_预付款项",
        "资产负债表_其他应收款",
        "资产负债表_存货",
        "资产负债表_流动资产合计",
        "资产负债表_固定资产",
        "资产负债表_在建工程",
        "资产负债表_无形资产",
        "资产负债表_商誉",
        "资产负债表_资产总计",
        "资产负债表_应付票据",
        "资产负债表_应付账款",
        "资产负债表_其他应付款",
        "资产负债表_短期借款",
        "资产负债表_长期借款",
        "资产负债表_应付债券",
        "资产负债表_流动负债合计",
        "资产负债表_负债合计",
        "资产负债表_所有者权益（或股东权益）合计",
        "资产负债表_未分配利润",
        "资产负债表_实收资本（或股本）",
    ],
    "income": [
        "利润表_营业收入",
        "利润表_营业成本",
        "利润表_营业税金及附加",
        "利润表_销售费用",
        "利润表_管理费用",
        "利润表_财务费用",
        "利润表_研发费用",
        "利润表_营业利润",
        "利润表_利润总额",
        "利润表_净利润",
        "利润表_归属于母公司所有者的净利润",
        "利润表_稀释每股收益",
    ],
    "cashflow": [
        "现金流量表_销售商品、提供劳务收到的现金",
        "现金流量表_经营活动产生的现金流量净额",
        "现金流量表_投资活动产生的现金流量净额",
        "现金流量表_购建固定资产、无形资产和其他长期资产支付的现金",
        "现金流量表_筹资活动产生的现金流量净额",
        "现金流量表_分配股利、利润或偿付利息支付的现金",
        "现金流量表_现金及现金等价物净增加额",
    ],
    "indicators": [
        "基本每股收益",
        "扣除非经常性损益每股收益",
        "每股未分配利润",
        "每股净资产",
        "每股资本公积金",
        "净资产收益率",
        "每股经营现金流量",
        "盈利能力_销售毛利率",
        "盈利能力_销售净利率",
        "盈利能力_总资产报酬率",
        "盈利能力_扣除非经常性损益后的净利润",
        "成长能力_营业收入增长率",
        "成长能力_净利润增长率",
        "偿债能力_流动比率",
        "偿债能力_速动比率",
        "资本结构_资产负债率",
        "营运能力_总资产周转率",
        "营运能力_存货周转率",
        "现金能力_每股经营性现金流",
    ],
}

_VALID_STATEMENTS = tuple(_STATEMENT_FIELDS)

# Chinese name -> column name, loaded once per process from the schema file.
_field_map_cache: Optional[Dict[str, str]] = None


def is_available() -> bool:
    """True when duckdb imports and the data directory holds history_finance/."""
    try:
        import duckdb  # noqa: F401
    except Exception:  # noqa: BLE001 - any import breakage = unavailable
        return False
    root = _data_dir()
    return (root / _DATASET).is_dir()


def field_map() -> Optional[Dict[str, str]]:
    """Return ``{Chinese account name: column name}`` from the schema file.

    ``None`` when the schema file is missing or unreadable — the caller then
    reports no local data and the tool falls back to Eastmoney.
    """
    global _field_map_cache
    if _field_map_cache is not None:
        return _field_map_cache
    path = _data_dir() / _SCHEMA_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - missing/broken schema -> no mapping
        logger.warning("ashare financial: cannot read %s: %s", path, exc)
        return None
    mapping: Dict[str, str] = {}
    for column in payload.get("columns") or ():
        desc = str(column.get("desc") or "").strip()
        name = str(column.get("name") or "").strip()
        if desc and name:
            mapping[desc] = name
    if not mapping:
        logger.warning("ashare financial: %s lists no named columns", path)
        return None
    _field_map_cache = mapping
    return mapping


def query_history(con: Any, root: Path, code: str, columns: List[str]) -> Optional[pd.DataFrame]:
    """Read and dedup history_finance rows for one code, newest period first.

    Args:
        con: An open duckdb connection.
        root: ashare data directory.
        code: 6-digit ticker (no exchange suffix — the dataset has no exchange
            column).
        columns: Column names (``fNNNN``) to select besides ``report_date``.

    Returns:
        A frame with ``report_date`` plus ``columns``, deduped by
        ``(code, report_date)`` on ``_ingested_at``, or ``None`` when empty.
    """
    selected = ", ".join(["report_date", *columns])
    directory = root / _DATASET
    sql = (
        "WITH src AS ("
        f" SELECT code, {selected}, _ingested_at, filename"
        f" FROM read_parquet({_quote(str(directory / '**' / '*.parquet'))},"
        " hive_partitioning = true, union_by_name = true, filename = true)"
        f" WHERE code = {_quote(code)})"
        f" SELECT {selected} FROM ("
        "   SELECT *, row_number() OVER ("
        "     PARTITION BY code, report_date"
        "     ORDER BY _ingested_at DESC, filename DESC) AS _rn"
        "   FROM src) t"
        " WHERE _rn = 1 ORDER BY report_date DESC"
    )
    frame = con.execute(sql).df()
    if frame.empty:
        return None
    frame["report_date"] = pd.to_datetime(frame["report_date"])
    return frame


def _quote(value: Any) -> str:
    """Quote a value as a SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _cell(value: Any) -> Optional[float]:
    """Coerce a history cell to float; missing and zero both read as ``None``.

    ashare's gpcw source leaves unreported accounts at zero, so a zero is an
    absence rather than a measured value — the same reading the hikyuu
    precedent applies.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number) or number == 0.0:
        return None
    return number


class AshareFinancial:
    """Accessor for the local ashare financial-statement panel."""

    def fetch(
        self,
        code: str,
        *,
        statement: str = "indicators",
        period: str = "annual",
        max_periods: int = _MAX_PERIODS,
    ) -> Optional[List[dict]]:
        """Return per-report-period financial rows for an A-share symbol.

        Args:
            code: A-share symbol, e.g. ``"600519.SH"``.
            statement: ``balance`` / ``income`` / ``cashflow`` / ``indicators``.
            period: ``annual`` (December year-end rows only) or ``quarter``.
            max_periods: Most-recent period count cap.

        Returns:
            ``list[dict]`` newest-first, each with ``REPORT_DATE`` plus Chinese
            account names, or ``None`` when the local directory has no data for
            ``code`` (so the caller falls back to Eastmoney).

        Raises:
            ValueError: If ``code`` is not A-share or ``statement`` is invalid.
        """
        if statement not in _STATEMENT_FIELDS:
            raise ValueError(
                f"ashare financial: unsupported statement {statement!r}; choose from {list(_VALID_STATEMENTS)}"
            )
        if not _is_a_share(code):
            raise ValueError(f"ashare financial is A-share only; got '{code}'")
        parsed = _split_symbol(code)
        if parsed is None:
            raise ValueError(f"could not resolve A-share symbol '{code}'")
        symbol, _exchange = parsed

        root = _data_dir()
        if not (root / _DATASET).is_dir():
            return None
        mapping = field_map()
        if mapping is None:
            return None
        wanted = [(desc, mapping[desc]) for desc in _STATEMENT_FIELDS[statement] if desc in mapping]
        if not wanted:
            return None

        try:
            import duckdb
        except Exception as exc:  # noqa: BLE001
            logger.warning("ashare financial: duckdb unavailable: %s", exc)
            return None

        con = duckdb.connect()
        try:
            frame = query_history(con, root, symbol, [column for _, column in wanted])
        except Exception as exc:  # noqa: BLE001 - missing column/partition -> fall back
            logger.warning("ashare financial query failed for %s: %s", code, exc)
            return None
        finally:
            con.close()

        if frame is None or frame.empty:
            logger.info(
                "ashare financial: %s has no %s rows in the local directory (will fall back)",
                code,
                statement,
            )
            return None

        rows: List[dict] = []
        for record in frame.to_dict("records"):
            report_date = pd.Timestamp(record["report_date"]).strftime("%Y-%m-%d")
            if period == "annual" and not report_date.endswith("-12-31"):
                continue
            row: dict = {"REPORT_DATE": report_date}
            for desc, column in wanted:
                row[desc] = _cell(record.get(column))
            rows.append(row)

        if not rows:
            return None
        logger.info(
            "ashare financial: %s statement=%s period=%s -> %d report period(s)",
            code,
            statement,
            period,
            min(len(rows), max_periods),
        )
        return rows[:max_periods]
