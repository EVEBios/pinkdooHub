"""用户模块测试 —— 个人信息 + 修改密码。"""

from httpx import AsyncClient


class TestGetMe:
    """GET /users/me"""

    async def test_get_me(self, client: AsyncClient, auth_user: dict):
        token = auth_user["token"]
        resp = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["username"] == "alice"
        assert body["data"]["role"] == "user"

    async def test_no_token(self, client: AsyncClient):
        resp = await client.get("/api/v1/users/me")
        assert resp.status_code == 403 or resp.status_code == 401

    async def test_invalid_token(self, client: AsyncClient):
        resp = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer xxxxx.yyyyy.zzzzz"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 1006


class TestChangePassword:
    """PUT /users/me/password"""

    async def test_change_password_success(self, client: AsyncClient, auth_user: dict):
        token = auth_user["token"]
        resp = await client.put(
            "/api/v1/users/me/password",
            json={"old_password": "12345678", "new_password": "newpass90"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        assert resp.json()["message"] == "Password changed"

    async def test_wrong_old_password(self, client: AsyncClient, auth_user: dict):
        token = auth_user["token"]
        resp = await client.put(
            "/api/v1/users/me/password",
            json={"old_password": "wrong", "new_password": "newpass90"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 1004

    async def test_login_with_new_password(self, client: AsyncClient, auth_user: dict):
        """修改密码后，新密码可以登录。"""
        token = auth_user["token"]
        await client.put(
            "/api/v1/users/me/password",
            json={"old_password": "12345678", "new_password": "newpass90"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "newpass90"},
        )
        assert resp.status_code == 200

    async def test_login_with_old_password_after_change(
        self, client: AsyncClient, auth_user: dict
    ):
        """修改密码后，旧密码被拒绝。"""
        token = auth_user["token"]
        await client.put(
            "/api/v1/users/me/password",
            json={"old_password": "12345678", "new_password": "newpass90"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "12345678"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 1003

    async def test_last_login_at_updated(self, client: AsyncClient):
        """登录后 last_login_at 被设置。"""
        await client.post(
            "/api/v1/auth/register",
            json={"username": "time", "password": "12345678", "nickname": "Time"},
        )

        from app.repositories.user_repo import UserRepository

        user = await UserRepository().get_by_username("time")
        assert user.last_login_at is None

        await client.post(
            "/api/v1/auth/login",
            json={"username": "time", "password": "12345678"},
        )
        user = await UserRepository().get_by_username("time")
        assert user.last_login_at is not None
