"""桌台二维码开台的用户/管理响应白名单映射。"""

from datetime import datetime, timezone
from decimal import Decimal

from app.common.constants.table_session import TABLE_TIMER_BUFFER_MINUTES
from app.common.enums.table_session import AdminTableState, TableSessionStatus
from app.common.pagination import Page
from app.domain.table_session import timer_ended_at, timer_phase
from app.models.order import Order, OrderItem
from app.models.table_session import StoreTable, TableSession, TableSessionTimer
from app.schemas.table_session_response import (
    AdminTableListOut,
    AdminTableOut,
    AdminTableSessionListItemOut,
    AdminTableSessionOut,
    EligibleDurationGroupOut,
    EligibleOrderListItemOut,
    PublicTableCodeOut,
    TableSessionOut,
    TableSessionTimerOut,
    TableSummaryOut,
    TimerExperienceItemOut,
    enum_out,
)


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def map_table_summary(table: StoreTable) -> TableSummaryOut:
    return TableSummaryOut(
        id=table.id,
        table_no=table.table_no,
        display_name=table.display_name,
        is_enabled=table.is_enabled,
    )


def map_public_table_code(
    table: StoreTable,
    *,
    is_available: bool,
) -> PublicTableCodeOut:
    return PublicTableCodeOut(
        table_no=table.table_no,
        display_name=table.display_name,
        is_enabled=table.is_enabled,
        is_available=is_available,
    )


def map_eligible_order(order: Order) -> EligibleOrderListItemOut:
    grouped: dict[int, list[OrderItem]] = {}
    experience_count = 0
    kit_count = 0
    for item in list(order.items):
        if item.experience_option_id is None:
            kit_count += 1
            continue
        experience_count += 1
        duration = item.option_duration_minutes
        if duration is None:
            continue
        grouped.setdefault(duration, []).append(item)
    return EligibleOrderListItemOut(
        id=order.id,
        order_no=order.order_no,
        total_amount=Decimal(order.total_amount),
        created_at=order.created_at,
        experience_item_count=experience_count,
        kit_item_count=kit_count,
        duration_groups=[
            EligibleDurationGroupOut(
                duration_minutes=duration,
                buffer_minutes=TABLE_TIMER_BUFFER_MINUTES,
                experience_item_count=len(items),
                total_quantity=sum(item.quantity for item in items),
            )
            for duration, items in sorted(grouped.items())
        ],
    )


def map_eligible_order_page(page: Page[Order]) -> Page[EligibleOrderListItemOut]:
    return Page[EligibleOrderListItemOut](
        items=[map_eligible_order(order) for order in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def _experience_items_for_timer(
    session: TableSession,
    timer: TableSessionTimer,
) -> list[TimerExperienceItemOut]:
    mapped: list[TimerExperienceItemOut] = []
    for item in list(session.order.items):
        if (
            item.experience_option_id is None
            or item.option_duration_minutes != timer.duration_minutes
        ):
            continue
        participants = item.option_participants
        mapped.append(
            TimerExperienceItemOut(
                order_item_id=item.id,
                product_id=item.product_id,
                product_name=item.product_name,
                quantity=item.quantity,
                participants_per_unit=participants,
                total_participants=(
                    item.quantity * participants if participants is not None else None
                ),
            )
        )
    return mapped


def _map_timer(
    session: TableSession,
    timer: TableSessionTimer,
    *,
    server_now: datetime,
) -> TableSessionTimerOut:
    status = TableSessionStatus(session.status)
    phase = timer_phase(
        status=status,
        now=server_now,
        service_ends_at=timer.service_ends_at,
        grace_ends_at=timer.grace_ends_at,
    )
    return TableSessionTimerOut(
        id=timer.id,
        duration_minutes=timer.duration_minutes,
        buffer_minutes=timer.buffer_minutes,
        started_at=timer.started_at,
        service_ends_at=timer.service_ends_at,
        grace_ends_at=timer.grace_ends_at,
        phase=enum_out(phase),
        ended_at=timer_ended_at(
            status=status,
            now=server_now,
            grace_ends_at=timer.grace_ends_at,
            closed_at=session.closed_at,
        ),
        experience_items=_experience_items_for_timer(session, timer),
    )


def map_table_session(
    session: TableSession,
    *,
    server_now: datetime | None = None,
) -> TableSessionOut:
    captured_now = _now(server_now)
    status = TableSessionStatus(session.status)
    close_reason = session.close_reason
    return TableSessionOut(
        session_no=session.session_no,
        table=map_table_summary(session.table),
        order_id=session.order_id,
        order_no=session.order.order_no,
        status=enum_out(status),
        claimed_at=session.claimed_at,
        payment_deadline_at=session.payment_deadline_at,
        started_at=session.started_at,
        table_release_at=session.table_release_at,
        closed_at=session.closed_at,
        close_reason=enum_out(close_reason) if close_reason is not None else None,
        timers=[
            _map_timer(session, timer, server_now=captured_now)
            for timer in sorted(
                list(session.timers),
                key=lambda value: (value.duration_minutes, value.id),
            )
        ],
        server_now=captured_now,
    )


def map_admin_table_session(
    session: TableSession,
    *,
    server_now: datetime | None = None,
) -> AdminTableSessionOut:
    public = map_table_session(session, server_now=server_now)
    return AdminTableSessionOut(
        **public.model_dump(),
        user_id=session.user_id,
        user_nickname=session.user.nickname,
        payment_id=session.payment_id,
        closed_by_user_id=session.closed_by_user_id,
        admin_close_reason=session.admin_close_reason,
    )


def map_admin_table_session_list_item(
    session: TableSession,
) -> AdminTableSessionListItemOut:
    status = TableSessionStatus(session.status)
    return AdminTableSessionListItemOut(
        session_no=session.session_no,
        table=map_table_summary(session.table),
        order_id=session.order_id,
        order_no=session.order.order_no,
        user_id=session.user_id,
        user_nickname=session.user.nickname,
        status=enum_out(status),
        close_reason=(
            enum_out(session.close_reason) if session.close_reason is not None else None
        ),
        timer_count=session.timer_count,
        minimum_duration_minutes=session.minimum_duration_minutes,
        maximum_duration_minutes=session.maximum_duration_minutes,
        claimed_at=session.claimed_at,
        payment_deadline_at=session.payment_deadline_at,
        started_at=session.started_at,
        table_release_at=session.table_release_at,
        closed_at=session.closed_at,
    )


def map_admin_table_session_page(
    page: Page[TableSession],
) -> Page[AdminTableSessionListItemOut]:
    return Page[AdminTableSessionListItemOut](
        items=[map_admin_table_session_list_item(item) for item in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def map_admin_table_list(
    tables: list[StoreTable],
    *,
    server_now: datetime | None = None,
) -> AdminTableListOut:
    captured_now = _now(server_now)
    items: list[AdminTableOut] = []
    for table in tables:
        occupancies = list(table.occupancy)
        occupancy = occupancies[0] if occupancies else None
        session = occupancy.session if occupancy is not None else None
        if not table.is_enabled:
            state = AdminTableState.DISABLED
        elif session is None:
            state = AdminTableState.AVAILABLE
        else:
            state = AdminTableState(TableSessionStatus(session.status).value)
        items.append(
            AdminTableOut(
                **map_table_summary(table).model_dump(),
                state=state,
                current_session_no=session.session_no if session is not None else None,
                current_status=(
                    enum_out(TableSessionStatus(session.status))
                    if session is not None
                    else None
                ),
                current_order_no=(
                    session.order.order_no if session is not None else None
                ),
                current_user_id=session.user_id if session is not None else None,
                claimed_at=session.claimed_at if session is not None else None,
                payment_deadline_at=(
                    session.payment_deadline_at if session is not None else None
                ),
                table_release_at=(
                    session.table_release_at if session is not None else None
                ),
            )
        )
    return AdminTableListOut(items=items, server_now=captured_now)
