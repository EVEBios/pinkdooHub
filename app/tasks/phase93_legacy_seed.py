"""为 Phase 9.3 DR-02/DR-03 生成受控的旧迁移合成数据。"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import logging
import os
import sys
from typing import Mapping

from aerich.models import Aerich
from tortoise import Tortoise
from tortoise.transactions import in_transaction

from app.common.constants.order import (
    ORDER_AUDIT_ACTION_CREATE,
    ORDER_AUDIT_TARGET_TYPE,
    ORDER_NO_PREFIX,
    ORDER_NO_ULID_LENGTH,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.core.logging import setup_logging
from app.core.security import hash_password
from app.db.database import TORTOISE_ORM
from app.models.audit_log import AuditLog
from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.order_repo import OrderItemCreateData, OrderRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService


logger = logging.getLogger(__name__)

PHASE93_LEGACY_SEED_ENABLE_ENV = "PHASE93_LEGACY_SEED_ENABLED"
ALLOWED_DATABASES = {
    0: {"pinkdoohub_phase93_m0"},
    1: {
        "pinkdoohub_phase93_m1",
        "pinkdoohub_phase93_failure",
    },
}
EXPECTED_MIGRATIONS = {
    0: ["0_20260810101218_init.py"],
    1: [
        "0_20260810101218_init.py",
        "1_20260813130455_add_order_tables.py",
    ],
}
PHASE93_LEGACY_ORDER_NO = (
    f"{ORDER_NO_PREFIX}{'0' * (ORDER_NO_ULID_LENGTH - 1)}1"
)


class LegacySeedError(RuntimeError):
    """不包含 Secret 或连接串的旧版本 fixture 错误。"""


def validate_target(environment: Mapping[str, str], migration_version: int) -> None:
    """拒绝生产、默认端口、未知 Schema 与未显式启用的调用。"""

    allowed_databases = ALLOWED_DATABASES.get(migration_version)
    if allowed_databases is None:
        raise LegacySeedError("only migration 0 and migration 1 are supported")
    if environment.get(PHASE93_LEGACY_SEED_ENABLE_ENV) != "1":
        raise LegacySeedError("legacy synthetic seed must be explicitly enabled")
    if environment.get("APP_ENV") != "testing":
        raise LegacySeedError("legacy synthetic seed requires APP_ENV=testing")
    if environment.get("DB_ENGINE") != "mysql":
        raise LegacySeedError("legacy synthetic seed requires MySQL")
    if environment.get("DB_HOST") not in {"127.0.0.1", "mysql-source"}:
        raise LegacySeedError("legacy synthetic seed requires the isolated host")
    try:
        port = int(environment.get("DB_PORT", ""))
    except ValueError as error:
        raise LegacySeedError("legacy synthetic seed port is invalid") from error
    allowed_port = 14306 if environment.get("DB_HOST") == "127.0.0.1" else 3306
    if port != allowed_port:
        raise LegacySeedError("legacy synthetic seed port is not frozen")
    if environment.get("DB_NAME") not in allowed_databases:
        raise LegacySeedError("legacy synthetic seed database is not frozen")
    if environment.get("DB_USER") != "root":
        raise LegacySeedError("legacy synthetic seed requires disposable root")


async def _assert_empty(migration_version: int) -> None:
    base_counts = (
        await User.all().count(),
        await Product.all().count(),
        await AuditLog.all().count(),
    )
    if any(base_counts):
        raise LegacySeedError("legacy synthetic seed requires empty business tables")
    if migration_version == 1 and await Order.all().count():
        raise LegacySeedError("legacy synthetic seed requires an empty Order table")


async def _assert_migration_version(migration_version: int) -> None:
    actual = await Aerich.all().order_by("id").values_list("version", flat=True)
    if list(actual) != EXPECTED_MIGRATIONS[migration_version]:
        raise LegacySeedError(
            "Aerich state does not match the requested legacy version"
        )


async def seed(migration_version: int) -> dict[str, int]:
    """在单事务内通过 Repository 创建可比较的旧版本聚合。"""

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        await _assert_migration_version(migration_version)
        await _assert_empty(migration_version)
        user_repository = UserRepository()
        product_repository = ProductRepository()
        order_repository = OrderRepository()
        audit_service = AuditLogService(AuditLogRepository())

        async with in_transaction() as connection:
            operator = await user_repository.create(
                username=f"phase93_m{migration_version}_admin",
                password=hash_password("Phase93SyntheticOnly!1"),
                nickname=f"Phase93 M{migration_version}",
                phone=f"1380000931{migration_version}",
                role=UserRole.ADMIN.value,
                status=UserStatus.NORMAL.value,
                using_db=connection,
            )
            experience = await product_repository.create_product(
                name=f"[PHASE93] M{migration_version} Experience",
                product_type=ProductType.EXPERIENCE,
                description="Synthetic legacy migration fixture",
                using_db=connection,
            )
            await product_repository.update_product(
                experience,
                status=ProductStatus.ONLINE,
                using_db=connection,
            )
            option = await product_repository.create_option(
                product=experience,
                duration=60,
                participants=2,
                day_type=DayType.WEEKDAY,
                price=Decimal("88.00"),
                using_db=connection,
            )
            kit_product = await product_repository.create_product(
                name=f"[PHASE93] M{migration_version} Kit",
                product_type=ProductType.KIT,
                description="Synthetic opening balance fixture",
                using_db=connection,
            )
            await product_repository.update_product(
                kit_product,
                status=ProductStatus.ONLINE,
                using_db=connection,
            )
            await product_repository.create_kit(
                product=kit_product,
                price=Decimal("36.00"),
                stock=7,
                using_db=connection,
            )
            for product in (experience, kit_product):
                await audit_service.log(
                    operator_id=operator.id,
                    action="CREATE_PRODUCT",
                    target_type="product",
                    target_id=product.id,
                    ip_address="127.0.0.1",
                    description="Phase 9.3 synthetic legacy fixture",
                    using_db=connection,
                )

            order_count = 0
            if migration_version == 1:
                order = await order_repository.create_order(
                    order_no=PHASE93_LEGACY_ORDER_NO,
                    user_id=operator.id,
                    total_amount=Decimal("160.00"),
                    remark="Phase 9.3 migration 1 snapshot fixture",
                    using_db=connection,
                )
                await order_repository.bulk_create_items(
                    order=order,
                    items=[
                        OrderItemCreateData(
                            product_id=experience.id,
                            experience_option_id=option.id,
                            option_duration_minutes=60,
                            option_participants=2,
                            option_day_type=DayType.WEEKDAY,
                            product_name=experience.name,
                            product_price=Decimal("88.00"),
                            quantity=1,
                            subtotal=Decimal("88.00"),
                        ),
                        OrderItemCreateData(
                            product_id=kit_product.id,
                            experience_option_id=None,
                            option_duration_minutes=None,
                            option_participants=None,
                            option_day_type=None,
                            product_name=kit_product.name,
                            product_price=Decimal("36.00"),
                            quantity=2,
                            subtotal=Decimal("72.00"),
                        ),
                    ],
                    using_db=connection,
                )
                await audit_service.log(
                    operator_id=operator.id,
                    action=ORDER_AUDIT_ACTION_CREATE,
                    target_type=ORDER_AUDIT_TARGET_TYPE,
                    target_id=order.id,
                    ip_address="127.0.0.1",
                    description="Phase 9.3 synthetic legacy fixture",
                    using_db=connection,
                )
                order_count = 1

        return {
            "users": 1,
            "products": 2,
            "experience_options": 1,
            "product_kits": 1,
            "orders": order_count,
            "audit_logs": 2 + order_count,
            "kit_stock": 7,
        }
    finally:
        await Tortoise.close_connections()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration-version", required=True, type=int, choices=(0, 1))
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    setup_logging()
    try:
        validate_target(os.environ, arguments.migration_version)
        result = asyncio.run(seed(arguments.migration_version))
    except LegacySeedError as error:
        logger.error("Phase 9.3 legacy seed refused: %s", error)
        return 2
    except Exception as error:
        logger.error(
            "Phase 9.3 legacy seed failed: error_type=%s",
            type(error).__name__,
        )
        return 1
    logger.info(
        "Phase 9.3 legacy seed succeeded: migration=%d counts=%s",
        arguments.migration_version,
        result,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
