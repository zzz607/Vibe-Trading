# 投研团队（Swarm Presets）

多 agent 投研团队预设，定义在 `agent/src/swarm/presets/*.yaml`。每个团队由若干角色 agent
组成，按 DAG 并行分工、最后由策略 / 编辑角色汇总结论。

## 用法

```bash
# 交互模式
/swarm                                  # 列出全部团队
/swarm run equity_research_team '{"market":"A股","goal":"挖掘高景气赛道"}'
/swarm inspect equity_research_team     # 查看 DAG 与变量校验
/swarm show <run_id> / cancel <run_id> / retry <run_id> [--resume]

# 非交互模式
vibe-trading --swarm-run equity_research_team '{"market":"A股","goal":"..."}'
```

各预设的必填变量见 `/swarm inspect <preset>`。

## 团队清单

| 预设名 | 团队名 | Agent | 职责 | 匹配关键词（权重） | 可用技能 |
| --- | --- | --- | --- | --- | --- |
| `commodity_research_team` | 商品研究团队 | 3 | 供需两端并行深挖，由周期策略师汇总为投资论点 | **0.9**：commodity、crude、gold、copper、iron\s+ore、商品、原油、黄金、铜、铁矿石、白银、天然气 | commodity-analysis、geopolitical-risk、global-macro、seasonal、strategy-generate、web-reader |
| `convertible_bond_team` | 可转债研究团队 | 4 | 纯债底、正股期权性与内嵌期权价值三维并行分析，合成可转债投资策略 | **0.9**：convertible、可转债、\bCB\b | convertible-bond、credit-analysis、fundamental-filter、options-payoff、options-strategy、strategy-generate、technical-basic、valuation-model、volatility |
| `credit_research_team` | 固收信用研究团队 | 4 | 信用质量 + 利率环境 + 行业信用三维并行分析，由固收策略师合成完整债券投资策略 | **0.9**：credit\s+bond、LGFV、\bYTM\b、利差、信用债、城投 | credit-analysis、financial-statement、macro-analysis、regulatory-knowledge、risk-analysis、sector-rotation、strategy-generate |
| `crypto_research_lab` | 加密资产研究实验室 | 4 | 链上数据 + DeFi 协议 + 市场情绪三维并行分析，由 Alpha 合成师收敛投资建议 | **0.95**：\bBTC\b、\bETH\b、\bSOL\b、\b(?:XRP \| BNB \| ADA \| DOGE \| AVAX \| DOT \| LINK \| TON \| LTC \| MATIC)\b、crypto、bitcoin、加密、数字货币 | asset-allocation、crypto-derivatives、defi-yield、liquidation-heatmap、okx-market、onchain-analysis、perp-funding-basis、risk-analysis、sentiment-analysis、stablecoin-flow、token-unlock-treasury、web-reader |
| `crypto_trading_desk` | 加密交易与风控台 | 4 | 执行导向：资金费率/基差、清算/微观结构、链上与稳定币资金流三路并行加风控经理把关；不止于研究，延伸到仓位规模、执行时机与风险闸门 | 无关键词，需显式点名 | asset-allocation、crypto-derivatives、defi-yield、execution-model、hedging-strategy、liquidation-heatmap、market-microstructure、okx-market、onchain-analysis、perp-funding-basis、risk-analysis、stablecoin-flow、token-unlock-treasury、volatility |
| `derivatives_strategy_desk` | 衍生品策略台 | 3 | 波动率分析 → 策略设计 → Greeks 风控，串行期权交易台 | **0.9**：\boptions?\b、\bcall\s+options?\b、\bput\s+options?\b、\bGreeks?\b、implied\s+vol、\bIV\b、期权、衍生品 | hedging-strategy、options-advanced、options-payoff、options-strategy、risk-analysis、volatility |
| `earnings_research_desk` | 财报研究台 | 4 | 基本面与公告、盈利修正追踪、财报事件与期权三路并行加财报策略师；深挖公司财务、一致预期修正、财报事件交易与盈余公告后漂移 | 无关键词，需显式点名 | earnings-forecast、earnings-revision、edgar-sec-filings、event-driven、financial-statement、fundamental-filter、options-advanced、options-strategy、report-generate、risk-analysis、strategy-generate、valuation-model、volatility、yfinance |
| `equity_research_team` | 股票研究团队 | 4 | 宏观 → 行业 → 个股三级递进深研，由研报编辑汇总成完整报告 | **0.85**：equity research、stock research、研报、研究报告、行业分析、个股分析、投资分析、macro.*sector、投资机会 | earnings-revision、fundamental-filter、global-macro、multi-factor、okx-market、report-generate、sector-rotation、strategy-generate、technical-basic、tushare、us-etf-flow、web-reader、yfinance |
| `etf_allocation_desk` | ETF 配置台 | 4 | ETF 筛选 + 宏观配置 + 风险预算三维并行，由组合优化器构建最终 ETF 组合并回测 | **0.9**：\bETF\b、index\s+fund、指数基金、ETF配置 | asset-allocation、etf-analysis、fund-analysis、global-macro、macro-analysis、risk-analysis、strategy-generate、tushare、volatility |
| `event_driven_task_force` | 事件驱动特遣队 | 3 | 事件扫描 → 深度影响分析 → 策略构建，复刻事件驱动对冲基金专项调查组的串行深挖链 | **0.9**：M&A、merger、insider、earnings\s+surprise、事件驱动、并购、财报 | corporate-events、event-driven、geopolitical-risk、sentiment-analysis、strategy-generate、valuation-model、web-reader |
| `factor_research_committee` | 因子研究委员会 | 4 | 因子挖掘与因子验证并行 → 因子组合构建 → 回测评审，量化基金内部研究评审流 | **0.9**：factor\s+research、\bIC\b、ICIR、因子委员会、因子研究 | backtest-diagnose、factor-research、multi-factor、quant-statistics、strategy-generate |
| `fund_selection_panel` | 基金筛选委员会 | 3 | 多维量化筛选 → Brinson 业绩归因与风格分析 → FOF 组合权重优化，串行专业评审链 | **0.85**：\bFOF\b、mutual\s+fund、基金筛选、选基 | asset-allocation、etf-analysis、fund-analysis、fundamental-filter、multi-factor、performance-attribution、risk-analysis、strategy-generate |
| `fundamental_research_team` | 基本面深度研究团队 | 4 | 财务 / 估值 / 质量三维并行分析，由研报编辑汇总成买方深度研报 | **0.85**：fundamental、deep\s+dive、财务、基本面 | earnings-forecast、financial-statement、fundamental-filter、report-generate、valuation-model、web-reader |
| `geopolitical_war_room` | 地缘风险作战室 | 4 | 地缘分析、能源冲击与供应链影响并行，汇入首席策略师合成，产出地缘危机下的应急资产配置预案 | **0.9**：geopolitical、war\s+risk、sanction、地缘、危机场景 | asset-allocation、commodity-analysis、event-driven、geopolitical-risk、global-macro、hedging-strategy、risk-analysis、sector-rotation、web-reader |
| `global_allocation_committee` | 全球配置委员会 | 4 | A 股 + 加密 + 港美股分析师并行；配置策略师以数据驱动加权、情景分析与再平衡规则合成跨市场配置 | **1.0**：cross[- ]?market、global\s+alloc、multi[- ]asset、三市场、全球配置、资产配置、港美.*A股、A股.*加密、加密.*A股、多市场 | adr-hshare、asset-allocation、correlation-analysis、crypto-derivatives、earnings-revision、fundamental-filter、hk-connect-flow、multi-factor、okx-market、onchain-analysis、perp-funding-basis、risk-analysis、sector-rotation、stablecoin-flow、strategy-generate、technical-basic、tushare、us-etf-flow、volatility、yfinance |
| `global_equities_desk` | 全球股票研究台 | 4 | 跨市场股票研究：A 股、港美股、加密分析师加全球策略师；覆盖基本面筛选、盈利分析、ETF 资金流与跨市场上市套利 | 无关键词，需显式点名 | adr-hshare、asset-allocation、correlation-analysis、crypto-derivatives、earnings-revision、edgar-sec-filings、fundamental-filter、hk-connect-flow、multi-factor、okx-market、onchain-analysis、perp-funding-basis、risk-analysis、sector-rotation、stablecoin-flow、strategy-generate、technical-basic、tushare、us-etf-flow、yfinance |
| `investment_committee` | 投资委员会 | 4 | 多空辩论 → 风控评审 → 基金经理最终拍板，买方基金投委会工作流 | **0.85**：investment\s+committee、投委会、投资决策 | asset-allocation、correlation-analysis、earnings-revision、fundamental-filter、risk-analysis、sentiment-analysis、strategy-generate、technical-basic、volatility、yfinance |
| `macro_rates_fx_desk` | 宏观 / 利率 / 汇率台 | 4 | 跨资产宏观台：全球利率与收益率曲线、汇率策略、商品与通胀三路并行加宏观组合经理；覆盖央行政策、收益率曲线动态、货币头寸与宏观驱动配置 | 无关键词，需显式点名 | asset-allocation、commodity-analysis、credit-analysis、global-macro、hedging-strategy、macro-analysis、risk-analysis、seasonal、strategy-generate、yfinance |
| `macro_strategy_forum` | 宏观策略论坛 | 4 | 全球 + 国内 + 政策三视角并行；首席策略师给出整合后的跨资产配置指引 | **0.9**：\bFed\b、\bCPI\b、\bPMI\b、macro、货币政策、宏观 | asset-allocation、geopolitical-risk、global-macro、macro-analysis、regulatory-knowledge、sector-rotation、tushare、web-reader |
| `ml_quant_lab` | 机器学习量化实验室 | 3 | 特征工程与模型设计并行；流入回测工程师做严格样本外验证 | **0.9**：\bML\b、machine\s+learning、LSTM、XGBoost、机器学习、深度学习 | backtest-diagnose、factor-research、ml-strategy、multi-factor、quant-statistics、strategy-generate |
| `pairs_research_lab` | 配对交易研究实验室 | 4 | 相关性扫描与协整检验并行 → 配对策略师设计策略 → 微观结构评审执行可行性 | **0.9**：pairs\s+trading、cointegration、配对、统计套利 | correlation-analysis、execution-model、market-microstructure、multi-factor、pair-trading、quant-statistics、strategy-generate |
| `portfolio_review_board` | 组合评审委员会 | 4 | 业绩归因、风险评审与执行质量并行；CIO 汇总为再平衡决策 | **0.85**：portfolio\s+review、组合复盘、业绩归因 | asset-allocation、execution-model、market-microstructure、multi-factor、performance-attribution、risk-analysis、volatility |
| `quant_strategy_desk` | 量化策略台 | 5 | 选股与因子研究并行 → 策略回测 → 风险审计 → 最终报告 | **1.0**：\bquant\b、alpha、factor、backtest、多因子、量化策略、因子、选股、策略.*回测 | factor-research、fundamental-filter、multi-factor、report-generate、strategy-generate、technical-basic、tushare、volatility |
| `risk_committee` | 风险委员会 | 4 | 回撤、尾部风险与市场状态评审并行；由风险总监签核 | **1.0**：risk\s+audit、drawdown、tail\s+risk、stress\s+test、\bVaR\b、风控、风险审计、回撤、尾部风险、压力测试、风险评估 | technical-basic、volatility |
| `sector_rotation_team` | 行业轮动研究团队 | 4 | 经济周期 + 行业景气度 + 资金流并行 → 轮动策略师构建并回测行业轮动策略 | **0.85**：sector\s+rotation、板块轮动、行业轮动 | fundamental-filter、macro-analysis、multi-factor、seasonal、sector-rotation、sentiment-analysis、strategy-generate、tushare |
| `sentiment_intelligence_team` | 市场情绪情报组 | 4 | 新闻情报 / 社交情绪 / 资金流并行 → 情绪信号合成师输出综合评分与反转信号 | **0.85**：sentiment、fear\s+and\s+greed、情绪、恐慌 | behavioral-finance、risk-analysis、sentiment-analysis、social-media-intelligence、tushare、web-reader |
| `social_alpha_team` | 社交媒体另类数据团队 | 4 | Twitter、Telegram 与 Reddit 并行分析 → Alpha 合成师提取可交易的社交情绪因子 | **0.85**：social\s+media、twitter、reddit、社媒、舆情 | behavioral-finance、factor-research、onchain-analysis、quant-statistics、sentiment-analysis、social-media-intelligence |
| `statistical_arbitrage_desk` | 统计套利台 | 4 | 配对扫描与微观结构分析并行 → 套利策略师构建策略 → 最终风控复核 | **0.9**：statistical\s+arbitrage、stat\s+arb、统计套利 | correlation-analysis、execution-model、market-microstructure、pair-trading、quant-statistics、risk-analysis、strategy-generate、volatility |
| `technical_analysis_panel` | 技术分析委员会 | 6 | 经典技术、一目均衡表、谐波、艾略特波浪、SMC/订单流并行 → 信号聚合师评分一致性与共振 | **0.85**：technical\s+analysis、\bRSI\b、\bMACD\b、技术分析、K线 | candlestick、chanlun、elliott-wave、harmonic、ichimoku、minute-analysis、smc、technical-basic |
| `value_investing_committee` | 价值投资委员会（巴菲特 / 芒格 / 段永平 / 李路） | 5 | 四个对抗性大师视角对同一公司并行推演，再由主席把共识与矛盾合成结论；每个视角都是对公开方法论的复刻，不代表本人。用于单一具名公司的深度价值投资审议 | **0.9**：value\s+investing、价值投资、\bbuffett\b、巴菲特、\bmunger\b、芒格、段永平、李录、四大师、four\s+master | bottleneck-hunter、financial-statement、fundamental-filter、global-macro、management-deep-dive、report-generate、risk-analysis、thesis-tracker、valuation-model |

共 30 个预设。

「可用技能」= 该团队全部 agent 的 `agents[].skills` 白名单与 system_prompt 中
`load_skill(...)` 引用的并集。白名单是运行时硬边界：未列出的技能该团队加载不了
（`src/tools/__init__.py` 的 `skill_allowlist` 会重建 `load_skill` 并拒绝名单外的名字）。
单 agent 模式（普通对话）不受此限，可用全部 90 个技能，见 [skills.md](skills.md)。

## 团队工作流

由各 preset 的 `tasks[].depends_on` 推导；`[a | b]` 表示并行。

- **commodity_research_team**（商品研究团队）
  [供给分析师 | 需求分析师] → 周期策略师
- **convertible_bond_team**（可转债研究团队）
  [纯债底分析师 | 正股分析师 | 内嵌期权分析师] → 可转债策略师
- **credit_research_team**（固收信用研究团队）
  [信用分析师 | 利率分析师 | 行业信用分析师] → 固收策略师
- **crypto_research_lab**（加密资产研究实验室）
  [链上数据分析师 | DeFi 协议分析师 | 加密情绪分析师] → Alpha 合成师
- **crypto_trading_desk**（加密交易与风控台）
  [资金费率与基差分析师 | 清算与微观结构分析师 | 链上与稳定币资金流分析师] → 交易台风控经理
- **derivatives_strategy_desk**（衍生品策略台）
  波动率分析师 → 策略设计师 → Greeks 风控经理
- **earnings_research_desk**（财报研究台）
  [基本面与公告分析师 | 盈利修正与一致预期追踪 | 财报事件与期权分析师] → 财报台策略师
- **equity_research_team**（股票研究团队）
  宏观分析师 → 行业分析师 → 个股分析师 → 研报编辑
- **etf_allocation_desk**（ETF 配置台）
  [ETF 筛选 | 宏观配置师 | 风险预算师] → 组合优化器
- **event_driven_task_force**（事件驱动特遣队）
  事件侦察 → 影响分析师 → 策略构建师
- **factor_research_committee**（因子研究委员会）
  [因子挖掘 | 因子验证] → 因子合成 → 回测评审
- **fund_selection_panel**（基金筛选委员会）
  基金筛选 → 业绩归因分析师 → FOF 组合优化师
- **fundamental_research_team**（基本面深度研究团队）
  [财务分析师 | 估值分析师 | 质量分析师] → 研报编辑
- **geopolitical_war_room**（地缘风险作战室）
  [地缘分析师 | 能源冲击分析师 | 供应链分析师] → 首席策略师
- **global_allocation_committee**（全球配置委员会）
  [A 股分析师 | 加密分析师 | 港股/美股分析师] → 配置策略师
- **global_equities_desk**（全球股票研究台）
  [A 股研究员 | 港美股研究员 | 加密资产研究员] → 全球股票策略师
- **investment_committee**（投资委员会）
  [多方研究员 | 空方研究员] → 首席风险官 → 基金经理
- **macro_rates_fx_desk**（宏观 / 利率 / 汇率台）
  [全球利率与收益率曲线分析师 | 汇率策略师 | 商品与通胀分析师] → 宏观组合经理
- **macro_strategy_forum**（宏观策略论坛）
  [全球经济学家 | 中国经济学家 | 政策分析师] → 首席策略师
- **ml_quant_lab**（机器学习量化实验室）
  [特征工程师 | 数据科学家] → 回测工程师
- **pairs_research_lab**（配对交易研究实验室）
  [相关性扫描 | 协整检验] → 配对策略师 → 微观结构评审
- **portfolio_review_board**（组合评审委员会）
  [业绩归因分析师 | 风险检查 | 执行质量分析师] → 首席投资官
- **quant_strategy_desk**（量化策略台）
  [选股 | 因子研究员] → 策略回测 → 风险审计 → 报告汇总
- **risk_committee**（风险委员会）
  [回撤分析师 | 尾部风险分析师 | 市场状态分析师] → 风险总监
- **sector_rotation_team**（行业轮动研究团队）
  [经济周期分析师 | 行业景气度分析师 | 资金流分析师] → 行业轮动策略师
- **sentiment_intelligence_team**（市场情绪情报组）
  [新闻情报分析师 | 社交情绪分析师 | 资金流分析师] → 情绪信号合成师
- **social_alpha_team**（社交媒体另类数据团队）
  [Twitter 分析师 | Telegram 分析师 | Reddit 分析师] → Alpha 合成师
- **statistical_arbitrage_desk**（统计套利台）
  [配对扫描 | 微观结构分析师] → 套利策略师 → 风控监控
- **technical_analysis_panel**（技术分析委员会）
  [经典技术分析师 | 一目均衡表分析师 | 谐波形态分析师 | 艾略特波浪分析师 | SMC/订单流分析师] → 信号聚合师（裁判）
- **value_investing_committee**（价值投资委员会（巴菲特 / 芒格 / 段永平 / 李路））
  [巴菲特——护城河与价格 | 芒格——逆向与风险 | 段永平——好生意与可信之人 | 李路——十年确定性与文明趋势] → 委员会主席——共识与矛盾

## 团队匹配机制

由 `src/tools/swarm_tool.py` 的 `_match_preset()` 决定跑哪个团队，三级逻辑：

1. **显式点名优先**：prompt 中出现预设名（如 `investment_committee`）即直接使用，不打分。
2. **关键词打分**：按「团队清单」中各团队的匹配关键词逐条匹配（中英文、正则、忽略大小写），每命中一个累加其权重，取最高分。
3. **兜底**：无一命中时使用 `equity_research_team`（股票研究团队）。

适用范围：agent 通过 `run_swarm(prompt=...)` 工具启动时走上述匹配。
`/swarm run <preset>` 与 `--swarm-run PRESET` 必须显式指定预设名，不走匹配。

「团队清单」中标注"无关键词，需显式点名"的 4 个预设
（`crypto_trading_desk`、`earnings_research_desk`、`global_equities_desk`、`macro_rates_fx_desk`）
无法被自动匹配，只能显式点名，否则会被相邻关键词抢走或落到兜底。

## 技能

技能索引见 [skills.md](skills.md)（90 个，按 category 分组）。

## 新增团队

在 `agent/src/swarm/presets/` 下新增 YAML，字段含 `name` / `title` / `description` /
`agents`（id + role + system_prompt）/ `variables` / `tasks`（DAG）。
