"""ProductService Kit 价格与库存修改编排及事务测试。"""

import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import (
    OnlineProductCannotBeModified,
    ProductIsDeleted,
    ProductKitNotFound,
    ProductNotFound,
    ProductTypeMismatch,
)
from app.models.audit_log import AuditLog
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService
from app.validators.product_validator import ProductValidator


KitOperation = Callable[[ProductService], Awaitable[object]]


def _product(
    *,
    product_type: ProductType = ProductType.KIT,
    status: ProductStatus = ProductStatus.DRAFT,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        product_type=product_type,
        status=status,
        is_deleted=is_deleted,
    )


def _kit(
    *,
    price: Decimal = Decimal("599.00"),
    stock: int = 20,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=8,
        product_id=1,
        price=price,
        stock=stock,
    )


def _service_with_mocks(
    product: object | None,
    kit: object | None = None,
) -> tuple[ProductService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=ProductRepository)
    repository.get_product_by_id.return_value = product
    repository.get_kit_by_product_id.return_value = kit

    async def update_kit(target: object, **fields: object) -> object:
        for name, value in fields.items():
            if name != "using_db":
                setattr(target, name, value)
        return target

    repository.update_kit.side_effect = update_kit
    audit_service = AsyncMock(spec=AuditLogService)
    return ProductService(repository, audit_service), repository, audit_service


async def _update_price(
    service: ProductService,
    price: Decimal = Decimal("699.00"),
) -> object:
    return await service.update_kit_price(
        1,
        price=price,
        operator_id=7,
        ip_address="127.0.0.1",
    )


async def _update_stock(
    service: ProductService,
    stock: int = 35,
) -> object:
    return await service.update_kit_stock(
        1,
        stock=stock,
        operator_id=7,
        ip_address="127.0.0.1",
    )


@pytest.mark.parametrize("operation", [_update_price, _update_stock])
async def test_missing_product_is_rejected_before_kit_lookup(
    operation: KitOperation,
) -> None:
    service, repository, audit_service = _service_with_mocks(None)

    with pytest.raises(ProductNotFound):
        await operation(service)

    repository.get_product_by_id.assert_awaited_once_with(
        1,
        include_deleted=True,
    )
    repository.get_kit_by_product_id.assert_not_awaited()
    repository.update_kit.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("operation", [_update_price, _update_stock])
async def test_deleted_product_precedes_type_and_status(
    operation: KitOperation,
) -> None:
    product = _product(
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
        is_deleted=True,
    )
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(ProductIsDeleted):
        await operation(service)

    repository.get_kit_by_product_id.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("operation", [_update_price, _update_stock])
async def test_experience_product_returns_type_mismatch_before_status(
    operation: KitOperation,
) -> None:
    product = _product(
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
    )
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(ProductTypeMismatch) as caught:
        await operation(service)

    assert caught.value.data == {"expected": "kit", "actual": "experience"}
    repository.get_kit_by_product_id.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("operation", [_update_price, _update_stock])
async def test_online_kit_is_rejected_before_extension_lookup(
    operation: KitOperation,
) -> None:
    service, repository, audit_service = _service_with_mocks(
        _product(status=ProductStatus.ONLINE),
    )

    with pytest.raises(OnlineProductCannotBeModified):
        await operation(service)

    repository.get_kit_by_product_id.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("operation", [_update_price, _update_stock])
async def test_missing_kit_extension_uses_registered_40404(
    operation: KitOperation,
) -> None:
    service, repository, audit_service = _service_with_mocks(_product())

    with pytest.raises(ProductKitNotFound):
        await operation(service)

    repository.get_kit_by_product_id.assert_awaited_once_with(1)
    repository.update_kit.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_price_update_preserves_stock_and_writes_snapshot(
    status: ProductStatus,
) -> None:
    kit = _kit()
    service, repository, audit_service = _service_with_mocks(
        _product(status=status),
        kit,
    )

    result = await _update_price(service)

    assert result is kit
    assert result.price == Decimal("699.00")
    assert result.stock == 20
    update = repository.update_kit.await_args
    connection = update.kwargs["using_db"]
    assert update.args == (kit,)
    assert update.kwargs == {
        "price": Decimal("699.00"),
        "using_db": connection,
    }
    audit = audit_service.log.await_args.kwargs
    assert audit["action"] == "UPDATE_PRICE"
    assert audit["target_type"] == "product"
    assert audit["target_id"] == 1
    assert audit["using_db"] is connection
    assert json.loads(audit["description"]) == {
        "before": {"price": "599.00"},
        "after": {"price": "699.00"},
    }


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_stock_update_preserves_price_and_writes_snapshot(
    status: ProductStatus,
) -> None:
    kit = _kit()
    service, repository, audit_service = _service_with_mocks(
        _product(status=status),
        kit,
    )

    result = await _update_stock(service, stock=0)

    assert result is kit
    assert result.price == Decimal("599.00")
    assert result.stock == 0
    update = repository.update_kit.await_args
    connection = update.kwargs["using_db"]
    assert update.args == (kit,)
    assert update.kwargs == {"stock": 0, "using_db": connection}
    audit = audit_service.log.await_args.kwargs
    assert audit["action"] == "UPDATE_STOCK"
    assert audit["target_type"] == "product"
    assert audit["target_id"] == 1
    assert audit["using_db"] is connection
    assert json.loads(audit["description"]) == {
        "before": {"stock": 20},
        "after": {"stock": 0},
    }


@pytest.mark.parametrize("operation", [_update_price, _update_stock])
async def test_update_failure_does_not_audit(
    operation: KitOperation,
) -> None:
    service, repository, audit_service = _service_with_mocks(
        _product(),
        _kit(),
    )
    repository.update_kit.side_effect = RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        await operation(service)

    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("operation", [_update_price, _update_stock])
async def test_kit_update_does_not_call_validator(
    operation: KitOperation,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = Mock()
    monkeypatch.setattr(ProductValidator, "validate_before_online", validate)
    service, _, _ = _service_with_mocks(_product(), _kit())

    await operation(service)

    validate.assert_not_called()


async def _create_real_kit(
    *,
    status: ProductStatus = ProductStatus.DRAFT,
) -> tuple[Product, ProductKit]:
    repository = ProductRepository()
    product = await repository.create_product(
        name="Kit 修改测试",
        product_type=ProductType.KIT,
        description=None,
    )
    if status is not ProductStatus.DRAFT:
        await repository.update_product(product, status=status)
    kit = await repository.create_kit(
        product=product,
        price=Decimal("599.00"),
        stock=20,
    )
    return product, kit


async def test_real_price_and_stock_updates_preserve_other_field() -> None:
    product, kit = await _create_real_kit(status=ProductStatus.OFFLINE)
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    price_result = await service.update_kit_price(
        product.id,
        price=Decimal("699.00"),
        operator_id=31,
        ip_address="127.0.0.1",
    )
    stock_result = await service.update_kit_stock(
        product.id,
        stock=0,
        operator_id=31,
        ip_address="127.0.0.1",
    )

    stored_product = await Product.get(id=product.id)
    stored_kit = await ProductKit.get(id=kit.id)
    assert price_result.price == Decimal("699.00")
    assert stock_result.stock == 0
    assert stored_product.status is ProductStatus.OFFLINE
    assert stored_kit.price == Decimal("699.00")
    assert stored_kit.stock == 0
    audits = await AuditLog.filter(target_id=product.id).order_by("id")
    assert [audit.action for audit in audits] == ["UPDATE_PRICE", "UPDATE_STOCK"]
    assert json.loads(audits[0].description or "") == {
        "before": {"price": "599.00"},
        "after": {"price": "699.00"},
    }
    assert json.loads(audits[1].description or "") == {
        "before": {"stock": 20},
        "after": {"stock": 0},
    }


class _FailingAuditLogService(AuditLogService):
    async def log(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit failed")


@pytest.mark.parametrize("field", ["price", "stock"])
async def test_real_audit_failure_rolls_back_kit_update(field: str) -> None:
    product, kit = await _create_real_kit()
    service = ProductService(
        ProductRepository(),
        _FailingAuditLogService(AuditLogRepository()),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        if field == "price":
            await service.update_kit_price(
                product.id,
                price=Decimal("799.00"),
                operator_id=31,
                ip_address="127.0.0.1",
            )
        else:
            await service.update_kit_stock(
                product.id,
                stock=50,
                operator_id=31,
                ip_address="127.0.0.1",
            )

    stored = await ProductKit.get(id=kit.id)
    assert stored.price == Decimal("599.00")
    assert stored.stock == 20
    assert not await AuditLog.filter(target_id=product.id).exists()
