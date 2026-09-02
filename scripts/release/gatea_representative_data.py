#!/usr/bin/env python3
"""通过 Gate A loopback 正式 API 创建最小代表性备份数据。"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import getpass
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Any, Mapping
from urllib.parse import urlparse

from scripts.release import gatea_backup
from scripts.release import gatea_operations as gatea


DEFAULT_BOOTSTRAP_RECORD = Path(
    "/srv/pinkdoohub/gatea/records/bootstrap/super-admin-bootstrap.json"
)
DEFAULT_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/representative-data")
RECORD_NAME = "gatea-representative-data.json"
SUPER_ADMIN_USERNAME_PATTERN = re.compile(r"^.{3,32}$", re.DOTALL)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 64
SYNTHETIC_USERNAME = "gatea_backup_fixture_user"
SYNTHETIC_NICKNAME = "Gate A Backup Fixture"
SYNTHETIC_PHONE = "13900009401"
EXPERIENCE_NAME = "[GATEA-BACKUP] Representative Experience"
KIT_NAME = "[GATEA-BACKUP] Representative Kit"
EXPERIENCE_PRICE = "88.00"
KIT_PRICE = "36.00"
KIT_OPENING_STOCK = 10
KIT_ORDER_QUANTITY = 2
INVENTORY_IDEMPOTENCY_KEY = "gatea-backup-representative-kit-opening-v1"
PNG_CONTENT = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/w8AAusB9Y9Z4xkAAAAASUVORK5CYII="
)

BASELINE_SNAPSHOT = {
    "users": 1,
    "products": 0,
    "experience_options": 0,
    "product_images": 0,
    "product_kits": 0,
    "kit_stock": 0,
    "orders": 0,
    "order_items": 0,
    "order_total": "0.00",
    "inventory_transactions": 0,
    "inventory_change": 0,
    "audit_logs": 3,
}

EXPECTED_SNAPSHOT = {
    "users": 2,
    "products": 2,
    "experience_options": 1,
    "product_images": 3,
    "product_kits": 1,
    "kit_stock": KIT_OPENING_STOCK,
    "orders": 2,
    "order_items": 3,
    "order_total": "248.00",
    "inventory_transactions": 3,
    "inventory_change": KIT_OPENING_STOCK,
}

REPRESENTATIVE_DETAILS_COMMAND = f"""MYSQL_PWD=\"$(cat /run/secrets/mysql_root_password)\"
export MYSQL_PWD
mysql --batch --skip-column-names --host=127.0.0.1 --user=root \"$MYSQL_DATABASE\" <<'SQL'
SELECT JSON_OBJECT(
  'normal_super_admins', (
    SELECT COUNT(*) FROM users WHERE role = 3 AND status = 1
  ),
  'representative_users', (
    SELECT COUNT(*) FROM users WHERE username = '{SYNTHETIC_USERNAME}'
  ),
  'representative_disabled_users', (
    SELECT COUNT(*) FROM users
    WHERE username = '{SYNTHETIC_USERNAME}' AND role = 1 AND status = 2
  ),
  'representative_online_products', (
    SELECT COUNT(*) FROM products
    WHERE name IN ('{EXPERIENCE_NAME}', '{KIT_NAME}')
      AND status = 'online' AND is_deleted = 0
  ),
  'representative_cancelled_orders', (
    SELECT COUNT(*) FROM orders o
    INNER JOIN users u ON u.id = o.user_id
    WHERE u.username = '{SYNTHETIC_USERNAME}' AND o.status = 2
  ),
  'representative_completed_orders', (
    SELECT COUNT(*) FROM orders o
    INNER JOIN users u ON u.id = o.user_id
    WHERE u.username = '{SYNTHETIC_USERNAME}' AND o.status = 3
  ),
  'admin_adjustments', (
    SELECT COUNT(*) FROM inventory_transactions
    WHERE transaction_type = 'admin_adjustment'
  ),
  'order_deductions', (
    SELECT COUNT(*) FROM inventory_transactions
    WHERE transaction_type = 'order_deduction'
  ),
  'cancellation_restores', (
    SELECT COUNT(*) FROM inventory_transactions
    WHERE transaction_type = 'order_cancellation_restore'
  )
);
SQL"""

EXPECTED_DETAILS = {
    "normal_super_admins": 1,
    "representative_users": 1,
    "representative_disabled_users": 1,
    "representative_online_products": 2,
    "representative_cancelled_orders": 1,
    "representative_completed_orders": 1,
    "admin_adjustments": 1,
    "order_deductions": 1,
    "cancellation_restores": 1,
}


class RepresentativeDataError(RuntimeError):
    """不包含身份、密码、Token 或响应正文的安全错误。"""


class SecureArgumentParser(argparse.ArgumentParser):
    """参数错误不回显可能包含身份值的命令行。"""

    def error(self, message: str) -> None:
        self.exit(2, "Gate A representative data arguments are invalid\n")


@dataclass(frozen=True, slots=True)
class PreparedContext:
    values: Mapping[str, str]
    config_file: Path
    secret_dir: Path
    record_dir: Path
    candidate_sha: str
    image_id: str
    before_snapshot: Mapping[str, Any]
    started_at: str


class LoopbackClient:
    """只连接冻结回环端口，并仅记录脱敏步骤结果。"""

    def __init__(self, port: int) -> None:
        self.port = port
        self.results: list[dict[str, object]] = []

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
        request_headers = {
            "Accept": "application/json",
            "Connection": "close",
            "User-Agent": "pinkdoohub-gatea-representative-data/1",
        }
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        if content_type is not None:
            request_headers["Content-Type"] = content_type
        if body is not None:
            request_headers["Content-Length"] = str(len(body))
        if headers is not None:
            request_headers.update(headers)

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            response_headers = dict(response.getheaders())
            status = response.status
        except OSError as error:
            raise RepresentativeDataError(
                f"Gate A representative step {step} could not reach loopback"
            ) from error
        finally:
            connection.close()

        code: object = None
        if response_headers.get("Content-Type", "").startswith("application/json"):
            try:
                document = json.loads(content)
                code = document.get("code") if isinstance(document, dict) else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                code = "invalid-json"
        self.results.append(
            {
                "step": step,
                "method": method,
                "path": path,
                "status": status,
                "code": code,
                "passed": status == expected_status,
            }
        )
        if status != expected_status:
            raise RepresentativeDataError(
                f"Gate A representative step {step} failed: "
                f"status={status} code={code}"
            )
        return content, response_headers

    def json_request(
        self,
        step: str,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: object | None = None,
        headers: Mapping[str, str] | None = None,
        expected_status: int = 200,
        expected_code: int = 0,
    ) -> dict[str, Any]:
        body = None
        content_type = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json"
        content, _ = self.request(
            step,
            method,
            path,
            token=token,
            body=body,
            content_type=content_type,
            headers=headers,
            expected_status=expected_status,
        )
        try:
            document = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RepresentativeDataError(
                f"Gate A representative step {step} returned invalid JSON"
            ) from error
        if not isinstance(document, dict) or document.get("code") != expected_code:
            raise RepresentativeDataError(
                f"Gate A representative step {step} returned an invalid envelope"
            )
        return document


def _validate_identity(username: str, confirmation: str) -> None:
    if SUPER_ADMIN_USERNAME_PATTERN.fullmatch(username) is None:
        raise RepresentativeDataError("Gate A SUPER_ADMIN username is invalid")
    if username != confirmation:
        raise RepresentativeDataError(
            "Gate A SUPER_ADMIN username confirmation does not match"
        )


def _validate_password(password: str, confirmation: str) -> None:
    if password != confirmation:
        raise RepresentativeDataError(
            "Gate A SUPER_ADMIN password confirmation does not match"
        )
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise RepresentativeDataError(
            "Gate A SUPER_ADMIN password length is invalid"
        )


def _load_bootstrap_record(path: Path, candidate_sha: str, image_id: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise RepresentativeDataError(
            "Gate A verified bootstrap record is unavailable"
        ) from error
    if (
        not isinstance(payload, dict)
        or payload.get("passed") is not True
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("image_id") != image_id
        or payload.get("super_admin_count") != 1
        or payload.get("password_rotated") is not True
        or payload.get("initial_secret_file_removed") is not True
        or payload.get("pii_recorded") is not False
        or payload.get("secret_values_recorded") is not False
    ):
        raise RepresentativeDataError("Gate A verified bootstrap record is invalid")


def _assert_snapshot(
    snapshot: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    mismatched = [key for key, value in expected.items() if snapshot.get(key) != value]
    if mismatched:
        raise RepresentativeDataError(
            f"Gate A {label} snapshot does not match: {','.join(sorted(mismatched))}"
        )


def _representative_details(context: PreparedContext) -> dict[str, Any]:
    result = gatea._run_compose(
        values=context.values,
        config_file=context.config_file,
        secret_dir=context.secret_dir,
        mode="loopback",
        arguments=(
            "exec",
            "--no-tty",
            "mysql",
            "sh",
            "-ec",
            REPRESENTATIVE_DETAILS_COMMAND,
        ),
        capture_output=True,
    )
    return gatea_backup._parse_snapshot(result.stdout)


def prepare(
    *,
    username: str,
    confirm_username: str,
    config_file: Path,
    secret_dir: Path,
    release_record_dir: Path,
    bootstrap_record: Path,
    record_dir: Path,
) -> PreparedContext:
    """在读取密码前完成 Root、候选、健康、端口和空基线检查。"""

    if os.geteuid() != 0:
        raise RepresentativeDataError("Gate A representative data must run as root")
    _validate_identity(username, confirm_username)
    values = gatea._validated_inputs(
        config_file=config_file,
        secret_dir=secret_dir,
        mode="loopback",
        require_available_port=False,
    )
    gatea._validate_root_directory(
        record_dir,
        0o755,
        "Gate A representative data record directory",
    )
    record_path = record_dir / RECORD_NAME
    if record_path.exists():
        raise RepresentativeDataError(
            "Gate A representative data is already recorded"
        )
    image_id = gatea.validate_app_image(values)
    candidate_sha = gatea._candidate_sha(values)
    gatea._require_migration_record(
        record_dir=release_record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
    )
    _load_bootstrap_record(bootstrap_record, candidate_sha, image_id)
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
    snapshot = gatea_backup._source_snapshot(
        values,
        config_file,
        secret_dir,
        "loopback",
    )
    _assert_snapshot(snapshot, BASELINE_SNAPSHOT, "pre-write")
    if gatea_backup._source_image_manifest(
        values, config_file, secret_dir, "loopback"
    ):
        raise RepresentativeDataError(
            "Gate A pre-write image volume is not empty"
        )
    return PreparedContext(
        values=values,
        config_file=config_file,
        secret_dir=secret_dir,
        record_dir=record_dir,
        candidate_sha=candidate_sha,
        image_id=image_id,
        before_snapshot=snapshot,
        started_at=datetime.now(timezone.utc).isoformat(),
    )


def _login(
    client: LoopbackClient,
    *,
    step: str,
    username: str,
    password: str,
    expected_role: str,
) -> dict[str, Any]:
    document = client.json_request(
        step,
        "POST",
        "/api/v1/auth/login",
        payload={"username": username, "password": password},
    )
    data = document.get("data")
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("access_token"), str)
        or not isinstance(data.get("refresh_token"), str)
        or not isinstance(data.get("user"), dict)
        or data["user"].get("role") != expected_role
        or data["user"].get("status") != "normal"
    ):
        raise RepresentativeDataError(
            f"Gate A representative step {step} returned an invalid login"
        )
    return data


def _logout_and_verify(
    client: LoopbackClient,
    *,
    step_prefix: str,
    access_token: str,
    refresh_token: str,
) -> None:
    client.json_request(
        f"{step_prefix}-logout",
        "POST",
        "/api/v1/auth/logout",
        token=access_token,
    )
    client.json_request(
        f"{step_prefix}-refresh-revoked",
        "POST",
        "/api/v1/auth/refresh",
        payload={"refresh_token": refresh_token},
        expected_status=400,
        expected_code=1006,
    )


def _multipart_image(fields: Mapping[str, str]) -> tuple[bytes, str]:
    boundary = f"gatea-{secrets.token_hex(12)}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend(
            (
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            )
        )
    parts.extend(
        (
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; '
            b'filename="gatea-representative.png"\r\n',
            b"Content-Type: image/png\r\n\r\n",
            PNG_CONTENT,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        )
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _upload_image(
    client: LoopbackClient,
    *,
    step: str,
    path: str,
    token: str,
    fields: Mapping[str, str],
) -> dict[str, Any]:
    body, content_type = _multipart_image(fields)
    content, _ = client.request(
        step,
        "POST",
        path,
        token=token,
        body=body,
        content_type=content_type,
        expected_status=201,
    )
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RepresentativeDataError(
            f"Gate A representative step {step} returned invalid JSON"
        ) from error
    data = document.get("data") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or document.get("code") != 0
        or not isinstance(data, dict)
    ):
        raise RepresentativeDataError(
            f"Gate A representative step {step} returned an invalid envelope"
        )
    return data


def _verify_image_read(
    client: LoopbackClient, *, step: str, image: Mapping[str, Any]
) -> None:
    image_url = image.get("image_url")
    if not isinstance(image_url, str):
        raise RepresentativeDataError(
            f"Gate A representative step {step} has no image URL"
        )
    parsed = urlparse(image_url)
    if parsed.scheme != "https" or not parsed.path.startswith("/uploads/products/"):
        raise RepresentativeDataError(
            f"Gate A representative step {step} returned an invalid image URL"
        )
    content, headers = client.request(step, "GET", parsed.path)
    if content != PNG_CONTENT or not headers.get("Content-Type", "").startswith(
        "image/png"
    ):
        raise RepresentativeDataError(
            f"Gate A representative step {step} returned invalid image content"
        )


def execute(
    context: PreparedContext,
    *,
    username: str,
    password: str,
) -> dict[str, Any]:
    """经正式 API 写入数据、禁用合成账号并生成脱敏成功 Record。"""

    client = LoopbackClient(int(context.values.get("GATEA_LOOPBACK_PORT", "18080")))
    synthetic_password = secrets.token_urlsafe(32)
    super_admin: dict[str, Any] | None = None
    synthetic_user: dict[str, Any] | None = None
    synthetic_user_id: int | None = None
    synthetic_logged_out = False
    synthetic_disabled = False
    super_admin_logged_out = False
    operation_error: BaseException | None = None
    cleanup_errors: list[str] = []
    result_ids: dict[str, Any] = {}

    try:
        super_admin = _login(
            client,
            step="login-super-admin",
            username=username,
            password=password,
            expected_role="super_admin",
        )
        registered = client.json_request(
            "register-synthetic-user",
            "POST",
            "/api/v1/auth/register",
            payload={
                "username": SYNTHETIC_USERNAME,
                "password": synthetic_password,
                "nickname": SYNTHETIC_NICKNAME,
                "phone": SYNTHETIC_PHONE,
            },
            expected_status=201,
        )["data"]
        synthetic_user_id = int(registered["id"])
        synthetic_user = _login(
            client,
            step="login-synthetic-user",
            username=SYNTHETIC_USERNAME,
            password=synthetic_password,
            expected_role="user",
        )

        admin_token = super_admin["access_token"]
        user_token = synthetic_user["access_token"]

        experience = client.json_request(
            "create-experience",
            "POST",
            "/api/v1/admin/products/experience",
            token=admin_token,
            payload={
                "name": EXPERIENCE_NAME,
                "description": "Controlled Gate A backup and restore fixture",
            },
            expected_status=201,
        )["data"]
        option = client.json_request(
            "create-experience-option",
            "POST",
            f"/api/v1/admin/products/experience/{experience['id']}/options",
            token=admin_token,
            payload={
                "duration_minutes": 60,
                "participants": 2,
                "day_type": "weekday",
                "price": EXPERIENCE_PRICE,
            },
            expected_status=201,
        )["data"]
        experience_image = _upload_image(
            client,
            step="upload-experience-cover",
            path=f"/api/v1/admin/products/{experience['id']}/images",
            token=admin_token,
            fields={"is_cover": "true", "sort": "0"},
        )
        option_image = _upload_image(
            client,
            step="upload-option-image",
            path=f"/api/v1/admin/options/{option['id']}/images",
            token=admin_token,
            fields={"sort": "0"},
        )
        client.json_request(
            "online-experience",
            "PATCH",
            f"/api/v1/admin/products/{experience['id']}/online",
            token=admin_token,
        )

        kit = client.json_request(
            "create-kit",
            "POST",
            "/api/v1/admin/products/kit",
            token=admin_token,
            payload={
                "name": KIT_NAME,
                "description": "Controlled Gate A inventory backup fixture",
                "price": KIT_PRICE,
            },
            expected_status=201,
        )["data"]
        kit_image = _upload_image(
            client,
            step="upload-kit-cover",
            path=f"/api/v1/admin/products/{kit['id']}/images",
            token=admin_token,
            fields={"is_cover": "true", "sort": "0"},
        )
        adjustment = client.json_request(
            "adjust-kit-stock",
            "POST",
            f"/api/v1/admin/products/kit/{kit['id']}/inventory-adjustments",
            token=admin_token,
            payload={
                "change": KIT_OPENING_STOCK,
                "reason": "Gate A representative backup opening stock",
            },
            headers={"Idempotency-Key": INVENTORY_IDEMPOTENCY_KEY},
            expected_status=201,
        )["data"]
        if adjustment.get("stock") != KIT_OPENING_STOCK:
            raise RepresentativeDataError(
                "Gate A representative inventory adjustment is invalid"
            )
        client.json_request(
            "online-kit",
            "PATCH",
            f"/api/v1/admin/products/{kit['id']}/online",
            token=admin_token,
        )

        for step, image in (
            ("read-experience-cover", experience_image),
            ("read-option-image", option_image),
            ("read-kit-cover", kit_image),
        ):
            _verify_image_read(client, step=step, image=image)

        mixed_order = client.json_request(
            "create-cancellable-mixed-order",
            "POST",
            "/api/v1/orders",
            token=user_token,
            payload={
                "items": [
                    {
                        "product_id": experience["id"],
                        "experience_option_id": option["id"],
                        "quantity": 1,
                    },
                    {
                        "product_id": kit["id"],
                        "experience_option_id": None,
                        "quantity": KIT_ORDER_QUANTITY,
                    },
                ],
                "remark": "Gate A representative cancelled mixed order",
            },
            expected_status=201,
        )["data"]
        cancelled = client.json_request(
            "cancel-mixed-order",
            "PATCH",
            f"/api/v1/orders/{mixed_order['id']}/cancel",
            token=user_token,
        )["data"]
        if cancelled.get("status", {}).get("value") != "cancelled":
            raise RepresentativeDataError(
                "Gate A representative mixed order was not cancelled"
            )

        completed_order = client.json_request(
            "create-completable-order",
            "POST",
            "/api/v1/orders",
            token=user_token,
            payload={
                "items": [
                    {
                        "product_id": experience["id"],
                        "experience_option_id": option["id"],
                        "quantity": 1,
                    }
                ],
                "remark": "Gate A representative completed order",
            },
            expected_status=201,
        )["data"]
        client.json_request(
            "mark-order-paid",
            "PATCH",
            f"/api/v1/admin/orders/{completed_order['id']}/paid",
            token=admin_token,
        )
        completed = client.json_request(
            "complete-order",
            "PATCH",
            f"/api/v1/admin/orders/{completed_order['id']}/complete",
            token=admin_token,
        )["data"]
        if completed.get("status", {}).get("value") != "completed":
            raise RepresentativeDataError(
                "Gate A representative order was not completed"
            )

        _logout_and_verify(
            client,
            step_prefix="synthetic-user",
            access_token=synthetic_user["access_token"],
            refresh_token=synthetic_user["refresh_token"],
        )
        synthetic_logged_out = True
        client.json_request(
            "disable-synthetic-user",
            "PUT",
            f"/api/v1/admin/users/{synthetic_user_id}/disable",
            token=admin_token,
        )
        synthetic_disabled = True
        client.json_request(
            "disabled-synthetic-login-rejected",
            "POST",
            "/api/v1/auth/login",
            payload={
                "username": SYNTHETIC_USERNAME,
                "password": synthetic_password,
            },
            expected_status=400,
            expected_code=1005,
        )
        _logout_and_verify(
            client,
            step_prefix="super-admin",
            access_token=super_admin["access_token"],
            refresh_token=super_admin["refresh_token"],
        )
        super_admin_logged_out = True

        result_ids = {
            "user_id": synthetic_user_id,
            "product_ids": [int(experience["id"]), int(kit["id"])],
            "order_ids": [int(mixed_order["id"]), int(completed_order["id"])],
        }
    except BaseException as error:
        operation_error = error
    finally:
        if synthetic_user is not None and not synthetic_logged_out:
            try:
                _logout_and_verify(
                    client,
                    step_prefix="cleanup-synthetic-user",
                    access_token=synthetic_user["access_token"],
                    refresh_token=synthetic_user["refresh_token"],
                )
                synthetic_logged_out = True
            except BaseException:
                cleanup_errors.append("synthetic-session")
        if (
            super_admin is not None
            and synthetic_user_id is not None
            and not synthetic_disabled
        ):
            try:
                client.json_request(
                    "cleanup-disable-synthetic-user",
                    "PUT",
                    f"/api/v1/admin/users/{synthetic_user_id}/disable",
                    token=super_admin["access_token"],
                )
                synthetic_disabled = True
            except BaseException:
                cleanup_errors.append("synthetic-user")
        if super_admin is not None and not super_admin_logged_out:
            try:
                _logout_and_verify(
                    client,
                    step_prefix="cleanup-super-admin",
                    access_token=super_admin["access_token"],
                    refresh_token=super_admin["refresh_token"],
                )
                super_admin_logged_out = True
            except BaseException:
                cleanup_errors.append("super-admin-session")

    synthetic_password = ""
    password = ""
    if cleanup_errors:
        raise RepresentativeDataError(
            "Gate A representative data cleanup failed: "
            + ",".join(cleanup_errors)
        ) from operation_error
    if operation_error is not None:
        if isinstance(operation_error, (KeyboardInterrupt, SystemExit)):
            raise operation_error
        if isinstance(operation_error, RepresentativeDataError):
            raise operation_error
        raise RepresentativeDataError(
            "Gate A representative data operation failed safely"
        ) from operation_error

    after_snapshot = gatea_backup._source_snapshot(
        context.values,
        context.config_file,
        context.secret_dir,
        "loopback",
    )
    _assert_snapshot(after_snapshot, EXPECTED_SNAPSHOT, "post-write")
    if int(after_snapshot.get("audit_logs", 0)) < 21:
        raise RepresentativeDataError(
            "Gate A post-write audit count is below the representative minimum"
        )
    details = _representative_details(context)
    _assert_snapshot(details, EXPECTED_DETAILS, "representative detail")
    image_manifest = gatea_backup._source_image_manifest(
        context.values,
        context.config_file,
        context.secret_dir,
        "loopback",
    )
    if len(image_manifest) != 3:
        raise RepresentativeDataError(
            "Gate A representative image manifest must contain three files"
        )

    record = {
        "schema_version": 1,
        "candidate_sha": context.candidate_sha,
        "image_id": context.image_id,
        "started_at": context.started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "before_snapshot": dict(context.before_snapshot),
        "after_snapshot": after_snapshot,
        "representative_details": details,
        "synthetic_user_id": result_ids["user_id"],
        "product_ids": result_ids["product_ids"],
        "order_ids": result_ids["order_ids"],
        "image_file_count": len(image_manifest),
        "request_count": len(client.results),
        "synthetic_user_disabled": synthetic_disabled,
        "synthetic_session_revoked": synthetic_logged_out,
        "super_admin_session_revoked": super_admin_logged_out,
        "loopback_only": True,
        "pii_recorded": False,
        "secret_values_recorded": False,
        "passed": True,
    }
    gatea_backup._write_json_atomic(
        context.record_dir / RECORD_NAME,
        record,
        0o644,
    )
    return record


def _parser() -> argparse.ArgumentParser:
    parser = SecureArgumentParser(description=__doc__)
    parser.add_argument("--super-admin-username", required=True)
    parser.add_argument("--confirm-super-admin-username", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--config-file", type=Path, default=gatea.DEFAULT_CONFIG_FILE)
    parser.add_argument("--secret-dir", type=Path, default=gatea.DEFAULT_SECRET_DIR)
    parser.add_argument(
        "--release-record-dir",
        type=Path,
        default=gatea.DEFAULT_RECORD_DIR,
    )
    parser.add_argument(
        "--bootstrap-record",
        type=Path,
        default=DEFAULT_BOOTSTRAP_RECORD,
    )
    parser.add_argument("--record-dir", type=Path, default=DEFAULT_RECORD_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if not arguments.apply:
            raise RepresentativeDataError("Gate A representative data requires --apply")
        context = prepare(
            username=arguments.super_admin_username,
            confirm_username=arguments.confirm_super_admin_username,
            config_file=arguments.config_file,
            secret_dir=arguments.secret_dir,
            release_record_dir=arguments.release_record_dir,
            bootstrap_record=arguments.bootstrap_record,
            record_dir=arguments.record_dir,
        )
        if not sys.stdin.isatty():
            raise RepresentativeDataError(
                "Gate A representative data requires an interactive TTY"
            )
        password = getpass.getpass("Current SUPER_ADMIN password: ")
        confirmation = getpass.getpass("Confirm current SUPER_ADMIN password: ")
        _validate_password(password, confirmation)
        execute(
            context,
            username=arguments.super_admin_username,
            password=password,
        )
    except RepresentativeDataError as error:
        print(f"Gate A representative data failed: {error}", file=sys.stderr)
        return 1
    except (gatea.GateAError, OSError) as error:
        print(f"Gate A representative data failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Gate A representative data interrupted", file=sys.stderr)
        return 130
    print("Gate A representative data creation and cleanup passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
