"""AuditLog Repository。"""

from tortoise.backends.base.client import BaseDBAsyncClient

from app.models.audit_log import AuditLog


class AuditLogRepository:
    """审计日志数据访问层。"""

    async def create(
        self,
        operator_id: int,
        action: str,
        target_type: str,
        target_id: int,
        ip_address: str,
        description: str | None = None,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> AuditLog:
        return await AuditLog.create(
            operator_id=operator_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            description=description,
            using_db=using_db,
        )
