"""Service 层 Host session 生命周期协调器。

该模块统一封装 Service 请求期对 Host session 的三种策略：
- 首轮新建
- 显式续聊且要求既有 session
- 确定性 session 的幂等获取
"""

from __future__ import annotations

from dataclasses import dataclass

from alpha.contracts.session import SessionRecord, SessionSource
from alpha.host.protocols import SessionOperationsProtocol
from alpha.services.contracts import SessionResolutionPolicy


@dataclass
class ServiceSessionCoordinator:
    """Service 层会话协调器。

    Attributes:
        host: Service 可见的 session 能力边界。
        session_source: 该 Service 固定持有的会话来源。
    """

    host: SessionOperationsProtocol
    session_source: SessionSource

    def create_new(
        self,
        *,
        scene_name: str | None = None,
    ) -> SessionRecord:
        """创建新的 Host session。

        Args:
            scene_name: 可选 scene 名称。

        Returns:
            新建的会话记录。

        Raises:
            无。
        """

        return self.host.create_session(
            self.session_source,
            scene_name=scene_name,
        )

    def require_existing(
        self,
        session_id: str,
        *,
        scene_name: str | None = None,
    ) -> SessionRecord:
        """要求给定 session 已存在，并刷新活跃时间。

        Args:
            session_id: 会话 ID。
            scene_name: 保留的 scene 信息，仅用于接口对齐。

        Returns:
            已存在的会话记录。

        Raises:
            KeyError: session 不存在时抛出。
        """

        del scene_name
        session = self.host.get_session(session_id)
        if session is None:
            raise KeyError(f"session 不存在: {session_id}")
        self.host.touch_session(session_id)
        refreshed = self.host.get_session(session_id)
        if refreshed is None:
            raise KeyError(f"session 不存在: {session_id}")
        return refreshed

    def ensure_deterministic(
        self,
        session_id: str,
        *,
        scene_name: str | None = None,
    ) -> SessionRecord:
        """按确定性 session_id 幂等获取或创建会话。

        Args:
            session_id: 确定性会话 ID。
            scene_name: 可选 scene 名称。

        Returns:
            已存在或新建的会话记录。

        Raises:
            无。
        """

        return self.host.ensure_session(
            session_id,
            self.session_source,
            scene_name=scene_name,
        )

    def resolve(
        self,
        *,
        session_id: str | None,
        scene_name: str | None,
        policy: SessionResolutionPolicy,
    ) -> SessionRecord:
        """按策略解析本次请求对应的 Host session。

        Args:
            session_id: 可选会话 ID。
            scene_name: 可选 scene 名称。
            policy: 会话解析策略。

        Returns:
            解析得到的会话记录。

        Raises:
            ValueError: 会话策略与 `session_id` 组合非法时抛出。
            KeyError: 要求既有 session 但不存在时抛出。
        """

        if policy == SessionResolutionPolicy.AUTO:
            if session_id is None:
                return self.create_new(scene_name=scene_name)
            return self.require_existing(session_id, scene_name=scene_name)
        if policy == SessionResolutionPolicy.CREATE_NEW:
            if session_id is not None:
                raise ValueError("CREATE_NEW 策略不接受显式 session_id")
            return self.create_new(scene_name=scene_name)
        if policy == SessionResolutionPolicy.REQUIRE_EXISTING:
            if session_id is None:
                raise ValueError("REQUIRE_EXISTING 策略要求显式 session_id")
            return self.require_existing(session_id, scene_name=scene_name)
        if policy == SessionResolutionPolicy.ENSURE_DETERMINISTIC:
            if session_id is None:
                raise ValueError("ENSURE_DETERMINISTIC 策略要求显式 session_id")
            return self.ensure_deterministic(session_id, scene_name=scene_name)
        raise ValueError(f"未知 session 解析策略: {policy}")


__all__ = ["ServiceSessionCoordinator"]
