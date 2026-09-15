"""管理员跟进的只追加记录；无记录的有效事项视为待处理。"""
from tortoise import fields
from tortoise.indexes import Index
from app.common.enums.reservation_followup import FollowupKind, FollowupOutcome
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel


class ReservationFollowup(BaseModel):
    reservation = fields.ForeignKeyField("models.Reservation", related_name="followups", on_delete=fields.RESTRICT)
    kind = fields.CharEnumField(FollowupKind, max_length=16)
    outcome = fields.CharEnumField(FollowupOutcome, max_length=16)
    revision = fields.IntField()
    request_key = fields.CharField(max_length=36)
    note = fields.CharField(max_length=500)
    operator = fields.ForeignKeyField("models.User", related_name="reservation_followups", on_delete=fields.RESTRICT)

    class Meta:
        table = "reservation_followups"
        indexes = [
            UniqueIndex(fields=("reservation_id", "kind", "revision"), name="uidx_followup_revision"),
            UniqueIndex(fields=("reservation_id", "kind", "request_key"), name="uidx_followup_request"),
            Index(fields=("kind", "outcome", "reservation_id"), name="idx_followup_completed"),
        ]
