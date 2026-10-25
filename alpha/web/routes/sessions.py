"""Session REST 端点。"""

from __future__ import annotations

from alpha.services.protocols import HostAdminServiceProtocol


def _parse_session_state(state: str | None) -> str | None:
    """把查询参数里的 session 状态标准化为小写字符串。

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
    if parsed not in {"active", "closed"}:
        raise ValueError(parsed)
    return parsed


def create_session_router(host_admin_service: HostAdminServiceProtocol):
    """创建 session 路由。

    Args:
        无。

    Returns:
        FastAPI 路由对象。

    Raises:
        无。
    """

    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    from alpha.services.contracts import SessionAdminView

    router = APIRouter(prefix="/api/sessions", tags=["sessions"])

    class CreateSessionRequest(BaseModel):
        """创建 session 请求体。"""

        source: str = "web"
        scene_name: str | None = None

    class SessionResponse(BaseModel):
        """Session 响应。"""

        session_id: str
        source: str
        state: str
        scene_name: str | None = None
        created_at: str
        last_activity_at: str

    def _session_to_response(record: SessionAdminView) -> SessionResponse:
        """将会话管理视图转为响应。"""

        return SessionResponse(
            session_id=record.session_id,
            source=record.source,
            state=record.state,
            scene_name=record.scene_name,
            created_at=record.created_at,
            last_activity_at=record.last_activity_at,
        )

    @router.post("", response_model=SessionResponse, status_code=201)
    async def create_session(body: CreateSessionRequest) -> SessionResponse:
        """创建新 session。"""

        try:
            record = host_admin_service.create_session(
                source=body.source,
                scene_name=body.scene_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid session source: {body.source}") from exc
        return _session_to_response(record)

    @router.get("", response_model=list[SessionResponse])
    async def list_sessions(state: str | None = None) -> list[SessionResponse]:
        """列出 session。"""

        try:
            parsed_state = _parse_session_state(state)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid session state: {state}") from exc
        records = host_admin_service.list_sessions(state=parsed_state)
        return [_session_to_response(record) for record in records]

    @router.get("/{session_id}", response_model=SessionResponse)
    async def get_session(session_id: str) -> SessionResponse:
        """获取单个 session。"""

        record = host_admin_service.get_session(session_id)
        if record is None:
            raise HTTPException(status_code=404, detail="session not found")
        return _session_to_response(record)

    @router.delete("/{session_id}", response_model=SessionResponse)
    async def close_session(session_id: str) -> SessionResponse:
        """关闭 session。"""

        try:
            record, _cancelled_run_ids = host_admin_service.close_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        return _session_to_response(record)

    return router


__all__ = ["create_session_router"]
