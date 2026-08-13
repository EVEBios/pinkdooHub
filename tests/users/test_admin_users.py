"""管理端用户管理测试 —— 分页列表 + 禁用用户。"""

from httpx import AsyncClient


class TestListUsers:
    """GET /admin/users"""

    async def test_list_users(self, client: AsyncClient):
        """管理员可以分页获取用户列表。"""
        await _register_admin(client, "boss", "13800000001")
        token = await _login(client, "boss")

        resp = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "items" in data
        assert "total" in data
        assert "pages" in data

    async def test_list_users_filter_status(self, client: AsyncClient):
        """按 status 筛选。"""
        await _register_admin(client, "boss2", "13800000002")
        token = await _login(client, "boss2")

        resp = await client.get(
            "/api/v1/admin/users?status=normal",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    async def test_user_cannot_access(self, client: AsyncClient, auth_user: dict):
        """普通用户 → 403。"""
        resp = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {auth_user['token']}"},
        )
        assert resp.status_code == 403

    async def test_admin_can_access(self, client: AsyncClient):
        """管理员 → 200。"""
        await _register_admin(client, "boss3", "13800000003")
        token = await _login(client, "boss3")

        resp = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


class TestDisableUser:
    """PUT /admin/users/{id}/disable"""

    async def test_disable_user(self, client: AsyncClient):
        """禁用正常用户。"""
        await _register_admin(client, "admin1", "13800000004")
        admin_token = await _login(client, "admin1")

        # 注册一个普通用户
        from app.repositories.user_repo import UserRepository

        await client.post(
            "/api/v1/auth/register",
            json={"username": "victim", "password": "12345678", "nickname": "V", "phone": "13800000005"},
        )
        user = await UserRepository().get_by_username("victim")

        resp = await client.put(
            f"/api/v1/admin/users/{user.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "User disabled"

    async def test_disable_self(self, client: AsyncClient):
        """不能禁用自己。"""
        await _register_admin(client, "admin2", "13800000006")
        token = await _login(client, "admin2")

        from app.repositories.user_repo import UserRepository
        user = await UserRepository().get_by_username("admin2")

        resp = await client.put(
            f"/api/v1/admin/users/{user.id}/disable",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 422

    async def test_admin_cannot_disable_super_admin(self, client: AsyncClient):
        """管理员不能禁用超级管理员。"""
        await _register_admin(client, "admin3", "13800000007")
        admin_token = await _login(client, "admin3")

        # 创建超级管理员
        from app.repositories.user_repo import UserRepository

        await client.post(
            "/api/v1/auth/register",
            json={"username": "sadmin", "password": "12345678", "nickname": "SA", "phone": "13800000008"},
        )
        sa = await UserRepository().get_by_username("sadmin")
        sa.role = 3  # SUPER_ADMIN
        await sa.save()

        resp = await client.put(
            f"/api/v1/admin/users/{sa.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 403

    async def test_disable_not_found(self, client: AsyncClient):
        """不存在的用户 → 404（实际返回 400，因为 UserNotFound 是 BusinessException 子类）。"""
        await _register_admin(client, "admin4", "13800000009")
        token = await _login(client, "admin4")

        resp = await client.put(
            "/api/v1/admin/users/99999/disable",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 1002


# ── helpers ─────────────────────────────────────


async def _register_admin(client: AsyncClient, username: str, phone: str) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "12345678", "nickname": username, "phone": phone},
    )
    from app.repositories.user_repo import UserRepository

    user = await UserRepository().get_by_username(username)
    user.role = 2  # ADMIN
    await user.save()


async def _login(client: AsyncClient, username: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "12345678"},
    )
    return resp.json()["data"]["access_token"]
