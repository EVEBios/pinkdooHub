"""Product 写操作轻量响应 Schema 契约测试。"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.product_response import (
    DeletedResourceOut,
    ExperienceProductCreateOut,
    KitPriceOut,
    KitProductCreateOut,
    ProductBasicInfoOut,
    ProductOfflineOut,
    ProductOnlineOut,
)

NOW = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)


def _labeled(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}


@pytest.mark.parametrize(
    "schema_type,product_type,type_label",
    [
        (ExperienceProductCreateOut, "experience", "拼豆体验"),
        (KitProductCreateOut, "kit", "拼豆套装"),
    ],
)
def test_create_response_requires_expected_type_and_draft_status(
    schema_type: type[ExperienceProductCreateOut | KitProductCreateOut],
    product_type: str,
    type_label: str,
) -> None:
    schema = schema_type.model_validate(
        {
            "id": 1,
            "name": "新商品",
            "product_type": _labeled(product_type, type_label),
            "status": _labeled("draft", "草稿"),
            "description": "not part of create response",
            "is_deleted": False,
        }
    )

    assert schema.model_dump(mode="json") == {
        "id": 1,
        "name": "新商品",
        "product_type": {"value": product_type, "label": type_label},
        "status": {"value": "draft", "label": "草稿"},
    }


@pytest.mark.parametrize(
    "schema_type,product_type",
    [
        (ExperienceProductCreateOut, "kit"),
        (KitProductCreateOut, "experience"),
    ],
)
def test_create_response_rejects_mismatched_product_type(
    schema_type: type[ExperienceProductCreateOut | KitProductCreateOut],
    product_type: str,
) -> None:
    with pytest.raises(ValidationError):
        schema_type.model_validate(
            {
                "id": 1,
                "name": "新商品",
                "product_type": _labeled(product_type, "错误类型"),
                "status": _labeled("draft", "草稿"),
            }
        )


@pytest.mark.parametrize("status", ["online", "offline"])
def test_create_response_rejects_non_draft_status(status: str) -> None:
    with pytest.raises(ValidationError):
        ExperienceProductCreateOut.model_validate(
            {
                "id": 1,
                "name": "新商品",
                "product_type": _labeled("experience", "拼豆体验"),
                "status": _labeled(status, "错误状态"),
            }
        )


def test_basic_info_response_keeps_nullable_description_and_timestamp() -> None:
    schema = ProductBasicInfoOut.model_validate(
        {
            "id": 1,
            "name": "新版拼豆体验",
            "description": None,
            "updated_at": NOW,
            "status": _labeled("draft", "草稿"),
        }
    )

    assert schema.model_dump(mode="json") == {
        "id": 1,
        "name": "新版拼豆体验",
        "description": None,
        "updated_at": "2026-08-09T08:00:00Z",
    }


@pytest.mark.parametrize(
    "schema_type,expected_status,wrong_status",
    [
        (ProductOnlineOut, "online", "offline"),
        (ProductOfflineOut, "offline", "online"),
    ],
)
def test_status_action_response_requires_exact_target_status(
    schema_type: type[ProductOnlineOut | ProductOfflineOut],
    expected_status: str,
    wrong_status: str,
) -> None:
    valid = schema_type.model_validate(
        {
            "id": 1,
            "status": _labeled(expected_status, "目标状态"),
        }
    )

    assert valid.status.value == expected_status

    with pytest.raises(ValidationError):
        schema_type.model_validate(
            {"id": 1, "status": _labeled(wrong_status, "错误状态")}
        )


@pytest.mark.parametrize("is_deleted", [False, 0, 1, "true", None])
def test_delete_response_only_accepts_boolean_true(is_deleted: object) -> None:
    with pytest.raises(ValidationError):
        DeletedResourceOut.model_validate({"id": 1, "is_deleted": is_deleted})


def test_delete_response_accepts_true_and_filters_internal_fields() -> None:
    schema = DeletedResourceOut.model_validate(
        {
            "id": 1,
            "is_deleted": True,
            "deleted_at": NOW,
            "product_id": 10,
        }
    )

    assert schema.model_dump() == {"id": 1, "is_deleted": True}


def test_kit_price_response_serializes_decimal_and_filters_stock() -> None:
    schema = KitPriceOut.model_validate(
        {"id": 2, "price": Decimal("699"), "stock": 80}
    )

    assert schema.model_dump(mode="json") == {"id": 2, "price": "699.00"}


@pytest.mark.parametrize("price", ["699.00", 699, 699.0])
def test_kit_price_response_rejects_non_decimal(price: object) -> None:
    with pytest.raises(ValidationError):
        KitPriceOut.model_validate({"id": 2, "price": price})
