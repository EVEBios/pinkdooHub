"""Product 组合响应的错误路径与嵌套契约测试。"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.common.constants.inventory import INVENTORY_STOCK_MAX
from app.common.pagination import Page
from app.schemas.product_response import (
    AdminExperienceProductDetailOut,
    AdminKitProductDetailOut,
    AdminProductListItemOut,
    ExperienceProductDetailOut,
    KitProductDetailOut,
    ProductListItemOut,
)
from tests.support.product_response import (
    PayloadFactory,
    ResponseSchema,
    admin_experience,
    admin_kit,
    admin_list_item,
    product_type,
    set_nested,
    user_experience,
    user_kit,
    user_list_item,
)


@pytest.mark.parametrize(
    "schema_type,payload_factory,wrong_type,wrong_label",
    [
        (
            ExperienceProductDetailOut,
            user_experience,
            "kit",
            "拼豆套装",
        ),
        (KitProductDetailOut, user_kit, "experience", "拼豆体验"),
        (
            AdminExperienceProductDetailOut,
            admin_experience,
            "kit",
            "拼豆套装",
        ),
        (
            AdminKitProductDetailOut,
            admin_kit,
            "experience",
            "拼豆体验",
        ),
    ],
)
def test_type_specific_detail_rejects_mismatched_product_type(
    schema_type: ResponseSchema,
    payload_factory: PayloadFactory,
    wrong_type: str,
    wrong_label: str,
) -> None:
    payload = payload_factory()
    payload["product_type"] = product_type(wrong_type, wrong_label)

    with pytest.raises(ValidationError) as exc_info:
        schema_type.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == ("product_type", "value")


@pytest.mark.parametrize(
    "path,value",
    [
        (("description",), "   "),
        (("images",), []),
        (("dimensions", "durations"), []),
        (("dimensions", "participants"), []),
        (("dimensions", "day_types"), []),
        (("options",), []),
        (("options", 0, "images"), []),
    ],
)
def test_user_experience_rejects_incomplete_online_data(
    path: tuple[str | int, ...], value: Any
) -> None:
    payload = user_experience()
    set_nested(payload, path, value)

    with pytest.raises(ValidationError) as exc_info:
        ExperienceProductDetailOut.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == path


@pytest.mark.parametrize(
    "path,value",
    [
        (("dimensions", "durations", 0, "value"), "60"),
        (("dimensions", "participants", 0, "value"), True),
        (("options", 0, "duration", "value"), "60"),
        (("options", 0, "participants", "value"), False),
        (("options", 0, "duration", "value"), 0),
        (("options", 0, "participants", "value"), 0),
    ],
)
def test_experience_integer_values_are_strict_positive_integers(
    path: tuple[str | int, ...], value: Any
) -> None:
    payload = user_experience()
    set_nested(payload, path, value)

    with pytest.raises(ValidationError) as exc_info:
        ExperienceProductDetailOut.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == path


@pytest.mark.parametrize(
    "field,value",
    [
        ("description", "   "),
        ("images", []),
        ("stock", -1),
        ("stock", True),
    ],
)
def test_user_kit_rejects_incomplete_or_invalid_fields(
    field: str, value: Any
) -> None:
    payload = user_kit()
    payload[field] = value

    with pytest.raises(ValidationError):
        KitProductDetailOut.model_validate(payload)


@pytest.mark.parametrize("stock,available", [(0, True), (1, False)])
def test_user_kit_rejects_inconsistent_availability(
    stock: int, available: bool
) -> None:
    payload = user_kit()
    payload["stock"] = stock
    payload["available"] = available

    with pytest.raises(ValidationError) as exc_info:
        KitProductDetailOut.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == ()


@pytest.mark.parametrize(
    "schema_type,payload_factory",
    [
        (KitProductDetailOut, user_kit),
        (AdminKitProductDetailOut, admin_kit),
    ],
)
def test_kit_details_reject_stock_above_inventory_limit(
    schema_type: ResponseSchema,
    payload_factory: PayloadFactory,
) -> None:
    payload = payload_factory()
    payload["stock"] = INVENTORY_STOCK_MAX + 1

    with pytest.raises(ValidationError) as exc_info:
        schema_type.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == ("stock",)


@pytest.mark.parametrize("field", ["cover_image", "display_price"])
def test_user_list_rejects_missing_online_summary_field(field: str) -> None:
    payload = user_list_item()
    payload[field] = None

    with pytest.raises(ValidationError):
        ProductListItemOut.model_validate(payload)


def test_page_preserves_nested_product_validation_location() -> None:
    valid_item = user_list_item()
    invalid_item = user_list_item()
    invalid_item["cover_image"] = None

    with pytest.raises(ValidationError) as exc_info:
        Page[ProductListItemOut].model_validate(
            {
                "items": [valid_item, invalid_item],
                "total": 2,
                "page": 1,
                "page_size": 20,
                "pages": 1,
            }
        )

    assert exc_info.value.errors()[0]["loc"] == (
        "items",
        1,
        "cover_image",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("cover_image", ""),
        ("cover_image", 1),
        ("display_price", "299.00"),
        ("updated_at", "2026-08-09T04:00:00Z"),
        ("is_deleted", 1),
    ],
)
def test_admin_list_rejects_invalid_summary_types(
    field: str, value: Any
) -> None:
    payload = admin_list_item()
    payload[field] = value

    with pytest.raises(ValidationError):
        AdminProductListItemOut.model_validate(payload)


@pytest.mark.parametrize(
    "schema_type,payload_factory,required_field",
    [
        (AdminExperienceProductDetailOut, admin_experience, "description"),
        (AdminExperienceProductDetailOut, admin_experience, "status"),
        (AdminExperienceProductDetailOut, admin_experience, "images"),
        (AdminExperienceProductDetailOut, admin_experience, "dimensions"),
        (AdminExperienceProductDetailOut, admin_experience, "options"),
        (AdminExperienceProductDetailOut, admin_experience, "created_at"),
        (AdminExperienceProductDetailOut, admin_experience, "updated_at"),
        (AdminExperienceProductDetailOut, admin_experience, "is_deleted"),
        (AdminKitProductDetailOut, admin_kit, "description"),
        (AdminKitProductDetailOut, admin_kit, "status"),
        (AdminKitProductDetailOut, admin_kit, "images"),
        (AdminKitProductDetailOut, admin_kit, "price"),
        (AdminKitProductDetailOut, admin_kit, "stock"),
        (AdminKitProductDetailOut, admin_kit, "created_at"),
        (AdminKitProductDetailOut, admin_kit, "updated_at"),
        (AdminKitProductDetailOut, admin_kit, "is_deleted"),
    ],
)
def test_admin_detail_requires_explicit_contract_fields(
    schema_type: ResponseSchema,
    payload_factory: PayloadFactory,
    required_field: str,
) -> None:
    payload = payload_factory()
    del payload[required_field]

    with pytest.raises(ValidationError) as exc_info:
        schema_type.model_validate(payload)

    assert exc_info.value.errors()[0]["loc"] == (required_field,)
