"""运行时 trace 基础设施。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from alpha.engine.tool_trace import (
    JsonlToolTraceRecorderFactory,
    JsonlToolTraceStore,
    ToolTraceRecorderFactory,
)
from alpha.execution.options import TraceSettings


@dataclass(frozen=True)
class _TraceSinkKey:
    """Trace store 缓存键。"""

    output_dir: str
    max_file_bytes: int
    retention_days: int
    compress_rolled: bool
    partition_by_session: bool


class TraceRecorderFactoryProvider:
    """管理 trace store 缓存与 recorder factory 复用。"""

    def __init__(self) -> None:
        """初始化 trace provider。

        Args:
            无。

        Returns:
            无。

        Raises:
            无。
        """

        self._trace_lock = Lock()
        self._trace_stores: dict[_TraceSinkKey, JsonlToolTraceStore] = {}

    def get_or_create(self, trace_settings: TraceSettings) -> ToolTraceRecorderFactory | None:
        """按配置获取 trace recorder 工厂。

        Args:
            trace_settings: 工具追踪配置。

        Returns:
            trace recorder 工厂；未启用时返回 ``None``。

        Raises:
            无。
        """

        if not trace_settings.enabled:
            return None

        key = _TraceSinkKey(
            output_dir=str(trace_settings.output_dir),
            max_file_bytes=trace_settings.max_file_bytes,
            retention_days=trace_settings.retention_days,
            compress_rolled=trace_settings.compress_rolled,
            partition_by_session=trace_settings.partition_by_session,
        )
        with self._trace_lock:
            store = self._trace_stores.get(key)
            if store is None:
                store = JsonlToolTraceStore(
                    output_dir=trace_settings.output_dir,
                    max_file_bytes=trace_settings.max_file_bytes,
                    retention_days=trace_settings.retention_days,
                    compress_rolled=trace_settings.compress_rolled,
                    partition_by_session=trace_settings.partition_by_session,
                )
                self._trace_stores[key] = store
            return JsonlToolTraceRecorderFactory(store)
