"""Product 图片文件校验与本地存储适配器测试。"""

from hashlib import md5
from io import BytesIO
from pathlib import Path

import pytest

from app.common.constants.product import PRODUCT_IMAGE_MAX_BYTES
from app.common.exceptions import InvalidImageFile
from app.storage.image import LocalImageStorage

PNG_CONTENT = (
    b"\x89PNG\r\n\x1a\n"
    + b"valid-test-payload"
    + b"\x00\x00\x00\x00IEND\xaeB`\x82"
)
JPEG_CONTENT = b"\xff\xd8\xff" + b"valid-test-payload" + b"\xff\xd9"
WEBP_PAYLOAD = b"WEBPVP8 " + b"payload"
WEBP_CONTENT = b"RIFF" + len(WEBP_PAYLOAD).to_bytes(4, "little") + WEBP_PAYLOAD
FIXED_KEY = "a" * 32
JPEG_HASH_TRAILER_PREFIX = b"\x17\x4d\xa1\x01\x00\x00\x00\x00"


def _with_jpeg_hash_trailer(content: bytes) -> bytes:
    return (
        content
        + JPEG_HASH_TRAILER_PREFIX
        + md5(content, usedforsecurity=False).digest()
    )


def _storage(root: Path) -> LocalImageStorage:
    return LocalImageStorage(
        root=root,
        base_url="/uploads/products/",
        key_factory=lambda: FIXED_KEY,
    )


@pytest.mark.parametrize(
    ("content", "media_type", "extension"),
    [
        (JPEG_CONTENT, "image/jpeg", "jpg"),
        (PNG_CONTENT, "image/png", "png"),
        (WEBP_CONTENT, "image/webp", "webp"),
    ],
)
def test_save_valid_image_uses_server_generated_name_and_returns_metadata(
    tmp_path: Path,
    content: bytes,
    media_type: str,
    extension: str,
) -> None:
    storage = _storage(tmp_path / "nested" / "products")

    result = storage.save(BytesIO(content), declared_media_type=media_type)

    assert result.key == f"{FIXED_KEY}.{extension}"
    assert result.url == f"/uploads/products/{FIXED_KEY}.{extension}"
    assert result.media_type == media_type
    assert result.size == len(content)
    assert (storage.root / result.key).read_bytes() == content
    assert not list(storage.root.glob("*.tmp"))


def test_save_verified_jpeg_hash_trailer_stores_canonical_jpeg(tmp_path: Path) -> None:
    storage = _storage(tmp_path / "products")

    result = storage.save(
        BytesIO(_with_jpeg_hash_trailer(JPEG_CONTENT)),
        declared_media_type="image/jpeg",
    )

    assert result.key == f"{FIXED_KEY}.jpg"
    assert result.size == len(JPEG_CONTENT)
    assert (storage.root / result.key).read_bytes() == JPEG_CONTENT


@pytest.mark.parametrize(
    ("content", "media_type", "reason"),
    [
        (PNG_CONTENT, None, "unsupported_media_type"),
        (PNG_CONTENT, "application/octet-stream", "unsupported_media_type"),
        (b"not-an-image", "image/png", "invalid_image_content"),
        (b"\x89PNG\r\n\x1a\ntruncated", "image/png", "invalid_image_content"),
        (PNG_CONTENT, "image/jpeg", "content_type_mismatch"),
        (JPEG_CONTENT + b"arbitrary-trailer", "image/jpeg", "invalid_image_content"),
        (
            JPEG_CONTENT + JPEG_HASH_TRAILER_PREFIX + b"\x00" * 16,
            "image/jpeg",
            "invalid_image_content",
        ),
        (
            _with_jpeg_hash_trailer(JPEG_CONTENT),
            "image/png",
            "content_type_mismatch",
        ),
        (b"", "image/png", "empty_file"),
    ],
)
def test_invalid_file_is_rejected_without_writing(
    tmp_path: Path,
    content: bytes,
    media_type: str | None,
    reason: str,
) -> None:
    storage = _storage(tmp_path / "products")

    with pytest.raises(InvalidImageFile) as exc_info:
        storage.save(BytesIO(content), declared_media_type=media_type)

    assert exc_info.value.code == 42221
    assert exc_info.value.message == "Invalid image file"
    assert exc_info.value.data == {"reason": reason}
    assert not storage.root.exists()


def test_oversized_file_is_rejected_after_bounded_read(tmp_path: Path) -> None:
    storage = _storage(tmp_path / "products")
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * PRODUCT_IMAGE_MAX_BYTES

    with pytest.raises(InvalidImageFile) as exc_info:
        storage.save(BytesIO(oversized), declared_media_type="image/png")

    assert exc_info.value.data == {"reason": "file_too_large"}
    assert not storage.root.exists()


def test_delete_is_idempotent_and_rejects_path_traversal(tmp_path: Path) -> None:
    storage = _storage(tmp_path / "products")
    stored = storage.save(BytesIO(PNG_CONTENT), declared_media_type="image/png")

    assert storage.delete(stored.key) is True
    assert storage.delete(stored.key) is False

    assert not (storage.root / stored.key).exists()
    with pytest.raises(ValueError, match="invalid image storage key"):
        storage.delete("../outside.png")


@pytest.mark.parametrize(
    ("image_url", "expected"),
    [
        (f"/uploads/products/{FIXED_KEY}.png", f"{FIXED_KEY}.png"),
        (f"https://cdn.example.com/{FIXED_KEY}.png", None),
        ("/uploads/products/../outside.png", None),
        ("/uploads/products/not-a-managed-name.png", None),
        (f"/uploads/products/{FIXED_KEY}.png/extra", None),
    ],
)
def test_key_from_url_accepts_only_current_managed_namespace(
    tmp_path: Path,
    image_url: str,
    expected: str | None,
) -> None:
    assert _storage(tmp_path).key_from_url(image_url) == expected


def test_existing_target_is_not_silently_overwritten(tmp_path: Path) -> None:
    storage = _storage(tmp_path / "products")
    first = storage.save(BytesIO(PNG_CONTENT), declared_media_type="image/png")

    with pytest.raises(FileExistsError):
        storage.save(BytesIO(PNG_CONTENT), declared_media_type="image/png")

    assert (storage.root / first.key).read_bytes() == PNG_CONTENT
    assert not list(storage.root.glob("*.tmp"))


def test_key_factory_cannot_inject_a_path(tmp_path: Path) -> None:
    storage = LocalImageStorage(
        root=tmp_path / "products",
        base_url="/uploads/products",
        key_factory=lambda: "../outside",
    )

    with pytest.raises(RuntimeError, match="key_factory"):
        storage.save(BytesIO(PNG_CONTENT), declared_media_type="image/png")

    assert not storage.root.exists()
