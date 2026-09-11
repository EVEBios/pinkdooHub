#!/usr/bin/env python3
"""Install and activate one CI-proven Gate A candidate without touching data.

The five commands in this module deliberately keep release installation,
non-Secret configuration activation, guarded pre-migration rollback, and the
``current`` operations symlink separate from database migration.  Database and
runtime changes remain owned by ``gatea_upgrade`` and the other reviewed Gate A
tools.

``stage`` is self-contained so an exact copy from the candidate archive can be
used as the temporary, checksum-confirmed launcher.  The other commands must be
run as a module from the installed versioned release directory.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import fcntl
from functools import wraps
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Callable, Iterator, Mapping, Sequence, TypeVar
import urllib.error
import urllib.parse
import urllib.request
import zipfile


SOURCE_M7_SHA = "73dca350505d43775fb1ff1158ccf6aabc221998"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_PATTERN = re.compile(r"^[1-9][0-9]*$")
BACKUP_ID_PATTERN = re.compile(r"^[0-9]{8}t[0-9]{6}z$")

DEFAULT_RELEASE_ROOT = Path("/srv/pinkdoohub/gatea/releases")
DEFAULT_STAGING_ROOT = Path("/srv/pinkdoohub/gatea/staging")
DEFAULT_RELEASE_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/releases")
DEFAULT_CONFIG_FILE = Path("/etc/pinkdoohub/gatea/config.env")
DEFAULT_CONFIG_HISTORY_DIR = Path("/etc/pinkdoohub/gatea/config-history")
DEFAULT_SECRET_DIR = Path("/etc/pinkdoohub/gatea/secrets")
DEFAULT_BACKUP_ROOT = Path("/srv/pinkdoohub/gatea/backups")
DEFAULT_BACKUP_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/backups")
DEFAULT_RESTORE_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/restores")
DEFAULT_RESILIENCE_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/resilience")
DEFAULT_ACCEPTANCE_RECORD_DIR = Path(
    "/srv/pinkdoohub/gatea/records/m9-acceptance"
)
DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR = Path(
    "/srv/pinkdoohub/gatea/records/m9-acceptance-failures"
)
DEFAULT_CURRENT_LINK = Path("/srv/pinkdoohub/gatea/current")
DEFAULT_LOCK_FILE = Path("/run/lock/pinkdoohub-gatea-operation.lock")

EXPECTED_APP_USER = "10001:10001"
EXPECTED_APP_ENTRYPOINT = ["/usr/local/bin/pinkdoo-entrypoint"]
EXPECTED_APP_COMMAND = [
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--no-server-header",
    "--no-access-log",
]
M9_RUNTIME_SERVICES = ("mysql", "redis", "app", "table-sweeper", "nginx")
M9_WRITER_SERVICES = ("nginx", "table-sweeper", "app", "image-init")
RETIREMENT_DATABASE_SERVICES = ("mysql", "redis")
RETIREMENT_WRITER_SERVICES = ("nginx", "table-sweeper", "app")
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
MAX_SOURCE_ARCHIVE_FILE_BYTES = 160 * 1024 * 1024
MAX_CI_MEMBERS = 100
MAX_CI_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_ACCEPTANCE_PENDING_BYTES = 1024 * 1024
MAX_GITHUB_RESPONSE_BYTES = 8 * 1024 * 1024
CANDIDATE_CLEANUP_ATTEMPTS = 2
ROOT_UID = 0
ROOT_GID = 0

GITHUB_API_ORIGIN = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_REPOSITORY = "EVEBios/pinkdooHub"
GITHUB_BASE_REF = "develop"
GITHUB_WORKFLOW_NAME = "CI"
GITHUB_WORKFLOW_PATH = ".github/workflows/ci.yml"
GITHUB_REQUIRED_JOBS = frozenset(
    {
        "backend-sqlite",
        "backend-mysql-release",
        "gatea-m7-m8-updater",
        "frontend-quality",
        "openapi-contract",
        "weapp-build",
        "python-dependency-audit",
        "npm-dependency-audit",
        "repository-hygiene",
    }
)
GITHUB_REQUIRED_JOBS_SHA256 = hashlib.sha256(
    ("\n".join(sorted(GITHUB_REQUIRED_JOBS)) + "\n").encode("utf-8")
).hexdigest()

REQUIRED_SOURCE_FILES = frozenset(
    {
        ".dockerignore",
        "requirements.txt",
        "pyproject.toml",
        "deploy/runtime/Dockerfile",
        "deploy/runtime/app-entrypoint.sh",
        "deploy/gatea/compose.yml",
        "deploy/gatea/compose.loopback.yml",
        "scripts/release/gatea_candidate.py",
        "scripts/release/gatea_operations.py",
        "scripts/release/gatea_backup.py",
        "scripts/release/gatea_upgrade.py",
    }
)
FORBIDDEN_SOURCE_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "artifacts",
        "backups",
        "uploads",
    }
)
CI_ARTIFACT_ALLOWLIST = frozenset(
    {
        "artifact-scan-passed.json",
        "bootstrap-record.json",
        "cleanup-report.json",
        "color-fixture.json",
        "drill-state.json",
        "images.json",
        "representative-data.json",
        "runtime-verification.json",
        "source-backup-record.json",
        "source-mard.json",
        "source-m7-verification.json",
        "source-restore-record.json",
        "summary.json",
        "target-backup-record.json",
        "target-restore-record.json",
        "upgrade-apply.json",
        "upgrade-evidence.json",
        "upgrade-plan-replay.json",
        "upgrade-plan.json",
        "upgrade-record.json",
    }
)
CI_REQUIRED_FILES = frozenset(
    {
        "artifact-scan-passed.json",
        "cleanup-report.json",
        "drill-state.json",
        "summary.json",
    }
)
UPGRADE_REPLAY_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "passed",
        "candidate_sha",
        "source_candidate_sha",
        "source_version",
        "image_id",
        "backup_id",
        "manifest_sha256",
        "upgrade_record_sha256",
        "evidence_sha256",
        "result",
        "completed_at",
        "database_snapshot",
        "image_manifest",
        "table_reconcile",
        "secret_values_recorded",
    }
)
PRECLAIM_ACCEPTANCE_RECONCILE_KEYS = frozenset(
    {
        "open_sessions",
        "occupancies",
        "closed_with_occupancy",
        "awaiting_with_timers",
        "active_without_timers",
        "scanned",
        "violations",
    }
)
PRECLAIM_ACCEPTANCE_WALLET_KEYS = frozenset(
    {"scanned", "mismatches", "violations"}
)
PRECLAIM_ACCEPTANCE_CLEANUP_KEYS = frozenset(
    {
        "order_cancelled",
        "fixture_products_offline",
        "synthetic_session_revoked",
        "super_admin_session_revoked",
    }
)
PRECLAIM_ACCEPTANCE_PENDING_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "environment",
        "candidate_sha",
        "image_id",
        "operations_sha",
        "ci_run_id",
        "source_candidate_sha",
        "upgrade_record_sha256",
        "upgrade_plan_replay_record_sha256",
        "representative_record_sha256",
        "credentials_sha256",
        "started_at",
        "attempt_id",
        "attempt_id_sha256",
        "updated_at",
        "stage",
        "pre_reconcile",
        "pre_wallet_reconcile",
        "fixture_ids",
        "fixture",
        "fixture_sha256",
        "order_id",
        "order_evidence",
        "order_evidence_sha256",
        "table_no",
        "session_no_sha256",
        "payment_deadline_offset_seconds",
        "payment_evidence",
        "timer_evidence",
        "claim_replay_verified",
        "payment_replay_verified",
        "admin_visibility_verified",
        "release_replay_verified",
        "payment_committed",
        "session_released",
        "cleanup",
        "failure",
        "secret_values_recorded",
        "source_volume_restored",
        "passed",
    }
)
PRECLAIM_ACCEPTANCE_FIXTURE_KEYS = frozenset(
    {
        "experience_product_id",
        "kit_product_id",
        "option_ids",
        "option_durations_minutes",
        "option_participants",
        "option_price",
        "kit_price",
        "kit_opening_stock",
        "product_images_created",
        "option_images_created",
        "products_online",
    }
)
PRECLAIM_ACCEPTANCE_ORDER_KEYS = frozenset(
    {
        "order_id",
        "expected_timer_items",
        "kit_order_item_id",
        "eligible_duration_groups",
    }
)
PRECLAIM_ACCEPTANCE_TIMER_ITEM_KEYS = frozenset(
    {"order_item_id", "duration_minutes", "quantity"}
)
RETIREMENT_LIVE_VERIFICATION_KEYS = frozenset(
    {
        "business_verification",
        "database_snapshot",
        "runtime_services",
        "database_services_healthy",
        "writer_services_stopped",
        "table_reconcile",
        "wallet_reconcile",
        "checked_at",
    }
)
FAILED_ACCEPTANCE_BUSINESS_VERIFICATION_KEYS = frozenset(
    {
        "schema_version",
        "passed",
        "counts",
        "evidence_sha256",
        "secret_values_recorded",
    }
)
FAILED_ACCEPTANCE_BUSINESS_COUNTS = {
    "orders": 1,
    "fixtures": 2,
    "fixture_images": 5,
    "experience_options": 3,
    "order_items": 4,
    "experience_items": 3,
    "kit_items": 1,
    "payments": 0,
    "settlements": 0,
    "refunds": 0,
    "wallet_transactions": 0,
    "table_sessions": 0,
    "admin_adjustments": 1,
    "order_deductions": 1,
    "cancellation_restores": 1,
}
FAILED_ACCEPTANCE_BUSINESS_EVIDENCE_SHA256 = (
    "9f262cb7c7a500cfd3b245f045c9ff8a887a640a6576539b421a61add81c1012"
)
RETIREMENT_PENDING_PHASES = frozenset(
    {
        "prepared",
        "write-free-verified",
        "acceptance-archived",
        "record-published",
        "canonical-removed",
        "runtime-restored",
    }
)
RETIREMENT_PENDING_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "candidate_sha",
        "image_id",
        "source_candidate_sha",
        "source_image_id",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "stage_record_sha256",
        "predecessor_stage_record_sha256",
        "predecessor_activation_record_sha256",
        "predecessor_upgrade_record_sha256",
        "predecessor_upgrade_evidence_sha256",
        "predecessor_upgrade_plan_replay_record_sha256",
        "acceptance_pending_sha256",
        "acceptance_attempt_id_sha256",
        "acceptance_archive_path",
        "acceptance_archive_sha256",
        "live_verification",
        "started_at",
        "phase",
        "secret_values_recorded",
    }
)
RETIREMENT_RECORD_KEYS = RETIREMENT_PENDING_KEYS | frozenset(
    {"completed_at", "passed"}
)
ACCEPTANCE_REQUIRED_TRUE_FIELDS = (
    "upgrade_plan_replayed",
    "wallet_reconcile_passed",
    "table_reconcile_passed",
    "table_sweep_passed",
    "log_redaction_passed",
    "passed",
)
ACCEPTANCE_REQUIRED_FALSE_FIELDS = (
    "pii_recorded",
    "secret_values_recorded",
    "table_tokens_recorded",
    "super_admin_credentials_recorded",
    "synthetic_credentials_recorded",
    "token_values_recorded",
    "qr_token_values_recorded",
    "request_or_response_bodies_recorded",
    "raw_dynamic_paths_recorded",
    "source_volume_restored",
)
STAGE_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "passed",
        "candidate_sha",
        "source_head_sha",
        "source_m7_sha",
        "source_archive_sha256",
        "launcher_sha256",
        "ci_artifact_sha256",
        "ci_artifact_name",
        "required_jobs_verified",
        "artifact_file_count",
        "artifact_uncompressed_bytes",
        "artifact_scan_passed",
        "ci_cleanup_passed",
        "ci_run_attempt",
        "ci_run_id",
        "reported_pr_head_sha",
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
        "source_file_count",
        "source_total_bytes",
        "source_manifest_sha256",
        "image",
        "architecture",
        "image_id",
        "operating_system",
        "completed_at",
        "secret_values_recorded",
    }
)
STAGE_PENDING_KEYS = (
    STAGE_RECORD_KEYS
    - frozenset(
        {
            "record_type",
            "passed",
            "image",
            "architecture",
            "image_id",
            "operating_system",
            "completed_at",
        }
    )
) | frozenset(
    {
        "record_type",
        "final_image",
        "temporary_image",
        "started_at",
        "phase",
    }
)
ADOPTION_STAGE_RECORD_KEYS = STAGE_RECORD_KEYS | frozenset(
    {"transition_kind", "superseded_candidate_sha", "failed_acceptance_sha256"}
)
ADOPTION_STAGE_PENDING_KEYS = (
    ADOPTION_STAGE_RECORD_KEYS
    - frozenset(
        {
            "record_type",
            "passed",
            "image",
            "architecture",
            "image_id",
            "operating_system",
            "completed_at",
        }
    )
) | frozenset(
    {
        "record_type",
        "final_image",
        "temporary_image",
        "started_at",
        "phase",
    }
)
ACTIVATION_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "source_candidate_sha",
        "candidate_sha",
        "image_id",
        "backup_id",
        "manifest_sha256",
        "source_config_sha256",
        "target_config_sha256",
        "changed_keys",
        "history_path",
        "stage_record_sha256",
        "started_at",
        "config_values_recorded",
        "secret_values_recorded",
        "completed_at",
        "passed",
    }
)
ACTIVATION_PENDING_KEYS = ACTIVATION_RECORD_KEYS - frozenset(
    {"completed_at", "passed"}
)
ADOPTION_ACTIVATION_RECORD_KEYS = ACTIVATION_RECORD_KEYS | frozenset(
    {
        "transition_kind",
        "source_image_id",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "predecessor_stage_record_sha256",
        "predecessor_activation_record_sha256",
        "predecessor_upgrade_record_sha256",
        "predecessor_upgrade_evidence_sha256",
        "predecessor_upgrade_plan_replay_record_sha256",
        "acceptance_retirement_record_sha256",
    }
)
ADOPTION_ACTIVATION_PENDING_KEYS = ADOPTION_ACTIVATION_RECORD_KEYS - frozenset(
    {"completed_at", "passed"}
)
ROLLBACK_PENDING_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "source_candidate_sha",
        "candidate_sha",
        "activation_record_sha256",
        "source_config_sha256",
        "target_config_sha256",
        "database_chain",
        "started_at",
        "secret_values_recorded",
    }
)
ROLLBACK_RECORD_KEYS = ROLLBACK_PENDING_KEYS | frozenset(
    {"completed_at", "passed"}
)
ADOPTION_ROLLBACK_PENDING_KEYS = ROLLBACK_PENDING_KEYS | frozenset(
    {
        "transition_kind",
        "source_image_id",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "acceptance_retirement_record_sha256",
        "predecessor_stage_record_sha256",
        "predecessor_activation_record_sha256",
        "predecessor_upgrade_record_sha256",
        "predecessor_upgrade_evidence_sha256",
        "predecessor_upgrade_plan_replay_record_sha256",
    }
)
ADOPTION_ROLLBACK_RECORD_KEYS = ADOPTION_ROLLBACK_PENDING_KEYS | frozenset(
    {"completed_at", "passed"}
)
FINAL_LIVE_RECHECK_KEYS = frozenset(
    {
        "database_snapshot",
        "m7_content_snapshot",
        "m8_swatch_content_snapshot",
        "m9_table_content_snapshot",
        "image_manifest_sha256",
        "image_file_count",
        "table_reconcile",
        "wallet_reconcile",
        "checked_at",
    }
)
FINAL_PENDING_PHASES = frozenset(
    {"prepared", "live-rechecked", "current-switched", "runtime-restored"}
)
FINAL_PENDING_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "source_candidate_sha",
        "candidate_sha",
        "image_id",
        "source_link",
        "target_link",
        "stage_record_sha256",
        "activation_record_sha256",
        "upgrade_record_sha256",
        "upgrade_plan_replay_record_sha256",
        "runtime_acceptance_record_sha256",
        "resilience_record_sha256",
        "post_backup_id",
        "post_backup_record_sha256",
        "post_restore_record_sha256",
        "runtime_services",
        "started_at",
        "phase",
        "live_recheck",
        "secret_values_recorded",
    }
)
FINAL_RECORD_KEYS = FINAL_PENDING_KEYS | frozenset({"completed_at", "passed"})
ADOPTION_FINAL_PENDING_KEYS = FINAL_PENDING_KEYS | frozenset(
    {
        "transition_kind",
        "source_image_id",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "predecessor_stage_record_sha256",
        "predecessor_activation_record_sha256",
        "predecessor_upgrade_record_sha256",
        "predecessor_upgrade_evidence_sha256",
        "predecessor_upgrade_plan_replay_record_sha256",
        "acceptance_retirement_record_sha256",
    }
)
ADOPTION_FINAL_RECORD_KEYS = ADOPTION_FINAL_PENDING_KEYS | frozenset(
    {"completed_at", "passed"}
)
RESILIENCE_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "candidate_sha",
        "image_id",
        "representative_candidate_sha",
        "representative_image_id",
        "representative_record_sha256",
        "runtime_acceptance_record_sha256",
        "runtime_acceptance_attempt_id_sha256",
        "runtime_acceptance_completed_at",
        "started_at",
        "completed_at",
        "dependency_drills",
        "app_restart",
        "database_snapshot_unchanged",
        "database_content_snapshots",
        "database_content_snapshots_unchanged",
        "image_manifest_unchanged",
        "image_file_count",
        "source_services_healthy",
        "runtime_services",
        "table_sweeper_included",
        "loopback_only",
        "log_rotation",
        "log_observability",
        "pii_recorded",
        "secret_values_recorded",
        "passed",
    }
)


class GateACandidateError(RuntimeError):
    """A redacted failure in the host-side candidate state machine."""


class GateACandidateOperationInterrupted(GateACandidateError):
    """A termination signal interrupted one guarded candidate mutation."""


class _MutationTerminationController:
    """Keep work interruptible while shielding mandatory recovery."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.recovery_started = False
        self.work_interruption: BaseException | None = None
        self.recovery_interruption: BaseException | None = None
        self._previous_handlers: dict[int, Any] = {}
        self._installed_signals: list[int] = []

    def begin_recovery(self) -> None:
        self.recovery_started = True

    def remember_recovery_interruption(self, error: BaseException) -> None:
        if self.recovery_interruption is None:
            self.recovery_interruption = error

    def interrupt(self, signum: int, _frame: object) -> None:
        was_recovering = self.recovery_started
        if not was_recovering:
            # This assignment is deliberately the first handler action. A second
            # signal can no longer raise while the first interruption is built.
            self.recovery_started = True
        signal_name = signal.Signals(signum).name
        message = (
            f"Gate A candidate {self.operation} received {signal_name} and is recovering"
        )
        interruption: BaseException = (
            KeyboardInterrupt(message)
            if signum == signal.SIGINT
            else GateACandidateOperationInterrupted(message)
        )
        if not was_recovering:
            self.work_interruption = interruption
            raise interruption
        self.remember_recovery_interruption(interruption)

    def install(self) -> None:
        try:
            for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                self._previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, self.interrupt)
                self._installed_signals.append(signum)
        except BaseException:
            self.restore_handlers()
            raise

    def restore_handlers(self) -> None:
        while self._installed_signals:
            signum = self._installed_signals.pop()
            signal.signal(signum, self._previous_handlers[signum])

    def pending_interruption(self) -> BaseException | None:
        return self.work_interruption or self.recovery_interruption


@contextmanager
def _mutation_termination_controller(
    operation: str,
) -> Iterator[_MutationTerminationController]:
    """Install signal handling inside the global mutation lock."""

    controller = _MutationTerminationController(operation)
    completed = False
    controller.install()
    try:
        yield controller
        completed = True
    finally:
        controller.restore_handlers()
    if completed and (interruption := controller.pending_interruption()) is not None:
        raise interruption


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_root() -> None:
    if os.geteuid() != 0:
        raise GateACandidateError("Gate A candidate operations require root")


def _require_root_directory(path: Path, mode: int, description: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise GateACandidateError(f"{description} is unavailable") from error
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise GateACandidateError(f"{description} must be a non-symlink directory")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise GateACandidateError(f"{description} must be owned by root:root")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise GateACandidateError(f"{description} has unsafe permissions")


def _require_root_file(path: Path, mode: int, description: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise GateACandidateError(f"{description} is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise GateACandidateError(f"{description} must be a regular file")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise GateACandidateError(f"{description} must be owned by root:root")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise GateACandidateError(f"{description} has unsafe permissions")


def _ensure_root_directory(path: Path, mode: int, description: str) -> None:
    if not path.exists():
        path.mkdir(mode=mode)
        os.chown(path, 0, 0)
    _require_root_directory(path, mode, description)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    descriptor = os.open(
        path,
        os.O_RDWR
        | os.O_CREAT
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise GateACandidateError("Gate A candidate lock file is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GateACandidateError(
                "Another Gate A candidate operation is active"
            ) from error
        yield
    finally:
        os.close(descriptor)


def _serialized_operation(function: Any) -> Any:
    """Hold the one Gate A operation lock across every mutable observation."""

    @wraps(function)
    def locked(
        *args: Any,
        lock_file: Path = DEFAULT_LOCK_FILE,
        **kwargs: Any,
    ) -> dict[str, Any]:
        _require_root()
        with _exclusive_lock(lock_file):
            with _mutation_termination_controller(
                function.__name__.replace("_", "-")
            ) as termination:
                kwargs["_termination_controller"] = termination
                return function(*args, lock_file=None, **kwargs)

    return locked


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_bytes_exclusive(path: Path, content: bytes, mode: int) -> None:
    """Atomically publish one complete file without replacing an existing path."""

    descriptor: int | None = None
    temporary: Path | None = None
    published = False
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.publish-",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        os.set_inheritable(descriptor, False)
        os.fchown(descriptor, 0, 0)
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # The same-directory hard link is an atomic no-clobber publication:
        # a crash can leave only a complete destination or an unclaimed temp,
        # never a truncated file occupying the immutable destination name.
        os.link(temporary, path, follow_symlinks=False)
        published = True
        _fsync_directory(path.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
            if published:
                _fsync_directory(path.parent)


def _write_json_exclusive(path: Path, payload: Mapping[str, Any], mode: int = 0o644) -> None:
    content = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    _write_bytes_exclusive(path, content, mode)


def _atomic_replace_bytes(path: Path, content: bytes, mode: int) -> None:
    temporary = path.parent / f".{path.name}.pending-{os.getpid()}"
    try:
        _write_bytes_exclusive(temporary, content, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_replace_json(path: Path, payload: Mapping[str, Any], mode: int) -> None:
    content = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    _atomic_replace_bytes(path, content, mode)


def _load_json(path: Path, description: str, *, mode: int = 0o644) -> dict[str, Any]:
    _require_root_file(path, mode, description)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise GateACandidateError(f"{description} is unexpectedly large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateACandidateError(f"{description} is invalid") from error
    if not isinstance(payload, dict):
        raise GateACandidateError(f"{description} has an invalid shape")
    return payload


def _load_evidence_line(path: Path, description: str) -> str:
    _require_root_file(path, 0o644, description)
    if path.stat().st_size > 128:
        raise GateACandidateError(f"{description} is unexpectedly large")
    try:
        content = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as error:
        raise GateACandidateError(f"{description} is invalid") from error
    if not content.endswith("\n") or "\n" in content[:-1] or "\r" in content:
        raise GateACandidateError(f"{description} is invalid")
    return content[:-1]


def _validate_sha(value: str, description: str) -> str:
    if SHA_PATTERN.fullmatch(value) is None:
        raise GateACandidateError(f"{description} must be a full Git SHA")
    return value


def _validate_sha256(value: str, description: str) -> str:
    if SHA256_PATTERN.fullmatch(value) is None:
        raise GateACandidateError(f"{description} must be a SHA-256 digest")
    return value


def _github_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN")
    if token in {None, ""}:
        return None
    if (
        len(token) > 2048
        or not token.isascii()
        or any(ord(character) < 33 or ord(character) > 126 for character in token)
    ):
        raise GateACandidateError("GitHub provenance authentication is invalid")
    return token


class _RejectGitHubRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Any,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def _github_urlopen(request: urllib.request.Request) -> Any:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _RejectGitHubRedirects()
    )
    return opener.open(request, timeout=20)


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON key")
        payload[key] = value
    return payload


def _github_get_json(api_path: str, *, token: str | None) -> dict[str, Any]:
    prefix = f"/repos/{GITHUB_REPOSITORY}/"
    if (
        not api_path.startswith(prefix)
        or "://" in api_path
        or "\r" in api_path
        or "\n" in api_path
    ):
        raise GateACandidateError("GitHub provenance API path is invalid")
    headers = {
        "Accept": "application/vnd.github+json",
        "Accept-Encoding": "identity",
        "User-Agent": "pinkdoohub-gatea-candidate",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{GITHUB_API_ORIGIN}{api_path}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _github_urlopen(request) as response:
            content_type = response.headers.get_content_type()
            content_encoding = response.headers.get("Content-Encoding", "identity")
            if (
                response.getcode() != 200
                or response.geturl() != url
                or content_type != "application/json"
                or not isinstance(content_encoding, str)
                or content_encoding.lower() != "identity"
            ):
                raise GateACandidateError("GitHub provenance API response is invalid")
            raw = response.read(MAX_GITHUB_RESPONSE_BYTES + 1)
        if len(raw) > MAX_GITHUB_RESPONSE_BYTES:
            raise GateACandidateError("GitHub provenance API response is too large")
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_json_object_without_duplicates
        )
    except GateACandidateError:
        raise
    except (
        OSError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        ValueError,
    ):
        raise GateACandidateError("GitHub provenance API request failed") from None
    if not isinstance(payload, dict):
        raise GateACandidateError("GitHub provenance API response has an invalid shape")
    return payload


def _git_blob_sha(path: Path, size: int) -> str:
    try:
        digest = hashlib.sha1(usedforsecurity=False)
        digest.update(f"blob {size}\0".encode("ascii"))
        bytes_read = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                bytes_read += len(block)
        if bytes_read != size or path.stat().st_size != size:
            raise GateACandidateError("Candidate source changed during Git verification")
    except GateACandidateError:
        raise
    except OSError:
        raise GateACandidateError("Candidate source cannot be verified") from None
    return digest.hexdigest()


def _github_utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed


def _validate_github_source_tree(
    root: Path,
    *,
    target_sha: str,
    commit_payload: Mapping[str, Any],
    tree_payload: Mapping[str, Any],
) -> dict[str, Any]:
    tree_reference = commit_payload.get("tree")
    tree_sha = tree_reference.get("sha") if isinstance(tree_reference, dict) else None
    entries = tree_payload.get("tree")
    if (
        commit_payload.get("sha") != target_sha
        or not isinstance(tree_sha, str)
        or SHA_PATTERN.fullmatch(tree_sha) is None
        or tree_payload.get("sha") != tree_sha
        or tree_payload.get("truncated") is not False
        or not isinstance(entries, list)
        or not entries
        or len(entries) > MAX_ARCHIVE_MEMBERS
    ):
        raise GateACandidateError("GitHub candidate source tree is invalid")

    try:
        root_metadata = root.lstat()
    except OSError:
        raise GateACandidateError("Candidate source tree is unavailable") from None
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root.is_symlink()
        or stat.S_IMODE(root_metadata.st_mode) != 0o755
    ):
        raise GateACandidateError("Candidate source tree is invalid")

    seen: set[str] = set()
    blob_paths: set[str] = set()
    tree_paths: set[str] = set()
    blob_lines: list[str] = []
    total_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise GateACandidateError("GitHub candidate source tree is invalid")
        try:
            path_name = _safe_archive_name(entry.get("path"))
        except (GateACandidateError, TypeError):
            raise GateACandidateError("GitHub candidate source tree is invalid") from None
        if path_name in seen:
            raise GateACandidateError("GitHub candidate source tree is invalid")
        seen.add(path_name)
        entry_type = entry.get("type")
        mode = entry.get("mode")
        object_sha = entry.get("sha")
        if not isinstance(object_sha, str) or SHA_PATTERN.fullmatch(object_sha) is None:
            raise GateACandidateError("GitHub candidate source tree is invalid")
        local_path = root.joinpath(*PurePosixPath(path_name).parts)
        if entry_type == "tree":
            try:
                metadata = local_path.lstat()
            except OSError:
                raise GateACandidateError("GitHub candidate source tree is invalid") from None
            if (
                mode != "040000"
                or not stat.S_ISDIR(metadata.st_mode)
                or local_path.is_symlink()
                or stat.S_IMODE(metadata.st_mode) != 0o755
            ):
                raise GateACandidateError("GitHub candidate source tree is invalid")
            tree_paths.add(path_name)
            continue
        if entry_type != "blob" or mode not in {"100644", "100755"}:
            raise GateACandidateError("GitHub candidate source tree is invalid")
        size = entry.get("size")
        if (
            type(size) is not int
            or size < 0
            or size > MAX_ARCHIVE_MEMBER_BYTES
        ):
            raise GateACandidateError("GitHub candidate source tree is invalid")
        try:
            metadata = local_path.lstat()
        except OSError:
            raise GateACandidateError("GitHub candidate source tree is invalid") from None
        expected_mode = 0o755 if mode == "100755" else 0o644
        if (
            not stat.S_ISREG(metadata.st_mode)
            or local_path.is_symlink()
            or stat.S_IMODE(metadata.st_mode) != expected_mode
            or metadata.st_size != size
            or _git_blob_sha(local_path, size) != object_sha
        ):
            raise GateACandidateError("GitHub candidate source tree does not match Git")
        total_bytes += size
        if total_bytes > MAX_ARCHIVE_BYTES:
            raise GateACandidateError("GitHub candidate source tree is too large")
        blob_paths.add(path_name)
        blob_lines.append(f"{path_name}\0{mode}\0{object_sha}")

    local_files: set[str] = set()
    local_directories: set[str] = set()
    for local_path in root.rglob("*"):
        try:
            metadata = local_path.lstat()
        except OSError:
            raise GateACandidateError("Candidate source tree cannot be verified") from None
        if stat.S_ISDIR(metadata.st_mode) and not local_path.is_symlink():
            local_directories.add(local_path.relative_to(root).as_posix())
            continue
        if not stat.S_ISREG(metadata.st_mode) or local_path.is_symlink():
            raise GateACandidateError("Candidate source tree contains a special file")
        local_files.add(local_path.relative_to(root).as_posix())
    if (
        not blob_paths
        or local_files != blob_paths
        or local_directories != tree_paths
    ):
        raise GateACandidateError("GitHub candidate source tree does not match the archive")

    normalized = "\n".join(sorted(blob_lines)) + "\n"
    return {
        "github_tree_sha": tree_sha,
        "github_blob_count": len(blob_paths),
        "github_tree_manifest_sha256": _sha256_bytes(normalized.encode("utf-8")),
    }


def _verify_github_provenance(
    *,
    source_root: Path,
    ci_artifact: Path,
    ci_artifact_sha256: str,
    target_sha: str,
    source_head_sha: str,
    run_id: str,
    run_attempt: int,
    artifact_name: str,
) -> dict[str, Any]:
    target_sha = _validate_sha(target_sha, "target SHA")
    source_head_sha = _validate_sha(source_head_sha, "source head SHA")
    ci_artifact_sha256 = _validate_sha256(
        ci_artifact_sha256, "CI artifact digest"
    )
    if (
        RUN_ID_PATTERN.fullmatch(run_id) is None
        or len(run_id) > 20
        or type(run_attempt) is not int
        or run_attempt <= 0
        or artifact_name
        != f"gatea-m7-m9-updater-{target_sha}-{run_id}-{run_attempt}"
        or _sha256(ci_artifact) != ci_artifact_sha256
    ):
        raise GateACandidateError("GitHub provenance inputs are invalid")

    token = _github_token()
    prefix = f"/repos/{GITHUB_REPOSITORY}"
    run_number_value = int(run_id)
    run = _github_get_json(f"{prefix}/actions/runs/{run_id}", token=token)
    run_repository = run.get("repository")
    run_head_repository = run.get("head_repository")
    pull_requests = run.get("pull_requests")
    run_pull = (
        pull_requests[0]
        if isinstance(pull_requests, list)
        and len(pull_requests) == 1
        and isinstance(pull_requests[0], dict)
        else {}
    )
    run_pull_head = run_pull.get("head")
    run_pull_base = run_pull.get("base")
    run_pull_head = run_pull_head if isinstance(run_pull_head, dict) else {}
    run_pull_base = run_pull_base if isinstance(run_pull_base, dict) else {}
    run_pull_head_repository = run_pull_head.get("repo")
    run_pull_base_repository = run_pull_base.get("repo")
    run_pull_head_repository = (
        run_pull_head_repository
        if isinstance(run_pull_head_repository, dict)
        else {}
    )
    run_pull_base_repository = (
        run_pull_base_repository
        if isinstance(run_pull_base_repository, dict)
        else {}
    )
    pull_number = run_pull.get("number")
    run_pull_base_sha = run_pull_base.get("sha")
    repository_id = (
        run_repository.get("id") if isinstance(run_repository, dict) else None
    )
    head_repository_id = (
        run_head_repository.get("id")
        if isinstance(run_head_repository, dict)
        else None
    )
    workflow_run_number = run.get("run_number")
    workflow_path = run.get("path")
    allowed_workflow_paths = {
        GITHUB_WORKFLOW_PATH,
        f"{GITHUB_WORKFLOW_PATH}@{GITHUB_BASE_REF}",
    }
    if (
        type(run.get("id")) is not int
        or run.get("id") != run_number_value
        or type(run.get("run_attempt")) is not int
        or run.get("run_attempt") != run_attempt
        or run.get("event") != "pull_request"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        # GitHub 的 pull_request Run/Job/Artifact 元数据使用 PR head SHA；
        # 工作流内的 GITHUB_SHA 才是本次经测试的临时 merge commit。
        or run.get("head_sha") != source_head_sha
        or run.get("head_branch") != run_pull_head.get("ref")
        or not isinstance(run.get("head_commit"), dict)
        or run["head_commit"].get("id") != source_head_sha
        or run.get("name") != GITHUB_WORKFLOW_NAME
        or not isinstance(workflow_path, str)
        or workflow_path not in allowed_workflow_paths
        or not isinstance(run_repository, dict)
        or run_repository.get("full_name") != GITHUB_REPOSITORY
        or not isinstance(run_head_repository, dict)
        or run_head_repository.get("full_name") != GITHUB_REPOSITORY
        or type(repository_id) is not int
        or repository_id <= 0
        or type(head_repository_id) is not int
        or head_repository_id != repository_id
        or type(workflow_run_number) is not int
        or workflow_run_number <= 0
        or type(pull_number) is not int
        or pull_number <= 0
        or run_pull_head.get("sha") != source_head_sha
        or run_pull_base.get("ref") != GITHUB_BASE_REF
        or not isinstance(run_pull_base_sha, str)
        or SHA_PATTERN.fullmatch(run_pull_base_sha) is None
        or run_pull_head_repository.get("id") != head_repository_id
        or run_pull_base_repository.get("id") != repository_id
    ):
        raise GateACandidateError("GitHub workflow run provenance is invalid")

    pull = _github_get_json(f"{prefix}/pulls/{pull_number}", token=token)
    pull_head = pull.get("head")
    pull_base = pull.get("base")
    pull_head = pull_head if isinstance(pull_head, dict) else {}
    pull_base = pull_base if isinstance(pull_base, dict) else {}
    pull_head_repository = pull_head.get("repo")
    pull_base_repository = pull_base.get("repo")
    pull_head_repository = (
        pull_head_repository if isinstance(pull_head_repository, dict) else {}
    )
    pull_base_repository = (
        pull_base_repository if isinstance(pull_base_repository, dict) else {}
    )
    pull_head_ref = pull_head.get("ref")
    pull_base_sha = pull_base.get("sha")
    if (
        pull.get("number") != pull_number
        or pull.get("state") != "open"
        or pull.get("merged") is not False
        or pull.get("merge_commit_sha") != target_sha
        or pull_head.get("sha") != source_head_sha
        or not isinstance(pull_head_ref, str)
        or not pull_head_ref
        or run_pull_head.get("ref") != pull_head_ref
        or pull_base.get("ref") != GITHUB_BASE_REF
        or pull_base_sha != run_pull_base_sha
        or pull_head_repository.get("full_name") != GITHUB_REPOSITORY
        or pull_base_repository.get("full_name") != GITHUB_REPOSITORY
    ):
        raise GateACandidateError("GitHub pull request provenance is invalid")

    jobs = _github_get_json(
        (
            f"{prefix}/actions/runs/{run_id}/attempts/{run_attempt}/jobs"
            "?per_page=100&page=1"
        ),
        token=token,
    )
    job_items = jobs.get("jobs")
    if (
        type(jobs.get("total_count")) is not int
        or jobs.get("total_count") != len(GITHUB_REQUIRED_JOBS)
        or not isinstance(job_items, list)
        or len(job_items) != len(GITHUB_REQUIRED_JOBS)
        or any(not isinstance(job, dict) for job in job_items)
    ):
        raise GateACandidateError("GitHub required jobs provenance is invalid")
    job_names = [job.get("name") for job in job_items]
    job_ids = [job.get("id") for job in job_items]
    if (
        any(not isinstance(name, str) for name in job_names)
        or len(set(job_names)) != len(GITHUB_REQUIRED_JOBS)
        or set(job_names) != GITHUB_REQUIRED_JOBS
        or any(type(job_id) is not int or job_id <= 0 for job_id in job_ids)
        or len(set(job_ids)) != len(job_ids)
        or any(
            job.get("run_id") != run_number_value
            or job.get("head_sha") != source_head_sha
            or job.get("status") != "completed"
            or job.get("conclusion") != "success"
            or job.get("workflow_name") != GITHUB_WORKFLOW_NAME
            for job in job_items
        )
    ):
        raise GateACandidateError("GitHub required jobs provenance is invalid")

    artifact_query = urllib.parse.urlencode(
        {"name": artifact_name, "per_page": 100, "page": 1}
    )
    artifacts = _github_get_json(
        f"{prefix}/actions/runs/{run_id}/artifacts?{artifact_query}", token=token
    )
    artifact_items = artifacts.get("artifacts")
    artifact = (
        artifact_items[0]
        if isinstance(artifact_items, list)
        and len(artifact_items) == 1
        and isinstance(artifact_items[0], dict)
        else {}
    )
    artifact_run = artifact.get("workflow_run")
    artifact_run = artifact_run if isinstance(artifact_run, dict) else {}
    artifact_id = artifact.get("id")
    artifact_size = artifact.get("size_in_bytes")
    artifact_expires_at = artifact.get("expires_at")
    artifact_expiration = _github_utc_datetime(artifact_expires_at)
    artifact_is_current = (
        artifact_expiration is not None
        and artifact_expiration > datetime.now(timezone.utc)
    )
    expected_artifact_digest = f"sha256:{ci_artifact_sha256}"
    if (
        type(artifacts.get("total_count")) is not int
        or artifacts.get("total_count") != 1
        or type(artifact_id) is not int
        or artifact_id <= 0
        or artifact.get("name") != artifact_name
        or artifact.get("expired") is not False
        or artifact.get("digest") != expected_artifact_digest
        or type(artifact_size) is not int
        or artifact_size <= 0
        or artifact_size > MAX_CI_BYTES
        or not artifact_is_current
        or artifact_run.get("id") != run_number_value
        or artifact_run.get("repository_id") != repository_id
        or artifact_run.get("head_repository_id") != head_repository_id
        or artifact_run.get("head_sha") != source_head_sha
        or artifact_run.get("head_branch") != pull_head_ref
    ):
        raise GateACandidateError("GitHub Actions artifact provenance is invalid")

    commit = _github_get_json(
        f"{prefix}/git/commits/{target_sha}", token=token
    )
    commit_tree = commit.get("tree")
    commit_tree_sha = (
        commit_tree.get("sha") if isinstance(commit_tree, dict) else None
    )
    commit_parents = commit.get("parents")
    if (
        not isinstance(commit_tree_sha, str)
        or SHA_PATTERN.fullmatch(commit_tree_sha) is None
        or not isinstance(commit_parents, list)
        or len(commit_parents) != 2
        or any(not isinstance(parent, dict) for parent in commit_parents)
        or [parent.get("sha") for parent in commit_parents]
        != [pull_base_sha, source_head_sha]
    ):
        raise GateACandidateError("GitHub candidate commit provenance is invalid")
    tree = _github_get_json(
        f"{prefix}/git/trees/{commit_tree_sha}?recursive=1", token=token
    )
    tree_evidence = _validate_github_source_tree(
        source_root,
        target_sha=target_sha,
        commit_payload=commit,
        tree_payload=tree,
    )
    return {
        "required_jobs_verified": len(GITHUB_REQUIRED_JOBS),
        "github_repository": GITHUB_REPOSITORY,
        "github_repository_id": repository_id,
        "github_workflow": GITHUB_WORKFLOW_NAME,
        "github_workflow_path": workflow_path,
        "github_base_ref": GITHUB_BASE_REF,
        "github_pull_request_number": pull_number,
        "github_run_number": workflow_run_number,
        "github_api_authenticated": token is not None,
        "github_required_jobs_sha256": GITHUB_REQUIRED_JOBS_SHA256,
        "github_artifact_id": artifact_id,
        "github_artifact_digest": expected_artifact_digest,
        "github_artifact_size_bytes": artifact_size,
        "github_artifact_expires_at": artifact_expires_at,
        **tree_evidence,
    }


def _safe_archive_name(raw_name: str) -> str:
    if not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise GateACandidateError("Candidate archive contains an unsafe path")
    without_trailing_slash = raw_name[:-1] if raw_name.endswith("/") else raw_name
    raw_parts = without_trailing_slash.split("/")
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise GateACandidateError("Candidate archive contains an unsafe path")
    path = PurePosixPath(without_trailing_slash)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise GateACandidateError("Candidate archive contains an unsafe path")
    normalized = path.as_posix().rstrip("/")
    if not normalized:
        raise GateACandidateError("Candidate archive contains an unsafe path")
    parts = PurePosixPath(normalized).parts
    if any(part in FORBIDDEN_SOURCE_PARTS for part in parts) or normalized == ".env":
        raise GateACandidateError("Candidate archive contains a forbidden path")
    return normalized


def _extract_source_archive(
    archive: Path, destination: Path, *, target_sha: str
) -> dict[str, Any]:
    seen: set[str] = set()
    file_count = 0
    total_bytes = 0
    try:
        if archive.stat().st_size > MAX_SOURCE_ARCHIVE_FILE_BYTES:
            raise GateACandidateError("Candidate source archive is too large")
        stream = tarfile.open(archive, mode="r:")
    except (OSError, tarfile.TarError) as error:
        raise GateACandidateError("Candidate source archive is invalid") from error
    with stream:
        if stream.pax_headers.get("comment") != target_sha:
            raise GateACandidateError(
                "Candidate source archive does not identify the tested Git commit"
            )
        members = stream.getmembers()
        if not members or len(members) > MAX_ARCHIVE_MEMBERS:
            raise GateACandidateError("Candidate source archive cardinality is invalid")
        for member in members:
            name = _safe_archive_name(member.name)
            if name in seen:
                raise GateACandidateError("Candidate archive contains duplicate paths")
            seen.add(name)
            if not member.isdir() and not member.isfile():
                raise GateACandidateError("Candidate archive contains a special file")
            if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                raise GateACandidateError("Candidate archive member is too large")
            if member.isfile():
                file_count += 1
                total_bytes += member.size
                if total_bytes > MAX_ARCHIVE_BYTES:
                    raise GateACandidateError("Candidate source archive is too large")

        for member in members:
            name = _safe_archive_name(member.name)
            target = destination.joinpath(*PurePosixPath(name).parts)
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
                os.chmod(target, 0o755)
                continue
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            source = stream.extractfile(member)
            if source is None:
                raise GateACandidateError("Candidate archive member cannot be read")
            mode = 0o755 if member.mode & 0o111 else 0o644
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                mode,
            )
            try:
                with os.fdopen(descriptor, "wb") as output:
                    descriptor = -1
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                source.close()
                if descriptor >= 0:
                    os.close(descriptor)
            os.chmod(target, mode)

    for directory in sorted(
        (path for path in destination.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        os.chmod(directory, 0o755)
    os.chmod(destination, 0o755)

    missing = sorted(REQUIRED_SOURCE_FILES - seen)
    if missing:
        raise GateACandidateError("Candidate source archive is incomplete")
    return {
        "file_count": file_count,
        "total_bytes": total_bytes,
        **_source_manifest(destination),
    }


def _source_manifest(root: Path) -> dict[str, Any]:
    root_metadata = root.lstat()
    expected_uid = os.geteuid()
    expected_gid = os.getegid()
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root.is_symlink()
        or root_metadata.st_uid != expected_uid
        or root_metadata.st_gid != expected_gid
        or stat.S_IMODE(root_metadata.st_mode) != 0o755
    ):
        raise GateACandidateError("Candidate release root metadata changed")
    lines: list[str] = []
    file_count = 0
    total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISDIR(metadata.st_mode):
            if (
                path.is_symlink()
                or metadata.st_uid != expected_uid
                or metadata.st_gid != expected_gid
                or stat.S_IMODE(metadata.st_mode) != 0o755
            ):
                raise GateACandidateError("Candidate release directory metadata changed")
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_uid != expected_uid
            or metadata.st_gid != expected_gid
        ):
            raise GateACandidateError("Candidate release contains a special file")
        mode = stat.S_IMODE(metadata.st_mode)
        if mode not in {0o644, 0o755}:
            raise GateACandidateError("Candidate release file mode changed")
        file_count += 1
        total_bytes += metadata.st_size
        lines.append(f"{relative}\0{mode:o}\0{metadata.st_size}\0{_sha256(path)}")
    normalized = "\n".join(lines)
    if lines:
        normalized += "\n"
    return {
        "source_file_count": file_count,
        "source_total_bytes": total_bytes,
        "source_manifest_sha256": _sha256_bytes(normalized.encode("utf-8")),
    }


def _zip_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        raw = archive.read(name)
        payload = json.loads(raw.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as error:
        raise GateACandidateError("Gate A CI artifact evidence is invalid") from error
    if not isinstance(payload, dict):
        raise GateACandidateError("Gate A CI artifact evidence has an invalid shape")
    return payload


def _validate_ci_artifact(
    path: Path,
    *,
    target_sha: str,
    source_head_sha: str,
    run_id: str,
    run_attempt: int,
) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_CI_BYTES:
            raise GateACandidateError("Gate A CI artifact ZIP is too large")
        archive = zipfile.ZipFile(path, mode="r")
    except (OSError, zipfile.BadZipFile) as error:
        raise GateACandidateError("Gate A CI artifact ZIP is invalid") from error
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_CI_MEMBERS:
            raise GateACandidateError("Gate A CI artifact cardinality is invalid")
        names: set[str] = set()
        total = 0
        for info in infos:
            name = _safe_archive_name(info.filename)
            if name in names or name not in CI_ARTIFACT_ALLOWLIST:
                raise GateACandidateError("Gate A CI artifact member is not allowlisted")
            names.add(name)
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(unix_mode)
            if file_type not in {0, stat.S_IFREG}:
                raise GateACandidateError("Gate A CI artifact contains a special file")
            if info.flag_bits & 0x1:
                raise GateACandidateError("Gate A CI artifact must not be encrypted")
            if info.file_size < 0 or info.file_size > MAX_JSON_BYTES:
                raise GateACandidateError("Gate A CI artifact member is too large")
            total += info.file_size
            if total > MAX_CI_BYTES:
                raise GateACandidateError("Gate A CI artifact is too large")
        if not CI_REQUIRED_FILES.issubset(names):
            raise GateACandidateError("Gate A CI artifact evidence is incomplete")

        summary = _zip_json(archive, "summary.json")
        state = _zip_json(archive, "drill-state.json")
        cleanup = _zip_json(archive, "cleanup-report.json")
        scan = _zip_json(archive, "artifact-scan-passed.json")

    artifact_scan = summary.get("artifact_scan")
    expected_residual = {
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
    if (
        summary.get("schema_version") != 1
        or summary.get("record_type") != "gatea-m7-m9-drill"
        or summary.get("status") != "passed"
        or summary.get("source_sha") != SOURCE_M7_SHA
        or summary.get("target_sha") != target_sha
        or summary.get("reported_pr_head_sha") != source_head_sha
        or summary.get("cleanup_passed") is not True
        or summary.get("production_secrets_used") is not False
        or summary.get("persistent_gatea_authorized") is not False
        or summary.get("scope") != "github-hosted-disposable-linux"
        or not isinstance(artifact_scan, dict)
        or artifact_scan.get("allowlist_passed") is not True
        or artifact_scan.get("secret_scan_passed") is not True
        or artifact_scan.get("file_count") != len(names)
        or artifact_scan.get("scope")
        != "all-artifacts-before-final-summary-rewrite"
        or state.get("schema_version") != 1
        or state.get("record_type") != "gatea-m7-m9-drill-state"
        or state.get("target_sha") != target_sha
        or state.get("source_sha") != SOURCE_M7_SHA
        or state.get("source_image") != f"pinkdoohub-gatea:{SOURCE_M7_SHA}"
        or state.get("target_image") != f"pinkdoohub-gatea:{target_sha}"
        or state.get("ownership_acquired") is not True
        or set(cleanup)
        != {
            "schema_version",
            "record_type",
            "checked_at",
            "ownership_acquired",
            "cleanup_performed",
            "errors",
            "residual",
            "passed",
        }
        or cleanup.get("schema_version") != 1
        or cleanup.get("record_type") != "gatea-m7-m9-drill-cleanup"
        or not _is_utc_timestamp(cleanup.get("checked_at"))
        or cleanup.get("ownership_acquired") is not True
        or cleanup.get("cleanup_performed") is not True
        or cleanup.get("passed") is not True
        or cleanup.get("errors") != []
        or cleanup.get("residual") != expected_residual
        or scan
        != {
            "allowlist_passed": True,
            "checked_at": scan.get("checked_at"),
            "record_type": "gatea-m7-m9-drill-artifact-scan",
            "schema_version": 1,
            "secret_scan_passed": True,
        }
        or not _is_utc_timestamp(scan.get("checked_at"))
        or RUN_ID_PATTERN.fullmatch(run_id) is None
        or type(run_attempt) is not int
        or run_attempt <= 0
    ):
        raise GateACandidateError("Gate A CI artifact does not prove this candidate")
    return {
        "artifact_file_count": len(names),
        "artifact_uncompressed_bytes": total,
        "artifact_scan_passed": True,
        "ci_cleanup_passed": True,
        "ci_run_attempt": run_attempt,
        "ci_run_id": run_id,
        "reported_pr_head_sha": source_head_sha,
    }


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    start_new_session: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            text=True,
            capture_output=True,
            start_new_session=start_new_session,
        )
    except OSError as error:
        raise GateACandidateError("A required host command is unavailable") from error
    if check and result.returncode != 0:
        raise GateACandidateError("A required host command failed")
    return result


def _image_exists(image: str) -> bool:
    return _run(("docker", "image", "inspect", image), check=False).returncode == 0


def _remove_temporary_image(image: str) -> None:
    """隔离并有界重试临时 Tag 删除，以精确列表查询作为完成条件。"""

    last_error: GateACandidateError | None = None
    for _ in range(CANDIDATE_CLEANUP_ATTEMPTS):
        try:
            _run(
                ("docker", "image", "rm", image),
                check=False,
                start_new_session=True,
            )
            remaining = _run(
                (
                    "docker",
                    "image",
                    "ls",
                    "--quiet",
                    "--filter",
                    f"reference={image}",
                ),
                start_new_session=True,
            )
        except GateACandidateError as error:
            last_error = error
            continue
        if not remaining.stdout.strip():
            return
    raise GateACandidateError(
        "Gate A temporary candidate image cleanup failed"
    ) from last_error


def _cleanup_candidate_stage(
    *,
    termination: _MutationTerminationController,
    temporary_image: str | None,
    record_path: Path,
    temporary_dir: Path | None,
) -> None:
    """关闭 work→recovery 边界并完成两个相互独立的 stage 清理。"""

    try:
        termination.begin_recovery()
    finally:
        cleanup_error: BaseException | None = None
        try:
            if temporary_image is not None and record_path.exists():
                _remove_temporary_image(temporary_image)
        except BaseException as error:
            cleanup_error = error
        try:
            if temporary_dir is not None and temporary_dir.exists():
                shutil.rmtree(temporary_dir)
        except BaseException as error:
            if cleanup_error is None:
                cleanup_error = error
        if cleanup_error is not None:
            if isinstance(cleanup_error, GateACandidateError):
                raise cleanup_error
            raise GateACandidateError(
                "Gate A candidate stage cleanup failed"
            ) from cleanup_error
        if interruption := termination.pending_interruption():
            raise interruption


def _inspect_image(
    image: str,
    target_sha: str,
    *,
    ci_run_id: str | None = None,
    source_archive_sha256: str | None = None,
) -> dict[str, str]:
    result = _run(("docker", "image", "inspect", image, "--format", "{{json .}}"))
    try:
        payload = json.loads(result.stdout)
        config = payload["Config"]
        labels = config.get("Labels") or {}
        image_id = payload["Id"]
        architecture = payload["Architecture"]
        operating_system = payload["Os"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise GateACandidateError("Gate A candidate image metadata is invalid") from error
    if (
        config.get("User") != EXPECTED_APP_USER
        or config.get("Entrypoint") != EXPECTED_APP_ENTRYPOINT
        or config.get("Cmd") != EXPECTED_APP_COMMAND
        or labels.get("org.opencontainers.image.revision") != target_sha
        or (
            ci_run_id is not None
            and labels.get("com.pinkdoohub.gatea.ci-run") != ci_run_id
        )
        or (
            source_archive_sha256 is not None
            and labels.get("com.pinkdoohub.gatea.source-archive-sha256")
            != source_archive_sha256
        )
        or not isinstance(image_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or architecture != "amd64"
        or operating_system != "linux"
    ):
        raise GateACandidateError("Gate A candidate image violates the runtime contract")
    return {
        "architecture": architecture,
        "image_id": image_id,
        "operating_system": operating_system,
    }


def _stage_record_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.candidate-stage.json"


def _stage_pending_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.candidate-stage.pending.json"


def _activation_record_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.config-activation.json"


def _activation_pending_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.config-activation.pending.json"


def _rollback_record_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.config-rollback.json"


def _rollback_pending_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.config-rollback.pending.json"


def _retirement_record_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.acceptance-retirement.json"


def _retirement_pending_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.acceptance-retirement.pending.json"


def _upgrade_replay_record_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.upgrade-plan-replay.json"


def _upgrade_evidence_paths(record_dir: Path, target_sha: str) -> tuple[Path, ...]:
    return (
        record_dir / f"{target_sha}.existing-database-upgrade.json",
        record_dir / f"{target_sha}.existing-database-upgrade.evidence.json",
        _upgrade_replay_record_path(record_dir, target_sha),
    )


def _final_record_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.current-finalization.json"


def _final_pending_path(record_dir: Path, target_sha: str) -> Path:
    return record_dir / f"{target_sha}.current-finalization.pending.json"


_CANDIDATE_PENDING_KINDS = (
    "candidate-stage",
    "config-activation",
    "config-rollback",
    "acceptance-retirement",
    "current-finalization",
)
_CANDIDATE_PENDING_NAME_PATTERN = re.compile(
    rf"^([0-9a-f]{{40}})\.({'|'.join(_CANDIDATE_PENDING_KINDS)})\.pending\.json$"
)
_ACCEPTANCE_SIDECAR_NAME_PATTERN = re.compile(
    r"^gatea-m9-runtime-acceptance-([0-9a-f]{40})\.json\.(pending|complete)$"
)


def _lexical_absolute_path(path: Path) -> Path:
    """Compare journal paths without resolving or following a symlink."""

    return Path(os.path.abspath(os.fspath(path)))


def _direct_children(path: Path, description: str) -> tuple[Path, ...]:
    try:
        return tuple(path.iterdir())
    except OSError as error:
        raise GateACandidateError(f"{description} could not be scanned") from error


def _path_entry_exists(path: Path, description: str) -> bool:
    """Check directory-entry presence without following a dangling symlink."""

    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise GateACandidateError(
            f"{description} metadata is unavailable"
        ) from error
    return True


def _is_candidate_pending_name(name: str) -> bool:
    return any(
        name.endswith(f".{kind}.pending.json")
        for kind in _CANDIDATE_PENDING_KINDS
    )


def _is_acceptance_sidecar_name(name: str) -> bool:
    return name.startswith("gatea-m9-runtime-acceptance-") and name.endswith(
        (".json.pending", ".json.complete")
    )


def _require_regular_blocker(path: Path, description: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise GateACandidateError(f"{description} metadata is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise GateACandidateError(f"{description} is not a regular file")


def _acceptance_pending_path(record_dir: Path, candidate_sha: str) -> Path:
    return record_dir / f"gatea-m9-runtime-acceptance-{candidate_sha}.json.pending"


def _canonical_json_sha256(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(content)


def _read_stable_protected_bytes(
    path: Path,
    *,
    mode: int,
    max_bytes: int,
    description: str,
    allowed_link_counts: frozenset[int] = frozenset({1}),
) -> tuple[bytes, tuple[int, ...]]:
    """Read one root-owned file through a stable no-follow descriptor."""

    _require_root_file(path, mode, description)
    descriptor: int | None = None
    try:
        path_metadata = path.lstat()
        if (
            path_metadata.st_nlink not in allowed_link_counts
            or path_metadata.st_size > max_bytes
        ):
            raise GateACandidateError(f"{description} has unsafe metadata")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before_metadata.st_mode)
            or stat.S_IMODE(before_metadata.st_mode) != mode
            or before_metadata.st_uid != ROOT_UID
            or before_metadata.st_gid != ROOT_GID
            or before_metadata.st_nlink not in allowed_link_counts
            or before_metadata.st_size > max_bytes
            or _file_identity(path_metadata) != _file_identity(before_metadata)
        ):
            raise GateACandidateError(f"{description} changed during validation")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise GateACandidateError(f"{description} is unexpectedly large")
        after_metadata = os.fstat(descriptor)
        final_metadata = path.lstat()
        if not (
            _file_identity(before_metadata)
            == _file_identity(after_metadata)
            == _file_identity(final_metadata)
        ):
            raise GateACandidateError(f"{description} changed during validation")
        return b"".join(chunks), _file_identity(after_metadata)
    except GateACandidateError:
        raise
    except OSError as error:
        raise GateACandidateError(f"{description} could not be read safely") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_preclaim_failed_acceptance(
    *,
    path: Path,
    expected_candidate_sha: str,
    expected_sha256: str,
) -> tuple[dict[str, Any], bytes, tuple[int, ...]]:
    """Accept only the one known pre-claim, fully-cleaned schema-v3 failure."""

    raw_payload, identity = _read_stable_protected_bytes(
        path,
        mode=0o600,
        max_bytes=MAX_ACCEPTANCE_PENDING_BYTES,
        description="Gate A pre-claim failed acceptance journal",
    )
    if _sha256_bytes(raw_payload) != expected_sha256:
        raise GateACandidateError(
            "Gate A pre-claim failed acceptance digest does not match"
        )
    try:
        payload = json.loads(
            raw_payload,
            object_pairs_hook=_json_object_without_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise GateACandidateError(
            "Gate A pre-claim failed acceptance journal is invalid"
        ) from error
    if not isinstance(payload, dict):
        raise GateACandidateError(
            "Gate A pre-claim failed acceptance journal is invalid"
        )

    reconcile = payload.get("pre_reconcile")
    wallet = payload.get("pre_wallet_reconcile")
    cleanup = payload.get("cleanup")
    fixture_ids = payload.get("fixture_ids")
    fixture = payload.get("fixture")
    order_evidence = payload.get("order_evidence")
    timer_items = (
        order_evidence.get("expected_timer_items")
        if isinstance(order_evidence, dict)
        else None
    )
    started_at = payload.get("started_at")
    updated_at = payload.get("updated_at")
    if (
        set(payload) != PRECLAIM_ACCEPTANCE_PENDING_KEYS
        or payload.get("schema_version") != 3
        or payload.get("record_type")
        != "gatea-m9-internal-acceptance-pending"
        or payload.get("environment") != "gatea"
        or payload.get("candidate_sha") != expected_candidate_sha
        or payload.get("operations_sha") != expected_candidate_sha
        or not isinstance(payload.get("image_id"), str)
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(payload.get("image_id", ""))
        )
        is None
        or SHA_PATTERN.fullmatch(str(payload.get("source_candidate_sha", "")))
        is None
        or payload.get("source_candidate_sha") == expected_candidate_sha
        or not isinstance(payload.get("ci_run_id"), str)
        or RUN_ID_PATTERN.fullmatch(str(payload.get("ci_run_id", ""))) is None
        or any(
            SHA256_PATTERN.fullmatch(str(payload.get(field, ""))) is None
            for field in (
                "upgrade_record_sha256",
                "upgrade_plan_replay_record_sha256",
                "representative_record_sha256",
                "credentials_sha256",
                "attempt_id_sha256",
                "fixture_sha256",
                "order_evidence_sha256",
            )
        )
        or re.fullmatch(r"[0-9a-f]{32}", str(payload.get("attempt_id", "")))
        is None
        or payload.get("attempt_id_sha256")
        != _sha256_bytes(str(payload.get("attempt_id", "")).encode("utf-8"))
        or not _is_utc_timestamp(started_at)
        or not _is_utc_timestamp(updated_at)
        or _parse_utc_timestamp(updated_at, "acceptance updated-at")
        < _parse_utc_timestamp(started_at, "acceptance started-at")
        or payload.get("stage") != "order_created"
        or not isinstance(reconcile, dict)
        or set(reconcile) != PRECLAIM_ACCEPTANCE_RECONCILE_KEYS
        or any(type(value) is not int or value != 0 for value in reconcile.values())
        or not isinstance(wallet, dict)
        or set(wallet) != PRECLAIM_ACCEPTANCE_WALLET_KEYS
        or any(type(value) is not int or value < 0 for value in wallet.values())
        or wallet.get("scanned", 0) <= 0
        or wallet.get("mismatches") != 0
        or wallet.get("violations") != 0
        or not isinstance(cleanup, dict)
        or set(cleanup) != PRECLAIM_ACCEPTANCE_CLEANUP_KEYS
        or any(cleanup.get(key) is not True for key in cleanup)
        or payload.get("failure") is not True
        or payload.get("payment_committed") is not False
        or payload.get("session_released") is not False
        or any(
            payload.get(field) is not False
            for field in (
                "claim_replay_verified",
                "payment_replay_verified",
                "admin_visibility_verified",
                "release_replay_verified",
            )
        )
        or any(
            payload.get(field) is not None
            for field in (
                "table_no",
                "session_no_sha256",
                "payment_deadline_offset_seconds",
                "payment_evidence",
                "timer_evidence",
            )
        )
        or payload.get("secret_values_recorded") is not False
        or payload.get("source_volume_restored") is not False
        or payload.get("passed") is not False
        or not isinstance(fixture_ids, list)
        or len(fixture_ids) != 2
        or any(type(value) is not int or value <= 0 for value in fixture_ids)
        or len(set(fixture_ids)) != 2
        or not isinstance(fixture, dict)
        or set(fixture) != PRECLAIM_ACCEPTANCE_FIXTURE_KEYS
        or payload.get("fixture_sha256") != _canonical_json_sha256(fixture)
        or fixture_ids
        != [fixture.get("experience_product_id"), fixture.get("kit_product_id")]
        or fixture.get("option_durations_minutes") != [60, 60, 120]
        or fixture.get("option_participants") != [1, 2, 1]
        or fixture.get("option_price") != "1.00"
        or fixture.get("kit_price") != "1.00"
        or fixture.get("kit_opening_stock") != 10
        or fixture.get("product_images_created") != 2
        or fixture.get("option_images_created") != 3
        or fixture.get("products_online") is not True
        or not isinstance(fixture.get("option_ids"), list)
        or len(fixture["option_ids"]) != 3
        or any(type(value) is not int or value <= 0 for value in fixture["option_ids"])
        or len(set(fixture["option_ids"])) != 3
        or type(payload.get("order_id")) is not int
        or payload["order_id"] <= 0
        or not isinstance(order_evidence, dict)
        or set(order_evidence) != PRECLAIM_ACCEPTANCE_ORDER_KEYS
        or order_evidence.get("order_id") != payload.get("order_id")
        or payload.get("order_evidence_sha256")
        != _canonical_json_sha256(order_evidence)
        or not isinstance(timer_items, list)
        or len(timer_items) != 3
        or any(
            not isinstance(item, dict)
            or set(item) != PRECLAIM_ACCEPTANCE_TIMER_ITEM_KEYS
            or type(item.get("order_item_id")) is not int
            or item["order_item_id"] <= 0
            or item.get("duration_minutes") not in {60, 120}
            or type(item.get("quantity")) is not int
            or item["quantity"] <= 0
            for item in timer_items
        )
        or [item["duration_minutes"] for item in timer_items]
        != [60, 60, 120]
        or [item["quantity"] for item in timer_items] != [2, 1, 1]
        or len({item["order_item_id"] for item in timer_items}) != 3
        or type(order_evidence.get("kit_order_item_id")) is not int
        or order_evidence["kit_order_item_id"] <= 0
        or order_evidence["kit_order_item_id"]
        in {item["order_item_id"] for item in timer_items}
        or order_evidence.get("eligible_duration_groups")
        != [
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
        ]
    ):
        raise GateACandidateError(
            "Gate A pre-claim failed acceptance journal is not safely retireable"
        )
    return dict(payload), raw_payload, identity


def _reject_unresolved_transition_journals(
    *,
    release_record_dir: Path,
    acceptance_record_dir: Path,
    allowed_release_pending: Path | None = None,
    allowed_acceptance_candidate_sha: str | None = None,
    allowed_acceptance_pending_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Fail closed on every cross-candidate transition and acceptance sidecar."""

    allowed = (
        _lexical_absolute_path(allowed_release_pending)
        if allowed_release_pending is not None
        else None
    )
    if allowed is not None:
        expected_parent = _lexical_absolute_path(release_record_dir)
        if (
            allowed.parent != expected_parent
            or _CANDIDATE_PENDING_NAME_PATTERN.fullmatch(allowed.name) is None
        ):
            raise GateACandidateError(
                "Gate A candidate transition recovery allowance is invalid"
            )
    has_acceptance_candidate = allowed_acceptance_candidate_sha is not None
    has_acceptance_digest = allowed_acceptance_pending_sha256 is not None
    if has_acceptance_candidate != has_acceptance_digest:
        raise GateACandidateError(
            "Gate A acceptance recovery allowance must be confirmed as one pair"
        )
    allowed_acceptance_path: Path | None = None
    if has_acceptance_candidate:
        allowed_acceptance_candidate_sha = _validate_sha(
            str(allowed_acceptance_candidate_sha),
            "superseded candidate SHA",
        )
        allowed_acceptance_pending_sha256 = _validate_sha256(
            str(allowed_acceptance_pending_sha256),
            "failed acceptance digest",
        )
        allowed_acceptance_path = _lexical_absolute_path(
            _acceptance_pending_path(
                acceptance_record_dir,
                allowed_acceptance_candidate_sha,
            )
        )

    for path in _direct_children(
        release_record_dir, "Gate A release record directory"
    ):
        if not _is_candidate_pending_name(path.name):
            continue
        _require_regular_blocker(path, "Gate A candidate transition journal")
        if _CANDIDATE_PENDING_NAME_PATTERN.fullmatch(path.name) is None:
            raise GateACandidateError(
                "Gate A malformed candidate transition journal blocks mutation"
            )
        if allowed is None or _lexical_absolute_path(path) != allowed:
            raise GateACandidateError(
                "Gate A unresolved candidate transition journal blocks mutation"
            )

    acceptance_children: tuple[Path, ...] = ()
    if _path_entry_exists(
        acceptance_record_dir,
        "Gate A M9 runtime acceptance record directory",
    ):
        _require_root_directory(
            acceptance_record_dir,
            0o755,
            "Gate A M9 runtime acceptance record directory",
        )
        acceptance_children = _direct_children(
            acceptance_record_dir,
            "Gate A M9 runtime acceptance record directory",
        )
    allowed_acceptance: dict[str, Any] | None = None
    for path in acceptance_children:
        if not _is_acceptance_sidecar_name(path.name):
            continue
        _require_regular_blocker(path, "Gate A M9 runtime acceptance sidecar")
        if _ACCEPTANCE_SIDECAR_NAME_PATTERN.fullmatch(path.name) is None:
            raise GateACandidateError(
                "Gate A malformed M9 runtime acceptance sidecar blocks mutation"
            )
        if (
            allowed_acceptance_path is None
            or _lexical_absolute_path(path) != allowed_acceptance_path
            or allowed_acceptance is not None
        ):
            raise GateACandidateError(
                "Gate A M9 runtime acceptance sidecar blocks candidate mutation"
            )
        payload, _, _ = _validate_preclaim_failed_acceptance(
            path=path,
            expected_candidate_sha=str(allowed_acceptance_candidate_sha),
            expected_sha256=str(allowed_acceptance_pending_sha256),
        )
        allowed_acceptance = payload
    if allowed_acceptance_path is not None and allowed_acceptance is None:
        raise GateACandidateError(
            "Gate A confirmed failed acceptance journal is unavailable"
        )
    return allowed_acceptance


def _validate_stage_pending(
    payload: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    target_sha: str,
) -> dict[str, Any]:
    temporary_image = payload.get("temporary_image")
    adoption = expected.get("transition_kind") == "m9-candidate-adoption"
    expected_keys = (
        ADOPTION_STAGE_PENDING_KEYS if adoption else STAGE_PENDING_KEYS
    )
    expected_schema = 2 if adoption else 1
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != expected_schema
        or payload.get("record_type") != "gatea-candidate-stage-pending"
        or payload.get("phase") != "source-and-ci-verified"
        or any(payload.get(key) != value for key, value in expected.items())
        or not isinstance(temporary_image, str)
        or re.fullmatch(
            rf"pinkdoohub-gatea-stage:{re.escape(target_sha)}-[1-9][0-9]*",
            temporary_image,
        )
        is None
        or not _is_utc_timestamp(payload.get("started_at"))
        or payload.get("secret_values_recorded") is not False
    ):
        raise GateACandidateError("Gate A candidate stage pending journal is invalid")
    return dict(payload)


def _ensure_text_evidence(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        _require_root_file(path, 0o644, "Gate A candidate evidence sidecar")
        if path.read_bytes() != content:
            raise GateACandidateError("Gate A candidate evidence sidecar differs")
        return
    _write_bytes_exclusive(path, content, 0o644)


@_serialized_operation
def stage_candidate(
    *,
    source_archive: Path,
    source_archive_sha256: str,
    ci_artifact: Path,
    ci_artifact_sha256: str,
    launcher: Path,
    launcher_sha256: str,
    target_sha: str,
    source_head_sha: str,
    ci_run_id: str,
    ci_run_attempt: int,
    ci_artifact_name: str,
    confirmed_required_jobs: int,
    release_root: Path,
    staging_root: Path,
    release_record_dir: Path,
    superseded_candidate_sha: str | None = None,
    failed_acceptance_sha256: str | None = None,
    acceptance_record_dir: Path = DEFAULT_ACCEPTANCE_RECORD_DIR,
    lock_file: Path | None = DEFAULT_LOCK_FILE,
    _termination_controller: _MutationTerminationController | None = None,
) -> dict[str, Any]:
    """Install a source tree and image, leaving runtime/config/current untouched."""

    _require_root()
    if _termination_controller is None:
        raise GateACandidateError(
            "Gate A candidate stage termination guard is unavailable"
        )
    termination = _termination_controller
    target_sha = _validate_sha(target_sha, "target SHA")
    source_head_sha = _validate_sha(source_head_sha, "source head SHA")
    _validate_sha256(source_archive_sha256, "source archive digest")
    _validate_sha256(ci_artifact_sha256, "CI artifact digest")
    _validate_sha256(launcher_sha256, "launcher digest")
    if confirmed_required_jobs != 9:
        raise GateACandidateError("Exactly nine required CI jobs must be confirmed")
    if (superseded_candidate_sha is None) != (failed_acceptance_sha256 is None):
        raise GateACandidateError(
            "Gate A failed acceptance stage allowance requires paired confirmations"
        )
    if superseded_candidate_sha is not None:
        superseded_candidate_sha = _validate_sha(
            superseded_candidate_sha,
            "superseded candidate SHA",
        )
        failed_acceptance_sha256 = _validate_sha256(
            str(failed_acceptance_sha256),
            "failed acceptance digest",
        )
        if superseded_candidate_sha == target_sha:
            raise GateACandidateError(
                "Gate A superseded and target candidates must differ"
            )
    expected_artifact_name = (
        f"gatea-m7-m9-updater-{target_sha}-{ci_run_id}-{ci_run_attempt}"
    )
    if ci_artifact_name != expected_artifact_name:
        raise GateACandidateError("Gate A CI artifact name does not match the run")
    _require_root_directory(release_root, 0o755, "Gate A release root")
    _require_root_directory(staging_root, 0o700, "Gate A staging root")
    _require_root_directory(release_record_dir, 0o755, "Gate A release record directory")
    _reject_unresolved_transition_journals(
        release_record_dir=release_record_dir,
        acceptance_record_dir=acceptance_record_dir,
        allowed_release_pending=_stage_pending_path(release_record_dir, target_sha),
        allowed_acceptance_candidate_sha=superseded_candidate_sha,
        allowed_acceptance_pending_sha256=failed_acceptance_sha256,
    )
    _require_root_file(source_archive, 0o600, "Gate A source archive")
    _require_root_file(ci_artifact, 0o600, "Gate A CI artifact")
    _require_root_file(launcher, 0o700, "Gate A candidate launcher")
    if _sha256(source_archive) != source_archive_sha256:
        raise GateACandidateError("Gate A source archive digest does not match")
    if _sha256(ci_artifact) != ci_artifact_sha256:
        raise GateACandidateError("Gate A CI artifact digest does not match")
    if _sha256(launcher) != launcher_sha256:
        raise GateACandidateError("Gate A candidate launcher digest does not match")
    ci_evidence = _validate_ci_artifact(
        ci_artifact,
        target_sha=target_sha,
        source_head_sha=source_head_sha,
        run_id=ci_run_id,
        run_attempt=ci_run_attempt,
    )

    release_dir = release_root / target_sha
    record_path = _stage_record_path(release_record_dir, target_sha)
    pending_path = _stage_pending_path(release_record_dir, target_sha)
    final_image = f"pinkdoohub-gatea:{target_sha}"
    temporary_dir: Path | None = None
    temporary_image: str | None = None
    with nullcontext() if lock_file is None else _exclusive_lock(lock_file):
        temporary_dir = Path(
            tempfile.mkdtemp(prefix=f".{target_sha}.stage-", dir=staging_root)
        )
        try:
            source_evidence = _extract_source_archive(
                source_archive, temporary_dir, target_sha=target_sha
            )
            archived_launcher = temporary_dir / "scripts/release/gatea_candidate.py"
            if _sha256(archived_launcher) != launcher_sha256:
                raise GateACandidateError(
                    "Gate A launcher is not the candidate archive implementation"
                )
            github_evidence = _verify_github_provenance(
                source_root=temporary_dir,
                ci_artifact=ci_artifact,
                ci_artifact_sha256=ci_artifact_sha256,
                target_sha=target_sha,
                source_head_sha=source_head_sha,
                run_id=ci_run_id,
                run_attempt=ci_run_attempt,
                artifact_name=ci_artifact_name,
            )
            expected_pending = {
                "candidate_sha": target_sha,
                "source_head_sha": source_head_sha,
                "source_m7_sha": SOURCE_M7_SHA,
                "source_archive_sha256": source_archive_sha256,
                "launcher_sha256": launcher_sha256,
                "ci_artifact_sha256": ci_artifact_sha256,
                "ci_artifact_name": ci_artifact_name,
                **ci_evidence,
                **github_evidence,
                **{
                    key: source_evidence[key]
                    for key in (
                        "source_file_count",
                        "source_total_bytes",
                        "source_manifest_sha256",
                    )
                },
                "final_image": final_image,
                "secret_values_recorded": False,
                **(
                    {
                        "transition_kind": "m9-candidate-adoption",
                        "superseded_candidate_sha": superseded_candidate_sha,
                        "failed_acceptance_sha256": failed_acceptance_sha256,
                    }
                    if superseded_candidate_sha is not None
                    else {}
                ),
            }
            if record_path.exists() or record_path.is_symlink():
                final_record = _load_stage(
                    release_root=release_root,
                    release_record_dir=release_record_dir,
                    target_sha=target_sha,
                )
                if any(
                    final_record.get(key) != value
                    for key, value in expected_pending.items()
                    if key != "final_image"
                ) or final_record.get("image") != final_image:
                    raise GateACandidateError(
                        "Gate A completed candidate stage does not match these inputs"
                    )
                if pending_path.exists() or pending_path.is_symlink():
                    pending = _validate_stage_pending(
                        _load_json(
                            pending_path,
                            "Gate A candidate stage pending journal",
                            mode=0o600,
                        ),
                        expected=expected_pending,
                        target_sha=target_sha,
                    )
                    temporary_image = str(pending["temporary_image"])
                    pending_path.unlink()
                    _fsync_directory(release_record_dir)
                return final_record
            if pending_path.exists() or pending_path.is_symlink():
                pending = _validate_stage_pending(
                    _load_json(
                        pending_path,
                        "Gate A candidate stage pending journal",
                        mode=0o600,
                    ),
                    expected=expected_pending,
                    target_sha=target_sha,
                )
                temporary_image = str(pending["temporary_image"])
            else:
                if release_dir.exists() or release_dir.is_symlink():
                    raise GateACandidateError(
                        "Gate A target release exists without its stage journal"
                    )
                if any(
                    (release_record_dir / name).exists()
                    or (release_record_dir / name).is_symlink()
                    for name in (
                        f"{target_sha}.source-sha",
                        f"{target_sha}.ci-run-id",
                        f"{target_sha}.ci-run-attempt",
                    )
                ):
                    raise GateACandidateError(
                        "Gate A target evidence exists without its stage journal"
                    )
                if _image_exists(final_image):
                    raise GateACandidateError(
                        "Gate A target image exists without its stage journal"
                    )
                temporary_image = (
                    f"pinkdoohub-gatea-stage:{target_sha}-{os.getpid()}"
                )
                if _image_exists(temporary_image):
                    raise GateACandidateError(
                        "Gate A temporary image tag already exists"
                    )
                pending = {
                    "schema_version": (
                        2 if superseded_candidate_sha is not None else 1
                    ),
                    "record_type": "gatea-candidate-stage-pending",
                    **expected_pending,
                    "temporary_image": temporary_image,
                    "started_at": _utc_now(),
                    "phase": "source-and-ci-verified",
                }
                _write_json_exclusive(pending_path, pending, 0o600)

            if _image_exists(temporary_image):
                temporary_metadata = _inspect_image(
                    temporary_image,
                    target_sha,
                    ci_run_id=ci_run_id,
                    source_archive_sha256=source_archive_sha256,
                )
            elif _image_exists(final_image):
                # Tag 已发布而临时 Tag 未保留是合法崩溃窗口；严格标签与
                # source archive digest 足以继续，不重新拉取可能漂移的基础镜像。
                temporary_metadata = _inspect_image(
                    final_image,
                    target_sha,
                    ci_run_id=ci_run_id,
                    source_archive_sha256=source_archive_sha256,
                )
            else:
                _run(
                    (
                        "docker",
                        "build",
                        "--pull",
                        "--file",
                        str(temporary_dir / "deploy/runtime/Dockerfile"),
                        "--tag",
                        temporary_image,
                        "--label",
                        f"org.opencontainers.image.revision={target_sha}",
                        "--label",
                        f"com.pinkdoohub.gatea.ci-run={ci_run_id}",
                        "--label",
                        (
                            "com.pinkdoohub.gatea.source-archive-sha256="
                            f"{source_archive_sha256}"
                        ),
                        str(temporary_dir),
                    ),
                    cwd=temporary_dir,
                )
                temporary_metadata = _inspect_image(
                    temporary_image,
                    target_sha,
                    ci_run_id=ci_run_id,
                    source_archive_sha256=source_archive_sha256,
                )
            if release_dir.exists() or release_dir.is_symlink():
                _require_root_directory(
                    release_dir, 0o755, "Gate A candidate release"
                )
                if _source_manifest(release_dir) != {
                    key: source_evidence[key]
                    for key in (
                        "source_file_count",
                        "source_total_bytes",
                        "source_manifest_sha256",
                    )
                }:
                    raise GateACandidateError(
                        "Gate A installed source manifest changed"
                    )
            else:
                os.chmod(temporary_dir, 0o755)
                os.replace(temporary_dir, release_dir)
                _fsync_directory(release_root)
            if _image_exists(final_image):
                final_metadata = _inspect_image(
                    final_image,
                    target_sha,
                    ci_run_id=ci_run_id,
                    source_archive_sha256=source_archive_sha256,
                )
            else:
                _run(("docker", "image", "tag", temporary_image, final_image))
                final_metadata = _inspect_image(
                    final_image,
                    target_sha,
                    ci_run_id=ci_run_id,
                    source_archive_sha256=source_archive_sha256,
                )
            if final_metadata != temporary_metadata:
                raise GateACandidateError("Gate A final image identity changed")
            if _source_manifest(release_dir) != {
                key: source_evidence[key]
                for key in (
                    "source_file_count",
                    "source_total_bytes",
                    "source_manifest_sha256",
                )
            }:
                raise GateACandidateError("Gate A installed source manifest changed")

            _ensure_text_evidence(
                release_record_dir / f"{target_sha}.source-sha",
                f"{target_sha}\n".encode(),
            )
            _ensure_text_evidence(
                release_record_dir / f"{target_sha}.ci-run-id",
                f"{ci_run_id}\n".encode(),
            )
            _ensure_text_evidence(
                release_record_dir / f"{target_sha}.ci-run-attempt",
                f"{ci_run_attempt}\n".encode(),
            )
            payload = {
                "schema_version": (
                    2 if superseded_candidate_sha is not None else 1
                ),
                "record_type": "gatea-candidate-stage",
                "passed": True,
                "candidate_sha": target_sha,
                "source_head_sha": source_head_sha,
                "source_m7_sha": SOURCE_M7_SHA,
                "source_archive_sha256": source_archive_sha256,
                "launcher_sha256": launcher_sha256,
                "ci_artifact_sha256": ci_artifact_sha256,
                "ci_artifact_name": ci_artifact_name,
                **ci_evidence,
                **github_evidence,
                **{
                    key: source_evidence[key]
                    for key in (
                        "source_file_count",
                        "source_total_bytes",
                        "source_manifest_sha256",
                    )
                },
                "image": final_image,
                **final_metadata,
                "completed_at": _utc_now(),
                "secret_values_recorded": False,
                **(
                    {
                        "transition_kind": "m9-candidate-adoption",
                        "superseded_candidate_sha": superseded_candidate_sha,
                        "failed_acceptance_sha256": failed_acceptance_sha256,
                    }
                    if superseded_candidate_sha is not None
                    else {}
                ),
            }
            _write_json_exclusive(record_path, payload)
            pending_path.unlink()
            _fsync_directory(release_record_dir)
            return payload
        finally:
            _cleanup_candidate_stage(
                termination=termination,
                temporary_image=temporary_image,
                record_path=record_path,
                temporary_dir=temporary_dir,
            )


def _runtime_modules() -> tuple[Any, Any, Any]:
    try:
        from scripts.release import gatea_backup as backup
        from scripts.release import gatea_operations as gatea
        from scripts.release import gatea_upgrade as upgrade
    except ImportError as error:
        raise GateACandidateError(
            "Gate A activation must run from an installed candidate release"
        ) from error
    return gatea, backup, upgrade


def _load_stage(
    *, release_root: Path, release_record_dir: Path, target_sha: str
) -> dict[str, Any]:
    release_dir = release_root / target_sha
    _require_root_directory(release_dir, 0o755, "Gate A candidate release")
    payload = _load_json(
        _stage_record_path(release_record_dir, target_sha),
        "Gate A candidate stage record",
    )
    current_manifest = _source_manifest(release_dir)
    ci_run_id = payload.get("ci_run_id")
    ci_run_attempt = payload.get("ci_run_attempt")
    source_head_sha = payload.get("source_head_sha")
    schema_version = payload.get("schema_version")
    adoption = (
        schema_version == 2
        and payload.get("transition_kind") == "m9-candidate-adoption"
    )
    expected_keys = ADOPTION_STAGE_RECORD_KEYS if adoption else STAGE_RECORD_KEYS
    if (
        set(payload) != expected_keys
        or schema_version not in {1, 2}
        or (schema_version == 2 and not adoption)
        or payload.get("record_type") != "gatea-candidate-stage"
        or payload.get("passed") is not True
        or payload.get("candidate_sha") != target_sha
        or payload.get("source_m7_sha") != SOURCE_M7_SHA
        or not isinstance(source_head_sha, str)
        or SHA_PATTERN.fullmatch(source_head_sha) is None
        or payload.get("reported_pr_head_sha") != source_head_sha
        or not isinstance(ci_run_id, str)
        or RUN_ID_PATTERN.fullmatch(ci_run_id) is None
        or type(ci_run_attempt) is not int
        or ci_run_attempt <= 0
        or payload.get("ci_artifact_name")
        != f"gatea-m7-m9-updater-{target_sha}-{ci_run_id}-{ci_run_attempt}"
        or any(
            SHA256_PATTERN.fullmatch(str(payload.get(field, ""))) is None
            for field in (
                "source_archive_sha256",
                "launcher_sha256",
                "ci_artifact_sha256",
                "source_manifest_sha256",
                "github_required_jobs_sha256",
                "github_tree_manifest_sha256",
            )
        )
        or payload.get("github_repository") != GITHUB_REPOSITORY
        or type(payload.get("github_repository_id")) is not int
        or payload["github_repository_id"] <= 0
        or payload.get("github_workflow") != GITHUB_WORKFLOW_NAME
        or payload.get("github_workflow_path")
        not in {
            GITHUB_WORKFLOW_PATH,
            f"{GITHUB_WORKFLOW_PATH}@{GITHUB_BASE_REF}",
        }
        or payload.get("github_base_ref") != GITHUB_BASE_REF
        or type(payload.get("github_pull_request_number")) is not int
        or payload["github_pull_request_number"] <= 0
        or type(payload.get("github_run_number")) is not int
        or payload["github_run_number"] <= 0
        or type(payload.get("github_api_authenticated")) is not bool
        or payload.get("github_required_jobs_sha256")
        != GITHUB_REQUIRED_JOBS_SHA256
        or type(payload.get("github_artifact_id")) is not int
        or payload["github_artifact_id"] <= 0
        or payload.get("github_artifact_digest")
        != f"sha256:{payload.get('ci_artifact_sha256')}"
        or type(payload.get("github_artifact_size_bytes")) is not int
        or payload["github_artifact_size_bytes"] <= 0
        or payload["github_artifact_size_bytes"] > MAX_CI_BYTES
        or _github_utc_datetime(payload.get("github_artifact_expires_at")) is None
        or SHA_PATTERN.fullmatch(str(payload.get("github_tree_sha", ""))) is None
        or type(payload.get("github_blob_count")) is not int
        or payload.get("github_blob_count") != payload.get("source_file_count")
        or payload.get("image") != f"pinkdoohub-gatea:{target_sha}"
        or payload.get("architecture") != "amd64"
        or payload.get("operating_system") != "linux"
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(payload.get("image_id", "")))
        is None
        or payload.get("required_jobs_verified") != 9
        or payload.get("artifact_scan_passed") is not True
        or payload.get("ci_cleanup_passed") is not True
        or type(payload.get("artifact_file_count")) is not int
        or payload["artifact_file_count"] < len(CI_REQUIRED_FILES)
        or type(payload.get("artifact_uncompressed_bytes")) is not int
        or payload["artifact_uncompressed_bytes"] <= 0
        or not _is_utc_timestamp(payload.get("completed_at"))
        or payload.get("secret_values_recorded") is not False
        or any(payload.get(key) != value for key, value in current_manifest.items())
        or (
            adoption
            and (
                SHA_PATTERN.fullmatch(
                    str(payload.get("superseded_candidate_sha", ""))
                )
                is None
                or payload.get("superseded_candidate_sha") == target_sha
                or SHA256_PATTERN.fullmatch(
                    str(payload.get("failed_acceptance_sha256", ""))
                )
                is None
            )
        )
    ):
        raise GateACandidateError("Gate A candidate stage record is invalid")
    if (
        _load_evidence_line(
            release_record_dir / f"{target_sha}.source-sha",
            "Gate A candidate source SHA evidence",
        )
        != target_sha
        or _load_evidence_line(
            release_record_dir / f"{target_sha}.ci-run-id",
            "Gate A candidate CI run evidence",
        )
        != ci_run_id
        or _load_evidence_line(
            release_record_dir / f"{target_sha}.ci-run-attempt",
            "Gate A candidate CI attempt evidence",
        )
        != str(ci_run_attempt)
    ):
        raise GateACandidateError("Gate A candidate operation evidence changed")
    metadata = _inspect_image(
        payload["image"],
        target_sha,
        ci_run_id=ci_run_id,
        source_archive_sha256=payload["source_archive_sha256"],
    )
    if metadata["image_id"] != payload.get("image_id"):
        raise GateACandidateError("Gate A candidate image no longer matches its stage")
    return payload


def _require_execution_release(release_root: Path, target_sha: str) -> None:
    expected = (release_root / target_sha / "scripts/release/gatea_candidate.py").resolve()
    if Path(__file__).resolve() != expected:
        raise GateACandidateError(
            "Gate A command must run from the exact versioned candidate release"
        )


def _rewrite_config(original: bytes, target_sha: str) -> tuple[bytes, list[str]]:
    gatea, _, _ = _runtime_modules()
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GateACandidateError("Gate A config is not valid UTF-8") from error
    lines = text.splitlines(keepends=True)
    seen: set[str] = set()
    changed: list[str] = []
    output: list[str] = []
    claims_seen = False
    replacements = {
        "GATEA_APP_IMAGE": f"pinkdoohub-gatea:{target_sha}",
        "TABLE_SESSION_CLAIMS_ENABLED": "true",
    }
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in seen:
            raise GateACandidateError("Gate A config contains duplicate keys")
        seen.add(key)
        if key not in replacements:
            output.append(raw)
            continue
        claims_seen = claims_seen or key == "TABLE_SESSION_CLAIMS_ENABLED"
        newline = "\r\n" if raw.endswith("\r\n") else "\n"
        replacement = f"{key}={replacements[key]}{newline}"
        if raw != replacement:
            changed.append(key)
        output.append(replacement)
    if "GATEA_APP_IMAGE" not in seen:
        raise GateACandidateError("Gate A config is missing its application image")
    if not claims_seen:
        if output and not output[-1].endswith(("\n", "\r\n")):
            output[-1] += "\n"
        output.append("TABLE_SESSION_CLAIMS_ENABLED=true\n")
        changed.append("TABLE_SESSION_CLAIMS_ENABLED")
    candidate = "".join(output).encode("utf-8")

    def parse(content: bytes) -> dict[str, str]:
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        try:
            return gatea.parse_env_file(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    try:
        original_values = parse(original)
        values = parse(candidate)
        gatea.validate_config_values(values, mode="loopback")
    except Exception as error:
        raise GateACandidateError("Gate A derived config is invalid") from error
    if (
        set(original_values) - set(values)
        or set(values) - set(original_values) - {"TABLE_SESSION_CLAIMS_ENABLED"}
        or any(
            values.get(key) != value
            for key, value in original_values.items()
            if key not in replacements
        )
        or values.get("GATEA_APP_IMAGE") != replacements["GATEA_APP_IMAGE"]
    ):
        raise GateACandidateError("Gate A derived config changed an unauthorized key")
    if values.get("TABLE_SESSION_CLAIMS_ENABLED") != "true":
        raise GateACandidateError("Gate A table-session claims must be enabled")
    return candidate, sorted(set(changed))


def _read_current_target(current_link: Path, release_root: Path) -> Path:
    try:
        metadata = current_link.lstat()
    except FileNotFoundError as error:
        raise GateACandidateError("Gate A current release link is unavailable") from error
    if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_gid != 0:
        raise GateACandidateError("Gate A current release must be a root-owned symlink")
    try:
        release_root_resolved = release_root.resolve(strict=True)
        if current_link.parent.resolve(strict=True) != release_root_resolved.parent:
            raise GateACandidateError("Gate A current release link is misplaced")
        resolved = current_link.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise GateACandidateError("Gate A current release link is invalid") from error
    try:
        resolved.relative_to(release_root_resolved)
    except ValueError as error:
        raise GateACandidateError("Gate A current release escapes the release root") from error
    _require_root_directory(resolved, 0o755, "Gate A current release target")
    return resolved


def _plan_upgrade(
    *,
    config_file: Path,
    secret_dir: Path,
    source_version: int,
    source_candidate_sha: str,
    backup_id: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    release_record_dir: Path,
    lineage_source_candidate_sha: str | None = None,
    acceptance_retirement_record_sha256: str | None = None,
) -> dict[str, Any]:
    _, _, upgrade = _runtime_modules()
    try:
        adoption_arguments: dict[str, Any] = {}
        if source_version == 9:
            adoption_arguments = {
                "lineage_source_candidate_sha": lineage_source_candidate_sha,
                "acceptance_retirement_record_sha256": (
                    acceptance_retirement_record_sha256
                ),
                "confirm_lineage_source_sha": None,
                "confirm_acceptance_retirement_record_sha256": None,
            }
        return upgrade.upgrade_existing_database(
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            source_candidate_sha=source_candidate_sha,
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
            restore_record_dir=restore_record_dir,
            release_record_dir=release_record_dir,
            apply=False,
            confirm_target_sha=None,
            confirm_source_sha=None,
            confirm_backup_id=None,
            confirm_manifest_sha256=None,
            source_version=source_version,
            **adoption_arguments,
        )
    except Exception as error:
        raise GateACandidateError("Gate A upgrade plan failed") from error


def _validate_activation_journal(
    payload: Mapping[str, Any],
    *,
    source_sha: str,
    target_sha: str,
    stage: Mapping[str, Any],
    backup_id: str,
    history_path: Path,
    release_record_dir: Path,
    final: bool,
    adoption_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    adoption = adoption_binding is not None
    expected_keys = (
        ADOPTION_ACTIVATION_RECORD_KEYS
        if adoption and final
        else ADOPTION_ACTIVATION_PENDING_KEYS
        if adoption
        else ACTIVATION_RECORD_KEYS
        if final
        else ACTIVATION_PENDING_KEYS
    )
    expected_type = "gatea-config-activation" if final else "gatea-config-activation-pending"
    expected_changed_keys = (
        ["GATEA_APP_IMAGE"]
        if adoption
        else ["GATEA_APP_IMAGE", "TABLE_SESSION_CLAIMS_ENABLED"]
    )
    adoption_keys = ADOPTION_ACTIVATION_RECORD_KEYS - ACTIVATION_RECORD_KEYS
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != (2 if adoption else 1)
        or payload.get("record_type") != expected_type
        or payload.get("source_candidate_sha") != source_sha
        or payload.get("candidate_sha") != target_sha
        or payload.get("image_id") != stage.get("image_id")
        or payload.get("backup_id") != backup_id
        or SHA256_PATTERN.fullmatch(str(payload.get("manifest_sha256", "")))
        is None
        or SHA256_PATTERN.fullmatch(
            str(payload.get("source_config_sha256", ""))
        )
        is None
        or SHA256_PATTERN.fullmatch(
            str(payload.get("target_config_sha256", ""))
        )
        is None
        or payload.get("changed_keys") != expected_changed_keys
        or payload.get("history_path") != str(history_path)
        or payload.get("stage_record_sha256")
        != _sha256(_stage_record_path(release_record_dir, target_sha))
        or not _is_utc_timestamp(payload.get("started_at"))
        or payload.get("config_values_recorded") is not False
        or payload.get("secret_values_recorded") is not False
        or (
            adoption
            and any(
                payload.get(key) != adoption_binding.get(key)
                for key in adoption_keys
            )
        )
        or (final and payload.get("passed") is not True)
        or (final and not _is_utc_timestamp(payload.get("completed_at")))
    ):
        raise GateACandidateError("Gate A config activation journal is invalid")
    return dict(payload)


def _finish_activation_journal(
    *,
    pending: Mapping[str, Any],
    pending_path: Path,
    activation_path: Path,
    config_file: Path,
    history_path: Path,
) -> dict[str, Any]:
    _require_root_file(history_path, 0o600, "Gate A config rollback copy")
    source_content = history_path.read_bytes()
    if _sha256_bytes(source_content) != pending.get("source_config_sha256"):
        raise GateACandidateError("Gate A config rollback copy changed")
    target_content, changed_keys = _rewrite_config(
        source_content, str(pending["candidate_sha"])
    )
    if (
        changed_keys != pending.get("changed_keys")
        or _sha256_bytes(target_content) != pending.get("target_config_sha256")
    ):
        raise GateACandidateError("Gate A pending activation target changed")
    current_digest = _sha256(config_file)
    if current_digest == pending.get("source_config_sha256"):
        _atomic_replace_bytes(config_file, target_content, 0o640)
    elif current_digest != pending.get("target_config_sha256"):
        raise GateACandidateError("Gate A config is incompatible with activation recovery")
    final_payload = {
        **pending,
        "record_type": "gatea-config-activation",
        "completed_at": _utc_now(),
        "passed": True,
    }
    if activation_path.exists() or activation_path.is_symlink():
        raise GateACandidateError(
            "Gate A config activation record appeared during recovery"
        )
    _write_json_exclusive(activation_path, final_payload)
    pending_path.unlink(missing_ok=True)
    _fsync_directory(activation_path.parent)
    return dict(final_payload)


@_serialized_operation
def activate_config(
    *,
    source_version: int,
    source_candidate_sha: str,
    target_sha: str,
    backup_id: str,
    apply: bool,
    confirm_source_sha: str | None,
    confirm_target_sha: str | None,
    confirm_backup_id: str | None,
    confirm_manifest_sha256: str | None,
    config_file: Path,
    config_history_dir: Path,
    secret_dir: Path,
    release_root: Path,
    release_record_dir: Path,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    current_link: Path,
    lineage_source_candidate_sha: str | None = None,
    acceptance_retirement_record_sha256: str | None = None,
    confirm_lineage_source_sha: str | None = None,
    confirm_acceptance_retirement_record_sha256: str | None = None,
    acceptance_record_dir: Path = DEFAULT_ACCEPTANCE_RECORD_DIR,
    acceptance_failure_archive_dir: Path = DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    lock_file: Path | None = DEFAULT_LOCK_FILE,
    _termination_controller: _MutationTerminationController | None = None,
) -> dict[str, Any]:
    """Plan against a derived config, then atomically activate only two keys."""

    _require_root()
    target_sha = _validate_sha(target_sha, "target SHA")
    source_candidate_sha = _validate_sha(source_candidate_sha, "source SHA")
    adoption = source_version == 9
    if source_version not in {7, 9} or source_candidate_sha == target_sha:
        raise GateACandidateError(
            "Gate A config activation source transition is invalid"
        )
    adoption_values = (
        lineage_source_candidate_sha,
        acceptance_retirement_record_sha256,
        confirm_lineage_source_sha,
        confirm_acceptance_retirement_record_sha256,
    )
    if adoption:
        if (
            lineage_source_candidate_sha is None
            or acceptance_retirement_record_sha256 is None
        ):
            raise GateACandidateError(
                "Gate A M9 adoption lineage and retirement binding are required"
            )
        lineage_source_candidate_sha = _validate_sha(
            lineage_source_candidate_sha,
            "lineage source candidate SHA",
        )
        acceptance_retirement_record_sha256 = _validate_sha256(
            acceptance_retirement_record_sha256,
            "acceptance retirement record digest",
        )
        if lineage_source_candidate_sha in {source_candidate_sha, target_sha}:
            raise GateACandidateError("Gate A M9 adoption lineage is invalid")
    elif any(value is not None for value in adoption_values):
        raise GateACandidateError(
            "Gate A M7-to-M9 activation cannot accept adoption bindings"
        )
    if BACKUP_ID_PATTERN.fullmatch(backup_id) is None:
        raise GateACandidateError("Gate A backup ID is invalid")
    _require_execution_release(release_root, target_sha)
    _require_root_directory(release_record_dir, 0o755, "Gate A release record directory")
    activation_recovery_confirmed = (
        apply
        and confirm_source_sha == source_candidate_sha
        and confirm_target_sha == target_sha
        and confirm_backup_id == backup_id
        and isinstance(confirm_manifest_sha256, str)
        and SHA256_PATTERN.fullmatch(confirm_manifest_sha256) is not None
        and (
            not adoption
            or (
                confirm_lineage_source_sha == lineage_source_candidate_sha
                and confirm_acceptance_retirement_record_sha256
                == acceptance_retirement_record_sha256
            )
        )
    )
    _reject_unresolved_transition_journals(
        release_record_dir=release_record_dir,
        acceptance_record_dir=acceptance_record_dir,
        allowed_release_pending=(
            _activation_pending_path(release_record_dir, target_sha)
            if activation_recovery_confirmed
            else None
        ),
    )
    stage = _load_stage(
        release_root=release_root,
        release_record_dir=release_record_dir,
        target_sha=target_sha,
    )
    adoption_context: dict[str, Any] | None = None
    if adoption:
        adoption_context = _load_adoption_context(
            release_root=release_root,
            release_record_dir=release_record_dir,
            source_candidate_sha=source_candidate_sha,
            lineage_source_candidate_sha=str(lineage_source_candidate_sha),
            target_sha=target_sha,
            acceptance_retirement_record_sha256=str(
                acceptance_retirement_record_sha256
            ),
            acceptance_failure_archive_dir=acceptance_failure_archive_dir,
        )
    current_source_sha = (
        str(lineage_source_candidate_sha) if adoption else source_candidate_sha
    )
    unresolved_journals = (
        _stage_pending_path(release_record_dir, target_sha),
        _rollback_pending_path(release_record_dir, target_sha),
        _final_pending_path(release_record_dir, target_sha),
    )
    if any(path.exists() or path.is_symlink() for path in unresolved_journals):
        raise GateACandidateError(
            "Gate A conflicting pending journal must be resolved before activation"
        )
    _require_root_file(config_file, 0o640, "Gate A config file")
    activation_path = _activation_record_path(release_record_dir, target_sha)
    pending_path = _activation_pending_path(release_record_dir, target_sha)
    history_path = config_history_dir / f"{target_sha}.pre-activation.env"
    has_activation = activation_path.exists() or activation_path.is_symlink()
    has_pending = pending_path.exists() or pending_path.is_symlink()
    if has_activation or has_pending:
        if not apply:
            raise GateACandidateError(
                "Gate A config activation recovery requires apply confirmations"
            )
        if (
            confirm_source_sha != source_candidate_sha
            or confirm_target_sha != target_sha
            or confirm_backup_id != backup_id
            or _read_current_target(current_link, release_root)
            != release_root / current_source_sha
            or (
                adoption
                and (
                    confirm_lineage_source_sha
                    != lineage_source_candidate_sha
                    or confirm_acceptance_retirement_record_sha256
                    != acceptance_retirement_record_sha256
                )
            )
            or _rollback_record_path(release_record_dir, target_sha).exists()
            or _rollback_record_path(release_record_dir, target_sha).is_symlink()
        ):
            raise GateACandidateError(
                "Gate A config activation recovery confirmations do not match"
            )
        selected: dict[str, Any]
        if has_pending:
            selected = _validate_activation_journal(
                _load_json(
                    pending_path,
                    "Gate A config activation pending journal",
                    mode=0o600,
                ),
                source_sha=source_candidate_sha,
                target_sha=target_sha,
                stage=stage,
                backup_id=backup_id,
                history_path=history_path,
                release_record_dir=release_record_dir,
                final=False,
                adoption_binding=adoption_context,
            )
            if confirm_manifest_sha256 != selected.get("manifest_sha256"):
                raise GateACandidateError(
                    "Gate A config activation recovery manifest does not match"
                )
            if has_activation:
                completed = _validate_activation_journal(
                    _load_json(
                        activation_path, "Gate A config activation record"
                    ),
                    source_sha=source_candidate_sha,
                    target_sha=target_sha,
                    stage=stage,
                    backup_id=backup_id,
                    history_path=history_path,
                    release_record_dir=release_record_dir,
                    final=True,
                    adoption_binding=adoption_context,
                )
                if any(
                    selected.get(key) != completed.get(key)
                    for key in (
                        ADOPTION_ACTIVATION_PENDING_KEYS
                        if adoption
                        else ACTIVATION_PENDING_KEYS
                    )
                    - {"record_type"}
                ):
                    raise GateACandidateError(
                        "Gate A config activation records differ"
                    )
                if _sha256(config_file) != completed.get("target_config_sha256"):
                    raise GateACandidateError(
                        "Gate A completed config activation no longer matches"
                    )
                pending_path.unlink()
                _fsync_directory(release_record_dir)
                selected = completed
            else:
                if any(
                    path.exists() or path.is_symlink()
                    for path in _upgrade_evidence_paths(
                        release_record_dir, target_sha
                    )
                ):
                    raise GateACandidateError(
                        "Gate A upgrade started before activation recovery completed"
                    )
                selected = _finish_activation_journal(
                    pending=selected,
                    pending_path=pending_path,
                    activation_path=activation_path,
                    config_file=config_file,
                    history_path=history_path,
                )
        else:
            selected = _load_json(
                activation_path, "Gate A config activation record"
            )
        validated = _validate_activation_journal(
            selected,
            source_sha=source_candidate_sha,
            target_sha=target_sha,
            stage=stage,
            backup_id=backup_id,
            history_path=history_path,
            release_record_dir=release_record_dir,
            final=True,
            adoption_binding=adoption_context,
        )
        if (
            confirm_manifest_sha256 != validated.get("manifest_sha256")
            or _sha256(config_file) != validated.get("target_config_sha256")
        ):
            raise GateACandidateError(
                "Gate A recovered config activation no longer matches"
            )
        return validated

    original = config_file.read_bytes()
    gatea, _, _ = _runtime_modules()
    source_values = gatea.parse_env_file(config_file)
    if gatea._candidate_sha(source_values) != source_candidate_sha:
        raise GateACandidateError("Gate A config does not identify the approved source")
    if (
        adoption
        and source_values.get("TABLE_SESSION_CLAIMS_ENABLED") != "true"
    ) or (
        not adoption
        and source_values.get("TABLE_SESSION_CLAIMS_ENABLED") not in {None, "false"}
    ):
        raise GateACandidateError("Gate A source config claims state is invalid")
    if _read_current_target(current_link, release_root) != (
        release_root / current_source_sha
    ):
        raise GateACandidateError("Gate A current release does not match the source")
    if any(path.exists() or path.is_symlink() for path in _upgrade_evidence_paths(
        release_record_dir, target_sha
    )):
        raise GateACandidateError("Gate A target upgrade evidence already exists")
    target_content, changed_keys = _rewrite_config(original, target_sha)
    expected_changed_keys = (
        ["GATEA_APP_IMAGE"]
        if adoption
        else ["GATEA_APP_IMAGE", "TABLE_SESSION_CLAIMS_ENABLED"]
    )
    if changed_keys != expected_changed_keys:
        raise GateACandidateError("Gate A config activation change set is invalid")

    temporary = config_file.parent / f".{config_file.name}.candidate-{target_sha}"
    if temporary.exists() or temporary.is_symlink():
        _require_root_file(
            temporary, 0o640, "Gate A candidate config staging file"
        )
        if temporary.read_bytes() != target_content:
            raise GateACandidateError(
                "Gate A candidate config staging file already differs"
            )
    else:
        _write_bytes_exclusive(temporary, target_content, 0o640)
    try:
        plan = _plan_upgrade(
            config_file=temporary,
            secret_dir=secret_dir,
            source_version=source_version,
            source_candidate_sha=source_candidate_sha,
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
            restore_record_dir=restore_record_dir,
            release_record_dir=release_record_dir,
            lineage_source_candidate_sha=lineage_source_candidate_sha,
            acceptance_retirement_record_sha256=(
                acceptance_retirement_record_sha256
            ),
        )
        expected_source_chain = (
            list(gatea.APPROVED_TARGET_M9_CHAIN)
            if adoption
            else list(gatea.APPROVED_TARGET_M7_CHAIN)
        )
        if (
            plan.get("mode") != "plan"
            or plan.get("already_current") is not False
            or plan.get("candidate_sha") != target_sha
            or plan.get("source_candidate_sha") != source_candidate_sha
            or plan.get("backup_id") != backup_id
            or plan.get("source_version") != source_version
            or plan.get("restore_verified") is not True
            or plan.get("source_aerich_versions")
            != expected_source_chain
            or plan.get("target_aerich_versions")
            != list(gatea.APPROVED_TARGET_M9_CHAIN)
            or plan.get("target_version") != 9
            or SHA256_PATTERN.fullmatch(str(plan.get("manifest_sha256", ""))) is None
            or (
                adoption
                and (
                    plan.get("transition_kind") != "m9-candidate-adoption"
                    or plan.get("lineage_source_candidate_sha")
                    != lineage_source_candidate_sha
                    or plan.get("acceptance_retirement_record_sha256")
                    != acceptance_retirement_record_sha256
                )
            )
        ):
            raise GateACandidateError("Gate A upgrade plan is not the approved transition")
        if not apply:
            return {
                "mode": "plan",
                "config_changed": False,
                "changed_keys": changed_keys,
                "source_config_sha256": _sha256_bytes(original),
                "target_config_sha256": _sha256_bytes(target_content),
                "upgrade_plan": plan,
            }
        if (
            confirm_source_sha != source_candidate_sha
            or confirm_target_sha != target_sha
            or confirm_backup_id != backup_id
            or confirm_manifest_sha256 != plan["manifest_sha256"]
            or (
                adoption
                and (
                    confirm_lineage_source_sha != lineage_source_candidate_sha
                    or confirm_acceptance_retirement_record_sha256
                    != acceptance_retirement_record_sha256
                )
            )
        ):
            raise GateACandidateError(
                "Gate A config activation confirmations do not match the plan"
            )
        with nullcontext() if lock_file is None else _exclusive_lock(lock_file):
            if (
                _rollback_record_path(release_record_dir, target_sha).exists()
                or _rollback_record_path(
                    release_record_dir, target_sha
                ).is_symlink()
            ):
                raise GateACandidateError("Gate A candidate config was previously rolled back")
            if _activation_record_path(release_record_dir, target_sha).exists():
                raise GateACandidateError("Gate A candidate config is already activated")
            if any(
                path.exists() or path.is_symlink()
                for path in _upgrade_evidence_paths(release_record_dir, target_sha)
            ):
                raise GateACandidateError("Gate A target upgrade evidence already exists")
            if config_file.read_bytes() != original:
                raise GateACandidateError("Gate A config changed after planning")
            _ensure_root_directory(
                config_history_dir, 0o700, "Gate A config history directory"
            )
            if history_path.exists() or history_path.is_symlink():
                _require_root_file(
                    history_path, 0o600, "Gate A config rollback copy"
                )
                if history_path.read_bytes() != original:
                    raise GateACandidateError(
                        "Gate A config rollback copy already exists with different content"
                    )
            else:
                _write_bytes_exclusive(history_path, original, 0o600)
            pending = {
                "schema_version": 2 if adoption else 1,
                "record_type": "gatea-config-activation-pending",
                "source_candidate_sha": source_candidate_sha,
                "candidate_sha": target_sha,
                "image_id": stage["image_id"],
                "backup_id": backup_id,
                "manifest_sha256": plan["manifest_sha256"],
                "source_config_sha256": _sha256_bytes(original),
                "target_config_sha256": _sha256_bytes(target_content),
                "changed_keys": changed_keys,
                "history_path": str(history_path),
                "stage_record_sha256": _sha256(
                    _stage_record_path(release_record_dir, target_sha)
                ),
                "started_at": _utc_now(),
                "config_values_recorded": False,
                "secret_values_recorded": False,
                **(
                    {
                        key: adoption_context[key]
                        for key in (
                            ADOPTION_ACTIVATION_RECORD_KEYS
                            - ACTIVATION_RECORD_KEYS
                        )
                    }
                    if adoption_context is not None
                    else {}
                ),
            }
            _validate_activation_journal(
                pending,
                source_sha=source_candidate_sha,
                target_sha=target_sha,
                stage=stage,
                backup_id=backup_id,
                history_path=history_path,
                release_record_dir=release_record_dir,
                final=False,
                adoption_binding=adoption_context,
            )
            _write_json_exclusive(pending_path, pending, 0o600)
            os.replace(temporary, config_file)
            _fsync_directory(config_file.parent)
            if _sha256(config_file) != pending["target_config_sha256"]:
                raise GateACandidateError("Gate A config activation did not persist")
            final_payload = {
                **pending,
                "record_type": "gatea-config-activation",
                "completed_at": _utc_now(),
                "passed": True,
            }
            _validate_activation_journal(
                final_payload,
                source_sha=source_candidate_sha,
                target_sha=target_sha,
                stage=stage,
                backup_id=backup_id,
                history_path=history_path,
                release_record_dir=release_record_dir,
                final=True,
                adoption_binding=adoption_context,
            )
            _write_json_exclusive(activation_path, final_payload)
            pending_path.unlink()
            _fsync_directory(release_record_dir)
            return final_payload
    finally:
        temporary.unlink(missing_ok=True)


def _validate_rollback_journal(
    payload: Mapping[str, Any],
    *,
    source_sha: str,
    target_sha: str,
    activation_record_sha256: str,
    activation: Mapping[str, Any],
    database_chain: Sequence[str],
    final: bool,
    adoption_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    adoption = adoption_binding is not None
    expected_keys = (
        ADOPTION_ROLLBACK_RECORD_KEYS
        if adoption and final
        else ADOPTION_ROLLBACK_PENDING_KEYS
        if adoption
        else ROLLBACK_RECORD_KEYS
        if final
        else ROLLBACK_PENDING_KEYS
    )
    expected_type = "gatea-config-rollback" if final else "gatea-config-rollback-pending"
    adoption_keys = ADOPTION_ROLLBACK_RECORD_KEYS - ROLLBACK_RECORD_KEYS
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != (2 if adoption else 1)
        or payload.get("record_type") != expected_type
        or payload.get("source_candidate_sha") != source_sha
        or payload.get("candidate_sha") != target_sha
        or payload.get("activation_record_sha256")
        != activation_record_sha256
        or payload.get("source_config_sha256")
        != activation.get("source_config_sha256")
        or payload.get("target_config_sha256")
        != activation.get("target_config_sha256")
        or payload.get("database_chain") != list(database_chain)
        or not _is_utc_timestamp(payload.get("started_at"))
        or payload.get("secret_values_recorded") is not False
        or (
            adoption
            and any(
                payload.get(key) != adoption_binding.get(key)
                for key in adoption_keys
            )
        )
        or (final and payload.get("passed") is not True)
        or (final and not _is_utc_timestamp(payload.get("completed_at")))
    ):
        raise GateACandidateError("Gate A config rollback journal is invalid")
    return dict(payload)


def _finish_rollback_journal(
    *,
    pending: Mapping[str, Any],
    pending_path: Path,
    rollback_path: Path,
    config_file: Path,
    source_content: bytes,
) -> dict[str, Any]:
    current_digest = _sha256(config_file)
    if current_digest == pending.get("target_config_sha256"):
        _atomic_replace_bytes(config_file, source_content, 0o640)
    elif current_digest != pending.get("source_config_sha256"):
        raise GateACandidateError("Gate A config is incompatible with rollback recovery")
    final_payload = {
        **pending,
        "record_type": "gatea-config-rollback",
        "completed_at": _utc_now(),
        "passed": True,
    }
    if rollback_path.exists() or rollback_path.is_symlink():
        raise GateACandidateError(
            "Gate A config rollback record appeared during recovery"
        )
    _write_json_exclusive(rollback_path, final_payload)
    pending_path.unlink(missing_ok=True)
    _fsync_directory(rollback_path.parent)
    return dict(final_payload)


@_serialized_operation
def rollback_config(
    *,
    source_sha: str,
    target_sha: str,
    confirm_source_sha: str,
    confirm_target_sha: str,
    confirm_activation_record_sha256: str,
    config_file: Path,
    config_history_dir: Path,
    secret_dir: Path,
    release_root: Path,
    release_record_dir: Path,
    current_link: Path,
    lineage_source_candidate_sha: str | None = None,
    acceptance_retirement_record_sha256: str | None = None,
    confirm_lineage_source_sha: str | None = None,
    confirm_acceptance_retirement_record_sha256: str | None = None,
    acceptance_record_dir: Path = DEFAULT_ACCEPTANCE_RECORD_DIR,
    acceptance_failure_archive_dir: Path = DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    lock_file: Path | None = DEFAULT_LOCK_FILE,
    _termination_controller: _MutationTerminationController | None = None,
) -> dict[str, Any]:
    """Restore the immediate source config before deployment evidence exists."""

    _require_root()
    source_sha = _validate_sha(source_sha, "source SHA")
    target_sha = _validate_sha(target_sha, "target SHA")
    _validate_sha256(confirm_activation_record_sha256, "activation record digest")
    if confirm_source_sha != source_sha or confirm_target_sha != target_sha:
        raise GateACandidateError("Gate A config rollback confirmations do not match")
    _require_root_directory(release_record_dir, 0o755, "Gate A release record directory")
    _reject_unresolved_transition_journals(
        release_record_dir=release_record_dir,
        acceptance_record_dir=acceptance_record_dir,
        allowed_release_pending=_rollback_pending_path(
            release_record_dir, target_sha
        ),
    )
    _require_execution_release(release_root, target_sha)
    stage = _load_stage(
        release_root=release_root,
        release_record_dir=release_record_dir,
        target_sha=target_sha,
    )
    unresolved_predecessors = (
        _stage_pending_path(release_record_dir, target_sha),
        _activation_pending_path(release_record_dir, target_sha),
        _final_pending_path(release_record_dir, target_sha),
    )
    if any(path.exists() or path.is_symlink() for path in unresolved_predecessors):
        raise GateACandidateError(
            "Gate A predecessor pending journal must be resolved before rollback"
        )
    gatea, _, upgrade = _runtime_modules()
    activation_path = _activation_record_path(release_record_dir, target_sha)
    activation = _load_json(activation_path, "Gate A config activation record")
    if _sha256(activation_path) != confirm_activation_record_sha256:
        raise GateACandidateError("Gate A activation record digest does not match")
    adoption = activation.get("schema_version") == 2
    adoption_context: dict[str, Any] | None = None
    if adoption:
        if (
            activation.get("transition_kind") != "m9-candidate-adoption"
            or lineage_source_candidate_sha is None
            or acceptance_retirement_record_sha256 is None
        ):
            raise GateACandidateError("Gate A adoption rollback binding is invalid")
        lineage_source_candidate_sha = _validate_sha(
            lineage_source_candidate_sha,
            "lineage source candidate SHA",
        )
        acceptance_retirement_record_sha256 = _validate_sha256(
            acceptance_retirement_record_sha256,
            "acceptance retirement record digest",
        )
        if (
            confirm_lineage_source_sha != lineage_source_candidate_sha
            or confirm_acceptance_retirement_record_sha256
            != acceptance_retirement_record_sha256
        ):
            raise GateACandidateError(
                "Gate A adoption rollback confirmations do not match"
            )
        adoption_context = _load_adoption_context(
            release_root=release_root,
            release_record_dir=release_record_dir,
            source_candidate_sha=source_sha,
            lineage_source_candidate_sha=lineage_source_candidate_sha,
            target_sha=target_sha,
            acceptance_retirement_record_sha256=(
                acceptance_retirement_record_sha256
            ),
            acceptance_failure_archive_dir=acceptance_failure_archive_dir,
        )
    elif any(
        value is not None
        for value in (
            lineage_source_candidate_sha,
            acceptance_retirement_record_sha256,
            confirm_lineage_source_sha,
            confirm_acceptance_retirement_record_sha256,
        )
    ):
        raise GateACandidateError(
            "Gate A legacy rollback cannot accept adoption bindings"
        )
    history_path = config_history_dir / f"{target_sha}.pre-activation.env"
    _validate_activation_journal(
        activation,
        source_sha=source_sha,
        target_sha=target_sha,
        stage=stage,
        backup_id=str(activation.get("backup_id", "")),
        history_path=history_path,
        release_record_dir=release_record_dir,
        final=True,
        adoption_binding=adoption_context,
    )
    _require_root_file(history_path, 0o600, "Gate A config rollback copy")
    source_content = history_path.read_bytes()
    if _sha256_bytes(source_content) != activation.get("source_config_sha256"):
        raise GateACandidateError("Gate A config rollback copy changed")
    _require_root_file(config_file, 0o640, "Gate A config file")
    rollback_path = _rollback_record_path(release_record_dir, target_sha)
    pending_path = _rollback_pending_path(release_record_dir, target_sha)
    has_rollback = rollback_path.exists() or rollback_path.is_symlink()
    has_pending = pending_path.exists() or pending_path.is_symlink()
    config_digest = _sha256(config_file)
    allowed_config_digests = {activation.get("target_config_sha256")}
    if has_rollback or has_pending:
        allowed_config_digests.add(activation.get("source_config_sha256"))
    if config_digest not in allowed_config_digests:
        raise GateACandidateError("Gate A active config changed after activation")
    current_source_sha = (
        str(lineage_source_candidate_sha) if adoption else source_sha
    )
    if (
        _read_current_target(current_link, release_root)
        != release_root / current_source_sha
    ):
        raise GateACandidateError("Gate A current release no longer matches the source")
    if any(
        path.exists() or path.is_symlink()
        for path in _upgrade_evidence_paths(release_record_dir, target_sha)
    ):
        raise GateACandidateError("Gate A upgrade has started; config rollback is forbidden")

    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        require_available_port=False,
    )
    snapshot = gatea.read_database_snapshot(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
    )
    expected_chain = (
        gatea.APPROVED_TARGET_M9_CHAIN
        if adoption
        else gatea.APPROVED_TARGET_M7_CHAIN
    )
    if snapshot.get("aerich_versions") != list(expected_chain):
        raise GateACandidateError(
            "Gate A config rollback requires the exact approved chain"
        )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=M9_RUNTIME_SERVICES,
    )
    if adoption:
        gatea._ensure_services_healthy(rows, *M9_RUNTIME_SERVICES)
    else:
        gatea._ensure_services_healthy(rows, "mysql", "redis", "app", "nginx")
        upgrade._ensure_not_running(rows, "table-sweeper")

    with nullcontext() if lock_file is None else _exclusive_lock(lock_file):
        if any(
            path.exists() or path.is_symlink()
            for path in _upgrade_evidence_paths(release_record_dir, target_sha)
        ):
            raise GateACandidateError(
                "Gate A upgrade started before config rollback"
            )
        if (
            _read_current_target(current_link, release_root)
            != release_root / current_source_sha
        ):
            raise GateACandidateError("Gate A current release changed before rollback")
        final_snapshot = gatea.read_database_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
        )
        if final_snapshot.get("aerich_versions") != list(expected_chain):
            raise GateACandidateError("Gate A database changed before config rollback")
        if has_pending:
            pending = _validate_rollback_journal(
                _load_json(
                    pending_path,
                    "Gate A config rollback pending journal",
                    mode=0o600,
                ),
                source_sha=source_sha,
                target_sha=target_sha,
                activation_record_sha256=confirm_activation_record_sha256,
                activation=activation,
                database_chain=expected_chain,
                final=False,
                adoption_binding=adoption_context,
            )
            if has_rollback:
                recovered = _validate_rollback_journal(
                    _load_json(
                        rollback_path, "Gate A config rollback record"
                    ),
                    source_sha=source_sha,
                    target_sha=target_sha,
                    activation_record_sha256=confirm_activation_record_sha256,
                    activation=activation,
                    database_chain=expected_chain,
                    final=True,
                    adoption_binding=adoption_context,
                )
                if any(
                    pending.get(key) != recovered.get(key)
                    for key in (
                        ADOPTION_ROLLBACK_PENDING_KEYS
                        if adoption
                        else ROLLBACK_PENDING_KEYS
                    )
                    - {"record_type"}
                ):
                    raise GateACandidateError(
                        "Gate A config rollback records differ"
                    )
                if _sha256(config_file) != activation["source_config_sha256"]:
                    raise GateACandidateError(
                        "Gate A completed config rollback no longer matches"
                    )
                pending_path.unlink()
                _fsync_directory(release_record_dir)
                return recovered
            recovered = _finish_rollback_journal(
                pending=pending,
                pending_path=pending_path,
                rollback_path=rollback_path,
                config_file=config_file,
                source_content=source_content,
            )
            return _validate_rollback_journal(
                recovered,
                source_sha=source_sha,
                target_sha=target_sha,
                activation_record_sha256=confirm_activation_record_sha256,
                activation=activation,
                database_chain=expected_chain,
                final=True,
                adoption_binding=adoption_context,
            )
        if has_rollback:
            recovered = _validate_rollback_journal(
                _load_json(rollback_path, "Gate A config rollback record"),
                source_sha=source_sha,
                target_sha=target_sha,
                activation_record_sha256=confirm_activation_record_sha256,
                activation=activation,
                database_chain=expected_chain,
                final=True,
                adoption_binding=adoption_context,
            )
            if _sha256(config_file) != activation["source_config_sha256"]:
                raise GateACandidateError(
                    "Gate A rolled-back config no longer matches its source"
                )
            return recovered
        if _sha256(config_file) != activation["target_config_sha256"]:
            raise GateACandidateError("Gate A config changed before rollback")
        pending = {
            "schema_version": 2 if adoption else 1,
            "record_type": "gatea-config-rollback-pending",
            "source_candidate_sha": source_sha,
            "candidate_sha": target_sha,
            "activation_record_sha256": confirm_activation_record_sha256,
            "source_config_sha256": activation["source_config_sha256"],
            "target_config_sha256": activation["target_config_sha256"],
            "database_chain": list(expected_chain),
            "started_at": _utc_now(),
            "secret_values_recorded": False,
            **(
                {
                    key: adoption_context[key]
                    for key in (
                        ADOPTION_ROLLBACK_RECORD_KEYS - ROLLBACK_RECORD_KEYS
                    )
                }
                if adoption_context is not None
                else {}
            ),
        }
        _validate_rollback_journal(
            pending,
            source_sha=source_sha,
            target_sha=target_sha,
            activation_record_sha256=confirm_activation_record_sha256,
            activation=activation,
            database_chain=expected_chain,
            final=False,
            adoption_binding=adoption_context,
        )
        _write_json_exclusive(pending_path, pending, 0o600)
        completed = _finish_rollback_journal(
            pending=pending,
            pending_path=pending_path,
            rollback_path=rollback_path,
            config_file=config_file,
            source_content=source_content,
        )
        return _validate_rollback_journal(
            completed,
            source_sha=source_sha,
            target_sha=target_sha,
            activation_record_sha256=confirm_activation_record_sha256,
            activation=activation,
            database_chain=expected_chain,
            final=True,
            adoption_binding=adoption_context,
        )


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _parse_utc_timestamp(value: object, description: str) -> datetime:
    if not _is_utc_timestamp(value):
        raise GateACandidateError(f"{description} timestamp is invalid")
    return datetime.fromisoformat(str(value))


def _is_nonnegative_metric(value: object) -> bool:
    return type(value) in (int, float) and value >= 0


def _has_ordered_utc_interval(payload: Mapping[str, Any]) -> bool:
    if not _is_utc_timestamp(payload.get("started_at")) or not _is_utc_timestamp(
        payload.get("completed_at")
    ):
        return False
    return datetime.fromisoformat(str(payload["started_at"])) <= datetime.fromisoformat(
        str(payload["completed_at"])
    )


def _validate_upgrade_replay_record(
    *,
    path: Path,
    source_sha: str,
    target_sha: str,
    image_id: str,
    upgrade_path: Path,
    upgrade_record: Mapping[str, Any],
    evidence_path: Path,
    gatea: Any,
    upgrade: Any,
) -> dict[str, Any]:
    payload = _load_json(path, "Gate A M9 upgrade plan-replay record")
    if (
        upgrade_record.get("schema_version") == 2
        and upgrade_record.get("transition_kind") == "m9-candidate-adoption"
    ):
        try:
            validated = gatea._require_m9_upgrade_replay_record(
                record_dir=upgrade_path.parent,
                candidate_sha=target_sha,
                image_id=image_id,
                upgrade_record=upgrade_record,
            )
        except Exception as error:
            raise GateACandidateError(
                "Gate A M9 adoption upgrade plan-replay record is invalid"
            ) from error
        if (
            validated != payload
            or payload.get("source_candidate_sha") != source_sha
            or payload.get("source_version") != 9
            or payload.get("database_changes_applied") is not False
            or payload.get("migrations_applied") != []
            or payload.get("upgrade_record_sha256") != _sha256(upgrade_path)
            or payload.get("evidence_sha256") != _sha256(evidence_path)
        ):
            raise GateACandidateError(
                "Gate A M9 adoption upgrade plan-replay record is invalid"
            )
        return dict(payload)
    result = payload.get("result")
    expected_result_keys = {
        "already_current",
        "backup_id",
        "candidate_sha",
        "manifest_sha256",
        "mode",
        "source_aerich_versions",
        "source_version",
        "target_aerich_versions",
        "target_version",
    }
    expected_upgrade_sha256 = _sha256(upgrade_path)
    expected_evidence_sha256 = str(upgrade_record.get("evidence_sha256", ""))
    try:
        upgrade._validate_empty_table_reconcile_result(payload.get("table_reconcile"))
    except Exception as error:
        raise GateACandidateError(
            "Gate A M9 upgrade plan-replay table evidence is invalid"
        ) from error
    if (
        set(payload) != UPGRADE_REPLAY_RECORD_KEYS
        or payload.get("schema_version") != 1
        or payload.get("record_type") != "gatea-m9-upgrade-plan-replay"
        or payload.get("passed") is not True
        or payload.get("candidate_sha") != target_sha
        or payload.get("source_candidate_sha") != source_sha
        or payload.get("source_version") != 7
        or payload.get("image_id") != image_id
        or payload.get("backup_id") != upgrade_record.get("backup_id")
        or payload.get("manifest_sha256") != upgrade_record.get("manifest_sha256")
        or payload.get("upgrade_record_sha256") != expected_upgrade_sha256
        or payload.get("evidence_sha256") != expected_evidence_sha256
        or SHA256_PATTERN.fullmatch(expected_evidence_sha256) is None
        or _sha256(evidence_path) != expected_evidence_sha256
        or payload.get("database_snapshot")
        != upgrade_record.get("final_database_snapshot")
        or payload.get("image_manifest") != upgrade_record.get("final_image_manifest")
        or payload.get("table_reconcile") != upgrade_record.get("table_reconcile")
        or not isinstance(result, dict)
        or set(result) != expected_result_keys
        or result.get("mode") != "plan-replay"
        or result.get("already_current") is not True
        or result.get("candidate_sha") != target_sha
        or result.get("source_version") != 7
        or result.get("target_version") != 9
        or result.get("backup_id") != payload.get("backup_id")
        or result.get("manifest_sha256") != payload.get("manifest_sha256")
        or result.get("source_aerich_versions")
        != list(gatea.APPROVED_TARGET_M7_CHAIN)
        or result.get("target_aerich_versions")
        != list(gatea.APPROVED_TARGET_M9_CHAIN)
        or payload.get("secret_values_recorded") is not False
        or not _is_utc_timestamp(payload.get("completed_at"))
    ):
        raise GateACandidateError("Gate A M9 upgrade plan-replay record is invalid")
    return payload


def _retirement_archive_path(
    archive_dir: Path,
    source_candidate_sha: str,
    acceptance_pending_sha256: str,
) -> Path:
    return archive_dir / (
        "gatea-m9-failed-acceptance-"
        f"{source_candidate_sha}-{acceptance_pending_sha256}.json"
    )


def _load_adoption_predecessor_binding(
    *,
    release_root: Path,
    release_record_dir: Path,
    source_candidate_sha: str,
    lineage_source_candidate_sha: str,
) -> dict[str, Any]:
    """Validate the complete schema-v1 M7-to-M9 predecessor lineage."""

    gatea, _, upgrade = _runtime_modules()
    source_stage_path = _stage_record_path(
        release_record_dir, source_candidate_sha
    )
    source_stage = _load_stage(
        release_root=release_root,
        release_record_dir=release_record_dir,
        target_sha=source_candidate_sha,
    )
    source_image_id = str(source_stage.get("image_id", ""))
    source_activation_path = _activation_record_path(
        release_record_dir, source_candidate_sha
    )
    source_activation = _load_json(
        source_activation_path,
        "Gate A predecessor config activation record",
    )
    activation_backup_id = source_activation.get("backup_id")
    activation_history_path = source_activation.get("history_path")
    if (
        not isinstance(activation_backup_id, str)
        or BACKUP_ID_PATTERN.fullmatch(activation_backup_id) is None
        or not isinstance(activation_history_path, str)
        or not activation_history_path
    ):
        raise GateACandidateError(
            "Gate A predecessor config activation is invalid"
        )
    _validate_activation_journal(
        source_activation,
        source_sha=lineage_source_candidate_sha,
        target_sha=source_candidate_sha,
        stage=source_stage,
        backup_id=activation_backup_id,
        history_path=Path(activation_history_path),
        release_record_dir=release_record_dir,
        final=True,
    )
    source_upgrade_path = release_record_dir / (
        f"{source_candidate_sha}.existing-database-upgrade.json"
    )
    source_upgrade = gatea._require_upgrade_record(
        record_dir=release_record_dir,
        candidate_sha=source_candidate_sha,
        image_id=source_image_id,
    )
    source_evidence_path = release_record_dir / (
        f"{source_candidate_sha}.existing-database-upgrade.evidence.json"
    )
    source_replay_path = _upgrade_replay_record_path(
        release_record_dir, source_candidate_sha
    )
    if (
        source_upgrade.get("schema_version") != 1
        or source_upgrade.get("record_type") != "existing-database-upgrade"
        or source_upgrade.get("source_version") != 7
        or source_upgrade.get("source_candidate_sha")
        != lineage_source_candidate_sha
        or source_upgrade.get("source_image_id") in {None, ""}
        or source_upgrade.get("candidate_sha") != source_candidate_sha
        or source_upgrade.get("image_id") != source_image_id
        or source_upgrade.get("backup_id") != activation_backup_id
        or source_upgrade.get("manifest_sha256")
        != source_activation.get("manifest_sha256")
        or source_upgrade.get("target_aerich_versions")
        != list(gatea.APPROVED_TARGET_M9_CHAIN)
        or SHA256_PATTERN.fullmatch(
            str(source_upgrade.get("evidence_sha256", ""))
        )
        is None
        or _sha256(source_evidence_path) != source_upgrade.get("evidence_sha256")
    ):
        raise GateACandidateError(
            "Gate A predecessor M7-to-M9 deployment evidence is invalid"
        )
    try:
        replay = gatea._require_m9_upgrade_replay_record(
            record_dir=release_record_dir,
            candidate_sha=source_candidate_sha,
            image_id=source_image_id,
            upgrade_record=source_upgrade,
        )
    except Exception as error:
        raise GateACandidateError(
            "Gate A predecessor M9 replay evidence is invalid"
        ) from error
    if (
        replay.get("source_candidate_sha") != lineage_source_candidate_sha
        or replay.get("source_version") != 7
        or replay.get("upgrade_record_sha256") != _sha256(source_upgrade_path)
        or replay.get("evidence_sha256") != _sha256(source_evidence_path)
    ):
        raise GateACandidateError(
            "Gate A predecessor M9 replay lineage is invalid"
        )
    return {
        "source_candidate_sha": source_candidate_sha,
        "source_image_id": source_image_id,
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
        "lineage_source_image_id": str(source_upgrade["source_image_id"]),
        "predecessor_stage_record_sha256": _sha256(source_stage_path),
        "predecessor_activation_record_sha256": _sha256(
            source_activation_path
        ),
        "predecessor_upgrade_record_sha256": _sha256(source_upgrade_path),
        "predecessor_upgrade_evidence_sha256": _sha256(
            source_evidence_path
        ),
        "predecessor_upgrade_plan_replay_record_sha256": _sha256(
            source_replay_path
        ),
    }


def _failed_acceptance_business_verification(
    *,
    gatea: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    target_image_id: str,
    failed_acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    """Run B's read-only verifier against the exact identities frozen by A."""

    fixture = failed_acceptance.get("fixture")
    order_evidence = failed_acceptance.get("order_evidence")
    if not isinstance(fixture, dict) or not isinstance(order_evidence, dict):
        raise GateACandidateError(
            "Gate A failed acceptance business identities are unavailable"
        )
    timer_items = order_evidence.get("expected_timer_items")
    option_ids = fixture.get("option_ids")
    option_participants = fixture.get("option_participants")
    if (
        not isinstance(timer_items, list)
        or len(timer_items) != 3
        or not isinstance(option_ids, list)
        or len(option_ids) != 3
        or not isinstance(option_participants, list)
        or len(option_participants) != 3
    ):
        raise GateACandidateError(
            "Gate A failed acceptance business identities are invalid"
        )
    command = (
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "app",
        "python3",
        "-B",
        "-m",
        "app.tasks.gatea_m9_failed_acceptance_verify",
    )
    verifier_input = {
        "schema_version": 1,
        "candidate_sha": failed_acceptance["candidate_sha"],
        "order_id": failed_acceptance["order_id"],
        "experience_product_id": fixture["experience_product_id"],
        "kit_product_id": fixture["kit_product_id"],
        "experience_items": [
            {
                "order_item_id": item["order_item_id"],
                "option_id": option_id,
                "duration_minutes": item["duration_minutes"],
                "participants": participants,
                "day_type": "weekday",
                "price": fixture["option_price"],
                "quantity": item["quantity"],
            }
            for option_id, participants, item in zip(
                option_ids,
                option_participants,
                timer_items,
                strict=True,
            )
        ],
        "kit_item_id": order_evidence["kit_order_item_id"],
        "kit_price": fixture["kit_price"],
    }
    verifier_input_text = json.dumps(
        verifier_input,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    pinned_values = dict(values)
    pinned_values["GATEA_APP_IMAGE"] = target_image_id
    try:
        result = gatea._run_compose(
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            arguments=command,
            capture_output=True,
            check=False,
            input_text=verifier_input_text,
        )
        lines = result.stdout.splitlines()
        if result.returncode != 0 or len(lines) != 1 or not lines[0]:
            raise GateACandidateError(
                "Gate A failed acceptance business verifier refused the state"
            )
        payload = json.loads(
            lines[0], object_pairs_hook=_json_object_without_duplicates
        )
    except GateACandidateError:
        raise
    except Exception as error:
        raise GateACandidateError(
            "Gate A failed acceptance business verification failed"
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != FAILED_ACCEPTANCE_BUSINESS_VERIFICATION_KEYS
        or payload.get("schema_version") != 1
        or payload.get("passed") is not True
        or payload.get("counts") != FAILED_ACCEPTANCE_BUSINESS_COUNTS
        or payload.get("evidence_sha256")
        != FAILED_ACCEPTANCE_BUSINESS_EVIDENCE_SHA256
        or payload.get("secret_values_recorded") is not False
    ):
        raise GateACandidateError(
            "Gate A failed acceptance business verification is invalid"
        )
    return dict(payload)


def _retirement_source_runtime_context(
    *,
    config_file: Path,
    secret_dir: Path,
    current_link: Path,
    release_root: Path,
    source_candidate_sha: str,
    source_image_id: str,
    lineage_source_candidate_sha: str,
) -> tuple[Any, Any, dict[str, str]]:
    """Load and pin the exact A runtime which retirement must restore."""

    gatea, _, upgrade = _runtime_modules()
    try:
        values = gatea._validated_inputs(
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            require_available_port=False,
        )
        if (
            gatea._candidate_sha(values) != source_candidate_sha
            or gatea.validate_app_image(values) != source_image_id
            or values.get("TABLE_SESSION_CLAIMS_ENABLED") != "true"
            or _read_current_target(current_link, release_root)
            != release_root / lineage_source_candidate_sha
        ):
            raise GateACandidateError(
                "Gate A failed acceptance runtime lineage is invalid"
            )
    except GateACandidateError:
        raise
    except Exception as error:
        raise GateACandidateError(
            "Gate A failed acceptance runtime lineage could not be verified"
        ) from error
    return gatea, upgrade, dict(values)


def _assert_retirement_write_free_window(
    *,
    gatea: Any,
    upgrade: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    current_link: Path,
    release_root: Path,
    source_candidate_sha: str,
    source_image_id: str,
    lineage_source_candidate_sha: str,
) -> None:
    """Recheck A/S lineage and prove all three runtime writers are stopped."""

    try:
        current_values = gatea._validated_inputs(
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            require_available_port=False,
        )
        if (
            gatea._candidate_sha(current_values) != source_candidate_sha
            or gatea.validate_app_image(current_values) != source_image_id
            or current_values.get("TABLE_SESSION_CLAIMS_ENABLED") != "true"
            or _read_current_target(current_link, release_root)
            != release_root / lineage_source_candidate_sha
            or dict(current_values) != dict(values)
        ):
            raise GateACandidateError(
                "Gate A failed acceptance runtime lineage changed"
            )
        rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            services=M9_RUNTIME_SERVICES,
        )
        gatea._ensure_services_healthy(rows, *RETIREMENT_DATABASE_SERVICES)
        upgrade._ensure_not_running(rows, *RETIREMENT_WRITER_SERVICES)
    except (GateACandidateOperationInterrupted, KeyboardInterrupt, SystemExit):
        raise
    except GateACandidateError:
        raise
    except Exception as error:
        raise GateACandidateError(
            "Gate A failed acceptance write-free state is invalid"
        ) from error


def _stop_retirement_writers(
    *,
    gatea: Any,
    upgrade: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    current_link: Path,
    release_root: Path,
    source_candidate_sha: str,
    source_image_id: str,
    lineage_source_candidate_sha: str,
) -> None:
    """Establish retirement's write-free window before any business read."""

    pinned_values = dict(values)
    pinned_values["GATEA_APP_IMAGE"] = source_image_id
    try:
        gatea._run_compose(
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            arguments=(
                "stop",
                "--timeout",
                "30",
                *RETIREMENT_WRITER_SERVICES,
            ),
        )
        _assert_retirement_write_free_window(
            gatea=gatea,
            upgrade=upgrade,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            current_link=current_link,
            release_root=release_root,
            source_candidate_sha=source_candidate_sha,
            source_image_id=source_image_id,
            lineage_source_candidate_sha=lineage_source_candidate_sha,
        )
    except (GateACandidateOperationInterrupted, KeyboardInterrupt, SystemExit):
        raise
    except GateACandidateError:
        raise
    except Exception as error:
        raise GateACandidateError(
            "Gate A failed acceptance retirement could not establish the write-free window"
        ) from error


def _retirement_live_verification(
    *,
    gatea: Any,
    upgrade: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    current_link: Path,
    release_root: Path,
    source_candidate_sha: str,
    source_image_id: str,
    lineage_source_candidate_sha: str,
    target_image_id: str,
    failed_acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute all clean-state evidence while A's writers remain stopped."""

    assertion_arguments = {
        "gatea": gatea,
        "upgrade": upgrade,
        "values": values,
        "config_file": config_file,
        "secret_dir": secret_dir,
        "current_link": current_link,
        "release_root": release_root,
        "source_candidate_sha": source_candidate_sha,
        "source_image_id": source_image_id,
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
    }
    try:
        _assert_retirement_write_free_window(**assertion_arguments)
        database_snapshot = gatea.read_database_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
        )
        _assert_retirement_write_free_window(**assertion_arguments)
        table_reconcile = gatea._run_m9_table_reconcile(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
        )
        _assert_retirement_write_free_window(**assertion_arguments)
        wallet_reconcile = _final_wallet_reconcile(
            gatea=gatea,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
        )
        _assert_retirement_write_free_window(**assertion_arguments)
        business_verification = _failed_acceptance_business_verification(
            gatea=gatea,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            target_image_id=target_image_id,
            failed_acceptance=failed_acceptance,
        )
        _assert_retirement_write_free_window(**assertion_arguments)
    except (GateACandidateOperationInterrupted, KeyboardInterrupt, SystemExit):
        raise
    except GateACandidateError:
        raise
    except Exception as error:
        raise GateACandidateError(
            "Gate A failed acceptance live verification failed"
        ) from error
    if (
        database_snapshot.get("aerich_versions")
        != list(gatea.APPROVED_TARGET_M9_CHAIN)
        or not isinstance(table_reconcile, dict)
        or set(table_reconcile) != PRECLAIM_ACCEPTANCE_RECONCILE_KEYS
        or any(
            type(value) is not int or value != 0
            for value in table_reconcile.values()
        )
        or set(wallet_reconcile) != PRECLAIM_ACCEPTANCE_WALLET_KEYS
        or wallet_reconcile.get("scanned", 0) <= 0
        or wallet_reconcile.get("mismatches") != 0
        or wallet_reconcile.get("violations") != 0
    ):
        raise GateACandidateError(
            "Gate A failed acceptance live verification is not clean"
        )
    return {
        "business_verification": business_verification,
        "database_snapshot": dict(database_snapshot),
        "runtime_services": list(M9_RUNTIME_SERVICES),
        "database_services_healthy": list(RETIREMENT_DATABASE_SERVICES),
        "writer_services_stopped": list(RETIREMENT_WRITER_SERVICES),
        "table_reconcile": dict(table_reconcile),
        "wallet_reconcile": dict(wallet_reconcile),
        "checked_at": _utc_now(),
    }


def _validate_retirement_live_verification(payload: object) -> dict[str, Any]:
    gatea, _, _ = _runtime_modules()
    business = (
        payload.get("business_verification")
        if isinstance(payload, dict)
        else None
    )
    if (
        not isinstance(payload, dict)
        or set(payload) != RETIREMENT_LIVE_VERIFICATION_KEYS
        or not isinstance(business, dict)
        or set(business) != FAILED_ACCEPTANCE_BUSINESS_VERIFICATION_KEYS
        or business.get("schema_version") != 1
        or business.get("passed") is not True
        or business.get("counts") != FAILED_ACCEPTANCE_BUSINESS_COUNTS
        or business.get("evidence_sha256")
        != FAILED_ACCEPTANCE_BUSINESS_EVIDENCE_SHA256
        or business.get("secret_values_recorded") is not False
        or not isinstance(payload.get("database_snapshot"), dict)
        or payload["database_snapshot"].get("aerich_versions")
        != list(gatea.APPROVED_TARGET_M9_CHAIN)
        or payload.get("runtime_services") != list(M9_RUNTIME_SERVICES)
        or payload.get("database_services_healthy")
        != list(RETIREMENT_DATABASE_SERVICES)
        or payload.get("writer_services_stopped")
        != list(RETIREMENT_WRITER_SERVICES)
        or not isinstance(payload.get("table_reconcile"), dict)
        or set(payload["table_reconcile"])
        != PRECLAIM_ACCEPTANCE_RECONCILE_KEYS
        or any(
            type(value) is not int or value != 0
            for value in payload["table_reconcile"].values()
        )
        or not isinstance(payload.get("wallet_reconcile"), dict)
        or set(payload["wallet_reconcile"])
        != PRECLAIM_ACCEPTANCE_WALLET_KEYS
        or any(
            type(value) is not int or value < 0
            for value in payload["wallet_reconcile"].values()
        )
        or payload["wallet_reconcile"].get("scanned", 0) <= 0
        or payload["wallet_reconcile"].get("mismatches") != 0
        or payload["wallet_reconcile"].get("violations") != 0
        or not _is_utc_timestamp(payload.get("checked_at"))
    ):
        raise GateACandidateError(
            "Gate A failed acceptance live verification is invalid"
        )
    return dict(payload)


def _validate_retirement_journal(
    payload: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    final: bool,
) -> dict[str, Any]:
    expected_keys = RETIREMENT_RECORD_KEYS if final else RETIREMENT_PENDING_KEYS
    expected_type = (
        "gatea-m9-failed-acceptance-retirement"
        if final
        else "gatea-m9-failed-acceptance-retirement-pending"
    )
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != 1
        or payload.get("record_type") != expected_type
        or any(payload.get(key) != value for key, value in expected.items())
        or payload.get("phase") not in RETIREMENT_PENDING_PHASES
        or not _is_utc_timestamp(payload.get("started_at"))
        or payload.get("secret_values_recorded") is not False
        or (final and payload.get("phase") != "record-published")
        or (final and payload.get("passed") is not True)
        or (final and not _is_utc_timestamp(payload.get("completed_at")))
        or (
            final
            and _parse_utc_timestamp(
                payload.get("completed_at"), "retirement completed-at"
            )
            < _parse_utc_timestamp(
                payload.get("started_at"), "retirement started-at"
            )
        )
    ):
        raise GateACandidateError(
            "Gate A failed acceptance retirement journal is invalid"
        )
    if payload.get("phase") == "prepared":
        if payload.get("live_verification") is not None:
            raise GateACandidateError(
                "Gate A failed acceptance retirement prepared journal is invalid"
            )
    else:
        _validate_retirement_live_verification(payload.get("live_verification"))
    return dict(payload)


def _retirement_live_identity(payload: object) -> dict[str, Any]:
    """Compare repeat verifications while excluding only their observation time."""

    validated = _validate_retirement_live_verification(payload)
    return {
        key: value
        for key, value in validated.items()
        if key != "checked_at"
    }


def _require_retirement_live_match(
    current: Mapping[str, Any],
    recorded: object,
) -> None:
    if _retirement_live_identity(current) != _retirement_live_identity(recorded):
        raise GateACandidateError(
            "Gate A failed acceptance state drifted during retirement recovery"
        )


def _unlink_exact_protected_file(
    path: Path,
    expected_identity: tuple[int, ...],
    *,
    description: str,
) -> None:
    _require_root_directory(path.parent, 0o755, f"{description} parent directory")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        current = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if _file_identity(current) != expected_identity:
            raise GateACandidateError(f"{description} changed before removal")
        os.unlink(path.name, dir_fd=descriptor)
        os.fsync(descriptor)
    except GateACandidateError:
        raise
    except OSError as error:
        raise GateACandidateError(f"{description} could not be removed") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_retirement_record(
    *,
    release_record_dir: Path,
    target_sha: str,
    expected_sha256: str,
    expected_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_sha256(expected_sha256, "acceptance retirement record digest")
    path = _retirement_record_path(release_record_dir, target_sha)
    raw_payload, _ = _read_stable_protected_bytes(
        path,
        mode=0o644,
        max_bytes=MAX_JSON_BYTES,
        description="Gate A failed acceptance retirement record",
    )
    if _sha256_bytes(raw_payload) != expected_sha256:
        raise GateACandidateError(
            "Gate A failed acceptance retirement digest does not match"
        )
    try:
        payload = json.loads(
            raw_payload,
            object_pairs_hook=_json_object_without_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise GateACandidateError(
            "Gate A failed acceptance retirement record is invalid"
        ) from error
    if not isinstance(payload, dict):
        raise GateACandidateError(
            "Gate A failed acceptance retirement record is invalid"
        )
    expected = dict(expected_binding or {})
    return _validate_retirement_journal(payload, expected=expected, final=True)


def _validate_adoption_retirement_archive(
    *,
    acceptance_failure_archive_dir: Path,
    source_candidate_sha: str,
    failed_acceptance_sha256: str,
    lineage_source_candidate_sha: str,
    source_image_id: str,
    retirement: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-read the immutable raw failure on every downstream adoption step."""

    _require_root_directory(
        acceptance_failure_archive_dir,
        0o700,
        "Gate A failed acceptance archive directory",
    )
    expected_archive_path = _retirement_archive_path(
        acceptance_failure_archive_dir,
        source_candidate_sha,
        failed_acceptance_sha256,
    )
    if (
        _lexical_absolute_path(expected_archive_path.parent)
        != _lexical_absolute_path(acceptance_failure_archive_dir)
        or retirement.get("acceptance_archive_path")
        != str(expected_archive_path)
        or retirement.get("acceptance_archive_sha256")
        != failed_acceptance_sha256
    ):
        raise GateACandidateError(
            "Gate A failed acceptance archive binding is invalid"
        )
    archived_acceptance, _, _ = _validate_preclaim_failed_acceptance(
        path=expected_archive_path,
        expected_candidate_sha=source_candidate_sha,
        expected_sha256=failed_acceptance_sha256,
    )
    if (
        archived_acceptance.get("attempt_id_sha256")
        != retirement.get("acceptance_attempt_id_sha256")
        or archived_acceptance.get("source_candidate_sha")
        != lineage_source_candidate_sha
        or archived_acceptance.get("image_id") != source_image_id
    ):
        raise GateACandidateError(
            "Gate A failed acceptance archive lineage is invalid"
        )
    return archived_acceptance


def _load_adoption_context(
    *,
    release_root: Path,
    release_record_dir: Path,
    source_candidate_sha: str,
    lineage_source_candidate_sha: str,
    target_sha: str,
    acceptance_retirement_record_sha256: str,
    acceptance_failure_archive_dir: Path,
) -> dict[str, Any]:
    target_stage = _load_stage(
        release_root=release_root,
        release_record_dir=release_record_dir,
        target_sha=target_sha,
    )
    predecessor = _load_adoption_predecessor_binding(
        release_root=release_root,
        release_record_dir=release_record_dir,
        source_candidate_sha=source_candidate_sha,
        lineage_source_candidate_sha=lineage_source_candidate_sha,
    )
    if (
        target_stage.get("schema_version") != 2
        or target_stage.get("transition_kind") != "m9-candidate-adoption"
        or target_stage.get("superseded_candidate_sha")
        != source_candidate_sha
        or SHA256_PATTERN.fullmatch(
            str(target_stage.get("failed_acceptance_sha256", ""))
        )
        is None
    ):
        raise GateACandidateError("Gate A adoption stage binding is invalid")
    target_stage_sha256 = _sha256(
        _stage_record_path(release_record_dir, target_sha)
    )
    _require_root_directory(
        acceptance_failure_archive_dir,
        0o700,
        "Gate A failed acceptance archive directory",
    )
    expected_archive_path = _retirement_archive_path(
        acceptance_failure_archive_dir,
        source_candidate_sha,
        str(target_stage["failed_acceptance_sha256"]),
    )
    if (
        _lexical_absolute_path(expected_archive_path.parent)
        != _lexical_absolute_path(acceptance_failure_archive_dir)
    ):
        raise GateACandidateError(
            "Gate A failed acceptance archive path is invalid"
        )
    expected_retirement = {
        "candidate_sha": target_sha,
        "image_id": target_stage["image_id"],
        **predecessor,
        "stage_record_sha256": target_stage_sha256,
        "acceptance_pending_sha256": target_stage["failed_acceptance_sha256"],
        "acceptance_archive_path": str(expected_archive_path),
        "acceptance_archive_sha256": target_stage["failed_acceptance_sha256"],
    }
    retirement = _load_retirement_record(
        release_record_dir=release_record_dir,
        target_sha=target_sha,
        expected_sha256=acceptance_retirement_record_sha256,
        expected_binding=expected_retirement,
    )
    _validate_adoption_retirement_archive(
        acceptance_failure_archive_dir=acceptance_failure_archive_dir,
        source_candidate_sha=source_candidate_sha,
        failed_acceptance_sha256=str(target_stage["failed_acceptance_sha256"]),
        lineage_source_candidate_sha=lineage_source_candidate_sha,
        source_image_id=str(predecessor["source_image_id"]),
        retirement=retirement,
    )
    return {
        "transition_kind": "m9-candidate-adoption",
        "source_candidate_sha": source_candidate_sha,
        "source_image_id": predecessor["source_image_id"],
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
        "lineage_source_image_id": predecessor["lineage_source_image_id"],
        "candidate_sha": target_sha,
        "image_id": target_stage["image_id"],
        "stage_record_sha256": target_stage_sha256,
        "predecessor_stage_record_sha256": predecessor[
            "predecessor_stage_record_sha256"
        ],
        "predecessor_activation_record_sha256": predecessor[
            "predecessor_activation_record_sha256"
        ],
        "predecessor_upgrade_record_sha256": predecessor[
            "predecessor_upgrade_record_sha256"
        ],
        "predecessor_upgrade_evidence_sha256": predecessor[
            "predecessor_upgrade_evidence_sha256"
        ],
        "predecessor_upgrade_plan_replay_record_sha256": predecessor[
            "predecessor_upgrade_plan_replay_record_sha256"
        ],
        "acceptance_retirement_record_sha256": (
            acceptance_retirement_record_sha256
        ),
        "retirement": retirement,
        "stage": target_stage,
    }


def _validated_retirement_recovery_allowances(
    *,
    gatea: Any,
    release_record_dir: Path,
    acceptance_record_dir: Path,
    source_candidate_sha: str,
    target_sha: str,
    failed_acceptance_sha256: str,
    pending_path: Path,
    expected_binding: Mapping[str, Any],
) -> tuple[Any, Any | None]:
    """Build only the two exact allowances needed to restart A."""

    expected_path = _retirement_pending_path(release_record_dir, target_sha)
    if _lexical_absolute_path(pending_path) != _lexical_absolute_path(expected_path):
        raise GateACandidateError(
            "Gate A failed acceptance retirement recovery path is invalid"
        )
    canonical_pending = _acceptance_pending_path(
        acceptance_record_dir, source_candidate_sha
    )
    acceptance_exists = _path_entry_exists(
        canonical_pending,
        "Gate A failed acceptance journal",
    )
    _reject_unresolved_transition_journals(
        release_record_dir=release_record_dir,
        acceptance_record_dir=acceptance_record_dir,
        allowed_release_pending=expected_path,
        allowed_acceptance_candidate_sha=(
            source_candidate_sha if acceptance_exists else None
        ),
        allowed_acceptance_pending_sha256=(
            failed_acceptance_sha256 if acceptance_exists else None
        ),
    )
    _validate_retirement_journal(
        _load_json(
            expected_path,
            "Gate A failed acceptance retirement pending journal",
            mode=0o600,
        ),
        expected=expected_binding,
        final=False,
    )
    try:
        transition = gatea.CandidateTransitionRecoveryAllowance(
            path=expected_path,
            kind="failed-acceptance-retirement",
            candidate_sha=target_sha,
            runtime_candidate_sha=source_candidate_sha,
        )
        acceptance = (
            gatea.M9AcceptanceSidecarRecoveryAllowance(
                candidate_sha=source_candidate_sha,
                pending_path=canonical_pending,
            )
            if acceptance_exists
            else None
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise GateACandidateError(
            "Gate A operations retirement recovery API is unavailable"
        ) from error
    return transition, acceptance


def _restore_retirement_runtime(
    *,
    gatea: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    release_root: Path,
    release_record_dir: Path,
    acceptance_record_dir: Path,
    current_link: Path,
    source_candidate_sha: str,
    source_image_id: str,
    lineage_source_candidate_sha: str,
    target_sha: str,
    failed_acceptance_sha256: str,
    pending_path: Path,
    expected_binding: Mapping[str, Any],
) -> None:
    """Restart and re-prove A's exact five-service M9 runtime."""

    transition_allowance, acceptance_allowance = (
        _validated_retirement_recovery_allowances(
            gatea=gatea,
            release_record_dir=release_record_dir,
            acceptance_record_dir=acceptance_record_dir,
            source_candidate_sha=source_candidate_sha,
            target_sha=target_sha,
            failed_acceptance_sha256=failed_acceptance_sha256,
            pending_path=pending_path,
            expected_binding=expected_binding,
        )
    )
    try:
        gatea.app_up(
            config_file=config_file,
            secret_dir=secret_dir,
            record_dir=release_record_dir,
            mode="loopback",
            wait_timeout=120,
            include_table_sweeper=True,
            allow_existing_gatea_publisher=True,
            candidate_transition_recovery=transition_allowance,
            acceptance_sidecar_recovery=acceptance_allowance,
            acceptance_record_dir=acceptance_record_dir,
            _start_new_session=True,
        )
        current_values = gatea._validated_inputs(
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            require_available_port=False,
        )
        if (
            dict(current_values) != dict(values)
            or gatea._candidate_sha(current_values) != source_candidate_sha
            or gatea.validate_app_image(
                current_values, start_new_session=True
            )
            != source_image_id
            or current_values.get("TABLE_SESSION_CLAIMS_ENABLED") != "true"
            or _read_current_target(current_link, release_root)
            != release_root / lineage_source_candidate_sha
        ):
            raise GateACandidateError(
                "Gate A failed acceptance source runtime changed during recovery"
            )
        snapshot = gatea.read_database_snapshot(
            values=current_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            start_new_session=True,
        )
        if snapshot.get("aerich_versions") != list(
            gatea.APPROVED_TARGET_M9_CHAIN
        ):
            raise GateACandidateError(
                "Gate A failed acceptance source runtime is not exact M9"
            )
        rows = gatea._compose_ps(
            values=current_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            services=M9_RUNTIME_SERVICES,
            start_new_session=True,
        )
        gatea._ensure_services_healthy(rows, *M9_RUNTIME_SERVICES)
        gatea._validate_loopback_publishers(
            rows, int(current_values.get("GATEA_LOOPBACK_PORT", "18080"))
        )
    except Exception as error:
        raise GateACandidateError(
            "Gate A failed acceptance retirement could not restore the source runtime"
        ) from error


def _restore_retirement_runtime_with_shield(
    *,
    termination: _MutationTerminationController,
    **arguments: Any,
) -> None:
    """Ignore control-flow signals until A's five services are healthy again."""

    termination.begin_recovery()
    while True:
        try:
            _restore_retirement_runtime(**arguments)
        except (KeyboardInterrupt, SystemExit) as error:
            termination.remember_recovery_interruption(error)
            continue
        except BaseException as recovery_error:
            raise GateACandidateError(
                "Gate A failed acceptance source runtime recovery failed"
            ) from recovery_error
        return


_RetirementWorkResult = TypeVar("_RetirementWorkResult")


def _run_retirement_work_then_restore(
    *,
    termination: _MutationTerminationController,
    work: Callable[[], _RetirementWorkResult],
    restore_arguments: Mapping[str, Any],
) -> tuple[_RetirementWorkResult | None, BaseException | None]:
    """Run retirement work and unconditionally cross into shielded recovery."""

    result: _RetirementWorkResult | None = None
    work_error: BaseException | None = None
    try:
        try:
            result = work()
        except BaseException as error:
            work_error = error
            termination.begin_recovery()
        else:
            termination.begin_recovery()
    finally:
        termination.begin_recovery()
        _restore_retirement_runtime_with_shield(
            termination=termination,
            **dict(restore_arguments),
        )
    return result, work_error


@_serialized_operation
def retire_failed_acceptance(
    *,
    source_candidate_sha: str,
    lineage_source_candidate_sha: str,
    target_sha: str,
    failed_acceptance_sha256: str,
    confirm_source_sha: str,
    confirm_lineage_source_sha: str,
    confirm_target_sha: str,
    confirm_failed_acceptance_sha256: str,
    config_file: Path,
    secret_dir: Path,
    release_root: Path,
    release_record_dir: Path,
    acceptance_record_dir: Path = DEFAULT_ACCEPTANCE_RECORD_DIR,
    acceptance_failure_archive_dir: Path = DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    current_link: Path = DEFAULT_CURRENT_LINK,
    lock_file: Path | None = DEFAULT_LOCK_FILE,
    _termination_controller: _MutationTerminationController | None = None,
) -> dict[str, Any]:
    """Durably archive and retire one exact cleaned pre-claim failure."""

    _require_root()
    if _termination_controller is None:
        raise GateACandidateError(
            "Gate A failed acceptance retirement termination guard is unavailable"
        )
    target_sha = _validate_sha(target_sha, "target SHA")
    source_candidate_sha = _validate_sha(
        source_candidate_sha, "source candidate SHA"
    )
    lineage_source_candidate_sha = _validate_sha(
        lineage_source_candidate_sha, "lineage source candidate SHA"
    )
    failed_acceptance_sha256 = _validate_sha256(
        failed_acceptance_sha256, "failed acceptance digest"
    )
    if (
        len(
            {
                target_sha,
                source_candidate_sha,
                lineage_source_candidate_sha,
            }
        )
        != 3
        or confirm_source_sha != source_candidate_sha
        or confirm_lineage_source_sha != lineage_source_candidate_sha
        or confirm_target_sha != target_sha
        or confirm_failed_acceptance_sha256 != failed_acceptance_sha256
    ):
        raise GateACandidateError(
            "Gate A failed acceptance retirement confirmations do not match"
        )
    _require_execution_release(release_root, target_sha)
    _require_root_directory(
        release_record_dir, 0o755, "Gate A release record directory"
    )
    canonical_pending = _acceptance_pending_path(
        acceptance_record_dir, source_candidate_sha
    )
    pending_path = _retirement_pending_path(release_record_dir, target_sha)
    record_path = _retirement_record_path(release_record_dir, target_sha)
    acceptance_exists = _path_entry_exists(
        canonical_pending,
        "Gate A failed acceptance journal",
    )
    _reject_unresolved_transition_journals(
        release_record_dir=release_record_dir,
        acceptance_record_dir=acceptance_record_dir,
        allowed_release_pending=pending_path,
        allowed_acceptance_candidate_sha=(
            source_candidate_sha if acceptance_exists else None
        ),
        allowed_acceptance_pending_sha256=(
            failed_acceptance_sha256 if acceptance_exists else None
        ),
    )
    target_stage = _load_stage(
        release_root=release_root,
        release_record_dir=release_record_dir,
        target_sha=target_sha,
    )
    if (
        target_stage.get("schema_version") != 2
        or target_stage.get("transition_kind") != "m9-candidate-adoption"
        or target_stage.get("superseded_candidate_sha")
        != source_candidate_sha
        or target_stage.get("failed_acceptance_sha256")
        != failed_acceptance_sha256
    ):
        raise GateACandidateError(
            "Gate A target stage does not bind the failed acceptance allowance"
        )
    predecessor = _load_adoption_predecessor_binding(
        release_root=release_root,
        release_record_dir=release_record_dir,
        source_candidate_sha=source_candidate_sha,
        lineage_source_candidate_sha=lineage_source_candidate_sha,
    )
    if (
        _read_current_target(current_link, release_root)
        != release_root / lineage_source_candidate_sha
    ):
        raise GateACandidateError(
            "Gate A failed acceptance current lineage changed"
        )
    target_stage_path = _stage_record_path(release_record_dir, target_sha)
    archive_path = _retirement_archive_path(
        acceptance_failure_archive_dir,
        source_candidate_sha,
        failed_acceptance_sha256,
    )

    raw_payload: bytes
    acceptance_identity: tuple[int, ...] | None = None
    if acceptance_exists:
        failed, raw_payload, acceptance_identity = _validate_preclaim_failed_acceptance(
            path=canonical_pending,
            expected_candidate_sha=source_candidate_sha,
            expected_sha256=failed_acceptance_sha256,
        )
    else:
        if not _path_entry_exists(
            archive_path, "Gate A failed acceptance archive"
        ):
            raise GateACandidateError(
                "Gate A failed acceptance disappeared without a durable archive"
            )
        _require_root_directory(
            acceptance_failure_archive_dir,
            0o700,
            "Gate A failed acceptance archive directory",
        )
        failed, raw_payload, _ = _validate_preclaim_failed_acceptance(
            path=archive_path,
            expected_candidate_sha=source_candidate_sha,
            expected_sha256=failed_acceptance_sha256,
        )
    if (
        failed.get("source_candidate_sha") != lineage_source_candidate_sha
        or failed.get("image_id") != predecessor["source_image_id"]
        or failed.get("ci_run_id")
        != _load_stage(
            release_root=release_root,
            release_record_dir=release_record_dir,
            target_sha=source_candidate_sha,
        ).get("ci_run_id")
        or failed.get("upgrade_record_sha256")
        != predecessor["predecessor_upgrade_record_sha256"]
        or failed.get("upgrade_plan_replay_record_sha256")
        != predecessor["predecessor_upgrade_plan_replay_record_sha256"]
    ):
        raise GateACandidateError(
            "Gate A failed acceptance predecessor binding is invalid"
        )
    final_acceptance = acceptance_record_dir / (
        f"gatea-m9-runtime-acceptance-{source_candidate_sha}.json"
    )
    complete_acceptance = Path(f"{final_acceptance}.complete")
    if any(
        _path_entry_exists(path, "Gate A predecessor acceptance publication")
        for path in (final_acceptance, complete_acceptance)
    ):
        raise GateACandidateError(
            "Gate A successful or completing predecessor acceptance cannot retire"
        )

    expected_binding = {
        "candidate_sha": target_sha,
        "image_id": target_stage["image_id"],
        **predecessor,
        "stage_record_sha256": _sha256(target_stage_path),
        "acceptance_pending_sha256": failed_acceptance_sha256,
        "acceptance_attempt_id_sha256": failed["attempt_id_sha256"],
        "acceptance_archive_path": str(archive_path),
        "acceptance_archive_sha256": failed_acceptance_sha256,
    }
    has_pending = _path_entry_exists(
        pending_path, "Gate A failed acceptance retirement pending journal"
    )
    has_record = _path_entry_exists(
        record_path, "Gate A failed acceptance retirement record"
    )
    archive_exists = _path_entry_exists(
        archive_path, "Gate A failed acceptance archive"
    )
    if archive_exists:
        _require_root_directory(
            acceptance_failure_archive_dir,
            0o700,
            "Gate A failed acceptance archive directory",
        )
    if not acceptance_exists and not has_record:
        raise GateACandidateError(
            "Gate A failed acceptance retirement recovery evidence is incomplete"
        )

    if has_pending:
        pending = _validate_retirement_journal(
            _load_json(
                pending_path,
                "Gate A failed acceptance retirement pending journal",
                mode=0o600,
            ),
            expected=expected_binding,
            final=False,
        )
    else:
        if has_record:
            if acceptance_exists:
                raise GateACandidateError(
                    "Gate A failed acceptance retirement journal is missing"
                )
            return _load_retirement_record(
                release_record_dir=release_record_dir,
                target_sha=target_sha,
                expected_sha256=_sha256(record_path),
                expected_binding=expected_binding,
            )
        if archive_exists:
            raise GateACandidateError(
                "Gate A failed acceptance archive has no retirement journal"
            )
        pending = {
            "schema_version": 1,
            "record_type": "gatea-m9-failed-acceptance-retirement-pending",
            **expected_binding,
            "live_verification": None,
            "started_at": _utc_now(),
            "phase": "prepared",
            "secret_values_recorded": False,
        }
        _validate_retirement_journal(
            pending,
            expected=expected_binding,
            final=False,
        )
        _write_json_exclusive(pending_path, pending, 0o600)
    if has_record and pending["phase"] in {"prepared", "write-free-verified"}:
        raise GateACandidateError(
            "Gate A failed acceptance retirement record appeared too early"
        )
    if (
        pending["phase"]
        in {"record-published", "canonical-removed", "runtime-restored"}
        and not has_record
    ):
        raise GateACandidateError(
            "Gate A failed acceptance retirement record is missing"
        )

    gatea, upgrade, values = _retirement_source_runtime_context(
        config_file=config_file,
        secret_dir=secret_dir,
        current_link=current_link,
        release_root=release_root,
        source_candidate_sha=source_candidate_sha,
        source_image_id=str(predecessor["source_image_id"]),
        lineage_source_candidate_sha=lineage_source_candidate_sha,
    )

    def perform_retirement() -> tuple[dict[str, Any], dict[str, Any]]:
        nonlocal pending
        _stop_retirement_writers(
            gatea=gatea,
            upgrade=upgrade,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            current_link=current_link,
            release_root=release_root,
            source_candidate_sha=source_candidate_sha,
            source_image_id=str(predecessor["source_image_id"]),
            lineage_source_candidate_sha=lineage_source_candidate_sha,
        )
        current_live_verification = _retirement_live_verification(
            gatea=gatea,
            upgrade=upgrade,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            current_link=current_link,
            release_root=release_root,
            source_candidate_sha=source_candidate_sha,
            source_image_id=str(predecessor["source_image_id"]),
            lineage_source_candidate_sha=lineage_source_candidate_sha,
            target_image_id=str(target_stage["image_id"]),
            failed_acceptance=failed,
        )
        if pending["live_verification"] is not None:
            _require_retirement_live_match(
                current_live_verification,
                pending["live_verification"],
            )
        if has_record:
            recorded = _load_retirement_record(
                release_record_dir=release_record_dir,
                target_sha=target_sha,
                expected_sha256=_sha256(record_path),
                expected_binding=expected_binding,
            )
            _require_retirement_live_match(
                current_live_verification,
                recorded["live_verification"],
            )
        if pending["phase"] == "prepared":
            pending = {
                **pending,
                "live_verification": current_live_verification,
                "phase": "write-free-verified",
            }
            _atomic_replace_json(pending_path, pending, 0o600)

        if pending["phase"] == "write-free-verified":
            _ensure_root_directory(
                acceptance_failure_archive_dir,
                0o700,
                "Gate A failed acceptance archive directory",
            )
            if _path_entry_exists(
                archive_path, "Gate A failed acceptance archive"
            ):
                archived_raw, _ = _read_stable_protected_bytes(
                    archive_path,
                    mode=0o600,
                    max_bytes=MAX_ACCEPTANCE_PENDING_BYTES,
                    description="Gate A failed acceptance archive",
                )
                if archived_raw != raw_payload:
                    raise GateACandidateError(
                        "Gate A failed acceptance archive differs"
                    )
            else:
                _write_bytes_exclusive(archive_path, raw_payload, 0o600)
            pending = {**pending, "phase": "acceptance-archived"}
            _atomic_replace_json(pending_path, pending, 0o600)

        _require_root_directory(
            acceptance_failure_archive_dir,
            0o700,
            "Gate A failed acceptance archive directory",
        )
        archived_raw, _ = _read_stable_protected_bytes(
            archive_path,
            mode=0o600,
            max_bytes=MAX_ACCEPTANCE_PENDING_BYTES,
            description="Gate A failed acceptance archive",
        )
        if (
            archived_raw != raw_payload
            or _sha256_bytes(archived_raw) != failed_acceptance_sha256
        ):
            raise GateACandidateError(
                "Gate A failed acceptance archive changed"
            )

        if _path_entry_exists(
            record_path, "Gate A failed acceptance retirement record"
        ):
            final_payload = _load_retirement_record(
                release_record_dir=release_record_dir,
                target_sha=target_sha,
                expected_sha256=_sha256(record_path),
                expected_binding=expected_binding,
            )
            _require_retirement_live_match(
                current_live_verification,
                final_payload["live_verification"],
            )
        else:
            final_payload = {
                **pending,
                "record_type": "gatea-m9-failed-acceptance-retirement",
                "phase": "record-published",
                "completed_at": _utc_now(),
                "passed": True,
            }
            _validate_retirement_journal(
                final_payload,
                expected=expected_binding,
                final=True,
            )
            _write_json_exclusive(record_path, final_payload)
        if pending["phase"] in {
            "acceptance-archived",
        }:
            pending = {**pending, "phase": "record-published"}
            _atomic_replace_json(pending_path, pending, 0o600)

        if pending["phase"] == "record-published":
            if _path_entry_exists(
                canonical_pending, "Gate A failed acceptance journal"
            ):
                if acceptance_identity is None:
                    raise GateACandidateError(
                        "Gate A failed acceptance identity is unavailable"
                    )
                _unlink_exact_protected_file(
                    canonical_pending,
                    acceptance_identity,
                    description="Gate A failed acceptance journal",
                )
            pending = {**pending, "phase": "canonical-removed"}
            _atomic_replace_json(pending_path, pending, 0o600)
        return dict(final_payload), dict(pending)

    restore_arguments = {
        "gatea": gatea,
        "values": values,
        "config_file": config_file,
        "secret_dir": secret_dir,
        "release_root": release_root,
        "release_record_dir": release_record_dir,
        "acceptance_record_dir": acceptance_record_dir,
        "current_link": current_link,
        "source_candidate_sha": source_candidate_sha,
        "source_image_id": str(predecessor["source_image_id"]),
        "lineage_source_candidate_sha": lineage_source_candidate_sha,
        "target_sha": target_sha,
        "failed_acceptance_sha256": failed_acceptance_sha256,
        "pending_path": pending_path,
        "expected_binding": expected_binding,
    }
    work_result, work_error = _run_retirement_work_then_restore(
        termination=_termination_controller,
        work=perform_retirement,
        restore_arguments=restore_arguments,
    )
    if work_error is not None or _termination_controller.work_interruption is not None:
        propagated_error = _finalization_error_after_recovery(
            termination=_termination_controller,
            work_error=work_error,
        )
        if propagated_error is not None:
            raise propagated_error
    if work_result is None:
        raise GateACandidateError(
            "Gate A failed acceptance retirement produced no durable result"
        )
    final_payload, completed_pending = work_result
    restored_pending = {**completed_pending, "phase": "runtime-restored"}
    _atomic_replace_json(pending_path, restored_pending, 0o600)
    pending_path.unlink()
    _fsync_directory(release_record_dir)
    if (
        propagated_error := _finalization_error_after_recovery(
            termination=_termination_controller,
            work_error=None,
        )
    ) is not None:
        raise propagated_error
    return dict(final_payload)


def _acceptance_sidecar_paths(path: Path) -> tuple[Path, Path]:
    return (Path(f"{path}.pending"), Path(f"{path}.complete"))


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """Freeze metadata fields unaffected by atime changes during reads."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_stable_acceptance_record(path: Path, expected_sha256: str) -> bytes:
    """Read one immutable acceptance final while rejecting publication sidecars."""

    _validate_sha256(expected_sha256, "runtime acceptance record digest")
    if any(
        _path_entry_exists(sidecar, "Gate A M9 runtime acceptance sidecar")
        for sidecar in _acceptance_sidecar_paths(path)
    ):
        raise GateACandidateError(
            "Gate A M9 runtime acceptance sidecar requires manual review"
        )
    _require_root_file(path, 0o644, "Gate A M9 runtime acceptance record")
    try:
        before_metadata = path.lstat()
        if before_metadata.st_size > MAX_JSON_BYTES:
            raise GateACandidateError(
                "Gate A M9 runtime acceptance record is unexpectedly large"
            )
        raw_payload = path.read_bytes()
        after_metadata = path.lstat()
    except OSError as error:
        raise GateACandidateError(
            "Gate A M9 runtime acceptance record could not be read"
        ) from error
    if (
        stat.S_ISLNK(before_metadata.st_mode)
        or not stat.S_ISREG(before_metadata.st_mode)
        or stat.S_ISLNK(after_metadata.st_mode)
        or not stat.S_ISREG(after_metadata.st_mode)
        or _file_identity(before_metadata) != _file_identity(after_metadata)
    ):
        raise GateACandidateError(
            "Gate A M9 runtime acceptance record changed during validation"
        )
    if any(
        _path_entry_exists(sidecar, "Gate A M9 runtime acceptance sidecar")
        for sidecar in _acceptance_sidecar_paths(path)
    ):
        raise GateACandidateError(
            "Gate A M9 runtime acceptance sidecar requires manual review"
        )
    if _sha256_bytes(raw_payload) != expected_sha256:
        raise GateACandidateError(
            "Gate A runtime acceptance record digest does not match"
        )
    return raw_payload


def _validate_acceptance_record(
    path: Path,
    *,
    expected_sha256: str,
    source_sha: str,
    target_sha: str,
    image_id: str,
    ci_run_id: str,
    upgrade_record_sha256: str,
    upgrade_replay_record_sha256: str,
) -> dict[str, Any]:
    raw_payload = _read_stable_acceptance_record(path, expected_sha256)
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateACandidateError(
            "Gate A M9 runtime acceptance record is invalid"
        ) from error
    if not isinstance(payload, dict):
        raise GateACandidateError(
            "Gate A M9 runtime acceptance record has an invalid shape"
        )
    try:
        from scripts.release import gatea_m9_acceptance as acceptance

        acceptance._validate_success_record(payload)
    except Exception as error:
        raise GateACandidateError("Gate A M9 runtime acceptance record is invalid") from error
    if (
        payload.get("schema_version") != 1
        or payload.get("record_type") != "gatea-m9-runtime-acceptance"
        or payload.get("source_candidate_sha") != source_sha
        or payload.get("candidate_sha") != target_sha
        or payload.get("image_id") != image_id
        or payload.get("operations_sha") != target_sha
        or payload.get("ci_run_id") != ci_run_id
        or payload.get("upgrade_record_sha256") != upgrade_record_sha256
        or payload.get("upgrade_plan_replay_record_sha256")
        != upgrade_replay_record_sha256
        or payload.get("runtime_services") != list(M9_RUNTIME_SERVICES)
        or any(
            payload.get(field) is not True
            for field in ACCEPTANCE_REQUIRED_TRUE_FIELDS
        )
        or any(
            payload.get(field) is not False
            for field in ACCEPTANCE_REQUIRED_FALSE_FIELDS
        )
    ):
        raise GateACandidateError("Gate A M9 runtime acceptance record is invalid")
    return payload


def _ensure_resilience_publication_artifacts_absent(
    path: Path,
    record_dir: Path,
) -> None:
    """只接受已收口的 resilience final，不替上游清理 temp 或 sidecar。"""

    hidden_prefix = f".{path.name}"
    sidecar_prefix = f"{path.name}."
    for artifact in _direct_children(
        record_dir,
        "Gate A resilience record directory",
    ):
        if artifact == path:
            continue
        if artifact.name.startswith((hidden_prefix, sidecar_prefix)):
            raise GateACandidateError(
                "Gate A resilience record publication is not settled"
            )


def _read_settled_resilience_record(
    path: Path,
    *,
    record_dir: Path,
    expected_sha256: str,
) -> bytes:
    """稳定读取 canonical final，并拒绝 hard-link/temp/sidecar 崩溃窗口。"""

    _validate_sha256(expected_sha256, "resilience record digest")
    _ensure_resilience_publication_artifacts_absent(path, record_dir)
    _require_root_file(path, 0o644, "Gate A M9 resilience record")
    try:
        before_metadata = path.lstat()
        if before_metadata.st_size > MAX_JSON_BYTES:
            raise GateACandidateError(
                "Gate A M9 resilience record is unexpectedly large"
            )
        raw_payload = path.read_bytes()
        after_metadata = path.lstat()
    except GateACandidateError:
        raise
    except OSError as error:
        raise GateACandidateError(
            "Gate A M9 resilience record could not be read"
        ) from error
    if (
        stat.S_ISLNK(before_metadata.st_mode)
        or not stat.S_ISREG(before_metadata.st_mode)
        or before_metadata.st_nlink != 1
        or stat.S_ISLNK(after_metadata.st_mode)
        or not stat.S_ISREG(after_metadata.st_mode)
        or after_metadata.st_nlink != 1
        or _file_identity(before_metadata) != _file_identity(after_metadata)
    ):
        raise GateACandidateError(
            "Gate A M9 resilience record publication is not settled"
        )
    _ensure_resilience_publication_artifacts_absent(path, record_dir)
    if _sha256_bytes(raw_payload) != expected_sha256:
        raise GateACandidateError(
            "Gate A resilience record digest does not match"
        )
    return raw_payload


def _validate_resilience_record(
    path: Path,
    *,
    record_dir: Path | None = None,
    expected_sha256: str,
    source_sha: str,
    source_image_id: str,
    target_sha: str,
    image_id: str,
    runtime_acceptance_record_sha256: str,
    runtime_acceptance_attempt_id_sha256: str,
    runtime_acceptance_completed_at: str,
) -> dict[str, Any]:
    selected_record_dir = record_dir or path.parent
    raw_payload = _read_settled_resilience_record(
        path,
        record_dir=selected_record_dir,
        expected_sha256=expected_sha256,
    )
    _validate_sha256(
        runtime_acceptance_record_sha256,
        "runtime acceptance record digest binding",
    )
    _validate_sha256(
        runtime_acceptance_attempt_id_sha256,
        "runtime acceptance attempt digest binding",
    )
    if not _is_utc_timestamp(runtime_acceptance_completed_at):
        raise GateACandidateError(
            "Gate A runtime acceptance completion binding is invalid"
        )
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateACandidateError(
            "Gate A M9 resilience record is invalid"
        ) from error
    if not isinstance(payload, dict):
        raise GateACandidateError(
            "Gate A M9 resilience record has an invalid shape"
        )
    dependency_drills = payload.get("dependency_drills")
    app_restart = payload.get("app_restart")
    content_snapshots = payload.get("database_content_snapshots")
    log_rotation = payload.get("log_rotation")
    log_observability = payload.get("log_observability")
    dependency_keys = {
        "service",
        "started_at",
        "completed_at",
        "outage_readiness_status",
        "outage_liveness_status",
        "failure_detection_seconds",
        "service_recovery_seconds",
        "readiness_recovery_seconds",
        "recovered_readiness_status",
        "passed",
    }
    app_restart_keys = {
        "started_at",
        "completed_at",
        "total_seconds",
        "service_recovery_seconds",
        "readiness_recovery_seconds",
        "readiness_status",
        "passed",
    }
    log_observability_keys = {
        "window",
        "combined_line_count",
        "nginx_request_count",
        "nginx_4xx_count",
        "nginx_5xx_count",
        "request_time_seconds",
        "exact_secret_matches",
        "forbidden_pattern_matches",
        "raw_log_content_recorded",
        "passed",
    }
    request_time_keys = {"median", "p95", "max"}
    try:
        from scripts.release import gatea_backup as backup

        if not isinstance(content_snapshots, dict) or set(content_snapshots) != {
            "m7_preserved_business",
            "m8_swatch_content",
            "m9_table_business",
        }:
            raise ValueError
        m7_content = backup._validate_m7_content_snapshot(
            content_snapshots["m7_preserved_business"]
        )
        m8_swatch_content = backup._validate_m8_swatch_content_snapshot(
            content_snapshots["m8_swatch_content"]
        )
        m9_content = backup._validate_m9_table_content_snapshot(
            content_snapshots["m9_table_business"]
        )
    except Exception as error:
        raise GateACandidateError(
            "Gate A M9 resilience content evidence is invalid"
        ) from error
    request_time = (
        log_observability.get("request_time_seconds")
        if isinstance(log_observability, dict)
        else None
    )
    if (
        set(payload) != RESILIENCE_RECORD_KEYS
        or payload.get("schema_version") != 2
        or payload.get("candidate_sha") != target_sha
        or payload.get("image_id") != image_id
        or payload.get("representative_candidate_sha") != source_sha
        or payload.get("representative_image_id") != source_image_id
        or payload.get("runtime_acceptance_record_sha256")
        != runtime_acceptance_record_sha256
        or payload.get("runtime_acceptance_attempt_id_sha256")
        != runtime_acceptance_attempt_id_sha256
        or payload.get("runtime_acceptance_completed_at")
        != runtime_acceptance_completed_at
        or SHA256_PATTERN.fullmatch(
            str(payload.get("representative_record_sha256", ""))
        )
        is None
        or not _has_ordered_utc_interval(payload)
        or not isinstance(dependency_drills, list)
        or len(dependency_drills) != 2
        or any(not isinstance(item, dict) for item in dependency_drills)
        or [item.get("service") for item in dependency_drills]
        != ["mysql", "redis"]
        or any(
            set(item) != dependency_keys
            or item.get("passed") is not True
            or item.get("outage_readiness_status") != 503
            or item.get("outage_liveness_status") != 200
            or item.get("recovered_readiness_status") != 200
            or not _has_ordered_utc_interval(item)
            or any(
                not _is_nonnegative_metric(item.get(field))
                for field in (
                    "failure_detection_seconds",
                    "service_recovery_seconds",
                    "readiness_recovery_seconds",
                )
            )
            for item in dependency_drills
        )
        or not isinstance(app_restart, dict)
        or set(app_restart) != app_restart_keys
        or app_restart.get("passed") is not True
        or app_restart.get("readiness_status") != 200
        or not _has_ordered_utc_interval(app_restart)
        or any(
            not _is_nonnegative_metric(app_restart.get(field))
            for field in (
                "total_seconds",
                "service_recovery_seconds",
                "readiness_recovery_seconds",
            )
        )
        or content_snapshots.get("m7_preserved_business") != m7_content
        or content_snapshots.get("m8_swatch_content")
        != m8_swatch_content
        or content_snapshots.get("m9_table_business") != m9_content
        or payload.get("runtime_services") != list(M9_RUNTIME_SERVICES)
        or not isinstance(log_rotation, dict)
        or set(log_rotation) != set(M9_RUNTIME_SERVICES)
        or any(
            value
            != {"driver": "json-file", "max_file": "5", "max_size": "10m"}
            for value in log_rotation.values()
        )
        or not isinstance(log_observability, dict)
        or set(log_observability) != log_observability_keys
        or log_observability.get("window") != "24h"
        or type(log_observability.get("combined_line_count")) is not int
        or log_observability["combined_line_count"] <= 0
        or type(log_observability.get("nginx_request_count")) is not int
        or log_observability["nginx_request_count"] <= 0
        or any(
            type(log_observability.get(field)) is not int
            or log_observability[field] < 0
            or log_observability[field] > log_observability["nginx_request_count"]
            for field in ("nginx_4xx_count", "nginx_5xx_count")
        )
        or not isinstance(request_time, dict)
        or set(request_time) != request_time_keys
        or any(not _is_nonnegative_metric(request_time.get(field)) for field in request_time_keys)
        or log_observability.get("exact_secret_matches") != 0
        or log_observability.get("forbidden_pattern_matches") != 0
        or log_observability.get("raw_log_content_recorded") is not False
        or log_observability.get("passed") is not True
        or payload.get("table_sweeper_included") is not True
        or payload.get("database_snapshot_unchanged") is not True
        or payload.get("database_content_snapshots_unchanged") is not True
        or payload.get("image_manifest_unchanged") is not True
        or type(payload.get("image_file_count")) is not int
        or payload["image_file_count"] <= 0
        or payload.get("source_services_healthy") is not True
        or payload.get("loopback_only") is not True
        or payload.get("passed") is not True
        or payload.get("pii_recorded") is not False
        or payload.get("secret_values_recorded") is not False
    ):
        raise GateACandidateError("Gate A M9 resilience record is invalid")
    return payload


def _validate_post_backup(
    *,
    backup_id: str,
    target_sha: str,
    image_id: str,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    gatea, backup, _ = _runtime_modules()
    backup_path = backup_record_dir / f"{backup_id}.json"
    restore_path = restore_record_dir / f"{backup_id}.json"
    backup_payload = _load_json(backup_path, "Gate A M9 backup record")
    restore_payload = _load_json(restore_path, "Gate A M9 restore record")
    try:
        verified_backup, _, _ = backup._load_backup_record(
            backup_id=backup_id,
            backup_root=backup_root,
            backup_record_dir=backup_record_dir,
        )
    except Exception as error:
        raise GateACandidateError("Gate A M9 backup artifacts are invalid") from error
    if verified_backup != backup_payload:
        raise GateACandidateError("Gate A M9 backup record changed during validation")
    versions = backup_payload.get("database_snapshot", {}).get("aerich_versions")
    exact_m9 = versions == ",".join(gatea.APPROVED_TARGET_M9_CHAIN)
    try:
        m7_snapshot = backup._validate_m7_content_snapshot(
            backup_payload.get("m7_content_snapshot")
        )
        m8_swatch_snapshot = backup._validate_m8_swatch_content_snapshot(
            backup_payload.get("m8_swatch_content_snapshot")
        )
        m9_snapshot = backup._validate_m9_table_content_snapshot(
            backup_payload.get("m9_table_content_snapshot")
        )
        restored_m7 = backup._validate_m7_content_snapshot(
            restore_payload.get("m7_content_snapshot")
        )
        restored_m8_swatch = backup._validate_m8_swatch_content_snapshot(
            restore_payload.get("m8_swatch_content_snapshot")
        )
        restored_m9 = backup._validate_m9_table_content_snapshot(
            restore_payload.get("m9_table_content_snapshot")
        )
    except Exception as error:
        raise GateACandidateError("Gate A M9 backup content evidence is invalid") from error
    if (
        not exact_m9
        or backup_payload.get("schema_version") != 1
        or backup_payload.get("backup_id") != backup_id
        or backup_payload.get("candidate_sha") != target_sha
        or backup_payload.get("image_id") != image_id
        or not _has_ordered_utc_interval(backup_payload)
        or backup_payload.get("redis_recovery_policy")
        != "start-empty-and-invalidate-refresh-sessions"
        or backup_payload.get("application_restarted") is not True
        or backup_payload.get("table_sweeper_restarted") is not True
        or backup_payload.get("passed") is not True
        or restore_payload.get("schema_version") != 1
        or restore_payload.get("backup_id") != backup_id
        or restore_payload.get("restore_project") != backup.restore_project(backup_id)
        or restore_payload.get("candidate_sha") != target_sha
        or restore_payload.get("backup_record_sha256") != _sha256(backup_path)
        or restore_payload.get("mysql_artifact_sha256")
        != backup_payload.get("artifacts", {}).get("mysql", {}).get("sha256")
        or restore_payload.get("image_artifact_sha256")
        != backup_payload.get("artifacts", {}).get("images", {}).get("sha256")
        or not _has_ordered_utc_interval(restore_payload)
        or restore_payload.get("host_ports_published") is not False
        or restore_payload.get("m7_content_matches") is not True
        or restore_payload.get("m8_swatch_content_matches") is not True
        or restore_payload.get("m9_table_content_matches") is not True
        or any(
            restore_payload.get(field) is not True
            for field in (
                "database_matches",
                "images_match",
                "restore_app_ready",
                "redis_started_empty",
                "refresh_sessions_invalidated",
                "temporary_resources_removed",
                "passed",
            )
        )
        or restored_m7 != m7_snapshot
        or restored_m8_swatch != m8_swatch_snapshot
        or restored_m9 != m9_snapshot
    ):
        raise GateACandidateError("Gate A M9 backup/restore record is invalid")
    return backup_payload, restore_payload, backup_path, restore_path


FINAL_WALLET_RECONCILE_COMMAND = (
    "import asyncio,json; "
    "from app.tasks.wallet_reconcile import run; "
    "value=asyncio.run(run(batch_size=500)); "
    "print(json.dumps({'scanned':value.scanned,'mismatches':value.mismatches,"
    "'violations':value.violations},separators=(',',':')))"
)


def _stop_finalization_writers(
    *,
    gatea: Any,
    upgrade: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    image_id: str,
) -> None:
    """停止全部正式 writer；MySQL/Redis 保持健康以便最终只读复验。"""

    pinned_values = dict(values)
    pinned_values["GATEA_APP_IMAGE"] = image_id
    try:
        gatea._run_compose(
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            arguments=("stop", "--timeout", "30", *M9_WRITER_SERVICES),
        )
        rows = gatea._compose_ps(
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            services=(*M9_RUNTIME_SERVICES, "image-init"),
        )
        gatea._ensure_services_healthy(rows, "mysql", "redis")
        for service in M9_WRITER_SERVICES:
            upgrade._ensure_not_running(rows, service)
    except GateACandidateOperationInterrupted:
        raise
    except Exception as error:
        raise GateACandidateError(
            "Gate A finalization could not establish the write-free window"
        ) from error


def _final_wallet_reconcile(
    *,
    gatea: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> dict[str, int]:
    try:
        result = gatea._run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            arguments=(
                "run",
                "--rm",
                "--no-deps",
                "app",
                "python",
                "-c",
                FINAL_WALLET_RECONCILE_COMMAND,
            ),
            capture_output=True,
        )
        payload = json.loads(result.stdout.strip())
    except Exception as error:
        raise GateACandidateError(
            "Gate A finalization wallet reconciliation failed"
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"scanned", "mismatches", "violations"}
        or any(type(value) is not int or value < 0 for value in payload.values())
        or payload.get("mismatches") != 0
        or payload.get("violations") != 0
    ):
        raise GateACandidateError(
            "Gate A finalization wallet reconciliation is invalid"
        )
    return {str(key): int(value) for key, value in payload.items()}


def _final_live_recheck(
    *,
    gatea: Any,
    backup_module: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    image_id: str,
    backup_record: Mapping[str, Any],
    acceptance_record: Mapping[str, Any],
) -> dict[str, Any]:
    """在 write-free 窗口内重算所有可变数据证据。"""

    pinned_values = dict(values)
    pinned_values["GATEA_APP_IMAGE"] = image_id
    try:
        database_snapshot = backup_module._source_snapshot(
            pinned_values, config_file, secret_dir, "loopback"
        )
        m7_snapshot = backup_module._source_m7_content_snapshot(
            pinned_values, config_file, secret_dir, "loopback"
        )
        m8_swatch_snapshot = (
            backup_module._source_m8_swatch_content_snapshot(
                pinned_values, config_file, secret_dir, "loopback"
            )
        )
        m9_snapshot = backup_module._source_m9_table_content_snapshot(
            pinned_values, config_file, secret_dir, "loopback"
        )
        images = backup_module._source_image_manifest(
            pinned_values, config_file, secret_dir, "loopback"
        )
        table_reconcile = gatea._run_m9_table_reconcile(
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
        )
        wallet_reconcile = _final_wallet_reconcile(
            gatea=gatea,
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
        )
    except GateACandidateError:
        raise
    except Exception as error:
        raise GateACandidateError(
            "Gate A finalization live evidence could not be recomputed"
        ) from error
    if (
        database_snapshot != backup_record.get("database_snapshot")
        or m7_snapshot != backup_record.get("m7_content_snapshot")
        or m8_swatch_snapshot
        != backup_record.get("m8_swatch_content_snapshot")
        or m9_snapshot != backup_record.get("m9_table_content_snapshot")
        or images != backup_record.get("image_manifest")
        or table_reconcile != acceptance_record.get("post_reconcile")
        or wallet_reconcile != acceptance_record.get("post_wallet_reconcile")
        or gatea.validate_app_image(values) != image_id
    ):
        raise GateACandidateError(
            "Gate A live state differs from the post-acceptance backup"
        )
    manifest_bytes = (
        ("\n".join(images) + "\n").encode("utf-8") if images else b""
    )
    return {
        "database_snapshot": database_snapshot,
        "m7_content_snapshot": m7_snapshot,
        "m8_swatch_content_snapshot": m8_swatch_snapshot,
        "m9_table_content_snapshot": m9_snapshot,
        "image_manifest_sha256": _sha256_bytes(manifest_bytes),
        "image_file_count": len(images),
        "table_reconcile": table_reconcile,
        "wallet_reconcile": wallet_reconcile,
        "checked_at": _utc_now(),
    }


def _restore_finalization_runtime(
    *,
    gatea: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    acceptance_record_dir: Path = DEFAULT_ACCEPTANCE_RECORD_DIR,
    candidate_transition_recovery: Any | None = None,
) -> None:
    try:
        app_up_arguments: dict[str, Any] = {
            "config_file": config_file,
            "secret_dir": secret_dir,
            "record_dir": release_record_dir,
            "mode": "loopback",
            "wait_timeout": 120,
            "include_table_sweeper": True,
            # A prior attempt may have restored all five services and then
            # crashed before advancing the finalization journal.  Recovery
            # must validate and reuse that exact loopback publisher instead
            # of treating its occupied port as an unrelated process.
            "allow_existing_gatea_publisher": True,
            "acceptance_record_dir": acceptance_record_dir,
            "_start_new_session": True,
        }
        if candidate_transition_recovery is not None:
            app_up_arguments["candidate_transition_recovery"] = (
                candidate_transition_recovery
            )
        gatea.app_up(
            **app_up_arguments,
        )
        rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            services=M9_RUNTIME_SERVICES,
            start_new_session=True,
        )
        gatea._ensure_services_healthy(rows, *M9_RUNTIME_SERVICES)
        gatea._validate_loopback_publishers(
            rows, int(values.get("GATEA_LOOPBACK_PORT", "18080"))
        )
    except Exception as error:
        raise GateACandidateError(
            "Gate A finalization could not restore the target runtime"
        ) from error


_FinalizationWorkResult = TypeVar("_FinalizationWorkResult")


def _restore_finalization_runtime_with_shield(
    *,
    termination: _MutationTerminationController,
    gatea: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    acceptance_record_dir: Path = DEFAULT_ACCEPTANCE_RECORD_DIR,
    candidate_transition_recovery: Any | None = None,
) -> None:
    """Retry control-flow interruptions until all five services are healthy."""

    termination.begin_recovery()
    while True:
        try:
            _restore_finalization_runtime(
                gatea=gatea,
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                release_record_dir=release_record_dir,
                acceptance_record_dir=acceptance_record_dir,
                candidate_transition_recovery=candidate_transition_recovery,
            )
        except (KeyboardInterrupt, SystemExit) as error:
            termination.remember_recovery_interruption(error)
            continue
        except BaseException as recovery_error:
            raise GateACandidateError(
                "Gate A finalization target runtime recovery failed"
            ) from recovery_error
        return


def _run_finalization_work_then_restore(
    *,
    termination: _MutationTerminationController,
    work: Callable[[], _FinalizationWorkResult],
    gatea: Any,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    acceptance_record_dir: Path = DEFAULT_ACCEPTANCE_RECORD_DIR,
    candidate_transition_recovery: Any | None = None,
) -> tuple[_FinalizationWorkResult | None, BaseException | None]:
    """Run mutable work and always cross into shielded runtime recovery."""

    result: _FinalizationWorkResult | None = None
    work_error: BaseException | None = None
    try:
        try:
            result = work()
        except BaseException as error:
            work_error = error
            termination.begin_recovery()
        else:
            # Switch before leaving the work block. If the first signal lands
            # in this boundary, its handler switches state before raising and
            # the outer finally still performs recovery.
            termination.begin_recovery()
    finally:
        # The signal handler enters recovery before raising.  Normal completion,
        # ordinary exceptions, SIGINT and SystemExit all reach this outer finally;
        # once entered, termination signals are remembered and cannot abort recovery.
        termination.begin_recovery()
        _restore_finalization_runtime_with_shield(
            termination=termination,
            gatea=gatea,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            release_record_dir=release_record_dir,
            acceptance_record_dir=acceptance_record_dir,
            candidate_transition_recovery=candidate_transition_recovery,
        )
    return result, work_error


def _finalization_error_after_recovery(
    *,
    termination: _MutationTerminationController,
    work_error: BaseException | None,
) -> BaseException | None:
    """Preserve the original work failure ahead of a deferred recovery signal."""

    if termination.work_interruption is not None:
        return termination.work_interruption
    if work_error is not None:
        return work_error
    if termination.recovery_interruption is not None:
        return termination.recovery_interruption
    return None


def _validate_final_live_recheck(payload: object) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or set(payload) != FINAL_LIVE_RECHECK_KEYS
        or not isinstance(payload.get("database_snapshot"), dict)
        or not isinstance(payload.get("m7_content_snapshot"), dict)
        or not isinstance(payload.get("m8_swatch_content_snapshot"), dict)
        or not isinstance(payload.get("m9_table_content_snapshot"), dict)
        or SHA256_PATTERN.fullmatch(
            str(payload.get("image_manifest_sha256", ""))
        )
        is None
        or type(payload.get("image_file_count")) is not int
        or payload["image_file_count"] <= 0
        or not isinstance(payload.get("table_reconcile"), dict)
        or not isinstance(payload.get("wallet_reconcile"), dict)
        or not _is_utc_timestamp(payload.get("checked_at"))
    ):
        raise GateACandidateError("Gate A finalization live recheck is invalid")
    return dict(payload)


def _validate_finalization_journal(
    payload: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    expected_live_recheck: Mapping[str, Any],
    final: bool,
    adoption_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    adoption = adoption_binding is not None
    expected_keys = (
        ADOPTION_FINAL_RECORD_KEYS
        if adoption and final
        else ADOPTION_FINAL_PENDING_KEYS
        if adoption
        else FINAL_RECORD_KEYS
        if final
        else FINAL_PENDING_KEYS
    )
    expected_type = (
        "gatea-current-finalization" if final else "gatea-current-finalization-pending"
    )
    adoption_keys = ADOPTION_FINAL_RECORD_KEYS - FINAL_RECORD_KEYS
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != (2 if adoption else 1)
        or payload.get("record_type") != expected_type
        or any(payload.get(key) != value for key, value in expected.items())
        or (
            adoption
            and any(
                payload.get(key) != adoption_binding.get(key)
                for key in adoption_keys
            )
        )
        or payload.get("runtime_services") != list(M9_RUNTIME_SERVICES)
        or payload.get("phase") not in FINAL_PENDING_PHASES
        or not _is_utc_timestamp(payload.get("started_at"))
        or payload.get("secret_values_recorded") is not False
        or (final and payload.get("phase") != "runtime-restored")
        or (final and payload.get("passed") is not True)
        or (final and not _is_utc_timestamp(payload.get("completed_at")))
    ):
        raise GateACandidateError("Gate A finalization journal is invalid")
    live_recheck = payload.get("live_recheck")
    if payload.get("phase") == "prepared":
        if live_recheck is not None:
            raise GateACandidateError("Gate A finalization journal is invalid")
    else:
        validated_live = _validate_final_live_recheck(live_recheck)
        if any(
            validated_live.get(key) != value
            for key, value in expected_live_recheck.items()
        ):
            raise GateACandidateError("Gate A finalization live recheck changed")
    return dict(payload)


def _validated_finalization_recovery_allowance(
    *,
    gatea: Any,
    release_record_dir: Path,
    acceptance_record_dir: Path,
    target_sha: str,
    pending_path: Path,
    expected: Mapping[str, Any],
    expected_live_recheck: Mapping[str, Any],
    adoption_binding: Mapping[str, Any] | None = None,
) -> Any:
    """Construct the operations bypass only after exact local journal validation."""

    expected_path = _final_pending_path(release_record_dir, target_sha)
    if _lexical_absolute_path(pending_path) != _lexical_absolute_path(expected_path):
        raise GateACandidateError(
            "Gate A finalization recovery journal path is invalid"
        )
    _reject_unresolved_transition_journals(
        release_record_dir=release_record_dir,
        acceptance_record_dir=acceptance_record_dir,
        allowed_release_pending=expected_path,
    )
    _validate_finalization_journal(
        _load_json(
            expected_path,
            "Gate A candidate finalization pending journal",
            mode=0o600,
        ),
        expected=expected,
        expected_live_recheck=expected_live_recheck,
        final=False,
        adoption_binding=adoption_binding,
    )
    try:
        return gatea.CandidateTransitionRecoveryAllowance(
            path=expected_path,
            kind="current-finalization",
            candidate_sha=target_sha,
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise GateACandidateError(
            "Gate A operations finalization recovery API is unavailable"
        ) from error


def _finish_finalization_journal(
    *,
    pending: Mapping[str, Any],
    pending_path: Path,
    record_path: Path,
    expected: Mapping[str, Any],
    expected_live_recheck: Mapping[str, Any],
    adoption_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if pending.get("phase") != "runtime-restored":
        raise GateACandidateError(
            "Gate A finalization runtime is not durably restored"
        )
    final_payload = {
        **pending,
        "record_type": "gatea-current-finalization",
        "completed_at": _utc_now(),
        "passed": True,
    }
    _validate_finalization_journal(
        final_payload,
        expected=expected,
        expected_live_recheck=expected_live_recheck,
        final=True,
        adoption_binding=adoption_binding,
    )
    if record_path.exists() or record_path.is_symlink():
        raise GateACandidateError(
            "Gate A finalization record appeared during recovery"
        )
    _write_json_exclusive(record_path, final_payload)
    pending_path.unlink()
    _fsync_directory(record_path.parent)
    return final_payload


@_serialized_operation
def finalize_candidate(
    *,
    source_sha: str,
    target_sha: str,
    runtime_acceptance_record: Path,
    runtime_acceptance_sha256: str,
    resilience_record: Path,
    resilience_sha256: str,
    post_backup_id: str,
    confirm_source_sha: str,
    confirm_target_sha: str,
    confirm_post_backup_id: str,
    config_file: Path,
    secret_dir: Path,
    release_root: Path,
    release_record_dir: Path,
    backup_root: Path,
    backup_record_dir: Path,
    restore_record_dir: Path,
    current_link: Path,
    acceptance_record_dir: Path = DEFAULT_ACCEPTANCE_RECORD_DIR,
    acceptance_failure_archive_dir: Path = DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    resilience_record_dir: Path = DEFAULT_RESILIENCE_RECORD_DIR,
    predecessor_candidate_sha: str | None = None,
    acceptance_retirement_record_sha256: str | None = None,
    confirm_predecessor_sha: str | None = None,
    confirm_acceptance_retirement_record_sha256: str | None = None,
    lock_file: Path | None = DEFAULT_LOCK_FILE,
    _termination_controller: _MutationTerminationController | None = None,
) -> dict[str, Any]:
    """在最终短停写复验后选择候选；pending 支持严格幂等续跑。"""

    _require_root()
    if _termination_controller is None:
        raise GateACandidateError(
            "Gate A finalization termination guard is unavailable"
        )
    termination = _termination_controller
    source_sha = _validate_sha(source_sha, "source SHA")
    target_sha = _validate_sha(target_sha, "target SHA")
    adoption_values = (
        predecessor_candidate_sha,
        acceptance_retirement_record_sha256,
        confirm_predecessor_sha,
        confirm_acceptance_retirement_record_sha256,
    )
    adoption = any(value is not None for value in adoption_values)
    if adoption and any(value is None for value in adoption_values):
        raise GateACandidateError(
            "Gate A adoption finalization arguments must be supplied together"
        )
    if adoption:
        predecessor_candidate_sha = _validate_sha(
            str(predecessor_candidate_sha), "predecessor candidate SHA"
        )
        acceptance_retirement_record_sha256 = _validate_sha256(
            str(acceptance_retirement_record_sha256),
            "acceptance retirement record digest",
        )
    if (
        confirm_source_sha != source_sha
        or confirm_target_sha != target_sha
        or confirm_post_backup_id != post_backup_id
        or BACKUP_ID_PATTERN.fullmatch(post_backup_id) is None
        or (
            adoption
            and (
                predecessor_candidate_sha in {source_sha, target_sha}
                or confirm_predecessor_sha != predecessor_candidate_sha
                or confirm_acceptance_retirement_record_sha256
                != acceptance_retirement_record_sha256
            )
        )
    ):
        raise GateACandidateError("Gate A finalization confirmations do not match")
    _require_root_directory(release_record_dir, 0o755, "Gate A release record directory")
    _reject_unresolved_transition_journals(
        release_record_dir=release_record_dir,
        acceptance_record_dir=acceptance_record_dir,
        allowed_release_pending=_final_pending_path(
            release_record_dir, target_sha
        ),
    )
    if (
        _lexical_absolute_path(runtime_acceptance_record.parent)
        != _lexical_absolute_path(acceptance_record_dir)
    ):
        raise GateACandidateError(
            "Gate A runtime acceptance record must use the guarded directory"
        )
    _require_root_directory(
        resilience_record_dir,
        0o755,
        "Gate A resilience record directory",
    )
    if (
        _lexical_absolute_path(resilience_record.parent)
        != _lexical_absolute_path(resilience_record_dir)
    ):
        raise GateACandidateError(
            "Gate A resilience record must use the guarded directory"
        )
    _require_execution_release(release_root, target_sha)
    stage = _load_stage(
        release_root=release_root,
        release_record_dir=release_record_dir,
        target_sha=target_sha,
    )
    unresolved_predecessors = (
        _stage_pending_path(release_record_dir, target_sha),
        _activation_pending_path(release_record_dir, target_sha),
        _rollback_pending_path(release_record_dir, target_sha),
    )
    if any(path.exists() or path.is_symlink() for path in unresolved_predecessors):
        raise GateACandidateError(
            "Gate A predecessor pending journal must be resolved before finalization"
        )
    image_id = str(stage["image_id"])
    activation_path = _activation_record_path(release_record_dir, target_sha)
    activation = _load_json(activation_path, "Gate A config activation record")
    activation_backup_id = activation.get("backup_id")
    activation_history_path = activation.get("history_path")
    if (
        not isinstance(activation_backup_id, str)
        or BACKUP_ID_PATTERN.fullmatch(activation_backup_id) is None
        or not isinstance(activation_history_path, str)
        or not activation_history_path
    ):
        raise GateACandidateError("Gate A config activation is not finalizable")
    adoption_context: dict[str, Any] | None = None
    if adoption:
        adoption_context = _load_adoption_context(
            release_root=release_root,
            release_record_dir=release_record_dir,
            source_candidate_sha=str(predecessor_candidate_sha),
            lineage_source_candidate_sha=source_sha,
            target_sha=target_sha,
            acceptance_retirement_record_sha256=str(
                acceptance_retirement_record_sha256
            ),
            acceptance_failure_archive_dir=acceptance_failure_archive_dir,
        )
    activation = _validate_activation_journal(
        activation,
        source_sha=(
            str(predecessor_candidate_sha) if adoption else source_sha
        ),
        target_sha=target_sha,
        stage=stage,
        backup_id=activation_backup_id,
        history_path=Path(activation_history_path),
        release_record_dir=release_record_dir,
        final=True,
        adoption_binding=adoption_context,
    )
    if (
        _rollback_record_path(release_record_dir, target_sha).exists()
        or _rollback_record_path(release_record_dir, target_sha).is_symlink()
    ):
        raise GateACandidateError("Gate A config activation is not finalizable")
    _require_root_file(config_file, 0o640, "Gate A config file")
    if _sha256(config_file) != activation.get("target_config_sha256"):
        raise GateACandidateError("Gate A active config no longer matches activation")

    gatea, backup_module, upgrade = _runtime_modules()
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        require_available_port=False,
    )
    if gatea._candidate_sha(values) != target_sha:
        raise GateACandidateError("Gate A active config is not the target candidate")
    if gatea.validate_app_image(values) != image_id:
        raise GateACandidateError("Gate A target image identity changed")
    upgrade_path = release_record_dir / f"{target_sha}.existing-database-upgrade.json"
    upgrade_record = gatea._require_upgrade_record(
        record_dir=release_record_dir,
        candidate_sha=target_sha,
        image_id=image_id,
    )
    if adoption:
        if adoption_context is None:
            raise GateACandidateError(
                "Gate A adoption finalization context is unavailable"
            )
        expected_upgrade_binding = {
            "transition_kind": "m9-candidate-adoption",
            "source_candidate_sha": adoption_context[
                "source_candidate_sha"
            ],
            "source_image_id": adoption_context["source_image_id"],
            "lineage_source_candidate_sha": source_sha,
            "lineage_source_image_id": adoption_context[
                "lineage_source_image_id"
            ],
            "stage_record_sha256": adoption_context[
                "stage_record_sha256"
            ],
            "activation_record_sha256": _sha256(activation_path),
            "predecessor_stage_record_sha256": adoption_context[
                "predecessor_stage_record_sha256"
            ],
            "predecessor_activation_record_sha256": adoption_context[
                "predecessor_activation_record_sha256"
            ],
            "predecessor_upgrade_record_sha256": adoption_context[
                "predecessor_upgrade_record_sha256"
            ],
            "predecessor_upgrade_evidence_sha256": adoption_context[
                "predecessor_upgrade_evidence_sha256"
            ],
            "predecessor_upgrade_plan_replay_record_sha256": (
                adoption_context[
                    "predecessor_upgrade_plan_replay_record_sha256"
                ]
            ),
            "acceptance_retirement_record_sha256": adoption_context[
                "acceptance_retirement_record_sha256"
            ],
        }
        if (
            upgrade_record.get("schema_version") != 2
            or any(
                upgrade_record.get(key) != value
                for key, value in expected_upgrade_binding.items()
            )
            or upgrade_record.get("source_version") != 9
            or upgrade_record.get("target_version") != 9
            or upgrade_record.get("source_aerich_versions")
            != list(gatea.APPROVED_TARGET_M9_CHAIN)
            or upgrade_record.get("target_aerich_versions")
            != list(gatea.APPROVED_TARGET_M9_CHAIN)
            or upgrade_record.get("database_changes_applied") is not False
            or upgrade_record.get("migrations_applied") != []
        ):
            raise GateACandidateError(
                "Gate A target upgrade record is not the approved M9 adoption"
            )
    elif (
        upgrade_record.get("source_candidate_sha") != source_sha
        or upgrade_record.get("source_version") != 7
        or upgrade_record.get("backup_id") != activation.get("backup_id")
        or upgrade_record.get("manifest_sha256") != activation.get("manifest_sha256")
        or upgrade_record.get("target_aerich_versions")
        != list(gatea.APPROVED_TARGET_M9_CHAIN)
    ):
        raise GateACandidateError("Gate A target upgrade record is not M7-to-M9")
    if (
        upgrade_record.get("backup_id") != activation.get("backup_id")
        or upgrade_record.get("manifest_sha256")
        != activation.get("manifest_sha256")
    ):
        raise GateACandidateError(
            "Gate A target upgrade record does not bind config activation"
        )
    evidence_path = release_record_dir / (
        f"{target_sha}.existing-database-upgrade.evidence.json"
    )
    replay_path = _upgrade_replay_record_path(release_record_dir, target_sha)
    replay = _validate_upgrade_replay_record(
        path=replay_path,
        source_sha=(
            str(predecessor_candidate_sha) if adoption else source_sha
        ),
        target_sha=target_sha,
        image_id=image_id,
        upgrade_path=upgrade_path,
        upgrade_record=upgrade_record,
        evidence_path=evidence_path,
        gatea=gatea,
        upgrade=upgrade,
    )
    snapshot = gatea.read_database_snapshot(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
    )
    if snapshot.get("aerich_versions") != list(gatea.APPROVED_TARGET_M9_CHAIN):
        raise GateACandidateError("Gate A finalization requires the exact M9 chain")

    acceptance = _validate_acceptance_record(
        runtime_acceptance_record,
        expected_sha256=runtime_acceptance_sha256,
        source_sha=source_sha,
        target_sha=target_sha,
        image_id=image_id,
        ci_run_id=str(stage["ci_run_id"]),
        upgrade_record_sha256=_sha256(upgrade_path),
        upgrade_replay_record_sha256=_sha256(replay_path),
    )

    def require_acceptance_unchanged() -> None:
        _read_stable_acceptance_record(
            runtime_acceptance_record, runtime_acceptance_sha256
        )

    resilience = _validate_resilience_record(
        resilience_record,
        record_dir=resilience_record_dir,
        expected_sha256=resilience_sha256,
        source_sha=source_sha,
        source_image_id=(
            str(adoption_context["lineage_source_image_id"])
            if adoption_context is not None
            else str(upgrade_record["source_image_id"])
        ),
        target_sha=target_sha,
        image_id=image_id,
        runtime_acceptance_record_sha256=runtime_acceptance_sha256,
        runtime_acceptance_attempt_id_sha256=str(
            acceptance.get("attempt_id_sha256", "")
        ),
        runtime_acceptance_completed_at=str(acceptance.get("completed_at", "")),
    )
    backup_record, restore_record, backup_path, restore_path = _validate_post_backup(
        backup_id=post_backup_id,
        target_sha=target_sha,
        image_id=image_id,
        backup_root=backup_root,
        backup_record_dir=backup_record_dir,
        restore_record_dir=restore_record_dir,
    )
    resilience_content = resilience.get("database_content_snapshots", {})
    if (
        not isinstance(resilience_content, dict)
        or resilience_content.get("m7_preserved_business")
        != backup_record.get("m7_content_snapshot")
        or resilience_content.get("m8_swatch_content")
        != backup_record.get("m8_swatch_content_snapshot")
        or resilience_content.get("m9_table_business")
        != backup_record.get("m9_table_content_snapshot")
        or resilience.get("image_file_count")
        != len(backup_record.get("image_manifest", []))
    ):
        raise GateACandidateError(
            "Gate A resilience and post-backup content evidence differ"
        )
    if post_backup_id == upgrade_record.get("backup_id"):
        raise GateACandidateError("Gate A post-acceptance backup must be fresh")
    if (
        resilience.get("representative_record_sha256")
        != acceptance.get("representative_record_sha256")
    ):
        raise GateACandidateError(
            "Gate A acceptance and resilience source evidence differ"
        )
    if (
        _parse_utc_timestamp(replay.get("completed_at"), "upgrade plan replay")
        > _parse_utc_timestamp(acceptance.get("started_at"), "runtime acceptance")
        or _parse_utc_timestamp(
            acceptance.get("completed_at"), "runtime acceptance"
        )
        > _parse_utc_timestamp(resilience.get("started_at"), "M9 resilience")
        or _parse_utc_timestamp(acceptance.get("completed_at"), "runtime acceptance")
        > _parse_utc_timestamp(backup_record.get("started_at"), "M9 backup")
        or _parse_utc_timestamp(resilience.get("completed_at"), "M9 resilience")
        > _parse_utc_timestamp(backup_record.get("started_at"), "M9 backup")
        or _parse_utc_timestamp(backup_record.get("completed_at"), "M9 backup")
        > _parse_utc_timestamp(restore_record.get("started_at"), "M9 restore")
    ):
        raise GateACandidateError("Gate A finalization evidence order is invalid")

    expected_journal = {
        "source_candidate_sha": (
            str(predecessor_candidate_sha) if adoption else source_sha
        ),
        "candidate_sha": target_sha,
        "image_id": image_id,
        "source_link": str(release_root / source_sha),
        "target_link": str(release_root / target_sha),
        "stage_record_sha256": _sha256(
            _stage_record_path(release_record_dir, target_sha)
        ),
        "activation_record_sha256": _sha256(activation_path),
        "upgrade_record_sha256": _sha256(upgrade_path),
        "upgrade_plan_replay_record_sha256": _sha256(replay_path),
        "runtime_acceptance_record_sha256": runtime_acceptance_sha256,
        "resilience_record_sha256": resilience_sha256,
        "post_backup_id": post_backup_id,
        "post_backup_record_sha256": _sha256(backup_path),
        "post_restore_record_sha256": _sha256(restore_path),
        **(
            {
                key: adoption_context[key]
                for key in (
                    ADOPTION_FINAL_RECORD_KEYS - FINAL_RECORD_KEYS
                )
            }
            if adoption_context is not None
            else {}
        ),
    }
    recorded_images = backup_record.get("image_manifest")
    if not isinstance(recorded_images, list) or any(
        not isinstance(item, str) for item in recorded_images
    ):
        raise GateACandidateError("Gate A post-backup image manifest is invalid")
    recorded_manifest_bytes = (
        ("\n".join(recorded_images) + "\n").encode("utf-8")
        if recorded_images
        else b""
    )
    expected_live_recheck = {
        "database_snapshot": backup_record.get("database_snapshot"),
        "m7_content_snapshot": backup_record.get("m7_content_snapshot"),
        "m8_swatch_content_snapshot": backup_record.get(
            "m8_swatch_content_snapshot"
        ),
        "m9_table_content_snapshot": backup_record.get(
            "m9_table_content_snapshot"
        ),
        "image_manifest_sha256": _sha256_bytes(recorded_manifest_bytes),
        "image_file_count": len(recorded_images),
        "table_reconcile": acceptance.get("post_reconcile"),
        "wallet_reconcile": acceptance.get("post_wallet_reconcile"),
    }
    record_path = _final_record_path(release_record_dir, target_sha)
    pending_path = _final_pending_path(release_record_dir, target_sha)

    with nullcontext() if lock_file is None else _exclusive_lock(lock_file):
        current_target = _read_current_target(current_link, release_root)
        final_payload: dict[str, Any] | None = None
        recovery_allowance: Any | None = None
        if record_path.exists() or record_path.is_symlink():
            final_payload = _validate_finalization_journal(
                _load_json(record_path, "Gate A candidate finalization record"),
                expected=expected_journal,
                expected_live_recheck=expected_live_recheck,
                final=True,
                adoption_binding=adoption_context,
            )
            if current_target != release_root / target_sha:
                raise GateACandidateError(
                    "Gate A finalized current release no longer matches the target"
                )
            if pending_path.exists() or pending_path.is_symlink():
                pending_payload = _validate_finalization_journal(
                    _load_json(
                        pending_path,
                        "Gate A candidate finalization pending journal",
                        mode=0o600,
                    ),
                    expected=expected_journal,
                    expected_live_recheck=expected_live_recheck,
                    final=False,
                    adoption_binding=adoption_context,
                )
                for key in (
                    ADOPTION_FINAL_PENDING_KEYS
                    if adoption
                    else FINAL_PENDING_KEYS
                ) - {"record_type"}:
                    if pending_payload.get(key) != final_payload.get(key):
                        raise GateACandidateError(
                            "Gate A finalization records do not match"
                        )
                require_acceptance_unchanged()
                pending_path.unlink()
                _fsync_directory(release_record_dir)
            rows = gatea._compose_ps(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                mode="loopback",
                services=M9_RUNTIME_SERVICES,
            )
            try:
                gatea._ensure_services_healthy(rows, *M9_RUNTIME_SERVICES)
                gatea._validate_loopback_publishers(
                    rows, int(values.get("GATEA_LOOPBACK_PORT", "18080"))
                )
            except GateACandidateOperationInterrupted:
                raise
            except Exception:

                def repair_final_runtime() -> None:
                    _stop_finalization_writers(
                        gatea=gatea,
                        upgrade=upgrade,
                        values=values,
                        config_file=config_file,
                        secret_dir=secret_dir,
                        image_id=image_id,
                    )

                _, repair_error = _run_finalization_work_then_restore(
                    termination=termination,
                    work=repair_final_runtime,
                    gatea=gatea,
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    release_record_dir=release_record_dir,
                    acceptance_record_dir=acceptance_record_dir,
                )
                if (
                    propagated_error := _finalization_error_after_recovery(
                        termination=termination,
                        work_error=repair_error,
                    )
                ) is not None:
                    raise propagated_error
            require_acceptance_unchanged()
            return final_payload

        if pending_path.exists() or pending_path.is_symlink():
            pending = _validate_finalization_journal(
                _load_json(
                    pending_path,
                    "Gate A candidate finalization pending journal",
                    mode=0o600,
                ),
                expected=expected_journal,
                expected_live_recheck=expected_live_recheck,
                final=False,
                adoption_binding=adoption_context,
            )
            recovery_allowance = _validated_finalization_recovery_allowance(
                gatea=gatea,
                release_record_dir=release_record_dir,
                acceptance_record_dir=acceptance_record_dir,
                target_sha=target_sha,
                pending_path=pending_path,
                expected=expected_journal,
                expected_live_recheck=expected_live_recheck,
                adoption_binding=adoption_context,
            )
            if current_target not in {
                release_root / source_sha,
                release_root / target_sha,
            }:
                raise GateACandidateError(
                    "Gate A current release is incompatible with pending finalization"
                )
            if (
                current_target == release_root / source_sha
                and pending["phase"] in {"current-switched", "runtime-restored"}
            ):
                raise GateACandidateError(
                    "Gate A pending finalization state moved backwards"
                )
            if current_target == release_root / target_sha:
                if pending["phase"] == "prepared":
                    raise GateACandidateError(
                        "Gate A current changed without a durable live recheck"
                    )

                def prepare_pending_target_recovery() -> dict[str, Any]:
                    resumed_pending = dict(pending)
                    if resumed_pending["phase"] == "live-rechecked":
                        resumed_pending = {
                            **resumed_pending,
                            "phase": "current-switched",
                        }
                        require_acceptance_unchanged()
                        _atomic_replace_json(
                            pending_path, resumed_pending, 0o600
                        )
                    return resumed_pending

                # Once the target link is observable after a durable live recheck,
                # that journal is the cutover proof. Runtime writers may already
                # have accepted legitimate work, so recovery must not compare that
                # evolving state with the older post-acceptance backup again.
                recovered_pending, resume_error = (
                    _run_finalization_work_then_restore(
                        termination=termination,
                        work=prepare_pending_target_recovery,
                        gatea=gatea,
                        values=values,
                        config_file=config_file,
                        secret_dir=secret_dir,
                        release_record_dir=release_record_dir,
                        acceptance_record_dir=acceptance_record_dir,
                        candidate_transition_recovery=recovery_allowance,
                    )
                )
                if (
                    resume_error is not None
                    or termination.work_interruption is not None
                ):
                    propagated_error = _finalization_error_after_recovery(
                        termination=termination,
                        work_error=resume_error,
                    )
                    if propagated_error is not None:
                        raise propagated_error
                if recovered_pending is None:
                    raise GateACandidateError(
                        "Gate A pending finalization recovery produced no journal"
                    )
                pending = recovered_pending
                if pending["phase"] != "runtime-restored":
                    pending = {**pending, "phase": "runtime-restored"}
                    require_acceptance_unchanged()
                    _atomic_replace_json(pending_path, pending, 0o600)
                require_acceptance_unchanged()
                final_payload = _finish_finalization_journal(
                    pending=pending,
                    pending_path=pending_path,
                    record_path=record_path,
                    expected=expected_journal,
                    expected_live_recheck=expected_live_recheck,
                    adoption_binding=adoption_context,
                )
                if (
                    propagated_error := _finalization_error_after_recovery(
                        termination=termination,
                        work_error=None,
                    )
                ) is not None:
                    raise propagated_error
                return final_payload
        else:
            if current_target != release_root / source_sha:
                raise GateACandidateError(
                    "Gate A current release no longer matches the source"
                )
            rows = gatea._compose_ps(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                mode="loopback",
                services=M9_RUNTIME_SERVICES,
            )
            gatea._ensure_services_healthy(rows, *M9_RUNTIME_SERVICES)
            gatea._validate_loopback_publishers(
                rows, int(values.get("GATEA_LOOPBACK_PORT", "18080"))
            )
            pending = {
                "schema_version": 2 if adoption else 1,
                "record_type": "gatea-current-finalization-pending",
                **expected_journal,
                "runtime_services": list(M9_RUNTIME_SERVICES),
                "started_at": _utc_now(),
                "phase": "prepared",
                "live_recheck": None,
                "secret_values_recorded": False,
            }
            require_acceptance_unchanged()
            _write_json_exclusive(pending_path, pending, 0o600)
            recovery_allowance = _validated_finalization_recovery_allowance(
                gatea=gatea,
                release_record_dir=release_record_dir,
                acceptance_record_dir=acceptance_record_dir,
                target_sha=target_sha,
                pending_path=pending_path,
                expected=expected_journal,
                expected_live_recheck=expected_live_recheck,
                adoption_binding=adoption_context,
            )

        def perform_final_cutover() -> dict[str, Any]:
            _stop_finalization_writers(
                gatea=gatea,
                upgrade=upgrade,
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                image_id=image_id,
            )
            live_recheck = _final_live_recheck(
                gatea=gatea,
                backup_module=backup_module,
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                image_id=image_id,
                backup_record=backup_record,
                acceptance_record=acceptance,
            )
            live_pending = {
                **pending,
                "phase": "live-rechecked",
                "live_recheck": live_recheck,
            }
            require_acceptance_unchanged()
            _atomic_replace_json(pending_path, live_pending, 0o600)
            if _sha256(config_file) != activation.get("target_config_sha256"):
                raise GateACandidateError(
                    "Gate A config changed during final live recheck"
                )
            if gatea.validate_app_image(values) != image_id:
                raise GateACandidateError(
                    "Gate A target image changed during final live recheck"
                )
            current_target = _read_current_target(current_link, release_root)
            if current_target == release_root / source_sha:
                temporary_link = current_link.parent / (
                    f".{current_link.name}.pending-{os.getpid()}"
                )
                if temporary_link.exists() or temporary_link.is_symlink():
                    raise GateACandidateError(
                        "Gate A temporary current link already exists"
                    )
                try:
                    relative_target = os.path.relpath(
                        release_root / target_sha, current_link.parent
                    )
                    os.symlink(relative_target, temporary_link)
                    os.chown(temporary_link, 0, 0, follow_symlinks=False)
                    _fsync_directory(current_link.parent)
                    require_acceptance_unchanged()
                    os.replace(temporary_link, current_link)
                    _fsync_directory(current_link.parent)
                finally:
                    temporary_link.unlink(missing_ok=True)
            elif current_target != release_root / target_sha:
                raise GateACandidateError(
                    "Gate A current release changed before finalization"
                )
            if (
                _read_current_target(current_link, release_root)
                != release_root / target_sha
            ):
                raise GateACandidateError(
                    "Gate A current release switch did not persist"
                )
            switched_pending = {**live_pending, "phase": "current-switched"}
            require_acceptance_unchanged()
            _atomic_replace_json(pending_path, switched_pending, 0o600)
            return switched_pending

        switched_pending, work_error = _run_finalization_work_then_restore(
            termination=termination,
            work=perform_final_cutover,
            gatea=gatea,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            release_record_dir=release_record_dir,
            acceptance_record_dir=acceptance_record_dir,
            candidate_transition_recovery=recovery_allowance,
        )
        if work_error is not None or termination.work_interruption is not None:
            propagated_error = _finalization_error_after_recovery(
                termination=termination,
                work_error=work_error,
            )
            if propagated_error is not None:
                raise propagated_error
        if switched_pending is None:
            raise GateACandidateError(
                "Gate A finalization cutover produced no journal"
            )
        pending = {**switched_pending, "phase": "runtime-restored"}
        require_acceptance_unchanged()
        _atomic_replace_json(pending_path, pending, 0o600)
        require_acceptance_unchanged()
        final_payload = _finish_finalization_journal(
            pending=pending,
            pending_path=pending_path,
            record_path=record_path,
            expected=expected_journal,
            expected_live_recheck=expected_live_recheck,
            adoption_binding=adoption_context,
        )
        if (
            propagated_error := _finalization_error_after_recovery(
                termination=termination,
                work_error=None,
            )
        ) is not None:
            raise propagated_error
        return final_payload


def _common_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    parser.add_argument(
        "--release-record-dir", type=Path, default=DEFAULT_RELEASE_RECORD_DIR
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage = subparsers.add_parser("stage")
    _common_paths(stage)
    stage.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING_ROOT)
    stage.add_argument("--source-archive", type=Path, required=True)
    stage.add_argument("--confirm-source-archive-sha256", required=True)
    stage.add_argument("--ci-artifact", type=Path, required=True)
    stage.add_argument("--confirm-ci-artifact-sha256", required=True)
    stage.add_argument("--launcher", type=Path, default=Path(__file__).resolve())
    stage.add_argument("--confirm-launcher-sha256", required=True)
    stage.add_argument("--target-sha", required=True)
    stage.add_argument("--source-head-sha", required=True)
    stage.add_argument("--ci-run-id", required=True)
    stage.add_argument("--ci-run-attempt", type=int, required=True)
    stage.add_argument("--ci-artifact-name", required=True)
    stage.add_argument("--confirm-required-jobs", type=int, required=True)
    stage.add_argument("--confirm-target-sha", required=True)
    stage.add_argument("--superseded-candidate-sha")
    stage.add_argument("--confirm-failed-acceptance-sha256")
    stage.add_argument(
        "--acceptance-record-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_RECORD_DIR,
    )
    stage.add_argument("--apply", action="store_true")

    retire = subparsers.add_parser("retire-failed-acceptance")
    _common_paths(retire)
    retire.add_argument("--source-candidate-sha", required=True)
    retire.add_argument("--lineage-source-candidate-sha", required=True)
    retire.add_argument("--target-sha", required=True)
    retire.add_argument("--failed-acceptance-sha256", required=True)
    retire.add_argument("--confirm-source-sha", required=True)
    retire.add_argument("--confirm-lineage-source-sha", required=True)
    retire.add_argument("--confirm-target-sha", required=True)
    retire.add_argument(
        "--confirm-failed-acceptance-sha256", required=True
    )
    retire.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    retire.add_argument("--secret-dir", type=Path, default=DEFAULT_SECRET_DIR)
    retire.add_argument(
        "--acceptance-record-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_RECORD_DIR,
    )
    retire.add_argument(
        "--acceptance-failure-archive-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    )
    retire.add_argument("--current-link", type=Path, default=DEFAULT_CURRENT_LINK)
    retire.add_argument("--apply", action="store_true")

    activate = subparsers.add_parser("activate-config")
    _common_paths(activate)
    activate.add_argument("--source-version", type=int, required=True)
    activate.add_argument("--source-candidate-sha", required=True)
    activate.add_argument("--target-sha", required=True)
    activate.add_argument("--backup-id", required=True)
    activate.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    activate.add_argument(
        "--config-history-dir", type=Path, default=DEFAULT_CONFIG_HISTORY_DIR
    )
    activate.add_argument("--secret-dir", type=Path, default=DEFAULT_SECRET_DIR)
    activate.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    activate.add_argument(
        "--backup-record-dir", type=Path, default=DEFAULT_BACKUP_RECORD_DIR
    )
    activate.add_argument(
        "--restore-record-dir", type=Path, default=DEFAULT_RESTORE_RECORD_DIR
    )
    activate.add_argument("--current-link", type=Path, default=DEFAULT_CURRENT_LINK)
    activate.add_argument("--confirm-source-sha")
    activate.add_argument("--confirm-target-sha")
    activate.add_argument("--confirm-backup-id")
    activate.add_argument("--confirm-manifest-sha256")
    activate.add_argument("--lineage-source-candidate-sha")
    activate.add_argument("--acceptance-retirement-record-sha256")
    activate.add_argument("--confirm-lineage-source-sha")
    activate.add_argument(
        "--confirm-acceptance-retirement-record-sha256"
    )
    activate.add_argument(
        "--acceptance-record-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_RECORD_DIR,
    )
    activate.add_argument(
        "--acceptance-failure-archive-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    )
    activate.add_argument("--apply", action="store_true")

    rollback = subparsers.add_parser("rollback-config")
    _common_paths(rollback)
    rollback.add_argument("--source-sha", required=True)
    rollback.add_argument("--target-sha", required=True)
    rollback.add_argument("--confirm-source-sha", required=True)
    rollback.add_argument("--confirm-target-sha", required=True)
    rollback.add_argument("--confirm-activation-record-sha256", required=True)
    rollback.add_argument("--lineage-source-candidate-sha")
    rollback.add_argument("--acceptance-retirement-record-sha256")
    rollback.add_argument("--confirm-lineage-source-sha")
    rollback.add_argument(
        "--confirm-acceptance-retirement-record-sha256"
    )
    rollback.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    rollback.add_argument(
        "--config-history-dir", type=Path, default=DEFAULT_CONFIG_HISTORY_DIR
    )
    rollback.add_argument("--secret-dir", type=Path, default=DEFAULT_SECRET_DIR)
    rollback.add_argument("--current-link", type=Path, default=DEFAULT_CURRENT_LINK)
    rollback.add_argument(
        "--acceptance-record-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_RECORD_DIR,
    )
    rollback.add_argument(
        "--acceptance-failure-archive-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    )
    rollback.add_argument("--apply", action="store_true")

    finalize = subparsers.add_parser("finalize")
    _common_paths(finalize)
    finalize.add_argument("--source-sha", required=True)
    finalize.add_argument("--target-sha", required=True)
    finalize.add_argument("--runtime-acceptance-record", type=Path, required=True)
    finalize.add_argument("--confirm-runtime-acceptance-sha256", required=True)
    finalize.add_argument(
        "--acceptance-record-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_RECORD_DIR,
    )
    finalize.add_argument("--resilience-record", type=Path, required=True)
    finalize.add_argument("--confirm-resilience-record-sha256", required=True)
    finalize.add_argument(
        "--resilience-record-dir",
        type=Path,
        default=DEFAULT_RESILIENCE_RECORD_DIR,
    )
    finalize.add_argument(
        "--acceptance-failure-archive-dir",
        type=Path,
        default=DEFAULT_ACCEPTANCE_FAILURE_ARCHIVE_DIR,
    )
    finalize.add_argument("--post-backup-id", required=True)
    finalize.add_argument("--confirm-source-sha", required=True)
    finalize.add_argument("--confirm-target-sha", required=True)
    finalize.add_argument("--confirm-post-backup-id", required=True)
    finalize.add_argument("--predecessor-candidate-sha")
    finalize.add_argument("--acceptance-retirement-record-sha256")
    finalize.add_argument("--confirm-predecessor-sha")
    finalize.add_argument(
        "--confirm-acceptance-retirement-record-sha256"
    )
    finalize.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    finalize.add_argument("--secret-dir", type=Path, default=DEFAULT_SECRET_DIR)
    finalize.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    finalize.add_argument(
        "--backup-record-dir", type=Path, default=DEFAULT_BACKUP_RECORD_DIR
    )
    finalize.add_argument(
        "--restore-record-dir", type=Path, default=DEFAULT_RESTORE_RECORD_DIR
    )
    finalize.add_argument("--current-link", type=Path, default=DEFAULT_CURRENT_LINK)
    finalize.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "stage":
            if not args.apply or args.confirm_target_sha != args.target_sha:
                raise GateACandidateError(
                    "Gate A stage requires --apply and an exact target confirmation"
                )
            result = stage_candidate(
                source_archive=args.source_archive,
                source_archive_sha256=args.confirm_source_archive_sha256,
                ci_artifact=args.ci_artifact,
                ci_artifact_sha256=args.confirm_ci_artifact_sha256,
                launcher=args.launcher,
                launcher_sha256=args.confirm_launcher_sha256,
                target_sha=args.target_sha,
                source_head_sha=args.source_head_sha,
                ci_run_id=args.ci_run_id,
                ci_run_attempt=args.ci_run_attempt,
                ci_artifact_name=args.ci_artifact_name,
                confirmed_required_jobs=args.confirm_required_jobs,
                release_root=args.release_root,
                staging_root=args.staging_root,
                release_record_dir=args.release_record_dir,
                superseded_candidate_sha=args.superseded_candidate_sha,
                failed_acceptance_sha256=(
                    args.confirm_failed_acceptance_sha256
                ),
                acceptance_record_dir=args.acceptance_record_dir,
            )
        elif args.command == "retire-failed-acceptance":
            if not args.apply:
                raise GateACandidateError(
                    "Gate A failed acceptance retirement requires --apply"
                )
            result = retire_failed_acceptance(
                source_candidate_sha=args.source_candidate_sha,
                lineage_source_candidate_sha=(
                    args.lineage_source_candidate_sha
                ),
                target_sha=args.target_sha,
                failed_acceptance_sha256=args.failed_acceptance_sha256,
                confirm_source_sha=args.confirm_source_sha,
                confirm_lineage_source_sha=args.confirm_lineage_source_sha,
                confirm_target_sha=args.confirm_target_sha,
                confirm_failed_acceptance_sha256=(
                    args.confirm_failed_acceptance_sha256
                ),
                config_file=args.config_file,
                secret_dir=args.secret_dir,
                release_root=args.release_root,
                release_record_dir=args.release_record_dir,
                acceptance_record_dir=args.acceptance_record_dir,
                acceptance_failure_archive_dir=(
                    args.acceptance_failure_archive_dir
                ),
                current_link=args.current_link,
            )
        elif args.command == "activate-config":
            result = activate_config(
                source_version=args.source_version,
                source_candidate_sha=args.source_candidate_sha,
                target_sha=args.target_sha,
                backup_id=args.backup_id,
                apply=args.apply,
                confirm_source_sha=args.confirm_source_sha,
                confirm_target_sha=args.confirm_target_sha,
                confirm_backup_id=args.confirm_backup_id,
                confirm_manifest_sha256=args.confirm_manifest_sha256,
                config_file=args.config_file,
                config_history_dir=args.config_history_dir,
                secret_dir=args.secret_dir,
                release_root=args.release_root,
                release_record_dir=args.release_record_dir,
                backup_root=args.backup_root,
                backup_record_dir=args.backup_record_dir,
                restore_record_dir=args.restore_record_dir,
                current_link=args.current_link,
                lineage_source_candidate_sha=(
                    args.lineage_source_candidate_sha
                ),
                acceptance_retirement_record_sha256=(
                    args.acceptance_retirement_record_sha256
                ),
                confirm_lineage_source_sha=args.confirm_lineage_source_sha,
                confirm_acceptance_retirement_record_sha256=(
                    args.confirm_acceptance_retirement_record_sha256
                ),
                acceptance_record_dir=args.acceptance_record_dir,
                acceptance_failure_archive_dir=(
                    args.acceptance_failure_archive_dir
                ),
            )
        elif args.command == "rollback-config":
            if not args.apply:
                raise GateACandidateError("Gate A config rollback requires --apply")
            result = rollback_config(
                source_sha=args.source_sha,
                target_sha=args.target_sha,
                confirm_source_sha=args.confirm_source_sha,
                confirm_target_sha=args.confirm_target_sha,
                confirm_activation_record_sha256=(
                    args.confirm_activation_record_sha256
                ),
                config_file=args.config_file,
                config_history_dir=args.config_history_dir,
                secret_dir=args.secret_dir,
                release_root=args.release_root,
                release_record_dir=args.release_record_dir,
                current_link=args.current_link,
                lineage_source_candidate_sha=(
                    args.lineage_source_candidate_sha
                ),
                acceptance_retirement_record_sha256=(
                    args.acceptance_retirement_record_sha256
                ),
                confirm_lineage_source_sha=args.confirm_lineage_source_sha,
                confirm_acceptance_retirement_record_sha256=(
                    args.confirm_acceptance_retirement_record_sha256
                ),
                acceptance_record_dir=args.acceptance_record_dir,
                acceptance_failure_archive_dir=(
                    args.acceptance_failure_archive_dir
                ),
            )
        elif args.command == "finalize":
            if not args.apply:
                raise GateACandidateError("Gate A finalization requires --apply")
            result = finalize_candidate(
                source_sha=args.source_sha,
                target_sha=args.target_sha,
                runtime_acceptance_record=args.runtime_acceptance_record,
                runtime_acceptance_sha256=args.confirm_runtime_acceptance_sha256,
                resilience_record=args.resilience_record,
                resilience_sha256=args.confirm_resilience_record_sha256,
                post_backup_id=args.post_backup_id,
                confirm_source_sha=args.confirm_source_sha,
                confirm_target_sha=args.confirm_target_sha,
                confirm_post_backup_id=args.confirm_post_backup_id,
                config_file=args.config_file,
                secret_dir=args.secret_dir,
                release_root=args.release_root,
                release_record_dir=args.release_record_dir,
                backup_root=args.backup_root,
                backup_record_dir=args.backup_record_dir,
                restore_record_dir=args.restore_record_dir,
                current_link=args.current_link,
                acceptance_record_dir=args.acceptance_record_dir,
                resilience_record_dir=args.resilience_record_dir,
                acceptance_failure_archive_dir=(
                    args.acceptance_failure_archive_dir
                ),
                predecessor_candidate_sha=args.predecessor_candidate_sha,
                acceptance_retirement_record_sha256=(
                    args.acceptance_retirement_record_sha256
                ),
                confirm_predecessor_sha=args.confirm_predecessor_sha,
                confirm_acceptance_retirement_record_sha256=(
                    args.confirm_acceptance_retirement_record_sha256
                ),
            )
        else:  # pragma: no cover - argparse enforces the command choices.
            raise GateACandidateError("Gate A candidate command is invalid")
    except (GateACandidateError, subprocess.SubprocessError) as error:
        print(f"Gate A candidate operation failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(
            "Gate A candidate operation failed: "
            f"error_type={type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
