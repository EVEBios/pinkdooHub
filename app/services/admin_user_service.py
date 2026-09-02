"""Admin User Service —— 管理员用户管理业务逻辑。"""

import logging

from tortoise.transactions import in_transaction

from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions.user import (
    CannotDisableSelf,
    CannotDisableSuperAdmin,
    UserDeleted,
    UserNotFound,
)
from app.common.pagination import Page, PageParams
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class AdminUserService:
    """管理员用户管理。"""

    def __init__(
        self,
        user_repo: UserRepository,
        audit_log_service: AuditLogService,
    ) -> None:
        self.user_repo = user_repo
        self.audit_log_service = audit_log_service

    async def list_users(
        self,
        params: PageParams,
        status: UserStatus | None = None,
        role: UserRole | None = None,
    ) -> Page[User]:
        """分页获取用户列表，支持按 status/role 筛选。"""
        offset = (params.page - 1) * params.page_size

        items, total = await self.user_repo.list_filtered(
            offset=offset,
            limit=params.page_size,
            status=int(status) if status is not None else None,
            role=int(role) if role is not None else None,
        )
        pages = (total + params.page_size - 1) // params.page_size
        return Page(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )

    async def disable_user(self, admin: User, user_id: int, ip_address: str) -> None:
        """禁用指定用户。

        校验：不能禁自己 → 管理员不能禁超级管理员 → 幂等处理
        校验、状态更新与审计日志统一由当前事务原子提交。
        """
        async with in_transaction() as connection:
            target = await self.user_repo.get_for_update(
                user_id,
                using_db=connection,
            )
            if not target:
                raise UserNotFound()

            if target.id == admin.id:
                raise CannotDisableSelf()

            if (
                target.role == UserRole.SUPER_ADMIN
                and admin.role != UserRole.SUPER_ADMIN
            ):
                raise CannotDisableSuperAdmin()

            if target.status == UserStatus.DISABLED:
                return
            if target.status == UserStatus.DELETED:
                raise UserDeleted()

            await self.user_repo.update(
                target,
                status=int(UserStatus.DISABLED),
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=admin.id,
                action="DISABLE_USER",
                target_type="user",
                target_id=target.id,
                ip_address=ip_address,
                using_db=connection,
            )
        logger.info("User disabled: admin_id=%d target_id=%d", admin.id, target.id)
