#!/usr/bin/env python3
"""通过 Gate A loopback API 执行 M9 桌台计时的受控内部验收。

默认模式只执行只读 plan。``--apply-admin-assisted`` 仅在精确 M7→M9 或受控
M9 候选接管、当前 CI Operations、五项健康服务和 root-only M7 合成凭据全部绑定后，才从
``/dev/tty`` 隐藏读取并确认当前 SUPER_ADMIN 身份。业务写入只调用正式 HTTP API；
工具不会写数据库、恢复来源卷、接入真实支付或覆盖既有 Record。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from typing import Any

from scripts.release import gatea_backup as backup
from scripts.release import gatea_m7_representative_data as m7_data
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_representative_data as base_data
from scripts.release import gatea_resilience as resilience
from scripts.release import gatea_upgrade as upgrade


DEFAULT_REPRESENTATIVE_DIR = Path(
    "/srv/pinkdoohub/gatea/records/representative-data"
)
DEFAULT_CREDENTIALS_FILE = (
    DEFAULT_REPRESENTATIVE_DIR / "gatea-m7-synthetic-credentials.json"
)
DEFAULT_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/m9-acceptance")
RECORD_PREFIX = "gatea-m9-runtime-acceptance"
CI_JOB_NAME = "gatea-m7-m8-updater"
M9_SERVICES = ("mysql", "redis", "app", "table-sweeper", "nginx")
EXPECTED_RUNTIME_FEATURE_FLAGS = "true,true,true,false,disabled,false,true"
EXPECTED_WALLET_BALANCE = "160.00"
EXPECTED_POST_PAYMENT_BALANCE = "155.00"
FIXTURE_PRICE = "1.00"
FIXTURE_KIT_STOCK = 10
FIXTURE_ORDER_TOTAL = "5.00"
TABLE_NO = "T01"
TABLE_QR_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9]{32}$")
TABLE_SESSION_NO_PATTERN = re.compile(r"^TS[0-9A-HJKMNP-TV-Z]{26}$")
ATTEMPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SUCCESS_TEMP_NAME_PATTERN = re.compile(r"^[0-9a-f]{32}$")
ROOT_UID = 0
ROOT_GID = 0
MAX_ACCEPTANCE_JSON_BYTES = 1024 * 1024
PENDING_STAGES = (
    "prepared",
    "authentication_started",
    "admin_authenticated",
    "authenticated",
    "fixture_creation_started",
    "experience_created",
    "experience_online",
    "kit_created",
    "kit_online",
    "order_creation_started",
    "order_created",
    "claim_started",
    "claimed",
    "payment_started",
    "paid",
    "release_started",
    "released",
    "fixtures_offline",
    "verified",
)
PENDING_STAGE_RANK = {stage: index for index, stage in enumerate(PENDING_STAGES)}
PENDING_RECORD_KEYS = frozenset(
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
PENDING_CLEANUP_KEYS = frozenset(
    {
        "order_cancelled",
        "fixture_products_offline",
        "synthetic_session_revoked",
        "super_admin_session_revoked",
    }
)
ORDER_EVIDENCE_KEYS = frozenset(
    {
        "order_id",
        "expected_timer_items",
        "kit_order_item_id",
        "eligible_duration_groups",
    }
)
ORDER_TIMER_ITEM_KEYS = frozenset(
    {"order_item_id", "duration_minutes", "quantity"}
)
PAYMENT_EVIDENCE_KEYS = frozenset(
    {"payment_id", "payment_no_sha256", "succeeded_at"}
)
TIMER_EVIDENCE_KEYS = frozenset(
    {
        "durations",
        "buffers",
        "item_counts",
        "quantities",
        "service_offsets",
        "grace_offsets",
        "release_offset",
    }
)
SUCCESS_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "environment",
        "candidate_sha",
        "image_id",
        "operations_sha",
        "ci_run_id",
        "ci_job_name",
        "upgrade_record_sha256",
        "upgrade_plan_replay_record_sha256",
        "representative_record_sha256",
        "credentials_sha256",
        "source_candidate_sha",
        "attempt_id_sha256",
        "started_at",
        "completed_at",
        "fixture",
        "scenario",
        "pre_reconcile",
        "post_reconcile",
        "pre_wallet_reconcile",
        "post_wallet_reconcile",
        "request_count",
        "cleanup",
        "runtime_services",
        "upgrade_plan_replayed",
        "wallet_reconcile_passed",
        "table_reconcile_passed",
        "table_sweep_passed",
        "log_redaction_passed",
        "pii_recorded",
        "secret_values_recorded",
        "table_tokens_recorded",
        "super_admin_credentials_recorded",
        "synthetic_credentials_recorded",
        "token_values_recorded",
        "qr_token_values_recorded",
        "request_or_response_bodies_recorded",
        "raw_dynamic_paths_recorded",
        "loopback_only",
        "source_volume_restored",
        "table_sweep",
        "log_redaction",
        "passed",
    }
)
FIXTURE_RECORD_KEYS = frozenset(
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
SCENARIO_RECORD_KEYS = frozenset(
    {
        "order_id",
        "payment_id",
        "payment_no_sha256",
        "payment_succeeded_at",
        "table_no",
        "session_no_sha256",
        "order_total",
        "experience_item_count",
        "kit_item_count",
        "eligible_duration_groups",
        "claim_statuses",
        "claim_replay_same_session",
        "payment_deadline_offset_seconds",
        "awaiting_timer_count",
        "payment_statuses",
        "payment_replay_same_payment",
        "post_payment_balance",
        "active_timer_durations_minutes",
        "active_timer_buffer_minutes",
        "active_timer_experience_item_counts",
        "active_timer_total_quantities",
        "timer_started_at_matches_payment",
        "timer_service_offsets_seconds",
        "timer_grace_offsets_seconds",
        "table_release_offset_seconds",
        "same_duration_items_merged",
        "different_durations_separated",
        "quantity_did_not_multiply_duration",
        "kit_excluded_from_timers",
        "admin_visible_while_active",
        "release_statuses",
        "release_replay_same_fact",
        "final_session_status",
        "final_close_reason",
        "final_order_status",
        "table_available_after_release",
    }
)
RECONCILE_KEYS = frozenset(
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
WALLET_RECONCILE_KEYS = frozenset({"scanned", "mismatches", "violations"})
TABLE_SWEEP_KEYS = frozenset({"status", "closed"})
LOG_REDACTION_KEYS = frozenset(
    {
        "window",
        "combined_line_count",
        "services_scanned",
        "exact_secret_matches",
        "forbidden_pattern_matches",
        "raw_log_content_recorded",
        "passed",
    }
)
UPGRADE_PLAN_REPLAY_KEYS = frozenset(
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
        "database_snapshot",
        "image_manifest",
        "table_reconcile",
        "upgrade_record_sha256",
        "evidence_sha256",
        "result",
        "completed_at",
        "secret_values_recorded",
    }
)
UPGRADE_PLAN_REPLAY_V2_KEYS = UPGRADE_PLAN_REPLAY_KEYS | frozenset(
    {
        "transition_kind",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "acceptance_retirement_record_sha256",
        "database_changes_applied",
        "migrations_applied",
        "m8_swatch_content_snapshot",
    }
)
CLEANUP_RECORD_KEYS = frozenset(
    {
        "active_session_released",
        "synthetic_session_revoked",
        "synthetic_refresh_rejected",
        "super_admin_session_revoked",
        "super_admin_refresh_rejected",
        "open_sessions_after",
        "occupancies_after",
        "fixture_products_offline",
        "pending_record_retained",
    }
)
FORBIDDEN_RECORD_KEYS = frozenset(
    {
        "username",
        "password",
        "access_token",
        "refresh_token",
        "qr_token",
        "session_no",
        "authorization",
        "idempotency_key",
        "phone",
        "nickname",
        "request_body",
        "response_body",
        "raw_path",
        "attempt_id",
    }
)


class M9AcceptanceError(RuntimeError):
    """不包含身份、凭据、Token、动态路径或响应正文的安全验收错误。"""


class _ConfirmedCredentialRejection(M9AcceptanceError):
    """登录端点明确拒绝凭据，且按冻结契约不会创建 RefreshSession。"""

    def __init__(self, principal: str) -> None:
        self.principal = principal
        super().__init__(f"Gate A M9 {principal} credentials were rejected")


class SecureArgumentParser(argparse.ArgumentParser):
    """参数错误不回显可能由误用者放入命令行的敏感值。"""

    def error(self, message: str) -> None:
        self.exit(2, "Gate A M9 acceptance arguments are invalid\n")


@dataclass(frozen=True, slots=True)
class PreparedContext:
    values: Mapping[str, str]
    config_file: Path
    secret_dir: Path
    release_record_dir: Path
    record_dir: Path
    credentials_file: Path
    representative_record: Path
    candidate_sha: str
    image_id: str
    operations_sha: str
    ci_run_id: str
    source_candidate_sha: str
    source_image_id: str
    upgrade_record_sha256: str
    upgrade_plan_replay_record_sha256: str
    representative_record_sha256: str
    credentials_sha256: str
    pre_reconcile: Mapping[str, int]
    pre_wallet_reconcile: Mapping[str, int]
    started_at: str
    attempt_id: str
    pending: Mapping[str, Any] | None = None
    staged_success: Mapping[str, Any] | None = None

    @property
    def record_path(self) -> Path:
        return self.record_dir / f"{RECORD_PREFIX}-{self.candidate_sha}.json"

    @property
    def pending_path(self) -> Path:
        return self.record_path.with_suffix(".json.pending")

    @property
    def complete_path(self) -> Path:
        return self.record_path.with_suffix(".json.complete")


class SafeLoopbackClient(base_data.LoopbackClient):
    """复用冻结 loopback 客户端，但不保留任何请求路径。"""

    def request(
        self,
        step: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
        expected_status: int = 200,
    ) -> tuple[bytes, Mapping[str, str]]:
        before = len(self.results)
        try:
            return super().request(
                step,
                method,
                path,
                token=token,
                body=body,
                content_type=content_type,
                headers=headers,
                expected_status=expected_status,
            )
        finally:
            for result in self.results[before:]:
                result.pop("path", None)


def _login_with_confirmed_rejection(
    client: SafeLoopbackClient,
    *,
    step: str,
    username: str,
    password: str,
    expected_role: str,
    principal: str,
) -> dict[str, Any]:
    """区分冻结的错误密码响应与结果不明的登录故障。

    登录成功响应意味着 RefreshSession 已经持久化。只有应用冻结的
    HTTP 400/code=1003 错误密码响应能证明请求在会话签发前终止；
    网络错误、非法响应、成功后的角色投影错误等一律保持结果不明，
    并由 journal fail closed。
    """

    result_offset = len(client.results)
    try:
        return base_data._login(
            client,
            step=step,
            username=username,
            password=password,
            expected_role=expected_role,
        )
    except base_data.RepresentativeDataError as error:
        new_results = client.results[result_offset:]
        if len(new_results) == 1:
            result = new_results[0]
            if (
                result.get("step") == step
                and result.get("status") == 400
                and result.get("code") == 1003
                and result.get("passed") is False
            ):
                raise _ConfirmedCredentialRejection(principal) from error
        raise


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _sha256_text(serialized)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """冻结不受读取 atime 影响的文件身份与持久元数据。"""

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


def _validate_record_directory_metadata(
    metadata: os.stat_result,
    label: str,
) -> None:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != ROOT_UID
        or metadata.st_gid != ROOT_GID
        or stat.S_IMODE(metadata.st_mode) != 0o755
    ):
        raise M9AcceptanceError(f"{label} is not a protected root-owned directory")


def _open_protected_record_directory(path: Path, label: str) -> int:
    """以 no-follow fd 冻结受保护目录，避免后续操作跟随路径替换。"""

    descriptor: int | None = None
    try:
        path_metadata = path.lstat()
        _validate_record_directory_metadata(path_metadata, label)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptor_metadata = os.fstat(descriptor)
        final_path_metadata = path.lstat()
        _validate_record_directory_metadata(descriptor_metadata, label)
        _validate_record_directory_metadata(final_path_metadata, label)
        if (
            descriptor_metadata.st_dev != path_metadata.st_dev
            or descriptor_metadata.st_ino != path_metadata.st_ino
            or final_path_metadata.st_dev != path_metadata.st_dev
            or final_path_metadata.st_ino != path_metadata.st_ino
        ):
            raise M9AcceptanceError(f"{label} changed during validation")
    except FileNotFoundError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise M9AcceptanceError(f"{label} is unavailable") from error
    except M9AcceptanceError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise M9AcceptanceError(f"{label} could not be opened safely") from error
    return descriptor


def _validate_record_directory(path: Path, label: str) -> None:
    """拒绝目录软链接，并稳定验证 acceptance 发布目录的 Root 元数据。"""

    descriptor = _open_protected_record_directory(path, label)
    os.close(descriptor)


def _validate_protected_metadata(
    metadata: os.stat_result,
    *,
    modes: frozenset[int],
    link_counts: frozenset[int],
    label: str,
) -> None:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != ROOT_UID
        or metadata.st_gid != ROOT_GID
        or stat.S_IMODE(metadata.st_mode) not in modes
        or metadata.st_nlink not in link_counts
        or metadata.st_size > MAX_ACCEPTANCE_JSON_BYTES
    ):
        raise M9AcceptanceError(f"{label} is not a protected root-owned file")


def _read_protected_json(
    path: Path,
    *,
    modes: frozenset[int],
    link_counts: frozenset[int],
    label: str,
) -> tuple[dict[str, Any], tuple[int, ...]]:
    """从同一 no-follow fd 稳定读取 JSON，并冻结其身份供后续删除。"""

    descriptor: int | None = None
    try:
        path_metadata = path.lstat()
        _validate_protected_metadata(
            path_metadata,
            modes=modes,
            link_counts=link_counts,
            label=label,
        )
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before_metadata = os.fstat(descriptor)
        _validate_protected_metadata(
            before_metadata,
            modes=modes,
            link_counts=link_counts,
            label=label,
        )
        if (
            path_metadata.st_dev != before_metadata.st_dev
            or path_metadata.st_ino != before_metadata.st_ino
        ):
            raise M9AcceptanceError(f"{label} changed during validation")
        chunks: list[bytes] = []
        remaining = MAX_ACCEPTANCE_JSON_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise M9AcceptanceError(f"{label} is unexpectedly large")
        after_metadata = os.fstat(descriptor)
        final_path_metadata = path.lstat()
        if (
            _file_identity(before_metadata) != _file_identity(after_metadata)
            or _file_identity(after_metadata) != _file_identity(final_path_metadata)
        ):
            raise M9AcceptanceError(f"{label} changed during validation")
        raw_payload = b"".join(chunks)
        payload = json.loads(raw_payload)
    except M9AcceptanceError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise M9AcceptanceError(f"{label} could not be read safely") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise M9AcceptanceError(f"{label} is invalid")
    return payload, _file_identity(after_metadata)


def _stable_protected_identity(
    path: Path,
    *,
    modes: frozenset[int],
    link_counts: frozenset[int],
    label: str,
) -> tuple[int, ...]:
    """不解释临时内容，仅确认一个目录项稳定指向受保护普通文件。"""

    descriptor: int | None = None
    try:
        path_metadata = path.lstat()
        _validate_protected_metadata(
            path_metadata,
            modes=modes,
            link_counts=link_counts,
            label=label,
        )
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptor_metadata = os.fstat(descriptor)
        final_path_metadata = path.lstat()
    except M9AcceptanceError:
        raise
    except OSError as error:
        raise M9AcceptanceError(f"{label} could not be inspected safely") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _validate_protected_metadata(
        descriptor_metadata,
        modes=modes,
        link_counts=link_counts,
        label=label,
    )
    if not (
        _file_identity(path_metadata)
        == _file_identity(descriptor_metadata)
        == _file_identity(final_path_metadata)
    ):
        raise M9AcceptanceError(f"{label} changed during validation")
    return _file_identity(descriptor_metadata)


def _unlink_exact_file(
    path: Path,
    expected_identity: tuple[int, ...],
    *,
    label: str,
) -> None:
    """只在已冻结的受保护父目录中删除仍是已验证 inode 的目录项。"""

    directory_descriptor: int | None = None
    try:
        directory_descriptor = _open_protected_record_directory(
            path.parent,
            f"{label} parent directory",
        )
        current = os.stat(
            path.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError as error:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise M9AcceptanceError(f"{label} disappeared before cleanup") from error
    except M9AcceptanceError:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise
    except OSError as error:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        raise M9AcceptanceError(f"{label} could not be inspected safely") from error
    if _file_identity(current) != expected_identity:
        os.close(directory_descriptor)
        raise M9AcceptanceError(f"{label} changed before cleanup")
    try:
        os.unlink(path.name, dir_fd=directory_descriptor)
    except OSError as error:
        os.close(directory_descriptor)
        raise M9AcceptanceError(f"{label} could not be removed safely") from error
    os.close(directory_descriptor)


def _link_exact_file(
    source: Path,
    target: Path,
    expected_identity: tuple[int, ...],
    *,
    label: str,
) -> None:
    """在冻结的受保护目录 fd 内 no-clobber 链接精确的来源 inode。"""

    if source.parent != target.parent:
        raise M9AcceptanceError(f"{label} paths do not share a protected directory")
    directory_descriptor: int | None = None
    try:
        directory_descriptor = _open_protected_record_directory(
            source.parent,
            f"{label} parent directory",
        )
        source_metadata = os.stat(
            source.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if _file_identity(source_metadata) != expected_identity:
            raise M9AcceptanceError(f"{label} source changed before hard-link")
        os.link(
            source.name,
            target.name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        target_metadata = os.stat(
            target.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            target_metadata.st_dev != source_metadata.st_dev
            or target_metadata.st_ino != source_metadata.st_ino
        ):
            raise M9AcceptanceError(f"{label} target identity is invalid")
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _success_temporary_paths(context: PreparedContext) -> tuple[Path, ...]:
    prefix = f".{context.complete_path.name}."
    suffix = ".tmp"
    try:
        entries = tuple(context.record_dir.iterdir())
    except OSError as error:
        raise M9AcceptanceError(
            "Gate A M9 success temporary files could not be inspected"
        ) from error
    return tuple(
        entry
        for entry in entries
        if entry.name.startswith(prefix)
        and entry.name.endswith(suffix)
        and SUCCESS_TEMP_NAME_PATTERN.fullmatch(
            entry.name[len(prefix) : -len(suffix)]
        )
        is not None
    )


def _cleanup_success_temporaries(context: PreparedContext) -> None:
    """清除本候选未发布的随机临时项，包括崩溃留下的 hard-link 别名。"""

    temporary_paths = _success_temporary_paths(context)
    if not temporary_paths:
        return
    identities: list[tuple[Path, tuple[int, ...]]] = []
    for path in temporary_paths:
        identity = _stable_protected_identity(
            path,
            modes=frozenset({0o600, 0o644}),
            link_counts=frozenset({1, 2, 3}),
            label="Gate A M9 success temporary file",
        )
        identities.append((path, identity))
    for path, identity in identities:
        _unlink_exact_file(
            path,
            identity,
            label="Gate A M9 success temporary file",
        )
    _fsync_directory(context.record_dir)


def _run_compose_safely(
    label: str,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """将 Host 进程故障收口为不含命令输出或环境值的验收错误。"""

    try:
        return gatea._run_compose(**kwargs)
    except (OSError, subprocess.SubprocessError) as error:
        raise M9AcceptanceError(
            f"Gate A M9 {label} command failed safely"
        ) from error


def _parse_datetime(value: object, step: str) -> datetime:
    if not isinstance(value, str):
        raise M9AcceptanceError(f"Gate A M9 step {step} returned invalid time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise M9AcceptanceError(
            f"Gate A M9 step {step} returned invalid time"
        ) from error
    if parsed.utcoffset() != timedelta(0):
        raise M9AcceptanceError(f"Gate A M9 step {step} returned non-UTC time")
    return parsed


def _data(document: Mapping[str, Any], step: str) -> dict[str, Any]:
    data = document.get("data")
    if document.get("code") != 0 or not isinstance(data, dict):
        raise M9AcceptanceError(
            f"Gate A M9 step {step} returned an invalid success envelope"
        )
    return data


def _optional_data(document: Mapping[str, Any], step: str) -> dict[str, Any] | None:
    if document.get("code") != 0:
        raise M9AcceptanceError(
            f"Gate A M9 step {step} returned an invalid success envelope"
        )
    data = document.get("data")
    if data is not None and not isinstance(data, dict):
        raise M9AcceptanceError(f"Gate A M9 step {step} returned invalid data")
    return data


def _enum_value(payload: Mapping[str, Any], field: str) -> object:
    value = payload.get(field)
    return value.get("value") if isinstance(value, dict) else value


def _positive_id(payload: Mapping[str, Any], field: str, step: str) -> int:
    value = payload.get(field)
    if type(value) is not int or value <= 0:
        raise M9AcceptanceError(f"Gate A M9 step {step} returned invalid identity")
    return value


def _assert_status(payload: Mapping[str, Any], expected: str, step: str) -> None:
    if _enum_value(payload, "status") != expected:
        raise M9AcceptanceError(f"Gate A M9 step {step} returned invalid status")


def _expected_duration_groups() -> list[dict[str, int]]:
    return [
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


def _operations_evidence(release_record_dir: Path) -> tuple[str, str]:
    operations_sha = gatea.REPOSITORY_ROOT.resolve().name
    if gatea.GIT_SHA_PATTERN.fullmatch(operations_sha) is None:
        raise M9AcceptanceError(
            "Gate A M9 operation must run from a versioned release directory"
        )
    source_record = release_record_dir / f"{operations_sha}.source-sha"
    ci_record = release_record_dir / f"{operations_sha}.ci-run-id"
    try:
        source_sha = source_record.read_text(encoding="utf-8").strip()
        ci_run_id = ci_record.read_text(encoding="utf-8").strip()
    except FileNotFoundError as error:
        raise M9AcceptanceError(
            "Gate A M9 operation CI source evidence is unavailable"
        ) from error
    if (
        source_sha != operations_sha
        or not ci_run_id.isascii()
        or not ci_run_id.isdecimal()
        or int(ci_run_id) <= 0
    ):
        raise M9AcceptanceError(
            "Gate A M9 operation CI source evidence is invalid"
        )
    return operations_sha, ci_run_id


def _path_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as error:
        raise M9AcceptanceError(
            "Gate A M9 acceptance sidecar could not be inspected"
        ) from error
    return True


def _reject_unresolved_release_state(
    *,
    release_record_dir: Path,
    record_dir: Path,
    candidate_sha: str,
) -> None:
    """在读取配置/凭据或调用 API 前阻断所有外部未收口事务。"""

    try:
        gatea.reject_unresolved_candidate_transition_journals(
            record_dir=release_record_dir,
        )
        pending_path = record_dir / f"{RECORD_PREFIX}-{candidate_sha}.json.pending"
        complete_path = record_dir / f"{RECORD_PREFIX}-{candidate_sha}.json.complete"
        pending_exists = _path_entry_exists(pending_path)
        complete_exists = _path_entry_exists(complete_path)
        allowance = (
            gatea.M9AcceptanceSidecarRecoveryAllowance(
                candidate_sha=candidate_sha,
                pending_path=pending_path if pending_exists else None,
                complete_path=complete_path if complete_exists else None,
            )
            if pending_exists or complete_exists
            else None
        )
        gatea.reject_unresolved_m9_acceptance_sidecars(
            record_dir=record_dir,
            recovery_allowance=allowance,
        )
    except gatea.GateAError as error:
        raise M9AcceptanceError(
            "Gate A M9 acceptance is blocked by unresolved release state"
        ) from error


def _require_feature_flags(values: Mapping[str, str]) -> None:
    expected = {
        "WALLET_ADMIN_WRITE_ENABLED": "true",
        "WALLET_ORDER_PAYMENT_ENABLED": "true",
        "WALLET_REFUND_ENABLED": "true",
        "WALLET_TOPUP_ENABLED": "false",
        "PAYMENT_PROVIDER": "disabled",
        "PASSWORD_REGISTRATION_ENABLED": "false",
        "TABLE_SESSION_CLAIMS_ENABLED": "true",
    }
    invalid = [name for name, value in expected.items() if values.get(name) != value]
    if invalid:
        raise M9AcceptanceError(
            "Gate A M9 internal acceptance feature flags are invalid: "
            + ",".join(sorted(invalid))
        )


def _require_runtime_feature_flags(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> None:
    command = (
        "from pathlib import Path; "
        "targets=(b'WALLET_ADMIN_WRITE_ENABLED',"
        "b'WALLET_ORDER_PAYMENT_ENABLED',b'WALLET_REFUND_ENABLED',"
        "b'WALLET_TOPUP_ENABLED',b'PAYMENT_PROVIDER',"
        "b'PASSWORD_REGISTRATION_ENABLED',b'TABLE_SESSION_CLAIMS_ENABLED'); "
        "pairs=(item.partition(b'=') for item in "
        "Path('/proc/1/environ').read_bytes().split(b'\\0') if b'=' in item); "
        "env={key.decode():value.decode() for key,sep,value in pairs "
        "if sep and key in targets}; "
        "print(','.join(("
        "env.get('WALLET_ADMIN_WRITE_ENABLED',''),"
        "env.get('WALLET_ORDER_PAYMENT_ENABLED',''),"
        "env.get('WALLET_REFUND_ENABLED',''),"
        "env.get('WALLET_TOPUP_ENABLED',''),"
        "env.get('PAYMENT_PROVIDER',''),"
        "env.get('PASSWORD_REGISTRATION_ENABLED',''),"
        "env.get('TABLE_SESSION_CLAIMS_ENABLED',''))))"
    )
    result = _run_compose_safely(
        "runtime feature flag",
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("exec", "--no-TTY", "app", "python", "-c", command),
        capture_output=True,
    )
    if result.stdout.strip() != EXPECTED_RUNTIME_FEATURE_FLAGS:
        raise M9AcceptanceError(
            "Gate A M9 running App feature flags do not match the config"
        )


def _validate_root_file(path: Path, mode: int, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise M9AcceptanceError(f"{label} is unavailable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        raise M9AcceptanceError(f"{label} is not a protected root-owned file")


def _load_representative_evidence(
    *,
    representative_record: Path,
    credentials_file: Path,
    source_candidate_sha: str,
    source_image_id: str,
) -> tuple[str, str]:
    try:
        resilience._validate_representative_record_file(representative_record)
        record = resilience._load_representative_record(
            representative_record,
            source_candidate_sha,
            source_image_id,
            require_m7_record=True,
        )
        resilience._validate_m7_credentials_artifact(
            record_path=representative_record,
            payload=record,
        )
    except resilience.ResilienceError as error:
        raise M9AcceptanceError(
            "Gate A M7 representative identity evidence is invalid"
        ) from error
    _validate_root_file(
        credentials_file,
        0o600,
        "Gate A M7 synthetic credentials",
    )
    try:
        credentials = json.loads(credentials_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise M9AcceptanceError(
            "Gate A M7 representative identity evidence is invalid"
        ) from error
    credentials_sha256 = _sha256(credentials_file)
    if (
        Path(str(record.get("credentials_file", ""))).resolve()
        != credentials_file.resolve()
        or record.get("credentials_file_mode") != "0600"
        or record.get("credentials_sha256") != credentials_sha256
        or record.get("synthetic_sessions_revoked") is not True
        or record.get("super_admin_session_revoked") is not True
        or record.get("super_admin_credentials_recorded") is not False
        or record.get("request_or_response_bodies_recorded") is not False
        or record.get("passed") is not True
    ):
        raise M9AcceptanceError(
            "Gate A M7 representative record does not match the upgrade source"
        )
    expected_accounts = {
        str(item["purpose"]): str(item["username"])
        for item in m7_data.SYNTHETIC_ACCOUNTS
    }
    accounts = credentials.get("accounts") if isinstance(credentials, dict) else None
    if (
        not isinstance(credentials, dict)
        or set(credentials) != {
            "schema_version",
            "environment",
            "candidate_sha",
            "created_at",
            "accounts",
        }
        or credentials.get("schema_version") != 1
        or credentials.get("environment") != "gatea"
        or credentials.get("candidate_sha") != source_candidate_sha
        or not isinstance(accounts, list)
        or len(accounts) != len(expected_accounts)
    ):
        raise M9AcceptanceError("Gate A M7 synthetic credentials are invalid")
    observed: dict[str, str] = {}
    for account in accounts:
        if not isinstance(account, dict) or set(account) != {
            "purpose",
            "username",
            "password",
        }:
            raise M9AcceptanceError("Gate A M7 synthetic credentials are invalid")
        purpose = account.get("purpose")
        username = account.get("username")
        password = account.get("password")
        if (
            not isinstance(purpose, str)
            or not isinstance(username, str)
            or not isinstance(password, str)
            or expected_accounts.get(purpose) != username
            or not 8 <= len(password) <= 64
            or purpose in observed
        ):
            raise M9AcceptanceError("Gate A M7 synthetic credentials are invalid")
        observed[purpose] = username
    if observed != expected_accounts:
        raise M9AcceptanceError("Gate A M7 synthetic credentials are incomplete")
    return _sha256(representative_record), credentials_sha256


def _load_upgrade_plan_replay(
    *,
    path: Path,
    upgrade_record_path: Path,
    upgrade_record: Mapping[str, Any],
    candidate_sha: str,
    image_id: str,
) -> str:
    """验证停写窗口中生成、并在 app-up 前冻结的 M9 plan replay sidecar。"""

    evidence_path = upgrade_record_path.with_name(
        f"{candidate_sha}.existing-database-upgrade.evidence.json"
    )
    is_adoption = resilience._is_m9_candidate_adoption(upgrade_record)
    if is_adoption:
        try:
            payload, replay_record_sha256 = (
                gatea._load_schema2_record_with_sha256(
                    path,
                    "M9 upgrade plan replay record",
                )
            )
            stable_upgrade_record, upgrade_record_sha256 = (
                gatea._load_schema2_record_with_sha256(
                    upgrade_record_path,
                    "M9 adoption upgrade record",
                )
            )
            _, evidence_record_sha256 = gatea._load_schema2_record_with_sha256(
                evidence_path,
                "M9 adoption upgrade evidence",
            )
        except gatea.GateAError as error:
            raise M9AcceptanceError(
                "Gate A M9 upgrade plan replay record is invalid"
            ) from error
        if stable_upgrade_record != upgrade_record:
            raise M9AcceptanceError(
                "Gate A M9 upgrade record changed during replay validation"
            )
    else:
        _validate_root_file(path, 0o644, "Gate A M9 upgrade plan replay record")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise M9AcceptanceError(
                "Gate A M9 upgrade plan replay record is invalid"
            ) from error
        _validate_root_file(
            upgrade_record_path,
            0o644,
            "Gate A M9 upgrade record",
        )
        _validate_root_file(
            evidence_path,
            0o644,
            "Gate A M9 upgrade evidence",
        )
        replay_record_sha256 = _sha256(path)
        upgrade_record_sha256 = _sha256(upgrade_record_path)
        evidence_record_sha256 = _sha256(evidence_path)
    result = payload.get("result") if isinstance(payload, dict) else None
    expected_source = str(upgrade_record.get("source_candidate_sha", ""))
    expected_schema = 2 if is_adoption else 1
    expected_source_version = 9 if is_adoption else 7
    expected_source_chain = (
        list(gatea.APPROVED_TARGET_M9_CHAIN)
        if is_adoption
        else list(gatea.APPROVED_TARGET_M7_CHAIN)
    )
    expected_payload_keys = (
        UPGRADE_PLAN_REPLAY_V2_KEYS if is_adoption else UPGRADE_PLAN_REPLAY_KEYS
    )
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
    if is_adoption:
        expected_result_keys |= {
            "transition_kind",
            "database_changes_applied",
            "migrations_applied",
        }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected_payload_keys
        or payload.get("schema_version") != expected_schema
        or payload.get("record_type") != "gatea-m9-upgrade-plan-replay"
        or payload.get("passed") is not True
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("source_candidate_sha") != expected_source
        or payload.get("source_version") != expected_source_version
        or payload.get("image_id") != image_id
        or payload.get("backup_id") != upgrade_record.get("backup_id")
        or payload.get("manifest_sha256") != upgrade_record.get("manifest_sha256")
        or payload.get("database_snapshot")
        != upgrade_record.get("final_database_snapshot")
        or payload.get("image_manifest") != upgrade_record.get("final_image_manifest")
        or payload.get("table_reconcile") != upgrade_record.get("table_reconcile")
        or payload.get("upgrade_record_sha256") != upgrade_record_sha256
        or payload.get("evidence_sha256") != upgrade_record.get("evidence_sha256")
        or payload.get("secret_values_recorded") is not False
        or not isinstance(payload.get("completed_at"), str)
        or not isinstance(result, dict)
        or set(result) != expected_result_keys
        or result.get("already_current") is not True
        or result.get("mode") != "plan-replay"
        or result.get("backup_id") != upgrade_record.get("backup_id")
        or result.get("candidate_sha") != candidate_sha
        or result.get("manifest_sha256") != upgrade_record.get("manifest_sha256")
        or result.get("source_version") != expected_source_version
        or result.get("source_aerich_versions")
        != expected_source_chain
        or result.get("target_version") != 9
        or result.get("target_aerich_versions")
        != list(gatea.APPROVED_TARGET_M9_CHAIN)
        or (
            is_adoption
            and (
                payload.get("transition_kind") != "m9-candidate-adoption"
                or payload.get("lineage_source_candidate_sha")
                != upgrade_record.get("lineage_source_candidate_sha")
                or payload.get("lineage_source_image_id")
                != upgrade_record.get("lineage_source_image_id")
                or payload.get("acceptance_retirement_record_sha256")
                != upgrade_record.get("acceptance_retirement_record_sha256")
                or payload.get("database_changes_applied") is not False
                or payload.get("migrations_applied") != []
                or payload.get("m8_swatch_content_snapshot")
                != upgrade_record.get("final_m8_swatch_content_snapshot")
                or result.get("transition_kind") != "m9-candidate-adoption"
                or result.get("database_changes_applied") is not False
                or result.get("migrations_applied") != []
            )
        )
    ):
        raise M9AcceptanceError(
            "Gate A M9 upgrade plan replay record does not match the live candidate"
        )
    try:
        _parse_datetime(payload["completed_at"], "upgrade-plan-replay")
        if is_adoption:
            backup._validate_m8_swatch_content_snapshot(
                payload["m8_swatch_content_snapshot"]
            )
            upgrade._validate_adoption_table_reconcile_result(
                payload["table_reconcile"]
            )
        else:
            upgrade._validate_empty_table_reconcile_result(
                payload["table_reconcile"]
            )
    except (gatea.GateAError, upgrade.GateAUpgradeError, KeyError) as error:
        raise M9AcceptanceError(
            "Gate A M9 upgrade plan replay consistency evidence is invalid"
        ) from error
    if evidence_record_sha256 != payload["evidence_sha256"]:
        raise M9AcceptanceError(
            "Gate A M9 upgrade plan replay evidence digest does not match"
        )
    return replay_record_sha256


def _read_synthetic_user(context: PreparedContext) -> tuple[str, str]:
    """重新验证并只返回 orders-and-wallet 凭据；调用方必须及时清空引用。"""

    _load_representative_evidence(
        representative_record=context.representative_record,
        credentials_file=context.credentials_file,
        source_candidate_sha=context.source_candidate_sha,
        source_image_id=context.source_image_id,
    )
    try:
        payload = json.loads(context.credentials_file.read_text(encoding="utf-8"))
        accounts = payload["accounts"]
        selected = next(
            item for item in accounts if item.get("purpose") == "orders-and-wallet"
        )
        return str(selected["username"]), str(selected["password"])
    except (KeyError, StopIteration, TypeError, json.JSONDecodeError) as error:
        raise M9AcceptanceError(
            "Gate A M7 orders-and-wallet credentials are unavailable"
        ) from error


def _parse_task_json(output: str, label: str) -> dict[str, int]:
    try:
        payload = json.loads(output.strip())
    except json.JSONDecodeError as error:
        raise M9AcceptanceError(f"Gate A M9 {label} output is invalid") from error
    if not isinstance(payload, dict) or any(
        type(value) is not int for value in payload.values()
    ):
        raise M9AcceptanceError(f"Gate A M9 {label} output is invalid")
    return {str(key): int(value) for key, value in payload.items()}


def _run_table_reconcile(context: PreparedContext) -> dict[str, int]:
    result = _run_compose_safely(
        "table reconcile",
        values=context.values,
        config_file=context.config_file,
        secret_dir=context.secret_dir,
        mode="loopback",
        arguments=(
            "run",
            "--rm",
            "--no-deps",
            "app",
            "python",
            "-m",
            "app.tasks.table_reconcile",
        ),
        capture_output=True,
    )
    payload = _parse_task_json(result.stdout, "table reconcile")
    if set(payload) != RECONCILE_KEYS or payload.get("violations") != 0:
        raise M9AcceptanceError("Gate A M9 table reconciliation failed")
    return payload


WALLET_RECONCILE_COMMAND = (
    "import asyncio,json; "
    "from app.tasks.wallet_reconcile import run; "
    "value=asyncio.run(run(batch_size=500)); "
    "print(json.dumps({'scanned':value.scanned,'mismatches':value.mismatches,"
    "'violations':value.violations},separators=(',',':')))"
)


def _run_wallet_reconcile(context: PreparedContext) -> dict[str, int]:
    result = _run_compose_safely(
        "wallet reconcile",
        values=context.values,
        config_file=context.config_file,
        secret_dir=context.secret_dir,
        mode="loopback",
        arguments=(
            "run",
            "--rm",
            "--no-deps",
            "app",
            "python",
            "-c",
            WALLET_RECONCILE_COMMAND,
        ),
        capture_output=True,
    )
    payload = _parse_task_json(result.stdout, "wallet reconcile")
    if (
        set(payload) != WALLET_RECONCILE_KEYS
        or payload.get("mismatches") != 0
        or payload.get("violations") != 0
    ):
        raise M9AcceptanceError("Gate A M9 wallet reconciliation failed")
    return payload


def _run_table_sweep(context: PreparedContext) -> dict[str, Any]:
    result = _run_compose_safely(
        "table sweep",
        values=context.values,
        config_file=context.config_file,
        secret_dir=context.secret_dir,
        mode="loopback",
        arguments=(
            "run",
            "--rm",
            "--no-deps",
            "app",
            "python",
            "-m",
            "app.tasks.table_sweep",
        ),
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as error:
        raise M9AcceptanceError("Gate A M9 table sweep output is invalid") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != TABLE_SWEEP_KEYS
        or payload.get("status") != "ok"
        or type(payload.get("closed")) is not int
        or payload["closed"] != 0
    ):
        raise M9AcceptanceError("Gate A M9 table sweep did not remain a no-op")
    return payload


def _verify_log_redaction(
    context: PreparedContext,
    *,
    transient_secrets: Sequence[str],
) -> dict[str, Any]:
    """扫描五服务日志；只返回计数，绝不返回原文或命中值。"""

    logs = resilience._compose_logs(
        values=context.values,
        config_file=context.config_file,
        secret_dir=context.secret_dir,
        services=M9_SERVICES,
    )
    deployment_secrets: list[str] = []
    try:
        for secret_name in gatea.EXPECTED_SECRET_FILES:
            value = (context.secret_dir / secret_name).read_text(
                encoding="utf-8"
            ).strip()
            if len(value) < 12:
                raise M9AcceptanceError(
                    "Gate A M9 deployment Secret does not meet the scan floor"
                )
            deployment_secrets.append(value)
    except (OSError, UnicodeError) as error:
        raise M9AcceptanceError(
            "Gate A M9 deployment Secrets could not be scanned"
        ) from error
    exact_values = [
        value
        for value in (*deployment_secrets, *transient_secrets)
        if isinstance(value, str) and len(value) >= 6
    ]
    if not logs.strip():
        raise M9AcceptanceError("Gate A M9 logs are empty after runtime acceptance")
    if any(value in logs for value in exact_values):
        raise M9AcceptanceError("Gate A M9 logs contain an exact sensitive value")
    if any(pattern.search(logs) for pattern in resilience.FORBIDDEN_LOG_PATTERNS):
        raise M9AcceptanceError("Gate A M9 logs contain a sensitive pattern")
    return {
        "window": "24h",
        "combined_line_count": len(logs.splitlines()),
        "services_scanned": list(M9_SERVICES),
        "exact_secret_matches": 0,
        "forbidden_pattern_matches": 0,
        "raw_log_content_recorded": False,
        "passed": True,
    }


def _ensure_m9_services(context: PreparedContext) -> None:
    rows = gatea._compose_ps(
        values=context.values,
        config_file=context.config_file,
        secret_dir=context.secret_dir,
        mode="loopback",
        services=M9_SERVICES,
    )
    gatea._ensure_services_healthy(rows, *M9_SERVICES)
    gatea._validate_loopback_publishers(
        rows,
        int(context.values.get("GATEA_LOOPBACK_PORT", "18080")),
    )


def _validate_resume_runtime_snapshot(snapshot: Mapping[str, Any]) -> None:
    """续跑允许一条验收历史，但桌台 bootstrap 结构仍必须精确。"""

    for key, expected in upgrade.M9_EMPTY_TABLE_INVARIANTS[:8]:
        actual = snapshot.get(key)
        if type(actual) is not int or actual != expected:
            raise M9AcceptanceError(
                f"Gate A M9 resume invariant failed: {key}"
            )
    session_count = snapshot.get("table_sessions")
    timer_count = snapshot.get("table_session_timers")
    occupancy_count = snapshot.get("table_occupancies")
    if (
        type(session_count) is not int
        or session_count not in {0, 1}
        or type(timer_count) is not int
        or timer_count not in {0, 2}
        or type(occupancy_count) is not int
        or occupancy_count not in {0, 1}
        or timer_count == 2
        and session_count != 1
        or occupancy_count == 1
        and session_count != 1
    ):
        raise M9AcceptanceError(
            "Gate A M9 pending journal does not bound the live table history"
        )


def _validate_resume_reconcile(
    pending: Mapping[str, Any],
    reconcile: Mapping[str, int],
) -> None:
    if (
        set(reconcile) != RECONCILE_KEYS
        or any(type(value) is not int or value < 0 for value in reconcile.values())
        or reconcile.get("violations") != 0
        or reconcile.get("closed_with_occupancy") != 0
        or reconcile.get("awaiting_with_timers") != 0
        or reconcile.get("active_without_timers") != 0
        or reconcile.get("scanned") not in {0, 1}
        or reconcile.get("open_sessions") not in {0, 1}
        or reconcile.get("occupancies") != reconcile.get("open_sessions")
    ):
        raise M9AcceptanceError(
            "Gate A M9 pending journal does not match live reconciliation"
        )
    has_bound_session = pending.get("session_no_sha256") is not None
    has_bound_order = pending.get("order_id") is not None
    if (
        (has_bound_session and reconcile["scanned"] != 1)
        or (not has_bound_order and reconcile["scanned"] != 0)
        or (pending.get("session_released") is True and reconcile["open_sessions"] != 0)
    ):
        raise M9AcceptanceError(
            "Gate A M9 pending journal does not match live reconciliation"
        )


def prepare(
    *,
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    record_dir: Path,
    credentials_file: Path,
    representative_record: Path | None = None,
    upgrade_plan_replay_record: Path | None = None,
) -> PreparedContext:
    """在 TTY 凭据读取和任何业务写入前完成全部只读绑定。"""

    if os.geteuid() != 0:
        raise M9AcceptanceError("Gate A M9 acceptance must run as root")
    operation_candidate_sha = gatea.REPOSITORY_ROOT.resolve().name
    if gatea.GIT_SHA_PATTERN.fullmatch(operation_candidate_sha) is None:
        raise M9AcceptanceError(
            "Gate A M9 operation must run from a versioned release directory"
        )
    _reject_unresolved_release_state(
        release_record_dir=release_record_dir,
        record_dir=record_dir,
        candidate_sha=operation_candidate_sha,
    )
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        require_available_port=False,
    )
    _require_feature_flags(values)
    _validate_record_directory(
        record_dir,
        "Gate A M9 acceptance record directory",
    )
    _validate_record_directory(
        release_record_dir,
        "Gate A release record directory",
    )
    image_id = gatea.validate_app_image(values)
    candidate_sha = gatea._candidate_sha(values)
    operations_sha, ci_run_id = _operations_evidence(release_record_dir)
    if candidate_sha != operation_candidate_sha or operations_sha != candidate_sha:
        raise M9AcceptanceError(
            "Gate A M9 Operations candidate does not match the runtime"
        )
    upgrade_record = gatea._require_upgrade_record(
        record_dir=release_record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    is_m7_upgrade = bool(
        upgrade_record.get("schema_version") == 1
        and upgrade_record.get("source_version") == 7
        and upgrade_record.get("source_aerich_versions")
        == list(gatea.APPROVED_TARGET_M7_CHAIN)
        and upgrade_record.get("target_aerich_versions")
        == list(gatea.APPROVED_TARGET_M9_CHAIN)
    )
    is_m9_adoption = resilience._is_m9_candidate_adoption(upgrade_record)
    if not (is_m7_upgrade or is_m9_adoption):
        raise M9AcceptanceError(
            "Gate A M9 acceptance requires an approved deployment record"
        )
    upgrade_record_path = (
        release_record_dir / f"{candidate_sha}.existing-database-upgrade.json"
    )
    selected_plan_replay = upgrade_plan_replay_record or (
        release_record_dir / f"{candidate_sha}.upgrade-plan-replay.json"
    )
    upgrade_plan_replay_record_sha256 = _load_upgrade_plan_replay(
        path=selected_plan_replay,
        upgrade_record_path=upgrade_record_path,
        upgrade_record=upgrade_record,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    source_candidate_sha = str(
        upgrade_record[
            "lineage_source_candidate_sha"
            if is_m9_adoption
            else "source_candidate_sha"
        ]
    )
    source_image_id = str(
        upgrade_record[
            "lineage_source_image_id"
            if is_m9_adoption
            else "source_image_id"
        ]
    )
    selected_record = representative_record or (
        DEFAULT_REPRESENTATIVE_DIR
        / f"gatea-m7-representative-data-{source_candidate_sha}.json"
    )
    representative_sha256, credentials_sha256 = _load_representative_evidence(
        representative_record=selected_record,
        credentials_file=credentials_file,
        source_candidate_sha=source_candidate_sha,
        source_image_id=source_image_id,
    )
    context = PreparedContext(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        release_record_dir=release_record_dir,
        record_dir=record_dir,
        credentials_file=credentials_file,
        representative_record=selected_record,
        candidate_sha=candidate_sha,
        image_id=image_id,
        operations_sha=operations_sha,
        ci_run_id=ci_run_id,
        source_candidate_sha=source_candidate_sha,
        source_image_id=source_image_id,
        upgrade_record_sha256=_sha256(upgrade_record_path),
        upgrade_plan_replay_record_sha256=upgrade_plan_replay_record_sha256,
        representative_record_sha256=representative_sha256,
        credentials_sha256=credentials_sha256,
        pre_reconcile={},
        pre_wallet_reconcile={},
        started_at=_utc_now(),
        attempt_id=secrets.token_hex(16),
    )
    if context.pending_path.exists() or context.pending_path.is_symlink():
        pending, _ = _read_protected_json(
            context.pending_path,
            modes=frozenset({0o600}),
            link_counts=frozenset({1}),
            label="Gate A M9 pending acceptance journal",
        )
        pending_pre_reconcile = pending.get("pre_reconcile")
        pending_pre_wallet = pending.get("pre_wallet_reconcile")
        if (
            not isinstance(pending.get("started_at"), str)
            or not isinstance(pending.get("attempt_id"), str)
            or not isinstance(pending_pre_reconcile, dict)
            or not isinstance(pending_pre_wallet, dict)
        ):
            raise M9AcceptanceError("Gate A M9 pending journal is invalid")
        context = replace(
            context,
            started_at=str(pending["started_at"]),
            attempt_id=str(pending["attempt_id"]),
            pre_reconcile=dict(pending_pre_reconcile),
            pre_wallet_reconcile=dict(pending_pre_wallet),
        )
        pending = _validate_pending_payload(context, pending)
        context = replace(context, pending=pending)
    final_exists = context.record_path.exists() or context.record_path.is_symlink()
    complete_exists = (
        context.complete_path.exists() or context.complete_path.is_symlink()
    )
    if (
        context.pending is not None
        and context.pending.get("stage") == "verified"
        and not complete_exists
        and not final_exists
    ):
        raise M9AcceptanceError(
            "Gate A M9 verified pending journal has no staged success record"
        )
    if complete_exists and context.pending is None and not final_exists:
        raise M9AcceptanceError(
            "Gate A M9 staged success has no pending journal"
        )
    staged_success: dict[str, Any] | None = None
    if complete_exists or final_exists:
        expected_links = (
            frozenset({2, 3}) if complete_exists and final_exists else frozenset({1, 2})
        )
        complete_payload: dict[str, Any] | None = None
        complete_identity: tuple[int, ...] | None = None
        final_payload: dict[str, Any] | None = None
        final_identity: tuple[int, ...] | None = None
        if complete_exists:
            complete_payload, complete_identity = _read_protected_json(
                context.complete_path,
                modes=frozenset({0o600, 0o644}),
                link_counts=expected_links,
                label="Gate A M9 staged acceptance success",
            )
        if final_exists:
            final_payload, final_identity = _read_protected_json(
                context.record_path,
                modes=frozenset({0o600, 0o644}),
                link_counts=expected_links,
                label="Gate A M9 acceptance success",
            )
        staged_success = complete_payload or final_payload
        if staged_success is None:
            raise M9AcceptanceError("Gate A M9 staged success record is invalid")
        if final_exists and complete_exists and (
            complete_payload != final_payload
            or complete_identity is None
            or final_identity is None
            or complete_identity[:2] != final_identity[:2]
        ):
            raise M9AcceptanceError("Gate A M9 staged success links are inconsistent")
        if final_exists and not complete_exists and (
            final_identity is None
            or stat.S_IMODE(final_identity[2]) != 0o644
        ):
            raise M9AcceptanceError(
                "Gate A M9 incomplete success publication cannot be recovered"
            )
        if context.pending is None:
            success_pre_reconcile = staged_success.get("pre_reconcile")
            success_pre_wallet = staged_success.get("pre_wallet_reconcile")
            if not isinstance(success_pre_reconcile, dict) or not isinstance(
                success_pre_wallet, dict
            ):
                raise M9AcceptanceError(
                    "Gate A M9 staged success record binding is invalid"
                )
            context = replace(
                context,
                pre_reconcile=dict(success_pre_reconcile),
                pre_wallet_reconcile=dict(success_pre_wallet),
            )
        context = replace(context, staged_success=staged_success)
        _validate_success_binding(
            context,
            staged_success,
            allow_preverified_complete=complete_exists and not final_exists,
        )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=M9_SERVICES,
    )
    gatea._ensure_services_healthy(rows, *M9_SERVICES)
    gatea._validate_loopback_publishers(
        rows,
        int(values.get("GATEA_LOOPBACK_PORT", "18080")),
    )
    _require_runtime_feature_flags(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
    )
    snapshot = upgrade._read_final_snapshot(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
    )
    if snapshot.get("aerich_versions") != list(gatea.APPROVED_TARGET_M9_CHAIN):
        raise M9AcceptanceError("Gate A M9 runtime is not exact M0 to M9")
    current_reconcile = _run_table_reconcile(context)
    current_wallet_reconcile = _run_wallet_reconcile(context)
    if context.pending is None and context.staged_success is None:
        try:
            upgrade._validate_empty_m9_table_snapshot(snapshot)
        except upgrade.GateAUpgradeError as error:
            raise M9AcceptanceError(
                "Gate A M9 acceptance requires the fresh 30-table empty baseline"
            ) from error
        if any(current_reconcile.values()):
            raise M9AcceptanceError(
                "Gate A M9 acceptance requires no prior table session history"
            )
        return replace(
            context,
            pre_reconcile=current_reconcile,
            pre_wallet_reconcile=current_wallet_reconcile,
        )
    _validate_resume_runtime_snapshot(snapshot)
    if context.staged_success is not None:
        if (
            current_reconcile != context.staged_success.get("post_reconcile")
            or current_wallet_reconcile
            != context.staged_success.get("post_wallet_reconcile")
        ):
            raise M9AcceptanceError(
                "Gate A M9 staged success no longer matches live reconciliation"
            )
        return context
    if context.pending is None:
        raise M9AcceptanceError("Gate A M9 recovery state is invalid")
    _validate_resume_reconcile(context.pending, current_reconcile)
    if (
        current_wallet_reconcile.get("scanned")
        != context.pre_wallet_reconcile.get("scanned")
        or current_wallet_reconcile.get("mismatches") != 0
        or current_wallet_reconcile.get("violations") != 0
    ):
        raise M9AcceptanceError(
            "Gate A M9 pending journal does not match wallet reconciliation"
        )
    return context


TABLE_SECRET_COMMAND = (
    "import asyncio,json\n"
    "from tortoise import Tortoise\n"
    "from app.db.database import TORTOISE_ORM\n"
    "from app.models.table_session import StoreTable\n"
    "async def read():\n"
    " await Tortoise.init(config=TORTOISE_ORM)\n"
    " try:\n"
    f"  row=await StoreTable.get(table_no='{TABLE_NO}')\n"
    "  print(json.dumps({'table_no':row.table_no,'qr_token':row.qr_token},"
    "separators=(',',':')))\n"
    " finally:\n"
    "  await Tortoise.close_connections()\n"
    "asyncio.run(read())"
)


def _read_table_secret(context: PreparedContext) -> tuple[str, str]:
    """只读取得一个 bootstrap Token；捕获值绝不写日志、路径清单或 Record。"""

    try:
        result = gatea._run_compose(
            values=context.values,
            config_file=context.config_file,
            secret_dir=context.secret_dir,
            mode="loopback",
            arguments=(
                "run",
                "--rm",
                "--no-deps",
                "app",
                "python",
                "-c",
                TABLE_SECRET_COMMAND,
            ),
            capture_output=True,
        )
        payload = json.loads(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise M9AcceptanceError(
            "Gate A M9 table bootstrap identity could not be read safely"
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"table_no", "qr_token"}
        or payload.get("table_no") != TABLE_NO
        or not isinstance(payload.get("qr_token"), str)
        or TABLE_QR_TOKEN_PATTERN.fullmatch(payload["qr_token"]) is None
    ):
        raise M9AcceptanceError("Gate A M9 table bootstrap identity is invalid")
    return TABLE_NO, str(payload["qr_token"])


def _read_admin_identity_from_tty() -> tuple[str, str]:
    """只从 /dev/tty 隐藏读取并双确认 SUPER_ADMIN 用户名和密码。"""

    try:
        with open("/dev/tty", "w", encoding="utf-8", buffering=1) as terminal:
            if not os.isatty(terminal.fileno()):
                raise M9AcceptanceError(
                    "Gate A M9 admin-assisted acceptance requires /dev/tty"
                )
            username = getpass.getpass(
                "Current SUPER_ADMIN username: ", stream=terminal
            )
            username_confirmation = getpass.getpass(
                "Confirm current SUPER_ADMIN username: ", stream=terminal
            )
            password = getpass.getpass(
                "Current SUPER_ADMIN password: ", stream=terminal
            )
            password_confirmation = getpass.getpass(
                "Confirm current SUPER_ADMIN password: ", stream=terminal
            )
    except (OSError, EOFError, KeyboardInterrupt) as error:
        raise M9AcceptanceError(
            "Gate A M9 admin-assisted acceptance requires a usable /dev/tty"
        ) from error
    try:
        base_data._validate_identity(username, username_confirmation)
        base_data._validate_password(password, password_confirmation)
    except base_data.RepresentativeDataError as error:
        raise M9AcceptanceError(
            "Gate A M9 SUPER_ADMIN TTY confirmation is invalid"
        ) from error
    username_confirmation = ""
    password_confirmation = ""
    return username, password


def _pending_payload(
    context: PreparedContext,
    *,
    stage: str = "prepared",
) -> dict[str, Any]:
    if stage not in PENDING_STAGE_RANK or ATTEMPT_ID_PATTERN.fullmatch(
        context.attempt_id
    ) is None:
        raise M9AcceptanceError("Gate A M9 pending stage is invalid")
    return {
        "schema_version": 3,
        "record_type": "gatea-m9-internal-acceptance-pending",
        "environment": "gatea",
        "candidate_sha": context.candidate_sha,
        "image_id": context.image_id,
        "operations_sha": context.operations_sha,
        "ci_run_id": context.ci_run_id,
        "source_candidate_sha": context.source_candidate_sha,
        "upgrade_record_sha256": context.upgrade_record_sha256,
        "upgrade_plan_replay_record_sha256": (
            context.upgrade_plan_replay_record_sha256
        ),
        "representative_record_sha256": context.representative_record_sha256,
        "credentials_sha256": context.credentials_sha256,
        "started_at": context.started_at,
        "attempt_id": context.attempt_id,
        "attempt_id_sha256": _sha256_text(context.attempt_id),
        "updated_at": _utc_now(),
        "stage": stage,
        "pre_reconcile": dict(context.pre_reconcile),
        "pre_wallet_reconcile": dict(context.pre_wallet_reconcile),
        "fixture_ids": [],
        "fixture": None,
        "fixture_sha256": None,
        "order_id": None,
        "order_evidence": None,
        "order_evidence_sha256": None,
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
            "order_cancelled": False,
            "fixture_products_offline": False,
            "synthetic_session_revoked": False,
            "super_admin_session_revoked": False,
        },
        "failure": False,
        "secret_values_recorded": False,
        "source_volume_restored": False,
        "passed": False,
    }


def _validate_pending_payload(
    context: PreparedContext,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        set(payload) != PENDING_RECORD_KEYS
        or payload.get("schema_version") != 3
        or payload.get("record_type")
        != "gatea-m9-internal-acceptance-pending"
        or payload.get("environment") != "gatea"
        or payload.get("candidate_sha") != context.candidate_sha
        or payload.get("image_id") != context.image_id
        or payload.get("operations_sha") != context.operations_sha
        or payload.get("ci_run_id") != context.ci_run_id
        or payload.get("source_candidate_sha") != context.source_candidate_sha
        or payload.get("upgrade_record_sha256")
        != context.upgrade_record_sha256
        or payload.get("upgrade_plan_replay_record_sha256")
        != context.upgrade_plan_replay_record_sha256
        or payload.get("representative_record_sha256")
        != context.representative_record_sha256
        or payload.get("credentials_sha256") != context.credentials_sha256
        or payload.get("started_at") != context.started_at
        or payload.get("attempt_id") != context.attempt_id
        or ATTEMPT_ID_PATTERN.fullmatch(str(payload.get("attempt_id", "")))
        is None
        or payload.get("attempt_id_sha256")
        != _sha256_text(context.attempt_id)
        or payload.get("stage") not in PENDING_STAGE_RANK
        or set(payload.get("pre_reconcile", {})) != RECONCILE_KEYS
        or payload.get("pre_reconcile") != dict(context.pre_reconcile)
        or set(payload.get("pre_wallet_reconcile", {}))
        != WALLET_RECONCILE_KEYS
        or payload.get("pre_wallet_reconcile")
        != dict(context.pre_wallet_reconcile)
        or set(payload.get("cleanup", {})) != PENDING_CLEANUP_KEYS
        or any(
            type(payload.get(field)) is not bool
            for field in (
                "claim_replay_verified",
                "payment_replay_verified",
                "admin_visibility_verified",
                "release_replay_verified",
                "payment_committed",
                "session_released",
                "failure",
            )
        )
        or any(
            type(payload["cleanup"].get(field)) is not bool
            for field in PENDING_CLEANUP_KEYS
        )
        or payload.get("secret_values_recorded") is not False
        or payload.get("source_volume_restored") is not False
        or payload.get("passed") is not False
    ):
        raise M9AcceptanceError("Gate A M9 pending journal binding is invalid")
    started_at = _parse_datetime(payload.get("started_at"), "pending-started-at")
    updated_at = _parse_datetime(payload.get("updated_at"), "pending-updated-at")
    if (
        updated_at < started_at
        or any(
            type(value) is not int or value != 0
            for value in payload["pre_reconcile"].values()
        )
        or any(
            type(value) is not int for value in payload["pre_wallet_reconcile"].values()
        )
        or payload["pre_wallet_reconcile"].get("scanned", 0) <= 0
        or payload["pre_wallet_reconcile"].get("mismatches") != 0
        or payload["pre_wallet_reconcile"].get("violations") != 0
    ):
        raise M9AcceptanceError("Gate A M9 pending journal baseline is invalid")

    fixture_ids = payload.get("fixture_ids")
    if (
        not isinstance(fixture_ids, list)
        or len(fixture_ids) > 2
        or any(type(value) is not int or value <= 0 for value in fixture_ids)
        or len(set(fixture_ids)) != len(fixture_ids)
    ):
        raise M9AcceptanceError("Gate A M9 pending fixture binding is invalid")
    fixture = payload.get("fixture")
    fixture_sha256 = payload.get("fixture_sha256")
    if fixture is None:
        if fixture_sha256 is not None:
            raise M9AcceptanceError("Gate A M9 pending fixture binding is invalid")
    elif (
        not isinstance(fixture, dict)
        or set(fixture) != FIXTURE_RECORD_KEYS
        or fixture_sha256 != _canonical_sha256(fixture)
        or fixture_ids
        != [fixture.get("experience_product_id"), fixture.get("kit_product_id")]
        or fixture.get("option_durations_minutes") != [60, 60, 120]
        or fixture.get("option_participants") != [1, 2, 1]
        or fixture.get("option_price") != FIXTURE_PRICE
        or fixture.get("kit_price") != FIXTURE_PRICE
        or fixture.get("kit_opening_stock") != FIXTURE_KIT_STOCK
        or fixture.get("product_images_created") != 2
        or fixture.get("option_images_created") != 3
        or fixture.get("products_online") is not True
        or not isinstance(fixture.get("option_ids"), list)
        or len(fixture["option_ids"]) != 3
        or any(
            type(value) is not int or value <= 0
            for value in fixture["option_ids"]
        )
        or len(set(fixture["option_ids"])) != 3
    ):
        raise M9AcceptanceError("Gate A M9 pending fixture binding is invalid")

    order_id = payload.get("order_id")
    order_evidence = payload.get("order_evidence")
    order_evidence_sha256 = payload.get("order_evidence_sha256")
    if order_evidence is None:
        if order_id is not None or order_evidence_sha256 is not None:
            raise M9AcceptanceError("Gate A M9 pending Order binding is invalid")
    else:
        timer_items = (
            order_evidence.get("expected_timer_items")
            if isinstance(order_evidence, dict)
            else None
        )
        if (
            not isinstance(order_evidence, dict)
            or set(order_evidence) != ORDER_EVIDENCE_KEYS
            or type(order_id) is not int
            or order_id <= 0
            or order_evidence.get("order_id") != order_id
            or order_evidence_sha256 != _canonical_sha256(order_evidence)
            or fixture is None
            or not isinstance(timer_items, list)
            or len(timer_items) != 3
            or any(
                not isinstance(item, dict)
                or set(item) != ORDER_TIMER_ITEM_KEYS
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
            != _expected_duration_groups()
        ):
            raise M9AcceptanceError("Gate A M9 pending Order binding is invalid")

    table_no = payload.get("table_no")
    session_hash = payload.get("session_no_sha256")
    deadline_offset = payload.get("payment_deadline_offset_seconds")
    if session_hash is None:
        if table_no is not None or deadline_offset is not None:
            raise M9AcceptanceError("Gate A M9 pending Session binding is invalid")
    elif (
        table_no != TABLE_NO
        or gatea.SHA256_PATTERN.fullmatch(str(session_hash)) is None
        or deadline_offset != 900
        or order_evidence is None
    ):
        raise M9AcceptanceError("Gate A M9 pending Session binding is invalid")

    payment_evidence = payload.get("payment_evidence")
    if payment_evidence is not None:
        if (
            not isinstance(payment_evidence, dict)
            or set(payment_evidence) != PAYMENT_EVIDENCE_KEYS
            or type(payment_evidence.get("payment_id")) is not int
            or payment_evidence["payment_id"] <= 0
            or gatea.SHA256_PATTERN.fullmatch(
                str(payment_evidence.get("payment_no_sha256", ""))
            )
            is None
            or session_hash is None
        ):
            raise M9AcceptanceError("Gate A M9 pending Payment binding is invalid")
        payment_succeeded_at = _parse_datetime(
            payment_evidence.get("succeeded_at"),
            "pending-payment-succeeded-at",
        )
        if payment_succeeded_at < started_at or payment_succeeded_at > updated_at:
            raise M9AcceptanceError("Gate A M9 pending Payment binding is invalid")
    if payment_evidence is not None and payload.get("payment_committed") is not True:
        raise M9AcceptanceError("Gate A M9 pending Payment binding is invalid")

    timer_evidence = payload.get("timer_evidence")
    if timer_evidence is not None and (
        not isinstance(timer_evidence, dict)
        or set(timer_evidence) != TIMER_EVIDENCE_KEYS
        or timer_evidence
        != {
            "durations": [60, 120],
            "buffers": [10, 10],
            "item_counts": [2, 1],
            "quantities": [3, 1],
            "service_offsets": [3600, 7200],
            "grace_offsets": [4200, 7800],
            "release_offset": 7800,
        }
    ):
        raise M9AcceptanceError("Gate A M9 pending Timer binding is invalid")
    if timer_evidence is not None and payment_evidence is None:
        raise M9AcceptanceError("Gate A M9 pending Timer binding is invalid")
    if (
        (
            payload.get("claim_replay_verified") is True
            and session_hash is None
        )
        or (
            payload.get("payment_replay_verified") is True
            and payment_evidence is None
        )
        or (
            payload.get("admin_visibility_verified") is True
            and timer_evidence is None
        )
        or (
            payload.get("release_replay_verified") is True
            and payload.get("session_released") is not True
        )
        or (
            payload.get("payment_committed") is True
            and payment_evidence is None
            and payload.get("failure") is not True
        )
    ):
        raise M9AcceptanceError("Gate A M9 pending replay binding is invalid")
    if payload.get("session_released") is True and session_hash is None:
        raise M9AcceptanceError("Gate A M9 pending Session binding is invalid")

    stage_rank = PENDING_STAGE_RANK[str(payload["stage"])]
    if (
        (
            stage_rank <= PENDING_STAGE_RANK["authenticated"]
            and fixture_ids
        )
        or (
            PENDING_STAGE_RANK["experience_created"]
            <= stage_rank
            <= PENDING_STAGE_RANK["experience_online"]
            and len(fixture_ids) != 1
        )
        or (
            stage_rank == PENDING_STAGE_RANK["kit_created"]
            and len(fixture_ids) != 2
        )
        or (stage_rank >= PENDING_STAGE_RANK["kit_online"] and fixture is None)
        or (
            stage_rank >= PENDING_STAGE_RANK["order_created"]
            and order_evidence is None
        )
        or (
            stage_rank >= PENDING_STAGE_RANK["claimed"]
            and (
                session_hash is None
                or payload.get("claim_replay_verified") is not True
            )
        )
        or (
            stage_rank >= PENDING_STAGE_RANK["paid"]
            and (
                payment_evidence is None
                or payload.get("payment_replay_verified") is not True
            )
        )
        or (
            stage_rank >= PENDING_STAGE_RANK["release_started"]
            and (
                timer_evidence is None
                or payload.get("admin_visibility_verified") is not True
            )
        )
        or (
            stage_rank >= PENDING_STAGE_RANK["released"]
            and (
                timer_evidence is None
                or payload.get("session_released") is not True
                or payload.get("admin_visibility_verified") is not True
                or payload.get("release_replay_verified") is not True
            )
        )
        or (
            stage_rank >= PENDING_STAGE_RANK["fixtures_offline"]
            and payload["cleanup"].get("fixture_products_offline") is not True
        )
        or (
            stage_rank >= PENDING_STAGE_RANK["verified"]
            and (
                payload["cleanup"].get("synthetic_session_revoked") is not True
                or payload["cleanup"].get("super_admin_session_revoked")
                is not True
            )
        )
        or (
            payload["cleanup"].get("order_cancelled") is True
            and (
                order_evidence is None
                or payload.get("payment_committed") is True
                or payload.get("failure") is not True
            )
        )
        or (
            payload["cleanup"].get("fixture_products_offline") is True
            and not fixture_ids
        )
    ):
        raise M9AcceptanceError("Gate A M9 pending stage evidence is incomplete")
    return dict(payload)


def _read_pending_file(
    context: PreparedContext,
) -> tuple[dict[str, Any], tuple[int, ...]]:
    payload, identity = _read_protected_json(
        context.pending_path,
        modes=frozenset({0o600}),
        link_counts=frozenset({1}),
        label="Gate A M9 pending acceptance journal",
    )
    return _validate_pending_payload(context, payload), identity


def _create_pending(context: PreparedContext) -> None:
    payload = _pending_payload(context, stage="prepared")
    _validate_record_directory(
        context.record_dir,
        "Gate A M9 acceptance record directory",
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            context.pending_path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        metadata = os.fstat(descriptor)
        if metadata.st_uid != ROOT_UID or metadata.st_gid != ROOT_GID:
            os.fchown(descriptor, ROOT_UID, ROOT_GID)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(context.pending_path.parent)
    except OSError as error:
        raise M9AcceptanceError(
            "Gate A M9 pending journal could not be created safely"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _read_pending_file(context)


def _discard_fresh_pending_after_admin_rejection(
    context: PreparedContext,
) -> None:
    """仅在首个管理员登录被明确拒绝时撤销尚无副作用的 checkpoint。"""

    current, current_identity = _read_pending_file(context)
    if (
        current.get("stage") != "authentication_started"
        or current.get("failure") is not False
        or current.get("fixture_ids") != []
        or current.get("fixture") is not None
        or current.get("order_id") is not None
        or current.get("session_no_sha256") is not None
        or current.get("payment_evidence") is not None
        or current.get("timer_evidence") is not None
        or any(current["cleanup"].values())
    ):
        raise M9AcceptanceError(
            "Gate A M9 rejected authentication checkpoint is not disposable"
        )
    try:
        _unlink_exact_file(
            context.pending_path,
            current_identity,
            label="Gate A M9 rejected authentication checkpoint",
        )
        _fsync_directory(context.pending_path.parent)
    except OSError as error:
        raise M9AcceptanceError(
            "Gate A M9 rejected authentication checkpoint could not be removed"
        ) from error


def _update_pending(
    context: PreparedContext,
    *,
    stage: str,
    fixture_ids: Sequence[int] | None = None,
    fixture: Mapping[str, Any] | None = None,
    order_evidence: Mapping[str, Any] | None = None,
    table_no: str | None = None,
    session_no: str | None = None,
    payment_deadline_offset_seconds: int | None = None,
    payment_evidence: Mapping[str, Any] | None = None,
    timer_evidence: Mapping[str, Any] | None = None,
    claim_replay_verified: bool | None = None,
    payment_replay_verified: bool | None = None,
    admin_visibility_verified: bool | None = None,
    release_replay_verified: bool | None = None,
    payment_committed: bool | None = None,
    session_released: bool | None = None,
    cleanup_updates: Mapping[str, bool] | None = None,
    reset_session_cleanup_for_authentication: bool = False,
    failure: bool | None = None,
) -> None:
    current, _ = _read_pending_file(context)
    if stage not in PENDING_STAGE_RANK or (
        PENDING_STAGE_RANK[stage] < PENDING_STAGE_RANK[str(current["stage"])]
    ):
        raise M9AcceptanceError("Gate A M9 pending stage cannot move backwards")
    current["stage"] = stage
    next_updated_at = _utc_now()
    if _parse_datetime(
        next_updated_at,
        "pending-next-updated-at",
    ) < _parse_datetime(current["updated_at"], "pending-current-updated-at"):
        raise M9AcceptanceError("Gate A M9 pending timestamp cannot move backwards")
    current["updated_at"] = next_updated_at
    if fixture_ids is not None:
        next_fixture_ids = list(fixture_ids)
        existing_fixture_ids = list(current["fixture_ids"])
        if (
            len(next_fixture_ids) < len(existing_fixture_ids)
            or next_fixture_ids[: len(existing_fixture_ids)]
            != existing_fixture_ids
        ):
            raise M9AcceptanceError(
                "Gate A M9 pending fixture identity cannot be rebound"
            )
        current["fixture_ids"] = next_fixture_ids
    if fixture is not None:
        next_fixture = dict(fixture)
        if current["fixture"] is not None and current["fixture"] != next_fixture:
            raise M9AcceptanceError(
                "Gate A M9 pending fixture evidence cannot be rebound"
            )
        current["fixture"] = next_fixture
        current["fixture_sha256"] = _canonical_sha256(current["fixture"])
    if order_evidence is not None:
        next_order_evidence = dict(order_evidence)
        if (
            current["order_evidence"] is not None
            and current["order_evidence"] != next_order_evidence
        ):
            raise M9AcceptanceError(
                "Gate A M9 pending Order evidence cannot be rebound"
            )
        current["order_id"] = next_order_evidence.get("order_id")
        current["order_evidence"] = next_order_evidence
        current["order_evidence_sha256"] = _canonical_sha256(
            current["order_evidence"]
        )
    if session_no is not None:
        next_session_hash = _sha256_text(session_no)
        if current["session_no_sha256"] is not None and (
            current["session_no_sha256"] != next_session_hash
            or current["table_no"] != table_no
            or current["payment_deadline_offset_seconds"]
            != payment_deadline_offset_seconds
        ):
            raise M9AcceptanceError(
                "Gate A M9 pending Session evidence cannot be rebound"
            )
        current["table_no"] = table_no
        current["session_no_sha256"] = next_session_hash
        current["payment_deadline_offset_seconds"] = (
            payment_deadline_offset_seconds
        )
    if payment_evidence is not None:
        next_payment_evidence = dict(payment_evidence)
        if (
            current["payment_evidence"] is not None
            and current["payment_evidence"] != next_payment_evidence
        ):
            raise M9AcceptanceError(
                "Gate A M9 pending Payment evidence cannot be rebound"
            )
        current["payment_evidence"] = next_payment_evidence
    if timer_evidence is not None:
        next_timer_evidence = dict(timer_evidence)
        if (
            current["timer_evidence"] is not None
            and current["timer_evidence"] != next_timer_evidence
        ):
            raise M9AcceptanceError(
                "Gate A M9 pending Timer evidence cannot be rebound"
            )
        current["timer_evidence"] = next_timer_evidence
    for field, value in (
        ("claim_replay_verified", claim_replay_verified),
        ("payment_replay_verified", payment_replay_verified),
        ("admin_visibility_verified", admin_visibility_verified),
        ("release_replay_verified", release_replay_verified),
    ):
        if value is not None:
            if type(value) is not bool or (
                current[field] is True and value is not True
            ):
                raise M9AcceptanceError("Gate A M9 pending replay binding is invalid")
            current[field] = value
    if payment_committed is not None:
        if current["payment_committed"] is True and payment_committed is not True:
            raise M9AcceptanceError(
                "Gate A M9 pending Payment commitment cannot move backwards"
            )
        current["payment_committed"] = payment_committed
    if session_released is not None:
        if current["session_released"] is True and session_released is not True:
            raise M9AcceptanceError(
                "Gate A M9 pending Session release cannot move backwards"
            )
        current["session_released"] = session_released
    if type(reset_session_cleanup_for_authentication) is not bool:
        raise M9AcceptanceError("Gate A M9 authentication checkpoint is invalid")
    if reset_session_cleanup_for_authentication:
        if (
            PENDING_STAGE_RANK[stage]
            < PENDING_STAGE_RANK["authentication_started"]
            or cleanup_updates is not None
            and {
                "synthetic_session_revoked",
                "super_admin_session_revoked",
            }
            & set(cleanup_updates)
        ):
            raise M9AcceptanceError(
                "Gate A M9 authentication checkpoint is invalid"
            )
        # 该写入必须先于下一次登录调用完成。这样旧一轮的 cleanup=True
        # 不会被误用来证明新一轮可能已创建的 RefreshSession 已撤销。
        current["cleanup"]["synthetic_session_revoked"] = False
        current["cleanup"]["super_admin_session_revoked"] = False
    if cleanup_updates is not None:
        if not set(cleanup_updates).issubset(PENDING_CLEANUP_KEYS):
            raise M9AcceptanceError("Gate A M9 pending cleanup binding is invalid")
        for key, value in cleanup_updates.items():
            if type(value) is not bool or (
                current["cleanup"][key] is True and value is not True
            ):
                raise M9AcceptanceError(
                    "Gate A M9 pending cleanup binding is invalid"
                )
            current["cleanup"][key] = value
    if failure is not None:
        if (
            current["failure"] is True
            and failure is not True
            and current["stage"] != "verified"
        ):
            raise M9AcceptanceError("Gate A M9 pending failure cannot be cleared")
        current["failure"] = failure
    _validate_pending_payload(context, current)
    backup._write_json_atomic(
        context.pending_path,
        current,
        0o600,
    )
    _fsync_directory(context.pending_path.parent)
    persisted, _ = _read_pending_file(context)
    if persisted != current:
        raise M9AcceptanceError(
            "Gate A M9 pending journal changed during durable update"
        )


def _assert_no_forbidden_record_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or key.lower() in FORBIDDEN_RECORD_KEYS:
                raise M9AcceptanceError(
                    "Gate A M9 success record contains a forbidden field"
                )
            _assert_no_forbidden_record_keys(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_record_keys(child)


def _validate_success_semantics(payload: Mapping[str, Any]) -> None:
    """校验安装器依赖的绑定，以及业务结论对应的冻结数值。"""

    fixture = payload["fixture"]
    scenario = payload["scenario"]
    pre_reconcile = payload["pre_reconcile"]
    post_reconcile = payload["post_reconcile"]
    pre_wallet = payload["pre_wallet_reconcile"]
    post_wallet = payload["post_wallet_reconcile"]
    cleanup = payload["cleanup"]
    log_redaction = payload["log_redaction"]
    expected_groups = [
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
    invalid_binding = (
        gatea.GIT_SHA_PATTERN.fullmatch(str(payload.get("candidate_sha", "")))
        is None
        or gatea.GIT_SHA_PATTERN.fullmatch(
            str(payload.get("source_candidate_sha", ""))
        )
        is None
        or payload["candidate_sha"] == payload["source_candidate_sha"]
        or gatea.SHA256_PATTERN.fullmatch(
            str(payload.get("attempt_id_sha256", ""))
        )
        is None
        or payload.get("operations_sha") != payload["candidate_sha"]
        or not isinstance(payload.get("image_id"), str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", payload["image_id"])
        or not isinstance(payload.get("ci_run_id"), str)
        or not payload["ci_run_id"].isascii()
        or not payload["ci_run_id"].isdecimal()
        or int(payload["ci_run_id"]) <= 0
        or any(
            gatea.SHA256_PATTERN.fullmatch(str(payload.get(field, ""))) is None
            for field in (
                "upgrade_record_sha256",
                "upgrade_plan_replay_record_sha256",
                "representative_record_sha256",
                "credentials_sha256",
            )
        )
        or type(payload.get("request_count")) is not int
        or payload["request_count"] <= 0
    )
    invalid_fixture = (
        type(fixture.get("experience_product_id")) is not int
        or fixture["experience_product_id"] <= 0
        or type(fixture.get("kit_product_id")) is not int
        or fixture["kit_product_id"] <= 0
        or not isinstance(fixture.get("option_ids"), list)
        or len(fixture["option_ids"]) != 3
        or any(type(value) is not int or value <= 0 for value in fixture["option_ids"])
        or len(set(fixture["option_ids"])) != 3
        or fixture.get("option_durations_minutes") != [60, 60, 120]
        or fixture.get("option_participants") != [1, 2, 1]
        or fixture.get("option_price") != FIXTURE_PRICE
        or fixture.get("kit_price") != FIXTURE_PRICE
        or fixture.get("kit_opening_stock") != FIXTURE_KIT_STOCK
        or fixture.get("product_images_created") != 2
        or fixture.get("option_images_created") != 3
        or fixture.get("products_online") is not True
    )
    invalid_scenario = (
        type(scenario.get("order_id")) is not int
        or scenario["order_id"] <= 0
        or type(scenario.get("payment_id")) is not int
        or scenario["payment_id"] <= 0
        or gatea.SHA256_PATTERN.fullmatch(
            str(scenario.get("payment_no_sha256", ""))
        )
        is None
        or scenario.get("table_no") != TABLE_NO
        or gatea.SHA256_PATTERN.fullmatch(
            str(scenario.get("session_no_sha256", ""))
        )
        is None
        or scenario.get("order_total") != FIXTURE_ORDER_TOTAL
        or scenario.get("experience_item_count") != 3
        or scenario.get("kit_item_count") != 1
        or scenario.get("eligible_duration_groups") != expected_groups
        or scenario.get("claim_statuses") != [201, 200]
        or scenario.get("payment_deadline_offset_seconds") != 900
        or scenario.get("awaiting_timer_count") != 0
        or scenario.get("payment_statuses") != [201, 200]
        or scenario.get("post_payment_balance") != EXPECTED_POST_PAYMENT_BALANCE
        or scenario.get("active_timer_durations_minutes") != [60, 120]
        or scenario.get("active_timer_buffer_minutes") != [10, 10]
        or scenario.get("active_timer_experience_item_counts") != [2, 1]
        or scenario.get("active_timer_total_quantities") != [3, 1]
        or scenario.get("timer_service_offsets_seconds") != [3600, 7200]
        or scenario.get("timer_grace_offsets_seconds") != [4200, 7800]
        or scenario.get("table_release_offset_seconds") != 7800
        or any(
            scenario.get(field) is not True
            for field in (
                "claim_replay_same_session",
                "payment_replay_same_payment",
                "timer_started_at_matches_payment",
                "same_duration_items_merged",
                "different_durations_separated",
                "quantity_did_not_multiply_duration",
                "kit_excluded_from_timers",
                "admin_visible_while_active",
                "release_replay_same_fact",
                "table_available_after_release",
            )
        )
        or scenario.get("release_statuses") != [200, 200]
        or scenario.get("final_session_status") != "closed"
        or scenario.get("final_close_reason") != "admin_released"
        or scenario.get("final_order_status") != "paid"
    )
    invalid_consistency = (
        any(type(value) is not int or value != 0 for value in pre_reconcile.values())
        or any(type(value) is not int for value in post_reconcile.values())
        or post_reconcile.get("scanned") != 1
        or any(value != 0 for key, value in post_reconcile.items() if key != "scanned")
        or any(type(value) is not int for value in pre_wallet.values())
        or any(type(value) is not int for value in post_wallet.values())
        or pre_wallet.get("scanned", 0) <= 0
        or post_wallet.get("scanned") != pre_wallet.get("scanned")
        or any(
            evidence.get(field) != 0
            for evidence in (pre_wallet, post_wallet)
            for field in ("mismatches", "violations")
        )
        or payload.get("table_sweep") != {"status": "ok", "closed": 0}
        or cleanup
        != {
            "active_session_released": True,
            "synthetic_session_revoked": True,
            "synthetic_refresh_rejected": True,
            "super_admin_session_revoked": True,
            "super_admin_refresh_rejected": True,
            "open_sessions_after": 0,
            "occupancies_after": 0,
            "fixture_products_offline": True,
            "pending_record_retained": False,
        }
        or log_redaction.get("window") != "24h"
        or type(log_redaction.get("combined_line_count")) is not int
        or log_redaction["combined_line_count"] <= 0
        or log_redaction.get("services_scanned") != list(M9_SERVICES)
        or log_redaction.get("exact_secret_matches") != 0
        or log_redaction.get("forbidden_pattern_matches") != 0
        or log_redaction.get("raw_log_content_recorded") is not False
        or log_redaction.get("passed") is not True
    )
    started_at = _parse_datetime(payload.get("started_at"), "record-started-at")
    completed_at = _parse_datetime(
        payload.get("completed_at"), "record-completed-at"
    )
    payment_succeeded_at = _parse_datetime(
        scenario.get("payment_succeeded_at"),
        "record-payment-succeeded-at",
    )
    if (
        invalid_binding
        or invalid_fixture
        or invalid_scenario
        or invalid_consistency
        or completed_at < started_at
        or payment_succeeded_at < started_at
        or payment_succeeded_at > completed_at
    ):
        raise M9AcceptanceError("Gate A M9 success record evidence is invalid")


def _validate_success_record(payload: Mapping[str, Any]) -> None:
    if (
        set(payload) != SUCCESS_RECORD_KEYS
        or payload.get("schema_version") != 1
        or payload.get("record_type") != "gatea-m9-runtime-acceptance"
        or payload.get("environment") != "gatea"
        or payload.get("ci_job_name") != CI_JOB_NAME
        or payload.get("runtime_services") != list(M9_SERVICES)
        or set(payload.get("fixture", {})) != FIXTURE_RECORD_KEYS
        or set(payload.get("scenario", {})) != SCENARIO_RECORD_KEYS
        or set(payload.get("pre_reconcile", {})) != RECONCILE_KEYS
        or set(payload.get("post_reconcile", {})) != RECONCILE_KEYS
        or set(payload.get("pre_wallet_reconcile", {}))
        != WALLET_RECONCILE_KEYS
        or set(payload.get("post_wallet_reconcile", {}))
        != WALLET_RECONCILE_KEYS
        or set(payload.get("cleanup", {})) != CLEANUP_RECORD_KEYS
        or set(payload.get("table_sweep", {})) != TABLE_SWEEP_KEYS
        or set(payload.get("log_redaction", {})) != LOG_REDACTION_KEYS
        or any(
            payload.get(field) is not True
            for field in (
                "upgrade_plan_replayed",
                "wallet_reconcile_passed",
                "table_reconcile_passed",
                "table_sweep_passed",
                "log_redaction_passed",
                "passed",
            )
        )
        or any(
            payload.get(field) is not False
            for field in (
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
        )
        or payload.get("loopback_only") is not True
        or payload.get("table_sweep", {}).get("status") != "ok"
        or payload.get("table_sweep", {}).get("closed") != 0
        or payload.get("log_redaction", {}).get("passed") is not True
    ):
        raise M9AcceptanceError("Gate A M9 success record shape is invalid")
    _validate_success_semantics(payload)
    _assert_no_forbidden_record_keys(payload)


def _validate_success_binding(
    context: PreparedContext,
    payload: Mapping[str, Any],
    *,
    allow_preverified_complete: bool = False,
) -> dict[str, Any]:
    _validate_success_record(payload)
    if (
        payload.get("candidate_sha") != context.candidate_sha
        or payload.get("image_id") != context.image_id
        or payload.get("operations_sha") != context.operations_sha
        or payload.get("ci_run_id") != context.ci_run_id
        or payload.get("source_candidate_sha") != context.source_candidate_sha
        or payload.get("upgrade_record_sha256")
        != context.upgrade_record_sha256
        or payload.get("upgrade_plan_replay_record_sha256")
        != context.upgrade_plan_replay_record_sha256
        or payload.get("representative_record_sha256")
        != context.representative_record_sha256
        or payload.get("credentials_sha256") != context.credentials_sha256
    ):
        raise M9AcceptanceError(
            "Gate A M9 staged success record binding is invalid"
        )
    pending = context.pending
    if pending is not None:
        scenario = payload.get("scenario", {})
        order_evidence = pending.get("order_evidence")
        payment_evidence = pending.get("payment_evidence")
        timer_evidence = pending.get("timer_evidence")
        stage = str(pending.get("stage"))
        stage_is_committed = stage == "verified" and pending.get("failure") is False
        stage_is_recoverable = (
            allow_preverified_complete
            and stage in {"fixtures_offline", "verified"}
        )
        if (
            not (stage_is_committed or stage_is_recoverable)
            or payload.get("attempt_id_sha256")
            != pending.get("attempt_id_sha256")
            or payload.get("started_at") != pending.get("started_at")
            or payload.get("pre_reconcile") != pending.get("pre_reconcile")
            or payload.get("pre_wallet_reconcile")
            != pending.get("pre_wallet_reconcile")
            or payload.get("fixture") != pending.get("fixture")
            or not isinstance(order_evidence, dict)
            or scenario.get("order_id") != pending.get("order_id")
            or scenario.get("eligible_duration_groups")
            != order_evidence.get("eligible_duration_groups")
            or scenario.get("experience_item_count")
            != len(order_evidence.get("expected_timer_items", []))
            or scenario.get("kit_item_count") != 1
            or scenario.get("session_no_sha256")
            != pending.get("session_no_sha256")
            or scenario.get("table_no") != pending.get("table_no")
            or scenario.get("payment_deadline_offset_seconds")
            != pending.get("payment_deadline_offset_seconds")
            or not isinstance(payment_evidence, dict)
            or scenario.get("payment_id") != payment_evidence.get("payment_id")
            or scenario.get("payment_no_sha256")
            != payment_evidence.get("payment_no_sha256")
            or scenario.get("payment_succeeded_at")
            != payment_evidence.get("succeeded_at")
            or not isinstance(timer_evidence, dict)
            or scenario.get("active_timer_durations_minutes")
            != timer_evidence.get("durations")
            or scenario.get("active_timer_buffer_minutes")
            != timer_evidence.get("buffers")
            or scenario.get("active_timer_experience_item_counts")
            != timer_evidence.get("item_counts")
            or scenario.get("active_timer_total_quantities")
            != timer_evidence.get("quantities")
            or scenario.get("timer_service_offsets_seconds")
            != timer_evidence.get("service_offsets")
            or scenario.get("timer_grace_offsets_seconds")
            != timer_evidence.get("grace_offsets")
            or scenario.get("table_release_offset_seconds")
            != timer_evidence.get("release_offset")
            or pending.get("payment_committed") is not True
            or pending.get("session_released") is not True
            or pending.get("claim_replay_verified") is not True
            or pending.get("payment_replay_verified") is not True
            or pending.get("admin_visibility_verified") is not True
            or pending.get("release_replay_verified") is not True
            or pending.get("cleanup", {}).get("fixture_products_offline")
            is not True
        ):
            raise M9AcceptanceError(
                "Gate A M9 staged success record does not match its pending journal"
            )
    return dict(payload)


def _promote_success_inode(
    path: Path,
    expected_identity: tuple[int, ...],
    *,
    link_counts: frozenset[int],
    label: str,
) -> tuple[int, ...]:
    """在稳定 fd 上发布 mode，并同步 inode 后重新确认目录项身份。"""

    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before_metadata = os.fstat(descriptor)
        _validate_protected_metadata(
            before_metadata,
            modes=frozenset({0o600, 0o644}),
            link_counts=link_counts,
            label=label,
        )
        if _file_identity(before_metadata) != expected_identity:
            raise M9AcceptanceError(f"{label} changed before publication")
        os.fchmod(descriptor, 0o644)
        os.fsync(descriptor)
        after_metadata = os.fstat(descriptor)
        path_metadata = path.lstat()
        _validate_protected_metadata(
            after_metadata,
            modes=frozenset({0o644}),
            link_counts=link_counts,
            label=label,
        )
        if (
            after_metadata.st_dev != before_metadata.st_dev
            or after_metadata.st_ino != before_metadata.st_ino
            or _file_identity(after_metadata) != _file_identity(path_metadata)
        ):
            raise M9AcceptanceError(f"{label} changed during publication")
    except M9AcceptanceError:
        raise
    except OSError as error:
        raise M9AcceptanceError(
            "Gate A M9 staged success inode could not be published safely"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return _file_identity(after_metadata)


def _publish_staged_success(context: PreparedContext) -> dict[str, Any]:
    payload = context.staged_success
    if payload is None:
        raise M9AcceptanceError("Gate A M9 staged success record is unavailable")
    _validate_record_directory(
        context.record_dir,
        "Gate A M9 acceptance record directory",
    )
    _cleanup_success_temporaries(context)
    complete_exists = _path_entry_exists(context.complete_path)
    final_exists = _path_entry_exists(context.record_path)
    if not complete_exists and not final_exists:
        raise M9AcceptanceError(
            "Gate A M9 staged success payload has no publication source"
        )
    complete_identity: tuple[int, ...] | None = None
    final_identity: tuple[int, ...] | None = None
    complete_payload: dict[str, Any] | None = None
    final_payload: dict[str, Any] | None = None
    expected_links = frozenset({2}) if complete_exists and final_exists else frozenset({1})
    if complete_exists:
        complete_payload, complete_identity = _read_protected_json(
            context.complete_path,
            modes=frozenset({0o600, 0o644}),
            link_counts=expected_links,
            label="Gate A M9 staged acceptance success",
        )
    if final_exists:
        final_payload, final_identity = _read_protected_json(
            context.record_path,
            modes=frozenset({0o644}) if not complete_exists else frozenset({0o600, 0o644}),
            link_counts=expected_links,
            label="Gate A M9 acceptance success",
        )
    source_payload = complete_payload if complete_payload is not None else final_payload
    if source_payload != payload:
        raise M9AcceptanceError(
            "Gate A M9 staged success payload changed before publication"
        )
    if complete_exists and final_exists and (
        complete_payload != final_payload
        or complete_identity is None
        or final_identity is None
        or complete_identity[:2] != final_identity[:2]
    ):
        raise M9AcceptanceError("Gate A M9 staged success links are inconsistent")
    current_pending: dict[str, Any] | None = None
    if _path_entry_exists(context.pending_path):
        current_pending, _ = _read_pending_file(context)
    current_context = replace(context, pending=current_pending)
    if complete_exists and not final_exists:
        if current_pending is None:
            raise M9AcceptanceError(
                "Gate A M9 staged success has no pending journal"
            )
        validated = _validate_success_binding(
            current_context,
            payload,
            allow_preverified_complete=True,
        )
        if (
            current_pending.get("stage") != "verified"
            or current_pending.get("failure") is not False
        ):
            _update_pending(
                context,
                stage="verified",
                cleanup_updates={
                    "fixture_products_offline": True,
                    "synthetic_session_revoked": True,
                    "super_admin_session_revoked": True,
                },
                failure=False,
            )
            current_pending, _ = _read_pending_file(context)
            current_context = replace(context, pending=current_pending)
            validated = _validate_success_binding(current_context, payload)
    else:
        validated = _validate_success_binding(current_context, payload)

    # 完整的 complete inode 先在稳定 fd 上切到最终权限并 fsync；随后 final
    # hard-link 一旦可见，就从未指向 mode 未持久化或内容未完成的 inode。
    if complete_exists:
        if complete_identity is None:
            raise M9AcceptanceError("Gate A M9 staged success identity is unavailable")
        complete_identity = _promote_success_inode(
            context.complete_path,
            complete_identity,
            link_counts=expected_links,
            label="Gate A M9 staged acceptance success",
        )
        complete_payload, complete_identity = _read_protected_json(
            context.complete_path,
            modes=frozenset({0o644}),
            link_counts=expected_links,
            label="Gate A M9 staged acceptance success",
        )
        if complete_payload != payload:
            raise M9AcceptanceError(
                "Gate A M9 staged success payload changed during publication"
            )
    try:
        if not final_exists:
            if complete_identity is None:
                raise M9AcceptanceError(
                    "Gate A M9 staged success identity is unavailable"
                )
            _link_exact_file(
                context.complete_path,
                context.record_path,
                complete_identity,
                label="Gate A M9 final success publication",
            )
            _fsync_directory(context.record_dir)
    except OSError as error:
        raise M9AcceptanceError(
            "Gate A M9 staged success record could not be recovered safely"
        ) from error

    final_payload, final_identity = _read_protected_json(
        context.record_path,
        modes=frozenset({0o644}),
        link_counts=frozenset({2}) if complete_exists else frozenset({1}),
        label="Gate A M9 acceptance success",
    )
    if final_payload != payload:
        raise M9AcceptanceError(
            "Gate A M9 success payload changed after publication"
        )
    if complete_exists:
        complete_payload, complete_identity = _read_protected_json(
            context.complete_path,
            modes=frozenset({0o644}),
            link_counts=frozenset({2}),
            label="Gate A M9 staged acceptance success",
        )
        if (
            complete_payload != payload
            or complete_identity[:2] != final_identity[:2]
        ):
            raise M9AcceptanceError(
                "Gate A M9 staged success links changed after publication"
            )

    # 在移除 journal 前再次绑定完整证据，避免基于 prepare 的旧元数据发布。
    if _path_entry_exists(context.pending_path):
        current_pending, pending_identity = _read_pending_file(context)
        _validate_success_binding(replace(context, pending=current_pending), payload)
        _unlink_exact_file(
            context.pending_path,
            pending_identity,
            label="Gate A M9 pending acceptance journal",
        )
        _fsync_directory(context.record_dir)
    if complete_exists:
        complete_payload, complete_identity = _read_protected_json(
            context.complete_path,
            modes=frozenset({0o644}),
            link_counts=frozenset({2}),
            label="Gate A M9 staged acceptance success",
        )
        final_payload, final_identity = _read_protected_json(
            context.record_path,
            modes=frozenset({0o644}),
            link_counts=frozenset({2}),
            label="Gate A M9 acceptance success",
        )
        if (
            complete_payload != payload
            or final_payload != payload
            or complete_identity[:2] != final_identity[:2]
        ):
            raise M9AcceptanceError(
                "Gate A M9 success links changed before staged cleanup"
            )
        _unlink_exact_file(
            context.complete_path,
            complete_identity,
            label="Gate A M9 staged acceptance success",
        )
        _fsync_directory(context.record_dir)
    final_payload, _ = _read_protected_json(
        context.record_path,
        modes=frozenset({0o644}),
        link_counts=frozenset({1}),
        label="Gate A M9 acceptance success",
    )
    if final_payload != payload:
        raise M9AcceptanceError("Gate A M9 published success record changed")
    return validated


def _write_success_temp_exclusive(path: Path, serialized: str) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        metadata = os.fstat(descriptor)
        if metadata.st_uid != ROOT_UID or metadata.st_gid != ROOT_GID:
            os.fchown(descriptor, ROOT_UID, ROOT_GID)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            if stream.write(serialized) != len(serialized):
                raise OSError("Gate A M9 success temporary write was incomplete")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _stage_success_record_exclusive(
    context: PreparedContext,
    payload: Mapping[str, Any],
    *,
    secret_values: Sequence[str],
) -> None:
    _validate_success_record(payload)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    if any(value and value in serialized for value in secret_values):
        raise M9AcceptanceError("Gate A M9 success record contains a sensitive value")
    _validate_record_directory(
        context.record_dir,
        "Gate A M9 acceptance record directory",
    )
    _cleanup_success_temporaries(context)
    temporary_path: Path | None = None
    operation_error: BaseException | None = None
    try:
        for _ in range(16):
            candidate = context.record_dir / (
                f".{context.complete_path.name}.{secrets.token_hex(16)}.tmp"
            )
            temporary_path = candidate
            try:
                _write_success_temp_exclusive(candidate, serialized)
            except FileExistsError:
                temporary_path = None
                continue
            break
        else:
            raise M9AcceptanceError(
                "Gate A M9 success temporary path could not be reserved"
            )
        if temporary_path is None:
            raise M9AcceptanceError(
                "Gate A M9 success temporary path could not be reserved"
            )
        temporary_payload, temporary_identity = _read_protected_json(
            temporary_path,
            modes=frozenset({0o600}),
            link_counts=frozenset({1}),
            label="Gate A M9 success temporary file",
        )
        if temporary_payload != payload:
            raise M9AcceptanceError(
                "Gate A M9 success temporary payload changed before staging"
            )
        # hard link 在目标已存在时必定失败，因此 complete 永不覆盖；目标一旦
        # 可见就和已完整 fsync 的随机临时文件共享同一个 inode。
        _link_exact_file(
            temporary_path,
            context.complete_path,
            temporary_identity,
            label="Gate A M9 staged success publication",
        )
        _fsync_directory(context.record_dir)
        temporary_payload, temporary_identity = _read_protected_json(
            temporary_path,
            modes=frozenset({0o600}),
            link_counts=frozenset({2}),
            label="Gate A M9 success temporary file",
        )
        complete_payload, complete_identity = _read_protected_json(
            context.complete_path,
            modes=frozenset({0o600}),
            link_counts=frozenset({2}),
            label="Gate A M9 staged acceptance success",
        )
        if (
            temporary_payload != payload
            or complete_payload != payload
            or temporary_identity[:2] != complete_identity[:2]
        ):
            raise M9AcceptanceError(
                "Gate A M9 staged success identity changed during publication"
            )
    except BaseException as error:
        operation_error = error
    finally:
        cleanup_error: BaseException | None = None
        if temporary_path is not None:
            try:
                if _path_entry_exists(temporary_path):
                    temporary_identity = _stable_protected_identity(
                        temporary_path,
                        modes=frozenset({0o600, 0o644}),
                        link_counts=frozenset({1, 2, 3}),
                        label="Gate A M9 success temporary file",
                    )
                    _unlink_exact_file(
                        temporary_path,
                        temporary_identity,
                        label="Gate A M9 success temporary file",
                    )
                    _fsync_directory(context.record_dir)
            except BaseException as error:
                cleanup_error = error
    interruption_types = (
        KeyboardInterrupt,
        gatea.GateAOperationInterrupted,
        SystemExit,
    )
    if isinstance(operation_error, interruption_types):
        raise operation_error
    if isinstance(cleanup_error, interruption_types):
        raise cleanup_error
    if cleanup_error is not None:
        raise M9AcceptanceError(
            "Gate A M9 success temporary file could not be cleaned safely"
        ) from cleanup_error
    if operation_error is not None:
        if isinstance(operation_error, M9AcceptanceError):
            raise operation_error
        if isinstance(operation_error, OSError):
            raise M9AcceptanceError(
                "Gate A M9 success record could not be staged safely"
            ) from operation_error
        raise operation_error
    complete_payload, _ = _read_protected_json(
        context.complete_path,
        modes=frozenset({0o600}),
        link_counts=frozenset({1}),
        label="Gate A M9 staged acceptance success",
    )
    if complete_payload != payload:
        raise M9AcceptanceError(
            "Gate A M9 staged success payload changed after temporary cleanup"
        )


def _labeled_value(payload: Mapping[str, Any], field: str, step: str) -> object:
    value = payload.get(field)
    if not isinstance(value, dict) or set(value) != {"value", "label"}:
        raise M9AcceptanceError(f"Gate A M9 step {step} returned invalid {field}")
    return value.get("value")


def _assert_product_identity(
    payload: Mapping[str, Any],
    *,
    product_type: str,
    status_value: str,
    step: str,
) -> int:
    product_id = _positive_id(payload, "id", step)
    if (
        _labeled_value(payload, "product_type", step) != product_type
        or _labeled_value(payload, "status", step) != status_value
    ):
        raise M9AcceptanceError(f"Gate A M9 step {step} returned invalid Product")
    return product_id


def _create_fixture(
    client: SafeLoopbackClient,
    *,
    admin_token: str,
    acceptance_attempt_id: str,
    progress: Callable[[str, Sequence[int]], None] | None = None,
) -> dict[str, Any]:
    suffix = acceptance_attempt_id[:12]
    experience = _data(
        client.json_request(
            "create-experience",
            "POST",
            "/api/v1/admin/products/experience",
            token=admin_token,
            payload={
                "name": f"[GATEA-M9] Runtime experience {suffix}",
                "description": "Controlled M9 multi-duration timer acceptance fixture",
            },
            expected_status=201,
        ),
        "create-experience",
    )
    experience_id = _assert_product_identity(
        experience,
        product_type="experience",
        status_value="draft",
        step="create-experience",
    )
    if progress is not None:
        progress("experience_created", (experience_id,))
    option_specs = ((60, 1), (60, 2), (120, 1))
    option_ids: list[int] = []
    for index, (duration, participants) in enumerate(option_specs, start=1):
        step = f"create-experience-option-{index}"
        option = _data(
            client.json_request(
                step,
                "POST",
                f"/api/v1/admin/products/experience/{experience_id}/options",
                token=admin_token,
                payload={
                    "duration_minutes": duration,
                    "participants": participants,
                    "day_type": "weekday",
                    "price": FIXTURE_PRICE,
                },
                expected_status=201,
            ),
            step,
        )
        option_id = _positive_id(option, "id", step)
        if (
            _labeled_value(option, "duration", step) != duration
            or _labeled_value(option, "participants", step) != participants
            or _labeled_value(option, "day_type", step) != "weekday"
            or option.get("price") != FIXTURE_PRICE
            or option.get("images") != []
        ):
            raise M9AcceptanceError(f"Gate A M9 step {step} returned invalid Option")
        option_ids.append(option_id)
        image = base_data._upload_image(
            client,
            step=f"upload-option-image-{index}",
            path=f"/api/v1/admin/options/{option_id}/images",
            token=admin_token,
            fields={"sort": "0"},
        )
        base_data._verify_image_read(
            client,
            step=f"read-option-image-{index}",
            image=image,
        )
    product_image = base_data._upload_image(
        client,
        step="upload-experience-cover",
        path=f"/api/v1/admin/products/{experience_id}/images",
        token=admin_token,
        fields={"is_cover": "true", "sort": "0"},
    )
    base_data._verify_image_read(
        client,
        step="read-experience-cover",
        image=product_image,
    )
    online_experience = _data(
        client.json_request(
            "online-experience",
            "PATCH",
            f"/api/v1/admin/products/{experience_id}/online",
            token=admin_token,
        ),
        "online-experience",
    )
    if (
        _positive_id(online_experience, "id", "online-experience")
        != experience_id
        or _labeled_value(online_experience, "status", "online-experience")
        != "online"
    ):
        raise M9AcceptanceError("Gate A M9 Experience did not become sale-ready")
    if progress is not None:
        progress("experience_online", (experience_id,))

    kit = _data(
        client.json_request(
            "create-kit",
            "POST",
            "/api/v1/admin/products/kit",
            token=admin_token,
            payload={
                "name": f"[GATEA-M9] Runtime fixed Kit {suffix}",
                "description": "Controlled M9 non-timer Kit fixture",
                "price": FIXTURE_PRICE,
                "kit_kind": "fixed",
            },
            expected_status=201,
        ),
        "create-kit",
    )
    kit_id = _assert_product_identity(
        kit,
        product_type="kit",
        status_value="draft",
        step="create-kit",
    )
    if progress is not None:
        progress("kit_created", (experience_id, kit_id))
    if _labeled_value(kit, "kit_kind", "create-kit") != "fixed":
        raise M9AcceptanceError("Gate A M9 Kit kind is invalid")
    kit_image = base_data._upload_image(
        client,
        step="upload-kit-cover",
        path=f"/api/v1/admin/products/{kit_id}/images",
        token=admin_token,
        fields={"is_cover": "true", "sort": "0"},
    )
    base_data._verify_image_read(
        client,
        step="read-kit-cover",
        image=kit_image,
    )
    inventory_payload = {
        "change": FIXTURE_KIT_STOCK,
        "reason": "Gate A M9 controlled fixture supply",
    }
    inventory_headers = {
        "Idempotency-Key": (
            f"gatea-m9-kit-stock-{acceptance_attempt_id}-v1"
        )
    }
    adjusted = _data(
        client.json_request(
            "supply-kit",
            "POST",
            f"/api/v1/admin/products/kit/{kit_id}/inventory-adjustments",
            token=admin_token,
            payload=inventory_payload,
            headers=inventory_headers,
            expected_status=201,
        ),
        "supply-kit",
    )
    replayed_adjustment = _data(
        client.json_request(
            "replay-kit-supply",
            "POST",
            f"/api/v1/admin/products/kit/{kit_id}/inventory-adjustments",
            token=admin_token,
            payload=inventory_payload,
            headers=inventory_headers,
            expected_status=200,
        ),
        "replay-kit-supply",
    )
    if (
        adjusted.get("product_id") != kit_id
        or adjusted.get("stock") != FIXTURE_KIT_STOCK
        or replayed_adjustment.get("product_id") != kit_id
        or replayed_adjustment.get("stock") != FIXTURE_KIT_STOCK
        or _positive_id(adjusted.get("transaction", {}), "id", "supply-kit")
        != _positive_id(
            replayed_adjustment.get("transaction", {}),
            "id",
            "replay-kit-supply",
        )
    ):
        raise M9AcceptanceError("Gate A M9 Kit inventory replay is invalid")
    online_kit = _data(
        client.json_request(
            "online-kit",
            "PATCH",
            f"/api/v1/admin/products/{kit_id}/online",
            token=admin_token,
        ),
        "online-kit",
    )
    if (
        _positive_id(online_kit, "id", "online-kit") != kit_id
        or _labeled_value(online_kit, "status", "online-kit") != "online"
    ):
        raise M9AcceptanceError("Gate A M9 Kit did not become sale-ready")
    if progress is not None:
        progress("kit_online", (experience_id, kit_id))
    return {
        "experience_product_id": experience_id,
        "kit_product_id": kit_id,
        "option_ids": option_ids,
        "option_durations_minutes": [60, 60, 120],
        "option_participants": [1, 2, 1],
        "option_price": FIXTURE_PRICE,
        "kit_price": FIXTURE_PRICE,
        "kit_opening_stock": FIXTURE_KIT_STOCK,
        "product_images_created": 2,
        "option_images_created": 3,
        "products_online": True,
    }


def _create_mixed_order(
    client: SafeLoopbackClient,
    *,
    user_token: str,
    fixture: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[int, tuple[int, int]], int]:
    experience_id = int(fixture["experience_product_id"])
    kit_id = int(fixture["kit_product_id"])
    option_ids = [int(value) for value in fixture["option_ids"]]
    quantities = (2, 1, 1)
    items = [
        {
            "product_id": experience_id,
            "experience_option_id": option_id,
            "quantity": quantity,
        }
        for option_id, quantity in zip(option_ids, quantities, strict=True)
    ]
    items.append(
        {
            "product_id": kit_id,
            "experience_option_id": None,
            "quantity": 1,
        }
    )
    order = _data(
        client.json_request(
            "create-mixed-order",
            "POST",
            "/api/v1/orders",
            token=user_token,
            payload={
                "items": items,
                "remark": "[GATEA-M9] same/different duration and Kit acceptance",
            },
            expected_status=201,
        ),
        "create-mixed-order",
    )
    timer_items, kit_order_item_id = _parse_mixed_order(
        order,
        fixture=fixture,
        step="create-mixed-order",
    )
    return order, timer_items, kit_order_item_id


def _parse_mixed_order(
    order: Mapping[str, Any],
    *,
    fixture: Mapping[str, Any],
    step: str,
) -> tuple[dict[int, tuple[int, int]], int]:
    """从正式 Order 投影重建并校验可续跑的计时绑定。"""

    experience_id = int(fixture["experience_product_id"])
    kit_id = int(fixture["kit_product_id"])
    option_ids = [int(value) for value in fixture["option_ids"]]
    quantities = (2, 1, 1)
    order_id = _positive_id(order, "id", step)
    if (
        _labeled_value(order, "status", step) not in {"pending", "paid"}
        or order.get("total_amount") != FIXTURE_ORDER_TOTAL
        or not isinstance(order.get("items"), list)
        or len(order["items"]) != 4
    ):
        raise M9AcceptanceError("Gate A M9 mixed Order shape is invalid")
    expected = {
        option_id: (duration, quantity)
        for option_id, duration, quantity in zip(
            option_ids,
            (60, 60, 120),
            quantities,
            strict=True,
        )
    }
    timer_items: dict[int, tuple[int, int]] = {}
    kit_order_item_id = 0
    observed_options: set[int] = set()
    for item in order["items"]:
        if not isinstance(item, dict):
            raise M9AcceptanceError("Gate A M9 mixed Order item is invalid")
        item_id = _positive_id(item, "id", step)
        option_id = item.get("experience_option_id")
        if option_id is None:
            if (
                item.get("product_id") != kit_id
                or item.get("quantity") != 1
                or item.get("option_duration_minutes") is not None
                or item.get("product_price") != FIXTURE_PRICE
                or item.get("subtotal") != FIXTURE_PRICE
            ):
                raise M9AcceptanceError("Gate A M9 Kit Order item is invalid")
            kit_order_item_id = item_id
            continue
        if type(option_id) is not int or option_id not in expected:
            raise M9AcceptanceError("Gate A M9 Experience Order item is invalid")
        duration, quantity = expected[option_id]
        if (
            item.get("product_id") != experience_id
            or item.get("quantity") != quantity
            or item.get("option_duration_minutes") != duration
            or item.get("product_price") != FIXTURE_PRICE
            or item.get("subtotal") != f"{quantity:.2f}"
        ):
            raise M9AcceptanceError("Gate A M9 Experience snapshot is invalid")
        observed_options.add(option_id)
        timer_items[item_id] = (duration, quantity)
    if observed_options != set(option_ids) or kit_order_item_id <= 0:
        raise M9AcceptanceError("Gate A M9 mixed Order items are incomplete")
    del order_id
    return timer_items, kit_order_item_id


def _build_order_evidence(
    *,
    order_id: int,
    expected_timer_items: Mapping[int, tuple[int, int]],
    kit_order_item_id: int,
    eligible_duration_groups: Sequence[Mapping[str, int]],
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "expected_timer_items": [
            {
                "order_item_id": item_id,
                "duration_minutes": duration,
                "quantity": quantity,
            }
            for item_id, (duration, quantity) in sorted(
                expected_timer_items.items()
            )
        ],
        "kit_order_item_id": kit_order_item_id,
        "eligible_duration_groups": [dict(group) for group in eligible_duration_groups],
    }


def _unpack_order_evidence(
    evidence: Mapping[str, Any],
) -> tuple[dict[int, tuple[int, int]], int, list[dict[str, int]]]:
    timer_items = {
        int(item["order_item_id"]): (
            int(item["duration_minutes"]),
            int(item["quantity"]),
        )
        for item in evidence["expected_timer_items"]
    }
    return (
        timer_items,
        int(evidence["kit_order_item_id"]),
        [dict(group) for group in evidence["eligible_duration_groups"]],
    )


def _verify_eligible_order(
    client: SafeLoopbackClient,
    *,
    user_token: str,
    order_id: int,
) -> list[dict[str, int]]:
    page = _data(
        client.json_request(
            "list-eligible-orders",
            "GET",
            "/api/v1/table-sessions/eligible-orders?page=1&page_size=100",
            token=user_token,
        ),
        "list-eligible-orders",
    )
    items = page.get("items")
    if not isinstance(items, list):
        raise M9AcceptanceError("Gate A M9 eligible Order page is invalid")
    matches = [
        item
        for item in items
        if isinstance(item, dict) and item.get("id") == order_id
    ]
    if len(matches) != 1:
        raise M9AcceptanceError("Gate A M9 mixed Order is not uniquely eligible")
    item = matches[0]
    expected_groups = [
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
    if (
        item.get("total_amount") != FIXTURE_ORDER_TOTAL
        or item.get("experience_item_count") != 3
        or item.get("kit_item_count") != 1
        or item.get("duration_groups") != expected_groups
    ):
        raise M9AcceptanceError("Gate A M9 eligible duration grouping is invalid")
    return expected_groups


def _verify_awaiting_session(
    payload: Mapping[str, Any],
    *,
    order_id: int,
    table_no: str,
) -> tuple[str, int]:
    session_no = payload.get("session_no")
    if (
        not isinstance(session_no, str)
        or TABLE_SESSION_NO_PATTERN.fullmatch(session_no) is None
        or payload.get("order_id") != order_id
        or not isinstance(payload.get("table"), dict)
        or payload["table"].get("table_no") != table_no
        or _enum_value(payload, "status") != "awaiting_payment"
        or payload.get("timers") != []
        or payload.get("started_at") is not None
        or payload.get("table_release_at") is not None
    ):
        raise M9AcceptanceError("Gate A M9 awaiting-payment Session is invalid")
    claimed_at = _parse_datetime(payload.get("claimed_at"), "claim")
    payment_deadline = _parse_datetime(
        payload.get("payment_deadline_at"), "claim"
    )
    expected_window = timedelta(minutes=15)
    if payment_deadline - claimed_at != expected_window:
        raise M9AcceptanceError("Gate A M9 payment window is not 15 minutes")
    return session_no, int(expected_window.total_seconds())


def _verify_active_session(
    payload: Mapping[str, Any],
    *,
    order_id: int,
    table_no: str,
    session_no: str,
    payment_succeeded_at: datetime,
    expected_timer_items: Mapping[int, tuple[int, int]],
    kit_order_item_id: int,
    expected_status: str = "active",
) -> dict[str, Any]:
    timers = payload.get("timers")
    if (
        payload.get("session_no") != session_no
        or payload.get("order_id") != order_id
        or not isinstance(payload.get("table"), dict)
        or payload["table"].get("table_no") != table_no
        or _enum_value(payload, "status") != expected_status
        or not isinstance(timers, list)
        or len(timers) != 2
    ):
        raise M9AcceptanceError("Gate A M9 active Session is invalid")
    session_started = _parse_datetime(payload.get("started_at"), "active-session")
    if session_started != payment_succeeded_at:
        raise M9AcceptanceError("Gate A M9 timer start does not match payment")
    durations: list[int] = []
    buffers: list[int] = []
    item_counts: list[int] = []
    quantities: list[int] = []
    service_offsets: list[int] = []
    grace_offsets: list[int] = []
    observed_order_items: set[int] = set()
    for timer in timers:
        if not isinstance(timer, dict):
            raise M9AcceptanceError("Gate A M9 Timer is invalid")
        duration = timer.get("duration_minutes")
        buffer_minutes = timer.get("buffer_minutes")
        experience_items = timer.get("experience_items")
        if (
            type(duration) is not int
            or duration not in (60, 120)
            or buffer_minutes != 10
            or not isinstance(experience_items, list)
            or not experience_items
            or _parse_datetime(timer.get("started_at"), "timer")
            != session_started
        ):
            raise M9AcceptanceError("Gate A M9 Timer shape is invalid")
        timer_quantity = 0
        for item in experience_items:
            if not isinstance(item, dict):
                raise M9AcceptanceError("Gate A M9 Timer item is invalid")
            order_item_id = item.get("order_item_id")
            if (
                type(order_item_id) is not int
                or order_item_id not in expected_timer_items
                or order_item_id in observed_order_items
                or expected_timer_items[order_item_id]
                != (duration, item.get("quantity"))
            ):
                raise M9AcceptanceError("Gate A M9 Timer item grouping is invalid")
            observed_order_items.add(order_item_id)
            timer_quantity += int(item["quantity"])
        service_ends = _parse_datetime(timer.get("service_ends_at"), "timer")
        grace_ends = _parse_datetime(timer.get("grace_ends_at"), "timer")
        expected_service_offset = timedelta(minutes=duration)
        expected_grace_offset = timedelta(minutes=duration + 10)
        if (
            service_ends - session_started != expected_service_offset
            or grace_ends - session_started != expected_grace_offset
        ):
            raise M9AcceptanceError("Gate A M9 timer semantics are invalid")
        durations.append(duration)
        buffers.append(buffer_minutes)
        item_counts.append(len(experience_items))
        quantities.append(timer_quantity)
        service_offsets.append(int(expected_service_offset.total_seconds()))
        grace_offsets.append(int(expected_grace_offset.total_seconds()))
    release_at = _parse_datetime(payload.get("table_release_at"), "active-session")
    expected_release_offset = timedelta(minutes=130)
    if release_at - session_started != expected_release_offset:
        raise M9AcceptanceError("Gate A M9 timer semantics are invalid")
    release_offset = int(expected_release_offset.total_seconds())
    if (
        durations != [60, 120]
        or buffers != [10, 10]
        or item_counts != [2, 1]
        or quantities != [3, 1]
        or service_offsets != [3600, 7200]
        or grace_offsets != [4200, 7800]
        or release_offset != 7800
        or observed_order_items != set(expected_timer_items)
        or kit_order_item_id in observed_order_items
    ):
        raise M9AcceptanceError("Gate A M9 timer semantics are invalid")
    return {
        "durations": durations,
        "buffers": buffers,
        "item_counts": item_counts,
        "quantities": quantities,
        "service_offsets": service_offsets,
        "grace_offsets": grace_offsets,
        "release_offset": release_offset,
    }


def _admin_session_is_open(payload: Mapping[str, Any]) -> bool:
    return _enum_value(payload, "status") in {"awaiting_payment", "active"}


def _verify_cleanup_session_release(
    context: PreparedContext,
    client: SafeLoopbackClient,
    *,
    admin_token: str,
    session_no: str,
    table_no: str,
) -> None:
    """只在 Session、桌台投影和全局占用对账一致时确认 cleanup 已释放。"""

    detail = _data(
        client.json_request(
            "cleanup-verify-session-closed",
            "GET",
            f"/api/v1/admin/table-sessions/{session_no}",
            token=admin_token,
        ),
        "cleanup-verify-session-closed",
    )
    if (
        detail.get("session_no") != session_no
        or _enum_value(detail, "status") != "closed"
    ):
        raise M9AcceptanceError("Gate A M9 cleanup Session remains open")
    tables = _data(
        client.json_request(
            "cleanup-verify-table-available",
            "GET",
            "/api/v1/admin/tables",
            token=admin_token,
        ),
        "cleanup-verify-table-available",
    )
    matches = [
        item
        for item in tables.get("items", [])
        if isinstance(item, dict) and item.get("table_no") == table_no
    ]
    if (
        len(matches) != 1
        or matches[0].get("state") != "available"
        or matches[0].get("current_session_no") is not None
    ):
        raise M9AcceptanceError("Gate A M9 cleanup table remains occupied")
    reconciled = _run_table_reconcile(context)
    if (
        reconciled.get("open_sessions") != 0
        or reconciled.get("occupancies") != 0
        or reconciled.get("violations") != 0
    ):
        raise M9AcceptanceError("Gate A M9 cleanup reconciliation failed")


def _release_session(
    client: SafeLoopbackClient,
    *,
    admin_token: str,
    session_no: str,
    idempotency_key: str,
    step: str,
) -> dict[str, Any]:
    return _data(
        client.json_request(
            step,
            "POST",
            f"/api/v1/admin/table-sessions/{session_no}/release",
            token=admin_token,
            payload={"reason": "Gate A M9 controlled internal acceptance release"},
            headers={"Idempotency-Key": idempotency_key},
        ),
        step,
    )


def _verify_admin_visibility(
    client: SafeLoopbackClient,
    *,
    admin_token: str,
    order_id: int,
    table_no: str,
    session_no: str,
    payment_id: int,
) -> None:
    tables = _data(
        client.json_request(
            "admin-list-active-tables",
            "GET",
            "/api/v1/admin/tables",
            token=admin_token,
        ),
        "admin-list-active-tables",
    )
    items = tables.get("items")
    if not isinstance(items, list) or len(items) != 30:
        raise M9AcceptanceError("Gate A M9 admin table list is invalid")
    selected = [
        item
        for item in items
        if isinstance(item, dict) and item.get("table_no") == table_no
    ]
    if (
        len(selected) != 1
        or selected[0].get("state") != "active"
        or selected[0].get("current_session_no") != session_no
    ):
        raise M9AcceptanceError("Gate A M9 active table is not admin-visible")
    detail = _data(
        client.json_request(
            "admin-read-active-session",
            "GET",
            f"/api/v1/admin/table-sessions/{session_no}",
            token=admin_token,
        ),
        "admin-read-active-session",
    )
    if (
        detail.get("session_no") != session_no
        or detail.get("order_id") != order_id
        or detail.get("payment_id") != payment_id
        or _enum_value(detail, "status") != "active"
    ):
        raise M9AcceptanceError("Gate A M9 active Session detail is invalid")
    page = _data(
        client.json_request(
            "admin-list-active-session",
            "GET",
            f"/api/v1/admin/table-sessions?order_id={order_id}&page=1&page_size=20",
            token=admin_token,
        ),
        "admin-list-active-session",
    )
    listed = page.get("items")
    if (
        not isinstance(listed, list)
        or len(listed) != 1
        or listed[0].get("session_no") != session_no
        or _enum_value(listed[0], "status") != "active"
        or listed[0].get("timer_count") != 2
    ):
        raise M9AcceptanceError("Gate A M9 active Session list is invalid")


def _verify_released_state(
    client: SafeLoopbackClient,
    *,
    user_token: str,
    admin_token: str,
    order_id: int,
    table_no: str,
    qr_token: str,
    session_no: str,
    first_release: Mapping[str, Any],
    replay_release: Mapping[str, Any],
) -> None:
    for payload in (first_release, replay_release):
        if (
            payload.get("session_no") != session_no
            or payload.get("order_id") != order_id
            or _enum_value(payload, "status") != "closed"
            or _enum_value(payload, "close_reason") != "admin_released"
            or payload.get("closed_at") is None
            or not isinstance(payload.get("timers"), list)
            or len(payload["timers"]) != 2
        ):
            raise M9AcceptanceError("Gate A M9 released Session is invalid")
    if (
        first_release.get("closed_at") != replay_release.get("closed_at")
        or first_release.get("closed_by_user_id")
        != replay_release.get("closed_by_user_id")
        or first_release.get("admin_close_reason")
        != replay_release.get("admin_close_reason")
        or type(first_release.get("closed_by_user_id")) is not int
        or first_release.get("admin_close_reason")
        != "Gate A M9 controlled internal acceptance release"
    ):
        raise M9AcceptanceError("Gate A M9 release replay changed the closure fact")
    current = _optional_data(
        client.json_request(
            "read-no-current-session",
            "GET",
            "/api/v1/table-sessions/current",
            token=user_token,
        ),
        "read-no-current-session",
    )
    if current is not None:
        raise M9AcceptanceError("Gate A M9 released user still has a current Session")
    latest = _data(
        client.json_request(
            "read-released-order-session",
            "GET",
            f"/api/v1/orders/{order_id}/table-session",
            token=user_token,
        ),
        "read-released-order-session",
    )
    if (
        latest.get("session_no") != session_no
        or _enum_value(latest, "status") != "closed"
        or len(latest.get("timers", [])) != 2
    ):
        raise M9AcceptanceError("Gate A M9 released timer history was not retained")
    order = _data(
        client.json_request(
            "read-paid-order-after-release",
            "GET",
            f"/api/v1/orders/{order_id}",
            token=user_token,
        ),
        "read-paid-order-after-release",
    )
    if _labeled_value(order, "status", "read-paid-order-after-release") != "paid":
        raise M9AcceptanceError("Gate A M9 release changed the paid Order")
    tables = _data(
        client.json_request(
            "admin-list-released-tables",
            "GET",
            "/api/v1/admin/tables",
            token=admin_token,
        ),
        "admin-list-released-tables",
    )
    selected = [
        item
        for item in tables.get("items", [])
        if isinstance(item, dict) and item.get("table_no") == table_no
    ]
    if (
        len(selected) != 1
        or selected[0].get("state") != "available"
        or selected[0].get("current_session_no") is not None
    ):
        raise M9AcceptanceError("Gate A M9 table was not released")
    public_table = _data(
        client.json_request(
            "resolve-released-table-code",
            "GET",
            f"/api/v1/table-codes/{qr_token}",
        ),
        "resolve-released-table-code",
    )
    if (
        public_table.get("table_no") != table_no
        or public_table.get("is_available") is not True
        or qr_token in json.dumps(public_table, ensure_ascii=False)
    ):
        raise M9AcceptanceError("Gate A M9 released public table is invalid")


def _ensure_fixture_products_not_online(
    client: SafeLoopbackClient,
    *,
    admin_token: str,
    fixture_ids: Sequence[int],
    require_offline: bool,
) -> None:
    """下架验收商品；失败恢复时 Draft 也属于安全、不可售状态。"""

    if len(fixture_ids) > 2:
        raise M9AcceptanceError("Gate A M9 fixture Product inventory is invalid")
    specifications = (
        ("experience", fixture_ids[0]) if len(fixture_ids) >= 1 else None,
        ("kit", fixture_ids[1]) if len(fixture_ids) >= 2 else None,
    )
    for specification in specifications:
        if specification is None:
            continue
        product_type, product_id = specification
        detail_path = f"/api/v1/admin/products/{product_type}/{product_id}"
        before_step = f"read-{product_type}-before-fixture-offline"
        before = _data(
            client.json_request(
                before_step,
                "GET",
                detail_path,
                token=admin_token,
            ),
            before_step,
        )
        if _positive_id(before, "id", before_step) != product_id:
            raise M9AcceptanceError("Gate A M9 fixture Product identity changed")
        before_status = _enum_value(before, "status")
        if before_status == "online":
            offline_step = f"offline-fixture-{product_type}"
            offline = _data(
                client.json_request(
                    offline_step,
                    "PATCH",
                    f"/api/v1/admin/products/{product_id}/offline",
                    token=admin_token,
                ),
                offline_step,
            )
            if (
                _positive_id(offline, "id", offline_step) != product_id
                or _enum_value(offline, "status") != "offline"
            ):
                raise M9AcceptanceError(
                    "Gate A M9 fixture Product did not become offline"
                )
        elif before_status not in {"draft", "offline"}:
            raise M9AcceptanceError("Gate A M9 fixture Product status is invalid")

        verify_step = f"verify-{product_type}-fixture-not-online"
        verified = _data(
            client.json_request(
                verify_step,
                "GET",
                detail_path,
                token=admin_token,
            ),
            verify_step,
        )
        final_status = _enum_value(verified, "status")
        if (
            _positive_id(verified, "id", verify_step) != product_id
            or final_status == "online"
            or (require_offline and final_status != "offline")
            or (not require_offline and final_status not in {"draft", "offline"})
        ):
            raise M9AcceptanceError(
                "Gate A M9 fixture Product remains saleable after cleanup"
            )


def _payment_evidence(
    payment: Mapping[str, Any],
    *,
    order_id: int,
    step: str,
) -> tuple[dict[str, Any], datetime]:
    if (
        payment.get("order_id") != order_id
        or payment.get("recharge_order_id") is not None
        or payment.get("purpose") != "order"
        or payment.get("amount") != FIXTURE_ORDER_TOTAL
        or payment.get("method") != "wallet"
        or payment.get("status") != "succeeded"
        or not isinstance(payment.get("payment_no"), str)
    ):
        raise M9AcceptanceError(f"Gate A M9 step {step} Payment is invalid")
    payment_id = _positive_id(payment, "id", step)
    succeeded_at = _parse_datetime(payment.get("succeeded_at"), step)
    return (
        {
            "payment_id": payment_id,
            "payment_no_sha256": _sha256_text(str(payment["payment_no"])),
            "succeeded_at": succeeded_at.isoformat(),
        },
        succeeded_at,
    )


def _verify_wallet_payment_result(
    payload: Mapping[str, Any],
    *,
    order_id: int,
    step: str,
) -> tuple[dict[str, Any], datetime]:
    payment = payload.get("payment")
    if (
        payload.get("order_id") != order_id
        or _enum_value(payload, "order_status") != "paid"
        or payload.get("post_payment_balance") != EXPECTED_POST_PAYMENT_BALANCE
        or not isinstance(payment, dict)
    ):
        raise M9AcceptanceError(f"Gate A M9 step {step} payment is invalid")
    return _payment_evidence(payment, order_id=order_id, step=step)


def _read_order_financials(
    client: SafeLoopbackClient,
    *,
    user_token: str,
    order_id: int,
) -> tuple[dict[str, Any] | None, datetime | None]:
    financials = _data(
        client.json_request(
            "read-order-financials",
            "GET",
            f"/api/v1/orders/{order_id}/financials",
            token=user_token,
        ),
        "read-order-financials",
    )
    if financials.get("order_id") != order_id or financials.get("refund") is not None:
        raise M9AcceptanceError("Gate A M9 Order financial facts are invalid")
    payment = financials.get("payment")
    status = _enum_value(financials, "order_status")
    if payment is None:
        if status != "pending":
            raise M9AcceptanceError("Gate A M9 Order financial facts are invalid")
        return None, None
    if not isinstance(payment, dict) or status != "paid":
        raise M9AcceptanceError("Gate A M9 Order financial facts are invalid")
    return _payment_evidence(
        payment,
        order_id=order_id,
        step="read-order-financials",
    )


def _require_fixture_products_online(
    client: SafeLoopbackClient,
    *,
    admin_token: str,
    fixture: Mapping[str, Any],
) -> None:
    for product_type, field in (
        ("experience", "experience_product_id"),
        ("kit", "kit_product_id"),
    ):
        product_id = int(fixture[field])
        step = f"resume-read-{product_type}-fixture"
        product = _data(
            client.json_request(
                step,
                "GET",
                f"/api/v1/admin/products/{product_type}/{product_id}",
                token=admin_token,
            ),
            step,
        )
        if (
            _positive_id(product, "id", step) != product_id
            or _enum_value(product, "status") != "online"
        ):
            raise M9AcceptanceError(
                "Gate A M9 pending fixture cannot safely continue"
            )


def execute(
    context: PreparedContext,
    *,
    admin_username: str,
    admin_password: str,
) -> dict[str, Any]:
    """执行完整 API 闭环；任一断言失败都保留 pending journal 并 fail closed。"""

    if context.staged_success is not None:
        return _publish_staged_success(context)
    if _is_terminal_cleaned_preclaim_failure(context.pending):
        raise M9AcceptanceError(
            "Gate A M9 cleaned acceptance failure requires a forward candidate"
        )
    termination = backup._RecoveryTerminationController("M9 acceptance")
    termination.install()
    try:
        return _execute_active_acceptance(
            context,
            admin_username=admin_username,
            admin_password=admin_password,
            termination=termination,
        )
    finally:
        termination.restore_handlers()


def _execute_active_acceptance(
    context: PreparedContext,
    *,
    admin_username: str,
    admin_password: str,
    termination: backup._RecoveryTerminationController,
) -> dict[str, Any]:
    """在贯穿工作与清理的 stateful 信号控制器下执行一次验收。"""

    admin: dict[str, Any] | None = None
    synthetic: dict[str, Any] | None = None
    synthetic_username = ""
    synthetic_password = ""
    fixture: dict[str, Any] = {}
    fixture_ids: tuple[int, ...] = ()
    order_id: int | None = None
    session_no: str | None = None
    table_no: str | None = None
    qr_token = ""
    payment_id: int | None = None
    payment_deadline_offset: int | None = None
    payment_committed = False
    session_released = False
    admin_logged_out = False
    synthetic_logged_out = False
    admin_session_resolved = True
    synthetic_session_resolved = True
    fixture_products_offline = False
    order_cancelled = False
    pending_created = context.pending is not None or _path_entry_exists(
        context.pending_path
    )
    pending_existed_at_start = pending_created
    pending = _read_pending_file(context)[0] if pending_created else None
    if pending is not None:
        payment_deadline_offset = pending.get("payment_deadline_offset_seconds")
    checkpoint_stage = str(pending["stage"]) if pending is not None else "prepared"
    resume_initial_stage = checkpoint_stage if pending is not None else None
    order_evidence: dict[str, Any] | None = (
        dict(pending["order_evidence"])
        if pending is not None and isinstance(pending.get("order_evidence"), dict)
        else None
    )
    payment_evidence: dict[str, Any] | None = (
        dict(pending["payment_evidence"])
        if pending is not None and isinstance(pending.get("payment_evidence"), dict)
        else None
    )
    timer_evidence: dict[str, Any] | None = (
        dict(pending["timer_evidence"])
        if pending is not None and isinstance(pending.get("timer_evidence"), dict)
        else None
    )
    if pending is not None:
        fixture = (
            dict(pending["fixture"])
            if isinstance(pending.get("fixture"), dict)
            else {}
        )
        fixture_ids = tuple(int(value) for value in pending["fixture_ids"])
        order_id = pending.get("order_id")
        table_no = pending.get("table_no")
        payment_committed = bool(pending["payment_committed"])
        session_released = bool(pending["session_released"])
        fixture_products_offline = bool(
            pending["cleanup"]["fixture_products_offline"]
        )
        order_cancelled = bool(pending["cleanup"]["order_cancelled"])
        if str(pending["stage"]) != "prepared" and (
            pending.get("failure") is not True
            or pending["cleanup"].get("synthetic_session_revoked") is not True
            or pending["cleanup"].get("super_admin_session_revoked") is not True
        ):
            raise M9AcceptanceError(
                "Gate A M9 pending attempt lacks complete session cleanup"
            )
    client = SafeLoopbackClient(
        int(context.values.get("GATEA_LOOPBACK_PORT", "18080"))
    )
    operation_error: BaseException | None = None
    cleanup_errors: list[str] = []
    cleanup_control_error: BaseException | None = None
    success_payload: dict[str, Any] | None = None

    def record_cleanup_error(label: str, error: BaseException) -> None:
        nonlocal cleanup_control_error
        cleanup_errors.append(label)
        if (
            cleanup_control_error is None
            and isinstance(
                error,
                (KeyboardInterrupt, gatea.GateAOperationInterrupted, SystemExit),
            )
        ):
            cleanup_control_error = error

    def advance_pending(stage: str, **kwargs: Any) -> None:
        nonlocal checkpoint_stage
        next_stage = checkpoint_stage
        if PENDING_STAGE_RANK[stage] > PENDING_STAGE_RANK[next_stage]:
            next_stage = stage
        _update_pending(context, stage=next_stage, **kwargs)
        checkpoint_stage = next_stage

    try:
        synthetic_username, synthetic_password = _read_synthetic_user(context)
        if not pending_created:
            _create_pending(context)
            pending_created = True
        # 每一轮认证都先让旧 cleanup 证明失效并落盘。此调用返回后，直到
        # logout+refresh 拒绝完成前，SIGKILL 或结果不明的响应都会留下一个
        # 无法自动续跑的 journal，而不会静默再创建一组 RefreshSession。
        advance_pending(
            "authentication_started",
            reset_session_cleanup_for_authentication=True,
        )
        admin_session_resolved = False
        try:
            admin = _login_with_confirmed_rejection(
                client,
                step="login-super-admin",
                username=admin_username,
                password=admin_password,
                expected_role="super_admin",
                principal="SUPER_ADMIN",
            )
        except _ConfirmedCredentialRejection:
            admin_session_resolved = True
            raise
        advance_pending("admin_authenticated")
        synthetic_session_resolved = False
        try:
            synthetic = _login_with_confirmed_rejection(
                client,
                step="login-orders-and-wallet-user",
                username=synthetic_username,
                password=synthetic_password,
                expected_role="user",
                principal="synthetic user",
            )
        except _ConfirmedCredentialRejection:
            synthetic_session_resolved = True
            raise
        advance_pending("authenticated")
        admin_token = str(admin["access_token"])
        user_token = str(synthetic["access_token"])
        wallet = _data(
            client.json_request(
                "read-pre-payment-wallet",
                "GET",
                "/api/v1/wallet",
                token=user_token,
            ),
            "read-pre-payment-wallet",
        )
        if not isinstance(wallet.get("wallet"), dict) or (
            wallet["wallet"].get("balance")
            not in {EXPECTED_WALLET_BALANCE, EXPECTED_POST_PAYMENT_BALANCE}
            or wallet["wallet"].get("status") != "active"
        ):
            raise M9AcceptanceError("Gate A M9 synthetic wallet baseline is invalid")

        def record_fixture_progress(stage: str, ids: Sequence[int]) -> None:
            nonlocal fixture_ids
            fixture_ids = tuple(ids)
            advance_pending(
                "kit_created" if stage == "kit_online" else stage,
                fixture_ids=fixture_ids,
            )

        if not fixture:
            if fixture_ids:
                raise M9AcceptanceError(
                    "Gate A M9 partial fixture journal requires operator review"
                )
            if resume_initial_stage == "fixture_creation_started":
                raise M9AcceptanceError(
                    "Gate A M9 uncertain fixture creation requires operator review"
                )
            advance_pending("fixture_creation_started")
            fixture = _create_fixture(
                client,
                admin_token=admin_token,
                acceptance_attempt_id=context.attempt_id,
                progress=record_fixture_progress,
            )
            fixture_ids = (
                int(fixture["experience_product_id"]),
                int(fixture["kit_product_id"]),
            )
            advance_pending(
                "kit_online",
                fixture_ids=fixture_ids,
                fixture=fixture,
            )
        elif order_id is None:
            if fixture_products_offline:
                raise M9AcceptanceError(
                    "Gate A M9 cleaned fixture cannot safely continue"
                )
            _require_fixture_products_online(
                client,
                admin_token=admin_token,
                fixture=fixture,
            )

        if order_id is None:
            if resume_initial_stage == "order_creation_started":
                raise M9AcceptanceError(
                    "Gate A M9 uncertain Order creation requires operator review"
                )
            advance_pending(
                "order_creation_started",
                fixture_ids=fixture_ids,
                fixture=fixture,
            )
            order, expected_timer_items, kit_order_item_id = _create_mixed_order(
                client,
                user_token=user_token,
                fixture=fixture,
            )
            order_id = int(order["id"])
            eligible_groups = _verify_eligible_order(
                client,
                user_token=user_token,
                order_id=order_id,
            )
            order_evidence = _build_order_evidence(
                order_id=order_id,
                expected_timer_items=expected_timer_items,
                kit_order_item_id=kit_order_item_id,
                eligible_duration_groups=eligible_groups,
            )
            advance_pending(
                "order_created",
                fixture_ids=fixture_ids,
                fixture=fixture,
                order_evidence=order_evidence,
            )
        else:
            if order_cancelled or order_evidence is None:
                raise M9AcceptanceError(
                    "Gate A M9 cleaned Order cannot safely continue"
                )
            live_order = _data(
                client.json_request(
                    "resume-read-mixed-order",
                    "GET",
                    f"/api/v1/orders/{order_id}",
                    token=user_token,
                ),
                "resume-read-mixed-order",
            )
            expected_timer_items, kit_order_item_id = _parse_mixed_order(
                live_order,
                fixture=fixture,
                step="resume-read-mixed-order",
            )
            _, _, eligible_groups = _unpack_order_evidence(order_evidence)
            live_order_evidence = _build_order_evidence(
                order_id=order_id,
                expected_timer_items=expected_timer_items,
                kit_order_item_id=kit_order_item_id,
                eligible_duration_groups=eligible_groups,
            )
            if live_order_evidence != order_evidence:
                raise M9AcceptanceError(
                    "Gate A M9 live Order does not match pending evidence"
                )
        if order_id is None:
            raise M9AcceptanceError("Gate A M9 Order identity is unavailable")
        table_no, qr_token = _read_table_secret(context)
        claim_payload = {"qr_token": qr_token, "order_id": order_id}
        claim_headers = {
            "Idempotency-Key": f"gatea-m9-claim-{context.attempt_id}-v1"
        }
        existing_session = _optional_data(
            client.json_request(
                "resume-read-order-session",
                "GET",
                f"/api/v1/orders/{order_id}/table-session",
                token=user_token,
            ),
            "resume-read-order-session",
        )
        if existing_session is None:
            resolved = _data(
                client.json_request(
                    "resolve-available-table-code",
                    "GET",
                    f"/api/v1/table-codes/{qr_token}",
                ),
                "resolve-available-table-code",
            )
            if (
                resolved.get("table_no") != table_no
                or resolved.get("is_enabled") is not True
                or resolved.get("is_available") is not True
                or qr_token in json.dumps(resolved, ensure_ascii=False)
            ):
                raise M9AcceptanceError(
                    "Gate A M9 public table code projection is invalid"
                )
            eligible_groups = _verify_eligible_order(
                client,
                user_token=user_token,
                order_id=order_id,
            )
            advance_pending(
                "claim_started",
                fixture_ids=fixture_ids,
                fixture=fixture,
                order_evidence=order_evidence,
            )
            claimed = _data(
                client.json_request(
                    "claim-table",
                    "POST",
                    "/api/v1/table-sessions",
                    token=user_token,
                    payload=claim_payload,
                    headers=claim_headers,
                    expected_status=201,
                ),
                "claim-table",
            )
            session_no, payment_deadline_offset = _verify_awaiting_session(
                claimed,
                order_id=order_id,
                table_no=table_no,
            )
        else:
            session_no = existing_session.get("session_no")
            if (
                not isinstance(session_no, str)
                or TABLE_SESSION_NO_PATTERN.fullmatch(session_no) is None
                or existing_session.get("order_id") != order_id
                or not isinstance(existing_session.get("table"), dict)
                or existing_session["table"].get("table_no") != table_no
            ):
                raise M9AcceptanceError(
                    "Gate A M9 live Session does not match pending evidence"
                )
            if (
                pending is not None
                and pending.get("session_no_sha256") is not None
                and pending["session_no_sha256"] != _sha256_text(session_no)
            ):
                raise M9AcceptanceError(
                    "Gate A M9 live Session does not match pending evidence"
                )
            claimed_at = _parse_datetime(
                existing_session.get("claimed_at"), "resume-session"
            )
            deadline = _parse_datetime(
                existing_session.get("payment_deadline_at"), "resume-session"
            )
            if deadline - claimed_at != timedelta(minutes=15):
                raise M9AcceptanceError(
                    "Gate A M9 resumed payment window is not 15 minutes"
                )
            payment_deadline_offset = 900
        replayed_claim = _data(
            client.json_request(
                "replay-table-claim",
                "POST",
                "/api/v1/table-sessions",
                token=user_token,
                payload=claim_payload,
                headers=claim_headers,
                expected_status=200,
            ),
            "replay-table-claim",
        )
        replayed_session_no = replayed_claim.get("session_no")
        if (
            replayed_session_no != session_no
            or replayed_claim.get("order_id") != order_id
            or not isinstance(replayed_claim.get("table"), dict)
            or replayed_claim["table"].get("table_no") != table_no
        ):
            raise M9AcceptanceError("Gate A M9 claim replay changed the Session")
        if _enum_value(replayed_claim, "status") == "awaiting_payment":
            _, replayed_offset = _verify_awaiting_session(
                replayed_claim,
                order_id=order_id,
                table_no=table_no,
            )
            if replayed_offset != payment_deadline_offset:
                raise M9AcceptanceError("Gate A M9 claim replay changed the Session")
        elif _enum_value(replayed_claim, "status") not in {"active", "closed"}:
            raise M9AcceptanceError("Gate A M9 claim replay changed the Session")
        advance_pending(
            "claimed",
            fixture_ids=fixture_ids,
            fixture=fixture,
            order_evidence=order_evidence,
            table_no=table_no,
            session_no=session_no,
            payment_deadline_offset_seconds=payment_deadline_offset,
            claim_replay_verified=True,
        )

        payment_headers = {
            "Idempotency-Key": f"gatea-m9-wallet-{context.attempt_id}-v1",
            "Table-Session-No": session_no,
        }
        live_payment_evidence, payment_succeeded_at = _read_order_financials(
            client,
            user_token=user_token,
            order_id=order_id,
        )
        pre_payment_balance = wallet["wallet"].get("balance")
        if live_payment_evidence is None:
            if (
                pre_payment_balance != EXPECTED_WALLET_BALANCE
                or _enum_value(existing_session or claimed, "status")
                != "awaiting_payment"
            ):
                raise M9AcceptanceError(
                    "Gate A M9 pending payment baseline is invalid"
                )
            advance_pending(
                "payment_started",
                table_no=table_no,
                session_no=session_no,
                payment_deadline_offset_seconds=payment_deadline_offset,
                claim_replay_verified=True,
            )
            paid = _data(
                client.json_request(
                    "pay-mixed-order-with-wallet",
                    "POST",
                    f"/api/v1/orders/{order_id}/payments/wallet",
                    token=user_token,
                    headers=payment_headers,
                    expected_status=201,
                ),
                "pay-mixed-order-with-wallet",
            )
            # 收到 201/code=0 时资金事务已经提交；后续投影断言失败也不得尝试取消。
            payment_committed = True
            live_payment_evidence, payment_succeeded_at = (
                _verify_wallet_payment_result(
                    paid,
                    order_id=order_id,
                    step="pay-mixed-order-with-wallet",
                )
            )
        elif pre_payment_balance != EXPECTED_POST_PAYMENT_BALANCE:
            raise M9AcceptanceError("Gate A M9 resumed wallet balance is invalid")
        payment_committed = True
        if (
            payment_evidence is not None
            and live_payment_evidence != payment_evidence
        ):
            raise M9AcceptanceError(
                "Gate A M9 live Payment does not match pending evidence"
            )
        if live_payment_evidence is None or payment_succeeded_at is None:
            raise M9AcceptanceError("Gate A M9 Payment evidence is unavailable")
        payment_evidence = live_payment_evidence
        payment_id = int(payment_evidence["payment_id"])
        replayed_paid = _data(
            client.json_request(
                "replay-wallet-payment",
                "POST",
                f"/api/v1/orders/{order_id}/payments/wallet",
                token=user_token,
                headers=payment_headers,
                expected_status=200,
            ),
            "replay-wallet-payment",
        )
        replay_evidence, replay_succeeded_at = _verify_wallet_payment_result(
            replayed_paid,
            order_id=order_id,
            step="replay-wallet-payment",
        )
        if (
            replay_evidence != payment_evidence
            or replay_succeeded_at != payment_succeeded_at
        ):
            raise M9AcceptanceError("Gate A M9 wallet payment replay is invalid")
        advance_pending(
            "paid",
            fixture_ids=fixture_ids,
            fixture=fixture,
            order_evidence=order_evidence,
            table_no=table_no,
            session_no=session_no,
            payment_deadline_offset_seconds=payment_deadline_offset,
            payment_evidence=payment_evidence,
            payment_committed=True,
            claim_replay_verified=True,
            payment_replay_verified=True,
        )
        current = _data(
            client.json_request(
                "read-active-current-session",
                "GET",
                f"/api/v1/orders/{order_id}/table-session",
                token=user_token,
            ),
            "read-active-current-session",
        )
        current_status = _enum_value(current, "status")
        if current_status not in {"active", "closed"}:
            raise M9AcceptanceError(
                "Gate A M9 paid Session did not activate"
            )
        timer_evidence = _verify_active_session(
            current,
            order_id=order_id,
            table_no=table_no,
            session_no=session_no,
            payment_succeeded_at=payment_succeeded_at,
            expected_timer_items=expected_timer_items,
            kit_order_item_id=kit_order_item_id,
            expected_status=str(current_status),
        )
        if (
            pending is not None
            and pending.get("timer_evidence") is not None
            and pending["timer_evidence"] != timer_evidence
        ):
            raise M9AcceptanceError(
                "Gate A M9 live Timer does not match pending evidence"
            )
        if current_status == "active":
            _verify_admin_visibility(
                client,
                admin_token=admin_token,
                order_id=order_id,
                table_no=table_no,
                session_no=session_no,
                payment_id=payment_id,
            )
            advance_pending(
                "paid",
                timer_evidence=timer_evidence,
                admin_visibility_verified=True,
            )
        elif pending is None or pending.get("admin_visibility_verified") is not True:
            raise M9AcceptanceError(
                "Gate A M9 closed Session lacks prior admin visibility evidence"
            )
        release_key = f"gatea-m9-release-{context.attempt_id}-v1"
        advance_pending(
            "release_started",
            timer_evidence=timer_evidence,
            admin_visibility_verified=True,
        )
        released = _release_session(
            client,
            admin_token=admin_token,
            session_no=session_no,
            idempotency_key=release_key,
            step="admin-release-session",
        )
        replayed_release = _release_session(
            client,
            admin_token=admin_token,
            session_no=session_no,
            idempotency_key=release_key,
            step="replay-admin-release",
        )
        _verify_released_state(
            client,
            user_token=user_token,
            admin_token=admin_token,
            order_id=order_id,
            table_no=table_no,
            qr_token=qr_token,
            session_no=session_no,
            first_release=released,
            replay_release=replayed_release,
        )
        session_released = True
        advance_pending(
            "released",
            fixture_ids=fixture_ids,
            fixture=fixture,
            order_evidence=order_evidence,
            table_no=table_no,
            session_no=session_no,
            payment_deadline_offset_seconds=payment_deadline_offset,
            payment_evidence=payment_evidence,
            timer_evidence=timer_evidence,
            payment_committed=True,
            session_released=True,
            claim_replay_verified=True,
            payment_replay_verified=True,
            admin_visibility_verified=True,
            release_replay_verified=True,
        )
        table_sweep = _run_table_sweep(context)
        post_reconcile = _run_table_reconcile(context)
        if (
            post_reconcile.get("open_sessions") != 0
            or post_reconcile.get("occupancies") != 0
            or post_reconcile.get("scanned") != 1
            or post_reconcile.get("violations") != 0
        ):
            raise M9AcceptanceError("Gate A M9 post-release reconciliation is invalid")
        post_wallet_reconcile = _run_wallet_reconcile(context)
        post_wallet = _data(
            client.json_request(
                "read-post-payment-wallet",
                "GET",
                "/api/v1/wallet",
                token=user_token,
            ),
            "read-post-payment-wallet",
        )
        if (
            not isinstance(post_wallet.get("wallet"), dict)
            or post_wallet["wallet"].get("balance")
            != EXPECTED_POST_PAYMENT_BALANCE
        ):
            raise M9AcceptanceError("Gate A M9 post-payment wallet is invalid")
        _ensure_fixture_products_not_online(
            client,
            admin_token=admin_token,
            fixture_ids=fixture_ids,
            require_offline=True,
        )
        fixture_products_offline = True
        advance_pending(
            "fixtures_offline",
            fixture_ids=fixture_ids,
            fixture=fixture,
            order_evidence=order_evidence,
            table_no=table_no,
            session_no=session_no,
            payment_deadline_offset_seconds=payment_deadline_offset,
            payment_evidence=payment_evidence,
            timer_evidence=timer_evidence,
            payment_committed=True,
            session_released=True,
            claim_replay_verified=True,
            payment_replay_verified=True,
            admin_visibility_verified=True,
            release_replay_verified=True,
            cleanup_updates={"fixture_products_offline": True},
        )
        base_data._logout_and_verify(
            client,
            step_prefix="orders-and-wallet-user",
            access_token=str(synthetic["access_token"]),
            refresh_token=str(synthetic["refresh_token"]),
        )
        synthetic_logged_out = True
        synthetic_session_resolved = True
        base_data._logout_and_verify(
            client,
            step_prefix="super-admin",
            access_token=str(admin["access_token"]),
            refresh_token=str(admin["refresh_token"]),
        )
        admin_logged_out = True
        admin_session_resolved = True
        log_redaction = _verify_log_redaction(
            context,
            transient_secrets=(
                admin_username,
                admin_password,
                synthetic_username,
                synthetic_password,
                context.attempt_id,
                str(admin["access_token"]),
                str(admin["refresh_token"]),
                str(synthetic["access_token"]),
                str(synthetic["refresh_token"]),
                qr_token,
            ),
        )
        _ensure_m9_services(context)
        scenario = {
            "order_id": order_id,
            "payment_id": payment_id,
            "payment_no_sha256": payment_evidence["payment_no_sha256"],
            "payment_succeeded_at": payment_evidence["succeeded_at"],
            "table_no": table_no,
            "session_no_sha256": _sha256_text(session_no),
            "order_total": FIXTURE_ORDER_TOTAL,
            "experience_item_count": 3,
            "kit_item_count": 1,
            "eligible_duration_groups": eligible_groups,
            "claim_statuses": [201, 200],
            "claim_replay_same_session": True,
            "payment_deadline_offset_seconds": payment_deadline_offset,
            "awaiting_timer_count": 0,
            "payment_statuses": [201, 200],
            "payment_replay_same_payment": True,
            "post_payment_balance": EXPECTED_POST_PAYMENT_BALANCE,
            "active_timer_durations_minutes": timer_evidence["durations"],
            "active_timer_buffer_minutes": timer_evidence["buffers"],
            "active_timer_experience_item_counts": timer_evidence["item_counts"],
            "active_timer_total_quantities": timer_evidence["quantities"],
            "timer_started_at_matches_payment": True,
            "timer_service_offsets_seconds": timer_evidence["service_offsets"],
            "timer_grace_offsets_seconds": timer_evidence["grace_offsets"],
            "table_release_offset_seconds": timer_evidence["release_offset"],
            "same_duration_items_merged": True,
            "different_durations_separated": True,
            "quantity_did_not_multiply_duration": True,
            "kit_excluded_from_timers": True,
            "admin_visible_while_active": True,
            "release_statuses": [200, 200],
            "release_replay_same_fact": True,
            "final_session_status": "closed",
            "final_close_reason": "admin_released",
            "final_order_status": "paid",
            "table_available_after_release": True,
        }
        cleanup = {
            "active_session_released": session_released,
            "synthetic_session_revoked": synthetic_logged_out,
            "synthetic_refresh_rejected": synthetic_logged_out,
            "super_admin_session_revoked": admin_logged_out,
            "super_admin_refresh_rejected": admin_logged_out,
            "open_sessions_after": post_reconcile["open_sessions"],
            "occupancies_after": post_reconcile["occupancies"],
            "fixture_products_offline": fixture_products_offline,
            "pending_record_retained": False,
        }
        success_payload = {
            "schema_version": 1,
            "record_type": "gatea-m9-runtime-acceptance",
            "environment": "gatea",
            "candidate_sha": context.candidate_sha,
            "image_id": context.image_id,
            "operations_sha": context.operations_sha,
            "ci_run_id": context.ci_run_id,
            "ci_job_name": CI_JOB_NAME,
            "upgrade_record_sha256": context.upgrade_record_sha256,
            "upgrade_plan_replay_record_sha256": (
                context.upgrade_plan_replay_record_sha256
            ),
            "representative_record_sha256": context.representative_record_sha256,
            "credentials_sha256": context.credentials_sha256,
            "source_candidate_sha": context.source_candidate_sha,
            "attempt_id_sha256": _sha256_text(context.attempt_id),
            "started_at": context.started_at,
            "completed_at": _utc_now(),
            "fixture": fixture,
            "scenario": scenario,
            "pre_reconcile": dict(context.pre_reconcile),
            "post_reconcile": post_reconcile,
            "pre_wallet_reconcile": dict(context.pre_wallet_reconcile),
            "post_wallet_reconcile": post_wallet_reconcile,
            "request_count": len(client.results),
            "cleanup": cleanup,
            "runtime_services": list(M9_SERVICES),
            "upgrade_plan_replayed": True,
            "wallet_reconcile_passed": True,
            "table_reconcile_passed": True,
            "table_sweep_passed": True,
            "log_redaction_passed": True,
            "pii_recorded": False,
            "secret_values_recorded": False,
            "table_tokens_recorded": False,
            "super_admin_credentials_recorded": False,
            "synthetic_credentials_recorded": False,
            "token_values_recorded": False,
            "qr_token_values_recorded": False,
            "request_or_response_bodies_recorded": False,
            "raw_dynamic_paths_recorded": False,
            "loopback_only": True,
            "source_volume_restored": False,
            "table_sweep": table_sweep,
            "log_redaction": log_redaction,
            "passed": True,
        }
        _stage_success_record_exclusive(
            context,
            success_payload,
            secret_values=(
                admin_username,
                admin_password,
                synthetic_username,
                synthetic_password,
                context.attempt_id,
                qr_token,
                session_no,
                str(admin["access_token"]),
                str(admin["refresh_token"]),
                str(synthetic["access_token"]),
                str(synthetic["refresh_token"]),
            ),
        )
        advance_pending(
            "verified",
            fixture_ids=fixture_ids,
            fixture=fixture,
            order_evidence=order_evidence,
            table_no=table_no,
            session_no=session_no,
            payment_deadline_offset_seconds=payment_deadline_offset,
            payment_evidence=payment_evidence,
            timer_evidence=timer_evidence,
            payment_committed=True,
            session_released=True,
            claim_replay_verified=True,
            payment_replay_verified=True,
            admin_visibility_verified=True,
            release_replay_verified=True,
            cleanup_updates={
                "fixture_products_offline": True,
                "synthetic_session_revoked": True,
                "super_admin_session_revoked": True,
            },
            failure=False,
        )
    except BaseException as error:
        operation_error = error
        termination.begin_recovery()
    else:
        # 正常路径也在离开 work block 前切换，消除 finally 入口的信号窗口。
        termination.begin_recovery()
    finally:
        # work signal handler 会在抛出前切换；普通成功/异常由上面的
        # else/except 切换。清理阶段首个 HUP/TERM 因而只会延迟记账。
        termination.begin_recovery()
        if order_id is not None and not payment_committed and synthetic is not None:
            try:
                cancelled = _data(
                    client.json_request(
                        "cleanup-cancel-pending-order",
                        "PATCH",
                        f"/api/v1/orders/{order_id}/cancel",
                        token=str(synthetic["access_token"]),
                    ),
                    "cleanup-cancel-pending-order",
                )
                if _enum_value(cancelled, "status") != "cancelled":
                    raise M9AcceptanceError("cleanup cancellation did not complete")
                order_cancelled = True
                if (
                    session_no is not None
                    and table_no is not None
                    and admin is not None
                ):
                    _verify_cleanup_session_release(
                        context,
                        client,
                        admin_token=str(admin["access_token"]),
                        session_no=session_no,
                        table_no=table_no,
                    )
                    session_released = True
            except BaseException as error:
                record_cleanup_error("pending-order", error)
        if session_no is not None and not session_released and admin is not None:
            try:
                detail = _data(
                    client.json_request(
                        "cleanup-read-session",
                        "GET",
                        f"/api/v1/admin/table-sessions/{session_no}",
                        token=str(admin["access_token"]),
                    ),
                    "cleanup-read-session",
                )
                if _admin_session_is_open(detail):
                    _release_session(
                        client,
                        admin_token=str(admin["access_token"]),
                        session_no=session_no,
                        idempotency_key=(
                            f"gatea-m9-release-{context.attempt_id}-v1"
                        ),
                        step="cleanup-release-session",
                    )
                if table_no is None:
                    raise M9AcceptanceError(
                        "Gate A M9 cleanup table identity is unavailable"
                    )
                _verify_cleanup_session_release(
                    context,
                    client,
                    admin_token=str(admin["access_token"]),
                    session_no=session_no,
                    table_no=table_no,
                )
                session_released = True
            except BaseException as error:
                record_cleanup_error("table-session", error)
        if fixture_ids and not fixture_products_offline and admin is not None:
            try:
                _ensure_fixture_products_not_online(
                    client,
                    admin_token=str(admin["access_token"]),
                    fixture_ids=fixture_ids,
                    require_offline=False,
                )
                fixture_products_offline = True
            except BaseException as error:
                record_cleanup_error("fixture-products", error)
        if synthetic is not None and not synthetic_logged_out:
            try:
                base_data._logout_and_verify(
                    client,
                    step_prefix="cleanup-orders-and-wallet-user",
                    access_token=str(synthetic["access_token"]),
                    refresh_token=str(synthetic["refresh_token"]),
                )
                synthetic_logged_out = True
                synthetic_session_resolved = True
            except BaseException as error:
                record_cleanup_error("synthetic-session", error)
        if admin is not None and not admin_logged_out:
            try:
                base_data._logout_and_verify(
                    client,
                    step_prefix="cleanup-super-admin",
                    access_token=str(admin["access_token"]),
                    refresh_token=str(admin["refresh_token"]),
                )
                admin_logged_out = True
                admin_session_resolved = True
            except BaseException as error:
                record_cleanup_error("super-admin-session", error)

    admin_password = ""
    synthetic_password = ""
    # 关闭本地 handler 后再决定返回/传播，避免最后一次 deferred 检查之后
    # 又接收一个被静默吞掉的终止信号；外围 operation guard 随即重新生效。
    termination.restore_handlers()
    if (
        isinstance(operation_error, _ConfirmedCredentialRejection)
        and operation_error.principal == "SUPER_ADMIN"
        and not pending_existed_at_start
        and admin is None
        and synthetic is None
        and admin_session_resolved
        and synthetic_session_resolved
        and not cleanup_errors
    ):
        try:
            _discard_fresh_pending_after_admin_rejection(context)
            pending_created = False
        except BaseException as error:
            record_cleanup_error("pending-journal", error)
        else:
            if (
                termination.work_interruption is None
                and not termination.deferred_interruptions
            ):
                raise M9AcceptanceError(str(operation_error)) from operation_error
    if (
        operation_error is not None
        or cleanup_errors
        or termination.work_interruption is not None
        or termination.deferred_interruptions
        or success_payload is None
    ):
        if cleanup_errors and not pending_created:
            try:
                _create_pending(context)
                pending_created = True
            except BaseException as error:
                record_cleanup_error("pending-journal", error)
        if pending_created:
            try:
                failure_updates: dict[str, Any] = {
                    "fixture_ids": fixture_ids,
                    "payment_committed": payment_committed,
                    "session_released": session_released,
                    "cleanup_updates": {
                        "order_cancelled": order_cancelled,
                        "fixture_products_offline": fixture_products_offline,
                        "synthetic_session_revoked": synthetic_session_resolved,
                        "super_admin_session_revoked": admin_session_resolved,
                    },
                    "failure": True,
                }
                if fixture:
                    failure_updates["fixture"] = fixture
                if order_evidence is not None:
                    failure_updates["order_evidence"] = order_evidence
                if session_no is not None and (
                    pending is None or pending.get("session_no_sha256") is None
                ):
                    failure_updates.update(
                        {
                            "table_no": table_no,
                            "session_no": session_no,
                            "payment_deadline_offset_seconds": (
                                payment_deadline_offset
                            ),
                        }
                    )
                if payment_evidence is not None:
                    failure_updates["payment_evidence"] = payment_evidence
                if timer_evidence is not None:
                    failure_updates["timer_evidence"] = timer_evidence
                _update_pending(
                    context,
                    stage=checkpoint_stage,
                    **failure_updates,
                )
            except BaseException as error:
                record_cleanup_error("pending-journal", error)
        interruption_types = (
            KeyboardInterrupt,
            gatea.GateAOperationInterrupted,
            SystemExit,
        )
        # 工作阶段先发生的控制异常必须保留原对象；普通工作错误之后发生的
        # cleanup 控制异常或 deferred HUP/TERM 则优先传播。
        if isinstance(operation_error, interruption_types):
            raise operation_error
        if termination.work_interruption is not None:
            raise termination.work_interruption
        if cleanup_control_error is not None:
            raise cleanup_control_error
        if termination.deferred_interruptions:
            raise termination.deferred_interruptions[0]
        if cleanup_errors:
            raise M9AcceptanceError(
                "Gate A M9 acceptance failed and cleanup is incomplete: "
                + ",".join(sorted(set(cleanup_errors)))
            ) from operation_error
        if isinstance(operation_error, M9AcceptanceError):
            raise operation_error
        if isinstance(operation_error, base_data.RepresentativeDataError):
            raise M9AcceptanceError(str(operation_error)) from operation_error
        raise M9AcceptanceError(
            "Gate A M9 acceptance failed safely"
        ) from operation_error
    return _publish_staged_success(
        replace(
            context,
            staged_success=success_payload,
        )
    )


def _plan_payload(context: PreparedContext) -> dict[str, Any]:
    terminal_cleaned_failure = _is_terminal_cleaned_preclaim_failure(
        context.pending
    )
    return {
        "schema_version": 1,
        "record_type": "gatea-m9-runtime-acceptance-plan",
        "candidate_sha": context.candidate_sha,
        "image_id": context.image_id,
        "source_candidate_sha": context.source_candidate_sha,
        "runtime_services": list(M9_SERVICES),
        "pre_reconcile": dict(context.pre_reconcile),
        "pre_wallet_reconcile": dict(context.pre_wallet_reconcile),
        "upgrade_plan_replayed": True,
        "writes_performed": False,
        "admin_credentials_requested": False,
        "source_volume_restored": False,
        "resume_pending": context.pending is not None,
        "resume_stage": (
            context.pending.get("stage") if context.pending is not None else None
        ),
        "staged_success_recovery": context.staged_success is not None,
        "disposition": (
            "terminal_failure_requires_forward_candidate"
            if terminal_cleaned_failure
            else "ready"
        ),
        "ready_for_admin_assisted_acceptance": (
            context.staged_success is None and not terminal_cleaned_failure
        ),
    }


def _is_terminal_cleaned_preclaim_failure(
    pending: Mapping[str, Any] | None,
) -> bool:
    """识别只能保留证据并由新候选接管的未付款、未开台失败终态。"""

    if pending is None:
        return False
    fixture = pending.get("fixture")
    order_evidence = pending.get("order_evidence")
    cleanup = pending.get("cleanup")
    pre_reconcile = pending.get("pre_reconcile")
    pre_wallet = pending.get("pre_wallet_reconcile")
    return bool(
        pending.get("schema_version") == 3
        and pending.get("record_type")
        == "gatea-m9-internal-acceptance-pending"
        and pending.get("stage") == "order_created"
        and pending.get("failure") is True
        and isinstance(fixture, dict)
        and isinstance(order_evidence, dict)
        and isinstance(pending.get("fixture_ids"), list)
        and len(pending["fixture_ids"]) == 2
        and pending.get("order_id") is not None
        and pending.get("table_no") is None
        and pending.get("session_no_sha256") is None
        and pending.get("payment_deadline_offset_seconds") is None
        and pending.get("payment_evidence") is None
        and pending.get("timer_evidence") is None
        and pending.get("claim_replay_verified") is False
        and pending.get("payment_replay_verified") is False
        and pending.get("admin_visibility_verified") is False
        and pending.get("release_replay_verified") is False
        and pending.get("payment_committed") is False
        and pending.get("session_released") is False
        and isinstance(cleanup, dict)
        and set(cleanup) == PENDING_CLEANUP_KEYS
        and all(cleanup.get(key) is True for key in PENDING_CLEANUP_KEYS)
        and isinstance(pre_reconcile, dict)
        and set(pre_reconcile) == RECONCILE_KEYS
        and all(value == 0 for value in pre_reconcile.values())
        and isinstance(pre_wallet, dict)
        and set(pre_wallet) == WALLET_RECONCILE_KEYS
        and type(pre_wallet.get("scanned")) is int
        and pre_wallet["scanned"] > 0
        and pre_wallet.get("mismatches") == 0
        and pre_wallet.get("violations") == 0
    )


def _parser() -> argparse.ArgumentParser:
    parser = SecureArgumentParser(description=__doc__)
    parser.add_argument("--apply-admin-assisted", action="store_true")
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
    parser.add_argument(
        "--release-record-dir",
        type=Path,
        default=gatea.DEFAULT_RECORD_DIR,
    )
    parser.add_argument("--record-dir", type=Path, default=DEFAULT_RECORD_DIR)
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=DEFAULT_CREDENTIALS_FILE,
    )
    parser.add_argument("--representative-record", type=Path)
    parser.add_argument("--upgrade-plan-replay-record", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    admin_username = ""
    admin_password = ""
    try:
        with gatea.operation_lock(), gatea.operation_termination_guard():
            context = prepare(
                config_file=arguments.config_file,
                secret_dir=arguments.secret_dir,
                release_record_dir=arguments.release_record_dir,
                record_dir=arguments.record_dir,
                credentials_file=arguments.credentials_file,
                representative_record=arguments.representative_record,
                upgrade_plan_replay_record=arguments.upgrade_plan_replay_record,
            )
            if not arguments.apply_admin_assisted:
                print(
                    json.dumps(
                        _plan_payload(context),
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return 0
            # A fully-cleaned pre-claim failure is an immutable predecessor
            # checkpoint.  Refuse it before touching /dev/tty so the retired
            # candidate cannot solicit or load administrator credentials.
            if _is_terminal_cleaned_preclaim_failure(context.pending):
                raise M9AcceptanceError(
                    "Gate A M9 cleaned acceptance failure requires a forward candidate"
                )
            if context.staged_success is None:
                admin_username, admin_password = _read_admin_identity_from_tty()
            record = execute(
                context,
                admin_username=admin_username,
                admin_password=admin_password,
            )
        print(
            json.dumps(
                {
                    "candidate_sha": record["candidate_sha"],
                    "record_path": str(context.record_path),
                    "record_sha256": _sha256(context.record_path),
                    "passed": True,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    except (M9AcceptanceError, gatea.GateAError, upgrade.GateAUpgradeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        admin_username = ""
        admin_password = ""


if __name__ == "__main__":
    raise SystemExit(main())
