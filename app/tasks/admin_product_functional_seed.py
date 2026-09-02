"""仅供本地开发环境使用的 ADMIN Product 只读页面测试数据命令。"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

from tortoise import Tortoise

from app.common.enums.product import ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.database import TORTOISE_ORM
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService
from app.tasks.product_functional_seed import LOCAL_IP, assert_local_seed_allowed

logger = logging.getLogger(__name__)
SEED_PREFIX = "[LOCAL-ADMIN-FE]"
DRAFT_EXPERIENCE_NAME = f"{SEED_PREFIX} Draft 空配置体验"
DRAFT_KIT_NAME = f"{SEED_PREFIX} Draft 无封面材料包"
DELETED_KIT_NAME = f"{SEED_PREFIX} 已逻辑删除材料包"


@dataclass(frozen=True, slots=True)
class AdminSeedResult:
    created: int
    skipped: int
    draft_experience_id: int
    draft_kit_id: int
    deleted_kit_id: int


async def seed_admin_product_samples(
    service: ProductService,
    *,
    operator_id: int,
) -> AdminSeedResult:
    """通过正式 Product Service 幂等创建两个 Draft 和一个删除样本。"""

    created = 0
    skipped = 0

    draft_experience_id, was_created = await _ensure_sample(
        service,
        name=DRAFT_EXPERIENCE_NAME,
        product_type=ProductType.EXPERIENCE,
        deleted=False,
        operator_id=operator_id,
    )
    created += int(was_created)
    skipped += int(not was_created)

    draft_kit_id, was_created = await _ensure_sample(
        service,
        name=DRAFT_KIT_NAME,
        product_type=ProductType.KIT,
        deleted=False,
        operator_id=operator_id,
    )
    created += int(was_created)
    skipped += int(not was_created)

    deleted_kit_id, was_created = await _ensure_sample(
        service,
        name=DELETED_KIT_NAME,
        product_type=ProductType.KIT,
        deleted=True,
        operator_id=operator_id,
    )
    created += int(was_created)
    skipped += int(not was_created)

    return AdminSeedResult(
        created=created,
        skipped=skipped,
        draft_experience_id=draft_experience_id,
        draft_kit_id=draft_kit_id,
        deleted_kit_id=deleted_kit_id,
    )


async def _ensure_sample(
    service: ProductService,
    *,
    name: str,
    product_type: ProductType,
    deleted: bool,
    operator_id: int,
) -> tuple[int, bool]:
    matches = await service.list_admin_products(
        page=1,
        page_size=100,
        keyword=name,
        include_deleted=True,
    )
    exact = [item for item in matches.items if item.name == name]
    if exact:
        if len(exact) != 1:
            raise RuntimeError(f"Reserved admin seed name is not unique: {name}")
        product = exact[0]
        if (
            product.product_type != product_type
            or product.status != ProductStatus.DRAFT
            or product.is_deleted != deleted
        ):
            raise RuntimeError(
                f"Reserved admin seed name is occupied by conflicting data: {name}"
            )
        return product.id, False

    common = {"operator_id": operator_id, "ip_address": LOCAL_IP}
    if product_type == ProductType.EXPERIENCE:
        product = await service.create_experience_product(
            name=name,
            description=None,
            **common,
        )
    else:
        product = await service.create_kit_product(
            name=name,
            description=(
                "本地 ADMIN Product Functional：逻辑删除标记样本。"
                if deleted
                else "本地 ADMIN Product Functional：Draft Kit 无封面样本。"
            ),
            price=Decimal("19.90") if deleted else Decimal("49.90"),
            **common,
        )
    if deleted:
        await service.delete_product(product.id, **common)
    return product.id, True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed local ADMIN Product read-only functional samples.",
    )
    parser.add_argument("--operator-username", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-local-only", action="store_true")
    return parser


async def run(*, operator_username: str) -> AdminSeedResult:
    """初始化依赖并以数据库中的 ADMIN+ 操作者执行正式业务用例。"""

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        operator = await UserRepository().get_by_username(operator_username)
        if operator is None:
            raise RuntimeError(f"Operator user not found: {operator_username}")
        if operator.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            raise RuntimeError("Operator must have ADMIN or SUPER_ADMIN role")
        if operator.status != UserStatus.NORMAL:
            raise RuntimeError("Operator must be enabled")

        service = ProductService(
            ProductRepository(),
            AuditLogService(AuditLogRepository()),
        )
        return await seed_admin_product_samples(service, operator_id=operator.id)
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
        result = asyncio.run(run(operator_username=args.operator_username))
    except RuntimeError as error:
        logger.error("Local ADMIN Product seed refused: %s", error)
        return 2
    logger.info(
        "Local ADMIN Product seed complete: created=%d skipped=%d "
        "draft_experience_id=%d draft_kit_id=%d deleted_kit_id=%d",
        result.created,
        result.skipped,
        result.draft_experience_id,
        result.draft_kit_id,
        result.deleted_kit_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
