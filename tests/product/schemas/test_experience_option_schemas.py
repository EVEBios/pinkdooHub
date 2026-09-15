"""Experience Option 请求 Schema 契约测试。"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.common.enums.product import DayType
from app.schemas.product import ExperienceOptionCreate, ExperienceOptionUpdate


class TestExperienceOptionCreate:
    """体验 Option 创建请求。"""

    def test_valid_request_supports_extensible_values(self) -> None:
        schema = ExperienceOptionCreate.model_validate(
            {
                "duration_minutes": 180,
                "participants": 3,
                "day_type": "holiday",
                "price": "899.00",
            }
        )

        assert schema.duration_minutes == 180
        assert schema.participants == 3
        assert schema.day_type == DayType.HOLIDAY
        assert schema.price == Decimal("899.00")

    @pytest.mark.parametrize(
        "missing_field",
        ["duration_minutes", "participants", "day_type", "price"],
    )
    def test_all_fields_are_required(self, missing_field: str) -> None:
        payload = {
            "duration_minutes": 120,
            "participants": 2,
            "day_type": "weekday",
            "price": "699.00",
        }
        payload.pop(missing_field)

        with pytest.raises(ValidationError) as exc_info:
            ExperienceOptionCreate.model_validate(payload)

        assert exc_info.value.errors()[0]["loc"] == (missing_field,)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("duration_minutes", 0),
            ("duration_minutes", -1),
            ("duration_minutes", True),
            ("duration_minutes", 60.0),
            ("duration_minutes", "60"),
            ("participants", 0),
            ("participants", -1),
            ("participants", True),
            ("participants", 2.0),
            ("participants", "2"),
            ("day_type", "weekend"),
            ("day_type", 1),
            ("price", 699.0),
        ],
    )
    def test_invalid_field_values_are_rejected(
        self, field: str, value: object
    ) -> None:
        payload = {
            "duration_minutes": 120,
            "participants": 2,
            "day_type": "weekday",
            "price": "699.00",
        }
        payload[field] = value

        with pytest.raises(ValidationError):
            ExperienceOptionCreate.model_validate(payload)

    @pytest.mark.parametrize(
        "field,value",
        [
            ("product_id", 1),
            ("images", []),
            ("is_deleted", False),
        ],
    )
    def test_server_controlled_or_related_fields_are_rejected(
        self, field: str, value: object
    ) -> None:
        payload = {
            "duration_minutes": 120,
            "participants": 2,
            "day_type": "weekday",
            "price": "699.00",
            field: value,
        }

        with pytest.raises(ValidationError) as exc_info:
            ExperienceOptionCreate.model_validate(payload)

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"


class TestExperienceOptionUpdate:
    """体验 Option PATCH 请求。"""

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"duration_minutes": 240}, {"duration_minutes": 240}),
            ({"participants": 4}, {"participants": 4}),
            ({"day_type": "holiday"}, {"day_type": DayType.HOLIDAY}),
            ({"price": "799.00"}, {"price": Decimal("799.00")}),
        ],
    )
    def test_single_field_update(
        self, payload: dict[str, object], expected: dict[str, object]
    ) -> None:
        schema = ExperienceOptionUpdate.model_validate(payload)

        assert schema.model_fields_set == set(payload)
        assert schema.model_dump(exclude_unset=True) == expected

    def test_multiple_field_update(self) -> None:
        schema = ExperienceOptionUpdate.model_validate(
            {
                "duration_minutes": 180,
                "participants": 3,
                "day_type": "holiday",
                "price": "899.00",
            }
        )

        assert schema.model_dump(exclude_unset=True) == {
            "duration_minutes": 180,
            "participants": 3,
            "day_type": DayType.HOLIDAY,
            "price": Decimal("899.00"),
        }

    def test_empty_body_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ExperienceOptionUpdate.model_validate({})

        assert exc_info.value.errors()[0]["type"] == "value_error"

    @pytest.mark.parametrize(
        "field",
        ["duration_minutes", "participants", "day_type", "price"],
    )
    def test_explicit_null_is_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ExperienceOptionUpdate.model_validate({field: None})

        assert exc_info.value.errors()[0]["loc"] == (field,)

    @pytest.mark.parametrize(
        "payload",
        [
            {"duration_minutes": 0},
            {"duration_minutes": True},
            {"participants": 0},
            {"participants": "2"},
            {"day_type": "weekend"},
            {"price": 799.0},
        ],
    )
    def test_invalid_update_values_are_rejected(
        self, payload: dict[str, object]
    ) -> None:
        with pytest.raises(ValidationError):
            ExperienceOptionUpdate.model_validate(payload)

    def test_related_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ExperienceOptionUpdate.model_validate(
                {"price": "799.00", "images": []}
            )

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
