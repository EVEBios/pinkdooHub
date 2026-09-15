"""ProductService 商品下架编排与事务契约测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import (
    ProductAlreadyOffline,
    ProductIsDeleted,
    ProductNotFound,
)
from app.models.audit_log import AuditLog
from app.models.product import Product
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService
from app.validators.product_validator import ProductValidator


def _product(
    *,
    status: ProductStatus = ProductStatus.ONLINE,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
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


async def test_missing_product_is_rejected_before_write() -> None:
    service, repository, audit_service = _service_with_mocks(None)

    with pytest.raises(ProductNotFound):
        await service.offline_product(
            404,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.get_product_by_id.assert_awaited_once_with(
        404,
        include_deleted=True,
    )
    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_deleted_product_precedes_status_conflict() -> None:
    product = _product(
        status=ProductStatus.OFFLINE,
        is_deleted=True,
    )
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(ProductIsDeleted):
        await service.offline_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize(
    "status",
    [ProductStatus.DRAFT, ProductStatus.OFFLINE],
)
async def test_non_online_product_is_already_offline(
    status: ProductStatus,
) -> None:
    product = _product(status=status)
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(ProductAlreadyOffline):
        await service.offline_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_success_does_not_call_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _product()
    service, repository, audit_service = _service_with_mocks(product)
    validate = Mock()
    monkeypatch.setattr(
        ProductValidator,
        "validate_before_online",
        validate,
    )

    result = await service.offline_product(
        product.id,
        operator_id=17,
        ip_address="2001:db8::1",
    )

    assert result is product
    assert result.status is ProductStatus.OFFLINE
    validate.assert_not_called()
    repository.update_product.assert_awaited_once()
    update_call = repository.update_product.await_args
    connection = update_call.kwargs["using_db"]
    assert update_call.kwargs["status"] is ProductStatus.OFFLINE
    audit_service.log.assert_awaited_once_with(
        operator_id=17,
        action="OFFLINE_PRODUCT",
        target_type="product",
        target_id=product.id,
        ip_address="2001:db8::1",
        using_db=connection,
    )


async def test_update_failure_does_not_write_audit() -> None:
    product = _product()
    service, repository, audit_service = _service_with_mocks(product)
    repository.update_product.side_effect = RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        await service.offline_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    audit_service.log.assert_not_awaited()


async def test_success_preserves_load_update_audit_order() -> None:
    product = _product()
    events: list[str] = []
    repository = AsyncMock(spec=ProductRepository)

    async def load(*args: object, **kwargs: object) -> object:
        events.append("load")
        return product

    async def update(target: object, **kwargs: object) -> object:
        events.append("update")
        target.status = kwargs["status"]
        return target

    async def audit(**kwargs: object) -> None:
        events.append("audit")

    repository.get_product_by_id.side_effect = load
    repository.update_product.side_effect = update
    audit_service = AsyncMock(spec=AuditLogService)
    audit_service.log.side_effect = audit
    service = ProductService(repository, audit_service)

    await service.offline_product(
        product.id,
        operator_id=17,
        ip_address="127.0.0.1",
    )

    assert events == ["load", "update", "audit"]


async def _create_online_product() -> Product:
    repository = ProductRepository()
    return await repository.create_product(
        name="待下架商品",
        product_type=ProductType.KIT,
        description="下架不要求完整聚合",
        using_db=None,
    )


async def test_real_online_product_is_persisted_offline_with_audit() -> None:
    repository = ProductRepository()
    product = await _create_online_product()
    await repository.update_product(product, status=ProductStatus.ONLINE)
    service = ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )

    result = await service.offline_product(
        product.id,
        operator_id=31,
        ip_address="127.0.0.1",
    )

    assert result.status is ProductStatus.OFFLINE
    assert (await Product.get(id=product.id)).status is ProductStatus.OFFLINE
    audit = await AuditLog.get(
        action="OFFLINE_PRODUCT",
        target_id=product.id,
    )
    assert audit.operator_id == 31


class _FailingAuditLogService(AuditLogService):
    async def log(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit failed")


async def test_audit_failure_rolls_back_real_product_status() -> None:
    repository = ProductRepository()
    product = await _create_online_product()
    await repository.update_product(product, status=ProductStatus.ONLINE)
    service = ProductService(
        repository,
        _FailingAuditLogService(AuditLogRepository()),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.offline_product(
            product.id,
            operator_id=31,
            ip_address="127.0.0.1",
        )

    assert (await Product.get(id=product.id)).status is ProductStatus.ONLINE
    assert not await AuditLog.filter(
        action="OFFLINE_PRODUCT",
        target_id=product.id,
    ).exists()
