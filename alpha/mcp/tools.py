"""外部 coding agent 的交互层，只调用 Service，不启动嵌套模型。"""

import json
from dataclasses import asdict, dataclass
from typing import cast

from mcp.server import MCPServer

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.publication import PublishResearchRequest
from alpha.contracts.research import CreateResearchRequest, ResearchExecutionMode, ResearchPublicationPolicy, ResearchRevision, ResumeResearchTurnRequest, SubmitResearchTurnRequest
from alpha.contracts.research_financials import decode_financial_requirements
from alpha.services.external_research_service import ExternalResearchService
from alpha.services.publication_service import PublicationService
from alpha.services.research_service import ResearchService
from alpha.contracts.publication import PublicationState
from alpha.research.report_encoding import decode_summary
from alpha.research.report_composer import summary_markdown

_MAX_ARGUMENT_BYTES = 20 * 1024 * 1024
_MAX_SESSION_PAGE = 50


def _delivery_markdown(presentation: dict[str, JsonValue], publication: dict[str, JsonValue] | None) -> str:
    """呈现判断及可信交付状态。参数：正式版本呈现、实际发布记录。返回：聊天Markdown。异常：摘要损坏。"""
    summary = presentation.get('summary')
    text = summary_markdown(decode_summary(summary)) if isinstance(summary, dict) else '此版本未提供与正文绑定的结构化摘要。'
    text += f"\n\n报告状态：正式版本 v{presentation['number']}；信息截止：{presentation['as_of']}。"
    if publication is None:
        return text + '\n\nNotion：未发现当前目标下的发布意图。'
    url = publication.get('page_url')
    if publication.get('state') == PublicationState.PUBLISHED.value and isinstance(url, str) and url:
        return text + f'\n\n[Notion完整报告]({url})'
    return text + f"\n\nNotion：{publication.get('state')}；尚不能确认完整报告已交付。"


def _json(value: JsonValue) -> str:
    """编码协议结果。参数：JSON。返回：文本。异常：序列化错误。"""
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


@dataclass(frozen=True)
class AlphaMcpTools:
    """用户身份固定于本地进程配置，不接受模型伪造身份。"""

    research: ResearchService
    external: ExternalResearchService
    owner_id: str
    publication: PublicationService | None

    async def sessions(self, offset: int = 0, limit: int = 20) -> str:
        """分页查看当前用户的研究、执行状态和最近版本。参数：偏移、每页数量。返回：简明研究索引 JSON。异常：参数或存储错误。"""
        if offset < 0 or not 1 <= limit <= _MAX_SESSION_PAGE:
            raise ValueError("研究列表的偏移或数量无效")
        all_records = self.research.list_research(self.owner_id)
        rows: list[JsonValue] = []
        for record in all_records[offset:offset + limit]:
            overview = self.research.overview(record.research_id, self.owner_id)
            rows.append({"research_id": record.research_id, "title": record.title, "subjects": list(record.subjects), "state": record.state.value,
                "run_state": overview.run.state.value if overview.run is not None else None,
                "turn_id": overview.execution_turn.turn_id if overview.execution_turn is not None else None,
                "latest_revision_id": overview.revisions[-1].revision_id if overview.revisions else None, "queued_count": overview.queued_count})
        return _json({"sessions": rows, "total": len(all_records), "next_offset": offset + limit if offset + limit < len(all_records) else None})

    async def create(self, question: str, request_key: str, title: str = "", subjects: list[str] | None = None) -> str:
        """创建研究主题；subjects 只填证券代码，证券研究默认必须读取三表。参数：问题、稳定创建键、标题、标的。返回：研究 JSON。异常：冲突。"""
        return _json(cast(JsonValue, asdict(self.research.create(CreateResearchRequest(self.owner_id, request_key, question, tuple(subjects or []), title)))))

    async def begin(self, research_id: str, text: str, request_key: str, financial_requirements_json: str = "[]", publish_on_complete: bool = False) -> str:
        """使用当前 coding agent 直接开始研究；返回句柄和业务工具目录。参数：研究、输入、稳定键、可选财报要求 JSON、明确完成后发布策略。返回：执行 JSON。异常：繁忙或配置缺失。"""
        requirements = decode_financial_requirements(cast(JsonValue, json.loads(financial_requirements_json)))
        return _json(await self.external.begin(SubmitResearchTurnRequest(research_id, self.owner_id, request_key, text,
                     financial_requirements=requirements, execution_mode=ResearchExecutionMode.EXTERNAL,
                     publication_policy=ResearchPublicationPolicy.ON_COMPLETE if publish_on_complete else ResearchPublicationPolicy.MANUAL)))

    async def resume(self, turn_id: str, request_key: str) -> str:
        """显式恢复失败或异常退出的原外部输入，保留原截止和方法。参数：原输入、恢复键。返回：新句柄 JSON。异常：原输入不可恢复。"""
        return _json(await self.external.resume(ResumeResearchTurnRequest(turn_id, self.owner_id, request_key)))

    async def call(self, handle: str, tool_name: str, arguments_json: str, call_id: str) -> str:
        """在 Host 作用域执行 begin 返回的业务工具；同调用 ID 必须对应同参数。参数：句柄、工具、JSON 参数、稳定调用 ID。返回：工具结果 JSON。异常：取消、非法参数或已结束。"""
        if len(arguments_json.encode()) > _MAX_ARGUMENT_BYTES:
            raise ValueError("工具参数超过 20 MiB")
        arguments = cast(JsonValue, json.loads(arguments_json))
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须为 JSON 对象")
        return _json(await self.external.call(handle, tool_name, arguments, call_id))

    async def finish(self, handle: str, candidate_id: str, content_hash: str, call_id: str) -> str:
        """按候选 ID/hash 结束本轮；校验错误保持研究可修订，Host 成功后形成正式版本。参数：句柄、候选、hash、稳定调用 ID。返回：版本或校验错误 JSON。异常：取消或冲突。"""
        result = await self.external.finish(handle, candidate_id, content_hash, call_id)
        return _json({**cast(dict[str, JsonValue], asdict(result)), 'delivery': self._delivery(result.revision_id)}) if isinstance(result, ResearchRevision) else _json(result)

    def _delivery(self, revision_id: str) -> dict[str, JsonValue]:
        """按实际版本和发布投影组装摘要。参数：版本。返回：结构化交付与聊天文本。异常：越权或损坏。"""
        presentation = self.research.report_presentation(revision_id, self.owner_id)
        publications = self.publication.list_for_owner(self.owner_id) if self.publication is not None else []
        matching = next((item for item in publications if item.revision_id == revision_id and self.publication is not None and item.target_id == self.publication.target_id), None)
        publication = cast(dict[str, JsonValue], asdict(matching)) if matching is not None else None
        return {**presentation, 'publication': publication, 'chat_markdown': _delivery_markdown(presentation, publication)}

    async def delivery(self, revision_id: str) -> str:
        """读取完整报告对应的聊天摘要和当前真实交付状态。参数：正式版本。返回：摘要、状态及已确认链接。异常：越权或版本不存在。"""
        return _json(self._delivery(revision_id))

    async def abort(self, handle: str) -> str:
        """停止此连接拥有的研究执行，保留候选稿与读取证据。参数：句柄。返回：停止状态 JSON。异常：宿主错误。"""
        await self.external.abort(handle)
        return _json({"stopped": True})

    async def publish(self, revision_id: str, request_key: str) -> str:
        """明确发布指定正式版本到配置的 Invest/研究主题，重复请求复用同一意图。参数：固定版本、请求键。返回：发布状态 JSON。异常：未配置、越权或缺失。"""
        if self.publication is None:
            raise ValueError("Notion 连接或 Invest 目录尚未配置")
        return _json(cast(JsonValue, asdict(self.publication.request_publish(PublishResearchRequest(revision_id, self.owner_id, request_key)))))

    async def publications(self) -> str:
        """查看已授权发布的状态和页面链接。参数：无。返回：发布列表 JSON。异常：存储错误。"""
        return _json(cast(JsonValue, [asdict(item) for item in self.publication.list_for_owner(self.owner_id)])) if self.publication is not None else _json([])


def register_mcp_tools(server: MCPServer[None], handlers: AlphaMcpTools) -> None:
    """使用官方 SDK 注册控制面工具。参数：服务器、交互服务。返回：无。异常：SDK schema 错误。"""
    server.tool(name="alpha_sessions")(handlers.sessions)
    server.tool(name="alpha_create")(handlers.create)
    server.tool(name="alpha_begin")(handlers.begin)
    server.tool(name="alpha_resume")(handlers.resume)
    server.tool(name="alpha_call")(handlers.call)
    server.tool(name="alpha_finish")(handlers.finish)
    server.tool(name="alpha_abort")(handlers.abort)
    server.tool(name="alpha_publish")(handlers.publish)
    server.tool(name="alpha_publications")(handlers.publications)
    server.tool(name="alpha_delivery")(handlers.delivery)
