"""ProductImage 延迟文件清理用例测试。"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.common.enums.product import ProductType
from app.models.product import Product
from app.models.product_image import ProductImage
from app.repositories.product_repo import ProductRepository
from app.services.product_image_cleanup_service import ProductImageCleanupService
from app.storage.image import LocalImageStorage

PNG_CONTENT = (
    b"\x89PNG\r\n\x1a\ncleanup"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


def _storage(tmp_path: Path, key: str = "a" * 32) -> LocalImageStorage:
    return LocalImageStorage(
        root=tmp_path / "products",
        base_url="/uploads/products",
        key_factory=lambda: key,
    )


async def _product() -> Product:
    return await Product.create(
        name="清理测试商品",
        product_type=ProductType.EXPERIENCE,
    )


async def _image(
    product: Product,
    *,
    image_url: str,
    is_deleted: bool,
    updated_at: datetime,
) -> ProductImage:
    image = await ProductImage.create(
        product=product,
        image_url=image_url,
        is_deleted=is_deleted,
    )
    await ProductImage.filter(id=image.id).update(updated_at=updated_at)
    image.updated_at = updated_at
    return image


async def test_cleanup_deletes_only_mature_unreferenced_managed_file(
    tmp_path: Path,
) -> None:
    product = await _product()
    storage = _storage(tmp_path)
    stored = storage.save(BytesIO(PNG_CONTENT), declared_media_type="image/png")
    deleted_image = await _image(
        product,
        image_url=stored.url,
        is_deleted=True,
        updated_at=NOW - timedelta(days=2),
    )
    await _image(
        product,
        image_url="https://cdn.example.com/external.png",
        is_deleted=True,
        updated_at=NOW - timedelta(days=2),
    )
    await _image(
        product,
        image_url=f"/uploads/products/{'b' * 32}.png",
        is_deleted=True,
        updated_at=NOW + timedelta(minutes=1),
    )

    result = await ProductImageCleanupService(
        ProductRepository(),
        storage,
    ).cleanup_batch(before=NOW)

    assert result.scanned == 2
    assert result.deleted == 1
    assert result.skipped_unmanaged == 1
    assert result.already_missing == 0
    assert result.failed == 0
    assert result.last_image_id > deleted_image.id
    assert not (storage.root / stored.key).exists()
    assert await ProductImage.filter(id=deleted_image.id, is_deleted=True).exists()


async def test_cleanup_preserves_url_still_referenced_by_active_image(
    tmp_path: Path,
) -> None:
    product = await _product()
    storage = _storage(tmp_path)
    stored = storage.save(BytesIO(PNG_CONTENT), declared_media_type="image/png")
    await _image(
        product,
        image_url=stored.url,
        is_deleted=True,
        updated_at=NOW - timedelta(days=1),
    )
    await _image(
        product,
        image_url=stored.url,
        is_deleted=False,
        updated_at=NOW - timedelta(days=1),
    )

    result = await ProductImageCleanupService(
        ProductRepository(),
        storage,
    ).cleanup_batch(before=NOW)

    assert result.skipped_active_reference == 1
    assert result.deleted == 0
    assert (storage.root / stored.key).exists()


async def test_cleanup_checks_active_references_once_per_batch(
    tmp_path: Path,
) -> None:
    repository = ProductRepository()
    storage = _storage(tmp_path)
    product = await _product()
    first_url = f"/uploads/products/{'1' * 32}.png"
    second_url = f"/uploads/products/{'2' * 32}.png"
    await _image(
        product,
        image_url=first_url,
        is_deleted=True,
        updated_at=NOW - timedelta(days=1),
    )
    await _image(
        product,
        image_url=second_url,
        is_deleted=True,
        updated_at=NOW - timedelta(days=1),
    )
    original_method = repository.get_active_image_urls
    calls: list[set[str]] = []

    async def capture_urls(image_urls: set[str]) -> set[str]:
        calls.append(image_urls)
        return await original_method(image_urls)

    repository.get_active_image_urls = capture_urls  # type: ignore[method-assign]

    await ProductImageCleanupService(repository, storage).cleanup_batch(
        before=NOW,
    )

    assert calls == [{first_url, second_url}]


async def test_cleanup_counts_missing_file_as_successful_idempotent_state(
    tmp_path: Path,
) -> None:
    product = await _product()
    storage = _storage(tmp_path)
    missing_url = f"/uploads/products/{'c' * 32}.jpg"
    await _image(
        product,
        image_url=missing_url,
        is_deleted=True,
        updated_at=NOW - timedelta(days=1),
    )

    result = await ProductImageCleanupService(
        ProductRepository(),
        storage,
    ).cleanup_batch(before=NOW)

    assert result.already_missing == 1
    assert result.deleted == 0
    assert result.failed == 0


async def test_cleanup_dry_run_reports_candidate_without_deleting_file(
    tmp_path: Path,
) -> None:
    product = await _product()
    storage = _storage(tmp_path)
    stored = storage.save(BytesIO(PNG_CONTENT), declared_media_type="image/png")
    await _image(
        product,
        image_url=stored.url,
        is_deleted=True,
        updated_at=NOW - timedelta(days=1),
    )

    result = await ProductImageCleanupService(
        ProductRepository(),
        storage,
    ).cleanup_batch(before=NOW, dry_run=True)

    assert result.would_delete == 1
    assert result.deleted == 0
    assert (storage.root / stored.key).exists()


async def test_cleanup_failure_is_counted_without_stopping_later_candidates(
    tmp_path: Path,
) -> None:
    product = await _product()
    storage = _storage(tmp_path)
    first_url = f"/uploads/products/{'d' * 32}.png"
    second_url = f"/uploads/products/{'e' * 32}.png"
    await _image(
        product,
        image_url=first_url,
        is_deleted=True,
        updated_at=NOW - timedelta(days=1),
    )
    await _image(
        product,
        image_url=second_url,
        is_deleted=True,
        updated_at=NOW - timedelta(days=1),
    )
    original_delete = storage.delete
    delete = Mock(side_effect=[OSError("simulated failure"), False])
    storage.delete = delete  # type: ignore[method-assign]

    result = await ProductImageCleanupService(
        ProductRepository(),
        storage,
    ).cleanup_batch(before=NOW)

    assert result.failed == 1
    assert result.already_missing == 1
    assert delete.call_count == 2
    storage.delete = original_delete  # type: ignore[method-assign]


@pytest.mark.parametrize(
    ("before", "after_id", "batch_size", "message"),
    [
        (datetime(2026, 8, 13), 0, 100, "timezone-aware"),
        (NOW, -1, 100, "after_id"),
        (NOW, 0, 0, "batch_size"),
    ],
)
async def test_cleanup_rejects_unsafe_scan_parameters(
    tmp_path: Path,
    before: datetime,
    after_id: int,
    batch_size: int,
    message: str,
) -> None:
    service = ProductImageCleanupService(
        ProductRepository(),
        _storage(tmp_path),
    )

    with pytest.raises(ValueError, match=message):
        await service.cleanup_batch(
            before=before,
            after_id=after_id,
            batch_size=batch_size,
        )
