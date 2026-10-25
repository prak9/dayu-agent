"""Fins 小模块覆盖补充测试。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, BinaryIO, cast

import pytest

from alpha.fins.domain.document_models import BatchToken
from alpha.fins.processors.sc13_processor import Sc13FormProcessor
from alpha.fins.storage.fs_batching_repository import FsBatchingRepository


class _DummySource:
    """满足 `Source` 协议的最小测试桩。"""

    def __init__(self, path: Path) -> None:
        """记录底层路径。"""

        self._path = path

    @property
    def uri(self) -> str:
        """返回资源 URI。"""

        return self._path.as_uri()

    @property
    def media_type(self) -> str | None:
        """返回媒体类型。"""

        return "text/html"

    @property
    def content_length(self) -> int | None:
        """返回内容长度。"""

        return 0

    @property
    def etag(self) -> str | None:
        """返回 etag。"""

        return None

    def open(self) -> BinaryIO:
        """打开二进制流。"""

        return BytesIO(b"")

    def materialize(self, suffix: str | None = None) -> Path:
        """返回物化路径。"""

        del suffix
        return self._path


@pytest.mark.unit
def test_fs_batching_repository_delegates_begin_commit_and_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    """批处理仓储应把事务操作委托给底层 core。"""

    token = BatchToken(
        token_id="batch_1",
        ticker="AAPL",
        target_ticker_dir=Path("/tmp/target"),
        staging_root_dir=Path("/tmp/staging_root"),
        staging_ticker_dir=Path("/tmp/staging"),
        backup_dir=Path("/tmp/backup"),
        journal_path=Path("/tmp/staging_root/transaction.json"),
        ticker_lock_path=Path("/tmp/batch.lock"),
        created_at="2026-04-14T12:00:00+00:00",
    )
    calls: list[tuple[str, object]] = []

    class _Core:
        def begin_batch(self, ticker: str) -> BatchToken:
            calls.append(("begin", ticker))
            return token

        def commit_batch(self, batch_token: BatchToken) -> None:
            calls.append(("commit", batch_token))

        def rollback_batch(self, batch_token: BatchToken) -> None:
            calls.append(("rollback", batch_token))

        def recover_orphan_batches(self, *, dry_run: bool = False) -> tuple[str, ...]:
            calls.append(("recover", dry_run))
            return ("recover action",)

    repository_set = type("_RepoSet", (), {"core": _Core()})()
    monkeypatch.setattr(
        "alpha.fins.storage.fs_batching_repository.build_fs_repository_set",
        lambda **_kwargs: cast(Any, repository_set),
    )

    repository = FsBatchingRepository(Path("/tmp/workspace"))

    started = repository.begin_batch("AAPL")
    repository.commit_batch(started)
    repository.rollback_batch(started)
    recovered = repository.recover_orphan_batches(dry_run=True)

    assert started == token
    assert recovered == ("recover action",)
    assert calls == [("begin", "AAPL"), ("commit", token), ("rollback", token), ("recover", True)]


@pytest.mark.unit
def test_sc13_processor_init_and_build_markers_delegate_to_shared_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """SC13 处理器应把初始化和 marker 构建委托给共享真源。"""

    init_calls: list[tuple[object, object, object]] = []

    def _fake_base_init(self: object, *, source: object, form_type: object = None, media_type: object = None) -> None:
        """记录基类初始化入参。"""

        init_calls.append((source, form_type, media_type))

    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._BaseSecReportFormProcessor.__init__",
        _fake_base_init,
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._build_sc13_markers",
        lambda full_text: [(0, full_text[:4])],
    )

    with TemporaryDirectory() as tmp_dir:
        source = _DummySource(Path(tmp_dir) / "sample.html")
        processor = Sc13FormProcessor(source=source, form_type="SC 13D", media_type="text/html")

    markers = processor._build_markers("Item 1. Security")

    assert init_calls == [(source, "SC 13D", "text/html")]
    assert markers == [(0, "Item")]


@pytest.mark.unit
def test_sc13_processor_collect_full_text_prefers_sufficient_base_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """base 文本已足够时应直接返回，不再回退 `document.text()`。"""

    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._BaseSecReportFormProcessor._collect_full_text_from_base",
        lambda self: "base text",
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._has_sufficient_sc13_markers",
        lambda text: text == "base text",
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._safe_virtual_document_text",
        lambda self: pytest.fail("不应访问 document.text()"),
    )

    processor = object.__new__(Sc13FormProcessor)

    assert processor._collect_full_text_from_base() == "base text"


@pytest.mark.unit
def test_sc13_processor_collect_full_text_falls_back_to_document_and_placeholder_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """base 文本不足时应按 document/fallback 规则收敛。"""

    processor = object.__new__(Sc13FormProcessor)

    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._BaseSecReportFormProcessor._collect_full_text_from_base",
        lambda self: "placeholder base",
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._safe_virtual_document_text",
        lambda self: "document text with markers",
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._has_sufficient_sc13_markers",
        lambda text: text == "document text with markers",
    )

    assert processor._collect_full_text_from_base() == "document text with markers"

    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._safe_virtual_document_text",
        lambda self: "much longer document text",
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._has_sufficient_sc13_markers",
        lambda text: False,
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._is_table_placeholder_dominant_text",
        lambda text: True,
    )
    monkeypatch.setattr(
        "alpha.fins.processors.sc13_processor._normalize_whitespace",
        lambda text: "short",
    )

    assert processor._collect_full_text_from_base() == "much longer document text"