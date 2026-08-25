"""仅供本地开发环境使用的 Product 前端功能测试数据命令。"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import struct
import zlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from tortoise import Tortoise

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.database import TORTOISE_ORM
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import InventoryService
from app.services.product_service import ProductService
from app.storage.image import LocalImageStorage

logger = logging.getLogger(__name__)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEED_PREFIX = "[LOCAL-FE]"
LOCAL_IP = "127.0.0.1"
LEGACY_INVALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """构造包含长度和 CRC 的标准 PNG chunk。"""

    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", checksum)
    )


def _build_test_png(*, pixels: bytes | None = None) -> bytes:
    """生成可被真实图片解码器读取的 2×2 RGB PNG。"""

    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    # 每行第一个字节是 PNG filter type 0，随后是两个 RGB 像素。
    pixel_rows = pixels or (
        b"\x00\xff\x7a\xb8\xff\xd3\xe4"
        b"\x00\xff\xd3\xe4\xff\x7a\xb8"
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(pixel_rows))
        + _png_chunk(b"IEND", b"")
    )


PNG_BYTES = _build_test_png()
ALTERNATE_OPTION_PNG_BYTES = _build_test_png(
    pixels=(
        b"\x00\x68\xb5\xff\x96\xd0\xff"
        b"\x00\x96\xd0\xff\x68\xb5\xff"
    ),
)


@dataclass(frozen=True, slots=True)
class SeedOptionSpec:
    duration_minutes: int
    participants: int
    day_type: DayType
    price: Decimal
    image_bytes: bytes = PNG_BYTES


@dataclass(frozen=True, slots=True)
class SeedSpec:
    name: str
    description: str
    product_type: ProductType
    price: Decimal
    option_specs: tuple[SeedOptionSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class SeedTotals:
    created: int = 0
    skipped: int = 0
    repaired_images: int = 0
    in_stock_kit_id: int | None = None
    in_stock_kit_stock: int = 0
    inventory_adjusted: bool = False
    inventory_replayed: bool = False


@dataclass(frozen=True, slots=True)
class InventorySeedResult:
    product_id: int
    stock: int
    adjusted: bool
    replayed: bool


MULTI_OPTION_SEED_NAME = f"{SEED_PREFIX} 多配置拼豆体验"
IN_STOCK_KIT_SEED_NAME = f"{SEED_PREFIX} 拼豆材料包 01"
IN_STOCK_KIT_INITIAL_CHANGE = 8
IN_STOCK_KIT_IDEMPOTENCY_KEY = "local-fe-product-seed-kit-01-stock-v1"
IN_STOCK_KIT_REASON = "Local frontend functional seed initial stock"


SEED_SPECS = (
    tuple(
        SeedSpec(
            f"{SEED_PREFIX} 拼豆体验 {index:02d}",
            f"本地前端功能测试：体验商品第 {index:02d} 条，用于内容、图片和分页验证。",
            ProductType.EXPERIENCE,
            Decimal("39.00") + index,
            (
                SeedOptionSpec(
                    duration_minutes=90,
                    participants=1,
                    day_type=DayType.WEEKDAY,
                    price=Decimal("39.00") + index,
                ),
            ),
        )
        for index in range(1, 7)
    )
    + tuple(
        SeedSpec(
            f"{SEED_PREFIX} 拼豆材料包 {index:02d}",
            f"本地前端功能测试：材料包第 {index:02d} 条，用于价格、图片和分页验证。",
            ProductType.KIT,
            Decimal("29.00") + index,
        )
        for index in range(1, 7)
    )
    + (
        SeedSpec(
            MULTI_OPTION_SEED_NAME,
            "本地前端功能测试：用于验证 Experience 详情中的完整 Option 切换、价格和专属图片。",
            ProductType.EXPERIENCE,
            Decimal("59.00"),
            (
                SeedOptionSpec(
                    duration_minutes=60,
                    participants=1,
                    day_type=DayType.WEEKDAY,
                    price=Decimal("59.00"),
                ),
                SeedOptionSpec(
                    duration_minutes=120,
                    participants=2,
                    day_type=DayType.HOLIDAY,
                    price=Decimal("89.00"),
                    image_bytes=ALTERNATE_OPTION_PNG_BYTES,
                ),
            ),
        ),
    )
)


def assert_local_seed_allowed(
    *,
    app_env: str,
    db_engine: str,
    db_sqlite_path: str,
    upload_dir: str,
    apply: bool,
    confirm_local_only: bool,
    repository_root: Path = REPOSITORY_ROOT,
) -> None:
    """连接数据库前拒绝生产、MySQL、仓库外路径和非显式操作。"""

    if not apply or not confirm_local_only:
        raise RuntimeError(
            "Refusing to seed: both --apply and --confirm-local-only are required"
        )
    if app_env != "development":
        raise RuntimeError("Refusing to seed: APP_ENV must be development")
    if db_engine != "sqlite":
        raise RuntimeError("Refusing to seed: DB_ENGINE must be sqlite")

    root = repository_root.resolve()
    database_path = Path(db_sqlite_path).resolve()
    image_path = Path(upload_dir).resolve()
    if not database_path.is_relative_to(root):
        raise RuntimeError("Refusing to seed: SQLite database must be inside repository")
    if not image_path.is_relative_to(root):
        raise RuntimeError("Refusing to seed: image upload directory must be inside repository")


async def seed_products(
    service: ProductService,
    storage: LocalImageStorage,
    *,
    operator_id: int,
) -> SeedTotals:
    """创建本地前端 Online Product；重复运行跳过完整的同名数据。"""

    totals = SeedTotals()
    for spec in SEED_SPECS:
        matches = await service.list_admin_products(
            page=1,
            page_size=100,
            keyword=spec.name,
            include_deleted=True,
        )
        exact = [item for item in matches.items if item.name == spec.name]
        if exact:
            if len(exact) == 1 and (
                not exact[0].is_deleted
                and exact[0].status == ProductStatus.ONLINE
                and exact[0].product_type == spec.product_type
            ):
                totals = SeedTotals(totals.created, totals.skipped + 1)
                continue
            raise RuntimeError(
                f"Reserved seed name is occupied by incomplete/conflicting data: {spec.name}"
            )

        await _create_one(service, storage, spec=spec, operator_id=operator_id)
        totals = SeedTotals(totals.created + 1, totals.skipped)
    return totals


async def seed_in_stock_kit(
    product_service: ProductService,
    inventory_service: InventoryService,
    *,
    operator_id: int,
) -> InventorySeedResult:
    """通过正式 Inventory 用例为一个本地 Seed Kit 建立有库存场景。"""

    matches = await product_service.list_admin_products(
        page=1,
        page_size=100,
        keyword=IN_STOCK_KIT_SEED_NAME,
        include_deleted=False,
    )
    exact = [item for item in matches.items if item.name == IN_STOCK_KIT_SEED_NAME]
    if len(exact) != 1 or exact[0].product_type != ProductType.KIT:
        raise RuntimeError(
            f"In-stock seed Kit is missing or conflicting: {IN_STOCK_KIT_SEED_NAME}"
        )

    product = await product_service.get_admin_product_detail(
        exact[0].id,
        product_type=ProductType.KIT,
    )
    if product.kit.stock > 0:
        return InventorySeedResult(
            product_id=product.id,
            stock=product.kit.stock,
            adjusted=False,
            replayed=False,
        )

    result = await inventory_service.adjust_stock(
        product.id,
        change=IN_STOCK_KIT_INITIAL_CHANGE,
        reason=IN_STOCK_KIT_REASON,
        operator_id=operator_id,
        ip_address=LOCAL_IP,
        idempotency_key=IN_STOCK_KIT_IDEMPOTENCY_KEY,
    )
    refreshed = await product_service.get_admin_product_detail(
        product.id,
        product_type=ProductType.KIT,
    )
    if refreshed.kit.stock <= 0:
        raise RuntimeError(
            "In-stock seed Kit initial adjustment was already consumed; "
            "replenish it through the Inventory adjustment API"
        )
    return InventorySeedResult(
        product_id=refreshed.id,
        stock=refreshed.kit.stock,
        adjusted=not result.is_replay,
        replayed=result.is_replay,
    )


async def repair_legacy_seed_images(
    service: ProductService,
    storage: LocalImageStorage,
) -> int:
    """只修复本脚本保留 Product 引用的旧错误 PNG 或缺失文件。"""

    repaired = 0
    visited_keys: set[str] = set()
    for spec in SEED_SPECS:
        matches = await service.list_admin_products(
            page=1,
            page_size=100,
            keyword=spec.name,
            include_deleted=False,
        )
        exact = [item for item in matches.items if item.name == spec.name]
        if len(exact) != 1 or exact[0].product_type != spec.product_type:
            continue

        product = await service.get_admin_product_detail(
            exact[0].id,
            product_type=spec.product_type,
        )
        images_with_expected_bytes = [
            (image, PNG_BYTES) for image in product.images
        ]
        if spec.product_type == ProductType.EXPERIENCE:
            for option in product.experience_options:
                option_spec = next(
                    (
                        candidate
                        for candidate in spec.option_specs
                        if (
                            candidate.duration_minutes == option.duration
                            and candidate.participants == option.participants
                            and candidate.day_type == option.day_type
                        )
                    ),
                    None,
                )
                expected_bytes = (
                    option_spec.image_bytes if option_spec is not None else PNG_BYTES
                )
                images_with_expected_bytes.extend(
                    (image, expected_bytes) for image in option.images
                )

        for image, expected_bytes in images_with_expected_bytes:
            key = storage.key_from_url(image.image_url)
            if key is None or key in visited_keys:
                continue
            visited_keys.add(key)
            target = storage.root / key
            try:
                existing = target.read_bytes()
            except FileNotFoundError:
                existing = None
            is_old_default_option_fixture = (
                expected_bytes != PNG_BYTES and existing == PNG_BYTES
            )
            if (
                existing is not None
                and existing != LEGACY_INVALID_PNG_BYTES
                and not is_old_default_option_fixture
            ):
                continue
            _replace_with_valid_png(target, expected_bytes)
            repaired += 1
    return repaired


def _replace_with_valid_png(target: Path, image_bytes: bytes = PNG_BYTES) -> None:
    """原子发布修复图片，避免读取方看到半写入文件。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.repair.tmp")
    try:
        with temporary.open("xb") as file_handle:
            file_handle.write(image_bytes)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


async def _create_one(
    service: ProductService,
    storage: LocalImageStorage,
    *,
    spec: SeedSpec,
    operator_id: int,
) -> None:
    common = {"operator_id": operator_id, "ip_address": LOCAL_IP}
    if spec.product_type == ProductType.EXPERIENCE:
        if not spec.option_specs:
            raise RuntimeError(f"Experience seed requires options: {spec.name}")
        product = await service.create_experience_product(
            name=spec.name,
            description=spec.description,
            **common,
        )
        option_ids = []
        for option_spec in spec.option_specs:
            result = await service.create_experience_option(
                product.id,
                duration_minutes=option_spec.duration_minutes,
                participants=option_spec.participants,
                day_type=option_spec.day_type,
                price=option_spec.price,
                **common,
            )
            option_ids.append(result.option.id)
    else:
        product = await service.create_kit_product(
            name=spec.name,
            description=spec.description,
            price=spec.price,
            **common,
        )
        option_ids = []

    await _store_image(
        service,
        storage,
        product_id=product.id,
        operator_id=operator_id,
        is_cover=True,
    )
    for option_id, option_spec in zip(option_ids, spec.option_specs, strict=True):
        await _store_image(
            service,
            storage,
            option_id=option_id,
            operator_id=operator_id,
            image_bytes=option_spec.image_bytes,
        )
    await service.online_product(product.id, **common)


async def _store_image(
    service: ProductService,
    storage: LocalImageStorage,
    *,
    operator_id: int,
    product_id: int | None = None,
    option_id: int | None = None,
    is_cover: bool = False,
    image_bytes: bytes = PNG_BYTES,
) -> None:
    stored = storage.save(
        io.BytesIO(image_bytes),
        declared_media_type="image/png",
    )
    try:
        if product_id is not None:
            await service.create_product_image(
                product_id,
                image_url=stored.url,
                is_cover=is_cover,
                sort=0,
                operator_id=operator_id,
                ip_address=LOCAL_IP,
            )
        elif option_id is not None:
            await service.create_option_image(
                option_id,
                image_url=stored.url,
                sort=0,
                operator_id=operator_id,
                ip_address=LOCAL_IP,
            )
        else:
            raise ValueError("product_id or option_id is required")
    except Exception:
        storage.delete(stored.key)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed local Product data for frontend functional testing.",
    )
    parser.add_argument("--operator-username", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-local-only",
        action="store_true",
        help="Confirm that the configured SQLite database is disposable local data.",
    )
    return parser


async def run(*, operator_username: str) -> SeedTotals:
    """初始化命令依赖，并再次以数据库中的操作者角色进行授权。"""

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        operator = await UserRepository().get_by_username(operator_username)
        if operator is None:
            raise RuntimeError(f"Operator user not found: {operator_username}")
        if operator.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            raise RuntimeError("Operator must have ADMIN or SUPER_ADMIN role")
        if operator.status != UserStatus.NORMAL:
            raise RuntimeError("Operator must be enabled")

        product_repository = ProductRepository()
        audit_log_service = AuditLogService(AuditLogRepository())
        service = ProductService(product_repository, audit_log_service)
        inventory_service = InventoryService(
            InventoryRepository(),
            product_repository,
            audit_log_service,
        )
        storage = LocalImageStorage(
            root=settings.product_image_upload_dir,
            base_url=settings.product_image_base_url,
        )
        repaired_images = await repair_legacy_seed_images(service, storage)
        totals = await seed_products(service, storage, operator_id=operator.id)
        inventory = await seed_in_stock_kit(
            service,
            inventory_service,
            operator_id=operator.id,
        )
        return SeedTotals(
            created=totals.created,
            skipped=totals.skipped,
            repaired_images=repaired_images,
            in_stock_kit_id=inventory.product_id,
            in_stock_kit_stock=inventory.stock,
            inventory_adjusted=inventory.adjusted,
            inventory_replayed=inventory.replayed,
        )
    finally:
        await Tortoise.close_connections()


def main() -> int:
    args = build_parser().parse_args()
    setup_logging()
    try:
        assert_local_seed_allowed(
            app_env=settings.app_env,
            db_engine=settings.db_engine,
            db_sqlite_path=settings.db_sqlite_path,
            upload_dir=settings.product_image_upload_dir,
            apply=args.apply,
            confirm_local_only=args.confirm_local_only,
        )
        totals = asyncio.run(run(operator_username=args.operator_username))
    except RuntimeError as error:
        logger.error("Local Product seed refused: %s", error)
        return 2
    logger.info(
        "Local Product seed complete: created=%d skipped=%d "
        "repaired_images=%d total=%d in_stock_kit_id=%d stock=%d "
        "inventory_adjusted=%s inventory_replayed=%s",
        totals.created,
        totals.skipped,
        totals.repaired_images,
        len(SEED_SPECS),
        totals.in_stock_kit_id,
        totals.in_stock_kit_stock,
        totals.inventory_adjusted,
        totals.inventory_replayed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
