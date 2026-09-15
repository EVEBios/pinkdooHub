"""本地 Product seed 的真实 PNG 与旧夹具修复回归测试。"""

import struct
import zlib

import pytest

from app.models.product import Product
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService
from app.storage.image import LocalImageStorage
from app.tasks.product_functional_seed import (
    ALTERNATE_OPTION_PNG_BYTES,
    LEGACY_INVALID_PNG_BYTES,
    PNG_BYTES,
    repair_legacy_seed_images,
    seed_products,
)


def test_seed_png_has_valid_chunks_crc_and_pixel_stream() -> None:
    assert PNG_BYTES.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(PNG_BYTES):
        length = struct.unpack(">I", PNG_BYTES[offset:offset + 4])[0]
        chunk_type = PNG_BYTES[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        data = PNG_BYTES[data_start:data_end]
        expected_crc = struct.unpack(
            ">I",
            PNG_BYTES[data_end:data_end + 4],
        )[0]
        assert zlib.crc32(chunk_type + data) & 0xFFFFFFFF == expected_crc
        chunks.append((chunk_type, data))
        offset = data_end + 4

    assert offset == len(PNG_BYTES)
    assert [chunk_type for chunk_type, _ in chunks] == [
        b"IHDR",
        b"IDAT",
        b"IEND",
    ]
    assert struct.unpack(">IIBBBBB", chunks[0][1]) == (
        2,
        2,
        8,
        2,
        0,
        0,
        0,
    )
    pixels = zlib.decompress(chunks[1][1])
    assert len(pixels) == 14
    assert pixels[0] == 0
    assert pixels[7] == 0


def make_service() -> ProductService:
    return ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )


@pytest.mark.asyncio
async def test_repairs_only_legacy_referenced_images(tmp_path) -> None:
    service = make_service()
    storage = LocalImageStorage(
        root=tmp_path / "uploads",
        base_url="/uploads/products",
    )
    await seed_products(service, storage, operator_id=51)

    assert await Product.filter(name__startswith="[LOCAL-FE]").count() == 13
    files = sorted((tmp_path / "uploads").glob("*.png"))
    assert len(files) == 21
    target = next(file for file in files if file.read_bytes() == PNG_BYTES)
    target.write_bytes(LEGACY_INVALID_PNG_BYTES)
    unrelated = tmp_path / "uploads" / ("f" * 32 + ".png")
    unrelated.write_bytes(LEGACY_INVALID_PNG_BYTES)

    repaired = await repair_legacy_seed_images(service, storage)

    assert repaired == 1
    assert target.read_bytes() == PNG_BYTES
    assert unrelated.read_bytes() == LEGACY_INVALID_PNG_BYTES


@pytest.mark.asyncio
async def test_repair_restores_missing_referenced_seed_image(tmp_path) -> None:
    service = make_service()
    storage = LocalImageStorage(
        root=tmp_path / "uploads",
        base_url="/uploads/products",
    )
    await seed_products(service, storage, operator_id=51)
    target = next(
        file
        for file in (tmp_path / "uploads").glob("*.png")
        if file.read_bytes() == PNG_BYTES
    )
    target.unlink()

    repaired = await repair_legacy_seed_images(service, storage)

    assert repaired == 1
    assert target.read_bytes() == PNG_BYTES


@pytest.mark.asyncio
async def test_repair_migrates_multi_option_image_from_old_default_fixture(
    tmp_path,
) -> None:
    service = make_service()
    storage = LocalImageStorage(
        root=tmp_path / "uploads",
        base_url="/uploads/products",
    )
    await seed_products(service, storage, operator_id=51)
    target = next(
        file
        for file in (tmp_path / "uploads").glob("*.png")
        if file.read_bytes() == ALTERNATE_OPTION_PNG_BYTES
    )
    target.write_bytes(PNG_BYTES)

    repaired = await repair_legacy_seed_images(service, storage)

    assert repaired == 1
    assert target.read_bytes() == ALTERNATE_OPTION_PNG_BYTES
