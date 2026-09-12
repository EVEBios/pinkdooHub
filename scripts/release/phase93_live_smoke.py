#!/usr/bin/env python3
"""通过真实 Phase 9.3 HTTPS 入口执行服务端纵向 Smoke。"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import secrets
import ssl
import sys
from typing import Mapping
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.phase93_operations import Phase93Operations
from scripts.release.phase93_rehearsal import (
    HTTPS_HOST,
    PORTS,
    RehearsalError,
    config_for_run,
)


PNG_CONTENT = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/w8AAusB9Y9Z4xkAAAAASUVORK5CYII="
)


class SmokeError(RuntimeError):
    """只包含步骤、HTTP 状态和业务码的安全 Smoke 错误。"""

    def __init__(self, step: str, status: int, code: object = None) -> None:
        super().__init__(f"{step} failed: status={status} code={code}")


class HttpsSmokeClient:
    """直接连回环地址，同时使用冻结 Host Header 和短期 CA。"""

    def __init__(self, ca_path: Path) -> None:
        self.context = ssl.create_default_context(cafile=str(ca_path))
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
        request_headers = {"Host": HTTPS_HOST, "Accept": "application/json"}
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        if content_type:
            request_headers["Content-Type"] = content_type
        if body is not None:
            request_headers["Content-Length"] = str(len(body))
        if headers:
            request_headers.update(headers)

        connection = http.client.HTTPSConnection(
            "127.0.0.1",
            PORTS["https"],
            timeout=10,
            context=self.context,
        )
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            content = response.read()
            response_headers = dict(response.getheaders())
        finally:
            connection.close()

        code: object = None
        if response_headers.get("Content-Type", "").startswith("application/json"):
            try:
                code = json.loads(content).get("code")
            except (UnicodeDecodeError, json.JSONDecodeError):
                code = "invalid-json"
        self.results.append(
            {
                "step": step,
                "method": method,
                "path": path,
                "status": response.status,
                "code": code,
                "passed": response.status == expected_status,
            }
        )
        if response.status != expected_status:
            raise SmokeError(step, response.status, code)
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
    ) -> dict:
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
        document = json.loads(content)
        if document.get("code") != expected_code:
            raise SmokeError(step, expected_status, document.get("code"))
        return document


def multipart_image(fields: Mapping[str, str]) -> tuple[bytes, str]:
    """构造固定 PNG multipart；不接受外部文件路径。"""

    boundary = f"phase93-{secrets.token_hex(12)}"
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
            b'filename="phase93.png"\r\n',
            b"Content-Type: image/png\r\n\r\n",
            PNG_CONTENT,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        )
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _login(client: HttpsSmokeClient, username: str, password: str) -> dict:
    response = client.json_request(
        f"login-{username}",
        "POST",
        "/api/v1/auth/login",
        payload={"username": username, "password": password},
    )
    return response["data"]


def _upload_image(
    client: HttpsSmokeClient,
    *,
    step: str,
    path: str,
    token: str,
    fields: Mapping[str, str],
) -> dict:
    body, content_type = multipart_image(fields)
    content, _ = client.request(
        step,
        "POST",
        path,
        token=token,
        body=body,
        content_type=content_type,
        expected_status=201,
    )
    document = json.loads(content)
    if document.get("code") != 0:
        raise SmokeError(step, 201, document.get("code"))
    return document["data"]


def run(run_id: str) -> dict[str, object]:
    config = config_for_run(run_id)
    Phase93Operations(config).validate_workspace()
    password = (config.secret_dir / "bootstrap_password").read_text(
        encoding="utf-8"
    ).strip()
    client = HttpsSmokeClient(config.cert_dir / "ca.crt")

    client.json_request(
        "liveness",
        "GET",
        "/api/v1/health/live",
    )
    ready = client.json_request(
        "readiness",
        "GET",
        "/api/v1/health/ready",
    )
    if ready["data"]["checks"] != {"database": "up", "redis": "up"}:
        raise SmokeError("readiness-checks", 200, ready.get("code"))

    owner = _login(client, "phase93_owner", password)
    admin = _login(client, "phase93_admin", password)
    user = _login(client, "phase93_user", password)
    client.json_request(
        "disabled-login",
        "POST",
        "/api/v1/auth/login",
        payload={"username": "phase93_disabled", "password": password},
        expected_status=400,
        expected_code=1005,
    )
    if owner["user"]["role"] != "super_admin":
        raise SmokeError("owner-role", 200, 0)
    if admin["user"]["role"] != "admin" or user["user"]["role"] != "user":
        raise SmokeError("runtime-roles", 200, 0)

    client.json_request(
        "user-admin-boundary",
        "GET",
        "/api/v1/admin/users",
        token=user["access_token"],
        expected_status=403,
        expected_code=403,
    )
    users = client.json_request(
        "owner-user-list",
        "GET",
        "/api/v1/admin/users?page_size=100",
        token=owner["access_token"],
    )
    if users["data"]["total"] != 4:
        raise SmokeError("owner-user-list-count", 200, 0)

    experience = client.json_request(
        "create-experience",
        "POST",
        "/api/v1/admin/products/experience",
        token=admin["access_token"],
        payload={
            "name": "[PHASE93] HTTPS Experience",
            "description": "Synthetic live rehearsal",
        },
        expected_status=201,
    )["data"]
    option = client.json_request(
        "create-option",
        "POST",
        f"/api/v1/admin/products/experience/{experience['id']}/options",
        token=admin["access_token"],
        payload={
            "duration_minutes": 60,
            "participants": 2,
            "day_type": "weekday",
            "price": "88.00",
        },
        expected_status=201,
    )["data"]
    experience_image = _upload_image(
        client,
        step="upload-experience-cover",
        path=f"/api/v1/admin/products/{experience['id']}/images",
        token=admin["access_token"],
        fields={"is_cover": "true", "sort": "0"},
    )
    _upload_image(
        client,
        step="upload-option-image",
        path=f"/api/v1/admin/options/{option['id']}/images",
        token=admin["access_token"],
        fields={"sort": "0"},
    )
    client.json_request(
        "online-experience",
        "PATCH",
        f"/api/v1/admin/products/{experience['id']}/online",
        token=admin["access_token"],
    )

    kit = client.json_request(
        "create-kit",
        "POST",
        "/api/v1/admin/products/kit",
        token=admin["access_token"],
        payload={
            "name": "[PHASE93] HTTPS Kit",
            "description": "Synthetic inventory rehearsal",
            "price": "36.00",
        },
        expected_status=201,
    )["data"]
    kit_image = _upload_image(
        client,
        step="upload-kit-cover",
        path=f"/api/v1/admin/products/{kit['id']}/images",
        token=admin["access_token"],
        fields={"is_cover": "true", "sort": "0"},
    )
    adjustment_path = (
        f"/api/v1/admin/products/kit/{kit['id']}/inventory-adjustments"
    )
    idempotency_headers = {"Idempotency-Key": "phase93-live-kit-opening"}
    adjustment_payload = {
        "change": 10,
        "reason": "Phase 9.3 live rehearsal stock",
    }
    adjusted = client.json_request(
        "adjust-kit-stock",
        "POST",
        adjustment_path,
        token=admin["access_token"],
        payload=adjustment_payload,
        headers=idempotency_headers,
        expected_status=201,
    )
    replayed = client.json_request(
        "replay-kit-adjustment",
        "POST",
        adjustment_path,
        token=admin["access_token"],
        payload=adjustment_payload,
        headers=idempotency_headers,
    )
    if adjusted["data"]["stock"] != 10 or replayed["data"]["stock"] != 10:
        raise SmokeError("adjustment-replay", 200, 0)
    client.json_request(
        "online-kit",
        "PATCH",
        f"/api/v1/admin/products/{kit['id']}/online",
        token=admin["access_token"],
    )

    for name, image in (
        ("experience-image-read", experience_image),
        ("kit-image-read", kit_image),
    ):
        parsed = urlparse(image["image_url"])
        if (
            parsed.scheme != "https"
            or parsed.hostname != HTTPS_HOST
            or parsed.port != PORTS["https"]
        ):
            raise SmokeError(f"{name}-url", 200, 0)
        content, headers = client.request(name, "GET", parsed.path)
        if content != PNG_CONTENT or not headers.get("Content-Type", "").startswith(
            "image/png"
        ):
            raise SmokeError(name, 200, 0)

    mixed_order = client.json_request(
        "create-mixed-order",
        "POST",
        "/api/v1/orders",
        token=user["access_token"],
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
                    "quantity": 2,
                },
            ],
            "remark": "Phase 9.3 mixed order",
        },
        expected_status=201,
    )["data"]
    cancelled = client.json_request(
        "cancel-mixed-order",
        "PATCH",
        f"/api/v1/orders/{mixed_order['id']}/cancel",
        token=user["access_token"],
    )
    if cancelled["data"]["status"]["value"] != "cancelled":
        raise SmokeError("cancel-mixed-order-status", 200, 0)

    paid_order = client.json_request(
        "create-payable-order",
        "POST",
        "/api/v1/orders",
        token=user["access_token"],
        payload={
            "items": [
                {
                    "product_id": experience["id"],
                    "experience_option_id": option["id"],
                    "quantity": 1,
                }
            ]
        },
        expected_status=201,
    )["data"]
    client.json_request(
        "admin-mark-paid",
        "PATCH",
        f"/api/v1/admin/orders/{paid_order['id']}/paid",
        token=admin["access_token"],
    )
    completed = client.json_request(
        "admin-complete-order",
        "PATCH",
        f"/api/v1/admin/orders/{paid_order['id']}/complete",
        token=admin["access_token"],
    )
    if completed["data"]["status"]["value"] != "completed":
        raise SmokeError("admin-complete-order-status", 200, 0)

    client.json_request(
        "refresh-user-token",
        "POST",
        "/api/v1/auth/refresh",
        payload={"refresh_token": user["refresh_token"]},
    )
    client.json_request(
        "disable-user",
        "PUT",
        f"/api/v1/admin/users/{user['user']['id']}/disable",
        token=owner["access_token"],
    )
    client.json_request(
        "disabled-old-access",
        "GET",
        "/api/v1/users/me",
        token=user["access_token"],
        expected_status=400,
        expected_code=1005,
    )
    client.json_request(
        "disabled-old-refresh",
        "POST",
        "/api/v1/auth/refresh",
        payload={"refresh_token": user["refresh_token"]},
        expected_status=400,
        expected_code=1005,
    )

    rotated_password = (
        config.secret_dir / "bootstrap_rotated_password"
    ).read_text(encoding="utf-8").strip()
    client.json_request(
        "rotate-owner-password",
        "PUT",
        "/api/v1/users/me/password",
        token=owner["access_token"],
        payload={"old_password": password, "new_password": rotated_password},
    )
    rotated_login = _login(client, "phase93_owner", rotated_password)
    if rotated_login["user"]["role"] != "super_admin":
        raise SmokeError("rotated-owner-login", 200, 0)
    client.json_request(
        "old-owner-password-rejected",
        "POST",
        "/api/v1/auth/login",
        payload={"username": "phase93_owner", "password": password},
        expected_status=400,
        expected_code=1003,
    )

    return {
        "schema_version": 1,
        "scenario": "DR-06/DR-07/DR-09",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "https_host": HTTPS_HOST,
        "request_count": len(client.results),
        "results": client.results,
        "product_ids": [experience["id"], kit["id"]],
        "order_ids": [mixed_order["id"], paid_order["id"]],
        "bootstrap_credential_rotated": True,
        "secret_values_recorded": False,
        "passed": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    try:
        config = config_for_run(arguments.run_id)
        report = run(arguments.run_id)
        report_path = config.evidence_dir / "dr06-dr07-dr09-live-smoke.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(
            "Phase 9.3 live HTTPS smoke passed: "
            f"requests={report['request_count']} credential_rotated=true"
        )
        return 0
    except (RehearsalError, SmokeError) as error:
        print(f"Phase 9.3 live HTTPS smoke refused: {error}", file=sys.stderr)
    except Exception as error:
        print(
            f"Phase 9.3 live HTTPS smoke failed safely: {type(error).__name__}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
