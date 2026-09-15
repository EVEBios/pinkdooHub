"""跨 Product/Order 边界共享的拼豆颜色值规则。"""

import re

from app.common.constants.product import BEAD_COLOR_SWATCH_HEX_PATTERN


_SWATCH_HEX_REGEX = re.compile(BEAD_COLOR_SWATCH_HEX_PATTERN)


def normalize_bead_color_swatch_hex(value: object) -> str:
    """将输入规范化为大写 ``#RRGGBB``，并拒绝其他颜色写法。"""

    if not isinstance(value, str):
        raise ValueError("swatch_hex must be a string")
    normalized = value.strip().upper()
    if _SWATCH_HEX_REGEX.fullmatch(normalized) is None:
        raise ValueError("swatch_hex must use canonical #RRGGBB format")
    return normalized


def is_bead_color_configured(
    *,
    color_code: object,
    name: object,
    swatch_hex: object,
) -> bool:
    """判断颜色身份与数字色块是否完整且可用于销售链路。"""

    return (
        isinstance(color_code, str)
        and bool(color_code.strip())
        and isinstance(name, str)
        and bool(name.strip())
        and isinstance(swatch_hex, str)
        and _SWATCH_HEX_REGEX.fullmatch(swatch_hex) is not None
    )
