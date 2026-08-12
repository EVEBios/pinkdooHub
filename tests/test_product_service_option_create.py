"""ProductService ExperienceOption 新增/恢复编排与事务测试。"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from tortoise.exceptions import IntegrityError

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.exceptions import (
    ExperienceOptionAlreadyExists,
    OnlineProductCannotBeModified,
    ProductIsDeleted,
    ProductNotFound,
    ProductTypeMismatch,
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
    product_type: ProductType = ProductType.EXPERIENCE,
    status: ProductStatus = ProductStatus.DRAFT,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        product_type=product_type,
        status=status,
        is_deleted=is_deleted,
    )


def _option(
    *,
    option_id: int = 11,
    price: Decimal = Decimal("699.00"),
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=option_id,
        product_id=1,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=price,
        is_deleted=is_deleted,
        images=[],
    )


def _service_with_mocks(
    product: object | None,
    existing: object | None = None,
) -> tuple[ProductService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=ProductRepository)
    repository.get_product_by_id.return_value = product
    repository.get_option_by_combination.return_value = existing

    async def create_option(**kwargs: object) -> object:
        return _option(price=kwargs["price"])  # type: ignore[arg-type]

    async def update_option(
        target: object,
        **kwargs: object,
    ) -> object:
        target.price = kwargs["price"]
        target.is_deleted = kwargs["is_deleted"]
        return target

    repository.create_option.side_effect = create_option
    repository.update_option.side_effect = update_option
    repository.get_option_detail.side_effect = (
        lambda option_id, **kwargs: repository.create_option.return_value
    )
    audit_service = AsyncMock(spec=AuditLogService)
    return ProductService(repository, audit_service), repository, audit_service


async def _call(service: ProductService) -> object:
    return await service.create_experience_option(
        1,
        duration_minutes=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("799.00"),
        operator_id=7,
        ip_address="127.0.0.1",
    )


@pytest.mark.parametrize(
    ("product", "expected_exception"),
    [
        (None, ProductNotFound),
        (
            _product(
                product_type=ProductType.KIT,
                status=ProductStatus.ONLINE,
                is_deleted=True,
            ),
            ProductIsDeleted,
        ),
        (_product(product_type=ProductType.KIT), ProductTypeMismatch),
        (_product(status=ProductStatus.ONLINE), OnlineProductCannotBeModified),
    ],
)
async def test_product_preconditions_short_circuit_before_option_lookup(
    product: object | None,
    expected_exception: type[Exception],
) -> None:
    service, repository, audit_service = _service_with_mocks(product)

    with pytest.raises(expected_exception) as caught:
        await _call(service)

    repository.get_product_by_id.assert_awaited_once_with(
        1,
        include_deleted=True,
    )
    repository.get_option_by_combination.assert_not_awaited()
    repository.create_option.assert_not_awaited()
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()
    if expected_exception is ProductTypeMismatch:
        assert caught.value.data == {
            "expected": "experience",
            "actual": "kit",
        }


async def test_active_combination_returns_stable_conflict() -> None:
    service, repository, audit_service = _service_with_mocks(
        _product(),
        _option(),
    )

    with pytest.raises(ExperienceOptionAlreadyExists) as caught:
        await _call(service)

    assert caught.value.data == {
        "duration_minutes": 120,
        "participants": 2,
        "day_type": "holiday",
    }
    repository.create_option.assert_not_awaited()
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_new_combination_is_created_and_audited_in_one_transaction(
    status: ProductStatus,
) -> None:
    service, repository, audit_service = _service_with_mocks(
        _product(status=status),
    )
    created = _option(price=Decimal("799.00"))
    loaded = _option(price=Decimal("799.00"))
    repository.create_option.return_value = created
    repository.create_option.side_effect = None
    repository.get_option_detail.return_value = loaded
    repository.get_option_detail.side_effect = None

    result = await _call(service)

    assert result.option is loaded
    assert result.restored is False
    repository.get_option_by_combination.assert_awaited_once_with(
        product_id=1,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
    )
    create_call = repository.create_option.await_args
    connection = create_call.kwargs["using_db"]
    assert create_call.kwargs == {
        "product": repository.get_product_by_id.return_value,
        "duration": 120,
        "participants": 2,
        "day_type": DayType.HOLIDAY,
        "price": Decimal("799.00"),
        "using_db": connection,
    }
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_awaited_once_with(
        operator_id=7,
        action="CREATE_OPTION",
        target_type="product",
        target_id=1,
        ip_address="127.0.0.1",
        description=None,
        using_db=connection,
    )
    repository.get_option_detail.assert_awaited_once_with(
        created.id,
        using_db=connection,
    )


async def test_deleted_combination_is_restored_with_price_snapshot() -> None:
    deleted = _option(price=Decimal("699.00"), is_deleted=True)
    loaded = _option(price=Decimal("799.00"), is_deleted=False)
    service, repository, audit_service = _service_with_mocks(
        _product(status=ProductStatus.OFFLINE),
        deleted,
    )
    repository.get_option_detail.return_value = loaded
    repository.get_option_detail.side_effect = None

    result = await _call(service)

    assert result.option is loaded
    assert result.restored is True
    update_call = repository.update_option.await_args
    connection = update_call.kwargs["using_db"]
    repository.update_option.assert_awaited_once_with(
        deleted,
        price=Decimal("799.00"),
        is_deleted=False,
        using_db=connection,
    )
    repository.create_option.assert_not_awaited()
    audit_call = audit_service.log.await_args.kwargs
    assert audit_call["action"] == "RESTORE_OPTION"
    assert audit_call["target_type"] == "product"
    assert audit_call["target_id"] == 1
    assert audit_call["using_db"] is connection
    assert json.loads(audit_call["description"]) == {
        "option_id": 11,
        "before": {"price": "699.00"},
        "after": {"price": "799.00"},
    }


async def test_unique_index_race_is_translated_to_option_conflict() -> None:
    service, repository, audit_service = _service_with_mocks(_product())
    repository.create_option.side_effect = IntegrityError("duplicate")

    with pytest.raises(ExperienceOptionAlreadyExists) as caught:
        await _call(service)

    assert caught.value.data["day_type"] == "holiday"
    audit_service.log.assert_not_awaited()
    repository.get_option_detail.assert_not_awaited()


@pytest.mark.parametrize("operation", ["create", "restore"])
async def test_option_write_failure_does_not_audit(operation: str) -> None:
    existing = (
        _option(is_deleted=True)
        if operation == "restore"
        else None
    )
    service, repository, audit_service = _service_with_mocks(
        _product(),
        existing,
    )
    target = (
        repository.update_option
        if operation == "restore"
        else repository.create_option
    )
    target.side_effect = RuntimeError("option write failed")

    with pytest.raises(RuntimeError, match="option write failed"):
        await _call(service)

    audit_service.log.assert_not_awaited()


async def test_create_flow_does_not_call_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = Mock()
    monkeypatch.setattr(ProductValidator, "validate_before_online", validate)
    service, repository, _ = _service_with_mocks(_product())
    created = _option(price=Decimal("799.00"))
    repository.create_option.return_value = created
    repository.create_option.side_effect = None
    repository.get_option_detail.return_value = created
    repository.get_option_detail.side_effect = None

    await _call(service)

    validate.assert_not_called()


async def _create_real_product(
    *,
    status: ProductStatus = ProductStatus.DRAFT,
) -> Product:
    repository = ProductRepository()
    product = await repository.create_product(
        name="Option Service 体验",
        product_type=ProductType.EXPERIENCE,
        description=None,
    )
    if status is not ProductStatus.DRAFT:
        await repository.update_product(product, status=status)
    return product


async def test_real_new_option_persists_with_audit_and_empty_images() -> None:
    product = await _create_real_product(status=ProductStatus.OFFLINE)
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    result = await service.create_experience_option(
        product.id,
        duration_minutes=180,
        participants=3,
        day_type=DayType.WEEKDAY,
        price=Decimal("899.00"),
        operator_id=31,
        ip_address="127.0.0.1",
    )

    stored = await ExperienceOption.get(id=result.option.id)
    assert result.restored is False
    assert list(result.option.images) == []
    assert stored.product_id == product.id
    assert stored.duration == 180
    assert stored.participants == 3
    assert stored.day_type is DayType.WEEKDAY
    assert stored.price == Decimal("899.00")
    assert stored.is_deleted is False
    audit = await AuditLog.get(
        action="CREATE_OPTION",
        target_id=product.id,
    )
    assert audit.target_type == "product"
    assert audit.description is None


async def test_real_restore_preserves_id_images_and_updates_price() -> None:
    product = await _create_real_product()
    repository = ProductRepository()
    option = await repository.create_option(
        product=product,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("699.00"),
    )
    image = await repository.create_image(
        product=product,
        experience_option=option,
        image_url="https://example.com/restored.jpg",
    )
    await repository.update_option(option, is_deleted=True)
    service = ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )

    result = await service.create_experience_option(
        product.id,
        duration_minutes=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("799.00"),
        operator_id=32,
        ip_address="127.0.0.1",
    )

    assert result.restored is True
    assert result.option.id == option.id
    assert result.option.price == Decimal("799.00")
    assert [item.id for item in result.option.images] == [image.id]
    assert await ExperienceOption.all().count() == 1
    audit = await AuditLog.get(
        action="RESTORE_OPTION",
        target_id=product.id,
    )
    assert json.loads(audit.description or "") == {
        "option_id": option.id,
        "before": {"price": "699.00"},
        "after": {"price": "799.00"},
    }


class _FailingAuditLogService(AuditLogService):
    async def log(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("audit failed")


class _MissingReloadProductRepository(ProductRepository):
    async def get_option_detail(
        self,
        *args: object,
        **kwargs: object,
    ) -> None:
        return None


async def test_real_response_reload_failure_rolls_back_write_and_audit() -> None:
    product = await _create_real_product()
    service = ProductService(
        _MissingReloadProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    with pytest.raises(
        RuntimeError,
        match="Persisted experience option not found",
    ):
        await service.create_experience_option(
            product.id,
            duration_minutes=120,
            participants=2,
            day_type=DayType.HOLIDAY,
            price=Decimal("799.00"),
            operator_id=31,
            ip_address="127.0.0.1",
        )

    assert not await ExperienceOption.filter(product_id=product.id).exists()
    assert not await AuditLog.filter(target_id=product.id).exists()


@pytest.mark.parametrize("operation", ["create", "restore"])
async def test_real_audit_failure_rolls_back_create_or_restore(
    operation: str,
) -> None:
    product = await _create_real_product()
    repository = ProductRepository()
    original: ExperienceOption | None = None
    if operation == "restore":
        original = await repository.create_option(
            product=product,
            duration=120,
            participants=2,
            day_type=DayType.HOLIDAY,
            price=Decimal("699.00"),
        )
        await repository.update_option(original, is_deleted=True)
    service = ProductService(
        repository,
        _FailingAuditLogService(AuditLogRepository()),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.create_experience_option(
            product.id,
            duration_minutes=120,
            participants=2,
            day_type=DayType.HOLIDAY,
            price=Decimal("799.00"),
            operator_id=31,
            ip_address="127.0.0.1",
        )

    options = await ExperienceOption.filter(product_id=product.id)
    if operation == "create":
        assert options == []
    else:
        assert original is not None
        assert len(options) == 1
        assert options[0].id == original.id
        assert options[0].price == Decimal("699.00")
        assert options[0].is_deleted is True
    assert not await AuditLog.filter(target_id=product.id).exists()
