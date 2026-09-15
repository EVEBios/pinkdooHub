"""门店未拆封整包余额与不可变批次记录；缺少余额行表示未盘点。"""
from tortoise import fields
from tortoise.indexes import Index
from tortoise.validators import MaxValueValidator, MinValueValidator
from app.common.constants.store_bead_stock import STORE_BEAD_STOCK_MAX
from app.db.indexes import UniqueIndex
from app.models.base import BaseModel


class StoreBeadStock(BaseModel):
    bead_color = fields.OneToOneField("models.BeadColor", related_name="store_stock", on_delete=fields.RESTRICT)
    packs = fields.IntField(validators=[MinValueValidator(0), MaxValueValidator(STORE_BEAD_STOCK_MAX)])
    revision = fields.IntField(validators=[MinValueValidator(1)])

    class Meta:
        table = "store_bead_stocks"


class StoreBeadStockBatch(BaseModel):
    operator = fields.ForeignKeyField("models.User", related_name="store_bead_batches", on_delete=fields.RESTRICT)
    request_key = fields.CharField(max_length=36)
    fingerprint = fields.CharField(max_length=64)
    reason = fields.CharField(max_length=20)
    note = fields.CharField(max_length=500)

    class Meta:
        table = "store_bead_stock_batches"
        indexes = [
            UniqueIndex(fields=("operator_id", "request_key"), name="uidx_store_bead_batch_request"),
            Index(fields=("created_at", "id"), name="idx_store_bead_batch_time"),
        ]


class StoreBeadStockEntry(BaseModel):
    batch = fields.ForeignKeyField("models.StoreBeadStockBatch", related_name="entries", on_delete=fields.RESTRICT)
    bead_color = fields.ForeignKeyField("models.BeadColor", related_name="store_stock_entries", on_delete=fields.RESTRICT)
    slot_no = fields.SmallIntField()
    color_code = fields.CharField(max_length=50, null=True)
    color_name = fields.CharField(max_length=100, null=True)
    before_packs = fields.IntField(null=True)
    after_packs = fields.IntField()
    revision = fields.IntField()

    class Meta:
        table = "store_bead_stock_entries"
        indexes = [
            UniqueIndex(fields=("batch_id", "bead_color_id"), name="uidx_store_bead_entry_batch"),
            UniqueIndex(fields=("bead_color_id", "revision"), name="uidx_store_bead_entry_revision"),
        ]
