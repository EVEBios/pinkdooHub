"""业务异常体系。

所有异常继承自 AppException，由 middleware/exception.py 统一捕获
并转换为对应 HTTP 状态码的 JSON 响应。

异常层级：

    AppException（基类）
    ├── BusinessException        → 400  业务规则不满足
    ├── AuthenticationException  → 401  未登录 / Token 失效
    ├── PermissionException      → 403  已登录但权限不足
    └── NotFoundException        → 404  请求的资源不存在

使用方式（Service 层）：

    raise BusinessException(code=1001, message="Username already exists")
    raise AuthenticationException(message="Token expired")
    raise PermissionException(message="Admin access required")
    raise NotFoundException(message="Product not found")

禁止在 API 层 try/except 构造错误响应——抛出异常，中间件会自动处理。
"""


class AppException(Exception):
    """应用异常基类。

    所有业务异常的公共祖先，携带 code、message 和可选的 data。
    中间件根据异常类型映射 HTTP 状态码。
    """

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)


class BusinessException(AppException):
    """业务规则不满足 → HTTP 400。

    示例：
        raise BusinessException(code=1001, message="Username already exists")
        raise BusinessException(code=2002, message="Stock insufficient")
        raise BusinessException(code=3002, message="Order cannot be cancelled")
    """


class AuthenticationException(AppException):
    """未登录或 Token 失效 → HTTP 401。

    code 固定为 401，与 HTTP 语义一致。
    由认证中间件或 Service 层在 Token 验证失败时抛出。

    示例：
        raise AuthenticationException(message="Token has expired")
        raise AuthenticationException(message="Invalid credentials")
    """

    def __init__(self, message: str = "Authentication required", data: dict | None = None) -> None:
        super().__init__(code=401, message=message, data=data)


class PermissionException(AppException):
    """已登录但权限不足 → HTTP 403。

    code 固定为 403，与 HTTP 语义一致。
    由权限检查中间件或 Service 层在角色校验失败时抛出。

    示例：
        raise PermissionException(message="Admin access required")
        raise PermissionException(message="You can only modify your own profile")
    """

    def __init__(self, message: str = "Permission denied", data: dict | None = None) -> None:
        super().__init__(code=403, message=message, data=data)


class NotFoundException(AppException):
    """请求的资源不存在 → HTTP 404。

    code 固定为 404，与 HTTP 语义一致。
    由 Service 层在资源查找失败时抛出。

    示例：
        raise NotFoundException(message="User not found")
        raise NotFoundException(message="Product not found")
        raise NotFoundException(message="Order not found")
    """

    def __init__(self, message: str = "Resource not found", data: dict | None = None) -> None:
        super().__init__(code=404, message=message, data=data)
