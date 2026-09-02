#!/usr/bin/env python3
"""Gate A 首个 SUPER_ADMIN 的受控交互式 Bootstrap。

密码只通过 TTY 隐藏输入。初始密码短暂写入 ``/run`` 的 root-owned
Secret，用于首次创建与严格重放；最终密码只存在于进程内存和
loopback HTTPS/HTTP 请求体。主机脚本不会在参数、宿主环境、日志或
Record 中保存密码、Token、手机号或用户名。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.release import gatea_backup
from scripts.release import gatea_operations as gatea


DEFAULT_BOOTSTRAP_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/bootstrap")
DEFAULT_BOOTSTRAP_SECRET_FILE = Path(
    "/run/pinkdoohub-gatea/bootstrap_password.pending"
)
BOOTSTRAP_RECORD_NAME = "super-admin-bootstrap.json"
USERNAME_PATTERN = re.compile(r"^.{3,32}$", re.DOTALL)
NICKNAME_PATTERN = re.compile(r"^.{1,32}$", re.DOTALL)
PHONE_PATTERN = re.compile(r"^1[3-9][0-9]{9}$")
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 64
BOOTSTRAP_SECRET_GID = gatea.APP_RUNTIME_SECRET_GID
BOOTSTRAP_SNAPSHOT_COMMAND = r"""MYSQL_PWD="$(cat /run/secrets/mysql_root_password)"
export MYSQL_PWD
mysql --batch --skip-column-names --host=127.0.0.1 --user=root "$MYSQL_DATABASE" <<'SQL'
SELECT JSON_OBJECT(
  'super_admins', (SELECT COUNT(*) FROM users WHERE role = 3),
  'normal_super_admins', (SELECT COUNT(*) FROM users WHERE role = 3 AND status = 1),
  'bootstrap_audits', (
    SELECT COUNT(*) FROM audit_logs WHERE action = 'BOOTSTRAP_SUPER_ADMIN'
  ),
  'self_target_audits', (
    SELECT COUNT(*)
    FROM audit_logs a
    JOIN users u ON u.id = a.operator_id
    WHERE a.action = 'BOOTSTRAP_SUPER_ADMIN'
      AND a.target_type = 'user'
      AND a.target_id = u.id
      AND u.role = 3
  ),
  'user_id', (SELECT id FROM users WHERE role = 3 ORDER BY id LIMIT 1),
  'updated_at', (
    SELECT DATE_FORMAT(updated_at, '%Y-%m-%dT%H:%i:%s.%fZ')
    FROM users WHERE role = 3 ORDER BY id LIMIT 1
  )
);
SQL"""


class SecureArgumentParser(argparse.ArgumentParser):
    """拒绝参数时不回显可能被误放到命令行中的 Secret。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: invalid arguments\n")


def _validate_identity(
    *, username: str, nickname: str, phone: str, confirm_username: str
) -> None:
    """在创建 Secret 前验证身份形状和精确确认，不回显 PII。"""

    if USERNAME_PATTERN.fullmatch(username) is None:
        raise gatea.GateAError("Gate A bootstrap username is invalid")
    if NICKNAME_PATTERN.fullmatch(nickname) is None:
        raise gatea.GateAError("Gate A bootstrap nickname is invalid")
    if PHONE_PATTERN.fullmatch(phone) is None:
        raise gatea.GateAError("Gate A bootstrap phone is invalid")
    if confirm_username != username:
        raise gatea.GateAError("Gate A bootstrap username confirmation does not match")


def _validate_passwords(initial_password: str, final_password: str) -> None:
    for label, password in (
        ("initial", initial_password),
        ("final", final_password),
    ):
        if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
            raise gatea.GateAError(
                f"Gate A bootstrap {label} password must be 8-64 characters"
            )
    if initial_password == final_password:
        raise gatea.GateAError(
            "Gate A bootstrap final password must differ from the initial password"
        )


def _read_password_twice(label: str) -> str:
    if not sys.stdin.isatty():
        raise gatea.GateAError("Gate A bootstrap passwords require an interactive TTY")
    password = getpass.getpass(f"{label} password: ")
    confirmation = getpass.getpass(f"Confirm {label.lower()} password: ")
    if password != confirmation:
        raise gatea.GateAError(
            f"Gate A bootstrap {label.lower()} password confirmation does not match"
        )
    return password


def read_passwords() -> tuple[str, str]:
    """依次隐藏读取初始与最终密码；调用方不得输出返回值。"""

    initial_password = _read_password_twice("Initial bootstrap")
    final_password = _read_password_twice("Final rotated")
    _validate_passwords(initial_password, final_password)
    return initial_password, final_password


def _bootstrap_environment(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    secret_file: Path,
    username: str,
    nickname: str,
    phone: str,
) -> dict[str, str]:
    return gatea._operation_environment(values, config_file, secret_dir) | {
        "GATEA_BOOTSTRAP_SECRET_FILE": str(secret_file),
        "GATEA_BOOTSTRAP_USERNAME": username,
        "GATEA_BOOTSTRAP_NICKNAME": nickname,
        "GATEA_BOOTSTRAP_PHONE": phone,
    }


def _run_bootstrap_compose(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    secret_file: Path,
    username: str,
    nickname: str,
    phone: str,
    arguments: Sequence[str],
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        gatea.compose_command(
            config_file=config_file,
            mode="loopback",
            include_bootstrap=True,
            profiles=("bootstrap",),
            arguments=arguments,
        ),
        check=False,
        cwd=gatea.REPOSITORY_ROOT,
        env=_bootstrap_environment(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            secret_file=secret_file,
            username=username,
            nickname=nickname,
            phone=phone,
        ),
        text=True,
        capture_output=capture_output,
    )


def _create_secret_file(path: Path, password: str) -> bool:
    """在 root-owned ``/run`` 创建 0440 Secret，返回是否创建父目录。"""

    if path.name != "bootstrap_password.pending":
        raise gatea.GateAError("Gate A bootstrap Secret path is not approved")
    parent_created = False
    if not path.parent.exists():
        path.parent.mkdir(mode=0o700)
        parent_created = True
    gatea._validate_root_directory(
        path.parent,
        0o700,
        "Gate A bootstrap runtime Secret directory",
    )
    if path.exists():
        raise gatea.GateAError("Gate A bootstrap pending Secret already exists")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o440)
        os.fchown(descriptor, 0, BOOTSTRAP_SECRET_GID)
        os.fchmod(descriptor, 0o440)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(password)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        if parent_created:
            path.parent.rmdir()
        raise
    return parent_created


def _remove_secret_file(path: Path, *, parent_created: bool) -> None:
    path.unlink(missing_ok=True)
    if path.exists():
        raise gatea.GateAError("Gate A bootstrap pending Secret could not be removed")
    if parent_created:
        path.parent.rmdir()


def _parse_bootstrap_result(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode != 0:
        raise gatea.GateAError("Gate A bootstrap container failed")
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    created = "created=True replay=False" in output
    replay = "created=False replay=True" in output
    if created == replay:
        raise gatea.GateAError("Gate A bootstrap result marker is invalid")
    return created


def _run_bootstrap_once(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
    secret_file: Path,
    username: str,
    nickname: str,
    phone: str,
) -> bool:
    result = _run_bootstrap_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        secret_file=secret_file,
        username=username,
        nickname=nickname,
        phone=phone,
        arguments=("run", "--rm", "--no-deps", "bootstrap"),
        capture_output=True,
    )
    return _parse_bootstrap_result(result)


def _bootstrap_container_absent() -> None:
    result = subprocess.run(
        (
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            "label=com.docker.compose.project=pinkdoohub-gatea",
            "--filter",
            "label=com.docker.compose.service=bootstrap",
        ),
        check=True,
        text=True,
        capture_output=True,
    )
    if result.stdout.strip():
        raise gatea.GateAError("Gate A bootstrap one-off container was not removed")


def _bootstrap_snapshot(
    *,
    values: Mapping[str, str],
    config_file: Path,
    secret_dir: Path,
) -> dict[str, Any]:
    result = gatea._run_compose(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        arguments=(
            "exec",
            "--no-tty",
            "mysql",
            "sh",
            "-ec",
            BOOTSTRAP_SNAPSHOT_COMMAND,
        ),
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as error:
        raise gatea.GateAError(
            "Gate A bootstrap database evidence is invalid"
        ) from error
    if not isinstance(payload, dict):
        raise gatea.GateAError(
            "Gate A bootstrap database evidence has an invalid shape"
        )
    return payload


def _validate_bootstrap_snapshot(payload: Mapping[str, Any]) -> int:
    if (
        payload.get("super_admins") != 1
        or payload.get("normal_super_admins") != 1
        or payload.get("bootstrap_audits") != 1
        or payload.get("self_target_audits") != 1
        or not isinstance(payload.get("user_id"), int)
        or not payload.get("updated_at")
    ):
        raise gatea.GateAError("Gate A bootstrap database evidence does not match")
    return int(payload["user_id"])


def _json_request(
    *,
    base_url: str,
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
            raw = response.read()
    except HTTPError as error:
        status = error.code
        raw = error.read()
    except (OSError, URLError) as error:
        raise gatea.GateAError(
            "Gate A bootstrap loopback API is unavailable"
        ) from error
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise gatea.GateAError("Gate A bootstrap API response is invalid") from error
    if not isinstance(document, dict):
        raise gatea.GateAError("Gate A bootstrap API response has an invalid shape")
    return status, document


def _login(
    *, base_url: str, username: str, password: str
) -> dict[str, Any]:
    status, document = _json_request(
        base_url=base_url,
        method="POST",
        path="/api/v1/auth/login",
        payload={"username": username, "password": password},
    )
    data = document.get("data")
    if (
        status != 200
        or document.get("code") != 0
        or not isinstance(data, dict)
        or data.get("user", {}).get("role") != "super_admin"
        or data.get("user", {}).get("status") != "normal"
        or not isinstance(data.get("access_token"), str)
        or not isinstance(data.get("refresh_token"), str)
    ):
        raise gatea.GateAError("Gate A SUPER_ADMIN login verification failed")
    return data


def _change_password(
    *, base_url: str, token: str, old_password: str, new_password: str
) -> None:
    status, document = _json_request(
        base_url=base_url,
        method="PUT",
        path="/api/v1/users/me/password",
        token=token,
        payload={"old_password": old_password, "new_password": new_password},
    )
    if status != 200 or document.get("code") != 0:
        raise gatea.GateAError("Gate A SUPER_ADMIN password rotation failed")


def _expect_login_rejected(*, base_url: str, username: str, password: str) -> None:
    status, document = _json_request(
        base_url=base_url,
        method="POST",
        path="/api/v1/auth/login",
        payload={"username": username, "password": password},
    )
    if status != 400 or document.get("code") != 1003:
        raise gatea.GateAError("Gate A initial password was not rejected")


def _logout_and_verify_refresh_revoked(
    *, base_url: str, access_token: str, refresh_token: str
) -> None:
    status, document = _json_request(
        base_url=base_url,
        method="POST",
        path="/api/v1/auth/logout",
        token=access_token,
    )
    if status != 200 or document.get("code") != 0:
        raise gatea.GateAError("Gate A bootstrap session logout failed")
    refresh_status, refresh_document = _json_request(
        base_url=base_url,
        method="POST",
        path="/api/v1/auth/refresh",
        payload={"refresh_token": refresh_token},
    )
    if refresh_status != 400 or refresh_document.get("code") != 1006:
        raise gatea.GateAError("Gate A bootstrap refresh session was not revoked")


def _record_path(record_dir: Path) -> Path:
    return record_dir / BOOTSTRAP_RECORD_NAME


def execute_bootstrap(
    *,
    username: str,
    nickname: str,
    phone: str,
    confirm_username: str,
    initial_password: str,
    final_password: str,
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    bootstrap_record_dir: Path,
    secret_file: Path,
) -> None:
    """执行首次/重放、登录、轮换、会话撤销并写脱敏 Record。"""

    if os.geteuid() != 0:
        raise gatea.GateAError("Gate A bootstrap must run as root")
    _validate_identity(
        username=username,
        nickname=nickname,
        phone=phone,
        confirm_username=confirm_username,
    )
    _validate_passwords(initial_password, final_password)
    gatea._require_loopback_write_mode("loopback")
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        require_available_port=False,
    )
    gatea._validate_root_directory(
        bootstrap_record_dir,
        0o755,
        "Gate A bootstrap record directory",
    )
    record_path = _record_path(bootstrap_record_dir)
    if record_path.exists():
        raise gatea.GateAError("Gate A SUPER_ADMIN bootstrap is already recorded")
    if secret_file.exists():
        raise gatea.GateAError("Gate A bootstrap pending Secret already exists")

    image_id = gatea.validate_app_image(values)
    candidate_sha = gatea._candidate_sha(values)
    gatea._require_migration_record(
        record_dir=release_record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    rows = gatea._compose_ps(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        services=("mysql", "redis", "app", "nginx"),
    )
    gatea._ensure_services_healthy(rows, "mysql", "redis", "app", "nginx")
    gatea._validate_loopback_publishers(
        rows,
        int(values.get("GATEA_LOOPBACK_PORT", "18080")),
    )

    started_at = datetime.now(timezone.utc).isoformat()
    parent_created = False
    secret_created = False
    operation_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    first_created = False
    user_id = 0
    try:
        parent_created = _create_secret_file(secret_file, initial_password)
        secret_created = True
        config_result = _run_bootstrap_compose(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            secret_file=secret_file,
            username=username,
            nickname=nickname,
            phone=phone,
            arguments=("config", "--quiet"),
        )
        if config_result.returncode != 0:
            raise gatea.GateAError("Gate A bootstrap Compose contract is invalid")

        first_created = _run_bootstrap_once(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            secret_file=secret_file,
            username=username,
            nickname=nickname,
            phone=phone,
        )
        first_snapshot = _bootstrap_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
        )
        user_id = _validate_bootstrap_snapshot(first_snapshot)
        if _run_bootstrap_once(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
            secret_file=secret_file,
            username=username,
            nickname=nickname,
            phone=phone,
        ):
            raise gatea.GateAError(
                "Gate A bootstrap strict replay created another user"
            )
        replay_snapshot = _bootstrap_snapshot(
            values=values,
            config_file=config_file,
            secret_dir=secret_dir,
        )
        if replay_snapshot != first_snapshot:
            raise gatea.GateAError(
                "Gate A bootstrap strict replay mutated database state"
            )
        _bootstrap_container_absent()

        base_url = (
            "http://127.0.0.1:"
            f"{int(values.get('GATEA_LOOPBACK_PORT', '18080'))}"
        )
        initial_login = _login(
            base_url=base_url,
            username=username,
            password=initial_password,
        )
        if initial_login.get("user", {}).get("id") != user_id:
            raise gatea.GateAError("Gate A bootstrap login identity does not match")
        # Logout 只撤销同一 jti 的 Refresh 会话，当前 Access Token 仍可用于
        # 紧接着的密码轮换。先撤销初始 Refresh，缩小轮换后失败时的残留面。
        _logout_and_verify_refresh_revoked(
            base_url=base_url,
            access_token=initial_login["access_token"],
            refresh_token=initial_login["refresh_token"],
        )
        _change_password(
            base_url=base_url,
            token=initial_login["access_token"],
            old_password=initial_password,
            new_password=final_password,
        )
        _expect_login_rejected(
            base_url=base_url,
            username=username,
            password=initial_password,
        )
        final_login = _login(
            base_url=base_url,
            username=username,
            password=final_password,
        )
        if final_login.get("user", {}).get("id") != user_id:
            raise gatea.GateAError("Gate A rotated login identity does not match")
        _logout_and_verify_refresh_revoked(
            base_url=base_url,
            access_token=final_login["access_token"],
            refresh_token=final_login["refresh_token"],
        )
    except BaseException as error:
        operation_error = error
    finally:
        if secret_created:
            try:
                _remove_secret_file(
                    secret_file,
                    parent_created=parent_created,
                )
            except BaseException as error:
                cleanup_error = error

    if cleanup_error is not None:
        raise gatea.GateAError(
            "Gate A bootstrap temporary Secret cleanup failed"
        ) from cleanup_error
    if operation_error is not None:
        if isinstance(operation_error, (KeyboardInterrupt, SystemExit)):
            raise operation_error
        raise gatea.GateAError(
            "Gate A SUPER_ADMIN bootstrap failed"
        ) from operation_error
    if secret_file.exists():
        raise gatea.GateAError("Gate A bootstrap pending Secret still exists")

    gatea_backup._write_json_atomic(
        record_path,
        {
            "schema_version": 1,
            "candidate_sha": candidate_sha,
            "image_id": image_id,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "created_on_this_run": first_created,
            "strict_replay_verified": True,
            "identity_fields_verified": True,
            "super_admin_count": 1,
            "bootstrap_audit_count": 1,
            "bootstrap_audit_self_target": True,
            "role": "super_admin",
            "status": "normal",
            "initial_login_verified": True,
            "password_rotated": True,
            "old_password_rejected": True,
            "rotated_login_verified": True,
            "refresh_sessions_revoked": True,
            "initial_secret_file_removed": True,
            "loopback_only": True,
            "pii_recorded": False,
            "secret_values_recorded": False,
            "passed": True,
        },
        0o644,
    )
    print("Gate A SUPER_ADMIN bootstrap, strict replay, and credential rotation passed")


def _parser() -> argparse.ArgumentParser:
    parser = SecureArgumentParser(
        description="Run controlled interactive Gate A SUPER_ADMIN bootstrap",
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--nickname", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--confirm-username", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
    parser.add_argument(
        "--release-record-dir", type=Path, default=gatea.DEFAULT_RECORD_DIR
    )
    parser.add_argument(
        "--bootstrap-record-dir",
        type=Path,
        default=DEFAULT_BOOTSTRAP_RECORD_DIR,
    )
    parser.add_argument(
        "--secret-file",
        type=Path,
        default=DEFAULT_BOOTSTRAP_SECRET_FILE,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.apply:
        print("Gate A bootstrap failed: --apply is required", file=sys.stderr)
        return 2
    try:
        _validate_identity(
            username=args.username,
            nickname=args.nickname,
            phone=args.phone,
            confirm_username=args.confirm_username,
        )
        initial_password, final_password = read_passwords()
        execute_bootstrap(
            username=args.username,
            nickname=args.nickname,
            phone=args.phone,
            confirm_username=args.confirm_username,
            initial_password=initial_password,
            final_password=final_password,
            config_file=args.config_file,
            secret_dir=args.secret_dir,
            release_record_dir=args.release_record_dir,
            bootstrap_record_dir=args.bootstrap_record_dir,
            secret_file=args.secret_file,
        )
    except KeyboardInterrupt:
        print("\nGate A bootstrap cancelled", file=sys.stderr)
        return 130
    except (gatea.GateAError, subprocess.CalledProcessError) as error:
        print(f"Gate A bootstrap failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
