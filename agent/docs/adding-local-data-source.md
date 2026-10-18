# 添加本地数据源（以 Hikyuu 为范例）的修改范围

结论：添加一个本地数据源 = 1 个 loader 模块 + 注册中心 3 处 + 符号默认路由 1 处 + 工具/文档描述 4 处 + 测试。本地源一律 lazy import、失败即静默降级，绝不阻塞回退链。

## 1. Loader 模块本体 `agent/backtest/loaders/<name>_loader.py`

- `@register` 装饰的 `DataLoader` 类，类属性：`name`、`markets`（如 `{"a_share"}`）、`requires_auth = False`。
- `is_available()` 只探测依赖可导入（如 `import hikyuu`），重初始化推迟到首次 `fetch()`；不可用返回 `False`，registry 继续走链。
- `fetch(codes, start_date, end_date, *, interval, fields)`：
  - 先 `validate_date_range`；
  - 用 `cached_loader_fetch(source=..., symbol=..., timeframe=..., ...)` 包住单标的取数，拿到缓存；
  - 输出契约：`trade_date` 索引 + `open/high/low/close/volume`，`pd.to_numeric` 后 `dropna` + `sort_index`。
- 不支持的 interval 直接 warning + 返回 `{}`，不静默降级为日线。
- 单标的失败只 warning，不影响同批其它标的。

## 2. 注册中心 `agent/backtest/loaders/registry.py`

- `VALID_SOURCES` 集合加新源名。
- `_ensure_registered()` 的 `_loader_modules` 列表加模块路径。
- `FALLBACK_CHAINS` 中目标市场的链插入新源（hikyuu 插在 `a_share` 链首，注释说明"本地/离线/无封禁风险，缺失时自然降级"）。
- 同步更新 `agent/tests/test_registry.py` 的链顺序断言。
- 价格口径表 `PRICE_CALIBER_BY_SOURCE`：实测复权行为后才填；未实测保持缺省 `"unknown"`（hikyuu 即为 unknown，未补）。

## 3. 符号 → 默认源路由 `agent/src/market_data.py`

- `_SOURCE_PATTERNS` 的正则条目指向新源（A 股 `^\d{6}\.(SZ|SH|BJ)$` 从 tencent 改指 hikyuu）。

## 4. 工具与入口描述

- `agent/src/tools/market_data_tool.py`：`_SOURCE_ENUM` 加名 + description 文案提及。
- `agent/mcp_server.py`：`get_market_data` docstring 源列表加一行。

## 5. 技能文档 `agent/src/skills/data-routing/SKILL.md`

- 源表格加一行（覆盖市场 / 是否需 key / 网络要求）；
- "Source priority" 小节更新对应市场的排序描述。

## 6. 非 OHLCV 数据（财务、股东户数等）的接入方式

- 新建 companion 访问器模块（如 `hikyuu_financial.py`、`hikyuu_shareholder.py`），复用 loader 的符号解析私有函数（`_is_a_share` / `_split_symbol`）；同样 lazy init + `is_available()`。
- 在对应 tool（`financial_statements_tool.py`、`shareholder_count_tool.py`）内加 `_fetch_<name>_*` 私有函数：优先调本地源，无数据/异常回退原网络源；返回信封的 `source` 字段标注实际来源。
- 访问器模块内 lazy import，保证依赖缺失时工具仍可导入。
- 更新工具 description，说明新源的行为与字段范围（如 Hikyuu 仅返回精选核心科目）。

## 7. 测试

- 每个新模块一个 `agent/tests/test_<name>.py`：用 `sys.modules` 注入假模块，不依赖真实本地数据目录；覆盖符号解析、frame 契约、lazy init、降级路径。
- 更新受影响工具的既有测试（默认源断言、回退断言）。

## 8. 依赖管理

- 本地源按可选依赖处理：不在 base 依赖里安装；如需安装入口，在 `pyproject.toml` 的 `[project.optional-dependencies]` 加 extra（hikyuu 未加 extra，靠用户环境自带，未装即自动走回退链）。

## 已识别缺口（下一源可顺手补齐）

- `volume_units` 未声明（A 股应为 `lots`，参照 tencent loader）。
- `PRICE_CALIBER_BY_SOURCE` 未实测填写。
- README / CHANGELOG 未更新。
