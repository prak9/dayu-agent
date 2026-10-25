# Notion HTTP 适配开发手册

`NotionClient` 使用现有 `httpx` 和固定的 `Notion-Version: 2026-03-11`。connection token 通过装配注入；入口可直接复用 Codex config.toml 中 Notion 服务已保存的 token，不读取或复制 ChatGPT 登录令牌。客户端不决定发布权限、目标版本或重试次数。

支持读取页面和直接父页、原生 Markdown 创建/回读/替换、异步任务轮询、完整枚举直接子页。异步写入返回 `NotionTask`，不被当作已完成页面；回读保留 `truncated` 与 `unknown_block_ids`，供业务层判断完整性。

HTTP 响应有大小上限，连接有超时，操作间检查 Host 取消令牌。写入收到 page/task 身份后先交回业务层持久保存，避免紧随其后的取消丢失已知远端结果。错误保留安全分类和 Retry-After，不包含 token；写请求不在客户端自动重试。

创建、超时等写入失败区分明确拒绝和结果未知；未知结果必须由发布业务调和。`child_pages` 枚举固定父页的直接子页候选；异步轮询只拼接官方 API 路径，不跟随响应中任意 URL。

503 响应若提供 `additional_data.committed_resource_id`，客户端保留该身份，主题或版本业务先持久保存再回读；不会重新创建。依据为官方[503 写入恢复说明](https://developers.notion.com/reference/request-limits#retry-a-write-that-returns-503)。没有已知身份且无法找到唯一标记时保持待核对，不能仅因未找到就认定未写入。

协议依据：[创建页面](https://developers.notion.com/reference/post-page)、[Markdown 内容](https://developers.notion.com/guides/data-apis/working-with-markdown-content)、[Markdown 回读](https://developers.notion.com/reference/retrieve-page-markdown)。测试为 `pytest tests/integrations/notion`，不连接真实账号。

`services.publication_service` 校验所有权和正式版本，冻结正文并通过 Host 的独立操作入口执行。发布不占研究 Session 写互斥。`publication_operation` 保存已知 page/task 身份、轮询异步任务，回读核对直接父页、完整性标记、正文/数值/币种/来源序列及发布标记后才确认成功。

直接父页现在是固定研究主题，层次为 Invest 根目录、研究主题页、不可变版本页。`services.notion_topic_service` 在同一 Host 发布执行内创建或只读找回主题，主题身份由研究 ID/根目录确定；主题创建响应丢失、异步身份、租约接管和已知页移动均保持可核对状态，不按显示标题重建。

创建响应丢失后先枚举固定父页的候选子页，核对完整发布标记；唯一匹配关联原页，多匹配或未找到保留待核对。未找到不证明未创建。已发布页不进入后台写入路径。一般 GFM 表格转换为官方增强 Markdown 表格，代码块保持原文，本地路径只作为文字引用。

`PublicationWorker` 使异步入口持有同步 HTTP 线程的整个生命周期。退出先向 Host 请求取消并等待线程，HTTP 已返回的页面/任务身份优先持久保存。取消为协作语义，已完成且核验通过的远端副作用不会被伪装成未发生。

大正文使用 [update_content](https://developers.notion.com/reference/update-page-markdown) 将唯一旧哨兵替换成下一固定段与新哨兵。消费过的标记不能重复追加；每次写后回读完整前缀，全部核验才发布。异步追加同样持久 task ID，任务过期回读已知页，未知创建回查原候选。不得用整页替换修复人工改动。
