"""Reservation 请求体与查询 Schema。"""

import re
from datetime import date
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from app.common.constants.product import PRODUCT_NAME_MAX_LENGTH
from app.common.constants.reservation import RESERVATION_LOCAL_TIME_PATTERN
from app.common.enums.reservation import ReservationStatus, ReservationWeekday
from app.common.pagination import PageParams


def _parse_positive_query_id(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Query ID must be a positive integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isascii() and normalized.isdecimal():
            return int(normalized)
    raise ValueError("Query ID must be a positive integer")


def _parse_iso_date(value: object) -> date:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError("Date must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Date must be a valid calendar date") from exc


PositiveReservationResourceId = Annotated[int, Field(strict=True, gt=0)]
PositiveReservationQueryId = Annotated[
    int,
    BeforeValidator(_parse_positive_query_id),
    Field(gt=0),
]
ReservationBusinessDate = Annotated[date, BeforeValidator(_parse_iso_date)]
ReservationLocalTime = Annotated[
    str,
    Field(strict=True, pattern=RESERVATION_LOCAL_TIME_PATTERN),
]
ReservationProductNameQuery = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=PRODUCT_NAME_MAX_LENGTH),
]


class _ReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReservationCreate(_ReservationRequest):
    """创建独立体验预约；其余快照均由服务端生成。"""

    experience_option_id: PositiveReservationResourceId
    reservation_date: ReservationBusinessDate
    start_time: ReservationLocalTime


class WeeklyClosureUpdateRequest(_ReservationRequest):
    """更换全店每周固定店休日。"""

    weekly_closed_weekday: ReservationWeekday


class ReservationBookingOptionsQuery(_ReservationRequest):
    """查询一个 ExperienceOption 当前可选的本地日期和时段。"""

    experience_option_id: PositiveReservationQueryId


class ReservationListQuery(PageParams):
    """用户端预约分页查询。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: ReservationStatus | None = None


class AdminReservationListQuery(ReservationListQuery):
    """管理端预约分页与组合筛选。"""

    business_date: ReservationBusinessDate | None = None
    user_id: PositiveReservationQueryId | None = None
    product_id: PositiveReservationQueryId | None = None


class StoreClosureListQuery(PageParams):
    """管理端营业日状态分页查询。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date_from: ReservationBusinessDate | None = None
    date_to: ReservationBusinessDate | None = None
    is_closed: bool | None = True

    @model_validator(mode="after")
    def validate_date_range(self) -> "StoreClosureListQuery":
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("date_to must not be earlier than date_from")
        return self
