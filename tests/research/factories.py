"""研究存储测试共用的最小有效接受规格，不依赖实际模型或 API。"""

from alpha.contracts.agent_execution import AcceptedExecutionSpec, AcceptedModelSpec
from alpha.contracts.research import ResearchTurnPreparation

TEST_METHOD_HASH = "0" * 64


def research_turn_preparation() -> ResearchTurnPreparation:
    """构造最小接受结果。参数：无。返回：确定方法和模型。异常：无。"""
    return ResearchTurnPreparation(TEST_METHOD_HASH, AcceptedExecutionSpec(AcceptedModelSpec("test-model")))
