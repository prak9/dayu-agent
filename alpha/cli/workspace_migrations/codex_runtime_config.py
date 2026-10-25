"""已有工作区安装本地 Codex 模型定义，保持既有默认选择。"""

from pathlib import Path

from alpha.cli.workspace_migrations.run_json_utils import as_json_object, load_json_value, write_json_value
from alpha.startup.config_file_resolver import resolve_package_config_path

CODEX_MODEL_NAME = "codex-local"
_MODELS_FILE = "llm_models.json"


def migrate_codex_runtime_config(config_dir: Path) -> bool:
    """补齐可选择的原生运行器。参数：配置根目录。返回：是否修改。异常：配置损坏。"""
    path = config_dir / _MODELS_FILE
    if not path.exists():
        return False
    models = as_json_object(load_json_value(path))
    package = as_json_object(load_json_value(resolve_package_config_path() / _MODELS_FILE))
    if models is None or package is None:
        raise ValueError("llm_models.json 必须为对象")
    changed = CODEX_MODEL_NAME not in models
    if changed:
        models[CODEX_MODEL_NAME] = package[CODEX_MODEL_NAME]
        write_json_value(path, models)
    return changed


def configure_codex_defaults(config_dir: Path) -> int:
    """按用户明确 --codex 选择配置全部 scene。参数：配置目录。返回：实际更新数量。异常：配置损坏。"""
    migrate_codex_runtime_config(config_dir)
    count = 0
    for path in sorted((config_dir / "prompts" / "manifests").glob("*.json")):
        manifest = as_json_object(load_json_value(path))
        if manifest is None:
            raise ValueError("scene manifest 必须为对象")
        model = as_json_object(manifest.get("model"))
        if model is None:
            continue
        allowed = model.get("allowed_names")
        if allowed is not None and not isinstance(allowed, list):
            raise ValueError("model.allowed_names 必须为数组")
        changed = model.get("default_name") != CODEX_MODEL_NAME
        if isinstance(allowed, list) and CODEX_MODEL_NAME not in allowed:
            allowed.append(CODEX_MODEL_NAME)
            changed = True
        if changed:
            model["default_name"] = CODEX_MODEL_NAME
            write_json_value(path, manifest)
            count += 1
    return count
