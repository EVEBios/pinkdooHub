"""OrderService 独立状态变迁用例的业务编排契约测试。"""

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.constants.order import (
    ORDER_AUDIT_ACTION_CANCEL,
    ORDER_AUDIT_ACTION_COMPLETE,
    ORDER_AUDIT_ACTION_MARK_PAID,
    ORDER_OPERATION_CANCEL,
    ORDER_OPERATION_COMPLETE,
    ORDER_OPERATION_MARK_PAID,
)
from app.common.enums.order import OrderStatus
from app.common.exceptions import OrderNotFound, OrderStatusConflict
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderService


def _service() -> tuple[OrderService, AsyncMock, AsyncMock]:
    order_repository = AsyncMock(spec=OrderRepository)
    audit_service = AsyncMock(spec=AuditLogService)
    service = OrderService(
        order_repository,
        AsyncMock(spec=ProductRepository),
        audit_service,
    )
    return service, order_repository, audit_service


@pytest.mark.parametrize(
    (
        "method_name",
        "identity_name",
        "required_status",
        "target_status",
        "operation",
        "audit_action",
        "visible_user_id",
    ),
    [
        (
            "cancel_order",
            "user_id",
            OrderStatus.PENDING,
            OrderStatus.CANCELLED,
            ORDER_OPERATION_CANCEL,
            ORDER_AUDIT_ACTION_CANCEL,
            7,
        ),
        (
            "mark_order_paid",
            "operator_id",
            OrderStatus.PENDING,
            OrderStatus.PAID,
            ORDER_OPERATION_MARK_PAID,
            ORDER_AUDIT_ACTION_MARK_PAID,
            None,
        ),
        (
            "complete_order",
            "operator_id",
            OrderStatus.PAID,
            OrderStatus.COMPLETED,
            ORDER_OPERATION_COMPLETE,
            ORDER_AUDIT_ACTION_COMPLETE,
            None,
        ),
    ],
)
async def test_status_use_cases_lock_validate_update_audit_and_reload(
    method_name: str,
    identity_name: str,
    required_status: OrderStatus,
    target_status: OrderStatus,
    operation: str,
    audit_action: str,
    visible_user_id: int | None,
) -> None:
    """每条公开用例固定目标状态，并在同一事务连接内完成全部步骤。"""

    service, repository, audit_service = _service()
    locked = SimpleNamespace(id=11, status=required_status)
    loaded = SimpleNamespace(id=11, status=target_status)
    repository.get_order_for_update.return_value = locked
    repository.get_order_by_id.return_value = loaded

    result = await getattr(service, method_name)(
        11,
        **{identity_name: 7, "ip_address": "2001:db8::7"},
    )

    assert result is loaded
    lock_kwargs = repository.get_order_for_update.await_args.kwargs
    connection = lock_kwargs["using_db"]
    repository.get_order_for_update.assert_awaited_once_with(
        11,
        user_id=visible_user_id,
        using_db=connection,
    )
    repository.update_status.assert_awaited_once_with(
        locked,
        status=target_status,
        using_db=connection,
    )
    audit_service.log.assert_awaited_once_with(
        operator_id=7,
        action=audit_action,
        target_type="order",
        target_id=11,
        ip_address="2001:db8::7",
        description=(
            '{"before_status":"'
            f"{required_status.name.lower()}"
            '","after_status":"'
            f"{target_status.name.lower()}"
            '"}'
        ),
        using_db=connection,
    )
    repository.get_order_by_id.assert_awaited_once_with(
        11,
        using_db=connection,
    )


@pytest.mark.parametrize(
    (
        "method_name",
        "identity_name",
        "current_status",
        "required_status",
        "operation",
    ),
    [
        (
            "cancel_order",
            "user_id",
            OrderStatus.PAID,
            OrderStatus.PENDING,
            ORDER_OPERATION_CANCEL,
        ),
        (
            "mark_order_paid",
            "operator_id",
            OrderStatus.CANCELLED,
            OrderStatus.PENDING,
            ORDER_OPERATION_MARK_PAID,
        ),
        (
            "complete_order",
            "operator_id",
            OrderStatus.PENDING,
            OrderStatus.PAID,
            ORDER_OPERATION_COMPLETE,
        ),
    ],
)
async def test_status_conflict_is_decided_after_lock_and_writes_nothing(
    method_name: str,
    identity_name: str,
    current_status: OrderStatus,
    required_status: OrderStatus,
    operation: str,
) -> None:
    """锁后最新状态不合法时返回精确冲突数据且不写审计。"""

    service, repository, audit_service = _service()
    repository.get_order_for_update.return_value = SimpleNamespace(
        id=11,
        status=current_status,
    )

    with pytest.raises(OrderStatusConflict) as caught:
        await getattr(service, method_name)(
            11,
            **{identity_name: 7, "ip_address": "127.0.0.1"},
        )

    assert caught.value.data == {
        "operation": operation,
        "current_status": current_status.name.lower(),
        "required_status": required_status.name.lower(),
    }
    repository.update_status.assert_not_awaited()
    repository.get_order_by_id.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize(
    ("method_name", "identity_name", "expected_user_id"),
    [
        ("cancel_order", "user_id", 7),
        ("mark_order_paid", "operator_id", None),
        ("complete_order", "operator_id", None),
    ],
)
async def test_missing_or_hidden_order_raises_before_any_write(
    method_name: str,
    identity_name: str,
    expected_user_id: int | None,
) -> None:
    """不存在及用户不可见订单统一由锁查询映射为 OrderNotFound。"""

    service, repository, audit_service = _service()
    repository.get_order_for_update.return_value = None

    with pytest.raises(OrderNotFound):
        await getattr(service, method_name)(
            404,
            **{identity_name: 7, "ip_address": "127.0.0.1"},
        )

    assert repository.get_order_for_update.await_args.kwargs["user_id"] == (
        expected_user_id
    )
    repository.update_status.assert_not_awaited()
    repository.get_order_by_id.assert_not_awaited()
    audit_service.log.assert_not_awaited()


def test_no_public_generic_status_mutator_or_target_status_parameter() -> None:
    """调用方只能选择独立用例，不能传入任意目标状态绕过状态机。"""

    assert not hasattr(OrderService, "update_order_status")
    for method_name in ("cancel_order", "mark_order_paid", "complete_order"):
        parameters = inspect.signature(getattr(OrderService, method_name)).parameters
        assert "status" not in parameters
        assert "target_status" not in parameters
