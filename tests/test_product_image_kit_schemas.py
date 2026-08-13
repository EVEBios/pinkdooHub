"""Product 图片与 Kit 修改请求 Schema 契约测试。"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.product import KitPriceUpdate, KitStockUpdate, ProductImageUpdate


class TestProductImageUpdate:
    """商品图片 PATCH 请求。"""

    @pytest.mark.parametrize(
        "payload",
        [
            {"sort": 0},
            {"sort": 20},
            {"is_cover": True},
            {"sort": 0, "is_cover": True},
        ],
    )
    def test_valid_update(self, payload: dict[str, object]) -> None:
        schema = ProductImageUpdate.model_validate(payload)

        assert schema.model_fields_set == set(payload)
        assert schema.model_dump(exclude_unset=True) == payload

    def test_empty_body_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ProductImageUpdate.model_validate({})

        assert exc_info.value.errors()[0]["type"] == "value_error"

    @pytest.mark.parametrize("sort", [None, -1, True, False, 1.0, "1"])
    def test_invalid_sort_is_rejected(self, sort: object) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ProductImageUpdate.model_validate({"sort": sort})

        assert exc_info.value.errors()[0]["loc"] == ("sort",)

    @pytest.mark.parametrize("is_cover", [None, False, 1, 0, "true"])
    def test_is_cover_only_accepts_boolean_true(self, is_cover: object) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ProductImageUpdate.model_validate({"is_cover": is_cover})

        assert exc_info.value.errors()[0]["loc"] == ("is_cover",)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("image_url", "https://example.com/image.jpg"),
            ("file", "image.jpg"),
            ("experience_option_id", 1),
            ("is_deleted", False),
        ],
    )
    def test_non_editable_fields_are_rejected(
        self, field: str, value: object
    ) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ProductImageUpdate.model_validate({"sort": 0, field: value})

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"

    def test_openapi_declares_is_cover_as_true_only(self) -> None:
        schema = ProductImageUpdate.model_json_schema()
        is_cover_schema = schema["properties"]["is_cover"]

        assert {"const": True, "type": "boolean"} in is_cover_schema["anyOf"]


class TestKitPriceUpdate:
    """套装价格修改请求。"""

    def test_valid_price_is_converted_to_decimal(self) -> None:
        schema = KitPriceUpdate.model_validate({"price": "699.00"})

        assert schema.price == Decimal("699.00")
        assert schema.model_dump() == {"price": Decimal("699.00")}

    @pytest.mark.parametrize(
        "price",
        [None, 699, 699.0, Decimal("699.00"), "0", "100000.00", "1.001"],
    )
    def test_invalid_price_is_rejected(self, price: object) -> None:
        with pytest.raises(ValidationError):
            KitPriceUpdate.model_validate({"price": price})

    def test_extra_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            KitPriceUpdate.model_validate({"price": "699.00", "stock": 1})

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


class TestKitStockUpdate:
    """套装库存修改请求。"""

    @pytest.mark.parametrize("stock", [0, 1, 80])
    def test_valid_stock(self, stock: int) -> None:
        schema = KitStockUpdate.model_validate({"stock": stock})

        assert schema.stock == stock

    @pytest.mark.parametrize("stock", [None, -1, True, False, 1.0, "1"])
    def test_invalid_stock_is_rejected(self, stock: object) -> None:
        with pytest.raises(ValidationError):
            KitStockUpdate.model_validate({"stock": stock})

    def test_extra_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            KitStockUpdate.model_validate({"stock": 10, "price": "699.00"})

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
