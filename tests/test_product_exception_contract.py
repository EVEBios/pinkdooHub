"""Product 上架完整性异常契约测试。"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.common.exceptions import ProductNotReadyForOnline
from app.core.exceptions import BusinessException, UnprocessableEntityException
from app.middleware.exception import register_exception_handlers


PRODUCT_NOT_READY_ISSUES = ["product description is required"]


def _create_exception_test_app() -> FastAPI:
    """创建只用于验证全局异常映射的最小 ASGI 应用。"""

    test_app = FastAPI()

    @test_app.get("/product-not-ready")
    async def raise_product_not_ready() -> None:
        raise ProductNotReadyForOnline(issues=PRODUCT_NOT_READY_ISSUES)

    @test_app.get("/ordinary-business-error")
    async def raise_ordinary_business_error() -> None:
        raise BusinessException(
            code=42201,
            message="Ordinary business error",
            data={"source": "test"},
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


def test_product_not_ready_exception_contract() -> None:
    """命名异常固定继承关系、错误码、消息和 issues 数据结构。"""

    exc = ProductNotReadyForOnline(issues=PRODUCT_NOT_READY_ISSUES)

    assert isinstance(exc, UnprocessableEntityException)
    assert isinstance(exc, BusinessException)
    assert exc.code == 42201
    assert exc.message == "Product is not ready to go online"
    assert exc.data == {"issues": ["product description is required"]}


@pytest.mark.parametrize("issues", [[], [""]])
def test_product_not_ready_rejects_invalid_issues(
    issues: list[str],
) -> None:
    with pytest.raises(
        ValueError,
        match="issues must contain non-empty strings",
    ):
        ProductNotReadyForOnline(issues=issues)


def test_product_not_ready_copies_issues() -> None:
    issues = ["product description is required"]
    exc = ProductNotReadyForOnline(issues=issues)

    issues.append("product cover image is required")

    assert exc.data == {"issues": ["product description is required"]}


async def test_product_not_ready_maps_to_http_422() -> None:
    """ProductNotReadyForOnline 通过全局中间件映射为 HTTP 422。"""

    response = await _get("/product-not-ready")

    assert response.status_code == 422
    assert response.json() == {
        "code": 42201,
        "message": "Product is not ready to go online",
        "data": {"issues": ["product description is required"]},
    }


async def test_business_exception_still_maps_to_http_400() -> None:
    """HTTP 状态按异常类型映射，不能根据 422xx 业务码推断。"""

    response = await _get("/ordinary-business-error")

    assert response.status_code == 400
    assert response.json() == {
        "code": 42201,
        "message": "Ordinary business error",
        "data": {"source": "test"},
    }
