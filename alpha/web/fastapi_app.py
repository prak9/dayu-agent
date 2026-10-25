"""FastAPI Web UI 骨架。"""

from __future__ import annotations

from alpha.services.protocols import (
    ChatServiceProtocol,
    FinsServiceProtocol,
    HostAdminServiceProtocol,
    PromptServiceProtocol,
    ReplyDeliveryServiceProtocol,
)
from alpha.web.routes.sessions import create_session_router
from alpha.web.routes.runs import create_run_router
from alpha.web.routes.events import create_events_router
from alpha.web.routes.chat import create_chat_router
from alpha.web.routes.prompt import create_prompt_router
from alpha.web.routes.reply_outbox import create_reply_outbox_router
from alpha.web.routes.write import create_write_router
from alpha.web.routes.fins import create_fins_router


def create_fastapi_app(
    *,
    chat_service: ChatServiceProtocol,
    prompt_service: PromptServiceProtocol,
    fins_service: FinsServiceProtocol,
    host_admin_service: HostAdminServiceProtocol,
    reply_delivery_service: ReplyDeliveryServiceProtocol,
):
    """创建 FastAPI 应用骨架。"""

    try:
        from fastapi import FastAPI
    except ImportError as exc:  # pragma: no cover - 依赖是否安装由环境决定
        raise RuntimeError("未安装 fastapi，无法创建 Web UI 入口") from exc

    app = FastAPI(title="Alpha Web")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """健康检查路由。"""

        return {"status": "ok"}

    # 挂载所有 API 路由
    app.include_router(create_session_router(host_admin_service))
    app.include_router(create_run_router(host_admin_service))
    app.include_router(create_events_router(host_admin_service))
    app.include_router(create_chat_router(chat_service, reply_delivery_service))
    app.include_router(create_prompt_router(prompt_service))
    app.include_router(create_reply_outbox_router(reply_delivery_service))
    app.include_router(create_write_router())
    app.include_router(create_fins_router(fins_service))

    return app


__all__ = ["create_fastapi_app"]
