"""Inventory 严格写请求、幂等键和查询 Schema 契约。"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.schemas.inventory import (
    InventoryAdjustmentCreate,
    InventoryIdempotencyKey,
    InventoryProductTransactionQuery,
    InventoryTransactionQuery,
)


def test_inventory_adjustment_accepts_boundaries_and_trims_reason() -> None:
    assert InventoryAdjustmentCreate.model_validate(
        {"change": -999_999, "reason": "  盘点损耗  "}
    ).model_dump() == {"change": -999_999, "reason": "盘点损耗"}
    assert InventoryAdjustmentCreate.model_validate(
        {"change": 999_999, "reason": "采购入库"}
    ).change == 999_999


@pytest.mark.parametrize(
    "payload",
    [
        {"change": 0, "reason": "盘点"},
        {"change": True, "reason": "盘点"},
        {"change": 1.0, "reason": "盘点"},
        {"change": "1", "reason": "盘点"},
        {"change": 1_000_000, "reason": "盘点"},
        {"change": 1, "reason": "   "},
        {"change": 1, "reason": "x" * 257},
        {"change": 1, "reason": "盘点", "stock": 10},
        {"change": 1, "reason": "盘点", "operator_id": 7},
        {"change": 1, "reason": "盘点", "transaction_type": "admin_adjustment"},
    ],
)
def test_inventory_adjustment_rejects_invalid_or_forged_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InventoryAdjustmentCreate.model_validate(payload)


def test_idempotency_key_trims_and_accepts_printable_ascii() -> None:
    adapter = TypeAdapter(InventoryIdempotencyKey)

    assert adapter.validate_python("  request key:123  ") == "request key:123"
    assert adapter.validate_python("x" * 128) == "x" * 128


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "x" * 129,
        "line\nbreak",
        "tab\tkey",
        "请求-1",
        123,
    ],
)
def test_idempotency_key_rejects_non_contract_values(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(InventoryIdempotencyKey).validate_python(value)


def test_inventory_query_parses_http_values_and_alias() -> None:
    query = InventoryTransactionQuery.model_validate(
        {
            "page": "2",
            "page_size": "50",
            "product_id": "5",
            "type": "order_deduction",
            "source_type": "order",
            "source_id": "42",
            "created_from": "2026-08-13T00:00:00Z",
            "created_to": "2026-08-14T00:00:00Z",
        }
    )

    assert query.page == 2
    assert query.page_size == 50
    assert query.product_id == 5
    assert query.transaction_type is InventoryTransactionType.ORDER_DEDUCTION
    assert query.source_type is InventorySourceType.ORDER
    assert query.source_id == 42
    assert query.model_dump()["transaction_type"] == (
        InventoryTransactionType.ORDER_DEDUCTION
    )


def test_product_query_does_not_accept_product_id_in_query_string() -> None:
    with pytest.raises(ValidationError):
        InventoryProductTransactionQuery.model_validate({"product_id": "5"})


def test_inventory_query_only_accepts_public_type_alias() -> None:
    with pytest.raises(ValidationError):
        InventoryTransactionQuery.model_validate(
            {"transaction_type": "admin_adjustment"}
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "unknown"},
        {"source_type": "unknown"},
        {"source_id": "42"},
        {"source_type": "admin", "source_id": "42"},
        {"product_id": True},
        {"created_from": "2026-08-13T08:00:00+08:00"},
        {
            "created_from": "2026-08-14T00:00:00Z",
            "created_to": "2026-08-13T00:00:00Z",
        },
        {"unknown": "value"},
    ],
)
def test_inventory_query_rejects_invalid_filters(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        InventoryTransactionQuery.model_validate(payload)


def test_inventory_query_accepts_utc_datetime_objects() -> None:
    query = InventoryTransactionQuery.model_validate(
        {
            "created_from": datetime(2026, 8, 13, tzinfo=timezone.utc),
            "created_to": datetime(
                2026,
                8,
                14,
                tzinfo=timezone(timedelta(0)),
            ),
        }
    )

    assert query.created_from is not None
    assert query.created_from.utcoffset() == timedelta(0)
