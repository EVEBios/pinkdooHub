"""Gate A 微信产物入口与发布元数据契约。"""

import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MINIAPP_ROOT = REPOSITORY_ROOT / "miniapp"
RELEASE_DESCRIPTION = (
    "pinkdooHub 微信小程序客户端（Gate A 内部测试版；不可公开）"
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_weapp_project_disables_source_map_upload() -> None:
    project_config = _read_json(MINIAPP_ROOT / "project.config.json")

    assert project_config["miniprogramRoot"] == "dist/weapp/"
    assert project_config["setting"]["urlCheck"] is True
    assert project_config["setting"]["uploadWithSourceMap"] is False


def test_current_release_metadata_is_wechat_only_and_internal() -> None:
    project_config = _read_json(MINIAPP_ROOT / "project.config.json")
    package = _read_json(MINIAPP_ROOT / "package.json")

    assert project_config["description"] == RELEASE_DESCRIPTION
    assert package["description"] == RELEASE_DESCRIPTION
