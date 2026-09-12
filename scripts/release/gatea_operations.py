#!/usr/bin/env python3
"""Gate A 持久部署的受控预检与生命周期操作。

本模块不生成、读取或输出 Secret 值。写操作固定到经过验证的 Compose
文件、完整 Git SHA 镜像与受保护配置；当前写操作只允许 loopback，空库首次迁移与
专用既有库升级分别生成可验证 Record，并提供既有库的只读状态采样。不提供删卷、
来源卷恢复、TLS 切换或公开发布操作。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GATEA_ROOT = REPOSITORY_ROOT / "deploy" / "gatea"
BASE_COMPOSE = GATEA_ROOT / "compose.yml"
MODE_COMPOSE = {
    "loopback": GATEA_ROOT / "compose.loopback.yml",
    "tls": GATEA_ROOT / "compose.tls.yml",
}
BOOTSTRAP_COMPOSE = GATEA_ROOT / "compose.bootstrap.yml"
DEFAULT_CONFIG_FILE = Path("/etc/pinkdoohub/gatea/config.env")
DEFAULT_SECRET_DIR = Path("/etc/pinkdoohub/gatea/secrets")
DEFAULT_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/releases")
DEFAULT_M9_ACCEPTANCE_RECORD_DIR = Path(
    "/srv/pinkdoohub/gatea/records/m9-acceptance"
)
DEFAULT_OPERATION_LOCK_FILE = Path("/run/lock/pinkdoohub-gatea-operation.lock")
CURRENT_FINALIZATION_PENDING_SUFFIX = "current-finalization.pending.json"
CANDIDATE_TRANSITION_PENDING_KINDS = (
    ("candidate-stage", "candidate-stage.pending.json"),
    ("config-activation", "config-activation.pending.json"),
    ("config-rollback", "config-rollback.pending.json"),
    ("current-finalization", CURRENT_FINALIZATION_PENDING_SUFFIX),
    ("acceptance-retirement", "acceptance-retirement.pending.json"),
)
CANDIDATE_TRANSITION_PENDING_SUFFIXES = tuple(
    suffix for _, suffix in CANDIDATE_TRANSITION_PENDING_KINDS
)
CANDIDATE_TRANSITION_PENDING_SUFFIX_BY_KIND = dict(
    CANDIDATE_TRANSITION_PENDING_KINDS
)
# ``failed-acceptance-retirement`` is deliberately an allowance-only kind.  The
# on-disk journal keeps the established ``acceptance-retirement`` suffix, while
# app-up can distinguish this narrowly validated recovery from every ordinary
# lifecycle invocation.
CANDIDATE_TRANSITION_PENDING_SUFFIX_BY_KIND[
    "failed-acceptance-retirement"
] = "acceptance-retirement.pending.json"
M9_ACCEPTANCE_SIDECAR_PREFIX = "gatea-m9-runtime-acceptance-"
M9_ACCEPTANCE_PENDING_SUFFIX = ".json.pending"
M9_ACCEPTANCE_COMPLETE_SUFFIX = ".json.complete"
M9_ACCEPTANCE_SIDECAR_SUFFIXES = (
    M9_ACCEPTANCE_PENDING_SUFFIX,
    M9_ACCEPTANCE_COMPLETE_SUFFIX,
)
EXPECTED_SECRET_FILES = (
    "mysql_app_password",
    "mysql_root_password",
    "redis_password",
    "jwt_secret",
)
APP_RUNTIME_SECRET_GID = 10001
EXPECTED_SECRET_METADATA = {
    "mysql_app_password": (0o440, APP_RUNTIME_SECRET_GID),
    "mysql_root_password": (0o400, 0),
    "redis_password": (0o440, APP_RUNTIME_SECRET_GID),
    "jwt_secret": (0o440, APP_RUNTIME_SECRET_GID),
}
REQUIRED_CONFIG_KEYS = (
    "GATEA_APP_IMAGE",
    "GATEA_API_HOST",
    "APP_VERSION",
    "APP_ENV",
    "APP_DEBUG",
    "DB_ENGINE",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "PRODUCT_IMAGE_UPLOAD_DIR",
    "PRODUCT_IMAGE_BASE_URL",
    "JWT_ALGORITHM",
)
FORBIDDEN_CONFIG_KEYS = (
    "DB_PASSWORD",
    "JWT_SECRET_KEY",
    "REDIS_URL",
    "MYSQL_ROOT_PASSWORD",
    "PINKDOOHUB_BOOTSTRAP_PASSWORD",
)
APP_IMAGE_PATTERN = re.compile(r"^pinkdoohub-gatea:[0-9a-f]{40}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
BACKUP_ID_PATTERN = re.compile(r"^[0-9]{8}t[0-9]{6}z$")
APPROVED_SOURCE_M2_CHAIN = (
    "0_20260810101218_init.py",
    "1_20260813130455_add_order_tables.py",
    "2_20260814104655_add_inventory_transactions.py",
)
APPROVED_TARGET_M7_CHAIN = APPROVED_SOURCE_M2_CHAIN + (
    "3_20260902125032_phase95_external_identity.py",
    "4_20260905162243_add_wallet_payment_refund.py",
    "5_20260906094653_add_reservations.py",
    "6_20260906123000_add_color_selectable_kits.py",
    "7_20260907190000_add_reservation_settings.py",
)
APPROVED_SOURCE_M7_CHAIN = APPROVED_TARGET_M7_CHAIN
APPROVED_TARGET_M8_CHAIN = APPROVED_TARGET_M7_CHAIN + (
    "8_20260908140000_add_bead_color_swatch_hex.py",
)
APPROVED_TARGET_M9_CHAIN = APPROVED_TARGET_M8_CHAIN + (
    "9_20260910180000_add_table_sessions.py",
)
HOST_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
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
M9_RECONCILE_KEYS = frozenset(
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
M9_STATIC_SNAPSHOT_KEYS = (
    "aerich_versions",
    "tables",
    "columns",
    "statistics",
    "constraints",
    "columns_sha256",
    "statistics_sha256",
    "constraints_sha256",
)
M9_ADOPTION_TRANSITION_KIND = "m9-candidate-adoption"
MAX_M9_ADOPTION_RECORD_BYTES = 4 * 1024 * 1024
M9_ADOPTION_CONTENT_SNAPSHOT_KEYS = frozenset(
    {"content_sha256", "profile", "schema_version"}
)
M9_ADOPTION_UPGRADE_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "transition_kind",
        "record_type",
        "passed",
        "candidate_sha",
        "image_id",
        "source_candidate_sha",
        "source_image_id",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "source_version",
        "target_version",
        "source_aerich_versions",
        "target_aerich_versions",
        "backup_id",
        "manifest_sha256",
        "stage_record_sha256",
        "activation_record_sha256",
        "predecessor_stage_record_sha256",
        "predecessor_activation_record_sha256",
        "predecessor_upgrade_record_sha256",
        "predecessor_upgrade_evidence_sha256",
        "predecessor_upgrade_plan_replay_record_sha256",
        "acceptance_retirement_record_sha256",
        "backup_record_sha256",
        "restore_record_sha256",
        "runtime_preflight",
        "started_at",
        "completed_at",
        "evidence_path",
        "evidence_sha256",
        "source_database_snapshot",
        "final_database_snapshot",
        "source_image_manifest",
        "final_image_manifest",
        "source_m7_content_snapshot",
        "final_m7_content_snapshot",
        "source_m8_swatch_content_snapshot",
        "final_m8_swatch_content_snapshot",
        "source_m9_table_content_snapshot",
        "final_m9_table_content_snapshot",
        "database_changes_applied",
        "migrations_applied",
        "table_reconcile",
    }
)
M9_ADOPTION_EVIDENCE_RECORD_KEYS = (
    M9_ADOPTION_UPGRADE_RECORD_KEYS
    - frozenset({"passed", "evidence_path", "evidence_sha256"})
) | frozenset({"status", "current_stage", "stopped_source_verified", "steps"})
M9_ADOPTION_REPLAY_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "transition_kind",
        "record_type",
        "passed",
        "candidate_sha",
        "source_candidate_sha",
        "source_version",
        "image_id",
        "backup_id",
        "manifest_sha256",
        "lineage_source_candidate_sha",
        "lineage_source_image_id",
        "acceptance_retirement_record_sha256",
        "database_changes_applied",
        "migrations_applied",
        "database_snapshot",
        "m8_swatch_content_snapshot",
        "image_manifest",
        "table_reconcile",
        "upgrade_record_sha256",
        "evidence_sha256",
        "result",
        "completed_at",
        "secret_values_recorded",
    }
)
LEGACY_M7_APP_COMMAND = [
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--no-server-header",
]
INITIAL_SCHEMA_COUNT_COMMAND = (
    'MYSQL_PWD="$(cat /run/secrets/mysql_root_password)" '
    "mysql --batch --skip-column-names --host=127.0.0.1 --user=root "
    '--execute="SELECT COUNT(*) FROM information_schema.tables '
    'WHERE table_schema = DATABASE();" "$MYSQL_DATABASE"'
)
DATABASE_STATUS_COMMAND = r"""MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --raw --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SET SESSION group_concat_max_len = 1048576;
SELECT JSON_OBJECT(
  'aerich_versions', COALESCE((SELECT GROUP_CONCAT(version ORDER BY id SEPARATOR ',') FROM aerich), ''),
  'tables', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()),
  'columns', (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()),
  'statistics', (SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE()),
  'constraints', (SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema = DATABASE()),
  'columns_sha256', SHA2(COALESCE((
    SELECT GROUP_CONCAT(
      CONCAT_WS(':', table_name, ordinal_position, column_name, column_type,
                is_nullable, COALESCE(column_default, '<NULL>'), extra)
      ORDER BY table_name, ordinal_position SEPARATOR '\n'
    )
    FROM information_schema.columns WHERE table_schema = DATABASE()
  ), ''), 256),
  'statistics_sha256', SHA2(COALESCE((
    SELECT GROUP_CONCAT(
      CONCAT_WS(':', table_name, index_name, non_unique, seq_in_index,
                column_name, COALESCE(sub_part, '<NULL>'))
      ORDER BY table_name, index_name, seq_in_index SEPARATOR '\n'
    )
    FROM information_schema.statistics WHERE table_schema = DATABASE()
  ), ''), 256),
  'constraints_sha256', SHA2(COALESCE((
    SELECT GROUP_CONCAT(
      CONCAT_WS(':', table_name, constraint_name, constraint_type)
      ORDER BY table_name, constraint_name SEPARATOR '\n'
    )
    FROM information_schema.table_constraints WHERE table_schema = DATABASE()
  ), ''), 256),
  'users', (SELECT COUNT(*) FROM users),
  'products', (SELECT COUNT(*) FROM products),
  'experience_options', (SELECT COUNT(*) FROM experience_options),
  'product_images', (SELECT COUNT(*) FROM product_images),
  'product_kits', (SELECT COUNT(*) FROM product_kits),
  'kit_stock', (SELECT COALESCE(SUM(stock), 0) FROM product_kits),
  'orders', (SELECT COUNT(*) FROM orders),
  'order_items', (SELECT COUNT(*) FROM order_items),
  'order_total', (SELECT CAST(COALESCE(SUM(total_amount), 0) AS CHAR) FROM orders),
  'inventory_transactions', (SELECT COUNT(*) FROM inventory_transactions),
  'inventory_change', (SELECT COALESCE(SUM(change_quantity), 0) FROM inventory_transactions),
  'audit_logs', (SELECT COUNT(*) FROM audit_logs)
);
SQL"""
LIFECYCLE_COMMANDS = (
    "preflight",
    "database-status",
    "infra-up",
    "initial-migrate",
    "app-up",
    "status",
    "safe-stop",
)


class GateAError(RuntimeError):
    """不包含 Secret、Token、密码或连接串的 Gate A 操作错误。"""


class GateAOperationInterrupted(GateAError):
    """可恢复的终止信号已请求中止当前 Gate A 操作。"""


@dataclass(frozen=True)
class CandidateTransitionRecoveryAllowance:
    """只允许一个已由所属状态机验证的精确 candidate pending。"""

    path: Path
    kind: str
    candidate_sha: str
    runtime_candidate_sha: str | None = None


@dataclass(frozen=True)
class M9AcceptanceSidecarRecoveryAllowance:
    """只允许一个候选由 acceptance 状态机验证的精确 sidecar。"""

    candidate_sha: str
    pending_path: Path | None = None
    complete_path: Path | None = None


@dataclass(frozen=True)
class SupersededCandidatePendingRecoveryAllowance:
    """M9 候选接管时，已被取代 journal 的不可变身份。"""

    candidate_sha: str
    path: Path
    sha256: str | None
    expected_exists: bool


@dataclass(frozen=True)
class M9CandidateTakeoverRecoveryAllowance:
    """只允许 C 接管 B 的 prepared retirement 时恢复既有 A runtime。

    这个 bundle 不是通用的多 pending 豁免：它把运行中的 A、当前 C 的
    own retirement、可能仍存在的 B retirement 和 A 的 acceptance sidecar
    固定在一次受控恢复中。B unlink 之后调用方必须显式把
    ``superseded_pending.expected_exists`` 设为 ``False``；届时目录中只能
    留下 C 的 own pending。
    """

    runtime_candidate_sha: str
    current_transition: CandidateTransitionRecoveryAllowance
    current_pending_sha256: str
    superseded_pending: SupersededCandidatePendingRecoveryAllowance
    acceptance_sidecar: M9AcceptanceSidecarRecoveryAllowance | None


@contextmanager
def operation_lock(
    *,
    _path: Path = DEFAULT_OPERATION_LOCK_FILE,
) -> Iterator[None]:
    """互斥执行会改变 Gate A 持久环境的受控操作。"""

    descriptor: int | None = None
    locked = False
    try:
        try:
            descriptor = os.open(
                _path,
                os.O_RDWR
                | os.O_CREAT
                | os.O_CLOEXEC
                | os.O_NOFOLLOW,
                0o600,
            )
            metadata = os.fstat(descriptor)
        except OSError as error:
            raise GateAError("Gate A operation lock is unavailable") from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise GateAError("Gate A operation lock is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as error:
            raise GateAError("Another Gate A operation is active") from error
        locked = True
        yield
    finally:
        if descriptor is not None:
            try:
                if locked:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


class _OperationTerminationController:
    """工作阶段立即中止，恢复阶段延迟 HUP/TERM/SIGINT。"""

    def __init__(self) -> None:
        self.work_interruption: BaseException | None = None
        self.deferred_interruption: BaseException | None = None
        self._recovering = False
        self._previous_handlers: dict[int, Any] = {}
        self._installed_signals: list[int] = []

    def begin_recovery(self) -> None:
        """在任何补偿动作前切换信号语义。"""

        self._recovering = True

    def interrupt(self, signum: int, _frame: object) -> None:
        signal_name = signal.Signals(signum).name
        interruption: BaseException = (
            KeyboardInterrupt(f"Gate A operation received {signal_name}")
            if signum == signal.SIGINT
            else GateAOperationInterrupted(
                f"Gate A operation received {signal_name} and is recovering"
            )
        )
        if self._recovering:
            if self.deferred_interruption is None:
                self.deferred_interruption = interruption
            return

        # 先切换相位再抛出，确保由本信号触发的 finally 已处于恢复语义。
        self._recovering = True
        self.work_interruption = interruption
        raise interruption

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


@contextmanager
def operation_termination_guard() -> Iterator[_OperationTerminationController]:
    """在工作开始前安装统一终止信号状态机，并在退出时还原。"""

    controller = _OperationTerminationController()
    body_error: BaseException | None = None
    controller.install()
    try:
        try:
            yield controller
        except BaseException as error:
            body_error = error
    finally:
        controller.restore_handlers()
    if body_error is not None:
        raise body_error
    if controller.work_interruption is not None:
        raise controller.work_interruption
    if controller.deferred_interruption is not None:
        raise controller.deferred_interruption


def parse_env_file(path: Path) -> dict[str, str]:
    """读取只允许简单 KEY=VALUE 的非 Secret 配置文件。"""

    if not path.is_file():
        raise GateAError("Gate A config file is unavailable")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or "=" not in line:
            raise GateAError(
                f"Gate A config line {line_number} must use plain KEY=VALUE"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise GateAError(f"Gate A config line {line_number} has an invalid key")
        if key in values:
            raise GateAError(f"Gate A config contains duplicate key {key}")
        values[key] = value.strip()
    return values


def validate_config_values(values: Mapping[str, str], *, mode: str) -> None:
    """验证非 Secret 配置的生产语义，不在错误中回显值。"""

    if mode not in MODE_COMPOSE:
        raise GateAError("Gate A mode must be loopback or tls")

    missing = [key for key in REQUIRED_CONFIG_KEYS if not values.get(key)]
    if missing:
        raise GateAError(f"Gate A config is missing required keys: {', '.join(missing)}")

    forbidden = [key for key in FORBIDDEN_CONFIG_KEYS if key in values]
    if forbidden:
        raise GateAError(
            f"Gate A config must not contain Secret keys: {', '.join(forbidden)}"
        )

    if APP_IMAGE_PATTERN.fullmatch(values["GATEA_APP_IMAGE"]) is None:
        raise GateAError("GATEA_APP_IMAGE must use an immutable full Git SHA tag")
    if HOST_PATTERN.fullmatch(values["GATEA_API_HOST"]) is None:
        raise GateAError("GATEA_API_HOST must be a DNS hostname without scheme or path")
    if values["APP_ENV"] != "production" or values["APP_DEBUG"].lower() != "false":
        raise GateAError("Gate A must use production semantics with APP_DEBUG=false")
    if values["DB_ENGINE"] != "mysql":
        raise GateAError("Gate A DB_ENGINE must be mysql")
    if values["DB_HOST"] != "mysql" or values["DB_PORT"] != "3306":
        raise GateAError("Gate A database must use the internal mysql service")
    if values["PRODUCT_IMAGE_UPLOAD_DIR"] != "/data/images":
        raise GateAError("Gate A product images must use the persistent image volume")
    if values["JWT_ALGORITHM"] != "HS256":
        raise GateAError("Gate A JWT_ALGORITHM must be HS256")

    image_url = urlsplit(values["PRODUCT_IMAGE_BASE_URL"])
    if (
        image_url.scheme != "https"
        or image_url.hostname != values["GATEA_API_HOST"]
        or image_url.username is not None
        or image_url.password is not None
        or image_url.query
        or image_url.fragment
        or image_url.path != "/uploads/products"
    ):
        raise GateAError(
            "PRODUCT_IMAGE_BASE_URL must use the approved HTTPS Gate A image path"
        )

    if mode == "loopback":
        raw_port = values.get("GATEA_LOOPBACK_PORT", "18080")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise GateAError("GATEA_LOOPBACK_PORT must be an integer") from error
        if not 1024 <= port <= 65535:
            raise GateAError("GATEA_LOOPBACK_PORT must be an unprivileged TCP port")
    else:
        for key in ("GATEA_LETSENCRYPT_DIR", "GATEA_ACME_CHALLENGE_DIR"):
            if not values.get(key):
                raise GateAError(f"TLS mode requires {key}")


def _validate_root_file(
    path: Path,
    expected_mode: int,
    description: str,
    *,
    expected_gid: int = 0,
) -> None:
    """验证 Root 所有普通文件及其精确权限，不读取内容。"""

    try:
        metadata = path.stat()
    except FileNotFoundError as error:
        raise GateAError(f"{description} is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise GateAError(f"{description} must be a regular file")
    if metadata.st_uid != 0 or metadata.st_gid != expected_gid:
        raise GateAError(f"{description} has an unexpected owner or group")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise GateAError(f"{description} has unsafe permissions")


def _validate_root_directory(
    path: Path,
    expected_mode: int,
    description: str,
) -> None:
    """验证 Root 所有目录及其精确权限。"""

    try:
        metadata = path.stat()
    except FileNotFoundError as error:
        raise GateAError(f"{description} is unavailable") from error
    if not stat.S_ISDIR(metadata.st_mode):
        raise GateAError(f"{description} must be a directory")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise GateAError(f"{description} must be owned by root:root")
    if stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise GateAError(f"{description} has unsafe permissions")


def validate_secret_metadata(secret_dir: Path) -> None:
    """只检查 Secret 文件元数据和非空大小，不读取 Secret。"""

    _validate_root_directory(secret_dir, 0o700, "Gate A Secret directory")
    for name in EXPECTED_SECRET_FILES:
        path = secret_dir / name
        expected_mode, expected_gid = EXPECTED_SECRET_METADATA[name]
        _validate_root_file(
            path,
            expected_mode,
            f"Gate A Secret file {name}",
            expected_gid=expected_gid,
        )
        if path.stat().st_size == 0:
            raise GateAError(f"Gate A Secret file {name} is empty")


def compose_command(
    *,
    config_file: Path,
    mode: str,
    arguments: Sequence[str],
    include_bootstrap: bool = False,
    profiles: Sequence[str] = (),
) -> list[str]:
    """构造绑定精确配置与 mode override 的 Compose 命令。"""

    if mode not in MODE_COMPOSE:
        raise GateAError("Gate A mode must be loopback or tls")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(config_file),
        "--file",
        str(BASE_COMPOSE),
        "--file",
        str(MODE_COMPOSE[mode]),
    ]
    if include_bootstrap:
        command.extend(("--file", str(BOOTSTRAP_COMPOSE)))
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return command


def _operation_environment(
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> dict[str, str]:
    return os.environ | dict(values) | {
        "GATEA_CONFIG_FILE": str(config_file),
        "GATEA_SECRET_DIR": str(secret_dir),
    }


def _run_compose(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    arguments: Sequence[str],
    profiles: Sequence[str] = (),
    capture_output: bool = False,
    check: bool = True,
    start_new_session: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        compose_command(
            config_file=config_file,
            mode=mode,
            arguments=arguments,
            profiles=profiles,
        ),
        check=check,
        cwd=REPOSITORY_ROOT,
        env=_operation_environment(values, config_file, secret_dir),
        text=True,
        capture_output=capture_output,
        start_new_session=start_new_session,
        input=input_text,
    )


def _assert_loopback_port_available(port: int) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise GateAError("Gate A loopback port is already in use") from error
    finally:
        listener.close()


def _validated_inputs(
    *,
    config_file: Path,
    secret_dir: Path,
    mode: str,
    require_available_port: bool,
    require_secrets: bool = True,
) -> dict[str, str]:
    _validate_root_file(config_file, 0o640, "Gate A config file")
    values = parse_env_file(config_file)
    validate_config_values(values, mode=mode)
    if require_secrets:
        validate_secret_metadata(secret_dir)
    if shutil.which("docker") is None:
        raise GateAError("Docker CLI is unavailable")

    if mode == "loopback" and require_available_port:
        _assert_loopback_port_available(
            int(values.get("GATEA_LOOPBACK_PORT", "18080"))
        )
    elif mode == "tls":
        cert_dir = (
            Path(values["GATEA_LETSENCRYPT_DIR"])
            / "live"
            / values["GATEA_API_HOST"]
        )
        _validate_root_file(cert_dir / "fullchain.pem", 0o644, "TLS certificate")
        _validate_root_file(cert_dir / "privkey.pem", 0o600, "TLS private key")
        acme_dir = Path(values["GATEA_ACME_CHALLENGE_DIR"])
        if not acme_dir.is_dir():
            raise GateAError("ACME challenge directory is unavailable")

    _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=("config", "--quiet"),
    )
    return values


def _require_loopback_write_mode(mode: str) -> None:
    if mode != "loopback":
        raise GateAError(
            "Gate A lifecycle writes are currently restricted to loopback mode"
        )


def _candidate_sha(values: Mapping[str, str]) -> str:
    return values["GATEA_APP_IMAGE"].rsplit(":", 1)[1]


def _lexical_absolute_path(path: Path) -> Path:
    """规范化路径但不跟随可能由攻击者控制的符号链接。"""

    return Path(os.path.abspath(os.fspath(path)))


def _direct_child_paths_with_suffixes(
    *,
    record_dir: Path,
    suffixes: Sequence[str],
) -> tuple[Path, ...]:
    """按后缀枚举受保护 Record 目录的直接子项，不跟随链接。"""

    try:
        entries = tuple(record_dir.iterdir())
    except OSError as error:
        raise GateAError("Gate A pending journals could not be inspected") from error
    return tuple(
        entry
        for entry in entries
        if any(entry.name.endswith(suffix) for suffix in suffixes)
    )


def _candidate_transition_pending_paths(record_dir: Path) -> tuple[Path, ...]:
    """枚举 release Record 目录直接子项中的所有 candidate pending。"""

    return _direct_child_paths_with_suffixes(
        record_dir=record_dir,
        suffixes=CANDIDATE_TRANSITION_PENDING_SUFFIXES,
    )


def _validate_candidate_transition_recovery_allowance(
    *,
    record_dir: Path,
    candidate_sha: str | None,
    recovery_allowance: CandidateTransitionRecoveryAllowance,
    pending_paths: Sequence[Path],
) -> Path:
    """验证 allowance 只精确指向当前候选的一个普通 pending 文件。"""

    if (
        not isinstance(recovery_allowance, CandidateTransitionRecoveryAllowance)
        or not isinstance(recovery_allowance.path, Path)
        or not isinstance(recovery_allowance.kind, str)
        or not isinstance(recovery_allowance.candidate_sha, str)
        or (
            recovery_allowance.runtime_candidate_sha is not None
            and not isinstance(recovery_allowance.runtime_candidate_sha, str)
        )
    ):
        raise GateAError(
            "Gate A candidate transition recovery allowance is invalid"
        )
    suffix = CANDIDATE_TRANSITION_PENDING_SUFFIX_BY_KIND.get(
        recovery_allowance.kind
    )
    normalized_record_dir = _lexical_absolute_path(record_dir)
    normalized_allowance_path = _lexical_absolute_path(recovery_allowance.path)
    expected_path = normalized_record_dir / (
        f"{recovery_allowance.candidate_sha}.{suffix}"
        if suffix is not None
        else "invalid"
    )
    if (
        suffix is None
        or candidate_sha is None
        or GIT_SHA_PATTERN.fullmatch(candidate_sha) is None
        or GIT_SHA_PATTERN.fullmatch(recovery_allowance.candidate_sha) is None
        or (
            recovery_allowance.kind == "failed-acceptance-retirement"
            and (
                recovery_allowance.runtime_candidate_sha is None
                or GIT_SHA_PATTERN.fullmatch(
                    recovery_allowance.runtime_candidate_sha
                )
                is None
                or recovery_allowance.runtime_candidate_sha
                == recovery_allowance.candidate_sha
            )
        )
        or (
            recovery_allowance.kind != "failed-acceptance-retirement"
            and recovery_allowance.runtime_candidate_sha is not None
        )
        or recovery_allowance.candidate_sha != candidate_sha
        or normalized_allowance_path.parent != normalized_record_dir
        or normalized_allowance_path != expected_path
        or all(
            _lexical_absolute_path(path) != normalized_allowance_path
            for path in pending_paths
        )
    ):
        raise GateAError(
            "Gate A candidate transition recovery allowance is invalid"
        )
    try:
        metadata = normalized_allowance_path.lstat()
    except OSError as error:
        raise GateAError(
            "Gate A candidate transition recovery allowance is invalid"
        ) from error
    if not stat.S_ISREG(metadata.st_mode) or normalized_allowance_path.is_symlink():
        raise GateAError(
            "Gate A candidate transition recovery allowance is invalid"
        )
    return normalized_allowance_path


def reject_unresolved_candidate_transition_journals(
    *,
    record_dir: Path,
    candidate_sha: str | None = None,
    recovery_allowance: CandidateTransitionRecoveryAllowance | None = None,
) -> None:
    """阻断任意候选未收口事务，仅允许一个精确且安全的 own recovery。"""

    if (
        candidate_sha is not None
        and GIT_SHA_PATTERN.fullmatch(candidate_sha) is None
    ):
        raise GateAError("Gate A candidate SHA is invalid")
    pending_paths = _candidate_transition_pending_paths(record_dir)
    allowed_path = (
        _validate_candidate_transition_recovery_allowance(
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            recovery_allowance=recovery_allowance,
            pending_paths=pending_paths,
        )
        if recovery_allowance is not None
        else None
    )
    if any(
        allowed_path is None
        or _lexical_absolute_path(path) != allowed_path
        for path in pending_paths
    ):
        raise GateAError(
            "Gate A candidate transition has an unresolved pending journal"
        )


def _m9_takeover_pending_lstat(path: Path) -> os.stat_result:
    """隔离 takeover journal 的 metadata 读取，供安全单测替换边界。"""

    return path.lstat()


def _m9_takeover_pending_fstat(descriptor: int) -> os.stat_result:
    """隔离 takeover journal 的 fd metadata 读取，供安全单测替换边界。"""

    return os.fstat(descriptor)


def _m9_takeover_pending_identity(metadata: os.stat_result) -> tuple[int, ...]:
    """可重读的 pending journal 必须在校验窗口内保持同一 inode 与内容身份。"""

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


def _require_m9_takeover_pending_metadata(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or metadata.st_size > MAX_M9_ADOPTION_RECORD_BYTES
    ):
        raise GateAError("Gate A M9 candidate takeover recovery allowance is invalid")


def _validate_m9_takeover_pending_file(
    *,
    path: Path,
    expected_sha256: str,
) -> None:
    """稳定读取并摘要绑定 root-only retirement journal。"""

    descriptor: int | None = None
    try:
        initial_metadata = _m9_takeover_pending_lstat(path)
        _require_m9_takeover_pending_metadata(initial_metadata)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before_metadata = _m9_takeover_pending_fstat(descriptor)
        _require_m9_takeover_pending_metadata(before_metadata)
        if _m9_takeover_pending_identity(
            initial_metadata
        ) != _m9_takeover_pending_identity(before_metadata):
            raise GateAError(
                "Gate A M9 candidate takeover recovery allowance is invalid"
            )
        digest = hashlib.sha256()
        remaining = MAX_M9_ADOPTION_RECORD_BYTES + 1
        while remaining > 0:
            block = os.read(descriptor, min(1024 * 1024, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
        if remaining == 0:
            raise GateAError("Gate A M9 candidate takeover recovery allowance is invalid")
        after_metadata = _m9_takeover_pending_fstat(descriptor)
        final_metadata = _m9_takeover_pending_lstat(path)
        _require_m9_takeover_pending_metadata(after_metadata)
        _require_m9_takeover_pending_metadata(final_metadata)
        if (
            _m9_takeover_pending_identity(before_metadata)
            != _m9_takeover_pending_identity(after_metadata)
            or _m9_takeover_pending_identity(before_metadata)
            != _m9_takeover_pending_identity(final_metadata)
            or digest.hexdigest() != expected_sha256
        ):
            raise GateAError(
                "Gate A M9 candidate takeover recovery allowance is invalid"
            )
    except GateAError:
        raise
    except OSError as error:
        raise GateAError(
            "Gate A M9 candidate takeover recovery allowance is invalid"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_m9_candidate_takeover_recovery_allowance(
    *,
    record_dir: Path,
    acceptance_record_dir: Path,
    recovery_allowance: M9CandidateTakeoverRecoveryAllowance,
    pending_paths: Sequence[Path],
    sidecar_paths: Sequence[Path],
) -> None:
    """验证唯一允许的 C+B retirement 恢复集合，拒绝一切泛化多 pending。"""

    invalid = "Gate A M9 candidate takeover recovery allowance is invalid"
    if (
        not isinstance(recovery_allowance, M9CandidateTakeoverRecoveryAllowance)
        or not isinstance(recovery_allowance.runtime_candidate_sha, str)
        or not isinstance(
            recovery_allowance.current_transition,
            CandidateTransitionRecoveryAllowance,
        )
        or not isinstance(
            recovery_allowance.superseded_pending,
            SupersededCandidatePendingRecoveryAllowance,
        )
        or (
            recovery_allowance.acceptance_sidecar is not None
            and not isinstance(
                recovery_allowance.acceptance_sidecar,
                M9AcceptanceSidecarRecoveryAllowance,
            )
        )
    ):
        raise GateAError(invalid)

    current = recovery_allowance.current_transition
    superseded = recovery_allowance.superseded_pending
    runtime_sha = recovery_allowance.runtime_candidate_sha
    if (
        current.kind != "failed-acceptance-retirement"
        or current.runtime_candidate_sha != runtime_sha
        or not isinstance(current.path, Path)
        or not isinstance(current.candidate_sha, str)
        or not isinstance(recovery_allowance.current_pending_sha256, str)
        or not isinstance(superseded.candidate_sha, str)
        or not isinstance(superseded.path, Path)
        or (
            superseded.sha256 is not None
            and not isinstance(superseded.sha256, str)
        )
        or not isinstance(superseded.expected_exists, bool)
        or any(
            GIT_SHA_PATTERN.fullmatch(value) is None
            for value in (
                runtime_sha,
                current.candidate_sha,
                superseded.candidate_sha,
            )
        )
        or (
            superseded.sha256 is not None
            and SHA256_PATTERN.fullmatch(superseded.sha256) is None
        )
        or (superseded.expected_exists and superseded.sha256 is None)
        or SHA256_PATTERN.fullmatch(
            recovery_allowance.current_pending_sha256
        ) is None
        or len(
            {
                runtime_sha,
                current.candidate_sha,
                superseded.candidate_sha,
            }
        )
        != 3
        or (
            recovery_allowance.acceptance_sidecar is not None
            and recovery_allowance.acceptance_sidecar.candidate_sha != runtime_sha
        )
    ):
        raise GateAError(invalid)

    normalized_record_dir = _lexical_absolute_path(record_dir)
    current_path = _lexical_absolute_path(current.path)
    superseded_path = _lexical_absolute_path(superseded.path)
    expected_current_path = normalized_record_dir / (
        f"{current.candidate_sha}.acceptance-retirement.pending.json"
    )
    expected_superseded_path = normalized_record_dir / (
        f"{superseded.candidate_sha}.acceptance-retirement.pending.json"
    )
    if (
        current_path != expected_current_path
        or superseded_path != expected_superseded_path
        or current_path.parent != normalized_record_dir
        or superseded_path.parent != normalized_record_dir
    ):
        raise GateAError(invalid)

    scanned_pending = {_lexical_absolute_path(path) for path in pending_paths}
    expected_pending = {current_path}
    if superseded.expected_exists:
        expected_pending.add(superseded_path)
    if scanned_pending != expected_pending:
        raise GateAError(invalid)

    _validate_m9_takeover_pending_file(
        path=current_path,
        expected_sha256=recovery_allowance.current_pending_sha256,
    )
    if superseded.expected_exists:
        _validate_m9_takeover_pending_file(
            path=superseded_path,
            expected_sha256=superseded.sha256,
        )
    if recovery_allowance.acceptance_sidecar is None:
        if sidecar_paths:
            raise GateAError(invalid)
    else:
        allowed_sidecars = _validate_m9_acceptance_sidecar_recovery_allowance(
            record_dir=acceptance_record_dir,
            recovery_allowance=recovery_allowance.acceptance_sidecar,
            sidecar_paths=sidecar_paths,
        )
        if {
            _lexical_absolute_path(path)
            for path in sidecar_paths
        } != allowed_sidecars:
            raise GateAError(invalid)


def _m9_acceptance_sidecar_paths(record_dir: Path) -> tuple[Path, ...]:
    """枚举安全 acceptance Record 目录中的 pending/complete 直接子项。"""

    try:
        metadata = record_dir.lstat()
    except FileNotFoundError:
        # Candidate lifecycle 在首次 M9 acceptance 之前没有这个目录。
        return ()
    except OSError as error:
        raise GateAError(
            "Gate A M9 acceptance record directory could not be inspected"
        ) from error
    if stat.S_ISLNK(metadata.st_mode):
        raise GateAError("Gate A M9 acceptance record directory must not be a symlink")
    _validate_root_directory(
        record_dir,
        0o755,
        "Gate A M9 acceptance record directory",
    )
    return tuple(
        path
        for path in _direct_child_paths_with_suffixes(
            record_dir=record_dir,
            suffixes=M9_ACCEPTANCE_SIDECAR_SUFFIXES,
        )
        if path.name.startswith(M9_ACCEPTANCE_SIDECAR_PREFIX)
    )


def _validate_m9_acceptance_sidecar_recovery_allowance(
    *,
    record_dir: Path,
    recovery_allowance: M9AcceptanceSidecarRecoveryAllowance,
    sidecar_paths: Sequence[Path],
) -> frozenset[Path]:
    """验证 acceptance own recovery 最多精确豁免 pending 与 complete 各一个。"""

    if (
        not isinstance(recovery_allowance, M9AcceptanceSidecarRecoveryAllowance)
        or not isinstance(recovery_allowance.candidate_sha, str)
        or GIT_SHA_PATTERN.fullmatch(recovery_allowance.candidate_sha) is None
        or not any(
            path is not None
            for path in (
                recovery_allowance.pending_path,
                recovery_allowance.complete_path,
            )
        )
    ):
        raise GateAError("Gate A M9 acceptance recovery allowance is invalid")

    normalized_record_dir = _lexical_absolute_path(record_dir)
    scanned_paths = {
        _lexical_absolute_path(path)
        for path in sidecar_paths
    }
    allowed_paths: set[Path] = set()
    for supplied_path, suffix, allowed_modes in (
        (
            recovery_allowance.pending_path,
            M9_ACCEPTANCE_PENDING_SUFFIX,
            frozenset({0o600}),
        ),
        (
            recovery_allowance.complete_path,
            M9_ACCEPTANCE_COMPLETE_SUFFIX,
            frozenset({0o600, 0o644}),
        ),
    ):
        if supplied_path is None:
            continue
        if not isinstance(supplied_path, Path):
            raise GateAError("Gate A M9 acceptance recovery allowance is invalid")
        normalized_path = _lexical_absolute_path(supplied_path)
        expected_path = normalized_record_dir / (
            f"{M9_ACCEPTANCE_SIDECAR_PREFIX}"
            f"{recovery_allowance.candidate_sha}{suffix}"
        )
        if (
            normalized_path.parent != normalized_record_dir
            or normalized_path != expected_path
            or normalized_path not in scanned_paths
        ):
            raise GateAError("Gate A M9 acceptance recovery allowance is invalid")
        try:
            metadata = _m9_acceptance_sidecar_lstat(normalized_path)
        except OSError as error:
            raise GateAError(
                "Gate A M9 acceptance recovery allowance is invalid"
            ) from error
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or stat.S_IMODE(metadata.st_mode) not in allowed_modes
        ):
            raise GateAError("Gate A M9 acceptance recovery allowance is invalid")
        allowed_paths.add(normalized_path)
    return frozenset(allowed_paths)


def _m9_acceptance_sidecar_lstat(path: Path) -> os.stat_result:
    """隔离 sidecar lstat，便于非 root 单测只替换 metadata 边界。"""

    return path.lstat()


def reject_unresolved_m9_acceptance_sidecars(
    *,
    record_dir: Path,
    recovery_allowance: M9AcceptanceSidecarRecoveryAllowance | None = None,
) -> None:
    """阻断所有 M9 acceptance sidecar，仅容许精确 own recovery。"""

    sidecar_paths = _m9_acceptance_sidecar_paths(record_dir)
    allowed_paths = (
        _validate_m9_acceptance_sidecar_recovery_allowance(
            record_dir=record_dir,
            recovery_allowance=recovery_allowance,
            sidecar_paths=sidecar_paths,
        )
        if recovery_allowance is not None
        else frozenset()
    )
    if any(
        _lexical_absolute_path(path) not in allowed_paths
        for path in sidecar_paths
    ):
        raise GateAError("Gate A M9 acceptance has an unresolved sidecar")


def validate_app_image(
    values: Mapping[str, str],
    *,
    allow_legacy_m7_command: bool = False,
    start_new_session: bool = False,
) -> str:
    """验证本地镜像身份、运行用户、入口和候选 SHA，返回 Image ID。"""

    image = values["GATEA_APP_IMAGE"]
    result = subprocess.run(
        ("docker", "image", "inspect", image, "--format", "{{json .}}"),
        check=True,
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        start_new_session=start_new_session,
    )
    try:
        payload = json.loads(result.stdout)
        config = payload["Config"]
        labels = config.get("Labels") or {}
        image_id = payload["Id"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise GateAError("Gate A app image metadata is invalid") from error

    if config.get("User") != EXPECTED_APP_USER:
        raise GateAError("Gate A app image must run as UID/GID 10001")
    if config.get("Entrypoint") != EXPECTED_APP_ENTRYPOINT:
        raise GateAError("Gate A app image entrypoint does not match the contract")
    command = config.get("Cmd")
    if command != EXPECTED_APP_COMMAND and not (
        allow_legacy_m7_command and command == LEGACY_M7_APP_COMMAND
    ):
        raise GateAError("Gate A app image command does not match the contract")
    if labels.get("org.opencontainers.image.revision") != _candidate_sha(values):
        raise GateAError("Gate A app image revision does not match its Git SHA tag")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise GateAError("Gate A app image ID is invalid")
    return image_id


def _compose_ps(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    services: Sequence[str] = (),
    start_new_session: bool = False,
) -> list[dict[str, Any]]:
    result = _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=("ps", "--all", "--format", "json", *services),
        capture_output=True,
        start_new_session=start_new_session,
    )
    payload = _parse_compose_ps_output(result.stdout)
    return payload


def _parse_compose_ps_output(output: str) -> list[dict[str, Any]]:
    """兼容 Compose v2 JSON 数组与 v5 newline-delimited JSON。"""

    stripped = output.strip()
    if not stripped:
        payload: Any = []
    else:
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            try:
                payload = [
                    json.loads(line)
                    for line in stripped.splitlines()
                    if line.strip()
                ]
            except json.JSONDecodeError as error:
                raise GateAError("Docker Compose status output is invalid") from error
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise GateAError("Docker Compose status output has an invalid shape")
    return payload


def _ensure_services_healthy(rows: Sequence[Mapping[str, Any]], *services: str) -> None:
    by_service = {str(row.get("Service")): row for row in rows}
    for service in services:
        row = by_service.get(service)
        if row is None:
            raise GateAError(f"Gate A service {service} is unavailable")
        if str(row.get("State", "")).lower() != "running":
            raise GateAError(f"Gate A service {service} is not running")
        if str(row.get("Health", "")).lower() != "healthy":
            raise GateAError(f"Gate A service {service} is not healthy")


def _validate_loopback_publishers(
    rows: Sequence[Mapping[str, Any]],
    expected_port: int,
) -> None:
    """运行时确认只有 Nginx 发布精确的宿主环回端口。"""

    publishers: list[tuple[str, int, int, str]] = []
    for row in rows:
        service = str(row.get("Service") or "")
        raw_publishers = row.get("Publishers") or []
        if not isinstance(raw_publishers, list):
            raise GateAError("Gate A runtime publisher metadata is invalid")
        for publisher in raw_publishers:
            if not isinstance(publisher, dict):
                raise GateAError("Gate A runtime publisher metadata is invalid")
            try:
                url = str(publisher.get("URL") or "")
                target_port = int(publisher["TargetPort"])
                published_port = int(publisher["PublishedPort"])
                protocol = str(publisher.get("Protocol") or "")
            except (KeyError, TypeError, ValueError) as error:
                raise GateAError(
                    "Gate A runtime publisher metadata is invalid"
                ) from error
            # Compose v5 also reports image EXPOSE metadata as an unbound
            # publisher (empty URL and published port zero). It is not a host
            # listener, so keep it out of the exact host-binding contract.
            if url == "" and published_port == 0:
                if target_port <= 0 or protocol not in {"tcp", "udp"}:
                    raise GateAError("Gate A runtime publisher metadata is invalid")
                continue
            if service != "nginx":
                raise GateAError(f"Gate A service {service} must not publish host ports")
            publishers.append((url, target_port, published_port, protocol))
    if publishers != [("127.0.0.1", 8080, expected_port, "tcp")]:
        raise GateAError("Gate A loopback publisher does not match the port contract")


def _best_effort_stop(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    services: Sequence[str],
    start_new_session: bool = True,
) -> None:
    """严格停止并复核目标服务；历史名称保留供既有调用方使用。"""

    _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=("stop", "--timeout", "30", *services),
        start_new_session=start_new_session,
    )
    rows = _compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=services,
        start_new_session=start_new_session,
    )
    stopped_states = frozenset({"created", "dead", "exited", "stopped"})
    targets = frozenset(services)
    for row in rows:
        service = str(row.get("Service") or "")
        if service not in targets:
            continue
        state = str(row.get("State") or "").lower()
        if state not in stopped_states:
            raise GateAError(f"Gate A service {service} did not stop")


def _select_error_after_stop(
    *,
    termination: _OperationTerminationController | None,
    operation_error: BaseException | None,
    transition_error: BaseException | None,
    recovery_error: BaseException | None,
) -> BaseException | None:
    """恢复失败优先，其次原工作错误，最后传播延期控制信号。"""

    if recovery_error is not None:
        return recovery_error
    if transition_error is not None and not isinstance(
        transition_error,
        (GateAOperationInterrupted, KeyboardInterrupt, SystemExit),
    ):
        return transition_error
    if operation_error is not None:
        return operation_error
    if termination is not None and termination.work_interruption is not None:
        return termination.work_interruption
    if transition_error is not None:
        return transition_error
    if termination is not None:
        return termination.deferred_interruption
    return None


@contextmanager
def _stop_services_on_failure(
    *,
    termination: _OperationTerminationController | None,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    services: Sequence[str],
) -> Iterator[None]:
    """任意工作异常后无窗口切入严格 stop，再按固定优先级传播。"""

    operation_error: BaseException | None = None
    transition_error: BaseException | None = None
    recovery_error: BaseException | None = None
    try:
        try:
            yield
        except BaseException as error:
            operation_error = error
    finally:
        try:
            if operation_error is not None and termination is not None:
                termination.begin_recovery()
        except BaseException as error:
            transition_error = error
        finally:
            if operation_error is not None:
                try:
                    _best_effort_stop(
                        values=values,
                        config_file=config_file,
                        secret_dir=secret_dir,
                        mode=mode,
                        services=services,
                        start_new_session=True,
                    )
                except BaseException as error:
                    recovery_error = error

    selected_error = _select_error_after_stop(
        termination=termination,
        operation_error=operation_error,
        transition_error=transition_error,
        recovery_error=recovery_error,
    )
    if selected_error is not None:
        raise selected_error


def _migration_marker(record_dir: Path, candidate_sha: str) -> Path:
    return record_dir / f"{candidate_sha}.initial-migration.json"


def _upgrade_marker(record_dir: Path, candidate_sha: str) -> Path:
    return record_dir / f"{candidate_sha}.existing-database-upgrade.json"


def _upgrade_replay_marker(record_dir: Path, candidate_sha: str) -> Path:
    return record_dir / f"{candidate_sha}.upgrade-plan-replay.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    """同步证据目录项，确保发布和临时文件清理都跨崩溃持久化。"""

    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unlink_temporary_and_fsync(path: Path) -> None:
    """清理同目录临时文件，并持久化目录项删除。"""

    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


def _write_migration_record(
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
) -> None:
    marker = _migration_marker(record_dir, candidate_sha)
    payload = {
        "candidate_sha": candidate_sha,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "image_id": image_id,
        "schema_version": 1,
    }
    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=record_dir,
            prefix=f".{marker.name}.tmp-",
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, marker, follow_symlinks=False)
        except FileExistsError as error:
            raise GateAError(
                "Gate A initial migration record path is already reserved"
            ) from error
        _fsync_directory(record_dir)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            _unlink_temporary_and_fsync(temporary)


def _require_migration_record(
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
) -> dict[str, Any]:
    marker = _migration_marker(record_dir, candidate_sha)
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise GateAError("Gate A initial migration record is unavailable") from error
    if (
        payload.get("schema_version") != 1
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("image_id") != image_id
        or not payload.get("completed_at")
    ):
        raise GateAError("Gate A initial migration record does not match the candidate")
    return payload


def _utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed


def _is_utc_timestamp(value: object) -> bool:
    return _utc_datetime(value) is not None


def _schema2_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
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


def _require_schema2_record_metadata(
    metadata: os.stat_result,
    description: str,
) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o644
        or metadata.st_uid != 0
        or metadata.st_gid != 0
        or metadata.st_nlink != 1
        or metadata.st_size > MAX_M9_ADOPTION_RECORD_BYTES
    ):
        raise GateAError(f"Gate A {description} has unsafe metadata")


def _json_object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON key")
        payload[key] = value
    return payload


def _load_schema2_record_with_sha256(
    path: Path,
    description: str,
) -> tuple[dict[str, Any], str]:
    """稳定读取 root-only 发布的 schema-v2 Record 与同字节摘要。"""

    descriptor: int | None = None
    try:
        path_metadata = path.lstat()
        _require_schema2_record_metadata(path_metadata, description)
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before_metadata = os.fstat(descriptor)
        _require_schema2_record_metadata(before_metadata, description)
        if _schema2_file_identity(path_metadata) != _schema2_file_identity(
            before_metadata
        ):
            raise GateAError(f"Gate A {description} changed during validation")
        chunks: list[bytes] = []
        remaining = MAX_M9_ADOPTION_RECORD_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise GateAError(f"Gate A {description} is unexpectedly large")
        after_metadata = os.fstat(descriptor)
        final_metadata = path.lstat()
        _require_schema2_record_metadata(after_metadata, description)
        _require_schema2_record_metadata(final_metadata, description)
        if not (
            _schema2_file_identity(before_metadata)
            == _schema2_file_identity(after_metadata)
            == _schema2_file_identity(final_metadata)
        ):
            raise GateAError(f"Gate A {description} changed during validation")
        content = b"".join(chunks)
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicates,
        )
    except GateAError:
        raise
    except (
        FileNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise GateAError(f"Gate A {description} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise GateAError(f"Gate A {description} is invalid")
    return payload, hashlib.sha256(content).hexdigest()


def _load_upgrade_record_for_classification(
    path: Path,
) -> tuple[dict[str, Any], str]:
    """从一个稳定 fd 分类 schema；schema v2 再施加 root-only 元数据契约。"""

    descriptor: int | None = None
    description = "existing-database upgrade record"
    try:
        path_metadata = path.lstat()
        if (
            not stat.S_ISREG(path_metadata.st_mode)
            or path_metadata.st_size > MAX_M9_ADOPTION_RECORD_BYTES
        ):
            raise GateAError(f"Gate A {description} is unsafe")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        before_metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before_metadata.st_mode)
            or _schema2_file_identity(path_metadata)
            != _schema2_file_identity(before_metadata)
        ):
            raise GateAError(f"Gate A {description} changed during validation")
        chunks: list[bytes] = []
        remaining = MAX_M9_ADOPTION_RECORD_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise GateAError(f"Gate A {description} is unexpectedly large")
        after_metadata = os.fstat(descriptor)
        final_metadata = path.lstat()
        if not (
            _schema2_file_identity(before_metadata)
            == _schema2_file_identity(after_metadata)
            == _schema2_file_identity(final_metadata)
        ):
            raise GateAError(f"Gate A {description} changed during validation")
        content = b"".join(chunks)
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicates,
        )
        if not isinstance(payload, dict):
            raise GateAError(f"Gate A {description} is invalid")
        if payload.get("schema_version") == 2:
            for metadata in (
                path_metadata,
                before_metadata,
                after_metadata,
                final_metadata,
            ):
                _require_schema2_record_metadata(metadata, description)
    except GateAError:
        raise
    except (
        FileNotFoundError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise GateAError(f"Gate A {description} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return payload, hashlib.sha256(content).hexdigest()


def _validate_m9_adoption_content_snapshot(
    payload: object,
    *,
    profile: str,
) -> bool:
    content_sha256 = (
        payload.get("content_sha256") if isinstance(payload, dict) else None
    )
    return (
        isinstance(payload, dict)
        and set(payload) == M9_ADOPTION_CONTENT_SNAPSHOT_KEYS
        and type(payload.get("schema_version")) is int
        and payload.get("schema_version") == 1
        and payload.get("profile") == profile
        and isinstance(content_sha256, str)
        and SHA256_PATTERN.fullmatch(content_sha256) is not None
    )


def _validate_m9_adoption_image_manifest(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and set(payload) == {"files", "sha256"}
        and type(payload.get("files")) is int
        and payload["files"] >= 0
        and SHA256_PATTERN.fullmatch(str(payload.get("sha256", ""))) is not None
    )


def _require_m9_adoption_upgrade_record(
    payload: Mapping[str, Any],
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
) -> dict[str, Any]:
    source_candidate_sha = payload.get("source_candidate_sha")
    lineage_source_candidate_sha = payload.get("lineage_source_candidate_sha")
    digest_fields = (
        "manifest_sha256",
        "stage_record_sha256",
        "activation_record_sha256",
        "predecessor_stage_record_sha256",
        "predecessor_activation_record_sha256",
        "predecessor_upgrade_record_sha256",
        "predecessor_upgrade_evidence_sha256",
        "predecessor_upgrade_plan_replay_record_sha256",
        "acceptance_retirement_record_sha256",
        "backup_record_sha256",
        "restore_record_sha256",
        "evidence_sha256",
    )
    runtime_preflight = payload.get("runtime_preflight")
    source_database_snapshot = payload.get("source_database_snapshot")
    final_database_snapshot = payload.get("final_database_snapshot")
    source_image_manifest = payload.get("source_image_manifest")
    final_image_manifest = payload.get("final_image_manifest")
    source_m7_content = payload.get("source_m7_content_snapshot")
    final_m7_content = payload.get("final_m7_content_snapshot")
    source_m8_swatch_content = payload.get("source_m8_swatch_content_snapshot")
    final_m8_swatch_content = payload.get("final_m8_swatch_content_snapshot")
    source_m9_content = payload.get("source_m9_table_content_snapshot")
    final_m9_content = payload.get("final_m9_table_content_snapshot")
    started_at = _utc_datetime(payload.get("started_at"))
    completed_at = _utc_datetime(payload.get("completed_at"))
    evidence_path = record_dir / (
        f"{candidate_sha}.existing-database-upgrade.evidence.json"
    )
    if (
        set(payload) != M9_ADOPTION_UPGRADE_RECORD_KEYS
        or payload.get("schema_version") != 2
        or payload.get("transition_kind") != M9_ADOPTION_TRANSITION_KIND
        or payload.get("record_type") != "existing-database-upgrade"
        or payload.get("passed") is not True
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("image_id") != image_id
        or not isinstance(source_candidate_sha, str)
        or GIT_SHA_PATTERN.fullmatch(source_candidate_sha) is None
        or source_candidate_sha == candidate_sha
        or not isinstance(lineage_source_candidate_sha, str)
        or GIT_SHA_PATTERN.fullmatch(lineage_source_candidate_sha) is None
        or lineage_source_candidate_sha in {source_candidate_sha, candidate_sha}
        or not isinstance(payload.get("source_image_id"), str)
        or not payload["source_image_id"]
        or not isinstance(payload.get("lineage_source_image_id"), str)
        or not payload["lineage_source_image_id"]
        or payload.get("source_version") != 9
        or payload.get("target_version") != 9
        or payload.get("source_aerich_versions")
        != list(APPROVED_TARGET_M9_CHAIN)
        or payload.get("target_aerich_versions")
        != list(APPROVED_TARGET_M9_CHAIN)
        or BACKUP_ID_PATTERN.fullmatch(str(payload.get("backup_id", ""))) is None
        or any(
            SHA256_PATTERN.fullmatch(str(payload.get(field, ""))) is None
            for field in digest_fields
        )
        or payload.get("evidence_path") != str(evidence_path)
        or started_at is None
        or completed_at is None
        or completed_at < started_at
        or not isinstance(runtime_preflight, dict)
        or runtime_preflight
        != {
            "app_env": "production",
            "db_engine": "mysql",
            "jwt_algorithm": "HS256",
            "table_session_claims_enabled": True,
            "validated": True,
        }
        or not isinstance(source_database_snapshot, dict)
        or source_database_snapshot != final_database_snapshot
        or source_database_snapshot.get("aerich_versions")
        != list(APPROVED_TARGET_M9_CHAIN)
        or not _validate_m9_adoption_image_manifest(source_image_manifest)
        or source_image_manifest != final_image_manifest
        or not _validate_m9_adoption_content_snapshot(
            source_m7_content, profile="m7-preserved-business-v1"
        )
        or source_m7_content != final_m7_content
        or not _validate_m9_adoption_content_snapshot(
            source_m8_swatch_content, profile="m8-swatch-content-v1"
        )
        or source_m8_swatch_content != final_m8_swatch_content
        or not _validate_m9_adoption_content_snapshot(
            source_m9_content, profile="m9-table-business-v1"
        )
        or source_m9_content != final_m9_content
        or payload.get("database_changes_applied") is not False
        or payload.get("migrations_applied") != []
    ):
        raise GateAError(
            "Gate A existing-database upgrade record does not match the candidate"
        )
    _validate_m9_reconcile(payload.get("table_reconcile"), require_empty=False)
    recorded_reconcile = payload["table_reconcile"]
    if (
        recorded_reconcile.get("open_sessions") != 0
        or recorded_reconcile.get("occupancies") != 0
        or recorded_reconcile.get("violations") != 0
    ):
        raise GateAError(
            "Gate A existing-database upgrade record does not match the candidate"
        )
    return dict(payload)


def _require_upgrade_record(
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
) -> dict[str, Any]:
    """验证既有数据库升级成功 Record 与当前不可变候选一致。"""

    marker = _upgrade_marker(record_dir, candidate_sha)
    payload, _ = _load_upgrade_record_for_classification(marker)
    schema_transition = (
        payload.get("schema_version"),
        payload.get("transition_kind") if "transition_kind" in payload else None,
    )
    if schema_transition == (2, M9_ADOPTION_TRANSITION_KIND):
        return _require_m9_adoption_upgrade_record(
            payload,
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
    if schema_transition != (1, None):
        raise GateAError(
            "Gate A existing-database upgrade record does not match the candidate"
        )
    source_candidate_sha = str(payload.get("source_candidate_sha", ""))
    source_image_id = payload.get("source_image_id")
    source_aerich_versions = payload.get("source_aerich_versions")
    source_version_is_present = "source_version" in payload
    source_version = payload.get("source_version")
    target_aerich_versions = payload.get("target_aerich_versions")
    source_target_transition_is_valid = (
        source_aerich_versions == list(APPROVED_SOURCE_M2_CHAIN)
        and (
            not source_version_is_present
            or (type(source_version) is int and source_version == 2)
        )
        and target_aerich_versions
        in (
            list(APPROVED_TARGET_M7_CHAIN),
            list(APPROVED_TARGET_M8_CHAIN),
            list(APPROVED_TARGET_M9_CHAIN),
        )
    ) or (
        source_aerich_versions == list(APPROVED_SOURCE_M7_CHAIN)
        and source_version_is_present
        and type(source_version) is int
        and source_version == 7
        and target_aerich_versions
        in (list(APPROVED_TARGET_M8_CHAIN), list(APPROVED_TARGET_M9_CHAIN))
    )
    if (
        payload.get("schema_version") != 1
        or payload.get("record_type") != "existing-database-upgrade"
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("image_id") != image_id
        or payload.get("passed") is not True
        or not payload.get("completed_at")
        or GIT_SHA_PATTERN.fullmatch(source_candidate_sha) is None
        or source_candidate_sha == candidate_sha
        or not isinstance(source_image_id, str)
        or not source_image_id
        or BACKUP_ID_PATTERN.fullmatch(str(payload.get("backup_id", ""))) is None
        or SHA256_PATTERN.fullmatch(str(payload.get("manifest_sha256", ""))) is None
        or not source_target_transition_is_valid
    ):
        raise GateAError(
            "Gate A existing-database upgrade record does not match the candidate"
        )
    return payload


def _require_deployment_record(
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
) -> dict[str, Any]:
    """接受精确匹配的首次迁移或既有数据库升级 Record。"""

    initial_marker = _migration_marker(record_dir, candidate_sha)
    upgrade_marker = _upgrade_marker(record_dir, candidate_sha)
    if initial_marker.is_symlink() or upgrade_marker.is_symlink():
        raise GateAError("Gate A deployment record is ambiguous or unsafe")
    available = (initial_marker.exists(), upgrade_marker.exists())
    if sum(available) != 1:
        raise GateAError("Gate A deployment record is ambiguous or unavailable")
    if available[0]:
        return _require_migration_record(
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
    return _require_upgrade_record(
        record_dir=record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )


def _validate_m9_reconcile(
    payload: object,
    *,
    require_empty: bool,
) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or set(payload) != M9_RECONCILE_KEYS
        or any(type(payload.get(key)) is not int or payload[key] < 0 for key in payload)
        or payload.get("violations") != 0
        or payload.get("closed_with_occupancy") != 0
        or payload.get("awaiting_with_timers") != 0
        or payload.get("active_without_timers") != 0
        or (require_empty and any(payload[key] != 0 for key in payload))
    ):
        raise GateAError("Gate A M9 table reconciliation is invalid")
    return dict(payload)


def _require_m9_adoption_replay_record(
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
    upgrade_record: Mapping[str, Any],
) -> dict[str, Any]:
    success_path = _upgrade_marker(record_dir, candidate_sha)
    evidence_path = record_dir / (
        f"{candidate_sha}.existing-database-upgrade.evidence.json"
    )
    replay_path = _upgrade_replay_marker(record_dir, candidate_sha)
    try:
        stable_upgrade, upgrade_record_sha256 = (
            _load_schema2_record_with_sha256(
                success_path, "M9 adoption upgrade record"
            )
        )
        evidence, evidence_sha256 = _load_schema2_record_with_sha256(
            evidence_path, "M9 adoption upgrade evidence"
        )
        replay, _ = _load_schema2_record_with_sha256(
            replay_path, "M9 adoption upgrade replay record"
        )
    except GateAError as error:
        raise GateAError("Gate A M9 upgrade replay evidence is unavailable") from error
    expected_result = {
        "already_current": True,
        "backup_id": upgrade_record.get("backup_id"),
        "candidate_sha": candidate_sha,
        "database_changes_applied": False,
        "manifest_sha256": upgrade_record.get("manifest_sha256"),
        "migrations_applied": [],
        "mode": "plan-replay",
        "source_aerich_versions": list(APPROVED_TARGET_M9_CHAIN),
        "source_version": 9,
        "target_aerich_versions": list(APPROVED_TARGET_M9_CHAIN),
        "target_version": 9,
        "transition_kind": M9_ADOPTION_TRANSITION_KIND,
    }
    if not isinstance(replay, dict) or not isinstance(evidence, dict):
        raise GateAError("Gate A M9 upgrade replay evidence is invalid")
    evidence_started_at = _utc_datetime(evidence.get("started_at"))
    evidence_completed_at = _utc_datetime(evidence.get("completed_at"))
    recorded_reconcile = _validate_m9_reconcile(
        replay.get("table_reconcile"), require_empty=False
    )
    bound_evidence_fields = M9_ADOPTION_EVIDENCE_RECORD_KEYS - frozenset(
        {"schema_version", "record_type", "status", "current_stage", "steps", "stopped_source_verified"}
    )
    if (
        set(replay) != M9_ADOPTION_REPLAY_RECORD_KEYS
        or stable_upgrade != upgrade_record
        or replay.get("schema_version") != 2
        or replay.get("transition_kind") != M9_ADOPTION_TRANSITION_KIND
        or replay.get("record_type") != "gatea-m9-upgrade-plan-replay"
        or replay.get("passed") is not True
        or replay.get("candidate_sha") != candidate_sha
        or replay.get("source_candidate_sha")
        != upgrade_record.get("source_candidate_sha")
        or replay.get("source_version") != 9
        or replay.get("image_id") != image_id
        or replay.get("backup_id") != upgrade_record.get("backup_id")
        or replay.get("manifest_sha256") != upgrade_record.get("manifest_sha256")
        or replay.get("lineage_source_candidate_sha")
        != upgrade_record.get("lineage_source_candidate_sha")
        or replay.get("lineage_source_image_id")
        != upgrade_record.get("lineage_source_image_id")
        or replay.get("acceptance_retirement_record_sha256")
        != upgrade_record.get("acceptance_retirement_record_sha256")
        or replay.get("database_changes_applied") is not False
        or replay.get("migrations_applied") != []
        or replay.get("database_snapshot")
        != upgrade_record.get("final_database_snapshot")
        or replay.get("m8_swatch_content_snapshot")
        != upgrade_record.get("final_m8_swatch_content_snapshot")
        or not _validate_m9_adoption_content_snapshot(
            replay.get("m8_swatch_content_snapshot"),
            profile="m8-swatch-content-v1",
        )
        or replay.get("image_manifest")
        != upgrade_record.get("final_image_manifest")
        or replay.get("table_reconcile")
        != upgrade_record.get("table_reconcile")
        or replay.get("upgrade_record_sha256") != upgrade_record_sha256
        or replay.get("evidence_sha256") != upgrade_record.get("evidence_sha256")
        or replay.get("result") != expected_result
        or not _is_utc_timestamp(replay.get("completed_at"))
        or replay.get("secret_values_recorded") is not False
        or set(evidence) != M9_ADOPTION_EVIDENCE_RECORD_KEYS
        or evidence.get("schema_version") != 2
        or evidence.get("transition_kind") != M9_ADOPTION_TRANSITION_KIND
        or evidence.get("record_type") != "existing-database-upgrade-evidence"
        or evidence.get("status") != "succeeded"
        or evidence.get("current_stage") != "completed"
        or evidence.get("stopped_source_verified") is not True
        or evidence.get("steps") != []
        or evidence_started_at is None
        or evidence_completed_at is None
        or evidence_completed_at < evidence_started_at
        or any(
            evidence.get(field) != upgrade_record.get(field)
            for field in bound_evidence_fields
        )
        or upgrade_record.get("evidence_path") != str(evidence_path)
        or evidence_sha256 != upgrade_record.get("evidence_sha256")
        or recorded_reconcile != replay.get("table_reconcile")
        or recorded_reconcile.get("open_sessions") != 0
        or recorded_reconcile.get("occupancies") != 0
        or recorded_reconcile.get("violations") != 0
    ):
        raise GateAError("Gate A M9 upgrade replay evidence is invalid")
    return replay


def _require_m9_upgrade_replay_record(
    *,
    record_dir: Path,
    candidate_sha: str,
    image_id: str,
    upgrade_record: Mapping[str, Any],
) -> dict[str, Any]:
    """验证 M9 app-up 前不可变的 upgrade evidence 与 plan-replay sidecar。"""

    schema_transition = (
        upgrade_record.get("schema_version"),
        upgrade_record.get("transition_kind")
        if "transition_kind" in upgrade_record
        else None,
    )
    if schema_transition == (2, M9_ADOPTION_TRANSITION_KIND):
        return _require_m9_adoption_replay_record(
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
            upgrade_record=upgrade_record,
        )
    if schema_transition != (1, None):
        raise GateAError("Gate A M9 upgrade replay evidence is invalid")

    success_path = _upgrade_marker(record_dir, candidate_sha)
    evidence_path = record_dir / (
        f"{candidate_sha}.existing-database-upgrade.evidence.json"
    )
    replay_path = _upgrade_replay_marker(record_dir, candidate_sha)
    try:
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise GateAError("Gate A M9 upgrade replay evidence is unavailable") from error
    expected_replay_keys = {
        "backup_id",
        "candidate_sha",
        "completed_at",
        "database_snapshot",
        "evidence_sha256",
        "image_id",
        "image_manifest",
        "manifest_sha256",
        "passed",
        "record_type",
        "result",
        "schema_version",
        "secret_values_recorded",
        "source_candidate_sha",
        "source_version",
        "table_reconcile",
        "upgrade_record_sha256",
    }
    source_version = upgrade_record.get("source_version")
    expected_result = {
        "already_current": True,
        "backup_id": upgrade_record.get("backup_id"),
        "candidate_sha": candidate_sha,
        "manifest_sha256": upgrade_record.get("manifest_sha256"),
        "mode": "plan-replay",
        "source_aerich_versions": upgrade_record.get("source_aerich_versions"),
        "source_version": source_version,
        "target_aerich_versions": list(APPROVED_TARGET_M9_CHAIN),
        "target_version": 9,
    }
    recorded_reconcile = (
        _validate_m9_reconcile(replay.get("table_reconcile"), require_empty=True)
        if isinstance(replay, dict)
        else {}
    )
    if (
        not isinstance(replay, dict)
        or set(replay) != expected_replay_keys
        or replay.get("schema_version") != 1
        or replay.get("record_type") != "gatea-m9-upgrade-plan-replay"
        or replay.get("passed") is not True
        or replay.get("candidate_sha") != candidate_sha
        or replay.get("source_candidate_sha")
        != upgrade_record.get("source_candidate_sha")
        or type(replay.get("source_version")) is not int
        or replay.get("source_version") != source_version
        or replay.get("image_id") != image_id
        or replay.get("backup_id") != upgrade_record.get("backup_id")
        or replay.get("manifest_sha256") != upgrade_record.get("manifest_sha256")
        or replay.get("database_snapshot")
        != upgrade_record.get("final_database_snapshot")
        or replay.get("image_manifest") != upgrade_record.get("final_image_manifest")
        or replay.get("upgrade_record_sha256") != _sha256(success_path)
        or replay.get("evidence_sha256") != upgrade_record.get("evidence_sha256")
        or replay.get("result") != expected_result
        or not isinstance(replay.get("completed_at"), str)
        or not replay["completed_at"]
        or replay.get("secret_values_recorded") is not False
        or upgrade_record.get("evidence_path") != str(evidence_path)
        or SHA256_PATTERN.fullmatch(str(upgrade_record.get("evidence_sha256", "")))
        is None
        or _sha256(evidence_path) != upgrade_record.get("evidence_sha256")
        or not isinstance(evidence, dict)
        or evidence.get("schema_version") != 1
        or evidence.get("record_type") != "existing-database-upgrade-evidence"
        or evidence.get("status") != "succeeded"
        or evidence.get("candidate_sha") != candidate_sha
        or evidence.get("source_candidate_sha")
        != upgrade_record.get("source_candidate_sha")
        or evidence.get("backup_id") != upgrade_record.get("backup_id")
        or evidence.get("final_database_snapshot")
        != upgrade_record.get("final_database_snapshot")
        or evidence.get("final_image_manifest")
        != upgrade_record.get("final_image_manifest")
        or evidence.get("table_reconcile") != upgrade_record.get("table_reconcile")
        or evidence.get("table_sweep") != upgrade_record.get("table_sweep")
        or recorded_reconcile != replay.get("table_reconcile")
    ):
        raise GateAError("Gate A M9 upgrade replay evidence is invalid")
    _validate_m9_reconcile(upgrade_record.get("table_reconcile"), require_empty=True)
    if upgrade_record.get("table_sweep") != {"status": "ok", "closed": 0}:
        raise GateAError("Gate A M9 upgrade table sweep evidence is invalid")
    return replay


def _run_m9_table_reconcile(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    start_new_session: bool = False,
) -> dict[str, Any]:
    result = _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
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
        check=False,
        start_new_session=start_new_session,
    )
    if result.returncode != 0:
        raise GateAError("Gate A M9 table reconciliation task failed")
    try:
        payload = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, TypeError) as error:
        raise GateAError("Gate A M9 table reconciliation output is invalid") from error
    return _validate_m9_reconcile(payload, require_empty=False)


def preflight(*, config_file: Path, secret_dir: Path, mode: str) -> None:
    """在创建任何 Docker 资源前完成只读 Gate A 预检。"""

    _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=True,
    )
    print(f"Gate A {mode} preflight passed")


def read_database_snapshot(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    mode: str,
    start_new_session: bool = False,
) -> dict[str, Any]:
    """从已有健康 MySQL 读取规范化的只读数据库摘要。"""

    rows = _compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("mysql",),
        start_new_session=start_new_session,
    )
    _ensure_services_healthy(rows, "mysql")
    result = _run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        arguments=(
            "exec",
            "--no-TTY",
            "mysql",
            "sh",
            "-ec",
            DATABASE_STATUS_COMMAND,
        ),
        capture_output=True,
        start_new_session=start_new_session,
    )
    try:
        snapshot = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, TypeError) as error:
        raise GateAError("Gate A database status output is invalid") from error
    if not isinstance(snapshot, dict):
        raise GateAError("Gate A database status output has an invalid shape")

    raw_versions = snapshot.get("aerich_versions")
    if not isinstance(raw_versions, str):
        raise GateAError("Gate A Aerich status output is invalid")
    snapshot["aerich_versions"] = (
        raw_versions.split(",") if raw_versions else []
    )
    return snapshot


def database_status(*, config_file: Path, secret_dir: Path, mode: str) -> None:
    """只读输出 Aerich、Schema 指纹和 M2 关键业务摘要。"""

    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
    )
    snapshot = read_database_snapshot(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    print(
        json.dumps(
            {
                "app_version": values["APP_VERSION"],
                "candidate_sha": _candidate_sha(values),
                "database_snapshot": snapshot,
                "mode": mode,
                "read_only": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def infra_up(
    *,
    config_file: Path,
    secret_dir: Path,
    mode: str,
    wait_timeout: int,
    _termination_controller: _OperationTerminationController | None = None,
) -> None:
    """仅启动 MySQL/Redis 并等待健康；失败时停止已启动的基础设施。"""

    _require_loopback_write_mode(mode)
    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=True,
    )
    validate_app_image(values)
    with _stop_services_on_failure(
        termination=_termination_controller,
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("redis", "mysql"),
    ):
        _run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                str(wait_timeout),
                "mysql",
                "redis",
            ),
        )
        rows = _compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis"),
        )
        _ensure_services_healthy(rows, "mysql", "redis")
    print("Gate A infrastructure is healthy")


def initial_migrate(
    *,
    config_file: Path,
    secret_dir: Path,
    record_dir: Path,
    mode: str,
    acceptance_record_dir: Path = DEFAULT_M9_ACCEPTANCE_RECORD_DIR,
    _termination_controller: _OperationTerminationController | None = None,
) -> None:
    """只对首次空库执行 Aerich upgrade，并原子记录候选和镜像身份。"""

    _require_loopback_write_mode(mode)
    _validate_root_directory(record_dir, 0o755, "Gate A release record directory")
    reject_unresolved_candidate_transition_journals(record_dir=record_dir)
    reject_unresolved_m9_acceptance_sidecars(record_dir=acceptance_record_dir)
    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=True,
    )
    image_id = validate_app_image(values)
    candidate_sha = _candidate_sha(values)
    marker = _migration_marker(record_dir, candidate_sha)
    if marker.exists():
        _require_migration_record(
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
        print("Gate A initial migration was already recorded for this candidate")
        return

    with _stop_services_on_failure(
        termination=_termination_controller,
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("redis", "mysql"),
    ):
        rows = _compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=("mysql", "redis"),
        )
        _ensure_services_healthy(rows, "mysql", "redis")
        count_result = _run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "exec",
                "--no-TTY",
                "mysql",
                "sh",
                "-ec",
                INITIAL_SCHEMA_COUNT_COMMAND,
            ),
            capture_output=True,
        )
        table_count = count_result.stdout.strip()
        if table_count != "0":
            raise GateAError(
                "Gate A initial migration requires an empty application database"
            )

        _run_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            profiles=("operations",),
            arguments=("run", "--rm", "--no-deps", "migrate"),
        )
        _write_migration_record(
            record_dir=record_dir,
            candidate_sha=candidate_sha,
            image_id=image_id,
        )
    print("Gate A initial migration completed and was recorded")


def app_up(
    *,
    config_file: Path,
    secret_dir: Path,
    record_dir: Path,
    mode: str,
    wait_timeout: int,
    include_table_sweeper: bool = True,
    allow_legacy_m7_command: bool = False,
    allow_existing_gatea_publisher: bool = False,
    candidate_transition_recovery: CandidateTransitionRecoveryAllowance | None = None,
    acceptance_sidecar_recovery: M9AcceptanceSidecarRecoveryAllowance | None = None,
    candidate_takeover_recovery: M9CandidateTakeoverRecoveryAllowance | None = None,
    acceptance_record_dir: Path = DEFAULT_M9_ACCEPTANCE_RECORD_DIR,
    _termination_controller: _OperationTerminationController | None = None,
    _start_new_session: bool = False,
) -> None:
    """Record 匹配后启动 App/Nginx，并默认严格要求 M9 sweeper。"""

    _require_loopback_write_mode(mode)
    subprocess_options = (
        {"start_new_session": True} if _start_new_session else {}
    )
    allowed_recovery_kinds = frozenset(
        {"current-finalization", "failed-acceptance-retirement"}
    )
    if candidate_transition_recovery is not None and (
        not isinstance(
            candidate_transition_recovery,
            CandidateTransitionRecoveryAllowance,
        )
        or candidate_transition_recovery.kind not in allowed_recovery_kinds
    ):
        raise GateAError(
            "Gate A app-up recovery allowance is restricted to finalization or failed-acceptance retirement"
        )
    if candidate_takeover_recovery is not None and (
        not isinstance(
            candidate_takeover_recovery,
            M9CandidateTakeoverRecoveryAllowance,
        )
        or candidate_transition_recovery is not None
        or acceptance_sidecar_recovery is not None
    ):
        raise GateAError(
            "Gate A app-up candidate takeover recovery must be the only recovery allowance"
        )
    if acceptance_sidecar_recovery is not None and (
        candidate_transition_recovery is None
        or candidate_transition_recovery.kind
        != "failed-acceptance-retirement"
        or not isinstance(
            acceptance_sidecar_recovery,
            M9AcceptanceSidecarRecoveryAllowance,
        )
    ):
        raise GateAError(
            "Gate A app-up acceptance allowance is restricted to failed-acceptance retirement"
        )
    if (
        acceptance_sidecar_recovery is not None
        and candidate_transition_recovery is not None
        and acceptance_sidecar_recovery.candidate_sha
        != candidate_transition_recovery.runtime_candidate_sha
    ):
        raise GateAError(
            "Gate A app-up acceptance allowance does not match the retirement runtime candidate"
        )
    _validate_root_directory(record_dir, 0o755, "Gate A release record directory")
    if candidate_takeover_recovery is not None:
        _validate_m9_candidate_takeover_recovery_allowance(
            record_dir=record_dir,
            acceptance_record_dir=acceptance_record_dir,
            recovery_allowance=candidate_takeover_recovery,
            pending_paths=_candidate_transition_pending_paths(record_dir),
            sidecar_paths=_m9_acceptance_sidecar_paths(acceptance_record_dir),
        )
    else:
        recovery_candidate_sha = (
            candidate_transition_recovery.candidate_sha
            if candidate_transition_recovery is not None
            else None
        )
        reject_unresolved_candidate_transition_journals(
            record_dir=record_dir,
            candidate_sha=recovery_candidate_sha,
            recovery_allowance=candidate_transition_recovery,
        )
        reject_unresolved_m9_acceptance_sidecars(
            record_dir=acceptance_record_dir,
            recovery_allowance=acceptance_sidecar_recovery,
        )
    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=not allow_existing_gatea_publisher,
    )
    candidate_sha = _candidate_sha(values)
    expected_runtime_candidate_sha = (
        candidate_takeover_recovery.runtime_candidate_sha
        if candidate_takeover_recovery is not None
        else (
            candidate_transition_recovery.runtime_candidate_sha
            if candidate_transition_recovery is not None
            and candidate_transition_recovery.kind
            == "failed-acceptance-retirement"
            else recovery_candidate_sha
        )
    )
    if (
        (candidate_transition_recovery is not None or candidate_takeover_recovery is not None)
        and candidate_sha != expected_runtime_candidate_sha
    ):
        raise GateAError(
            "Gate A app-up recovery allowance does not match the live candidate"
        )
    if allow_legacy_m7_command:
        if include_table_sweeper:
            raise GateAError(
                "Gate A legacy M7 app command recovery cannot start the table sweeper"
            )
        snapshot = read_database_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            **subprocess_options,
        )
        if snapshot.get("aerich_versions") != list(APPROVED_TARGET_M7_CHAIN):
            raise GateAError(
                "Gate A legacy app command recovery requires the exact M7 chain"
            )
        image_id = validate_app_image(
            values,
            allow_legacy_m7_command=True,
            **subprocess_options,
        )
    else:
        image_id = validate_app_image(values, **subprocess_options)
    deployment_record = _require_deployment_record(
        record_dir=record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    live_snapshot = read_database_snapshot(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        **subprocess_options,
    )
    live_versions = live_snapshot.get("aerich_versions")
    if (
        allow_legacy_m7_command
        and live_versions != list(APPROVED_TARGET_M7_CHAIN)
    ):
        raise GateAError(
            "Gate A legacy app command recovery requires the exact M7 chain"
        )
    if include_table_sweeper:
        if live_versions != list(APPROVED_TARGET_M9_CHAIN):
            raise GateAError("Gate A table sweeper requires the exact M9 chain")
        if deployment_record.get("record_type") == "existing-database-upgrade":
            _require_m9_upgrade_replay_record(
                record_dir=record_dir,
                candidate_sha=candidate_sha,
                image_id=image_id,
                upgrade_record=deployment_record,
            )
            recorded_snapshot = deployment_record.get("final_database_snapshot")
            if not isinstance(recorded_snapshot, dict) or any(
                live_snapshot.get(key) != recorded_snapshot.get(key)
                for key in M9_STATIC_SNAPSHOT_KEYS
            ):
                raise GateAError(
                    "Gate A live M9 schema no longer matches the upgrade record"
                )
        pinned_values = dict(values)
        pinned_values["GATEA_APP_IMAGE"] = image_id
        _run_m9_table_reconcile(
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            **subprocess_options,
        )
        if validate_app_image(values, **subprocess_options) != image_id:
            raise GateAError("Gate A app image tag changed before runtime start")
    else:
        approved_pre_m9 = (
            list(APPROVED_SOURCE_M2_CHAIN),
            list(APPROVED_TARGET_M7_CHAIN),
            list(APPROVED_TARGET_M8_CHAIN),
        )
        if live_versions not in approved_pre_m9:
            raise GateAError(
                "Gate A runtime without table sweeper requires an approved pre-M9 chain"
            )
        pinned_values = dict(values)
        pinned_values["GATEA_APP_IMAGE"] = image_id
    rows = _compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("mysql", "redis"),
        **subprocess_options,
    )
    _ensure_services_healthy(rows, "mysql", "redis")

    runtime_services = (
        ("app", "table-sweeper", "nginx")
        if include_table_sweeper
        else ("app", "nginx")
    )
    if allow_existing_gatea_publisher:
        existing_rows = _compose_ps(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=runtime_services,
            **subprocess_options,
        )
        nginx = next(
            (row for row in existing_rows if row.get("Service") == "nginx"),
            None,
        )
        if nginx is not None and str(nginx.get("State", "")).lower() == "running":
            _validate_loopback_publishers(
                existing_rows,
                int(values.get("GATEA_LOOPBACK_PORT", "18080")),
            )
        else:
            _assert_loopback_port_available(
                int(values.get("GATEA_LOOPBACK_PORT", "18080"))
            )
    with _stop_services_on_failure(
        termination=_termination_controller,
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        services=("nginx", "table-sweeper", "app", "image-init"),
    ):
        _run_compose(
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            arguments=(
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                str(wait_timeout),
                *runtime_services,
            ),
            **subprocess_options,
        )
        rows = _compose_ps(
            values=pinned_values,
            config_file=config_file,
            secret_dir=secret_dir,
            mode=mode,
            services=runtime_services,
            **subprocess_options,
        )
        _ensure_services_healthy(rows, *runtime_services)
        _validate_loopback_publishers(
            rows,
            int(values.get("GATEA_LOOPBACK_PORT", "18080")),
        )
    print("Gate A application and loopback edge are healthy")


def status(
    *,
    config_file: Path,
    secret_dir: Path,
    record_dir: Path,
    mode: str,
) -> None:
    """输出不含 Secret、环境值和挂载详情的运行状态。"""

    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
    )
    rows = _compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
    )
    summary = [
        {
            "health": str(row.get("Health") or ""),
            "service": str(row.get("Service") or ""),
            "state": str(row.get("State") or ""),
        }
        for row in rows
    ]
    candidate_sha = _candidate_sha(values)
    initial_marker = _migration_marker(record_dir, candidate_sha)
    upgrade_marker = _upgrade_marker(record_dir, candidate_sha)
    print(
        json.dumps(
            {
                "candidate_sha": candidate_sha,
                "deployment_recorded": initial_marker.is_file()
                or upgrade_marker.is_file(),
                "existing_database_upgrade_recorded": upgrade_marker.is_file(),
                "initial_migration_recorded": initial_marker.is_file(),
                "mode": mode,
                "services": sorted(summary, key=lambda item: item["service"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def safe_stop(
    *,
    config_file: Path,
    secret_dir: Path,
    mode: str,
    _termination_controller: _OperationTerminationController | None = None,
) -> None:
    """停止 Gate A 服务但保留容器、命名卷、迁移记录和 Secret。"""

    values = _validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode=mode,
        require_available_port=False,
        require_secrets=False,
    )
    transition_error: BaseException | None = None
    recovery_error: BaseException | None = None
    try:
        try:
            if _termination_controller is not None:
                _termination_controller.begin_recovery()
        except BaseException as error:
            transition_error = error
    finally:
        try:
            _best_effort_stop(
                values=values,
                config_file=config_file,
                secret_dir=secret_dir,
                mode=mode,
                services=(
                    "nginx",
                    "table-sweeper",
                    "app",
                    "image-init",
                    "redis",
                    "mysql",
                ),
                start_new_session=True,
            )
        except BaseException as error:
            recovery_error = error

    selected_error = _select_error_after_stop(
        termination=_termination_controller,
        operation_error=None,
        transition_error=transition_error,
        recovery_error=recovery_error,
    )
    if selected_error is not None:
        raise selected_error
    print("Gate A services stopped; named volumes were preserved")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run guarded pinkdooHub Gate A deployment operations",
    )
    parser.add_argument("command", choices=LIFECYCLE_COMMANDS)
    parser.add_argument("--mode", choices=tuple(MODE_COMPOSE), required=True)
    parser.add_argument(
        "--config-file",
        type=Path,
        default=DEFAULT_CONFIG_FILE,
    )
    parser.add_argument(
        "--secret-dir",
        type=Path,
        default=DEFAULT_SECRET_DIR,
    )
    parser.add_argument(
        "--record-dir",
        type=Path,
        default=DEFAULT_RECORD_DIR,
    )
    parser.add_argument(
        "--acceptance-record-dir",
        type=Path,
        default=DEFAULT_M9_ACCEPTANCE_RECORD_DIR,
    )
    parser.add_argument("--wait-timeout", type=int, default=180)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 30 <= args.wait_timeout <= 600:
        print(
            "Gate A operation failed: --wait-timeout must be between 30 and 600",
            file=sys.stderr,
        )
        return 1
    common = {
        "config_file": args.config_file,
        "secret_dir": args.secret_dir,
        "mode": args.mode,
    }
    try:
        mutating = args.command in {
            "infra-up",
            "initial-migrate",
            "app-up",
            "safe-stop",
        }
        lock_context = (
            operation_lock()
            if mutating
            else nullcontext()
        )
        termination_context = (
            operation_termination_guard() if mutating else nullcontext(None)
        )
        with lock_context, termination_context as termination_controller:
            if args.command == "preflight":
                preflight(**common)
            elif args.command == "database-status":
                database_status(**common)
            elif args.command == "infra-up":
                infra_up(
                    **common,
                    wait_timeout=args.wait_timeout,
                    _termination_controller=termination_controller,
                )
            elif args.command == "initial-migrate":
                initial_migrate(
                    **common,
                    record_dir=args.record_dir,
                    acceptance_record_dir=args.acceptance_record_dir,
                    _termination_controller=termination_controller,
                )
            elif args.command == "app-up":
                app_up(
                    **common,
                    record_dir=args.record_dir,
                    wait_timeout=args.wait_timeout,
                    acceptance_record_dir=args.acceptance_record_dir,
                    _termination_controller=termination_controller,
                )
            elif args.command == "status":
                status(**common, record_dir=args.record_dir)
            else:
                safe_stop(
                    **common,
                    _termination_controller=termination_controller,
                )
    except (GateAError, subprocess.CalledProcessError) as error:
        print(f"Gate A {args.command} failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
