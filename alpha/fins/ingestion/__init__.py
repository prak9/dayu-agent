"""财报长事务编排模块。

该子包承载 `download/process` 两类长事务的共享编排能力，职责包括：
- 定义统一的 `process` 事件模型。
- 提供 `FinsIngestionService` 统一封装流式执行与同步聚合。
- 提供独立于 `AsyncAgent` 生命周期的进程内 Job 管理器。

注意：
- 文档读取与快照内容生成的唯一真相源仍是 `FinsToolService`。
- 本子包只负责长事务编排与状态管理，不复制读取工具字段逻辑。
"""

from .job_manager import IngestionJobManager, get_or_create_ingestion_job_manager
from .process_events import ProcessEvent, ProcessEventType
from .service import FinsIngestionService, IngestionBackendProtocol

__all__ = [
    "FinsIngestionService",
    "IngestionBackendProtocol",
    "IngestionJobManager",
    "ProcessEvent",
    "ProcessEventType",
    "get_or_create_ingestion_job_manager",
]
