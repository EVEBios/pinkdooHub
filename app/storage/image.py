"""Product 图片文件校验与本地存储适配器。"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import md5
from hmac import compare_digest
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4

from app.common.constants.product import (
    PRODUCT_IMAGE_MAX_BYTES,
    PRODUCT_IMAGE_MEDIA_TYPE_EXTENSIONS,
    PRODUCT_IMAGE_READ_CHUNK_BYTES,
)
from app.common.exceptions import InvalidImageFile

_STORAGE_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|webp)$")
_JPEG_HASH_TRAILER_PREFIX = b"\x17\x4d\xa1\x01\x00\x00\x00\x00"
_JPEG_HASH_TRAILER_DIGEST_BYTES = 16
_JPEG_HASH_TRAILER_BYTES = (
    len(_JPEG_HASH_TRAILER_PREFIX) + _JPEG_HASH_TRAILER_DIGEST_BYTES
)


@dataclass(frozen=True, slots=True)
class StoredImage:
    """已存储图片的公开引用与补偿删除标识。"""

    key: str
    url: str
    media_type: str
    size: int


class ImageStorage(Protocol):
    """上传链路依赖的最小存储端口；实现不得信任客户端文件名。"""

    def save(
        self,
        source: BinaryIO,
        *,
        declared_media_type: str | None,
    ) -> StoredImage:
        """校验并写入图片，返回不可变公开引用。"""

    def key_from_url(self, image_url: str) -> str | None:
        """仅将当前适配器管理的 URL 解析为内部对象键。"""

    def delete(self, storage_key: str) -> bool:
        """幂等删除对象并报告是否实际存在。"""


class LocalImageStorage(ImageStorage):
    """使用服务端 UUID 文件名的本地 Product 图片存储。"""

    def __init__(
        self,
        *,
        root: str | Path,
        base_url: str,
        key_factory: Callable[[], str] | None = None,
    ) -> None:
        normalized_base_url = base_url.rstrip("/")
        if not normalized_base_url:
            raise ValueError("base_url must be a non-empty URL or URL path")

        self._root = Path(root).resolve()
        self._base_url = normalized_base_url
        self._key_factory = key_factory or (lambda: uuid4().hex)

    @property
    def root(self) -> Path:
        """返回已解析的存储根目录。"""

        return self._root

    def save(self, source: BinaryIO, *, declared_media_type: str | None) -> StoredImage:
        """限量读取、校验图片内容，并原子写入最终文件。"""

        expected_extension = PRODUCT_IMAGE_MEDIA_TYPE_EXTENSIONS.get(
            declared_media_type or ""
        )
        if expected_extension is None:
            raise InvalidImageFile(reason="unsupported_media_type")

        content = _normalize_image_content(self._read_bounded(source))
        detected_extension = _detect_image_extension(content)
        if detected_extension is None:
            raise InvalidImageFile(reason="invalid_image_content")
        if detected_extension != expected_extension:
            raise InvalidImageFile(reason="content_type_mismatch")

        storage_key = self._build_storage_key(detected_extension)
        target = self._resolve_storage_key(storage_key)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        self._root.mkdir(parents=True, exist_ok=True)
        published = False

        try:
            with temporary.open("xb") as file_handle:
                file_handle.write(content)
                file_handle.flush()
                os.fsync(file_handle.fileno())
            os.link(temporary, target)
            published = True
            temporary.unlink()
        except Exception:
            if published:
                target.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
            raise

        return StoredImage(
            key=storage_key,
            url=f"{self._base_url}/{storage_key}",
            media_type=declared_media_type,
            size=len(content),
        )

    def key_from_url(self, image_url: str) -> str | None:
        """仅解析当前适配器生成的 URL；外部或异常 URL 返回 None。"""

        prefix = f"{self._base_url}/"
        if not image_url.startswith(prefix):
            return None
        storage_key = image_url[len(prefix):]
        if _STORAGE_KEY_PATTERN.fullmatch(storage_key) is None:
            return None
        return storage_key

    def delete(self, storage_key: str) -> bool:
        """幂等删除由本适配器生成的文件，并报告文件是否实际存在。"""

        target = self._resolve_storage_key(storage_key)
        try:
            target.unlink()
        except FileNotFoundError:
            return False
        return True

    def _read_bounded(self, source: BinaryIO) -> bytes:
        content = bytearray()
        while True:
            remaining = PRODUCT_IMAGE_MAX_BYTES + 1 - len(content)
            if remaining <= 0:
                raise InvalidImageFile(reason="file_too_large")

            chunk = source.read(min(PRODUCT_IMAGE_READ_CHUNK_BYTES, remaining))
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise TypeError("image source must be opened in binary mode")
            content.extend(chunk)

        if not content:
            raise InvalidImageFile(reason="empty_file")
        if len(content) > PRODUCT_IMAGE_MAX_BYTES:
            raise InvalidImageFile(reason="file_too_large")
        return bytes(content)

    def _build_storage_key(self, extension: str) -> str:
        generated_name = self._key_factory()
        if not re.fullmatch(r"[0-9a-f]{32}", generated_name):
            raise RuntimeError("key_factory must return 32 lowercase hexadecimal characters")
        return f"{generated_name}.{extension}"

    def _resolve_storage_key(self, storage_key: str) -> Path:
        if _STORAGE_KEY_PATTERN.fullmatch(storage_key) is None:
            raise ValueError("invalid image storage key")

        target = (self._root / storage_key).resolve()
        if target.parent != self._root:
            raise ValueError("image storage key escapes the storage root")
        return target


def _detect_image_extension(content: bytes) -> str | None:
    """使用文件签名识别允许的图片格式，不信任客户端文件名。"""

    if content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
        return "jpg"
    if (
        content.startswith(b"\x89PNG\r\n\x1a\n")
        and content.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    ):
        return "png"
    if (
        len(content) >= 16
        and content.startswith(b"RIFF")
        and int.from_bytes(content[4:8], "little") == len(content) - 8
        and content[8:12] == b"WEBP"
        and content[12:16] in {b"VP8 ", b"VP8L", b"VP8X"}
    ):
        return "webp"
    return None


def _normalize_image_content(content: bytes) -> bytes:
    """移除校验通过的 JPEG 哈希尾部，拒绝任意或伪造尾随数据。"""

    if len(content) <= _JPEG_HASH_TRAILER_BYTES:
        return content

    jpeg_content = content[:-_JPEG_HASH_TRAILER_BYTES]
    trailer = content[-_JPEG_HASH_TRAILER_BYTES:]
    if (
        not jpeg_content.startswith(b"\xff\xd8\xff")
        or not jpeg_content.endswith(b"\xff\xd9")
        or not trailer.startswith(_JPEG_HASH_TRAILER_PREFIX)
    ):
        return content

    declared_digest = trailer[len(_JPEG_HASH_TRAILER_PREFIX):]
    # 该 MD5 只用于识别导出器附加的完整性尾部，不是认证或安全摘要。
    actual_digest = md5(jpeg_content, usedforsecurity=False).digest()
    return jpeg_content if compare_digest(declared_digest, actual_digest) else content
