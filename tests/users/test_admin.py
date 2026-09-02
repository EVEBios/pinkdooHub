"""管理端测试 —— RBAC 权限验证。"""

from httpx import AsyncClient


class TestAdminAccess:
    """GET /admin/users — requires ADMIN+"""

    async def test_admin_list_as_user(self, client: AsyncClient, auth_user: dict):
        """普通用户 → 403。"""
        token = auth_user["token"]
        resp = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_admin_list_as_admin(self, client: AsyncClient):
        """管理员 → 200。"""
        from app.repositories.user_repo import UserRepository

        # 注册管理员
        await client.post(
            "/api/v1/auth/register",
            json={"username": "boss", "password": "12345678", "nickname": "Boss", "phone": "13800000002"},
        )
        user = await UserRepository().get_by_username("boss")
        user.role = 2  # ADMIN
        await user.save()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "boss", "password": "12345678"},
        )
        token = resp.json()["data"]["access_token"]

        resp = await client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "items" in resp.json()["data"]

    async def test_super_admin_endpoint_as_admin(self, client: AsyncClient):
        """管理员访问超级管理员接口 → 403。"""
        from app.repositories.user_repo import UserRepository

        await client.post(
            "/api/v1/auth/register",
            json={"username": "boss2", "password": "12345678", "nickname": "Boss2", "phone": "13800000003"},
        )
        user = await UserRepository().get_by_username("boss2")
        user.role = 2  # ADMIN only, not SUPER_ADMIN
        await user.save()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "boss2", "password": "12345678"},
        )
        token = resp.json()["data"]["access_token"]

        resp = await client.get(
            "/api/v1/admin/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_admin_access_no_token(self, client: AsyncClient):
        """无 token → 401（HTTPBearer 拦截）。"""
        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 401
