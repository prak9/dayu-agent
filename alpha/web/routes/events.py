"""SSE 事件流端点。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import json
from typing import Any, cast

from alpha.contracts.events import PublishedRunEventProtocol
from alpha.services.protocols import HostAdminServiceProtocol


def _normalize_event_payload(payload: object) -> object:
    """把事件负载规范化为可 JSON 序列化结构。"""

    if not isinstance(payload, type) and is_dataclass(payload):
        return asdict(cast(Any, payload))
    return payload


def _normalize_event_discriminator(value: object) -> str:
    """把事件判别字段规范化为稳定字符串。"""

    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _build_sse_event_payload(event: PublishedRunEventProtocol) -> dict[str, object]:
    """构造稳定 SSE 事件包络。

    Args:
        event: 宿主管理面透传的运行事件。

    Returns:
        可直接 JSON 序列化的 SSE 事件数据。

    Raises:
        无。
    """

    payload: dict[str, object] = {
        "type": _normalize_event_discriminator(event.type),
        "payload": _normalize_event_payload(event.payload),
    }
    command = getattr(event, "command", None)
    if command is not None:
        payload["command"] = _normalize_event_discriminator(command)
    return payload


def create_events_router(host_admin_service: HostAdminServiceProtocol):
    """创建 SSE 事件流路由。

    Args:
        无。

    Returns:
        FastAPI 路由对象。

    Raises:
        无。
    """

    from fastapi import APIRouter, HTTPException
    from fastapi.responses import StreamingResponse

    router = APIRouter(prefix="/api", tags=["events"])

    async def _sse_generator(stream):
        """将事件流转为 SSE 文本流。

        Args:
            stream: 应用层事件流。

        Yields:
            SSE 文本片段。

        Raises:
            无。
        """

        async for event in stream:
            data = json.dumps(_build_sse_event_payload(event), ensure_ascii=False)
            yield f"data: {data}\n\n"

    @router.get("/runs/{run_id}/events")
    async def run_events(run_id: str):
        """订阅单个 run 的实时事件。"""

        try:
            stream = host_admin_service.subscribe_run_events(run_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        return StreamingResponse(
            _sse_generator(stream),
            media_type="text/event-stream",
        )

    @router.get("/sessions/{session_id}/events")
    async def session_events(session_id: str):
        """订阅 session 下所有 run 的实时事件。"""

        try:
            stream = host_admin_service.subscribe_session_events(session_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        return StreamingResponse(
            _sse_generator(stream),
            media_type="text/event-stream",
        )

    return router


__all__ = ["create_events_router"]
