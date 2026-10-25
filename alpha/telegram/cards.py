"""Telegram 多研究列表和状态卡；只显示可观察阶段，不暴露内部推理。"""

from dataclasses import dataclass

from alpha.contracts.agent_types import JsonValue
from alpha.contracts.research import ResearchRevision, ResearchState
from alpha.contracts.research_execution import ResearchOverview
from alpha.contracts.run import RunState
from alpha.services.research_service import ResearchService
from alpha.telegram.actions import ResearchAction, SQLiteTelegramActions

_PAGE_SIZE = 5
_TITLE_CHARS = 80
_SUMMARY_CHARS = 1200
_STATUS_TEXT: dict[RunState, str] = {
    RunState.CREATED: "已受理，等待执行", RunState.QUEUED: "等待宿主资源", RunState.RUNNING: "研究中",
    RunState.SUCCEEDED: "执行完成", RunState.FAILED: "执行失败，可显式恢复", RunState.CANCELLED: "已停止或超时",
    RunState.UNSETTLED: "执行中断，需要核对后恢复",
}


@dataclass(frozen=True)
class TelegramCard:
    """纯文本和已有权限绑定的按钮行。"""

    text: str
    keyboard: list[JsonValue]


@dataclass(frozen=True)
class TelegramCards:
    """按用户拥有的研究生成卡片；短 token 对应服务端固定目标。"""

    research: ResearchService
    actions: SQLiteTelegramActions

    def _button(
        self, key: str, label: str, *, user_id: int, chat_id: int, thread_id: int | None, action: ResearchAction,
        research_id: str | None = None, revision_id: str | None = None, expected_version: int | None = None,
        page_offset: int = 0, list_state: str | None = None,
    ) -> dict[str, JsonValue]:
        """生成固定目标按钮。参数：卡片键、标签、地址及显式目标。返回：Bot 按钮。异常：幂等键冲突。"""
        token = self.actions.issue(key, user_id=user_id, chat_id=chat_id, thread_id=thread_id, action=action, research_id=research_id,
                                   revision_id=revision_id, expected_version=expected_version, page_offset=page_offset, list_state=list_state)
        return {"text": label, "callback_data": token.token}

    def listing(self, key: str, user_id: int, chat_id: int, thread_id: int | None, *, offset: int = 0, state: str | None = None, query: str = "") -> TelegramCard:
        """生成分页研究列表。参数：卡片键、地址、游标、状态、查询。返回：卡片。异常：状态或游标非法。"""
        if offset < 0:
            raise ValueError("研究列表游标非法")
        selected_state = ResearchState(state) if state is not None else None
        records = [item for item in self.research.list_research(str(user_id))
                   if (selected_state is None or item.state == selected_state) and (not query or query.casefold() in (item.title + item.question + " ".join(item.subjects)).casefold())]
        page = records[offset:offset + _PAGE_SIZE]
        lines = [f"alpha · 我的研究（{len(records)} 项）", "从 Telegram 原生话题列表切换研究。"]
        buttons: list[JsonValue] = []
        for record in page:
            view = self.research.overview(record.research_id, str(user_id))
            lines.extend(("", f"{record.title[:_TITLE_CHARS]} · {'已归档' if record.state == ResearchState.ARCHIVED else '活跃'}",
                          f"{_execution_status(view)} · 报告 {len(view.revisions)} 版 · 排队 {view.queued_count}"))
            buttons.append([self._button(f"{key}:status:{record.research_id}", f"查看 · {record.title[:20]}", user_id=user_id,
                                         chat_id=chat_id, thread_id=thread_id, action=ResearchAction.STATUS, research_id=record.research_id)])
        if not records:
            lines.append("尚无符合条件的研究。发送 /new 研究问题 新建。")
        navigation: list[JsonValue] = []
        # 检索结果不提供丢失查询条件的翻页；用户可缩小查询或打开完整列表。
        if not query:
            for label, target in (("上一页", offset - _PAGE_SIZE), ("下一页", offset + _PAGE_SIZE)):
                if target >= 0 and target < len(records):
                    navigation.append(self._button(f"{key}:page:{target}", label, user_id=user_id, chat_id=chat_id, thread_id=thread_id,
                                                   action=ResearchAction.LIST, page_offset=target, list_state=state))
        if navigation:
            buttons.append(navigation)
        buttons.append([self._button(f"{key}:active", "活跃研究", user_id=user_id, chat_id=chat_id, thread_id=thread_id, action=ResearchAction.LIST, list_state=ResearchState.ACTIVE.value),
                        self._button(f"{key}:archived", "已归档", user_id=user_id, chat_id=chat_id, thread_id=thread_id, action=ResearchAction.LIST, list_state=ResearchState.ARCHIVED.value)])
        return TelegramCard("\n".join(lines), buttons)

    def status(self, key: str, user_id: int, chat_id: int, thread_id: int | None, view: ResearchOverview) -> TelegramCard:
        """生成研究详情。参数：卡片键、地址、已授权详情。返回：状态卡。异常：按钮持久化失败。"""
        record = view.research
        key = f"{key}:version:{record.version}"
        text = f"alpha · {record.title[:_TITLE_CHARS]}\n{record.research_id}\n{_execution_status(view)}\n排队 {view.queued_count} · 正式报告 {len(view.revisions)} 版"
        if view.active_turn is not None:
            text += f"\n输入 {view.active_turn.turn_id}"
        elif view.latest_turn is not None:
            text += f"\n最近输入 {view.latest_turn.turn_id}"
        if view.run is not None:
            text += f"\nRun {view.run.run_id}"
            if view.execution_turn is not None and view.run.state in (RunState.FAILED, RunState.UNSETTLED, RunState.CANCELLED):
                text += f"\n恢复：/resume {view.execution_turn.turn_id}"
        buttons: list[JsonValue] = []
        if record.state == ResearchState.ARCHIVED:
            action, label = ResearchAction.REOPEN, "重新打开"
        else:
            action, label = ResearchAction.ARCHIVE, "归档"
            if view.active_turn is not None or view.queued_count:
                buttons.append([self._button(f"{key}:stop", "停止研究", user_id=user_id, chat_id=chat_id, thread_id=thread_id,
                                             action=ResearchAction.STOP, research_id=record.research_id, expected_version=record.version)])
        buttons.append([self._button(f"{key}:{action.value}", label, user_id=user_id, chat_id=chat_id, thread_id=thread_id,
                                     action=action, research_id=record.research_id, expected_version=record.version)])
        if view.revisions:
            revision = view.revisions[-1]
            buttons.append([self._button(f"{key}:report", f"完整报告 v{revision.number}", user_id=user_id, chat_id=chat_id, thread_id=thread_id,
                                         action=ResearchAction.REPORT, research_id=record.research_id, revision_id=revision.revision_id)])
        return TelegramCard(text, buttons)

    def report(self, key: str, user_id: int, chat_id: int, thread_id: int | None, view: ResearchOverview, revision: ResearchRevision) -> TelegramCard:
        """生成固定版本报告卡。参数：卡片键、地址、详情、指定版本。返回：摘要卡。异常：读取或按钮错误。"""
        text = self.research.read_report(revision.revision_id, str(user_id))
        title = f"研究完成 · {view.research.title[:_TITLE_CHARS]} · v{revision.number}\n截止 {revision.as_of.isoformat()}\n\n"
        row: list[JsonValue] = []
        for action, label in ((ResearchAction.REPORT, "完整报告"), (ResearchAction.UPDATE, "更新研究"),
                              (ResearchAction.COUNTERCASE, "检查反方"), (ResearchAction.PUBLISH, "推送到 Invest")):
            row.append(self._button(f"{key}:{action.value}", label, user_id=user_id, chat_id=chat_id, thread_id=thread_id, action=action,
                                    research_id=view.research.research_id, revision_id=revision.revision_id,
                                    expected_version=None))
        return TelegramCard(title + text[:_SUMMARY_CHARS] + f"\n\n版本 {revision.revision_id}", [row[:2], row[2:]])


def _execution_status(view: ResearchOverview) -> str:
    """投影实际业务阶段。参数：详情。返回：状态文本。异常：无。"""
    if view.run is not None:
        return _STATUS_TEXT[view.run.state]
    return "等待派发" if view.queued_count else "等待输入"
