"""研究库进入 alpha init 的幂等初始化测试。"""

from pathlib import Path

from alpha.cli.workspace_migrations.research_store_init import migrate_research_store_init
from alpha.cli.workspace_migrations.runner import apply_all_workspace_migrations
from alpha.contracts.research import CreateResearchRequest
from alpha.research.storage.catalog import SQLiteResearchCatalog
from alpha.research.storage.store import ResearchStore
from alpha.workspace_paths import build_research_artifacts_dir, build_research_store_path


def test_init_preserves_existing_research(tmp_path: Path) -> None:
    """重复 init 不修改已建研究。参数：目录。返回：无。异常：断言失败。"""
    assert migrate_research_store_init(tmp_path)
    catalog = SQLiteResearchCatalog(ResearchStore(build_research_store_path(tmp_path)))
    research = catalog.create(CreateResearchRequest("owner", "key", "研究问题"))
    assert not migrate_research_store_init(tmp_path)
    assert catalog.get(research.research_id, "owner") == research
    assert build_research_artifacts_dir(tmp_path).is_dir()


def test_runner_initializes_research_store(tmp_path: Path) -> None:
    """迁移调度器登记研究库。参数：目录。返回：无。异常：断言失败。"""
    apply_all_workspace_migrations(base_dir=tmp_path, config_dir=tmp_path / "config")
    assert build_research_store_path(tmp_path).is_file()
