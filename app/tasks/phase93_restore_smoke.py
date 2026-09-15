"""在独立 Restore App 容器内验证 readiness 与已轮换管理员登录。"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import urllib.error
import urllib.request


ROTATED_PASSWORD_PATH = Path("/run/secrets/bootstrap_rotated_password")


class RestoreSmokeError(RuntimeError):
    """不包含凭据、Token 或响应正文的恢复 Smoke 错误。"""


def _json_request(
    path: str,
    *,
    payload: dict[str, str] | None = None,
) -> tuple[int, dict]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:8000{path}",
        data=body,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def run() -> None:
    if not ROTATED_PASSWORD_PATH.is_file():
        raise RestoreSmokeError("rotated credential Secret is unavailable")
    password = ROTATED_PASSWORD_PATH.read_text(encoding="utf-8").strip()
    if not password:
        raise RestoreSmokeError("rotated credential Secret is empty")

    ready_status, ready = _json_request("/api/v1/health/ready")
    if (
        ready_status != 200
        or ready.get("code") != 0
        or ready.get("data", {}).get("checks")
        != {"database": "up", "redis": "up"}
    ):
        raise RestoreSmokeError("restored application is not ready")
    login_status, login = _json_request(
        "/api/v1/auth/login",
        payload={"username": "phase93_owner", "password": password},
    )
    if (
        login_status != 200
        or login.get("code") != 0
        or login.get("data", {}).get("user", {}).get("role") != "super_admin"
    ):
        raise RestoreSmokeError("restored SUPER_ADMIN login failed")


def main() -> int:
    try:
        run()
    except RestoreSmokeError as error:
        print(f"Phase 9.3 restore smoke refused: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(
            f"Phase 9.3 restore smoke failed safely: {type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    print("Phase 9.3 restore app readiness and login passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
