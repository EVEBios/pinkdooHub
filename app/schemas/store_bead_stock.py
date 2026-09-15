"""整包盘点请求及输出契约。未盘点与确认零库存严格区分。"""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.common.constants.store_bead_stock import STORE_BEAD_BATCH_MAX, STORE_BEAD_STOCK_MAX

Packs = Annotated[int, Field(strict=True, ge=0, le=STORE_BEAD_STOCK_MAX)]
Reason = Literal["stocktake", "restock", "opening", "other"]


class StoreBeadStockChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bead_color_id: int = Field(strict=True, gt=0)
    expected_revision: int = Field(strict=True, ge=0)
    packs: Packs


class StoreBeadStockWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    reason: Reason = "stocktake"
    note: str = Field(default="", max_length=500, strict=True)
    items: list[StoreBeadStockChange] = Field(min_length=1, max_length=STORE_BEAD_BATCH_MAX)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def unique_colors(self) -> "StoreBeadStockWrite":
        if len({item.bead_color_id for item in self.items}) != len(self.items):
            raise ValueError("同一批次不能重复提交同一颜色")
        return self


class StoreBeadStockQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=221, ge=1, le=221)


class StoreBeadStockOut(BaseModel):
    bead_color_id: int
    slot_no: int
    color_code: str | None
    color_name: str | None
    packs: Packs | None
    revision: int


class StoreBeadStockEntryOut(BaseModel):
    bead_color_id: int
    slot_no: int
    color_code: str | None
    color_name: str | None
    before_packs: Packs | None
    after_packs: Packs
    revision: int


class StoreBeadStockBatchSummary(BaseModel):
    id: int
    operator_id: int
    operator_name: str
    created_at: datetime
    reason: Reason
    note: str
    changed_colors: int


class StoreBeadStockBatchOut(StoreBeadStockBatchSummary):
    items: list[StoreBeadStockEntryOut]
