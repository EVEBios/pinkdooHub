"""首个 SUPER_ADMIN 的一次性初始化用例。"""

import asyncio
import logging
from dataclasses import dataclass

from tortoise.backends.base.client import TransactionalDBClient
from tortoise.transactions import in_transaction

from app.common.constants.bootstrap import (
    SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION,
    SUPER_ADMIN_BOOTSTRAP_LOCK_TIMEOUT_SECONDS,
    SUPER_ADMIN_BOOTSTRAP_SYSTEM_IP,
)
from app.common.enums.user import UserRole, UserStatus
from app.core.security import hash_password, verify_password
from app.repositories.bootstrap_lock_repo import BootstrapLockRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class SuperAdminBootstrapError(RuntimeError):
    """受控初始化可安全展示的操作错误。"""


class SuperAdminBootstrapConflict(SuperAdminBootstrapError):
    """数据库已有状态与一次性初始化契约冲突。"""


class SuperAdminBootstrapLockUnavailable(SuperAdminBootstrapError):
    """无法在限定时间内取得初始化互斥锁。"""


@dataclass(frozen=True, slots=True)
class SuperAdminBootstrapResult:
    """初始化结果；重放不会改变已有用户。"""

    user_id: int
    created: bool

    @property
    def is_replay(self) -> bool:
        return not self.created


class SuperAdminBootstrapService:
    """原子创建且只创建首个 SUPER_ADMIN。"""

    def __init__(
        self,
        user_repo: UserRepository,
        audit_log_service: AuditLogService,
        lock_repo: BootstrapLockRepository,
    ) -> None:
        self.user_repo = user_repo
        self.audit_log_service = audit_log_service
        self.lock_repo = lock_repo

    async def bootstrap(
        self,
        *,
        username: str,
        password: str,
        nickname: str,
        phone: str,
    ) -> SuperAdminBootstrapResult:
        """创建首个 SUPER_ADMIN，或严格识别同一初始化的安全重放。"""

        process_lock_acquired = await self.lock_repo.acquire_process_lock(
            SUPER_ADMIN_BOOTSTRAP_LOCK_TIMEOUT_SECONDS
        )
        if not process_lock_acquired:
            raise SuperAdminBootstrapLockUnavailable(
                "SUPER_ADMIN bootstrap is already running"
            )

        try:
            async with in_transaction() as connection:
                database_lock_acquired = await self.lock_repo.acquire_database_lock(
                    using_db=connection,
                    timeout_seconds=SUPER_ADMIN_BOOTSTRAP_LOCK_TIMEOUT_SECONDS,
                )
                if not database_lock_acquired:
                    raise SuperAdminBootstrapLockUnavailable(
                        "SUPER_ADMIN bootstrap database lock timed out"
                    )

                try:
                    result = await self._bootstrap_locked(
                        username=username,
                        password=password,
                        nickname=nickname,
                        phone=phone,
                        using_db=connection,
                    )
                    # MySQL GET_LOCK 是 session lock，不随事务提交自动释放。
                    # 必须先提交用户与审计，再释放锁，避免另一进程在提交窗口内
                    # 读到旧状态并创建第二个 SUPER_ADMIN。
                    await connection.commit()
                finally:
                    await asyncio.shield(
                        self.lock_repo.release_database_lock(using_db=connection)
                    )
        finally:
            self.lock_repo.release_process_lock()

        logger.info(
            "SUPER_ADMIN bootstrap complete: user_id=%d created=%s",
            result.user_id,
            result.created,
        )
        return result

    async def _bootstrap_locked(
        self,
        *,
        username: str,
        password: str,
        nickname: str,
        phone: str,
        using_db: TransactionalDBClient,
    ) -> SuperAdminBootstrapResult:
        super_admins = await self.user_repo.list_by_role_for_update(
            int(UserRole.SUPER_ADMIN),
            using_db=using_db,
        )
        bootstrap_audit_count = await self.audit_log_service.count_action(
            SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION,
            using_db=using_db,
        )

        if super_admins:
            if len(super_admins) != 1:
                raise SuperAdminBootstrapConflict(
                    "Multiple SUPER_ADMIN users already exist"
                )
            existing = super_admins[0]
            target_audit_count = await self.audit_log_service.count_action_target(
                action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION,
                target_type="user",
                target_id=existing.id,
                using_db=using_db,
            )
            password_matches = self._password_matches(password, existing.password)
            if (
                bootstrap_audit_count == 1
                and target_audit_count == 1
                and existing.username == username
                and existing.nickname == nickname
                and existing.phone == phone
                and existing.status == UserStatus.NORMAL
                and password_matches
            ):
                return SuperAdminBootstrapResult(
                    user_id=existing.id,
                    created=False,
                )
            raise SuperAdminBootstrapConflict(
                "An existing SUPER_ADMIN does not match the bootstrap identity"
            )

        if bootstrap_audit_count:
            raise SuperAdminBootstrapConflict(
                "Bootstrap audit exists without a matching SUPER_ADMIN"
            )

        username_owner = await self.user_repo.get_by_username(
            username,
            using_db=using_db,
        )
        phone_owner = await self.user_repo.get_by_phone(
            phone,
            using_db=using_db,
        )
        if username_owner is not None or phone_owner is not None:
            raise SuperAdminBootstrapConflict(
                "Bootstrap username or phone is already in use"
            )

        user = await self.user_repo.create(
            username=username,
            password=hash_password(password),
            nickname=nickname,
            phone=phone,
            role=int(UserRole.SUPER_ADMIN),
            status=int(UserStatus.NORMAL),
            using_db=using_db,
        )
        await self.audit_log_service.log(
            operator_id=user.id,
            action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION,
            target_type="user",
            target_id=user.id,
            ip_address=SUPER_ADMIN_BOOTSTRAP_SYSTEM_IP,
            description="Created by controlled SUPER_ADMIN bootstrap",
            using_db=using_db,
        )
        return SuperAdminBootstrapResult(user_id=user.id, created=True)

    @staticmethod
    def _password_matches(password: str, password_hash: str) -> bool:
        try:
            return verify_password(password, password_hash)
        except (TypeError, ValueError):
            return False
