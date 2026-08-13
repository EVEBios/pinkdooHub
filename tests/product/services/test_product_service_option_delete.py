"""ProductService ExperienceOption 逻辑删除编排与事务测试。"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.exceptions import (
    ExperienceOptionAlreadyDeleted,
    ExperienceOptionNotFound,
    OnlineProductCannotBeModified,
)
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
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
        product_type=ProductType.EXPERIENCE,
        status=status,
        is_deleted=is_deleted,
    )


def _option(
    *,
    product: SimpleNamespace | None = None,
    is_deleted: bool = False,
) -> SimpleNamespace:
    owner = product or _product()
    return SimpleNamespace(
        id=11,
        product_id=owner.id,
        product=owner,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("699.00"),
        is_deleted=is_deleted,
    )


def _service_with_mocks(
    option: object | None,
) -> tuple[ProductService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=ProductRepository)
    repository.get_option_by_id.return_value = option

    async def update_option(target: object, **fields: object) -> object:
        target.is_deleted = fields["is_deleted"]
        return target

    repository.update_option.side_effect = update_option
    audit_service = AsyncMock(spec=AuditLogService)
    return ProductService(repository, audit_service), repository, audit_service


async def _call(service: ProductService) -> object:
    return await service.delete_experience_option(
        11,
        operator_id=7,
        ip_address="127.0.0.1",
    )


async def test_missing_option_is_rejected_before_write() -> None:
    service, repository, audit_service = _service_with_mocks(None)

    with pytest.raises(ExperienceOptionNotFound):
        await _call(service)

    repository.get_option_by_id.assert_awaited_once_with(
        11,
        include_deleted=True,
    )
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_deleted_option_precedes_product_status() -> None:
    option = _option(
        product=_product(status=ProductStatus.ONLINE),
        is_deleted=True,
    )
    service, repository, audit_service = _service_with_mocks(option)

    with pytest.raises(ExperienceOptionAlreadyDeleted):
        await _call(service)

    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_deleted_product_is_hidden_as_option_not_found() -> None:
    option = _option(product=_product(is_deleted=True))
    service, repository, audit_service = _service_with_mocks(option)

    with pytest.raises(ExperienceOptionNotFound):
        await _call(service)

    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_online_owner_cannot_delete_option() -> None:
    option = _option(product=_product(status=ProductStatus.ONLINE))
    service, repository, audit_service = _service_with_mocks(option)

    with pytest.raises(OnlineProductCannotBeModified):
        await _call(service)

    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_delete_marks_option_and_audits_snapshot_in_one_transaction(
    status: ProductStatus,
) -> None:
    option = _option(product=_product(status=status))
    service, repository, audit_service = _service_with_mocks(option)

    result = await _call(service)

    assert result is option
    assert result.is_deleted is True
    update_call = repository.update_option.await_args
    connection = update_call.kwargs["using_db"]
    repository.update_option.assert_awaited_once_with(
        option,
        is_deleted=True,
        using_db=connection,
    )
    audit_service.log.assert_awaited_once()
    audit = audit_service.log.await_args.kwargs
    assert audit == {
        "operator_id": 7,
        "action": "DELETE_OPTION",
        "target_type": "product",
        "target_id": 1,
        "ip_address": "127.0.0.1",
        "description": audit["description"],
        "using_db": connection,
    }
    assert json.loads(audit["description"]) == {
        "option_id": 11,
        "duration_minutes": 120,
        "participants": 2,
        "day_type": "holiday",
        "price": "699.00",
    }


async def test_update_failure_does_not_audit() -> None:
    service, repository, audit_service = _service_with_mocks(_option())
    repository.update_option.side_effect = RuntimeError("delete failed")

    with pytest.raises(RuntimeError, match="delete failed"):
        await _call(service)

    audit_service.log.assert_not_awaited()


async def test_delete_flow_does_not_call_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = Mock()
    monkeypatch.setattr(ProductValidator, "validate_before_online", validate)
    service, _, _ = _service_with_mocks(_option())

    await _call(service)

    validate.assert_not_called()


async def _create_real_aggregate(
    *,
    status: ProductStatus,
    option_count: int = 1,
) -> tuple[Product, list[ExperienceOption], ProductImage]:
    repository = ProductRepository()
    product = await repository.create_product(
        name="Option 删除体验",
        product_type=ProductType.EXPERIENCE,
        description=None,
    )
    if status is not ProductStatus.DRAFT:
        await repository.update_product(product, status=status)
    options: list[ExperienceOption] = []
    for index in range(option_count):
        options.append(
            await repository.create_option(
                product=product,
                duration=120 + index * 60,
                participants=2,
                day_type=DayType.HOLIDAY,
                price=Decimal("699.00") + Decimal(index),
            ),
        )
    image = await repository.create_image(
        product=product,
        experience_option=options[0],
        image_url="https://example.com/option-delete.jpg",
    )
    return product, options, image


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_real_delete_preserves_product_status_and_image(
    status: ProductStatus,
) -> None:
    product, options, image = await _create_real_aggregate(
        status=status,
        option_count=2,
    )
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    result = await service.delete_experience_option(
        options[0].id,
        operator_id=31,
        ip_address="127.0.0.1",
    )

    stored_product = await Product.get(id=product.id)
    stored_option = await ExperienceOption.get(id=options[0].id)
    stored_image = await ProductImage.get(id=image.id)
    assert result.is_deleted is True
    assert stored_product.status is status
    assert stored_option.is_deleted is True
    assert stored_image.experience_option_id == options[0].id
    assert stored_image.is_deleted is False
    assert await ExperienceOption.filter(
        product_id=product.id,
        is_deleted=False,
    ).count() == 1
    audit = await AuditLog.get(
        action="DELETE_OPTION",
        target_id=product.id,
    )
    assert json.loads(audit.description or "") == {
        "option_id": options[0].id,
        "duration_minutes": 120,
        "participants": 2,
        "day_type": "holiday",
        "price": "699.00",
    }


async def test_real_last_option_can_be_deleted_without_status_change() -> None:
    product, options, _ = await _create_real_aggregate(
        status=ProductStatus.OFFLINE,
    )
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    await service.delete_experience_option(
        options[0].id,
        operator_id=31,
        ip_address="127.0.0.1",
    )

    assert not await ExperienceOption.filter(
        product_id=product.id,
        is_deleted=False,
    ).exists()
    assert (await Product.get(id=product.id)).status is ProductStatus.OFFLINE


class _FailingAuditLogService(AuditLogService):
    async def log(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit failed")


async def test_real_audit_failure_rolls_back_option_delete() -> None:
    product, options, image = await _create_real_aggregate(
        status=ProductStatus.DRAFT,
    )
    service = ProductService(
        ProductRepository(),
        _FailingAuditLogService(AuditLogRepository()),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.delete_experience_option(
            options[0].id,
            operator_id=31,
            ip_address="127.0.0.1",
        )

    stored = await ExperienceOption.get(id=options[0].id)
    assert stored.is_deleted is False
    assert await ProductImage.filter(
        id=image.id,
        experience_option_id=options[0].id,
        is_deleted=False,
    ).exists()
    assert not await AuditLog.filter(target_id=product.id).exists()
