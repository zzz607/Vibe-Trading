# 技能索引（Skills）

每个技能是 `agent/src/skills/<name>/SKILL.md`，agent 运行中通过 `load_skill("<name>")` 加载。
本文件只收录 front matter 元数据（name / category / description）；分析方法论见对应 SKILL.md 正文。

共 90 个，按 category 分组。

## analysis（23）

- **behavioral-finance** — 行为金融学应用：过度反应与反应不足理论、动量与反转的行为解释、投资者情绪周期、认知偏差清单，以及去偏后的量化策略。
- **commodity-analysis** — 商品分析（原油供需平衡 / 黄金定价 / 铜作为经济预测指标 / 库存周期 / 期货升贴水结构 / 季节性），输出方向性商品信号。
- **correlation-analysis** — 相关性与协整分析：共动发现、收益相关性深析、行业聚类、已实现相关、Engle-Granger / Johansen 协整、半衰期、Kalman 动态对冲比率、跨市场联动分析，以及配对交易信号生成。
- **correlation-regime** — 相关性状态识别与危机归因：基于边缘密度的状态划分（带迟滞）、因果（无前视）平滑、状态感知的敞口背景、第一推动者危机归因并给出 NAME / MACRO / AMBIGUOUS / ABSTAIN 的诚实结论，以及能捕捉慢刀式失血的相关性重连排行榜。
- **credit-analysis** — 固收与信用分析：信用债评级、利差分析、违约风险评估、城投债研究、可转债定价与策略。
- **deep-company-series** — 为单一公司撰写可发表级别的 8 篇深度系列（全文约 12 万字）：认知重置 / 护城河 / 盈利引擎 / 隐性资产 / 时代变量（如 AI）/ 巴菲特式财务分析 / 管理层 / 估值与红线。核心能力不是"写"而是"改"——严格的核查清单会揪出伪精确（概率加权预期、第三方 MAU 口径不一、线性外推）、绝对化措辞，以及多数财经长文都会犯的跨文章数字不一致。每篇可独立阅读，但共用同一套估值 / 管理层 / 价格框架。当用户想要教科书级深度、且用于公开发表的单公司内容时使用（单篇研报或业绩点评不属于此类，改用 investment-research / earnings-review）。
- **dividend-analysis** — 股息股分析：收益型、股息增长与股东回报策略，含股息率质量、派息可持续性、除息机制与高息陷阱检查。
- **earnings-forecast** — 盈利预测与一致预期分析（自上而下/自下而上预测法/SUE/PEAD/分析师预期修正），捕捉业绩超预期交易机会。
- **earnings-revision** — 盈利预测修正、指引分析与盈余公告后漂移（PEAD）：跟踪分析师一致预期变化、业绩超预期模式与管理层指引变动，适用于美股 / 港股。
- **factor-research** — 因子研究框架：IC/IR 分析、分位回测与因子合成，适用于多品种的截面因子评估。
- **global-macro** — 全球宏观分析框架（央行政策传导 / 汇率预测 / 地缘风险 / 资本流动），用于构建驱动跨资产配置的宏观因子信号。
- **investor-lenses** — 把知名投资人的推理框架打包成可复用的分析透镜：12 个透镜（深度价值、优质特许、逆向反转、闲聊式成长、GARP、周期定位、债务周期、法证做空、成本拖累、好生意、弱系统逆向、三问法），叠加在已收集的证据之上，各自带优先级排序信号、硬性排除项与已记录的失效模式。
- **macro-analysis** — 宏观周期定位与央行政策解读，含 GDP/CPI/PMI/利率/汇率分析，输出为大类资产配置倾斜。
- **management-deep-dive** — 管理层深度评估："买股票就是买人"这一层。针对公司或具名高管，评估诚信（承诺与兑现跟踪、危机时刻表现、利益相关方待遇）、能力（战略远见、执行力、资本配置记录）与治理（股权结构、薪酬、关联交易）。输出诚信 / 能力 / 资本配置 / 治理的加权评分，以及段永平三问结论（"你敢把钱交给他十年吗"）。当常规研究无法确定管理层质量，或管理层本身就是投资论点时使用。
- **market-microstructure** — 市场微观结构：买卖价差分析、订单流毒性指标（VPIN / Kyle lambda）、流动性度量（Amihud / Roll）、价格冲击模型、限价订单簿分析，以及 A 股集合竞价 / 大宗交易机制。
- **performance-attribution** — 业绩归因分析：Brinson 行业 / 选股归因、因子 alpha/beta 分解、择时评估与基准比较框架。
- **private-company-research** — 面向 IPO 前 / 非上市公司的深度研究框架（蚂蚁集团、SpaceX、Stripe、字节跳动等）。六个分析师透镜——商业模式、财务法证、竞争格局、风险与治理、技术与知识产权、另类数据信号——通过 run_swarm 并行运行，再在给出结论前交叉验证信号一致性。围绕非上市公司研究的核心难点：信息稀缺，因此每个数据点都带置信标签（高 / 中 / 低），推断与事实分开呈现，"我不知道"是有效输出。输出公允价值区间、退出路径分析与信息缺口图。当需要对任何未上市公司判断其真实价值时使用。
- **quant-statistics** — 量化统计方法：ADF 单位根 / 协整检验、GARCH 波动率建模、回归诊断（异方差 / 自相关）、Bootstrap 与假设检验。
- **research-discipline** — 在任何投研任务（选股 / 行业研究 / 公司深挖）开始时运行的简短偏差自查清单。四类系统性扭曲 AI 研究的偏差——龙头偏差（只看大票）、英文偏差（漏掉日韩台玩家）、叙事偏差（追逐概念标签）、确认偏差（只看多头证据）——加上近因偏差。先加载本技能，再带着修正去做研究。它不是工作流，只是 60 秒的态度重置，能实质性改善覆盖面与诚实度。
- **risk-analysis** — 风险度量与压力测试：VaR/CVaR/最大回撤计算、蒙特卡洛模拟、极值尾部风险分析与历史情景压力测试。
- **sentiment-analysis** — 市场情绪分析——恐贪指数/Put-Call Ratio/融资融券/北向资金信号解读、社交媒体舆情量化框架
- **shadow-account** — Shadow Account — 从用户交割单提炼盈利模式（3-5 条人话规则）→ 跨 A股/港股/美股/crypto 多市场回测 → 差值归因 → 8-section PDF 报告。叙事：你的影子，没有情绪噪音。
- **valuation-model** — 估值方法论：绝对估值（DCF / DDM / SOTP）、相对估值（PE-Band / PB-ROE / EV-EBITDA）、敏感性分析与估值陷阱识别。

## asset-class（9）

- **asset-allocation** — 资产配置理论与优化器使用：MPT / Black-Litterman / 风险预算 / 全天候策略，含 5 个优化器的使用说明与再平衡规则。
- **convertible-bond** — A股可转债分析——转股/纯债/期权三维估值、下修/强赎/回售博弈、双低策略与转债轮动选债框架
- **etf-analysis** — ETF分析：产品筛选、费率对比、跟踪误差、流动性评估、策略应用与中国市场ETF量化配置框架。
- **fund-analysis** — 基金分析与筛选：晨星评级/夏普比率/信息比率、Sharpe风格箱分析、风格漂移检测、基金经理评价、FOF组合构建、ETF选择
- **hedging-strategy** — 对冲策略设计（beta 对冲 / 期权保护 / 尾部风险 / 跨资产对冲），含对冲比率计算与成本评估。
- **options-advanced** — 进阶期权策略：波动率曲面建模（SABR / Local Vol）、动态 Greeks 再平衡、日历价差、波动率套利与偏度交易，以及期权做市基础。
- **options-payoff** — 期权盈亏分析方法论：盈亏图、盈亏平衡计算、多腿策略可视化与基于 Greeks 的情景分析。
- **options-strategy** — 期权策略框架，支持 Black-Scholes 定价、Greeks 分析与多腿回测，适用于加密与股票期权。
- **sector-rotation** — 行业轮动分析——申万行业景气度评分、行业动量排名、产业链传导、估值/盈利/资金流多维比较框架

## crypto（7）

- **crypto-derivatives** — 加密衍生品策略：永续资金费率套利、期货期限结构 contango/backwardation 交易、期权波动率微笑 / Greeks 分析。
- **defi-yield** — DeFi 收益分析与优化：借贷利率、LP 收益、质押回报、挖矿策略、风险调整后收益比较与协议级可持续性评估。
- **liquidation-heatmap** — 清算位分析与热力图解读：识别杠杆仓位集中区、清算级联、猎杀止损区，并把清算数据用作支撑 / 阻力信号。
- **onchain-analysis** — 链上数据分析：活跃地址 / 巨鲸追踪 / TVL / DEX 流动性，以及 MVRV / NVT / SOPR 等链上估值指标的解读与信号生成。
- **perp-funding-basis** — 永续合约资金费率分析与期现基差交易：资金费率状态、年化基差信号、carry 交易构建与跨所资金费率套利。
- **stablecoin-flow** — 稳定币供给与流向分析：USDT/USDC 铸造销毁信号、交易所稳定币储备、链上稳定币流通速度，以及用于加密市场择时的资本轮动指标。
- **token-unlock-treasury** — 代币解锁计划分析与项目金库追踪：悬崖式解锁、线性解锁、团队 / 投资人 / 生态代币释放、金库多元化与抛压预测。

## data-source（10）

- **akshare** — AKShare 财经数据聚合库（GitHub 18k+ stars）。免费、无需 API key。覆盖 A 股、美股、港股、期货、宏观、外汇。tushare 与 yfinance 的主要回退源。
- **ccxt** — CCXT 统一加密货币交易所库（100+ 家交易所）。免费公开行情数据。OKX 不可用时的回退。
- **data-routing** — 所有数据需求的唯一路由器。在做任何回测、取数或研究任务前先加载本技能，以选择当前最优数据源 / 工具、满足鉴权（环境变量）要求，并避开有封禁风险的数据源。
- **eastmoney** — 东方财富（Eastmoney）免费免鉴权数据接口，覆盖资金流向、龙虎榜、融资融券、大宗交易、股东户数、限售解禁、行业概念板块、券商研报、财经新闻、A股/港股三大报表+主要指标、全市场选股与代码搜索；美股财报由 get_financial_statements 转 SEC EDGAR。东财请求经共享 IP 限速层节流（东财按源 IP 限流并临时封禁突发请求），通过 Vibe-Trading 工具直接调用，无需 token。
- **mootdx** — 通过 TCP 直连通达信服务器获取 A 股行情。2026-10 已停用：通达信服务器不再响应该客户端协议，因此该源已退出自动回退链，仅在显式 `source="mootdx"` 时保留。
- **okx-market** — OKX 加密货币行情接口。使用 OKX V5 REST API 获取现货、衍生品、指数等加密市场数据，含实时价格、K 线、资金费率、持仓量等。无需鉴权，免费使用。
- **qveris** — 全球多资产数据付费能力市场；当 Vibe-Trading 免费数据源在覆盖度、深度或供应商质量上不足时使用，常规 OHLCV 仍以免费源为默认。
- **sec-edgar** — 美股 SEC EDGAR 取数接口：把股票代码解析为 CIK、列出近期公告（10-K / 10-Q / 8-K 等）及主要文档 URL、拉取 XBRL companyfacts 财务序列。免费、无需 API key；按 IP 限流，因此每个请求都会被节流并附带联系用 User-Agent。仅适用于美国。
- **tushare** — tushare是一个财经数据接口包，拥有丰富的数据内容，如股票、基金、期货、数字货币等行情数据，公司财务、基金经理等基本面数据。该模块通过标准化API方式统一了数据资产的对外服务方式，以帮助有需要的技术用户更实时、简洁、轻量的使用相关数据。
- **yfinance** — yfinance 全球行情接口：通过雅虎财经获取美股、港股、加拿大股票、ETF 与指数的 OHLCV 及研究数据。免费、无需 API key。

## flow（8）

- **adr-hshare** — ADR/H股/A股跨市场上市溢价分析：跟踪美股 ADR、港股 H 股与 A 股之间的价差，用于套利信号、双重上市估值与退市风险评估。
- **corporate-events** — 公司事件驱动分析：并购套利价差计算、大股东增减持信号、股权激励解读、定增配股影响评估、A股ST/退市预警
- **edgar-sec-filings** — SEC EDGAR 公告分析：10-K、10-Q、8-K、委托书、内部人 Form 4。提取关键财务、风险因素、管理层讨论，并从美股上市公司公告中生成投资信号。
- **financial-statement** — 财报三表深度解读——三表勾稽关系、盈利质量(应计vs现金流)分析、杜邦分解、10+财务造假红旗指标
- **fundamental-filter** — 基本面因子筛选：按 PE/PB/ROE、财务报表字段等指标筛选价值股或成长股。支持 A 股（tushare extra_fields 或 fundamental_fields）与港美股（yfinance Ticker info）。
- **hk-connect-flow** — 沪深港通资金流分析：北向（外资进 A 股）、南向（内资进港股）、行业配置跟踪与跨境套利信号。
- **research-goal** — 目标驱动的投研工作流：挂上一个仅研究性质的目标、跟踪达成标准、持续补充证据，同时避免触发实盘交易执行。
- **us-etf-flow** — 美股 ETF 资金流、行业轮动广度与风格因子流向分析：通过 ETF 申购赎回跟踪机构资金动向、行业广度信号与主题动量。

## research（3）

- **alpha-zoo** — 浏览并对基准测试内置 alpha 动物园——预置截面因子库（Kakushadze 101、GTJA 191、Qlib 158、Fama-French / Carhart）。当用户问"有哪些 alpha"、想要某个 alpha 的元数据，或想对整个动物园在某个股票池上跑 IC/IR 时使用。
- **strategy-dev-manager** — 策略开发管理器：把学术论文与研究报告转化为经过验证的因子与策略，配套自动化回测、持久化存储与衰减监控。
- **strategy-discovery** — 策略发现：Alpha Zoo 与 SDM 策略库之上的证据门面——回答存在哪些策略及其当前状态，用分状态证据替代情景标签；对每条返回记录报告证据新鲜度，并从本地回测运行重建一次性证据缓存。

## risk-analysis（1）

- **ashare-pre-st-filter** — A 股 ST/*ST 风险预测框架 — 基于最新中报/三季报或业绩预告/快报，预测下一财年是否会因营收、利润、净资产、分红不达标而被风险警示，并将新浪监管处罚记录作为独立证据面纳入风险等级。仅适用于 A 股，不预测财务造假。

## strategy（19）

- **bottleneck-hunter** — 供应链瓶颈套利。给定一个超级趋势（AI 基建、能源转型、国防、半导体回流、太空经济），把其物理供应链拆解到 Layer 2/3 卡点（光学、激光器、InP/SOI 衬底、IC 载板、探针卡、特种玻纤等），并找出坐落在每个瓶颈上、尚未被市场注意的上市公司。按 6 项稀缺性标准给每个环节打分，通过 financial_rigor 工具施加强制估值门槛（PS/PE/安全边际），并用芒格式反向验证。输出排序后的瓶颈机会榜。当用户想找结构性趋势的隐性受益者而非已被定价的龙头时使用。
- **candlestick** — K 线形态识别引擎，纯 pandas 向量化实现 15 种经典 K 线形态（5 单根 + 5 双根 + 4 三根 + 1 趋势确认），由多空形态评分合成复合信号。
- **chanlun** — 基于缠论（缠中说禅）的形态识别引擎，使用czsc库自动检测K线分型、笔、中枢，并生成一买/一卖/二买/二卖/三买/三卖等买卖点信号。支持多周期分析和形态分类（3/5/7/9/11笔形态）。
- **cross-market-strategy** — 为跨市场组合（A 股 + 加密、股票 + 外汇等）编写 signal_engine.py。
- **elliott-wave** — 艾略特波浪信号引擎。通过 Zigzag 检测摆动点，匹配 5 浪推动与 3 浪调整结构，用斐波那契波浪关系验证，生成趋势见顶 / 调整完成信号。纯自研 pandas 实现。
- **event-driven** — 事件驱动策略，基于新闻、公告与宏观事件的情绪打分信号。LLM 作为 NLP 引擎，事件数据遵循 CSV schema。
- **execution-model** — 交易执行建模（仅回测）：滑点公式（线性 / 平方根冲击）、VWAP/TWAP 执行逻辑、市场冲击成本估算与执行假设配置。
- **harmonic** — 谐波形态信号引擎。基于斐波那契几何识别 Gartley/Bat/Butterfly/Crab 等 XABCD 五点结构，在 PRZ（潜在反转区）生成交易信号。
- **ichimoku** — 一目均衡表五线系统信号引擎。独立的技术分析流派，由转换线 / 基准线交叉、云层位置与迟行线确认生成交易信号。纯 pandas 实现。
- **minute-analysis** — 分钟级数据分析与回测。通过 OKX/Tushare/yfinance 获取分钟 K 线，既可用于分析，也可作为回测引擎输入。
- **ml-strategy** — 基于 sklearn 前向训练（walk-forward）的机器学习预测策略，含特征工程与信号生成。适用于任何 OHLCV 数据。
- **multi-factor** — 多因子截面选股排名。组合因子标准化、等权或 IC 加权打分与 TopN 组合构建。适用于多品种组合策略。
- **pair-trading** — 配对交易策略。用两个相关品种的价差 / 比价 Z-score 交易均值回归。至少需要两个品种。
- **seasonal** — 季节性 / 日历效应策略。由年月效应、星期效应等基于时间的模式生成交易信号。适用于任何 OHLCV 数据。
- **smc** — 聪明钱概念（ICT）信号引擎。使用 smartmoneyconcepts 库实现机构交易流派对 BOS、ChoCH、FVG 与订单块（OB）的分析。
- **strategy-generate** — 创建、修改与优化量化交易策略，并对其进行回测与评估。
- **technical-basic** — 核心技术指标集合（趋势 EMA/ADX + 均值回归 BB/RSI + 量价 OBV/量比），通过三维投票生成复合信号。纯 pandas 实现，适用于任何 OHLCV 数据。
- **thesis-tracker** — 买方纪律系统。对每个持仓维护一份书面投资论点——5 句话核心论点、可证伪假设、红线、估值锚——每季度对照新财报 / 事件复查。由假设破裂与红线触发打分论点健康度（1-10），并给出持有 / 加仓 / 减仓 / 清仓建议。买入后立即使用（写下论点），每个财报季复查。它补上多数投资者跳过的"研究→买入→跟踪"缺口。
- **volatility** — 波动率策略。基于历史波动率（HV）分位排名交易均值回归。适用于任何 OHLCV 数据。

## tool（10）

- **backtest-diagnose** — 诊断失败或表现不佳的回测，定位根因并修复问题。
- **doc-reader** — 读取常见文档与数据文件——PDF、Word（.docx）、Excel（.xlsx/.xls）、PowerPoint（.pptx）、图片（OCR）、CSV/TSV、纯文本、JSON/YAML/TOML、HTML/XML 及多数源码文件。使用 `read_document` 工具。
- **geopolitical-risk** — 地缘风险分析：量化危机信号、识别前兆，并为战争、制裁与供给中断情景构建事件驱动策略。
- **pine-script** — 把回测策略导出为主流交易平台的指标 / 策略代码——TradingView、通达信、同花顺、东方财富、MT5。
- **regulatory-knowledge** — 金融监管知识库：A股涨跌停/ST退市新规/融券、港股T+0/做空机制、美股PDT/熔断、加密监管政策、跨境税务基础
- **report-generate** — 专业财经研报生成：标准结构（摘要 / 观点 / 正文 / 风险 / 建议）、Markdown 格式规范、评级体系与术语表。
- **social-media-intelligence** — 社交媒体情报：从 Twitter/X、Telegram、Discord 与 Reddit 提取金融信号，用于情绪驱动交易策略。
- **trade-journal** — 分析用户交易记录（券商导出的 CSV/Excel）。解析同花顺 / 东方财富 / 富途 / 通用格式，产出交易画像与 4 项行为诊断（处置效应、过度交易、追涨、锚定）。使用 `analyze_trade_journal` 工具。
- **vnpy-export** — 把 Vibe-Trading 回测策略导出为可直接运行的 vnpy CtaTemplate Python 类——通过 BarGenerator + ArrayManager 支持 A 股股票、期货与加密。
- **web-reader** — 把网页、文章与文档链接转为 Markdown 文本读取。直接使用 `read_url` 工具，无需 bash。完整 URL 发给第三方 Jina Reader（r.jina.ai）。
