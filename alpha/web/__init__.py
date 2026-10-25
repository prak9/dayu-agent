"""Web UI 适配层占位包。

本包当前提供 FastAPI 适配入口，Web 组合根应显式注入所需 Service 协议，
请求期路由不应再依赖全局 service locator。
"""

from .fastapi_app import create_fastapi_app

__all__ = ["create_fastapi_app"]
