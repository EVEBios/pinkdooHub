"""Gate A 持久备份与隔离恢复边界。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from scripts.release import gatea_backup as backup
from scripts.release import gatea_operations as gatea


def _values(backup_root: Path) -> dict[str, str]:
    return {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:" + "a" * 40,
        "GATEA_BACKUP_ROOT": str(backup_root),
    }


def _directories(tmp_path: Path) -> tuple[Path, Path, Path]:
    backup_root = tmp_path / "backups"
    backup_record_dir = tmp_path / "records" / "backups"
    restore_record_dir = tmp_path / "records" / "restores"
    for directory in (
        backup_root,
        backup_root / "mysql",
        backup_root / "images",
        backup_record_dir,
        restore_record_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)
    return backup_root, backup_record_dir, restore_record_dir


def _render_restore_compose() -> dict[str, object]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required to validate restore topology")
    with tempfile.TemporaryDirectory(prefix="gatea-restore-contract-") as raw:
        root = Path(raw)
        secret_dir = root / "secrets"
        secret_dir.mkdir()
        for name in gatea.EXPECTED_SECRET_FILES:
            (secret_dir / name).write_text("contract-only\n", encoding="utf-8")
        config = root / "config.env"
        config.write_text(
            "\n".join(
                (
                    "GATEA_APP_IMAGE=pinkdoohub-gatea:" + "a" * 40,
                    f"GATEA_CONFIG_FILE={config}",
                    f"GATEA_SECRET_DIR={secret_dir}",
                    "APP_NAME=pinkdooHub",
                    "APP_VERSION=0.6.0",
                    "APP_ENV=production",
                    "APP_DEBUG=false",
                    "DB_ENGINE=mysql",
                    "DB_HOST=mysql",
                    "DB_PORT=3306",
                    "DB_NAME=pinkdoohub_gatea",
                    "DB_USER=pinkdoo_app",
                    "PRODUCT_IMAGE_UPLOAD_DIR=/data/images",
                    "PRODUCT_IMAGE_BASE_URL=https://api-test.pinkdoohub.cn/uploads/products",
                    "JWT_ALGORITHM=HS256",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            (
                "docker",
                "compose",
                "--env-file",
                str(config),
                "--file",
                str(backup.RESTORE_COMPOSE),
                "--profile",
                "operations",
                "config",
                "--format",
                "json",
            ),
            check=True,
            capture_output=True,
            text=True,
            env=os.environ
            | {"GATEA_RESTORE_PROJECT": "pinkdoohub-gatea-restore-contract"},
        )
    return json.loads(result.stdout)


def test_backup_id_and_restore_project_are_exact() -> None:
    backup_id = "20260902t120000z"

    assert backup.restore_project(backup_id) == (
        "pinkdoohub-gatea-restore-20260902t120000z"
    )
    for invalid in ("20260902T120000Z", "latest", "../escape", "20260902t1200z"):
        with pytest.raises(gatea.GateAError, match="YYYYMMDD"):
            backup.restore_project(invalid)


def test_restore_compose_is_isolated_and_has_no_host_ports() -> None:
    payload = _render_restore_compose()
    services = payload["services"]

    assert payload["name"] == "pinkdoohub-gatea-restore-contract"
    assert set(services) == {
        "mysql-restore",
        "redis",
        "image-restore",
        "image-init",
        "restore-app",
    }
    assert all("ports" not in service for service in services.values())
    assert services["mysql-restore"]["image"] == "mysql:8.0.46"
    assert services["redis"]["image"] == "redis:8.0.1-alpine"
    assert services["restore-app"]["environment"]["DB_HOST"] == "mysql-restore"
    assert payload["networks"]["restore"]["internal"] is True
    volume_names = {value["name"] for value in payload["volumes"].values()}
    assert volume_names == {
        "pinkdoohub-gatea-restore-contract-mysql-data",
        "pinkdoohub-gatea-restore-contract-product-images",
    }
    assert "pinkdoohub-gatea-mysql-data" not in str(payload)
    assert "pinkdoohub-gatea-product-images" not in str(payload)


def test_restore_command_binds_exact_project_and_standalone_compose() -> None:
    command = backup.restore_command(
        project="pinkdoohub-gatea-restore-20260902t120000z",
        config_file=Path("/config.env"),
        operations_profile=True,
        arguments=("config", "--quiet"),
    )

    assert command[:4] == [
        "docker",
        "compose",
        "--project-name",
        "pinkdoohub-gatea-restore-20260902t120000z",
    ]
    assert str(backup.RESTORE_COMPOSE) in command
    assert command[-4:] == ["--profile", "operations", "config", "--quiet"]


def test_snapshot_parser_rejects_non_object_or_invalid_json() -> None:
    assert backup._parse_snapshot('{"tables": 10}') == {"tables": 10}

    for value in ("", "[]", "not-json"):
        with pytest.raises(gatea.GateAError, match="snapshot output"):
            backup._parse_snapshot(value)


def test_create_backup_stops_writes_records_artifacts_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    values = _values(backup_root)
    compose_commands: list[tuple[str, ...]] = []
    restarted: list[bool] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(gatea, "validate_app_image", lambda value: "sha256:image")
    monkeypatch.setattr(gatea, "_require_migration_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in ("mysql", "redis", "app", "nginx")
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: compose_commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(backup, "_source_snapshot", lambda *args: {"tables": 10})
    monkeypatch.setattr(backup, "_source_image_manifest", lambda *args: [])

    def fake_stream(**kwargs: object) -> None:
        Path(kwargs["path"]).write_bytes(b"verified-artifact")
        Path(kwargs["path"]).chmod(0o600)

    monkeypatch.setattr(backup, "_stream_source_artifact", fake_stream)
    monkeypatch.setattr(
        gatea,
        "app_up",
        lambda **kwargs: restarted.append(True),
    )

    backup.create_backup(
        backup_id="20260902t120000z",
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        backup_root=backup_root,
        backup_record_dir=backup_records,
        release_record_dir=tmp_path / "releases",
        wait_timeout=180,
    )

    assert compose_commands == [("stop", "--timeout", "30", "nginx", "app")]
    assert restarted == [True]
    payload = json.loads(
        (backup_records / "20260902t120000z.json").read_text(encoding="utf-8")
    )
    assert payload["passed"] is True
    assert payload["database_snapshot"] == {"tables": 10}
    assert payload["redis_recovery_policy"] == (
        "start-empty-and-invalidate-refresh-sessions"
    )
    for name in ("mysql", "images"):
        path = Path(payload["artifacts"][name]["path"])
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600


def _write_backup_fixture(
    backup_root: Path,
    backup_records: Path,
    backup_id: str,
) -> dict[str, object]:
    database_path, image_path = backup._backup_paths(backup_root, backup_id)
    database_path.write_bytes(b"sql")
    image_path.write_bytes(b"tar")
    database_path.chmod(0o600)
    image_path.chmod(0o600)
    payload: dict[str, object] = {
        "schema_version": 1,
        "backup_id": backup_id,
        "candidate_sha": "a" * 40,
        "database_snapshot": {"tables": 10},
        "image_manifest": [],
        "artifacts": {
            "mysql": {
                "path": str(database_path),
                "bytes": database_path.stat().st_size,
                "sha256": backup._sha256(database_path),
            },
            "images": {
                "path": str(image_path),
                "bytes": image_path.stat().st_size,
                "sha256": backup._sha256(image_path),
            },
        },
        "passed": True,
    }
    (backup_records / f"{backup_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return payload


def test_load_backup_record_rejects_tampered_artifact(tmp_path: Path) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    backup_id = "20260902t120000z"
    payload = _write_backup_fixture(backup_root, backup_records, backup_id)

    loaded, _, image_path = backup._load_backup_record(
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_records,
    )
    assert loaded == payload

    image_path.write_bytes(b"tampered")
    with pytest.raises(gatea.GateAError, match="record is invalid"):
        backup._load_backup_record(
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_records,
        )


def test_verify_restore_compares_and_always_removes_temporary_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(backup_root, backup_records, backup_id)
    values = _values(backup_root)
    commands: list[tuple[str, ...]] = []
    absence_checks: list[str] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        backup,
        "_restore_project_absent",
        lambda project: absence_checks.append(project),
    )
    monkeypatch.setattr(backup, "_restore_snapshot", lambda *args: {"tables": 10})
    monkeypatch.setattr(backup, "_restored_image_manifest", lambda *args: [])

    def fake_restore(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        commands.append(arguments)
        stdout = ""
        if arguments[:3] == ("exec", "--no-tty", "redis"):
            stdout = "0\n"
        elif arguments[:3] == ("ps", "--all", "--format"):
            stdout = json.dumps(
                {"Service": "restore-app", "Publishers": []}
            )
        return subprocess.CompletedProcess([], 0, stdout=stdout)

    monkeypatch.setattr(backup, "_run_restore", fake_restore)

    project = backup.restore_project(backup_id)
    backup.verify_restore(
        backup_id=backup_id,
        confirm_project=project,
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        backup_root=backup_root,
        backup_record_dir=backup_records,
        restore_record_dir=restore_records,
        wait_timeout=180,
    )

    assert commands[-1] == ("down", "--volumes", "--remove-orphans")
    assert absence_checks == [project, project]
    record = json.loads(
        (restore_records / f"{backup_id}.json").read_text(encoding="utf-8")
    )
    assert record["passed"] is True
    assert record["temporary_resources_removed"] is True
    assert record["refresh_sessions_invalidated"] is True


def test_restore_confirmation_fails_before_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called = False

    def unexpected(**kwargs: object) -> dict[str, str]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(gatea, "_validated_inputs", unexpected)

    with pytest.raises(gatea.GateAError, match="confirmation"):
        backup.verify_restore(
            backup_id="20260902t120000z",
            confirm_project="wrong-project",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_root=tmp_path,
            backup_record_dir=tmp_path,
            restore_record_dir=tmp_path,
            wait_timeout=180,
        )

    assert called is False


def test_restore_mismatch_still_removes_isolated_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(backup_root, backup_records, backup_id)
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: _values(backup_root),
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(backup, "_restore_project_absent", lambda project: None)
    monkeypatch.setattr(backup, "_restore_snapshot", lambda *args: {"tables": 9})
    monkeypatch.setattr(backup, "_restored_image_manifest", lambda *args: [])

    def fake_restore(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        commands.append(arguments)
        stdout = "0\n" if arguments[:3] == ("exec", "--no-tty", "redis") else ""
        return subprocess.CompletedProcess([], 0, stdout=stdout)

    monkeypatch.setattr(backup, "_run_restore", fake_restore)

    with pytest.raises(gatea.GateAError, match="verification failed"):
        backup.verify_restore(
            backup_id=backup_id,
            confirm_project=backup.restore_project(backup_id),
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_root=backup_root,
            backup_record_dir=backup_records,
            restore_record_dir=restore_records,
            wait_timeout=180,
        )

    assert commands[-1] == ("down", "--volumes", "--remove-orphans")
    assert not (restore_records / f"{backup_id}.json").exists()
