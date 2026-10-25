"""Telegram 接收、业务派发、研究执行和结果交付的独立协程。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from contextlib import aclosing
import time
from alpha.contracts.events import AppEventType
from alpha.contracts.research import ResearchConflictError, ResearchState
from alpha.contracts.publication import PublicationState
from alpha.services.publication_worker import PublicationWorker
from alpha.services.research_service import ResearchReportMissingError
from alpha.log import Log
from alpha.telegram.client import TelegramApiError
from alpha.telegram.controller import TelegramController
from alpha.telegram.inbox import SQLiteTelegramInbox
from alpha.telegram.research_topics import TelegramTopicUnknownError
from alpha.telegram.sender import TelegramDeliveryUnknownError
from alpha.telegram.types import TelegramIncoming, decode_incoming
from alpha.telegram.publication_delivery import TelegramPublicationDelivery

_IDLE_SECONDS = 1.0
_RETRY_SECONDS = 5.0
_PROGRESS_INTERVAL_SECONDS = 10.0
_MAX_INBOX_ATTEMPTS = 5
_MODULE = "TELEGRAM"


@dataclass
class TelegramDaemon:
    """耗时研究不会阻塞收信；所有任务由当前运行作用域持有并在退出时取消。"""

    controller: TelegramController
    inbox: SQLiteTelegramInbox
    publication_worker: PublicationWorker | None = None
    _research_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict, init=False)
    _blocked_versions: dict[str, int] = field(default_factory=dict, init=False)
    _delivered: set[str] = field(default_factory=set, init=False)
    _delivery_retry_at: dict[str, float] = field(default_factory=dict, init=False)
    _publication_notifications: set[tuple[str, PublicationState, str | None]] = field(default_factory=set, init=False)

    async def run(self) -> None:
        """持有单实例锁时运行四条独立循环。参数：无。返回：无。异常：不可恢复协议故障或外层取消。"""
        self.inbox.recover_interrupted()
        self.controller.topics.log.recover_interrupted()
        self.controller.sender.receipts.recover_interrupted()
        self.controller.topics.repair_ready_bindings()
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self._poll(), name="telegram-poll")
                group.create_task(self._dispatch(), name="telegram-inbox")
                group.create_task(self._schedule(), name="telegram-research-scheduler")
                group.create_task(self._deliver(), name="telegram-report-delivery")
                if self.publication_worker is not None:
                    group.create_task(self._publish(), name="telegram-notion-publication")
        finally:
            for task in self._research_tasks.values():
                task.cancel()
            await asyncio.gather(*self._research_tasks.values(), return_exceptions=True)
            self._research_tasks.clear()

    async def poll_once(self) -> int:
        """轮询并原子保存整批。参数：无。返回：新 offset。异常：API 或持久化失败。"""
        updates = await self.controller.sender.client.get_updates(self.inbox.offset())
        return self.inbox.accept_batch(updates)

    async def _poll(self) -> None:
        """持续收信。参数：无。返回：不主动返回。异常：409 实例冲突或权限错误。"""
        while True:
            try:
                before = self.inbox.offset()
                after = await self.poll_once()
                await asyncio.sleep(_IDLE_SECONDS if after == before else 0)
            except TelegramApiError as exc:
                if exc.code in (401, 403, 409):
                    raise
                await asyncio.sleep(exc.retry_after or _RETRY_SECONDS)

    async def dispatch_once(self) -> bool:
        """派发一条更新，不等待研究。参数：无。返回：是否领取。异常：仓储完整性错误。"""
        item = self.inbox.claim_next()
        if item is None:
            return False
        incoming: TelegramIncoming | None = None
        try:
            incoming = decode_incoming(item.update)
            if incoming is not None:
                await self.controller.handle(incoming)
            self.inbox.finish(item)
        except TelegramApiError as exc:
            retry = float(exc.retry_after) if exc.retry_after is not None and item.attempt < _MAX_INBOX_ATTEMPTS else None
            self.inbox.finish(item, error=str(exc), retry_after=retry)
        except (ValueError, KeyError, PermissionError, ResearchConflictError, TelegramTopicUnknownError, TelegramDeliveryUnknownError) as exc:
            self.inbox.finish(item, error=str(exc))
            if incoming is not None and incoming.private and incoming.user_id in self.controller.allowed_users and incoming.chat_id == incoming.user_id:
                try:
                    await self.controller.sender.text(f"update-error:{item.update_id}", incoming.chat_id, incoming.thread_id, str(exc)[:1000])
                except (TelegramApiError, TelegramDeliveryUnknownError):
                    Log.warning(f"入站错误提示未确认，update_id={item.update_id}", module=_MODULE)
        except Exception as exc:
            # 不把模型供应商或 HTTP 原始异常文本写入渠道消息或日志，避免携带凭据。
            self.inbox.finish(item, error=type(exc).__name__)
            Log.warning(f"更新处理失败，update_id={item.update_id}，type={type(exc).__name__}", module=_MODULE)
        return True

    async def _dispatch(self) -> None:
        """持续消费 inbox。参数：无。返回：不主动返回。异常：数据库错误。"""
        while True:
            if not await self.dispatch_once():
                await asyncio.sleep(_IDLE_SECONDS)

    async def schedule_once(self) -> None:
        """启动各研究的单个工作者。参数：无。返回：无。异常：目录或绑定损坏。"""
        finished = [research_id for research_id, task in self._research_tasks.items() if task.done()]
        for research_id in finished:
            task = self._research_tasks.pop(research_id)
            task.result()
        for user_id in self.controller.allowed_users:
            for record in self.controller.research.list_research(str(user_id)):
                if record.state != ResearchState.ACTIVE or record.research_id in self._research_tasks:
                    continue
                view = self.controller.research.overview(record.research_id, str(user_id))
                turn = view.active_turn or view.latest_turn
                if turn is None or self._blocked_versions.get(record.research_id) == record.version or (view.active_turn is None and view.queued_count == 0):
                    continue
                binding = self.controller.topics.for_research(record.research_id, str(user_id))
                if binding is not None:
                    self._research_tasks[record.research_id] = asyncio.create_task(self._research(record.research_id, user_id,
                                                                                             int(binding.conversation_id), int(binding.topic_id)))

    async def _schedule(self) -> None:
        """持续调度，模型执行位于独立任务。参数：无。返回：不主动返回。异常：持久状态错误。"""
        while True:
            await self.schedule_once()
            await asyncio.sleep(_IDLE_SECONDS)

    async def _research(self, research_id: str, user_id: int, chat_id: int, thread_id: int) -> None:
        """消费一项研究的最早输入。参数：研究及绑定地址。返回：无。异常：取消透传，执行错误转为状态提示。"""
        progress_id: int | None = None
        turn_id: str | None = None
        try:
            turn = self.controller.research.dispatch(research_id, str(user_id))
            if turn is None:
                return
            turn_id = turn.turn_id
            try:
                progress_id = await self.controller.sender.text(f"progress:{turn.turn_id}:{turn.run_id}", chat_id, thread_id, "alpha · 已受理研究，正在核对材料与问题。")
            except (TelegramApiError, TelegramDeliveryUnknownError):
                pass
            last_update = time.monotonic()
            async with aclosing(self.controller.research.run_next(research_id, str(user_id))) as stream:
                async for event in stream:
                    if event.type in (AppEventType.TOOL_EVENT, AppEventType.ITERATION_START) and progress_id is not None and time.monotonic() - last_update >= _PROGRESS_INTERVAL_SECONDS:
                        try:
                            await self.controller.sender.client.edit_message(chat_id, progress_id, "alpha · 正在检索、核对证据与计算；完成后投递正式报告。")
                        except TelegramApiError:
                            pass
                        last_update = time.monotonic()
            if progress_id is not None:
                try:
                    await self.controller.sender.client.edit_message(chat_id, progress_id, "alpha · 本轮执行已结束。报告、摘要交付分别记录，可用 /status 查看。")
                except TelegramApiError:
                    pass
        except Exception as exc:
            view = self.controller.research.overview(research_id, str(user_id))
            failed_turn = view.active_turn or view.latest_turn
            turn_id = turn_id or (failed_turn.turn_id if failed_turn is not None else None)
            self._blocked_versions[research_id] = view.research.version
            Log.warning(f"研究等待核对，research_id={research_id}，type={type(exc).__name__}", module=_MODULE)
            try:
                message = ("模型本轮未提交正式报告。请在本话题发送‘根据已有记录补齐证据并提交正式报告’，建立下一轮输入。"
                           if isinstance(exc, ResearchReportMissingError) else
                           f"本轮研究未完成。请用 /status 查看状态；失败或中断可显式 /resume {turn_id}，放弃当前输入可发送 /stop。")
                await self.controller.sender.text(f"research-error:{turn_id}", chat_id, thread_id, message)
            except (TelegramApiError, TelegramDeliveryUnknownError):
                pass

    async def deliver_once(self) -> None:
        """独立调和正式报告摘要，不阻塞后续研究。参数：无。返回：无。异常：持久状态损坏。"""
        for user_id in self.controller.allowed_users:
            for record in self.controller.research.list_research(str(user_id)):
                binding = self.controller.topics.for_research(record.research_id, str(user_id))
                if binding is None:
                    continue
                view = self.controller.research.overview(record.research_id, str(user_id))
                for revision in view.revisions:
                    if revision.revision_id in self._delivered or self._delivery_retry_at.get(revision.revision_id, 0) > time.time():
                        continue
                    try:
                        await self.controller.reports.summary(view, revision, user_id, int(binding.conversation_id), int(binding.topic_id))
                        self._delivered.add(revision.revision_id)
                    except TelegramApiError as exc:
                        if exc.retry_after is not None:
                            self._delivery_retry_at[revision.revision_id] = time.time() + exc.retry_after
                        else:
                            self._delivered.add(revision.revision_id)
                    except TelegramDeliveryUnknownError:
                        self._delivered.add(revision.revision_id)

    async def _deliver(self) -> None:
        """持续交付，未知结果保持待核对。参数：无。返回：不主动返回。异常：存储损坏。"""
        while True:
            await self.deliver_once()
            await asyncio.sleep(_IDLE_SECONDS)

    async def publish_once(self) -> None:
        """推进发布队列并投递状态。参数：无。返回：无。异常：业务持久错误，结果保留。"""
        worker = self.publication_worker
        if worker is None:
            return
        await worker.process_once()
        delivery = TelegramPublicationDelivery(self.controller.research, self.controller.topics, self.controller.sender, self.controller.cards.actions)
        for user_id in self.controller.allowed_users:
            for publication in worker.service.list_for_owner(str(user_id)):
                key = (publication.publication_id, publication.state, publication.run_id if publication.state == PublicationState.FAILED_TERMINAL else None)
                if key in self._publication_notifications:
                    continue
                try:
                    if await delivery.notify(publication, user_id):
                        self._publication_notifications.add(key)
                except TelegramApiError as exc:
                    if exc.retry_after is not None:
                        await asyncio.sleep(exc.retry_after)
                    else:
                        self._publication_notifications.add(key)
                except TelegramDeliveryUnknownError:
                    self._publication_notifications.add(key)

    async def _publish(self) -> None:
        """独立发布循环，不占研究会话互斥。参数：无。返回：不主动返回。异常：持久错误。"""
        while True:
            await self.publish_once()
            await asyncio.sleep(_IDLE_SECONDS)
