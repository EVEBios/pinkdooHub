"""Admin User Service —— 管理员用户管理业务逻辑。"""

import logging

from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions.user import UserNotFound
from app.common.pagination import Page, PageParams
from app.core.exceptions import BusinessException, PermissionException
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserListItem
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class AdminUserService:
    """管理员用户管理。"""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def list_users(
        self,
        params: PageParams,
        status: str | None = None,
        role: str | None = None,
    ) -> Page[UserListItem]:
        """分页获取用户列表，支持按 status/role 筛选。"""
        offset = (params.page - 1) * params.page_size

        # 字符串 → 枚举值
        status_int = self._parse_status(status)
        role_int = self._parse_role(role)

        items, total = await self.user_repo.list_filtered(
            offset=offset,
            limit=params.page_size,
            status=status_int,
            role=role_int,
        )
        pages = (total + params.page_size - 1) // params.page_size
        return Page(
            items=[UserListItem.model_validate(u) for u in items],
            total=total,
            page=params.page,
            page_size=params.page_size,
            pages=pages,
        )

    async def disable_user(self, admin: User, user_id: int, ip_address: str) -> None:
        """禁用指定用户。

        校验：不能禁自己 → 管理员不能禁超级管理员 → 幂等处理
        Phase 4: 校验 + 更新 + 审计日志用 in_transaction() 包裹。
        """
        target = await self.user_repo.get_by_id(user_id)
        if not target:
            raise UserNotFound()

        if target.id == admin.id:
            raise BusinessException(code=422, message="Cannot disable yourself")

        if target.role == UserRole.SUPER_ADMIN and admin.role != UserRole.SUPER_ADMIN:
            raise PermissionException(message="Cannot disable super admin")

        if target.status == UserStatus.DISABLED:
            return  # 幂等：已经禁用，直接返回成功

        await self.user_repo.update(target, status=UserStatus.DISABLED)
        await AuditLogService(AuditLogRepository()).log(
            operator_id=admin.id,
            action="DISABLE_USER",
            target_type="user",
            target_id=target.id,
            ip_address=ip_address,
        )
        logger.info("User disabled: admin_id=%d target_id=%d", admin.id, target.id)

    # ── helper ───────────────────────────────────

    @staticmethod
    def _parse_status(value: str | None) -> int | None:
        if value is None:
            return None
        mapping = {"normal": UserStatus.NORMAL, "disabled": UserStatus.DISABLED}
        return mapping.get(value)

    @staticmethod
    def _parse_role(value: str | None) -> int | None:
        if value is None:
            return None
        mapping = {"user": UserRole.USER, "admin": UserRole.ADMIN, "super_admin": UserRole.SUPER_ADMIN}
        return mapping.get(value)
