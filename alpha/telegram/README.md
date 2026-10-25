# Telegram 渠道开发手册

入口为 `alpha-telegram` 或 `python -m alpha.telegram`，使用现有 `httpx`，不引入 Bot SDK。首版仅接收配置白名单中的私聊用户。启动时预检 `getMe.has_topics_enabled` 和 webhook；不自动修改 Bot 设置。每个工作区内，同一 Bot 由独占文件锁约束。

协议以 [Telegram Bot API](https://core.telegram.org/bots/api) 为准。私聊原生话题使用 `message_thread_id`；不将频道私信的 `direct_messages_topic_id` 混入此流程。

`database.py` 保存当前渠道 schema，`alpha init` 的 `telegram_store_init` 插件显式初始化；未知 schema 不兼容读。各窄仓储固定 Bot ID，数据不会跨 Bot 解析。

- `inbox.py`：整批原始更新和下一 offset 同事务提交。重启后可重新派发已落盘更新，研究输入以稳定请求键去重。
- `topics.py`：先保存随机操作标记，再创建话题。网络结果未知或创建中断不自动重建；可用包含完整标记的服务消息调和，或在目标话题显式 `/bind`。确认话题和研究绑定后才进入渠道研究调度。
- `actions.py`：按钮 token 固定操作者、私聊、话题、动作、研究和版本，默认有效七天。停止按钮还校验研究版本，避免旧卡片停止后来接受的输入。
- `deliveries.py`：消息与文件分别保存意图和 message ID。发送中崩溃转为未知，明确限流可重试；未知结果不盲目重发。文字与按钮在首次发送前冻结，重试不会换成后来状态。

`controller.py` 只调用研究、渠道绑定、reply delivery 等 Service。`daemon.py` 将收信、inbox 派发、研究调度和正式摘要交付分为四条独立协程；配置 Notion 后另有独立发布协程。研究通过 Host 运行，不在渠道层复制 Run 状态。退出会取消并等待本实例持有的研究任务和发布线程。进度卡只显示已观察阶段，不输出内部 reasoning。

`cards.py` 提供分页列表、状态、归档过滤、关键词检索及固定版本报告卡。用户从 Telegram 原生话题列表切换研究，首版不使用未经验证的话题深链。报告通过 Markdown 附件交付。

`report_delivery.py` 的正式摘要使用 Host reply outbox；渠道回执先保存远端消息 ID，再确认 outbox。正式版本生成、摘要投递和文件投递是不同结果。发布按钮通过 `ResearchPublicationGateway` 接受指定版本的显式意图；未装配 Notion connection 时明确提示配置要求。

`publication_delivery.py` 将发布状态和页面链接发回原研究话题。失败重试按钮生成新的明确授权键；原失败键重放不会重新执行。`/publication <publication_id>` 查询当前推送状态。发布消费者通过 `PublicationWorker` 持有线程，退出时先把取消请求交给 Host，再等待有界 HTTP 收尾；已知 page/task 身份先落盘，不因协作取消丢失。

当前普通文件消息不会被当作已提取内容；财报应使用 Fins 导入入口，研究材料的渠道导入仍需接线。

验证：`pytest tests/telegram` 使用真实 SQLite、HTTP 编码和 Service/Host/scene，仅隔离 Telegram 远端与模型流。覆盖双研究隔离、分页和旧按钮、创建丢响应、摘要/附件去重、发送未知结果、显式恢复与完整 daemon 生命周期。真实 Bot 的客户端行为和权限需单独验收。

研究话题可直接接收 PDF/TXT/Markdown/HTML 文件，下载检查实际 20 MiB 上限，未知文件格式明确拒绝；附件说明 `/filing TICKER FORM_TYPE [要求]` 将财报交由 Fins 保存。接收建立新输入，实际提取在 Host 研究工具内执行；重复更新不重复排队，v2 保留 v1。状态卡保留最近执行输入及恢复命令，较新的排队输入不会遮住失败输入。

启动入口默认复用 Codex 保存的 Telegram/Notion 服务 env 凭据，显式 ALPHA_* 环境变量优先。无 Telegram MCP 连接时读取 Codex 用户目录内 `alpha/credentials.toml` 的 `[telegram].bot_token`，文件权限设为 `0600`；不注册虚假 MCP 服务。用户白名单仍需明确配置，不能从 Bot token 或首条消息推断。`--check` 只读验证 Bot 身份、私聊话题和 webhook 条件，不发送消息。模型使用本地 Codex 时，先 `alpha init --codex`。
