"""Reservation Service/Repository 的真实 SQLite 业务闭环测试。"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from tortoise.backends.base.client import BaseDBAsyncClient

import app.services.account_lifecycle_service as account_lifecycle_module
from app.api.mappers.reservation import (
    map_admin_reservation_detail,
    map_admin_reservation_page,
    map_reservation,
)
from app.common.constants.reservation import RESERVATION_CUSTOMER_MESSAGES
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationScheduleUnavailableReason,
    ReservationStatus,
)
from app.common.enums.user import UserStatus
from app.common.exceptions.reservation import (
    ReservationCancellationWindowClosed,
    ReservationNotFound,
    ReservationOperationExpired,
    ReservationOptionUnavailable,
    ReservationPhoneRequired,
    ReservationProductUnavailable,
    ReservationScheduleUnavailable,
    ReservationStatusConflict,
)
from app.common.exceptions.user import AccountDeletionBlocked
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.reservation import Reservation, StoreBusinessDay
from app.repositories.audit_log_repo import AuditLogCreateData, AuditLogRepository
from app.repositories.external_identity_repo import ExternalIdentityRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wallet_repo import WalletRepository
from app.schemas.user import AccountDeletionRequest
from app.services.account_lifecycle_service import AccountLifecycleService
from app.services.audit_log_service import AuditLogService
from app.services.reservation_service import ReservationService
from tests.reservation.support import (
    FROZEN_LOCAL_DATE,
    FROZEN_NOW,
    create_option,
    create_reservation_record,
    create_user,
    make_service,
)


async def test_create_reservation_persists_pending_snapshot_and_audit() -> None:
    customer = await create_user("create")
    product, option = await create_option(
        "create",
        duration=90,
        participants=3,
        price=Decimal("128.00"),
    )

    result = await make_service().create_reservation(
        user_id=customer.id,
        experience_option_id=option.id,
        reservation_date=date(2026, 9, 9),
        start_time="11:30",
        ip_address="203.0.113.10",
    )

    assert ReservationStatus(result.status) is ReservationStatus.PENDING
    assert result.user_id == customer.id
    assert result.product_id == product.id
    assert result.experience_option_id == option.id
    assert result.product_name == product.name
    assert result.option_duration_minutes == 90
    assert result.option_participants == 3
    assert DayType(result.option_day_type) is DayType.WEEKDAY
    assert result.option_price == Decimal("128.00")
    assert result.scheduled_start_at == datetime(
        2026, 9, 9, 3, 30, tzinfo=timezone.utc
    )
    assert result.scheduled_end_at == datetime(
        2026, 9, 9, 5, 0, tzinfo=timezone.utc
    )
    assert result.rejection_reason is None
    assert result.cancellation_reason is None

    audit = await AuditLog.get(
        action="CREATE_RESERVATION",
        target_type="reservation",
        target_id=result.id,
    )
    assert audit.operator_id == customer.id
    assert audit.ip_address == "203.0.113.10"
    assert audit.description is None


async def test_create_requires_current_phone_and_leaves_no_business_facts() -> None:
    customer = await create_user("no-phone", phone=None)
    _, option = await create_option("no-phone")

    with pytest.raises(ReservationPhoneRequired) as caught:
        await make_service().create_reservation(
            user_id=customer.id,
            experience_option_id=option.id,
            reservation_date=date(2026, 9, 9),
            start_time="11:00",
            ip_address="127.0.0.1",
        )

    assert caught.value.code == 42254
    assert not await Reservation.all().exists()
    assert not await StoreBusinessDay.all().exists()
    assert not await AuditLog.filter(action="CREATE_RESERVATION").exists()


async def test_create_on_custom_closed_day_is_rejected_atomically() -> None:
    customer = await create_user("closed-day")
    admin = await create_user("closed-admin", phone="13900139001")
    _, option = await create_option("closed-day")
    service = make_service()
    business_date = date(2026, 9, 9)
    await service.close_store_day(
        business_date,
        operator_id=admin.id,
        ip_address="127.0.0.1",
    )

    with pytest.raises(ReservationScheduleUnavailable) as caught:
        await service.create_reservation(
            user_id=customer.id,
            experience_option_id=option.id,
            reservation_date=business_date,
            start_time="11:00",
            ip_address="127.0.0.1",
        )

    assert caught.value.data == {
        "reason": ReservationScheduleUnavailableReason.STORE_CLOSED.value
    }
    assert not await Reservation.all().exists()
    assert not await AuditLog.filter(action="CREATE_RESERVATION").exists()


@pytest.mark.parametrize(
    "case",
    ["missing", "deleted_option", "offline", "deleted_product", "kit"],
)
async def test_create_rejects_unavailable_option_or_product(case: str) -> None:
    customer = await create_user(f"unavailable-{case}")
    expected_exception: type[Exception]
    if case == "missing":
        option_id = 999_999
        expected_exception = ReservationOptionUnavailable
    else:
        _, option = await create_option(
            f"unavailable-{case}",
            option_deleted=case == "deleted_option",
            product_status=(
                ProductStatus.OFFLINE if case == "offline" else ProductStatus.ONLINE
            ),
            product_deleted=case == "deleted_product",
            product_type=(ProductType.KIT if case == "kit" else ProductType.EXPERIENCE),
        )
        option_id = option.id
        expected_exception = (
            ReservationOptionUnavailable
            if case == "deleted_option"
            else ReservationProductUnavailable
        )

    with pytest.raises(expected_exception):
        await make_service().create_reservation(
            user_id=customer.id,
            experience_option_id=option_id,
            reservation_date=date(2026, 9, 9),
            start_time="11:00",
            ip_address="127.0.0.1",
        )

    assert not await Reservation.all().exists()
    assert not await AuditLog.filter(action="CREATE_RESERVATION").exists()


@pytest.mark.parametrize(
    ("method_name", "expected_status", "expected_action"),
    [
        ("confirm_reservation", ReservationStatus.CONFIRMED, "CONFIRM_RESERVATION"),
        ("reject_reservation", ReservationStatus.REJECTED, "REJECT_RESERVATION"),
    ],
)
async def test_admin_pending_transition_sets_exact_reason_time_message_and_audit(
    method_name: str,
    expected_status: ReservationStatus,
    expected_action: str,
) -> None:
    owner = await create_user(f"transition-owner-{method_name}")
    admin = await create_user(
        f"transition-admin-{method_name}",
        phone="13900139001",
    )
    product, option = await create_option(f"transition-{method_name}")
    reservation = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        business_date=date(2026, 9, 9),
    )

    result = await getattr(make_service(), method_name)(
        reservation.id,
        operator_id=admin.id,
        ip_address="198.51.100.8",
    )
    payload = map_reservation(result).model_dump(mode="json")

    assert ReservationStatus(result.status) is expected_status
    assert payload["status"]["value"] == expected_status.value
    assert payload["customer_message"] == RESERVATION_CUSTOMER_MESSAGES[expected_status]
    if expected_status is ReservationStatus.CONFIRMED:
        assert result.confirmed_at == FROZEN_NOW
        assert result.rejection_reason is None
        assert result.rejected_at is None
        assert payload["rejection_reason"] is None
    else:
        assert result.confirmed_at is None
        assert result.rejection_reason == ReservationRejectionReason.NO_CAPACITY
        assert result.rejected_at == FROZEN_NOW
        assert payload["rejection_reason"] == {
            "value": "no_capacity",
            "label": "当前时段无空位",
        }
        assert "无空位" in payload["customer_message"]
        assert "重新预约" in payload["customer_message"]
    audit = await AuditLog.get(
        target_type="reservation",
        target_id=reservation.id,
        action=expected_action,
    )
    assert audit.operator_id == admin.id
    assert audit.ip_address == "198.51.100.8"
    assert audit.description == (
        "reason=no_capacity"
        if expected_status is ReservationStatus.REJECTED
        else None
    )


@pytest.mark.parametrize("initial_status", [ReservationStatus.PENDING, ReservationStatus.CONFIRMED])
async def test_customer_can_cancel_pending_or_confirmed_with_customer_reason(
    initial_status: ReservationStatus,
) -> None:
    owner = await create_user(f"cancel-{initial_status.value}")
    product, option = await create_option(f"cancel-{initial_status.value}")
    confirmed_at = (
        FROZEN_NOW - timedelta(hours=1)
        if initial_status is ReservationStatus.CONFIRMED
        else None
    )
    reservation = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        business_date=FROZEN_LOCAL_DATE,
        local_start=time(11, 0),
        status=initial_status,
        confirmed_at=confirmed_at,
    )

    result = await make_service().cancel_reservation(
        reservation.id,
        user_id=owner.id,
        ip_address="203.0.113.5",
    )
    payload = map_reservation(result).model_dump(mode="json")

    assert ReservationStatus(result.status) is ReservationStatus.CANCELLED
    assert result.cancellation_reason == ReservationCancellationReason.CUSTOMER_REQUEST
    assert result.cancelled_at == FROZEN_NOW
    assert result.confirmed_at == confirmed_at
    assert payload["cancellation_reason"] == {
        "value": "customer_request",
        "label": "顾客取消",
    }
    assert payload["customer_message"] == RESERVATION_CUSTOMER_MESSAGES[
        ReservationCancellationReason.CUSTOMER_REQUEST
    ]
    audit = await AuditLog.get(
        action="CANCEL_RESERVATION",
        target_type="reservation",
        target_id=reservation.id,
    )
    assert audit.operator_id == owner.id
    assert audit.description == "reason=customer_request"


async def test_customer_cancellation_allows_exact_deadline_but_not_one_microsecond_late() -> None:
    owner = await create_user("cancel-boundary")
    product, option = await create_option("cancel-boundary")
    allowed = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(11, 0),
    )
    late = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(11, 0),
    )

    await make_service(now=FROZEN_NOW).cancel_reservation(
        allowed.id,
        user_id=owner.id,
        ip_address="127.0.0.1",
    )
    with pytest.raises(ReservationCancellationWindowClosed):
        await make_service(
            now=FROZEN_NOW + timedelta(microseconds=1)
        ).cancel_reservation(
            late.id,
            user_id=owner.id,
            ip_address="127.0.0.1",
        )

    assert (
        ReservationStatus((await Reservation.get(id=allowed.id)).status)
        is ReservationStatus.CANCELLED
    )
    assert (
        ReservationStatus((await Reservation.get(id=late.id)).status)
        is ReservationStatus.PENDING
    )


async def test_owner_scoped_detail_and_cancel_hide_another_customers_reservation() -> None:
    owner = await create_user("owner", phone="13800138000")
    stranger = await create_user("stranger", phone="13900139001")
    product, option = await create_option("owner")
    reservation = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        business_date=date(2026, 9, 9),
    )
    service = make_service()

    with pytest.raises(ReservationNotFound) as detail_error:
        await service.get_user_reservation_detail(
            reservation.id,
            user_id=stranger.id,
        )
    with pytest.raises(ReservationNotFound) as cancel_error:
        await service.cancel_reservation(
            reservation.id,
            user_id=stranger.id,
            ip_address="127.0.0.1",
        )

    assert detail_error.value.code == cancel_error.value.code == 40451
    assert (
        ReservationStatus((await Reservation.get(id=reservation.id)).status)
        is ReservationStatus.PENDING
    )
    assert not await AuditLog.filter(target_id=reservation.id).exists()


async def test_admin_transition_rejects_terminal_status_and_exact_start_time() -> None:
    owner = await create_user("expired-owner")
    admin = await create_user("expired-admin", phone="13900139001")
    product, option = await create_option("expired")
    terminal = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        business_date=date(2026, 9, 9),
        status=ReservationStatus.REJECTED,
        rejection_reason=ReservationRejectionReason.NO_CAPACITY,
        rejected_at=FROZEN_NOW,
    )
    begins_now = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(11, 0),
    )

    with pytest.raises(ReservationStatusConflict) as conflict:
        await make_service().confirm_reservation(
            terminal.id,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )
    with pytest.raises(ReservationOperationExpired):
        await make_service(now=begins_now.scheduled_start_at).reject_reservation(
            begins_now.id,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )

    assert conflict.value.data == {
        "operation": "confirm",
        "current_status": "rejected",
        "allowed_statuses": ["pending"],
    }
    assert not await AuditLog.filter(target_id__in=[terminal.id, begins_now.id]).exists()


async def test_store_closure_is_selective_idempotent_and_reopen_does_not_revive() -> None:
    now = datetime(2026, 9, 8, 7, 0, tzinfo=timezone.utc)  # 15:00 Shanghai.
    owner = await create_user("closure-owner")
    admin = await create_user("closure-admin", phone="13900139001")
    product, option = await create_option("closure")
    pending = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(18, 0),
    )
    confirmed = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(19, 0),
        status=ReservationStatus.CONFIRMED,
        confirmed_at=now - timedelta(hours=1),
    )
    started = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(14, 0),
    )
    starts_exactly_now = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(15, 0),
    )
    rejected = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(18, 30),
        status=ReservationStatus.REJECTED,
        rejection_reason=ReservationRejectionReason.NO_CAPACITY,
        rejected_at=now - timedelta(minutes=5),
    )
    already_cancelled = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(17, 30),
        status=ReservationStatus.CANCELLED,
        cancellation_reason=ReservationCancellationReason.CUSTOMER_REQUEST,
        cancelled_at=now - timedelta(minutes=10),
    )
    other_day = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        business_date=date(2026, 9, 9),
        local_start=time(11, 0),
    )
    service = make_service(now=now)

    first = await service.close_store_day(
        FROZEN_LOCAL_DATE,
        operator_id=admin.id,
        ip_address="198.51.100.9",
    )

    assert first.newly_cancelled_count == 2
    assert first.cancelled_pending_count == 1
    assert first.cancelled_confirmed_count == 1
    assert first.is_replay is False
    assert first.business_day.is_closed is True
    for expected in (pending, confirmed):
        stored = await Reservation.get(id=expected.id)
        assert ReservationStatus(stored.status) is ReservationStatus.CANCELLED
        assert stored.cancellation_reason == ReservationCancellationReason.STORE_CLOSED
        assert stored.cancelled_at == now
        payload = map_reservation(stored).model_dump(mode="json")
        assert payload["customer_message"] == RESERVATION_CUSTOMER_MESSAGES[
            ReservationCancellationReason.STORE_CLOSED
        ]
        assert "门店当天休息" in payload["customer_message"]

    expected_unchanged = {
        started.id: ReservationStatus.PENDING,
        starts_exactly_now.id: ReservationStatus.PENDING,
        rejected.id: ReservationStatus.REJECTED,
        already_cancelled.id: ReservationStatus.CANCELLED,
        other_day.id: ReservationStatus.PENDING,
    }
    for reservation_id, expected_status in expected_unchanged.items():
        stored = await Reservation.get(id=reservation_id)
        assert ReservationStatus(stored.status) is expected_status
    assert (
        await Reservation.get(id=rejected.id)
    ).rejection_reason == ReservationRejectionReason.NO_CAPACITY
    assert (
        await Reservation.get(id=already_cancelled.id)
    ).cancellation_reason == ReservationCancellationReason.CUSTOMER_REQUEST

    audit_count_after_first = await AuditLog.all().count()
    assert audit_count_after_first == 3
    assert await AuditLog.filter(
        action="CANCEL_RESERVATION",
        target_type="reservation",
        target_id__in=[pending.id, confirmed.id],
        description="reason=store_closed",
    ).count() == 2
    assert await AuditLog.filter(
        action="CLOSE_STORE_BUSINESS_DAY",
        target_type="store_business_day",
        target_id=first.business_day.id,
        description="cancelled_count=2",
    ).count() == 1

    replay = await service.close_store_day(
        FROZEN_LOCAL_DATE,
        operator_id=admin.id,
        ip_address="198.51.100.9",
    )
    assert replay.is_replay is True
    assert replay.newly_cancelled_count == 0
    assert await AuditLog.all().count() == audit_count_after_first

    reopened = await service.reopen_store_day(
        FROZEN_LOCAL_DATE,
        operator_id=admin.id,
        ip_address="198.51.100.9",
    )
    assert reopened.business_day.is_closed is False
    assert reopened.newly_cancelled_count == 0
    assert reopened.is_replay is False
    assert (
        ReservationStatus((await Reservation.get(id=pending.id)).status)
        is ReservationStatus.CANCELLED
    )
    assert (
        ReservationStatus((await Reservation.get(id=confirmed.id)).status)
        is ReservationStatus.CANCELLED
    )
    assert await AuditLog.filter(action="REOPEN_STORE_BUSINESS_DAY").count() == 1


class _FailAfterBatchAudit(AuditLogService):
    async def log_many(
        self,
        entries: list[AuditLogCreateData],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        await super().log_many(entries, using_db=using_db)
        raise RuntimeError("fail after closure audit")


async def test_store_closure_failure_rolls_back_day_reservations_and_audits() -> None:
    now = datetime(2026, 9, 8, 7, 0, tzinfo=timezone.utc)
    owner = await create_user("closure-rollback-owner")
    admin = await create_user("closure-rollback-admin", phone="13900139001")
    product, option = await create_option("closure-rollback")
    reservation = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        local_start=time(18, 0),
    )
    service = ReservationService(
        ReservationRepository(),
        ProductRepository(),
        UserRepository(),
        _FailAfterBatchAudit(AuditLogRepository()),
        now_provider=lambda: now,
    )

    with pytest.raises(RuntimeError, match="fail after closure audit"):
        await service.close_store_day(
            FROZEN_LOCAL_DATE,
            operator_id=admin.id,
            ip_address="127.0.0.1",
        )

    day = await StoreBusinessDay.get(business_date=FROZEN_LOCAL_DATE)
    stored = await Reservation.get(id=reservation.id)
    assert day.is_closed is False
    assert ReservationStatus(stored.status) is ReservationStatus.PENDING
    assert stored.cancellation_reason is None
    assert stored.cancelled_at is None
    assert not await AuditLog.all().exists()


async def test_admin_list_masks_phone_detail_is_full_and_customer_gets_neither() -> None:
    owner = await create_user("privacy", phone="13800138000")
    product, option = await create_option("privacy")
    reservation = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        business_date=date(2026, 9, 9),
    )
    owner.phone = "13912345678"
    await owner.save(update_fields=["phone", "updated_at"])
    service = make_service()

    page = await service.list_admin_reservations(
        page=1,
        page_size=20,
        status=None,
        business_date=None,
        user_id=None,
        product_id=None,
    )
    detail = await service.get_admin_reservation_detail(reservation.id)
    list_payload = map_admin_reservation_page(page).model_dump(mode="json")["items"][0]
    detail_payload = map_admin_reservation_detail(detail).model_dump(mode="json")
    customer_payload = map_reservation(detail).model_dump(mode="json")

    assert list_payload["user_phone_masked"] == "139****5678"
    assert "user_phone" not in list_payload
    assert detail_payload["user_phone"] == "13912345678"
    assert "user_phone_masked" not in detail_payload
    assert not (
        {"user_id", "user_nickname", "user_phone", "user_phone_masked"}
        & customer_payload.keys()
    )
    assert not hasattr(reservation, "phone")


class _UnusedProvider:
    async def exchange_code(self, code: str) -> None:
        raise AssertionError("password deletion must not call WeChat")


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz: timezone | None = None) -> datetime:
        value = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
        return value if tz is not None else value.replace(tzinfo=None)


async def test_active_future_pending_reservation_blocks_account_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(account_lifecycle_module, "datetime", _FrozenDateTime)
    owner = await create_user(
        "deletion",
        password=hash_password("12345678"),
    )
    product, option = await create_option("deletion")
    reservation = await create_reservation_record(
        user=owner,
        product=product,
        option=option,
        business_date=date(2026, 9, 9),
        local_start=time(11, 0),
    )
    service = AccountLifecycleService(
        UserRepository(),
        OrderRepository(),
        ExternalIdentityRepository(),
        AuditLogService(AuditLogRepository()),
        _UnusedProvider(),
        wallet_repository=WalletRepository(),
        payment_repository=PaymentRepository(),
        reservation_repository=ReservationRepository(),
    )

    with pytest.raises(AccountDeletionBlocked):
        await service.delete_account(
            user=owner,
            data=AccountDeletionRequest(
                confirmation="DELETE",
                password="12345678",
            ),
            ip_address="127.0.0.1",
        )

    await owner.refresh_from_db()
    assert UserStatus(owner.status) is UserStatus.NORMAL
    assert (
        ReservationStatus((await Reservation.get(id=reservation.id)).status)
        is ReservationStatus.PENDING
    )
    assert not await AuditLog.filter(action="DELETE_ACCOUNT").exists()
