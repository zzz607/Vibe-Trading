# 添加本地数据源：ashare（A 股 Parquet 数据目录）

结论：新增 `ashare` 本地源 = 1 个 loader（内含查询时前复权）+ 2 个 companion + 注册中心 4 处 + 配置 1 处 + 符号路由 1 处 + 工具/文档描述 4 处 + 测试。读取引擎用 duckdb（已是硬依赖），不引入 pyarrow。本地源一律 lazy import、失败即静默降级，绝不阻塞回退链。

基线分支：`main`。`feature/hikyuu-source` 上的 hikyuu 实现未合入 main，本文仅作先例引用。

## 0. 一期范围

| 接入 | 不接入（原因） |
|---|---|
| `kline_day` ∪ `index_day` 日线 OHLCV，**查询时前复权** | ETF/基金行情：ashare prd §5 排除基金行情 ⇒ 自然降级 tencent |
| `xdxr` 权息事件 → 前复权因子 | 分钟/小时线：ashare 一期仅日线 ⇒ 自然降级 eastmoney/tushare |
| `history_finance` → 财务报表 companion | `finance` 快照（35 字段）：eastmoney 三表字段更全，作回退即可 |
| `history_finance` → 股东户数 companion | 停牌/交易日历/codelist/f10/equity/板块/资金流向/封单：无消费方或现源更强（见 §9） |

数据目录：`DataConfig.vibe_ashare_data_dir`（env `VIBE_ASHARE_DATA_DIR`），缺省 `~/.vibe-trading/ashare/data`；定位模式同 `src/br_data/store.py` 的 `vibe_br_data_db`（config 优先 + 默认路径）。不读 ashare 项目的 `config.yaml`。

## 1. Loader `agent/backtest/loaders/ashare_loader.py`

- `@register`，类属性：`name="ashare"`、`markets={"a_share"}`、`requires_auth=False`、`volume_units={"a_share": "lots"}`（ashare prd §4.5：volume 单位为手）。
- `is_available()`：数据目录下存在任一 bar 数据集（`kline_day/` 或 `index_day/`）；duckdb lazy import 失败同样返回 False。不探测网络、不读数据内容。
- `fetch(codes, start_date, end_date, *, interval, fields)`：
  - 先 `validate_date_range`；interval 仅接受日线别名（`1d`/`d`/`day`/`daily`/`1D`），其余 warning + 返回 `{}`，不静默降级为日线；
  - 符号 `600037.SH` → `(code="600037", exchange="SH")`（末段拆分、大写）；
  - 单标的走 duckdb 内存只读连接，`kline_day` 与 `index_day` 两表 UNION，同一 `(code, date)` 两表并存时取 `kline_day`（不依赖两表 code 空间不交叠的假设）：

    ```sql
    SELECT date, open, high, low, close, volume
    FROM read_parquet(['<dir>/kline_day/**/*.parquet',
                       '<dir>/index_day/**/*.parquet'],
                      hive_partitioning=true, union_by_name=true, filename=true)
    WHERE code = ? AND exchange = ? AND date BETWEEN ? AND ?
    QUALIFY row_number() OVER (
        PARTITION BY code, date ORDER BY _ingested_at DESC, filename DESC) = 1
    ```

    去重语义与 ashare `data/_views.sql` 逐字一致，不依赖该文件存在；空数据集目录（已建未 compact）跳过，不参与 glob；ETF 等两表皆无的标的不进 result，交由回退链；
  - interval 不支持返回 `{}` 后，`market_data.py` 的逐符号链上回退（`_fetch_via_chain`，空结果不占位、继续走下一个源）会把分钟线请求落到 eastmoney/tushare；
  - 输出契约：`trade_date` 索引 + `open/high/low/close/volume`，`pd.to_numeric` 后 `dropna` + `sort_index` + `validate_ohlc`；
  - 缓存只有调权后一条（`cached_loader_fetch(fields=None)`）；raw bars 与 xdxr 每次现读——窗口末锚定使调权结果是窗口内容的纯函数，传 `source_revision` 需额外全分区扫描而无收益，故不传；
  - 单标的失败只 warning，不影响同批其它标的；
  - 对外只返回前复权日线（复权在模块内完成，见 §2），不存在 raw 对外路径。

## 2. 复权（实现在 loader 内，不单独成文件）

ashare 只落不复权价 + 权息事件（prd §4.5/§4.7），复权在 `ashare_loader.py` 内于查询时算完再返回——与 hikyuu_loader 调 `Query.FORWARD` 同形，调用方只拿到前复权日线。实现为模块内私有纯函数 `_apply_forward_adjustment(bars, events)`，单测直接 import 调用。

- 事件字段：`fenhong`（元/10股）、`peigujia`（配股价，元）、`songzhuangu`（股/10股）、`peigu`（股/10股）；
- 每个除权日 e：`prev_close` = e 之前最后一根 raw close（窗口内），理论除权价
  `theo = (prev_close − fenhong/10 + peigujia × peigu/10) / (1 + songzhuangu/10 + peigu/10)`，
  `factor(e) = theo / prev_close`；
- bar 缩放比 `ratio(t) = ∏ factor(e)`，e 取窗口内 `t < e ≤ 窗口末` 的全部事件——**窗口末锚定**，与 `cn_adjust.apply_qfq`、`additive_conversion` 同一约定（绝对水平随请求窗口而变、收益不变；全历史窗口下等于 hikyuu `Query.FORWARD` 的数据集最新锚定）；
- OHLC × ratio，**volume ÷ ratio**（同 `cn_adjust`，保 VWAP 口径）；loader 不返回 amount；
- 跳过规则（只 warning，不产出坏价）：`theo ≤ 0` 或非有限；该事件前窗口内无 bar；`factor == 1` 静默跳过；
- 无事件的个股与全部指数（`index_day` 无 xdxr）原样返回；A 股指数经 `price_caliber` 的 `_A_SHARE_INDEX_CODE` 自动得 `raw`，无需单独登记；
- 调权后 frame `attrs["adjustment"] = "split_dividend"`（乘法口径）。

口径登记 `PRICE_CALIBER_BY_SOURCE["ashare"] = "split_dividend"`，**已实测**：与 baostock `adjustflag=2` 前复权逐 bar 比对（600519.SH 673 根、300750.SZ 1887 根、000001.SZ 1887 根，2019-01→2026-10-16），最大相对差 0.072%、尾部比值 1.000000（锚点一致）、事件处无结构性断点。

## 3. 注册中心 `agent/backtest/loaders/registry.py`

- `VALID_SOURCES` 加 `"ashare"`（`test_covers_all_registered_loaders` 强制全覆盖）；
- `_loader_modules` 加 `"backtest.loaders.ashare_loader"`（companion 由工具直接导入，不注册）；
- `FALLBACK_CHAINS["a_share"]` 插链首：`["ashare", "tencent", "eastmoney", "baostock", "akshare", "tushare", "gildata", "local"]`，注释「本地/离线/无封禁风险；数据目录缺失即自然降级」；
- 同步 `tests/test_registry.py::test_chains_ordered_by_ip_ban_risk` 的 a_share 字面量；
- **不进** `_NO_NETWORK_FALLBACK_SOURCES`：显式请求不可用时沿链降级（自动链首，非 local/tickerall 式显式专属源）；
- `agent/src/config/env_schema.py` 的 `DataConfig` 加 `vibe_ashare_data_dir`（`VIBE_ASHARE_DATA_DIR`），loader 经 `get_env_config()` 读，不裸 `os.getenv`。

## 4. 符号 → 默认源路由 `agent/src/market_data.py`

- `_SOURCE_PATTERNS` 的 `^\d{6}\.(SZ|SH|BJ)$` 从 `tencent` 改指 `ashare`；A 股指数（`000300.SH`/`399xxx.SZ`/`899xxx.BJ`）同命中该正则且 `_detect_market` 归 `a_share`，随链首走 ashare（`index_day` 供给）。

## 5. 工具与入口描述

- `agent/src/tools/market_data_tool.py`：source description 加一行——ashare = 本地数据目录（`VIBE_ASHARE_DATA_DIR`），个股/指数日线、前复权、无 key；
- `agent/mcp_server.py`：`get_market_data` docstring 源列表加一行；
- `agent/src/skills/data-routing/SKILL.md`：Source Overview 加一行（ashare | A-shares stocks+indices, daily, qfq | No | Offline | data-routing）；A-shares priority 行 ashare 居首；注明新鲜度 = ashare 调度最新完成日（通常 T-1 收盘后），盘中请求得 T-1。SKILL.md 源名须为 `VALID_SOURCES` 子集（`test_data_routing_sources_subset.py` 强制）；
- 根 `CHANGELOG.md` 加一条（补 hikyuu 先例未更新的缺口）。

## 6. 财务 companion（D2-a）

`agent/backtest/loaders/ashare_financial.py` + `ashare_shareholder.py`，模式照搬 hikyuu 先例（`feature/hikyuu-source` 分支，未合入 main：财务访问器 `8a770270`、股东户数 `b3a07e04`、字段白名单定稿 `b4495d73`）：

- 数据源 `history_finance`（分区 `report=YYYYMMDD`，584 列 `f0000…f0583`；命名映射仅覆盖 `f0000…f0580`，`f0581–f0583` 未定名），f 索引 → 中文科目名映射运行时读数据目录内 `_meta/schemas/history_finance.json`（随数据交付）；
- 字段白名单平移 hikyuu 先例的三表核心科目 + `股本股东_股东人数`/`股本股东_已上市流通A股`/`股本股东_总股本`；按报告期对齐，`≤40` 期（财务）/`≤24` 期（股东户数）；
- `financial_statements_tool.py` / `shareholder_count_tool.py` 的 a_share 分支：ashare 优先 → 无数据/异常回退 eastmoney，信封 `source` 标注实际来源（照现有 br 分支 cvm→yahoo 模式）；
- companion 内 lazy import + `is_available()`（探 duckdb 可导入且数据目录含 `history_finance/`），依赖缺失时工具仍可导入；
- 工具 description 注明：ashare 侧为精选核心科目（非 eastmoney 全字段三表），股东户数为报告期粒度。

## 7. 测试

- `tests/test_ashare_loader.py`：tmpdir 内 duckdb 写小型 hive 分区 parquet，覆盖符号解析、两表 union 与 kline_day 优先、去重（重复 `(code,date)` 行）、日期过滤、目录缺失 `is_available()=False`、非日线 interval 返回 `{}`、单标的失败不影响同批、`source_revision` 缓存键；复权部分用合成事件覆盖——纯分红（10派5）、10送10、10配3 含配股价、分红+送转组合、事件落窗口首/末、事件前无 bar、`theo≤0` 跳过、volume 缩放、窗口末锚定语义（直接 import `_apply_forward_adjustment` 调用）；
- `tests/test_ashare_financial.py` / `tests/test_ashare_shareholder.py`：假 parquet + 假 schema json，覆盖字段映射、期数上限、回退路径；
- 需同步的既有断言（按 main 基线已核实）：`tests/test_registry.py::test_chains_ordered_by_ip_ban_risk` 的 a_share 字面量；`tests/test_market_data.py` 的 `detect_source` 参数化（`600519.SH`/`000001.SZ`/`430139.BJ` 当前期望 `tencent`）；`tests/test_settings_api.py` 的 `a_share["default_order"][0] == "tencent"`；实现时再 grep 兜底。

## 8. 依赖

零新增：duckdb 已是硬依赖（`agent/requirements.txt`），hive 分区 parquet 读取、去重、复权输入全部走 duckdb；不引入 pyarrow，不加 optional extra。注意 `pyproject.toml` 已有同名 optional extra `ashare`（= baostock）：本源不碰 extra，无功能冲突，仅命名相近，错误信息与文档中避免混用。用户侧只需准备 ashare 数据目录并设 `VIBE_ASHARE_DATA_DIR`（或用缺省路径）。

## 9. 明确排除（留档）

| 排除 | 原因 |
|---|---|
| ETF/LOF/REITs 行情 | ashare prd §5 排除基金行情；自然降级 tencent |
| 分钟/小时线 | ashare 一期仅日线；自然降级 eastmoney/tushare |
| `finance` 快照 | eastmoney 三表字段更全 |
| `suspend` 停牌 | 引擎 bounded ffill 是已接受的设计，无主动消费方 |
| `trade_calendar` | 回测从 bars 并集推导，够用 |
| `codelist`/退市 | symbol_search + market_screener 实时源够用 |
| `f10`/`equity`/`volume_profile`/`capital_flow`/`block`/`industry` | 无消费方，或现源更强（资金流向全历史 vs ashare 仅 5 日；申万 PIT vs 当前快照） |

数据已在 ashare 落库，未来要做（显式停牌、退市校验、A 股 F10 profile 等）随时可接，不影响本契约。

## 10. 开发约定

- **新代码只进新文件**：loader / companion / 测试全部新建；既有文件只做最小局部改动，避免从上游更新时冲突。
- **既有文件的改动点（实际落地清单）**：`registry.py` 4 处、`market_data.py` `_SOURCE_PATTERNS` 1 行、`env_schema.py` 1 个字段、`loader_health.py` 1 条本地源排除、`metrics.py` 年化映射 8 行、两个工具各 1 个本地优先分支、`market_data_tool.py` / `mcp_server.py` / `data-routing/SKILL.md` 描述、7 个 README + `agent/SKILL.md` 计数与链序（由 `test_readme_counts.py` / `test_distribution_skill_manifest.py` 强制，属必改项）、`test_loader_contract.py` 注册新套件、4 处既有测试断言。除此之外不动。
- **开发分支**：自 `main` 切 `feature/ashare-source`；不在 `main` 或 `feature/hikyuu-source` 上直接开发。
