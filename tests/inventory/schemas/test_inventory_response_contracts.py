"""Inventory 响应白名单与流水一致性契约测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.inventory_response import (
    InventoryAdjustmentOut,
    InventoryBalanceOut,
    InventoryTransactionListItem,
    InventoryTransactionOut,
)


ORDER_NO = "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC"
UTC_TIME = datetime(2026, 8, 13, 10, 30, tzinfo=timezone.utc)


def _transaction(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": 101,
        "product_id": 5,
        "transaction_type": "admin_adjustment",
        "change_quantity": 20,
        "before_quantity": 60,
        "after_quantity": 80,
        "reason": "采购入库",
        "source_type": "admin",
        "source_id": None,
        "source_order_no": None,
        "operator_id": 7,
        "operator_nickname": "店长",
        "created_at": UTC_TIME,
    }
    payload.update(overrides)
    return payload


def test_inventory_balance_is_strict_and_filters_internal_fields() -> None:
    output = InventoryBalanceOut.model_validate(
        {"product_id": 5, "stock": 80, "idempotency_key": "secret"}
    )

    assert output.model_dump(mode="json") == {"product_id": 5, "stock": 80}


def test_inventory_transaction_filters_internal_and_private_fields() -> None:
    output = InventoryTransactionOut.model_validate(
        _transaction(
            idempotency_key="secret",
            operator_username="admin",
            operator_phone="13800000000",
            order_remark="private",
        )
    )

    assert output.model_dump(mode="json") == {
        "id": 101,
        "product_id": 5,
        "transaction_type": "admin_adjustment",
        "change_quantity": 20,
        "before_quantity": 60,
        "after_quantity": 80,
        "reason": "采购入库",
        "source_type": "admin",
        "source_id": None,
        "source_order_no": None,
        "operator_id": 7,
        "operator_nickname": "店长",
        "created_at": "2026-08-13T10:30:00Z",
    }


@pytest.mark.parametrize(
    "payload",
    [
        _transaction(change_quantity=0, before_quantity=80),
        _transaction(after_quantity=79),
        _transaction(change_quantity=True),
        _transaction(before_quantity=-1, after_quantity=19),
        _transaction(created_at="2026-08-13T10:30:00Z"),
        _transaction(created_at=datetime(2026, 8, 13)),
        _transaction(
            created_at=datetime(
                2026,
                8,
                13,
                tzinfo=timezone(timedelta(hours=8)),
            )
        ),
    ],
)
def test_inventory_transaction_rejects_inconsistent_core_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InventoryTransactionOut.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        _transaction(source_type="order"),
        _transaction(operator_id=None, operator_nickname=None),
        _transaction(source_id=42),
        _transaction(source_order_no=ORDER_NO),
        _transaction(transaction_type="order_deduction"),
    ],
)
def test_admin_adjustment_requires_admin_metadata(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InventoryTransactionOut.model_validate(payload)


def test_opening_and_order_transactions_validate_direction_and_source() -> None:
    opening = InventoryTransactionOut.model_validate(
        _transaction(
            transaction_type="opening_balance",
            change_quantity=60,
            before_quantity=0,
            after_quantity=60,
            reason="Inventory opening balance",
            source_type="migration",
            operator_id=None,
            operator_nickname=None,
        )
    )
    deduction = InventoryTransactionOut.model_validate(
        _transaction(
            transaction_type="order_deduction",
            change_quantity=-3,
            before_quantity=10,
            after_quantity=7,
            reason="Order stock deduction",
            source_type="order",
            source_id=42,
            source_order_no=ORDER_NO,
        )
    )
    restore = InventoryTransactionListItem.model_validate(
        _transaction(
            transaction_type="order_cancellation_restore",
            change_quantity=3,
            before_quantity=7,
            after_quantity=10,
            reason="Order cancellation stock restore",
            source_type="order",
            source_id=42,
            source_order_no=ORDER_NO,
        )
    )

    assert opening.after_quantity == 60
    assert deduction.change_quantity == -3
    assert restore.change_quantity == 3


@pytest.mark.parametrize(
    "payload",
    [
        _transaction(
            transaction_type="opening_balance",
            source_type="migration",
            before_quantity=10,
            after_quantity=30,
            operator_id=None,
            operator_nickname=None,
        ),
        _transaction(
            transaction_type="order_deduction",
            source_type="order",
            source_id=42,
            source_order_no=ORDER_NO,
        ),
        _transaction(
            transaction_type="order_cancellation_restore",
            source_type="order",
            source_id=42,
            source_order_no=ORDER_NO,
            change_quantity=-20,
            before_quantity=80,
            after_quantity=60,
        ),
    ],
)
def test_transaction_type_rejects_wrong_direction_or_metadata(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InventoryTransactionOut.model_validate(payload)


def test_adjustment_response_matches_transaction_product_and_balance() -> None:
    output = InventoryAdjustmentOut.model_validate(
        {"product_id": 5, "stock": 80, "transaction": _transaction()}
    )

    assert output.stock == output.transaction.after_quantity


@pytest.mark.parametrize(
    "payload",
    [
        {"product_id": 6, "stock": 80, "transaction": _transaction()},
        {"product_id": 5, "stock": 79, "transaction": _transaction()},
        {
            "product_id": 5,
            "stock": 7,
            "transaction": _transaction(
                transaction_type="order_deduction",
                change_quantity=-3,
                before_quantity=10,
                after_quantity=7,
                reason="Order stock deduction",
                source_type="order",
                source_id=42,
                source_order_no=ORDER_NO,
            ),
        },
    ],
)
def test_adjustment_response_rejects_mismatched_transaction(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InventoryAdjustmentOut.model_validate(payload)
