"""InventoryService MySQL 瞬态错误与唯一冲突归因测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tortoise.exceptions import IntegrityError, OperationalError

from app.common.exceptions import InventoryTransactionConflict
from app.models.inventory_transaction import InventoryTransaction
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import InventoryAdjustmentResult, InventoryService
from app.utils.database import get_database_error_code


def _result(*, replay: bool = False) -> InventoryAdjustmentResult:
    transaction = SimpleNamespace(
        id=11,
        product_id=5,
        after_quantity=15,
    )
    return InventoryAdjustmentResult(
        product_id=5,
        stock=15,
        transaction=transaction,  # type: ignore[arg-type]
        is_replay=replay,
    )


def _service() -> InventoryService:
    return InventoryService(
        AsyncMock(spec=InventoryRepository),
        AsyncMock(spec=ProductRepository),
        AsyncMock(spec=AuditLogService),
    )


async def _adjust(service: InventoryService) -> InventoryAdjustmentResult:
    return await service.adjust_stock(
        5,
        change=5,
        reason="采购入库",
        operator_id=7,
        ip_address="127.0.0.1",
        idempotency_key="retry-key",
    )


@pytest.mark.parametrize("error_code", [1205, 1213])
async def test_retryable_mysql_error_retries_entire_attempt(
    error_code: int,
) -> None:
    service = _service()
    expected = _result()
    service._adjust_once = AsyncMock(  # type: ignore[method-assign]
        side_effect=[OperationalError(error_code, "transient"), expected]
    )

    result = await _adjust(service)

    assert result is expected
    assert service._adjust_once.await_count == 2
    assert service._adjust_once.await_args_list[0] == (
        service._adjust_once.await_args_list[1]
    )


async def test_retryable_mysql_error_stops_after_three_attempts() -> None:
    service = _service()
    failure = OperationalError(1213, "deadlock")
    service._adjust_once = AsyncMock(  # type: ignore[method-assign]
        side_effect=failure
    )

    with pytest.raises(OperationalError) as caught:
        await _adjust(service)

    assert caught.value is failure
    assert service._adjust_once.await_count == 3


async def test_non_retryable_database_error_is_not_retried() -> None:
    service = _service()
    failure = OperationalError(2006, "server gone")
    service._adjust_once = AsyncMock(  # type: ignore[method-assign]
        side_effect=failure
    )

    with pytest.raises(OperationalError) as caught:
        await _adjust(service)

    assert caught.value is failure
    service._adjust_once.assert_awaited_once()


async def test_unique_race_returns_committed_identical_result() -> None:
    service = _service()
    failure = IntegrityError("duplicate idempotency key")
    replay = _result(replay=True)
    service._adjust_once = AsyncMock(  # type: ignore[method-assign]
        side_effect=failure
    )
    service._resolve_committed_idempotency = AsyncMock(  # type: ignore[method-assign]
        return_value=replay
    )

    result = await _adjust(service)

    assert result is replay
    service._resolve_committed_idempotency.assert_awaited_once_with(
        internal_key="inventory:admin:adjust:retry-key",
        product_id=5,
        change=5,
        reason="采购入库",
        operator_id=7,
    )


async def test_unrelated_integrity_error_preserves_original_exception() -> None:
    service = _service()
    failure = IntegrityError("operator foreign key failed")
    service._adjust_once = AsyncMock(  # type: ignore[method-assign]
        side_effect=failure
    )
    service._resolve_committed_idempotency = AsyncMock(  # type: ignore[method-assign]
        return_value=None
    )

    with pytest.raises(IntegrityError) as caught:
        await _adjust(service)

    assert caught.value is failure


async def test_unique_race_with_different_payload_returns_conflict() -> None:
    service = _service()
    service._adjust_once = AsyncMock(  # type: ignore[method-assign]
        side_effect=IntegrityError("duplicate")
    )
    service._resolve_committed_idempotency = AsyncMock(  # type: ignore[method-assign]
        side_effect=InventoryTransactionConflict()
    )

    with pytest.raises(InventoryTransactionConflict):
        await _adjust(service)


def test_database_error_code_walks_wrapped_exception_chain() -> None:
    driver_error = RuntimeError(1213, "deadlock")
    wrapped = OperationalError(driver_error)

    assert get_database_error_code(wrapped) == 1213
    assert get_database_error_code(OperationalError("unknown")) is None


def test_result_contract_uses_inventory_transaction_type_annotation() -> None:
    assert InventoryAdjustmentResult.__annotations__["transaction"] is (
        InventoryTransaction
    )
