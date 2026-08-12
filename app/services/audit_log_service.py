"""AuditLog Service —— 操作审计日志。

写入方式：顺序 await，同一请求内完成；可加入调用方管理的事务。
"""

import logging

from tortoise.backends.base.client import BaseDBAsyncClient

from app.repositories.audit_log_repo import AuditLogRepository

logger = logging.getLogger(__name__)


class AuditLogService:
    """审计日志服务。"""

    def __init__(self, audit_repo: AuditLogRepository) -> None:
        self.audit_repo = audit_repo

    async def log(
        self,
        operator_id: int,
        action: str,
        target_type: str,
        target_id: int,
        ip_address: str,
        description: str | None = None,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        """写入一条审计日志，并可加入调用方提供的事务连接。"""
        await self.audit_repo.create(
            operator_id=operator_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            description=description,
            using_db=using_db,
        )
        logger.info(
            "Audit: operator=%d action=%s target=%s/%d",
            operator_id, action, target_type, target_id,
        )
