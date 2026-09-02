"""用户注销、匿名化与会话撤销。"""

import logging
import secrets
from datetime import datetime, timezone

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions.user import (
    AccountDeletionBlocked,
    ExternalIdentityInvalid,
    IncorrectPassword,
    UserDeleted,
)
from app.core.exceptions import PermissionException
from app.core.external_identity import external_identity_key
from app.core.redis import revoke_user_refresh_sessions
from app.core.security import verify_password
from app.core.security_events import emit_security_event
from app.integrations.wechat import (
    ExternalIdentityCredentials,
    ExternalIdentityProvider,
)
from app.models.user import User
from app.repositories.external_identity_repo import ExternalIdentityRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.user_repo import UserRepository
from app.schemas.user import AccountDeletionRequest
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class AccountLifecycleService:
    """在保留订单/库存/审计外键完整性的前提下逻辑注销。"""

    def __init__(
        self,
        user_repository: UserRepository,
        order_repository: OrderRepository,
        identity_repository: ExternalIdentityRepository,
        audit_log_service: AuditLogService,
        provider: ExternalIdentityProvider,
    ) -> None:
        self.user_repository = user_repository
        self.order_repository = order_repository
        self.identity_repository = identity_repository
        self.audit_log_service = audit_log_service
        self.provider = provider

    async def delete_account(
        self,
        *,
        user: User,
        data: AccountDeletionRequest,
        ip_address: str,
    ) -> None:
        if user.role != UserRole.USER:
            raise PermissionException(
                message="Privileged accounts cannot self-delete"
            )
        credentials = None
        if data.wechat_code is not None:
            credentials = await self.provider.exchange_code(data.wechat_code)

        async with in_transaction() as connection:
            locked_user = await self.user_repository.get_for_update(
                user.id,
                using_db=connection,
            )
            if locked_user is None or locked_user.status == UserStatus.DELETED:
                raise UserDeleted()
            if locked_user.role != UserRole.USER:
                raise PermissionException(
                    message="Privileged accounts cannot self-delete"
                )
            await self._reauthenticate_locked(
                user=locked_user,
                data=data,
                credentials=credentials,
                using_db=connection,
            )
            if await self.order_repository.has_non_terminal_orders_for_user(
                locked_user.id,
                using_db=connection,
            ):
                emit_security_event(
                    "account_deletion",
                    "blocked_active_order",
                    level=logging.WARNING,
                    user_id=locked_user.id,
                )
                raise AccountDeletionBlocked()

            await self.audit_log_service.log(
                operator_id=locked_user.id,
                action="DELETE_ACCOUNT",
                target_type="user",
                target_id=locked_user.id,
                ip_address=ip_address,
                using_db=connection,
            )
            await self.identity_repository.delete_all_for_user(
                locked_user.id,
                using_db=connection,
            )
            await self.user_repository.update(
                locked_user,
                username=f"deleted_{secrets.token_hex(12)}",
                password=None,
                nickname="已注销用户",
                phone=None,
                avatar=None,
                status=int(UserStatus.DELETED),
                last_login_at=None,
                auth_version=locked_user.auth_version + 1,
                deleted_at=datetime.now(timezone.utc),
                using_db=connection,
            )

        await revoke_user_refresh_sessions(user.id)
        logger.info("User account anonymized: user_id=%d", user.id)
        emit_security_event(
            "account_deletion",
            "anonymized",
            user_id=user.id,
        )

    async def _reauthenticate_locked(
        self,
        *,
        user: User,
        data: AccountDeletionRequest,
        credentials: ExternalIdentityCredentials | None,
        using_db: BaseDBAsyncClient,
    ) -> None:
        if data.password is not None:
            if user.password is None or not verify_password(data.password, user.password):
                raise IncorrectPassword()
            return

        if credentials is None:
            raise ExternalIdentityInvalid()
        identity = await self.identity_repository.get_by_subject(
            provider=credentials.provider,
            app_id=credentials.app_id,
            subject_id=external_identity_key(
                credentials.provider,
                credentials.subject_id,
            ),
            using_db=using_db,
        )
        if identity is None or identity.user_id != user.id:
            raise ExternalIdentityInvalid()
