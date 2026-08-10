"""Model 字段级通用校验器。"""

from decimal import Decimal

from tortoise.exceptions import ValidationError


class MaxDecimalPlacesValidator:
    """拒绝超过指定小数位数的 Decimal 值，避免数据库静默舍入。"""

    def __init__(self, decimal_places: int) -> None:
        self.decimal_places = decimal_places

    def __call__(self, value: int | float | Decimal) -> None:
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite():
            raise ValidationError("Decimal value must be finite")

        exponent = decimal_value.as_tuple().exponent
        if not isinstance(exponent, int):
            raise ValidationError("Decimal value must be finite")
        actual_places = max(-exponent, 0)
        if actual_places > self.decimal_places:
            raise ValidationError(
                f"Decimal places should be less or equal to {self.decimal_places}"
            )
