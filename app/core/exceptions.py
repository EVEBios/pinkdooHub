"""业务异常类定义。

所有业务错误通过抛出 BusinessException 表达，
由 middleware/exception.py 中的全局异常处理器统一捕获并转换为 JSON 响应。
"""


class BusinessException(Exception):
    """业务异常，携带 code 和 message。

    Attributes:
        code: 业务错误码，见 docs/03_api/api_design_conventions.md §8
        message: 可读的错误描述（英文）
        data: 可选的附加数据（如字段级校验错误）
    """

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)
