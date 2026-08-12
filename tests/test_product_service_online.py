"""ProductService 商品上架编排与事务契约测试。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.exceptions import (
    ProductAlreadyOnline,
    ProductIsDeleted,
    ProductNotFound,
    ProductNotReadyForOnline,
)
from app.models.audit_log import AuditLog
from app.models.product import Product
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService
from app.validators.product_validator import ProductValidator


def _complete_kit_product(
    *,
    product_id: int = 1,
    status: ProductStatus = ProductStatus.DRAFT,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=product_id,
        name="新手拼豆套装",
        description="包含材料与工具",
        product_type=ProductType.KIT,
        status=status,
        is_deleted=is_deleted,
        images=[SimpleNamespace(is_cover=True)],
        kit=SimpleNamespace(price=Decimal("99.00"), stock=10),
    )


def _service_with_mocks(
    product: object | None,
) -> tuple[ProductService, AsyncMock, AsyncMock]:
    product_repository = AsyncMock(spec=ProductRepository)
    product_repository.get_product_detail.return_value = product

    async def update_product(
        target: object,
        *,
        using_db: object,
        **fields: object,
    ) -> object:
        for name, value in fields.items():
            setattr(target, name, value)
        return target

    product_repository.update_product.side_effect = update_product
    audit_service = AsyncMock(spec=AuditLogService)
    return (
        ProductService(product_repository, audit_service),
        product_repository,
        audit_service,
    )


async def test_missing_product_is_rejected_before_write() -> None:
    service, repository, audit_service = _service_with_mocks(None)

    with pytest.raises(ProductNotFound):
        await service.online_product(
            404,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.get_product_detail.assert_awaited_once_with(
        404,
        include_deleted=True,
    )
    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_deleted_product_precedes_online_conflict() -> None:
    product = _complete_kit_product(
        status=ProductStatus.ONLINE,
        is_deleted=True,
    )
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(ProductIsDeleted):
        await service.online_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_already_online_product_is_rejected_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _complete_kit_product(status=ProductStatus.ONLINE)
    service, repository, audit_service = _service_with_mocks(product)
    validate = AsyncMock()
    monkeypatch.setattr(
        ProductValidator,
        "validate_before_online",
        validate,
    )

    with pytest.raises(ProductAlreadyOnline):
        await service.online_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    validate.assert_not_called()
    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_validator_failure_is_propagated_before_write() -> None:
    product = _complete_kit_product()
    product.description = None
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(ProductNotReadyForOnline) as exc_info:
        await service.online_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    assert exc_info.value.data == {
        "issues": ["product description is required"],
    }
    repository.update_product.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize(
    "initial_status",
    [ProductStatus.DRAFT, ProductStatus.OFFLINE],
)
async def test_success_updates_and_audits_with_same_transaction_connection(
    initial_status: ProductStatus,
) -> None:
    product = _complete_kit_product(status=initial_status)
    service, repository, audit_service = _service_with_mocks(product)

    result = await service.online_product(
        product.id,
        operator_id=17,
        ip_address="2001:db8::1",
    )

    assert result is product
    assert result.status is ProductStatus.ONLINE
    repository.update_product.assert_awaited_once()
    update_call = repository.update_product.await_args
    assert update_call.args == (product,)
    assert update_call.kwargs["status"] is ProductStatus.ONLINE
    connection = update_call.kwargs["using_db"]
    audit_service.log.assert_awaited_once_with(
        operator_id=17,
        action="ONLINE_PRODUCT",
        target_type="product",
        target_id=product.id,
        ip_address="2001:db8::1",
        using_db=connection,
    )


async def test_success_preserves_load_validate_update_audit_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _complete_kit_product()
    events: list[str] = []
    repository = AsyncMock(spec=ProductRepository)

    async def load(*args: object, **kwargs: object) -> object:
        events.append("load")
        return product

    async def update(
        target: object,
        **kwargs: object,
    ) -> object:
        events.append("update")
        target.status = kwargs["status"]
        return target

    async def audit(**kwargs: object) -> None:
        events.append("audit")

    repository.get_product_detail.side_effect = load
    repository.update_product.side_effect = update
    audit_service = AsyncMock(spec=AuditLogService)
    audit_service.log.side_effect = audit
    validate = Mock(side_effect=lambda target: events.append("validate"))
    monkeypatch.setattr(
        ProductValidator,
        "validate_before_online",
        validate,
    )
    service = ProductService(repository, audit_service)

    await service.online_product(
        product.id,
        operator_id=17,
        ip_address="127.0.0.1",
    )

    assert events == ["load", "validate", "update", "audit"]
    validate.assert_called_once_with(product)


async def test_update_failure_does_not_write_audit() -> None:
    product = _complete_kit_product()
    service, repository, audit_service = _service_with_mocks(product)
    repository.update_product.side_effect = RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        await service.online_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    audit_service.log.assert_not_awaited()


async def _create_complete_experience(
    *,
    status: ProductStatus = ProductStatus.DRAFT,
) -> Product:
    repository = ProductRepository()
    product = await repository.create_product(
        name="零基础拼豆体验",
        product_type=ProductType.EXPERIENCE,
        description="包含材料与现场指导",
    )
    if status is not ProductStatus.DRAFT:
        await repository.update_product(product, status=status)
    await repository.create_image(
        product=product,
        image_url="https://example.com/product-cover.png",
        is_cover=True,
    )
    option = await repository.create_option(
        product=product,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("39.00"),
    )
    await repository.create_image(
        product=product,
        experience_option=option,
        image_url="https://example.com/option.png",
    )
    return product


async def _create_complete_kit() -> Product:
    repository = ProductRepository()
    product = await repository.create_product(
        name="新手拼豆套装",
        product_type=ProductType.KIT,
        description="包含材料与基础工具",
    )
    await repository.create_image(
        product=product,
        image_url="https://example.com/kit-cover.png",
        is_cover=True,
    )
    await repository.create_kit(
        product=product,
        price=Decimal("99.00"),
        stock=0,
    )
    return product


@pytest.mark.parametrize(
    "product_factory",
    [_create_complete_experience, _create_complete_kit],
)
async def test_real_complete_aggregate_is_persisted_online_with_audit(
    product_factory: object,
) -> None:
    product = await product_factory()
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    result = await service.online_product(
        product.id,
        operator_id=31,
        ip_address="127.0.0.1",
    )

    assert result.status is ProductStatus.ONLINE
    stored = await Product.get(id=product.id)
    assert stored.status is ProductStatus.ONLINE
    audit = await AuditLog.get(
        action="ONLINE_PRODUCT",
        target_type="product",
        target_id=product.id,
    )
    assert audit.operator_id == 31
    assert audit.ip_address == "127.0.0.1"


class _FailingAuditLogService(AuditLogService):
    async def log(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit failed")


async def test_audit_failure_rolls_back_real_product_status() -> None:
    product = await _create_complete_experience()
    service = ProductService(
        ProductRepository(),
        _FailingAuditLogService(AuditLogRepository()),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.online_product(
            product.id,
            operator_id=31,
            ip_address="127.0.0.1",
        )

    stored = await Product.get(id=product.id)
    assert stored.status is ProductStatus.DRAFT
    assert not await AuditLog.filter(
        action="ONLINE_PRODUCT",
        target_id=product.id,
    ).exists()
