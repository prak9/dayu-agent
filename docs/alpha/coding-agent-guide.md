# Alpha 使用指南：coding agent 入口与 Notion 报告

日常在当前 coding agent 中提出问题、切换研究和查看变化；完整报告保存到 Notion 的 Invest 目录。本地工作区保留原始材料、证据、计算、检查点与报告版本。本流程无需配置或启动 Telegram。

当前 coding agent 负责分析和写作，Alpha MCP 提供财报及研究工具，并管理执行、取消与版本。使用外部入口时，Alpha 不再启动另一个模型。普通的 `alpha research ask --run` 属于内置运行器路径，不是本指南的主入口。

## 1. 跑通入口

### 准备工作区

安装要求见[根用户手册](../../README.md#1-五分钟快速开始)。以下命令在仓库根目录执行，假设已经安装本项目的 Python 3.11 虚拟环境及 Codex CLI：

```bash
source .venv/bin/activate
alpha-mcp --help
alpha init --base ./workspace --codex
```

`--codex` 明确把工作区的内置模型方案配置为本地 Codex，适用于已登录 Codex 的环境；当前 coding agent 经 MCP 研究时仍直接使用当前会话的模型。已有工作区初始化保留研究和报告记录；日常使用不需要重复初始化，也不需要 `--reset`。

### 把 Alpha 加入 coding agent

Codex CLI 接入示例：

```bash
ALPHA_REPO="$(pwd -P)"
codex mcp add alpha -- "$ALPHA_REPO/.venv/bin/alpha-mcp" --base "$ALPHA_REPO/workspace" --owner local
```

只有尚未配置 `alpha` 服务时才执行添加。使用绝对路径，使从其他目录启动的客户端仍指向同一工作区。其他支持 stdio MCP 的 coding agent，也可使用同一个可执行文件与参数；具体注册方式以该客户端为准。

财报转换可能较慢。在 Codex 已有的 `[mcp_servers.alpha]` 表内配置工具时限，例如：

```toml
tool_timeout_sec = 600
```

这是客户端等待时限示例，不保证所有财报都能在十分钟内完成，也不会延长 Alpha 自身的执行限制。首次使用先下载明确日期和报告类型，避免一次转换多年全部年报。Codex 的注册、配置表和超时字段见[官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

重新打开 coding agent 会话。Codex CLI 中可用 `/mcp` 查看活跃连接；也可以直接输入：

```text
调用 alpha_sessions，列出已有研究。只做检查，不创建研究或推送报告。
```

能返回研究列表或空列表，才说明当前会话实际连上了 Alpha。`codex mcp list` 可以检查已注册服务，但配置存在不等于当前会话已经加载工具。

### 加载研究 skill

当前客户端已安装时，直接使用 `$alpha-research`。它规定恢复、财报读取、固定方法、写作检查及报告提交的用法。

仓库随包提供以下 skill 文件：

- [`alpha-research`](../../alpha/research/methods/assets/skills/alpha-research/SKILL.md)：研究入口与归档流程。
- [`invest`](../../alpha/research/methods/assets/skills/invest/SKILL.md)：投资研究与证据纪律。
- [`writing`](../../alpha/research/methods/assets/skills/writing/SKILL.md)：正文写作和全文复核。

如果客户端尚未发现 `$alpha-research`，可以在仓库会话中输入：

```text
读取 alpha/research/methods/assets/skills/alpha-research/SKILL.md，按其中流程使用 Alpha MCP；
开始研究后读取本轮固定的 invest、writing 方法及所需参考。
```

skill 文件指导使用工具，不能替代 MCP 连接。每轮受理会固定方法哈希；恢复旧轮使用原方法，不因本地 skill 更新而改写旧研究。

## 2. 配置 Notion 输出

### 连接与目标

Alpha 原生发布优先读取 `ALPHA_NOTION_TOKEN`，否则读取 Codex 用户配置中 `mcp_servers.notion.env` 下的 `NOTION_TOKEN` 或 `NOTION_API_KEY`。Codex 配置位置为 `$CODEX_HOME/config.toml`；未设置 `CODEX_HOME` 时为 `~/.codex/config.toml`。

已有受支持的 token 配置时无需复制一份。仅登录 Codex、安装 Notion 插件或完成插件 OAuth，并不保证 Alpha 能取得上述 token。当前原生发布器不读取插件的 OAuth 凭据库，也不自动解析其他命名服务的凭据。

需要显式覆盖时，可在启动 coding agent 前设置 token，并允许其 MCP 子进程继承。例如在 Bash 中交互输入，避免把真实值写入命令历史：

```bash
read -r -s -p "Notion token: " ALPHA_NOTION_TOKEN
export ALPHA_NOTION_TOKEN
```

若 Codex 配置需要显式转发，在已有 `[mcp_servers.alpha]` 表的 `env_vars` 数组中加入 `ALPHA_NOTION_TOKEN`，保留原有项，再重启连接。不要把 token 写进报告、研究问题或仓库文档。

目标由 `workspace/config/notion.json` 的固定页面 ID 决定：

```json
{
  "parent_page_id": "8b6f0c8f-c126-4555-b531-281fbb0b96bc"
}
```

本仓库默认目标为已确认的 [Invest](https://www.notion.so/8b6f0c8fc1264555b531281fbb0b96bc)。在自己的 Notion 空间使用时，改成自己的页面 ID，并授予对应 connection 读取、插入和更新该页及子页的权限。改变目标会影响发布校验；已有意图不会自动改发到新目标。

### 报告放在哪里

原生发布目录固定为：

```text
Invest
└── 研究主题页（绑定 research_id）
    ├── 正式报告 v1
    └── 正式报告 v2
```

同公司不同研究问题可以拥有不同主题；相同主题的新财报更新保留在原 `research_id` 下。已发布版本不覆盖，下次更新生成新版本。Notion 用于阅读和归档，本地工作区仍是研究状态及恢复记录的保存位置；手动修改 Notion 不会反向更新 Alpha 的模型和证据。

## 3. 发起一次研究

在 coding agent 中输入：

```text
$alpha-research
研究 AAPL 的长期股东现金回报，投资期限五年。
先查看已有主题；如没有相同问题，创建新主题，证券代码为 AAPL。
说明收益主要来自企业价值增长、估值修复还是承担特定风险。
读取适用财报及实际三表，核对资本开支、激励、股数和现金归属。
找出最影响估值的核心假设、反证，以及下一次能检验判断的经营结果。
给出质量评价、估值依据、情景回报、现价所需条件和价格参考。
应用本轮固定的 invest 和 writing 方法，完成全文复核。
本轮完成后，将通过验收的正式版本推送到配置的 Notion Invest 目录。
若验收未通过，保留候选和缺口；有独立 Notion 连接时，将完整正文另行归档为标明未通过项的研究稿。
交付时在聊天中只给主要结论、重要变化、尚未解决的问题及 Notion 链接。
```

这是一轮新的研究请求，不指定答案或保证收益。“完成后推送”授权本轮归档，agent 应在 `alpha_begin` 时设置 `publish_on_complete=true`；不需要研究完成后再次询问同一项授权。示例同时授权了单独归档研究稿，具体连接与验收区别见第6节。

如果只想先研究，去掉推送正式版本和归档研究稿两项要求，换为“先保存本地结果，暂不发布”。之后可以明确要求发布指定 `revision_id`，无需重新分析。

每轮至少应让读者找到下列内容，具体篇幅随问题调整：

| 内容 | 要回答的问题 |
|---|---|
| 收益来源与期限 | 为什么持有能获益，何时可能兑现？ |
| 核心判断与机制 | 哪些经营变化会影响普通股每股价值？ |
| 证据与假设 | 哪些已观察到，哪些是指引、推断或模型设定？ |
| 价格与风险 | 现价要求什么，下行情景能否承受？ |
| 下一次检验 | 看什么结果，出现什么情况需要重估？ |

这些内容通过四个业务工具保存和查看，参数 schema 随 `alpha_begin` 返回：

| 工具 | 保存或读取什么 |
|---|---|
| `research_save_mandate` | 收益来源、期限、失效条件、资金约束；改约定须说明原因 |
| `research_save_judgment` | 判断、传导机制、支持/反对证据、假设、替代解释、预期观察和检验时间 |
| `research_judgments` | 原判断、形成时的约定、复盘历史及到期状态；支持分页和 `due_only` |
| `research_review_judgment` | 实际经营结果、证据、判断变化、错误归因及下次检验 |

收益来源字段可选企业价值增长 `business_value_growth`、低估修复 `mispricing_convergence`、风险补偿 `risk_compensation`、交易行为变化 `market_behavior`，可以并存。未提供资金条件时保存“未知”，不据此编造仓位。每条判断有不可变记录 ID，并绑定当时的约定和信息截止日；改期限不会重写旧预测。

### 输出格式

聊天返回与正式正文绑定的简短摘要。例如：

```text
当前结论：等待价格。
关键假设：常态利润能够持续增长。
主要分歧：增长来自产量与成本改善，还是商品涨价。
本轮变化：新增证据如何支持或削弱原判断。
未解决问题／需要你决定：只列仍影响决策的事项。
报告状态：正式版本及信息截止时间。
Notion 完整报告：仅在已确认发布时附链接，否则展示实际状态。
```

完整报告用 `research_compose_report` 保存。单公司正文保留商业模式、关键指标、质量及依据、估值及依据、现价隐含预期、机会、上下行、情景回报和检验；章节围绕公司的关键问题安排。组装器附上所引用的原判断、原约定、复盘和来源，不把摘要替代正文。

比较报告先给条件性比较表，再给逐家公司论证：优先级、质量及依据、报价/币种/日期、基准情景年化、压力情景累计回报、买入参考、改变顺序的条件。允许并列、暂不可比、证据不足；未核验回报用空值。基准年化是特定情景的结果，系统不提供可靠的情景概率校准，不能自动称为“预期收益”。摘要和正文均须实际应用 writing 方法复核。

`research_validate_candidate` 验证候选。若用 `research_patch_candidate` 改变正文，应重新 compose 绑定摘要；系统不会把旧摘要套在新正文上。纯笔记可继续使用 `research_draft_report`，但不会自动生成结构化聊天摘要。

## 4. 管理多个研究 session

聊天窗口与 Alpha 研究不是一一对应。用 `research_id` 确定主题；同一 coding agent 会话可以切换主题，换一个聊天窗口也可以继续同一研究。

```text
列出 Alpha 的研究主题，展示标题、research_id、运行状态、待处理数量和最近正式版本。
如果还有下一页，继续读取；不要只按公司名合并研究。
```

`alpha_sessions` 返回 `next_offset` 时，用该偏移继续分页。同一主题同时只允许一个写执行；可以查看多个主题，但不要让两个 coding agent 同时修改同一研究。

| 标识 | 使用场景 |
|---|---|
| `research_id` | 创建后持续复用的研究主题 |
| `turn_id` | 一次研究输入，异常恢复时使用 |
| `run_id` | 执行及工具调用的追溯 |
| `candidate_id` + `content_hash` | 提交准确的候选稿 |
| `revision_id` | 读取或发布一个正式报告版本 |
| `publication_id` | 查询一次已授权归档的状态 |

继续原问题时明确给出 ID：

```text
$alpha-research
继续 research_实际ID。先读取检查点及原报告，保留原判断和信息截止日。
先调用 research_judgments，保留原约定；再查询 due_only=true 并继续分页。
只更新最新财报影响到的假设、估值和风险，解释结论为何变化或保持不变。
对已到检验日的原判断另存复盘，列出实际经营结果、证据及错误归因。
完成后将新的正式版本推送至原 Notion 研究主题，保留旧版本。
```

同一公司的新问题应另建主题，并引用相关旧研究。例如“现金回报是否改善”和“新业务是否具备商业可行性”可以独立研究。比较范围明显改变时，明确新范围及证券代码，必要时另建比较主题；不要让旧标题和旧标的列表代替本轮真实覆盖。

复盘结果可为获得支持、受到反证、证据不足或兑现延迟。前两项必须提供观察证据；后两项必须说明原因及新的检验时间。数据错误、机制误判、资本需求低估、兑现延迟和估值过高分别记录，也允许归因未定。股价涨跌不能单独作为经营检验。修订预测用 `previous_judgment_id` 连接旧记录；旧记录即使被替代，仍保留到期复盘责任。

到期状态按本轮固定的信息截止日计算；新财报复盘应开启新一轮。这里是按需查询与复盘，没有后台定时扫描或自动投资决策。

创建、开始和工具调用均有稳定请求键。相同操作因网络问题重试时复用原键和参数；新的研究意图使用新键。不能靠重放旧键获得一轮新的分析。

多公司比较也可以作为一个研究主题。例如：

```text
$alpha-research
比较 AAPL、MSFT、00981.HK 与 601899.SH 的五年股东回报机会。
明确采用的上市地与报价币种，以统一报价日期比较。
先识别影响结论的经营分歧，再决定逐家公司需要补哪些证据。
结合质量、资本需求、下行风险与证据把握给出条件性排序，允许并列或暂不可比。
保留每家公司现价所需经营条件、价格参考和判断失效条件。
完成后推送正式报告至配置的 Invest 目录，保留来源与限定。
```

## 5. 核对财报与判断

Agent 在 `alpha_begin` 返回的工具目录中调用以下能力，用户通常无需手填 JSON：

```text
下载明确范围的财报
→ 准备指定源文档
→ 实际读取利润表、资产负债表、现金流表
→ 保存来源、计算、判断和待核验问题
→ 保存候选稿并校验
→ 提交准确的候选 ID/hash
```

对应财报工具为 `research_download_filings`、`research_prepare_source`、`research_read_financial`。已下载源文档可直接准备。证券研究默认要求核心三表；需要更长历史或指定文档时，在本轮开始时固定 `financial_requirements_json`，不能在末尾为了过验收而删除缺口。

人工核读 PDF、自动三表覆盖和算术校验分别说明了不同事情。有原件或读取凭据，不代表读取结果含有效数值；出现 `supported=false`、`not_supported`、空表或口径缺失时，需要保留具体问题。当前 Docling 路径可从原始网格提取合并三表，保留续页首行、期间、币种、缩放及原表定位，并排除母公司表。它依赖原件有可识别的范围和口径，不能保证任意 A/H 股 PDF 都可用；具体以实际文档结果为准。

可以这样检查 agent 的判断：

```text
指出最影响估值的假设，以及当前最弱的一步证据。
说明哪项证据能区分主要解释与替代解释；先完成现在可做的核查。
用较差的经营结果重算每股回报，说明价格改善能解决哪些问题，哪些仍要等经营验证。
```

财报原件只能经 Fins 仓储存取。当前 MCP 控制面没有直接上传本地文件的参数；把 PDF 附在 coding agent 聊天里，不等于它已进入 Alpha。公开财报优先通过下载链路取得；CLI 材料导入及其排队执行属于[另一条使用路径](../../README.md#将指定报告版本推送到-notion-invest)，不应被描述为已完成外部入口的一键导入。

## 6. 确认报告已进入 Notion

### 正式报告

候选稿校验通过，并且 `alpha_finish` 成功返回 `revision_id` 后，才产生正式版本。设置了本轮完成后发布策略时，MCP 的独立发布工作者会处理队列，无需 Telegram 常驻进程。

```text
查询 alpha_delivery(revision_id)，读取与正式正文匹配的摘要和真实发布状态。
仅在 publication.state 为 published 时返回已确认的 Notion 链接；队列明细可查 alpha_publications。
若尚未完成，说明发布状态及具体问题，不重新运行研究。
```

正式版本已存在、先前没有要求推送时：

```text
将 revision_实际ID 推送到配置的 Invest 目录，查询发布结果并返回直接链接。
```

agent 使用 `alpha_publish(revision_id, request_key)`，再查 `alpha_publications`。保持连接直到确认结果；只看到 `pending` 或 `publishing` 时退出，不能保证后台进程继续运行。

### 研究稿

必需三表等验收未通过时，可以保留完整研究稿、候选和缺口，但没有正式 `revision_id`，也不会通过 Alpha 原生发布队列归档。

已有授权覆盖研究稿时直接沿用，不重复询问。只有正式版本发布授权时，不将其扩展为草稿归档；需要研究稿的用户可以这样指定：

```text
保留验收失败的候选和具体缺口。
若当前有可用的 Notion 连接，将完整正文另行归档为“研究稿”，放在已授权的 Invest 研究主题下。
在页面开头标明证据范围和未通过项；不要创建或宣称 Alpha 正式版本。
写入后读回核对，保存页面 ID、链接和归档记录，保持旧版本不变。
```

这条路径依赖 coding agent 的独立 Notion 连接，当前不是 Alpha 原生的“草稿发布”功能，也不会自动出现在 `alpha_publications` 中。没有连接或写权限时，保留本地稿件并报告“Notion 归档待完成”。

### 怎样判断完成

| 状态 | 完成的含义 |
|---|---|
| 研究判断 | 结论、关键假设、反证和未解决问题已明确 |
| 数据与提交 | 标准读取及候选校验是否通过，是否有正式版本 |
| Notion 归档 | 正文实际写入并读回核对，有可访问的页面链接 |

归档成功不证明研究假设正确，算术通过也不证明来源支持结论。聊天结尾应分别说明上述状态，尤其不能把“已受理发布”写成“已推送”。

## 7. 停止、恢复和故障处理

停止时输入“保存当前进展并停止这项研究”。agent 先保存工作笔记，再通过 `alpha_abort` 请求收尾。研究稿和检查点保留；主动停止后继续工作应开启新一轮，再读取旧检查点。

失败、孤立或超时输入可以请求：

```text
检查 turn_实际ID 是否可恢复；可恢复时用 alpha_resume 显式恢复，保留原截止时间和方法。
先读检查点，再继续未完成工作，不把旧证据改成刚刚重新核验。
```

连接退出会请求取消未完成工具执行，不能假设 coding agent 关闭后研究仍自动运行。新财报、晚于原截止时间导入的材料或新的研究问题，应开新一轮。

| 现象 | 处理方式 |
|---|---|
| 当前 agent 找不到 Alpha 工具 | 检查绝对路径和注册配置，重开会话后实际调用 `alpha_sessions` |
| 同一主题提示繁忙 | 核对原执行；停止或恢复它，不并发抢写同一研究 |
| 财报工具超时 | 保留检查点，检查执行状态；缩小下一次下载范围，必要时调整客户端时限 |
| 三表 `not_supported` 或无有效数值 | 保留缺口；原文可继续分析，但不声明标准覆盖通过 |
| Notion 连接未配置 | 检查 Alpha 支持的 token 来源和进程环境；插件 OAuth 不等于可复用 token |
| 发布为 `failed_retryable` | 查询错误并按队列状态处理；如已到期，保持 MCP 连接让工作者继续处理 |
| 发布为 `failed_terminal` | 修复明确错误后，用新请求键重新请求；重放旧失败键只返回原状态 |
| 发布为 `reconciling`、创建结果未知 | 先核对原页面和标记；不另建同名页，也不直接认定未创建 |
| Notion 人工编辑或正文回读不一致 | 保留待核对状态；不覆盖人工内容，不以重跑研究解决交付冲突 |

## 8. 本地核对与备份

CLI 可用于只读核对，以下占位 ID 需替换为实际值：

```bash
source .venv/bin/activate
alpha research --base ./workspace --owner local list
alpha research --base ./workspace --owner local status research_实际ID
alpha research --base ./workspace --owner local report revision_实际ID
alpha research --base ./workspace --owner local publication publication_实际ID
```

本轮已授权的正式版本也可通过 CLI 发布：

```bash
alpha research --base ./workspace --owner local publish revision_实际ID --key publish-实际唯一键 --run
```

`--run` 处理队列中最早的一项已授权发布；存在其他积压时，本次指定版本未必立即发布，仍应查询其 `publication_id`。这个命令处理报告发布，不启动研究模型。

需要收起已结束的研究时，可让 coding agent 执行以下管理命令。归档保留原研究、会话和报告，重新打开复用同一 ID；两者都不删除 Notion 页面：

```bash
alpha research --base ./workspace --owner local archive research_实际ID
alpha research --base ./workspace --owner local open research_实际ID
```

存在排队或派发中的输入时，先核对状态并按意图结束或停止，再归档。`alpha_sessions` 仍可列出归档状态；它目前没有按公司或状态筛选的参数，可让 coding agent 在完整分页结果上整理视图。

备份完整 `workspace/`，包括 `.alpha/`、研究材料和财报存储；仅复制 Notion 正文不足以恢复研究。复制前停止活跃写执行，避免得到不同时间点的数据库和文件快照。迁移到新机器后，更新 MCP 的绝对路径，并单独配置凭据。

维护与实现边界见[研究存储手册](../../alpha/research/README.md)。本指南描述现有入口的使用，支持逐条判断与按需复盘，不包含自动投资决策、交易或持续监控。
