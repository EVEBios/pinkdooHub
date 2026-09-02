"""外部平台登录、绑定与解绑编排。"""

import logging
from datetime import datetime, timezone

from tortoise.exceptions import IntegrityError
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions.user import (
    ExternalIdentityConflict,
    ExternalIdentityNotBound,
    ExternalIdentityUnlinkUnsafe,
    IncorrectPassword,
    UserDeleted,
    UserDisabled,
)
from app.core.auth_session import issue_token_pair
from app.core.exceptions import PermissionException
from app.core.external_identity import external_identity_key
from app.core.rate_limit import (
    AuthRateLimiter,
    WECHAT_BIND_POLICY,
    WECHAT_LOGIN_POLICY,
)
from app.core.redis import revoke_user_refresh_sessions
from app.core.security import verify_password
from app.core.security_events import emit_security_event
from app.integrations.wechat import ExternalIdentityCredentials, ExternalIdentityProvider
from app.models.external_identity import ExternalIdentity
from app.models.user import User
from app.repositories.external_identity_repo import ExternalIdentityRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


class ExternalAuthService:
    """不信任客户端身份，只消费 Provider 换取的服务端凭据。"""

    def __init__(
        self,
        user_repository: UserRepository,
        identity_repository: ExternalIdentityRepository,
        audit_log_service: AuditLogService,
        provider: ExternalIdentityProvider,
        rate_limiter: AuthRateLimiter | None = None,
    ) -> None:
        self.user_repository = user_repository
        self.identity_repository = identity_repository
        self.audit_log_service = audit_log_service
        self.provider = provider
        self.rate_limiter = rate_limiter or AuthRateLimiter()

    async def login(
        self,
        *,
        code: str,
        ip_address: str,
    ) -> dict[str, User | str]:
        await self.rate_limiter.check(
            WECHAT_LOGIN_POLICY,
            ip_address or "unknown",
        )
        credentials = await self.provider.exchange_code(code)
        identity = await self.identity_repository.get_by_subject(
            provider=credentials.provider,
            app_id=credentials.app_id,
            subject_id=self._subject_key(credentials),
        )
        if identity is None:
            user = await self._create_user_and_identity(credentials, ip_address)
        else:
            user = identity.user
            self._ensure_user_can_login(user)
            await self.user_repository.update(
                user,
                last_login_at=datetime.now(timezone.utc),
            )
            await self.audit_log_service.log(
                operator_id=user.id,
                action="WECHAT_LOGIN",
                target_type="user",
                target_id=user.id,
                ip_address=ip_address,
            )

        tokens = await issue_token_pair(
            user_id=user.id,
            auth_version=user.auth_version,
        )
        logger.info("External identity login succeeded: user_id=%d", user.id)
        emit_security_event(
            "external_identity_login",
            "succeeded",
            user_id=user.id,
            scope=credentials.provider,
        )
        return {"user": user, **tokens}

    async def bind(
        self,
        *,
        user: User,
        code: str,
        ip_address: str,
    ) -> ExternalIdentity:
        if user.role != UserRole.USER:
            raise PermissionException(
                message="Privileged accounts cannot bind external identities"
            )
        await self.rate_limiter.check(
            WECHAT_BIND_POLICY,
            f"{ip_address or 'unknown'}:{user.id}",
        )
        credentials = await self.provider.exchange_code(code)

        async with in_transaction() as connection:
            locked_user = await self.user_repository.get_for_update(
                user.id,
                using_db=connection,
            )
            if locked_user is None:
                raise UserDeleted()
            self._ensure_user_can_login(locked_user)
            self._ensure_standard_user(locked_user, operation="bind")

            subject = await self.identity_repository.get_by_subject(
                provider=credentials.provider,
                app_id=credentials.app_id,
                subject_id=self._subject_key(credentials),
                using_db=connection,
            )
            if subject is not None:
                if subject.user_id == locked_user.id:
                    return subject
                raise ExternalIdentityConflict()

            existing = await self.identity_repository.get_for_user_provider(
                user_id=locked_user.id,
                provider=credentials.provider,
                app_id=credentials.app_id,
                using_db=connection,
            )
            if existing is not None:
                raise ExternalIdentityConflict()
            await self._ensure_union_available(
                credentials,
                user_id=locked_user.id,
                using_db=connection,
            )
            identity = await self.identity_repository.create(
                provider=credentials.provider,
                app_id=credentials.app_id,
                subject_id=self._subject_key(credentials),
                union_id=self._union_key(credentials),
                user_id=locked_user.id,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=locked_user.id,
                action="BIND_EXTERNAL_IDENTITY",
                target_type="user",
                target_id=locked_user.id,
                ip_address=ip_address,
                using_db=connection,
            )
        logger.info("External identity bound: user_id=%d", user.id)
        emit_security_event(
            "external_identity_bind",
            "succeeded",
            user_id=user.id,
            scope=credentials.provider,
        )
        return identity

    async def unbind_wechat(
        self,
        *,
        user: User,
        password: str,
        ip_address: str,
    ) -> None:
        if user.role != UserRole.USER:
            raise PermissionException(
                message="Privileged accounts cannot unlink external identities"
            )
        async with in_transaction() as connection:
            locked_user = await self.user_repository.get_for_update(
                user.id,
                using_db=connection,
            )
            if locked_user is None:
                raise UserDeleted()
            self._ensure_user_can_login(locked_user)
            self._ensure_standard_user(locked_user, operation="unlink")
            if locked_user.password is None:
                raise ExternalIdentityUnlinkUnsafe()
            if not verify_password(password, locked_user.password):
                raise IncorrectPassword()
            identity = await self.identity_repository.get_for_user_provider(
                user_id=locked_user.id,
                provider="wechat_miniprogram",
                app_id=self._provider_app_id(),
                using_db=connection,
            )
            if identity is None:
                raise ExternalIdentityNotBound()
            await self.identity_repository.delete(identity, using_db=connection)
            await self.user_repository.update(
                locked_user,
                auth_version=locked_user.auth_version + 1,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=locked_user.id,
                action="UNBIND_EXTERNAL_IDENTITY",
                target_type="user",
                target_id=locked_user.id,
                ip_address=ip_address,
                using_db=connection,
            )
        await revoke_user_refresh_sessions(user.id)
        logger.info("External identity unbound: user_id=%d", user.id)
        emit_security_event(
            "external_identity_unbind",
            "succeeded",
            user_id=user.id,
            scope="wechat_miniprogram",
        )

    async def list_identities(self, user_id: int) -> list[ExternalIdentity]:
        return await self.identity_repository.list_for_user(user_id)

    async def _create_user_and_identity(
        self,
        credentials: ExternalIdentityCredentials,
        ip_address: str,
    ) -> User:
        username = self._system_username(credentials)
        try:
            async with in_transaction() as connection:
                await self._ensure_union_available(
                    credentials,
                    user_id=None,
                    using_db=connection,
                )
                user = await self.user_repository.create(
                    username=username,
                    password=None,
                    nickname="微信用户",
                    phone=None,
                    using_db=connection,
                )
                await self.identity_repository.create(
                    provider=credentials.provider,
                    app_id=credentials.app_id,
                    subject_id=self._subject_key(credentials),
                    union_id=self._union_key(credentials),
                    user_id=user.id,
                    using_db=connection,
                )
                await self.audit_log_service.log(
                    operator_id=user.id,
                    action="WECHAT_REGISTER",
                    target_type="user",
                    target_id=user.id,
                    ip_address=ip_address,
                    using_db=connection,
                )
        except IntegrityError:
            identity = await self.identity_repository.get_by_subject(
                provider=credentials.provider,
                app_id=credentials.app_id,
                subject_id=self._subject_key(credentials),
            )
            if identity is None:
                raise ExternalIdentityConflict()
            user = identity.user
        self._ensure_user_can_login(user)
        await self.user_repository.update(
            user,
            last_login_at=datetime.now(timezone.utc),
        )
        return user

    async def _ensure_union_available(
        self,
        credentials: ExternalIdentityCredentials,
        *,
        user_id: int | None,
        using_db: BaseDBAsyncClient,
    ) -> None:
        if credentials.union_id is None:
            return
        identity = await self.identity_repository.get_by_union(
            provider=credentials.provider,
            union_id=self._union_key(credentials) or "",
            using_db=using_db,
        )
        if identity is not None and identity.user_id != user_id:
            raise ExternalIdentityConflict()

    @staticmethod
    def _ensure_user_can_login(user: User) -> None:
        if user.status == UserStatus.DISABLED:
            raise UserDisabled()
        if user.status == UserStatus.DELETED:
            raise UserDeleted()

    @staticmethod
    def _ensure_standard_user(user: User, *, operation: str) -> None:
        if user.role != UserRole.USER:
            raise PermissionException(
                message=f"Privileged accounts cannot {operation} external identities"
            )

    @staticmethod
    def _system_username(credentials: ExternalIdentityCredentials) -> str:
        digest = external_identity_key(
            credentials.provider,
            f"{credentials.app_id}:{credentials.subject_id}",
        )[:27]
        return f"wx_{digest}"

    @staticmethod
    def _subject_key(credentials: ExternalIdentityCredentials) -> str:
        return external_identity_key(
            credentials.provider,
            credentials.subject_id,
        )

    @staticmethod
    def _union_key(credentials: ExternalIdentityCredentials) -> str | None:
        if credentials.union_id is None:
            return None
        return external_identity_key(credentials.provider, credentials.union_id)

    def _provider_app_id(self) -> str:
        app_id = getattr(self.provider, "app_id", None)
        if isinstance(app_id, str):
            return app_id
        from app.core.config import settings

        return settings.wechat_app_id
