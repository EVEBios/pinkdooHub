"""Order 创建请求 Schema 契约测试。"""

import pytest
from pydantic import ValidationError

from app.common.constants.order import (
    ORDER_ITEM_QUANTITY_MAX,
    ORDER_ITEMS_MAX_COUNT,
    ORDER_REMARK_MAX_LENGTH,
)
from app.schemas.order import OrderCreate, OrderItemCreate


def _item(
    *,
    product_id: int = 1,
    option_id: int = 10,
    quantity: int = 1,
) -> dict[str, int]:
    return {
        "product_id": product_id,
        "experience_option_id": option_id,
        "quantity": quantity,
    }


def test_order_item_create_accepts_strict_valid_fields() -> None:
    schema = OrderItemCreate.model_validate(_item(quantity=99))

    assert schema.model_dump() == _item(quantity=99)


@pytest.mark.parametrize(
    "payload",
    [
        {"product_id": 1, "quantity": 2},
        {"product_id": 1, "experience_option_id": None, "quantity": 2},
    ],
)
def test_order_item_create_normalizes_kit_option_to_none(
    payload: dict[str, object],
) -> None:
    schema = OrderItemCreate.model_validate(payload)

    assert schema.experience_option_id is None
    assert schema.model_dump() == {
        "product_id": 1,
        "experience_option_id": None,
        "quantity": 2,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product_id", 0),
        ("product_id", -1),
        ("product_id", True),
        ("product_id", "1"),
        ("experience_option_id", 0),
        ("experience_option_id", False),
        ("experience_option_id", "10"),
        ("quantity", 0),
        ("quantity", ORDER_ITEM_QUANTITY_MAX + 1),
        ("quantity", True),
        ("quantity", "1"),
    ],
)
def test_order_item_create_rejects_invalid_identifiers_or_quantity(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = _item()
    payload[field] = value

    with pytest.raises(ValidationError) as exc_info:
        OrderItemCreate.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product_name", "伪造名称"),
        ("product_price", "1.00"),
        ("subtotal", "1.00"),
        ("stock", 10),
        ("internal", True),
    ],
)
def test_order_item_create_rejects_client_snapshot_or_internal_fields(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = _item()
    payload[field] = value

    with pytest.raises(ValidationError) as exc_info:
        OrderItemCreate.model_validate(payload)

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


def test_order_create_normalizes_remark_and_preserves_items() -> None:
    schema = OrderCreate.model_validate(
        {"items": [_item()], "remark": "  周五晚上到店  "}
    )

    assert schema.remark == "周五晚上到店"
    assert schema.model_dump() == {
        "items": [_item()],
        "remark": "周五晚上到店",
    }


@pytest.mark.parametrize("remark", [None, "", "   "])
def test_order_create_normalizes_missing_or_empty_remark(
    remark: str | None,
) -> None:
    schema = OrderCreate.model_validate(
        {"items": [_item()], "remark": remark}
    )

    assert schema.remark is None


@pytest.mark.parametrize(
    "items",
    [
        [],
        [_item(option_id=index + 1) for index in range(ORDER_ITEMS_MAX_COUNT + 1)],
    ],
)
def test_order_create_enforces_item_count(items: list[dict[str, int]]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        OrderCreate.model_validate({"items": items})

    assert exc_info.value.errors()[0]["loc"] == ("items",)


def test_order_create_rejects_duplicate_product_option_combination() -> None:
    with pytest.raises(ValidationError) as exc_info:
        OrderCreate.model_validate(
            {
                "items": [
                    _item(product_id=1, option_id=10, quantity=1),
                    _item(product_id=1, option_id=10, quantity=2),
                ]
            }
        )

    error = exc_info.value.errors()[0]
    assert error["loc"] == ()
    assert "Duplicate product and experience option" in error["msg"]


def test_order_create_rejects_duplicate_kit_product() -> None:
    with pytest.raises(ValidationError):
        OrderCreate.model_validate(
            {
                "items": [
                    {"product_id": 1, "quantity": 1},
                    {
                        "product_id": 1,
                        "experience_option_id": None,
                        "quantity": 2,
                    },
                ]
            }
        )


def test_order_create_allows_same_product_with_different_options() -> None:
    schema = OrderCreate.model_validate(
        {
            "items": [
                _item(product_id=1, option_id=10),
                _item(product_id=1, option_id=11),
            ]
        }
    )

    assert len(schema.items) == 2


def test_order_create_rejects_oversized_remark() -> None:
    with pytest.raises(ValidationError) as exc_info:
        OrderCreate.model_validate(
            {
                "items": [_item()],
                "remark": "注" * (ORDER_REMARK_MAX_LENGTH + 1),
            }
        )

    assert exc_info.value.errors()[0]["loc"] == ("remark",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("order_no", "OD01K2M7Y0J7A3N5Q8T4V6W9X2BC"),
        ("user_id", 7),
        ("total_amount", "1.00"),
        ("status", "pending"),
        ("created_at", "2026-08-13T00:00:00Z"),
    ],
)
def test_order_create_rejects_server_owned_fields(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {"items": [_item()], field: value}

    with pytest.raises(ValidationError) as exc_info:
        OrderCreate.model_validate(payload)

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
