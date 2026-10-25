"""多话题研究的持久隔离和所有权测试。"""

from dataclasses import replace
from pathlib import Path

import pytest

from alpha.contracts.research import CreateResearchRequest, ResearchConflictError
from alpha.contracts.research_channels import BindResearchChannelRequest
from alpha.research.storage.bindings import SQLiteResearchBindings
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.store import ResearchStore


def test_binding_survives_restart_and_rejects_ambiguous_reassignment(tmp_path: Path) -> None:
    """重启沿用绑定且拒绝猜测迁移。参数：目录。返回：无。异常：断言失败。"""
    path = tmp_path / "research.db"
    store = ResearchStore(path)
    catalog = SQLiteResearchCatalog(store)
    first = catalog.create(CreateResearchRequest("owner", "first", "同公司质量"))
    second = catalog.create(CreateResearchRequest("owner", "second", "同公司估值"))
    bindings = SQLiteResearchBindings(store)
    request = BindResearchChannelRequest(first.research_id, "owner", "telegram", "bot1", "chat1", "topic1")
    bound = bindings.bind(request)
    assert bindings.bind(request) == bound
    reopened = SQLiteResearchBindings(ResearchStore(path))
    assert reopened.resolve(owner_id="owner", channel="telegram", instance_id="bot1", conversation_id="chat1", topic_id="topic1") == bound
    assert reopened.for_research(first.research_id, "owner", channel="telegram", instance_id="bot1") == bound
    assert reopened.for_research(second.research_id, "owner", channel="telegram", instance_id="bot1") is None
    with pytest.raises(ResearchConflictError):
        bindings.bind(replace(request, research_id=second.research_id))
    with pytest.raises(ResearchConflictError):
        bindings.bind(replace(request, topic_id="topic2"))
    assert bindings.bind(replace(request, research_id=second.research_id, topic_id="topic2")).research_id == second.research_id
    # 同一原生 topic 数字在另一机器人或会话里没有全局含义。
    assert reopened.resolve(owner_id="owner", channel="telegram", instance_id="bot2", conversation_id="chat1", topic_id="topic1") is None
    with pytest.raises(PermissionError):
        reopened.resolve(owner_id="intruder", channel="telegram", instance_id="bot1", conversation_id="chat1", topic_id="topic1")
    with pytest.raises(PermissionError):
        bindings.bind(replace(request, owner_id="intruder"))
    with pytest.raises(ValueError):
        bindings.bind(replace(request, topic_id=""))
