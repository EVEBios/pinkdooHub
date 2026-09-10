"""Gate A 持久备份与隔离恢复边界。"""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import signal
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


def _m7_database_snapshot() -> dict[str, object]:
    return {
        "aerich_versions": ",".join(gatea.APPROVED_TARGET_M7_CHAIN),
        "tables": 23,
    }


def _m8_database_snapshot() -> dict[str, object]:
    return {
        "aerich_versions": ",".join(gatea.APPROVED_TARGET_M8_CHAIN),
        "tables": 23,
    }


def _m9_database_snapshot() -> dict[str, object]:
    return {
        "aerich_versions": ",".join(gatea.APPROVED_TARGET_M9_CHAIN),
        "tables": 27,
    }


def _m7_content_snapshot(digest: str = "7" * 64) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "profile": backup.M7_CONTENT_SNAPSHOT_PROFILE,
        "schema_version": backup.M7_CONTENT_SNAPSHOT_SCHEMA_VERSION,
    }


def _m9_table_content_snapshot(digest: str = "9" * 64) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "profile": backup.M9_TABLE_CONTENT_SNAPSHOT_PROFILE,
        "schema_version": backup.M9_TABLE_CONTENT_SNAPSHOT_SCHEMA_VERSION,
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
        tmp_path / "releases",
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


def test_run_restore_can_isolate_a_mandatory_recovery_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    def fake_run(
        command: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del command
        observed.append(dict(kwargs))
        return subprocess.CompletedProcess([], 0, stdout="")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)

    backup._run_restore(
        values={},
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        project="pinkdoohub-gatea-restore-20260902t120000z",
        arguments=("down", "--volumes", "--remove-orphans"),
        start_new_session=True,
    )

    assert observed[0]["start_new_session"] is True


def test_restore_cleanup_inventory_isolates_every_docker_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    isolation_flags: list[bool] = []

    def fake_run(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        isolation_flags.append(bool(kwargs.get("start_new_session")))
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)

    backup._restore_cleanup_verified(
        "pinkdoohub-gatea-restore-20260902t120000z"
    )

    assert [command[1:3] for command in commands] == [
        ("ps", "--all"),
        ("volume", "ls"),
        ("network", "ls"),
    ]
    assert isolation_flags == [True, True, True]


def test_restore_cleanup_retries_an_interrupted_child_until_inventory_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    down_calls: list[bool] = []
    verification_calls = 0

    def fake_restore(**kwargs: object) -> subprocess.CompletedProcess[str]:
        down_calls.append(bool(kwargs.get("start_new_session")))
        return subprocess.CompletedProcess(
            [],
            -2 if len(down_calls) == 1 else 0,
            stdout="",
        )

    def verify(project: str) -> None:
        nonlocal verification_calls
        assert project == "pinkdoohub-gatea-restore-20260902t120000z"
        verification_calls += 1
        if verification_calls == 1:
            raise gatea.GateAError("resources remain")

    monkeypatch.setattr(backup, "_run_restore", fake_restore)
    monkeypatch.setattr(backup, "_restore_cleanup_verified", verify)

    backup._cleanup_restore_project(
        values={},
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        project="pinkdoohub-gatea-restore-20260902t120000z",
    )

    assert down_calls == [True, True]
    assert verification_calls == 2


def test_snapshot_parser_rejects_non_object_or_invalid_json() -> None:
    assert backup._parse_snapshot('{"tables": 10}') == {"tables": 10}

    for value in ("", "[]", "not-json"):
        with pytest.raises(gatea.GateAError, match="snapshot output"):
            backup._parse_snapshot(value)


def test_m7_content_snapshot_contract_is_versioned_sanitized_and_pre_m8_safe() -> None:
    snapshot = _m7_content_snapshot()

    assert backup._validate_m7_content_snapshot(snapshot) == snapshot
    assert "umask 077" in backup.M7_CONTENT_SNAPSHOT_COMMAND
    assert 'chmod 0600 "$snapshot_file"' in backup.M7_CONTENT_SNAPSHOT_COMMAND
    assert "swatch_hex" not in backup.M7_CONTENT_SNAPSHOT_COMMAND
    assert "bead_colors" not in backup.M7_PRESERVED_TABLES
    for table in backup.M7_PRESERVED_TABLES:
        assert table in backup.M7_CONTENT_SNAPSHOT_COMMAND

    for invalid in (
        {},
        snapshot | {"schema_version": 2},
        snapshot | {"schema_version": 1.0},
        snapshot | {"schema_version": True},
        snapshot | {"profile": "other"},
        snapshot | {"content_sha256": "not-a-digest"},
        snapshot | {"extra": True},
    ):
        with pytest.raises(gatea.GateAError, match="content snapshot"):
            backup._validate_m7_content_snapshot(invalid)


def test_m9_table_content_snapshot_contract_is_exact_and_sanitized() -> None:
    snapshot = _m9_table_content_snapshot()

    assert backup._validate_m9_table_content_snapshot(snapshot) == snapshot
    assert "umask 077" in backup.M9_TABLE_CONTENT_SNAPSHOT_COMMAND
    assert 'chmod 0600 "$snapshot_file"' in backup.M9_TABLE_CONTENT_SNAPSHOT_COMMAND
    assert "--order-by-primary" in backup.M9_TABLE_CONTENT_SNAPSHOT_COMMAND
    assert "qr_token" not in backup.M9_TABLE_CONTENT_SNAPSHOT_COMMAND
    for table in backup.M9_TABLE_CONTENT_SNAPSHOT_TABLES:
        assert table in backup.M9_TABLE_CONTENT_SNAPSHOT_COMMAND

    for invalid in (
        {},
        snapshot | {"schema_version": 2},
        snapshot | {"schema_version": 1.0},
        snapshot | {"schema_version": True},
        snapshot | {"profile": "other"},
        snapshot | {"content_sha256": "not-a-digest"},
        snapshot | {"row_counts": {}},
    ):
        with pytest.raises(gatea.GateAError, match="M9 table content snapshot"):
            backup._validate_m9_table_content_snapshot(invalid)


def test_backup_runtime_services_follow_the_exact_migration_chain() -> None:
    m2_snapshot = {
        "aerich_versions": ",".join(gatea.APPROVED_SOURCE_M2_CHAIN)
    }
    assert backup._requires_table_sweeper(m2_snapshot) is False
    assert backup._requires_table_sweeper(_m7_database_snapshot()) is False
    assert backup._requires_table_sweeper(_m8_database_snapshot()) is False
    assert backup._requires_table_sweeper(_m9_database_snapshot()) is True
    assert backup._allows_legacy_m7_app_command(_m7_database_snapshot()) is True
    assert backup._allows_legacy_m7_app_command(m2_snapshot) is False
    assert backup._allows_legacy_m7_app_command(_m8_database_snapshot()) is False
    assert backup._allows_legacy_m7_app_command(_m9_database_snapshot()) is False

    with pytest.raises(gatea.GateAError, match="migration chain is not approved"):
        backup._requires_table_sweeper(
            {
                "aerich_versions": ",".join(gatea.APPROVED_TARGET_M9_CHAIN)
                + ",unknown"
            }
        )


def test_create_backup_stops_writes_records_artifacts_and_restarts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    values = _values(backup_root)
    compose_commands: list[tuple[str, ...]] = []
    image_validation_flags: list[bool] = []
    restarted: list[tuple[bool, bool, bool]] = []
    synced_directories: list[Path] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def fake_validate_image(
        value: object,
        *,
        allow_legacy_m7_command: bool = False,
    ) -> str:
        image_validation_flags.append(allow_legacy_m7_command)
        return "sha256:image"

    monkeypatch.setattr(gatea, "validate_app_image", fake_validate_image)
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: None)
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
        backup,
        "_fsync_directory",
        lambda path: synced_directories.append(path),
    )
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: compose_commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(backup, "_source_snapshot", lambda *args: _m7_database_snapshot())
    monkeypatch.setattr(
        backup,
        "_source_m7_content_snapshot",
        lambda *args: _m7_content_snapshot(),
    )
    monkeypatch.setattr(backup, "_source_image_manifest", lambda *args: [])

    def fake_stream(**kwargs: object) -> None:
        Path(kwargs["path"]).write_bytes(b"verified-artifact")
        Path(kwargs["path"]).chmod(0o600)

    monkeypatch.setattr(backup, "_stream_source_artifact", fake_stream)
    monkeypatch.setattr(
        gatea,
        "app_up",
        lambda **kwargs: restarted.append(
            (
                bool(kwargs["include_table_sweeper"]),
                bool(kwargs["allow_legacy_m7_command"]),
                bool(kwargs["_start_new_session"]),
            )
        ),
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
    assert image_validation_flags == [True]
    assert restarted == [(False, True, True)]
    payload = json.loads(
        (backup_records / "20260902t120000z.json").read_text(encoding="utf-8")
    )
    assert payload["passed"] is True
    assert payload["database_snapshot"] == _m7_database_snapshot()
    assert payload["m7_content_snapshot"] == _m7_content_snapshot()
    assert payload["redis_recovery_policy"] == (
        "start-empty-and-invalidate-refresh-sessions"
    )
    assert payload["table_sweeper_restarted"] is False
    assert not (backup_records / ".20260902t120000z.pending.json").exists()
    # pending 发布、final Record 发布及 pending 删除都必须同步 records 目录；
    # exclusive writer 清理同目录随机临时文件时还会额外同步。
    assert synced_directories.count(backup_records) >= 3
    for name in ("mysql", "images"):
        path = Path(payload["artifacts"][name]["path"])
        assert path.is_file()
        assert path.stat().st_mode & 0o777 == 0o600


def test_create_m9_backup_stops_and_strictly_restarts_the_table_sweeper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    values = _values(backup_root)
    compose_commands: list[tuple[str, ...]] = []
    image_validation_flags: list[bool] = []
    restarted: list[tuple[bool, bool]] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def fake_validate_image(
        value: object,
        *,
        allow_legacy_m7_command: bool = False,
    ) -> str:
        image_validation_flags.append(allow_legacy_m7_command)
        return "sha256:image"

    monkeypatch.setattr(gatea, "validate_app_image", fake_validate_image)
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in kwargs["services"]
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: compose_commands.append(tuple(kwargs["arguments"]))
        or subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(
        backup,
        "_source_snapshot",
        lambda *args: _m9_database_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_source_m7_content_snapshot",
        lambda *args: _m7_content_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_source_m9_table_content_snapshot",
        lambda *args: _m9_table_content_snapshot(),
    )
    monkeypatch.setattr(backup, "_source_image_manifest", lambda *args: [])

    def fake_stream(**kwargs: object) -> None:
        Path(kwargs["path"]).write_bytes(b"verified-artifact")
        Path(kwargs["path"]).chmod(0o600)

    monkeypatch.setattr(backup, "_stream_source_artifact", fake_stream)
    monkeypatch.setattr(
        gatea,
        "app_up",
        lambda **kwargs: restarted.append(
            (
                bool(kwargs["include_table_sweeper"]),
                bool(kwargs["allow_legacy_m7_command"]),
            )
        ),
    )

    backup.create_backup(
        backup_id="20260902t120001z",
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        backup_root=backup_root,
        backup_record_dir=backup_records,
        release_record_dir=tmp_path / "releases",
        wait_timeout=180,
    )

    assert compose_commands == [
        ("stop", "--timeout", "30", "nginx", "table-sweeper", "app")
    ]
    assert image_validation_flags == [False]
    assert restarted == [(True, False)]
    payload = json.loads(
        (backup_records / "20260902t120001z.json").read_text(encoding="utf-8")
    )
    assert payload["table_sweeper_restarted"] is True
    assert payload["m9_table_content_snapshot"] == _m9_table_content_snapshot()
    assert not (backup_records / ".20260902t120001z.pending.json").exists()


def test_create_m7_backup_rejects_chain_change_during_backup_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    values = _values(backup_root)
    snapshots = iter((_m7_database_snapshot(), _m8_database_snapshot()))
    recovery_flags: list[bool] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda value, **kwargs: "sha256:image",
    )
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in kwargs["services"]
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(backup, "_source_snapshot", lambda *args: next(snapshots))
    monkeypatch.setattr(
        backup,
        "_source_image_manifest",
        lambda *args: pytest.fail("chain drift must stop before artifact capture"),
    )
    monkeypatch.setattr(
        gatea,
        "app_up",
        lambda **kwargs: recovery_flags.append(
            bool(kwargs["allow_legacy_m7_command"])
        ),
    )

    with pytest.raises(gatea.GateAError, match="backup creation failed"):
        backup.create_backup(
            backup_id="20260902t120002z",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_root=backup_root,
            backup_record_dir=backup_records,
            release_record_dir=tmp_path / "releases",
            wait_timeout=180,
        )

    assert recovery_flags == [True]
    assert not (backup_records / "20260902t120002z.json").exists()
    pending = backup_records / ".20260902t120002z.pending.json"
    assert pending.is_file()
    assert pending.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "interruption",
    (
        KeyboardInterrupt(),
        gatea.GateAOperationInterrupted("controlled SIGTERM interruption"),
    ),
    ids=("keyboard-interrupt", "controlled-termination-signal"),
)
def test_create_backup_recovers_services_and_propagates_original_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interruption: BaseException,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    values = _values(backup_root)
    recovered: list[bool] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda value, **kwargs: "sha256:image",
    )
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in kwargs["services"]
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: subprocess.CompletedProcess([], 0, stdout=""),
    )
    monkeypatch.setattr(
        backup,
        "_source_snapshot",
        lambda *args: _m7_database_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_source_m7_content_snapshot",
        lambda *args: _m7_content_snapshot(),
    )
    monkeypatch.setattr(backup, "_source_image_manifest", lambda *args: [])
    monkeypatch.setattr(
        backup,
        "_stream_source_artifact",
        lambda **kwargs: (_ for _ in ()).throw(interruption),
    )
    monkeypatch.setattr(
        gatea,
        "app_up",
        lambda **kwargs: recovered.append(True),
    )

    with pytest.raises(type(interruption)) as caught:
        backup.create_backup(
            backup_id="20260902t120004z",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_root=backup_root,
            backup_record_dir=backup_records,
            release_record_dir=tmp_path / "releases",
            wait_timeout=180,
        )

    assert caught.value is interruption
    assert recovered == [True]
    assert not (backup_records / "20260902t120004z.json").exists()
    assert (backup_records / ".20260902t120004z.pending.json").is_file()


@pytest.mark.parametrize(
    ("interrupt_during_work", "signum"),
    [
        pytest.param(False, signal.SIGTERM, id="sigterm-during-recovery"),
        pytest.param(True, signal.SIGTERM, id="sigterm-during-work"),
        pytest.param(False, signal.SIGINT, id="sigint-during-recovery"),
        pytest.param(True, signal.SIGINT, id="sigint-during-work"),
    ],
)
def test_create_backup_defers_signals_until_service_recovery_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interrupt_during_work: bool,
    signum: int,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    values = _values(backup_root)
    previous_handlers = {
        backup.signal.SIGHUP: object(),
        backup.signal.SIGTERM: object(),
        backup.signal.SIGINT: object(),
    }
    active_handlers: dict[int, object] = {}
    recovery_events: list[str] = []
    first_interruptions: list[BaseException] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda value, **kwargs: "sha256:image",
    )
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in kwargs["services"]
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)

    def stop_or_interrupt(**kwargs: object) -> subprocess.CompletedProcess[str]:
        if interrupt_during_work:
            handler = active_handlers[signum]
            assert callable(handler)
            handler(signum, None)
        return subprocess.CompletedProcess([], 0, stdout="")

    monkeypatch.setattr(gatea, "_run_compose", stop_or_interrupt)
    monkeypatch.setattr(
        backup,
        "_source_snapshot",
        lambda *args: _m7_database_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_source_m7_content_snapshot",
        lambda *args: _m7_content_snapshot(),
    )
    monkeypatch.setattr(backup, "_source_image_manifest", lambda *args: [])

    def fake_stream(**kwargs: object) -> None:
        path = Path(kwargs["path"])
        path.write_bytes(b"verified-artifact")
        path.chmod(0o600)

    monkeypatch.setattr(backup, "_stream_source_artifact", fake_stream)
    monkeypatch.setattr(
        backup.signal,
        "getsignal",
        lambda signum: previous_handlers[signum],
    )
    monkeypatch.setattr(
        backup.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )

    def recover_and_receive_term(**kwargs: object) -> None:
        del kwargs
        recovery_events.append("started")
        handler = active_handlers[backup.signal.SIGINT]
        controller = getattr(handler, "__self__")
        assert isinstance(controller, backup._RecoveryTerminationController)
        if interrupt_during_work:
            assert controller.work_interruption is not None
            first_interruptions.append(controller.work_interruption)
        recovery_signal = (
            backup.signal.SIGHUP
            if interrupt_during_work
            else signum
        )
        recovery_handler = active_handlers[recovery_signal]
        assert callable(recovery_handler)
        recovery_handler(recovery_signal, None)
        if not interrupt_during_work:
            assert controller.deferred_interruptions
            first_interruptions.append(controller.deferred_interruptions[0])
        recovery_events.append("completed")

    monkeypatch.setattr(gatea, "app_up", recover_and_receive_term)

    expected_type = (
        KeyboardInterrupt
        if signum == signal.SIGINT
        else gatea.GateAOperationInterrupted
    )
    with pytest.raises(
        expected_type,
        match=f"received {signal.Signals(signum).name} and is recovering",
    ) as caught:
        backup.create_backup(
            backup_id="20260902t120005z",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_root=backup_root,
            backup_record_dir=backup_records,
            release_record_dir=tmp_path / "releases",
            wait_timeout=180,
        )

    assert recovery_events == ["started", "completed"]
    assert caught.value is first_interruptions[0]
    assert active_handlers == previous_handlers
    database_path, image_path = backup._backup_paths(
        backup_root, "20260902t120005z"
    )
    assert not database_path.exists()
    assert not image_path.exists()
    assert not (backup_records / "20260902t120005z.json").exists()
    assert (backup_records / ".20260902t120005z.pending.json").is_file()


def test_work_signal_handler_switches_phase_before_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_handlers = {
        backup.signal.SIGHUP: object(),
        backup.signal.SIGTERM: object(),
        backup.signal.SIGINT: object(),
    }
    active_handlers: dict[int, object] = {}
    monkeypatch.setattr(
        backup.signal,
        "getsignal",
        lambda signum: previous_handlers[signum],
    )
    monkeypatch.setattr(
        backup.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )

    with backup._recovery_termination_controller("backup") as termination:
        work_handler = active_handlers[backup.signal.SIGTERM]
        assert callable(work_handler)
        with pytest.raises(gatea.GateAOperationInterrupted) as caught:
            work_handler(backup.signal.SIGTERM, None)

        assert termination.recovery_started is True
        assert termination.work_interruption is caught.value
        recovery_handler = active_handlers[backup.signal.SIGHUP]
        assert callable(recovery_handler)
        assert recovery_handler(backup.signal.SIGHUP, None) is None
        assert len(termination.deferred_interruptions) == 1

    assert active_handlers == previous_handlers


def test_create_backup_rejects_an_existing_reservation_before_stopping_services(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    values = _values(backup_root)
    pending = backup_records / ".20260902t120003z.pending.json"
    pending.write_text("{}\n", encoding="utf-8")
    pending.chmod(0o600)
    compose_commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "validate_app_image",
        lambda value, **kwargs: "sha256:image",
    )
    monkeypatch.setattr(gatea, "_require_deployment_record", lambda **kwargs: None)
    monkeypatch.setattr(
        gatea,
        "_compose_ps",
        lambda **kwargs: [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in kwargs["services"]
        ],
    )
    monkeypatch.setattr(gatea, "_ensure_services_healthy", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_run_compose",
        lambda **kwargs: compose_commands.append(tuple(kwargs["arguments"])),
    )
    monkeypatch.setattr(backup, "_source_snapshot", lambda *args: _m7_database_snapshot())

    with pytest.raises(gatea.GateAError, match="backup ID already exists"):
        backup.create_backup(
            backup_id="20260902t120003z",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_root=backup_root,
            backup_record_dir=backup_records,
            release_record_dir=tmp_path / "releases",
            wait_timeout=180,
        )

    assert compose_commands == []


@pytest.mark.parametrize("blocker", ("candidate", "acceptance"))
def test_create_backup_rejects_global_release_state_before_compose_or_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    blocker: str,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    release_record_dir = tmp_path / "releases"
    acceptance_record_dir = tmp_path / "acceptance"
    acceptance_record_dir.mkdir()
    if blocker == "candidate":
        (release_record_dir / f"{'b' * 40}.config-rollback.pending.json").write_text(
            "{}\n", encoding="utf-8"
        )
    else:
        (
            acceptance_record_dir
            / (
                f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}not-a-sha"
                f"{gatea.M9_ACCEPTANCE_COMPLETE_SUFFIX}"
            )
        ).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail("global guard must run before compose config"),
    )
    monkeypatch.setattr(
        backup,
        "_source_snapshot",
        lambda *args: pytest.fail("global guard must run before snapshot"),
    )

    with pytest.raises(gatea.GateAError, match="unresolved"):
        backup.create_backup(
            backup_id="20260902t120004z",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_root=backup_root,
            backup_record_dir=backup_records,
            release_record_dir=release_record_dir,
            wait_timeout=180,
            acceptance_record_dir=acceptance_record_dir,
        )


def test_create_backup_does_not_globally_block_another_backup_id_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    other_pending = backup_records / ".20260902t120005z.pending.json"
    other_pending.write_text("{}\n", encoding="utf-8")
    other_pending.chmod(0o600)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)

    def after_global_guards(**kwargs: object) -> dict[str, str]:
        del kwargs
        raise RuntimeError("passed global release guards")

    monkeypatch.setattr(gatea, "_validated_inputs", after_global_guards)
    with pytest.raises(RuntimeError, match="passed global release guards"):
        backup.create_backup(
            backup_id="20260902t120006z",
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            backup_root=backup_root,
            backup_record_dir=backup_records,
            release_record_dir=tmp_path / "releases",
            wait_timeout=180,
        )


def test_backup_exclusive_json_writer_never_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    backup._write_json_exclusive(path, {"owner": "first"}, 0o644)

    with pytest.raises(gatea.GateAError, match="already reserved"):
        backup._write_json_exclusive(path, {"owner": "second"}, 0o644)

    assert json.loads(path.read_text(encoding="utf-8")) == {"owner": "first"}
    assert list(tmp_path.glob(".record.json.tmp-*")) == []


def test_exclusive_json_writer_never_publishes_partial_tempfile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "record.json"
    synced_directories: list[Path] = []

    def fail_after_partial_write(
        payload: object,
        stream: object,
        **kwargs: object,
    ) -> None:
        del payload, kwargs
        stream.write('{"partial":')
        raise OSError("simulated ENOSPC")

    monkeypatch.setattr(backup.json, "dump", fail_after_partial_write)
    monkeypatch.setattr(
        backup,
        "_fsync_directory",
        lambda directory: synced_directories.append(directory),
    )

    with pytest.raises(OSError, match="ENOSPC"):
        backup._write_json_exclusive(path, {"owner": "first"}, 0o644)

    assert not path.exists()
    assert list(tmp_path.glob(".record.json.tmp-*")) == []
    assert synced_directories == [tmp_path]


def test_atomic_json_writer_preserves_previous_journal_on_partial_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.json"
    path.write_text('{"status":"previous"}\n', encoding="utf-8")

    def fail_after_partial_write(
        payload: object,
        stream: object,
        **kwargs: object,
    ) -> None:
        del payload, kwargs
        stream.write('{"status":"partial"')
        raise OSError("simulated ENOSPC")

    monkeypatch.setattr(backup.json, "dump", fail_after_partial_write)

    with pytest.raises(OSError, match="ENOSPC"):
        backup._write_json_atomic(path, {"status": "new"}, 0o644)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "status": "previous"
    }
    assert list(tmp_path.glob(".evidence.json.tmp-*")) == []


def test_stream_source_artifact_fsyncs_file_then_parent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "mysql" / "backup.sql"
    path.parent.mkdir()
    file_fsyncs: list[int] = []
    directory_fsyncs: list[Path] = []

    monkeypatch.setattr(
        backup,
        "_source_command",
        lambda **kwargs: (["artifact-command"], {}),
    )

    def fake_run(
        command: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        assert command == ["artifact-command"]
        stream = kwargs["stdout"]
        stream.write(b"durable artifact")
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    monkeypatch.setattr(backup.os, "fsync", lambda fd: file_fsyncs.append(fd))
    monkeypatch.setattr(
        backup,
        "_fsync_directory",
        lambda directory: directory_fsyncs.append(directory),
    )

    backup._stream_source_artifact(
        values={},
        config_file=Path("/config.env"),
        secret_dir=Path("/secrets"),
        mode="loopback",
        arguments=("ignored",),
        path=path,
    )

    assert path.read_bytes() == b"durable artifact"
    assert len(file_fsyncs) == 1
    assert directory_fsyncs == [path.parent, path.parent]


@pytest.mark.parametrize("artifact_name", ("backup.sql", "backup.tar"))
def test_stream_source_artifact_never_publishes_partial_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    artifact_name: str,
) -> None:
    path = tmp_path / artifact_name
    synced_directories: list[Path] = []
    monkeypatch.setattr(
        backup,
        "_source_command",
        lambda **kwargs: (["artifact-command"], {}),
    )

    def fail_after_partial_write(
        command: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        del command
        stream = kwargs["stdout"]
        stream.write(b"partial")
        raise subprocess.CalledProcessError(1, ["artifact-command"])

    monkeypatch.setattr(backup.subprocess, "run", fail_after_partial_write)
    monkeypatch.setattr(
        backup,
        "_fsync_directory",
        lambda directory: synced_directories.append(directory),
    )

    with pytest.raises(subprocess.CalledProcessError):
        backup._stream_source_artifact(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            arguments=("ignored",),
            path=path,
        )

    assert not path.exists()
    assert list(tmp_path.glob(f".{artifact_name}.tmp-*")) == []
    assert synced_directories == [tmp_path]


def test_stream_source_artifact_never_overwrites_existing_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "backup.sql"
    path.write_bytes(b"original")
    monkeypatch.setattr(
        backup,
        "_source_command",
        lambda **kwargs: (["artifact-command"], {}),
    )

    def write_replacement(
        command: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        del command
        kwargs["stdout"].write(b"replacement")
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(backup.subprocess, "run", write_replacement)

    with pytest.raises(gatea.GateAError, match="artifact path is already reserved"):
        backup._stream_source_artifact(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            arguments=("ignored",),
            path=path,
        )

    assert path.read_bytes() == b"original"
    assert list(tmp_path.glob(".backup.sql.tmp-*")) == []


def test_stream_source_artifact_publish_boundary_is_never_partial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "backup.tar"
    monkeypatch.setattr(
        backup,
        "_source_command",
        lambda **kwargs: (["artifact-command"], {}),
    )

    def write_complete_artifact(
        command: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        del command
        kwargs["stdout"].write(b"complete artifact")
        return subprocess.CompletedProcess([], 0)

    sync_calls = 0

    def interrupt_first_directory_sync(directory: Path) -> None:
        nonlocal sync_calls
        assert directory == tmp_path
        sync_calls += 1
        if sync_calls == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(backup.subprocess, "run", write_complete_artifact)
    monkeypatch.setattr(backup, "_fsync_directory", interrupt_first_directory_sync)

    with pytest.raises(KeyboardInterrupt):
        backup._stream_source_artifact(
            values={},
            config_file=Path("/config.env"),
            secret_dir=Path("/secrets"),
            mode="loopback",
            arguments=("ignored",),
            path=path,
        )

    # 中断发生在 no-clobber link 之后时，最终路径也只能是完整且已 fsync 的
    # artifact；随机临时名仍被清掉。
    assert path.read_bytes() == b"complete artifact"
    assert list(tmp_path.glob(".backup.tar.tmp-*")) == []
    assert sync_calls == 2


def test_failed_artifact_cleanup_fsyncs_each_changed_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mysql" / "backup.sql"
    image_path = tmp_path / "images" / "backup.tar"
    database_path.parent.mkdir()
    image_path.parent.mkdir()
    database_path.write_bytes(b"sql")
    image_path.write_bytes(b"tar")
    synced_directories: list[Path] = []
    monkeypatch.setattr(
        backup,
        "_fsync_directory",
        lambda directory: synced_directories.append(directory),
    )

    backup._remove_backup_artifacts(database_path, image_path)

    assert not database_path.exists()
    assert not image_path.exists()
    assert synced_directories == [database_path.parent, image_path.parent]


def _write_backup_fixture(
    backup_root: Path,
    backup_records: Path,
    backup_id: str,
    *,
    database_snapshot: dict[str, object] | None = None,
    m7_content_snapshot: dict[str, object] | None = None,
    m9_table_content_snapshot: dict[str, object] | None = None,
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
        "database_snapshot": database_snapshot
        or {
            "aerich_versions": ",".join(gatea.APPROVED_SOURCE_M2_CHAIN),
            "tables": 10,
        },
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
    if m7_content_snapshot is not None:
        payload["m7_content_snapshot"] = m7_content_snapshot
    if m9_table_content_snapshot is not None:
        payload["m9_table_content_snapshot"] = m9_table_content_snapshot
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


def test_load_m7_backup_record_requires_exact_content_snapshot(tmp_path: Path) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(
        backup_root,
        backup_records,
        backup_id,
        database_snapshot=_m7_database_snapshot(),
    )

    with pytest.raises(gatea.GateAError, match="record is invalid"):
        backup._load_backup_record(
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_records,
        )

    payload = json.loads(
        (backup_records / f"{backup_id}.json").read_text(encoding="utf-8")
    )
    payload["m7_content_snapshot"] = _m7_content_snapshot()
    (backup_records / f"{backup_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    loaded, _, _ = backup._load_backup_record(
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_records,
    )
    assert loaded["m7_content_snapshot"] == _m7_content_snapshot()


def test_load_m9_backup_record_requires_only_the_m9_table_content_snapshot(
    tmp_path: Path,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(
        backup_root,
        backup_records,
        backup_id,
        database_snapshot=_m9_database_snapshot(),
        m7_content_snapshot=_m7_content_snapshot(),
    )

    with pytest.raises(gatea.GateAError, match="record is invalid"):
        backup._load_backup_record(
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_records,
        )

    payload = json.loads(
        (backup_records / f"{backup_id}.json").read_text(encoding="utf-8")
    )
    payload["m9_table_content_snapshot"] = _m9_table_content_snapshot()
    (backup_records / f"{backup_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    loaded, _, _ = backup._load_backup_record(
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_records,
    )
    assert loaded["m9_table_content_snapshot"] == _m9_table_content_snapshot()


def test_load_m8_backup_record_keeps_m7_evidence_and_rejects_m9_evidence(
    tmp_path: Path,
) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    backup_id = "20260902t120000z"
    m8_snapshot = {
        "aerich_versions": ",".join(gatea.APPROVED_TARGET_M8_CHAIN),
        "tables": 26,
    }
    _write_backup_fixture(
        backup_root,
        backup_records,
        backup_id,
        database_snapshot=m8_snapshot,
        m7_content_snapshot=_m7_content_snapshot(),
    )

    loaded, _, _ = backup._load_backup_record(
        backup_id=backup_id,
        backup_root=backup_root,
        backup_record_dir=backup_records,
    )
    assert loaded["m7_content_snapshot"] == _m7_content_snapshot()
    assert "m9_table_content_snapshot" not in loaded

    loaded["m9_table_content_snapshot"] = _m9_table_content_snapshot()
    (backup_records / f"{backup_id}.json").write_text(
        json.dumps(loaded), encoding="utf-8"
    )
    with pytest.raises(gatea.GateAError, match="record is invalid"):
        backup._load_backup_record(
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_records,
        )


def test_load_backup_record_rejects_unknown_migration_chain(tmp_path: Path) -> None:
    backup_root, backup_records, _ = _directories(tmp_path)
    _write_backup_fixture(
        backup_root,
        backup_records,
        "20260902t120000z",
        database_snapshot={"aerich_versions": "unrecognized"},
    )

    with pytest.raises(gatea.GateAError, match="record is invalid"):
        backup._load_backup_record(
            backup_id="20260902t120000z",
            backup_root=backup_root,
            backup_record_dir=backup_records,
        )


def test_verify_m9_restore_compares_and_always_removes_temporary_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(
        backup_root,
        backup_records,
        backup_id,
        database_snapshot=_m9_database_snapshot(),
        m7_content_snapshot=_m7_content_snapshot(),
        m9_table_content_snapshot=_m9_table_content_snapshot(),
    )
    values = _values(backup_root)
    commands: list[tuple[str, ...]] = []
    absence_checks: list[tuple[str, bool]] = []

    monkeypatch.setattr(gatea, "_validated_inputs", lambda **kwargs: values)
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        backup,
        "_restore_project_absent",
        lambda project, **kwargs: absence_checks.append(
            (project, bool(kwargs.get("start_new_session", False)))
        ),
    )
    monkeypatch.setattr(
        backup,
        "_restore_snapshot",
        lambda *args: _m9_database_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_restored_m7_content_snapshot",
        lambda *args: _m7_content_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_restored_m9_table_content_snapshot",
        lambda *args: _m9_table_content_snapshot(),
    )
    monkeypatch.setattr(backup, "_restored_image_manifest", lambda *args: [])

    def fake_restore(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        commands.append(arguments)
        stdout = ""
        if arguments[:3] == ("exec", "--no-TTY", "redis"):
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
        release_record_dir=tmp_path / "releases",
    )

    assert commands[-1] == ("down", "--volumes", "--remove-orphans")
    assert absence_checks == [(project, False), (project, True)]
    record = json.loads(
        (restore_records / f"{backup_id}.json").read_text(encoding="utf-8")
    )
    database_path, image_path = backup._backup_paths(backup_root, backup_id)
    assert record["backup_record_sha256"] == backup._sha256(
        backup_records / f"{backup_id}.json"
    )
    assert record["mysql_artifact_sha256"] == backup._sha256(database_path)
    assert record["image_artifact_sha256"] == backup._sha256(image_path)
    assert record["passed"] is True
    assert record["temporary_resources_removed"] is True
    assert record["refresh_sessions_invalidated"] is True
    assert record["m7_content_matches"] is True
    assert record["m7_content_snapshot"] == _m7_content_snapshot()
    assert record["m9_table_content_matches"] is True
    assert record["m9_table_content_snapshot"] == _m9_table_content_snapshot()


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
            release_record_dir=tmp_path / "releases",
        )

    assert called is False


def test_restore_rejects_unresolved_backup_pending_before_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(backup_root, backup_records, backup_id)
    pending = backup_records / f".{backup_id}.pending.json"
    pending.write_text("{}\n", encoding="utf-8")
    pending.chmod(0o600)
    docker_calls: list[str] = []

    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: _values(backup_root),
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        backup,
        "_restore_project_absent",
        lambda project, **kwargs: docker_calls.append("project-absence-check"),
    )
    monkeypatch.setattr(
        backup,
        "_run_restore",
        lambda **kwargs: docker_calls.append("restore-compose"),
    )

    with pytest.raises(gatea.GateAError, match="unresolved pending journal"):
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
            release_record_dir=tmp_path / "releases",
        )

    assert docker_calls == []


@pytest.mark.parametrize("blocker", ("candidate", "acceptance"))
def test_restore_rejects_global_release_state_before_compose_or_resource_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    blocker: str,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    release_record_dir = tmp_path / "releases"
    acceptance_record_dir = tmp_path / "acceptance"
    acceptance_record_dir.mkdir()
    if blocker == "candidate":
        (release_record_dir / f"{'b' * 40}.candidate-stage.pending.json").write_text(
            "{}\n", encoding="utf-8"
        )
    else:
        (
            acceptance_record_dir
            / (
                f"{gatea.M9_ACCEPTANCE_SIDECAR_PREFIX}{'b' * 40}"
                f"{gatea.M9_ACCEPTANCE_PENDING_SUFFIX}"
            )
        ).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: pytest.fail("global guard must run before compose config"),
    )
    monkeypatch.setattr(
        backup,
        "_restore_project_absent",
        lambda project, **kwargs: pytest.fail(
            "global guard must run before resource inspection"
        ),
    )
    backup_id = "20260902t120007z"

    with pytest.raises(gatea.GateAError, match="unresolved"):
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
            release_record_dir=release_record_dir,
            acceptance_record_dir=acceptance_record_dir,
        )


def test_restore_cli_passes_release_and_acceptance_record_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    release_record_dir = tmp_path / "exact-release-records"
    acceptance_record_dir = tmp_path / "exact-acceptance-records"
    backup_id = "20260902t120008z"
    monkeypatch.setattr(gatea, "operation_lock", lambda: nullcontext())
    monkeypatch.setattr(
        gatea,
        "operation_termination_guard",
        lambda: nullcontext(),
    )
    monkeypatch.setattr(backup, "verify_restore", lambda **kwargs: calls.append(kwargs))

    assert backup.main(
        (
            "restore-verify",
            "--backup-id",
            backup_id,
            "--confirm-project",
            backup.restore_project(backup_id),
            "--mode",
            "loopback",
            "--release-record-dir",
            str(release_record_dir),
            "--acceptance-record-dir",
            str(acceptance_record_dir),
        )
    ) == 0
    assert calls[0]["release_record_dir"] == release_record_dir
    assert calls[0]["acceptance_record_dir"] == acceptance_record_dir


@pytest.mark.parametrize(
    "interruption",
    (
        KeyboardInterrupt(),
        gatea.GateAOperationInterrupted("controlled termination"),
        SystemExit(17),
    ),
    ids=("keyboard-interrupt", "controlled-termination", "system-exit"),
)
def test_restore_cleans_temporary_project_and_propagates_original_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    interruption: BaseException,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(backup_root, backup_records, backup_id)
    calls: list[tuple[str, ...]] = []
    cleanup_verified: list[str] = []

    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: _values(backup_root),
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        backup,
        "_restore_project_absent",
        lambda project, **kwargs: None,
    )
    monkeypatch.setattr(
        backup,
        "_restore_cleanup_verified",
        lambda project: cleanup_verified.append(project),
    )

    def fake_restore(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        calls.append(arguments)
        if arguments[0] == "up":
            raise interruption
        return subprocess.CompletedProcess([], 0, stdout="")

    monkeypatch.setattr(backup, "_run_restore", fake_restore)

    project = backup.restore_project(backup_id)
    with pytest.raises(type(interruption)) as caught:
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
            release_record_dir=tmp_path / "releases",
        )

    assert caught.value is interruption
    assert calls == [
        ("config", "--quiet"),
        (
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            "mysql-restore",
            "redis",
        ),
        ("down", "--volumes", "--remove-orphans"),
    ]
    assert cleanup_verified == [project]
    assert not (restore_records / f"{backup_id}.json").exists()


@pytest.mark.parametrize(
    ("signal_during_work", "signum"),
    [
        pytest.param(True, signal.SIGTERM, id="sigterm-during-work"),
        pytest.param(False, signal.SIGTERM, id="sigterm-during-cleanup"),
        pytest.param(True, signal.SIGINT, id="sigint-during-work"),
        pytest.param(False, signal.SIGINT, id="sigint-during-cleanup"),
    ],
)
def test_restore_signal_controller_never_interrupts_exact_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    signal_during_work: bool,
    signum: int,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(backup_root, backup_records, backup_id)
    previous_handlers = {
        backup.signal.SIGHUP: object(),
        backup.signal.SIGTERM: object(),
        backup.signal.SIGINT: object(),
    }
    active_handlers: dict[int, object] = {}
    calls: list[tuple[str, ...]] = []
    cleanup_events: list[str] = []
    first_interruptions: list[BaseException] = []

    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: _values(backup_root),
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        backup,
        "_restore_project_absent",
        lambda project, **kwargs: None,
    )
    monkeypatch.setattr(
        backup,
        "_restore_cleanup_verified",
        lambda project: cleanup_events.append("verified"),
    )
    monkeypatch.setattr(
        backup.signal,
        "getsignal",
        lambda signum: previous_handlers[signum],
    )
    monkeypatch.setattr(
        backup.signal,
        "signal",
        lambda signum, handler: active_handlers.__setitem__(signum, handler),
    )

    def fake_restore(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        calls.append(arguments)
        if arguments[0] == "up":
            if signal_during_work:
                work_handler = active_handlers[signum]
                assert callable(work_handler)
                work_handler(signum, None)
            raise RuntimeError("restore work failed")
        if arguments[0] == "down":
            assert kwargs.get("start_new_session") is True
            cleanup_events.append("down-started")
            handler = active_handlers[backup.signal.SIGINT]
            controller = getattr(handler, "__self__")
            assert isinstance(controller, backup._RecoveryTerminationController)
            if signal_during_work:
                assert controller.work_interruption is not None
                first_interruptions.append(controller.work_interruption)
            recovery_signal = (
                backup.signal.SIGHUP
                if signal_during_work
                else signum
            )
            cleanup_handler = active_handlers[recovery_signal]
            assert callable(cleanup_handler)
            cleanup_handler(recovery_signal, None)
            if not signal_during_work:
                assert controller.deferred_interruptions
                first_interruptions.append(controller.deferred_interruptions[0])
            cleanup_events.append("down-completed")
        return subprocess.CompletedProcess([], 0, stdout="")

    monkeypatch.setattr(backup, "_run_restore", fake_restore)
    project = backup.restore_project(backup_id)

    expected_type = (
        KeyboardInterrupt
        if signum == signal.SIGINT
        else gatea.GateAOperationInterrupted
    )
    with pytest.raises(
        expected_type,
        match=f"received {signal.Signals(signum).name} and is recovering",
    ) as caught:
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
            release_record_dir=tmp_path / "releases",
        )

    assert calls == [
        ("config", "--quiet"),
        (
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            "mysql-restore",
            "redis",
        ),
        ("down", "--volumes", "--remove-orphans"),
    ]
    assert cleanup_events == ["down-started", "down-completed", "verified"]
    assert caught.value is first_interruptions[0]
    assert active_handlers == previous_handlers
    assert not (restore_records / f"{backup_id}.json").exists()


def test_restore_m7_content_mismatch_still_removes_isolated_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(
        backup_root,
        backup_records,
        backup_id,
        database_snapshot=_m7_database_snapshot(),
        m7_content_snapshot=_m7_content_snapshot(),
    )
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: _values(backup_root),
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        backup,
        "_restore_project_absent",
        lambda project, **kwargs: None,
    )
    monkeypatch.setattr(
        backup,
        "_restore_snapshot",
        lambda *args: _m7_database_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_restored_m7_content_snapshot",
        lambda *args: _m7_content_snapshot("8" * 64),
    )
    monkeypatch.setattr(backup, "_restored_image_manifest", lambda *args: [])

    def fake_restore(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        commands.append(arguments)
        stdout = "0\n" if arguments[:3] == ("exec", "--no-TTY", "redis") else ""
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
            release_record_dir=tmp_path / "releases",
        )

    assert commands[-1] == ("down", "--volumes", "--remove-orphans")
    assert not (restore_records / f"{backup_id}.json").exists()


def test_restore_m9_table_content_mismatch_still_removes_isolated_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backup_root, backup_records, restore_records = _directories(tmp_path)
    backup_id = "20260902t120000z"
    _write_backup_fixture(
        backup_root,
        backup_records,
        backup_id,
        database_snapshot=_m9_database_snapshot(),
        m7_content_snapshot=_m7_content_snapshot(),
        m9_table_content_snapshot=_m9_table_content_snapshot(),
    )
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        gatea,
        "_validated_inputs",
        lambda **kwargs: _values(backup_root),
    )
    monkeypatch.setattr(gatea, "_validate_root_directory", lambda *args: None)
    monkeypatch.setattr(
        backup,
        "_restore_project_absent",
        lambda project, **kwargs: None,
    )
    monkeypatch.setattr(
        backup,
        "_restore_snapshot",
        lambda *args: _m9_database_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_restored_m7_content_snapshot",
        lambda *args: _m7_content_snapshot(),
    )
    monkeypatch.setattr(
        backup,
        "_restored_m9_table_content_snapshot",
        lambda *args: _m9_table_content_snapshot("8" * 64),
    )
    monkeypatch.setattr(backup, "_restored_image_manifest", lambda *args: [])

    def fake_restore(**kwargs: object) -> subprocess.CompletedProcess[str]:
        arguments = tuple(kwargs["arguments"])
        commands.append(arguments)
        stdout = "0\n" if arguments[:3] == ("exec", "--no-TTY", "redis") else ""
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
            release_record_dir=tmp_path / "releases",
        )

    assert commands[-1] == ("down", "--volumes", "--remove-orphans")
    assert not (restore_records / f"{backup_id}.json").exists()
