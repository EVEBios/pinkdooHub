"""AuditLog Service —— 操作审计日志。

单条写入顺序 await；同一业务批处理可一次 bulk create。两者都可加入
调用方管理的事务。
"""

import logging

from tortoise.backends.base.client import BaseDBAsyncClient

from app.common.pagination import Page
from app.models.audit_log import AuditLog
from app.repositories.audit_log_repo import (
    AuditLogCreateData,
    AuditLogRepository,
)

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

    async def log_many(
        self,
        entries: list[AuditLogCreateData],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        """批量写入审计事实，供单事务批处理避免逐条数据库往返。"""

        await self.audit_repo.bulk_create(entries, using_db=using_db)
        if entries:
            logger.info(
                "Audit batch: count=%d action=%s",
                len(entries),
                entries[0].action,
            )

    async def list_logs(
        self,
        *,
        target_type: str,
        target_id: int,
        page: int,
        page_size: int,
    ) -> Page[AuditLog]:
        """分页查询指定目标的审计日志。"""

        return await self.audit_repo.list_logs(
            target_type=target_type,
            target_id=target_id,
            page=page,
            page_size=page_size,
        )

    async def count_action(
        self,
        action: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> int:
        """统计动作审计，供受控基础设施用例校验不可变事实。"""

        return await self.audit_repo.count_by_action(
            action,
            using_db=using_db,
        )

    async def count_action_target(
        self,
        *,
        action: str,
        target_type: str,
        target_id: int,
        using_db: BaseDBAsyncClient | None = None,
    ) -> int:
        """统计指定动作与目标的审计。"""

        return await self.audit_repo.count_by_action_target(
            action=action,
            target_type=target_type,
            target_id=target_id,
            using_db=using_db,
        )
