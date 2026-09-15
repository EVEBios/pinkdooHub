"""桌台二维码解析、开台、查询、收敛与管理员释放编排。"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.transactions import in_transaction

from app.common.constants.inventory import (
    INVENTORY_RETRYABLE_MYSQL_ERROR_CODES,
    INVENTORY_TRANSACTION_MAX_ATTEMPTS,
)
from app.common.constants.table_session import (
    TABLE_AUDIT_ACTION_CREATE,
    TABLE_AUDIT_ACTION_RELEASE,
    TABLE_AUDIT_ACTION_UPDATE,
    TABLE_AUDIT_TARGET_TYPE,
    TABLE_CLAIM_IDEMPOTENCY_PREFIX,
    TABLE_PAYMENT_WINDOW_MINUTES,
    TABLE_RELEASE_IDEMPOTENCY_PREFIX,
    TABLE_SESSION_NO_GENERATION_MAX_ATTEMPTS,
    TABLE_SWEEP_BATCH_SIZE,
)
from app.common.enums.table_session import TableSessionCloseReason, TableSessionStatus
from app.common.enums.user import UserRole, UserStatus
from app.common.exceptions import OrderNotFound, UserDeleted, UserDisabled
from app.common.exceptions.table_session import (
    OrderTableSessionConflict,
    StoreTableNotFound,
    TableCodeNotFound,
    TableIdempotencyConflict,
    TableSessionNotFound,
    TableSessionStatusConflict,
    TableUnavailable,
    UserTableSessionConflict,
)
from app.common.pagination import Page
from app.common.table_session_number import generate_table_session_number
from app.core.config import settings
from app.core.exceptions import PermissionException, ServiceUnavailableException
from app.domain.table_session import automatic_close_for
from app.models.order import Order
from app.models.table_session import StoreTable, TableSession
from app.models.user import User
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.table_session_repo import (
    TableSessionCreateData,
    TableSessionRepository,
)
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.utils.database import get_database_error_code
from app.validators.table_session import validate_order_eligible

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TableCodeResolution:
    table: StoreTable
    is_available: bool


@dataclass(frozen=True, slots=True)
class TableSessionCreateResult:
    session: TableSession
    is_replay: bool


@dataclass(frozen=True, slots=True)
class TableSessionReleaseResult:
    session: TableSession
    is_replay: bool


class TableSessionService:
    """桌台业务事务所有者；支付/订单/退款联动仍由原 Service 所有。"""

    def __init__(
        self,
        table_repository: TableSessionRepository,
        order_repository: OrderRepository,
        user_repository: UserRepository,
        payment_repository: PaymentRepository,
        audit_log_service: AuditLogService,
        *,
        now_provider: Callable[[], datetime] | None = None,
        session_number_generator: Callable[[], str] = generate_table_session_number,
    ) -> None:
        self.table_repository = table_repository
        self.order_repository = order_repository
        self.user_repository = user_repository
        self.payment_repository = payment_repository
        self.audit_log_service = audit_log_service
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.session_number_generator = session_number_generator

    @staticmethod
    def _ensure_claims_available() -> None:
        if not settings.table_session_claims_available:
            raise ServiceUnavailableException(
                message="Table session claims are temporarily disabled"
            )

    @staticmethod
    def _fingerprint(*, user_id: int, qr_token: str, order_id: int) -> str:
        canonical = json.dumps(
            {"order_id": order_id, "qr_token": qr_token, "user_id": user_id},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("ascii")).hexdigest()

    async def resolve_table_code(self, qr_token: str) -> TableCodeResolution:
        self._ensure_claims_available()
        table = await self.table_repository.get_table_by_qr_token(qr_token)
        if table is None:
            raise TableCodeNotFound()
        occupancy = await self.table_repository.get_occupancy_by_table_id(table.id)
        if occupancy is not None:
            await self.converge_session(occupancy.session_id)
            occupancy = await self.table_repository.get_occupancy_by_table_id(table.id)
        return TableCodeResolution(
            table=table,
            is_available=table.is_enabled and occupancy is None,
        )

    async def list_eligible_orders(
        self,
        *,
        user_id: int,
        page: int,
        page_size: int,
    ) -> Page[Order]:
        self._ensure_claims_available()
        await self._converge_user_session(user_id)
        if await self.table_repository.get_occupancy_by_user_id(user_id) is not None:
            raise UserTableSessionConflict()
        return await self.table_repository.list_eligible_orders(
            user_id=user_id,
            page=page,
            page_size=page_size,
        )

    async def create_session(
        self,
        *,
        user: User,
        qr_token: str,
        order_id: int,
        idempotency_key: str,
        ip_address: str,
    ) -> TableSessionCreateResult:
        internal_key = f"{TABLE_CLAIM_IDEMPOTENCY_PREFIX}{idempotency_key}"
        fingerprint = self._fingerprint(
            user_id=user.id,
            qr_token=qr_token,
            order_id=order_id,
        )
        replay = await self._resolve_claim_replay(
            internal_key=internal_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return replay
        self._ensure_claims_available()

        table = await self.table_repository.get_table_by_qr_token(qr_token)
        if table is None:
            raise TableCodeNotFound()
        if not table.is_enabled:
            raise TableUnavailable(table_no=table.table_no, reason="disabled")
        if await self.order_repository.get_order_detail(
            order_id,
            user_id=user.id,
        ) is None:
            raise OrderNotFound()

        await self._converge_user_session(user.id)
        occupancy = await self.table_repository.get_occupancy_by_table_id(table.id)
        if occupancy is not None:
            await self.converge_session(occupancy.session_id)

        for attempt in range(1, INVENTORY_TRANSACTION_MAX_ATTEMPTS + 1):
            session_no = self.session_number_generator()
            try:
                result = await self._create_session_once(
                    user=user,
                    table_id=table.id,
                    order_id=order_id,
                    internal_key=internal_key,
                    fingerprint=fingerprint,
                    session_no=session_no,
                    ip_address=ip_address,
                )
            except IntegrityError:
                replay = await self._resolve_claim_replay(
                    internal_key=internal_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return replay
                await self._raise_current_occupancy_conflict(
                    user_id=user.id,
                    order_id=order_id,
                    table_id=table.id,
                    table_no=table.table_no,
                )
                if (
                    attempt >= TABLE_SESSION_NO_GENERATION_MAX_ATTEMPTS
                    or not await self.table_repository.session_number_exists(session_no)
                ):
                    raise
                continue
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= INVENTORY_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying table claim after MySQL transient error: "
                    "user_id=%d order_id=%d table_id=%d error_code=%d attempt=%d",
                    user.id,
                    order_id,
                    table.id,
                    error_code,
                    attempt,
                )
                continue
            logger.info(
                "Table session created: user_id=%d order_id=%d table_id=%d session_id=%d",
                user.id,
                order_id,
                table.id,
                result.session.id,
            )
            return result
        raise RuntimeError("Table session create retry loop exhausted")

    async def _create_session_once(
        self,
        *,
        user: User,
        table_id: int,
        order_id: int,
        internal_key: str,
        fingerprint: str,
        session_no: str,
        ip_address: str,
    ) -> TableSessionCreateResult:
        async with in_transaction() as connection:
            locked_user = await self.user_repository.get_for_update(
                user.id,
                using_db=connection,
            )
            if locked_user is None or locked_user.status == UserStatus.DELETED:
                raise UserDeleted()
            if locked_user.status == UserStatus.DISABLED:
                raise UserDisabled()
            if locked_user.status != UserStatus.NORMAL or locked_user.role != UserRole.USER:
                raise PermissionException(message="Customer access required")

            order = await self.order_repository.get_order_for_update(
                order_id,
                user_id=locked_user.id,
                using_db=connection,
            )
            if order is None:
                raise OrderNotFound()
            table = await self.table_repository.get_table_for_update(
                table_id,
                using_db=connection,
            )
            if table is None:
                raise TableCodeNotFound()

            existing = await self.table_repository.get_session_by_claim_idempotency_key(
                internal_key,
                using_db=connection,
            )
            if existing is not None:
                if existing.claim_request_fingerprint != fingerprint:
                    raise TableIdempotencyConflict()
                detail = await self.table_repository.get_session_detail(
                    existing.id,
                    using_db=connection,
                )
                if detail is None:
                    raise TableSessionNotFound()
                return TableSessionCreateResult(session=detail, is_replay=True)

            if not table.is_enabled:
                raise TableUnavailable(table_no=table.table_no, reason="disabled")
            items = await self.table_repository.get_order_item_snapshots(
                order.id,
                using_db=connection,
            )
            settlement = await self.payment_repository.get_settlement_by_order_id(
                order.id,
                using_db=connection,
            )
            validate_order_eligible(
                order_id=order.id,
                order_status=order.status,
                has_settlement=settlement is not None,
                items=items,
            )

            await self._converge_locked_table_occupancy(
                table_id=table.id,
                now=self.now_provider(),
                using_db=connection,
            )

            if await self.table_repository.get_occupancy_by_user_id(
                locked_user.id,
                using_db=connection,
            ) is not None:
                raise UserTableSessionConflict()
            if await self.table_repository.get_occupancy_by_order_id(
                order.id,
                using_db=connection,
            ) is not None:
                raise OrderTableSessionConflict(order_id=order.id)
            if await self.table_repository.get_occupancy_by_table_id(
                table.id,
                using_db=connection,
            ) is not None:
                raise TableUnavailable(table_no=table.table_no, reason="occupied")

            claimed_at = self.now_provider()
            session = await self.table_repository.create_session(
                data=TableSessionCreateData(
                    session_no=session_no,
                    table_id=table.id,
                    user_id=locked_user.id,
                    order_id=order.id,
                    claim_idempotency_key=internal_key,
                    claim_request_fingerprint=fingerprint,
                    claimed_at=claimed_at,
                    payment_deadline_at=claimed_at
                    + timedelta(minutes=TABLE_PAYMENT_WINDOW_MINUTES),
                ),
                using_db=connection,
            )
            await self.table_repository.create_occupancy(
                session_id=session.id,
                table_id=table.id,
                user_id=locked_user.id,
                order_id=order.id,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=locked_user.id,
                action=TABLE_AUDIT_ACTION_CREATE,
                target_type=TABLE_AUDIT_TARGET_TYPE,
                target_id=session.id,
                ip_address=ip_address,
                description=json.dumps(
                    {"order_id": order.id, "table_id": table.id},
                    separators=(",", ":"),
                ),
                using_db=connection,
            )
            detail = await self.table_repository.get_session_detail(
                session.id,
                using_db=connection,
            )
            if detail is None:
                raise RuntimeError("Created table session not found")
            return TableSessionCreateResult(session=detail, is_replay=False)

    async def _converge_locked_table_occupancy(
        self,
        *,
        table_id: int,
        now: datetime,
        using_db: BaseDBAsyncClient,
    ) -> None:
        """桌台锁内重检并收敛刚跨过边界的旧占用。"""

        occupancy = await self.table_repository.get_occupancy_by_table_id(
            table_id,
            using_db=using_db,
        )
        if occupancy is None:
            return
        session = await self.table_repository.get_session_for_update(
            occupancy.session_id,
            using_db=using_db,
        )
        if session is None:
            return
        close = automatic_close_for(
            status=TableSessionStatus(session.status),
            now=now,
            payment_deadline_at=session.payment_deadline_at,
            table_release_at=session.table_release_at,
        )
        if close is None:
            return
        await self.table_repository.close_session(
            session,
            reason=close.reason,
            closed_at=close.closed_at,
            closed_by_user_id=None,
            admin_close_reason=None,
            release_idempotency_key=None,
            using_db=using_db,
        )

    async def _resolve_claim_replay(
        self,
        *,
        internal_key: str,
        fingerprint: str,
    ) -> TableSessionCreateResult | None:
        session = await self.table_repository.get_session_by_claim_idempotency_key(
            internal_key
        )
        if session is None:
            return None
        if session.claim_request_fingerprint != fingerprint:
            raise TableIdempotencyConflict()
        detail = await self.table_repository.get_session_detail(session.id)
        if detail is None:
            raise TableSessionNotFound()
        return TableSessionCreateResult(session=detail, is_replay=True)

    async def _raise_current_occupancy_conflict(
        self,
        *,
        user_id: int,
        order_id: int,
        table_id: int,
        table_no: str,
    ) -> None:
        if await self.table_repository.get_occupancy_by_user_id(user_id) is not None:
            raise UserTableSessionConflict()
        if await self.table_repository.get_occupancy_by_order_id(order_id) is not None:
            raise OrderTableSessionConflict(order_id=order_id)
        if await self.table_repository.get_occupancy_by_table_id(table_id) is not None:
            raise TableUnavailable(table_no=table_no, reason="occupied")

    async def _converge_user_session(self, user_id: int) -> None:
        session = await self.table_repository.get_open_session_by_user_id(user_id)
        if session is not None:
            await self.converge_session(session.id)

    async def converge_session(
        self,
        session_id: int,
        *,
        now: datetime | None = None,
    ) -> bool:
        """按全局锁序惰性关闭一个已超时或已到期会话。"""

        current_time = now or self.now_provider()
        for attempt in range(1, INVENTORY_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                return await self._converge_session_once(
                    session_id=session_id,
                    current_time=current_time,
                )
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= INVENTORY_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying table convergence after MySQL transient error: "
                    "session_id=%d error_code=%d attempt=%d",
                    session_id,
                    error_code,
                    attempt,
                )

        raise RuntimeError("Table session convergence retry loop exhausted")

    async def _converge_session_once(
        self,
        *,
        session_id: int,
        current_time: datetime,
    ) -> bool:
        visible = await self.table_repository.get_session_detail(session_id)
        if visible is None:
            return False
        async with in_transaction() as connection:
            await self.user_repository.get_for_update(
                visible.user_id,
                using_db=connection,
            )
            await self.order_repository.get_order_for_update(
                visible.order_id,
                using_db=connection,
            )
            await self.table_repository.get_table_for_update(
                visible.table_id,
                using_db=connection,
            )
            session = await self.table_repository.get_session_for_update(
                visible.id,
                using_db=connection,
            )
            if session is None:
                return False
            close = automatic_close_for(
                status=TableSessionStatus(session.status),
                now=current_time,
                payment_deadline_at=session.payment_deadline_at,
                table_release_at=session.table_release_at,
            )
            if close is None:
                return False
            await self.table_repository.close_session(
                session,
                reason=close.reason,
                closed_at=close.closed_at,
                closed_by_user_id=None,
                admin_close_reason=None,
                release_idempotency_key=None,
                using_db=connection,
            )
            logger.info(
                "Table session converged: session_id=%d reason=%s",
                session.id,
                close.reason.value,
            )
            return True

    async def sweep_due_sessions(
        self,
        *,
        now: datetime | None = None,
        limit: int = TABLE_SWEEP_BATCH_SIZE,
    ) -> int:
        current_time = now or self.now_provider()
        session_ids = await self.table_repository.list_due_session_ids(
            now=current_time,
            after_id=0,
            limit=limit,
        )
        closed = 0
        for session_id in session_ids:
            closed += int(await self.converge_session(session_id, now=current_time))
        return closed

    async def get_current_session(self, *, user_id: int) -> TableSession | None:
        await self._converge_user_session(user_id)
        session = await self.table_repository.get_open_session_by_user_id(user_id)
        if session is None:
            return None
        return await self.table_repository.get_session_detail(session.id)

    async def get_latest_order_session(
        self,
        *,
        order_id: int,
        user_id: int,
    ) -> TableSession | None:
        owner_order = await self.order_repository.get_order_detail(
            order_id,
            user_id=user_id,
        )
        if owner_order is None:
            raise OrderNotFound()
        session = await self.table_repository.get_latest_session_by_order_id(
            order_id,
            user_id=user_id,
        )
        if session is None:
            return None
        if TableSessionStatus(session.status) is not TableSessionStatus.CLOSED:
            await self.converge_session(session.id)
            session = await self.table_repository.get_session_detail(session.id)
        return session

    async def list_admin_tables(self) -> list[StoreTable]:
        await self.sweep_due_sessions()
        return await self.table_repository.list_tables()

    async def update_table(
        self,
        *,
        table_id: int,
        is_enabled: bool,
        reason: str,
        operator_id: int,
        ip_address: str,
    ) -> StoreTable:
        normalized_reason = reason.strip()
        async with in_transaction() as connection:
            table = await self.table_repository.get_table_for_update(
                table_id,
                using_db=connection,
            )
            if table is None:
                raise StoreTableNotFound()
            if table.is_enabled == is_enabled:
                return table
            before = table.is_enabled
            await self.table_repository.update_table_enabled(
                table,
                is_enabled=is_enabled,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action=TABLE_AUDIT_ACTION_UPDATE,
                target_type="store_table",
                target_id=table.id,
                ip_address=ip_address,
                description=json.dumps(
                    {
                        "before_enabled": before,
                        "after_enabled": is_enabled,
                        "reason": normalized_reason,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                using_db=connection,
            )
            return table

    async def list_admin_sessions(self, **filters: object) -> Page[TableSession]:
        await self.sweep_due_sessions()
        return await self.table_repository.list_admin_sessions(**filters)

    async def get_admin_session(self, session_no: str) -> TableSession:
        session = await self.table_repository.get_session_detail_by_no(session_no)
        if session is None:
            raise TableSessionNotFound()
        if TableSessionStatus(session.status) is not TableSessionStatus.CLOSED:
            await self.converge_session(session.id)
            session = await self.table_repository.get_session_detail(session.id)
            if session is None:
                raise TableSessionNotFound()
        return session

    async def release_session(
        self,
        *,
        session_no: str,
        operator_id: int,
        reason: str,
        idempotency_key: str,
        ip_address: str,
    ) -> TableSessionReleaseResult:
        internal_key = f"{TABLE_RELEASE_IDEMPOTENCY_PREFIX}{idempotency_key}"
        normalized_reason = reason.strip()
        replay = await self._resolve_release_replay(
            session_no=session_no,
            operator_id=operator_id,
            normalized_reason=normalized_reason,
            internal_key=internal_key,
        )
        if replay is not None:
            return replay

        visible = await self.table_repository.get_session_detail_by_no(session_no)
        if visible is None:
            raise TableSessionNotFound()
        await self.converge_session(visible.id)

        for attempt in range(1, INVENTORY_TRANSACTION_MAX_ATTEMPTS + 1):
            try:
                return await self._release_session_once(
                    visible=visible,
                    session_no=session_no,
                    operator_id=operator_id,
                    normalized_reason=normalized_reason,
                    internal_key=internal_key,
                    ip_address=ip_address,
                )
            except IntegrityError:
                replay = await self._resolve_release_replay(
                    session_no=session_no,
                    operator_id=operator_id,
                    normalized_reason=normalized_reason,
                    internal_key=internal_key,
                )
                if replay is not None:
                    return replay
                raise
            except OperationalError as exc:
                error_code = get_database_error_code(exc)
                if (
                    error_code not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES
                    or attempt >= INVENTORY_TRANSACTION_MAX_ATTEMPTS
                ):
                    raise
                logger.warning(
                    "Retrying table release after MySQL transient error: "
                    "operator_id=%d session_id=%d error_code=%d attempt=%d",
                    operator_id,
                    visible.id,
                    error_code,
                    attempt,
                )

        raise RuntimeError("Table session release retry loop exhausted")

    async def _release_session_once(
        self,
        *,
        visible: TableSession,
        session_no: str,
        operator_id: int,
        normalized_reason: str,
        internal_key: str,
        ip_address: str,
    ) -> TableSessionReleaseResult:
        async with in_transaction() as connection:
            await self.user_repository.get_for_update(
                visible.user_id,
                using_db=connection,
            )
            await self.order_repository.get_order_for_update(
                visible.order_id,
                using_db=connection,
            )
            await self.table_repository.get_table_for_update(
                visible.table_id,
                using_db=connection,
            )
            session = await self.table_repository.get_session_by_no_for_update(
                session_no,
                using_db=connection,
            )
            if session is None:
                raise TableSessionNotFound()
            status = TableSessionStatus(session.status)
            if status is TableSessionStatus.CLOSED:
                if (
                    session.release_idempotency_key == internal_key
                    and session.closed_by_user_id == operator_id
                    and session.admin_close_reason == normalized_reason
                    and TableSessionCloseReason(session.close_reason)
                    is TableSessionCloseReason.ADMIN_RELEASED
                ):
                    detail = await self.table_repository.get_session_detail(
                        session.id,
                        using_db=connection,
                    )
                    if detail is None:
                        raise TableSessionNotFound()
                    return TableSessionReleaseResult(
                        session=detail,
                        is_replay=True,
                    )
                raise TableSessionStatusConflict(
                    operation="admin_release",
                    current_status=status,
                    required_status="awaiting_payment|active",
                )
            await self.table_repository.close_session(
                session,
                reason=TableSessionCloseReason.ADMIN_RELEASED,
                closed_at=self.now_provider(),
                closed_by_user_id=operator_id,
                admin_close_reason=normalized_reason,
                release_idempotency_key=internal_key,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action=TABLE_AUDIT_ACTION_RELEASE,
                target_type=TABLE_AUDIT_TARGET_TYPE,
                target_id=session.id,
                ip_address=ip_address,
                description=json.dumps(
                    {
                        "order_id": session.order_id,
                        "table_id": session.table_id,
                        "reason": normalized_reason,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                using_db=connection,
            )
            detail = await self.table_repository.get_session_detail(
                session.id,
                using_db=connection,
            )
            if detail is None:
                raise TableSessionNotFound()
            return TableSessionReleaseResult(session=detail, is_replay=False)

    async def _resolve_release_replay(
        self,
        *,
        session_no: str,
        operator_id: int,
        normalized_reason: str,
        internal_key: str,
    ) -> TableSessionReleaseResult | None:
        session = await self.table_repository.get_session_by_release_idempotency_key(
            internal_key
        )
        if session is None:
            return None
        if (
            session.session_no != session_no
            or session.closed_by_user_id != operator_id
            or session.admin_close_reason != normalized_reason
            or session.close_reason is not TableSessionCloseReason.ADMIN_RELEASED
        ):
            raise TableIdempotencyConflict()
        detail = await self.table_repository.get_session_detail(session.id)
        if detail is None:
            raise TableSessionNotFound()
        return TableSessionReleaseResult(session=detail, is_replay=True)
