"""Inventory ORM 数据到严格 API Out Schema 的同步纯映射。"""

from app.common.pagination import Page
from app.models.inventory_transaction import InventoryTransaction
from app.schemas.inventory_response import (
    InventoryAdjustmentOut,
    InventoryTransactionListItem,
    InventoryTransactionOut,
)


def _transaction_payload(
    transaction: InventoryTransaction,
) -> dict[str, object]:
    """只读取 Repository 已准备的展示字段并构造响应白名单。"""

    operator_nickname = (
        transaction.operator.nickname
        if transaction.operator_id is not None
        else None
    )
    return {
        "id": transaction.id,
        "product_id": transaction.product_id,
        "transaction_type": transaction.transaction_type,
        "change_quantity": transaction.change_quantity,
        "before_quantity": transaction.before_quantity,
        "after_quantity": transaction.after_quantity,
        "reason": transaction.reason,
        "source_type": transaction.source_type,
        "source_id": transaction.source_id,
        "source_order_no": transaction.source_order_no,
        "operator_id": transaction.operator_id,
        "operator_nickname": operator_nickname,
        "created_at": transaction.created_at,
    }


def map_inventory_transaction(
    transaction: InventoryTransaction,
) -> InventoryTransactionOut:
    """映射单条库存流水并执行完整响应一致性校验。"""

    return InventoryTransactionOut.model_validate(
        _transaction_payload(transaction)
    )


def map_inventory_transaction_list_item(
    transaction: InventoryTransaction,
) -> InventoryTransactionListItem:
    """映射库存流水列表项。"""

    return InventoryTransactionListItem.model_validate(
        _transaction_payload(transaction)
    )


def map_inventory_transaction_page(
    page: Page[InventoryTransaction],
) -> Page[InventoryTransactionListItem]:
    """保留分页元数据并映射库存流水列表。"""

    return Page[InventoryTransactionListItem](
        items=[
            map_inventory_transaction_list_item(transaction)
            for transaction in page.items
        ],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def map_inventory_adjustment(
    *,
    product_id: int,
    stock: int,
    transaction: InventoryTransaction,
) -> InventoryAdjustmentOut:
    """映射调整余额与对应流水，不让 API Mapper 依赖 Service DTO。"""

    return InventoryAdjustmentOut.model_validate(
        {
            "product_id": product_id,
            "stock": stock,
            "transaction": map_inventory_transaction(transaction),
        }
    )
