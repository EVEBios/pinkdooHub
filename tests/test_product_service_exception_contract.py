"""Product Service 资源与状态异常契约测试。"""

from collections.abc import Callable

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

import app.common.exceptions.product as product_exceptions
import app.core.exceptions as core_exceptions
from app.common.enums.product import DayType, ProductType
from app.middleware.exception import register_exception_handlers


def _exception_class(module: object, name: str) -> type[Exception]:
    """按契约名称读取异常类，使 Red 阶段保留每项独立失败信息。"""

    value = getattr(module, name)
    assert isinstance(value, type)
    assert issubclass(value, Exception)
    return value


def test_not_found_exception_accepts_stable_business_code() -> None:
    exc = core_exceptions.NotFoundException(
        code=40401,
        message="Product not found",
    )

    assert exc.code == 40401
    assert exc.message == "Product not found"
    assert exc.data is None


def test_not_found_exception_default_contract_remains_compatible() -> None:
    exc = core_exceptions.NotFoundException()

    assert exc.code == 404
    assert exc.message == "Resource not found"
    assert exc.data is None


def test_conflict_exception_contract() -> None:
    exception_class = _exception_class(
        core_exceptions,
        "ConflictException",
    )
    exc = exception_class(code=40901, message="Conflict")

    assert isinstance(exc, core_exceptions.BusinessException)
    assert exc.code == 40901
    assert exc.message == "Conflict"
    assert exc.data is None


def test_product_not_found_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ProductNotFound",
    )
    exc = exception_class()

    assert isinstance(exc, core_exceptions.NotFoundException)
    assert exc.code == 40401
    assert exc.message == "Product not found"
    assert exc.data is None


def test_product_is_deleted_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ProductIsDeleted",
    )
    exc = exception_class()

    conflict_class = _exception_class(
        core_exceptions,
        "ConflictException",
    )
    assert isinstance(exc, conflict_class)
    assert exc.code == 40903
    assert exc.message == "Product is deleted"
    assert exc.data is None


def test_product_already_online_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ProductAlreadyOnline",
    )
    exc = exception_class()

    conflict_class = _exception_class(
        core_exceptions,
        "ConflictException",
    )
    assert isinstance(exc, conflict_class)
    assert exc.code == 40901
    assert exc.message == "Product is already online"
    assert exc.data is None


def test_product_already_offline_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ProductAlreadyOffline",
    )
    exc = exception_class()

    conflict_class = _exception_class(
        core_exceptions,
        "ConflictException",
    )
    assert isinstance(exc, conflict_class)
    assert exc.code == 40902
    assert exc.message == "Product is already offline"
    assert exc.data is None


def test_product_must_be_offline_before_delete_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ProductMustBeOfflineBeforeDelete",
    )
    exc = exception_class()

    conflict_class = _exception_class(
        core_exceptions,
        "ConflictException",
    )
    assert isinstance(exc, conflict_class)
    assert exc.code == 40904
    assert exc.message == "Product must be offline before deletion"
    assert exc.data is None


def test_online_product_cannot_be_modified_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "OnlineProductCannotBeModified",
    )
    exc = exception_class()

    conflict_class = _exception_class(
        core_exceptions,
        "ConflictException",
    )
    assert isinstance(exc, conflict_class)
    assert exc.code == 40905
    assert exc.message == "Online product cannot be modified"
    assert exc.data is None


def test_product_type_mismatch_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ProductTypeMismatch",
    )
    exc = exception_class(
        expected=ProductType.EXPERIENCE,
        actual=ProductType.KIT,
    )

    assert isinstance(exc, core_exceptions.BusinessException)
    assert type(exc).__bases__ == (core_exceptions.BusinessException,)
    assert exc.code == 40001
    assert exc.message == "Product type does not match this operation"
    assert exc.data == {"expected": "experience", "actual": "kit"}


def test_experience_option_already_exists_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ExperienceOptionAlreadyExists",
    )
    exc = exception_class(
        duration_minutes=120,
        participants=2,
        day_type=DayType.HOLIDAY,
    )

    assert isinstance(exc, core_exceptions.ConflictException)
    assert exc.code == 40911
    assert exc.message == "Experience option already exists"
    assert exc.data == {
        "duration_minutes": 120,
        "participants": 2,
        "day_type": "holiday",
    }


def test_experience_option_not_found_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ExperienceOptionNotFound",
    )
    exc = exception_class()

    assert isinstance(exc, core_exceptions.NotFoundException)
    assert exc.code == 40402
    assert exc.message == "Experience option not found"
    assert exc.data is None


def test_experience_option_already_deleted_contract() -> None:
    exception_class = _exception_class(
        product_exceptions,
        "ExperienceOptionAlreadyDeleted",
    )
    exc = exception_class()

    assert isinstance(exc, core_exceptions.ConflictException)
    assert exc.code == 40912
    assert exc.message == "Experience option is already deleted"
    assert exc.data is None


def test_product_exceptions_use_http_semantic_bases_directly() -> None:
    assert not hasattr(product_exceptions, "ProductException")
    product_not_ready = product_exceptions.ProductNotReadyForOnline(
        issues=["product description is required"],
    )

    assert type(product_not_ready).__bases__ == (
        core_exceptions.UnprocessableEntityException,
    )


def _create_exception_test_app() -> FastAPI:
    test_app = FastAPI()

    routes: dict[str, Callable[[], Exception]] = {
        "/product-not-found": lambda: _exception_class(
            product_exceptions,
            "ProductNotFound",
        )(),
        "/product-is-deleted": lambda: _exception_class(
            product_exceptions,
            "ProductIsDeleted",
        )(),
        "/product-already-online": lambda: _exception_class(
            product_exceptions,
            "ProductAlreadyOnline",
        )(),
        "/product-must-be-offline-before-delete": lambda: _exception_class(
            product_exceptions,
            "ProductMustBeOfflineBeforeDelete",
        )(),
        "/online-product-cannot-be-modified": lambda: _exception_class(
            product_exceptions,
            "OnlineProductCannotBeModified",
        )(),
        "/product-type-mismatch": lambda: _exception_class(
            product_exceptions,
            "ProductTypeMismatch",
        )(
            expected=ProductType.EXPERIENCE,
            actual=ProductType.KIT,
        ),
        "/experience-option-already-exists": lambda: _exception_class(
            product_exceptions,
            "ExperienceOptionAlreadyExists",
        )(
            duration_minutes=120,
            participants=2,
            day_type=DayType.HOLIDAY,
        ),
        "/experience-option-not-found": lambda: _exception_class(
            product_exceptions,
            "ExperienceOptionNotFound",
        )(),
        "/experience-option-already-deleted": lambda: _exception_class(
            product_exceptions,
            "ExperienceOptionAlreadyDeleted",
        )(),
        "/ordinary-business-error": lambda: core_exceptions.BusinessException(
            code=40901,
            message="Ordinary business error",
        ),
    }

    for path, exception_factory in routes.items():
        async def raise_exception(
            factory: Callable[[], Exception] = exception_factory,
        ) -> None:
            raise factory()

        test_app.get(path)(raise_exception)

    register_exception_handlers(test_app)
    return test_app


async def _get(path: str) -> Response:
    transport = ASGITransport(
        app=_create_exception_test_app(),
        raise_app_exceptions=False,
    )
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        return await client.get(path)


async def test_product_not_found_maps_to_http_404() -> None:
    response = await _get("/product-not-found")

    assert response.status_code == 404
    assert response.json() == {
        "code": 40401,
        "message": "Product not found",
        "data": None,
    }


async def test_product_conflicts_map_to_http_409() -> None:
    deleted_response = await _get("/product-is-deleted")
    online_response = await _get("/product-already-online")

    assert deleted_response.status_code == 409
    assert deleted_response.json() == {
        "code": 40903,
        "message": "Product is deleted",
        "data": None,
    }
    assert online_response.status_code == 409
    assert online_response.json() == {
        "code": 40901,
        "message": "Product is already online",
        "data": None,
    }


async def test_update_and_delete_conflicts_map_to_http_409() -> None:
    delete_response = await _get(
        "/product-must-be-offline-before-delete",
    )
    update_response = await _get(
        "/online-product-cannot-be-modified",
    )

    assert delete_response.status_code == 409
    assert delete_response.json() == {
        "code": 40904,
        "message": "Product must be offline before deletion",
        "data": None,
    }
    assert update_response.status_code == 409
    assert update_response.json() == {
        "code": 40905,
        "message": "Online product cannot be modified",
        "data": None,
    }


async def test_option_create_business_errors_map_to_http_contracts() -> None:
    type_response = await _get("/product-type-mismatch")
    conflict_response = await _get("/experience-option-already-exists")

    assert type_response.status_code == 400
    assert type_response.json() == {
        "code": 40001,
        "message": "Product type does not match this operation",
        "data": {"expected": "experience", "actual": "kit"},
    }
    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "code": 40911,
        "message": "Experience option already exists",
        "data": {
            "duration_minutes": 120,
            "participants": 2,
            "day_type": "holiday",
        },
    }


async def test_option_resource_errors_map_to_http_contracts() -> None:
    missing_response = await _get("/experience-option-not-found")
    deleted_response = await _get("/experience-option-already-deleted")

    assert missing_response.status_code == 404
    assert missing_response.json() == {
        "code": 40402,
        "message": "Experience option not found",
        "data": None,
    }
    assert deleted_response.status_code == 409
    assert deleted_response.json() == {
        "code": 40912,
        "message": "Experience option is already deleted",
        "data": None,
    }


async def test_business_exception_with_409xx_code_still_maps_to_http_400(
) -> None:
    response = await _get("/ordinary-business-error")

    assert response.status_code == 400
    assert response.json() == {
        "code": 40901,
        "message": "Ordinary business error",
        "data": None,
    }
