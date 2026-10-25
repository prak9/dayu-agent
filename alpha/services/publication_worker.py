"""异步入口对同步发布线程的生命周期持有与协作取消。"""

import asyncio
from dataclasses import dataclass

from alpha.contracts.cancellation import CancellationToken
from alpha.contracts.publication import ResearchPublication
from alpha.services.publication_service import PublicationService


@dataclass(frozen=True)
class PublicationWorker:
    """退出时先请求 Host 取消，再等待当前有界 HTTP/线程收尾。"""

    service: PublicationService

    async def process_once(self) -> ResearchPublication | None:
        """处理最早意图。参数：无。返回：结果或空。异常：取消或持久错误，线程已收尾。"""
        token = CancellationToken()
        task = asyncio.create_task(asyncio.to_thread(self.service.process_next, token))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            token.cancel()
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
            raise
