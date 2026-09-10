"""GitHub-hosted Gate A M7→M9 完整演练的安全编排边界。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Mapping, Sequence

import pytest

from scripts.ci import gatea_m7_m8_drill as drill


TARGET_SHA = "b" * 40


class FakeRunner(drill.CommandRunner):
    def __init__(
        self,
        *,
        container_lines: str = "",
        volumes: str = "",
        networks: str = "",
        context: str = "default",
        daemon_host: str = "unix:///var/run/docker.sock",
        daemon_os: str = "linux",
        image_ids: Mapping[str, str] | None = None,
    ) -> None:
        self.container_lines = container_lines
        self.volumes = volumes
        self.networks = networks
        self.context = context
        self.daemon_host = daemon_host
        self.daemon_os = daemon_os
        self.image_ids = dict(image_ids or {})
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path = drill.REPOSITORY_ROOT,
        environment: Mapping[str, str] | None = None,
        timeout: int = 120,
    ) -> drill.CommandResult:
        del cwd, environment, timeout
        call = tuple(command)
        self.calls.append(call)
        if call[:3] == ("docker", "context", "show"):
            return drill.CommandResult(0, self.context + "\n")
        if call[:3] == ("docker", "context", "inspect"):
            return drill.CommandResult(0, self.daemon_host + "\n")
        if call[:3] == ("docker", "info", "--format"):
            return drill.CommandResult(0, self.daemon_os + "\n")
        if call[:3] == ("docker", "compose", "version"):
            return drill.CommandResult(0, "2.39.1\n")
        if call[:3] == ("docker", "version", "--format"):
            return drill.CommandResult(0, "28.0.0/28.0.0\n")
        if call[:3] == ("docker", "ps", "--all"):
            return drill.CommandResult(0, self.container_lines)
        if call[:3] == ("docker", "volume", "ls"):
            return drill.CommandResult(0, self.volumes)
        if call[:3] == ("docker", "network", "ls"):
            return drill.CommandResult(0, self.networks)
        if call[:3] == ("docker", "image", "ls"):
            reference = call[-1].removeprefix("reference=")
            return drill.CommandResult(0, self.image_ids.get(reference, ""))
        if call[:3] in {
            ("docker", "image", "inspect"),
            ("docker", "volume", "inspect"),
            ("docker", "network", "inspect"),
        }:
            return drill.CommandResult(1)
        if "merge-base" in call:
            return drill.CommandResult(0)
        return drill.CommandResult(0)


def _environment(tmp_path: Path) -> dict[str, str]:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        drill.SENTINEL_ENV: drill.SENTINEL_VALUE,
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_SHA": TARGET_SHA,
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(runner_temp),
    }


def _paths(tmp_path: Path, environment: Mapping[str, str]) -> drill.DrillPaths:
    return drill.paths_from_environment(
        Path(environment["GITHUB_WORKSPACE"])
        / "artifacts"
        / "gatea-m7-m9-updater",
        environment,
        require_empty_artifacts=True,
    )


def _state(
    tmp_path: Path,
    *,
    runner: drill.CommandRunner | None = None,
    ownership_acquired: bool = False,
) -> drill.DrillState:
    environment = _environment(tmp_path)
    paths = _paths(tmp_path, environment)
    return drill.DrillState(
        paths=paths,
        target_sha=TARGET_SHA,
        source_image=f"pinkdoohub-gatea:{drill.SOURCE_SHA}",
        target_image=f"pinkdoohub-gatea:{TARGET_SHA}",
        environment=environment,
        command_runner=runner or FakeRunner(),
        ownership_acquired=ownership_acquired,
    )


def test_cli_requires_exact_run_or_cleanup_and_artifact_directory() -> None:
    run = drill.parse_args(["run", "--artifact-dir", "/tmp/drill-artifacts"])
    cleanup = drill.parse_args(
        ["cleanup", "--artifact-dir", "/tmp/drill-artifacts"]
    )

    assert run.command == "run"
    assert cleanup.command == "cleanup"
    assert run.artifact_dir == Path("/tmp/drill-artifacts")

    with pytest.raises(SystemExit):
        drill.parse_args(["run"])


def test_paths_reject_an_artifact_directory_outside_the_frozen_workspace_path(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)

    with pytest.raises(drill.DrillError, match="frozen workspace path"):
        drill.paths_from_environment(
            tmp_path / "unexpected-artifacts",
            environment,
            require_empty_artifacts=True,
        )


def test_host_guard_accepts_only_root_github_hosted_local_linux(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment(tmp_path)
    runner = FakeRunner()
    monkeypatch.setattr(drill.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(drill, "_port_available", lambda port: port == 18080)

    evidence = drill.validate_host_environment(
        environment,
        runner,
        require_clean_start=True,
        geteuid=lambda: 0,
        system=lambda: "Linux",
    )

    assert evidence["github_hosted"] is True
    assert evidence["docker_context"] == "default"
    assert evidence["docker_daemon_host"] == "unix:///var/run/docker.sock"
    assert evidence["resources"] == {
        "main_containers": [],
        "restore_containers": [],
        "main_volumes": [],
        "restore_volumes": [],
        "main_networks": [],
        "restore_networks": [],
    }


@pytest.mark.parametrize(
    ("updates", "geteuid", "system", "message"),
    (
        ({"GITHUB_ACTIONS": "false"}, 0, "Linux", "GitHub Actions"),
        ({"RUNNER_ENVIRONMENT": "self-hosted"}, 0, "Linux", "self-hosted"),
        ({drill.SENTINEL_ENV: "wrong"}, 0, "Linux", "sentinel"),
        ({}, 501, "Linux", "root"),
        ({}, 0, "Darwin", "Linux"),
        ({"DOCKER_HOST": "tcp://remote.invalid:2375"}, 0, "Linux", "overridden"),
        ({"DOCKER_CONTEXT": "remote"}, 0, "Linux", "overridden"),
    ),
)
def test_host_guard_rejects_any_unsafe_execution_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    updates: Mapping[str, str],
    geteuid: int,
    system: str,
    message: str,
) -> None:
    environment = _environment(tmp_path) | dict(updates)
    monkeypatch.setattr(drill.shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(drill.DrillError, match=message):
        drill.validate_host_environment(
            environment,
            FakeRunner(),
            require_clean_start=True,
            geteuid=lambda: geteuid,
            system=lambda: system,
        )


@pytest.mark.parametrize(
    ("runner", "message"),
    (
        (FakeRunner(context="remote"), "default Docker context"),
        (FakeRunner(daemon_host="tcp://docker.invalid:2375"), "Unix socket"),
        (FakeRunner(daemon_os="windows"), "Linux Docker daemon"),
        (
            FakeRunner(
                container_lines="abc|pinkdoohub-gatea-app-1|pinkdoohub-gatea\n"
            ),
            "already exist",
        ),
        (
            FakeRunner(volumes="pinkdoohub-gatea-mysql-data\n"),
            "already exist",
        ),
        (
            FakeRunner(networks="pinkdoohub-gatea-backend\n"),
            "already exist",
        ),
    ),
)
def test_host_guard_rejects_remote_or_dirty_docker_daemon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: FakeRunner,
    message: str,
) -> None:
    monkeypatch.setattr(drill.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(drill, "_port_available", lambda port: True)

    with pytest.raises(drill.DrillError, match=message):
        drill.validate_host_environment(
            _environment(tmp_path),
            runner,
            require_clean_start=True,
            geteuid=lambda: 0,
            system=lambda: "Linux",
        )


def test_git_target_binds_exact_checkout_sha_and_records_pr_head_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = tmp_path / "event.json"
    pr_head = "c" * 40
    event.write_text(
        json.dumps({"pull_request": {"head": {"sha": pr_head}}}),
        encoding="utf-8",
    )
    environment = _environment(tmp_path) | {"GITHUB_EVENT_PATH": str(event)}
    expected_source = "\n".join(
        f"migrations/models/{name}" for name in drill.gatea.APPROVED_SOURCE_M7_CHAIN
    )
    expected_target = "\n".join(
        f"migrations/models/{name}" for name in drill.gatea.APPROVED_TARGET_M9_CHAIN
    )

    def fake_git_output(runner: drill.CommandRunner, *arguments: str) -> str:
        del runner
        if arguments == ("rev-parse", "HEAD"):
            return TARGET_SHA
        if arguments[:2] == ("status", "--porcelain=v1"):
            return ""
        if arguments[0] == "ls-tree" and drill.SOURCE_SHA in arguments:
            return expected_source
        if arguments[0] == "ls-tree" and TARGET_SHA in arguments:
            return expected_target
        raise AssertionError(arguments)

    manifest = drill.MARD_MANIFEST.read_text(encoding="utf-8")
    monkeypatch.setattr(drill, "_git_output", fake_git_output)
    monkeypatch.setattr(
        drill,
        "_git_raw_output",
        lambda runner, *arguments: manifest,
    )
    monkeypatch.setattr(
        drill,
        "_sha256_file",
        lambda path: drill.MARD_MANIFEST_SHA256,
    )

    target_sha, reported_head, evidence = drill.validate_git_target(
        environment,
        FakeRunner(),
    )

    assert target_sha == environment["GITHUB_SHA"] == TARGET_SHA
    assert reported_head == pr_head
    assert evidence["reported_pr_head_sha"] == pr_head
    assert evidence["source_sha"] == drill.SOURCE_SHA


def test_git_target_rejects_github_sha_different_from_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        drill,
        "_git_output",
        lambda runner, *arguments: TARGET_SHA,
    )
    environment = _environment(tmp_path) | {"GITHUB_SHA": "d" * 40}

    with pytest.raises(drill.DrillError, match="exactly match"):
        drill.validate_git_target(environment, FakeRunner())


def test_artifact_allowlist_and_exact_secret_scan(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "summary.json").write_text(
        '{"passed": true}\n',
        encoding="utf-8",
    )

    result = drill.scan_artifacts(artifact_dir, secret_values=("ephemeral-value",))

    assert result["allowlist_passed"] is True
    assert result["secret_scan_passed"] is True

    (artifact_dir / "summary.json").write_text(
        '{"value": "ephemeral-value"}\n',
        encoding="utf-8",
    )
    with pytest.raises(drill.DrillError, match="ephemeral Secret"):
        drill.scan_artifacts(artifact_dir, secret_values=("ephemeral-value",))

    (artifact_dir / "summary.json").write_text("{}\n", encoding="utf-8")
    (artifact_dir / "mysql.sql").write_text("raw backup", encoding="utf-8")
    with pytest.raises(drill.DrillError, match="non-allowlisted"):
        drill.scan_artifacts(artifact_dir)


def test_header_token_matching_is_case_insensitive_but_not_a_substring() -> None:
    headers = {"Vary": "Origin, Accept-Encoding"}

    assert drill._header_contains_token(headers, "vary", "accept-encoding") is True
    assert drill._header_contains_token(
        {"Vary": "X-Accept-Encoding-Hint"},
        "Vary",
        "Accept-Encoding",
    ) is False


def test_cleanup_without_ownership_never_deletes_preexisting_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(
        container_lines="abc|pinkdoohub-gatea-app-1|pinkdoohub-gatea\n"
    )
    state = _state(tmp_path, runner=runner, ownership_acquired=False)
    monkeypatch.setattr(drill, "_port_available", lambda port: True)

    payload = drill.cleanup_owned_state(state)

    assert payload["cleanup_performed"] is False
    assert payload["passed"] is False
    assert payload["residual"]["main_containers"]
    assert not any(call[:3] == ("docker", "rm", "--force") for call in runner.calls)
    assert not any(call[:3] == ("docker", "volume", "rm") for call in runner.calls)


def test_owned_cleanup_removes_only_exact_workspace_and_verifies_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path, ownership_acquired=True)
    state.paths.work_root.mkdir()
    marker = state.paths.work_root / "owned"
    marker.write_text("owned", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        drill,
        "_remove_exact_resources",
        lambda value: calls.append(value.target_image) or [],
    )
    monkeypatch.setattr(
        drill,
        "docker_inventory",
        lambda runner: {
            "main_containers": [],
            "restore_containers": [],
            "main_volumes": [],
            "restore_volumes": [],
            "main_networks": [],
            "restore_networks": [],
        },
    )
    monkeypatch.setattr(drill, "_port_available", lambda port: True)

    payload = drill.cleanup_owned_state(state)

    assert calls == [state.target_image]
    assert payload["cleanup_performed"] is True
    assert payload["passed"] is True
    assert not state.paths.work_root.exists()


def test_cleanup_fails_if_an_owned_image_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_image = f"pinkdoohub-gatea:{TARGET_SHA}"
    runner = FakeRunner(image_ids={target_image: "sha256:" + "a" * 64 + "\n"})
    state = _state(tmp_path, runner=runner, ownership_acquired=True)
    monkeypatch.setattr(drill, "_remove_exact_resources", lambda value: [])
    monkeypatch.setattr(
        drill,
        "docker_inventory",
        lambda value: {
            "main_containers": [],
            "restore_containers": [],
            "main_volumes": [],
            "restore_volumes": [],
            "main_networks": [],
            "restore_networks": [],
        },
    )
    monkeypatch.setattr(drill, "_port_available", lambda port: True)

    payload = drill.cleanup_owned_state(state)

    assert payload["passed"] is False
    assert payload["residual"]["images"] == [target_image]


def test_run_executes_complete_order_and_always_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    calls: list[str] = []

    class FakeDrill:
        def __init__(self, value: drill.DrillState) -> None:
            self.state = value

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return lambda: {"method": name}

        def _stage(self, name: str, method):  # type: ignore[no-untyped-def]
            calls.append(name)
            method()
            self.state.stages.append({"name": name, "passed": True})

    monkeypatch.setattr(
        drill,
        "_initial_state",
        lambda artifact_dir, environment, runner: (state, {"passed": True}, {"passed": True}),
    )
    monkeypatch.setattr(drill, "prepare_workspace", lambda value: None)
    monkeypatch.setattr(
        drill,
        "cleanup_owned_state",
        lambda value: {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-cleanup",
            "passed": True,
        },
    )
    monkeypatch.setattr(
        drill,
        "scan_artifacts",
        lambda path, secret_values=(): {
            "secret_scan_passed": True,
            "allowlist_passed": True,
            "file_count": 0,
        },
    )

    result = drill.run_command(
        state.paths.artifact_dir,
        environment=state.environment,
        runner=state.command_runner,
        drill_factory=FakeDrill,
    )

    assert result == 0
    assert calls == [name for name, _ in drill.PIPELINE]
    summary = json.loads(
        (state.paths.artifact_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "passed"
    assert summary["target_sha"] == TARGET_SHA
    assert summary["production_secrets_used"] is False


def test_run_failure_stops_pipeline_but_still_cleans_and_records_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    calls: list[str] = []
    cleanup_calls: list[bool] = []

    class FailingDrill:
        def __init__(self, value: drill.DrillState) -> None:
            self.state = value

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            if name == "apply_target":
                return lambda: (_ for _ in ()).throw(drill.DrillError("safe failure"))
            return lambda: {"method": name}

        def _stage(self, name: str, method):  # type: ignore[no-untyped-def]
            calls.append(name)
            method()
            self.state.stages.append({"name": name, "passed": True})

    monkeypatch.setattr(
        drill,
        "_initial_state",
        lambda artifact_dir, environment, runner: (state, {}, {}),
    )
    monkeypatch.setattr(drill, "prepare_workspace", lambda value: None)

    def fake_cleanup(value: drill.DrillState) -> dict[str, object]:
        cleanup_calls.append(value.ownership_acquired)
        return {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-cleanup",
            "passed": True,
        }

    monkeypatch.setattr(drill, "cleanup_owned_state", fake_cleanup)
    monkeypatch.setattr(
        drill,
        "scan_artifacts",
        lambda path, secret_values=(): {
            "secret_scan_passed": True,
            "allowlist_passed": True,
            "file_count": 0,
        },
    )

    result = drill.run_command(
        state.paths.artifact_dir,
        environment=state.environment,
        runner=state.command_runner,
        drill_factory=FailingDrill,
    )

    assert result == 1
    assert cleanup_calls == [True]
    assert calls[-1] == "apply-target"
    assert "plan-replay" not in calls
    summary = json.loads(
        (state.paths.artifact_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "failed"
    assert summary["failed_stage"] == "apply-target"
    assert summary["error_type"] == "DrillError"
    assert summary["failure_evidence"] == {
        "error_type": "DrillError",
        "message": "safe failure",
    }


def test_run_retries_a_transient_cleanup_result_before_failing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    cleanup_results = iter(
        (
            {
                "schema_version": 1,
                "record_type": "gatea-m7-m9-drill-cleanup",
                "passed": False,
                "errors": ["main-compose-down"],
                "residual": {"main_networks": ["pinkdoohub-gatea-backend"]},
            },
            {
                "schema_version": 1,
                "record_type": "gatea-m7-m9-drill-cleanup",
                "passed": True,
                "errors": [],
                "residual": {"main_networks": []},
            },
        )
    )
    sleep_calls: list[int] = []

    class FakeDrill:
        def __init__(self, value: drill.DrillState) -> None:
            self.state = value

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return lambda: {"method": name}

        def _stage(self, name: str, method):  # type: ignore[no-untyped-def]
            method()
            self.state.stages.append({"name": name, "passed": True})

    monkeypatch.setattr(
        drill,
        "_initial_state",
        lambda artifact_dir, environment, runner: (state, {}, {}),
    )
    monkeypatch.setattr(drill, "prepare_workspace", lambda value: None)
    monkeypatch.setattr(
        drill,
        "cleanup_owned_state",
        lambda value: next(cleanup_results),
    )
    monkeypatch.setattr(drill.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(
        drill,
        "scan_artifacts",
        lambda path, secret_values=(): {
            "secret_scan_passed": True,
            "allowlist_passed": True,
            "file_count": 0,
        },
    )

    result = drill.run_command(
        state.paths.artifact_dir,
        environment=state.environment,
        runner=state.command_runner,
        drill_factory=FakeDrill,
    )

    assert result == 0
    assert sleep_calls == [1]
    summary = json.loads(
        (state.paths.artifact_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["cleanup_passed"] is True
    assert summary["cleanup_attempts"] == [
        {
            "attempt": 1,
            "errors": ["main-compose-down"],
            "passed": False,
            "residual": {"main_networks": ["pinkdoohub-gatea-backend"]},
        },
        {
            "attempt": 2,
            "errors": [],
            "passed": True,
            "residual": {"main_networks": []},
        },
    ]


def test_called_process_failure_evidence_redacts_ephemeral_secrets() -> None:
    secret = "ephemeral-value-that-must-not-leak"
    error = subprocess.CalledProcessError(
        17,
        ("docker", "compose", "run", secret),
        output=f"safe prefix {secret}",
        stderr="migration command failed",
    )

    payload = drill._safe_failure_evidence(error, secret_values=(secret,))
    rendered = json.dumps(payload)

    assert payload == {
        "error_type": "CalledProcessError",
        "returncode": 17,
        "command": ["docker", "compose", "run", "[REDACTED]"],
        "stdout_tail": "safe prefix [REDACTED]",
        "stderr_tail": "migration command failed",
    }
    assert secret not in rendered


def test_called_process_failure_evidence_omits_credential_shaped_text() -> None:
    error = subprocess.CalledProcessError(
        1,
        ("python", "worker.py"),
        stderr="mysql://operator:credential@database.invalid/app",
    )

    payload = drill._safe_failure_evidence(error)

    assert payload == {
        "error_type": "CalledProcessError",
        "returncode": 1,
        "command": ["python", "worker.py"],
    }


def test_exact_secret_scan_failure_purges_all_candidate_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    secret = "ephemeral-secret-that-must-never-be-uploaded"

    class LeakingDrill:
        def __init__(self, value: drill.DrillState) -> None:
            self.state = value

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return lambda: {"method": name}

        def _stage(self, name: str, method):  # type: ignore[no-untyped-def]
            method()
            if name == "build-images":
                drill._write_json(
                    self.state.paths.artifact_dir / "images.json",
                    {"unexpected_secret": secret},
                )
            self.state.stages.append({"name": name, "passed": True})

    monkeypatch.setattr(
        drill,
        "_initial_state",
        lambda artifact_dir, environment, runner: (state, {}, {}),
    )

    def fake_prepare(value: drill.DrillState) -> None:
        value.secrets = drill.SecretBundle(secret, "", "", "", "", "")

    monkeypatch.setattr(drill, "prepare_workspace", fake_prepare)
    monkeypatch.setattr(
        drill,
        "cleanup_owned_state",
        lambda value: {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-cleanup",
            "passed": True,
        },
    )

    result = drill.run_command(
        state.paths.artifact_dir,
        environment=state.environment,
        runner=state.command_runner,
        drill_factory=LeakingDrill,
    )

    assert result == 1
    assert sorted(path.name for path in state.paths.artifact_dir.iterdir()) == [
        "cleanup-report.json",
        "drill-state.json",
        "summary.json",
    ]
    rendered = "".join(
        path.read_text(encoding="utf-8")
        for path in state.paths.artifact_dir.iterdir()
    )
    assert secret not in rendered
    summary = json.loads(
        (state.paths.artifact_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "failed"
    assert summary["failed_stage"] == "artifact-scan"
    assert summary["artifact_directory_purged"] is True


def test_finalization_failure_preserves_ownership_for_always_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)

    class FakeDrill:
        def __init__(self, value: drill.DrillState) -> None:
            self.state = value

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return lambda: {"method": name}

        def _stage(self, name: str, method):  # type: ignore[no-untyped-def]
            method()
            self.state.stages.append({"name": name, "passed": True})

    monkeypatch.setattr(
        drill,
        "_initial_state",
        lambda artifact_dir, environment, runner: (state, {}, {}),
    )
    monkeypatch.setattr(drill, "prepare_workspace", lambda value: None)
    cleanup_calls = 0

    def flaky_cleanup(value: drill.DrillState) -> dict[str, object]:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise drill.DrillError("transient cleanup inventory failure")
        return {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-cleanup",
            "passed": True,
        }

    monkeypatch.setattr(drill, "cleanup_owned_state", flaky_cleanup)

    assert (
        drill.run_command(
            state.paths.artifact_dir,
            environment=state.environment,
            runner=state.command_runner,
            drill_factory=FakeDrill,
        )
        == 1
    )
    restored = drill._state_from_record(
        state.paths,
        state.environment,
        state.command_runner,
    )
    assert restored is not None
    assert restored.ownership_acquired is True
    failure_summary = json.loads(
        (state.paths.artifact_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert failure_summary["failed_stage"] == "cleanup"
    assert failure_summary["error_type"] == "FinalizationSafetyError"

    monkeypatch.setattr(
        drill,
        "validate_host_environment",
        lambda *args, **kwargs: {},
    )
    assert (
        drill.cleanup_command(
            state.paths.artifact_dir,
            environment=state.environment,
            runner=state.command_runner,
        )
        == 0
    )
    assert cleanup_calls == 2
    assert (state.paths.artifact_dir / drill.ARTIFACT_SCAN_MARKER).is_file()


def test_cleanup_removes_stale_upload_marker_when_final_scan_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path, ownership_acquired=True)
    drill._write_json(state.state_path, state.safe_state())
    marker = state.paths.artifact_dir / drill.ARTIFACT_SCAN_MARKER
    drill._write_json(marker, {"secret_scan_passed": True})
    monkeypatch.setattr(
        drill,
        "validate_host_environment",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        drill,
        "cleanup_owned_state",
        lambda value: {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-cleanup",
            "passed": True,
        },
    )
    monkeypatch.setattr(
        drill,
        "scan_artifacts",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            drill.DrillError("unsafe final artifact")
        ),
    )

    result = drill.cleanup_command(
        state.paths.artifact_dir,
        environment=state.environment,
        runner=state.command_runner,
    )

    assert result == 1
    assert marker.exists() is False


def test_cleanup_uses_ownership_even_when_an_interrupted_temp_file_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path, ownership_acquired=True)
    drill._write_json(state.state_path, state.safe_state())
    interrupted = state.paths.artifact_dir / ".summary.json.tmp-1234"
    interrupted.write_text("possibly partial", encoding="utf-8")
    cleanup_calls: list[bool] = []
    monkeypatch.setattr(
        drill,
        "validate_host_environment",
        lambda *args, **kwargs: {},
    )

    def fake_cleanup(value: drill.DrillState) -> dict[str, object]:
        cleanup_calls.append(value.ownership_acquired)
        return {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-cleanup",
            "passed": True,
        }

    monkeypatch.setattr(drill, "cleanup_owned_state", fake_cleanup)

    result = drill.cleanup_command(
        state.paths.artifact_dir,
        environment=state.environment,
        runner=state.command_runner,
    )

    assert result == 1
    assert cleanup_calls == [True]
    assert interrupted.exists() is False
    assert (state.paths.artifact_dir / drill.ARTIFACT_SCAN_MARKER).is_file()
    summary = json.loads(
        (state.paths.artifact_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "failed"
    assert summary["failed_stage"] == "artifact-scan"


def test_secret_bundle_repr_and_safe_state_never_include_secret_values(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    state.secrets = drill.SecretBundle(
        mysql_app_password="mysql-app-value",
        mysql_root_password="mysql-root-value",
        redis_password="redis-value",
        jwt_secret="jwt-value",
        bootstrap_initial_password="initial-value",
        bootstrap_final_password="final-value",
    )

    rendered = repr(state.secrets) + json.dumps(state.safe_state())

    for value in state.secrets.values():
        assert value not in rendered
