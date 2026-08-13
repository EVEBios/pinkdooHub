"""AuditLog Repository。"""

from tortoise.backends.base.client import BaseDBAsyncClient

from app.common.pagination import Page
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

    async def list_logs(
        self,
        *,
        target_type: str,
        target_id: int,
        page: int,
        page_size: int,
    ) -> Page[AuditLog]:
        """按审计目标倒序分页，使用 ID 作为同时间戳的稳定排序键。"""

        query = AuditLog.filter(
            target_type=target_type,
            target_id=target_id,
        )
        total = await query.count()
        items = await (
            query.order_by("-created_at", "-id")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        pages = (total + page_size - 1) // page_size
        return Page[AuditLog](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )
