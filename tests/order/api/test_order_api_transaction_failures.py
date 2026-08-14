"""Order API 事务故障、响应重载故障与订单号冲突的真实 HTTP 测试。"""

from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from tortoise.backends.base.client import BaseDBAsyncClient

from app.api.deps import get_order_service
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.main import app
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderService


def _headers(auth_user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_user['token']}"}


def _order_no(number: int) -> str:
    return f"OD{number:026d}"


async def _create_catalog() -> tuple[Product, ExperienceOption]:
    product = await Product.create(
        name="HTTP 事务故障体验",
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("25.00"),
    )
    return product, option


def _service(
    *,
    repository: OrderRepository | None = None,
    audit_service: AuditLogService | None = None,
    generator: Callable[[], str] | None = None,
) -> OrderService:
    kwargs: dict[str, object] = {}
    if generator is not None:
        kwargs["order_number_generator"] = generator
    return OrderService(
        repository or OrderRepository(),
        ProductRepository(),
        InventoryRepository(),
        audit_service or AuditLogService(AuditLogRepository()),
        **kwargs,
    )


async def _post_order(
    client: AsyncClient,
    auth_user: dict,
    product: Product,
    option: ExperienceOption,
) -> object:
    return await client.post(
        "/api/v1/orders",
        json={
            "items": [
                {
                    "product_id": product.id,
                    "experience_option_id": option.id,
                    "quantity": 2,
                }
            ]
        },
        headers=_headers(auth_user),
    )


class _FailAfterAudit(AuditLogService):
    async def log(
        self,
        operator_id: int,
        action: str,
        target_type: str,
        target_id: int,
        ip_address: str,
        description: str | None = None,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        await super().log(
            operator_id,
            action,
            target_type,
            target_id,
            ip_address,
            description,
            using_db=using_db,
        )
        raise RuntimeError("injected audit failure")


class _MissingCreateReloadRepository(OrderRepository):
    async def get_order_detail(
        self,
        order_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order | None:
        return None


class _MissingStatusReloadRepository(OrderRepository):
    async def get_order_by_id(
        self,
        order_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order | None:
        return None


@pytest.mark.parametrize("failure_stage", ["audit", "reload"])
async def test_create_http_failure_rolls_back_order_items_and_audit(
    client: AsyncClient,
    auth_user: dict,
    failure_stage: str,
) -> None:
    """即使故障发生在审计写入之后或最终重载处，HTTP 失败也不留半成品。"""

    product, option = await _create_catalog()
    if failure_stage == "audit":
        service = _service(
            audit_service=_FailAfterAudit(AuditLogRepository()),
            generator=lambda: _order_no(10),
        )
    else:
        service = _service(
            repository=_MissingCreateReloadRepository(),
            generator=lambda: _order_no(10),
        )
    app.dependency_overrides[get_order_service] = lambda: service
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as safe_client:
            response = await _post_order(safe_client, auth_user, product, option)
    finally:
        app.dependency_overrides.pop(get_order_service, None)

    assert response.status_code == 500
    assert response.json() == {
        "code": 500,
        "message": "Internal server error",
        "data": None,
    }
    assert await Order.all().count() == 0
    assert await OrderItem.all().count() == 0
    assert await AuditLog.filter(target_type="order").count() == 0


@pytest.mark.parametrize("failure_stage", ["audit", "reload"])
async def test_status_http_failure_restores_previous_status_and_audit(
    client: AsyncClient,
    auth_user: dict,
    failure_stage: str,
) -> None:
    """状态更新、审计和轻量响应重载属于同一个事务原子单元。"""

    owner = await User.get(id=auth_user["user"]["id"])
    order = await Order.create(
        order_no=_order_no(20),
        user=owner,
        total_amount=Decimal("25.00"),
        status=OrderStatus.PENDING,
    )
    if failure_stage == "audit":
        service = _service(
            audit_service=_FailAfterAudit(AuditLogRepository()),
        )
    else:
        service = _service(repository=_MissingStatusReloadRepository())
    app.dependency_overrides[get_order_service] = lambda: service
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as safe_client:
            response = await safe_client.patch(
                f"/api/v1/orders/{order.id}/cancel",
                headers=_headers(auth_user),
            )
    finally:
        app.dependency_overrides.pop(get_order_service, None)

    assert response.status_code == 500
    assert response.json()["code"] == 500
    await order.refresh_from_db()
    assert order.status == OrderStatus.PENDING
    assert await AuditLog.filter(target_type="order", target_id=order.id).count() == 0


async def test_order_number_collision_retries_through_http_with_fresh_transaction(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    owner = await User.get(id=auth_user["user"]["id"])
    product, option = await _create_catalog()
    collision = _order_no(30)
    fresh = _order_no(31)
    await Order.create(
        order_no=collision,
        user=owner,
        total_amount=Decimal("1.00"),
    )
    numbers = iter([collision, fresh])
    service = _service(generator=lambda: next(numbers))
    app.dependency_overrides[get_order_service] = lambda: service
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as safe_client:
            response = await _post_order(safe_client, auth_user, product, option)
    finally:
        app.dependency_overrides.pop(get_order_service, None)

    assert response.status_code == 201, response.text
    created = response.json()["data"]
    assert created["order_no"] == fresh
    assert created["total_amount"] == "50.00"
    assert await Order.all().count() == 2
    assert await OrderItem.filter(order_id=created["id"]).count() == 1
    assert await AuditLog.filter(
        target_type="order",
        target_id=created["id"],
        action="CREATE_ORDER",
    ).count() == 1


async def test_third_order_number_collision_returns_500_without_partial_http_write(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    owner = await User.get(id=auth_user["user"]["id"])
    product, option = await _create_catalog()
    collisions = [_order_no(number) for number in (40, 41, 42)]
    for order_no in collisions:
        await Order.create(
            order_no=order_no,
            user=owner,
            total_amount=Decimal("1.00"),
        )
    numbers = iter(collisions)
    service = _service(generator=lambda: next(numbers))
    app.dependency_overrides[get_order_service] = lambda: service
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as safe_client:
            response = await _post_order(safe_client, auth_user, product, option)
    finally:
        app.dependency_overrides.pop(get_order_service, None)

    assert response.status_code == 500
    assert response.json()["message"] == "Internal server error"
    assert await Order.all().count() == 3
    assert await OrderItem.all().count() == 0
    assert await AuditLog.filter(target_type="order").count() == 0
