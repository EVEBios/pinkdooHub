"""Product 列表查询参数 Schema 契约测试。"""

import pytest
from pydantic import ValidationError

from app.common.enums.product import ProductStatus, ProductType
from app.schemas.product import AdminProductListQuery, ProductListQuery


class TestProductListQuery:
    """用户端商品列表查询参数。"""

    def test_defaults(self) -> None:
        schema = ProductListQuery.model_validate({})

        assert schema.page == 1
        assert schema.page_size == 20
        assert schema.product_type is None
        assert schema.keyword is None

    def test_query_strings_are_parsed_and_keyword_is_trimmed(self) -> None:
        schema = ProductListQuery.model_validate(
            {
                "page": "2",
                "page_size": "50",
                "product_type": "kit",
                "keyword": "  新手套装  ",
            }
        )

        assert schema.page == 2
        assert schema.page_size == 50
        assert schema.product_type == ProductType.KIT
        assert schema.keyword == "新手套装"

    @pytest.mark.parametrize("keyword", [None, "", "   "])
    def test_empty_keyword_is_normalized_to_none(
        self, keyword: str | None
    ) -> None:
        schema = ProductListQuery.model_validate({"keyword": keyword})

        assert schema.keyword is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"page": 0},
            {"page_size": 0},
            {"page_size": 101},
            {"product_type": "service"},
            {"product_type": ""},
            {"keyword": "a" * 101},
            {"keyword": 123},
        ],
    )
    def test_invalid_filters_are_rejected(
        self, payload: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError):
            ProductListQuery.model_validate(payload)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("status", "online"),
            ("include_deleted", "true"),
            ("sort_by", "created_at"),
        ],
    )
    def test_admin_or_unsupported_filters_are_rejected(
        self, field: str, value: object
    ) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ProductListQuery.model_validate({field: value})

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


class TestAdminProductListQuery:
    """管理端商品列表查询参数。"""

    def test_defaults(self) -> None:
        schema = AdminProductListQuery.model_validate({})

        assert schema.page == 1
        assert schema.page_size == 20
        assert schema.product_type is None
        assert schema.keyword is None
        assert schema.status is None
        assert schema.include_deleted is False

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("true", True),
            ("TRUE", True),
            (" false ", False),
            ("FALSE", False),
            (True, True),
            (False, False),
        ],
    )
    def test_include_deleted_accepts_only_explicit_booleans(
        self, raw: object, expected: bool
    ) -> None:
        schema = AdminProductListQuery.model_validate({"include_deleted": raw})

        assert schema.include_deleted is expected

    @pytest.mark.parametrize("raw", ["1", "0", "yes", "no", 1, 0, None])
    def test_ambiguous_include_deleted_values_are_rejected(self, raw: object) -> None:
        with pytest.raises(ValidationError):
            AdminProductListQuery.model_validate({"include_deleted": raw})

    def test_admin_filters_are_parsed(self) -> None:
        schema = AdminProductListQuery.model_validate(
            {
                "product_type": "experience",
                "status": "offline",
                "include_deleted": "true",
                "keyword": "  拼豆  ",
            }
        )

        assert schema.product_type == ProductType.EXPERIENCE
        assert schema.status == ProductStatus.OFFLINE
        assert schema.include_deleted is True
        assert schema.keyword == "拼豆"

    @pytest.mark.parametrize("status", ["deleted", "ONLINE", "", 1])
    def test_invalid_status_is_rejected(self, status: object) -> None:
        with pytest.raises(ValidationError):
            AdminProductListQuery.model_validate({"status": status})

    def test_unsupported_sort_filter_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AdminProductListQuery.model_validate({"sort_by": "created_at"})

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
