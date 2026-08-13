"""ProductImage 文件清理命令。

示例：
    python -m app.tasks.product_image_cleanup --before 2026-08-01T00:00:00+08:00
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from tortoise import Tortoise

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.database import TORTOISE_ORM
from app.repositories.product_repo import ProductRepository
from app.services.product_image_cleanup_service import ProductImageCleanupService
from app.storage.image import LocalImageStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CleanupTotals:
    scanned: int = 0
    deleted: int = 0
    already_missing: int = 0
    skipped_unmanaged: int = 0
    skipped_active_reference: int = 0
    would_delete: int = 0
    failed: int = 0


async def cleanup_all(
    service: ProductImageCleanupService,
    *,
    before: datetime,
    batch_size: int,
    dry_run: bool,
) -> CleanupTotals:
    """使用 ID 游标扫描全部候选，单项失败不阻断其余文件。"""

    totals = CleanupTotals()
    after_id = 0
    while True:
        result = await service.cleanup_batch(
            before=before,
            after_id=after_id,
            batch_size=batch_size,
            dry_run=dry_run,
        )
        totals = CleanupTotals(
            scanned=totals.scanned + result.scanned,
            deleted=totals.deleted + result.deleted,
            already_missing=totals.already_missing + result.already_missing,
            skipped_unmanaged=totals.skipped_unmanaged + result.skipped_unmanaged,
            skipped_active_reference=(
                totals.skipped_active_reference
                + result.skipped_active_reference
            ),
            would_delete=totals.would_delete + result.would_delete,
            failed=totals.failed + result.failed,
        )
        if result.scanned < batch_size:
            return totals
        after_id = result.last_image_id


def parse_before(value: str) -> datetime:
    """解析带时区 ISO 8601 截止时间，拒绝依赖服务器本地时区的输入。"""

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "--before must be an ISO 8601 datetime"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--before must include a timezone")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean files for logically deleted ProductImage records.",
    )
    parser.add_argument(
        "--before",
        required=True,
        type=parse_before,
        help="Only clean images deleted at or before this ISO 8601 datetime.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        choices=range(1, 1001),
        metavar="1..1000",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete eligible files. Without this flag the command only previews.",
    )
    return parser


async def run(
    *,
    before: datetime,
    batch_size: int,
    dry_run: bool,
) -> CleanupTotals:
    """初始化命令所需基础设施并执行清理。"""

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        storage = LocalImageStorage(
            root=settings.product_image_upload_dir,
            base_url=settings.product_image_base_url,
        )
        return await cleanup_all(
            ProductImageCleanupService(ProductRepository(), storage),
            before=before,
            batch_size=batch_size,
            dry_run=dry_run,
        )
    finally:
        await Tortoise.close_connections()


def main() -> int:
    args = build_parser().parse_args()
    setup_logging()
    totals = asyncio.run(
        run(
            before=args.before,
            batch_size=args.batch_size,
            dry_run=not args.apply,
        )
    )
    logger.info(
        "Product image cleanup complete: mode=%s scanned=%d deleted=%d "
        "already_missing=%d skipped_unmanaged=%d "
        "skipped_active_reference=%d would_delete=%d failed=%d",
        "apply" if args.apply else "preview",
        totals.scanned,
        totals.deleted,
        totals.already_missing,
        totals.skipped_unmanaged,
        totals.skipped_active_reference,
        totals.would_delete,
        totals.failed,
    )
    return 1 if totals.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
