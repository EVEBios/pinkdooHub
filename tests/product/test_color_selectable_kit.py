"""M6 自选颜色 Kit 的 Product 端到端基础契约。"""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from tortoise.exceptions import (
    IntegrityError,
    ValidationError as ORMValidationError,
)

from app.api.deps import get_current_admin
from app.api.mappers.product import (
    map_admin_kit_product_detail,
    map_admin_product_kit_color,
    map_kit_product_detail,
)
from app.common.constants.product import (
    BEAD_COLOR_AUDIT_DESCRIPTION_MAX_LENGTH,
    BEAD_COLOR_AUDIT_HASH_LENGTH,
    BEAD_COLOR_SLOT_COUNT,
    COLOR_SELECTABLE_SALE_UNIT_GRAMS,
    MAX_BEAD_COLOR_SORT,
)
from app.common.enums.product import KitKind, ProductStatus
from app.common.exceptions import (
    BeadColorInUseByOnlineProduct,
    BeadColorNotConfigured,
    OnlineProductCannotBeModified,
    ProductNotReadyForOnline,
)
from app.main import app
from app.models.audit_log import AuditLog
from app.models.bead_color import BeadColor
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.product_kit_color import ProductKitColor
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.schemas.product import BeadColorUpdate, KitProductCreate
from app.schemas.product_response import BeadColorOut
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService


def _service() -> ProductService:
    return ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )


async def _create_color_selectable_product() -> Product:
    return await _service().create_kit_product(
        name="自选 221 色",
        description="每 10g 自选颜色",
        price=Decimal("3.50"),
        kit_kind=KitKind.COLOR_SELECTABLE,
        operator_id=7,
        ip_address="127.0.0.1",
    )


def test_kit_create_schema_defaults_fixed_and_accepts_color_selectable() -> None:
    fixed = KitProductCreate.model_validate(
        {"name": "固定套装", "price": "99.00"}
    )
    selectable = KitProductCreate.model_validate(
        {
            "name": "自选颜色",
            "price": "3.50",
            "kit_kind": "color_selectable",
        }
    )

    assert fixed.kit_kind is KitKind.FIXED
    assert selectable.kit_kind is KitKind.COLOR_SELECTABLE
    with pytest.raises(ValidationError):
        KitProductCreate.model_validate(
            {"name": "未知形态", "price": "3.50", "kit_kind": "future"}
        )


def test_bead_color_patch_allows_metadata_clear_but_not_null_flags() -> None:
    cleared = BeadColorUpdate.model_validate(
        {"color_code": None, "name": None}
    )

    assert cleared.model_dump(exclude_unset=True) == {
        "color_code": None,
        "name": None,
    }
    with pytest.raises(ValidationError):
        BeadColorUpdate.model_validate({"is_active": None})
    with pytest.raises(ValidationError):
        BeadColorUpdate.model_validate({})


def test_bead_color_sort_schema_has_signed_smallint_upper_bound() -> None:
    maximum = BeadColorUpdate.model_validate(
        {"sort": MAX_BEAD_COLOR_SORT}
    )

    assert maximum.sort == MAX_BEAD_COLOR_SORT
    with pytest.raises(ValidationError):
        BeadColorUpdate.model_validate(
            {"sort": MAX_BEAD_COLOR_SORT + 1}
        )

    response = {
        "id": 1,
        "slot_no": 1,
        "color_code": None,
        "name": None,
        "swatch_image_url": None,
        "sort": MAX_BEAD_COLOR_SORT,
        "is_active": False,
        "is_configured": False,
    }
    assert BeadColorOut.model_validate(response).sort == MAX_BEAD_COLOR_SORT
    response["sort"] = MAX_BEAD_COLOR_SORT + 1
    with pytest.raises(ValidationError):
        BeadColorOut.model_validate(response)


async def test_bead_color_model_has_signed_smallint_upper_bound() -> None:
    maximum = await BeadColor.create(
        slot_no=1,
        sort=MAX_BEAD_COLOR_SORT,
    )

    assert maximum.sort == MAX_BEAD_COLOR_SORT
    with pytest.raises(ORMValidationError, match="less or equal to 32767"):
        await BeadColor.create(
            slot_no=2,
            sort=MAX_BEAD_COLOR_SORT + 1,
        )


async def test_color_selectable_create_builds_exact_atomic_zero_stock_shape() -> None:
    product = await _create_color_selectable_product()
    kit = await ProductKit.get(product_id=product.id)
    colors = await ProductKitColor.filter(product_id=product.id).order_by(
        "bead_color_id"
    )
    slots = await BeadColor.all().order_by("slot_no")

    assert kit.kit_kind is KitKind.COLOR_SELECTABLE
    assert kit.sale_unit_grams == COLOR_SELECTABLE_SALE_UNIT_GRAMS
    assert kit.stock is None
    assert len(slots) == BEAD_COLOR_SLOT_COUNT
    assert [color.slot_no for color in slots] == list(
        range(1, BEAD_COLOR_SLOT_COUNT + 1)
    )
    assert all(color.color_code is None for color in slots)
    assert all(color.name is None for color in slots)
    assert all(color.swatch_image_url is None for color in slots)
    assert all(not color.is_active for color in slots)
    assert [color.sort for color in slots] == list(
        range(1, BEAD_COLOR_SLOT_COUNT + 1)
    )
    assert len(colors) == BEAD_COLOR_SLOT_COUNT
    assert all(not color.is_enabled for color in colors)
    assert all(color.stock_units == 0 for color in colors)


async def test_partial_global_palette_fails_without_silent_repair() -> None:
    await BeadColor.create(slot_no=1, sort=1)

    with pytest.raises(
        RuntimeError,
        match="Global bead color catalog must contain slots 1 through 221",
    ):
        await _create_color_selectable_product()

    assert await BeadColor.all().count() == 1
    assert not await Product.filter(name="自选 221 色").exists()
    assert not await ProductKit.all().exists()
    assert not await ProductKitColor.all().exists()


async def test_product_color_unique_pair_and_batch_snapshot_metadata() -> None:
    product = await _create_color_selectable_product()
    color = await ProductKitColor.filter(product_id=product.id).first()
    assert color is not None

    with pytest.raises(IntegrityError):
        await ProductKitColor.create(
            product_id=product.id,
            bead_color_id=color.bead_color_id,
        )

    loaded = await ProductRepository().get_kit_colors_by_ids({color.id})
    assert len(loaded) == 1
    assert loaded[0].product_id == product.id
    assert loaded[0].bead_color.slot_no == 1


@pytest.mark.parametrize(
    ("color_code", "name", "is_active"),
    [
        ("C001", "示例红", False),
        (None, None, False),
        (None, None, True),
    ],
)
def test_admin_color_output_preserves_non_sale_ready_enabled_state(
    color_code: str | None,
    name: str | None,
    is_active: bool,
) -> None:
    """管理端必须能展示并修复非销售就绪状态。"""

    bead_color = SimpleNamespace(
        id=11,
        slot_no=1,
        color_code=color_code,
        name=name,
        swatch_image_url=None,
        sort=1,
        is_active=is_active,
    )
    kit_color = SimpleNamespace(
        id=21,
        bead_color_id=11,
        bead_color=bead_color,
        is_enabled=True,
        stock_units=0,
    )

    mapped = map_admin_product_kit_color(kit_color).model_dump(mode="json")

    assert mapped["is_enabled"] is True
    assert mapped["is_active"] is is_active
    assert mapped["is_configured"] is (
        color_code is not None and name is not None
    )


async def test_unconfigured_color_cannot_activate_or_enable() -> None:
    product = await _create_color_selectable_product()
    service = _service()
    bead_color = await BeadColor.get(slot_no=1)
    kit_color = await ProductKitColor.get(
        product_id=product.id,
        bead_color_id=bead_color.id,
    )

    with pytest.raises(BeadColorNotConfigured):
        await service.update_bead_color(
            bead_color.id,
            updates={"is_active": True},
            operator_id=7,
            ip_address="127.0.0.1",
        )
    with pytest.raises(BeadColorNotConfigured):
        await service.update_product_kit_color(
            kit_color.id,
            is_enabled=True,
            operator_id=7,
            ip_address="127.0.0.1",
        )


async def test_bead_color_update_uses_stable_product_first_lock_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_color_selectable_product()
    bead_color = await BeadColor.get(slot_no=1)
    repository = ProductRepository()
    service = ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )
    events: list[str] = []

    original_list = repository.list_product_ids_by_bead_color
    original_products = repository.get_products_for_update
    original_color = repository.get_bead_color_for_update
    original_enabled = repository.get_enabled_kit_colors_for_update

    async def list_product_ids(*args: object, **kwargs: object) -> list[int]:
        events.append("list_product_ids")
        return await original_list(*args, **kwargs)

    async def lock_products(*args: object, **kwargs: object) -> list[Product]:
        events.append("lock_products")
        return await original_products(*args, **kwargs)

    async def lock_color(*args: object, **kwargs: object) -> BeadColor | None:
        events.append("lock_bead_color")
        return await original_color(*args, **kwargs)

    async def lock_enabled(
        *args: object,
        **kwargs: object,
    ) -> list[ProductKitColor]:
        events.append("lock_enabled_colors")
        return await original_enabled(*args, **kwargs)

    monkeypatch.setattr(
        repository,
        "list_product_ids_by_bead_color",
        list_product_ids,
    )
    monkeypatch.setattr(repository, "get_products_for_update", lock_products)
    monkeypatch.setattr(repository, "get_bead_color_for_update", lock_color)
    monkeypatch.setattr(
        repository,
        "get_enabled_kit_colors_for_update",
        lock_enabled,
    )

    await service.update_bead_color(
        bead_color.id,
        updates={"color_code": "LOCK-001", "name": "锁序色"},
        operator_id=7,
        ip_address="127.0.0.1",
    )

    assert events == [
        "list_product_ids",
        "lock_products",
        "lock_bead_color",
        "lock_enabled_colors",
    ]


async def test_bead_color_update_recalculates_from_locked_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_color_selectable_product()
    bead_color = await BeadColor.get(slot_no=1)
    repository = ProductRepository()
    original_lock = repository.get_bead_color_for_update

    async def configure_then_lock(
        bead_color_id: int,
        **kwargs: object,
    ) -> BeadColor | None:
        await (
            BeadColor.filter(id=bead_color_id)
            .using_db(kwargs["using_db"])
            .update(color_code="LOCKED-001", name="锁后元数据")
        )
        return await original_lock(bead_color_id, **kwargs)

    monkeypatch.setattr(
        repository,
        "get_bead_color_for_update",
        configure_then_lock,
    )
    service = ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )

    updated = await service.update_bead_color(
        bead_color.id,
        updates={"is_active": True},
        operator_id=7,
        ip_address="127.0.0.1",
    )

    assert updated.color_code == "LOCKED-001"
    assert updated.name == "锁后元数据"
    assert updated.is_active is True


async def test_bead_color_audit_is_valid_bounded_json_for_max_unicode() -> None:
    await _create_color_selectable_product()
    service = _service()
    bead_color = await BeadColor.get(slot_no=1)
    await service.update_bead_color(
        bead_color.id,
        updates={
            "color_code": "旧" * 50,
            "name": "旧名" * 50,
            "is_active": True,
        },
        operator_id=7,
        ip_address="127.0.0.1",
    )

    await service.update_bead_color(
        bead_color.id,
        updates={
            "color_code": "新" * 50,
            "name": "新名" * 50,
            "sort": MAX_BEAD_COLOR_SORT,
            "is_active": False,
        },
        operator_id=7,
        ip_address="127.0.0.1",
    )

    audit = await AuditLog.filter(
        action="UPDATE_BEAD_COLOR",
        target_id=bead_color.id,
    ).order_by("-id").first()
    assert audit is not None and audit.description is not None
    assert len(audit.description) <= BEAD_COLOR_AUDIT_DESCRIPTION_MAX_LENGTH
    payload = json.loads(audit.description)
    assert payload["changed_fields"] == [
        "color_code",
        "name",
        "sort",
        "is_active",
    ]
    assert payload["before"][0] == {
        "len": 50,
        "sha256": payload["before"][0]["sha256"],
    }
    assert len(payload["before"][0]["sha256"]) == BEAD_COLOR_AUDIT_HASH_LENGTH
    assert payload["before"][1]["len"] == 100
    assert payload["after"][0]["len"] == 50
    assert payload["after"][1]["len"] == 100
    assert payload["before"][2:] == [1, True]
    assert payload["after"][2:] == [MAX_BEAD_COLOR_SORT, False]


async def test_product_color_update_rechecks_online_state_after_product_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = await _create_color_selectable_product()
    bead_color = await BeadColor.get(slot_no=1)
    await _service().update_bead_color(
        bead_color.id,
        updates={
            "color_code": "RACE-001",
            "name": "并发复验色",
            "is_active": True,
        },
        operator_id=7,
        ip_address="127.0.0.1",
    )
    kit_color = await ProductKitColor.get(
        product_id=product.id,
        bead_color_id=bead_color.id,
    )
    repository = ProductRepository()
    original_candidate = repository.get_product_kit_color_by_id

    async def load_stale_candidate(
        *args: object,
        **kwargs: object,
    ) -> ProductKitColor | None:
        candidate = await original_candidate(*args, **kwargs)
        await Product.filter(id=product.id).update(
            status=ProductStatus.ONLINE,
        )
        return candidate

    monkeypatch.setattr(
        repository,
        "get_product_kit_color_by_id",
        load_stale_candidate,
    )
    service = ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )

    with pytest.raises(OnlineProductCannotBeModified):
        await service.update_product_kit_color(
            kit_color.id,
            is_enabled=True,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    await kit_color.refresh_from_db()
    assert kit_color.is_enabled is False
    assert not await AuditLog.filter(
        action="UPDATE_PRODUCT_KIT_COLOR",
        target_id=product.id,
    ).exists()


async def test_bead_color_update_rechecks_locked_referencing_product_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = await _create_color_selectable_product()
    service = _service()
    bead_color = await BeadColor.get(slot_no=1)
    await service.update_bead_color(
        bead_color.id,
        updates={
            "color_code": "GLOBAL-001",
            "name": "全局并发色",
            "is_active": True,
        },
        operator_id=7,
        ip_address="127.0.0.1",
    )
    kit_color = await ProductKitColor.get(
        product_id=product.id,
        bead_color_id=bead_color.id,
    )
    await service.update_product_kit_color(
        kit_color.id,
        is_enabled=True,
        operator_id=7,
        ip_address="127.0.0.1",
    )
    repository = ProductRepository()
    original_list = repository.list_product_ids_by_bead_color

    async def list_then_publish(
        *args: object,
        **kwargs: object,
    ) -> list[int]:
        product_ids = await original_list(*args, **kwargs)
        await (
            Product.filter(id=product.id)
            .using_db(kwargs["using_db"])
            .update(status=ProductStatus.ONLINE)
        )
        return product_ids

    monkeypatch.setattr(
        repository,
        "list_product_ids_by_bead_color",
        list_then_publish,
    )
    protected_service = ProductService(
        repository,
        AuditLogService(AuditLogRepository()),
    )
    audits_before = await AuditLog.filter(
        action="UPDATE_BEAD_COLOR",
        target_id=bead_color.id,
    ).count()

    with pytest.raises(BeadColorInUseByOnlineProduct):
        await protected_service.update_bead_color(
            bead_color.id,
            updates={"name": "不应写入"},
            operator_id=7,
            ip_address="127.0.0.1",
        )

    await bead_color.refresh_from_db()
    assert bead_color.name == "全局并发色"
    assert await AuditLog.filter(
        action="UPDATE_BEAD_COLOR",
        target_id=bead_color.id,
    ).count() == audits_before


async def test_enabled_zero_stock_color_can_go_online_and_maps_without_leak() -> None:
    product = await _create_color_selectable_product()
    service = _service()
    repository = ProductRepository()
    bead_color = await BeadColor.get(slot_no=1)
    bead_color = await service.update_bead_color(
        bead_color.id,
        updates={
            "color_code": "C001",
            "name": "示例红",
            "is_active": True,
        },
        operator_id=7,
        ip_address="127.0.0.1",
    )
    kit_color = await ProductKitColor.get(
        product_id=product.id,
        bead_color_id=bead_color.id,
    )
    await service.update_product_kit_color(
        kit_color.id,
        is_enabled=True,
        operator_id=7,
        ip_address="127.0.0.1",
    )
    await repository.create_image(
        product=product,
        image_url="https://example.com/selectable-cover.jpg",
        is_cover=True,
    )

    online = await service.online_product(
        product.id,
        operator_id=7,
        ip_address="127.0.0.1",
    )
    assert online.status.value == "online"

    detail = await service.get_online_product_detail(
        product.id,
        product_type=product.product_type,
    )
    public = map_kit_product_detail(detail).model_dump(mode="json")
    admin = map_admin_kit_product_detail(detail).model_dump(mode="json")

    assert public["kit_kind"] == {
        "value": "color_selectable",
        "label": "自选颜色",
    }
    assert public["sale_unit_grams"] == 10
    assert public["stock"] is None
    assert public["available"] is False
    assert public["colors"] == [
        {
            "id": kit_color.id,
            "bead_color_id": bead_color.id,
            "slot_no": 1,
            "color_code": "C001",
            "name": "示例红",
            "swatch_image_url": None,
            "available": False,
        }
    ]
    assert "stock_units" not in public["colors"][0]
    assert len(admin["colors"]) == BEAD_COLOR_SLOT_COUNT
    assert admin["colors"][0]["stock_units"] == 0
    assert admin["colors"][0]["is_enabled"] is True


async def test_color_selectable_online_requires_an_enabled_color() -> None:
    product = await _create_color_selectable_product()
    repository = ProductRepository()
    await repository.create_image(
        product=product,
        image_url="https://example.com/selectable-cover.jpg",
        is_cover=True,
    )

    with pytest.raises(ProductNotReadyForOnline) as exc_info:
        await _service().online_product(
            product.id,
            operator_id=7,
            ip_address="127.0.0.1",
        )

    assert exc_info.value.data == {
        "issues": ["at least one product kit color must be enabled"]
    }


@pytest.fixture
def color_admin_api() -> None:
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=17)
    yield
    app.dependency_overrides.pop(get_current_admin, None)


async def test_color_admin_http_routes_form_a_minimal_configuration_flow(
    client: AsyncClient,
    color_admin_api: None,
) -> None:
    created = await client.post(
        "/api/v1/admin/products/kit",
        json={
            "name": "HTTP 自选颜色",
            "description": "按 10g 选色",
            "price": "3.50",
            "kit_kind": "color_selectable",
        },
    )
    assert created.status_code == 201
    created_data = created.json()["data"]
    assert created_data["kit_kind"]["value"] == "color_selectable"
    assert created_data["sale_unit_grams"] == 10

    palette = await client.get("/api/v1/admin/bead-colors?page=1&page_size=100")
    assert palette.status_code == 200
    assert palette.json()["data"]["total"] == BEAD_COLOR_SLOT_COUNT
    first = palette.json()["data"]["items"][0]
    assert first["slot_no"] == 1
    assert first["is_configured"] is False
    assert first["swatch_image_url"] is None

    configured = await client.patch(
        f"/api/v1/admin/bead-colors/{first['id']}",
        json={"color_code": "HTTP-001", "name": "HTTP 红", "is_active": True},
    )
    assert configured.status_code == 200
    assert configured.json()["data"]["is_configured"] is True

    product_id = created_data["id"]
    detail = await client.get(f"/api/v1/admin/products/kit/{product_id}")
    assert detail.status_code == 200
    first_kit_color = detail.json()["data"]["colors"][0]
    enabled = await client.patch(
        f"/api/v1/admin/product-kit-colors/{first_kit_color['id']}",
        json={"is_enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["data"]["is_enabled"] is True
    assert await AuditLog.filter(
        action="UPDATE_PRODUCT_KIT_COLOR",
        target_id=product_id,
    ).exists()
