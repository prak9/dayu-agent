"""为已有工作区补齐研究 registrar、发布 lane 和新增渠道配置，不覆盖定制值。"""

from pathlib import Path
import hashlib

from alpha.cli.workspace_migrations.run_json_utils import JsonObject, as_json_object, atomic_write_text, load_json_value, write_json_value
from alpha.startup.config_file_resolver import resolve_package_config_path

_REGISTRARS_FILE = "toolset_registrars.json"
_RESEARCH_TOOLSET = "research"
_RESEARCH_REGISTRAR = "alpha.research.toolset_registrars.register_research_toolset"
_CHANNEL_CONFIG_FILES = ("telegram.json", "notion.json")
_RUN_FILE = "run.json"
_HOST_KEY = "host_config"
_LANES_KEY = "lane"
_PUBLICATION_LANE = "publication"
_DEFAULT_PUBLICATION_CONCURRENCY = 1
_RESEARCH_PROMPT = "prompts/scenes/research.md"
_PREVIOUS_PROMPT_HASH = "4fc72c43471ceeac9de42a276249cbe1eb92858df69428aef0109ebba8bfae18"
_RESEARCH_MANIFEST = "prompts/manifests/research.json"
_PREVIOUS_RESEARCH_TAGS = ["research", "web", "fins", "ingestion"]
_CURRENT_RESEARCH_TAGS = ["research", "web", "fins"]


def _mapping(parent: JsonObject, key: str) -> JsonObject:
    """取得配置映射，缺失时新建。参数：父对象、键。返回：映射。异常：已有值不是对象。"""
    if key not in parent:
        parent[key] = {}
    mapped = as_json_object(parent[key])
    if mapped is None:
        raise ValueError(f"配置 {key} 必须是 JSON 对象")
    return mapped


def _add_publication_lane(path: Path) -> bool:
    """补发布并发配置。参数：run.json 路径。返回：是否修改。异常：配置损坏或写入失败。"""
    if not path.exists():
        return False
    payload = as_json_object(load_json_value(path))
    if payload is None:
        raise ValueError("run.json 必须是对象")
    lanes = _mapping(_mapping(payload, _HOST_KEY), _LANES_KEY)
    if _PUBLICATION_LANE in lanes:
        return False
    lanes[_PUBLICATION_LANE] = _DEFAULT_PUBLICATION_CONCURRENCY
    write_json_value(path, payload)
    return True


def migrate_research_runtime_config(config_dir: Path) -> bool:
    """增量升级研究配置。参数：工作区配置根目录。返回：是否补齐。异常：损坏配置、包资源或 I/O 错误。"""
    if not config_dir.exists():
        return False
    package = resolve_package_config_path()
    changed = False
    prompt = config_dir / _RESEARCH_PROMPT
    if prompt.exists() and hashlib.sha256(prompt.read_bytes()).hexdigest() == _PREVIOUS_PROMPT_HASH:
        atomic_write_text(prompt, (package / _RESEARCH_PROMPT).read_text(encoding="utf-8"))
        changed = True
    manifest = config_dir / _RESEARCH_MANIFEST
    if manifest.exists():
        definition = as_json_object(load_json_value(manifest))
        selection = as_json_object(definition.get("tool_selection")) if definition is not None else None
        if selection is not None and selection.get("tool_tags_any") == _PREVIOUS_RESEARCH_TAGS:
            selection["tool_tags_any"] = list(_CURRENT_RESEARCH_TAGS)
            if definition is not None:
                write_json_value(manifest, definition)
                changed = True
    registrar = config_dir / _REGISTRARS_FILE
    if not registrar.exists():
        atomic_write_text(registrar, (package / _REGISTRARS_FILE).read_text(encoding="utf-8"))
        changed = True
    else:
        payload = as_json_object(load_json_value(registrar))
        if payload is None:
            raise ValueError("toolset_registrars.json 必须是对象")
        if _RESEARCH_TOOLSET not in payload:
            payload[_RESEARCH_TOOLSET] = _RESEARCH_REGISTRAR
            write_json_value(registrar, payload)
            changed = True
    for name in _CHANNEL_CONFIG_FILES:
        destination = config_dir / name
        if not destination.exists():
            atomic_write_text(destination, (package / name).read_text(encoding="utf-8"))
            changed = True
    return _add_publication_lane(config_dir / _RUN_FILE) or changed
