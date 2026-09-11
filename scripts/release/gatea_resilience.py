#!/usr/bin/env python3
"""执行 Gate A 持久依赖故障、应用重启与日志可观测性演练。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import signal
import statistics
import stat
import subprocess
import sys
import time
from typing import Any, Iterator, Mapping, Sequence

from scripts.release import gatea_backup
from scripts.release import gatea_operations as gatea


DEFAULT_REPRESENTATIVE_RECORD = Path(
    "/srv/pinkdoohub/gatea/records/representative-data/"
    "gatea-representative-data.json"
)
DEFAULT_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/resilience")
RECORD_PREFIX = "gatea-resilience"
LEGACY_SERVICES = ("mysql", "redis", "app", "nginx")
M9_SERVICES = ("mysql", "redis", "app", "table-sweeper", "nginx")
M9_RUNTIME_ACCEPTANCE_PREFIX = "gatea-m9-runtime-acceptance"
RESILIENCE_RECORD_BASE_KEYS = frozenset(
    {
        "schema_version",
        "candidate_sha",
        "image_id",
        "representative_candidate_sha",
        "representative_image_id",
        "representative_record_sha256",
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
RESILIENCE_RECORD_V2_KEYS = RESILIENCE_RECORD_BASE_KEYS | frozenset(
    {
        "runtime_acceptance_record_sha256",
        "runtime_acceptance_attempt_id_sha256",
        "runtime_acceptance_completed_at",
    }
)
DEPENDENCY_DRILL_KEYS = frozenset(
    {
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
)
APP_RESTART_KEYS = frozenset(
    {
        "started_at",
        "completed_at",
        "total_seconds",
        "service_recovery_seconds",
        "readiness_recovery_seconds",
        "readiness_status",
        "passed",
    }
)
LOG_OBSERVABILITY_KEYS = frozenset(
    {
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
)
REQUEST_TIME_KEYS = frozenset({"median", "p95", "max"})
# 保留旧名称，避免下游只读工具在升级期间失去 M2/M7/M8 兼容语义。
SERVICES = LEGACY_SERVICES
FORBIDDEN_LOG_PATTERNS = (
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"(?:access|refresh)_token[\"'=:\s]+[A-Za-z0-9_.-]{12,}", re.IGNORECASE),
    re.compile(
        r"qr_token[\"'=:\s]+[A-Za-z0-9]{32}(?![A-Za-z0-9])",
        re.IGNORECASE,
    ),
    re.compile(r"/api/v1/table-codes/[A-Za-z0-9]{32}(?![A-Za-z0-9])"),
    re.compile(r"PINKDOOHUB_TABLE:v1:[A-Za-z0-9]{32}(?![A-Za-z0-9])"),
    re.compile(r"(?:redis|rediss|mysql(?:\+\w+)?)://[^\s/@]+:[^\s/@]+@", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
NGINX_METRIC_PATTERN = re.compile(
    r'"[A-Z]+ [^\"]+ HTTP/[^\"]+"\s+(?P<status>\d{3})\s+\d+\s+'
    r"request_time=(?P<duration>\d+(?:\.\d+)?)"
)
M7_REPRESENTATIVE_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "record_type",
        "candidate_sha",
        "image_id",
        "operations_sha",
        "backup_id",
        "started_at",
        "completed_at",
        "before_snapshot",
        "after_snapshot",
        "representative_details",
        "synthetic_user_ids",
        "color_product_id",
        "color_ids",
        "order_ids",
        "reservation_ids",
        "before_image_file_count",
        "after_image_file_count",
        "request_count",
        "synthetic_sessions_revoked",
        "super_admin_session_revoked",
        "credentials_file",
        "credentials_file_mode",
        "credentials_sha256",
        "super_admin_credentials_recorded",
        "request_or_response_bodies_recorded",
        "loopback_only",
        "passed",
    }
)


class ResilienceError(RuntimeError):
    """不包含日志正文、Secret、连接串或用户身份的安全演练错误。"""


@dataclass(frozen=True, slots=True)
class _RuntimeAcceptanceEvidence:
    """演练窗口两端必须保持完全相同的 M9 验收证据。"""

    path: Path
    record_sha256: str
    attempt_id_sha256: str
    completed_at: str
    payload: Mapping[str, Any]
    file_identity: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _ExistingResilienceRecord:
    """已发布 Record 及可能残留的同 inode 临时别名。"""

    path: Path
    payload: Mapping[str, Any]
    raw_payload: bytes
    record_sha256: str
    file_identity: tuple[int, ...]
    temporary_aliases: tuple[tuple[Path, tuple[int, ...]], ...]


class _ResilienceTermination:
    """在演练阶段中止操作，在恢复阶段延迟同一组终止信号。"""

    def __init__(self) -> None:
        self.recovering = False
        self.interruption: BaseException | None = None

    def handle(self, signum: int, _frame: object) -> None:
        if self.interruption is not None:
            # 首个信号已经记账；恢复阶段及其后的重复信号不得再次打断恢复。
            return
        was_recovering = self.recovering
        if not was_recovering:
            # 必须先切换相位再构造并抛出 work 中断；异常展开至 finally 的
            # 窗口内，后续信号因此只能被延迟，不能再次打断恢复。
            self.recovering = True
        signal_name = signal.Signals(signum).name
        message = f"Gate A operation received {signal_name} and is recovering"
        self.interruption = (
            KeyboardInterrupt(message)
            if signum == signal.SIGINT
            else gatea.GateAOperationInterrupted(message)
        )
        if not was_recovering:
            raise self.interruption

    def begin_recovery(self) -> None:
        """在执行任何恢复调用前切换为只记账、不抛出的信号状态。"""

        self.recovering = True


@contextmanager
def _resilience_termination_guard() -> Iterator[_ResilienceTermination]:
    """覆盖外层 Handler，保证终止信号不会中断服务恢复。"""

    previous_handlers: dict[int, Any] = {}
    installed_signals: list[int] = []
    termination = _ResilienceTermination()
    try:
        for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, termination.handle)
            installed_signals.append(signum)
        yield termination
    finally:
        for signum in reversed(installed_signals):
            signal.signal(signum, previous_handlers[signum])


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(
        parsed
    )


def _is_positive_integer_list(value: object, expected_size: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == expected_size
        and all(type(item) is int and item > 0 for item in value)
        and len(set(value)) == expected_size
    )


def _record_path(record_dir: Path, candidate_sha: str) -> Path:
    """返回与不可变候选提交绑定且不可覆盖的韧性演练记录路径。"""

    return record_dir / f"{RECORD_PREFIX}-{candidate_sha}.json"


def _write_resilience_record(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    """完整落盘后以 no-clobber hard link 发布不可变成功 Record。"""

    try:
        gatea_backup._write_json_exclusive(path, payload, 0o644)
    except gatea.GateAError as error:
        raise ResilienceError(
            "Gate A resilience record path is already reserved"
        ) from error


def _file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """冻结不受读取 atime 影响的文件身份与元数据。"""

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


def _validate_resilience_record_directory(path: Path) -> None:
    """Record 目录必须是 Root 所有的真实 0755 目录。"""

    try:
        metadata = path.lstat()
    except OSError as error:
        raise ResilienceError(
            "Gate A resilience record directory is unavailable"
        ) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ResilienceError(
            "Gate A resilience record directory must be a real directory"
        )
    try:
        gatea._validate_root_directory(
            path, 0o755, "Gate A resilience record directory"
        )
    except gatea.GateAError as error:
        raise ResilienceError(
            "Gate A resilience record directory metadata is invalid"
        ) from error


def _read_stable_root_record_file(
    path: Path,
    *,
    description: str,
) -> tuple[bytes, tuple[int, ...]]:
    """不跟随链接地读取一个 Root 0644 普通文件并冻结其身份。"""

    try:
        before_metadata = path.lstat()
        if stat.S_ISLNK(before_metadata.st_mode) or not stat.S_ISREG(
            before_metadata.st_mode
        ):
            raise ResilienceError(f"{description} must be a regular file")
        gatea._validate_root_file(path, 0o644, description)
        raw_payload = path.read_bytes()
        after_metadata = path.lstat()
    except ResilienceError:
        raise
    except (gatea.GateAError, OSError) as error:
        raise ResilienceError(f"{description} metadata is invalid") from error
    file_identity = _file_identity(before_metadata)
    if (
        stat.S_ISLNK(after_metadata.st_mode)
        or not stat.S_ISREG(after_metadata.st_mode)
        or _file_identity(after_metadata) != file_identity
    ):
        raise ResilienceError(f"{description} changed during validation")
    return raw_payload, file_identity


def _associated_resilience_record_artifacts(path: Path) -> tuple[Path, ...]:
    """只接受 writer 可产生的一个随机临时别名，其他 sidecar 均阻断。"""

    temporary_prefix = f".{path.name}.tmp-"
    associated_prefixes = (f".{path.name}", f"{path.name}.")
    temporary_aliases: list[Path] = []
    unknown_artifacts: list[Path] = []
    try:
        entries = tuple(path.parent.iterdir())
    except OSError as error:
        raise ResilienceError(
            "Gate A resilience record artifacts could not be inspected"
        ) from error
    for entry in entries:
        if entry == path or not entry.name.startswith(associated_prefixes):
            continue
        if entry.name.startswith(temporary_prefix) and entry.name != temporary_prefix:
            temporary_aliases.append(entry)
        else:
            unknown_artifacts.append(entry)
    if unknown_artifacts or len(temporary_aliases) > 1:
        raise ResilienceError(
            "Gate A resilience record has an unknown alias or sidecar"
        )
    return tuple(temporary_aliases)


def _load_existing_resilience_record(
    path: Path,
) -> _ExistingResilienceRecord | None:
    """加载可恢复的 final；孤儿 temp、非同 inode alias 或漂移一律拒绝。"""

    temporary_paths = _associated_resilience_record_artifacts(path)
    final_visible = path.exists() or path.is_symlink()
    if not final_visible:
        if temporary_paths:
            raise ResilienceError(
                "Gate A resilience record has an orphan temporary file"
            )
        return None

    raw_payload, file_identity = _read_stable_root_record_file(
        path,
        description="Gate A existing resilience record",
    )
    record_sha256 = hashlib.sha256(raw_payload).hexdigest()
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResilienceError(
            "Gate A existing resilience record is invalid"
        ) from error
    if not isinstance(payload, dict):
        raise ResilienceError("Gate A existing resilience record is invalid")

    temporary_aliases: list[tuple[Path, tuple[int, ...]]] = []
    for temporary_path in temporary_paths:
        temporary_payload, temporary_identity = _read_stable_root_record_file(
            temporary_path,
            description="Gate A resilience record temporary alias",
        )
        if (
            temporary_identity != file_identity
            or temporary_payload != raw_payload
            or hashlib.sha256(temporary_payload).hexdigest() != record_sha256
        ):
            raise ResilienceError(
                "Gate A resilience record temporary alias is inconsistent"
            )
        temporary_aliases.append((temporary_path, temporary_identity))

    if file_identity[3] != len(temporary_aliases) + 1:
        raise ResilienceError(
            "Gate A existing resilience record has an unknown hard-link alias"
        )
    if gatea._sha256(path) != record_sha256:
        raise ResilienceError(
            "Gate A existing resilience record digest changed during validation"
        )
    return _ExistingResilienceRecord(
        path=path,
        payload=payload,
        raw_payload=raw_payload,
        record_sha256=record_sha256,
        file_identity=file_identity,
        temporary_aliases=tuple(temporary_aliases),
    )


def _same_file_after_alias_cleanup(
    before: tuple[int, ...],
    after: tuple[int, ...],
) -> bool:
    """删除 hard-link 会改变 nlink/ctime，其余不可变身份必须保持一致。"""

    stable_indexes = (0, 1, 2, 4, 5, 6, 7)
    return all(before[index] == after[index] for index in stable_indexes)


def _complete_existing_resilience_publication(
    evidence: _ExistingResilienceRecord,
) -> None:
    """重新同步 final，安全清理同 inode temp，并验证最终单链接状态。"""

    raw_payload, file_identity = _read_stable_root_record_file(
        evidence.path,
        description="Gate A existing resilience record",
    )
    if (
        raw_payload != evidence.raw_payload
        or file_identity != evidence.file_identity
        or hashlib.sha256(raw_payload).hexdigest() != evidence.record_sha256
    ):
        raise ResilienceError(
            "Gate A existing resilience record changed before recovery"
        )
    for temporary_path, expected_identity in evidence.temporary_aliases:
        temporary_payload, temporary_identity = _read_stable_root_record_file(
            temporary_path,
            description="Gate A resilience record temporary alias",
        )
        if (
            temporary_identity != expected_identity
            or temporary_identity != file_identity
            or temporary_payload != raw_payload
        ):
            raise ResilienceError(
                "Gate A resilience record temporary alias changed before recovery"
            )

    # final 的目录项可能在上次 os.link 后尚未成功 fsync；先持久化 final，
    # 再删除可证明为同 inode 的 writer temp，并再次持久化目录项。
    gatea_backup._fsync_directory(evidence.path.parent)
    for temporary_path, expected_identity in evidence.temporary_aliases:
        try:
            if _file_identity(temporary_path.lstat()) != expected_identity:
                raise ResilienceError(
                    "Gate A resilience record temporary alias changed before cleanup"
                )
            temporary_path.unlink()
        except ResilienceError:
            raise
        except OSError as error:
            raise ResilienceError(
                "Gate A resilience record temporary alias could not be cleaned"
            ) from error
        gatea_backup._fsync_directory(evidence.path.parent)

    reloaded = _load_existing_resilience_record(evidence.path)
    if (
        reloaded is None
        or reloaded.raw_payload != evidence.raw_payload
        or reloaded.record_sha256 != evidence.record_sha256
        or reloaded.temporary_aliases
        or reloaded.file_identity[3] != 1
        or not _same_file_after_alias_cleanup(
            evidence.file_identity,
            reloaded.file_identity,
        )
    ):
        raise ResilienceError(
            "Gate A existing resilience record did not converge safely"
        )


def _runtime_acceptance_sidecars(path: Path) -> tuple[Path, Path]:
    return (
        path.with_suffix(".json.pending"),
        path.with_suffix(".json.complete"),
    )


def _ensure_runtime_acceptance_sidecars_absent(path: Path) -> None:
    if any(
        sidecar.exists() or sidecar.is_symlink()
        for sidecar in _runtime_acceptance_sidecars(path)
    ):
        raise ResilienceError(
            "Gate A M9 runtime acceptance sidecar requires manual review"
        )


def _parse_runtime_acceptance_completed_at(value: object) -> datetime:
    if not _is_utc_timestamp(value):
        raise ResilienceError(
            "Gate A M9 runtime acceptance completion time is invalid"
        )
    assert isinstance(value, str)
    return datetime.fromisoformat(value)


def _validate_runtime_acceptance_record(
    *,
    path: Path,
    confirmed_sha256: str,
    candidate_sha: str,
    image_id: str,
    deployment_record: Mapping[str, Any],
    representative_payload: Mapping[str, Any],
    representative_record_sha256: str,
    release_record_dir: Path,
    runtime_services: Sequence[str],
    expected: _RuntimeAcceptanceEvidence | None = None,
) -> _RuntimeAcceptanceEvidence:
    """验证并冻结 M9 acceptance；发布前可用 ``expected`` 检测漂移。"""

    expected_name = f"{M9_RUNTIME_ACCEPTANCE_PREFIX}-{candidate_sha}.json"
    if path.name != expected_name:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record filename is invalid"
        )
    if gatea.SHA256_PATTERN.fullmatch(confirmed_sha256) is None:
        raise ResilienceError(
            "Gate A M9 runtime acceptance confirmation digest is invalid"
        )
    try:
        parent_metadata = path.parent.lstat()
    except FileNotFoundError as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record directory is unavailable"
        ) from error
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(
        parent_metadata.st_mode
    ):
        raise ResilienceError(
            "Gate A M9 runtime acceptance record directory must be a real directory"
        )
    try:
        gatea._validate_root_directory(
            path.parent,
            0o755,
            "Gate A M9 runtime acceptance record directory",
        )
    except gatea.GateAError as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record directory metadata is invalid"
        ) from error
    _ensure_runtime_acceptance_sidecars_absent(path)
    try:
        before_metadata = path.lstat()
    except FileNotFoundError as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record is unavailable"
        ) from error
    if stat.S_ISLNK(before_metadata.st_mode) or not stat.S_ISREG(
        before_metadata.st_mode
    ):
        raise ResilienceError(
            "Gate A M9 runtime acceptance record must be a regular file"
        )
    try:
        gatea._validate_root_file(
            path,
            0o644,
            "Gate A M9 runtime acceptance record",
        )
        raw_payload = path.read_bytes()
        after_metadata = path.lstat()
    except (gatea.GateAError, OSError) as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record metadata is invalid"
        ) from error
    file_identity = _file_identity(before_metadata)
    if (
        stat.S_ISLNK(after_metadata.st_mode)
        or not stat.S_ISREG(after_metadata.st_mode)
        or _file_identity(after_metadata) != file_identity
    ):
        raise ResilienceError(
            "Gate A M9 runtime acceptance record changed during validation"
        )
    _ensure_runtime_acceptance_sidecars_absent(path)
    record_sha256 = hashlib.sha256(raw_payload).hexdigest()
    if record_sha256 != confirmed_sha256:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record digest does not match confirmation"
        )
    try:
        payload = json.loads(raw_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record is invalid"
        ) from error
    if not isinstance(payload, dict):
        raise ResilienceError("Gate A M9 runtime acceptance record is invalid")

    # gatea_m9_acceptance 会导入本模块复用 helper；这里延迟导入，
    # 避免模块初始化形成循环。
    from scripts.release import gatea_m9_acceptance as acceptance

    try:
        acceptance._validate_success_record(payload)
    except (
        acceptance.M9AcceptanceError,
        AttributeError,
        KeyError,
        TypeError,
    ) as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record is invalid"
        ) from error
    try:
        validated_raw_payload = path.read_bytes()
        validated_metadata = path.lstat()
    except OSError as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record changed during validation"
        ) from error
    if (
        validated_raw_payload != raw_payload
        or _file_identity(validated_metadata) != file_identity
    ):
        raise ResilienceError(
            "Gate A M9 runtime acceptance record changed during validation"
        )
    _ensure_runtime_acceptance_sidecars_absent(path)
    try:
        operations_sha, ci_run_id = acceptance._operations_evidence(
            release_record_dir
        )
    except acceptance.M9AcceptanceError as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance operations evidence is invalid"
        ) from error

    upgrade_record_path = gatea._upgrade_marker(
        release_record_dir,
        candidate_sha,
    )
    plan_replay_path = gatea._upgrade_replay_marker(
        release_record_dir,
        candidate_sha,
    )
    try:
        upgrade_record_sha256 = gatea._sha256(upgrade_record_path)
        plan_replay_record_sha256 = gatea._sha256(plan_replay_path)
    except OSError as error:
        raise ResilienceError(
            "Gate A M9 runtime acceptance prerequisite record is unavailable"
        ) from error
    is_m7_upgrade = bool(
        deployment_record.get("schema_version") == 1
        and deployment_record.get("record_type")
        == "existing-database-upgrade"
        and deployment_record.get("source_version") == 7
        and deployment_record.get("source_aerich_versions")
        == list(gatea.APPROVED_TARGET_M7_CHAIN)
        and deployment_record.get("target_aerich_versions")
        == list(gatea.APPROVED_TARGET_M9_CHAIN)
    )
    is_m9_adoption = _is_m9_candidate_adoption(deployment_record)
    representative_source_sha = (
        deployment_record.get("lineage_source_candidate_sha")
        if is_m9_adoption
        else deployment_record.get("source_candidate_sha")
    )
    if (
        not (is_m7_upgrade or is_m9_adoption)
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("image_id") != image_id
        or payload.get("operations_sha") != operations_sha
        or payload.get("ci_run_id") != ci_run_id
        or payload.get("source_candidate_sha") != representative_source_sha
        or payload.get("representative_record_sha256")
        != representative_record_sha256
        or payload.get("credentials_sha256")
        != representative_payload.get("credentials_sha256")
        or payload.get("upgrade_record_sha256") != upgrade_record_sha256
        or payload.get("upgrade_plan_replay_record_sha256")
        != plan_replay_record_sha256
        or payload.get("runtime_services") != list(runtime_services)
        or payload.get("upgrade_plan_replayed") is not True
        or payload.get("passed") is not True
    ):
        raise ResilienceError(
            "Gate A M9 runtime acceptance binding does not match current evidence"
        )
    attempt_id_sha256 = str(payload.get("attempt_id_sha256", ""))
    completed_at = str(payload.get("completed_at", ""))
    _parse_runtime_acceptance_completed_at(completed_at)
    evidence = _RuntimeAcceptanceEvidence(
        path=path,
        record_sha256=record_sha256,
        attempt_id_sha256=attempt_id_sha256,
        completed_at=completed_at,
        payload=payload,
        file_identity=file_identity,
    )
    if expected is not None and evidence != expected:
        raise ResilienceError(
            "Gate A M9 runtime acceptance record changed during resilience drill"
        )
    return evidence


def _parse_resilience_timestamp(value: object, description: str) -> datetime:
    if not _is_utc_timestamp(value):
        raise ResilienceError(f"{description} timestamp is invalid")
    return datetime.fromisoformat(str(value))


def _is_nonnegative_metric(value: object) -> bool:
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0
    )


def _validated_record_content_snapshots(
    *,
    payload: object,
    live_snapshot: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ResilienceError(
            "Gate A existing resilience content evidence is invalid"
        )
    expected_keys: set[str] = set()
    if gatea_backup._requires_m7_content_snapshot(live_snapshot):
        expected_keys.add("m7_preserved_business")
    if gatea_backup._requires_m9_table_content_snapshot(live_snapshot):
        expected_keys.add("m8_swatch_content")
        expected_keys.add("m9_table_business")
    if set(payload) != expected_keys:
        raise ResilienceError(
            "Gate A existing resilience content evidence is invalid"
        )
    validated: dict[str, dict[str, Any]] = {}
    try:
        if "m7_preserved_business" in payload:
            validated["m7_preserved_business"] = (
                gatea_backup._validate_m7_content_snapshot(
                    payload["m7_preserved_business"]
                )
            )
        if "m8_swatch_content" in payload:
            validated["m8_swatch_content"] = (
                gatea_backup._validate_m8_swatch_content_snapshot(
                    payload["m8_swatch_content"]
                )
            )
        if "m9_table_business" in payload:
            validated["m9_table_business"] = (
                gatea_backup._validate_m9_table_content_snapshot(
                    payload["m9_table_business"]
                )
            )
    except gatea.GateAError as error:
        raise ResilienceError(
            "Gate A existing resilience content evidence is invalid"
        ) from error
    return validated


def _validate_existing_resilience_payload(
    payload: Mapping[str, Any],
    *,
    candidate_sha: str,
    image_id: str,
    deployment_record: Mapping[str, Any],
    representative_candidate_sha: str,
    representative_image_id: str,
    representative_record_sha256: str,
    representative_payload: Mapping[str, Any],
    live_snapshot: Mapping[str, Any],
    live_content_snapshots: Mapping[str, Mapping[str, Any]],
    live_images: Sequence[str],
    runtime_services: Sequence[str],
    runtime_acceptance: _RuntimeAcceptanceEvidence | None,
) -> dict[str, Any]:
    """严格重验已发布 schema 1/2 Record，不能把“final 存在”当作通过。"""

    is_m9 = tuple(runtime_services) == M9_SERVICES
    expected_schema = 2 if is_m9 else 1
    expected_keys = (
        RESILIENCE_RECORD_V2_KEYS if is_m9 else RESILIENCE_RECORD_BASE_KEYS
    )
    dependency_drills = payload.get("dependency_drills")
    app_restart = payload.get("app_restart")
    log_rotation = payload.get("log_rotation")
    log_observability = payload.get("log_observability")
    request_time = (
        log_observability.get("request_time_seconds")
        if isinstance(log_observability, dict)
        else None
    )
    content_snapshots = _validated_record_content_snapshots(
        payload=payload.get("database_content_snapshots"),
        live_snapshot=live_snapshot,
    )
    if deployment_record.get("record_type") == "existing-database-upgrade":
        recorded_snapshot = deployment_record.get("final_database_snapshot")
        recorded_images = deployment_record.get("final_image_manifest")
        if (
            not isinstance(recorded_snapshot, dict)
            or any(
                live_snapshot.get(key) != recorded_snapshot.get(key)
                for key in gatea.M9_STATIC_SNAPSHOT_KEYS
            )
            or not isinstance(recorded_images, list)
            or list(live_images) != recorded_images
        ):
            raise ResilienceError(
                "Gate A live state differs from the deployment evidence"
            )

    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != expected_schema
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("image_id") != image_id
        or payload.get("representative_candidate_sha")
        != representative_candidate_sha
        or payload.get("representative_image_id") != representative_image_id
        or payload.get("representative_record_sha256")
        != representative_record_sha256
        or gatea.SHA256_PATTERN.fullmatch(representative_record_sha256) is None
        or content_snapshots != dict(live_content_snapshots)
        or not isinstance(dependency_drills, list)
        or len(dependency_drills) != 2
        or any(not isinstance(item, dict) for item in dependency_drills)
        or [item.get("service") for item in dependency_drills]
        != ["mysql", "redis"]
        or not isinstance(app_restart, dict)
        or not isinstance(log_rotation, dict)
        or set(log_rotation) != set(runtime_services)
        or any(
            value
            != {"driver": "json-file", "max_file": "5", "max_size": "10m"}
            for value in log_rotation.values()
        )
        or not isinstance(log_observability, dict)
        or set(log_observability) != LOG_OBSERVABILITY_KEYS
        or log_observability.get("window") != "24h"
        or type(log_observability.get("combined_line_count")) is not int
        or log_observability["combined_line_count"] <= 0
        or type(log_observability.get("nginx_request_count")) is not int
        or log_observability["nginx_request_count"] <= 0
        or any(
            type(log_observability.get(field)) is not int
            or log_observability[field] < 0
            or log_observability[field]
            > log_observability["nginx_request_count"]
            for field in ("nginx_4xx_count", "nginx_5xx_count")
        )
        or log_observability["nginx_4xx_count"]
        + log_observability["nginx_5xx_count"]
        > log_observability["nginx_request_count"]
        or not isinstance(request_time, dict)
        or set(request_time) != REQUEST_TIME_KEYS
        or any(
            not _is_nonnegative_metric(request_time.get(field))
            for field in REQUEST_TIME_KEYS
        )
        or not (
            request_time["median"] <= request_time["p95"] <= request_time["max"]
        )
        or log_observability.get("exact_secret_matches") != 0
        or log_observability.get("forbidden_pattern_matches") != 0
        or log_observability.get("raw_log_content_recorded") is not False
        or log_observability.get("passed") is not True
        or payload.get("database_snapshot_unchanged") is not True
        or payload.get("database_content_snapshots_unchanged") is not True
        or payload.get("image_manifest_unchanged") is not True
        or type(payload.get("image_file_count")) is not int
        or payload["image_file_count"] <= 0
        or payload["image_file_count"] != len(live_images)
        or payload.get("source_services_healthy") is not True
        or payload.get("runtime_services") != list(runtime_services)
        or payload.get("table_sweeper_included") is not is_m9
        or payload.get("loopback_only") is not True
        or payload.get("pii_recorded") is not False
        or payload.get("secret_values_recorded") is not False
        or payload.get("passed") is not True
    ):
        raise ResilienceError("Gate A existing resilience record is invalid")

    record_started = _parse_resilience_timestamp(
        payload.get("started_at"),
        "Gate A existing resilience start",
    )
    record_completed = _parse_resilience_timestamp(
        payload.get("completed_at"),
        "Gate A existing resilience completion",
    )
    cursor = record_started
    for item in dependency_drills:
        assert isinstance(item, dict)
        if (
            set(item) != DEPENDENCY_DRILL_KEYS
            or item.get("passed") is not True
            or item.get("outage_readiness_status") != 503
            or item.get("outage_liveness_status") != 200
            or item.get("recovered_readiness_status") != 200
            or any(
                not _is_nonnegative_metric(item.get(field))
                for field in (
                    "failure_detection_seconds",
                    "service_recovery_seconds",
                    "readiness_recovery_seconds",
                )
            )
        ):
            raise ResilienceError("Gate A existing resilience record is invalid")
        item_started = _parse_resilience_timestamp(
            item.get("started_at"),
            "Gate A dependency drill start",
        )
        item_completed = _parse_resilience_timestamp(
            item.get("completed_at"),
            "Gate A dependency drill completion",
        )
        if item_started < cursor or item_completed < item_started:
            raise ResilienceError(
                "Gate A existing resilience record time order is invalid"
            )
        cursor = item_completed

    if (
        set(app_restart) != APP_RESTART_KEYS
        or app_restart.get("passed") is not True
        or app_restart.get("readiness_status") != 200
        or any(
            not _is_nonnegative_metric(app_restart.get(field))
            for field in (
                "total_seconds",
                "service_recovery_seconds",
                "readiness_recovery_seconds",
            )
        )
    ):
        raise ResilienceError("Gate A existing resilience record is invalid")
    app_started = _parse_resilience_timestamp(
        app_restart.get("started_at"),
        "Gate A app restart start",
    )
    app_completed = _parse_resilience_timestamp(
        app_restart.get("completed_at"),
        "Gate A app restart completion",
    )
    if (
        app_started < cursor
        or app_completed < app_started
        or record_completed < app_completed
    ):
        raise ResilienceError(
            "Gate A existing resilience record time order is invalid"
        )

    for prerequisite in (deployment_record, representative_payload):
        prerequisite_completed = prerequisite.get("completed_at")
        if prerequisite_completed is not None and (
            _parse_resilience_timestamp(
                prerequisite_completed,
                "Gate A resilience prerequisite completion",
            )
            > record_started
        ):
            raise ResilienceError(
                "Gate A existing resilience record time order is invalid"
            )

    if is_m9:
        if (
            runtime_acceptance is None
            or payload.get("runtime_acceptance_record_sha256")
            != runtime_acceptance.record_sha256
            or payload.get("runtime_acceptance_attempt_id_sha256")
            != runtime_acceptance.attempt_id_sha256
            or payload.get("runtime_acceptance_completed_at")
            != runtime_acceptance.completed_at
            or _parse_runtime_acceptance_completed_at(
                runtime_acceptance.completed_at
            )
            > record_started
        ):
            raise ResilienceError(
                "Gate A existing resilience acceptance binding is invalid"
            )
    elif runtime_acceptance is not None:
        raise ResilienceError(
            "Gate A legacy resilience record has unexpected acceptance evidence"
        )
    return dict(payload)


def _http_status(port: int, path: str) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", path, headers={"Connection": "close"})
        response = connection.getresponse()
        response.read()
        return response.status
    except OSError:
        return 0
    finally:
        connection.close()


def _wait_http(
    *,
    port: int,
    path: str,
    expected: set[int],
    timeout: int,
) -> tuple[int, float]:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        status = _http_status(port, path)
        if status in expected:
            return status, round(time.monotonic() - started, 3)
        time.sleep(1)
    raise ResilienceError("Gate A health transition did not reach the expected state")


def _wait_services(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    services: Sequence[str],
    timeout: int,
) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        rows = gatea._compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode="loopback",
            services=services,
        )
        try:
            gatea._ensure_services_healthy(rows, *services)
            return round(time.monotonic() - started, 3)
        except gatea.GateAError:
            time.sleep(1)
    raise ResilienceError("Gate A services did not recover before the timeout")


def _restore_all_services(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    services: Sequence[str],
    timeout: int,
) -> None:
    gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=(
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            str(timeout),
            *services,
        ),
        start_new_session=True,
    )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=services,
        start_new_session=True,
    )
    gatea._ensure_services_healthy(rows, *services)
    gatea._validate_loopback_publishers(
        rows, int(values.get("GATEA_LOOPBACK_PORT", "18080"))
    )


def _dependency_drill(
    *,
    service: str,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    port: int,
    timeout: int,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("stop", "--timeout", "30", service),
    )
    readiness_status, failure_seconds = _wait_http(
        port=port,
        path="/api/v1/health/ready",
        expected={503},
        timeout=45,
    )
    liveness_status = _http_status(port, "/api/v1/health/live")
    if liveness_status != 200:
        raise ResilienceError("Gate A liveness failed during a dependency outage")
    gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("start", service),
    )
    service_recovery_seconds = _wait_services(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=(service,),
        timeout=timeout,
    )
    recovered_status, readiness_recovery_seconds = _wait_http(
        port=port,
        path="/api/v1/health/ready",
        expected={200},
        timeout=timeout,
    )
    return {
        "service": service,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "outage_readiness_status": readiness_status,
        "outage_liveness_status": liveness_status,
        "failure_detection_seconds": failure_seconds,
        "service_recovery_seconds": service_recovery_seconds,
        "readiness_recovery_seconds": readiness_recovery_seconds,
        "recovered_readiness_status": recovered_status,
        "passed": True,
    }


def _app_restart_drill(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    port: int,
    timeout: int,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("restart", "--timeout", "30", "app"),
    )
    service_recovery_seconds = _wait_services(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=("app",),
        timeout=timeout,
    )
    readiness_status, readiness_recovery_seconds = _wait_http(
        port=port,
        path="/api/v1/health/ready",
        expected={200},
        timeout=timeout,
    )
    return {
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_seconds": round(time.monotonic() - started, 3),
        "service_recovery_seconds": service_recovery_seconds,
        "readiness_recovery_seconds": readiness_recovery_seconds,
        "readiness_status": readiness_status,
        "passed": True,
    }


def _service_container_id(
    *,
    service: str,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> str:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("ps", "--quiet", service),
        capture_output=True,
    )
    container_id = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{12,64}", container_id):
        raise ResilienceError("Gate A service container identity is invalid")
    return container_id


def _log_rotation_contract(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    services: Sequence[str],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for service in services:
        container_id = _service_container_id(
            service=service,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
        )
        inspected = subprocess.run(
            (
                "docker",
                "inspect",
                "--format",
                "{{json .HostConfig.LogConfig}}",
                container_id,
            ),
            check=True,
            text=True,
            capture_output=True,
        )
        try:
            payload = json.loads(inspected.stdout)
        except json.JSONDecodeError as error:
            raise ResilienceError("Gate A Docker log metadata is invalid") from error
        if payload != {
            "Type": "json-file",
            "Config": {"max-file": "5", "max-size": "10m"},
        }:
            raise ResilienceError("Gate A Docker log rotation contract does not match")
        result[service] = {
            "driver": "json-file",
            "max_file": "5",
            "max_size": "10m",
        }
    return result


def _compose_logs(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    services: Sequence[str],
) -> str:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=("logs", "--no-color", "--since", "24h", *services),
        capture_output=True,
    )
    return (result.stdout or "") + (result.stderr or "")


def _scan_logs(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    services: Sequence[str],
) -> dict[str, Any]:
    logs = _compose_logs(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=services,
    )
    secret_values: list[str] = []
    for secret_name in gatea.EXPECTED_SECRET_FILES:
        value = (secret_dir / secret_name).read_text(encoding="utf-8").strip()
        if len(value) < 12:
            raise ResilienceError("Gate A Secret does not meet the log scan length floor")
        secret_values.append(value)
    if any(secret in logs for secret in secret_values):
        raise ResilienceError("Gate A logs contain an exact Secret value")
    if any(pattern.search(logs) for pattern in FORBIDDEN_LOG_PATTERNS):
        raise ResilienceError("Gate A logs contain a forbidden sensitive pattern")

    nginx_logs = _compose_logs(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=("nginx",),
    )
    statuses: list[int] = []
    durations: list[float] = []
    for match in NGINX_METRIC_PATTERN.finditer(nginx_logs):
        statuses.append(int(match.group("status")))
        durations.append(float(match.group("duration")))
    if not statuses or not durations:
        raise ResilienceError("Gate A Nginx logs have no queryable request metrics")
    ordered = sorted(durations)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "window": "24h",
        "combined_line_count": len(logs.splitlines()),
        "nginx_request_count": len(statuses),
        "nginx_4xx_count": sum(400 <= status < 500 for status in statuses),
        "nginx_5xx_count": sum(status >= 500 for status in statuses),
        "request_time_seconds": {
            "median": round(statistics.median(durations), 6),
            "p95": round(ordered[p95_index], 6),
            "max": round(max(durations), 6),
        },
        "exact_secret_matches": 0,
        "forbidden_pattern_matches": 0,
        "raw_log_content_recorded": False,
        "passed": True,
    }


def _load_representative_record(
    path: Path,
    candidate_sha: str,
    image_id: str,
    *,
    require_m7_record: bool = False,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        common_valid = (
            payload.get("schema_version") == 1
            and payload.get("candidate_sha") == candidate_sha
            and payload.get("image_id") == image_id
            and payload.get("passed") is True
        )
        record_type = payload.get("record_type")
        if require_m7_record:
            before_image_file_count = payload.get("before_image_file_count")
            after_image_file_count = payload.get("after_image_file_count")
            safe_shape = (
                set(payload) == M7_REPRESENTATIVE_RECORD_KEYS
                and record_type == "gatea-m7-representative-data"
                and gatea.GIT_SHA_PATTERN.fullmatch(
                    str(payload.get("operations_sha", ""))
                )
                is not None
                and gatea.BACKUP_ID_PATTERN.fullmatch(
                    str(payload.get("backup_id", ""))
                )
                is not None
                and _is_utc_timestamp(payload.get("started_at"))
                and _is_utc_timestamp(payload.get("completed_at"))
                and isinstance(payload.get("before_snapshot"), dict)
                and bool(payload["before_snapshot"])
                and isinstance(payload.get("after_snapshot"), dict)
                and bool(payload["after_snapshot"])
                and isinstance(payload.get("representative_details"), dict)
                and bool(payload["representative_details"])
                and _is_positive_integer_list(
                    payload.get("synthetic_user_ids"), 3
                )
                and type(payload.get("color_product_id")) is int
                and payload["color_product_id"] > 0
                and _is_positive_integer_list(payload.get("color_ids"), 3)
                and _is_positive_integer_list(payload.get("order_ids"), 6)
                and _is_positive_integer_list(payload.get("reservation_ids"), 6)
                and type(before_image_file_count) is int
                and before_image_file_count >= 0
                and type(after_image_file_count) is int
                and after_image_file_count == before_image_file_count + 1
                and type(payload.get("request_count")) is int
                and payload["request_count"] > 0
                and payload.get("synthetic_sessions_revoked") is True
                and payload.get("super_admin_session_revoked") is True
                and payload.get("super_admin_credentials_recorded") is False
                and payload.get("request_or_response_bodies_recorded") is False
                and payload.get("loopback_only") is True
                and isinstance(payload.get("credentials_file"), str)
                and Path(payload["credentials_file"]).is_absolute()
                and payload.get("credentials_file_mode") == "0600"
                and gatea.SHA256_PATTERN.fullmatch(
                    str(payload.get("credentials_sha256", ""))
                )
                is not None
            )
        else:
            safe_shape = (
                record_type in (None, "gatea-representative-data")
                and payload.get("synthetic_user_disabled") is True
                and payload.get("synthetic_session_revoked") is True
                and payload.get("super_admin_session_revoked") is True
                and payload.get("pii_recorded") is False
                and payload.get("secret_values_recorded") is False
            )
        if not common_valid or not safe_shape:
            raise ValueError
    except (FileNotFoundError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ResilienceError("Gate A representative data record is invalid") from error
    return payload


def _validate_representative_record_file(path: Path) -> None:
    """读取前拒绝软链接，并验证代表数据 Record 的 Root 元数据。"""

    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise ResilienceError("Gate A representative data record is invalid") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise ResilienceError("Gate A representative data record is invalid")
    try:
        gatea._validate_root_directory(
            path.parent,
            0o755,
            "Gate A representative data record directory",
        )
        gatea._validate_root_file(
            path,
            0o644,
            "Gate A representative data record",
        )
    except gatea.GateAError as error:
        raise ResilienceError("Gate A representative data record is invalid") from error


def _validate_m7_credentials_artifact(
    *,
    record_path: Path,
    payload: Mapping[str, Any],
) -> None:
    """验证 M7 合成凭据只存在于同一 Root 目录且与 Record 摘要一致。"""

    credentials_path = Path(str(payload.get("credentials_file", "")))
    try:
        metadata = credentials_path.lstat()
    except FileNotFoundError as error:
        raise ResilienceError("Gate A M7 credentials artifact is invalid") from error
    if (
        not credentials_path.is_absolute()
        or credentials_path.parent.resolve() != record_path.parent.resolve()
        or stat.S_ISLNK(metadata.st_mode)
    ):
        raise ResilienceError("Gate A M7 credentials artifact is invalid")
    try:
        gatea._validate_root_file(
            credentials_path,
            0o600,
            "Gate A M7 synthetic credentials file",
        )
    except gatea.GateAError as error:
        raise ResilienceError("Gate A M7 credentials artifact is invalid") from error
    if gatea._sha256(credentials_path) != payload.get("credentials_sha256"):
        raise ResilienceError("Gate A M7 credentials artifact is invalid")


def _representative_binding(
    deployment_record: Mapping[str, Any],
    candidate_sha: str,
    image_id: str,
) -> tuple[str, str]:
    """解析当前部署或受控升级来源所对应的代表性数据证据。"""

    if _is_m9_candidate_adoption(deployment_record):
        return (
            str(deployment_record["lineage_source_candidate_sha"]),
            str(deployment_record["lineage_source_image_id"]),
        )
    if deployment_record.get("record_type") == "existing-database-upgrade":
        return (
            str(deployment_record["source_candidate_sha"]),
            str(deployment_record["source_image_id"]),
        )
    return candidate_sha, image_id


def _is_m9_candidate_adoption(
    deployment_record: Mapping[str, Any],
) -> bool:
    """识别经 Operations 严格验证的 M9→M9 零迁移候选接管证据。"""

    return bool(
        deployment_record.get("schema_version") == 2
        and deployment_record.get("record_type")
        == "existing-database-upgrade"
        and deployment_record.get("transition_kind")
        == "m9-candidate-adoption"
        and deployment_record.get("source_version") == 9
        and deployment_record.get("target_version") == 9
        and deployment_record.get("source_aerich_versions")
        == list(gatea.APPROVED_TARGET_M9_CHAIN)
        and deployment_record.get("target_aerich_versions")
        == list(gatea.APPROVED_TARGET_M9_CHAIN)
        and gatea.GIT_SHA_PATTERN.fullmatch(
            str(deployment_record.get("lineage_source_candidate_sha", ""))
        )
        is not None
        and isinstance(deployment_record.get("lineage_source_image_id"), str)
    )


def _representative_record_path(
    configured: Path | None,
    deployment_record: Mapping[str, Any],
    source_candidate_sha: str,
) -> Path:
    """为 M7→M9 自动选择与升级来源绑定的代表数据 Record。"""

    if configured is not None:
        return configured
    if (
        deployment_record.get("record_type") == "existing-database-upgrade"
        and (
            deployment_record.get("source_version") == 7
            or _is_m9_candidate_adoption(deployment_record)
        )
    ):
        return DEFAULT_REPRESENTATIVE_RECORD.parent / (
            "gatea-m7-representative-data-"
            f"{source_candidate_sha}.json"
        )
    return DEFAULT_REPRESENTATIVE_RECORD


def _runtime_services(snapshot: Mapping[str, Any]) -> tuple[str, ...]:
    """按精确批准迁移链选择必须恢复、观察和扫描的常驻服务。"""

    versions = snapshot.get("aerich_versions")
    if versions == ",".join(gatea.APPROVED_TARGET_M9_CHAIN):
        return M9_SERVICES
    if versions in (
        ",".join(gatea.APPROVED_SOURCE_M2_CHAIN),
        ",".join(gatea.APPROVED_TARGET_M7_CHAIN),
        ",".join(gatea.APPROVED_TARGET_M8_CHAIN),
    ):
        return LEGACY_SERVICES
    raise ResilienceError("Gate A resilience migration chain is not approved")


def _database_content_snapshots(
    *,
    snapshot: Mapping[str, Any],
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> dict[str, dict[str, Any]]:
    """按精确迁移链读取不含业务明细的版本化内容摘要。"""

    content: dict[str, dict[str, Any]] = {}
    if gatea_backup._requires_m7_content_snapshot(snapshot):
        content["m7_preserved_business"] = (
            gatea_backup._source_m7_content_snapshot(
                values,
                config_file,
                secret_dir,
                "loopback",
            )
        )
    if gatea_backup._requires_m9_table_content_snapshot(snapshot):
        content["m8_swatch_content"] = (
            gatea_backup._source_m8_swatch_content_snapshot(
                values,
                config_file,
                secret_dir,
                "loopback",
            )
        )
        content["m9_table_business"] = (
            gatea_backup._source_m9_table_content_snapshot(
                values,
                config_file,
                secret_dir,
                "loopback",
            )
        )
    return content


def _recover_existing_resilience_record(
    *,
    evidence: _ExistingResilienceRecord,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    acceptance_record_dir: Path,
    candidate_sha: str,
    image_id: str,
    deployment_record: Mapping[str, Any],
    representative_candidate_sha: str,
    representative_image_id: str,
    representative_record: Path,
    representative_record_sha256: str,
    representative_payload: Mapping[str, Any],
    require_m7_record: bool,
    live_snapshot: Mapping[str, Any],
    live_content_snapshots: Mapping[str, Mapping[str, Any]],
    live_images: Sequence[str],
    runtime_services: Sequence[str],
    runtime_acceptance_record: Path | None,
    confirm_runtime_acceptance_record_sha256: str | None,
    runtime_acceptance: _RuntimeAcceptanceEvidence | None,
    port: int,
) -> dict[str, Any]:
    """无故障注入地重验 live invariants，并收口一次中断的 Record 发布。"""

    payload = _validate_existing_resilience_payload(
        evidence.payload,
        candidate_sha=candidate_sha,
        image_id=image_id,
        deployment_record=deployment_record,
        representative_candidate_sha=representative_candidate_sha,
        representative_image_id=representative_image_id,
        representative_record_sha256=representative_record_sha256,
        representative_payload=representative_payload,
        live_snapshot=live_snapshot,
        live_content_snapshots=live_content_snapshots,
        live_images=live_images,
        runtime_services=runtime_services,
        runtime_acceptance=runtime_acceptance,
    )
    current_log_rotation = _log_rotation_contract(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=runtime_services,
    )
    if current_log_rotation != payload["log_rotation"]:
        raise ResilienceError(
            "Gate A live log rotation differs from the resilience record"
        )
    # 只读扫描当前日志，确认恢复时没有 Secret/Token 泄漏；历史聚合计数
    # 会自然增长，因此只要求扫描本身通过，不伪造为原演练结果。
    _scan_logs(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=runtime_services,
    )

    gatea.reject_unresolved_candidate_transition_journals(
        record_dir=release_record_dir,
    )
    gatea.reject_unresolved_m9_acceptance_sidecars(
        record_dir=acceptance_record_dir,
    )
    revalidated_values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        require_available_port=False,
    )
    if (
        revalidated_values != dict(values)
        or gatea._candidate_sha(revalidated_values) != candidate_sha
        or gatea.validate_app_image(revalidated_values) != image_id
    ):
        raise ResilienceError(
            "Gate A runtime candidate changed during resilience recovery"
        )
    revalidated_deployment = gatea._require_deployment_record(
        record_dir=release_record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    if revalidated_deployment != deployment_record:
        raise ResilienceError(
            "Gate A deployment evidence changed during resilience recovery"
        )

    _validate_representative_record_file(representative_record)
    if gatea._sha256(representative_record) != representative_record_sha256:
        raise ResilienceError(
            "Gate A representative data record changed during resilience recovery"
        )
    revalidated_representative = _load_representative_record(
        representative_record,
        representative_candidate_sha,
        representative_image_id,
        require_m7_record=require_m7_record,
    )
    if revalidated_representative != representative_payload:
        raise ResilienceError(
            "Gate A representative data record changed during resilience recovery"
        )
    if require_m7_record:
        _validate_m7_credentials_artifact(
            record_path=representative_record,
            payload=revalidated_representative,
        )

    revalidated_acceptance = runtime_acceptance
    if runtime_acceptance is not None:
        assert runtime_acceptance_record is not None
        assert confirm_runtime_acceptance_record_sha256 is not None
        revalidated_acceptance = _validate_runtime_acceptance_record(
            path=runtime_acceptance_record,
            confirmed_sha256=confirm_runtime_acceptance_record_sha256,
            candidate_sha=candidate_sha,
            image_id=image_id,
            deployment_record=deployment_record,
            representative_payload=representative_payload,
            representative_record_sha256=representative_record_sha256,
            release_record_dir=release_record_dir,
            runtime_services=runtime_services,
            expected=runtime_acceptance,
        )

    current_snapshot = gatea_backup._source_snapshot(
        values, config_file, secret_dir, "loopback"
    )
    current_content_snapshots = _database_content_snapshots(
        snapshot=current_snapshot,
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
    )
    current_images = gatea_backup._source_image_manifest(
        values, config_file, secret_dir, "loopback"
    )
    if (
        current_snapshot != live_snapshot
        or _runtime_services(current_snapshot) != tuple(runtime_services)
        or current_content_snapshots != dict(live_content_snapshots)
        or current_images != list(live_images)
    ):
        raise ResilienceError(
            "Gate A live data or images changed during resilience recovery"
        )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=runtime_services,
    )
    gatea._ensure_services_healthy(rows, *runtime_services)
    gatea._validate_loopback_publishers(rows, port)
    payload = _validate_existing_resilience_payload(
        payload,
        candidate_sha=candidate_sha,
        image_id=image_id,
        deployment_record=revalidated_deployment,
        representative_candidate_sha=representative_candidate_sha,
        representative_image_id=representative_image_id,
        representative_record_sha256=representative_record_sha256,
        representative_payload=revalidated_representative,
        live_snapshot=current_snapshot,
        live_content_snapshots=current_content_snapshots,
        live_images=current_images,
        runtime_services=runtime_services,
        runtime_acceptance=revalidated_acceptance,
    )
    _complete_existing_resilience_publication(evidence)
    return payload


def execute(
    *,
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    representative_record: Path | None,
    record_dir: Path,
    wait_timeout: int,
    runtime_acceptance_record: Path | None = None,
    confirm_runtime_acceptance_record_sha256: str | None = None,
    acceptance_record_dir: Path | None = None,
) -> dict[str, Any]:
    """执行两次依赖故障、应用重启、数据保持与日志安全验证。"""

    if os.geteuid() != 0:
        raise ResilienceError("Gate A resilience drill must run as root")
    selected_acceptance_record_dir = acceptance_record_dir or (
        runtime_acceptance_record.parent
        if runtime_acceptance_record is not None
        else gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR
    )
    gatea.reject_unresolved_candidate_transition_journals(
        record_dir=release_record_dir,
    )
    gatea.reject_unresolved_m9_acceptance_sidecars(
        record_dir=selected_acceptance_record_dir,
    )
    if (
        runtime_acceptance_record is not None
        and gatea._lexical_absolute_path(runtime_acceptance_record.parent)
        != gatea._lexical_absolute_path(selected_acceptance_record_dir)
    ):
        raise ResilienceError(
            "Gate A M9 runtime acceptance record must use the guarded directory"
        )
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        require_available_port=False,
    )
    _validate_resilience_record_directory(record_dir)
    image_id = gatea.validate_app_image(values)
    candidate_sha = gatea._candidate_sha(values)
    record_path = _record_path(record_dir, candidate_sha)
    existing_record = _load_existing_resilience_record(record_path)
    deployment_record = gatea._require_deployment_record(
        record_dir=release_record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    representative_candidate_sha, representative_image_id = _representative_binding(
        deployment_record, candidate_sha, image_id
    )
    selected_representative_record = _representative_record_path(
        representative_record,
        deployment_record,
        representative_candidate_sha,
    )
    require_m7_record = (
        deployment_record.get("record_type") == "existing-database-upgrade"
        and (
            deployment_record.get("source_version") == 7
            or _is_m9_candidate_adoption(deployment_record)
        )
    )
    _validate_representative_record_file(selected_representative_record)
    representative_record_sha256 = gatea._sha256(selected_representative_record)
    representative_payload = _load_representative_record(
        selected_representative_record,
        representative_candidate_sha,
        representative_image_id,
        require_m7_record=require_m7_record,
    )
    if require_m7_record:
        _validate_m7_credentials_artifact(
            record_path=selected_representative_record,
            payload=representative_payload,
        )
    if gatea._sha256(selected_representative_record) != representative_record_sha256:
        raise ResilienceError(
            "Gate A representative data record changed during validation"
        )
    mysql_rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=("mysql",),
    )
    gatea._ensure_services_healthy(mysql_rows, "mysql")
    before_snapshot = gatea_backup._source_snapshot(
        values, config_file, secret_dir, "loopback"
    )
    services = _runtime_services(before_snapshot)
    runtime_acceptance: _RuntimeAcceptanceEvidence | None = None
    if services == M9_SERVICES:
        if (
            runtime_acceptance_record is None
            or confirm_runtime_acceptance_record_sha256 is None
        ):
            raise ResilienceError(
                "Gate A M9 resilience requires the runtime acceptance record "
                "and its confirmed digest"
            )
        runtime_acceptance = _validate_runtime_acceptance_record(
            path=runtime_acceptance_record,
            confirmed_sha256=confirm_runtime_acceptance_record_sha256,
            candidate_sha=candidate_sha,
            image_id=image_id,
            deployment_record=deployment_record,
            representative_payload=representative_payload,
            representative_record_sha256=representative_record_sha256,
            release_record_dir=release_record_dir,
            runtime_services=services,
        )
    before_content_snapshots = _database_content_snapshots(
        snapshot=before_snapshot,
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
    )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=services,
    )
    gatea._ensure_services_healthy(rows, *services)
    gatea._validate_loopback_publishers(
        rows, int(values.get("GATEA_LOOPBACK_PORT", "18080"))
    )
    before_images = gatea_backup._source_image_manifest(
        values, config_file, secret_dir, "loopback"
    )
    port = int(values.get("GATEA_LOOPBACK_PORT", "18080"))
    if existing_record is not None:
        return _recover_existing_resilience_record(
            evidence=existing_record,
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            release_record_dir=release_record_dir,
            acceptance_record_dir=selected_acceptance_record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
            deployment_record=deployment_record,
            representative_candidate_sha=representative_candidate_sha,
            representative_image_id=representative_image_id,
            representative_record=selected_representative_record,
            representative_record_sha256=representative_record_sha256,
            representative_payload=representative_payload,
            require_m7_record=require_m7_record,
            live_snapshot=before_snapshot,
            live_content_snapshots=before_content_snapshots,
            live_images=before_images,
            runtime_services=services,
            runtime_acceptance_record=runtime_acceptance_record,
            confirm_runtime_acceptance_record_sha256=(
                confirm_runtime_acceptance_record_sha256
            ),
            runtime_acceptance=runtime_acceptance,
            port=port,
        )
    started_at_datetime = datetime.now(timezone.utc)
    if (
        runtime_acceptance is not None
        and started_at_datetime
        < _parse_runtime_acceptance_completed_at(runtime_acceptance.completed_at)
    ):
        raise ResilienceError(
            "Gate A resilience drill starts before M9 runtime acceptance completed"
        )
    started_at = started_at_datetime.isoformat()
    drills: list[dict[str, Any]] = []
    operation_error: BaseException | None = None
    transition_error: BaseException | None = None
    recovery_error: BaseException | None = None
    with _resilience_termination_guard() as termination:
        try:
            try:
                for service in ("mysql", "redis"):
                    drills.append(
                        _dependency_drill(
                            service=service,
                            values=values,
                            config_file=config_file,
                            secret_dir=secret_dir,
                            port=port,
                            timeout=wait_timeout,
                        )
                    )
                app_restart = _app_restart_drill(
                    values=values,
                    config_file=config_file,
                    secret_dir=secret_dir,
                    port=port,
                    timeout=wait_timeout,
                )
            except BaseException as error:
                operation_error = error
                app_restart = {}
        finally:
            # 该层 finally 覆盖 drill 的成功、失败及异步终止；即使状态切换
            # 本身被首个终止信号命中，内层 finally 仍会执行完整恢复。
            try:
                termination.begin_recovery()
            except BaseException as error:
                transition_error = error
            finally:
                try:
                    _restore_all_services(
                        values=values,
                        config_file=config_file,
                        secret_dir=secret_dir,
                        services=services,
                        timeout=wait_timeout,
                    )
                except BaseException as error:
                    recovery_error = error

        if recovery_error is not None:
            if isinstance(recovery_error, KeyboardInterrupt):
                raise recovery_error
            raise ResilienceError(
                "Gate A resilience recovery failed"
            ) from recovery_error
        if operation_error is not None:
            if isinstance(
                operation_error,
                (KeyboardInterrupt, gatea.GateAOperationInterrupted),
            ):
                raise operation_error
            if isinstance(operation_error, ResilienceError):
                raise operation_error
            raise ResilienceError(
                "Gate A resilience drill failed safely"
            ) from operation_error
        if transition_error is not None:
            if isinstance(
                transition_error,
                (KeyboardInterrupt, gatea.GateAOperationInterrupted),
            ):
                raise transition_error
            raise ResilienceError(
                "Gate A resilience recovery transition failed"
            ) from transition_error
        if termination.interruption is not None:
            raise termination.interruption

    after_snapshot = gatea_backup._source_snapshot(
        values, config_file, secret_dir, "loopback"
    )
    after_content_snapshots = _database_content_snapshots(
        snapshot=after_snapshot,
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
    )
    after_images = gatea_backup._source_image_manifest(
        values, config_file, secret_dir, "loopback"
    )
    if after_snapshot != before_snapshot:
        raise ResilienceError("Gate A data changed during the resilience drill")
    if _runtime_services(after_snapshot) != services:
        raise ResilienceError("Gate A migration chain changed during resilience drill")
    if after_content_snapshots != before_content_snapshots:
        raise ResilienceError(
            "Gate A database content changed during the resilience drill"
        )
    if after_images != before_images:
        raise ResilienceError("Gate A images changed during the resilience drill")
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=services,
    )
    gatea._ensure_services_healthy(rows, *services)
    gatea._validate_loopback_publishers(rows, port)
    log_rotation = _log_rotation_contract(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=services,
    )
    log_observability = _scan_logs(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        services=services,
    )
    if runtime_acceptance is not None:
        assert runtime_acceptance_record is not None
        assert confirm_runtime_acceptance_record_sha256 is not None
        runtime_acceptance = _validate_runtime_acceptance_record(
            path=runtime_acceptance_record,
            confirmed_sha256=confirm_runtime_acceptance_record_sha256,
            candidate_sha=candidate_sha,
            image_id=image_id,
            deployment_record=deployment_record,
            representative_payload=representative_payload,
            representative_record_sha256=representative_record_sha256,
            release_record_dir=release_record_dir,
            runtime_services=services,
            expected=runtime_acceptance,
        )
    payload = {
        "schema_version": 2 if runtime_acceptance is not None else 1,
        "candidate_sha": candidate_sha,
        "image_id": image_id,
        "representative_candidate_sha": representative_candidate_sha,
        "representative_image_id": representative_image_id,
        "representative_record_sha256": representative_record_sha256,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "dependency_drills": drills,
        "app_restart": app_restart,
        "database_snapshot_unchanged": True,
        "database_content_snapshots": after_content_snapshots,
        "database_content_snapshots_unchanged": True,
        "image_manifest_unchanged": True,
        "image_file_count": len(after_images),
        "source_services_healthy": True,
        "runtime_services": list(services),
        "table_sweeper_included": "table-sweeper" in services,
        "loopback_only": True,
        "log_rotation": log_rotation,
        "log_observability": log_observability,
        "pii_recorded": False,
        "secret_values_recorded": False,
        "passed": True,
    }
    if runtime_acceptance is not None:
        payload.update(
            {
                "runtime_acceptance_record_sha256": (
                    runtime_acceptance.record_sha256
                ),
                "runtime_acceptance_attempt_id_sha256": (
                    runtime_acceptance.attempt_id_sha256
                ),
                "runtime_acceptance_completed_at": runtime_acceptance.completed_at,
            }
        )
    _write_resilience_record(record_path, payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
    parser.add_argument(
        "--release-record-dir", type=Path, default=gatea.DEFAULT_RECORD_DIR
    )
    parser.add_argument(
        "--representative-record",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--runtime-acceptance-record",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--acceptance-record-dir",
        type=Path,
        default=gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR,
    )
    parser.add_argument(
        "--confirm-runtime-acceptance-record-sha256",
        default=None,
    )
    parser.add_argument("--record-dir", type=Path, default=DEFAULT_RECORD_DIR)
    parser.add_argument("--wait-timeout", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if not arguments.apply:
            raise ResilienceError("Gate A resilience drill requires --apply")
        if not 60 <= arguments.wait_timeout <= 600:
            raise ResilienceError("Gate A resilience wait timeout is invalid")
        with gatea.operation_lock(), gatea.operation_termination_guard():
            execute(
                config_file=arguments.config_file,
                secret_dir=arguments.secret_dir,
                release_record_dir=arguments.release_record_dir,
                representative_record=arguments.representative_record,
                record_dir=arguments.record_dir,
                wait_timeout=arguments.wait_timeout,
                runtime_acceptance_record=arguments.runtime_acceptance_record,
                confirm_runtime_acceptance_record_sha256=(
                    arguments.confirm_runtime_acceptance_record_sha256
                ),
                acceptance_record_dir=arguments.acceptance_record_dir,
            )
    except (
        ResilienceError,
        gatea.GateAError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Gate A resilience drill failed: {error}", file=sys.stderr)
        return 1
    print("Gate A dependency, restart, data, and log resilience drill passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
