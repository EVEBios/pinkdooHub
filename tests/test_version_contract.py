"""应用版本来源一致性契约。"""

from pathlib import Path

from app.core.config import Settings


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "0.5.0"


def test_default_application_version_matches_release_candidate() -> None:
    """代码默认版本必须与当前候选版本一致。"""

    assert Settings.model_fields["app_version"].default == EXPECTED_VERSION


def test_example_environment_version_matches_release_candidate() -> None:
    """新环境复制的示例配置不得回退到旧版本。"""

    entries = dict(
        line.split("=", maxsplit=1)
        for line in (REPOSITORY_ROOT / ".env.example").read_text(
            encoding="utf-8"
        ).splitlines()
        if line and not line.startswith("#") and "=" in line
    )

    assert entries["APP_VERSION"] == EXPECTED_VERSION
