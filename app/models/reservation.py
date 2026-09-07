"""Reservation Models —— 门店营业日与独立体验预约历史。"""

from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import (
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
)

from app.common.constants.product import (
    MIN_DURATION_MINUTES,
    MIN_PARTICIPANTS,
    PRODUCT_ENUM_MAX_LENGTH,
    PRODUCT_NAME_MAX_LENGTH,
    PRODUCT_NAME_MIN_LENGTH,
    PRODUCT_PRICE_DECIMAL_PLACES,
    PRODUCT_PRICE_MAX,
    PRODUCT_PRICE_MIN,
)
from app.common.constants.reservation import RESERVATION_ENUM_MAX_LENGTH
from app.common.enums.product import DayType
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationRejectionReason,
    ReservationStatus,
)
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel
from app.models.fields import StrictDecimalField


class StoreBusinessDay(BaseModel):
    """预约创建与人工店休共用的一日一行并发锁点。"""

    business_date = fields.DateField()
    is_closed = fields.BooleanField(default=False, db_default=False)

    class Meta:
        table = "store_business_days"
        indexes = [
            UniqueIndex(
                fields=("business_date",),
                name="uidx_store_business_day_date",
            ),
        ]


class Reservation(BaseModel):
    """独立于 Order/Payment 的体验预约及不可变创建快照。"""

    user = fields.ForeignKeyField(
        "models.User",
        related_name="reservations",
        on_delete=fields.RESTRICT,
    )
    business_day = fields.ForeignKeyField(
        "models.StoreBusinessDay",
        related_name="reservations",
        on_delete=fields.RESTRICT,
    )
    product = fields.ForeignKeyField(
        "models.Product",
        related_name="reservations",
        on_delete=fields.RESTRICT,
    )
    experience_option = fields.ForeignKeyField(
        "models.ExperienceOption",
        related_name="reservations",
        on_delete=fields.RESTRICT,
    )
    scheduled_start_at = fields.DatetimeField()
    scheduled_end_at = fields.DatetimeField()
    product_name = fields.CharField(
        max_length=PRODUCT_NAME_MAX_LENGTH,
        validators=[MinLengthValidator(PRODUCT_NAME_MIN_LENGTH)],
    )
    option_duration_minutes = fields.IntField(
        validators=[MinValueValidator(MIN_DURATION_MINUTES)],
    )
    option_participants = fields.IntField(
        validators=[MinValueValidator(MIN_PARTICIPANTS)],
    )
    option_day_type = fields.CharEnumField(
        DayType,
        max_length=PRODUCT_ENUM_MAX_LENGTH,
    )
    option_price = StrictDecimalField(
        max_digits=10,
        decimal_places=PRODUCT_PRICE_DECIMAL_PLACES,
        validators=[
            MinValueValidator(PRODUCT_PRICE_MIN),
            MaxValueValidator(PRODUCT_PRICE_MAX),
        ],
    )
    status = fields.CharEnumField(
        ReservationStatus,
        max_length=RESERVATION_ENUM_MAX_LENGTH,
        default=ReservationStatus.PENDING,
        db_default=ReservationStatus.PENDING.value,
    )
    rejection_reason = fields.CharEnumField(
        ReservationRejectionReason,
        max_length=RESERVATION_ENUM_MAX_LENGTH,
        null=True,
    )
    cancellation_reason = fields.CharEnumField(
        ReservationCancellationReason,
        max_length=RESERVATION_ENUM_MAX_LENGTH,
        null=True,
    )
    confirmed_at = fields.DatetimeField(null=True)
    rejected_at = fields.DatetimeField(null=True)
    cancelled_at = fields.DatetimeField(null=True)

    class Meta:
        table = "reservations"
        indexes = [
            Index(
                fields=("user_id", "scheduled_start_at", "id"),
                name="idx_reservations_user_start_id",
            ),
            Index(
                fields=("user_id", "status", "scheduled_end_at", "id"),
                name="idx_reservations_user_status_end_id",
            ),
            Index(
                fields=("user_id", "status", "scheduled_start_at", "id"),
                name="idx_reservations_user_status_start_id",
            ),
            Index(
                fields=(
                    "business_day_id",
                    "status",
                    "scheduled_start_at",
                    "id",
                ),
                name="idx_reservations_day_status_start_id",
            ),
            Index(
                fields=("status", "scheduled_start_at", "id"),
                name="idx_reservations_status_start_id",
            ),
        ]
