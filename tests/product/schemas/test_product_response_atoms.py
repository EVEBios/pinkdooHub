"""Product 响应原子 Schema 契约测试。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from app.common.enums.product import DayType, ProductStatus
from app.schemas.product_response import (
    ExperienceDimensionsOut,
    ExperienceOptionBaseOut,
    ExperienceOptionOut,
    LabeledValue,
    OptionImageOut,
    ProductImageOut,
    ProductPriceOut,
)


class TestLabeledValue:
    """value-label 展示值对象。"""

    def test_enum_value_and_label_serialization(self) -> None:
        schema = LabeledValue[ProductStatus].model_validate(
            {"value": "online", "label": "  已上架  ", "internal": "ignored"}
        )

        assert schema.value == ProductStatus.ONLINE
        assert schema.label == "已上架"
        assert schema.model_dump(mode="json") == {
            "value": "online",
            "label": "已上架",
        }

    def test_open_integer_value(self) -> None:
        schema = LabeledValue[int].model_validate(
            {"value": 180, "label": "3小时"}
        )

        assert schema.model_dump() == {"value": 180, "label": "3小时"}

    @pytest.mark.parametrize("label", ["", "   ", None, 1])
    def test_invalid_label_is_rejected(self, label: object) -> None:
        with pytest.raises(ValidationError):
            LabeledValue[int].model_validate({"value": 60, "label": label})


class TestProductPriceOut:
    """Product 金额响应类型。"""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (Decimal("599"), "599.00"),
            (Decimal("599.0"), "599.00"),
            (Decimal("0.1"), "0.10"),
            (Decimal("99999.00"), "99999.00"),
        ],
    )
    def test_decimal_is_serialized_with_two_places(
        self, value: Decimal, expected: str
    ) -> None:
        adapter = TypeAdapter(ProductPriceOut)
        validated = adapter.validate_python(value)

        assert validated == value
        assert adapter.dump_python(validated) == expected
        assert adapter.dump_python(validated, mode="json") == expected

    @pytest.mark.parametrize(
        "value",
        [
            "599.00",
            599,
            599.0,
            Decimal("0"),
            Decimal("-1.00"),
            Decimal("100000.00"),
            Decimal("1.001"),
        ],
    )
    def test_invalid_internal_price_is_rejected(self, value: object) -> None:
        with pytest.raises(ValidationError):
            TypeAdapter(ProductPriceOut).validate_python(value)

    def test_serialization_schema_declares_fixed_string(self) -> None:
        schema = TypeAdapter(ProductPriceOut).json_schema(mode="serialization")

        assert schema["type"] == "string"
        assert schema["pattern"] == r"^\d+\.\d{2}$"


class TestImageOut:
    """Product 公共图片和 Option 专属图片响应。"""

    def test_product_image_reads_attributes_and_filters_internal_fields(self) -> None:
        source = SimpleNamespace(
            id=1,
            image_url="  https://example.com/product.jpg  ",
            is_cover=True,
            sort=0,
            product_id=10,
            is_deleted=False,
        )

        schema = ProductImageOut.model_validate(source)

        assert schema.model_dump() == {
            "id": 1,
            "image_url": "https://example.com/product.jpg",
            "is_cover": True,
            "sort": 0,
        }

    def test_option_image_never_returns_is_cover(self) -> None:
        schema = OptionImageOut.model_validate(
            {
                "id": 2,
                "image_url": "https://example.com/option.jpg",
                "is_cover": True,
                "sort": 10,
                "experience_option_id": 11,
            }
        )

        assert schema.model_dump() == {
            "id": 2,
            "image_url": "https://example.com/option.jpg",
            "sort": 10,
        }

    @pytest.mark.parametrize(
        "payload",
        [
            {"id": 0, "image_url": "x", "is_cover": True, "sort": 0},
            {"id": 1, "image_url": "", "is_cover": True, "sort": 0},
            {"id": 1, "image_url": "x", "is_cover": 1, "sort": 0},
            {"id": 1, "image_url": "x", "is_cover": True, "sort": True},
            {"id": 1, "image_url": "x", "is_cover": True, "sort": -1},
        ],
    )
    def test_invalid_product_image_is_rejected(
        self, payload: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError):
            ProductImageOut.model_validate(payload)


def _option_payload() -> dict[str, object]:
    return {
        "id": 11,
        "duration": {"value": 180, "label": "3小时"},
        "participants": {"value": 3, "label": "3人"},
        "day_type": {"value": "holiday", "label": "节假日"},
        "price": Decimal("899.0"),
    }


class TestExperienceOptionOut:
    """Experience Option 基础与完整响应。"""

    def test_base_response_serializes_nested_values_and_price(self) -> None:
        schema = ExperienceOptionBaseOut.model_validate(_option_payload())

        assert schema.model_dump(mode="json") == {
            "id": 11,
            "duration": {"value": 180, "label": "3小时"},
            "participants": {"value": 3, "label": "3人"},
            "day_type": {"value": "holiday", "label": "节假日"},
            "price": "899.00",
        }

    @pytest.mark.parametrize("price", ["899.00", 899.0, Decimal("1.001")])
    def test_invalid_internal_price_is_rejected(self, price: object) -> None:
        payload = _option_payload()
        payload["price"] = price

        with pytest.raises(ValidationError):
            ExperienceOptionBaseOut.model_validate(payload)

    def test_complete_response_requires_images_field(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ExperienceOptionOut.model_validate(_option_payload())

        assert exc_info.value.errors()[0]["loc"] == ("images",)

    def test_complete_response_allows_empty_images_and_filters_image_cover(self) -> None:
        empty_payload = {**_option_payload(), "images": []}
        empty_schema = ExperienceOptionOut.model_validate(empty_payload)

        assert empty_schema.images == []

        image_payload = {
            **_option_payload(),
            "images": [
                {
                    "id": 20,
                    "image_url": "https://example.com/option.jpg",
                    "is_cover": True,
                    "sort": 0,
                }
            ],
            "is_deleted": False,
        }
        image_schema = ExperienceOptionOut.model_validate(image_payload)

        assert image_schema.model_dump(mode="json")["images"] == [
            {
                "id": 20,
                "image_url": "https://example.com/option.jpg",
                "sort": 0,
            }
        ]


class TestExperienceDimensionsOut:
    """Experience 可选维度响应。"""

    def test_empty_dimensions_are_valid_for_incomplete_admin_product(self) -> None:
        schema = ExperienceDimensionsOut.model_validate(
            {"durations": [], "participants": [], "day_types": []}
        )

        assert schema.model_dump() == {
            "durations": [],
            "participants": [],
            "day_types": [],
        }

    def test_dimensions_serialize_value_labels(self) -> None:
        schema = ExperienceDimensionsOut.model_validate(
            {
                "durations": [{"value": 60, "label": "1小时"}],
                "participants": [{"value": 2, "label": "2人"}],
                "day_types": [
                    {"value": DayType.WEEKDAY, "label": "工作日"}
                ],
            }
        )

        assert schema.model_dump(mode="json") == {
            "durations": [{"value": 60, "label": "1小时"}],
            "participants": [{"value": 2, "label": "2人"}],
            "day_types": [{"value": "weekday", "label": "工作日"}],
        }

    def test_all_dimension_fields_are_required(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ExperienceDimensionsOut.model_validate(
                {"durations": [], "participants": []}
            )

        assert exc_info.value.errors()[0]["loc"] == ("day_types",)
