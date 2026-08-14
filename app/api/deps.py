"""API 依赖注入。

Depends 链式组合：

    HTTPBearer  →  get_current_user  →  get_current_admin  →  get_current_super_admin
    提取Token      验证JWT+查库         role >= ADMIN         role == SUPER_ADMIN

每一层只做一件事，外层层依赖内层，FastAPI 自动递归解析。
"""

from fastapi import Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.common.enums.user import UserRole
from app.core.config import settings
from app.core.exceptions import AuthenticationException, PermissionException
from app.core.security import decode_token
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import InventoryService
from app.services.order_service import OrderService
from app.services.product_service import ProductService
from app.storage.image import LocalImageStorage

security = HTTPBearer(auto_error=False)


async def reject_request_body(request: Request) -> None:
    """拒绝契约明确不接收 request body 的 mutation 请求。"""

    if await request.body():
        raise RequestValidationError(
            [
                {
                    "type": "extra_forbidden",
                    "loc": ("body",),
                    "msg": "Request body is not allowed",
                    "input": None,
                }
            ]
        )


def get_product_image_storage() -> LocalImageStorage:
    """组装 Product 本地图片存储适配器。"""

    return LocalImageStorage(
        root=settings.product_image_upload_dir,
        base_url=settings.product_image_base_url,
    )


def get_product_service(
    product_repository: ProductRepository = Depends(),
    audit_log_repository: AuditLogRepository = Depends(),
) -> ProductService:
    """组装 ProductService 及其 Repository/共享审计依赖。"""

    return ProductService(
        product_repository,
        AuditLogService(audit_log_repository),
    )


def get_order_service(
    order_repository: OrderRepository = Depends(),
    product_repository: ProductRepository = Depends(),
    inventory_repository: InventoryRepository = Depends(),
    audit_log_repository: AuditLogRepository = Depends(),
) -> OrderService:
    """组装 OrderService 及其数据访问与共享审计依赖。"""

    return OrderService(
        order_repository,
        product_repository,
        inventory_repository,
        AuditLogService(audit_log_repository),
    )


def get_inventory_service(
    inventory_repository: InventoryRepository = Depends(),
    product_repository: ProductRepository = Depends(),
    audit_log_repository: AuditLogRepository = Depends(),
) -> InventoryService:
    """组装 InventoryService 及其数据访问与共享审计依赖。"""

    return InventoryService(
        inventory_repository,
        product_repository,
        AuditLogService(audit_log_repository),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    user_repo: UserRepository = Depends(),
) -> User:
    """从 Authorization Header 解析 JWT，返回当前登录用户。"""
    if credentials is None:
        raise AuthenticationException(message="Authentication required")
    payload = decode_token(credentials.credentials, "access")
    user = await user_repo.get_by_id(int(payload["sub"]))
    if not user:
        from app.core.exceptions import NotFoundException
        raise NotFoundException(message="User not found")
    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """要求管理员及以上角色。"""
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise PermissionException(message="Admin access required")
    return current_user


async def get_current_super_admin(
    current_user: User = Depends(get_current_admin),
) -> User:
    """要求超级管理员角色。"""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise PermissionException(message="Super admin access required")
    return current_user
