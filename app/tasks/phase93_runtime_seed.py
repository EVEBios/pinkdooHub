"""为 Phase 9.3 纵向 Smoke 创建受控合成角色账号。"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Mapping

from tortoise import Tortoise
from tortoise.transactions import in_transaction

from app.common.constants.bootstrap import SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV
from app.common.enums.user import UserRole, UserStatus
from app.core.logging import setup_logging
from app.core.security import hash_password
from app.db.database import TORTOISE_ORM
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService


logger = logging.getLogger(__name__)

PHASE93_RUNTIME_SEED_ENABLE_ENV = "PHASE93_RUNTIME_SEED_ENABLED"
PHASE93_RUNTIME_SEED_ACTION = "CREATE_PHASE93_SYNTHETIC_USER"
SYNTHETIC_USERS = (
    (
        "phase93_admin",
        "Phase93 Admin",
        "13800009302",
        UserRole.ADMIN,
        UserStatus.NORMAL,
    ),
    ("phase93_user", "Phase93 User", "13800009303", UserRole.USER, UserStatus.NORMAL),
    (
        "phase93_disabled",
        "Phase93 Disabled",
        "13800009304",
        UserRole.USER,
        UserStatus.DISABLED,
    ),
)


class RuntimeSeedError(RuntimeError):
    """不包含密码或连接串的运行时合成数据错误。"""


def validate_target(environment: Mapping[str, str]) -> None:
    """只允许冻结 Compose 内部 source 数据库的显式调用。"""

    expected = {
        PHASE93_RUNTIME_SEED_ENABLE_ENV: "1",
        "APP_ENV": "production",
        "DB_ENGINE": "mysql",
        "DB_HOST": "mysql-source",
        "DB_PORT": "3306",
        "DB_NAME": "pinkdoohub_phase93_source",
        "DB_USER": "pinkdoo",
    }
    for key, value in expected.items():
        if environment.get(key) != value:
            raise RuntimeSeedError(f"runtime synthetic seed target rejected: {key}")
    if not environment.get(SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV):
        raise RuntimeSeedError("runtime synthetic seed password Secret is unavailable")


async def seed(password: str) -> dict[str, int]:
    """通过 Repository 在一个事务中创建 ADMIN/User/Disabled fixtures。"""

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        user_repository = UserRepository()
        audit_service = AuditLogService(AuditLogRepository())
        async with in_transaction() as connection:
            super_admins = await user_repository.list_by_role_for_update(
                UserRole.SUPER_ADMIN.value,
                using_db=connection,
            )
            if (
                len(super_admins) != 1
                or super_admins[0].username != "phase93_owner"
                or super_admins[0].status != UserStatus.NORMAL.value
            ):
                raise RuntimeSeedError("expected Phase 9.3 SUPER_ADMIN is unavailable")
            operator = super_admins[0]
            for username, _, phone, _, _ in SYNTHETIC_USERS:
                if (
                    await user_repository.get_by_username(
                        username,
                        using_db=connection,
                    )
                    is not None
                    or await user_repository.get_by_phone(
                        phone,
                        using_db=connection,
                    )
                    is not None
                ):
                    raise RuntimeSeedError("synthetic user identity already exists")

            created_ids: dict[str, int] = {}
            for username, nickname, phone, role, status in SYNTHETIC_USERS:
                user = await user_repository.create(
                    username=username,
                    password=hash_password(password),
                    nickname=nickname,
                    phone=phone,
                    role=role.value,
                    status=status.value,
                    using_db=connection,
                )
                await audit_service.log(
                    operator_id=operator.id,
                    action=PHASE93_RUNTIME_SEED_ACTION,
                    target_type="user",
                    target_id=user.id,
                    ip_address="127.0.0.1",
                    description="Phase 9.3 synthetic runtime fixture",
                    using_db=connection,
                )
                created_ids[username] = user.id
        return created_ids
    finally:
        await Tortoise.close_connections()


def main() -> int:
    setup_logging()
    try:
        validate_target(os.environ)
        password = os.environ[SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV]
        created = asyncio.run(seed(password))
    except RuntimeSeedError as error:
        logger.error("Phase 9.3 runtime seed refused: %s", error)
        return 2
    except Exception as error:
        logger.error(
            "Phase 9.3 runtime seed failed: error_type=%s",
            type(error).__name__,
        )
        return 1
    logger.info(
        "Phase 9.3 runtime seed succeeded: users=%d",
        len(created),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
