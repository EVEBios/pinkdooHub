"""Product 创建与基本信息修改 Schema 契约测试。"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.product import (
    ExperienceProductCreate,
    KitProductCreate,
    ProductUpdate,
)


class TestExperienceProductCreate:
    """体验商品创建请求。"""

    def test_minimal_request_and_name_normalization(self) -> None:
        schema = ExperienceProductCreate.model_validate({"name": "  拼豆体验  "})

        assert schema.name == "拼豆体验"
        assert schema.description is None
        assert schema.model_fields_set == {"name"}

    @pytest.mark.parametrize("description", [None, "", "   "])
    def test_empty_description_is_normalized_to_none(
        self, description: str | None
    ) -> None:
        schema = ExperienceProductCreate.model_validate(
            {"name": "拼豆体验", "description": description}
        )

        assert schema.description is None
        assert "description" in schema.model_fields_set

    def test_description_is_trimmed(self) -> None:
        schema = ExperienceProductCreate.model_validate(
            {"name": "拼豆体验", "description": "  商品介绍  "}
        )

        assert schema.description == "商品介绍"

    def test_maximum_lengths_are_accepted(self) -> None:
        schema = ExperienceProductCreate.model_validate(
            {"name": "a" * 100, "description": "b" * 2000}
        )

        assert len(schema.name) == 100
        assert schema.description is not None
        assert len(schema.description) == 2000

    def test_overlong_description_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExperienceProductCreate.model_validate(
                {"name": "拼豆体验", "description": "a" * 2001}
            )

    @pytest.mark.parametrize("name", ["", "   ", "a" * 101, 123])
    def test_invalid_name_is_rejected(self, name: object) -> None:
        with pytest.raises(ValidationError):
            ExperienceProductCreate.model_validate({"name": name})

    @pytest.mark.parametrize(
        "field,value",
        [
            ("product_type", "experience"),
            ("status", "online"),
            ("price", "1.00"),
            ("stock", 1),
            ("options", []),
            ("images", []),
        ],
    )
    def test_server_controlled_or_related_fields_are_rejected(
        self, field: str, value: object
    ) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ExperienceProductCreate.model_validate(
                {"name": "拼豆体验", field: value}
            )

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


class TestKitProductCreate:
    """套装商品创建请求。"""

    def test_minimal_request(self) -> None:
        schema = KitProductCreate.model_validate(
            {"name": "新手拼豆套装", "price": "599.00"}
        )

        assert schema.price == Decimal("599.00")
        assert schema.stock == 0
        assert schema.description is None

    def test_price_is_required(self) -> None:
        with pytest.raises(ValidationError):
            KitProductCreate.model_validate({"name": "新手拼豆套装"})

    @pytest.mark.parametrize(
        ("raw_price", "expected"),
        [
            ("1", Decimal("1")),
            ("599.0", Decimal("599.0")),
            ("99999.00", Decimal("99999.00")),
            (" 599.00 ", Decimal("599.00")),
        ],
    )
    def test_valid_price_strings_are_converted_to_decimal(
        self, raw_price: str, expected: Decimal
    ) -> None:
        schema = KitProductCreate.model_validate(
            {"name": "新手拼豆套装", "price": raw_price}
        )

        assert schema.price == expected
        assert isinstance(schema.price, Decimal)

    @pytest.mark.parametrize(
        "price",
        [
            599,
            599.0,
            Decimal("599.00"),
            "",
            "0",
            "-1.00",
            "100000.00",
            "1.001",
            "1e2",
            "NaN",
        ],
    )
    def test_invalid_price_is_rejected(self, price: object) -> None:
        with pytest.raises(ValidationError):
            KitProductCreate.model_validate(
                {"name": "新手拼豆套装", "price": price}
            )

    @pytest.mark.parametrize("stock", [True, False, 1.0, "1", -1])
    def test_invalid_stock_is_rejected(self, stock: object) -> None:
        with pytest.raises(ValidationError):
            KitProductCreate.model_validate(
                {"name": "新手拼豆套装", "price": "599.00", "stock": stock}
            )

    def test_extra_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            KitProductCreate.model_validate(
                {
                    "name": "新手拼豆套装",
                    "price": "599.00",
                    "status": "online",
                }
            )

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"

    def test_openapi_declares_price_as_string(self) -> None:
        price_schema = KitProductCreate.model_json_schema()["properties"]["price"]

        assert price_schema["type"] == "string"
        assert price_schema["pattern"] == r"^\d+(?:\.\d{1,2})?$"


class TestProductUpdate:
    """商品基本信息 PATCH 请求。"""

    def test_name_only_update(self) -> None:
        schema = ProductUpdate.model_validate({"name": "  新版拼豆体验  "})

        assert schema.name == "新版拼豆体验"
        assert schema.description is None
        assert schema.model_fields_set == {"name"}
        assert schema.model_dump(exclude_unset=True) == {"name": "新版拼豆体验"}

    @pytest.mark.parametrize("description", [None, "", "   "])
    def test_explicit_empty_description_is_preserved_as_clear_operation(
        self, description: str | None
    ) -> None:
        schema = ProductUpdate.model_validate({"description": description})

        assert schema.description is None
        assert schema.model_fields_set == {"description"}
        assert schema.model_dump(exclude_unset=True) == {"description": None}

    def test_both_fields_update(self) -> None:
        schema = ProductUpdate.model_validate(
            {"name": "新版拼豆体验", "description": "新版介绍"}
        )

        assert schema.model_dump(exclude_unset=True) == {
            "name": "新版拼豆体验",
            "description": "新版介绍",
        }

    def test_empty_body_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ProductUpdate.model_validate({})

        assert exc_info.value.errors()[0]["type"] == "value_error"

    def test_explicit_null_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ProductUpdate.model_validate({"name": None})

        assert exc_info.value.errors()[0]["loc"] == ("name",)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("product_type", "kit"),
            ("status", "online"),
            ("price", "599.00"),
            ("stock", 10),
            ("is_deleted", True),
            ("images", []),
            ("options", []),
        ],
    )
    def test_non_basic_fields_are_rejected(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ProductUpdate.model_validate({"name": "商品", field: value})

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
