"""Gate A MARD 221 在真实 MySQL 的事务、文件和重放门槛。"""

import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from tortoise import connections
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from app.common.enums.product import KitKind, ProductStatus, ProductType
from app.models.bead_color import BeadColor
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.product_kit_color import ProductKitColor
from app.repositories.product_repo import ProductRepository
from app.tasks import gatea_mard_publish as publisher


pytestmark = pytest.mark.mysql


class _HoldingProductBarrierRepository(ProductRepository):
    """锁定全部 Product 后等待测试放行。"""

    def __init__(self) -> None:
        self.lock_acquired = asyncio.Event()
        self.release = asyncio.Event()

    async def list_all_products_for_update(
        self,
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[Product]:
        products = await super().list_all_products_for_update(using_db=using_db)
        self.lock_acquired.set()
        await self.release.wait()
        return products


def _configure_publisher(
    monkeypatch: pytest.MonkeyPatch,
    image_root: Path,
) -> None:
    monkeypatch.setattr(publisher, "STORAGE_ROOT", image_root)
    monkeypatch.setattr(
        publisher,
        "settings",
        SimpleNamespace(
            app_env="production",
            db_engine="mysql",
            product_image_upload_dir=str(image_root),
            product_image_base_url=(
                "https://api-test.pinkdoohub.cn/uploads/products"
            ),
        ),
    )


async def _make_catalog_current(repository: ProductRepository) -> None:
    preview = await publisher.plan_publish(repository)
    if not preview.already_current:
        await publisher.apply_publish(repository, preview)
    replay = await publisher.plan_publish(repository)
    assert replay.already_current is True


async def _create_draft_product_with_enabled_color(name: str) -> Product:
    product = await Product.create(
        name=name,
        product_type=ProductType.KIT,
        status=ProductStatus.DRAFT,
    )
    await ProductKit.create(
        product_id=product.id,
        price=Decimal("1.00"),
        stock=None,
        kit_kind=KitKind.COLOR_SELECTABLE,
        sale_unit_grams=10,
    )
    first_color = await BeadColor.get(slot_no=1)
    await ProductKitColor.create(
        product_id=product.id,
        bead_color_id=first_color.id,
        is_enabled=True,
        stock_units=1,
    )
    return product


async def _wait_for_data_lock_wait() -> None:
    """等待 performance_schema 证明第二事务正在等待 InnoDB 行锁。"""

    connection = connections.get("default")
    for _ in range(200):
        rows = await connection.execute_query_dict(
            "SELECT COUNT(*) AS wait_count "
            "FROM performance_schema.data_lock_waits"
        )
        if int(rows[0]["wait_count"]) > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("expected an observable Product row-lock wait")


async def _reset_bead_catalog() -> None:
    connection = connections.get("default")
    await connection.execute_query(
        "UPDATE bead_colors SET color_code = NULL, name = NULL, "
        "swatch_image_url = NULL, sort = slot_no, is_active = 0"
    )


async def test_gatea_mard_publish_updates_mysql_and_replays_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    _configure_publisher(monkeypatch, image_root)
    repository = ProductRepository()
    connection = connections.get("default")
    try:
        preview = await publisher.plan_publish(repository)
        assert preview.database_changes == 221
        assert preview.images_to_create == 221
        assert preview.images_reused == 0

        assert await publisher.apply_publish(repository, preview) == 221
        replay = await publisher.plan_publish(repository)
        assert replay.already_current is True
        assert replay.database_changes == 0
        assert replay.images_to_create == 0
        assert replay.images_reused == 221
        assert await publisher.apply_publish(repository, replay) == 0

        online_product = await Product.create(
            name="MARD Online no-op safety gate",
            product_type=ProductType.KIT,
            status=ProductStatus.ONLINE,
        )
        await ProductKit.create(
            product_id=online_product.id,
            price=Decimal("1.00"),
            stock=None,
            kit_kind=KitKind.COLOR_SELECTABLE,
            sale_unit_grams=10,
        )
        first_color = await BeadColor.get(slot_no=1)
        await ProductKitColor.create(
            product_id=online_product.id,
            bead_color_id=first_color.id,
            is_enabled=True,
            stock_units=1,
        )
        bead_rows_before = await connection.execute_query_dict(
            "SELECT id, slot_no, color_code, name, swatch_hex, "
            "swatch_image_url, sort, is_active, updated_at "
            "FROM bead_colors ORDER BY slot_no"
        )
        image_state_before = {
            path.name: (
                path.stat().st_mode,
                path.stat().st_mtime_ns,
                path.read_bytes(),
            )
            for path in image_root.glob("*.png")
        }

        online_preview = await publisher.plan_publish(repository)
        assert online_preview.already_current is True
        assert online_preview.database_changes == 0
        assert online_preview.images_to_create == 0
        assert online_preview.images_reused == 221
        assert await publisher.apply_publish(repository, online_preview) == 0
        online_replay = await publisher.plan_publish(repository)
        assert online_replay.already_current is True
        assert await publisher.apply_publish(repository, online_replay) == 0

        assert await connection.execute_query_dict(
            "SELECT id, slot_no, color_code, name, swatch_hex, "
            "swatch_image_url, sort, is_active, updated_at "
            "FROM bead_colors ORDER BY slot_no"
        ) == bead_rows_before
        assert {
            path.name: (
                path.stat().st_mode,
                path.stat().st_mtime_ns,
                path.read_bytes(),
            )
            for path in image_root.glob("*.png")
        } == image_state_before

        rows = await connection.execute_query_dict(
            "SELECT COUNT(*) AS total, SUM(is_active <> 0) AS active, "
            "COUNT(DISTINCT color_code) AS codes, "
            "COUNT(DISTINCT swatch_hex) AS hex_values, "
            "COUNT(DISTINCT swatch_image_url) AS urls "
            "FROM bead_colors"
        )
        assert {key: int(value) for key, value in rows[0].items()} == {
            "total": 221,
            "active": 221,
            "codes": 221,
            "hex_values": 221,
            "urls": 221,
        }
        assert len(list(image_root.glob("*.png"))) == 221
        assert all(
            path.stat().st_mode & 0o777 == 0o644
            for path in image_root.glob("*.png")
        )

        first_image = image_root / online_preview.colors[0].image_filename
        first_image.unlink()
        with pytest.raises(
            publisher.GateAMardPublishError,
            match="refuse catalog changes while an Online product enables colors",
        ):
            await publisher.plan_publish(repository)
        assert not first_image.exists()
    finally:
        await _reset_bead_catalog()


async def test_publisher_waits_for_inflight_online_transition_then_rejects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    _configure_publisher(monkeypatch, image_root)
    repository = ProductRepository()
    await _make_catalog_current(repository)
    product = await _create_draft_product_with_enabled_color(
        "MARD Online transition holds Product lock"
    )
    first_image = image_root / publisher.load_manifest(publisher.MANIFEST)[
        0
    ].image_filename
    first_image.unlink()
    changed_plan = await publisher.plan_publish(repository)
    assert changed_plan.images_to_create == 1

    online_lock_acquired = asyncio.Event()
    release_online = asyncio.Event()
    online_task: asyncio.Task[None] | None = None
    apply_task: asyncio.Task[int] | None = None

    async def hold_uncommitted_online_transition() -> None:
        async with in_transaction() as connection:
            locked = await repository.get_product_for_update(
                product.id,
                using_db=connection,
            )
            assert locked is not None
            await repository.update_product(
                locked,
                status=ProductStatus.ONLINE,
                using_db=connection,
            )
            online_lock_acquired.set()
            await release_online.wait()

    try:
        online_task = asyncio.create_task(hold_uncommitted_online_transition())
        await asyncio.wait_for(online_lock_acquired.wait(), timeout=5)
        apply_task = asyncio.create_task(
            publisher.apply_publish(repository, changed_plan)
        )
        try:
            await asyncio.wait_for(_wait_for_data_lock_wait(), timeout=5)
        finally:
            release_online.set()
        await asyncio.wait_for(online_task, timeout=5)
        with pytest.raises(
            publisher.GateAMardPublishError,
            match="changed after preview while an Online product",
        ):
            await asyncio.wait_for(apply_task, timeout=5)
        assert not first_image.exists()
    finally:
        release_online.set()
        await asyncio.gather(
            *(task for task in (online_task, apply_task) if task is not None),
            return_exceptions=True,
        )
        await _reset_bead_catalog()


async def test_publisher_product_barrier_blocks_online_until_publish_commits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    _configure_publisher(monkeypatch, image_root)
    setup_repository = ProductRepository()
    await _make_catalog_current(setup_repository)
    product = await _create_draft_product_with_enabled_color(
        "MARD publisher holds Product barrier"
    )
    first_image = image_root / publisher.load_manifest(publisher.MANIFEST)[
        0
    ].image_filename
    first_image.unlink()
    changed_plan = await publisher.plan_publish(setup_repository)
    assert changed_plan.images_to_create == 1

    holding_repository = _HoldingProductBarrierRepository()
    online_lock_acquired = asyncio.Event()
    apply_task: asyncio.Task[int] | None = None
    online_task: asyncio.Task[None] | None = None

    async def transition_online() -> None:
        async with in_transaction() as connection:
            locked = await setup_repository.get_product_for_update(
                product.id,
                using_db=connection,
            )
            assert locked is not None
            online_lock_acquired.set()
            await setup_repository.update_product(
                locked,
                status=ProductStatus.ONLINE,
                using_db=connection,
            )

    try:
        apply_task = asyncio.create_task(
            publisher.apply_publish(holding_repository, changed_plan)
        )
        await asyncio.wait_for(holding_repository.lock_acquired.wait(), timeout=5)
        online_task = asyncio.create_task(transition_online())
        try:
            await asyncio.wait_for(_wait_for_data_lock_wait(), timeout=5)
            assert not online_lock_acquired.is_set()
        finally:
            holding_repository.release.set()

        created_images, _ = await asyncio.wait_for(
            asyncio.gather(apply_task, online_task),
            timeout=10,
        )
        assert created_images == 1
        assert online_lock_acquired.is_set()
        assert first_image.is_file()
        stored_product = await Product.get(id=product.id)
        assert stored_product.status == ProductStatus.ONLINE
    finally:
        holding_repository.release.set()
        await asyncio.gather(
            *(task for task in (apply_task, online_task) if task is not None),
            return_exceptions=True,
        )
        await _reset_bead_catalog()
