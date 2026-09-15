"""单接收目标的站内结果；业务状态与阅读状态互相独立。"""

from tortoise import fields
from tortoise.indexes import Index

from app.common.enums.attention import AttentionEventType
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel


class AttentionEvent(BaseModel):
    """user 为空表示门店共享知悉；首阶段每个事件只有一个接收目标。"""

    event_key = fields.CharField(max_length=128)
    event_type = fields.CharEnumField(AttentionEventType, max_length=40)
    reservation = fields.ForeignKeyField(
        "models.Reservation", related_name="attention_events", null=True, on_delete=fields.RESTRICT,
    )
    order = fields.ForeignKeyField(
        "models.Order", related_name="attention_events", null=True, on_delete=fields.RESTRICT,
    )
    session = fields.ForeignKeyField(
        "models.TableSession", related_name="attention_events", null=True, on_delete=fields.RESTRICT,
    )
    result_message = fields.CharField(max_length=255, null=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="attention_events", null=True, on_delete=fields.RESTRICT,
    )
    occurred_at = fields.DatetimeField()
    read_at = fields.DatetimeField(null=True)
    read_by = fields.ForeignKeyField(
        "models.User", related_name="read_attention_events", null=True, on_delete=fields.RESTRICT,
    )

    class Meta:
        table = "attention_events"
        indexes = [
            UniqueIndex(fields=("event_key",), name="uidx_attention_event_key"),
            Index(fields=("user_id", "read_at", "reservation_id"), name="idx_attention_recipient_unread"),
            Index(fields=("reservation_id", "user_id", "id"), name="idx_attention_reservation_recipient"),
            Index(fields=("user_id", "read_at", "order_id"), name="idx_attention_order_unread"),
            Index(fields=("user_id", "read_at", "session_id"), name="idx_attention_session_unread"),
        ]
