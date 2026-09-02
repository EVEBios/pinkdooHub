"""Product Mapper 原子映射测试。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.api.mappers.product import (
    map_day_type,
    map_duration,
    map_experience_dimensions,
    map_experience_option,
    map_experience_option_base,
    map_option_image,
    map_participants,
    map_product_image,
    map_product_image_by_owner,
    map_product_status,
    map_product_type,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.schemas.product_response import OptionImageOut, ProductImageOut


def _image(
    image_id: int,
    *,
    option_id: int | None,
    sort: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=image_id,
        image_url=f"https://cdn.example.com/{image_id}.jpg",
        experience_option_id=option_id,
        product_id=99,
        is_cover=option_id is None,
        sort=sort,
        is_deleted=False,
        password="must-not-leak",
    )


def _option(
    option_id: int,
    *,
    duration: int = 60,
    participants: int = 1,
    day_type: DayType = DayType.WEEKDAY,
    price: Decimal = Decimal("299.00"),
    images: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=option_id,
        product_id=99,
        duration=duration,
        participants=participants,
        day_type=day_type,
        price=price,
        images=[] if images is None else images,
        is_deleted=False,
        password="must-not-leak",
    )


@pytest.mark.parametrize(
    "mapper,value,expected",
    [
        (map_product_type, ProductType.EXPERIENCE, {"value": "experience", "label": "拼豆体验"}),
        (map_product_type, ProductType.KIT, {"value": "kit", "label": "拼豆套装"}),
        (map_product_status, ProductStatus.DRAFT, {"value": "draft", "label": "草稿"}),
        (map_product_status, ProductStatus.ONLINE, {"value": "online", "label": "已上架"}),
        (map_product_status, ProductStatus.OFFLINE, {"value": "offline", "label": "已下架"}),
        (map_day_type, DayType.WEEKDAY, {"value": "weekday", "label": "工作日"}),
        (map_day_type, DayType.HOLIDAY, {"value": "holiday", "label": "节假日"}),
    ],
)
def test_enum_mappers_use_authoritative_labels(mapper, value, expected) -> None:
    assert mapper(value).model_dump(mode="json") == expected


@pytest.mark.parametrize(
    "value,expected_label",
    [(60, "1小时"), (180, "3小时"), (90, "90分钟"), (540, "全天")],
)
def test_duration_mapper_supports_open_positive_values(
    value: int,
    expected_label: str,
) -> None:
    assert map_duration(value).model_dump() == {
        "value": value,
        "label": expected_label,
    }


def test_participants_mapper_supports_open_positive_values() -> None:
    assert map_participants(3).model_dump() == {"value": 3, "label": "3人"}


def test_image_mappers_whitelist_fields_and_select_schema_by_owner() -> None:
    public_image = _image(10, option_id=None)
    option_image = _image(20, option_id=11)

    public_out = map_product_image(public_image)
    option_out = map_option_image(option_image)

    assert isinstance(map_product_image_by_owner(public_image), ProductImageOut)
    assert isinstance(map_product_image_by_owner(option_image), OptionImageOut)
    assert public_out.model_dump(mode="json") == {
        "id": 10,
        "image_url": "https://cdn.example.com/10.jpg",
        "is_cover": True,
        "sort": 0,
    }
    assert option_out.model_dump(mode="json") == {
        "id": 20,
        "image_url": "https://cdn.example.com/20.jpg",
        "sort": 0,
    }


def test_image_mappers_reject_wrong_owner_kind() -> None:
    with pytest.raises(ValueError, match="public image"):
        map_product_image(_image(20, option_id=11))
    with pytest.raises(ValueError, match="option image"):
        map_option_image(_image(10, option_id=None))


def test_option_mappers_keep_images_only_in_full_response() -> None:
    option = _option(11, images=[_image(20, option_id=11)])

    base = map_experience_option_base(option).model_dump(mode="json")
    full = map_experience_option(option).model_dump(mode="json")

    assert base == {
        "id": 11,
        "duration": {"value": 60, "label": "1小时"},
        "participants": {"value": 1, "label": "1人"},
        "day_type": {"value": "weekday", "label": "工作日"},
        "price": "299.00",
    }
    assert full == {**base, "images": [{
        "id": 20,
        "image_url": "https://cdn.example.com/20.jpg",
        "sort": 0,
    }]}


def test_option_mapper_rejects_image_from_another_option() -> None:
    option = _option(11, images=[_image(20, option_id=12)])

    with pytest.raises(ValueError, match="different option"):
        map_experience_option(option)


def test_dimensions_are_deduplicated_and_stably_sorted() -> None:
    options = [
        _option(1, duration=120, participants=2, day_type=DayType.WEEKDAY),
        _option(2, duration=60, participants=3, day_type=DayType.HOLIDAY),
        _option(3, duration=120, participants=2, day_type=DayType.HOLIDAY),
    ]

    assert map_experience_dimensions(options).model_dump(mode="json") == {
        "durations": [
            {"value": 60, "label": "1小时"},
            {"value": 120, "label": "2小时"},
        ],
        "participants": [
            {"value": 2, "label": "2人"},
            {"value": 3, "label": "3人"},
        ],
        "day_types": [
            {"value": "weekday", "label": "工作日"},
            {"value": "holiday", "label": "节假日"},
        ],
    }
