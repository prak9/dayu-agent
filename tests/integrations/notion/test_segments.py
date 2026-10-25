"""大报告分段、未知追加与任务过期的真实仓储/HTTP 回归。"""

from pathlib import Path

import pytest

from alpha.contracts.publication import PublicationState, PublishResearchRequest
from alpha.research.publication_identity import publication_identifier, publication_marker
from alpha.research.publication_segments import split_publication, segment_progress
from alpha.research.storage.publications import SQLiteResearchPublications
from tests.integrations.notion.fakes import NotionServer
from tests.integrations.notion.test_client import PARENT_ID
from tests.integrations.notion.test_publication_service import _make_due, _service


@pytest.mark.parametrize("unknown,asynchronous", [(False, False), (True, False), (False, True)])
def test_segmented_report_recovers_without_duplicate_append(tmp_path: Path, unknown: bool, asynchronous: bool) -> None:
    """分段续写未知或异步后仍只有一个完整正文。参数：目录、丢响应、异步。返回：无。异常：断言失败。"""
    server = NotionServer(unknown_append=unknown, async_append=asynchronous)
    service, store, revision, client = _service(tmp_path, server)
    identifier = publication_identifier(revision.revision_id, PARENT_ID)
    body = publication_marker(identifier) + "\n\n" + "\n\n".join(f"第 {index} 段：" + "业务收入" * 3000 for index in range(10))
    records = SQLiteResearchPublications(store)
    records.request(PublishResearchRequest(revision.revision_id, "owner", "large"), target_id=PARENT_ID, title=identifier, markdown=body)
    result = service.process_next()
    assert result is not None
    if unknown:
        assert result.state == PublicationState.RECONCILING
        with store.connection() as conn:
            assert conn.execute("SELECT written_segments FROM research_publications").fetchone()[0] == 1
        _make_due(store)
        result = service.process_next()
        assert result is not None
    assert result.state == PublicationState.PUBLISHED and result.page_id is not None
    segments = split_publication(body)
    written, actual = segment_progress(server.markdown[result.page_id], identifier, segments)
    assert written == len(segments)
    # 格式分隔空行不改变正文；每段业务文字出现且只出现一次。
    for index in range(10):
        assert actual.count(f"第 {index} 段：") == 1
    assert server.created == 1 and server.append_attempts == len(segments) - 1
    assert service.process_next() is None
    client.close()


def test_expired_async_create_task_uses_readonly_candidate(tmp_path: Path) -> None:
    """任务过期后查找原页，不能重建。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(async_create=True, expired_task=True)
    service, store, revision, client = _service(tmp_path, server)
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    result = service.process_next()
    assert result is not None and result.state == PublicationState.RECONCILING
    _make_due(store)
    result = service.process_next()
    assert result is not None and result.state == PublicationState.PUBLISHED and server.created == 1
    client.close()


def test_unknown_creation_finds_renamed_page_and_duplicate_markers_stay_unsettled(tmp_path: Path) -> None:
    """改标题不丢正文身份，多候选不猜测归属。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(unknown_create=True)
    service, store, revision, client = _service(tmp_path, server)
    service.request_publish(PublishResearchRequest(revision.revision_id, "owner", "publish"))
    service.process_next()
    page_id = next(iter(server.pages))
    server.pages[page_id]["properties"] = {"title": {"type": "title", "title": [{"plain_text": "用户修改后的标题"}]}}
    duplicate = "00000000-0000-0000-0000-000000000002"
    server.pages[duplicate] = {**server.pages[page_id], "id": duplicate}
    server.markdown[duplicate] = server.markdown[page_id]
    _make_due(store)
    result = service.process_next()
    assert result is not None and result.state == PublicationState.RECONCILING and result.page_id is None
    del server.pages[duplicate]
    del server.markdown[duplicate]
    _make_due(store)
    result = service.process_next()
    assert result is not None and result.state == PublicationState.PUBLISHED and server.created == 1
    client.close()


def test_manual_edit_of_partial_page_never_triggers_rewrite(tmp_path: Path) -> None:
    """半页人工改动保留待核对，不能继续覆盖或追加。参数：目录。返回：无。异常：断言失败。"""
    server = NotionServer(unknown_append=True)
    service, store, revision, client = _service(tmp_path, server)
    identifier = publication_identifier(revision.revision_id, PARENT_ID)
    body = publication_marker(identifier) + "\n\n" + "\n\n".join("收入 100：" + "文字" * 10000 for _ in range(10))
    SQLiteResearchPublications(store).request(PublishResearchRequest(revision.revision_id, "owner", "large"),
        target_id=PARENT_ID, title=identifier, markdown=body)
    result = service.process_next()
    assert result is not None and result.state == PublicationState.RECONCILING and result.page_id is not None
    server.markdown[result.page_id] = server.markdown[result.page_id].replace("收入 100", "收入 1000", 1)
    attempts = server.append_attempts
    _make_due(store)
    result = service.process_next()
    assert result is not None and result.state == PublicationState.RECONCILING
    assert server.append_attempts == attempts and server.created == 1
    client.close()


def test_split_preserves_code_table_and_rejects_oversized_atomic_block() -> None:
    """编码上限考虑中文和转义，代码和表格不能从中切开。参数：无。返回：无。异常：断言失败。"""
    block = "```python\nprint('x')\n\nprint('y')\n```\n\n<table>\n<tr><td>x</td></tr>\n\n</table>\n\n"
    body = "段落\n\n" * 30000 + block
    segments = split_publication(body)
    assert "".join(segments) == body and any(block in segment for segment in segments)
    with pytest.raises(ValueError, match="单个"):
        split_publication("中" * 100000)
    with pytest.raises(ValueError, match="不能为空"):
        split_publication("")
    with pytest.raises(ValueError, match="不唯一"):
        segment_progress("no marker", "pub", ("x", "y"))
