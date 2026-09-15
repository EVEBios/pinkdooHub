"""门店库存持久化；颜色锁串行化首次盘点，不在读取时写入余额。"""
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.functions import Count
from app.models.bead_color import BeadColor
from app.models.store_bead_stock import StoreBeadStock, StoreBeadStockBatch, StoreBeadStockEntry


class StoreBeadStockRepository:
    async def colors(self, *, using_db: BaseDBAsyncClient) -> list[BeadColor]:
        return await BeadColor.all().using_db(using_db).order_by("sort", "slot_no")

    async def lock_colors(self, ids: list[int], *, using_db: BaseDBAsyncClient) -> list[BeadColor]:
        return await BeadColor.filter(id__in=ids).using_db(using_db).order_by("id").select_for_update()

    async def stocks(self, ids: list[int], *, using_db: BaseDBAsyncClient, lock: bool = False) -> dict[int, StoreBeadStock]:
        query = StoreBeadStock.filter(bead_color_id__in=ids).using_db(using_db)
        if lock:
            query = query.order_by("bead_color_id").select_for_update()
        return {row.bead_color_id: row for row in await query}

    async def find_batch(self, key: str, operator_id: int, *, using_db: BaseDBAsyncClient) -> StoreBeadStockBatch | None:
        return await StoreBeadStockBatch.filter(request_key=key, operator_id=operator_id).using_db(using_db).select_for_update().first()

    async def batch(self, batch_id: int, *, using_db: BaseDBAsyncClient) -> StoreBeadStockBatch | None:
        return await StoreBeadStockBatch.filter(id=batch_id).using_db(using_db).select_related("operator").first()

    async def entries(self, batch_id: int, *, using_db: BaseDBAsyncClient) -> list[StoreBeadStockEntry]:
        return await StoreBeadStockEntry.filter(batch_id=batch_id).using_db(using_db).order_by("slot_no", "id")

    async def batches(self, page: int, size: int, *, using_db: BaseDBAsyncClient) -> tuple[list[StoreBeadStockBatch], int]:
        query = StoreBeadStockBatch.all().using_db(using_db)
        total = await query.count()
        rows = await query.select_related("operator").annotate(changed_colors=Count("entries")).order_by("-created_at", "-id").offset((page-1)*size).limit(size)
        return rows, total

    async def create_batch(self, *, using_db: BaseDBAsyncClient, operator_id: int, request_key: str, fingerprint: str, reason: str, note: str) -> StoreBeadStockBatch:
        return await StoreBeadStockBatch.create(using_db=using_db, operator_id=operator_id, request_key=request_key, fingerprint=fingerprint, reason=reason, note=note)

    async def set_stock(self, color_id: int, packs: int, revision: int, existing: StoreBeadStock | None, *, using_db: BaseDBAsyncClient) -> None:
        if existing is None:
            await StoreBeadStock.create(bead_color_id=color_id, packs=packs, revision=revision, using_db=using_db)
        else:
            existing.packs, existing.revision = packs, revision
            await existing.save(using_db=using_db, update_fields=["packs", "revision", "updated_at"])

    async def append_entries(self, values: list[dict[str, int | str | None]], *, using_db: BaseDBAsyncClient) -> None:
        await StoreBeadStockEntry.bulk_create([StoreBeadStockEntry(**item) for item in values], using_db=using_db)
