"""原件幂等、Fins 财报边界、有界 PDF 与研究作用域的行为测试。"""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from io import BufferedWriter
import subprocess
import sys

import pytest
from pytest_mock import MockerFixture

from alpha.contracts.cancellation import CancellationToken, CancelledError
from alpha.contracts.protocols import ToolExecutionContext
from alpha.contracts.research import CreateResearchRequest, ResearchConflictError, SubmitResearchTurnRequest
from alpha.contracts.research_materials import FinancialMaterialTarget
from alpha.fins.storage.research_materials import FsFinancialMaterialBlobs
from alpha.fins.service_runtime import DefaultFinsRuntime
from alpha.fins.research_material_processing import prepare_financial_material_processor
from alpha.research.material_reading import extract_material_text
from alpha.research.material_tools import register_material_tools
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.materials import SQLiteResearchMaterials, validate_material
from alpha.research.storage.store import ResearchStore
from alpha.research.storage.turns import SQLiteResearchTurns
from tests.research.factories import research_turn_preparation
from alpha.services.research_material_service import prepare_research_materials
from tests.research.test_service import _service
from tests.research.test_tools import _registered

_PDF_FIXTURE = Path(__file__).parents[1] / "fixtures/docling/alpha_docling_integration_fixture.pdf"


def test_originals_are_immutable_owned_and_financial_bytes_live_only_in_fins(tmp_path: Path) -> None:
    """相同请求复用原件，财报字节不进入研究库。参数：目录。返回：无。异常：断言失败。"""
    store = ResearchStore(tmp_path / "research.db")
    catalog = SQLiteResearchCatalog(store)
    research = catalog.create(CreateResearchRequest("owner", "new", "研究"))
    other = catalog.create(CreateResearchRequest("owner", "other", "另一个研究"))
    financial = FsFinancialMaterialBlobs(tmp_path)
    materials = SQLiteResearchMaterials(store, financial)
    original = materials.put(research.research_id, "owner", "file", "note.md", b"# Original")
    assert materials.put(research.research_id, "owner", "file", "note.md", b"# Original") == original
    assert materials.put(research.research_id, "owner", "other-file", "note.md", b"# Original") == original
    assert materials.read(original.material_id, research.research_id, "owner")[1] == b"# Original"
    with pytest.raises(ResearchConflictError):
        materials.put(research.research_id, "owner", "file", "note.md", b"changed")
    with pytest.raises(PermissionError):
        materials.list_materials(research.research_id, "stranger")
    with pytest.raises(KeyError):
        materials.read(original.material_id, other.research_id, "owner")
    target = FinancialMaterialTarget("AAPL", "10-K")
    pdf = _PDF_FIXTURE.read_bytes()
    filing = materials.put(research.research_id, "owner", "filing", "report.pdf", pdf, target)
    assert filing.source_ref.startswith("fins://AAPL/materials/")
    assert materials.read(filing.material_id, research.research_id, "owner")[1] == pdf
    assert financial.put(target, filing.material_id, filing.name, pdf) == filing.source_ref
    with pytest.raises(ValueError, match="冲突"):
        financial.put(target, filing.material_id, filing.name, b"changed")
    with store.connection() as conn:
        assert conn.execute("SELECT body FROM research_materials WHERE material_id=?", (filing.material_id,)).fetchone()[0] is None
    catalog.archive(research.research_id, "owner")
    with pytest.raises(ResearchConflictError, match="打开"):
        materials.put(research.research_id, "owner", "archived", "note.md", b"new")
    with store.connection(write=True) as conn:
        conn.execute("UPDATE research_materials SET body=? WHERE material_id=?", (b"damaged", original.material_id))
    with pytest.raises(ResearchConflictError, match="完整性"):
        materials.read(original.material_id, research.research_id, "owner")


@pytest.mark.parametrize("name,body", [("../escape.md", b"x"), ("bad.exe", b"x"), ("bad.pdf", b"<html>denied</html>"),
    ("bad.txt", b"\xff"), ("bad.txt", b"\x00"), ("empty.md", b""), ("huge.txt", b"x" * (20 * 1024 * 1024 + 1))])
def test_invalid_bytes_never_become_verified_material(name: str, body: bytes) -> None:
    """真实字节优先于文件扩展名与声明长度。参数：文件、内容。返回：无。异常：断言失败。"""
    with pytest.raises(ValueError):
        validate_material(name, body)


def test_text_html_pdf_extraction_and_explicit_failures(tmp_path: Path, mocker: MockerFixture) -> None:
    """页码、HTML 正文和扫描件缺口均如实表达。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "create", "研究"))
    materials = prepare_research_materials(tmp_path, service).records
    text = materials.put(research.research_id, "owner", "text", "x.txt", b"text")
    assert extract_material_text(text, b"text", tmp_path / "tmp") == "text"
    html = replace(text, media_type="text/html")
    assert extract_material_text(html, b"<script>hidden</script><p>Body</p>", tmp_path / "tmp").strip() == "Body"
    pdf = replace(text, media_type="application/pdf")
    extracted = extract_material_text(pdf, _PDF_FIXTURE.read_bytes(), tmp_path / "tmp")
    assert "[PDF 第 1 页]" in extracted and "Integration" in extracted
    assert list((tmp_path / "tmp").iterdir()) == []
    for first, last in ((0, 1), (1, 6), (2, 1)):
        with pytest.raises(ValueError):
            extract_material_text(pdf, b"%PDF-broken", tmp_path / "tmp", first_page=first, last_page=last)
    with pytest.raises(ValueError, match="损坏"):
        extract_material_text(pdf, b"%PDF-broken", tmp_path / "tmp")
    with pytest.raises(ValueError, match="页码"):
        extract_material_text(text, b"text", tmp_path / "tmp", first_page=2, last_page=2)
    with pytest.raises(ValueError, match="有效正文"):
        extract_material_text(html, b"<script>x</script>", tmp_path / "tmp")
    with pytest.raises(ValueError, match="2 MiB"):
        extract_material_text(text, b"a" * (2 * 1024 * 1024 + 1), tmp_path / "tmp")
    mocker.patch("alpha.research.material_reading.shutil.which", return_value=None)
    with pytest.raises(ValueError, match="Poppler"):
        extract_material_text(pdf, b"%PDF-test", tmp_path / "tmp")


def test_pdf_cancel_reaps_child_and_cleans_temporary_files(tmp_path: Path, mocker: MockerFixture) -> None:
    """进程执行中取消不会留下子进程或原件副本。参数：目录、mock。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "create", "研究"))
    materials = prepare_research_materials(tmp_path, service).records
    material = materials.put(research.research_id, "owner", "pdf", "x.pdf", _PDF_FIXTURE.read_bytes())
    token = CancellationToken()
    original = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def spawn(command: list[str], *, stdout: BufferedWriter, stderr: int) -> subprocess.Popen[bytes]:
        """以真实阻塞子进程精确注入取消。参数：命令、输出、错误。返回：子进程。异常：启动错误。"""
        child = original([sys.executable, "-c", "import time; time.sleep(30)"], stdout=stdout, stderr=stderr)
        children.append(child)
        token.cancel()
        return child

    mocker.patch("alpha.research.material_reading.subprocess.Popen", side_effect=spawn)
    with pytest.raises(CancelledError):
        extract_material_text(material, _PDF_FIXTURE.read_bytes(), tmp_path / "tmp", token=token)
    assert children[0].poll() is not None and list((tmp_path / "tmp").iterdir()) == []


def test_material_tools_are_scoped_and_historical_unknown_time_is_rejected(tmp_path: Path) -> None:
    """附件只能由当前研究读取，历史模式不引入未知公开时间的新文件。参数：目录。返回：无。异常：断言失败。"""
    registry, working, scope = _registered(tmp_path)
    materials = SQLiteResearchMaterials(ResearchStore(tmp_path / "research.db"), FsFinancialMaterialBlobs(tmp_path))
    original = materials.put(scope.research_id, "owner", "text", "x.md", b"# Body")
    assert register_material_tools(registry, working, materials, tmp_path / "tmp", prepare_financial_material_processor(tmp_path)) == 3
    context = ToolExecutionContext(run_id=scope.run_id, tool_call_id="read")
    assert not registry.execute("research_read_material", {"material_id": original.material_id}, context)["ok"]
    turns = SQLiteResearchTurns(ResearchStore(tmp_path / "research.db"))
    turns.settle(scope.turn_id, scope.run_id)
    following = turns.enqueue(SubmitResearchTurnRequest(scope.research_id, "owner", "followup", "读取新材料"), research_turn_preparation())
    turns.claim_next(scope.research_id, "owner")
    turns.mark_submitted(following.turn_id, "next-run")
    context = replace(context, run_id="next-run")
    listing = registry.execute("research_list_materials", {}, context)
    assert listing["ok"] and listing["value"]["materials"][0]["material_id"] == original.material_id
    read = registry.execute("research_read_material", {"material_id": original.material_id}, context)
    assert read["ok"] and read["value"]["content"] == "# Body"
    assert not registry.execute("research_prepare_filing", {"material_id": original.material_id}, context)["ok"]
    assert not registry.execute("research_read_material", {"material_id": "other"}, context)["ok"]
    historical_root = tmp_path / "historical"
    registry, working, scope = _registered(historical_root, cutoff=datetime(2020, 1, 1, tzinfo=timezone.utc))
    materials = SQLiteResearchMaterials(ResearchStore(historical_root / "research.db"), FsFinancialMaterialBlobs(historical_root))
    original = materials.put(scope.research_id, "owner", "later", "x.md", b"Body")
    register_material_tools(registry, working, materials, historical_root / "tmp", prepare_financial_material_processor(historical_root))
    assert not registry.execute("research_read_material", {"material_id": original.material_id}, replace(context, run_id="run"))["ok"]


def test_material_service_queues_once_and_financial_caption_is_explicit(tmp_path: Path) -> None:
    """普通附件和明确财报路由相同新输入；重复请求不重复排队。参数：目录。返回：无。异常：断言失败。"""
    research_service = _service(tmp_path)
    research = research_service.create(CreateResearchRequest("owner", "create", "研究"))
    service = prepare_research_materials(tmp_path, research_service)
    turn = service.accept(research.research_id, "owner", "file", "x.md", b"# New", "检查变化")
    assert service.accept(research.research_id, "owner", "file", "x.md", b"# New", "检查变化") == turn
    assert len(turn.attachment_refs) == 1
    financial = service.accept(research.research_id, "owner", "pdf", "x.pdf", _PDF_FIXTURE.read_bytes(), "/filing AAPL 10-K 核对收入")
    assert "fins://" in financial.user_text
    with pytest.raises(ValueError, match="格式"):
        service.accept(research.research_id, "owner", "bad", "x.md", b"text", "/filing AAPL")


@pytest.mark.timeout(90)
def test_uploaded_financial_pdf_is_readable_by_existing_fins_tools(tmp_path: Path) -> None:
    """原件通过既有 Fins 工具实际解析，不只验证字节回读。参数：目录。返回：无。异常：断言失败。"""
    service = _service(tmp_path)
    research = service.create(CreateResearchRequest("owner", "new", "财报研究"))
    material_service = prepare_research_materials(tmp_path, service)
    turn = material_service.accept(research.research_id, "owner", "pdf", "filing.pdf", _PDF_FIXTURE.read_bytes(), "/filing AAPL 10-K")
    assert prepare_financial_material_processor(tmp_path).prepare(FinancialMaterialTarget("AAPL", "10-K"), turn.attachment_refs[0], "filing.pdf", None) == turn.attachment_refs[0]
    tools = DefaultFinsRuntime.create(workspace_root=tmp_path).get_tool_service()
    sections = tools.get_document_sections(ticker="AAPL", document_id=turn.attachment_refs[0])
    assert sections["sections"] and sections["document_id"] == turn.attachment_refs[0]
    processor = prepare_financial_material_processor(tmp_path)
    assert processor.prepare(FinancialMaterialTarget("AAPL", "10-K"), turn.attachment_refs[0], "filing.pdf", None) == turn.attachment_refs[0]
    token = CancellationToken()
    token.cancel()
    with pytest.raises(CancelledError):
        processor.prepare(FinancialMaterialTarget("AAPL", "10-K"), turn.attachment_refs[0], "filing.pdf", token)


def test_structured_financial_processing_rolls_back_storage_failure(tmp_path: Path, mocker: MockerFixture) -> None:
    """转换后写入失败保留原件与旧主文档。参数：目录、mock。返回：无。异常：断言失败。"""
    blobs = FsFinancialMaterialBlobs(tmp_path)
    target = FinancialMaterialTarget("AAPL", "10-K")
    pdf = _PDF_FIXTURE.read_bytes()
    blobs.put(target, "material_test", "filing.pdf", pdf)
    processor = prepare_financial_material_processor(tmp_path)
    mocker.patch("alpha.fins.research_material_processing.convert_pdf_bytes_to_docling_json_bytes", return_value=b"{}")
    mocker.patch.object(processor._blobs, "store_file", side_effect=OSError("模拟磁盘错误"))
    with pytest.raises(OSError, match="磁盘"):
        processor.prepare(target, "material_test", "filing.pdf", CancellationToken())
    assert blobs.read(target, "material_test", "filing.pdf") == pdf
