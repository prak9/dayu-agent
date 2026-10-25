"""Fins 操作端点。"""

from __future__ import annotations

import asyncio
from typing import Any

from alpha.contracts.fins import DownloadCommandPayload, FinsCommand, FinsCommandName, FinsResult, ProcessCommandPayload
from alpha.services.contracts import FinsSubmission
from alpha.services.protocols import FinsServiceProtocol


class _InvalidFinsSubmissionError(Exception):
    """FinsService 返回非法提交句柄时抛出的内部异常。"""


def _require_fins_submission(submission: object) -> FinsSubmission:
    """验证 Web fins 路由收到的 Service 提交句柄。

    Args:
        submission: FinsService 返回对象。

    Returns:
        通过验证的 `FinsSubmission`。

    Raises:
        _InvalidFinsSubmissionError: 返回值不是稳定 DTO，或 execution 不是流式句柄时抛出。
    """

    if not isinstance(submission, FinsSubmission):
        raise _InvalidFinsSubmissionError("fins service returned invalid submission")
    if not submission.session_id.strip():
        raise _InvalidFinsSubmissionError("fins service returned empty session_id")
    execution: Any = submission.execution
    if isinstance(execution, FinsResult):
        raise _InvalidFinsSubmissionError("fins service returned non-stream execution")
    if not hasattr(execution, "__aiter__"):
        raise _InvalidFinsSubmissionError("fins service returned invalid execution")
    return submission


def create_fins_router(fins_service: FinsServiceProtocol):
    """创建 fins 路由。

    Args:
        无。

    Returns:
        FastAPI 路由对象。

    Raises:
        无。
    """

    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    from alpha.services.contracts import FinsSubmitRequest

    router = APIRouter(prefix="/api/fins", tags=["fins"])

    class FinsDownloadRequest(BaseModel):
        """下载请求体。"""

        ticker: str
        forms: list[str] | None = None
        start_date: str | None = None
        end_date: str | None = None
        overwrite: bool = False

    class FinsProcessRequest(BaseModel):
        """处理请求体。"""

        ticker: str
        overwrite: bool = False
        ci: bool = False

    class FinsResponse(BaseModel):
        """Fins 响应。"""

        session_id: str
        accepted: bool = True

    @router.post("/download", response_model=FinsResponse, status_code=202)
    async def submit_download(body: FinsDownloadRequest) -> FinsResponse:
        """提交下载任务。

        Args:
            body: 请求体。

        Returns:
            可订阅的 session 句柄。

        Raises:
            无。
        """

        try:
            submission = fins_service.submit(
                FinsSubmitRequest(
                    command=FinsCommand(
                        name=FinsCommandName.DOWNLOAD,
                        payload=DownloadCommandPayload(
                            ticker=body.ticker,
                            form_type=tuple(body.forms or ()),
                            start_date=body.start_date,
                            end_date=body.end_date,
                            overwrite=body.overwrite,
                        ),
                        stream=True,
                    ),
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            validated_submission = _require_fins_submission(submission)
        except _InvalidFinsSubmissionError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        asyncio.create_task(_consume_stream(validated_submission.execution))
        return FinsResponse(session_id=validated_submission.session_id)

    @router.post("/process", response_model=FinsResponse, status_code=202)
    async def submit_process(body: FinsProcessRequest) -> FinsResponse:
        """提交处理任务。

        Args:
            body: 请求体。

        Returns:
            可订阅的 session 句柄。

        Raises:
            无。
        """

        try:
            submission = fins_service.submit(
                FinsSubmitRequest(
                    command=FinsCommand(
                        name=FinsCommandName.PROCESS,
                        payload=ProcessCommandPayload(
                            ticker=body.ticker,
                            overwrite=body.overwrite,
                            ci=body.ci,
                        ),
                        stream=True,
                    ),
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            validated_submission = _require_fins_submission(submission)
        except _InvalidFinsSubmissionError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        asyncio.create_task(_consume_stream(validated_submission.execution))
        return FinsResponse(session_id=validated_submission.session_id)

    return router


async def _consume_stream(stream):
    """后台消费流式事件。

    Args:
        stream: 流式执行句柄。

    Returns:
        无。

    Raises:
        TypeError: 收到非流式句柄时抛出。
    """

    if isinstance(stream, FinsResult):
        raise TypeError("异步路由要求流式 FinsSubmission.execution")
    async for _ in stream:
        pass


__all__ = ["create_fins_router"]
