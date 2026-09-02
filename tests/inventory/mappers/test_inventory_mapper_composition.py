"""Inventory Mapper 显式字段投影、组合校验与分页测试。"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.mappers.inventory import (
    map_inventory_adjustment,
    map_inventory_transaction,
    map_inventory_transaction_page,
)
from app.common.enums.inventory import InventorySourceType, InventoryTransactionType
from app.common.pagination import Page


NOW = datetime(2026, 8, 14, 10, 30, tzinfo=timezone.utc)
ORDER_NO = "OD01ARZ3NDEKTSV4RRFFQ69G6A01"


def _transaction(
    *,
    transaction_id: int = 101,
    transaction_type: InventoryTransactionType = (
        InventoryTransactionType.ADMIN_ADJUSTMENT
    ),
) -> SimpleNamespace:
    if transaction_type is InventoryTransactionType.OPENING_BALANCE:
        before, change = 0, 12
        source_type = InventorySourceType.MIGRATION
        source_id = None
        source_order_no = None
        operator_id = None
        operator = None
    elif transaction_type is InventoryTransactionType.ADMIN_ADJUSTMENT:
        before, change = 10, 2
        source_type = InventorySourceType.ADMIN
        source_id = None
        source_order_no = None
        operator_id = 7
        operator = SimpleNamespace(
            id=7,
            nickname="库存管理员",
            username="private-admin",
            phone="13800138000",
            password="must-not-leak",
        )
    else:
        before = 10
        change = (
            2
            if transaction_type
            is InventoryTransactionType.ORDER_CANCELLATION_RESTORE
            else -2
        )
        source_type = InventorySourceType.ORDER
        source_id = 31
        source_order_no = ORDER_NO
        operator_id = 7
        operator = SimpleNamespace(
            id=7,
            nickname="下单用户",
            username="private-user",
            phone="13800138001",
            password="must-not-leak",
        )

    return SimpleNamespace(
        id=transaction_id,
        product_id=5,
        transaction_type=transaction_type,
        change_quantity=change,
        before_quantity=before,
        after_quantity=before + change,
        reason="库存流水公开原因",
        source_type=source_type,
        source_id=source_id,
        source_order_no=source_order_no,
        operator_id=operator_id,
        operator=operator,
        idempotency_key="inventory:must-not-leak",
        created_at=NOW,
        updated_at=NOW,
        token="must-not-leak",
    )


@pytest.mark.parametrize(
    "transaction_type",
    list(InventoryTransactionType),
)
def test_transaction_mapper_supports_every_ledger_type_and_isolates_fields(
    transaction_type: InventoryTransactionType,
) -> None:
    transaction = _transaction(transaction_type=transaction_type)

    data = map_inventory_transaction(transaction).model_dump(mode="json")

    assert set(data) == {
        "id",
        "product_id",
        "transaction_type",
        "change_quantity",
        "before_quantity",
        "after_quantity",
        "reason",
        "source_type",
        "source_id",
        "source_order_no",
        "operator_id",
        "operator_nickname",
        "created_at",
    }
    assert not (
        {"idempotency_key", "updated_at", "username", "phone", "password", "token"}
        & data.keys()
    )
    if transaction.operator is not None:
        assert data["operator_nickname"] == transaction.operator.nickname
    else:
        assert data["operator_nickname"] is None


def test_transaction_page_preserves_metadata_and_order() -> None:
    first = _transaction(transaction_id=102)
    second = _transaction(
        transaction_id=101,
        transaction_type=InventoryTransactionType.OPENING_BALANCE,
    )
    page = Page(
        items=[first, second],
        total=22,
        page=2,
        page_size=20,
        pages=2,
    )

    data = map_inventory_transaction_page(page).model_dump(mode="json")

    assert [item["id"] for item in data["items"]] == [102, 101]
    assert data | {"items": []} == {
        "items": [],
        "total": 22,
        "page": 2,
        "page_size": 20,
        "pages": 2,
    }


def test_adjustment_mapper_validates_balance_against_transaction() -> None:
    transaction = _transaction()

    result = map_inventory_adjustment(
        product_id=5,
        stock=12,
        transaction=transaction,
    ).model_dump(mode="json")

    assert result["product_id"] == 5
    assert result["stock"] == 12
    assert result["transaction"]["id"] == 101

    with pytest.raises(ValidationError, match="adjustment result is inconsistent"):
        map_inventory_adjustment(
            product_id=5,
            stock=13,
            transaction=transaction,
        )


def test_mapper_rejects_corrupt_order_metadata() -> None:
    transaction = _transaction(
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION
    )
    transaction.source_order_no = None

    with pytest.raises(ValidationError, match="metadata is invalid"):
        map_inventory_transaction(transaction)
