"""审计日志测试。"""

from httpx import AsyncClient


class TestAuditLog:
    """验证关键操作产生审计日志。"""

    async def test_audit_log_on_register(self, client: AsyncClient):
        """注册成功后写入审计日志。"""
        from app.repositories.audit_log_repo import AuditLogRepository
        from app.models.audit_log import AuditLog

        await client.post(
            "/api/v1/auth/register",
            json={"username": "test1", "password": "12345678", "nickname": "T1", "phone": "13800000001"},
        )
        logs = await AuditLog.filter(action="REGISTER")
        assert len(logs) == 1
        assert logs[0].action == "REGISTER"
        assert logs[0].target_type == "user"

    async def test_audit_log_on_login(self, client: AsyncClient):
        """登录成功后写入审计日志。"""
        from app.models.audit_log import AuditLog

        await client.post(
            "/api/v1/auth/register",
            json={"username": "test2", "password": "12345678", "nickname": "T2", "phone": "13800000002"},
        )
        await client.post(
            "/api/v1/auth/login",
            json={"username": "test2", "password": "12345678"},
        )
        logs = await AuditLog.filter(action="LOGIN")
        assert len(logs) == 1

    async def test_audit_log_on_disable(self, client: AsyncClient):
        """禁用用户后写入审计日志。"""
        from app.repositories.user_repo import UserRepository
        from app.models.audit_log import AuditLog

        await client.post(
            "/api/v1/auth/register",
            json={"username": "boss1", "password": "12345678", "nickname": "Boss1", "phone": "13800000003"},
        )
        admin = await UserRepository().get_by_username("boss1")
        admin.role = 2
        await admin.save()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "boss1", "password": "12345678"},
        )
        token = resp.json()["data"]["access_token"]

        await client.post(
            "/api/v1/auth/register",
            json={"username": "victim", "password": "12345678", "nickname": "V", "phone": "13800000004"},
        )
        victim = await UserRepository().get_by_username("victim")

        await client.put(
            f"/api/v1/admin/users/{victim.id}/disable",
            headers={"Authorization": f"Bearer {token}"},
        )
        logs = await AuditLog.filter(action="DISABLE_USER")
        assert len(logs) == 1
        log = logs[0]
        assert log.operator_id == admin.id
        assert log.target_id == victim.id

    async def test_no_audit_on_failed_disable(self, client: AsyncClient):
        """禁用自己失败，不产生日志。"""
        from app.repositories.user_repo import UserRepository
        from app.models.audit_log import AuditLog

        await client.post(
            "/api/v1/auth/register",
            json={"username": "boss2", "password": "12345678", "nickname": "Boss2", "phone": "13800000005"},
        )
        admin = await UserRepository().get_by_username("boss2")
        admin.role = 2
        await admin.save()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "boss2", "password": "12345678"},
        )
        token = resp.json()["data"]["access_token"]

        # self-disable → 422, no audit log
        await client.put(
            f"/api/v1/admin/users/{admin.id}/disable",
            headers={"Authorization": f"Bearer {token}"},
        )
        logs = await AuditLog.filter(action="DISABLE_USER", operator_id=admin.id)
        assert len(logs) == 0
