"""Phase 9.2 干净构建工具链版本契约。"""

import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MINIAPP_ROOT = REPOSITORY_ROOT / "miniapp"
EXPECTED_PYTHON_VERSION = "3.10.9"
EXPECTED_NODE_VERSION = "24.13.0"
EXPECTED_NPM_VERSION = "11.6.2"
OFFICIAL_NPM_REGISTRY = "https://registry.npmjs.org/"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_npm_config() -> dict[str, str]:
    return dict(
        line.split("=", maxsplit=1)
        for line in (MINIAPP_ROOT / ".npmrc").read_text(
            encoding="utf-8"
        ).splitlines()
        if line and not line.startswith("#") and "=" in line
    )


def test_python_version_is_pinned_for_clean_environments() -> None:
    assert (REPOSITORY_ROOT / ".python-version").read_text(
        encoding="utf-8"
    ).strip() == EXPECTED_PYTHON_VERSION


def test_node_and_npm_versions_are_pinned_consistently() -> None:
    package = _read_json(MINIAPP_ROOT / "package.json")
    lockfile = _read_json(MINIAPP_ROOT / "package-lock.json")
    expected_engines = {
        "node": EXPECTED_NODE_VERSION,
        "npm": EXPECTED_NPM_VERSION,
    }

    assert (MINIAPP_ROOT / ".node-version").read_text(
        encoding="utf-8"
    ).strip() == EXPECTED_NODE_VERSION
    assert package["packageManager"] == f"npm@{EXPECTED_NPM_VERSION}"
    assert package["engines"] == expected_engines
    assert lockfile["packages"][""]["engines"] == expected_engines


def test_npm_install_policy_is_reproducible_and_strict() -> None:
    npm_config = _read_npm_config()

    assert npm_config == {
        "registry": OFFICIAL_NPM_REGISTRY,
        "legacy-peer-deps": "true",
        "engine-strict": "true",
    }
