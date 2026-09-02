"""Inventory Enum、常量和命名异常契约测试。"""

from collections.abc import Callable
from enum import Enum

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.common.constants.inventory import (
    INVENTORY_ADMIN_IDEMPOTENCY_PREFIX,
    INVENTORY_AUDIT_ACTION_ADJUST,
    INVENTORY_AUDIT_TARGET_TYPE,
    INVENTORY_CHANGE_MAX,
    INVENTORY_CHANGE_MIN,
    INVENTORY_IDEMPOTENCY_KEY_MAX_LENGTH,
    INVENTORY_ORDER_DEDUCTION_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_DEDUCTION_REASON,
    INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_RESTORE_REASON,
    INVENTORY_REASON_MAX_LENGTH,
    INVENTORY_RETRYABLE_MYSQL_ERROR_CODES,
    INVENTORY_STOCK_MAX,
    INVENTORY_STOCK_MIN,
    INVENTORY_TRANSACTION_MAX_ATTEMPTS,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.exceptions import (
    InsufficientStock,
    InventoryBalanceExceeded,
    InventoryTransactionConflict,
)
from app.core.exceptions import ConflictException
from app.middleware.exception import register_exception_handlers


def test_inventory_string_enums_match_frozen_values() -> None:
    assert issubclass(InventoryTransactionType, str)
    assert issubclass(InventoryTransactionType, Enum)
    assert [item.value for item in InventoryTransactionType] == [
        "opening_balance",
        "admin_adjustment",
        "order_deduction",
        "order_cancellation_restore",
    ]
    assert [item.value for item in InventorySourceType] == [
        "migration",
        "admin",
        "order",
    ]


def test_inventory_constants_match_frozen_boundaries() -> None:
    assert INVENTORY_STOCK_MIN == 0
    assert INVENTORY_STOCK_MAX == 999_999
    assert INVENTORY_CHANGE_MIN == -999_999
    assert INVENTORY_CHANGE_MAX == 999_999
    assert INVENTORY_REASON_MAX_LENGTH == 256
    assert INVENTORY_IDEMPOTENCY_KEY_MAX_LENGTH == 128
    assert INVENTORY_ADMIN_IDEMPOTENCY_PREFIX == "inventory:admin:adjust:"
    assert INVENTORY_ORDER_DEDUCTION_IDEMPOTENCY_KEY.format(
        order_id=7,
        product_id=5,
    ) == "inventory:order:7:deduct:product:5"
    assert INVENTORY_ORDER_DEDUCTION_REASON == "Order stock deduction"
    assert INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY.format(
        order_id=7,
        product_id=5,
    ) == "inventory:order:7:restore:product:5"
    assert INVENTORY_ORDER_RESTORE_REASON == "Order cancellation stock restore"
    assert INVENTORY_TRANSACTION_MAX_ATTEMPTS == 3
    assert INVENTORY_RETRYABLE_MYSQL_ERROR_CODES == frozenset({1205, 1213})
    assert INVENTORY_AUDIT_TARGET_TYPE == "product"
    assert INVENTORY_AUDIT_ACTION_ADJUST == "ADJUST_INVENTORY"


def test_insufficient_stock_contract_does_not_expose_available_quantity() -> None:
    error = InsufficientStock(product_id=5, requested_quantity=3)

    assert isinstance(error, ConflictException)
    assert error.code == 40931
    assert error.message == "Insufficient stock"
    assert error.data == {"product_id": 5, "requested_quantity": 3}
    assert "available_quantity" not in error.data


@pytest.mark.parametrize(
    ("before", "change"),
    [(0, -1), (999_999, 1)],
)
def test_inventory_balance_exceeded_contract(before: int, change: int) -> None:
    error = InventoryBalanceExceeded(
        product_id=5,
        before_quantity=before,
        change_quantity=change,
    )

    assert isinstance(error, ConflictException)
    assert error.code == 40932
    assert error.message == "Inventory balance exceeds the allowed range"
    assert error.data == {
        "product_id": 5,
        "before_quantity": before,
        "change_quantity": change,
        "minimum": 0,
        "maximum": 999_999,
    }


def test_inventory_transaction_conflict_contract_has_no_data() -> None:
    error = InventoryTransactionConflict()

    assert isinstance(error, ConflictException)
    assert error.code == 40933
    assert error.message == (
        "Inventory idempotency key conflicts with another request"
    )
    assert error.data is None


@pytest.mark.parametrize(
    "factory",
    [
        lambda: InsufficientStock(product_id=True, requested_quantity=1),
        lambda: InsufficientStock(product_id=1, requested_quantity=0),
        lambda: InventoryBalanceExceeded(
            product_id=0,
            before_quantity=0,
            change_quantity=-1,
        ),
        lambda: InventoryBalanceExceeded(
            product_id=1,
            before_quantity=-1,
            change_quantity=-1,
        ),
        lambda: InventoryBalanceExceeded(
            product_id=1,
            before_quantity=5,
            change_quantity=1,
        ),
    ],
)
def test_inventory_exceptions_reject_incoherent_payloads(
    factory: Callable[[], Exception],
) -> None:
    with pytest.raises(ValueError):
        factory()


def _create_exception_app() -> FastAPI:
    app = FastAPI()

    @app.get("/insufficient")
    async def insufficient() -> None:
        raise InsufficientStock(product_id=5, requested_quantity=3)

    @app.get("/balance")
    async def balance() -> None:
        raise InventoryBalanceExceeded(
            product_id=5,
            before_quantity=0,
            change_quantity=-1,
        )

    @app.get("/conflict")
    async def conflict() -> None:
        raise InventoryTransactionConflict()

    register_exception_handlers(app)
    return app


async def _get(path: str) -> Response:
    transport = ASGITransport(
        app=_create_exception_app(),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.parametrize(
    ("path", "code"),
    [("/insufficient", 40931), ("/balance", 40932), ("/conflict", 40933)],
)
async def test_inventory_exceptions_map_to_http_409(
    path: str,
    code: int,
) -> None:
    response = await _get(path)

    assert response.status_code == 409
    assert response.json()["code"] == code
