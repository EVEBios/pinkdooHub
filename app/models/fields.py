"""项目 Model 使用的自定义 ORM 字段。"""

from decimal import Decimal
from typing import Any

from tortoise import fields

from app.models.validators import MaxDecimalPlacesValidator


class StrictDecimalField(fields.DecimalField):
    """在 Tortoise 量化 Decimal 之前拒绝多余小数位。

    原生 ``DecimalField`` 会先按 ``decimal_places`` 量化，再运行字段校验器；
    直接挂精度校验器会遗漏被静默舍入的输入，因此必须在转换边界检查。
    """

    def to_python_value(self, value: Any) -> Decimal | None:
        if value is not None:
            MaxDecimalPlacesValidator(self.decimal_places)(value)
        return super().to_python_value(value)
