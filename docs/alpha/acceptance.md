# alpha 实施验收

当前实现及本地验收已完成：alpha 支持原生 Codex 和外部 coding agent 两条研究路径、结构化财报、候选稿校验及固定版本发布。真实 BABA 第二版已通过公开 MCP 入口生成，第一版保持不变。真实 Notion 主题创建返回503，最终结果尚未确认，归档保留为待核对；Telegram 缺少用户ID和私聊话题开关。具体状态以 [执行计划](program.md) 为准。

## 已实现

- 产品、Python 包、CLI、配置、构建及现有渠道统一为 alpha；旧命名工作区通过 `alpha init` 插件一次性升级，保留原始恢复副本，不保留旧导入或命令别名。
- 一个研究对应一个固定 Host Session；同公司不同问题独立，输入持久排队，报告形成不可变 revision。研究、执行、渠道交付和发布分别保存各自事实，Host 是运行、互斥和取消真源。
- invest 方法依赖与四类确定计算随 wheel 分发，受理时固定方法哈希、模型和工具规格；恢复使用原规格。研究工具支持记录、计算、历史报告、原文证据及正式提交。
- CLI 和 Telegram 支持创建、列表、状态、停止、显式恢复、归档、重新打开、报告获取。Telegram 使用原生话题切换研究，列表分页和权限绑定按钮管理多个研究，进度不展示内部推理。
- Telegram inbox、offset、话题创建标记、按钮和发送回执持久化；未知创建或发送不盲目重复。摘要与报告文件分别交付，重启保留绑定和结果。
- Telegram/CLI 可导入 PDF、TXT、Markdown、HTML，检查实际 20 MiB 上限与格式。普通材料在研究库；明确 `/filing` 财报原件只经 Fins 仓储。PDF 逐页读取有时间和输出上限，可取消并回收进程；财报结构准备复用 Docling，已有 Fins 章节与表格工具实测可读。新材料生成新输入和 v2，不改动 v1。
- 用户明确选择 revision 后向配置的 Invest 父页发布，一版一页。正文接受时冻结，独立 Host operation 执行；保存 page/task 身份，回读完整正文、数值、来源、父页和版本标记后才确认。大报告确定分段，消耗式标记续写防止重复追加；未知响应先调和，人工改动或多候选保留待核对。
- 已关闭父操作取消后晚注册子执行继续运行的竞争；失败研究后新增排队输入不遮住原执行，也不占住显式恢复位置。

## 验证结果

全部命令均使用 Python 3.11.17 的项目 `.venv`。当前运行环境的 `NO_PROXY`/`no_proxy` 存在不合法端口，测试进程隔离这两个变量，生产代码未掩盖环境错误。

| 检查 | 结果 | 原始证据 |
|---|---|---|
| 全量适用测试 | 5520 通过、6 跳过；10 条来自 Docling 的第三方弃用警告 | `workspace/tmp/alpha-validation/alpha-final-required-tests.txt` |
| 全量类型检查 | pyright 0 错误、0 警告 | `workspace/tmp/alpha-validation/alpha-final-pyright.txt` |
| 研究/Telegram/Notion 等最终专项与覆盖率 | 279 通过；新增材料、Fins 处理、发布文件覆盖率 92%–100%，Telegram daemon 81% | `workspace/tmp/alpha-validation/alpha-final-coverage-tests.txt`、`alpha-final-coverage.json` |
| CLI 完整研究流程 | 3 项通过；新研究命令模块覆盖率 98.9%，含真实 Host 执行与显式恢复，仅替换模型 | `workspace/tmp/alpha-validation/final-cli-workflow-tests.txt`、`final-cli-workflow-coverage.json` |
| 父取消作用域 | 2 项通过，作用域模块 100%；相关执行器专项 56 通过 | `workspace/tmp/alpha-validation/parent-scope-coverage.json`、`parent-cancellation-tests.txt` |
| 首次并发研究库初始化 | 20 轮 × 8 并发连接通过 | `workspace/tmp/alpha-validation/wal-stress.txt` |
| wheel 构建与独立安装 | 五个入口可加载，51 份方法资源可读，所有 alpha 模块来自安装目录 | `workspace/tmp/alpha-validation/alpha-final-wheel-build.txt`、`alpha-final-wheel-install.txt`、`alpha-final-wheel-smoke.txt` |
| 新安装与旧命名升级旅程 | 两研究独立 Session、材料、状态、停止、归档/打开、隔离计算通过；保留旧状态 | `workspace/tmp/alpha-validation/alpha-final-wheel-smoke.txt`；迁移专项见 program.md |
| 文档与修改格式 | 计划严格校验、`git diff --check` 通过 | `workspace/tmp/alpha-validation/alpha-final-document-checks.txt` |

全量测试命令：

```bash
source .venv/bin/activate
env -u NO_PROXY -u no_proxy pytest -m 'not e2e and not slow' -q --no-header
pyright
```

模型流在研究旅程中被替换，Service、Host、SQLite、文件快照、工具执行及 HTTP 编码使用实际实现；Telegram/Notion 的 HTTP 远端为状态化模拟服务。Fins 验证实际解析 PDF，不替换 Docling。wheel 安装检查隔离了源码导入，使用当前环境已安装的依赖；没有另行解析一套全新依赖环境。

## 运行与剩余外部验证

安装与常用命令见[用户手册](../../README.md)，架构和任务依据见[设计](design.md)与[执行记录](program.md)。本地 Codex 已登录时运行 `alpha init --base ./workspace --codex`，无需模型 API Key；该明确选择将工作区 scene 切到 codex-local。当前工作区已执行成功。

Telegram 默认复用 Codex `mcp_servers.telegram.env.TELEGRAM_BOT_TOKEN`，无该连接时读取 Codex 用户目录的 `alpha/credentials.toml` 中 `[telegram].bot_token`（权限 `0600`），可用 `ALPHA_TELEGRAM_BOT_TOKEN` 显式覆盖；仍需明确允许的 user ID，并在 BotFather 启用私聊话题。先运行 `alpha-telegram --base ./workspace --user <USER_ID> --check`，再去掉 `--check` 启动。

Notion 默认复用 Codex `mcp_servers.notion.env.NOTION_TOKEN`，`ALPHA_NOTION_TOKEN` 可显式覆盖；该 connection 需有父页写权限。默认目标是已只读核实的 [Invest](https://www.notion.so/8b6f0c8fc1264555b531281fbb0b96bc)，可在工作区 `config/notion.json` 显式设置固定父页 ID；不按同名搜索。Codex 当前本地保存的 token 已实际通过只读预检，不复制登录或连接密钥。

部署凭据可用后执行：创建两个同公司不同问题 → 原生话题切换 → 发一般材料和 `/filing` 财报 → 停止与重启 → 更新为 v2 → 点击旧 v1 的推送按钮 → 在 Invest 核对其仍为 v1、表格和引用完整 → 再推送 v2。该步骤验证实际客户端与远端 Markdown 归一化行为，当前未标记通过。

PDF 文本读取需要系统 Poppler `pdftotext`；扫描件不伪造文字，结构化财报处理可显式调用既有 Docling 能力。Docling 当前转换属于协作取消，停止会等待当前转换收尾。正文单块超分段上限、回读截断、未知块或人工改动均保持明确失败或待核对，不能当作成功。

跨系统未知副作用无法单凭本地状态承诺 exactly-once。系统以固定版本、唯一远端标记、回读、持久身份和拒绝盲重建降低重复风险；找不到页面或发现多页时，需核对远端实际结果后处理。未做生产部署、公共分发或远端仓库改名。

## 本地 Codex 追加验收

- 全量适用测试 5536 通过、6 跳过：`workspace/tmp/alpha-validation/codex-full-tests.txt`；全量 pyright 零错误：`codex-final-pyright.txt`。
- 接入专项 299 项与原生协议/凭据/迁移专项 15 项通过；新增生产文件覆盖率 86.9%–96%：`codex-integration-tests.txt`、`codex-focused-tests.txt`、`codex-coverage.json`。
- 真实本地 Codex 读取已导入材料并产生正式不可变报告版本：`codex-live-research.txt`。真实 Host 取消后 Run 为 CANCELLED、活跃 Run 和 permit 为零：`codex-live-cancel.txt`。这两项使用实际模型与实际工具，没有替换模型流。
- 当前工作区初始化实际通过：`codex-workspace-init.txt`；原有冲突仅为两套空 Fins 脚手架，已保留新侧空目录副本，旧侧由命名迁移保留原件，未合并或删除业务数据：`codex-empty-scaffold-backup.txt`。
- Codex 保存的 Notion token 读取当前工作区配置的 Invest 实际通过：`codex-notion-readonly.txt`；该阶段仅验证只读；本次真实写入结果见下节。Telegram 凭据已安全保存且 alpha 读取通过；真实 getMe 确认为 @spiritswordbot，webhook 为空，但私聊话题未开启，allowed_user_ids 仍为空。只读证据见 `telegram-live-preflight.txt`，未轮询或发送消息。新增配置和 Telegram/研究入口专项 35 项通过，修改文件覆盖率 97%–98%：`telegram-credentials-tests.txt`、`telegram-credentials-coverage.json`；追加全量类型检查见 `telegram-credentials-pyright.txt`。
- 最新 wheel 构建、独立安装与新旧工作区旅程见 `codex-wheel-build.txt`、`codex-wheel-install.txt`、`codex-wheel-smoke.txt`。

真实联调首次发现报告 evidence 的 accessed_at 缺失或未带时区，运行时校验正确拒绝，未产生伪成功版本。现已补齐必填结构/分类枚举/时间格式提示，材料读取返回真实 accessed_at；重新执行真实模型旅程通过，未放宽时间校验。


## 结构化财报与外部入口验收

- 全量测试 **5609 通过、6 跳过**，见 `workspace/tmp/alpha-validation/alpha-analysis-delivery-tests.txt`；随后503已提交身份恢复专项 **40 通过**，见 `notion-committed-id-green.txt`。最终全量 pyright **0 错误/0 警告**，见 `alpha-analysis-committed-id-pyright.txt`。17个新增生产模块的覆盖率最低 **85.9%**，见 `analysis-final-new-module-coverage.json`。
- 最终 wheel 在独立目录安装，所有alpha模块均从安装包加载；6个console入口、52份固定方法资产、`alpha-research` skill、干净工作区及真实stdio SDK工具发现/会话读取通过，见 `analysis-wheel-final-build.txt`、`analysis-wheel-final-install.txt`、`analysis-wheel-final-smoke.txt`。复用现有已验证依赖，未声称重新解析全新依赖环境。
- 当前 coding agent 通过已安装的 `alpha-mcp` 直接研究，未启动第二个模型。5份BABA源文件实际完成15次三表读取及7次原表核对；缓存二次命中。实际验收暴露并修复期间后缀、便利币种、括号负号及XBRL登记缓存问题。证据在 `baba-v2-retry-responses/`，最终校验为 `60-validate-final.json`，143个数据指标、9项加总检查通过。财报公开时刻、原表语义和投资判断仍与算术检查分开。
- 公开入口完成完整候选稿、JSON Pointer正文修订和ID/hash提交，形成 `revision_7cd6c3aec7c252f4afdf07727b21377f`，来源Run `run_12cce7fca6ea`，见 `61-finish.json`。正式报告位于 `workspace/.alpha/research/artifacts/research_813b744e59c84e9e89bf6f56383803a5/revisions/revision_7cd6c3aec7c252f4afdf07727b21377f/report.md`。v1正文SHA256仍为 `7df9defa70dd187f6ab461bfc6222ca8693bfbf17c0a9085753d2477d383f7c7`。
- BABA的完成后发布意图 `publication_81b5a273eb3c5794bd8996cd94567592` 已持久接受，目标固定为既定Invest。主题首次创建返回503，完整子页扫描和独立Markdown回读未找到唯一主题；没有重复创建或伪报成功。当前状态见 `baba-v2-notion-pending.json`。需要原页身份，或用户核实未生成后明确决定是否重建，再继续同一v2的发布和回读。
- 客户端补齐官方503响应中 `additional_data.committed_resource_id` 的保留；主题与版本业务先持久身份，再回读，测试覆盖两处创建。该修复不能恢复本次较早响应已丢失的身份，不据此把当前归档标成完成。[官方503恢复说明](https://developers.notion.com/reference/request-limits#retry-a-write-that-returns-503)

Codex全局已注册alpha MCP，并安装单一来源的alpha-research skill链接；凭据仍从Codex本地配置读取。新Codex会话可使用 `$alpha-research` 创建或继续主题，明确完成后推送时设置发布策略。当前会话的工具目录不会热加载新配置。
