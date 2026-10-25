"""run.json 迁移：补齐 ``host_config.lane.write_chapter``。

2026-04 架构调整把写作流水线的并发上限从 in-process 常量
``_MIDDLE_CHAPTER_MAX_WORKERS`` 移交给 Host ``write_chapter`` lane。
旧工作区的 ``workspace/config/run.json`` 在 ``host_config.lane`` 下
没有该 key，启动期会缺失业务默认值。

本迁移只做一件事：在 ``host_config.lane`` 缺少 ``write_chapter`` 时补 5；
存在则一律尊重用户取值，绝不覆写。

写入采用「写临时文件 + ``os.replace`` 原子替换」：在 init 持有 workspace
advisory lock 的前提下额外抵御进程被强制终止时残留半截写入的边界情况。
"""

from __future__ import annotations

from pathlib import Path

from alpha.cli.workspace_migrations.run_json_utils import (
    as_json_object,
    load_json_value,
    write_json_value,
)


_RUN_JSON_FILENAME = "run.json"
_HOST_CONFIG_KEY = "host_config"
_LANE_KEY = "lane"
_WRITE_CHAPTER_LANE = "write_chapter"
_DEFAULT_WRITE_CHAPTER_CONCURRENCY = 5


def migrate_run_json_add_write_chapter_lane(config_dir: Path) -> bool:
    """为旧工作区的 ``run.json`` 补齐 ``write_chapter`` lane 默认值。

    Args:
        config_dir: 工作区配置目录，即 ``workspace/config``。

    Returns:
        True 表示实际改写了文件；False 表示无需变更或文件不存在。

    Raises:
        OSError: 读取或写入 ``run.json`` 失败时抛出，由 init 命令显式失败。
        json.JSONDecodeError: ``run.json`` 既存但 JSON 解析失败；不再吞错，
            由上层决定是否继续。
    """

    run_json_path = config_dir / _RUN_JSON_FILENAME
    if not run_json_path.exists():
        return False

    payload = load_json_value(run_json_path)
    payload_obj = as_json_object(payload)
    if payload_obj is None:
        return False

    host_config = as_json_object(payload_obj.get(_HOST_CONFIG_KEY))
    if host_config is None:
        return False

    lane_section = as_json_object(host_config.get(_LANE_KEY))
    if lane_section is None:
        return False

    if _WRITE_CHAPTER_LANE in lane_section:
        return False

    lane_section[_WRITE_CHAPTER_LANE] = _DEFAULT_WRITE_CHAPTER_CONCURRENCY
    write_json_value(run_json_path, payload)
    return True
