"""Order 创建库存锁瞬态错误的完整事务重试契约。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from tortoise.exceptions import OperationalError

from app.repositories.inventory_repo import InventoryRepository
from app.repositories.order_repo import OrderItemCreateData, OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderItemInput, OrderService


def _service() -> OrderService:
    return OrderService(
        AsyncMock(spec=OrderRepository),
        AsyncMock(spec=ProductRepository),
        AsyncMock(spec=InventoryRepository),
        AsyncMock(spec=AuditLogService),
        user_repository=AsyncMock(spec=UserRepository),
        order_number_generator=Mock(return_value="OD00000000000000000000000001"),
    )


def _snapshot() -> OrderItemCreateData:
    return OrderItemCreateData(
        product_id=1,
        experience_option_id=None,
        option_duration_minutes=None,
        option_participants=None,
        option_day_type=None,
        product_name="重试 Kit",
        product_price=Decimal("10.00"),
        quantity=1,
        subtotal=Decimal("10.00"),
    )


@pytest.mark.parametrize("error_code", [1205, 1213])
async def test_retryable_lock_error_retries_same_order_write_set(
    error_code: int,
) -> None:
    service = _service()
    expected = SimpleNamespace(id=51)
    create_once = AsyncMock(
        side_effect=[OperationalError(error_code, "transient"), expected]
    )
    service._create_order_once = create_once  # type: ignore[method-assign]
    kwargs = {
        "order_no": "OD00000000000000000000000001",
        "user_id": 7,
        "snapshots": [_snapshot()],
        "kit_items": [OrderItemInput(1, None, 1)],
        "total_amount": Decimal("10.00"),
        "remark": None,
        "ip_address": "127.0.0.1",
        "audit_description": '{"item_count":1,"total_amount":"10.00"}',
    }

    result = await service._create_order_with_transient_retry(**kwargs)

    assert result is expected
    assert create_once.await_count == 2
    assert create_once.await_args_list[0].kwargs == kwargs
    assert create_once.await_args_list[1].kwargs == kwargs


async def test_retryable_lock_error_stops_after_three_transactions() -> None:
    service = _service()
    failure = OperationalError(1213, "deadlock")
    create_once = AsyncMock(side_effect=failure)
    service._create_order_once = create_once  # type: ignore[method-assign]

    with pytest.raises(OperationalError) as caught:
        await service._create_order_with_transient_retry(
            order_no="OD00000000000000000000000001",
            user_id=7,
            snapshots=[_snapshot()],
            kit_items=[OrderItemInput(1, None, 1)],
            total_amount=Decimal("10.00"),
            remark=None,
            ip_address="127.0.0.1",
            audit_description='{"item_count":1,"total_amount":"10.00"}',
        )

    assert caught.value is failure
    assert create_once.await_count == 3


async def test_non_retryable_database_error_is_not_retried() -> None:
    service = _service()
    failure = OperationalError(2006, "server gone")
    create_once = AsyncMock(side_effect=failure)
    service._create_order_once = create_once  # type: ignore[method-assign]

    with pytest.raises(OperationalError) as caught:
        await service._create_order_with_transient_retry(
            order_no="OD00000000000000000000000001",
            user_id=7,
            snapshots=[_snapshot()],
            kit_items=[OrderItemInput(1, None, 1)],
            total_amount=Decimal("10.00"),
            remark=None,
            ip_address="127.0.0.1",
            audit_description='{"item_count":1,"total_amount":"10.00"}',
        )

    assert caught.value is failure
    create_once.assert_awaited_once()


@pytest.mark.parametrize("error_code", [1205, 1213])
async def test_cancel_retryable_lock_error_retries_same_complete_use_case(
    error_code: int,
) -> None:
    service = _service()
    expected = SimpleNamespace(id=51)
    cancel_once = AsyncMock(
        side_effect=[OperationalError(error_code, "transient"), expected]
    )
    service._cancel_order_once = cancel_once  # type: ignore[method-assign]
    kwargs = {
        "order_id": 51,
        "user_id": 7,
        "ip_address": "127.0.0.1",
    }

    result = await service._cancel_order_with_transient_retry(**kwargs)

    assert result is expected
    assert cancel_once.await_count == 2
    assert cancel_once.await_args_list[0].kwargs == kwargs
    assert cancel_once.await_args_list[1].kwargs == kwargs


async def test_cancel_retryable_lock_error_stops_after_three_transactions() -> None:
    service = _service()
    failure = OperationalError(1213, "deadlock")
    cancel_once = AsyncMock(side_effect=failure)
    service._cancel_order_once = cancel_once  # type: ignore[method-assign]

    with pytest.raises(OperationalError) as caught:
        await service._cancel_order_with_transient_retry(
            order_id=51,
            user_id=7,
            ip_address="127.0.0.1",
        )

    assert caught.value is failure
    assert cancel_once.await_count == 3


async def test_cancel_non_retryable_database_error_is_not_retried() -> None:
    service = _service()
    failure = OperationalError(2006, "server gone")
    cancel_once = AsyncMock(side_effect=failure)
    service._cancel_order_once = cancel_once  # type: ignore[method-assign]

    with pytest.raises(OperationalError) as caught:
        await service._cancel_order_with_transient_retry(
            order_id=51,
            user_id=7,
            ip_address="127.0.0.1",
        )

    assert caught.value is failure
    cancel_once.assert_awaited_once()
