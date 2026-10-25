"""`toolset_config` 额外覆盖测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from alpha.contracts.toolset_config import (
    ToolsetConfigSnapshot,
    build_toolset_config_snapshot,
    coerce_toolset_config_float,
    coerce_toolset_config_int,
    find_toolset_config,
    normalize_toolset_configs,
    normalize_toolset_name,
    replace_toolset_config,
    serialize_toolset_config_payload_value,
)


@dataclass(frozen=True)
class _ToolConfig:
    """测试用 dataclass 配置对象。"""

    limit: int
    path: Path


@pytest.mark.unit
def test_toolset_config_normalize_find_replace_and_build_snapshot() -> None:
    """toolset 快照应支持规范化、替换、查找和 dataclass 构造。"""

    doc_snapshot = ToolsetConfigSnapshot(toolset_name=" doc ", payload={"limit": 1})
    web_snapshot = ToolsetConfigSnapshot(toolset_name="web", payload={"timeout": 2})

    normalized = normalize_toolset_configs((doc_snapshot, web_snapshot, ToolsetConfigSnapshot("doc", payload={"limit": 3})))
    found = find_toolset_config(normalized, "doc")
    replaced = replace_toolset_config(normalized, ToolsetConfigSnapshot("web", payload={"timeout": 9}))
    built = build_toolset_config_snapshot("fins", _ToolConfig(limit=5, path=Path("/tmp/demo")))

    assert normalize_toolset_name("  doc  ") == "doc"
    assert found is not None and found.payload == {"limit": 3}
    assert find_toolset_config(replaced, "web") is not None
    assert built is not None and built.payload == {"limit": 5, "path": "/tmp/demo"}


@pytest.mark.unit
def test_toolset_config_serialization_and_coercion_helpers() -> None:
    """toolset 配置值序列化与数值收敛应覆盖主要输入分支。"""

    serialized = serialize_toolset_config_payload_value(
        cast(Any, {
            "path": Path("/tmp/file"),
            "items": [1, 2],
            "nested": {"flag": True},
        })
    )

    assert serialized == {"path": "/tmp/file", "items": [1, 2], "nested": {"flag": True}}
    assert coerce_toolset_config_int("42", field_name="limit", default=1) == 42
    assert coerce_toolset_config_int(" ", field_name="limit", default=5) == 5
    assert coerce_toolset_config_float("3.5", field_name="ratio", default=1.0) == 3.5
    assert coerce_toolset_config_float(None, field_name="ratio", default=2.0) == 2.0

    with pytest.raises(TypeError):
        serialize_toolset_config_payload_value(cast(Any, set()))
    with pytest.raises(TypeError):
        coerce_toolset_config_int(True, field_name="limit", default=1)
    with pytest.raises(TypeError):
        coerce_toolset_config_float("bad", field_name="ratio", default=1.0)


@pytest.mark.unit
def test_build_toolset_config_snapshot_rejects_invalid_inputs() -> None:
    """构造 toolset 快照时应拒绝空名称与不支持类型。"""

    with pytest.raises(ValueError):
        normalize_toolset_name("   ")
    with pytest.raises(TypeError):
        build_toolset_config_snapshot("doc", object())
    assert build_toolset_config_snapshot("doc", None) is None