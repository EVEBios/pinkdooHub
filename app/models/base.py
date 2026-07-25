"""BaseModel —— 所有数据模型的抽象基类。

所有业务表（User、Product、Order 等）继承 BaseModel，
自动获得 id、created_at、updated_at 三个公共字段。

规范：
    - 主键统一用 BigIntField(pk=True)
    - 创建时间由 ORM 自动填充（auto_now_add）
    - 更新时间由 ORM 自动维护（auto_now）
    - 枚举字段用 SmallIntField 存储，注释标注对应 Enum 类
"""

from tortoise import fields
from tortoise.models import Model


class BaseModel(Model):
    """抽象基类，不单独建表。"""

    id = fields.BigIntField(pk=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        abstract = True
