"""独立宿主操作的持久受理身份，不承载研究或发布业务状态。"""

from dataclasses import dataclass


class OperationAdmissionConflictError(RuntimeError):
    """同一独立操作请求键对应了不同规格或输入。"""


class OperationAdmissionBusyError(RuntimeError):
    """独立操作仍有存活执行者。"""


class OperationAdmissionRecoveryRequiredError(RuntimeError):
    """操作曾经开始但未成功，调用者须先调和业务副作用。"""


@dataclass(frozen=True)
class OperationAdmission:
    """返回前已持久化的无 Session 操作身份。"""

    run_id: str
    request_key: str
