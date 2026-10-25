"""为已有及全新工作区初始化独立研究库，不改变财报或 Host 记录。"""

from pathlib import Path

from alpha.research.storage.store import ResearchStore
from alpha.workspace_paths import build_research_artifacts_dir, build_research_store_path


def migrate_research_store_init(base_dir: Path) -> bool:
    """创建当前研究 schema。参数：base_dir 工作区。返回：是否首次创建。异常：schema 冲突或 I/O 错误。"""
    path = build_research_store_path(base_dir)
    created = not path.exists()
    ResearchStore(path)
    build_research_artifacts_dir(base_dir).mkdir(parents=True, exist_ok=True)
    return created
