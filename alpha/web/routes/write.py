"""Write 操作端点。"""

from __future__ import annotations


def create_write_router():
    """创建 write 路由。"""

    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/api", tags=["write"])

    class WriteRequestBody(BaseModel):
        """写作请求体（精简版，供 Web UI 发起写作任务）。"""

        ticker: str
        template_path: str = ""
        output_dir: str = ""

    @router.post("/write")
    async def submit_write(body: WriteRequestBody) -> None:
        """提交写作任务。

        Args:
            body: 写作请求体。

        Returns:
            无。

        Raises:
            HTTPException: Web 端当前不支持在线写作时抛出。
        """

        del body
        raise HTTPException(status_code=501, detail="Web 端暂不支持在线写作")

    return router


__all__ = ["create_write_router"]
