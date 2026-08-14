"""Order 命名异常与全局 HTTP 映射契约测试。"""

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.common.enums.order import OrderStatus
from app.common.exceptions import (
    OrderNotFound,
    OrderOptionUnavailable,
    OrderProductUnavailable,
    OrderStatusConflict,
)
from app.core.exceptions import (
    BusinessException,
    ConflictException,
    NotFoundException,
    UnprocessableEntityException,
)
from app.middleware.exception import register_exception_handlers


def _create_exception_test_app() -> FastAPI:
    """创建只用于验证 Order 异常映射的最小 ASGI 应用。"""

    test_app = FastAPI()

    @test_app.get("/not-found")
    async def raise_not_found() -> None:
        raise OrderNotFound()

    @test_app.get("/status-conflict")
    async def raise_status_conflict() -> None:
        raise OrderStatusConflict(
            operation="complete",
            current_status=OrderStatus.PENDING,
            required_status=OrderStatus.PAID,
        )

    @test_app.get("/product-unavailable")
    async def raise_product_unavailable() -> None:
        raise OrderProductUnavailable(product_id=8)

    @test_app.get("/option-unavailable")
    async def raise_option_unavailable() -> None:
        raise OrderOptionUnavailable(
            product_id=8,
            experience_option_id=13,
        )


    register_exception_handlers(test_app)
    return test_app


async def _get(path: str) -> Response:
    transport = ASGITransport(
        app=_create_exception_test_app(),
        raise_app_exceptions=False,
    )
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_order_not_found_contract() -> None:
    exc = OrderNotFound()

    assert isinstance(exc, NotFoundException)
    assert not isinstance(exc, BusinessException)
    assert exc.code == 40411
    assert exc.message == "Order not found"
    assert exc.data is None


def test_order_status_conflict_contract() -> None:
    exc = OrderStatusConflict(
        operation="complete",
        current_status=OrderStatus.PENDING,
        required_status=OrderStatus.PAID,
    )

    assert isinstance(exc, ConflictException)
    assert isinstance(exc, BusinessException)
    assert exc.code == 40921
    assert exc.message == "Order status does not allow this operation"
    assert exc.data == {
        "operation": "complete",
        "current_status": "pending",
        "required_status": "paid",
    }


def test_order_product_unavailable_contract() -> None:
    exc = OrderProductUnavailable(product_id=8)

    assert isinstance(exc, UnprocessableEntityException)
    assert exc.code == 42231
    assert exc.message == "Order product is unavailable"
    assert exc.data == {"product_id": 8}


def test_order_option_unavailable_contract() -> None:
    exc = OrderOptionUnavailable(
        product_id=8,
        experience_option_id=13,
    )

    assert isinstance(exc, UnprocessableEntityException)
    assert exc.code == 42232
    assert exc.message == "Order experience option is unavailable"
    assert exc.data == {"product_id": 8, "experience_option_id": 13}

    missing = OrderOptionUnavailable(
        product_id=8,
        experience_option_id=None,
    )
    assert missing.data == {
        "product_id": 8,
        "experience_option_id": None,
    }


@pytest.mark.parametrize(
    ("path", "status_code", "payload"),
    [
        (
            "/not-found",
            404,
            {
                "code": 40411,
                "message": "Order not found",
                "data": None,
            },
        ),
        (
            "/status-conflict",
            409,
            {
                "code": 40921,
                "message": "Order status does not allow this operation",
                "data": {
                    "operation": "complete",
                    "current_status": "pending",
                    "required_status": "paid",
                },
            },
        ),
        (
            "/product-unavailable",
            422,
            {
                "code": 42231,
                "message": "Order product is unavailable",
                "data": {"product_id": 8},
            },
        ),
        (
            "/option-unavailable",
            422,
            {
                "code": 42232,
                "message": "Order experience option is unavailable",
                "data": {"product_id": 8, "experience_option_id": 13},
            },
        ),
    ],
)
async def test_order_exceptions_map_to_frozen_http_contract(
    path: str,
    status_code: int,
    payload: dict[str, object],
) -> None:
    response = await _get(path)

    assert response.status_code == status_code
    assert response.json() == payload


@pytest.mark.parametrize(
    "factory",
    [
        lambda: OrderProductUnavailable(product_id=-1),
        lambda: OrderOptionUnavailable(product_id=0, experience_option_id=1),
        lambda: OrderOptionUnavailable(product_id=1, experience_option_id=0),
    ],
)
def test_order_resource_exceptions_reject_invalid_ids(
    factory: Callable[[], Exception],
) -> None:
    with pytest.raises(ValueError, match="must be a positive integer"):
        factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: OrderStatusConflict(
            operation="",
            current_status=OrderStatus.PENDING,
            required_status=OrderStatus.PAID,
        ),
        lambda: OrderStatusConflict(
            operation="   ",
            current_status=OrderStatus.PENDING,
            required_status=OrderStatus.PAID,
        ),
        lambda: OrderStatusConflict(
            operation=1,  # type: ignore[arg-type]
            current_status=OrderStatus.PENDING,
            required_status=OrderStatus.PAID,
        ),
        lambda: OrderStatusConflict(
            operation="cancel",
            current_status=0,  # type: ignore[arg-type]
            required_status=OrderStatus.PENDING,
        ),
        lambda: OrderStatusConflict(
            operation="complete",
            current_status=OrderStatus.PAID,
            required_status=1,  # type: ignore[arg-type]
        ),
    ],
)
def test_order_status_conflict_rejects_invalid_payload(
    factory: Callable[[], Exception],
) -> None:
    with pytest.raises(ValueError):
        factory()
