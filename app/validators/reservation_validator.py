"""Reservation 纯业务校验器。"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.common.constants.reservation import (
    DEFAULT_RESERVATION_WEEKLY_CLOSED_WEEKDAY,
    RESERVATION_BOOKING_WINDOW_DAYS,
    RESERVATION_CLOSE_TIME,
    RESERVATION_MINIMUM_LEAD_HOURS,
    RESERVATION_OPEN_TIME,
    RESERVATION_SLOT_INTERVAL_MINUTES,
    RESERVATION_TIMEZONE,
    RESERVATION_WEEKDAY_NUMBERS,
)
from app.common.enums.product import DayType
from app.common.enums.reservation import (
    ReservationScheduleUnavailableReason,
    ReservationWeekday,
)
from app.common.exceptions.reservation import ReservationScheduleUnavailable

STORE_TIMEZONE = ZoneInfo(RESERVATION_TIMEZONE)


class ReservationValidator:
    """只判断预约时间规则，不查询或写入数据库。"""

    @staticmethod
    def day_type_for_date(business_date: date) -> DayType:
        """将上海营业日映射到当前 MVP 的工作日/节假日规则。"""

        return (
            DayType.HOLIDAY
            if business_date.weekday() >= 5
            else DayType.WEEKDAY
        )

    @staticmethod
    def build_scheduled_start(
        *,
        business_date: date,
        start_time: time,
    ) -> datetime:
        """把上海当地营业日期与时间转换为 UTC aware datetime。"""

        local_start = datetime.combine(
            business_date,
            start_time,
            tzinfo=STORE_TIMEZONE,
        )
        return local_start.astimezone(timezone.utc)

    def validate_schedule(
        self,
        *,
        business_date: date,
        start_time: time,
        duration_minutes: int,
        option_day_type: DayType,
        now_utc: datetime,
        is_store_closed: bool,
        weekly_closed_weekday: ReservationWeekday = (
            DEFAULT_RESERVATION_WEEKLY_CLOSED_WEEKDAY
        ),
    ) -> tuple[datetime, datetime]:
        """校验完整预约窗口并返回 UTC 起止时间。"""

        local_now = now_utc.astimezone(STORE_TIMEZONE)
        last_date = local_now.date() + timedelta(
            days=RESERVATION_BOOKING_WINDOW_DAYS
        )
        if business_date < local_now.date() or business_date > last_date:
            self._raise(
                ReservationScheduleUnavailableReason.OUTSIDE_BOOKING_WINDOW
            )

        if business_date.weekday() == RESERVATION_WEEKDAY_NUMBERS[weekly_closed_weekday]:
            self._raise(ReservationScheduleUnavailableReason.WEEKLY_CLOSED)

        if (
            start_time.second != 0
            or start_time.microsecond != 0
            or start_time.minute % RESERVATION_SLOT_INTERVAL_MINUTES != 0
        ):
            self._raise(
                ReservationScheduleUnavailableReason.INVALID_SLOT_INCREMENT
            )

        local_start = datetime.combine(
            business_date,
            start_time,
            tzinfo=STORE_TIMEZONE,
        )
        local_end = local_start + timedelta(minutes=duration_minutes)
        local_open = datetime.combine(
            business_date,
            RESERVATION_OPEN_TIME,
            tzinfo=STORE_TIMEZONE,
        )
        local_close = datetime.combine(
            business_date,
            RESERVATION_CLOSE_TIME,
            tzinfo=STORE_TIMEZONE,
        )
        if (
            local_start < local_open
            or local_end > local_close
            or local_end.date() != business_date
        ):
            self._raise(
                ReservationScheduleUnavailableReason.OUTSIDE_BUSINESS_HOURS
            )

        expected_day_type = self.day_type_for_date(business_date)
        if option_day_type != expected_day_type:
            self._raise(
                ReservationScheduleUnavailableReason.OPTION_DAY_TYPE_MISMATCH
            )

        scheduled_start_at = local_start.astimezone(timezone.utc)
        if scheduled_start_at < now_utc + timedelta(
            hours=RESERVATION_MINIMUM_LEAD_HOURS
        ):
            self._raise(
                ReservationScheduleUnavailableReason.MINIMUM_LEAD_TIME
            )

        if is_store_closed:
            self._raise(ReservationScheduleUnavailableReason.STORE_CLOSED)

        return scheduled_start_at, local_end.astimezone(timezone.utc)

    def list_available_start_times(
        self,
        *,
        business_date: date,
        duration_minutes: int,
        option_day_type: DayType,
        now_utc: datetime,
        is_store_closed: bool,
        weekly_closed_weekday: ReservationWeekday = (
            DEFAULT_RESERVATION_WEEKLY_CLOSED_WEEKDAY
        ),
    ) -> tuple[str, ...]:
        """生成指定日期当前仍合法的半小时时段。"""

        values: list[str] = []
        local_start = datetime.combine(
            business_date,
            RESERVATION_OPEN_TIME,
            tzinfo=STORE_TIMEZONE,
        )
        local_close = datetime.combine(
            business_date,
            RESERVATION_CLOSE_TIME,
            tzinfo=STORE_TIMEZONE,
        )
        while local_start + timedelta(minutes=duration_minutes) <= local_close:
            try:
                self.validate_schedule(
                    business_date=business_date,
                    start_time=local_start.time(),
                    duration_minutes=duration_minutes,
                    option_day_type=option_day_type,
                    now_utc=now_utc,
                    is_store_closed=is_store_closed,
                    weekly_closed_weekday=weekly_closed_weekday,
                )
            except ReservationScheduleUnavailable:
                pass
            else:
                values.append(local_start.strftime("%H:%M"))
            local_start += timedelta(minutes=RESERVATION_SLOT_INTERVAL_MINUTES)
        return tuple(values)

    @staticmethod
    def _raise(reason: ReservationScheduleUnavailableReason) -> None:
        raise ReservationScheduleUnavailable(reason=reason)
