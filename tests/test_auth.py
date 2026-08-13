"""认证模块测试 —— 注册 + 登录。"""

import pytest
from httpx import AsyncClient


class TestRegister:
    """POST /auth/register"""

    async def test_register_success(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "bob",
                "password": "12345678",
                "nickname": "Bob",
                "phone": "13900139000",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["username"] == "bob"
        assert body["data"]["nickname"] == "Bob"
        assert body["data"]["role"] == "user"
        assert body["data"]["status"] == "normal"
        assert "password" not in body["data"]
        assert body["data"]["last_login_at"] is None

    async def test_duplicate_username(self, client: AsyncClient):
        await client.post(
            "/api/v1/auth/register",
            json={"username": "dup", "password": "12345678", "nickname": "First", "phone": "13800000000"},
        )
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "dup", "password": "87654321", "nickname": "Second", "phone": "13800000000"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 1001
        assert "Username already exists" in body["message"]

    async def test_duplicate_phone(self, client: AsyncClient):
        await client.post(
            "/api/v1/auth/register",
            json={
                "username": "user1",
                "password": "12345678",
                "nickname": "U1",
                "phone": "13800000001",
            },
        )
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "user2",
                "password": "12345678",
                "nickname": "U2",
                "phone": "13800000001",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 1007

    async def test_short_password(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "bob", "password": "123", "nickname": "Bob", "phone": "13900139000"},
        )
        assert resp.status_code == 422

    async def test_invalid_phone(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "bob",
                "password": "12345678",
                "nickname": "Bob",
                "phone": "00000000000",
            },
        )
        assert resp.status_code == 422

    async def test_password_is_hashed(self, client: AsyncClient):
        """注册后 DB 中存储 bcrypt 哈希，非明文。"""
        from app.repositories.user_repo import UserRepository

        await client.post(
            "/api/v1/auth/register",
            json={"username": "hash", "password": "12345678", "nickname": "Hash", "phone": "13700000000"},
        )
        user = await UserRepository().get_by_username("hash")
        assert user is not None
        assert user.password != "12345678"
        assert user.password.startswith("$2b$")


class TestLogin:
    """POST /auth/login"""

    async def test_login_success(self, client: AsyncClient):
        await client.post(
            "/api/v1/auth/register",
            json={"username": "alice", "password": "12345678", "nickname": "Alice", "phone": "13800138000"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "12345678"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["access_token"]) > 50
        assert body["data"]["token_type"] == "Bearer"
        assert body["data"]["user"]["username"] == "alice"

    async def test_wrong_password(self, client: AsyncClient):
        await client.post(
            "/api/v1/auth/register",
            json={"username": "alice", "password": "12345678", "nickname": "Alice", "phone": "13800138000"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "wrongpass"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 1003

    async def test_user_not_found(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": "12345678"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 1002

    async def test_disabled_user(self, client: AsyncClient):
        """禁用用户登录返回 1005。"""
        from app.repositories.user_repo import UserRepository

        # 注册并手动设为禁用
        await client.post(
            "/api/v1/auth/register",
            json={"username": "bad", "password": "12345678", "nickname": "Bad", "phone": "13600000000"},
        )
        user = await UserRepository().get_by_username("bad")
        user.status = 2  # DISABLED
        await user.save()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "bad", "password": "12345678"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 1005
