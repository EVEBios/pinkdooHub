"""Inventory Repository —— 封装库存余额锁定、流水写入与分页查询。"""

from dataclasses import dataclass
from datetime import datetime, timezone

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.queryset import QuerySet

from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.pagination import Page
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order
from app.models.product_kit import ProductKit


@dataclass(frozen=True, slots=True)
class InventoryTransactionCreateData:
    """Repository 写入一条已由调用方计算完成的库存流水所需数据。"""

    product_id: int
    transaction_type: InventoryTransactionType
    change_quantity: int
    before_quantity: int
    after_quantity: int
    source_type: InventorySourceType
    source_id: int | None
    operator_id: int | None
    reason: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class InventoryStockUpdateData:
    """Repository 批量保存一个已锁定 Kit 的最终余额。"""

    kit: ProductKit
    stock: int


def _apply_transaction_filters(
    query: QuerySet[InventoryTransaction],
    *,
    product_id: int | None = None,
    transaction_type: InventoryTransactionType | None = None,
    source_type: InventorySourceType | None = None,
    source_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> QuerySet[InventoryTransaction]:
    """应用纯数据库流水筛选；筛选组合是否合法由上层 Schema 保证。"""

    if product_id is not None:
        query = query.filter(product_id=product_id)
    if transaction_type is not None:
        query = query.filter(transaction_type=transaction_type)
    if source_type is not None:
        query = query.filter(source_type=source_type)
    if source_id is not None:
        query = query.filter(source_id=source_id)
    if created_from is not None:
        query = query.filter(created_at__gte=created_from)
    if created_to is not None:
        query = query.filter(created_at__lt=created_to)
    return query


class InventoryRepository:
    """Inventory 数据访问层，不判断可售性、余额充足性或状态机。"""

    async def get_kit_for_update(
        self,
        product_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> ProductKit | None:
        """在调用方事务中锁定单个 ProductKit 余额行。"""

        return await (
            ProductKit.filter(product_id=product_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_kits_for_update(
        self,
        product_ids: set[int],
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[ProductKit]:
        """用一次查询按 Product ID 升序锁定多个余额行。"""

        if not product_ids:
            return []
        sorted_product_ids = sorted(product_ids)
        return await (
            ProductKit.filter(product_id__in=sorted_product_ids)
            .using_db(using_db)
            .order_by("product_id")
            .select_for_update()
        )

    async def update_stock(
        self,
        kit: ProductKit,
        *,
        stock: int,
        using_db: BaseDBAsyncClient,
    ) -> ProductKit:
        """持久化调用方已计算的最终余额，不执行库存业务判断。"""

        kit.stock = stock
        await kit.save(
            using_db=using_db,
            update_fields=["stock", "updated_at"],
        )
        return kit

    async def bulk_update_stocks(
        self,
        *,
        updates: list[InventoryStockUpdateData],
        using_db: BaseDBAsyncClient,
    ) -> None:
        """用一条批量更新保存多个已锁定 Kit 的最终余额。"""

        if not updates:
            return
        updated_at = datetime.now(timezone.utc)
        kits: list[ProductKit] = []
        for update in updates:
            update.kit.stock = update.stock
            update.kit.updated_at = updated_at
            kits.append(update.kit)
        await ProductKit.bulk_update(
            kits,
            fields=["stock", "updated_at"],
            using_db=using_db,
        )

    async def create_transaction(
        self,
        *,
        data: InventoryTransactionCreateData,
        using_db: BaseDBAsyncClient | None = None,
    ) -> InventoryTransaction:
        """创建单条库存流水，并加入调用方提供的事务连接。"""

        return await InventoryTransaction.create(
            **self._transaction_fields(data),
            using_db=using_db,
        )

    async def bulk_create_transactions(
        self,
        *,
        transactions: list[InventoryTransactionCreateData],
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        """一次批量写入多 Kit 自动流水；空集合不执行 SQL。"""

        if not transactions:
            return
        models = [
            InventoryTransaction(**self._transaction_fields(data))
            for data in transactions
        ]
        await InventoryTransaction.bulk_create(models, using_db=using_db)

    async def get_transaction_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> InventoryTransaction | None:
        """按唯一业务身份读取原始流水，供锁内幂等判断。"""

        query = InventoryTransaction.filter(idempotency_key=idempotency_key)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_transactions_by_idempotency_keys(
        self,
        idempotency_keys: set[str],
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[InventoryTransaction]:
        """用一次查询读取已提交到当前事务视图的自动事件幂等记录。"""

        if not idempotency_keys:
            return []
        return await (
            InventoryTransaction.filter(idempotency_key__in=idempotency_keys)
            .using_db(using_db)
            .order_by("id")
        )

    async def get_transaction_detail(
        self,
        transaction_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> InventoryTransaction | None:
        """读取单条流水及安全展示元数据，不产生 Mapper 查询。"""

        query = InventoryTransaction.filter(id=transaction_id).select_related(
            "operator"
        )
        if using_db is not None:
            query = query.using_db(using_db)
        transaction = await query.first()
        if transaction is None:
            return None
        await self._attach_source_order_numbers(
            [transaction],
            using_db=using_db,
        )
        return transaction

    async def list_transactions(
        self,
        *,
        page: int,
        page_size: int,
        product_id: int | None = None,
        transaction_type: InventoryTransactionType | None = None,
        source_type: InventorySourceType | None = None,
        source_id: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Page[InventoryTransaction]:
        """按冻结筛选和 `created_at DESC, id DESC` 稳定分页。"""

        query = _apply_transaction_filters(
            InventoryTransaction.all(),
            product_id=product_id,
            transaction_type=transaction_type,
            source_type=source_type,
            source_id=source_id,
            created_from=created_from,
            created_to=created_to,
        )
        if using_db is not None:
            query = query.using_db(using_db)

        total = await query.count()
        items = await (
            query.select_related("operator")
            .order_by("-created_at", "-id")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        await self._attach_source_order_numbers(items, using_db=using_db)
        pages = (total + page_size - 1) // page_size
        return Page[InventoryTransaction](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    @staticmethod
    def _transaction_fields(
        data: InventoryTransactionCreateData,
    ) -> dict[str, object]:
        """把冻结写入 DTO 显式投影为 Model 字段。"""

        return {
            "product_id": data.product_id,
            "transaction_type": data.transaction_type,
            "change_quantity": data.change_quantity,
            "before_quantity": data.before_quantity,
            "after_quantity": data.after_quantity,
            "source_type": data.source_type,
            "source_id": data.source_id,
            "operator_id": data.operator_id,
            "reason": data.reason,
            "idempotency_key": data.idempotency_key,
        }

    @staticmethod
    async def _attach_source_order_numbers(
        transactions: list[InventoryTransaction],
        *,
        using_db: BaseDBAsyncClient | None,
    ) -> None:
        """用一次批量查询补齐 Order 来源展示字段，避免 Mapper N+1。"""

        source_ids = {
            transaction.source_id
            for transaction in transactions
            if transaction.source_type is InventorySourceType.ORDER
            and transaction.source_id is not None
        }
        order_no_by_id: dict[int, str] = {}
        if source_ids:
            query = Order.filter(id__in=source_ids)
            if using_db is not None:
                query = query.using_db(using_db)
            rows = await query.values_list("id", "order_no")
            order_no_by_id = dict(rows)

        for transaction in transactions:
            source_order_no = (
                order_no_by_id.get(transaction.source_id)
                if transaction.source_type is InventorySourceType.ORDER
                and transaction.source_id is not None
                else None
            )
            setattr(transaction, "source_order_no", source_order_no)
