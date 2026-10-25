"""发布服务依赖的独立 Host 操作端口。"""

from collections.abc import Callable
from typing import Protocol

from alpha.contracts.host_execution import HostedRunContext, HostedRunSpec
from alpha.contracts.operation_admission import OperationAdmission
from alpha.contracts.run import RunRecord


class PublicationHost(Protocol):
    """发布不占研究 Session 的写互斥，生命周期仍由 Host 管理。"""

    def admit_operation(self, request_key: str, spec: HostedRunSpec, input_hash: str) -> OperationAdmission:
        """持久受理。参数：稳定尝试键、规格、输入摘要。返回：Run。异常：冲突。"""
        ...

    def run_admitted_operation_sync(self, run_id: str, operation: Callable[[HostedRunContext], None]) -> None:
        """执行已接受操作。参数：Run、处理函数。返回：无。异常：取消、繁忙或需调和。"""
        ...

    def get_run(self, run_id: str) -> RunRecord | None:
        """查询状态真源。参数：Run。返回：记录或空。异常：存储错误。"""
        ...

    def cancel_run(self, run_id: str) -> RunRecord:
        """请求取消当前尝试。参数：Run。返回：当前运行记录。异常：宿主存储错误。"""
        ...
