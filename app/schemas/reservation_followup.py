"""仅管理员可读写的预约跟进契约。"""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.common.enums.reservation_followup import FollowupKind, FollowupOutcome
from app.common.pagination import PageParams


class FollowupQuery(PageParams):
    model_config = ConfigDict(extra="forbid")
    kind: FollowupKind
    view: Literal["pending", "completed"] = "pending"


class FollowupWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    request_key: UUID
    outcome: FollowupOutcome
    note: str = Field(min_length=1, max_length=500)

    @field_validator("note")
    @classmethod
    def trim_note(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请填写联系情况或处理结果")
        return value


class FollowupCounts(BaseModel):
    server_now: datetime
    contact_pending: int = Field(ge=0)
    overdue_pending: int = Field(ge=0)


class FollowupRecordOut(BaseModel):
    id: int
    revision: int
    outcome: FollowupOutcome
    label: str
    note: str
    operator_id: int
    created_at: datetime


class FollowupSnapshotOut(BaseModel):
    reservation_id: int
    kind: FollowupKind
    eligible: bool
    completed: bool
    revision: int
    latest: FollowupRecordOut | None
    server_now: datetime


class FollowupItemOut(FollowupSnapshotOut):
    product_name: str | None
    customer_name: str
    scheduled_start_at: datetime
