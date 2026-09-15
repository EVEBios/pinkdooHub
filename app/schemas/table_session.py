"""桌台二维码开台请求、Header 与列表查询 Schema。"""

import re
from datetime import datetime, timedelta
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.common.constants.table_session import (
    TABLE_ADMIN_REASON_MAX_LENGTH,
    TABLE_IDEMPOTENCY_KEY_MAX_LENGTH,
    TABLE_QR_TOKEN_PATTERN,
    TABLE_SESSION_NO_PATTERN,
)
from app.common.enums.table_session import TableSessionCloseReason, TableSessionStatus
from app.common.pagination import PageParams


def _strip_ascii(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Value must be a string")
    return value.strip()


def _parse_positive_query_id(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Query ID must be a positive integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        return int(value.strip())
    raise ValueError("Query ID must be a positive integer")


TableQrToken = Annotated[
    str,
    Field(strict=True, pattern=TABLE_QR_TOKEN_PATTERN),
]
TableSessionNumber = Annotated[
    str,
    Field(strict=True, pattern=TABLE_SESSION_NO_PATTERN),
]
TableIdempotencyKey = Annotated[
    str,
    BeforeValidator(_strip_ascii),
    Field(
        strict=True,
        min_length=1,
        max_length=TABLE_IDEMPOTENCY_KEY_MAX_LENGTH,
        pattern=r"^[\x20-\x7E]+$",
    ),
]
TableAdminReason = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=TABLE_ADMIN_REASON_MAX_LENGTH),
]
PositiveTableQueryId = Annotated[
    int,
    BeforeValidator(_parse_positive_query_id),
    Field(gt=0),
]


class _TableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TableSessionCreate(_TableRequest):
    qr_token: TableQrToken
    order_id: int = Field(strict=True, gt=0)


class AdminTableUpdate(_TableRequest):
    is_enabled: bool = Field(strict=True)
    reason: TableAdminReason


class AdminTableSessionRelease(_TableRequest):
    reason: TableAdminReason


class EligibleOrderListQuery(PageParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AdminTableSessionListQuery(PageParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    table_id: PositiveTableQueryId | None = None
    user_id: PositiveTableQueryId | None = None
    order_id: PositiveTableQueryId | None = None
    status: TableSessionStatus | None = None
    close_reason: TableSessionCloseReason | None = None
    claimed_from: AwareDatetime | None = None
    claimed_to: AwareDatetime | None = None

    @field_validator("claimed_from", "claimed_to", mode="after")
    @classmethod
    def require_utc_datetime(
        cls,
        value: AwareDatetime | None,
    ) -> datetime | None:
        if value is not None and value.utcoffset() != timedelta(0):
            raise ValueError("Datetime must use UTC timezone")
        return value

    @model_validator(mode="after")
    def validate_claimed_range(self) -> "AdminTableSessionListQuery":
        if (
            self.claimed_from is not None
            and self.claimed_to is not None
            and self.claimed_to < self.claimed_from
        ):
            raise ValueError("claimed_to must not be earlier than claimed_from")
        return self


def validate_table_no(value: str) -> str:
    if re.fullmatch(r"T(?:0[1-9]|[12][0-9]|30)", value) is None:
        raise ValueError("invalid table number")
    return value
