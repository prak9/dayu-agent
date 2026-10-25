"""Run REST 端点。"""

from __future__ import annotations

from typing import Any

from alpha.services.contracts import RunAdminView
from alpha.services.protocols import HostAdminServiceProtocol


def _parse_run_state(state: str | None) -> str | None:
    """把查询参数里的 run 状态标准化为小写字符串。

    Args:
        state: 原始状态字符串。

    Returns:
        规范化后的状态字符串；未传时返回 `None`。

    Raises:
        ValueError: 状态值不合法时抛出。
    """

    if state is None:
        return None
    parsed = str(state).strip().lower()
    if parsed not in {"created", "queued", "running", "succeeded", "failed", "cancelled"}:
        raise ValueError(parsed)
    return parsed


def _build_run_response_payload(record: RunAdminView) -> dict[str, Any]:
    """把运行管理视图转为可序列化响应载荷。

    Args:
        record: 运行管理视图。

    Returns:
        响应字典。

    Raises:
        无。
    """

    return {
        "run_id": record.run_id,
        "session_id": record.session_id,
        "service_type": record.service_type,
        "state": record.state,
        "cancel_requested_at": record.cancel_requested_at,
        "cancel_requested_reason": record.cancel_requested_reason,
        "cancel_reason": record.cancel_reason,
        "scene_name": record.scene_name,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "error_summary": record.error_summary,
    }


def create_run_router(host_admin_service: HostAdminServiceProtocol):
    """创建 run 路由。

    Args:
        无。

    Returns:
        FastAPI 路由对象。

    Raises:
        无。
    """

    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/runs", tags=["runs"])

    class RunResponse(BaseModel):
        """Run 响应。"""

        run_id: str
        session_id: str | None = None
        service_type: str
        state: str
        cancel_requested_at: str | None = None
        cancel_requested_reason: str | None = None
        cancel_reason: str | None = None
        scene_name: str | None = None
        created_at: str
        started_at: str | None = None
        finished_at: str | None = None
        error_summary: str | None = None

    def _run_to_response(record: RunAdminView) -> RunResponse:
        """将运行管理视图转为响应。"""

        return RunResponse(**_build_run_response_payload(record))

    @router.get("", response_model=list[RunResponse])
    async def list_runs(
        session_id: str | None = None,
        state: str | None = None,
        service_type: str | None = None,
    ) -> list[RunResponse]:
        """列出 run。"""

        try:
            parsed_state = _parse_run_state(state)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid run state: {state}") from exc
        records = host_admin_service.list_runs(
            session_id=session_id,
            state=parsed_state,
            service_type=service_type,
        )
        return [_run_to_response(record) for record in records]

    @router.get("/{run_id}", response_model=RunResponse)
    async def get_run(run_id: str) -> RunResponse:
        """获取单个 run。"""

        record = host_admin_service.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run not found")
        return _run_to_response(record)

    @router.post("/{run_id}/cancel", response_model=RunResponse)
    async def cancel_run(run_id: str) -> RunResponse:
        """取消 run。"""

        try:
            record = host_admin_service.cancel_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return _run_to_response(record)

    return router


__all__ = ["create_run_router"]
