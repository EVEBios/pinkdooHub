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
import textwrap
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


def test_finalization_ordinary_work_error_wins_over_deferred_recovery_sigint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_candidate_signal_handlers(monkeypatch)
    work_failure = RuntimeError("injected work failure")
    recovery_interruption = KeyboardInterrupt("injected recovery interruption")
    restore_calls = 0

    def fail_work() -> None:
        raise work_failure

    def restore(**kwargs: object) -> None:
        nonlocal restore_calls
        del kwargs
        restore_calls += 1
        if restore_calls == 1:
            raise recovery_interruption

    monkeypatch.setattr(candidate, "_restore_finalization_runtime", restore)

    with pytest.raises(RuntimeError) as caught:
        with candidate._mutation_termination_controller("finalize") as termination:
            _, work_error = candidate._run_finalization_work_then_restore(
                termination=termination,
                work=fail_work,
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

            assert work_error is work_failure
            assert termination.recovery_interruption is recovery_interruption
            assert propagated is work_failure
            raise propagated

    assert caught.value is work_failure
    assert restore_calls == 2


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


def test_plan_upgrade_forwards_both_guarded_takeover_archive_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeUpgrade:
        @staticmethod
        def upgrade_existing_database(**kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {"mode": "plan"}

    monkeypatch.setattr(
        candidate,
        "_runtime_modules",
        lambda: (SimpleNamespace(), SimpleNamespace(), FakeUpgrade),
    )
    acceptance_archive_dir = tmp_path / "acceptance-failures"
    retirement_archive_dir = tmp_path / "retirement-failures"

    assert candidate._plan_upgrade(
        config_file=tmp_path / "candidate.env",
        secret_dir=tmp_path / "secrets",
        source_version=9,
        source_candidate_sha="a" * 40,
        backup_id=BACKUP_ID,
        backup_root=tmp_path / "backups",
        backup_record_dir=tmp_path / "backup-records",
        restore_record_dir=tmp_path / "restore-records",
        release_record_dir=tmp_path / "release-records",
        lineage_source_candidate_sha=SOURCE_SHA,
        acceptance_retirement_record_sha256="f" * 64,
        acceptance_failure_archive_dir=acceptance_archive_dir,
        retirement_failure_archive_dir=retirement_archive_dir,
    ) == {"mode": "plan"}

    assert len(calls) == 1
    assert calls[0]["acceptance_failure_archive_dir"] == acceptance_archive_dir
    assert calls[0]["retirement_failure_archive_dir"] == retirement_archive_dir
    assert calls[0]["lineage_source_candidate_sha"] == SOURCE_SHA
    assert calls[0]["acceptance_retirement_record_sha256"] == "f" * 64


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


def test_stage_writes_schema3_prepared_retirement_takeover_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mock_host_guards(monkeypatch)
    release_root = tmp_path / "releases"
    staging_root = tmp_path / "staging"
    record_dir = tmp_path / "records"
    acceptance_dir = tmp_path / "acceptance"
    acceptance_archive_dir = tmp_path / "acceptance-failures"
    retirement_archive_dir = tmp_path / "retirement-failures"
    for directory in (
        release_root,
        staging_root,
        record_dir,
        acceptance_dir,
    ):
        directory.mkdir()
    launcher = tmp_path / "launcher.py"
    launcher.write_bytes(b"candidate launcher\n")
    source = tmp_path / "source.tar"
    _write_source_tar(source, members=_source_members(launcher.read_bytes()))
    artifact = tmp_path / "artifact.zip"
    _write_ci_zip(artifact)
    source_candidate_sha = "a" * 40
    superseded_retirement_candidate_sha = "c" * 40
    failed_acceptance_sha256 = "f" * 64
    superseded_stage_sha256 = "1" * 64
    superseded_pending_sha256 = "2" * 64
    scanner_calls: list[dict[str, object]] = []
    takeover_calls: list[dict[str, object]] = []
    failed_acceptance = {"candidate_sha": source_candidate_sha}

    def scan(**kwargs: object) -> dict[str, object]:
        scanner_calls.append(kwargs)
        return failed_acceptance

    def validate_takeover(**kwargs: object) -> dict[str, object]:
        takeover_calls.append(kwargs)
        assert kwargs["failed_acceptance"] is failed_acceptance
        assert kwargs["require_unarchived"] is True
        return {}

    monkeypatch.setattr(candidate, "_reject_unresolved_transition_journals", scan)
    monkeypatch.setattr(
        candidate, "_validate_prepared_retirement_takeover", validate_takeover
    )
    monkeypatch.setattr(
        candidate,
        "_verified_stage_operations",
        lambda **kwargs: nullcontext(SimpleNamespace()),
    )
    monkeypatch.setattr(
        candidate,
        "_verify_github_provenance",
        lambda **kwargs: _github_stage_evidence(artifact),
    )
    images: set[str] = set()
    commands: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        del kwargs
        commands.append(command)
        if command[:2] == ("docker", "build"):
            images.add(command[command.index("--tag") + 1])
        elif command[:3] == ("docker", "image", "tag"):
            images.add(command[4])
        elif command[:3] == ("docker", "image", "rm"):
            images.discard(command[3])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

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
    monkeypatch.setattr(candidate, "_run", fake_run)
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
        "superseded_candidate_sha": source_candidate_sha,
        "failed_acceptance_sha256": failed_acceptance_sha256,
        "superseded_retirement_candidate_sha": (
            superseded_retirement_candidate_sha
        ),
        "superseded_retirement_stage_record_sha256": superseded_stage_sha256,
        "superseded_retirement_pending_sha256": superseded_pending_sha256,
        "acceptance_record_dir": acceptance_dir,
        "acceptance_failure_archive_dir": acceptance_archive_dir,
        "retirement_failure_archive_dir": retirement_archive_dir,
        "lock_file": tmp_path / "lock",
    }
    final_path = candidate._stage_record_path(record_dir, TARGET_SHA)
    pending_path = candidate._stage_pending_path(record_dir, TARGET_SHA)
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
            raise OSError("injected schema3 final publication failure")
        original_writer(path, payload, mode)

    monkeypatch.setattr(candidate, "_write_json_exclusive", fail_final_once)
    with pytest.raises(OSError, match="schema3 final publication"):
        candidate.stage_candidate(**arguments)
    assert pending_path.exists()
    assert json.loads(pending_path.read_text(encoding="utf-8"))[
        "schema_version"
    ] == 3
    monkeypatch.setattr(candidate, "_write_json_exclusive", original_writer)

    result = candidate.stage_candidate(**arguments)

    assert set(result) == candidate.TAKEOVER_STAGE_RECORD_KEYS
    assert result["schema_version"] == 3
    assert result["recovery_kind"] == "prepared-retirement-takeover"
    assert (
        result["superseded_retirement_candidate_sha"]
        == superseded_retirement_candidate_sha
    )
    assert result["superseded_retirement_stage_record_sha256"] == (
        superseded_stage_sha256
    )
    assert result["superseded_retirement_pending_sha256"] == (
        superseded_pending_sha256
    )
    assert len(scanner_calls) == 4
    for scanner_call in scanner_calls:
        assert scanner_call["allowed_release_pendings"] == (
            candidate._stage_pending_path(record_dir, TARGET_SHA),
            candidate._retirement_pending_path(
                record_dir, superseded_retirement_candidate_sha
            ),
        )
    assert len(takeover_calls) == 2


def _isolated_takeover_operations_source() -> bytes:
    return textwrap.dedent(
        f"""\
        import json
        import os
        from pathlib import Path

        with Path(os.environ["GATEA_ISOLATED_EVENTS"]).open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write("archive-operations\\n")

        REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
        APPROVED_TARGET_M9_CHAIN = {tuple(M9_CHAIN)!r}

        def _require_upgrade_record(*, record_dir, candidate_sha, image_id):
            del image_id
            return json.loads(
                (Path(record_dir) / (
                    f"{{candidate_sha}}.existing-database-upgrade.json"
                )).read_text(encoding="utf-8")
            )

        def _require_m9_upgrade_replay_record(
            *, record_dir, candidate_sha, image_id, upgrade_record
        ):
            del image_id, upgrade_record
            return json.loads(
                (Path(record_dir) / (
                    f"{{candidate_sha}}.upgrade-plan-replay.json"
                )).read_text(encoding="utf-8")
            )
        """
    ).encode("utf-8")


def _isolated_takeover_sitecustomize_source() -> str:
    return textwrap.dedent(
        """\
        import atexit
        import contextlib
        import importlib.util
        import json
        import os
        from pathlib import Path
        import sys
        from types import SimpleNamespace

        repository_root = Path(os.environ["GATEA_ISOLATED_REPOSITORY_ROOT"]).resolve()
        launcher = Path(os.environ["GATEA_ISOLATED_LAUNCHER"]).resolve()
        audit_path = Path(os.environ["GATEA_ISOLATED_AUDIT"])
        event_path = Path(os.environ["GATEA_ISOLATED_EVENTS"])

        retained_paths = []
        for raw_path in sys.path:
            if not raw_path:
                retained_paths.append(raw_path)
                continue
            resolved = Path(raw_path).resolve()
            if resolved == repository_root or repository_root in resolved.parents:
                continue
            retained_paths.append(raw_path)
        sys.path[:] = retained_paths
        try:
            ambient_spec = importlib.util.find_spec(
                "scripts.release.gatea_operations"
            )
        except (ImportError, ModuleNotFoundError):
            ambient_spec = None
        audit = {
            "ambient_operations_available": ambient_spec is not None,
            "cwd": str(Path.cwd().resolve()),
            "initial_release_modules": sorted(
                name for name in sys.modules if name.startswith("scripts.release")
            ),
            "sys_path": [
                str(Path(path).resolve()) if path else ""
                for path in sys.path
            ],
        }

        def write_audit():
            audit["final_release_modules"] = sorted(
                name for name in sys.modules if name.startswith("scripts.release")
            )
            audit_path.write_text(
                json.dumps(audit, sort_keys=True) + "\\n",
                encoding="utf-8",
            )

        atexit.register(write_audit)

        def record(event):
            with event_path.open("a", encoding="utf-8") as stream:
                stream.write(f"{event}\\n")

        def patch_candidate(frame, event, argument):
            del argument
            if (
                event != "call"
                or frame.f_code.co_name != "main"
                or Path(frame.f_code.co_filename).resolve() != launcher
            ):
                return patch_candidate
            namespace = frame.f_globals
            namespace["ROOT_UID"] = os.getuid()
            namespace["ROOT_GID"] = os.getgid()
            namespace["_require_root"] = lambda: None
            namespace["_require_root_directory"] = lambda *args: None
            namespace["_require_root_file"] = lambda *args: None
            namespace["_exclusive_lock"] = lambda path: contextlib.nullcontext()
            namespace["_fsync_directory"] = lambda path: None

            def write_bytes_exclusive(path, content, mode):
                descriptor = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    mode,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)

            namespace["_write_bytes_exclusive"] = write_bytes_exclusive
            stages = json.loads(os.environ["GATEA_ISOLATED_STAGES"])
            namespace["_load_stage"] = lambda **kwargs: dict(
                stages[kwargs["target_sha"]]
            )
            namespace["_validate_activation_journal"] = lambda *args, **kwargs: None

            real_scanner = namespace["_reject_unresolved_transition_journals"]
            scanner_calls = 0

            def scan_transitions(**kwargs):
                nonlocal scanner_calls
                result = real_scanner(**kwargs)
                scanner_calls += 1
                record(
                    "first-scan" if scanner_calls == 1 else "second-scan"
                )
                return result

            namespace["_reject_unresolved_transition_journals"] = scan_transitions
            real_takeover = namespace["_validate_prepared_retirement_takeover"]

            def validate_takeover(**kwargs):
                result = real_takeover(**kwargs)
                record("takeover")
                return result

            namespace["_validate_prepared_retirement_takeover"] = validate_takeover

            provenance = json.loads(os.environ["GATEA_ISOLATED_PROVENANCE"])
            drift_after_provenance = (
                os.environ.get("GATEA_ISOLATED_DRIFT") == "after-provenance"
            )

            def verify_github_provenance(**kwargs):
                record("provenance")
                if drift_after_provenance:
                    operations = (
                        Path(kwargs["source_root"])
                        / "scripts/release/gatea_operations.py"
                    )
                    operations.write_bytes(
                        operations.read_bytes() + b"\\n# post-provenance drift\\n"
                    )
                return dict(provenance)

            namespace["_verify_github_provenance"] = verify_github_provenance
            namespace["_image_exists"] = lambda image: False
            namespace["_inspect_image"] = lambda *args, **kwargs: {
                "architecture": "amd64",
                "image_id": os.environ["GATEA_ISOLATED_IMAGE_ID"],
                "operating_system": "linux",
            }

            def run(command, **kwargs):
                del kwargs
                if tuple(command[:2]) == ("docker", "build"):
                    record("docker-build")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            namespace["_run"] = run
            sys.settrace(None)
            return None

        sys.settrace(patch_candidate)
        """
    )


def _write_canonical_json(path: Path, payload: object, *, mode: int) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    path.chmod(mode)


def _isolated_takeover_stage_case(tmp_path: Path) -> SimpleNamespace:
    repository_root = Path(__file__).resolve().parents[2]
    isolated_root = tmp_path / "isolated"
    launcher_dir = isolated_root / "launcher"
    working_dir = isolated_root / "work"
    hook_dir = isolated_root / "hook"
    release_root = isolated_root / "releases"
    staging_root = isolated_root / "staging"
    release_record_dir = isolated_root / "release-records"
    acceptance_record_dir = isolated_root / "acceptance-records"
    acceptance_failure_archive_dir = isolated_root / "acceptance-failures"
    retirement_failure_archive_dir = isolated_root / "retirement-failures"
    for directory, mode in (
        (launcher_dir, 0o700),
        (working_dir, 0o700),
        (hook_dir, 0o700),
        (release_root, 0o755),
        (staging_root, 0o700),
        (release_record_dir, 0o755),
        (acceptance_record_dir, 0o755),
    ):
        directory.mkdir(parents=True, mode=mode)
        directory.chmod(mode)

    launcher = launcher_dir / "gatea_candidate.py"
    launcher.write_bytes(Path(candidate.__file__).read_bytes())
    launcher.chmod(0o700)
    members = _source_members(launcher.read_bytes())
    members["scripts/release/gatea_operations.py"] = (
        _isolated_takeover_operations_source()
    )
    members["scripts/release/gatea_backup.py"] = b"# isolated backup module\n"
    members["scripts/release/gatea_upgrade.py"] = b"# isolated upgrade module\n"
    source_archive = isolated_root / "source.tar"
    _write_source_tar(source_archive, members=members)
    source_archive.chmod(0o600)
    ci_artifact = isolated_root / "artifact.zip"
    _write_ci_zip(ci_artifact)
    ci_artifact.chmod(0o600)

    source_candidate_sha = "a" * 40
    superseded_retirement_candidate_sha = "d" * 40
    source_image_id = "sha256:" + "a" * 64
    lineage_source_image_id = "sha256:" + "7" * 64
    failed_acceptance = _preclaim_failure_payload(source_candidate_sha)
    acceptance_path = candidate._acceptance_pending_path(
        acceptance_record_dir, source_candidate_sha
    )
    _write_canonical_json(acceptance_path, failed_acceptance, mode=0o600)
    failed_acceptance_sha256 = candidate._sha256(acceptance_path)

    source_stage_path = candidate._stage_record_path(
        release_record_dir, source_candidate_sha
    )
    source_stage_path.write_text("source-stage\n", encoding="utf-8")
    source_stage_path.chmod(0o644)
    source_activation_path = candidate._activation_record_path(
        release_record_dir, source_candidate_sha
    )
    source_activation = {
        "backup_id": BACKUP_ID,
        "history_path": str(isolated_root / "history.env"),
        "manifest_sha256": MANIFEST_SHA,
    }
    _write_canonical_json(source_activation_path, source_activation, mode=0o644)
    source_evidence_path = release_record_dir / (
        f"{source_candidate_sha}.existing-database-upgrade.evidence.json"
    )
    _write_canonical_json(source_evidence_path, {}, mode=0o644)
    source_upgrade_path = release_record_dir / (
        f"{source_candidate_sha}.existing-database-upgrade.json"
    )
    source_upgrade = {
        "schema_version": 1,
        "record_type": "existing-database-upgrade",
        "source_version": 7,
        "source_candidate_sha": SOURCE_SHA,
        "source_image_id": lineage_source_image_id,
        "candidate_sha": source_candidate_sha,
        "image_id": source_image_id,
        "backup_id": BACKUP_ID,
        "manifest_sha256": MANIFEST_SHA,
        "target_aerich_versions": M9_CHAIN,
        "evidence_sha256": candidate._sha256(source_evidence_path),
    }
    _write_canonical_json(source_upgrade_path, source_upgrade, mode=0o644)
    source_replay_path = candidate._upgrade_replay_record_path(
        release_record_dir, source_candidate_sha
    )
    source_replay = {
        "source_candidate_sha": SOURCE_SHA,
        "source_version": 7,
        "upgrade_record_sha256": candidate._sha256(source_upgrade_path),
        "evidence_sha256": candidate._sha256(source_evidence_path),
    }
    _write_canonical_json(source_replay_path, source_replay, mode=0o644)
    predecessor = {
        "source_candidate_sha": source_candidate_sha,
        "source_image_id": source_image_id,
        "lineage_source_candidate_sha": SOURCE_SHA,
        "lineage_source_image_id": lineage_source_image_id,
        "predecessor_stage_record_sha256": candidate._sha256(source_stage_path),
        "predecessor_activation_record_sha256": candidate._sha256(
            source_activation_path
        ),
        "predecessor_upgrade_record_sha256": candidate._sha256(
            source_upgrade_path
        ),
        "predecessor_upgrade_evidence_sha256": candidate._sha256(
            source_evidence_path
        ),
        "predecessor_upgrade_plan_replay_record_sha256": candidate._sha256(
            source_replay_path
        ),
    }

    superseded_stage_path = candidate._stage_record_path(
        release_record_dir, superseded_retirement_candidate_sha
    )
    superseded_stage_path.write_text("superseded-stage\n", encoding="utf-8")
    superseded_stage_path.chmod(0o644)
    superseded_stage_sha256 = candidate._sha256(superseded_stage_path)
    superseded_image_id = "sha256:" + "d" * 64
    superseded_stage = {
        "schema_version": 2,
        "record_type": "gatea-candidate-stage",
        "passed": True,
        "candidate_sha": superseded_retirement_candidate_sha,
        "image_id": superseded_image_id,
        "transition_kind": "m9-candidate-adoption",
        "superseded_candidate_sha": source_candidate_sha,
        "failed_acceptance_sha256": failed_acceptance_sha256,
        "secret_values_recorded": False,
    }
    acceptance_archive_path = candidate._retirement_archive_path(
        acceptance_failure_archive_dir,
        source_candidate_sha,
        failed_acceptance_sha256,
    )
    superseded_pending_path = candidate._retirement_pending_path(
        release_record_dir, superseded_retirement_candidate_sha
    )
    superseded_pending = {
        "schema_version": 1,
        "record_type": "gatea-m9-failed-acceptance-retirement-pending",
        "candidate_sha": superseded_retirement_candidate_sha,
        "image_id": superseded_image_id,
        **predecessor,
        "stage_record_sha256": superseded_stage_sha256,
        "acceptance_pending_sha256": failed_acceptance_sha256,
        "acceptance_attempt_id_sha256": failed_acceptance[
            "attempt_id_sha256"
        ],
        "acceptance_archive_path": str(acceptance_archive_path),
        "acceptance_archive_sha256": failed_acceptance_sha256,
        "live_verification": None,
        "started_at": "2026-09-11T01:00:00+00:00",
        "phase": "prepared",
        "secret_values_recorded": False,
    }
    _write_canonical_json(superseded_pending_path, superseded_pending, mode=0o600)
    superseded_pending_sha256 = candidate._sha256(superseded_pending_path)

    events = isolated_root / "events.txt"
    audit = isolated_root / "audit.json"
    sitecustomize = hook_dir / "sitecustomize.py"
    sitecustomize.write_text(
        _isolated_takeover_sitecustomize_source(), encoding="utf-8"
    )
    provenance = _github_stage_evidence(ci_artifact)
    provenance["github_blob_count"] = len(members)
    environment = os.environ.copy()
    environment.pop("GITHUB_TOKEN", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONPATH"] = str(hook_dir)
    environment.update(
        {
            "GATEA_ISOLATED_REPOSITORY_ROOT": str(repository_root),
            "GATEA_ISOLATED_LAUNCHER": str(launcher),
            "GATEA_ISOLATED_AUDIT": str(audit),
            "GATEA_ISOLATED_EVENTS": str(events),
            "GATEA_ISOLATED_IMAGE_ID": IMAGE_ID,
            "GATEA_ISOLATED_PROVENANCE": json.dumps(provenance),
            "GATEA_ISOLATED_STAGES": json.dumps(
                {
                    source_candidate_sha: {"image_id": source_image_id},
                    superseded_retirement_candidate_sha: superseded_stage,
                }
            ),
        }
    )
    python3 = Path(sys.executable).with_name("python3")
    assert python3.is_file()
    command = (
        str(python3),
        "-B",
        str(launcher),
        "stage",
        "--source-archive",
        str(source_archive),
        "--confirm-source-archive-sha256",
        candidate._sha256(source_archive),
        "--ci-artifact",
        str(ci_artifact),
        "--confirm-ci-artifact-sha256",
        candidate._sha256(ci_artifact),
        "--launcher",
        str(launcher),
        "--confirm-launcher-sha256",
        candidate._sha256(launcher),
        "--target-sha",
        TARGET_SHA,
        "--source-head-sha",
        HEAD_SHA,
        "--ci-run-id",
        RUN_ID,
        "--ci-run-attempt",
        str(ATTEMPT),
        "--ci-artifact-name",
        ARTIFACT_NAME,
        "--confirm-required-jobs",
        "9",
        "--confirm-target-sha",
        TARGET_SHA,
        "--release-root",
        str(release_root),
        "--staging-root",
        str(staging_root),
        "--release-record-dir",
        str(release_record_dir),
        "--superseded-candidate-sha",
        source_candidate_sha,
        "--confirm-failed-acceptance-sha256",
        failed_acceptance_sha256,
        "--superseded-retirement-candidate-sha",
        superseded_retirement_candidate_sha,
        "--confirm-superseded-retirement-stage-record-sha256",
        superseded_stage_sha256,
        "--confirm-superseded-retirement-pending-sha256",
        superseded_pending_sha256,
        "--acceptance-record-dir",
        str(acceptance_record_dir),
        "--acceptance-failure-archive-dir",
        str(acceptance_failure_archive_dir),
        "--retirement-failure-archive-dir",
        str(retirement_failure_archive_dir),
        "--apply",
    )
    return SimpleNamespace(
        audit=audit,
        command=command,
        environment=environment,
        events=events,
        launcher=launcher,
        release_record_dir=release_record_dir,
        release_root=release_root,
        source_archive=source_archive,
        staging_root=staging_root,
        target_stage_path=candidate._stage_record_path(
            release_record_dir, TARGET_SHA
        ),
        target_pending_path=candidate._stage_pending_path(
            release_record_dir, TARGET_SHA
        ),
        working_dir=working_dir,
    )


def test_takeover_stage_cli_loads_only_verified_archive_operations(
    tmp_path: Path,
) -> None:
    case = _isolated_takeover_stage_case(tmp_path)

    result = subprocess.run(
        case.command,
        cwd=case.working_dir,
        env=case.environment,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 3
    assert payload["candidate_sha"] == TARGET_SHA
    assert case.target_stage_path.is_file()
    assert not case.target_pending_path.exists()
    assert case.events.read_text(encoding="utf-8").splitlines() == [
        "first-scan",
        "provenance",
        "second-scan",
        "archive-operations",
        "takeover",
        "docker-build",
    ]
    audit = json.loads(case.audit.read_text(encoding="utf-8"))
    assert audit["ambient_operations_available"] is False
    assert audit["cwd"] == str(case.working_dir.resolve())
    assert audit["initial_release_modules"] == []
    assert audit["final_release_modules"] == []
    assert all(
        not Path(path).is_relative_to(Path(__file__).resolve().parents[2])
        for path in audit["sys_path"]
        if path
    )


def test_takeover_stage_cli_rejects_archive_module_drift_before_execution(
    tmp_path: Path,
) -> None:
    case = _isolated_takeover_stage_case(tmp_path)
    case.environment["GATEA_ISOLATED_DRIFT"] = "after-provenance"

    result = subprocess.run(
        case.command,
        cwd=case.working_dir,
        env=case.environment,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "source" in result.stderr.lower()
    assert "changed" in result.stderr.lower()
    assert case.events.read_text(encoding="utf-8").splitlines() == [
        "first-scan",
        "provenance",
        "second-scan",
    ]
    assert not case.target_pending_path.exists()
    assert not case.target_stage_path.exists()
    assert not (case.release_root / TARGET_SHA).exists()
    assert not any(case.staging_root.iterdir())


def test_verified_stage_operations_executes_real_dataclass_module_in_isolation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    operations_path = source_root / "scripts/release/gatea_operations.py"
    operations_path.parent.mkdir(parents=True)
    operations_path.write_bytes(Path(gatea_operations.__file__).read_bytes())
    operations_path.chmod(0o644)
    source_root.chmod(0o755)
    monkeypatch.setattr(candidate, "ROOT_UID", os.getuid())
    monkeypatch.setattr(candidate, "ROOT_GID", os.getgid())
    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    private_name = f"_pinkdoohub_gatea_stage_operations_{TARGET_SHA}"
    canonical_module = sys.modules["scripts.release.gatea_operations"]
    original_sys_path = tuple(sys.path)

    assert private_name not in sys.modules
    assert canonical_module is gatea_operations
    assert not any(source_root.rglob("__pycache__"))

    with candidate._verified_stage_operations(
        source_root=source_root,
        target_sha=TARGET_SHA,
        expected_sha256=candidate._sha256(operations_path),
    ) as facade:
        private_module = sys.modules[private_name]
        assert facade.APPROVED_TARGET_M9_CHAIN == tuple(M9_CHAIN)
        assert callable(facade._require_upgrade_record)
        assert callable(facade._require_m9_upgrade_replay_record)
        assert private_module.__file__ == str(operations_path)
        assert private_module.REPOSITORY_ROOT == source_root.resolve()
        assert sys.modules["scripts.release.gatea_operations"] is canonical_module
        assert tuple(sys.path) == original_sys_path
        assert not any(source_root.rglob("__pycache__"))

    assert private_name not in sys.modules
    assert sys.modules["scripts.release.gatea_operations"] is canonical_module
    assert tuple(sys.path) == original_sys_path
    assert not any(source_root.rglob("__pycache__"))

    for interruption in (
        candidate.GateACandidateOperationInterrupted("SIGTERM test"),
        KeyboardInterrupt("SIGINT test"),
    ):
        with pytest.raises(type(interruption)):
            with candidate._verified_stage_operations(
                source_root=source_root,
                target_sha=TARGET_SHA,
                expected_sha256=candidate._sha256(operations_path),
            ):
                assert private_name in sys.modules
                raise interruption
        assert private_name not in sys.modules
        assert sys.modules["scripts.release.gatea_operations"] is canonical_module


@pytest.mark.parametrize(
    "source",
    (
        pytest.param(b"def invalid(:\n", id="syntax-error"),
        pytest.param(b"raise SystemExit(17)\n", id="system-exit"),
    ),
)
def test_verified_stage_operations_cleans_private_module_after_load_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: bytes,
) -> None:
    source_root = tmp_path / "source"
    operations_path = source_root / "scripts/release/gatea_operations.py"
    operations_path.parent.mkdir(parents=True)
    operations_path.write_bytes(source)
    operations_path.chmod(0o644)
    source_root.chmod(0o755)
    monkeypatch.setattr(candidate, "ROOT_UID", os.getuid())
    monkeypatch.setattr(candidate, "ROOT_GID", os.getgid())
    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    private_name = f"_pinkdoohub_gatea_stage_operations_{TARGET_SHA}"
    canonical_module = sys.modules["scripts.release.gatea_operations"]

    with pytest.raises(
        candidate.GateACandidateError,
        match="operations source could not be loaded",
    ):
        with candidate._verified_stage_operations(
            source_root=source_root,
            target_sha=TARGET_SHA,
            expected_sha256=candidate._sha256(operations_path),
        ):
            pytest.fail("invalid operations source unexpectedly loaded")

    assert private_name not in sys.modules
    assert sys.modules["scripts.release.gatea_operations"] is canonical_module
    assert not any(source_root.rglob("__pycache__"))


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
    m8_swatch_snapshot = {
        "schema_version": 1,
        "profile": "m8-swatch-content-v1",
        "content_sha256": "8" * 64,
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
        "m8_swatch_content_snapshot": m8_swatch_snapshot,
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
        "m8_swatch_content_matches": True,
        "m9_table_content_matches": True,
        "m7_content_snapshot": m7_snapshot,
        "m8_swatch_content_snapshot": m8_swatch_snapshot,
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
        _validate_m8_swatch_content_snapshot=(
            gatea_backup._validate_m8_swatch_content_snapshot
        ),
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

    backup_payload.pop("m8_swatch_content_snapshot")
    write_records()
    with pytest.raises(candidate.GateACandidateError, match="content evidence"):
        candidate._validate_post_backup(
            backup_id=BACKUP_ID,
            target_sha=TARGET_SHA,
            image_id=IMAGE_ID,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
            restore_record_dir=restore_record_dir,
        )
    backup_payload["m8_swatch_content_snapshot"] = m8_swatch_snapshot

    restore_payload["m8_swatch_content_snapshot"] = {
        **m8_swatch_snapshot,
        "content_sha256": "a" * 64,
    }
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
    restore_payload["m8_swatch_content_snapshot"] = m8_swatch_snapshot

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
    m8_swatch_snapshot = {
        "schema_version": 1,
        "profile": "m8-swatch-content-v1",
        "content_sha256": "8" * 64,
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
        _source_m8_swatch_content_snapshot=lambda *args: m8_swatch_snapshot,
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
        "m8_swatch_content_snapshot": m8_swatch_snapshot,
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
    assert result["m8_swatch_content_snapshot"] == m8_swatch_snapshot
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
            "m8_swatch_content": {
                "schema_version": 1,
                "profile": "m8-swatch-content-v1",
                "content_sha256": "8" * 64,
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
                "m8_swatch_content": {
                    "schema_version": 1,
                    "profile": "m8-swatch-content-v1",
                    "content_sha256": "8" * 64,
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
                "m8_swatch_content_snapshot": {
                    "schema_version": 1,
                    "profile": "m8-swatch-content-v1",
                    "content_sha256": "8" * 64,
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
            "m8_swatch_content_snapshot": {
                "schema_version": 1,
                "profile": "m8-swatch-content-v1",
                "content_sha256": "8" * 64,
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
    m8_swatch_snapshot = {
        "schema_version": 1,
        "profile": "m8-swatch-content-v1",
        "content_sha256": "8" * 64,
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
            "m8_swatch_content": m8_swatch_snapshot,
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
        "m8_swatch_content_snapshot": m8_swatch_snapshot,
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
        "m8_swatch_content_snapshot": m8_swatch_snapshot,
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


def test_takeover_stage_cli_forwards_exact_recovery_bindings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        candidate,
        "stage_candidate",
        lambda **kwargs: calls.append(kwargs) or {"passed": True},
    )
    source_candidate_sha = "a" * 40
    superseded_retirement_candidate_sha = "c" * 40
    acceptance_archive_dir = tmp_path / "acceptance-failures"
    retirement_archive_dir = tmp_path / "retirement-failures"

    status = candidate.main(
        [
            "stage",
            "--source-archive",
            "/source.tar",
            "--confirm-source-archive-sha256",
            "a" * 64,
            "--ci-artifact",
            "/artifact.zip",
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
            "--superseded-candidate-sha",
            source_candidate_sha,
            "--confirm-failed-acceptance-sha256",
            "f" * 64,
            "--superseded-retirement-candidate-sha",
            superseded_retirement_candidate_sha,
            "--confirm-superseded-retirement-stage-record-sha256",
            "1" * 64,
            "--confirm-superseded-retirement-pending-sha256",
            "2" * 64,
            "--acceptance-failure-archive-dir",
            str(acceptance_archive_dir),
            "--retirement-failure-archive-dir",
            str(retirement_archive_dir),
            "--apply",
        ]
    )

    assert status == 0
    assert len(calls) == 1
    assert calls[0]["superseded_candidate_sha"] == source_candidate_sha
    assert calls[0]["superseded_retirement_candidate_sha"] == (
        superseded_retirement_candidate_sha
    )
    assert calls[0]["superseded_retirement_stage_record_sha256"] == "1" * 64
    assert calls[0]["superseded_retirement_pending_sha256"] == "2" * 64
    assert calls[0]["acceptance_failure_archive_dir"] == acceptance_archive_dir
    assert calls[0]["retirement_failure_archive_dir"] == retirement_archive_dir


def test_takeover_retirement_cli_forwards_values_and_repeated_confirmations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        candidate,
        "retire_failed_acceptance",
        lambda **kwargs: calls.append(kwargs) or {"passed": True},
    )
    source_candidate_sha = "a" * 40
    superseded_retirement_candidate_sha = "c" * 40
    acceptance_archive_dir = tmp_path / "acceptance-failures"
    retirement_archive_dir = tmp_path / "retirement-failures"

    status = candidate.main(
        [
            "retire-failed-acceptance",
            "--source-candidate-sha",
            source_candidate_sha,
            "--lineage-source-candidate-sha",
            SOURCE_SHA,
            "--target-sha",
            TARGET_SHA,
            "--failed-acceptance-sha256",
            "f" * 64,
            "--confirm-source-sha",
            source_candidate_sha,
            "--confirm-lineage-source-sha",
            SOURCE_SHA,
            "--confirm-target-sha",
            TARGET_SHA,
            "--confirm-failed-acceptance-sha256",
            "f" * 64,
            "--superseded-retirement-candidate-sha",
            superseded_retirement_candidate_sha,
            "--superseded-retirement-stage-record-sha256",
            "1" * 64,
            "--superseded-retirement-pending-sha256",
            "2" * 64,
            "--confirm-superseded-retirement-candidate-sha",
            superseded_retirement_candidate_sha,
            "--confirm-superseded-retirement-stage-record-sha256",
            "1" * 64,
            "--confirm-superseded-retirement-pending-sha256",
            "2" * 64,
            "--acceptance-failure-archive-dir",
            str(acceptance_archive_dir),
            "--retirement-failure-archive-dir",
            str(retirement_archive_dir),
            "--apply",
        ]
    )

    assert status == 0
    assert len(calls) == 1
    expected = {
        "superseded_retirement_candidate_sha": (
            superseded_retirement_candidate_sha
        ),
        "superseded_retirement_stage_record_sha256": "1" * 64,
        "superseded_retirement_pending_sha256": "2" * 64,
        "confirm_superseded_retirement_candidate_sha": (
            superseded_retirement_candidate_sha
        ),
        "confirm_superseded_retirement_stage_record_sha256": "1" * 64,
        "confirm_superseded_retirement_pending_sha256": "2" * 64,
    }
    for key, value in expected.items():
        assert calls[0][key] == value
    assert calls[0]["acceptance_failure_archive_dir"] == acceptance_archive_dir
    assert calls[0]["retirement_failure_archive_dir"] == retirement_archive_dir


@pytest.mark.parametrize("command", ("activate-config", "rollback-config"))
def test_adoption_config_cli_forwards_retirement_archive_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
) -> None:
    calls: list[dict[str, object]] = []
    function_name = (
        "activate_config" if command == "activate-config" else "rollback_config"
    )
    monkeypatch.setattr(
        candidate,
        function_name,
        lambda **kwargs: calls.append(kwargs) or {"passed": True},
    )
    source_candidate_sha = "a" * 40
    retirement_archive_dir = tmp_path / "retirement-failures"
    shared = [
        "--lineage-source-candidate-sha",
        SOURCE_SHA,
        "--acceptance-retirement-record-sha256",
        "f" * 64,
        "--confirm-lineage-source-sha",
        SOURCE_SHA,
        "--confirm-acceptance-retirement-record-sha256",
        "f" * 64,
        "--retirement-failure-archive-dir",
        str(retirement_archive_dir),
        "--apply",
    ]
    if command == "activate-config":
        arguments = [
            command,
            "--source-version",
            "9",
            "--source-candidate-sha",
            source_candidate_sha,
            "--target-sha",
            TARGET_SHA,
            "--backup-id",
            BACKUP_ID,
            "--confirm-source-sha",
            source_candidate_sha,
            "--confirm-target-sha",
            TARGET_SHA,
            "--confirm-backup-id",
            BACKUP_ID,
            "--confirm-manifest-sha256",
            MANIFEST_SHA,
            *shared,
        ]
    else:
        arguments = [
            command,
            "--source-sha",
            source_candidate_sha,
            "--target-sha",
            TARGET_SHA,
            "--confirm-source-sha",
            source_candidate_sha,
            "--confirm-target-sha",
            TARGET_SHA,
            "--confirm-activation-record-sha256",
            "e" * 64,
            *shared,
        ]

    assert candidate.main(arguments) == 0
    assert len(calls) == 1
    assert calls[0]["retirement_failure_archive_dir"] == retirement_archive_dir


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
    retirement_failure_dir = tmp_path / "retirement-failures"

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
            "--retirement-failure-archive-dir",
            str(retirement_failure_dir),
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
    assert (
        calls[0]["retirement_failure_archive_dir"]
        == retirement_failure_dir
    )


def _preclaim_failure_payload(old_sha: str = "a" * 40) -> dict[str, object]:
    fixture = {
        "experience_product_id": 101,
        "kit_product_id": 102,
        "option_ids": [201, 202, 203],
        "option_durations_minutes": [60, 60, 120],
        "option_participants": [1, 2, 1],
        "option_price": "1.00",
        "kit_price": "1.00",
        "kit_opening_stock": 10,
        "product_images_created": 2,
        "option_images_created": 3,
        "products_online": True,
    }
    order_evidence = {
        "order_id": 301,
        "expected_timer_items": [
            {"order_item_id": 401, "duration_minutes": 60, "quantity": 2},
            {"order_item_id": 402, "duration_minutes": 60, "quantity": 1},
            {"order_item_id": 403, "duration_minutes": 120, "quantity": 1},
        ],
        "kit_order_item_id": 404,
        "eligible_duration_groups": [
            {
                "duration_minutes": 60,
                "buffer_minutes": 10,
                "experience_item_count": 2,
                "total_quantity": 3,
            },
            {
                "duration_minutes": 120,
                "buffer_minutes": 10,
                "experience_item_count": 1,
                "total_quantity": 1,
            },
        ],
    }
    attempt_id = "1" * 32
    return {
        "schema_version": 3,
        "record_type": "gatea-m9-internal-acceptance-pending",
        "environment": "gatea",
        "candidate_sha": old_sha,
        "image_id": "sha256:" + "a" * 64,
        "operations_sha": old_sha,
        "ci_run_id": RUN_ID,
        "source_candidate_sha": SOURCE_SHA,
        "upgrade_record_sha256": "2" * 64,
        "upgrade_plan_replay_record_sha256": "3" * 64,
        "representative_record_sha256": "4" * 64,
        "credentials_sha256": "5" * 64,
        "started_at": "2026-09-11T00:00:00+00:00",
        "attempt_id": attempt_id,
        "attempt_id_sha256": hashlib.sha256(attempt_id.encode()).hexdigest(),
        "updated_at": "2026-09-11T00:01:00+00:00",
        "stage": "order_created",
        "pre_reconcile": dict(EMPTY_TABLE_RECONCILE),
        "pre_wallet_reconcile": {
            "scanned": 1,
            "mismatches": 0,
            "violations": 0,
        },
        "fixture_ids": [101, 102],
        "fixture": fixture,
        "fixture_sha256": candidate._canonical_json_sha256(fixture),
        "order_id": 301,
        "order_evidence": order_evidence,
        "order_evidence_sha256": candidate._canonical_json_sha256(
            order_evidence
        ),
        "table_no": None,
        "session_no_sha256": None,
        "payment_deadline_offset_seconds": None,
        "payment_evidence": None,
        "timer_evidence": None,
        "claim_replay_verified": False,
        "payment_replay_verified": False,
        "admin_visibility_verified": False,
        "release_replay_verified": False,
        "payment_committed": False,
        "session_released": False,
        "cleanup": {
            "order_cancelled": True,
            "fixture_products_offline": True,
            "synthetic_session_revoked": True,
            "super_admin_session_revoked": True,
        },
        "failure": True,
        "secret_values_recorded": False,
        "source_volume_restored": False,
        "passed": False,
    }


def _write_preclaim_failure(path: Path, payload: dict[str, object]) -> str:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return candidate._sha256(path)


def test_preclaim_failure_allowance_is_exact_and_non_mutating(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release_records = tmp_path / "release-records"
    acceptance_records = tmp_path / "acceptance-records"
    release_records.mkdir()
    acceptance_records.mkdir()
    old_sha = "a" * 40
    path = candidate._acceptance_pending_path(acceptance_records, old_sha)
    digest = _write_preclaim_failure(path, _preclaim_failure_payload(old_sha))
    before = path.read_bytes()
    monkeypatch.setattr(candidate, "ROOT_UID", os.getuid())
    monkeypatch.setattr(candidate, "ROOT_GID", os.getgid())
    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)

    validated = candidate._reject_unresolved_transition_journals(
        release_record_dir=release_records,
        acceptance_record_dir=acceptance_records,
        allowed_acceptance_candidate_sha=old_sha,
        allowed_acceptance_pending_sha256=digest,
    )

    assert validated == _preclaim_failure_payload(old_sha)
    assert path.read_bytes() == before
    with pytest.raises(candidate.GateACandidateError, match="pair"):
        candidate._reject_unresolved_transition_journals(
            release_record_dir=release_records,
            acceptance_record_dir=acceptance_records,
            allowed_acceptance_candidate_sha=old_sha,
        )
    second = acceptance_records / (
        f"gatea-m9-runtime-acceptance-{'9' * 40}.json.complete"
    )
    second.write_text("{}", encoding="utf-8")
    with pytest.raises(candidate.GateACandidateError, match="sidecar"):
        candidate._reject_unresolved_transition_journals(
            release_record_dir=release_records,
            acceptance_record_dir=acceptance_records,
            allowed_acceptance_candidate_sha=old_sha,
            allowed_acceptance_pending_sha256=digest,
        )


def test_preclaim_failure_state_drift_is_not_retireable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _preclaim_failure_payload()
    payload["payment_committed"] = True
    path = tmp_path / "failed.json.pending"
    digest = _write_preclaim_failure(path, payload)
    monkeypatch.setattr(candidate, "ROOT_UID", os.getuid())
    monkeypatch.setattr(candidate, "ROOT_GID", os.getgid())
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)

    with pytest.raises(candidate.GateACandidateError, match="not safely retireable"):
        candidate._validate_preclaim_failed_acceptance(
            path=path,
            expected_candidate_sha="a" * 40,
            expected_sha256=digest,
        )


def test_failed_acceptance_business_verifier_uses_b_and_exact_option_ids() -> None:
    failed = _preclaim_failure_payload()
    observed: dict[str, object] = {}
    expected = {
        "schema_version": 2,
        "passed": True,
        "counts": dict(candidate.FAILED_ACCEPTANCE_BUSINESS_COUNTS),
        "evidence_sha256": candidate.FAILED_ACCEPTANCE_BUSINESS_EVIDENCE_SHA256,
        "secret_values_recorded": False,
    }

    class FakeGateA:
        @staticmethod
        def _run_compose(**kwargs: object) -> SimpleNamespace:
            observed.update(kwargs)
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    expected, sort_keys=True, separators=(",", ":")
                )
                + "\n",
            )

    result = candidate._failed_acceptance_business_verification(
        gatea=FakeGateA,
        values={"GATEA_APP_IMAGE": "old"},
        config_file=Path("config"),
        secret_dir=Path("secrets"),
        target_image_id=IMAGE_ID,
        failed_acceptance=failed,
    )

    assert result == expected
    assert observed["values"] == {"GATEA_APP_IMAGE": IMAGE_ID}
    arguments = observed["arguments"]
    assert isinstance(arguments, tuple)
    assert arguments[5:9] == (
        "python3",
        "-B",
        "-m",
        "app.tasks.gatea_m9_failed_acceptance_verify",
    )
    assert arguments[:5] == ("run", "--rm", "--no-deps", "-T", "app")
    assert not any(
        str(raw_id) in argument
        for raw_id in (101, 102, 201, 202, 203, 301, 401, 402, 403, 404)
        for argument in arguments
    )
    verifier_input = json.loads(str(observed["input_text"]))
    assert verifier_input["order_id"] == 301
    assert verifier_input["experience_items"] == [
        {
            "day_type": "weekday",
            "duration_minutes": 60,
            "option_id": 201,
            "order_item_id": 401,
            "participants": 1,
            "price": "1.00",
            "quantity": 2,
        },
        {
            "day_type": "weekday",
            "duration_minutes": 60,
            "option_id": 202,
            "order_item_id": 402,
            "participants": 2,
            "price": "1.00",
            "quantity": 1,
        },
        {
            "day_type": "weekday",
            "duration_minutes": 120,
            "option_id": 203,
            "order_item_id": 403,
            "participants": 1,
            "price": "1.00",
            "quantity": 1,
        },
    ]


def test_failed_acceptance_unlink_rechecks_stable_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "pending.json"
    path.write_text("before", encoding="utf-8")
    identity = candidate._file_identity(path.stat())
    path.write_text("after", encoding="utf-8")
    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)

    with pytest.raises(candidate.GateACandidateError, match="changed"):
        candidate._unlink_exact_protected_file(
            path, identity, description="acceptance pending"
        )
    assert path.exists()


def test_adoption_finalization_journal_uses_immediate_and_lineage_sources() -> None:
    binding = {
        "transition_kind": "m9-candidate-adoption",
        "source_image_id": "sha256:" + "a" * 64,
        "lineage_source_candidate_sha": SOURCE_SHA,
        "lineage_source_image_id": "sha256:" + "7" * 64,
        "predecessor_stage_record_sha256": "a" * 64,
        "predecessor_activation_record_sha256": "b" * 64,
        "predecessor_upgrade_record_sha256": "c" * 64,
        "predecessor_upgrade_evidence_sha256": "d" * 64,
        "predecessor_upgrade_plan_replay_record_sha256": "e" * 64,
        "acceptance_retirement_record_sha256": "f" * 64,
    }
    payload = {
        "schema_version": 2,
        "record_type": "gatea-current-finalization-pending",
        "source_candidate_sha": "a" * 40,
        "candidate_sha": TARGET_SHA,
        "image_id": IMAGE_ID,
        "source_link": f"/releases/{SOURCE_SHA}",
        "target_link": f"/releases/{TARGET_SHA}",
        "stage_record_sha256": "1" * 64,
        "activation_record_sha256": "2" * 64,
        "upgrade_record_sha256": "3" * 64,
        "upgrade_plan_replay_record_sha256": "4" * 64,
        "runtime_acceptance_record_sha256": "5" * 64,
        "resilience_record_sha256": "6" * 64,
        "post_backup_id": BACKUP_ID,
        "post_backup_record_sha256": "7" * 64,
        "post_restore_record_sha256": "8" * 64,
        "runtime_services": list(candidate.M9_RUNTIME_SERVICES),
        "started_at": "2026-09-11T01:00:00+00:00",
        "phase": "prepared",
        "live_recheck": None,
        "secret_values_recorded": False,
        **binding,
    }
    expected = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "schema_version",
            "record_type",
            "runtime_services",
            "started_at",
            "phase",
            "live_recheck",
            "secret_values_recorded",
        }
    }

    assert candidate._validate_finalization_journal(
        payload,
        expected=expected,
        expected_live_recheck={},
        final=False,
        adoption_binding=binding,
    ) == payload
    invalid = dict(payload)
    invalid["lineage_source_candidate_sha"] = "9" * 40
    with pytest.raises(candidate.GateACandidateError, match="journal"):
        candidate._validate_finalization_journal(
            invalid,
            expected=expected,
            expected_live_recheck={},
            final=False,
            adoption_binding=binding,
        )


def _retirement_live_evidence() -> dict[str, object]:
    return {
        "business_verification": {
            "schema_version": 2,
            "passed": True,
            "counts": dict(candidate.FAILED_ACCEPTANCE_BUSINESS_COUNTS),
            "evidence_sha256": (
                candidate.FAILED_ACCEPTANCE_BUSINESS_EVIDENCE_SHA256
            ),
            "secret_values_recorded": False,
        },
        "database_snapshot": {"aerich_versions": M9_CHAIN},
        "runtime_services": list(candidate.M9_RUNTIME_SERVICES),
        "database_services_healthy": list(
            candidate.RETIREMENT_DATABASE_SERVICES
        ),
        "writer_services_stopped": list(candidate.RETIREMENT_WRITER_SERVICES),
        "table_reconcile": dict(EMPTY_TABLE_RECONCILE),
        "wallet_reconcile": {
            "scanned": 1,
            "mismatches": 0,
            "violations": 0,
        },
        "checked_at": "2026-09-11T01:00:00+00:00",
    }


def _retirement_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> SimpleNamespace:
    old_sha = "a" * 40
    release_root = tmp_path / "releases"
    release_records = tmp_path / "release-records"
    acceptance_records = tmp_path / "acceptance-records"
    archive_dir = tmp_path / "acceptance-failures"
    for directory in (release_root, release_records, acceptance_records):
        directory.mkdir()
    canonical = candidate._acceptance_pending_path(acceptance_records, old_sha)
    failed_payload = _preclaim_failure_payload(old_sha)
    failed_digest = _write_preclaim_failure(canonical, failed_payload)
    target_stage_path = candidate._stage_record_path(
        release_records, TARGET_SHA
    )
    target_stage_path.write_text("stage\n", encoding="utf-8")
    target_stage_path.chmod(0o644)
    predecessor = {
        "source_candidate_sha": old_sha,
        "source_image_id": failed_payload["image_id"],
        "lineage_source_candidate_sha": SOURCE_SHA,
        "lineage_source_image_id": "sha256:" + "7" * 64,
        "predecessor_stage_record_sha256": "1" * 64,
        "predecessor_activation_record_sha256": "6" * 64,
        "predecessor_upgrade_record_sha256": failed_payload[
            "upgrade_record_sha256"
        ],
        "predecessor_upgrade_evidence_sha256": "8" * 64,
        "predecessor_upgrade_plan_replay_record_sha256": failed_payload[
            "upgrade_plan_replay_record_sha256"
        ],
    }
    target_stage = {
        "schema_version": 2,
        "transition_kind": "m9-candidate-adoption",
        "superseded_candidate_sha": old_sha,
        "failed_acceptance_sha256": failed_digest,
        "image_id": IMAGE_ID,
    }
    source_stage = {"schema_version": 1, "ci_run_id": RUN_ID}
    live_calls: list[dict[str, object]] = []

    monkeypatch.setattr(candidate, "ROOT_UID", os.getuid())
    monkeypatch.setattr(candidate, "ROOT_GID", os.getgid())
    monkeypatch.setattr(candidate, "_require_root", lambda: None)
    monkeypatch.setattr(candidate, "_require_root_file", lambda *args: None)
    monkeypatch.setattr(candidate, "_require_execution_release", lambda *args: None)

    def ensure_directory(path: Path, mode: int, description: str) -> None:
        del description
        path.mkdir(mode=mode, exist_ok=True)

    monkeypatch.setattr(candidate, "_require_root_directory", lambda *args: None)
    monkeypatch.setattr(candidate, "_ensure_root_directory", ensure_directory)
    monkeypatch.setattr(candidate, "_exclusive_lock", lambda path: nullcontext())
    _local_writers(monkeypatch)
    monkeypatch.setattr(
        candidate,
        "_load_stage",
        lambda **kwargs: (
            target_stage
            if kwargs["target_sha"] == TARGET_SHA
            else source_stage
        ),
    )
    monkeypatch.setattr(
        candidate,
        "_load_adoption_predecessor_binding",
        lambda **kwargs: dict(predecessor),
    )
    monkeypatch.setattr(
        candidate,
        "_read_current_target",
        lambda current_link, root: root / SOURCE_SHA,
    )
    runtime_events: list[str] = []
    monkeypatch.setattr(
        candidate,
        "_retirement_source_runtime_context",
        lambda **kwargs: (
            SimpleNamespace(),
            SimpleNamespace(),
            {"GATEA_LOOPBACK_PORT": "18080"},
        ),
    )
    monkeypatch.setattr(
        candidate,
        "_stop_retirement_writers",
        lambda **kwargs: runtime_events.append("stopped"),
    )
    monkeypatch.setattr(
        candidate,
        "_restore_retirement_runtime",
        lambda **kwargs: runtime_events.append("restored"),
    )

    def live_verification(**kwargs: object) -> dict[str, object]:
        live_calls.append(kwargs)
        return _retirement_live_evidence()

    monkeypatch.setattr(
        candidate, "_retirement_live_verification", live_verification
    )
    pending = candidate._retirement_pending_path(release_records, TARGET_SHA)
    record = candidate._retirement_record_path(release_records, TARGET_SHA)
    archive = candidate._retirement_archive_path(
        archive_dir, old_sha, failed_digest
    )
    arguments = {
        "source_candidate_sha": old_sha,
        "lineage_source_candidate_sha": SOURCE_SHA,
        "target_sha": TARGET_SHA,
        "failed_acceptance_sha256": failed_digest,
        "confirm_source_sha": old_sha,
        "confirm_lineage_source_sha": SOURCE_SHA,
        "confirm_target_sha": TARGET_SHA,
        "confirm_failed_acceptance_sha256": failed_digest,
        "config_file": tmp_path / "config.env",
        "secret_dir": tmp_path / "secrets",
        "release_root": release_root,
        "release_record_dir": release_records,
        "acceptance_record_dir": acceptance_records,
        "acceptance_failure_archive_dir": archive_dir,
        "current_link": tmp_path / "current",
        "lock_file": tmp_path / "operation.lock",
    }
    return SimpleNamespace(
        arguments=arguments,
        release_root=release_root,
        canonical=canonical,
        pending=pending,
        record=record,
        archive=archive,
        archive_dir=archive_dir,
        acceptance_records=acceptance_records,
        release_records=release_records,
        failed_payload=failed_payload,
        failed_digest=failed_digest,
        predecessor=predecessor,
        target_stage=target_stage,
        source_stage=source_stage,
        live_calls=live_calls,
        runtime_events=runtime_events,
    )


def _takeover_retirement_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> SimpleNamespace:
    case = _retirement_case(monkeypatch, tmp_path)
    superseded_sha = "c" * 40
    superseded_image_id = "sha256:" + "c" * 64
    retirement_archive_dir = tmp_path / "retirement-failures"
    superseded_stage_path = candidate._stage_record_path(
        case.release_records, superseded_sha
    )
    superseded_stage_path.write_text("superseded-stage\n", encoding="utf-8")
    superseded_stage_path.chmod(0o644)
    superseded_stage_sha256 = candidate._sha256(superseded_stage_path)
    superseded_stage = {
        "schema_version": 2,
        "record_type": "gatea-candidate-stage",
        "passed": True,
        "candidate_sha": superseded_sha,
        "image_id": superseded_image_id,
        "transition_kind": "m9-candidate-adoption",
        "superseded_candidate_sha": case.arguments["source_candidate_sha"],
        "failed_acceptance_sha256": case.failed_digest,
        "secret_values_recorded": False,
    }
    superseded_pending_path = candidate._retirement_pending_path(
        case.release_records, superseded_sha
    )
    superseded_pending = {
        "schema_version": 1,
        "record_type": "gatea-m9-failed-acceptance-retirement-pending",
        "candidate_sha": superseded_sha,
        "image_id": superseded_image_id,
        **case.predecessor,
        "stage_record_sha256": superseded_stage_sha256,
        "acceptance_pending_sha256": case.failed_digest,
        "acceptance_attempt_id_sha256": case.failed_payload[
            "attempt_id_sha256"
        ],
        "acceptance_archive_path": str(case.archive),
        "acceptance_archive_sha256": case.failed_digest,
        "live_verification": None,
        "started_at": "2026-09-11T01:00:00+00:00",
        "phase": "prepared",
        "secret_values_recorded": False,
    }
    candidate._write_json_exclusive(
        superseded_pending_path, superseded_pending, 0o600
    )
    superseded_pending_sha256 = candidate._sha256(superseded_pending_path)
    superseded_archive_path = candidate._retirement_journal_archive_path(
        retirement_archive_dir,
        superseded_sha,
        superseded_pending_sha256,
    )
    target_stage = {
        **case.target_stage,
        "schema_version": 3,
        "recovery_kind": "prepared-retirement-takeover",
        "superseded_retirement_candidate_sha": superseded_sha,
        "superseded_retirement_stage_record_sha256": (
            superseded_stage_sha256
        ),
        "superseded_retirement_pending_sha256": (
            superseded_pending_sha256
        ),
    }

    def load_stage(**kwargs: object) -> dict[str, object]:
        selected = kwargs["target_sha"]
        if selected == TARGET_SHA:
            return dict(target_stage)
        if selected == superseded_sha:
            return dict(superseded_stage)
        return dict(case.source_stage)

    monkeypatch.setattr(candidate, "_load_stage", load_stage)
    case.arguments.update(
        {
            "superseded_retirement_candidate_sha": superseded_sha,
            "superseded_retirement_stage_record_sha256": (
                superseded_stage_sha256
            ),
            "superseded_retirement_pending_sha256": (
                superseded_pending_sha256
            ),
            "confirm_superseded_retirement_candidate_sha": superseded_sha,
            "confirm_superseded_retirement_stage_record_sha256": (
                superseded_stage_sha256
            ),
            "confirm_superseded_retirement_pending_sha256": (
                superseded_pending_sha256
            ),
            "retirement_failure_archive_dir": retirement_archive_dir,
        }
    )
    case.superseded_sha = superseded_sha
    case.superseded_pending = superseded_pending_path
    case.superseded_pending_payload = superseded_pending
    case.superseded_pending_sha256 = superseded_pending_sha256
    case.superseded_archive = superseded_archive_path
    case.retirement_archive_dir = retirement_archive_dir
    case.target_stage = target_stage
    return case


@pytest.mark.parametrize(
    "drift",
    (
        "stage-digest",
        "pending-digest",
        "past-prepared",
        "superseded-final",
        "superseded-archive",
        "acceptance-archive",
    ),
)
def test_prepared_retirement_takeover_stage_requires_pristine_exact_b(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
) -> None:
    case = _takeover_retirement_case(monkeypatch, tmp_path)
    expected_stage_sha256 = case.arguments[
        "superseded_retirement_stage_record_sha256"
    ]
    expected_pending_sha256 = case.superseded_pending_sha256
    if drift == "stage-digest":
        expected_stage_sha256 = "9" * 64
    elif drift == "pending-digest":
        expected_pending_sha256 = "8" * 64
    elif drift == "past-prepared":
        changed = dict(case.superseded_pending_payload)
        changed["phase"] = "write-free-verified"
        changed["live_verification"] = _retirement_live_evidence()
        case.superseded_pending.write_text(
            json.dumps(
                changed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        expected_pending_sha256 = candidate._sha256(case.superseded_pending)
    elif drift == "superseded-final":
        candidate._retirement_record_path(
            case.release_records, case.superseded_sha
        ).write_text("{}\n", encoding="utf-8")
    elif drift == "superseded-archive":
        case.retirement_archive_dir.mkdir(mode=0o700)
        case.superseded_archive.write_bytes(case.superseded_pending.read_bytes())
        case.superseded_archive.chmod(0o600)
    else:
        case.archive_dir.mkdir(mode=0o700)
        case.archive.write_bytes(case.canonical.read_bytes())
        case.archive.chmod(0o600)

    with pytest.raises(candidate.GateACandidateError):
        candidate._validate_prepared_retirement_takeover(
            release_root=case.release_root,
            release_record_dir=case.release_records,
            acceptance_failure_archive_dir=case.archive_dir,
            retirement_failure_archive_dir=case.retirement_archive_dir,
            source_candidate_sha=case.arguments["source_candidate_sha"],
            failed_acceptance=case.failed_payload,
            failed_acceptance_sha256=case.failed_digest,
            superseded_retirement_candidate_sha=case.superseded_sha,
            expected_stage_record_sha256=str(expected_stage_sha256),
            expected_pending_sha256=str(expected_pending_sha256),
            require_unarchived=True,
        )


def test_retire_failed_acceptance_takes_over_exact_prepared_retirement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _takeover_retirement_case(monkeypatch, tmp_path)
    original_acceptance = case.canonical.read_bytes()
    original_superseded = case.superseded_pending.read_bytes()

    first = candidate.retire_failed_acceptance(**case.arguments)

    assert first["schema_version"] == 2
    assert first["recovery_kind"] == "prepared-retirement-takeover"
    assert first["superseded_retirement_candidate_sha"] == case.superseded_sha
    assert (
        first["superseded_retirement_pending_sha256"]
        == case.superseded_pending_sha256
    )
    assert not case.superseded_pending.exists()
    assert not case.canonical.exists()
    assert not case.pending.exists()
    assert case.superseded_archive.read_bytes() == original_superseded
    assert case.archive.read_bytes() == original_acceptance
    assert case.record.exists()

    replay = candidate.retire_failed_acceptance(**case.arguments)

    assert replay == first
    assert len(case.live_calls) == 1
    assert case.runtime_events == ["stopped", "restored"]

    adoption = candidate._load_adoption_context(
        release_root=case.release_root,
        release_record_dir=case.release_records,
        source_candidate_sha=case.arguments["source_candidate_sha"],
        lineage_source_candidate_sha=SOURCE_SHA,
        target_sha=TARGET_SHA,
        acceptance_retirement_record_sha256=candidate._sha256(case.record),
        acceptance_record_dir=case.acceptance_records,
        acceptance_failure_archive_dir=case.archive_dir,
        retirement_failure_archive_dir=case.retirement_archive_dir,
    )
    assert adoption["retirement"] == first
    assert adoption["takeover"]["candidate_sha"] == case.superseded_sha


@pytest.mark.parametrize(
    "failure_point",
    (
        "pending-published",
        "write-free-phase-published",
        "superseded-archive-published",
        "superseded-archive-phase-published",
        "acceptance-archive-published",
        "acceptance-archive-phase-published",
        "record-published",
        "record-phase-published",
        "superseded-pending-unlinked",
        "superseded-removed-phase-published",
        "acceptance-pending-unlinked",
        "canonical-removed-phase-published",
        "runtime-restored-phase-published",
        "own-pending-unlinked",
    ),
)
def test_takeover_retirement_recovers_every_durable_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_point: str,
) -> None:
    case = _takeover_retirement_case(monkeypatch, tmp_path)
    fsync_calls: list[Path] = []
    monkeypatch.setattr(
        candidate,
        "_fsync_directory",
        lambda path: fsync_calls.append(path),
    )
    base_write_bytes = candidate._write_bytes_exclusive
    base_write_json = candidate._write_json_exclusive
    base_atomic_json = candidate._atomic_replace_json
    base_unlink_exact = candidate._unlink_exact_protected_file
    base_path_unlink = Path.unlink
    raised = False

    if failure_point == "pending-published":

        def fail_pending_write(
            path: Path,
            payload: dict[str, object],
            mode: int = 0o644,
        ) -> None:
            nonlocal raised
            base_write_json(path, payload, mode)
            if path == case.pending and not raised:
                raised = True
                raise RuntimeError("injected takeover boundary")

        monkeypatch.setattr(candidate, "_write_json_exclusive", fail_pending_write)
    elif failure_point in {
        "write-free-phase-published",
        "superseded-archive-phase-published",
        "acceptance-archive-phase-published",
        "record-phase-published",
        "superseded-removed-phase-published",
        "canonical-removed-phase-published",
        "runtime-restored-phase-published",
    }:
        phase_by_failure = {
            "write-free-phase-published": "write-free-verified",
            "superseded-archive-phase-published": (
                "superseded-retirement-archived"
            ),
            "acceptance-archive-phase-published": "acceptance-archived",
            "record-phase-published": "record-published",
            "superseded-removed-phase-published": (
                "superseded-retirement-removed"
            ),
            "canonical-removed-phase-published": "canonical-removed",
            "runtime-restored-phase-published": "runtime-restored",
        }
        expected_phase = phase_by_failure[failure_point]

        def fail_phase(
            path: Path,
            payload: dict[str, object],
            mode: int,
        ) -> None:
            nonlocal raised
            base_atomic_json(path, payload, mode)
            if (
                path == case.pending
                and payload.get("phase") == expected_phase
                and not raised
            ):
                raised = True
                raise RuntimeError("injected takeover boundary")

        monkeypatch.setattr(candidate, "_atomic_replace_json", fail_phase)
    elif failure_point in {
        "superseded-archive-published",
        "acceptance-archive-published",
    }:
        expected_path = (
            case.superseded_archive
            if failure_point == "superseded-archive-published"
            else case.archive
        )

        def fail_archive(path: Path, content: bytes, mode: int) -> None:
            nonlocal raised
            base_write_bytes(path, content, mode)
            if path == expected_path and not raised:
                raised = True
                raise RuntimeError("injected takeover boundary")

        monkeypatch.setattr(candidate, "_write_bytes_exclusive", fail_archive)
    elif failure_point == "record-published":

        def fail_record(
            path: Path,
            payload: dict[str, object],
            mode: int = 0o644,
        ) -> None:
            nonlocal raised
            base_write_json(path, payload, mode)
            if path == case.record and not raised:
                raised = True
                raise RuntimeError("injected takeover boundary")

        monkeypatch.setattr(candidate, "_write_json_exclusive", fail_record)
    elif failure_point in {
        "superseded-pending-unlinked",
        "acceptance-pending-unlinked",
    }:
        expected_path = (
            case.superseded_pending
            if failure_point == "superseded-pending-unlinked"
            else case.canonical
        )

        def fail_exact_unlink(
            path: Path,
            identity: tuple[int, ...],
            *,
            description: str,
        ) -> None:
            nonlocal raised
            base_unlink_exact(path, identity, description=description)
            if path == expected_path and not raised:
                raised = True
                raise RuntimeError("injected takeover boundary")

        monkeypatch.setattr(
            candidate, "_unlink_exact_protected_file", fail_exact_unlink
        )
    else:

        def fail_own_unlink(
            path: Path,
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal raised
            base_path_unlink(path, *args, **kwargs)
            if path == case.pending and not raised:
                raised = True
                raise RuntimeError("injected takeover boundary")

        monkeypatch.setattr(Path, "unlink", fail_own_unlink)

    with pytest.raises(RuntimeError, match="takeover boundary"):
        candidate.retire_failed_acceptance(**case.arguments)
    assert raised is True

    monkeypatch.setattr(candidate, "_write_bytes_exclusive", base_write_bytes)
    monkeypatch.setattr(candidate, "_write_json_exclusive", base_write_json)
    monkeypatch.setattr(candidate, "_atomic_replace_json", base_atomic_json)
    monkeypatch.setattr(
        candidate, "_unlink_exact_protected_file", base_unlink_exact
    )
    monkeypatch.setattr(Path, "unlink", base_path_unlink)

    fsync_count_before_recovery = len(fsync_calls)
    recovered = candidate.retire_failed_acceptance(**case.arguments)

    assert recovered["passed"] is True
    assert not case.superseded_pending.exists()
    assert not case.canonical.exists()
    assert not case.pending.exists()
    assert case.superseded_archive.exists()
    assert case.archive.exists()
    assert case.record.exists()
    expected_live_calls = (
        1
        if failure_point in {"pending-published", "own-pending-unlinked"}
        else 2
    )
    assert len(case.live_calls) == expected_live_calls
    if failure_point == "own-pending-unlinked":
        assert len(fsync_calls) == fsync_count_before_recovery + 1
        assert fsync_calls[-1] == case.release_records


@pytest.mark.parametrize(
    "drift",
    (
        "missing",
        "tampered",
        "hardlink",
        "superseded-stage",
        "successful-acceptance",
    ),
)
def test_takeover_archives_remain_protected_downstream_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
) -> None:
    case = _takeover_retirement_case(monkeypatch, tmp_path)
    candidate.retire_failed_acceptance(**case.arguments)

    if drift == "missing":
        case.superseded_archive.unlink()
    elif drift == "tampered":
        case.superseded_archive.write_bytes(b"{}\n")
        case.superseded_archive.chmod(0o600)
    elif drift == "hardlink":
        os.link(case.superseded_archive, tmp_path / "retirement-alias.json")
    elif drift == "superseded-stage":
        candidate._stage_record_path(
            case.release_records, case.superseded_sha
        ).write_text("changed-stage\n", encoding="utf-8")
    else:
        (case.acceptance_records / (
            "gatea-m9-runtime-acceptance-"
            f"{case.arguments['source_candidate_sha']}.json"
        )).write_text("{}\n", encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError):
        candidate._load_adoption_context(
            release_root=case.release_root,
            release_record_dir=case.release_records,
            source_candidate_sha=case.arguments["source_candidate_sha"],
            lineage_source_candidate_sha=SOURCE_SHA,
            target_sha=TARGET_SHA,
            acceptance_retirement_record_sha256=candidate._sha256(case.record),
            acceptance_record_dir=case.acceptance_records,
            acceptance_failure_archive_dir=case.archive_dir,
            retirement_failure_archive_dir=case.retirement_archive_dir,
        )


@pytest.mark.parametrize(
    ("phase", "observed"),
    [
        pytest.param(
            "prepared",
            (False, False, True, False, False),
            id="prepared-without-b",
        ),
        pytest.param(
            "write-free-verified",
            (True, True, True, True, False),
            id="write-free-skips-ahead",
        ),
        pytest.param(
            "acceptance-archived",
            (False, True, True, True, False),
            id="a-archive-with-b-removed-too-soon",
        ),
        pytest.param(
            "record-published",
            (False, True, False, True, True),
            id="both-canonicals-removed-too-soon",
        ),
        pytest.param(
            None,
            (True, True, False, True, True),
            id="completed-c-still-has-b-pending",
        ),
    ],
)
def test_takeover_retirement_recovery_shape_rejects_impossible_mixtures(
    phase: str | None,
    observed: tuple[bool, bool, bool, bool, bool],
) -> None:
    with pytest.raises(candidate.GateACandidateError, match="inconsistent"):
        candidate._validate_takeover_retirement_recovery_shape(
            phase=phase,
            superseded_pending_exists=observed[0],
            superseded_archive_exists=observed[1],
            acceptance_pending_exists=observed[2],
            acceptance_archive_exists=observed[3],
            retirement_record_exists=observed[4],
        )


def test_retire_failed_acceptance_first_success_and_success_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = _retirement_case(monkeypatch, tmp_path)
    raw_pending = case.canonical.read_bytes()

    first = candidate.retire_failed_acceptance(**case.arguments)

    assert first["passed"] is True
    assert first["phase"] == "record-published"
    assert not case.canonical.exists()
    assert not case.pending.exists()
    assert case.archive.read_bytes() == raw_pending
    assert case.record.exists()
    assert len(case.live_calls) == 1
    assert case.runtime_events == ["stopped", "restored"]

    replay = candidate.retire_failed_acceptance(**case.arguments)

    assert replay == first
    assert len(case.live_calls) == 1
    assert case.runtime_events == ["stopped", "restored"]
    assert not case.canonical.exists()
    assert not case.pending.exists()


def test_retirement_success_replay_rejects_archive_parent_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = _retirement_case(monkeypatch, tmp_path)
    candidate.retire_failed_acceptance(**case.arguments)
    real_archive_dir = tmp_path / "real-acceptance-failures"
    case.archive_dir.rename(real_archive_dir)
    case.archive_dir.symlink_to(real_archive_dir, target_is_directory=True)

    def require_local_protected_directory(
        path: Path,
        mode: int,
        description: str,
    ) -> None:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
        ):
            raise candidate.GateACandidateError(
                f"{description} is not a protected directory"
            )

    monkeypatch.setattr(
        candidate,
        "_require_root_directory",
        require_local_protected_directory,
    )

    with pytest.raises(candidate.GateACandidateError, match="protected directory"):
        candidate.retire_failed_acceptance(**case.arguments)

    assert len(case.live_calls) == 1
    assert case.record.exists()
    assert case.runtime_events == ["stopped", "restored"]
    assert not case.canonical.exists()
    assert not case.pending.exists()


@pytest.mark.parametrize(
    "failure_point",
    (
        "pending-published",
        "write-free-phase-published",
        "archive-published",
        "archive-phase-published",
        "record-published",
        "record-phase-published",
        "canonical-unlinked",
        "canonical-phase-published",
        "runtime-restored-published",
        "own-pending-unlinked",
    ),
)
def test_retire_failed_acceptance_recovers_every_durable_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_point: str,
) -> None:
    case = _retirement_case(monkeypatch, tmp_path)
    base_write_bytes = candidate._write_bytes_exclusive
    base_write_json = candidate._write_json_exclusive
    base_atomic_json = candidate._atomic_replace_json
    base_unlink_exact = candidate._unlink_exact_protected_file
    base_path_unlink = Path.unlink
    raised = False

    if failure_point == "pending-published":

        def fail_write_json(
            path: Path,
            payload: dict[str, object],
            mode: int = 0o644,
        ) -> None:
            nonlocal raised
            base_write_json(path, payload, mode)
            if path == case.pending and not raised:
                raised = True
                raise RuntimeError("injected pending publication crash")

        monkeypatch.setattr(candidate, "_write_json_exclusive", fail_write_json)
    elif failure_point in {
        "write-free-phase-published",
        "archive-phase-published",
        "record-phase-published",
        "canonical-phase-published",
        "runtime-restored-published",
    }:
        phase_by_failure = {
            "write-free-phase-published": "write-free-verified",
            "archive-phase-published": "acceptance-archived",
            "record-phase-published": "record-published",
            "canonical-phase-published": "canonical-removed",
            "runtime-restored-published": "runtime-restored",
        }
        expected_phase = phase_by_failure[failure_point]

        def fail_phase(
            path: Path,
            payload: dict[str, object],
            mode: int,
        ) -> None:
            nonlocal raised
            base_atomic_json(path, payload, mode)
            if (
                path == case.pending
                and payload.get("phase") == expected_phase
                and not raised
            ):
                raised = True
                raise RuntimeError("injected phase publication crash")

        monkeypatch.setattr(candidate, "_atomic_replace_json", fail_phase)
    elif failure_point == "archive-published":

        def fail_archive(path: Path, content: bytes, mode: int) -> None:
            nonlocal raised
            base_write_bytes(path, content, mode)
            if path == case.archive and not raised:
                raised = True
                raise RuntimeError("injected archive publication crash")

        monkeypatch.setattr(candidate, "_write_bytes_exclusive", fail_archive)
    elif failure_point == "record-published":

        def fail_record(path: Path, content: bytes, mode: int) -> None:
            nonlocal raised
            base_write_bytes(path, content, mode)
            if path == case.record and not raised:
                raised = True
                raise RuntimeError("injected record publication crash")

        monkeypatch.setattr(candidate, "_write_bytes_exclusive", fail_record)
    elif failure_point == "canonical-unlinked":

        def fail_canonical_unlink(
            path: Path,
            identity: tuple[int, ...],
            *,
            description: str,
        ) -> None:
            nonlocal raised
            base_unlink_exact(path, identity, description=description)
            if path == case.canonical and not raised:
                raised = True
                raise RuntimeError("injected canonical unlink crash")

        monkeypatch.setattr(
            candidate, "_unlink_exact_protected_file", fail_canonical_unlink
        )
    else:

        def fail_own_pending_unlink(
            path: Path,
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal raised
            base_path_unlink(path, *args, **kwargs)
            if path == case.pending and not raised:
                raised = True
                raise RuntimeError("injected own pending unlink crash")

        monkeypatch.setattr(Path, "unlink", fail_own_pending_unlink)

    with pytest.raises(RuntimeError, match="injected"):
        candidate.retire_failed_acceptance(**case.arguments)
    assert raised is True

    monkeypatch.setattr(candidate, "_write_bytes_exclusive", base_write_bytes)
    monkeypatch.setattr(candidate, "_write_json_exclusive", base_write_json)
    monkeypatch.setattr(candidate, "_atomic_replace_json", base_atomic_json)
    monkeypatch.setattr(
        candidate, "_unlink_exact_protected_file", base_unlink_exact
    )
    monkeypatch.setattr(Path, "unlink", base_path_unlink)

    recovered = candidate.retire_failed_acceptance(**case.arguments)

    assert recovered["passed"] is True
    assert not case.canonical.exists()
    assert not case.pending.exists()
    assert case.archive.exists()
    assert case.record.exists()
    expected_live_calls = (
        1
        if failure_point in {"pending-published", "own-pending-unlinked"}
        else 2
    )
    assert len(case.live_calls) == expected_live_calls


def test_retire_failed_acceptance_live_failure_restores_runtime_and_keeps_recovery_journal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = _retirement_case(monkeypatch, tmp_path)
    monkeypatch.setattr(
        candidate,
        "_retirement_live_verification",
        lambda **kwargs: (_ for _ in ()).throw(
            candidate.GateACandidateError("live verifier failed")
        ),
    )

    with pytest.raises(candidate.GateACandidateError, match="live verifier"):
        candidate.retire_failed_acceptance(**case.arguments)

    assert case.canonical.exists()
    assert case.pending.exists()
    assert json.loads(case.pending.read_text())["phase"] == "prepared"
    assert not case.record.exists()
    assert not case.archive.exists()
    assert not case.archive_dir.exists()
    assert case.runtime_events == ["stopped", "restored"]


def test_retire_failed_acceptance_recovery_reverifies_and_rejects_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = _retirement_case(monkeypatch, tmp_path)
    base_write_bytes = candidate._write_bytes_exclusive
    crashed = False

    def crash_after_archive(path: Path, content: bytes, mode: int) -> None:
        nonlocal crashed
        base_write_bytes(path, content, mode)
        if path == case.archive and not crashed:
            crashed = True
            raise RuntimeError("injected archive crash")

    monkeypatch.setattr(candidate, "_write_bytes_exclusive", crash_after_archive)
    with pytest.raises(RuntimeError, match="archive crash"):
        candidate.retire_failed_acceptance(**case.arguments)
    monkeypatch.setattr(candidate, "_write_bytes_exclusive", base_write_bytes)

    drifted = _retirement_live_evidence()
    drifted["wallet_reconcile"] = {
        "scanned": 2,
        "mismatches": 0,
        "violations": 0,
    }

    def drifted_verification(**kwargs: object) -> dict[str, object]:
        case.live_calls.append(kwargs)
        return drifted

    monkeypatch.setattr(
        candidate, "_retirement_live_verification", drifted_verification
    )
    with pytest.raises(candidate.GateACandidateError, match="drifted"):
        candidate.retire_failed_acceptance(**case.arguments)

    assert case.canonical.exists()
    assert case.pending.exists()
    assert not case.record.exists()
    assert case.runtime_events == [
        "stopped",
        "restored",
        "stopped",
        "restored",
    ]
    assert len(case.live_calls) == 2


def test_retire_failed_acceptance_recovery_failure_wins_and_keeps_blocker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = _retirement_case(monkeypatch, tmp_path)
    work_error = ValueError("injected work failure")
    recovery_error = OSError("injected recovery failure")
    monkeypatch.setattr(
        candidate,
        "_retirement_live_verification",
        lambda **kwargs: (_ for _ in ()).throw(work_error),
    )
    monkeypatch.setattr(
        candidate,
        "_restore_retirement_runtime",
        lambda **kwargs: (_ for _ in ()).throw(recovery_error),
    )

    with pytest.raises(
        candidate.GateACandidateError,
        match="source runtime recovery failed",
    ) as caught:
        candidate.retire_failed_acceptance(**case.arguments)

    assert caught.value.__cause__ is recovery_error
    assert case.pending.exists()
    assert case.canonical.exists()
    assert not case.record.exists()


def test_restore_retirement_runtime_uses_exact_allowances_and_reproves_a_m9(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_sha = "a" * 40
    source_image_id = "sha256:" + "a" * 64
    transition_allowance = object()
    acceptance_allowance = object()
    values = {
        "GATEA_APP_IMAGE": "pinkdoohub-gatea:old",
        "GATEA_LOOPBACK_PORT": "18080",
        "TABLE_SESSION_CLAIMS_ENABLED": "true",
    }
    calls: list[tuple[str, object]] = []

    class FakeGateA:
        APPROVED_TARGET_M9_CHAIN = tuple(M9_CHAIN)

        @staticmethod
        def app_up(**kwargs: object) -> None:
            calls.append(("app-up", dict(kwargs)))

        @staticmethod
        def _validated_inputs(**kwargs: object) -> dict[str, str]:
            assert kwargs["require_available_port"] is False
            calls.append(("inputs", kwargs.get("mode")))
            return dict(values)

        @staticmethod
        def _candidate_sha(current_values: object) -> str:
            assert current_values == values
            return source_sha

        @staticmethod
        def validate_app_image(
            current_values: object,
            *,
            start_new_session: bool,
        ) -> str:
            assert current_values == values
            assert start_new_session is True
            calls.append(("image", start_new_session))
            return source_image_id

        @staticmethod
        def read_database_snapshot(**kwargs: object) -> dict[str, object]:
            assert kwargs["start_new_session"] is True
            calls.append(("database", kwargs["start_new_session"]))
            return {"aerich_versions": list(M9_CHAIN)}

        @staticmethod
        def _compose_ps(**kwargs: object) -> list[dict[str, object]]:
            assert kwargs["start_new_session"] is True
            assert kwargs["services"] == candidate.M9_RUNTIME_SERVICES
            calls.append(("compose-ps", kwargs["services"]))
            return []

        @staticmethod
        def _ensure_services_healthy(rows: object, *services: str) -> None:
            assert rows == []
            assert services == candidate.M9_RUNTIME_SERVICES
            calls.append(("healthy", services))

        @staticmethod
        def _validate_loopback_publishers(rows: object, port: int) -> None:
            assert rows == []
            calls.append(("publishers", port))

    monkeypatch.setattr(
        candidate,
        "_validated_retirement_recovery_allowances",
        lambda **kwargs: (
            transition_allowance,
            acceptance_allowance,
            None,
        ),
    )
    monkeypatch.setattr(
        candidate,
        "_read_current_target",
        lambda current_link, release_root: release_root / SOURCE_SHA,
    )

    candidate._restore_retirement_runtime(
        gatea=FakeGateA,
        values=values,
        config_file=tmp_path / "config.env",
        secret_dir=tmp_path / "secrets",
        release_root=tmp_path / "releases",
        release_record_dir=tmp_path / "records",
        acceptance_record_dir=tmp_path / "acceptance",
        current_link=tmp_path / "current",
        source_candidate_sha=source_sha,
        source_image_id=source_image_id,
        lineage_source_candidate_sha=SOURCE_SHA,
        target_sha=TARGET_SHA,
        failed_acceptance_sha256="b" * 64,
        pending_path=tmp_path / "retirement.pending.json",
        expected_binding={"candidate_sha": TARGET_SHA},
    )

    app_up = calls[0]
    assert app_up[0] == "app-up"
    app_up_kwargs = app_up[1]
    assert isinstance(app_up_kwargs, dict)
    assert app_up_kwargs["candidate_transition_recovery"] is transition_allowance
    assert app_up_kwargs["acceptance_sidecar_recovery"] is acceptance_allowance
    assert app_up_kwargs["include_table_sweeper"] is True
    assert app_up_kwargs["allow_existing_gatea_publisher"] is True
    assert app_up_kwargs["_start_new_session"] is True
    assert ("database", True) in calls
    assert ("compose-ps", candidate.M9_RUNTIME_SERVICES) in calls
    assert ("healthy", candidate.M9_RUNTIME_SERVICES) in calls
    assert ("publishers", 18080) in calls


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
def test_retirement_work_signal_restores_before_propagation_and_defers_next_signal(
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

    monkeypatch.setattr(candidate, "_restore_retirement_runtime", restore)

    with pytest.raises(expected_type) as caught:
        with candidate._mutation_termination_controller(
            "retire-failed-acceptance"
        ) as termination:
            observed = termination

            def work() -> None:
                assert callable(active[signum])
                active[signum](signum, None)  # type: ignore[operator]

            _, work_error = candidate._run_retirement_work_then_restore(
                termination=termination,
                work=work,
                restore_arguments={},
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


def test_retirement_recovery_retries_control_error_and_propagates_it_after_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_candidate_signal_handlers(monkeypatch)
    first_interrupt = KeyboardInterrupt("injected recovery interruption")
    restore_calls = 0

    def restore(**kwargs: object) -> None:
        nonlocal restore_calls
        del kwargs
        restore_calls += 1
        if restore_calls == 1:
            raise first_interrupt

    monkeypatch.setattr(candidate, "_restore_retirement_runtime", restore)

    with pytest.raises(KeyboardInterrupt) as caught:
        with candidate._mutation_termination_controller(
            "retire-failed-acceptance"
        ) as termination:
            _, work_error = candidate._run_retirement_work_then_restore(
                termination=termination,
                work=lambda: None,
                restore_arguments={},
            )
            assert work_error is None
            propagated = candidate._finalization_error_after_recovery(
                termination=termination,
                work_error=work_error,
            )
            assert propagated is first_interrupt
            raise propagated

    assert caught.value is first_interrupt
    assert restore_calls == 2


def test_retirement_stops_writers_before_every_live_domain_read_and_detects_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[str] = []
    values = {
        "GATEA_APP_IMAGE": "source-image",
        "TABLE_SESSION_CLAIMS_ENABLED": "true",
    }
    source_sha = "a" * 40
    source_image_id = "sha256:" + "a" * 64

    class FakeGateA:
        APPROVED_TARGET_M9_CHAIN = tuple(M9_CHAIN)

        @staticmethod
        def _validated_inputs(**kwargs: object) -> dict[str, str]:
            events.append("inputs")
            return dict(values)

        @staticmethod
        def _candidate_sha(current: object) -> str:
            return source_sha

        @staticmethod
        def validate_app_image(current: object) -> str:
            events.append("image")
            return source_image_id

        @staticmethod
        def _run_compose(**kwargs: object) -> None:
            assert kwargs["arguments"] == (
                "stop",
                "--timeout",
                "30",
                *candidate.RETIREMENT_WRITER_SERVICES,
            )
            events.append("stop")

        @staticmethod
        def _compose_ps(**kwargs: object) -> list[dict[str, object]]:
            events.append("ps")
            return [
                {
                    "Service": service,
                    "State": (
                        "running"
                        if service in candidate.RETIREMENT_DATABASE_SERVICES
                        else "exited"
                    ),
                    "Health": (
                        "healthy"
                        if service in candidate.RETIREMENT_DATABASE_SERVICES
                        else ""
                    ),
                }
                for service in candidate.M9_RUNTIME_SERVICES
            ]

        @staticmethod
        def _ensure_services_healthy(rows: object, *services: str) -> None:
            assert services == candidate.RETIREMENT_DATABASE_SERVICES
            events.append("database-healthy")

        @staticmethod
        def read_database_snapshot(**kwargs: object) -> dict[str, object]:
            events.append("database-read")
            return {"aerich_versions": M9_CHAIN}

        @staticmethod
        def _run_m9_table_reconcile(**kwargs: object) -> dict[str, int]:
            events.append("table-read")
            return dict(EMPTY_TABLE_RECONCILE)

    class FakeUpgrade:
        @staticmethod
        def _ensure_not_running(rows: object, *services: str) -> None:
            assert services == candidate.RETIREMENT_WRITER_SERVICES
            assert all(
                row["State"] == "exited"  # type: ignore[index]
                for row in rows  # type: ignore[union-attr]
                if row["Service"] in services  # type: ignore[index]
            )
            events.append("writers-stopped")

    monkeypatch.setattr(
        candidate,
        "_read_current_target",
        lambda link, root: root / SOURCE_SHA,
    )
    monkeypatch.setattr(
        candidate,
        "_final_wallet_reconcile",
        lambda **kwargs: events.append("wallet-read")
        or {"scanned": 1, "mismatches": 0, "violations": 0},
    )
    monkeypatch.setattr(
        candidate,
        "_failed_acceptance_business_verification",
        lambda **kwargs: events.append("business-read")
        or _retirement_live_evidence()["business_verification"],
    )
    common = {
        "gatea": FakeGateA,
        "upgrade": FakeUpgrade,
        "values": values,
        "config_file": tmp_path / "config",
        "secret_dir": tmp_path / "secrets",
        "current_link": tmp_path / "current",
        "release_root": tmp_path / "releases",
        "source_candidate_sha": source_sha,
        "source_image_id": source_image_id,
        "lineage_source_candidate_sha": SOURCE_SHA,
    }

    candidate._stop_retirement_writers(**common)
    candidate._retirement_live_verification(
        **common,
        target_image_id=IMAGE_ID,
        failed_acceptance=_preclaim_failure_payload(source_sha),
    )

    assert events.index("stop") < events.index("database-read")
    for read_event in ("database-read", "table-read", "wallet-read", "business-read"):
        read_index = events.index(read_event)
        assert "writers-stopped" in events[:read_index]
        assert events[read_index - 1] == "writers-stopped"

    original_ps = FakeGateA._compose_ps
    calls = 0

    def restarted_ps(**kwargs: object) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        rows = original_ps(**kwargs)
        if calls == 2:
            next(row for row in rows if row["Service"] == "app")["State"] = (
                "running"
            )
        return rows

    monkeypatch.setattr(FakeGateA, "_compose_ps", restarted_ps)
    with pytest.raises(candidate.GateACandidateError, match="write-free"):
        candidate._retirement_live_verification(
            **common,
            target_image_id=IMAGE_ID,
            failed_acceptance=_preclaim_failure_payload(source_sha),
        )


@pytest.mark.parametrize(
    "drift",
    ("missing", "tampered", "wrong-path", "file-symlink", "hardlink", "parent-symlink"),
)
def test_adoption_retirement_archive_remains_a_protected_downstream_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
) -> None:
    case = _retirement_case(monkeypatch, tmp_path)
    retirement = candidate.retire_failed_acceptance(**case.arguments)

    def require_local_protected_directory(
        path: Path, mode: int, description: str
    ) -> None:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != mode
        ):
            raise candidate.GateACandidateError(
                f"{description} is not a protected directory"
            )

    monkeypatch.setattr(
        candidate,
        "_require_root_directory",
        require_local_protected_directory,
    )
    helper_arguments = {
        "acceptance_failure_archive_dir": case.archive_dir,
        "source_candidate_sha": case.arguments["source_candidate_sha"],
        "failed_acceptance_sha256": case.arguments[
            "failed_acceptance_sha256"
        ],
        "lineage_source_candidate_sha": SOURCE_SHA,
        "source_image_id": "sha256:" + "a" * 64,
        "retirement": retirement,
    }
    assert candidate._validate_adoption_retirement_archive(
        **helper_arguments
    )["candidate_sha"] == case.arguments["source_candidate_sha"]

    if drift == "missing":
        case.archive.unlink()
    elif drift == "tampered":
        case.archive.write_bytes(b"{}\n")
    elif drift == "wrong-path":
        helper_arguments["retirement"] = {
            **retirement,
            "acceptance_archive_path": str(tmp_path / "outside.json"),
        }
    elif drift == "file-symlink":
        raw = case.archive.read_bytes()
        outside = tmp_path / "outside.json"
        outside.write_bytes(raw)
        outside.chmod(0o600)
        case.archive.unlink()
        case.archive.symlink_to(outside)
    elif drift == "hardlink":
        os.link(case.archive, tmp_path / "archive-alias.json")
    else:
        real_archive_dir = tmp_path / "real-archive"
        case.archive_dir.rename(real_archive_dir)
        case.archive_dir.symlink_to(real_archive_dir, target_is_directory=True)

    with pytest.raises(candidate.GateACandidateError):
        candidate._validate_adoption_retirement_archive(**helper_arguments)


def test_retire_failed_acceptance_rejects_impossible_or_competing_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = _retirement_case(monkeypatch, tmp_path)
    blocker = case.release_records / (
        f"{'9' * 40}.config-activation.pending.json"
    )
    blocker.write_text("{}", encoding="utf-8")

    with pytest.raises(candidate.GateACandidateError, match="blocks mutation"):
        candidate.retire_failed_acceptance(**case.arguments)
    assert case.canonical.exists()
    assert not case.archive.exists()

    blocker.unlink()
    case.archive_dir.mkdir()
    case.archive.write_bytes(case.canonical.read_bytes())
    case.archive.chmod(0o600)
    case.canonical.unlink()
    with pytest.raises(candidate.GateACandidateError, match="incomplete"):
        candidate.retire_failed_acceptance(**case.arguments)

    case.pending.write_text("{}", encoding="utf-8")
    case.pending.chmod(0o600)
    with pytest.raises(candidate.GateACandidateError, match="incomplete"):
        candidate.retire_failed_acceptance(**case.arguments)
