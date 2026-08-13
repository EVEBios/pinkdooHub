"""OrderService 创建校验、快照与重试归因的单元测试。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from tortoise.exceptions import IntegrityError

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.exceptions import (
    KitOrderingRequiresInventory,
    OrderOptionUnavailable,
    OrderProductUnavailable,
)
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderItemInput, OrderService


def _product(
    product_id: int,
    *,
    product_type: ProductType = ProductType.EXPERIENCE,
    status: ProductStatus = ProductStatus.ONLINE,
    is_deleted: bool = False,
    name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=product_id,
        product_type=product_type,
        status=status,
        is_deleted=is_deleted,
        name=name or f"数据库商品 {product_id}",
    )


def _option(
    option_id: int,
    product_id: int,
    *,
    is_deleted: bool = False,
    price: str = "199.90",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=option_id,
        product_id=product_id,
        is_deleted=is_deleted,
        duration=90,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal(price),
    )


def _service(
    *,
    products: list[object],
    options: list[object],
    order_number_generator: Mock | None = None,
) -> tuple[OrderService, AsyncMock, AsyncMock, AsyncMock, Mock]:
    order_repository = AsyncMock(spec=OrderRepository)
    product_repository = AsyncMock(spec=ProductRepository)
    product_repository.get_products_by_ids.return_value = products
    product_repository.get_options_by_ids.return_value = options
    audit_service = AsyncMock(spec=AuditLogService)
    generator = order_number_generator or Mock(
        return_value="OD00000000000000000000000001"
    )
    service = OrderService(
        order_repository,
        product_repository,
        audit_service,
        generator,
    )
    return service, order_repository, product_repository, audit_service, generator


async def test_create_builds_database_authoritative_snapshots_in_one_batch() -> None:
    """金额和全部展示快照只能取自批量加载的数据库聚合。"""

    products = [
        _product(1, name="权威体验 A"),
        _product(2, name="权威体验 B"),
    ]
    options = [
        _option(11, 1, price="199.90"),
        _option(22, 2, price="30.05"),
    ]
    service, order_repository, product_repository, audit_service, generator = (
        _service(products=products, options=options)
    )
    created = SimpleNamespace(id=51)
    loaded = SimpleNamespace(id=51, items=[object(), object()])
    order_repository.create_order.return_value = created
    order_repository.get_order_detail.return_value = loaded

    result = await service.create_order(
        user_id=7,
        items=[
            OrderItemInput(product_id=1, experience_option_id=11, quantity=2),
            OrderItemInput(product_id=2, experience_option_id=22, quantity=3),
        ],
        remark="客户只能提交备注",
        ip_address="2001:db8::1",
    )

    assert result is loaded
    product_repository.get_products_by_ids.assert_awaited_once_with({1, 2})
    product_repository.get_options_by_ids.assert_awaited_once_with({11, 22})
    generator.assert_called_once_with()
    create_kwargs = order_repository.create_order.await_args.kwargs
    assert create_kwargs["order_no"] == "OD00000000000000000000000001"
    assert create_kwargs["user_id"] == 7
    assert create_kwargs["total_amount"] == Decimal("489.95")
    assert create_kwargs["remark"] == "客户只能提交备注"

    item_kwargs = order_repository.bulk_create_items.await_args.kwargs
    assert item_kwargs["order"] is created
    assert item_kwargs["using_db"] is create_kwargs["using_db"]
    snapshots = item_kwargs["items"]
    assert [item.product_name for item in snapshots] == [
        "权威体验 A",
        "权威体验 B",
    ]
    assert [item.product_price for item in snapshots] == [
        Decimal("199.90"),
        Decimal("30.05"),
    ]
    assert [item.subtotal for item in snapshots] == [
        Decimal("399.80"),
        Decimal("90.15"),
    ]
    assert snapshots[0].option_duration_minutes == 90
    assert snapshots[0].option_participants == 2
    assert snapshots[0].option_day_type is DayType.HOLIDAY

    audit_kwargs = audit_service.log.await_args.kwargs
    assert audit_kwargs == {
        "operator_id": 7,
        "action": "CREATE_ORDER",
        "target_type": "order",
        "target_id": 51,
        "ip_address": "2001:db8::1",
        "description": '{"item_count":2,"total_amount":"489.95"}',
        "using_db": create_kwargs["using_db"],
    }
    order_repository.get_order_detail.assert_awaited_once_with(
        51,
        user_id=7,
        using_db=create_kwargs["using_db"],
    )


@pytest.mark.parametrize(
    ("product", "expected_exception"),
    [
        (None, OrderProductUnavailable),
        (_product(1, status=ProductStatus.DRAFT), OrderProductUnavailable),
        (_product(1, status=ProductStatus.OFFLINE), OrderProductUnavailable),
        (_product(1, is_deleted=True), OrderProductUnavailable),
    ],
)
async def test_create_rejects_unavailable_product_before_writes(
    product: SimpleNamespace | None,
    expected_exception: type[Exception],
) -> None:
    """不存在、删除或非 Online Product 均在事务前失败。"""

    service, order_repository, _, audit_service, generator = _service(
        products=[] if product is None else [product],
        options=[_option(11, 1)],
    )

    with pytest.raises(expected_exception):
        await service.create_order(
            user_id=7,
            items=[OrderItemInput(1, 11, 1)],
            remark=None,
            ip_address="127.0.0.1",
        )

    order_repository.create_order.assert_not_awaited()
    audit_service.log.assert_not_awaited()
    generator.assert_not_called()


async def test_kit_boundary_precedes_option_validation_even_when_deleted() -> None:
    """已识别的 Kit 优先返回 Phase 4.3 边界，不泄漏 Option 细节。"""

    kit = _product(
        1,
        product_type=ProductType.KIT,
        status=ProductStatus.OFFLINE,
        is_deleted=True,
    )
    service, order_repository, _, audit_service, generator = _service(
        products=[kit],
        options=[],
    )

    with pytest.raises(KitOrderingRequiresInventory) as caught:
        await service.create_order(
            user_id=7,
            items=[OrderItemInput(1, 999, 1)],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert caught.value.data == {"product_id": 1, "required_phase": "4.3"}
    order_repository.create_order.assert_not_awaited()
    audit_service.log.assert_not_awaited()
    generator.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [
        [],
        [_option(11, 1, is_deleted=True)],
        [_option(11, 2)],
    ],
)
async def test_create_rejects_unavailable_or_foreign_option(
    options: list[SimpleNamespace],
) -> None:
    """Option 不存在、已删除或归属错误使用同一不可用语义。"""

    service, order_repository, _, audit_service, generator = _service(
        products=[_product(1)],
        options=options,
    )

    with pytest.raises(OrderOptionUnavailable) as caught:
        await service.create_order(
            user_id=7,
            items=[OrderItemInput(1, 11, 1)],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert caught.value.data == {
        "product_id": 1,
        "experience_option_id": 11,
    }
    order_repository.create_order.assert_not_awaited()
    audit_service.log.assert_not_awaited()
    generator.assert_not_called()


async def test_first_invalid_item_wins_over_later_kit() -> None:
    """批量加载后仍按请求 Item 顺序返回首个稳定业务错误。"""

    service, *_ = _service(
        products=[
            _product(1),
            _product(2, product_type=ProductType.KIT),
        ],
        options=[_option(22, 2)],
    )

    with pytest.raises(OrderOptionUnavailable) as caught:
        await service.create_order(
            user_id=7,
            items=[
                OrderItemInput(1, 11, 1),
                OrderItemInput(2, 22, 1),
            ],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert caught.value.data["product_id"] == 1


async def test_non_order_number_integrity_error_is_not_retried() -> None:
    """非订单号约束错误保留根因，不被宽泛误判为可重试冲突。"""

    generator = Mock(return_value="OD00000000000000000000000001")
    service, order_repository, _, _, _ = _service(
        products=[_product(1)],
        options=[_option(11, 1)],
        order_number_generator=generator,
    )
    root_error = IntegrityError("another constraint failed")
    order_repository.create_order.side_effect = root_error
    order_repository.order_number_exists.return_value = False

    with pytest.raises(IntegrityError) as caught:
        await service.create_order(
            user_id=7,
            items=[OrderItemInput(1, 11, 1)],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert caught.value is root_error
    assert generator.call_count == 1
    order_repository.order_number_exists.assert_awaited_once_with(
        "OD00000000000000000000000001"
    )
