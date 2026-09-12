"""Product 公共类型契约测试。"""

import json

from app.common.enums.product import DayType, ProductStatus, ProductType


def test_product_enum_values_match_api_contract() -> None:
    """Product 字符串枚举必须与 API/数据库约定完全一致。"""

    assert {item.value for item in ProductType} == {"experience", "kit"}
    assert {item.value for item in ProductStatus} == {
        "draft",
        "online",
        "offline",
    }
    assert {item.value for item in DayType} == {"weekday", "holiday"}


def test_product_enums_serialize_as_string_values() -> None:
    """str Enum 在 JSON 中直接输出契约 value，而不是 Python 成员名。"""

    payload = {
        "product_type": ProductType.EXPERIENCE,
        "status": ProductStatus.ONLINE,
        "day_type": DayType.WEEKDAY,
    }

    assert json.loads(json.dumps(payload)) == {
        "product_type": "experience",
        "status": "online",
        "day_type": "weekday",
    }
