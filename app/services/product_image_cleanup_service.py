"""ProductImage 逻辑删除后的可重试文件清理用例。"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from app.repositories.product_repo import ProductRepository
from app.storage.image import LocalImageStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProductImageCleanupResult:
    """单批清理统计与后续扫描游标。"""

    scanned: int
    deleted: int
    already_missing: int
    skipped_unmanaged: int
    skipped_active_reference: int
    would_delete: int
    failed: int
    last_image_id: int


class ProductImageCleanupService:
    """扫描持久化删除标记并幂等清理本地图片对象。"""

    def __init__(
        self,
        product_repository: ProductRepository,
        storage: LocalImageStorage,
    ) -> None:
        self.product_repository = product_repository
        self.storage = storage

    async def cleanup_batch(
        self,
        *,
        before: datetime,
        after_id: int = 0,
        batch_size: int = 100,
        dry_run: bool = False,
    ) -> ProductImageCleanupResult:
        """清理一批截止时间前的文件；失败项保留供下次运行重试。"""

        if before.tzinfo is None or before.utcoffset() is None:
            raise ValueError("before must be timezone-aware")
        if after_id < 0:
            raise ValueError("after_id must be greater than or equal to 0")
        if batch_size < 1:
            raise ValueError("batch_size must be greater than or equal to 1")

        candidates = await self.product_repository.list_deleted_images_for_cleanup(
            before=before,
            after_id=after_id,
            limit=batch_size,
        )
        active_image_urls = await self.product_repository.get_active_image_urls(
            {image.image_url for image in candidates},
        )
        deleted = 0
        already_missing = 0
        skipped_unmanaged = 0
        skipped_active_reference = 0
        would_delete = 0
        failed = 0

        for image in candidates:
            storage_key = self.storage.key_from_url(image.image_url)
            if storage_key is None:
                skipped_unmanaged += 1
                continue
            if image.image_url in active_image_urls:
                skipped_active_reference += 1
                continue
            if dry_run:
                would_delete += 1
                logger.info(
                    "Product image cleanup preview: image_id=%d storage_key=%s",
                    image.id,
                    storage_key,
                )
                continue

            try:
                removed = await asyncio.to_thread(
                    self.storage.delete,
                    storage_key,
                )
            except Exception:
                failed += 1
                logger.exception(
                    "Product image cleanup failed: image_id=%d storage_key=%s",
                    image.id,
                    storage_key,
                )
            else:
                if removed:
                    deleted += 1
                else:
                    already_missing += 1

        return ProductImageCleanupResult(
            scanned=len(candidates),
            deleted=deleted,
            already_missing=already_missing,
            skipped_unmanaged=skipped_unmanaged,
            skipped_active_reference=skipped_active_reference,
            would_delete=would_delete,
            failed=failed,
            last_image_id=(candidates[-1].id if candidates else after_id),
        )
