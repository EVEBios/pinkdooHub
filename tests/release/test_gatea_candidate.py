"""Guard contracts for versioned Gate A candidate installation and activation."""

from __future__ import annotations

import copy
from contextlib import nullcontext
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tarfile
from types import SimpleNamespace
import zipfile

import pytest

from scripts.release import gatea_candidate as candidate
from scripts.release import gatea_operations


REAL_TRANSITION_SCANNER = candidate._reject_unresolved_transition_journals


SOURCE_SHA = candidate.SOURCE_M7_SHA
TARGET_SHA = "b" * 40
HEAD_SHA = "c" * 40
RUN_ID = "34499999999"
ATTEMPT = 2
ARTIFACT_NAME = f"gatea-m7-m9-updater-{TARGET_SHA}-{RUN_ID}-{ATTEMPT}"
BACKUP_ID = "20260910t120000z"
PRE_BACKUP_ID = "20260910t110000z"
IMAGE_ID = "sha256:" + "d" * 64
MANIFEST_SHA = "e" * 64
ACCEPTANCE_RECORD_SHA256 = "4" * 64
ACCEPTANCE_ATTEMPT_ID_SHA256 = "5" * 64
ACCEPTANCE_COMPLETED_AT = "2026-09-10T11:59:00+00:00"
TREE_SHA = "f" * 40
PULL_REQUEST_NUMBER = 93
WORKFLOW_RUN_NUMBER = 407
M7_CHAIN = list(gatea_operations.APPROVED_TARGET_M7_CHAIN)
M9_CHAIN = list(gatea_operations.APPROVED_TARGET_M9_CHAIN)
EMPTY_TABLE_RECONCILE = {
    "open_sessions": 0,
    "occupancies": 0,
    "closed_with_occupancy": 0,
    "awaiting_with_timers": 0,
    "active_without_timers": 0,
    "scanned": 0,
    "violations": 0,
}


def _source_members(candidate_script: bytes = b"candidate launcher\n") -> dict[str, bytes]:
    return {
        ".dockerignore": b".git\n",
        "requirements.txt": b"fastapi==0\n",
        "pyproject.toml": b"[tool.pytest.ini_options]\n",
        "deploy/runtime/Dockerfile": b"FROM scratch\n",
        "deploy/runtime/app-entrypoint.sh": b"#!/bin/sh\n",
        "deploy/gatea/compose.yml": b"services: {}\n",
        "deploy/gatea/compose.loopback.yml": b"services: {}\n",
        "scripts/release/gatea_candidate.py": candidate_script,
        "scripts/release/gatea_operations.py": b"# operations\n",
        "scripts/release/gatea_backup.py": b"# backup\n",
        "scripts/release/gatea_upgrade.py": b"# upgrade\n",
    }


def _write_source_tar(
    path: Path,
    *,
    commit: str = TARGET_SHA,
    members: dict[str, bytes] | None = None,
    special: tuple[str, bytes, int] | None = None,
) -> None:
    with tarfile.open(
        path,
        "w",
        format=tarfile.PAX_FORMAT,
        pax_headers={"comment": commit},
    ) as archive:
        for name, content in (members or _source_members()).items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            archive.addfile(info, BytesIO(content))
        if special is not None:
            name, content, member_type = special
            info = tarfile.TarInfo(name)
            info.type = member_type
            info.size = len(content)
            archive.addfile(info, BytesIO(content) if content else None)


def _write_source_directory(
    root: Path, members: dict[str, bytes] | None = None
) -> None:
    root.mkdir()
    for name, content in (members or _source_members()).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o755 if name.endswith(".sh") else 0o644)
    root.chmod(0o755)


def _github_tree_payload(root: Path) -> dict[str, object]:
    paths = sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())
    entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "mode": "040000",
            "type": "tree",
            "sha": hashlib.sha1(
                path.relative_to(root).as_posix().encode("utf-8"),
                usedforsecurity=False,
            ).hexdigest(),
        }
        for path in paths
        if path.is_dir()
    ]
    for path in (item for item in paths if item.is_file()):
        mode = "100755" if stat.S_IMODE(path.stat().st_mode) == 0o755 else "100644"
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "mode": mode,
                "type": "blob",
                "size": path.stat().st_size,
                "sha": candidate._git_blob_sha(path, path.stat().st_size),
            }
        )
    return {"sha": TREE_SHA, "truncated": False, "tree": entries}


def _github_api_documents(
    source_root: Path, ci_artifact: Path
) -> dict[str, dict[str, object]]:
    prefix = f"/repos/{candidate.GITHUB_REPOSITORY}"
    branch = "feature/phase9-ci"
    repository = {"id": 1234, "full_name": candidate.GITHUB_REPOSITORY}
    run_pull = {
        "number": PULL_REQUEST_NUMBER,
        "head": {"ref": branch, "sha": HEAD_SHA, "repo": repository},
        "base": {
            "ref": candidate.GITHUB_BASE_REF,
            "sha": "1" * 40,
            "repo": repository,
        },
    }
    artifact_query = candidate.urllib.parse.urlencode(
        {"name": ARTIFACT_NAME, "per_page": 100, "page": 1}
    )
    return {
        f"{prefix}/actions/runs/{RUN_ID}": {
            "id": int(RUN_ID),
            "run_number": WORKFLOW_RUN_NUMBER,
            "run_attempt": ATTEMPT,
            "event": "pull_request",
            "status": "completed",
            "conclusion": "success",
            "head_branch": branch,
            "head_sha": HEAD_SHA,
            "head_commit": {"id": HEAD_SHA},
            "name": candidate.GITHUB_WORKFLOW_NAME,
            "path": (
                f"{candidate.GITHUB_WORKFLOW_PATH}@{candidate.GITHUB_BASE_REF}"
            ),
            "repository": repository,
            "head_repository": repository,
            "pull_requests": [run_pull],
        },
        f"{prefix}/pulls/{PULL_REQUEST_NUMBER}": {
            "number": PULL_REQUEST_NUMBER,
            "state": "open",
            "merged": False,
            "merge_commit_sha": TARGET_SHA,
            "head": {"ref": branch, "sha": HEAD_SHA, "repo": repository},
            "base": {
                "ref": candidate.GITHUB_BASE_REF,
                "sha": "1" * 40,
                "repo": repository,
            },
        },
        (
            f"{prefix}/actions/runs/{RUN_ID}/attempts/{ATTEMPT}/jobs"
            "?per_page=100&page=1"
        ): {
            "total_count": len(candidate.GITHUB_REQUIRED_JOBS),
            "jobs": [
                {
                    "id": index,
                    "run_id": int(RUN_ID),
                    "head_sha": HEAD_SHA,
                    "status": "completed",
                    "conclusion": "success",
                    "name": name,
                    "workflow_name": candidate.GITHUB_WORKFLOW_NAME,
                }
                for index, name in enumerate(
                    sorted(candidate.GITHUB_REQUIRED_JOBS), start=1
                )
            ],
        },
        f"{prefix}/actions/runs/{RUN_ID}/artifacts?{artifact_query}": {
            "total_count": 1,
            "artifacts": [
                {
                    "id": 9876,
                    "name": ARTIFACT_NAME,
                    "size_in_bytes": ci_artifact.stat().st_size,
                    "expired": False,
                    "expires_at": "2099-09-20T00:00:00Z",
                    "digest": f"sha256:{candidate._sha256(ci_artifact)}",
                    "workflow_run": {
                        "id": int(RUN_ID),
                        "repository_id": repository["id"],
                        "head_repository_id": repository["id"],
                        "head_branch": branch,
                        "head_sha": HEAD_SHA,
                    },
                }
            ],
        },
        f"{prefix}/git/commits/{TARGET_SHA}": {
            "sha": TARGET_SHA,
            "tree": {"sha": TREE_SHA},
            "parents": [{"sha": "1" * 40}, {"sha": HEAD_SHA}],
        },
        f"{prefix}/git/trees/{TREE_SHA}?recursive=1": _github_tree_payload(
            source_root
        ),
    }


def _github_stage_evidence(ci_artifact: Path) -> dict[str, object]:
    return {
        "required_jobs_verified": len(candidate.GITHUB_REQUIRED_JOBS),
        "github_repository": candidate.GITHUB_REPOSITORY,
        "github_repository_id": 1234,
        "github_workflow": candidate.GITHUB_WORKFLOW_NAME,
        "github_workflow_path": (
            f"{candidate.GITHUB_WORKFLOW_PATH}@{candidate.GITHUB_BASE_REF}"
        ),
        "github_base_ref": candidate.GITHUB_BASE_REF,
        "github_pull_request_number": PULL_REQUEST_NUMBER,
        "github_run_number": WORKFLOW_RUN_NUMBER,
        "github_api_authenticated": False,
        "github_required_jobs_sha256": candidate.GITHUB_REQUIRED_JOBS_SHA256,
        "github_artifact_id": 9876,
        "github_artifact_digest": f"sha256:{candidate._sha256(ci_artifact)}",
        "github_artifact_size_bytes": ci_artifact.stat().st_size,
        "github_artifact_expires_at": "2099-09-20T00:00:00Z",
        "github_tree_sha": TREE_SHA,
        "github_blob_count": len(_source_members()),
        "github_tree_manifest_sha256": "9" * 64,
    }


def _ci_documents() -> dict[str, object]:
    residual = {
        "main_containers": [],
        "main_volumes": [],
        "main_networks": [],
        "restore_containers": [],
        "restore_volumes": [],
        "restore_networks": [],
        "images": [],
        "workspace_exists": False,
        "loopback_port_available": True,
    }
    return {
        "summary.json": {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill",
            "status": "passed",
            "source_sha": SOURCE_SHA,
            "target_sha": TARGET_SHA,
            "reported_pr_head_sha": HEAD_SHA,
            "cleanup_passed": True,
            "production_secrets_used": False,
            "persistent_gatea_authorized": False,
            "scope": "github-hosted-disposable-linux",
            "artifact_scan": {
                "allowlist_passed": True,
                "secret_scan_passed": True,
                "file_count": 4,
                "scope": "all-artifacts-before-final-summary-rewrite",
            },
        },
        "drill-state.json": {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-state",
            "ownership_acquired": True,
            "source_sha": SOURCE_SHA,
            "target_sha": TARGET_SHA,
            "source_image": f"pinkdoohub-gatea:{SOURCE_SHA}",
            "target_image": f"pinkdoohub-gatea:{TARGET_SHA}",
        },
        "cleanup-report.json": {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-cleanup",
            "checked_at": "2026-09-10T12:00:00+00:00",
            "ownership_acquired": True,
            "cleanup_performed": True,
            "errors": [],
            "residual": residual,
            "passed": True,
        },
        "artifact-scan-passed.json": {
            "schema_version": 1,
            "record_type": "gatea-m7-m9-drill-artifact-scan",
            "checked_at": "2026-09-10T12:00:01+00:00",
            "allowlist_passed": True,
            "secret_scan_passed": True,
        },
    }


def _write_ci_zip(path: Path, documents: dict[str, object] | None = None) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (documents or _ci_documents()).items():
            archive.writestr(name, json.dumps(payload, sort_keys=True))


def _upgrade_replay_payload(
    *,
    upgrade_path: Path,
    evidence_path: Path,
    database_snapshot: dict[str, object],
    image_manifest: dict[str, object],
    backup_id: str = BACKUP_ID,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "gatea-m9-upgrade-plan-replay",
        "passed": True,
        "candidate_sha": TARGET_SHA,
        "source_candidate_sha": SOURCE_SHA,
        "source_version": 7,
        "image_id": IMAGE_ID,
        "backup_id": backup_id,
        "manifest_sha256": MANIFEST_SHA,
        "upgrade_record_sha256": candidate._sha256(upgrade_path),
        "evidence_sha256": candidate._sha256(evidence_path),
        "result": {
            "already_current": True,
            "backup_id": backup_id,
            "candidate_sha": TARGET_SHA,
            "manifest_sha256": MANIFEST_SHA,
            "mode": "plan-replay",
            "source_aerich_versions": M7_CHAIN,
            "source_version": 7,
            "target_aerich_versions": M9_CHAIN,
            "target_version": 9,
        },
        "completed_at": "2026-09-10T12:00:00+00:00",
        "database_snapshot": database_snapshot,
        "image_manifest": image_manifest,
        "table_reconcile": EMPTY_TABLE_RECONCILE,
        "secret_values_recorded": False,
    }


def _local_writers(monkeypatch: pytest.MonkeyPatch) -> None:
    def write(path: Path, content: bytes, mode: int) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)

    monkeypatch.setattr(candidate, "_write_bytes_exclusive", write)
    monkeypatch.setattr(candidate, "_fsync_directory", lambda path: None)


def _valid_config(sha: str = SOURCE_SHA, *, claims: str | None = None) -> bytes:
    lines = [
        "# retained comment",
        f"GATEA_APP_IMAGE=pinkdoohub-gatea:{sha}",
        "GATEA_API_HOST=api-test.pinkdoohub.cn",
        "GATEA_LOOPBACK_PORT=18080",
        "GATEA_LETSENCRYPT_DIR=/etc/letsencrypt",
        "GATEA_ACME_CHALLENGE_DIR=/srv/pinkdoohub/gatea/acme",
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
        "PAYMENT_PROVIDER=disabled",
    ]
    if claims is not None:
        lines.append(f"TABLE_SESSION_CLAIMS_ENABLED={claims}")
    return ("\n".join(lines) + "\n").encode()


def _mock_host_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(candidate, "_require_root", lambda: None)
    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_execution_release", lambda *args: None)
    monkeypatch.setattr(
        candidate, "_load_stage", lambda **kwargs: {"image_id": IMAGE_ID}
    )
    monkeypatch.setattr(candidate, "_exclusive_lock", lambda path: nullcontext())
    monkeypatch.setattr(
        candidate, "_reject_unresolved_transition_journals", lambda **kwargs: None
    )
    _local_writers(monkeypatch)


def _capture_candidate_signal_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[int, object], dict[int, object], list[tuple[str, int]]]:
    previous = {
        signal.SIGHUP: object(),
        signal.SIGTERM: object(),
        signal.SIGINT: object(),
    }
    active: dict[int, object] = {}
    events: list[tuple[str, int]] = []

    monkeypatch.setattr(candidate.signal, "getsignal", lambda signum: previous[signum])

    def set_handler(signum: int, handler: object) -> None:
        action = "restore" if handler is previous[signum] else "install"
        events.append((action, signum))
        active[signum] = handler

    monkeypatch.setattr(candidate.signal, "signal", set_handler)
    return active, previous, events


def test_serialized_mutation_installs_signal_guard_inside_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(candidate, "_require_root", lambda: None)
    active, previous, signal_events = _capture_candidate_signal_handlers(monkeypatch)
    lock_events: list[str] = []
    observed: candidate._MutationTerminationController | None = None

    @candidate.contextmanager
    def fake_lock(path: Path) -> object:
        assert path == tmp_path / "lock"
        lock_events.append("entered")
        try:
            yield
        finally:
            lock_events.append("exited")

    monkeypatch.setattr(candidate, "_exclusive_lock", fake_lock)

    @candidate._serialized_operation
    def mutation(
        *,
        lock_file: Path | None = candidate.DEFAULT_LOCK_FILE,
        _termination_controller: (
            candidate._MutationTerminationController | None
        ) = None,
    ) -> dict[str, object]:
        del lock_file
        nonlocal observed
        observed = _termination_controller
        assert observed is not None
        assert lock_events == ["entered"]
        assert callable(active[signal.SIGTERM])
        active[signal.SIGTERM](signal.SIGTERM, None)  # type: ignore[operator]
        pytest.fail("the work-phase termination handler must raise")

    with pytest.raises(candidate.GateACandidateOperationInterrupted) as caught:
        mutation(lock_file=tmp_path / "lock")

    assert observed is not None
    assert caught.value is observed.work_interruption
    assert observed.recovery_started is True
    assert lock_events == ["entered", "exited"]
    assert signal_events == [
        ("install", signal.SIGHUP),
        ("install", signal.SIGTERM),
        ("install", signal.SIGINT),
        ("restore", signal.SIGINT),
        ("restore", signal.SIGTERM),
        ("restore", signal.SIGHUP),
    ]
    assert active == previous


@pytest.mark.parametrize(
    ("signum", "expected_type"),
    [
        pytest.param(
            signal.SIGHUP,
            candidate.GateACandidateOperationInterrupted,
            id="sighup",
        ),
        pytest.param(
            signal.SIGTERM,
            candidate.GateACandidateOperationInterrupted,
            id="sigterm",
        ),
        pytest.param(signal.SIGINT, KeyboardInterrupt, id="sigint"),
    ],
)
def test_finalization_work_signal_switches_before_raise_and_defers_recovery_signal(
    monkeypatch: pytest.MonkeyPatch,
    signum: int,
    expected_type: type[BaseException],
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    restore_calls = 0
    observed: candidate._MutationTerminationController | None = None

    def restore(**kwargs: object) -> None:
        nonlocal restore_calls
        del kwargs
        restore_calls += 1
        assert observed is not None
        assert observed.recovery_started is True
        repeated = signal.SIGTERM if signum == signal.SIGHUP else signal.SIGHUP
        assert callable(active[repeated])
        assert active[repeated](repeated, None) is None  # type: ignore[operator]

    monkeypatch.setattr(candidate, "_restore_finalization_runtime", restore)

    with pytest.raises(expected_type) as caught:
        with candidate._mutation_termination_controller("finalize") as termination:
            observed = termination

            def work() -> None:
                assert callable(active[signum])
                active[signum](signum, None)  # type: ignore[operator]

            _, work_error = candidate._run_finalization_work_then_restore(
                termination=termination,
                work=work,
                gatea=object(),
                values={},
                config_file=Path("config"),
                secret_dir=Path("secrets"),
                release_record_dir=Path("records"),
            )
            propagated = candidate._finalization_error_after_recovery(
                termination=termination,
                work_error=work_error,
            )
            assert propagated is termination.work_interruption
            raise propagated

    assert observed is not None
    assert caught.value is observed.work_interruption
    assert observed.recovery_interruption is not None
    assert restore_calls == 1


def test_finalization_recovery_sigint_is_deferred_and_propagates_same_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    recovery_events: list[str] = []
    deferred: list[BaseException] = []
    observed: candidate._MutationTerminationController | None = None

    def restore(**kwargs: object) -> None:
        del kwargs
        recovery_events.append("started")
        assert observed is not None
        assert observed.recovery_started is True
        handler = active[signal.SIGINT]
        assert callable(handler)
        assert handler(signal.SIGINT, None) is None  # type: ignore[operator]
        assert isinstance(observed.recovery_interruption, KeyboardInterrupt)
        deferred.append(observed.recovery_interruption)
        recovery_events.append("completed")

    monkeypatch.setattr(candidate, "_restore_finalization_runtime", restore)

    with pytest.raises(KeyboardInterrupt) as caught:
        with candidate._mutation_termination_controller("finalize") as termination:
            observed = termination
            _, work_error = candidate._run_finalization_work_then_restore(
                termination=termination,
                work=lambda: None,
                gatea=object(),
                values={},
                config_file=Path("config"),
                secret_dir=Path("secrets"),
                release_record_dir=Path("records"),
            )
            assert work_error is None
            propagated = candidate._finalization_error_after_recovery(
                termination=termination,
                work_error=work_error,
            )
            assert propagated is observed.recovery_interruption
            raise propagated

    assert recovery_events == ["started", "completed"]
    assert caught.value is deferred[0]


def test_stage_cleanup_defers_first_sigint_after_an_ordinary_work_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    record_path = tmp_path / "candidate-stage.json"
    record_path.write_text("{}\n", encoding="utf-8")
    temporary_dir = tmp_path / "stage"
    temporary_dir.mkdir()
    cleanup_events: list[str] = []
    deferred: list[BaseException] = []

    def remove_image(image: str) -> None:
        assert image == "temporary-image"
        cleanup_events.append("image-started")
        handler = active[signal.SIGINT]
        assert callable(handler)
        assert handler(signal.SIGINT, None) is None  # type: ignore[operator]
        controller = getattr(handler, "__self__")
        assert isinstance(controller, candidate._MutationTerminationController)
        assert isinstance(controller.recovery_interruption, KeyboardInterrupt)
        deferred.append(controller.recovery_interruption)
        cleanup_events.append("image-completed")

    def remove_directory(path: Path) -> None:
        assert path == temporary_dir
        cleanup_events.append("directory-completed")
        path.rmdir()

    monkeypatch.setattr(candidate, "_remove_temporary_image", remove_image)
    monkeypatch.setattr(candidate.shutil, "rmtree", remove_directory)

    with pytest.raises(KeyboardInterrupt) as caught:
        with candidate._mutation_termination_controller("stage") as termination:
            try:
                raise OSError("ordinary stage work failure")
            finally:
                candidate._cleanup_candidate_stage(
                    termination=termination,
                    temporary_image="temporary-image",
                    record_path=record_path,
                    temporary_dir=temporary_dir,
                )

    assert cleanup_events == [
        "image-started",
        "image-completed",
        "directory-completed",
    ]
    assert caught.value is deferred[0]


def test_stage_cleanup_boundary_sigint_cannot_skip_either_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    record_path = tmp_path / "candidate-stage.json"
    record_path.write_text("{}\n", encoding="utf-8")
    temporary_dir = tmp_path / "stage"
    temporary_dir.mkdir()
    cleanup_events: list[str] = []
    observed: candidate._MutationTerminationController | None = None

    monkeypatch.setattr(
        candidate,
        "_remove_temporary_image",
        lambda image: cleanup_events.append("image"),
    )

    def remove_directory(path: Path) -> None:
        cleanup_events.append("directory")
        path.rmdir()

    monkeypatch.setattr(candidate.shutil, "rmtree", remove_directory)

    with pytest.raises(KeyboardInterrupt) as caught:
        with candidate._mutation_termination_controller("stage") as termination:
            observed = termination

            def interrupt_at_boundary() -> None:
                handler = active[signal.SIGINT]
                assert callable(handler)
                handler(signal.SIGINT, None)  # type: ignore[operator]

            termination.begin_recovery = interrupt_at_boundary
            candidate._cleanup_candidate_stage(
                termination=termination,
                temporary_image="temporary-image",
                record_path=record_path,
                temporary_dir=temporary_dir,
            )

    assert observed is not None
    assert cleanup_events == ["image", "directory"]
    assert caught.value is observed.work_interruption


def test_temporary_image_cleanup_is_isolated_retried_and_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []
    inspections = 0

    def run(
        command: tuple[str, ...],
        **kwargs: object,
    ) -> SimpleNamespace:
        nonlocal inspections
        calls.append((command, bool(kwargs.get("start_new_session"))))
        if command[:3] == ("docker", "image", "ls"):
            inspections += 1
            return SimpleNamespace(
                returncode=0,
                stdout="sha256:temporary\n" if inspections == 1 else "",
                stderr="",
            )
        return SimpleNamespace(returncode=-2, stdout="", stderr="")

    monkeypatch.setattr(candidate, "_run", run)

    candidate._remove_temporary_image("temporary-image")

    assert [command[:3] for command, _ in calls] == [
        ("docker", "image", "rm"),
        ("docker", "image", "ls"),
        ("docker", "image", "rm"),
        ("docker", "image", "ls"),
    ]
    assert all(isolated for _, isolated in calls)


def test_candidate_run_forwards_recovery_process_group_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    def run(command: object, **kwargs: object) -> SimpleNamespace:
        del command
        observed.append(dict(kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(candidate.subprocess, "run", run)

    candidate._run(
        ("docker", "image", "rm", "temporary-image"),
        check=False,
        start_new_session=True,
    )

    assert observed[0]["start_new_session"] is True


@pytest.mark.parametrize("work_fails", [False, True], ids=("normal", "exception"))
def test_finalization_work_to_recovery_boundary_signal_cannot_skip_restore(
    monkeypatch: pytest.MonkeyPatch,
    work_fails: bool,
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    restore_calls = 0

    def restore(**kwargs: object) -> None:
        nonlocal restore_calls
        del kwargs
        restore_calls += 1

    monkeypatch.setattr(candidate, "_restore_finalization_runtime", restore)

    with pytest.raises(candidate.GateACandidateOperationInterrupted) as caught:
        with candidate._mutation_termination_controller("finalize") as termination:
            original_begin_recovery = termination.begin_recovery
            boundary_injected = False

            def inject_at_boundary() -> None:
                nonlocal boundary_injected
                if not boundary_injected:
                    boundary_injected = True
                    assert callable(active[signal.SIGTERM])
                    active[signal.SIGTERM](  # type: ignore[operator]
                        signal.SIGTERM, None
                    )
                original_begin_recovery()

            termination.begin_recovery = inject_at_boundary

            def work() -> None:
                if work_fails:
                    raise OSError("injected work failure")

            candidate._run_finalization_work_then_restore(
                termination=termination,
                work=work,
                gatea=object(),
                values={},
                config_file=Path("config"),
                secret_dir=Path("secrets"),
                release_record_dir=Path("records"),
            )

    assert caught.value is termination.work_interruption
    assert restore_calls == 1


@pytest.mark.parametrize(
    "control_error",
    [pytest.param(KeyboardInterrupt("stop"), id="keyboard-interrupt"),
     pytest.param(SystemExit(23), id="system-exit")],
)
@pytest.mark.parametrize("phase", ["work", "recovery"])
def test_finalization_control_error_is_preserved_after_exact_recovery(
    monkeypatch: pytest.MonkeyPatch,
    control_error: KeyboardInterrupt | SystemExit,
    phase: str,
) -> None:
    _capture_candidate_signal_handlers(monkeypatch)
    restore_calls = 0

    def work() -> str:
        if phase == "work":
            raise control_error
        return "completed"

    def restore(**kwargs: object) -> None:
        nonlocal restore_calls
        del kwargs
        restore_calls += 1
        if phase == "recovery" and restore_calls == 1:
            raise control_error

    monkeypatch.setattr(candidate, "_restore_finalization_runtime", restore)

    with pytest.raises(type(control_error)) as caught:
        with candidate._mutation_termination_controller("finalize") as termination:
            _, work_error = candidate._run_finalization_work_then_restore(
                termination=termination,
                work=work,
                gatea=object(),
                values={},
                config_file=Path("config"),
                secret_dir=Path("secrets"),
                release_record_dir=Path("records"),
            )
            propagated = candidate._finalization_error_after_recovery(
                termination=termination,
                work_error=work_error,
            )
            assert propagated is control_error
            raise propagated

    assert caught.value is control_error
    assert restore_calls == (1 if phase == "work" else 2)


def test_finalization_recovery_retains_first_control_error_and_recovery_failure_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    first_control = KeyboardInterrupt("first cleanup interruption")
    later_control = SystemExit(29)
    operation_failure = ValueError("injected work failure")
    recovery_failure = OSError("injected recovery failure")
    restore_calls = 0

    def restore(**kwargs: object) -> None:
        nonlocal restore_calls
        del kwargs
        restore_calls += 1
        if restore_calls == 1:
            raise first_control
        if restore_calls == 2:
            raise later_control
        assert callable(active[signal.SIGTERM])
        assert (
            active[signal.SIGTERM](  # type: ignore[operator]
                signal.SIGTERM, None
            )
            is None
        )
        raise recovery_failure

    monkeypatch.setattr(candidate, "_restore_finalization_runtime", restore)

    with pytest.raises(
        candidate.GateACandidateError,
        match="target runtime recovery failed",
    ) as caught:
        with candidate._mutation_termination_controller("finalize") as termination:

            def fail_work() -> None:
                raise operation_failure

            candidate._run_finalization_work_then_restore(
                termination=termination,
                work=fail_work,
                gatea=object(),
                values={},
                config_file=Path("config"),
                secret_dir=Path("secrets"),
                release_record_dir=Path("records"),
            )

    assert caught.value.__cause__ is recovery_failure
    assert termination.recovery_interruption is first_control
    assert restore_calls == 3


def test_finalization_successful_recovery_rethrows_first_of_repeated_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    first_control = KeyboardInterrupt("first cleanup interruption")
    later_control = SystemExit(31)
    restore_calls = 0

    def restore(**kwargs: object) -> None:
        nonlocal restore_calls
        del kwargs
        restore_calls += 1
        if restore_calls == 1:
            raise first_control
        if restore_calls == 2:
            raise later_control
        assert callable(active[signal.SIGTERM])
        assert (
            active[signal.SIGTERM](  # type: ignore[operator]
                signal.SIGTERM, None
            )
            is None
        )

    monkeypatch.setattr(candidate, "_restore_finalization_runtime", restore)

    with pytest.raises(KeyboardInterrupt) as caught:
        with candidate._mutation_termination_controller("finalize") as termination:
            _, work_error = candidate._run_finalization_work_then_restore(
                termination=termination,
                work=lambda: None,
                gatea=object(),
                values={},
                config_file=Path("config"),
                secret_dir=Path("secrets"),
                release_record_dir=Path("records"),
            )
            propagated = candidate._finalization_error_after_recovery(
                termination=termination,
                work_error=work_error,
            )
            assert propagated is first_control
            raise propagated

    assert caught.value is first_control
    assert termination.recovery_interruption is first_control
    assert restore_calls == 3


def test_exclusive_publication_is_atomic_and_does_not_replace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(candidate.os, "fchown", lambda *args: None)
    destination = tmp_path / "record.json"

    candidate._write_bytes_exclusive(destination, b"complete\n", 0o640)

    assert destination.read_bytes() == b"complete\n"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640
    assert list(tmp_path.iterdir()) == [destination]
    with pytest.raises(FileExistsError):
        candidate._write_bytes_exclusive(destination, b"replacement\n", 0o640)
    assert destination.read_bytes() == b"complete\n"
    assert list(tmp_path.iterdir()) == [destination]


def test_exclusive_publication_failure_never_occupies_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(candidate.os, "fchown", lambda *args: None)
    monkeypatch.setattr(candidate, "_fsync_directory", lambda path: None)
    monkeypatch.setattr(
        candidate.os,
        "fsync",
        lambda descriptor: (_ for _ in ()).throw(
            OSError("injected incomplete write")
        ),
    )
    destination = tmp_path / "record.json"

    with pytest.raises(OSError, match="injected incomplete write"):
        candidate._write_bytes_exclusive(destination, b"never published\n", 0o600)

    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_extract_source_archive_binds_git_archive_commit_and_normalizes_modes(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "source.tar"
    destination = tmp_path / "release"
    destination.mkdir()
    _write_source_tar(archive)

    result = candidate._extract_source_archive(
        archive, destination, target_sha=TARGET_SHA
    )

    assert result["source_file_count"] == len(_source_members())
    assert len(result["source_manifest_sha256"]) == 64
    assert stat.S_IMODE(
        (destination / "deploy/runtime/app-entrypoint.sh").stat().st_mode
    ) == 0o755


def test_extract_source_archive_rejects_wrong_git_commit(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar"
    destination = tmp_path / "release"
    destination.mkdir()
    _write_source_tar(archive, commit="a" * 40)

    with pytest.raises(candidate.GateACandidateError, match="tested Git commit"):
        candidate._extract_source_archive(
            archive, destination, target_sha=TARGET_SHA
        )


@pytest.mark.parametrize(
    "special",
    (
        ("../escape", b"bad", tarfile.REGTYPE),
        ("unsafe-link", b"", tarfile.SYMTYPE),
        ("unsafe-hardlink", b"", tarfile.LNKTYPE),
    ),
)
def test_extract_source_archive_rejects_unsafe_members(
    tmp_path: Path, special: tuple[str, bytes, int]
) -> None:
    archive = tmp_path / "source.tar"
    destination = tmp_path / "release"
    destination.mkdir()
    _write_source_tar(archive, special=special)

    with pytest.raises(candidate.GateACandidateError):
        candidate._extract_source_archive(
            archive, destination, target_sha=TARGET_SHA
        )
    assert not (tmp_path / "escape").exists()


def test_validate_ci_artifact_requires_all_independent_pass_evidence(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "artifact.zip"
    _write_ci_zip(archive)

    result = candidate._validate_ci_artifact(
        archive,
        target_sha=TARGET_SHA,
        source_head_sha=HEAD_SHA,
        run_id=RUN_ID,
        run_attempt=ATTEMPT,
    )

    assert result["artifact_scan_passed"] is True
    assert result["ci_cleanup_passed"] is True


@pytest.mark.parametrize(
    ("document", "field", "bad_value"),
    (
        ("summary.json", "record_type", "wrong"),
        ("summary.json", "target_sha", "a" * 40),
        ("summary.json", "cleanup_passed", False),
        ("cleanup-report.json", "passed", False),
        ("artifact-scan-passed.json", "secret_scan_passed", False),
    ),
)
def test_validate_ci_artifact_rejects_each_untrusted_claim(
    tmp_path: Path, document: str, field: str, bad_value: object
) -> None:
    documents = _ci_documents()
    assert isinstance(documents[document], dict)
    documents[document][field] = bad_value
    archive = tmp_path / "artifact.zip"
    _write_ci_zip(archive, documents)

    with pytest.raises(candidate.GateACandidateError, match="does not prove"):
        candidate._validate_ci_artifact(
            archive,
            target_sha=TARGET_SHA,
            source_head_sha=HEAD_SHA,
            run_id=RUN_ID,
            run_attempt=ATTEMPT,
        )


def test_validate_ci_artifact_rejects_non_allowlisted_member(tmp_path: Path) -> None:
    archive = tmp_path / "artifact.zip"
    documents = _ci_documents() | {"unexpected.json": {"value": True}}
    _write_ci_zip(archive, documents)

    with pytest.raises(candidate.GateACandidateError, match="not allowlisted"):
        candidate._validate_ci_artifact(
            archive,
            target_sha=TARGET_SHA,
            source_head_sha=HEAD_SHA,
            run_id=RUN_ID,
            run_attempt=ATTEMPT,
        )


def test_github_provenance_binds_run_pr_jobs_artifact_and_every_git_blob(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    source_root = tmp_path / "source"
    _write_source_directory(source_root)
    artifact = tmp_path / "artifact.zip"
    _write_ci_zip(artifact)
    documents = _github_api_documents(source_root, artifact)
    requested: list[str] = []

    def get_json(path: str, *, token: str | None) -> dict[str, object]:
        assert token is None
        requested.append(path)
        return copy.deepcopy(documents[path])

    monkeypatch.setattr(candidate, "_github_get_json", get_json)

    result = candidate._verify_github_provenance(
        source_root=source_root,
        ci_artifact=artifact,
        ci_artifact_sha256=candidate._sha256(artifact),
        target_sha=TARGET_SHA,
        source_head_sha=HEAD_SHA,
        run_id=RUN_ID,
        run_attempt=ATTEMPT,
        artifact_name=ARTIFACT_NAME,
    )

    assert set(result) == {
        "required_jobs_verified",
        "github_repository",
        "github_repository_id",
        "github_workflow",
        "github_workflow_path",
        "github_base_ref",
        "github_pull_request_number",
        "github_run_number",
        "github_api_authenticated",
        "github_required_jobs_sha256",
        "github_artifact_id",
        "github_artifact_digest",
        "github_artifact_size_bytes",
        "github_artifact_expires_at",
        "github_tree_sha",
        "github_blob_count",
        "github_tree_manifest_sha256",
    }
    assert result["required_jobs_verified"] == len(candidate.GITHUB_REQUIRED_JOBS)
    assert result["github_pull_request_number"] == PULL_REQUEST_NUMBER
    assert result["github_artifact_digest"] == f"sha256:{candidate._sha256(artifact)}"
    assert result["github_tree_sha"] == TREE_SHA
    assert result["github_blob_count"] == len(_source_members())
    assert set(requested) == set(documents)
    assert len(requested) == len(documents)


@pytest.mark.parametrize(
    "claim",
    (
        "run-attempt",
        "run-head",
        "run-head-commit",
        "run-repository",
        "run-pr-head",
        "workflow-path",
        "pr-base",
        "pr-merge-commit",
        "required-job-name",
        "required-job-conclusion",
        "required-job-head",
        "artifact-name",
        "artifact-expired",
        "artifact-expired-at",
        "artifact-digest",
        "artifact-workflow-run",
        "artifact-workflow-head",
        "commit-parents",
    ),
)
def test_github_provenance_rejects_each_untrusted_api_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, claim: str
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    source_root = tmp_path / "source"
    _write_source_directory(source_root)
    artifact = tmp_path / "artifact.zip"
    _write_ci_zip(artifact)
    documents = _github_api_documents(source_root, artifact)
    prefix = f"/repos/{candidate.GITHUB_REPOSITORY}"
    run = documents[f"{prefix}/actions/runs/{RUN_ID}"]
    pull = documents[f"{prefix}/pulls/{PULL_REQUEST_NUMBER}"]
    jobs = documents[
        (
            f"{prefix}/actions/runs/{RUN_ID}/attempts/{ATTEMPT}/jobs"
            "?per_page=100&page=1"
        )
    ]
    artifact_document = next(
        payload for path, payload in documents.items() if "/artifacts?" in path
    )
    commit = documents[f"{prefix}/git/commits/{TARGET_SHA}"]
    if claim == "run-attempt":
        run["run_attempt"] = ATTEMPT + 1
    elif claim == "run-head":
        run["head_sha"] = TARGET_SHA
    elif claim == "run-head-commit":
        assert isinstance(run["head_commit"], dict)
        run["head_commit"]["id"] = TARGET_SHA
    elif claim == "run-repository":
        assert isinstance(run["repository"], dict)
        run["repository"]["full_name"] = "EVEBios/not-pinkdooHub"
    elif claim == "run-pr-head":
        assert isinstance(run["pull_requests"], list)
        run_pull = run["pull_requests"][0]
        assert isinstance(run_pull, dict)
        assert isinstance(run_pull["head"], dict)
        run_pull["head"]["sha"] = "0" * 40
    elif claim == "workflow-path":
        run["path"] = ".github/workflows/other.yml@develop"
    elif claim == "pr-base":
        assert isinstance(pull["base"], dict)
        pull["base"]["ref"] = "main"
    elif claim == "pr-merge-commit":
        pull["merge_commit_sha"] = "0" * 40
    elif claim == "required-job-name":
        assert isinstance(jobs["jobs"], list)
        jobs["jobs"][0]["name"] = "unexpected-job"
    elif claim == "required-job-conclusion":
        assert isinstance(jobs["jobs"], list)
        jobs["jobs"][0]["conclusion"] = "failure"
    elif claim == "required-job-head":
        assert isinstance(jobs["jobs"], list)
        jobs["jobs"][0]["head_sha"] = TARGET_SHA
    elif claim == "artifact-name":
        assert isinstance(artifact_document["artifacts"], list)
        artifact_document["artifacts"][0]["name"] = "wrong-artifact"
    elif claim == "artifact-expired":
        assert isinstance(artifact_document["artifacts"], list)
        artifact_document["artifacts"][0]["expired"] = True
    elif claim == "artifact-expired-at":
        assert isinstance(artifact_document["artifacts"], list)
        artifact_document["artifacts"][0]["expires_at"] = (
            "2020-09-20T00:00:00+00:00"
        )
    elif claim == "artifact-digest":
        assert isinstance(artifact_document["artifacts"], list)
        artifact_document["artifacts"][0]["digest"] = "sha256:" + "0" * 64
    elif claim == "artifact-workflow-run":
        assert isinstance(artifact_document["artifacts"], list)
        workflow_run = artifact_document["artifacts"][0]["workflow_run"]
        assert isinstance(workflow_run, dict)
        workflow_run["id"] = int(RUN_ID) + 1
    elif claim == "artifact-workflow-head":
        assert isinstance(artifact_document["artifacts"], list)
        workflow_run = artifact_document["artifacts"][0]["workflow_run"]
        assert isinstance(workflow_run, dict)
        workflow_run["head_sha"] = TARGET_SHA
    else:
        commit["parents"] = [{"sha": HEAD_SHA}, {"sha": "1" * 40}]

    monkeypatch.setattr(
        candidate,
        "_github_get_json",
        lambda path, *, token: copy.deepcopy(documents[path]),
    )

    with pytest.raises(candidate.GateACandidateError, match="provenance"):
        candidate._verify_github_provenance(
            source_root=source_root,
            ci_artifact=artifact,
            ci_artifact_sha256=candidate._sha256(artifact),
            target_sha=TARGET_SHA,
            source_head_sha=HEAD_SHA,
            run_id=RUN_ID,
            run_attempt=ATTEMPT,
            artifact_name=ARTIFACT_NAME,
        )


@pytest.mark.parametrize(
    "mismatch",
    (
        "truncated",
        "path",
        "mode",
        "blob-sha",
        "local-extra-file",
        "local-extra-directory",
    ),
)
def test_github_source_tree_rejects_incomplete_or_mismatched_blobs(
    tmp_path: Path, mismatch: str
) -> None:
    source_root = tmp_path / "source"
    _write_source_directory(source_root)
    commit = {
        "sha": TARGET_SHA,
        "tree": {"sha": TREE_SHA},
        "parents": [{"sha": "1" * 40}, {"sha": HEAD_SHA}],
    }
    tree = _github_tree_payload(source_root)
    assert isinstance(tree["tree"], list)
    first_blob = next(entry for entry in tree["tree"] if entry["type"] == "blob")
    if mismatch == "truncated":
        tree["truncated"] = True
    elif mismatch == "path":
        first_blob["path"] = "renamed-file"
    elif mismatch == "mode":
        first_blob["mode"] = "100755"
    elif mismatch == "blob-sha":
        first_blob["sha"] = "0" * 40
    elif mismatch == "local-extra-file":
        extra = source_root / "untracked.txt"
        extra.write_text("not in Git", encoding="utf-8")
        extra.chmod(0o644)
    else:
        extra = source_root / "untracked-directory"
        extra.mkdir(mode=0o755)

    with pytest.raises(candidate.GateACandidateError, match="source tree"):
        candidate._validate_github_source_tree(
            source_root,
            target_sha=TARGET_SHA,
            commit_payload=commit,
            tree_payload=tree,
        )


def test_github_api_failure_does_not_expose_token_or_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "github-token-must-not-appear"

    def fail_request(request: object) -> object:
        raise candidate.urllib.error.HTTPError(
            "https://api.github.com/redacted",
            403,
            "response-secret-must-not-appear",
            None,
            None,
        )

    monkeypatch.setattr(candidate, "_github_urlopen", fail_request)
    with pytest.raises(candidate.GateACandidateError) as captured:
        candidate._github_get_json(
            f"/repos/{candidate.GITHUB_REPOSITORY}/actions/runs/{RUN_ID}",
            token=token,
        )

    message = str(captured.value)
    assert message == "GitHub provenance API request failed"
    assert token not in message
    assert "response-secret-must-not-appear" not in message


def test_rewrite_config_changes_only_image_and_claim_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.release import gatea_backup, gatea_operations, gatea_upgrade

    monkeypatch.setattr(
        candidate,
        "_runtime_modules",
        lambda: (gatea_operations, gatea_backup, gatea_upgrade),
    )
    original = _valid_config()

    rewritten, changed = candidate._rewrite_config(original, TARGET_SHA)

    assert changed == ["GATEA_APP_IMAGE", "TABLE_SESSION_CLAIMS_ENABLED"]
    assert b"# retained comment\n" in rewritten
    assert f"GATEA_APP_IMAGE=pinkdoohub-gatea:{TARGET_SHA}\n".encode() in rewritten
    assert rewritten.endswith(b"TABLE_SESSION_CLAIMS_ENABLED=true\n")
    before = {
        line for line in original.splitlines() if not line.startswith(b"GATEA_APP_IMAGE=")
    }
    after = {
        line
        for line in rewritten.splitlines()
        if not line.startswith((b"GATEA_APP_IMAGE=", b"TABLE_SESSION_CLAIMS_ENABLED="))
    }
    assert before == after


def test_rewrite_config_rejects_duplicate_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.release import gatea_backup, gatea_operations, gatea_upgrade

    monkeypatch.setattr(
        candidate,
        "_runtime_modules",
        lambda: (gatea_operations, gatea_backup, gatea_upgrade),
    )
    original = _valid_config() + b"APP_ENV=production\n"

    with pytest.raises(candidate.GateACandidateError, match="duplicate"):
        candidate._rewrite_config(original, TARGET_SHA)


def test_stage_writes_immutable_source_image_and_ci_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_host_guards(monkeypatch)
    release_root = tmp_path / "releases"
    staging_root = tmp_path / "staging"
    record_dir = tmp_path / "records"
    for directory in (release_root, staging_root, record_dir):
        directory.mkdir()
    launcher = tmp_path / "launcher.py"
    launcher.write_bytes(b"candidate launcher\n")
    source = tmp_path / "source.tar"
    _write_source_tar(source, members=_source_members(launcher.read_bytes()))
    artifact = tmp_path / "artifact.zip"
    _write_ci_zip(artifact)
    monkeypatch.setattr(
        candidate,
        "_verify_github_provenance",
        lambda **kwargs: _github_stage_evidence(artifact),
    )
    monkeypatch.setattr(candidate, "_image_exists", lambda image: False)
    monkeypatch.setattr(
        candidate,
        "_inspect_image",
        lambda image, sha, **kwargs: {
            "architecture": "amd64",
            "image_id": IMAGE_ID,
            "operating_system": "linux",
        },
    )
    commands: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(candidate, "_run", fake_run)

    result = candidate.stage_candidate(
        source_archive=source,
        source_archive_sha256=candidate._sha256(source),
        ci_artifact=artifact,
        ci_artifact_sha256=candidate._sha256(artifact),
        launcher=launcher,
        launcher_sha256=candidate._sha256(launcher),
        target_sha=TARGET_SHA,
        source_head_sha=HEAD_SHA,
        ci_run_id=RUN_ID,
        ci_run_attempt=ATTEMPT,
        ci_artifact_name=ARTIFACT_NAME,
        confirmed_required_jobs=9,
        release_root=release_root,
        staging_root=staging_root,
        release_record_dir=record_dir,
        lock_file=tmp_path / "lock",
    )

    assert set(result) == candidate.STAGE_RECORD_KEYS
    assert result["passed"] is True
    assert result["candidate_sha"] == TARGET_SHA
    assert result["image_id"] == IMAGE_ID
    assert result["github_repository"] == candidate.GITHUB_REPOSITORY
    assert result["github_artifact_digest"] == f"sha256:{candidate._sha256(artifact)}"
    assert result["required_jobs_verified"] == len(candidate.GITHUB_REQUIRED_JOBS)
    assert (release_root / TARGET_SHA).is_dir()
    assert (record_dir / f"{TARGET_SHA}.source-sha").read_text().strip() == TARGET_SHA
    assert any(command[:2] == ("docker", "build") and "--pull" in command for command in commands)


def test_installed_release_commands_do_not_change_the_stage_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_load_stage = candidate._load_stage
    _mock_host_guards(monkeypatch)
    release_root = tmp_path / "releases"
    staging_root = tmp_path / "staging"
    record_dir = tmp_path / "records"
    for directory in (release_root, staging_root, record_dir):
        directory.mkdir()

    launcher = tmp_path / "launcher.py"
    launcher.write_bytes(Path(candidate.__file__).read_bytes())
    members = _source_members(launcher.read_bytes())
    members["scripts/release/gatea_operations.py"] = Path(
        gatea_operations.__file__
    ).read_bytes()
    source = tmp_path / "source.tar"
    _write_source_tar(source, members=members)
    artifact = tmp_path / "artifact.zip"
    _write_ci_zip(artifact)
    monkeypatch.setattr(
        candidate,
        "_verify_github_provenance",
        lambda **kwargs: _github_stage_evidence(artifact),
    )
    monkeypatch.setattr(candidate, "_image_exists", lambda image: False)
    monkeypatch.setattr(
        candidate,
        "_inspect_image",
        lambda image, sha, **kwargs: {
            "architecture": "amd64",
            "image_id": IMAGE_ID,
            "operating_system": "linux",
        },
    )
    monkeypatch.setattr(
        candidate,
        "_run",
        lambda command, **kwargs: SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
    )

    staged = candidate.stage_candidate(
        source_archive=source,
        source_archive_sha256=candidate._sha256(source),
        ci_artifact=artifact,
        ci_artifact_sha256=candidate._sha256(artifact),
        launcher=launcher,
        launcher_sha256=candidate._sha256(launcher),
        target_sha=TARGET_SHA,
        source_head_sha=HEAD_SHA,
        ci_run_id=RUN_ID,
        ci_run_attempt=ATTEMPT,
        ci_artifact_name=ARTIFACT_NAME,
        confirmed_required_jobs=9,
        release_root=release_root,
        staging_root=staging_root,
        release_record_dir=record_dir,
        lock_file=tmp_path / "lock",
    )
    release_dir = release_root / TARGET_SHA
    staged_manifest = {
        key: staged[key]
        for key in (
            "source_file_count",
            "source_total_bytes",
            "source_manifest_sha256",
        )
    }

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    for module in (
        "scripts.release.gatea_operations",
        "scripts.release.gatea_candidate",
    ):
        subprocess.run(
            (sys.executable, "-B", "-m", module, "--help"),
            cwd=release_dir,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    assert candidate._source_manifest(release_dir) == staged_manifest
    assert not any(path.name == "__pycache__" for path in release_dir.rglob("*"))
    assert not list(release_dir.rglob("*.pyc"))
    assert not list(release_dir.rglob("*.pyo"))

    monkeypatch.setattr(candidate, "_load_stage", real_load_stage)
    assert candidate._load_stage(
        release_root=release_root,
        release_record_dir=record_dir,
        target_sha=TARGET_SHA,
    ) == staged


def test_gatea_runbooks_disable_bytecode_for_installed_release_modules() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    runbooks = (
        repository_root / "deploy/gatea/README.md",
        repository_root / "docs/09_release/release_drill_runbook.md",
    )
    marker = "-m scripts.release.gatea_"
    unsafe_commands: list[str] = []
    unsafe_stage_launchers: list[str] = []
    for runbook in runbooks:
        for line_number, line in enumerate(
            runbook.read_text(encoding="utf-8").splitlines(), start=1
        ):
            location = f"{runbook.relative_to(repository_root)}:{line_number}"
            if marker in line:
                prefix = line[: line.index(marker)]
                if "-B" not in prefix.split():
                    unsafe_commands.append(f"{location}: {line.strip()}")
            if "<checksum-confirmed-launcher>/gatea_candidate.py stage" in line:
                prefix = line[: line.index("<checksum-confirmed-launcher>")]
                if "-B" not in prefix.split():
                    unsafe_stage_launchers.append(f"{location}: {line.strip()}")

    failures: list[str] = []
    if unsafe_commands:
        failures.append(
            "installed Gate A release modules must run with Python -B:\n"
            + "\n".join(unsafe_commands)
        )
    if unsafe_stage_launchers:
        failures.append(
            "the checksum-confirmed Gate A stage launcher must run with Python -B:\n"
            + "\n".join(unsafe_stage_launchers)
        )

    assert not failures, "\n".join(failures)


def test_stage_recovers_after_release_publish_before_final_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_host_guards(monkeypatch)
    release_root = tmp_path / "releases"
    staging_root = tmp_path / "staging"
    record_dir = tmp_path / "records"
    for directory in (release_root, staging_root, record_dir):
        directory.mkdir()
    launcher = tmp_path / "launcher.py"
    launcher.write_bytes(b"candidate launcher\n")
    source = tmp_path / "source.tar"
    _write_source_tar(source, members=_source_members(launcher.read_bytes()))
    artifact = tmp_path / "artifact.zip"
    _write_ci_zip(artifact)
    monkeypatch.setattr(
        candidate,
        "_verify_github_provenance",
        lambda **kwargs: _github_stage_evidence(artifact),
    )

    images: set[str] = set()
    commands: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        if command[:2] == ("docker", "build"):
            images.add(command[command.index("--tag") + 1])
        elif command[:3] == ("docker", "image", "tag"):
            assert command[3] in images
            images.add(command[4])
        elif command[:3] == ("docker", "image", "rm"):
            images.discard(command[3])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(candidate, "_run", fake_run)
    monkeypatch.setattr(candidate, "_image_exists", lambda image: image in images)
    monkeypatch.setattr(
        candidate,
        "_inspect_image",
        lambda image, sha, **kwargs: {
            "architecture": "amd64",
            "image_id": IMAGE_ID,
            "operating_system": "linux",
        },
    )
    final_path = record_dir / f"{TARGET_SHA}.candidate-stage.json"
    pending_path = record_dir / f"{TARGET_SHA}.candidate-stage.pending.json"
    original_writer = candidate._write_json_exclusive
    failed_once = False

    def fail_final_once(
        path: Path,
        payload: dict[str, object],
        mode: int = 0o644,
    ) -> None:
        nonlocal failed_once
        if path == final_path and not failed_once:
            failed_once = True
            raise OSError("injected stage record failure")
        original_writer(path, payload, mode)

    monkeypatch.setattr(candidate, "_write_json_exclusive", fail_final_once)
    arguments = {
        "source_archive": source,
        "source_archive_sha256": candidate._sha256(source),
        "ci_artifact": artifact,
        "ci_artifact_sha256": candidate._sha256(artifact),
        "launcher": launcher,
        "launcher_sha256": candidate._sha256(launcher),
        "target_sha": TARGET_SHA,
        "source_head_sha": HEAD_SHA,
        "ci_run_id": RUN_ID,
        "ci_run_attempt": ATTEMPT,
        "ci_artifact_name": ARTIFACT_NAME,
        "confirmed_required_jobs": 9,
        "release_root": release_root,
        "staging_root": staging_root,
        "release_record_dir": record_dir,
        "lock_file": tmp_path / "lock",
    }

    with pytest.raises(OSError, match="injected stage record failure"):
        candidate.stage_candidate(**arguments)
    assert pending_path.is_file()
    assert stat.S_IMODE(pending_path.stat().st_mode) == 0o600
    assert (release_root / TARGET_SHA).is_dir()
    assert f"pinkdoohub-gatea:{TARGET_SHA}" in images
    build_count = sum(command[:2] == ("docker", "build") for command in commands)

    result = candidate.stage_candidate(**arguments)

    assert result["passed"] is True
    assert final_path.is_file()
    assert not pending_path.exists()
    assert sum(command[:2] == ("docker", "build") for command in commands) == build_count
    assert not any(image.startswith("pinkdoohub-gatea-stage:") for image in images)


def test_stage_rejects_github_provenance_before_docker_or_release_publish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_host_guards(monkeypatch)
    release_root = tmp_path / "releases"
    staging_root = tmp_path / "staging"
    record_dir = tmp_path / "records"
    for directory in (release_root, staging_root, record_dir):
        directory.mkdir()
    launcher = tmp_path / "launcher.py"
    launcher.write_bytes(b"candidate launcher\n")
    source = tmp_path / "source.tar"
    _write_source_tar(source, members=_source_members(launcher.read_bytes()))
    artifact = tmp_path / "artifact.zip"
    _write_ci_zip(artifact)
    monkeypatch.setattr(candidate, "_image_exists", lambda image: False)
    monkeypatch.setattr(
        candidate,
        "_verify_github_provenance",
        lambda **kwargs: (_ for _ in ()).throw(
            candidate.GateACandidateError("GitHub provenance rejected")
        ),
    )
    monkeypatch.setattr(
        candidate,
        "_run",
        lambda *args, **kwargs: pytest.fail("Docker must not run before provenance"),
    )

    with pytest.raises(candidate.GateACandidateError, match="provenance rejected"):
        candidate.stage_candidate(
            source_archive=source,
            source_archive_sha256=candidate._sha256(source),
            ci_artifact=artifact,
            ci_artifact_sha256=candidate._sha256(artifact),
            launcher=launcher,
            launcher_sha256=candidate._sha256(launcher),
            target_sha=TARGET_SHA,
            source_head_sha=HEAD_SHA,
            ci_run_id=RUN_ID,
            ci_run_attempt=ATTEMPT,
            ci_artifact_name=ARTIFACT_NAME,
            confirmed_required_jobs=9,
            release_root=release_root,
            staging_root=staging_root,
            release_record_dir=record_dir,
            lock_file=tmp_path / "lock",
        )

    assert list(release_root.iterdir()) == []
    assert list(record_dir.iterdir()) == []
    assert list(staging_root.iterdir()) == []


def test_stage_rejects_wrong_artifact_name_before_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_host_guards(monkeypatch)
    with pytest.raises(candidate.GateACandidateError, match="artifact name"):
        candidate.stage_candidate(
            source_archive=tmp_path / "missing.tar",
            source_archive_sha256="a" * 64,
            ci_artifact=tmp_path / "missing.zip",
            ci_artifact_sha256="b" * 64,
            launcher=tmp_path / "missing.py",
            launcher_sha256="c" * 64,
            target_sha=TARGET_SHA,
            source_head_sha=HEAD_SHA,
            ci_run_id=RUN_ID,
            ci_run_attempt=ATTEMPT,
            ci_artifact_name="wrong",
            confirmed_required_jobs=9,
            release_root=tmp_path,
            staging_root=tmp_path,
            release_record_dir=tmp_path,
        )


def test_activate_config_plan_is_read_only_and_apply_is_atomic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_host_guards(monkeypatch)
    from scripts.release import gatea_backup, gatea_operations, gatea_upgrade

    monkeypatch.setattr(
        candidate,
        "_runtime_modules",
        lambda: (gatea_operations, gatea_backup, gatea_upgrade),
    )
    monkeypatch.setattr(
        candidate,
        "_load_stage",
        lambda **kwargs: {"image_id": IMAGE_ID},
    )
    monkeypatch.setattr(
        candidate,
        "_read_current_target",
        lambda current, release_root: release_root / SOURCE_SHA,
    )
    monkeypatch.setattr(
        candidate,
        "_ensure_root_directory",
        lambda path, mode, description: path.mkdir(exist_ok=True),
    )
    plan = {
        "mode": "plan",
        "already_current": False,
        "candidate_sha": TARGET_SHA,
        "source_candidate_sha": SOURCE_SHA,
        "backup_id": BACKUP_ID,
        "source_version": 7,
        "restore_verified": True,
        "source_aerich_versions": M7_CHAIN,
        "target_aerich_versions": M9_CHAIN,
        "target_version": 9,
        "manifest_sha256": MANIFEST_SHA,
    }
    monkeypatch.setattr(candidate, "_plan_upgrade", lambda **kwargs: plan)
    config = tmp_path / "config.env"
    config.write_bytes(_valid_config())
    history = tmp_path / "history"
    common = {
        "source_version": 7,
        "source_candidate_sha": SOURCE_SHA,
        "target_sha": TARGET_SHA,
        "backup_id": BACKUP_ID,
        "config_file": config,
        "config_history_dir": history,
        "secret_dir": tmp_path / "secrets",
        "release_root": tmp_path / "releases",
        "release_record_dir": tmp_path / "records",
        "backup_root": tmp_path / "backups",
        "backup_record_dir": tmp_path / "backup-records",
        "restore_record_dir": tmp_path / "restore-records",
        "current_link": tmp_path / "current",
        "lock_file": tmp_path / "lock",
    }
    common["release_record_dir"].mkdir()
    (common["release_record_dir"] / f"{TARGET_SHA}.candidate-stage.json").write_text(
        "{}"
    )

    planned = candidate.activate_config(
        **common,
        apply=False,
        confirm_source_sha=None,
        confirm_target_sha=None,
        confirm_backup_id=None,
        confirm_manifest_sha256=None,
    )
    assert planned["config_changed"] is False
    assert config.read_bytes() == _valid_config()

    activation_path = (
        common["release_record_dir"] / f"{TARGET_SHA}.config-activation.json"
    )
    pending_path = (
        common["release_record_dir"]
        / f"{TARGET_SHA}.config-activation.pending.json"
    )
    original_writer = candidate._write_json_exclusive
    failed_once = False

    def fail_final_once(
        path: Path,
        payload: dict[str, object],
        mode: int = 0o644,
    ) -> None:
        nonlocal failed_once
        if path == activation_path and not failed_once:
            failed_once = True
            raise OSError("injected activation record failure")
        original_writer(path, payload, mode)

    monkeypatch.setattr(candidate, "_write_json_exclusive", fail_final_once)
    with pytest.raises(OSError, match="injected activation record failure"):
        candidate.activate_config(
            **common,
            apply=True,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_backup_id=BACKUP_ID,
            confirm_manifest_sha256=MANIFEST_SHA,
        )
    assert config.read_bytes() == _valid_config(TARGET_SHA, claims="true")
    assert pending_path.is_file()
    assert not activation_path.exists()

    applied = candidate.activate_config(
        **common,
        apply=True,
        confirm_source_sha=SOURCE_SHA,
        confirm_target_sha=TARGET_SHA,
        confirm_backup_id=BACKUP_ID,
        confirm_manifest_sha256=MANIFEST_SHA,
    )
    assert applied["passed"] is True
    assert config.read_bytes() == _valid_config(TARGET_SHA, claims="true")
    assert (history / f"{TARGET_SHA}.pre-activation.env").read_bytes() == _valid_config()
    assert activation_path.is_file()
    assert not pending_path.exists()

    completed = json.loads(activation_path.read_text(encoding="utf-8"))
    pending = {
        key: completed[key]
        for key in candidate.ACTIVATION_PENDING_KEYS
        if key != "record_type"
    }
    pending["record_type"] = "gatea-config-activation-pending"
    pending_path.write_text(json.dumps(pending), encoding="utf-8")

    replayed = candidate.activate_config(
        **common,
        apply=True,
        confirm_source_sha=SOURCE_SHA,
        confirm_target_sha=TARGET_SHA,
        confirm_backup_id=BACKUP_ID,
        confirm_manifest_sha256=MANIFEST_SHA,
    )

    assert replayed == completed
    assert not pending_path.exists()

    pending_path.write_text(json.dumps(pending), encoding="utf-8")
    config.write_bytes(_valid_config())

    with pytest.raises(
        candidate.GateACandidateError,
        match="completed config activation no longer matches",
    ):
        candidate.activate_config(
            **common,
            apply=True,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_backup_id=BACKUP_ID,
            confirm_manifest_sha256=MANIFEST_SHA,
        )

    assert config.read_bytes() == _valid_config()
    assert pending_path.exists()

    invalid_completed = {**completed, "unexpected": True}
    activation_path.write_text(json.dumps(invalid_completed), encoding="utf-8")
    with pytest.raises(candidate.GateACandidateError, match="journal is invalid"):
        candidate.activate_config(
            **common,
            apply=True,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_backup_id=BACKUP_ID,
            confirm_manifest_sha256=MANIFEST_SHA,
        )

    assert config.read_bytes() == _valid_config()
    assert pending_path.exists()


def test_activate_config_bad_confirmation_leaves_config_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_host_guards(monkeypatch)
    from scripts.release import gatea_backup, gatea_operations, gatea_upgrade

    monkeypatch.setattr(
        candidate,
        "_runtime_modules",
        lambda: (gatea_operations, gatea_backup, gatea_upgrade),
    )
    monkeypatch.setattr(
        candidate,
        "_load_stage",
        lambda **kwargs: {"image_id": IMAGE_ID, "ci_run_id": RUN_ID},
    )
    monkeypatch.setattr(
        candidate, "_read_current_target", lambda current, root: root / SOURCE_SHA
    )
    monkeypatch.setattr(
        candidate,
        "_plan_upgrade",
        lambda **kwargs: {
            "mode": "plan",
            "already_current": False,
            "candidate_sha": TARGET_SHA,
            "source_candidate_sha": SOURCE_SHA,
            "backup_id": BACKUP_ID,
            "source_version": 7,
            "restore_verified": True,
            "source_aerich_versions": M7_CHAIN,
            "target_aerich_versions": M9_CHAIN,
            "target_version": 9,
            "manifest_sha256": MANIFEST_SHA,
        },
    )
    config = tmp_path / "config.env"
    config.write_bytes(_valid_config())
    records = tmp_path / "records"
    records.mkdir()

    with pytest.raises(candidate.GateACandidateError, match="confirmations"):
        candidate.activate_config(
            source_version=7,
            source_candidate_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            backup_id=BACKUP_ID,
            apply=True,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_backup_id=BACKUP_ID,
            confirm_manifest_sha256="f" * 64,
            config_file=config,
            config_history_dir=tmp_path / "history",
            secret_dir=tmp_path / "secrets",
            release_root=tmp_path / "releases",
            release_record_dir=records,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            current_link=tmp_path / "current",
        )
    assert config.read_bytes() == _valid_config()


@pytest.mark.parametrize(
    "pending_suffix",
    (
        "candidate-stage.pending.json",
        "config-rollback.pending.json",
        "current-finalization.pending.json",
    ),
)
def test_activate_rejects_unresolved_conflicting_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pending_suffix: str
) -> None:
    _mock_host_guards(monkeypatch)
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    (record_dir / f"{TARGET_SHA}.{pending_suffix}").write_text("{}", encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError, match="conflicting pending"):
        candidate.activate_config(
            source_version=7,
            source_candidate_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            backup_id=BACKUP_ID,
            apply=False,
            confirm_source_sha=None,
            confirm_target_sha=None,
            confirm_backup_id=None,
            confirm_manifest_sha256=None,
            config_file=tmp_path / "config.env",
            config_history_dir=tmp_path / "history",
            secret_dir=tmp_path / "secrets",
            release_root=tmp_path / "releases",
            release_record_dir=record_dir,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            current_link=tmp_path / "current",
            lock_file=tmp_path / "lock",
        )


@pytest.mark.parametrize(
    "pending_suffix",
    (
        "candidate-stage.pending.json",
        "config-activation.pending.json",
        "current-finalization.pending.json",
    ),
)
def test_rollback_rejects_unresolved_predecessor_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pending_suffix: str
) -> None:
    _mock_host_guards(monkeypatch)
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    (record_dir / f"{TARGET_SHA}.{pending_suffix}").write_text("{}", encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError, match="predecessor pending"):
        candidate.rollback_config(
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_activation_record_sha256="a" * 64,
            config_file=tmp_path / "config.env",
            config_history_dir=tmp_path / "history",
            secret_dir=tmp_path / "secrets",
            release_root=tmp_path / "releases",
            release_record_dir=record_dir,
            current_link=tmp_path / "current",
            lock_file=tmp_path / "lock",
        )


@pytest.mark.parametrize(
    "pending_suffix",
    (
        "candidate-stage.pending.json",
        "config-activation.pending.json",
        "config-rollback.pending.json",
    ),
)
def test_finalize_rejects_unresolved_predecessor_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pending_suffix: str
) -> None:
    _mock_host_guards(monkeypatch)
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    (record_dir / f"{TARGET_SHA}.{pending_suffix}").write_text(
        "{}", encoding="utf-8"
    )

    with pytest.raises(candidate.GateACandidateError, match="predecessor pending"):
        candidate.finalize_candidate(
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            runtime_acceptance_record=tmp_path / "acceptance.json",
            runtime_acceptance_sha256="a" * 64,
            resilience_record=tmp_path / "resilience.json",
            resilience_sha256="b" * 64,
            post_backup_id=BACKUP_ID,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_post_backup_id=BACKUP_ID,
            config_file=tmp_path / "config.env",
            secret_dir=tmp_path / "secrets",
            release_root=tmp_path / "releases",
            release_record_dir=record_dir,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            current_link=tmp_path / "current",
            acceptance_record_dir=tmp_path,
            resilience_record_dir=tmp_path,
            lock_file=tmp_path / "lock",
        )


def test_finalize_rejects_acceptance_outside_guarded_directory_before_path_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mock_host_guards(monkeypatch)
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    monkeypatch.setattr(
        candidate,
        "_require_execution_release",
        lambda *args: pytest.fail(
            "acceptance directory binding must precede release path reads"
        ),
    )

    with pytest.raises(
        candidate.GateACandidateError,
        match="acceptance record must use the guarded directory",
    ):
        candidate.finalize_candidate(
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            runtime_acceptance_record=tmp_path / "outside" / "acceptance.json",
            runtime_acceptance_sha256="a" * 64,
            resilience_record=tmp_path / "resilience" / "resilience.json",
            resilience_sha256="b" * 64,
            post_backup_id=BACKUP_ID,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_post_backup_id=BACKUP_ID,
            config_file=tmp_path / "config.env",
            secret_dir=tmp_path / "secrets",
            release_root=tmp_path / "releases",
            release_record_dir=record_dir,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            current_link=tmp_path / "current",
            acceptance_record_dir=tmp_path / "guarded-acceptance",
            resilience_record_dir=tmp_path / "resilience",
            lock_file=tmp_path / "lock",
        )


def test_finalize_scans_acceptance_sidecars_before_release_or_evidence_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mock_host_guards(monkeypatch)
    record_dir = tmp_path / "records"
    acceptance_dir = tmp_path / "acceptance"
    resilience_dir = tmp_path / "resilience"
    for directory in (record_dir, acceptance_dir, resilience_dir):
        directory.mkdir()
    (acceptance_dir / (
        f"gatea-m9-runtime-acceptance-{'c' * 40}.json.pending"
    )).write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        candidate,
        "_reject_unresolved_transition_journals",
        REAL_TRANSITION_SCANNER,
    )
    monkeypatch.setattr(
        candidate,
        "_require_execution_release",
        lambda *args: pytest.fail(
            "acceptance sidecar scan must precede release path reads"
        ),
    )

    with pytest.raises(candidate.GateACandidateError, match="acceptance sidecar"):
        candidate.finalize_candidate(
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            runtime_acceptance_record=acceptance_dir / "acceptance.json",
            runtime_acceptance_sha256="a" * 64,
            resilience_record=resilience_dir / "resilience.json",
            resilience_sha256="b" * 64,
            post_backup_id=BACKUP_ID,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_post_backup_id=BACKUP_ID,
            config_file=tmp_path / "config.env",
            secret_dir=tmp_path / "secrets",
            release_root=tmp_path / "releases",
            release_record_dir=record_dir,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            current_link=tmp_path / "current",
            acceptance_record_dir=acceptance_dir,
            resilience_record_dir=resilience_dir,
            lock_file=tmp_path / "lock",
        )


def test_finalize_rejects_resilience_outside_guarded_directory_before_path_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mock_host_guards(monkeypatch)
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    acceptance_dir = tmp_path / "acceptance"
    resilience_dir = tmp_path / "resilience"
    monkeypatch.setattr(
        candidate,
        "_require_execution_release",
        lambda *args: pytest.fail(
            "resilience directory binding must precede release path reads"
        ),
    )

    with pytest.raises(
        candidate.GateACandidateError,
        match="resilience record must use the guarded directory",
    ):
        candidate.finalize_candidate(
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            runtime_acceptance_record=acceptance_dir / "acceptance.json",
            runtime_acceptance_sha256="a" * 64,
            resilience_record=tmp_path / "outside" / "resilience.json",
            resilience_sha256="b" * 64,
            post_backup_id=BACKUP_ID,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_post_backup_id=BACKUP_ID,
            config_file=tmp_path / "config.env",
            secret_dir=tmp_path / "secrets",
            release_root=tmp_path / "releases",
            release_record_dir=record_dir,
            backup_root=tmp_path / "backups",
            backup_record_dir=tmp_path / "backup-records",
            restore_record_dir=tmp_path / "restore-records",
            current_link=tmp_path / "current",
            acceptance_record_dir=acceptance_dir,
            resilience_record_dir=resilience_dir,
            lock_file=tmp_path / "lock",
        )


def test_transition_scanner_allows_exact_own_pending_and_absent_acceptance_dir(
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    own_pending = candidate._stage_pending_path(record_dir, TARGET_SHA)
    own_pending.write_text("{}", encoding="utf-8")
    acceptance_dir = tmp_path / "acceptance-not-created"

    REAL_TRANSITION_SCANNER(
        release_record_dir=record_dir,
        acceptance_record_dir=acceptance_dir,
        allowed_release_pending=own_pending,
    )

    assert not acceptance_dir.exists()


@pytest.mark.parametrize(
    "second_name",
    (
        f"{'c' * 40}.candidate-stage.pending.json",
        f"{'c' * 40}.config-activation.pending.json",
        f"{'c' * 40}.config-rollback.pending.json",
        f"{'c' * 40}.current-finalization.pending.json",
        f"{TARGET_SHA}.config-activation.pending.json",
    ),
)
def test_transition_scanner_rejects_own_pending_plus_any_second_transition(
    tmp_path: Path,
    second_name: str,
) -> None:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    own_pending = candidate._final_pending_path(record_dir, TARGET_SHA)
    own_pending.write_text("{}", encoding="utf-8")
    (record_dir / second_name).write_text("{}", encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError, match="unresolved"):
        REAL_TRANSITION_SCANNER(
            release_record_dir=record_dir,
            acceptance_record_dir=tmp_path / "acceptance-not-created",
            allowed_release_pending=own_pending,
        )


@pytest.mark.parametrize(
    "entry_kind",
    ("malformed-sha", "dangling-symlink", "directory", "fifo"),
)
def test_transition_scanner_rejects_malformed_or_nonregular_candidate_pending(
    tmp_path: Path,
    entry_kind: str,
) -> None:
    record_dir = tmp_path / "records"
    record_dir.mkdir()
    name = (
        "not-a-full-sha.candidate-stage.pending.json"
        if entry_kind == "malformed-sha"
        else f"{'c' * 40}.candidate-stage.pending.json"
    )
    path = record_dir / name
    if entry_kind == "dangling-symlink":
        path.symlink_to(record_dir / "missing")
    elif entry_kind == "directory":
        path.mkdir()
    elif entry_kind == "fifo":
        os.mkfifo(path)
    else:
        path.write_text("{}", encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError):
        REAL_TRANSITION_SCANNER(
            release_record_dir=record_dir,
            acceptance_record_dir=tmp_path / "acceptance-not-created",
        )


@pytest.mark.parametrize("sidecar_suffix", ("json.pending", "json.complete"))
def test_transition_scanner_rejects_every_acceptance_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sidecar_suffix: str,
) -> None:
    record_dir = tmp_path / "records"
    acceptance_dir = tmp_path / "acceptance-records"
    record_dir.mkdir()
    acceptance_dir.mkdir()
    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)
    sidecar = acceptance_dir / (
        f"gatea-m9-runtime-acceptance-{'c' * 40}.{sidecar_suffix}"
    )
    sidecar.write_text("{}", encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError, match="acceptance sidecar"):
        REAL_TRANSITION_SCANNER(
            release_record_dir=record_dir,
            acceptance_record_dir=acceptance_dir,
        )


def test_transition_scanner_rejects_malformed_acceptance_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "records"
    acceptance_dir = tmp_path / "acceptance-records"
    record_dir.mkdir()
    acceptance_dir.mkdir()
    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)
    (acceptance_dir / "gatea-m9-runtime-acceptance-short.json.complete").write_text(
        "{}", encoding="utf-8"
    )

    with pytest.raises(candidate.GateACandidateError, match="malformed"):
        REAL_TRANSITION_SCANNER(
            release_record_dir=record_dir,
            acceptance_record_dir=acceptance_dir,
        )


@pytest.mark.parametrize("dangling", (False, True))
def test_transition_scanner_rejects_symlink_acceptance_directory(
    tmp_path: Path,
    dangling: bool,
) -> None:
    record_dir = tmp_path / "records"
    target_dir = tmp_path / "acceptance-target"
    acceptance_dir = tmp_path / "acceptance-records"
    record_dir.mkdir()
    if not dangling:
        target_dir.mkdir()
    acceptance_dir.symlink_to(target_dir, target_is_directory=True)

    with pytest.raises(candidate.GateACandidateError, match="non-symlink"):
        REAL_TRANSITION_SCANNER(
            release_record_dir=record_dir,
            acceptance_record_dir=acceptance_dir,
        )


def test_transition_scanner_rejects_unsafe_acceptance_directory_metadata(
    tmp_path: Path,
) -> None:
    record_dir = tmp_path / "records"
    acceptance_dir = tmp_path / "acceptance-records"
    record_dir.mkdir()
    acceptance_dir.mkdir(mode=0o700)
    acceptance_dir.chmod(0o700)

    with pytest.raises(
        candidate.GateACandidateError,
        match="owned by root:root|unsafe permissions",
    ):
        REAL_TRANSITION_SCANNER(
            release_record_dir=record_dir,
            acceptance_record_dir=acceptance_dir,
        )


@pytest.mark.parametrize(
    "operation", ("stage", "activate", "activate-plan", "rollback", "finalize")
)
def test_each_candidate_mutation_scans_injected_acceptance_dir_inside_global_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: str,
) -> None:
    _mock_host_guards(monkeypatch)
    acceptance_dir = tmp_path / "acceptance-records"
    release_record_dir = tmp_path / "records"
    acceptance_dir.mkdir()
    release_record_dir.mkdir()
    in_lock = False

    @candidate.contextmanager
    def checked_lock(path: Path) -> object:
        del path
        nonlocal in_lock
        assert not in_lock
        in_lock = True
        try:
            yield
        finally:
            in_lock = False

    def stop_at_scanner(**kwargs: object) -> None:
        assert in_lock is True
        assert kwargs["acceptance_record_dir"] == acceptance_dir
        expected_allowed = {
            "stage": candidate._stage_pending_path(release_record_dir, TARGET_SHA),
            "activate": candidate._activation_pending_path(
                release_record_dir, TARGET_SHA
            ),
            "activate-plan": None,
            "rollback": candidate._rollback_pending_path(
                release_record_dir, TARGET_SHA
            ),
            "finalize": candidate._final_pending_path(
                release_record_dir, TARGET_SHA
            ),
        }[operation]
        assert kwargs["allowed_release_pending"] == expected_allowed
        raise candidate.GateACandidateError("scanner reached")

    monkeypatch.setattr(candidate, "_exclusive_lock", checked_lock)
    monkeypatch.setattr(
        candidate, "_reject_unresolved_transition_journals", stop_at_scanner
    )
    common = {
        "release_root": tmp_path / "releases",
        "release_record_dir": release_record_dir,
        "acceptance_record_dir": acceptance_dir,
        "lock_file": tmp_path / "lock",
    }

    with pytest.raises(candidate.GateACandidateError, match="scanner reached"):
        if operation == "stage":
            candidate.stage_candidate(
                source_archive=tmp_path / "source.tar",
                source_archive_sha256="1" * 64,
                ci_artifact=tmp_path / "ci.zip",
                ci_artifact_sha256="2" * 64,
                launcher=tmp_path / "candidate.py",
                launcher_sha256="3" * 64,
                target_sha=TARGET_SHA,
                source_head_sha=HEAD_SHA,
                ci_run_id=RUN_ID,
                ci_run_attempt=ATTEMPT,
                ci_artifact_name=ARTIFACT_NAME,
                confirmed_required_jobs=9,
                staging_root=tmp_path / "staging",
                **common,
            )
        elif operation in {"activate", "activate-plan"}:
            is_apply = operation == "activate"
            candidate.activate_config(
                source_version=7,
                source_candidate_sha=SOURCE_SHA,
                target_sha=TARGET_SHA,
                backup_id=BACKUP_ID,
                apply=is_apply,
                confirm_source_sha=SOURCE_SHA if is_apply else None,
                confirm_target_sha=TARGET_SHA if is_apply else None,
                confirm_backup_id=BACKUP_ID if is_apply else None,
                confirm_manifest_sha256=MANIFEST_SHA if is_apply else None,
                config_file=tmp_path / "config.env",
                config_history_dir=tmp_path / "history",
                secret_dir=tmp_path / "secrets",
                backup_root=tmp_path / "backups",
                backup_record_dir=tmp_path / "backup-records",
                restore_record_dir=tmp_path / "restore-records",
                current_link=tmp_path / "current",
                **common,
            )
        elif operation == "rollback":
            candidate.rollback_config(
                source_sha=SOURCE_SHA,
                target_sha=TARGET_SHA,
                confirm_source_sha=SOURCE_SHA,
                confirm_target_sha=TARGET_SHA,
                confirm_activation_record_sha256="4" * 64,
                config_file=tmp_path / "config.env",
                config_history_dir=tmp_path / "history",
                secret_dir=tmp_path / "secrets",
                current_link=tmp_path / "current",
                **common,
            )
        else:
            candidate.finalize_candidate(
                source_sha=SOURCE_SHA,
                target_sha=TARGET_SHA,
                runtime_acceptance_record=tmp_path / "acceptance.json",
                runtime_acceptance_sha256="5" * 64,
                resilience_record=tmp_path / "resilience.json",
                resilience_sha256="6" * 64,
                post_backup_id=BACKUP_ID,
                confirm_source_sha=SOURCE_SHA,
                confirm_target_sha=TARGET_SHA,
                confirm_post_backup_id=BACKUP_ID,
                config_file=tmp_path / "config.env",
                secret_dir=tmp_path / "secrets",
                backup_root=tmp_path / "backups",
                backup_record_dir=tmp_path / "backup-records",
                restore_record_dir=tmp_path / "restore-records",
                current_link=tmp_path / "current",
                **common,
            )


def test_upgrade_plan_replay_record_is_bound_to_upgrade_and_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    upgrade_path = tmp_path / "upgrade.json"
    evidence_path = tmp_path / "upgrade.evidence.json"
    replay_path = tmp_path / "replay.json"
    upgrade_path.write_text("{}")
    evidence_path.write_text('{"status":"succeeded"}')
    database_snapshot: dict[str, object] = {"aerich_versions": M9_CHAIN}
    image_manifest: dict[str, object] = {"files": 221, "sha256": "3" * 64}
    upgrade_record = {
        "backup_id": BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "evidence_sha256": candidate._sha256(evidence_path),
        "final_database_snapshot": database_snapshot,
        "final_image_manifest": image_manifest,
        "table_reconcile": EMPTY_TABLE_RECONCILE,
    }
    payload = _upgrade_replay_payload(
        upgrade_path=upgrade_path,
        evidence_path=evidence_path,
        database_snapshot=database_snapshot,
        image_manifest=image_manifest,
    )
    replay_path.write_text(json.dumps(payload))
    fake_gatea = SimpleNamespace(
        APPROVED_TARGET_M7_CHAIN=tuple(M7_CHAIN),
        APPROVED_TARGET_M9_CHAIN=tuple(M9_CHAIN),
    )
    fake_upgrade = SimpleNamespace(
        _validate_empty_table_reconcile_result=lambda value: None
    )

    assert candidate._validate_upgrade_replay_record(
        path=replay_path,
        source_sha=SOURCE_SHA,
        target_sha=TARGET_SHA,
        image_id=IMAGE_ID,
        upgrade_path=upgrade_path,
        upgrade_record=upgrade_record,
        evidence_path=evidence_path,
        gatea=fake_gatea,
        upgrade=fake_upgrade,
    ) == payload

    payload["database_snapshot"] = {"aerich_versions": M7_CHAIN}
    replay_path.write_text(json.dumps(payload))
    with pytest.raises(candidate.GateACandidateError, match="plan-replay record"):
        candidate._validate_upgrade_replay_record(
            path=replay_path,
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            upgrade_path=upgrade_path,
            upgrade_record=upgrade_record,
            evidence_path=evidence_path,
            gatea=fake_gatea,
            upgrade=fake_upgrade,
        )


def test_post_backup_requires_comma_delimited_m9_aerich_versions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts.release import gatea_backup

    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    backup_root = tmp_path / "backups"
    backup_record_dir = tmp_path / "backup-records"
    restore_record_dir = tmp_path / "restore-records"
    for directory in (backup_root, backup_record_dir, restore_record_dir):
        directory.mkdir()
    backup_path = backup_record_dir / f"{BACKUP_ID}.json"
    restore_path = restore_record_dir / f"{BACKUP_ID}.json"
    m7_snapshot = {
        "schema_version": 1,
        "profile": "m7-preserved-business-v1",
        "content_sha256": "1" * 64,
    }
    m9_snapshot = {
        "schema_version": 1,
        "profile": "m9-table-business-v1",
        "content_sha256": "2" * 64,
    }
    backup_payload: dict[str, object] = {
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "candidate_sha": TARGET_SHA,
        "image_id": IMAGE_ID,
        "started_at": "2026-09-10T12:00:00+00:00",
        "completed_at": "2026-09-10T12:01:00+00:00",
        "database_snapshot": {"aerich_versions": ",".join(M9_CHAIN)},
        "m7_content_snapshot": m7_snapshot,
        "m9_table_content_snapshot": m9_snapshot,
        "artifacts": {
            "mysql": {"sha256": "3" * 64},
            "images": {"sha256": "4" * 64},
        },
        "redis_recovery_policy": "start-empty-and-invalidate-refresh-sessions",
        "application_restarted": True,
        "table_sweeper_restarted": True,
        "passed": True,
    }
    restore_payload: dict[str, object] = {
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "restore_project": gatea_backup.restore_project(BACKUP_ID),
        "candidate_sha": TARGET_SHA,
        "mysql_artifact_sha256": "3" * 64,
        "image_artifact_sha256": "4" * 64,
        "started_at": "2026-09-10T12:02:00+00:00",
        "completed_at": "2026-09-10T12:03:00+00:00",
        "host_ports_published": False,
        "m7_content_matches": True,
        "m9_table_content_matches": True,
        "m7_content_snapshot": m7_snapshot,
        "m9_table_content_snapshot": m9_snapshot,
        "database_matches": True,
        "images_match": True,
        "restore_app_ready": True,
        "redis_started_empty": True,
        "refresh_sessions_invalidated": True,
        "temporary_resources_removed": True,
        "passed": True,
    }

    def write_records() -> None:
        backup_path.write_text(json.dumps(backup_payload), encoding="utf-8")
        restore_payload["backup_record_sha256"] = candidate._sha256(backup_path)
        restore_path.write_text(json.dumps(restore_payload), encoding="utf-8")

    fake_gatea = SimpleNamespace(APPROVED_TARGET_M9_CHAIN=tuple(M9_CHAIN))
    fake_backup = SimpleNamespace(
        _load_backup_record=lambda **kwargs: (
            json.loads(backup_path.read_text(encoding="utf-8")),
            tmp_path / "database.sql.gz",
            tmp_path / "images.tar.gz",
        ),
        _validate_m7_content_snapshot=gatea_backup._validate_m7_content_snapshot,
        _validate_m9_table_content_snapshot=(
            gatea_backup._validate_m9_table_content_snapshot
        ),
        restore_project=gatea_backup.restore_project,
    )
    monkeypatch.setattr(
        candidate, "_runtime_modules", lambda: (fake_gatea, fake_backup, object())
    )

    write_records()
    backup, _, _, _ = candidate._validate_post_backup(
        backup_id=BACKUP_ID,
        target_sha=TARGET_SHA,
        image_id=IMAGE_ID,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
    )
    assert backup["database_snapshot"] == {
        "aerich_versions": ",".join(M9_CHAIN)
    }

    backup_payload["database_snapshot"] = {"aerich_versions": M9_CHAIN}
    write_records()
    with pytest.raises(candidate.GateACandidateError, match="backup/restore record"):
        candidate._validate_post_backup(
            backup_id=BACKUP_ID,
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
            restore_record_dir=restore_record_dir,
        )

    backup_payload["database_snapshot"] = {
        "aerich_versions": ",".join(M9_CHAIN)
    }
    backup_payload["started_at"] = "2026-09-10T12:01:01+00:00"
    write_records()
    with pytest.raises(candidate.GateACandidateError, match="backup/restore record"):
        candidate._validate_post_backup(
            backup_id=BACKUP_ID,
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
            restore_record_dir=restore_record_dir,
        )


def test_acceptance_record_contract_is_candidate_image_and_redaction_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts.release import gatea_m9_acceptance

    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    monkeypatch.setattr(
        gatea_m9_acceptance, "_validate_success_record", lambda payload: None
    )
    record = tmp_path / "acceptance.json"
    payload = {
        "schema_version": 1,
        "record_type": "gatea-m9-runtime-acceptance",
        "source_candidate_sha": SOURCE_SHA,
        "candidate_sha": TARGET_SHA,
        "image_id": IMAGE_ID,
        "operations_sha": TARGET_SHA,
        "ci_run_id": RUN_ID,
        "upgrade_record_sha256": "1" * 64,
        "upgrade_plan_replay_record_sha256": "2" * 64,
        "runtime_services": list(candidate.M9_RUNTIME_SERVICES),
        **{field: True for field in candidate.ACCEPTANCE_REQUIRED_TRUE_FIELDS},
        **{field: False for field in candidate.ACCEPTANCE_REQUIRED_FALSE_FIELDS},
    }
    record.write_text(json.dumps(payload))
    digest = candidate._sha256(record)

    assert candidate._validate_acceptance_record(
        record,
        expected_sha256=digest,
        source_sha=SOURCE_SHA,
        target_sha=TARGET_SHA,
        image_id=IMAGE_ID,
        ci_run_id=RUN_ID,
        upgrade_record_sha256="1" * 64,
        upgrade_replay_record_sha256="2" * 64,
    ) == payload

    payload["table_tokens_recorded"] = True
    record.write_text(json.dumps(payload))
    with pytest.raises(candidate.GateACandidateError, match="invalid"):
        candidate._validate_acceptance_record(
            record,
            expected_sha256=candidate._sha256(record),
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            ci_run_id=RUN_ID,
            upgrade_record_sha256="1" * 64,
            upgrade_replay_record_sha256="2" * 64,
        )


@pytest.mark.parametrize("sidecar_suffix", ("pending", "complete"))
def test_acceptance_record_rejects_adjacent_publication_sidecar_before_loading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sidecar_suffix: str,
) -> None:
    record = tmp_path / f"gatea-m9-runtime-acceptance-{TARGET_SHA}.json"
    record.write_text("{}", encoding="utf-8")
    Path(f"{record}.{sidecar_suffix}").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)

    with pytest.raises(candidate.GateACandidateError, match="sidecar"):
        candidate._validate_acceptance_record(
            record,
            expected_sha256=candidate._sha256(record),
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            ci_run_id=RUN_ID,
            upgrade_record_sha256="1" * 64,
            upgrade_replay_record_sha256="2" * 64,
        )


def test_final_live_recheck_matches_backup_and_reconciliation_evidence() -> None:
    database_snapshot = {"aerich_versions": ",".join(M9_CHAIN)}
    m7_snapshot = {
        "schema_version": 1,
        "profile": "m7-preserved-business-v1",
        "content_sha256": "a" * 64,
    }
    m9_snapshot = {
        "schema_version": 1,
        "profile": "m9-table-business-v1",
        "content_sha256": "b" * 64,
    }
    images = ["1" * 64 + " product/a.png", "2" * 64 + " product/b.png"]
    table_reconcile = {**EMPTY_TABLE_RECONCILE, "scanned": 1}
    wallet_reconcile = {"scanned": 12, "mismatches": 0, "violations": 0}
    fake_backup = SimpleNamespace(
        _source_snapshot=lambda *args: database_snapshot,
        _source_m7_content_snapshot=lambda *args: m7_snapshot,
        _source_m9_table_content_snapshot=lambda *args: m9_snapshot,
        _source_image_manifest=lambda *args: images,
    )
    fake_gatea = SimpleNamespace(
        _run_m9_table_reconcile=lambda **kwargs: table_reconcile,
        _run_compose=lambda **kwargs: SimpleNamespace(
            stdout=json.dumps(wallet_reconcile)
        ),
        validate_app_image=lambda values: IMAGE_ID,
    )
    backup_record = {
        "database_snapshot": database_snapshot,
        "m7_content_snapshot": m7_snapshot,
        "m9_table_content_snapshot": m9_snapshot,
        "image_manifest": images,
    }
    acceptance_record = {
        "post_reconcile": table_reconcile,
        "post_wallet_reconcile": wallet_reconcile,
    }

    result = candidate._final_live_recheck(
        gatea=fake_gatea,
        backup_module=fake_backup,
        values={"GATEA_APP_IMAGE": "candidate"},
        config_file=Path("config.env"),
        secret_dir=Path("secrets"),
        image_id=IMAGE_ID,
        backup_record=backup_record,
        acceptance_record=acceptance_record,
    )

    assert result["database_snapshot"] == database_snapshot
    assert result["m7_content_snapshot"] == m7_snapshot
    assert result["m9_table_content_snapshot"] == m9_snapshot
    assert result["image_file_count"] == 2
    assert result["table_reconcile"] == table_reconcile
    assert result["wallet_reconcile"] == wallet_reconcile

    backup_record["image_manifest"] = [images[0]]
    with pytest.raises(candidate.GateACandidateError, match="live state differs"):
        candidate._final_live_recheck(
            gatea=fake_gatea,
            backup_module=fake_backup,
            values={"GATEA_APP_IMAGE": "candidate"},
            config_file=Path("config.env"),
            secret_dir=Path("secrets"),
            image_id=IMAGE_ID,
            backup_record=backup_record,
            acceptance_record=acceptance_record,
        )


def _resilience_payload() -> dict[str, object]:
    rotation = {
        service: {"driver": "json-file", "max_file": "5", "max_size": "10m"}
        for service in candidate.M9_RUNTIME_SERVICES
    }
    return {
        "schema_version": 2,
        "candidate_sha": TARGET_SHA,
        "image_id": IMAGE_ID,
        "representative_candidate_sha": SOURCE_SHA,
        "representative_image_id": "sha256:source-image",
        "representative_record_sha256": "a" * 64,
        "runtime_acceptance_record_sha256": ACCEPTANCE_RECORD_SHA256,
        "runtime_acceptance_attempt_id_sha256": ACCEPTANCE_ATTEMPT_ID_SHA256,
        "runtime_acceptance_completed_at": ACCEPTANCE_COMPLETED_AT,
        "started_at": "2026-09-10T12:00:00+00:00",
        "completed_at": "2026-09-10T12:03:00+00:00",
        "dependency_drills": [
            {
                "service": service,
                "started_at": "2026-09-10T12:00:00+00:00",
                "completed_at": "2026-09-10T12:01:00+00:00",
                "outage_readiness_status": 503,
                "outage_liveness_status": 200,
                "failure_detection_seconds": 0.1,
                "service_recovery_seconds": 0.2,
                "readiness_recovery_seconds": 0.3,
                "recovered_readiness_status": 200,
                "passed": True,
            }
            for service in ("mysql", "redis")
        ],
        "app_restart": {
            "started_at": "2026-09-10T12:02:00+00:00",
            "completed_at": "2026-09-10T12:03:00+00:00",
            "total_seconds": 0.4,
            "service_recovery_seconds": 0.2,
            "readiness_recovery_seconds": 0.2,
            "readiness_status": 200,
            "passed": True,
        },
        "database_snapshot_unchanged": True,
        "database_content_snapshots": {
            "m7_preserved_business": {
                "schema_version": 1,
                "profile": "m7-preserved-business-v1",
                "content_sha256": "b" * 64,
            },
            "m9_table_business": {
                "schema_version": 1,
                "profile": "m9-table-business-v1",
                "content_sha256": "c" * 64,
            },
        },
        "database_content_snapshots_unchanged": True,
        "image_manifest_unchanged": True,
        "image_file_count": 226,
        "source_services_healthy": True,
        "runtime_services": list(candidate.M9_RUNTIME_SERVICES),
        "table_sweeper_included": True,
        "loopback_only": True,
        "log_rotation": rotation,
        "log_observability": {
            "window": "24h",
            "combined_line_count": 20,
            "nginx_request_count": 10,
            "nginx_4xx_count": 0,
            "nginx_5xx_count": 0,
            "request_time_seconds": {"median": 0.01, "p95": 0.02, "max": 0.03},
            "exact_secret_matches": 0,
            "forbidden_pattern_matches": 0,
            "raw_log_content_recorded": False,
            "passed": True,
        },
        "pii_recorded": False,
        "secret_values_recorded": False,
        "passed": True,
    }


def test_resilience_record_is_bound_to_the_upgrade_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    record = tmp_path / "resilience.json"
    payload = _resilience_payload()
    record.write_text(json.dumps(payload), encoding="utf-8")

    assert candidate._validate_resilience_record(
        record,
        expected_sha256=candidate._sha256(record),
        source_sha=SOURCE_SHA,
        source_image_id="sha256:source-image",
        target_sha=TARGET_SHA,
        image_id=IMAGE_ID,
        runtime_acceptance_record_sha256=ACCEPTANCE_RECORD_SHA256,
        runtime_acceptance_attempt_id_sha256=ACCEPTANCE_ATTEMPT_ID_SHA256,
        runtime_acceptance_completed_at=ACCEPTANCE_COMPLETED_AT,
    ) == payload

    payload["representative_candidate_sha"] = "f" * 40
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(candidate.GateACandidateError, match="invalid"):
        candidate._validate_resilience_record(
            record,
            expected_sha256=candidate._sha256(record),
            source_sha=SOURCE_SHA,
            source_image_id="sha256:source-image",
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            runtime_acceptance_record_sha256=ACCEPTANCE_RECORD_SHA256,
            runtime_acceptance_attempt_id_sha256=ACCEPTANCE_ATTEMPT_ID_SHA256,
            runtime_acceptance_completed_at=ACCEPTANCE_COMPLETED_AT,
        )

    payload["representative_candidate_sha"] = SOURCE_SHA
    payload["representative_image_id"] = "sha256:wrong-source-image"
    record.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(candidate.GateACandidateError, match="invalid"):
        candidate._validate_resilience_record(
            record,
            expected_sha256=candidate._sha256(record),
            source_sha=SOURCE_SHA,
            source_image_id="sha256:source-image",
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            runtime_acceptance_record_sha256=ACCEPTANCE_RECORD_SHA256,
            runtime_acceptance_attempt_id_sha256=ACCEPTANCE_ATTEMPT_ID_SHA256,
            runtime_acceptance_completed_at=ACCEPTANCE_COMPLETED_AT,
        )


def test_resilience_record_rejects_unsettled_writer_alias_before_consumption(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    record = tmp_path / "resilience.json"
    payload = _resilience_payload()
    record.write_text(json.dumps(payload), encoding="utf-8")
    temporary = tmp_path / f".{record.name}.tmp-publication"
    os.link(record, temporary)

    with pytest.raises(
        candidate.GateACandidateError,
        match="publication is not settled",
    ):
        candidate._validate_resilience_record(
            record,
            record_dir=tmp_path,
            expected_sha256=candidate._sha256(record),
            source_sha=SOURCE_SHA,
            source_image_id="sha256:source-image",
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            runtime_acceptance_record_sha256=ACCEPTANCE_RECORD_SHA256,
            runtime_acceptance_attempt_id_sha256=ACCEPTANCE_ATTEMPT_ID_SHA256,
            runtime_acceptance_completed_at=ACCEPTANCE_COMPLETED_AT,
        )

    assert temporary.exists()
    assert record.stat().st_nlink == 2


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("schema_version", 1),
        ("runtime_acceptance_record_sha256", "6" * 64),
        ("runtime_acceptance_attempt_id_sha256", "7" * 64),
        ("runtime_acceptance_completed_at", "2026-09-10T11:58:00+00:00"),
    ),
)
def test_resilience_v2_rejects_legacy_or_changed_acceptance_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    record = tmp_path / "resilience.json"
    payload = _resilience_payload()
    payload[field] = replacement
    record.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError, match="invalid"):
        candidate._validate_resilience_record(
            record,
            expected_sha256=candidate._sha256(record),
            source_sha=SOURCE_SHA,
            source_image_id="sha256:source-image",
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            runtime_acceptance_record_sha256=ACCEPTANCE_RECORD_SHA256,
            runtime_acceptance_attempt_id_sha256=ACCEPTANCE_ATTEMPT_ID_SHA256,
            runtime_acceptance_completed_at=ACCEPTANCE_COMPLETED_AT,
        )


def test_resilience_v2_rejects_another_acceptance_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    record = tmp_path / "resilience.json"
    payload = _resilience_payload()
    record.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError, match="invalid"):
        candidate._validate_resilience_record(
            record,
            expected_sha256=candidate._sha256(record),
            source_sha=SOURCE_SHA,
            source_image_id="sha256:source-image",
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            runtime_acceptance_record_sha256="8" * 64,
            runtime_acceptance_attempt_id_sha256=ACCEPTANCE_ATTEMPT_ID_SHA256,
            runtime_acceptance_completed_at=ACCEPTANCE_COMPLETED_AT,
        )


def test_rollback_refuses_after_upgrade_evidence_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_host_guards(monkeypatch)
    monkeypatch.setattr(candidate, "_require_execution_release", lambda *args: None)
    monkeypatch.setattr(
        candidate, "_read_current_target", lambda current, root: root / SOURCE_SHA
    )
    record_dir = tmp_path / "records"
    history_dir = tmp_path / "history"
    record_dir.mkdir()
    history_dir.mkdir()
    config = tmp_path / "config.env"
    config.write_bytes(_valid_config(TARGET_SHA, claims="true"))
    history = history_dir / f"{TARGET_SHA}.pre-activation.env"
    history.write_bytes(_valid_config())
    stage_path = record_dir / f"{TARGET_SHA}.candidate-stage.json"
    stage_path.write_text("{}")
    activation = {
        "schema_version": 1,
        "record_type": "gatea-config-activation",
        "passed": True,
        "source_candidate_sha": SOURCE_SHA,
        "candidate_sha": TARGET_SHA,
        "image_id": IMAGE_ID,
        "backup_id": BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "source_config_sha256": candidate._sha256(history),
        "target_config_sha256": candidate._sha256(config),
        "changed_keys": ["GATEA_APP_IMAGE", "TABLE_SESSION_CLAIMS_ENABLED"],
        "history_path": str(history),
        "stage_record_sha256": candidate._sha256(stage_path),
        "started_at": "2026-09-10T11:00:00+00:00",
        "completed_at": "2026-09-10T11:00:01+00:00",
        "config_values_recorded": False,
        "secret_values_recorded": False,
    }
    activation_path = record_dir / f"{TARGET_SHA}.config-activation.json"
    activation_path.write_text(json.dumps(activation))
    (record_dir / f"{TARGET_SHA}.existing-database-upgrade.evidence.json").write_text("{}")

    with pytest.raises(candidate.GateACandidateError, match="upgrade has started"):
        candidate.rollback_config(
            source_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            confirm_source_sha=SOURCE_SHA,
            confirm_target_sha=TARGET_SHA,
            confirm_activation_record_sha256=candidate._sha256(activation_path),
            config_file=config,
            config_history_dir=history_dir,
            secret_dir=tmp_path / "secrets",
            release_root=tmp_path / "releases",
            release_record_dir=record_dir,
            current_link=tmp_path / "current",
        )


def test_rollback_recovers_after_config_restore_before_final_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_host_guards(monkeypatch)
    gatea = SimpleNamespace(
        APPROVED_TARGET_M7_CHAIN=tuple(M7_CHAIN),
        _validated_inputs=lambda **kwargs: {},
        read_database_snapshot=lambda **kwargs: {"aerich_versions": M7_CHAIN},
        _compose_ps=lambda **kwargs: [],
        _ensure_services_healthy=lambda *args, **kwargs: None,
    )
    upgrade = SimpleNamespace(_ensure_not_running=lambda *args, **kwargs: None)
    monkeypatch.setattr(
        candidate,
        "_runtime_modules",
        lambda: (gatea, SimpleNamespace(), upgrade),
    )
    monkeypatch.setattr(
        candidate,
        "_read_current_target",
        lambda current, release_root: release_root / SOURCE_SHA,
    )

    record_dir = tmp_path / "records"
    history_dir = tmp_path / "history"
    record_dir.mkdir()
    history_dir.mkdir()
    config = tmp_path / "config.env"
    source_config = _valid_config()
    target_config = _valid_config(TARGET_SHA, claims="true")
    config.write_bytes(target_config)
    history = history_dir / f"{TARGET_SHA}.pre-activation.env"
    history.write_bytes(source_config)
    stage_path = record_dir / f"{TARGET_SHA}.candidate-stage.json"
    stage_path.write_text("{}", encoding="utf-8")
    activation = {
        "schema_version": 1,
        "record_type": "gatea-config-activation",
        "passed": True,
        "source_candidate_sha": SOURCE_SHA,
        "candidate_sha": TARGET_SHA,
        "image_id": IMAGE_ID,
        "backup_id": BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "source_config_sha256": candidate._sha256_bytes(source_config),
        "target_config_sha256": candidate._sha256_bytes(target_config),
        "changed_keys": ["GATEA_APP_IMAGE", "TABLE_SESSION_CLAIMS_ENABLED"],
        "history_path": str(history),
        "stage_record_sha256": candidate._sha256(stage_path),
        "started_at": "2026-09-10T11:00:00+00:00",
        "completed_at": "2026-09-10T11:00:01+00:00",
        "config_values_recorded": False,
        "secret_values_recorded": False,
    }
    activation_path = record_dir / f"{TARGET_SHA}.config-activation.json"
    activation_path.write_text(json.dumps(activation), encoding="utf-8")
    rollback_path = record_dir / f"{TARGET_SHA}.config-rollback.json"
    pending_path = record_dir / f"{TARGET_SHA}.config-rollback.pending.json"
    original_writer = candidate._write_json_exclusive
    failed_once = False

    def fail_final_once(
        path: Path,
        payload: dict[str, object],
        mode: int = 0o644,
    ) -> None:
        nonlocal failed_once
        if path == rollback_path and not failed_once:
            failed_once = True
            raise OSError("injected rollback record failure")
        original_writer(path, payload, mode)

    monkeypatch.setattr(candidate, "_write_json_exclusive", fail_final_once)
    arguments = {
        "source_sha": SOURCE_SHA,
        "target_sha": TARGET_SHA,
        "confirm_source_sha": SOURCE_SHA,
        "confirm_target_sha": TARGET_SHA,
        "confirm_activation_record_sha256": candidate._sha256(activation_path),
        "config_file": config,
        "config_history_dir": history_dir,
        "secret_dir": tmp_path / "secrets",
        "release_root": tmp_path / "releases",
        "release_record_dir": record_dir,
        "current_link": tmp_path / "current",
        "lock_file": tmp_path / "lock",
    }

    with pytest.raises(OSError, match="injected rollback record failure"):
        candidate.rollback_config(**arguments)
    assert config.read_bytes() == source_config
    assert pending_path.is_file()
    assert stat.S_IMODE(pending_path.stat().st_mode) == 0o600
    assert not rollback_path.exists()

    result = candidate.rollback_config(**arguments)

    assert result["passed"] is True
    assert config.read_bytes() == source_config
    assert rollback_path.is_file()
    assert not pending_path.exists()

    completed = json.loads(rollback_path.read_text(encoding="utf-8"))
    pending = {
        key: completed[key]
        for key in candidate.ROLLBACK_PENDING_KEYS
        if key != "record_type"
    }
    pending["record_type"] = "gatea-config-rollback-pending"
    pending_path.write_text(json.dumps(pending), encoding="utf-8")

    replayed = candidate.rollback_config(**arguments)

    assert replayed == completed
    assert not pending_path.exists()

    pending_path.write_text(json.dumps(pending), encoding="utf-8")
    config.write_bytes(target_config)

    with pytest.raises(
        candidate.GateACandidateError,
        match="completed config rollback no longer matches",
    ):
        candidate.rollback_config(**arguments)

    assert config.read_bytes() == target_config
    assert pending_path.exists()

    rollback_path.write_text(
        json.dumps({**completed, "unexpected": True}), encoding="utf-8"
    )
    with pytest.raises(candidate.GateACandidateError, match="journal is invalid"):
        candidate.rollback_config(**arguments)

    assert config.read_bytes() == target_config
    assert pending_path.exists()


@pytest.mark.parametrize(
    (
        "resilience_representative_sha256",
        "proofs_match",
        "failure_point",
    ),
    [
        pytest.param(
            "a" * 64,
            True,
            None,
            id="matching-source-evidence",
        ),
        pytest.param(
            "a" * 64,
            True,
            "final-record",
            id="resume-after-final-record-failure",
        ),
        pytest.param(
            "a" * 64,
            True,
            "current-phase",
            id="resume-after-current-switch",
        ),
        pytest.param(
            "b" * 64,
            False,
            None,
            id="mismatched-source-evidence",
        ),
    ],
)
def test_finalize_switches_current_only_when_source_evidence_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    resilience_representative_sha256: str,
    proofs_match: bool,
    failure_point: str | None,
) -> None:
    _mock_host_guards(monkeypatch)
    release_root = tmp_path / "releases"
    record_dir = tmp_path / "records"
    backup_records = tmp_path / "backup-records"
    restore_records = tmp_path / "restore-records"
    for directory in (release_root, record_dir, backup_records, restore_records):
        directory.mkdir()
    source_release = release_root / SOURCE_SHA
    target_release = release_root / TARGET_SHA
    source_release.mkdir()
    target_release.mkdir()
    current = tmp_path / "current"
    current.symlink_to(source_release)
    monkeypatch.setattr(candidate.os, "chown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        candidate,
        "_load_stage",
        lambda **kwargs: {"image_id": IMAGE_ID, "ci_run_id": RUN_ID},
    )
    monkeypatch.setattr(
        candidate,
        "_read_current_target",
        lambda link, root: link.resolve(),
    )

    config = tmp_path / "config.env"
    config.write_bytes(_valid_config(TARGET_SHA, claims="true"))
    stage_path = record_dir / f"{TARGET_SHA}.candidate-stage.json"
    stage_path.write_text("{}", encoding="utf-8")
    activation_path = record_dir / f"{TARGET_SHA}.config-activation.json"
    activation_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "record_type": "gatea-config-activation",
                "passed": True,
                "source_candidate_sha": SOURCE_SHA,
                "candidate_sha": TARGET_SHA,
                "image_id": IMAGE_ID,
                "backup_id": PRE_BACKUP_ID,
                "manifest_sha256": MANIFEST_SHA,
                "source_config_sha256": "a" * 64,
                "target_config_sha256": candidate._sha256(config),
                "changed_keys": [
                    "GATEA_APP_IMAGE",
                    "TABLE_SESSION_CLAIMS_ENABLED",
                ],
                "history_path": str(tmp_path / "history.env"),
                "stage_record_sha256": candidate._sha256(stage_path),
                "started_at": "2026-09-10T11:00:00+00:00",
                "completed_at": "2026-09-10T11:00:01+00:00",
                "config_values_recorded": False,
                "secret_values_recorded": False,
            }
        )
    )
    upgrade_path = record_dir / f"{TARGET_SHA}.existing-database-upgrade.json"
    upgrade_path.write_text("{}")
    evidence_path = (
        record_dir / f"{TARGET_SHA}.existing-database-upgrade.evidence.json"
    )
    evidence_path.write_text('{"status":"succeeded"}')
    database_snapshot: dict[str, object] = {"aerich_versions": M9_CHAIN}
    image_manifest: dict[str, object] = {"files": 221, "sha256": "3" * 64}
    upgrade_record = {
        "source_candidate_sha": SOURCE_SHA,
        "source_image_id": "sha256:source-image",
        "source_version": 7,
        "backup_id": PRE_BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "target_aerich_versions": M9_CHAIN,
        "evidence_sha256": candidate._sha256(evidence_path),
        "final_database_snapshot": database_snapshot,
        "final_image_manifest": image_manifest,
        "table_reconcile": EMPTY_TABLE_RECONCILE,
    }
    replay_path = record_dir / f"{TARGET_SHA}.upgrade-plan-replay.json"
    replay_path.write_text(
        json.dumps(
            _upgrade_replay_payload(
                upgrade_path=upgrade_path,
                evidence_path=evidence_path,
                database_snapshot=database_snapshot,
                image_manifest=image_manifest,
                backup_id=PRE_BACKUP_ID,
            )
        )
    )
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text("{}")
    resilience = tmp_path / "resilience.json"
    resilience.write_text("{}")
    backup_path = backup_records / f"{BACKUP_ID}.json"
    restore_path = restore_records / f"{BACKUP_ID}.json"
    backup_path.write_text("{}")
    restore_path.write_text("{}")

    fake_gatea = SimpleNamespace(
        APPROVED_TARGET_M7_CHAIN=tuple(M7_CHAIN),
        APPROVED_TARGET_M9_CHAIN=tuple(M9_CHAIN),
        CandidateTransitionRecoveryAllowance=(
            gatea_operations.CandidateTransitionRecoveryAllowance
        ),
        _validated_inputs=lambda **kwargs: {
            "GATEA_APP_IMAGE": f"pinkdoohub-gatea:{TARGET_SHA}",
            "GATEA_LOOPBACK_PORT": "18080",
        },
        _candidate_sha=lambda values: TARGET_SHA,
        validate_app_image=lambda values: IMAGE_ID,
        _require_upgrade_record=lambda **kwargs: upgrade_record,
        read_database_snapshot=lambda **kwargs: {"aerich_versions": M9_CHAIN},
        _compose_ps=lambda **kwargs: [],
        _ensure_services_healthy=lambda *args: None,
        _validate_loopback_publishers=lambda *args: None,
    )
    fake_upgrade = SimpleNamespace(
        _validate_empty_table_reconcile_result=lambda value: None
    )
    monkeypatch.setattr(
        candidate, "_runtime_modules", lambda: (fake_gatea, object(), fake_upgrade)
    )
    monkeypatch.setattr(
        candidate,
        "_validate_acceptance_record",
        lambda *args, **kwargs: {
            "started_at": "2026-09-10T12:01:00+00:00",
            "completed_at": "2026-09-10T12:02:00+00:00",
            "representative_record_sha256": "a" * 64,
            "post_reconcile": EMPTY_TABLE_RECONCILE,
            "post_wallet_reconcile": {
                "scanned": 11,
                "mismatches": 0,
                "violations": 0,
            },
        },
    )
    monkeypatch.setattr(
        candidate,
        "_validate_resilience_record",
        lambda *args, **kwargs: {
            "started_at": "2026-09-10T12:02:30+00:00",
            "completed_at": "2026-09-10T12:03:00+00:00",
            "representative_record_sha256": resilience_representative_sha256,
            "database_content_snapshots": {
                "m7_preserved_business": {
                    "schema_version": 1,
                    "profile": "m7-preserved-business-v1",
                    "content_sha256": "b" * 64,
                },
                "m9_table_business": {
                    "schema_version": 1,
                    "profile": "m9-table-business-v1",
                    "content_sha256": "c" * 64,
                },
            },
            "image_file_count": 2,
        },
    )
    monkeypatch.setattr(
        candidate,
        "_validate_post_backup",
        lambda **kwargs: (
            {
                "started_at": "2026-09-10T12:04:00+00:00",
                "completed_at": "2026-09-10T12:05:00+00:00",
                "database_snapshot": {
                    "aerich_versions": ",".join(M9_CHAIN)
                },
                "m7_content_snapshot": {
                    "schema_version": 1,
                    "profile": "m7-preserved-business-v1",
                    "content_sha256": "b" * 64,
                },
                "m9_table_content_snapshot": {
                    "schema_version": 1,
                    "profile": "m9-table-business-v1",
                    "content_sha256": "c" * 64,
                },
                "image_manifest": ["fixture-1", "fixture-2"],
            },
            {"started_at": "2026-09-10T12:06:00+00:00"},
            backup_path,
            restore_path,
        ),
    )
    finalization_events: list[str] = []
    monkeypatch.setattr(
        candidate,
        "_stop_finalization_writers",
        lambda **kwargs: finalization_events.append("writers-stopped"),
    )
    live_state_changed_after_cutover = False
    live_recheck_calls = 0

    def final_live_recheck(**kwargs: object) -> dict[str, object]:
        nonlocal live_recheck_calls
        live_recheck_calls += 1
        if live_state_changed_after_cutover:
            pytest.fail(
                "finalization recovery must not compare post-cutover writes "
                "with the older backup"
            )
        return {
            "database_snapshot": {"aerich_versions": ",".join(M9_CHAIN)},
            "m7_content_snapshot": {
                "schema_version": 1,
                "profile": "m7-preserved-business-v1",
                "content_sha256": "b" * 64,
            },
            "m9_table_content_snapshot": {
                "schema_version": 1,
                "profile": "m9-table-business-v1",
                "content_sha256": "c" * 64,
            },
            "image_manifest_sha256": candidate._sha256_bytes(
                b"fixture-1\nfixture-2\n"
            ),
            "image_file_count": 2,
            "table_reconcile": EMPTY_TABLE_RECONCILE,
            "wallet_reconcile": {
                "scanned": 11,
                "mismatches": 0,
                "violations": 0,
            },
            "checked_at": "2026-09-10T12:07:00+00:00",
        }

    monkeypatch.setattr(
        candidate,
        "_final_live_recheck",
        final_live_recheck,
    )
    monkeypatch.setattr(
        candidate,
        "_restore_finalization_runtime",
        lambda **kwargs: finalization_events.append("runtime-restored"),
    )

    finalize_args = {
        "source_sha": SOURCE_SHA,
        "target_sha": TARGET_SHA,
        "runtime_acceptance_record": acceptance,
        "runtime_acceptance_sha256": candidate._sha256(acceptance),
        "resilience_record": resilience,
        "resilience_sha256": candidate._sha256(resilience),
        "post_backup_id": BACKUP_ID,
        "confirm_source_sha": SOURCE_SHA,
        "confirm_target_sha": TARGET_SHA,
        "confirm_post_backup_id": BACKUP_ID,
        "config_file": config,
        "secret_dir": tmp_path / "secrets",
        "release_root": release_root,
        "release_record_dir": record_dir,
        "backup_root": tmp_path / "backups",
        "backup_record_dir": backup_records,
        "restore_record_dir": restore_records,
        "current_link": current,
        "acceptance_record_dir": tmp_path,
        "resilience_record_dir": tmp_path,
        "lock_file": tmp_path / "lock",
    }
    final_path = record_dir / f"{TARGET_SHA}.current-finalization.json"
    pending_path = record_dir / f"{TARGET_SHA}.current-finalization.pending.json"

    if not proofs_match:
        with pytest.raises(candidate.GateACandidateError, match="source evidence differ"):
            candidate.finalize_candidate(**finalize_args)
        assert current.resolve() == source_release
        assert not final_path.exists()
        assert not pending_path.exists()
        return

    if failure_point == "final-record":
        original_writer = candidate._write_json_exclusive
        failure_injected = False

        def fail_final_record_once(
            path: Path,
            payload: dict[str, object],
            mode: int = 0o644,
        ) -> None:
            nonlocal failure_injected
            if path == final_path and not failure_injected:
                failure_injected = True
                raise OSError("injected final record failure")
            original_writer(path, payload, mode)

        monkeypatch.setattr(candidate, "_write_json_exclusive", fail_final_record_once)
        with pytest.raises(OSError, match="injected final record failure"):
            candidate.finalize_candidate(**finalize_args)
    elif failure_point == "current-phase":
        original_atomic_writer = candidate._atomic_replace_json
        failure_injected = False

        def fail_current_phase_once(
            path: Path,
            payload: dict[str, object],
            mode: int,
        ) -> None:
            nonlocal failure_injected
            if (
                path == pending_path
                and payload.get("phase") == "current-switched"
                and not failure_injected
            ):
                failure_injected = True
                raise OSError("injected current phase failure")
            original_atomic_writer(path, payload, mode)

        monkeypatch.setattr(candidate, "_atomic_replace_json", fail_current_phase_once)
        with pytest.raises(OSError, match="injected current phase failure"):
            candidate.finalize_candidate(**finalize_args)

    if failure_point is not None:
        assert current.resolve() == target_release
        assert pending_path.is_file()
        assert not final_path.exists()
        live_state_changed_after_cutover = True

    result = candidate.finalize_candidate(**finalize_args)

    assert result["passed"] is True
    assert result["phase"] == "runtime-restored"
    assert current.resolve() == target_release
    assert final_path.is_file()
    assert not pending_path.exists()
    assert live_recheck_calls == 1
    expected_events = ["writers-stopped", "runtime-restored"]
    if failure_point is not None:
        expected_events.append("runtime-restored")
    assert finalization_events == expected_events


def _build_signal_finalization_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> SimpleNamespace:
    _mock_host_guards(monkeypatch)
    release_root = tmp_path / "releases"
    record_dir = tmp_path / "records"
    backup_records = tmp_path / "backup-records"
    restore_records = tmp_path / "restore-records"
    for directory in (release_root, record_dir, backup_records, restore_records):
        directory.mkdir()
    source_release = release_root / SOURCE_SHA
    target_release = release_root / TARGET_SHA
    source_release.mkdir()
    target_release.mkdir()
    current = tmp_path / "current"
    current.symlink_to(source_release)
    monkeypatch.setattr(candidate.os, "chown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        candidate,
        "_load_stage",
        lambda **kwargs: {"image_id": IMAGE_ID, "ci_run_id": RUN_ID},
    )
    monkeypatch.setattr(
        candidate,
        "_read_current_target",
        lambda link, root: link.resolve(),
    )

    config = tmp_path / "config.env"
    config.write_bytes(_valid_config(TARGET_SHA, claims="true"))
    stage_path = record_dir / f"{TARGET_SHA}.candidate-stage.json"
    stage_path.write_text("{}", encoding="utf-8")
    activation_path = record_dir / f"{TARGET_SHA}.config-activation.json"
    activation_payload = {
        "backup_id": PRE_BACKUP_ID,
        "history_path": str(tmp_path / "history.env"),
        "target_config_sha256": candidate._sha256(config),
        "manifest_sha256": MANIFEST_SHA,
    }
    activation_path.write_text(json.dumps(activation_payload), encoding="utf-8")
    monkeypatch.setattr(
        candidate,
        "_validate_activation_journal",
        lambda payload, **kwargs: dict(activation_payload),
    )

    upgrade_path = record_dir / f"{TARGET_SHA}.existing-database-upgrade.json"
    upgrade_path.write_text("{}", encoding="utf-8")
    replay_path = record_dir / f"{TARGET_SHA}.upgrade-plan-replay.json"
    replay_path.write_text("{}", encoding="utf-8")
    upgrade_record = {
        "source_candidate_sha": SOURCE_SHA,
        "source_image_id": "sha256:source-image",
        "source_version": 7,
        "backup_id": PRE_BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "target_aerich_versions": M9_CHAIN,
    }
    monkeypatch.setattr(
        candidate,
        "_validate_upgrade_replay_record",
        lambda **kwargs: {"completed_at": "2026-09-10T12:00:00+00:00"},
    )

    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text("{}", encoding="utf-8")
    acceptance_payload = {
        "started_at": "2026-09-10T12:01:00+00:00",
        "completed_at": "2026-09-10T12:02:00+00:00",
        "attempt_id_sha256": ACCEPTANCE_ATTEMPT_ID_SHA256,
        "representative_record_sha256": "a" * 64,
        "post_reconcile": EMPTY_TABLE_RECONCILE,
        "post_wallet_reconcile": {
            "scanned": 11,
            "mismatches": 0,
            "violations": 0,
        },
    }
    resilience = tmp_path / "resilience.json"
    resilience.write_text("{}", encoding="utf-8")
    m7_snapshot = {
        "schema_version": 1,
        "profile": "m7-preserved-business-v1",
        "content_sha256": "b" * 64,
    }
    m9_snapshot = {
        "schema_version": 1,
        "profile": "m9-table-business-v1",
        "content_sha256": "c" * 64,
    }
    resilience_payload = {
        "started_at": "2026-09-10T12:02:30+00:00",
        "completed_at": "2026-09-10T12:03:00+00:00",
        "representative_record_sha256": "a" * 64,
        "database_content_snapshots": {
            "m7_preserved_business": m7_snapshot,
            "m9_table_business": m9_snapshot,
        },
        "image_file_count": 2,
    }
    monkeypatch.setattr(
        candidate,
        "_validate_acceptance_record",
        lambda *args, **kwargs: dict(acceptance_payload),
    )
    monkeypatch.setattr(
        candidate,
        "_validate_resilience_record",
        lambda *args, **kwargs: dict(resilience_payload),
    )

    backup_path = backup_records / f"{BACKUP_ID}.json"
    restore_path = restore_records / f"{BACKUP_ID}.json"
    backup_path.write_text("{}", encoding="utf-8")
    restore_path.write_text("{}", encoding="utf-8")
    backup_payload = {
        "started_at": "2026-09-10T12:04:00+00:00",
        "completed_at": "2026-09-10T12:05:00+00:00",
        "database_snapshot": {"aerich_versions": M9_CHAIN},
        "m7_content_snapshot": m7_snapshot,
        "m9_table_content_snapshot": m9_snapshot,
        "image_manifest": ["fixture-1", "fixture-2"],
    }
    monkeypatch.setattr(
        candidate,
        "_validate_post_backup",
        lambda **kwargs: (
            dict(backup_payload),
            {"started_at": "2026-09-10T12:06:00+00:00"},
            backup_path,
            restore_path,
        ),
    )

    state = SimpleNamespace(
        force_unhealthy=False,
        stop_hook=None,
        restore_hook=None,
        live_hook=None,
        stop_calls=0,
        restore_calls=0,
        live_calls=0,
    )

    def ensure_healthy(*args: object) -> None:
        del args
        if state.force_unhealthy:
            state.force_unhealthy = False
            raise candidate.GateACandidateError("injected unhealthy runtime")

    fake_gatea = SimpleNamespace(
        APPROVED_TARGET_M9_CHAIN=tuple(M9_CHAIN),
        CandidateTransitionRecoveryAllowance=(
            gatea_operations.CandidateTransitionRecoveryAllowance
        ),
        _validated_inputs=lambda **kwargs: {
            "GATEA_APP_IMAGE": f"pinkdoohub-gatea:{TARGET_SHA}",
            "GATEA_LOOPBACK_PORT": "18080",
        },
        _candidate_sha=lambda values: TARGET_SHA,
        validate_app_image=lambda values: IMAGE_ID,
        _require_upgrade_record=lambda **kwargs: dict(upgrade_record),
        read_database_snapshot=lambda **kwargs: {"aerich_versions": M9_CHAIN},
        _compose_ps=lambda **kwargs: [],
        _ensure_services_healthy=ensure_healthy,
        _validate_loopback_publishers=lambda *args: None,
    )
    monkeypatch.setattr(
        candidate,
        "_runtime_modules",
        lambda: (fake_gatea, object(), object()),
    )

    def stop_writers(**kwargs: object) -> None:
        del kwargs
        state.stop_calls += 1
        if state.stop_hook is not None:
            state.stop_hook()

    def restore_runtime(**kwargs: object) -> None:
        del kwargs
        state.restore_calls += 1
        if state.restore_hook is not None:
            state.restore_hook()

    live_payload = {
        "database_snapshot": backup_payload["database_snapshot"],
        "m7_content_snapshot": m7_snapshot,
        "m9_table_content_snapshot": m9_snapshot,
        "image_manifest_sha256": candidate._sha256_bytes(
            b"fixture-1\nfixture-2\n"
        ),
        "image_file_count": 2,
        "table_reconcile": EMPTY_TABLE_RECONCILE,
        "wallet_reconcile": acceptance_payload["post_wallet_reconcile"],
        "checked_at": "2026-09-10T12:07:00+00:00",
    }

    def live_recheck(**kwargs: object) -> dict[str, object]:
        del kwargs
        state.live_calls += 1
        if state.live_hook is not None:
            return state.live_hook()
        return copy.deepcopy(live_payload)

    monkeypatch.setattr(candidate, "_stop_finalization_writers", stop_writers)
    monkeypatch.setattr(candidate, "_restore_finalization_runtime", restore_runtime)
    monkeypatch.setattr(candidate, "_final_live_recheck", live_recheck)

    finalize_args = {
        "source_sha": SOURCE_SHA,
        "target_sha": TARGET_SHA,
        "runtime_acceptance_record": acceptance,
        "runtime_acceptance_sha256": candidate._sha256(acceptance),
        "resilience_record": resilience,
        "resilience_sha256": candidate._sha256(resilience),
        "post_backup_id": BACKUP_ID,
        "confirm_source_sha": SOURCE_SHA,
        "confirm_target_sha": TARGET_SHA,
        "confirm_post_backup_id": BACKUP_ID,
        "config_file": config,
        "secret_dir": tmp_path / "secrets",
        "release_root": release_root,
        "release_record_dir": record_dir,
        "backup_root": tmp_path / "backups",
        "backup_record_dir": backup_records,
        "restore_record_dir": restore_records,
        "current_link": current,
        "acceptance_record_dir": tmp_path,
        "resilience_record_dir": tmp_path,
        "lock_file": tmp_path / "lock",
    }
    return SimpleNamespace(
        args=finalize_args,
        state=state,
        current=current,
        source_release=source_release,
        target_release=target_release,
        pending_path=record_dir
        / f"{TARGET_SHA}.current-finalization.pending.json",
        final_path=record_dir / f"{TARGET_SHA}.current-finalization.json",
    )


@pytest.mark.parametrize("drift", ("content", "pending", "complete"))
def test_finalize_rechecks_acceptance_immediately_before_first_pending_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
) -> None:
    case = _build_signal_finalization_case(monkeypatch, tmp_path)
    acceptance_path = case.args["runtime_acceptance_record"]
    assert isinstance(acceptance_path, Path)
    validated_acceptance = candidate._validate_acceptance_record

    def validate_then_drift(*args: object, **kwargs: object) -> dict[str, object]:
        payload = validated_acceptance(*args, **kwargs)
        if drift == "content":
            acceptance_path.write_text('{"changed":true}', encoding="utf-8")
        else:
            Path(f"{acceptance_path}.{drift}").write_text("{}", encoding="utf-8")
        return payload

    monkeypatch.setattr(candidate, "_validate_acceptance_record", validate_then_drift)

    with pytest.raises(
        candidate.GateACandidateError,
        match="digest does not match|sidecar",
    ):
        candidate.finalize_candidate(**case.args)

    assert case.current.resolve() == case.source_release
    assert not case.pending_path.exists()
    assert not case.final_path.exists()
    assert case.state.stop_calls == 0
    assert case.state.restore_calls == 0


def test_finalize_passes_exact_structured_allowance_only_for_validated_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _build_signal_finalization_case(monkeypatch, tmp_path)
    restore_runtime = candidate._restore_finalization_runtime
    seen: list[object] = []

    def capture_allowance(**kwargs: object) -> None:
        seen.append(kwargs.get("candidate_transition_recovery"))
        restore_runtime(**kwargs)

    monkeypatch.setattr(candidate, "_restore_finalization_runtime", capture_allowance)

    result = candidate.finalize_candidate(**case.args)

    assert result["passed"] is True
    assert len(seen) == 1
    allowance = seen[0]
    assert isinstance(
        allowance, gatea_operations.CandidateTransitionRecoveryAllowance
    )
    assert allowance.path == case.pending_path
    assert allowance.kind == "current-finalization"
    assert allowance.candidate_sha == TARGET_SHA


def test_finalize_resume_rejects_own_pending_when_second_transition_appears(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _build_signal_finalization_case(monkeypatch, tmp_path)
    monkeypatch.setattr(
        candidate, "_reject_unresolved_transition_journals", REAL_TRANSITION_SCANNER
    )
    original_atomic_writer = candidate._atomic_replace_json
    injected = False

    def fail_current_phase_once(
        path: Path,
        payload: dict[str, object],
        mode: int,
    ) -> None:
        nonlocal injected
        if (
            path == case.pending_path
            and payload.get("phase") == "current-switched"
            and not injected
        ):
            injected = True
            raise OSError("injected current-phase crash")
        original_atomic_writer(path, payload, mode)

    monkeypatch.setattr(candidate, "_atomic_replace_json", fail_current_phase_once)
    with pytest.raises(OSError, match="current-phase crash"):
        candidate.finalize_candidate(**case.args)
    assert case.pending_path.is_file()

    second = case.pending_path.parent / (
        f"{'c' * 40}.config-activation.pending.json"
    )
    second.write_text("{}", encoding="utf-8")
    with pytest.raises(candidate.GateACandidateError, match="unresolved"):
        candidate.finalize_candidate(**case.args)

    assert case.pending_path.is_file()
    assert second.is_file()
    assert not case.final_path.exists()


def test_pending_target_resume_defers_repeated_signals_until_final_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    case = _build_signal_finalization_case(monkeypatch, tmp_path)
    original_atomic_writer = candidate._atomic_replace_json
    current_phase_failed = False

    def fail_current_phase_once(
        path: Path,
        payload: dict[str, object],
        mode: int,
    ) -> None:
        nonlocal current_phase_failed
        if (
            path == case.pending_path
            and payload.get("phase") == "current-switched"
            and not current_phase_failed
        ):
            current_phase_failed = True
            raise OSError("injected current phase failure")
        original_atomic_writer(path, payload, mode)

    monkeypatch.setattr(candidate, "_atomic_replace_json", fail_current_phase_once)
    with pytest.raises(OSError, match="injected current phase failure"):
        candidate.finalize_candidate(**case.args)

    assert case.current.resolve() == case.target_release
    assert case.pending_path.is_file()
    assert not case.final_path.exists()
    assert case.state.restore_calls == 1
    monkeypatch.setattr(candidate, "_atomic_replace_json", original_atomic_writer)

    def signal_during_resume_recovery() -> None:
        for signum in (signal.SIGTERM, signal.SIGHUP):
            assert callable(active[signum])
            assert active[signum](signum, None) is None  # type: ignore[operator]

    case.state.restore_hook = signal_during_resume_recovery
    with pytest.raises(
        candidate.GateACandidateOperationInterrupted,
        match="received SIGTERM",
    ):
        candidate.finalize_candidate(**case.args)

    assert case.state.restore_calls == 2
    assert case.final_path.is_file()
    assert not case.pending_path.exists()
    case.state.restore_hook = None
    result = candidate.finalize_candidate(**case.args)
    assert result["passed"] is True


def test_existing_final_repair_recovers_after_work_signal_and_defers_next_signal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    active, _, _ = _capture_candidate_signal_handlers(monkeypatch)
    case = _build_signal_finalization_case(monkeypatch, tmp_path)
    first = candidate.finalize_candidate(**case.args)
    assert first["passed"] is True

    def signal_while_stopping() -> None:
        assert callable(active[signal.SIGTERM])
        active[signal.SIGTERM](signal.SIGTERM, None)  # type: ignore[operator]

    def signal_during_recovery() -> None:
        assert callable(active[signal.SIGHUP])
        assert (
            active[signal.SIGHUP](  # type: ignore[operator]
                signal.SIGHUP, None
            )
            is None
        )

    case.state.force_unhealthy = True
    case.state.stop_hook = signal_while_stopping
    case.state.restore_hook = signal_during_recovery
    with pytest.raises(
        candidate.GateACandidateOperationInterrupted,
        match="received SIGTERM",
    ):
        candidate.finalize_candidate(**case.args)

    assert case.state.stop_calls == 2
    assert case.state.restore_calls == 2
    assert case.final_path.is_file()
    case.state.stop_hook = None
    case.state.restore_hook = None
    replay = candidate.finalize_candidate(**case.args)
    assert replay == first


def test_new_finalization_exception_restores_runtime_before_propagating_original(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _capture_candidate_signal_handlers(monkeypatch)
    case = _build_signal_finalization_case(monkeypatch, tmp_path)
    operation_error = OSError("injected live recheck failure")

    def fail_live_recheck() -> dict[str, object]:
        raise operation_error

    case.state.live_hook = fail_live_recheck
    with pytest.raises(OSError) as caught:
        candidate.finalize_candidate(**case.args)

    assert caught.value is operation_error
    assert case.current.resolve() == case.source_release
    assert case.pending_path.is_file()
    assert not case.final_path.exists()
    assert case.state.restore_calls == 1
    case.state.live_hook = None
    result = candidate.finalize_candidate(**case.args)
    assert result["passed"] is True
    assert case.state.restore_calls == 2


def test_restore_finalization_runtime_uses_only_explicit_recovery_allowance_and_checks_services(
) -> None:
    calls: list[tuple[str, object]] = []

    def app_up(**kwargs: object) -> None:
        calls.append(("app-up", dict(kwargs)))

    def compose_ps(**kwargs: object) -> list[dict[str, object]]:
        assert kwargs["start_new_session"] is True
        calls.append(("compose-ps", tuple(kwargs["services"])))
        return []

    def ensure_healthy(rows: object, *services: str) -> None:
        calls.append(("healthy", services))

    fake_gatea = SimpleNamespace(
        app_up=app_up,
        _compose_ps=compose_ps,
        _ensure_services_healthy=ensure_healthy,
        _validate_loopback_publishers=lambda rows, port: calls.append(
            ("publishers", port)
        ),
    )

    candidate._restore_finalization_runtime(
        gatea=fake_gatea,
        values={"GATEA_LOOPBACK_PORT": "18080"},
        config_file=Path("config"),
        secret_dir=Path("secrets"),
        release_record_dir=Path("records"),
    )

    app_up_kwargs = calls[0][1]
    assert isinstance(app_up_kwargs, dict)
    assert "candidate_transition_recovery" not in app_up_kwargs
    assert app_up_kwargs["allow_existing_gatea_publisher"] is True
    assert app_up_kwargs["_start_new_session"] is True
    assert ("compose-ps", candidate.M9_RUNTIME_SERVICES) in calls
    assert ("healthy", candidate.M9_RUNTIME_SERVICES) in calls
    assert ("publishers", 18080) in calls

    calls.clear()
    allowance = gatea_operations.CandidateTransitionRecoveryAllowance(
        path=Path("records") / f"{TARGET_SHA}.current-finalization.pending.json",
        kind="current-finalization",
        candidate_sha=TARGET_SHA,
    )
    candidate._restore_finalization_runtime(
        gatea=fake_gatea,
        values={"GATEA_LOOPBACK_PORT": "18080"},
        config_file=Path("config"),
        secret_dir=Path("secrets"),
        release_record_dir=Path("records"),
        candidate_transition_recovery=allowance,
    )
    app_up_kwargs = calls[0][1]
    assert isinstance(app_up_kwargs, dict)
    assert app_up_kwargs["candidate_transition_recovery"] is allowance
    assert app_up_kwargs["allow_existing_gatea_publisher"] is True
    assert app_up_kwargs["_start_new_session"] is True


def test_current_switched_replay_reuses_already_restored_loopback_publisher(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_restore_runtime = candidate._restore_finalization_runtime
    case = _build_signal_finalization_case(monkeypatch, tmp_path)
    fake_gatea, _, _ = candidate._runtime_modules()
    publisher_running = False
    app_up_calls: list[bool] = []

    def stop_existing_publisher() -> None:
        nonlocal publisher_running
        publisher_running = False

    case.state.stop_hook = stop_existing_publisher

    def app_up(**kwargs: object) -> None:
        nonlocal publisher_running
        allow_existing = kwargs.get("allow_existing_gatea_publisher") is True
        app_up_calls.append(allow_existing)
        if publisher_running and not allow_existing:
            raise gatea_operations.GateAError(
                "Gate A loopback port is already in use"
            )
        publisher_running = True
        case.state.restore_calls += 1

    fake_gatea.app_up = app_up
    monkeypatch.setattr(
        candidate,
        "_restore_finalization_runtime",
        real_restore_runtime,
    )
    original_atomic_writer = candidate._atomic_replace_json
    failed_after_restore = False

    def fail_first_runtime_restored_write(
        path: Path,
        payload: dict[str, object],
        mode: int,
    ) -> None:
        nonlocal failed_after_restore
        if (
            path == case.pending_path
            and payload.get("phase") == "runtime-restored"
            and not failed_after_restore
        ):
            failed_after_restore = True
            raise OSError("injected post-restore journal failure")
        original_atomic_writer(path, payload, mode)

    monkeypatch.setattr(
        candidate,
        "_atomic_replace_json",
        fail_first_runtime_restored_write,
    )
    with pytest.raises(OSError, match="post-restore journal failure"):
        candidate.finalize_candidate(**case.args)

    assert publisher_running is True
    assert case.current.resolve() == case.target_release
    pending = json.loads(case.pending_path.read_text(encoding="utf-8"))
    assert pending["phase"] == "current-switched"
    assert not case.final_path.exists()

    monkeypatch.setattr(candidate, "_atomic_replace_json", original_atomic_writer)
    result = candidate.finalize_candidate(**case.args)

    assert result["passed"] is True
    assert case.final_path.is_file()
    assert not case.pending_path.exists()
    assert app_up_calls == [True, True]


def test_cli_requires_apply_for_stage_and_finalization(capsys: pytest.CaptureFixture[str]) -> None:
    status = candidate.main(
        [
            "stage",
            "--source-archive",
            "/missing/source.tar",
            "--confirm-source-archive-sha256",
            "a" * 64,
            "--ci-artifact",
            "/missing/artifact.zip",
            "--confirm-ci-artifact-sha256",
            "b" * 64,
            "--confirm-launcher-sha256",
            "c" * 64,
            "--target-sha",
            TARGET_SHA,
            "--source-head-sha",
            HEAD_SHA,
            "--ci-run-id",
            RUN_ID,
            "--ci-run-attempt",
            "1",
            "--ci-artifact-name",
            f"gatea-m7-m9-updater-{TARGET_SHA}-{RUN_ID}-1",
            "--confirm-required-jobs",
            "9",
            "--confirm-target-sha",
            TARGET_SHA,
        ]
    )
    assert status == 1
    assert "requires --apply" in capsys.readouterr().err


def test_finalize_cli_forwards_guarded_acceptance_and_resilience_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        candidate,
        "finalize_candidate",
        lambda **kwargs: calls.append(kwargs) or {"passed": True},
    )
    acceptance_dir = tmp_path / "acceptance"
    resilience_dir = tmp_path / "resilience"

    status = candidate.main(
        [
            "finalize",
            "--source-sha",
            SOURCE_SHA,
            "--target-sha",
            TARGET_SHA,
            "--runtime-acceptance-record",
            str(acceptance_dir / "acceptance.json"),
            "--confirm-runtime-acceptance-sha256",
            "a" * 64,
            "--acceptance-record-dir",
            str(acceptance_dir),
            "--resilience-record",
            str(resilience_dir / "resilience.json"),
            "--confirm-resilience-record-sha256",
            "b" * 64,
            "--resilience-record-dir",
            str(resilience_dir),
            "--post-backup-id",
            BACKUP_ID,
            "--confirm-source-sha",
            SOURCE_SHA,
            "--confirm-target-sha",
            TARGET_SHA,
            "--confirm-post-backup-id",
            BACKUP_ID,
            "--apply",
        ]
    )

    assert status == 0
    assert len(calls) == 1
    assert calls[0]["acceptance_record_dir"] == acceptance_dir
    assert calls[0]["resilience_record_dir"] == resilience_dir
