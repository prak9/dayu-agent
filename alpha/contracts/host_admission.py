"""Host 持久受理及停止边界的公共契约，不包含研究或渠道语义。"""

from dataclasses import dataclass


class AgentAdmissionConflictError(RuntimeError):
    """同一受理键被用于不同执行输入。"""


class AgentAdmissionBusyError(RuntimeError):
    """会话仍有未收敛的写执行或待恢复输入。"""


class AgentAdmissionStaleError(RuntimeError):
    """派发属于已经停止的会话 epoch。"""


class AgentAdmissionRecoveryRequiredError(RuntimeError):
    """已开始的孤立执行需要显式恢复，不能盲目重跑工具。"""


@dataclass(frozen=True)
class AgentTurnAdmission:
    """已持久化的受理身份，Run 状态仍从 Host 查询。"""

    run_id: str
    session_id: str
    request_key: str
    pending_turn_id: str
    epoch: int
