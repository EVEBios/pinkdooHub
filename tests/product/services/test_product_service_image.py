"""ProductService 图片创建、修改与逻辑删除编排及事务测试。"""

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from tortoise.backends.base.client import BaseDBAsyncClient

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.exceptions import (
    ExperienceOptionAlreadyDeleted,
    ExperienceOptionNotFound,
    OnlineProductCannotBeModified,
    OptionImageCannotBeCover,
    ProductImageNotFound,
    ProductIsDeleted,
    ProductNotFound,
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
        is_deleted=is_deleted,
    )


def _image(
    *,
    image_id: int = 20,
    product: SimpleNamespace | None = None,
    option: SimpleNamespace | None = None,
    is_cover: bool = False,
    sort: int = 0,
    is_deleted: bool = False,
) -> SimpleNamespace:
    owner = product or (option.product if option is not None else _product())
    return SimpleNamespace(
        id=image_id,
        product_id=owner.id,
        product=owner,
        experience_option_id=(option.id if option is not None else None),
        experience_option=option,
        image_url=f"https://example.com/images/{image_id}.jpg",
        is_cover=is_cover,
        sort=sort,
        is_deleted=is_deleted,
    )


def _service_with_mocks() -> tuple[ProductService, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=ProductRepository)

    async def create_image(**fields: object) -> SimpleNamespace:
        product = cast(SimpleNamespace, fields["product"])
        option = cast(
            SimpleNamespace | None,
            fields.get("experience_option"),
        )
        return _image(
            product=product,
            option=option,
            is_cover=bool(fields.get("is_cover", False)),
            sort=int(fields.get("sort", 0)),
        )

    async def update_image(target: object, **fields: object) -> object:
        for name, value in fields.items():
            if name != "using_db":
                setattr(target, name, value)
        return target

    repository.create_image.side_effect = create_image
    repository.update_image.side_effect = update_image
    repository.get_product_cover.return_value = None
    repository.get_product_for_update.side_effect = (
        lambda product_id, **kwargs: repository.get_product_by_id.return_value
    )
    audit_service = AsyncMock(spec=AuditLogService)
    return ProductService(repository, audit_service), repository, audit_service


async def test_create_public_image_rejects_product_conflicts_in_order() -> None:
    service, repository, audit_service = _service_with_mocks()
    repository.get_product_by_id.return_value = None

    with pytest.raises(ProductNotFound):
        await service.create_product_image(
            1,
            image_url="https://example.com/new.jpg",
            is_cover=False,
            sort=0,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.create_image.assert_not_awaited()
    audit_service.log.assert_not_awaited()

    repository.get_product_by_id.return_value = _product(
        status=ProductStatus.ONLINE,
        is_deleted=True,
    )
    with pytest.raises(ProductIsDeleted):
        await service.create_product_image(
            1,
            image_url="https://example.com/new.jpg",
            is_cover=False,
            sort=0,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.get_product_by_id.return_value = _product(
        status=ProductStatus.ONLINE,
    )
    with pytest.raises(OnlineProductCannotBeModified):
        await service.create_product_image(
            1,
            image_url="https://example.com/new.jpg",
            is_cover=False,
            sort=0,
            operator_id=7,
            ip_address="127.0.0.1",
        )


@pytest.mark.parametrize("status", [ProductStatus.DRAFT, ProductStatus.OFFLINE])
async def test_create_public_cover_clears_old_cover_and_audits(
    status: ProductStatus,
) -> None:
    service, repository, audit_service = _service_with_mocks()
    repository.get_product_by_id.return_value = _product(status=status)

    result = await service.create_product_image(
        1,
        image_url="https://example.com/new.jpg",
        is_cover=True,
        sort=10,
        operator_id=7,
        ip_address="127.0.0.1",
    )

    clear = repository.clear_product_covers.await_args
    connection = clear.kwargs["using_db"]
    assert clear.args == (1,)
    create = repository.create_image.await_args
    assert create.kwargs == {
        "product": repository.get_product_by_id.return_value,
        "image_url": "https://example.com/new.jpg",
        "is_cover": True,
        "sort": 10,
        "using_db": connection,
    }
    assert result.is_cover is True
    audit = audit_service.log.await_args.kwargs
    assert audit["action"] == "CREATE_PRODUCT_IMAGE"
    assert audit["using_db"] is connection
    assert json.loads(audit["description"]) == {
        "image_id": 20,
        "is_cover": True,
    }


async def test_create_non_cover_does_not_clear_covers() -> None:
    service, repository, _ = _service_with_mocks()
    repository.get_product_by_id.return_value = _product()

    await service.create_product_image(
        1,
        image_url="https://example.com/new.jpg",
        is_cover=False,
        sort=0,
        operator_id=7,
        ip_address="127.0.0.1",
    )

    repository.clear_product_covers.assert_not_awaited()


async def test_create_option_image_rejects_resource_conflicts_in_order() -> None:
    service, repository, audit_service = _service_with_mocks()
    repository.get_option_by_id.return_value = None

    with pytest.raises(ExperienceOptionNotFound):
        await service.create_option_image(
            11,
            image_url="https://example.com/option.jpg",
            sort=0,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.get_option_by_id.return_value = _option(
        product=_product(status=ProductStatus.ONLINE),
        is_deleted=True,
    )
    with pytest.raises(ExperienceOptionAlreadyDeleted):
        await service.create_option_image(
            11,
            image_url="https://example.com/option.jpg",
            sort=0,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.get_option_by_id.return_value = _option(
        product=_product(is_deleted=True),
    )
    with pytest.raises(ExperienceOptionNotFound):
        await service.create_option_image(
            11,
            image_url="https://example.com/option.jpg",
            sort=0,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.get_option_by_id.return_value = _option(
        product=_product(status=ProductStatus.ONLINE),
    )
    with pytest.raises(OnlineProductCannotBeModified):
        await service.create_option_image(
            11,
            image_url="https://example.com/option.jpg",
            sort=0,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.create_image.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_create_option_image_fixes_ownership_and_cover_flag() -> None:
    service, repository, audit_service = _service_with_mocks()
    option = _option(product=_product(status=ProductStatus.OFFLINE))
    repository.get_option_by_id.return_value = option

    result = await service.create_option_image(
        11,
        image_url="https://example.com/option.jpg",
        sort=5,
        operator_id=7,
        ip_address="127.0.0.1",
    )

    create = repository.create_image.await_args
    connection = create.kwargs["using_db"]
    assert create.kwargs == {
        "product": option.product,
        "experience_option": option,
        "image_url": "https://example.com/option.jpg",
        "is_cover": False,
        "sort": 5,
        "using_db": connection,
    }
    assert result.experience_option_id == 11
    assert result.is_cover is False
    audit = audit_service.log.await_args.kwargs
    assert audit["action"] == "CREATE_OPTION_IMAGE"
    assert audit["using_db"] is connection
    assert json.loads(audit["description"]) == {
        "image_id": 20,
        "option_id": 11,
    }


@pytest.mark.parametrize(
    "updates",
    [{}, {"image_url": "x"}, {"is_cover": False}],
)
async def test_invalid_image_updates_fail_before_lookup(
    updates: dict[str, object],
) -> None:
    service, repository, audit_service = _service_with_mocks()

    with pytest.raises(ValueError):
        await service.update_product_image(
            20,
            updates=updates,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.get_image_by_id.assert_not_awaited()
    audit_service.log.assert_not_awaited()


@pytest.mark.parametrize(
    "image",
    [
        None,
        _image(is_deleted=True),
        _image(product=_product(is_deleted=True)),
        _image(option=_option(is_deleted=True)),
    ],
)
async def test_hidden_image_resources_return_40403(image: object | None) -> None:
    service, repository, audit_service = _service_with_mocks()
    repository.get_image_by_id.return_value = image

    with pytest.raises(ProductImageNotFound):
        await service.update_product_image(
            20,
            updates={"sort": 10},
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.update_image.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_online_image_is_rejected_before_update() -> None:
    service, repository, audit_service = _service_with_mocks()
    repository.get_image_by_id.return_value = _image(
        product=_product(status=ProductStatus.ONLINE),
    )

    with pytest.raises(OnlineProductCannotBeModified):
        await service.update_product_image(
            20,
            updates={"sort": 10},
            operator_id=7,
            ip_address="127.0.0.1",
        )

    audit_service.log.assert_not_awaited()


async def test_option_image_cannot_be_cover() -> None:
    service, repository, audit_service = _service_with_mocks()
    repository.get_image_by_id.return_value = _image(option=_option())

    with pytest.raises(OptionImageCannotBeCover):
        await service.update_product_image(
            20,
            updates={"is_cover": True},
            operator_id=7,
            ip_address="127.0.0.1",
        )

    repository.clear_product_covers.assert_not_awaited()
    repository.update_image.assert_not_awaited()
    audit_service.log.assert_not_awaited()


async def test_sort_update_writes_single_snapshot_audit() -> None:
    service, repository, audit_service = _service_with_mocks()
    image = _image(sort=0)
    repository.get_image_by_id.return_value = image

    result = await service.update_product_image(
        20,
        updates={"sort": 10},
        operator_id=7,
        ip_address="127.0.0.1",
    )

    update = repository.update_image.await_args
    connection = update.kwargs["using_db"]
    assert result.sort == 10
    assert update.kwargs == {"sort": 10, "using_db": connection}
    repository.get_product_cover.assert_not_awaited()
    repository.clear_product_covers.assert_not_awaited()
    assert len(audit_service.log.await_args_list) == 1
    audit = audit_service.log.await_args.kwargs
    assert audit["action"] == "UPDATE_PRODUCT_IMAGE"
    assert json.loads(audit["description"]) == {
        "image_id": 20,
        "before": {"sort": 0},
        "after": {"sort": 10},
    }


async def test_cover_switch_writes_two_ordered_audits() -> None:
    service, repository, audit_service = _service_with_mocks()
    image = _image(sort=10)
    old_cover = _image(image_id=19, is_cover=True)
    repository.get_image_by_id.return_value = image
    repository.get_product_by_id.return_value = image.product
    repository.get_product_cover.return_value = old_cover

    result = await service.update_product_image(
        20,
        updates={"is_cover": True, "sort": 0},
        operator_id=7,
        ip_address="127.0.0.1",
    )

    cover_lookup = repository.get_product_cover.await_args
    connection = cover_lookup.kwargs["using_db"]
    lock = repository.get_product_for_update.await_args
    assert lock.args == (1,)
    assert lock.kwargs["using_db"] is connection
    assert cover_lookup.args == (1,)
    assert cover_lookup.kwargs["exclude_image_id"] == 20
    clear = repository.clear_product_covers.await_args
    assert clear.kwargs == {
        "exclude_image_id": 20,
        "using_db": connection,
    }
    assert result.is_cover is True
    assert result.sort == 0
    assert [item.kwargs["action"] for item in audit_service.log.await_args_list] == [
        "UPDATE_PRODUCT_IMAGE",
        "SET_PRODUCT_COVER",
    ]
    assert json.loads(audit_service.log.await_args_list[1].kwargs["description"]) == {
        "old_cover_image_id": 19,
        "new_cover_image_id": 20,
    }


async def test_delete_image_writes_snapshot_without_long_url() -> None:
    service, repository, audit_service = _service_with_mocks()
    image = _image(option=_option(), is_cover=False, sort=10)
    image.image_url = "https://example.com/" + "x" * 2000
    repository.get_image_by_id.return_value = image

    result = await service.delete_product_image(
        20,
        operator_id=7,
        ip_address="127.0.0.1",
    )

    update = repository.update_image.await_args
    connection = update.kwargs["using_db"]
    assert result.is_deleted is True
    assert update.kwargs == {"is_deleted": True, "using_db": connection}
    audit = audit_service.log.await_args.kwargs
    assert audit["action"] == "DELETE_PRODUCT_IMAGE"
    snapshot = json.loads(audit["description"])
    assert snapshot == {
        "image_id": 20,
        "product_id": 1,
        "experience_option_id": 11,
        "is_cover": False,
        "sort": 10,
    }
    assert len(audit["description"]) <= 256


async def test_image_flows_do_not_call_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = Mock()
    monkeypatch.setattr(ProductValidator, "validate_before_online", validate)
    service, repository, _ = _service_with_mocks()
    repository.get_product_by_id.return_value = _product()
    repository.get_option_by_id.return_value = _option()
    repository.get_image_by_id.return_value = _image()

    await service.create_product_image(
        1,
        image_url="https://example.com/public.jpg",
        is_cover=False,
        sort=0,
        operator_id=7,
        ip_address="127.0.0.1",
    )
    await service.create_option_image(
        11,
        image_url="https://example.com/option.jpg",
        sort=0,
        operator_id=7,
        ip_address="127.0.0.1",
    )
    await service.update_product_image(
        20,
        updates={"sort": 5},
        operator_id=7,
        ip_address="127.0.0.1",
    )

    validate.assert_not_called()


async def _create_real_aggregate() -> tuple[Product, ExperienceOption]:
    repository = ProductRepository()
    product = await repository.create_product(
        name="图片 Service 测试",
        product_type=ProductType.EXPERIENCE,
    )
    option = await repository.create_option(
        product=product,
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("699.00"),
    )
    return product, option


async def test_real_image_lifecycle_preserves_cover_invariant() -> None:
    product, option = await _create_real_aggregate()
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    first_cover = await service.create_product_image(
        product.id,
        image_url="https://example.com/first.jpg",
        is_cover=True,
        sort=10,
        operator_id=31,
        ip_address="127.0.0.1",
    )
    second_cover = await service.create_product_image(
        product.id,
        image_url="https://example.com/second.jpg",
        is_cover=True,
        sort=20,
        operator_id=31,
        ip_address="127.0.0.1",
    )
    option_image = await service.create_option_image(
        option.id,
        image_url="https://example.com/option.jpg",
        sort=5,
        operator_id=31,
        ip_address="127.0.0.1",
    )
    await service.update_product_image(
        first_cover.id,
        updates={"is_cover": True, "sort": 0},
        operator_id=31,
        ip_address="127.0.0.1",
    )
    await service.delete_product_image(
        option_image.id,
        operator_id=31,
        ip_address="127.0.0.1",
    )

    stored_first = await ProductImage.get(id=first_cover.id)
    stored_second = await ProductImage.get(id=second_cover.id)
    stored_option = await ProductImage.get(id=option_image.id)
    assert stored_first.is_cover is True
    assert stored_first.sort == 0
    assert stored_second.is_cover is False
    assert stored_option.is_deleted is True
    assert stored_option.experience_option_id == option.id
    assert await ProductImage.filter(
        product_id=product.id,
        experience_option_id=None,
        is_deleted=False,
        is_cover=True,
    ).count() == 1
    assert await AuditLog.filter(target_id=product.id).count() == 6


class _FailOnActionAuditLogService(AuditLogService):
    def __init__(self, action: str) -> None:
        super().__init__(AuditLogRepository())
        self.action = action

    async def log(
        self,
        operator_id: int,
        action: str,
        target_type: str,
        target_id: int,
        ip_address: str,
        description: str | None = None,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        if action == self.action:
            raise RuntimeError("audit failed")
        await super().log(
            operator_id=operator_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            description=description,
            using_db=using_db,
        )


async def test_real_create_audit_failure_restores_previous_cover() -> None:
    product, _ = await _create_real_aggregate()
    repository = ProductRepository()
    old_cover = await repository.create_image(
        product=product,
        image_url="https://example.com/old.jpg",
        is_cover=True,
    )
    service = ProductService(
        repository,
        _FailOnActionAuditLogService("CREATE_PRODUCT_IMAGE"),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.create_product_image(
            product.id,
            image_url="https://example.com/new.jpg",
            is_cover=True,
            sort=0,
            operator_id=31,
            ip_address="127.0.0.1",
        )

    assert (await ProductImage.get(id=old_cover.id)).is_cover is True
    assert not await ProductImage.filter(
        image_url="https://example.com/new.jpg",
    ).exists()
    assert not await AuditLog.filter(target_id=product.id).exists()


async def test_real_second_cover_audit_failure_rolls_back_everything() -> None:
    product, _ = await _create_real_aggregate()
    repository = ProductRepository()
    old_cover = await repository.create_image(
        product=product,
        image_url="https://example.com/old.jpg",
        is_cover=True,
        sort=10,
    )
    candidate = await repository.create_image(
        product=product,
        image_url="https://example.com/candidate.jpg",
        sort=20,
    )
    service = ProductService(
        repository,
        _FailOnActionAuditLogService("SET_PRODUCT_COVER"),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.update_product_image(
            candidate.id,
            updates={"is_cover": True, "sort": 0},
            operator_id=31,
            ip_address="127.0.0.1",
        )

    stored_old = await ProductImage.get(id=old_cover.id)
    stored_candidate = await ProductImage.get(id=candidate.id)
    assert stored_old.is_cover is True
    assert stored_candidate.is_cover is False
    assert stored_candidate.sort == 20
    assert not await AuditLog.filter(target_id=product.id).exists()


async def test_real_delete_audit_failure_restores_image() -> None:
    product, _ = await _create_real_aggregate()
    repository = ProductRepository()
    image = await repository.create_image(
        product=product,
        image_url="https://example.com/delete.jpg",
        is_cover=True,
    )
    service = ProductService(
        repository,
        _FailOnActionAuditLogService("DELETE_PRODUCT_IMAGE"),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        await service.delete_product_image(
            image.id,
            operator_id=31,
            ip_address="127.0.0.1",
        )

    stored = await ProductImage.get(id=image.id)
    assert stored.is_deleted is False
    assert stored.is_cover is True
    assert not await AuditLog.filter(target_id=product.id).exists()
