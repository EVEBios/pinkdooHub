from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.pagination import Page
from app.models.product import Product
from app.models.product_image import ProductImage
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService
from app.storage.image import LocalImageStorage
from app.storage.image import StoredImage
from app.tasks.product_functional_seed import (
    MULTI_OPTION_SEED_NAME,
    SEED_SPECS,
    _store_image,
    assert_local_seed_allowed,
    seed_products,
)


def allowed_arguments(tmp_path: Path) -> dict[str, object]:
    return {
        "app_env": "development",
        "db_engine": "sqlite",
        "db_sqlite_path": str(tmp_path / "db.sqlite3"),
        "upload_dir": str(tmp_path / "uploads"),
        "apply": True,
        "confirm_local_only": True,
        "repository_root": tmp_path,
    }


def test_local_seed_gate_accepts_explicit_repository_local_development(tmp_path):
    assert_local_seed_allowed(**allowed_arguments(tmp_path))


@pytest.mark.parametrize("app_env", ["testing", "production"])
def test_local_seed_gate_rejects_non_development_environment(tmp_path, app_env):
    arguments = allowed_arguments(tmp_path)
    arguments["app_env"] = app_env

    with pytest.raises(RuntimeError, match="APP_ENV must be development"):
        assert_local_seed_allowed(**arguments)


def test_local_seed_gate_rejects_mysql(tmp_path):
    arguments = allowed_arguments(tmp_path)
    arguments["db_engine"] = "mysql"

    with pytest.raises(RuntimeError, match="DB_ENGINE must be sqlite"):
        assert_local_seed_allowed(**arguments)


@pytest.mark.parametrize("missing_flag", ["apply", "confirm_local_only"])
def test_local_seed_gate_requires_both_explicit_flags(tmp_path, missing_flag):
    arguments = allowed_arguments(tmp_path)
    arguments[missing_flag] = False

    with pytest.raises(RuntimeError, match="both --apply and --confirm-local-only"):
        assert_local_seed_allowed(**arguments)


@pytest.mark.parametrize("path_field", ["db_sqlite_path", "upload_dir"])
def test_local_seed_gate_rejects_paths_outside_repository(tmp_path, path_field):
    arguments = allowed_arguments(tmp_path)
    arguments[path_field] = str(tmp_path.parent / "shared" / "data")

    with pytest.raises(RuntimeError, match="must be inside repository"):
        assert_local_seed_allowed(**arguments)


def test_seed_catalog_covers_both_types_and_pagination():
    assert len(SEED_SPECS) == 13
    assert sum(spec.product_type == ProductType.EXPERIENCE for spec in SEED_SPECS) == 7
    assert sum(spec.product_type == ProductType.KIT for spec in SEED_SPECS) == 6
    assert len({spec.name for spec in SEED_SPECS}) == 13
    multi_option = next(
        spec for spec in SEED_SPECS if spec.name == MULTI_OPTION_SEED_NAME
    )
    assert len(multi_option.option_specs) == 2
    assert {option.price for option in multi_option.option_specs} == {
        Decimal("59.00"),
        Decimal("89.00"),
    }


@pytest.mark.asyncio
async def test_seed_products_skips_complete_existing_catalog():
    service = Mock()

    async def list_existing(**kwargs):
        spec = next(item for item in SEED_SPECS if item.name == kwargs["keyword"])
        product = SimpleNamespace(
            name=spec.name,
            is_deleted=False,
            status=ProductStatus.ONLINE,
            product_type=spec.product_type,
        )
        return Page(items=[product], total=1, page=1, page_size=100, pages=1)

    service.list_admin_products = AsyncMock(side_effect=list_existing)

    totals = await seed_products(service, Mock(), operator_id=1)

    assert totals.created == 0
    assert totals.skipped == 13


@pytest.mark.asyncio
async def test_seed_products_stops_on_reserved_name_conflict():
    spec = SEED_SPECS[0]
    conflicting = SimpleNamespace(
        name=spec.name,
        is_deleted=False,
        status=ProductStatus.DRAFT,
        product_type=spec.product_type,
    )
    service = Mock()
    service.list_admin_products = AsyncMock(
        return_value=Page(
            items=[conflicting], total=1, page=1, page_size=100, pages=1
        )
    )

    with pytest.raises(RuntimeError, match="incomplete/conflicting"):
        await seed_products(service, Mock(), operator_id=1)


@pytest.mark.asyncio
async def test_store_image_compensates_file_when_database_registration_fails():
    service = Mock()
    service.create_product_image = AsyncMock(side_effect=RuntimeError("db failed"))
    storage = Mock()
    storage.save.return_value = StoredImage(
        key="a" * 32 + ".png",
        url="/uploads/products/" + "a" * 32 + ".png",
        media_type="image/png",
        size=20,
    )

    with pytest.raises(RuntimeError, match="db failed"):
        await _store_image(
            service,
            storage,
            operator_id=1,
            product_id=10,
            is_cover=True,
        )

    storage.delete.assert_called_once_with("a" * 32 + ".png")


@pytest.mark.asyncio
async def test_real_seed_creates_online_catalog_and_second_run_is_idempotent(tmp_path):
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )
    storage = LocalImageStorage(
        root=tmp_path / "uploads",
        base_url="/uploads/products",
    )

    first = await seed_products(service, storage, operator_id=51)
    second = await seed_products(service, storage, operator_id=51)

    assert first.created == 13
    assert first.skipped == 0
    assert second.created == 0
    assert second.skipped == 13
    products = await Product.filter(name__startswith="[LOCAL-FE]")
    assert len(products) == 13
    assert all(product.status == ProductStatus.ONLINE for product in products)
    assert await ProductImage.filter(is_deleted=False).count() == 21
    assert len(list((tmp_path / "uploads").glob("*.png"))) == 21

    multi_option_product = next(
        product for product in products if product.name == MULTI_OPTION_SEED_NAME
    )
    detail = await service.get_online_product_detail(
        multi_option_product.id,
        product_type=ProductType.EXPERIENCE,
    )
    options = list(detail.experience_options)
    assert [option.price for option in options] == [
        Decimal("59.00"),
        Decimal("89.00"),
    ]
    assert [
        (option.duration, option.participants, option.day_type)
        for option in options
    ] == [
        (60, 1, DayType.WEEKDAY),
        (120, 2, DayType.HOLIDAY),
    ]
    assert all(len(list(option.images)) == 1 for option in options)
    option_image_contents = []
    for option in options:
        key = storage.key_from_url(list(option.images)[0].image_url)
        assert key is not None
        option_image_contents.append((storage.root / key).read_bytes())
    assert len(set(option_image_contents)) == 2
