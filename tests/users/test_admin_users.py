"""管理端用户管理测试 —— 分页列表 + 禁用用户。"""

import pytest
from httpx import AsyncClient

from app.common.enums.user import UserStatus
from app.models.audit_log import AuditLog
from app.services.audit_log_service import AuditLogService


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

    async def test_list_rejects_unknown_filters_and_query_keys(self, client: AsyncClient):
        """未知枚举或额外 Query 不得被静默忽略。"""
        await _register_admin(client, "strictboss", "13800000011")
        token = await _login(client, "strictboss")
        headers = {"Authorization": f"Bearer {token}"}

        for query in ("status=unknown", "role=owner", "keyword=alice"):
            resp = await client.get(f"/api/v1/admin/users?{query}", headers=headers)
            assert resp.status_code == 422

    async def test_list_has_safe_whitelist_and_stable_order(self, client: AsyncClient):
        """列表不输出手机号等敏感字段，并以 ID 作为稳定倒序键。"""
        await _register_admin(client, "orderboss", "13800000012")
        token = await _login(client, "orderboss")
        await client.post(
            "/api/v1/auth/register",
            json={"username": "listedone", "password": "12345678", "nickname": "一", "phone": "13800000013"},
        )
        await client.post(
            "/api/v1/auth/register",
            json={"username": "listedtwo", "password": "12345678", "nickname": "二", "phone": "13800000014"},
        )

        resp = await client.get(
            "/api/v1/admin/users?role=user&page_size=100",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        matching = [item for item in items if item["username"] in {"listedone", "listedtwo"}]
        assert [item["username"] for item in matching] == ["listedtwo", "listedone"]
        assert set(matching[0]) == {
            "id", "username", "nickname", "role", "status", "last_login_at", "created_at",
        }

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

        stored = await UserRepository().get_by_id(user.id)
        assert stored is not None
        assert stored.status == UserStatus.DISABLED
        log = await AuditLog.filter(
            action="DISABLE_USER",
            target_type="user",
            target_id=user.id,
        ).get()
        assert log.operator_id > 0

    async def test_disable_is_idempotent_and_does_not_duplicate_audit(self, client: AsyncClient):
        """重复禁用成功，但仅首次状态变更写一条审计。"""
        await _register_admin(client, "idemadmin", "13800000015")
        token = await _login(client, "idemadmin")
        await client.post(
            "/api/v1/auth/register",
            json={"username": "idemvictim", "password": "12345678", "nickname": "I", "phone": "13800000016"},
        )
        from app.repositories.user_repo import UserRepository
        user = await UserRepository().get_by_username("idemvictim")
        headers = {"Authorization": f"Bearer {token}"}

        first = await client.put(f"/api/v1/admin/users/{user.id}/disable", headers=headers)
        second = await client.put(f"/api/v1/admin/users/{user.id}/disable", headers=headers)
        assert first.status_code == second.status_code == 200
        assert await AuditLog.filter(
            action="DISABLE_USER",
            target_type="user",
            target_id=user.id,
        ).count() == 1

    async def test_disable_cannot_change_terminal_deleted_status(
        self,
        client: AsyncClient,
    ) -> None:
        """注销状态是终态，管理禁用不能把它改回 disabled。"""

        await _register_admin(client, "deletedadmin", "13800000022")
        token = await _login(client, "deletedadmin")
        await client.post(
            "/api/v1/auth/register",
            json={
                "username": "deletedvictim",
                "password": "12345678",
                "nickname": "D",
                "phone": "13800000023",
            },
        )
        from app.repositories.user_repo import UserRepository

        user = await UserRepository().get_by_username("deletedvictim")
        assert user is not None
        user.status = UserStatus.DELETED
        user.password = None
        user.phone = None
        await user.save(update_fields=["status", "password", "phone"])

        response = await client.put(
            f"/api/v1/admin/users/{user.id}/disable",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert (response.status_code, response.json()["code"]) == (400, 1009)
        await user.refresh_from_db()
        assert user.status == UserStatus.DELETED

    async def test_disable_immediately_blocks_existing_access_and_refresh_tokens(
        self,
        client: AsyncClient,
    ):
        """禁用后旧 access 不再鉴权，旧 refresh 也不能签发新 access。"""
        await _register_admin(client, "revoker", "13800000020")
        admin_token = await _login(client, "revoker")
        await client.post(
            "/api/v1/auth/register",
            json={"username": "activevictim", "password": "12345678", "nickname": "A", "phone": "13800000021"},
        )
        victim_login = await client.post(
            "/api/v1/auth/login",
            json={"username": "activevictim", "password": "12345678"},
        )
        victim_tokens = victim_login.json()["data"]
        from app.repositories.user_repo import UserRepository
        victim = await UserRepository().get_by_username("activevictim")

        disabled = await client.put(
            f"/api/v1/admin/users/{victim.id}/disable",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        access = await client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {victim_tokens['access_token']}"},
        )
        refresh = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": victim_tokens["refresh_token"]},
        )
        replay_refresh = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": victim_tokens["refresh_token"]},
        )

        assert disabled.status_code == 200
        assert (access.status_code, access.json()["code"]) == (400, 1005)
        assert (refresh.status_code, refresh.json()["code"]) == (400, 1005)
        assert (replay_refresh.status_code, replay_refresh.json()["code"]) == (400, 1006)

    async def test_disable_rejects_body_and_non_positive_id(self, client: AsyncClient):
        await _register_admin(client, "bodyadmin", "13800000017")
        token = await _login(client, "bodyadmin")
        headers = {"Authorization": f"Bearer {token}"}

        body_resp = await client.put(
            "/api/v1/admin/users/1/disable",
            headers=headers,
            json={"status": "disabled"},
        )
        invalid_id = await client.put("/api/v1/admin/users/0/disable", headers=headers)
        assert body_resp.status_code == 422
        assert invalid_id.status_code == 422

    async def test_audit_failure_rolls_back_disable(
        self,
        client: AsyncClient,
        monkeypatch,
    ):
        """审计写入失败时用户状态不得单独提交。"""
        await _register_admin(client, "rollbackadmin", "13800000018")
        token = await _login(client, "rollbackadmin")
        await client.post(
            "/api/v1/auth/register",
            json={"username": "rollbackvictim", "password": "12345678", "nickname": "R", "phone": "13800000019"},
        )
        from app.repositories.user_repo import UserRepository
        user = await UserRepository().get_by_username("rollbackvictim")

        async def fail_audit(*args, **kwargs):
            raise RuntimeError("injected audit failure")

        monkeypatch.setattr(AuditLogService, "log", fail_audit)
        with pytest.raises(RuntimeError, match="injected audit failure"):
            await client.put(
                f"/api/v1/admin/users/{user.id}/disable",
                headers={"Authorization": f"Bearer {token}"},
            )
        stored = await UserRepository().get_by_id(user.id)
        assert stored is not None
        assert stored.status == UserStatus.NORMAL

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
