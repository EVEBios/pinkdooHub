"""ProductService 基础信息修改与逻辑删除契约测试。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import (
    OnlineProductCannotBeModified,
    ProductIsDeleted,
    ProductMustBeOfflineBeforeDelete,
    ProductNotFound,
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
    status: ProductStatus = ProductStatus.DRAFT,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        name="原名称",
        description="原描述",
        product_type=ProductType.KIT,
        status=status,
        is_deleted=is_deleted,
    )


def _service_with_mocks(
    product: object | None,
) -> tuple[ProductService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=ProductRepository)
    repository.get_product_by_id.return_value = product

    async def update_product(
        target: object,
        *,
        using_db: object,
        **fields: object,
    ) -> object:
        for name, value in fields.items():
            setattr(target, name, value)
        return target

    repository.update_product.side_effect = update_product
    audit_service = AsyncMock(spec=AuditLogService)
    return ProductService(repository, audit_service), repository, audit_service


@pytest.mark.parametrize("method_name", ["update_product", "delete_product"])
async def test_missing_product_is_rejected_before_write(
    method_name: str,
) -> None:
    service, repository, audit_service = _service_with_mocks(None)
    method = getattr(service, method_name)
    kwargs: dict[str, object] = {
        "operator_id": 7,
        "ip_address": "127.0.0.1",
    }
    if method_name == "update_product":
        kwargs["updates"] = {"name": "新名称"}

    with pytest.raises(ProductNotFound):
        await method(404, **kwargs)

    repository.get_product_by_id.assert_awaited_once_with(
        404,
        include_deleted=True,
    )
    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("method_name", ["update_product", "delete_product"])
async def test_deleted_product_precedes_status_conflict(
    method_name: str,
) -> None:
    product = _product(status=ProductStatus.ONLINE, is_deleted=True)
    service, repository, audit_service = _service_with_mocks(product)
    method = getattr(service, method_name)
    kwargs: dict[str, object] = {
        "operator_id": 7,
        "ip_address": "127.0.0.1",
    }
    if method_name == "update_product":
        kwargs["updates"] = {"name": "新名称"}

    with pytest.raises(ProductIsDeleted):
        await method(product.id, **kwargs)

    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_online_product_cannot_be_updated() -> None:
    product = _product(status=ProductStatus.ONLINE)
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(OnlineProductCannotBeModified):
        await service.update_product(
            product.id,
            updates={"name": "新名称"},
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_online_product_must_be_offline_before_delete() -> None:
    product = _product(status=ProductStatus.ONLINE)
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(ProductMustBeOfflineBeforeDelete):
        await service.delete_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_update_preserves_patch_fields_and_uses_shared_transaction(
    status: ProductStatus,
) -> None:
    product = _product(status=status)
    service, repository, audit_service = _service_with_mocks(product)

    result = await service.update_product(
        product.id,
        updates={"description": None},
        operator_id=17,
        ip_address="2001:db8::1",
    )

    assert result is product
    assert result.name == "原名称"
    assert result.description is None
    update_call = repository.update_product.await_args
    assert "name" not in update_call.kwargs
    assert update_call.kwargs["description"] is None
    connection = update_call.kwargs["using_db"]
    audit_service.log.assert_awaited_once_with(
        operator_id=17,
        action="UPDATE_PRODUCT",
        target_type="product",
        target_id=product.id,
        ip_address="2001:db8::1",
        using_db=connection,
    )


@pytest.mark.parametrize(
    "updates",
    [
        {},
        {"status": ProductStatus.ONLINE},
        {"name": "允许字段", "is_deleted": True},
    ],
)
async def test_update_rejects_empty_or_unsupported_fields_before_lookup(
    updates: dict[str, object],
) -> None:
    service, repository, audit_service = _service_with_mocks(_product())

    with pytest.raises(ValueError, match="updates must contain only"):
        await service.update_product(
            1,
            updates=updates,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.get_product_by_id.assert_not_awaited()
    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_delete_marks_only_product_and_preserves_status(
    status: ProductStatus,
) -> None:
    product = _product(status=status)
    service, repository, audit_service = _service_with_mocks(product)

    result = await service.delete_product(
        product.id,
        operator_id=18,
        ip_address="127.0.0.1",
    )

    assert result is product
    assert result.is_deleted is True
    assert result.status is status
    update_call = repository.update_product.await_args
    assert update_call.kwargs["is_deleted"] is True
    assert "status" not in update_call.kwargs
    connection = update_call.kwargs["using_db"]
    audit_service.log.assert_awaited_once_with(
        operator_id=18,
        action="DELETE_PRODUCT",
        target_type="product",
        target_id=product.id,
        ip_address="127.0.0.1",
        using_db=connection,
    )


@pytest.mark.parametrize("method_name", ["update_product", "delete_product"])
async def test_write_flows_do_not_call_validator(
    method_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = Mock()
    monkeypatch.setattr(ProductValidator, "validate_before_online", validate)
    product = _product()
    service, _, _ = _service_with_mocks(product)
    method = getattr(service, method_name)
    kwargs: dict[str, object] = {
        "operator_id": 7,
        "ip_address": "127.0.0.1",
    }
    if method_name == "update_product":
        kwargs["updates"] = {"name": "新名称"}

    await method(product.id, **kwargs)

    validate.assert_not_called()


@pytest.mark.parametrize("method_name", ["update_product", "delete_product"])
async def test_update_failure_does_not_write_audit(method_name: str) -> None:
    product = _product()
    service, repository, audit_service = _service_with_mocks(product)
    repository.update_product.side_effect = RuntimeError("update failed")
    method = getattr(service, method_name)
    kwargs: dict[str, object] = {
        "operator_id": 7,
        "ip_address": "127.0.0.1",
    }
    if method_name == "update_product":
        kwargs["updates"] = {"name": "新名称"}

    with pytest.raises(RuntimeError, match="update failed"):
        await method(product.id, **kwargs)

    audit_service.log.assert_not_awaited()


async def _create_kit_product(*, status: ProductStatus) -> Product:
    repository = ProductRepository()
    product = await repository.create_product(
        name="原名称",
        product_type=ProductType.KIT,
        description="原描述",
    )
    await repository.create_kit(
        product=product,
        price=Decimal("99.00"),
        stock=3,
    )
    if status is not ProductStatus.DRAFT:
        await repository.update_product(product, status=status)
    return product


async def test_real_update_persists_only_submitted_fields_and_audit() -> None:
    product = await _create_kit_product(status=ProductStatus.OFFLINE)
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    result = await service.update_product(
        product.id,
        updates={"description": None},
        operator_id=31,
        ip_address="127.0.0.1",
    )

    stored = await Product.get(id=product.id)
    assert result.description is None
    assert stored.name == "原名称"
    assert stored.description is None
    assert stored.status is ProductStatus.OFFLINE
    assert await AuditLog.filter(
        action="UPDATE_PRODUCT",
        target_id=product.id,
    ).exists()


async def test_real_delete_preserves_status_and_child_records() -> None:
    product = await _create_kit_product(status=ProductStatus.OFFLINE)
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    result = await service.delete_product(
        product.id,
        operator_id=32,
        ip_address="127.0.0.1",
    )

    stored = await Product.get(id=product.id)
    assert result.is_deleted is True
    assert stored.is_deleted is True
    assert stored.status is ProductStatus.OFFLINE
    assert await ProductKit.filter(product_id=product.id).exists()
    assert await AuditLog.filter(
        action="DELETE_PRODUCT",
        target_id=product.id,
    ).exists()


class _FailingAuditLogService(AuditLogService):
    async def log(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit failed")


@pytest.mark.parametrize("method_name", ["update_product", "delete_product"])
async def test_real_audit_failure_rolls_back_product_write(
    method_name: str,
) -> None:
    product = await _create_kit_product(status=ProductStatus.DRAFT)
    service = ProductService(
        ProductRepository(),
        _FailingAuditLogService(AuditLogRepository()),
    )
    method = getattr(service, method_name)
    kwargs: dict[str, object] = {
        "operator_id": 31,
        "ip_address": "127.0.0.1",
    }
    if method_name == "update_product":
        kwargs["updates"] = {"name": "不应提交"}

    with pytest.raises(RuntimeError, match="audit failed"):
        await method(product.id, **kwargs)

    stored = await Product.get(id=product.id)
    assert stored.name == "原名称"
    assert stored.is_deleted is False
    assert not await AuditLog.filter(target_id=product.id).exists()
