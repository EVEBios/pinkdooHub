"""pytest 共享 fixtures。"""

import os
import tempfile
import uuid

os.environ["TESTING"] = "1"

# ── 用 fakeredis 替代真实 Redis ──────────────────
import fakeredis.aioredis

import app.core.redis as _redis_module

_test_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

_redis_module._redis = _test_redis
_redis_module.init_redis = lambda: None  # no-op, already initialized
_redis_module.close_redis = lambda: None  # no-op, skip cleanup

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise


@pytest_asyncio.fixture(autouse=True)
async def setup_db() -> None:
    """每个测试使用独立的临时数据库文件。"""
    db_path = os.path.join(tempfile.gettempdir(), f"test_{uuid.uuid4().hex}.sqlite3")
    os.environ["DB_SQLITE_PATH"] = db_path

    config = {
        "connections": {"default": f"sqlite://{db_path}"},
        "apps": {
            "models": {
                "models": ["app.models", "aerich.models"],
                "default_connection": "default",
            },
        },
    }
    await Tortoise.init(config=config)
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()
    try:
        os.unlink(db_path)
        os.unlink(db_path + "-shm")
        os.unlink(db_path + "-wal")
    except FileNotFoundError:
        pass


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """HTTP 测试客户端。"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_user(client: AsyncClient) -> dict:
    """注册并登录，返回 user 和 access_token。"""
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice",
            "password": "12345678",
            "nickname": "Alice",
            "phone": "13800138000",
        },
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": "12345678"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return {"user": data["user"], "token": data["access_token"]}
