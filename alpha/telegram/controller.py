"""Telegram 研究交互控制器；入站更新只接受业务输入，不等待模型执行。"""

from dataclasses import dataclass

from alpha.contracts.publication import PublishResearchRequest, ResearchPublicationGateway
from alpha.contracts.research import ResearchConflictError, ResearchState, ResumeResearchTurnRequest, SubmitResearchTurnRequest
from alpha.services.research_service import ResearchService
from alpha.services.research_material_service import ResearchMaterialService
from alpha.contracts.research_materials import MAX_MATERIAL_BYTES
from alpha.telegram.actions import ResearchAction
from alpha.telegram.cards import TelegramCard, TelegramCards
from alpha.telegram.client import TelegramApiError
from alpha.telegram.report_delivery import TelegramReportDelivery
from alpha.telegram.research_topics import TelegramResearchTopics
from alpha.telegram.sender import TelegramSender
from alpha.telegram.types import TelegramIncoming
from alpha.telegram.publication_delivery import publication_status_text

_HELP_TEXT = (
    "alpha · 投研助手\n\n/new 研究问题 — 创建独立话题并开始研究\n/researches [关键词] — 查看多项研究\n"
    "/status [research_id] — 查看状态\n/stop — 停止当前话题的研究\n/bind research_id — 显式绑定当前话题\n"
    "/resume turn_id — 显式恢复失败输入\n/publication publication_id — 查询推送\n\n"
    "在研究话题内发送补充问题或 PDF/TXT/Markdown/HTML。财报附件说明用 /filing TICKER FORM_TYPE [研究要求]。"
    "报告卡可以获取文件和推送指定版本至 Invest。"
)


@dataclass(frozen=True)
class TelegramController:
    """白名单私聊入口，按钮目标必须通过持久 token 校验。"""

    allowed_users: frozenset[int]
    research: ResearchService
    topics: TelegramResearchTopics
    cards: TelegramCards
    sender: TelegramSender
    reports: TelegramReportDelivery
    publication: ResearchPublicationGateway | None = None
    materials: ResearchMaterialService | None = None

    async def handle(self, incoming: TelegramIncoming) -> None:
        """接受一个持久更新。参数：消息。返回：无。异常：授权目标冲突、API 或业务错误。"""
        # 创建话题的服务消息可能由 Bot 发出，严格限制为已授权私聊和本 Bot 的随机操作标记。
        if (incoming.private and incoming.chat_id in self.allowed_users and incoming.topic_name is not None
                and incoming.user_id in (incoming.chat_id, self.topics.bot_id)):
            self.topics.created_event(incoming)
            return
        if not incoming.private or incoming.user_id not in self.allowed_users or incoming.chat_id != incoming.user_id:
            return
        key = f"telegram:{self.topics.bot_id}:update:{incoming.update_id}"
        if incoming.callback_data is not None:
            await self._callback(incoming, key)
            return
        text = incoming.text.strip()
        if incoming.document is not None:
            await self._document(incoming, key)
            return
        if text.startswith("/"):
            await self._command(incoming, key, text)
            return
        binding = self.topics.resolve(incoming)
        if binding is None:
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, "请发送 /new 研究问题，或从原生话题列表进入研究。已有话题可用 /bind research_id 显式绑定。")
            return
        turn = self.research.submit(SubmitResearchTurnRequest(binding.research_id, str(incoming.user_id), key, text))
        await self.sender.text(key + ":accepted", incoming.chat_id, incoming.thread_id, f"研究输入已保存。\n{turn.turn_id}")

    async def _document(self, incoming: TelegramIncoming, key: str) -> None:
        """在当前绑定研究接受真实附件。参数：消息、稳定键。返回：无。异常：未配置、未绑定或超限。"""
        document = incoming.document
        if document is None or self.materials is None:
            raise ValueError("材料导入服务未启用")
        research_id = self._research_id(incoming)
        if document.size is not None and document.size > MAX_MATERIAL_BYTES:
            raise ValueError("附件声明大小超过 20 MiB")
        content = await self.sender.client.download_document(document.file_id, max_bytes=MAX_MATERIAL_BYTES)
        turn = self.materials.accept(research_id, str(incoming.user_id), key, document.name, content, incoming.text)
        await self.sender.text(key + ":accepted", incoming.chat_id, incoming.thread_id,
                               f"原件已保存，正文提取与核验进入下一轮研究。\n{turn.turn_id}")

    async def _send_card(self, key: str, incoming: TelegramIncoming, card: TelegramCard) -> None:
        """发送固定卡片。参数：稳定键、入站地址、卡片。返回：无。异常：发送错误。"""
        await self.sender.text(key, incoming.chat_id, incoming.thread_id, card.text, keyboard=card.keyboard)

    def _research_id(self, incoming: TelegramIncoming, explicit: str = "") -> str:
        """解析显式研究或当前绑定。参数：消息、可选 ID。返回：研究 ID。异常：未选择研究。"""
        if explicit:
            self.research.overview(explicit, str(incoming.user_id))
            return explicit
        binding = self.topics.resolve(incoming)
        if binding is None:
            raise ValueError("请进入研究话题，或在命令后提供 research_id")
        return binding.research_id

    async def _command(self, incoming: TelegramIncoming, key: str, text: str) -> None:
        """处理明确命令。参数：消息、稳定键、命令文本。返回：无。异常：命令或业务错误。"""
        parts = text.split(maxsplit=1)
        command = parts[0].split("@", maxsplit=1)[0]
        argument = parts[1].strip() if len(parts) > 1 else ""
        owner = str(incoming.user_id)
        if command in ("/start", "/help"):
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, _HELP_TEXT)
        elif command == "/new":
            if not argument:
                raise ValueError("用法：/new 要研究的问题")
            record = await self.topics.create(incoming, argument, key)
            await self.sender.text(key + ":created", incoming.chat_id, incoming.thread_id, f"研究已创建，请从原生话题列表进入。\n{record.title}\n{record.research_id}")
        elif command == "/researches":
            await self._send_card(key, incoming, self.cards.listing(key, incoming.user_id, incoming.chat_id, incoming.thread_id, query=argument))
        elif command == "/status":
            research_id = self._research_id(incoming, argument)
            await self._send_card(key, incoming, self.cards.status(key, incoming.user_id, incoming.chat_id, incoming.thread_id, self.research.overview(research_id, owner)))
        elif command == "/stop":
            research_id = self._research_id(incoming, argument)
            self.research.stop(research_id, owner, key)
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, "已请求停止当前边界内的研究；执行中的工具会协作收尾，之后发送的新输入会保留。")
        elif command == "/bind":
            if not argument or incoming.thread_id is None:
                raise ValueError("请在目标研究话题内发送 /bind research_id")
            self.topics.bind(argument, incoming.user_id, incoming.chat_id, incoming.thread_id)
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, "该话题已绑定研究。后续输入会进入这项研究。")
        elif command == "/resume":
            if not argument:
                raise ValueError("用法：/resume turn_id")
            turn = self.research.resume(ResumeResearchTurnRequest(argument, owner, key))
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, f"恢复请求已保存。\n{turn.turn_id}")
        elif command == "/publication":
            if self.publication is None or not argument:
                raise ValueError("请配置 Notion 后使用 /publication publication_id 查询推送状态")
            publication = self.publication.get(argument, owner)
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, publication_status_text(publication))
        else:
            raise ValueError("未知命令，请发送 /help 查看用法")

    async def _callback(self, incoming: TelegramIncoming, key: str) -> None:
        """处理绑定目标按钮。参数：消息、稳定更新键。返回：无。异常：过期、越权、业务或交付错误。"""
        token = self.cards.actions.resolve(incoming.callback_data or "", user_id=incoming.user_id, chat_id=incoming.chat_id, thread_id=incoming.thread_id)
        if incoming.callback_id is not None:
            try:
                await self.sender.client.answer_callback(incoming.callback_id)
            except TelegramApiError:
                # 按钮应答只是结束客户端等待动画，失败不改变已持久输入的业务接受语义。
                pass
        if token.action == ResearchAction.LIST:
            await self._send_card(key, incoming, self.cards.listing(key, incoming.user_id, incoming.chat_id, incoming.thread_id,
                                                                  offset=token.page_offset, state=token.list_state))
            return
        if token.research_id is None:
            raise ValueError("按钮缺少研究目标")
        view = self.research.overview(token.research_id, str(incoming.user_id))
        if token.expected_version is not None and token.expected_version != view.research.version:
            raise ResearchConflictError("研究已更新，请刷新列表或状态卡")
        if token.action == ResearchAction.STATUS:
            await self._send_card(key, incoming, self.cards.status(key, incoming.user_id, incoming.chat_id, incoming.thread_id, view))
        elif token.action == ResearchAction.STOP:
            self.research.stop(token.research_id, str(incoming.user_id), token.token, expected_version=token.expected_version)
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, "已请求停止，正在等待执行资源收敛。")
        elif token.action in (ResearchAction.ARCHIVE, ResearchAction.REOPEN):
            operation = self.research.archive if token.action == ResearchAction.ARCHIVE else self.research.reopen
            operation(token.research_id, str(incoming.user_id))
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, "研究已归档。" if token.action == ResearchAction.ARCHIVE else "原研究已重新打开。")
        elif token.action in (ResearchAction.UPDATE, ResearchAction.COUNTERCASE):
            if view.research.state != ResearchState.ACTIVE:
                raise ValueError("请先重新打开研究")
            instruction = "收集增量材料，核验论点变化并提交新版本" if token.action == ResearchAction.UPDATE else "独立检查反方解释、反证和失效条件并提交新版本"
            self.research.submit(SubmitResearchTurnRequest(token.research_id, str(incoming.user_id), token.token, f"针对报告 {token.revision_id}：{instruction}"))
            await self.sender.text(key, incoming.chat_id, incoming.thread_id, "研究输入已保存，结果会投递到原研究话题。")
        elif token.action in (ResearchAction.REPORT, ResearchAction.PUBLISH):
            revision = next((item for item in view.revisions if item.revision_id == token.revision_id), None)
            if revision is None:
                raise ValueError("按钮指定的正式版本不存在")
            if token.action == ResearchAction.REPORT:
                await self.reports.file(f"file:{token.token}", revision, incoming.user_id, incoming.chat_id, incoming.thread_id)
            else:
                if self.publication is None:
                    raise ValueError("尚未配置 Notion connection；请配置 ALPHA_NOTION_TOKEN 和 Invest 目标后启用发布。")
                publication = self.publication.request_publish(PublishResearchRequest(revision.revision_id, str(incoming.user_id), token.token))
                await self.sender.text(key, incoming.chat_id, incoming.thread_id, publication_status_text(publication))
