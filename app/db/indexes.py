"""跨数据库使用的自定义索引类型。"""

from tortoise.indexes import Index


class UniqueIndex(Index):
    """生成带稳定名称的唯一索引。

    Tortoise 的 ``unique_together`` 能表达联合唯一，但无法声明稳定名称；
    Product 数据库契约要求迁移、监控与故障排查统一使用固定索引名。
    """

    INDEX_TYPE = "UNIQUE"
