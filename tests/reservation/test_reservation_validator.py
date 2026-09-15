"""ReservationValidator 的上海营业日历与边界测试。"""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.common.enums.product import DayType
from app.common.enums.reservation import ReservationScheduleUnavailableReason
from app.common.exceptions.reservation import ReservationScheduleUnavailable
from app.validators.reservation_validator import ReservationValidator

NOW = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)  # Tuesday 08:00 Shanghai.
TUESDAY = date(2026, 9, 8)


def _assert_unavailable(
    *,
    reason: ReservationScheduleUnavailableReason,
    business_date: date = TUESDAY,
    start_time: time = time(11, 0),
    duration_minutes: int = 60,
    option_day_type: DayType = DayType.WEEKDAY,
    now_utc: datetime = NOW,
    is_store_closed: bool = False,
) -> None:
    with pytest.raises(ReservationScheduleUnavailable) as caught:
        ReservationValidator().validate_schedule(
            business_date=business_date,
            start_time=start_time,
            duration_minutes=duration_minutes,
            option_day_type=option_day_type,
            now_utc=now_utc,
            is_store_closed=is_store_closed,
        )

    assert caught.value.code == 42253
    assert caught.value.data == {"reason": reason.value}


@pytest.mark.parametrize(
    ("business_date", "expected"),
    [
        (date(2026, 9, 8), DayType.WEEKDAY),
        (date(2026, 9, 9), DayType.WEEKDAY),
        (date(2026, 9, 10), DayType.WEEKDAY),
        (date(2026, 9, 11), DayType.WEEKDAY),
        (date(2026, 9, 12), DayType.HOLIDAY),
        (date(2026, 9, 13), DayType.HOLIDAY),
    ],
)
def test_day_type_uses_tuesday_to_friday_and_weekend_contract(
    business_date: date,
    expected: DayType,
) -> None:
    assert ReservationValidator.day_type_for_date(business_date) is expected


def test_build_scheduled_start_interprets_local_time_as_shanghai_and_returns_utc() -> None:
    assert ReservationValidator.build_scheduled_start(
        business_date=TUESDAY,
        start_time=time(11, 0),
    ) == datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc)


def test_exact_three_hour_lead_opening_and_closing_boundaries_are_allowed() -> None:
    validator = ReservationValidator()

    start, end = validator.validate_schedule(
        business_date=TUESDAY,
        start_time=time(11, 0),
        duration_minutes=540,
        option_day_type=DayType.WEEKDAY,
        now_utc=NOW,
        is_store_closed=False,
    )

    assert start == NOW + timedelta(hours=3)
    assert end == datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def test_thirty_day_booking_window_last_date_is_inclusive() -> None:
    start, _ = ReservationValidator().validate_schedule(
        business_date=TUESDAY + timedelta(days=30),
        start_time=time(11, 0),
        duration_minutes=60,
        option_day_type=DayType.WEEKDAY,
        now_utc=NOW,
        is_store_closed=False,
    )

    assert start.date() == date(2026, 10, 8)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        (
            {"business_date": date(2026, 9, 7)},
            ReservationScheduleUnavailableReason.OUTSIDE_BOOKING_WINDOW,
        ),
        (
            {"business_date": TUESDAY + timedelta(days=31)},
            ReservationScheduleUnavailableReason.OUTSIDE_BOOKING_WINDOW,
        ),
        (
            {"business_date": date(2026, 9, 14)},
            ReservationScheduleUnavailableReason.WEEKLY_CLOSED,
        ),
        (
            {"start_time": time(11, 15)},
            ReservationScheduleUnavailableReason.INVALID_SLOT_INCREMENT,
        ),
        (
            {"start_time": time(11, 0, 1)},
            ReservationScheduleUnavailableReason.INVALID_SLOT_INCREMENT,
        ),
        (
            {"start_time": time(11, 0, 0, 1)},
            ReservationScheduleUnavailableReason.INVALID_SLOT_INCREMENT,
        ),
        (
            {"start_time": time(10, 30)},
            ReservationScheduleUnavailableReason.OUTSIDE_BUSINESS_HOURS,
        ),
        (
            {"start_time": time(19, 30), "duration_minutes": 31},
            ReservationScheduleUnavailableReason.OUTSIDE_BUSINESS_HOURS,
        ),
        (
            {"option_day_type": DayType.HOLIDAY},
            ReservationScheduleUnavailableReason.OPTION_DAY_TYPE_MISMATCH,
        ),
        (
            {"is_store_closed": True},
            ReservationScheduleUnavailableReason.STORE_CLOSED,
        ),
    ],
)
def test_each_calendar_and_business_hours_failure_has_stable_reason(
    kwargs: dict[str, object],
    reason: ReservationScheduleUnavailableReason,
) -> None:
    _assert_unavailable(reason=reason, **kwargs)


def test_one_microsecond_less_than_three_hours_is_rejected() -> None:
    _assert_unavailable(
        reason=ReservationScheduleUnavailableReason.MINIMUM_LEAD_TIME,
        now_utc=NOW + timedelta(microseconds=1),
    )


def test_weekly_closed_takes_precedence_over_day_type_and_store_closure() -> None:
    _assert_unavailable(
        reason=ReservationScheduleUnavailableReason.WEEKLY_CLOSED,
        business_date=date(2026, 9, 14),
        option_day_type=DayType.HOLIDAY,
        is_store_closed=True,
    )


def test_available_start_times_respect_lead_interval_and_complete_end() -> None:
    values = ReservationValidator().list_available_start_times(
        business_date=TUESDAY,
        duration_minutes=60,
        option_day_type=DayType.WEEKDAY,
        now_utc=NOW,
        is_store_closed=False,
    )

    assert values[0] == "11:00"
    assert values[-1] == "19:00"
    assert len(values) == 17
    assert all(int(value[-2:]) in (0, 30) for value in values)


def test_full_day_only_has_opening_slot_and_closed_dates_have_none() -> None:
    validator = ReservationValidator()

    assert validator.list_available_start_times(
        business_date=TUESDAY,
        duration_minutes=540,
        option_day_type=DayType.WEEKDAY,
        now_utc=NOW,
        is_store_closed=False,
    ) == ("11:00",)
    assert validator.list_available_start_times(
        business_date=TUESDAY,
        duration_minutes=60,
        option_day_type=DayType.WEEKDAY,
        now_utc=NOW,
        is_store_closed=True,
    ) == ()
    assert validator.list_available_start_times(
        business_date=date(2026, 9, 14),
        duration_minutes=60,
        option_day_type=DayType.WEEKDAY,
        now_utc=NOW,
        is_store_closed=False,
    ) == ()


def test_available_start_times_drop_slots_inside_three_hour_lead_window() -> None:
    # 15:30 Shanghai: earliest legal start is 18:30, while a 60-minute
    # experience must begin no later than 19:00.
    now = datetime(2026, 9, 8, 7, 30, tzinfo=timezone.utc)

    assert ReservationValidator().list_available_start_times(
        business_date=TUESDAY,
        duration_minutes=60,
        option_day_type=DayType.WEEKDAY,
        now_utc=now,
        is_store_closed=False,
    ) == ("18:30", "19:00")
