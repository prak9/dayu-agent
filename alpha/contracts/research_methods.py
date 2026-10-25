"""研究方法的不可变资源身份，不包含模型或渠道实现。"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResearchMethodBundle:
    """经过完整性核对的方法包及首次载入文本。"""

    method_hash: str
    root: Path
    entrypoint_text: str
