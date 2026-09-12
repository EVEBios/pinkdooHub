"""Liveness 与 Readiness HTTP 契约。"""

from typing import Any

import pytest
from httpx import AsyncClient

from app.api.v1 import router as router_module
from app.core.health import ReadinessResult
from app.main import app


async def test_legacy_health_remains_a_dependency_free_compatibility_route(
    client: AsyncClient,
    monkeypatch,
) -> None:
    """旧入口保持原响应，且不会误触发依赖探测。"""

    async def unexpected_check() -> ReadinessResult:
        raise AssertionError("legacy health must not check dependencies")

    monkeypatch.setattr(router_module, "check_readiness", unexpected_check)

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {
            "app": "pinkdooHub",
            "env": "development",
            "status": "ok",
        },
    }


async def test_liveness_does_not_touch_dependencies(
    client: AsyncClient,
    monkeypatch,
) -> None:
    """外部依赖故障不能让进程存活探针失败。"""

    async def unexpected_check() -> ReadinessResult:
        raise AssertionError("liveness must not check dependencies")

    monkeypatch.setattr(router_module, "check_readiness", unexpected_check)

    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {"app": "pinkdooHub", "status": "alive"},
    }


async def test_readiness_returns_200_when_all_dependencies_are_up(
    client: AsyncClient,
    monkeypatch,
) -> None:
    """只有数据库和 Redis 同时可用时才返回 Ready。"""

    async def all_ready() -> ReadinessResult:
        return ReadinessResult(database=True, redis=True)

    monkeypatch.setattr(router_module, "check_readiness", all_ready)

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "success",
        "data": {
            "status": "ready",
            "checks": {"database": "up", "redis": "up"},
        },
    }


@pytest.mark.parametrize(
    ("database", "redis", "expected_checks"),
    [
        (False, True, {"database": "down", "redis": "up"}),
        (True, False, {"database": "up", "redis": "down"}),
        (False, False, {"database": "down", "redis": "down"}),
    ],
)
async def test_readiness_returns_safe_503_for_dependency_failure(
    client: AsyncClient,
    monkeypatch,
    database: bool,
    redis: bool,
    expected_checks: dict[str, str],
) -> None:
    """503 只公开依赖类别和 Up/Down，不公开连接目标或驱动错误。"""

    async def not_ready() -> ReadinessResult:
        return ReadinessResult(database=database, redis=redis)

    monkeypatch.setattr(router_module, "check_readiness", not_ready)

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": 503,
        "message": "Service unavailable",
        "data": {"status": "not_ready", "checks": expected_checks},
    }
    assert "password" not in response.text.lower()
    assert "redis://" not in response.text.lower()
    assert "mysql://" not in response.text.lower()


def _response_schema(path: str, status_code: int) -> dict[str, Any]:
    return app.openapi()["paths"][path]["get"]["responses"][str(status_code)][
        "content"
    ]["application/json"]["schema"]


def test_health_openapi_declares_typed_success_and_503_responses() -> None:
    """OpenAPI 必须让部署探针和客户端看到精确状态契约。"""

    assert _response_schema("/api/v1/health", 200)["$ref"].endswith(
        "/SuccessResponse_LegacyHealthOut_"
    )
    assert _response_schema("/api/v1/health/live", 200)["$ref"].endswith(
        "/SuccessResponse_LivenessOut_"
    )
    assert _response_schema("/api/v1/health/ready", 200)["$ref"].endswith(
        "/SuccessResponse_ReadinessOut_"
    )
    assert _response_schema("/api/v1/health/ready", 503)["$ref"].endswith(
        "/ReadinessErrorResponse"
    )
