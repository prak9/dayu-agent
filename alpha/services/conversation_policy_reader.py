"""Service 侧 conversation policy 读取模块。"""

from __future__ import annotations

from dataclasses import dataclass

from alpha.contracts.model_config import ModelConfig
from alpha.execution.options import ConversationMemorySettings, ResolvedExecutionOptions, resolve_conversation_memory_settings


@dataclass(frozen=True)
class ConversationPolicyReader:
    """解析多轮会话分层记忆策略。"""

    def resolve(
        self,
        *,
        resolved_execution_options: ResolvedExecutionOptions,
        model_config: ModelConfig | None,
    ) -> ConversationMemorySettings:
        """解析当前 scene 的 conversation memory 配置。"""

        return resolve_conversation_memory_settings(
            conversation_memory_config=resolved_execution_options.conversation_memory_config,
            model_config=model_config,
        )


__all__ = ["ConversationPolicyReader"]
