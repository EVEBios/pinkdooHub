"""管理列表按服务端时间筛选，过期不伪造业务转态。"""

from datetime import date, time

import pytest
from pydantic import ValidationError

from app.common.enums.reservation import ReservationReviewTiming, ReservationStatus
from app.models.reservation import Reservation
from app.schemas.reservation import AdminReservationListQuery
from tests.reservation.support import create_option, create_reservation_record, make_service
from tests.reservation.test_attention import setup_reservation


async def test_pending_review_timing_filters_before_pagination_at_exact_start():
    customer, _, expired = await setup_reservation()
    product, option = await create_option("later")
    upcoming = await create_reservation_record(
        user=customer, product=product, option=option,
        business_date=date(2026, 9, 9), local_start=time(12),
    )
    service = make_service(now=expired.scheduled_start_at)
    for timing, expected in [
        (ReservationReviewTiming.ACTIONABLE, upcoming.id),
        (ReservationReviewTiming.OVERDUE, expired.id),
    ]:
        page = await service.list_admin_reservations(
            page=1, page_size=1, status=ReservationStatus.PENDING,
            review_timing=timing, user_id=customer.id,
        )
        assert page.total == page.pages == 1
        assert [item.id for item in page.items] == [expected]
    legacy = await service.list_admin_reservations(page=1, page_size=20, status=ReservationStatus.PENDING)
    assert legacy.total == 2
    assert (await Reservation.get(id=expired.id)).status is ReservationStatus.PENDING


@pytest.mark.parametrize("status", [None, "confirmed", "cancelled", "rejected"])
def test_review_timing_requires_pending_status(status):
    with pytest.raises(ValidationError, match="requires status=pending"):
        AdminReservationListQuery(status=status, review_timing="overdue")
