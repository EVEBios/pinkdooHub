"""Phase 9.3 运维命令的确认闸门与目标契约。"""

import pytest

from scripts.release.phase93_operations import (
    FAILURE_DATABASE,
    RESTORE_DATABASE,
    Phase93Operations,
)
from scripts.release.phase93_rehearsal import RehearsalError, config_for_run


def _operations() -> Phase93Operations:
    return Phase93Operations(config_for_run("20260831t120000"))


def test_restore_refuses_wrong_project_before_reading_workspace() -> None:
    with pytest.raises(RehearsalError, match="project confirmation"):
        _operations().restore_database(
            confirm_project="wrong-project",
            confirm_database=RESTORE_DATABASE,
        )


def test_restore_refuses_wrong_database_before_reading_workspace() -> None:
    operations = _operations()
    with pytest.raises(RehearsalError, match="database confirmation"):
        operations.restore_database(
            confirm_project=operations.config.project,
            confirm_database="mysql",
        )


def test_image_restore_refuses_wrong_project_before_reading_workspace() -> None:
    with pytest.raises(RehearsalError, match="project confirmation"):
        _operations().restore_images(confirm_project="wrong-project")


def test_stop_refuses_wrong_project_before_reading_workspace() -> None:
    with pytest.raises(RehearsalError, match="project confirmation"):
        _operations().stop(confirm_project="wrong-project")


def test_cleanup_refuses_wrong_exact_targets_before_reading_workspace() -> None:
    operations = _operations()
    with pytest.raises(RehearsalError, match="project confirmation"):
        operations.cleanup(
            confirm_project="wrong-project",
            confirm_workspace=str(operations.config.root),
        )
    with pytest.raises(RehearsalError, match="workspace confirmation"):
        operations.cleanup(
            confirm_project=operations.config.project,
            confirm_workspace="/tmp",
        )


def test_failure_drill_refuses_wrong_exact_targets_before_workspace() -> None:
    operations = _operations()
    with pytest.raises(RehearsalError, match="project confirmation"):
        operations.run_failure_drill(
            confirm_project="wrong-project",
            confirm_database=FAILURE_DATABASE,
        )
    with pytest.raises(RehearsalError, match="database confirmation"):
        operations.run_failure_drill(
            confirm_project=operations.config.project,
            confirm_database="pinkdoohub",
        )


def test_dependency_and_restart_drills_require_exact_project() -> None:
    operations = _operations()
    with pytest.raises(RehearsalError, match="project confirmation"):
        operations.run_dependency_drill(confirm_project="wrong-project")
    with pytest.raises(RehearsalError, match="project confirmation"):
        operations.restart_application(confirm_project="wrong-project")


def test_restore_verification_requires_exact_project_and_database() -> None:
    operations = _operations()
    with pytest.raises(RehearsalError, match="project confirmation"):
        operations.verify_restore(
            confirm_project="wrong-project",
            confirm_database=RESTORE_DATABASE,
        )
    with pytest.raises(RehearsalError, match="database confirmation"):
        operations.verify_restore(
            confirm_project=operations.config.project,
            confirm_database="pinkdoohub",
        )
