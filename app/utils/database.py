"""数据库驱动异常的无状态解析工具。"""


def get_database_error_code(exc: BaseException) -> int | None:
    """从 ORM/驱动异常参数及异常链中提取整数数据库错误码。"""

    pending: list[BaseException] = [exc]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        for arg in current.args:
            if type(arg) is int:
                return arg
            if isinstance(arg, BaseException):
                pending.append(arg)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return None
