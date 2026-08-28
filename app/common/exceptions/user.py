"""User 模块业务异常。

每个异常封装了错误码和默认消息，Service 层只需 raise，无需手写 code 和 message。

使用：
    raise UsernameAlreadyExists()
    raise PhoneAlreadyExists()
    raise UserNotFound()

中间件自动根据 code 映射 HTTP 状态码，读取 message 构造响应。
"""

from app.core.exceptions import BusinessException, PermissionException


class UserException(BusinessException):
    """User 模块异常基类。"""


class UsernameAlreadyExists(UserException):
    def __init__(self) -> None:
        super().__init__(code=1001, message="Username already exists")


class UserNotFound(UserException):
    def __init__(self) -> None:
        super().__init__(code=1002, message="User not found")


class IncorrectPassword(UserException):
    def __init__(self) -> None:
        super().__init__(code=1003, message="Incorrect password")


class OldPasswordIncorrect(UserException):
    def __init__(self) -> None:
        super().__init__(code=1004, message="Old password is incorrect")


class UserDisabled(UserException):
    def __init__(self) -> None:
        super().__init__(code=1005, message="User is disabled")


class TokenExpired(UserException):
    def __init__(self) -> None:
        super().__init__(code=1006, message="Token expired or invalid")


class PhoneAlreadyExists(UserException):
    def __init__(self) -> None:
        super().__init__(code=1007, message="Phone already exists")


class CannotDisableSelf(UserException):
    """管理员不能禁用自己的当前账号。"""

    def __init__(self) -> None:
        super().__init__(code=422, message="Cannot disable yourself")


class CannotDisableSuperAdmin(PermissionException):
    """ADMIN 不能禁用 SUPER_ADMIN。"""

    def __init__(self) -> None:
        super().__init__(message="Cannot disable super admin")
