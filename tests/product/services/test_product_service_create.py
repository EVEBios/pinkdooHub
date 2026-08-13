"""ProductService Experience/Kit 创建与事务契约测试。"""

from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from app.common.enums.product import ProductStatus, ProductType
from app.models.audit_log import AuditLog
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService
from app.validators.product_validator import ProductValidator


def _mock_service() -> tuple[ProductService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=ProductRepository)
    audit_service = AsyncMock(spec=AuditLogService)
    return ProductService(repository, audit_service), repository, audit_service


async def test_experience_create_uses_fixed_type_and_shared_transaction(
) -> None:
    service, repository, audit_service = _mock_service()
    product = Product(
        id=11,
        name="拼豆体验",
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.DRAFT,
        is_deleted=False,
    )
    repository.create_product.return_value = product

    result = await service.create_experience_product(
        name="拼豆体验",
        description=None,
        operator_id=7,
        ip_address="127.0.0.1",
    )

    assert result is product
    repository.create_product.assert_awaited_once()
    create_call = repository.create_product.await_args
    assert create_call.kwargs["product_type"] is ProductType.EXPERIENCE
    assert create_call.kwargs["name"] == "拼豆体验"
    assert create_call.kwargs["description"] is None
    connection = create_call.kwargs["using_db"]
    repository.create_kit.assert_not_awaited()
    audit_service.log.assert_awaited_once_with(
        operator_id=7,
        action="CREATE_PRODUCT",
        target_type="product",
        target_id=product.id,
        ip_address="127.0.0.1",
        using_db=connection,
    )


async def test_kit_create_uses_one_transaction_for_all_writes() -> None:
    service, repository, audit_service = _mock_service()
    product = Product(
        id=12,
        name="新手套装",
        product_type=ProductType.KIT,
        status=ProductStatus.DRAFT,
        is_deleted=False,
    )
    repository.create_product.return_value = product

    result = await service.create_kit_product(
        name="新手套装",
        description="包含材料",
        price=Decimal("99.00"),
        stock=0,
        operator_id=8,
        ip_address="2001:db8::1",
    )

    assert result is product
    product_call = repository.create_product.await_args
    connection = product_call.kwargs["using_db"]
    assert product_call.kwargs["product_type"] is ProductType.KIT
    repository.create_kit.assert_awaited_once_with(
        product=product,
        price=Decimal("99.00"),
        stock=0,
        using_db=connection,
    )
    audit_service.log.assert_awaited_once_with(
        operator_id=8,
        action="CREATE_PRODUCT",
        target_type="product",
        target_id=product.id,
        ip_address="2001:db8::1",
        using_db=connection,
    )


async def test_experience_audit_failure_propagates() -> None:
    service, repository, audit_service = _mock_service()
    repository.create_product.return_value = Product(
        id=11,
        name="体验",
        product_type=ProductType.EXPERIENCE,
    )
    audit_service.log.side_effect = RuntimeError("audit failed")

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.create_experience_product(
            name="体验",
            description=None,
            operator_id=7,
            ip_address="127.0.0.1",
        )


async def test_kit_extension_failure_does_not_write_audit() -> None:
    service, repository, audit_service = _mock_service()
    repository.create_product.return_value = Product(
        id=12,
        name="套装",
        product_type=ProductType.KIT,
    )
    repository.create_kit.side_effect = RuntimeError("kit failed")

    with pytest.raises(RuntimeError, match="kit failed"):
        await service.create_kit_product(
            name="套装",
            description=None,
            price=Decimal("99.00"),
            stock=0,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    audit_service.log.assert_not_awaited()


async def test_create_flows_do_not_call_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = Mock()
    monkeypatch.setattr(
        ProductValidator,
        "validate_before_online",
        validate,
    )
    repository = ProductRepository()
    service = ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )

    await service.create_experience_product(
        name="不完整体验草稿",
        description=None,
        operator_id=7,
        ip_address="127.0.0.1",
    )
    await service.create_kit_product(
        name="零库存套装草稿",
        description=None,
        price=Decimal("99.00"),
        stock=0,
        operator_id=7,
        ip_address="127.0.0.1",
    )

    validate.assert_not_called()


async def test_real_experience_create_persists_draft_and_audit() -> None:
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    product = await service.create_experience_product(
        name="真实体验草稿",
        description=None,
        operator_id=31,
        ip_address="127.0.0.1",
    )

    stored = await Product.get(id=product.id)
    assert stored.product_type is ProductType.EXPERIENCE
    assert stored.status is ProductStatus.DRAFT
    assert stored.is_deleted is False
    assert stored.description is None
    assert await AuditLog.filter(
        action="CREATE_PRODUCT",
        target_id=product.id,
    ).exists()


async def test_real_kit_create_persists_complete_draft_aggregate() -> None:
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    product = await service.create_kit_product(
        name="真实套装草稿",
        description="包含材料",
        price=Decimal("199.00"),
        stock=0,
        operator_id=32,
        ip_address="127.0.0.1",
    )

    stored = await Product.get(id=product.id)
    kit = await ProductKit.get(product_id=product.id)
    assert stored.product_type is ProductType.KIT
    assert stored.status is ProductStatus.DRAFT
    assert kit.price == Decimal("199.00")
    assert kit.stock == 0
    assert await AuditLog.filter(
        action="CREATE_PRODUCT",
        target_id=product.id,
    ).exists()


class _FailingAuditLogService(AuditLogService):
    async def log(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit failed")


@pytest.mark.parametrize("product_type", [ProductType.EXPERIENCE, ProductType.KIT])
async def test_real_audit_failure_rolls_back_entire_create(
    product_type: ProductType,
) -> None:
    service = ProductService(
        ProductRepository(),
        _FailingAuditLogService(AuditLogRepository()),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        if product_type is ProductType.EXPERIENCE:
            await service.create_experience_product(
                name="应回滚体验",
                description=None,
                operator_id=31,
                ip_address="127.0.0.1",
            )
        else:
            await service.create_kit_product(
                name="应回滚套装",
                description=None,
                price=Decimal("99.00"),
                stock=0,
                operator_id=31,
                ip_address="127.0.0.1",
            )

    assert not await Product.filter(name__startswith="应回滚").exists()
    assert await ProductKit.all().count() == 0
