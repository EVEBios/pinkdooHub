"""首页提醒及精确事件阅读协议。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.common.constants.attention import ATTENTION_READ_BATCH_LIMIT
from app.common.enums.attention import AttentionEventType, ReservationAttentionView
from app.common.pagination import PageParams
from app.schemas.wallet_response import MoneyOut, WalletBalanceOut


class AttentionSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_now: datetime
    reservation_actionable: int = Field(ge=0, strict=True)
    reservation_unread: int = Field(ge=0, strict=True)
    reservation_overdue: int = Field(ge=0, strict=True)
    reservation_total: int = Field(ge=0, strict=True)
    order_pending: int = Field(ge=0, strict=True)
    order_fulfillment: int = Field(ge=0, strict=True)
    order_unread: int = Field(ge=0, strict=True)
    order_total: int = Field(ge=0, strict=True)
    table_pending: int = Field(ge=0, strict=True)
    table_unread: int = Field(ge=0, strict=True)
    table_total: int = Field(ge=0, strict=True)
    wallet_unread: int = Field(default=0, ge=0, strict=True)


class AttentionEventOut(BaseModel):
    id: int = Field(gt=0, strict=True)
    event_type: AttentionEventType
    label: str
    occurred_at: datetime


class ReservationAttentionSnapshotOut(BaseModel):
    reservation_id: int = Field(gt=0, strict=True)
    reservation_updated_at: datetime
    server_now: datetime
    events: list[AttentionEventOut]


class AttentionReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(min_length=1, max_length=ATTENTION_READ_BATCH_LIMIT)

    @model_validator(mode="after")
    def unique_events(self) -> "AttentionReadRequest":
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("Event IDs must be unique")
        return self


class CustomerAttentionQuery(PageParams):
    model_config = ConfigDict(extra="forbid")
    view: Literal["unread"] = "unread"


class AdminAttentionQuery(PageParams):
    model_config = ConfigDict(extra="forbid")
    view: ReservationAttentionView = ReservationAttentionView.ACTIONABLE


class CommerceAttentionQuery(PageParams):
    model_config = ConfigDict(extra="forbid")
    view: Literal["all", "pending", "fulfillment", "unread"] = "all"


class WalletAttentionQuery(PageParams):
    model_config = ConfigDict(extra="forbid")
    view: Literal["all", "unread"] = "unread"


class WalletAttentionTransactionOut(BaseModel):
    id: int = Field(gt=0, strict=True)
    change_amount: MoneyOut
    before_balance: WalletBalanceOut
    after_balance: WalletBalanceOut
    reason: str = Field(min_length=1, max_length=256)


class CommerceAttentionItemOut(BaseModel):
    id: int
    scope: Literal["orders", "tables", "wallet"]
    reference: str
    title: str
    status_label: str
    order_id: int | None
    session_no: str | None
    unread: bool
    created_at: datetime
    payment_deadline_at: datetime | None


class CommerceAttentionEventOut(AttentionEventOut):
    message: str
    session_no: str | None
    read: bool
    wallet_transaction: WalletAttentionTransactionOut | None = None


class CommerceAttentionSnapshotOut(BaseModel):
    server_now: datetime
    events: list[CommerceAttentionEventOut]
