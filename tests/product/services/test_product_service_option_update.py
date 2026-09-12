"""ProductService ExperienceOption PATCH 编排与事务测试。"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from tortoise.exceptions import IntegrityError

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.exceptions import (
    ExperienceOptionAlreadyDeleted,
    ExperienceOptionAlreadyExists,
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
    option_id: int = 11,
    product: SimpleNamespace | None = None,
    duration: int = 120,
    participants: int = 2,
    day_type: DayType = DayType.HOLIDAY,
    price: Decimal = Decimal("699.00"),
    is_deleted: bool = False,
) -> SimpleNamespace:
    owner = product or _product()
    return SimpleNamespace(
        id=option_id,
        product_id=owner.id,
        product=owner,
        duration=duration,
        participants=participants,
        day_type=day_type,
        price=price,
        is_deleted=is_deleted,
        images=[],
    )


def _service_with_mocks(
    option: object | None,
    collision: object | None = None,
) -> tuple[ProductService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=ProductRepository)
    repository.get_option_by_id.return_value = option
    repository.get_option_by_combination.return_value = collision

    async def update_option(target: object, **fields: object) -> object:
        for name, value in fields.items():
            if name != "using_db":
                setattr(target, name, value)
        return target

    repository.update_option.side_effect = update_option
    repository.get_option_detail.return_value = option
    audit_service = AsyncMock(spec=AuditLogService)
    return ProductService(repository, audit_service), repository, audit_service


async def _call(
    service: ProductService,
    updates: dict[str, object],
) -> object:
    return await service.update_experience_option(
        11,
        updates=updates,
        operator_id=7,
        ip_address="127.0.0.1",
    )


@pytest.mark.parametrize(
    "updates",
    [
        {},
        {"duration": 180},
        {"is_deleted": True},
        {"price": Decimal("799.00"), "product_id": 2},
    ],
)
async def test_empty_or_unsupported_updates_fail_before_lookup(
    updates: dict[str, object],
) -> None:
    service, repository, audit_service = _service_with_mocks(_option())

    with pytest.raises(ValueError, match="updates must contain only"):
        await _call(service, updates)

    repository.get_option_by_id.assert_not_awaited()
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_missing_option_is_rejected_before_combination_lookup() -> None:
    service, repository, audit_service = _service_with_mocks(None)

    with pytest.raises(ExperienceOptionNotFound):
        await _call(service, {"price": Decimal("799.00")})

    repository.get_option_by_id.assert_awaited_once_with(
        11,
        include_deleted=True,
    )
    repository.get_option_by_combination.assert_not_awaited()
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_deleted_option_precedes_product_status() -> None:
    option = _option(
        product=_product(status=ProductStatus.ONLINE),
        is_deleted=True,
    )
    service, repository, audit_service = _service_with_mocks(option)

    with pytest.raises(ExperienceOptionAlreadyDeleted):
        await _call(service, {"price": Decimal("799.00")})

    repository.get_option_by_combination.assert_not_awaited()
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_deleted_product_is_hidden_as_option_not_found() -> None:
    option = _option(product=_product(is_deleted=True))
    service, repository, audit_service = _service_with_mocks(option)

    with pytest.raises(ExperienceOptionNotFound):
        await _call(service, {"price": Decimal("799.00")})

    repository.get_option_by_combination.assert_not_awaited()
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_online_owner_cannot_be_modified() -> None:
    option = _option(product=_product(status=ProductStatus.ONLINE))
    service, repository, audit_service = _service_with_mocks(option)

    with pytest.raises(OnlineProductCannotBeModified):
        await _call(service, {"price": Decimal("799.00")})

    repository.get_option_by_combination.assert_not_awaited()
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize("collision_deleted", [False, True])
async def test_merged_combination_owned_by_other_history_is_rejected(
    collision_deleted: bool,
) -> None:
    option = _option()
    collision = _option(
        option_id=12,
        participants=3,
        is_deleted=collision_deleted,
    )
    service, repository, audit_service = _service_with_mocks(
        option,
        collision,
    )

    with pytest.raises(ExperienceOptionAlreadyExists) as caught:
        await _call(service, {"participants": 3})

    repository.get_option_by_combination.assert_awaited_once_with(
        product_id=1,
        duration=120,
        participants=3,
        day_type=DayType.HOLIDAY,
    )
    assert caught.value.data == {
        "duration_minutes": 120,
        "participants": 3,
        "day_type": "holiday",
    }
    repository.update_option.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_same_option_combination_is_not_a_collision() -> None:
    option = _option()
    service, repository, _ = _service_with_mocks(option, option)

    result = await _call(service, {"price": Decimal("799.00")})

    assert result is option
    repository.update_option.assert_awaited_once()


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_price_only_patch_preserves_dimensions_and_writes_price_audit(
    status: ProductStatus,
) -> None:
    option = _option(product=_product(status=status))
    loaded = _option(
        product=option.product,
        price=Decimal("799.00"),
    )
    service, repository, audit_service = _service_with_mocks(option, option)
    repository.get_option_detail.return_value = loaded

    result = await _call(service, {"price": Decimal("799.00")})

    assert result is loaded
    update_call = repository.update_option.await_args
    connection = update_call.kwargs["using_db"]
    assert update_call.kwargs == {
        "price": Decimal("799.00"),
        "using_db": connection,
    }
    audit_service.log.assert_awaited_once()
    audit = audit_service.log.await_args.kwargs
    assert audit["action"] == "UPDATE_PRICE"
    assert audit["using_db"] is connection
    assert json.loads(audit["description"]) == {
        "option_id": 11,
        "before": {"price": "699.00"},
        "after": {"price": "799.00"},
    }


async def test_dimension_patch_maps_api_name_and_writes_config_audit() -> None:
    option = _option()
    loaded = _option(duration=180, participants=3)
    service, repository, audit_service = _service_with_mocks(option)
    repository.get_option_detail.return_value = loaded

    result = await _call(
        service,
        {
            "duration_minutes": 180,
            "participants": 3,
        },
    )

    assert result is loaded
    update_call = repository.update_option.await_args
    connection = update_call.kwargs["using_db"]
    assert update_call.kwargs == {
        "duration": 180,
        "participants": 3,
        "using_db": connection,
    }
    audit_service.log.assert_awaited_once()
    audit = audit_service.log.await_args.kwargs
    assert audit["action"] == "UPDATE_OPTION"
    assert json.loads(audit["description"]) == {
        "option_id": 11,
        "before": {
            "duration_minutes": 120,
            "participants": 2,
            "day_type": "holiday",
        },
        "after": {
            "duration_minutes": 180,
            "participants": 3,
            "day_type": "holiday",
        },
    }
    repository.get_option_detail.assert_awaited_once_with(
        option.id,
        using_db=connection,
    )


async def test_dimension_and_price_patch_writes_two_ordered_audits() -> None:
    option = _option()
    service, repository, audit_service = _service_with_mocks(option)

    await _call(
        service,
        {
            "day_type": DayType.WEEKDAY,
            "price": Decimal("799.00"),
        },
    )

    connection = repository.update_option.await_args.kwargs["using_db"]
    assert [item.kwargs["action"] for item in audit_service.log.await_args_list] == [
        "UPDATE_OPTION",
        "UPDATE_PRICE",
    ]
    assert all(
        item.kwargs["using_db"] is connection
        for item in audit_service.log.await_args_list
    )


async def test_unique_index_race_is_translated_to_option_conflict() -> None:
    option = _option()
    service, repository, audit_service = _service_with_mocks(option)
    repository.update_option.side_effect = IntegrityError("duplicate")

    with pytest.raises(ExperienceOptionAlreadyExists) as caught:
        await _call(service, {"participants": 3})

    assert caught.value.data["participants"] == 3
    audit_service.log.assert_not_awaited()
    repository.get_option_detail.assert_not_awaited()


async def test_update_failure_does_not_audit() -> None:
    service, repository, audit_service = _service_with_mocks(_option())
    repository.update_option.side_effect = RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        await _call(service, {"price": Decimal("799.00")})

    audit_service.log.assert_not_awaited()


async def test_update_flow_does_not_call_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = Mock()
    monkeypatch.setattr(ProductValidator, "validate_before_online", validate)
    service, _, _ = _service_with_mocks(_option())

    await _call(service, {"price": Decimal("799.00")})

    validate.assert_not_called()


async def _create_real_option(
    *,
    status: ProductStatus = ProductStatus.DRAFT,
) -> tuple[Product, ExperienceOption, ProductImage]:
    repository = ProductRepository()
    product = await repository.create_product(
        name="Option PATCH 体验",
        product_type=ProductType.EXPERIENCE,
        description=None,
    )
    if status is not ProductStatus.DRAFT:
        await repository.update_product(product, status=status)
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
        image_url="https://example.com/option.jpg",
    )
    return product, option, image


async def test_real_patch_persists_fields_preserves_image_and_audits() -> None:
    product, option, image = await _create_real_option(
        status=ProductStatus.OFFLINE,
    )
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    result = await service.update_experience_option(
        option.id,
        updates={
            "duration_minutes": 180,
            "price": Decimal("799.00"),
        },
        operator_id=31,
        ip_address="127.0.0.1",
    )

    stored = await ExperienceOption.get(id=option.id)
    assert result.id == option.id
    assert result.duration == 180
    assert result.participants == 2
    assert result.price == Decimal("799.00")
    assert [item.id for item in result.images] == [image.id]
    assert stored.duration == 180
    assert stored.price == Decimal("799.00")
    audits = await AuditLog.filter(target_id=product.id).order_by("id")
    assert [audit.action for audit in audits] == [
        "UPDATE_OPTION",
        "UPDATE_PRICE",
    ]


@pytest.mark.parametrize("collision_deleted", [False, True])
async def test_real_other_historical_combination_blocks_patch(
    collision_deleted: bool,
) -> None:
    product, option, _ = await _create_real_option()
    repository = ProductRepository()
    collision = await repository.create_option(
        product=product,
        duration=180,
        participants=3,
        day_type=DayType.WEEKDAY,
        price=Decimal("899.00"),
    )
    if collision_deleted:
        await repository.update_option(collision, is_deleted=True)
    service = ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )

    with pytest.raises(ExperienceOptionAlreadyExists):
        await service.update_experience_option(
            option.id,
            updates={
                "duration_minutes": 180,
                "participants": 3,
                "day_type": DayType.WEEKDAY,
            },
            operator_id=31,
            ip_address="127.0.0.1",
        )

    stored = await ExperienceOption.get(id=option.id)
    assert stored.duration == 120
    assert stored.participants == 2
    assert stored.day_type is DayType.HOLIDAY
    assert not await AuditLog.filter(target_id=product.id).exists()


class _FailingAuditLogService(AuditLogService):
    def __init__(self, *, fail_on_call: int) -> None:
        super().__init__(AuditLogRepository())
        self.fail_on_call = fail_on_call
        self.call_count = 0

    async def log(self, *args: object, **kwargs: object) -> None:
        self.call_count += 1
        if self.call_count == self.fail_on_call:
            raise RuntimeError("audit failed")
        await super().log(*args, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("fail_on_call", [1, 2])
async def test_real_audit_failure_rolls_back_fields_and_all_audits(
    fail_on_call: int,
) -> None:
    product, option, _ = await _create_real_option()
    service = ProductService(
        ProductRepository(),
        _FailingAuditLogService(fail_on_call=fail_on_call),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.update_experience_option(
            option.id,
            updates={
                "participants": 3,
                "price": Decimal("799.00"),
            },
            operator_id=31,
            ip_address="127.0.0.1",
        )

    stored = await ExperienceOption.get(id=option.id)
    assert stored.participants == 2
    assert stored.price == Decimal("699.00")
    assert not await AuditLog.filter(target_id=product.id).exists()


class _MissingReloadProductRepository(ProductRepository):
    async def get_option_detail(
        self,
        *args: object,
        **kwargs: object,
    ) -> None:
        return None


async def test_real_response_reload_failure_rolls_back_update_and_audit() -> None:
    product, option, _ = await _create_real_option()
    service = ProductService(
        _MissingReloadProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    with pytest.raises(RuntimeError, match="Updated experience option not found"):
        await service.update_experience_option(
            option.id,
            updates={"price": Decimal("799.00")},
            operator_id=31,
            ip_address="127.0.0.1",
        )

    assert (await ExperienceOption.get(id=option.id)).price == Decimal("699.00")
    assert not await AuditLog.filter(target_id=product.id).exists()
