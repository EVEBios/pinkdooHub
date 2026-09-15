"""门店整包库存的事务、乐观版本核验与原批次重放。"""
import hashlib
import json
import logging
from math import ceil
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError, OperationalError
from tortoise.transactions import in_transaction
from app.common.constants.inventory import INVENTORY_RETRYABLE_MYSQL_ERROR_CODES, INVENTORY_TRANSACTION_MAX_ATTEMPTS
from app.common.constants.store_bead_stock import STORE_BEAD_AUDIT_ACTION
from app.common.exceptions.store_bead_stock import StoreBeadBatchConflict, StoreBeadStockConflict, StoreBeadStockNotFound, StoreBeadStockUnchanged
from app.common.pagination import Page
from app.repositories.store_bead_stock_repo import StoreBeadStockRepository
from app.schemas.store_bead_stock import StoreBeadStockOut, StoreBeadStockWrite, StoreBeadStockChange, StoreBeadStockBatchOut, StoreBeadStockBatchSummary, StoreBeadStockEntryOut
from app.services.audit_log_service import AuditLogService
from app.utils.database import get_database_error_code

logger = logging.getLogger(__name__)


class StoreBeadStockService:
    def __init__(self, repository: StoreBeadStockRepository, audit: AuditLogService) -> None:
        self.repository = repository
        self.audit = audit

    async def list_stock(self, page: int, size: int) -> Page[StoreBeadStockOut]:
        async with in_transaction() as db:
            colors = await self.repository.colors(using_db=db)
            selected = colors[(page-1)*size:page*size]
            stocks = await self.repository.stocks([c.id for c in selected], using_db=db)
            items = [StoreBeadStockOut(bead_color_id=c.id, slot_no=c.slot_no, color_code=c.color_code, color_name=c.name,
                packs=stocks[c.id].packs if c.id in stocks else None,
                revision=stocks[c.id].revision if c.id in stocks else 0) for c in selected]
            return Page(items=items, total=len(colors), page=page, page_size=size, pages=ceil(len(colors)/size))

    async def _detail(self, batch_id: int, db: BaseDBAsyncClient) -> StoreBeadStockBatchOut:
        batch = await self.repository.batch(batch_id, using_db=db)
        if batch is None:
            raise StoreBeadStockNotFound()
        entries = await self.repository.entries(batch.id, using_db=db)
        items = [StoreBeadStockEntryOut(bead_color_id=e.bead_color_id, slot_no=e.slot_no, color_code=e.color_code,
            color_name=e.color_name, before_packs=e.before_packs, after_packs=e.after_packs, revision=e.revision) for e in entries]
        return StoreBeadStockBatchOut(id=batch.id, operator_id=batch.operator_id, operator_name=batch.operator.nickname or "管理员",
            created_at=batch.created_at, reason=batch.reason, note=batch.note, changed_colors=len(items), items=items)

    async def detail(self, batch_id: int) -> StoreBeadStockBatchOut:
        async with in_transaction() as db:
            return await self._detail(batch_id, db)

    async def by_request(self, key: str, operator_id: int) -> StoreBeadStockBatchOut:
        async with in_transaction() as db:
            batch = await self.repository.find_batch(key, operator_id, using_db=db)
            if batch is None:
                raise StoreBeadStockNotFound()
            return await self._detail(batch.id, db)

    async def history(self, page: int, size: int) -> Page[StoreBeadStockBatchSummary]:
        async with in_transaction() as db:
            rows, total = await self.repository.batches(page, size, using_db=db)
            items = [StoreBeadStockBatchSummary(id=b.id, operator_id=b.operator_id, operator_name=b.operator.nickname or "管理员",
                created_at=b.created_at, reason=b.reason, note=b.note, changed_colors=b.changed_colors) for b in rows]
            return Page(items=items, total=total, page=page, page_size=size, pages=ceil(total/size))

    async def write(self, data: StoreBeadStockWrite, operator_id: int, ip_address: str) -> StoreBeadStockBatchOut:
        ordered = sorted(data.items, key=lambda item: item.bead_color_id)
        fingerprint = hashlib.sha256(json.dumps({"items": [i.model_dump() for i in ordered], "reason": data.reason, "note": data.note}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        for attempt in range(INVENTORY_TRANSACTION_MAX_ATTEMPTS):
            try:
                return await self._write_once(data, ordered, fingerprint, operator_id, ip_address)
            except IntegrityError:
                # 唯一键竞争可能来自相同请求的并发提交；仅已提交的相同意图可重放。
                async with in_transaction() as db:
                    replay = await self.repository.find_batch(str(data.request_key), operator_id, using_db=db)
                    if replay is None:
                        raise
                    if replay.fingerprint != fingerprint:
                        raise StoreBeadBatchConflict()
                    return await self._detail(replay.id, db)
            except OperationalError as error:
                if get_database_error_code(error) not in INVENTORY_RETRYABLE_MYSQL_ERROR_CODES or attempt + 1 == INVENTORY_TRANSACTION_MAX_ATTEMPTS:
                    raise
                logger.warning("Retry store bead batch after lock conflict: operator=%d attempt=%d", operator_id, attempt+1)
        raise RuntimeError("Store bead stock retry exhausted")

    async def _write_once(self, data: StoreBeadStockWrite, ordered: list[StoreBeadStockChange], fingerprint: str, operator_id: int, ip_address: str) -> StoreBeadStockBatchOut:
        async with in_transaction() as db:
            # 共用目录父行锁确保余额尚不存在时，首次盘点仍与其他管理员串行。
            colors = await self.repository.lock_colors([i.bead_color_id for i in ordered], using_db=db)
            if len(colors) != len(ordered):
                raise StoreBeadStockNotFound()
            replay = await self.repository.find_batch(str(data.request_key), operator_id, using_db=db)
            if replay is not None:
                if replay.fingerprint != fingerprint:
                    raise StoreBeadBatchConflict()
                return await self._detail(replay.id, db)
            stocks = await self.repository.stocks([c.id for c in colors], using_db=db, lock=True)
            conflicts = []
            for item in ordered:
                stock = stocks.get(item.bead_color_id)
                revision = stock.revision if stock else 0
                if item.expected_revision != revision:
                    conflicts.append({"bead_color_id": item.bead_color_id, "packs": stock.packs if stock else None, "revision": revision})
            if conflicts:
                raise StoreBeadStockConflict(conflicts)
            if any(i.bead_color_id in stocks and stocks[i.bead_color_id].packs == i.packs for i in ordered):
                raise StoreBeadStockUnchanged()
            batch = await self.repository.create_batch(operator_id=operator_id, request_key=str(data.request_key), fingerprint=fingerprint, reason=data.reason, note=data.note, using_db=db)
            by_id = {c.id: c for c in colors}
            entries = []
            for item in ordered:
                color = by_id[item.bead_color_id]
                stock = stocks.get(color.id)
                before = stock.packs if stock else None
                revision = (stock.revision if stock else 0) + 1
                await self.repository.set_stock(color.id, item.packs, revision, stock, using_db=db)
                entries.append(dict(batch_id=batch.id, bead_color_id=color.id, slot_no=color.slot_no, color_code=color.color_code,
                    color_name=color.name, before_packs=before, after_packs=item.packs, revision=revision))
            await self.repository.append_entries(entries, using_db=db)
            await self.audit.log(operator_id=operator_id, action=STORE_BEAD_AUDIT_ACTION, target_type="store_bead_batch", target_id=batch.id,
                ip_address=ip_address, description=f"调整 {len(entries)} 色门店整包库存", using_db=db)
            return await self._detail(batch.id, db)
