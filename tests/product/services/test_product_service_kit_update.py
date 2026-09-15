"""ProductService Kit 价格修改编排及事务测试。"""

import json
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


def _kit() -> SimpleNamespace:
    return SimpleNamespace(
        id=8,
        product_id=1,
        price=Decimal("599.00"),
        stock=20,
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


async def _update_price(service: ProductService) -> object:
    return await service.update_kit_price(
        1,
        price=Decimal("699.00"),
        operator_id=7,
        ip_address="127.0.0.1",
    )


@pytest.mark.parametrize(
    ("product", "expected_exception"),
    [
        (None, ProductNotFound),
        (
            _product(
                product_type=ProductType.EXPERIENCE,
                status=ProductStatus.ONLINE,
                is_deleted=True,
            ),
            ProductIsDeleted,
        ),
        (
            _product(
                product_type=ProductType.EXPERIENCE,
                status=ProductStatus.ONLINE,
            ),
            ProductTypeMismatch,
        ),
        (_product(status=ProductStatus.ONLINE), OnlineProductCannotBeModified),
    ],
)
async def test_price_update_rejects_invalid_product_before_kit_lookup(
    product: object | None,
    expected_exception: type[Exception],
) -> None:
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(expected_exception):
        await _update_price(service)

    repository.get_kit_by_product_id.assert_not_awaited()
    repository.update_kit.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_missing_kit_extension_uses_registered_40404() -> None:
    service, repository, audit_service = _service_with_mocks(_product())

    with pytest.raises(ProductKitNotFound):
        await _update_price(service)

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


async def test_update_failure_does_not_audit() -> None:
    service, repository, audit_service = _service_with_mocks(
        _product(),
        _kit(),
    )
    repository.update_kit.side_effect = RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        await _update_price(service)

    audit_service.log.assert_not_awaited()


async def test_kit_price_update_does_not_call_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = Mock()
    monkeypatch.setattr(ProductValidator, "validate_before_online", validate)
    service, _, _ = _service_with_mocks(_product(), _kit())

    await _update_price(service)

    validate.assert_not_called()


async def _create_real_kit() -> tuple[Product, ProductKit]:
    repository = ProductRepository()
    product = await repository.create_product(
        name="Kit 修改测试",
        product_type=ProductType.KIT,
        description=None,
    )
    kit = await repository.create_kit(
        product=product,
        price=Decimal("599.00"),
        stock=20,
    )
    return product, kit


async def test_real_price_update_preserves_stock() -> None:
    product, kit = await _create_real_kit()
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    result = await service.update_kit_price(
        product.id,
        price=Decimal("699.00"),
        operator_id=31,
        ip_address="127.0.0.1",
    )

    stored_kit = await ProductKit.get(id=kit.id)
    assert result.price == Decimal("699.00")
    assert stored_kit.price == Decimal("699.00")
    assert stored_kit.stock == 20
    audits = await AuditLog.filter(target_id=product.id).order_by("id")
    assert [audit.action for audit in audits] == ["UPDATE_PRICE"]


class _FailingAuditLogService(AuditLogService):
    async def log(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit failed")


async def test_real_audit_failure_rolls_back_price_update() -> None:
    product, kit = await _create_real_kit()
    service = ProductService(
        ProductRepository(),
        _FailingAuditLogService(AuditLogRepository()),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.update_kit_price(
            product.id,
            price=Decimal("799.00"),
            operator_id=31,
            ip_address="127.0.0.1",
        )

    stored = await ProductKit.get(id=kit.id)
    assert stored.price == Decimal("599.00")
    assert stored.stock == 20
    assert not await AuditLog.filter(target_id=product.id).exists()
