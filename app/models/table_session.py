"""固定桌台、开台会话、计时快照与当前占用。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import MinLengthValidator, MinValueValidator, RegexValidator

from app.common.constants.table_session import (
    TABLE_ADMIN_REASON_MAX_LENGTH,
    TABLE_DISPLAY_NAME_MAX_LENGTH,
    TABLE_FINGERPRINT_LENGTH,
    TABLE_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
    TABLE_NO_LENGTH,
    TABLE_NO_PATTERN,
    TABLE_QR_TOKEN_LENGTH,
    TABLE_QR_TOKEN_PATTERN,
    TABLE_SESSION_ENUM_MAX_LENGTH,
    TABLE_SESSION_NO_LENGTH,
    TABLE_SESSION_NO_PATTERN,
    TABLE_TIMER_BUFFER_MINUTES,
)
from app.common.enums.table_session import TableSessionCloseReason, TableSessionStatus
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel
from app.models.fields import AsciiBinaryCharField


class StoreTable(BaseModel):
    table_no = fields.CharField(
        max_length=TABLE_NO_LENGTH,
        validators=[RegexValidator(TABLE_NO_PATTERN, flags=0)],
    )
    display_name = fields.CharField(
        max_length=TABLE_DISPLAY_NAME_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )
    qr_token = AsciiBinaryCharField(
        max_length=TABLE_QR_TOKEN_LENGTH,
        validators=[RegexValidator(TABLE_QR_TOKEN_PATTERN, flags=0)],
    )
    is_enabled = fields.BooleanField(default=True, db_default=True)

    class Meta:
        table = "store_tables"
        indexes = [
            UniqueIndex(fields=("table_no",), name="uidx_store_table_no"),
            UniqueIndex(fields=("qr_token",), name="uidx_store_table_qr_token"),
        ]


class TableSession(BaseModel):
    session_no = AsciiBinaryCharField(
        max_length=TABLE_SESSION_NO_LENGTH,
        validators=[RegexValidator(TABLE_SESSION_NO_PATTERN, flags=0)],
    )
    table = fields.ForeignKeyField(
        "models.StoreTable", related_name="sessions", on_delete=fields.RESTRICT
    )
    user = fields.ForeignKeyField(
        "models.User", related_name="table_sessions", on_delete=fields.RESTRICT
    )
    order = fields.ForeignKeyField(
        "models.Order", related_name="table_sessions", on_delete=fields.RESTRICT
    )
    payment = fields.ForeignKeyField(
        "models.Payment",
        related_name="table_session",
        on_delete=fields.RESTRICT,
        null=True,
    )
    status = fields.CharEnumField(
        TableSessionStatus,
        max_length=TABLE_SESSION_ENUM_MAX_LENGTH,
        default=TableSessionStatus.AWAITING_PAYMENT,
        db_default=TableSessionStatus.AWAITING_PAYMENT.value,
    )
    claim_idempotency_key = AsciiBinaryCharField(
        max_length=TABLE_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
        validators=[MinLengthValidator(1)],
    )
    claim_request_fingerprint = AsciiBinaryCharField(
        max_length=TABLE_FINGERPRINT_LENGTH,
        validators=[RegexValidator(r"^[0-9a-f]{64}$", flags=0)],
    )
    release_idempotency_key = AsciiBinaryCharField(
        max_length=TABLE_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
        null=True,
        validators=[MinLengthValidator(1)],
    )
    claimed_at = fields.DatetimeField()
    payment_deadline_at = fields.DatetimeField()
    started_at = fields.DatetimeField(null=True)
    table_release_at = fields.DatetimeField(null=True)
    closed_at = fields.DatetimeField(null=True)
    close_reason = fields.CharEnumField(
        TableSessionCloseReason,
        max_length=TABLE_SESSION_ENUM_MAX_LENGTH,
        null=True,
    )
    closed_by_user = fields.ForeignKeyField(
        "models.User",
        related_name="closed_table_sessions",
        on_delete=fields.RESTRICT,
        null=True,
    )
    admin_close_reason = fields.CharField(
        max_length=TABLE_ADMIN_REASON_MAX_LENGTH,
        null=True,
    )

    class Meta:
        table = "table_sessions"
        indexes = [
            UniqueIndex(fields=("session_no",), name="uidx_table_session_no"),
            UniqueIndex(
                fields=("claim_idempotency_key",),
                name="uidx_table_session_claim_idempotency",
            ),
            UniqueIndex(
                fields=("release_idempotency_key",),
                name="uidx_table_session_release_idempotency",
            ),
            UniqueIndex(fields=("payment_id",), name="uidx_table_session_payment"),
            Index(
                fields=("table_id", "claimed_at", "id"),
                name="idx_table_session_table_claimed_id",
            ),
            Index(
                fields=("user_id", "status", "claimed_at", "id"),
                name="idx_table_session_user_status_claimed_id",
            ),
            Index(
                fields=("order_id", "status", "claimed_at", "id"),
                name="idx_table_session_order_status_claimed_id",
            ),
            Index(
                fields=("status", "payment_deadline_at", "id"),
                name="idx_table_session_status_payment_deadline_id",
            ),
            Index(
                fields=("status", "table_release_at", "id"),
                name="idx_table_session_status_release_id",
            ),
        ]


class TableSessionTimer(BaseModel):
    session = fields.ForeignKeyField(
        "models.TableSession", related_name="timers", on_delete=fields.RESTRICT
    )
    duration_minutes = fields.IntField(validators=[MinValueValidator(1)])
    buffer_minutes = fields.SmallIntField(
        default=TABLE_TIMER_BUFFER_MINUTES,
        db_default=TABLE_TIMER_BUFFER_MINUTES,
        validators=[MinValueValidator(1)],
    )
    started_at = fields.DatetimeField()
    service_ends_at = fields.DatetimeField()
    grace_ends_at = fields.DatetimeField()

    class Meta:
        table = "table_session_timers"
        indexes = [
            UniqueIndex(
                fields=("session_id", "duration_minutes"),
                name="uidx_table_session_timer_duration",
            )
        ]


class TableOccupancy(BaseModel):
    table = fields.ForeignKeyField(
        "models.StoreTable", related_name="occupancy", on_delete=fields.RESTRICT
    )
    session = fields.ForeignKeyField(
        "models.TableSession", related_name="occupancy", on_delete=fields.RESTRICT
    )
    user = fields.ForeignKeyField(
        "models.User", related_name="table_occupancy", on_delete=fields.RESTRICT
    )
    order = fields.ForeignKeyField(
        "models.Order", related_name="table_occupancy", on_delete=fields.RESTRICT
    )

    class Meta:
        table = "table_occupancies"
        indexes = [
            UniqueIndex(fields=("table_id",), name="uidx_table_occupancy_table"),
            UniqueIndex(fields=("session_id",), name="uidx_table_occupancy_session"),
            UniqueIndex(fields=("user_id",), name="uidx_table_occupancy_user"),
            UniqueIndex(fields=("order_id",), name="uidx_table_occupancy_order"),
        ]
