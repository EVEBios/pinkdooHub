"""API 文件上传与业务写入的补偿编排。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import BinaryIO, TypeVar

from anyio import CancelScope
from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.storage.image import ImageStorage, StoredImage

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)


async def store_image_and_call(
    upload: UploadFile,
    storage: ImageStorage,
    operation: Callable[..., Awaitable[ResultT]],
    *operation_args: object,
    **operation_kwargs: object,
) -> ResultT:
    """存储上传图片，调用业务写入，失败时补偿删除文件。"""

    stored: StoredImage | None = None
    try:
        stored = await run_in_threadpool(
            storage.save,
            _require_binary_file(upload.file),
            declared_media_type=upload.content_type,
        )
        await upload.close()
        return await operation(
            *operation_args,
            image_url=stored.url,
            **operation_kwargs,
        )
    except BaseException:
        with CancelScope(shield=True):
            await _close_upload_without_masking(upload)
            if stored is not None:
                await _delete_without_masking(storage, stored.key)
        raise


def _require_binary_file(file: object) -> BinaryIO:
    """为存储边界保留明确的二进制流类型。"""

    if not hasattr(file, "read"):
        raise TypeError("upload file must provide a binary read method")
    return file  # type: ignore[return-value]


async def _close_upload_without_masking(upload: UploadFile) -> None:
    try:
        await upload.close()
    except Exception:
        logger.exception("Failed to close Product image upload spool file")


async def _delete_without_masking(
    storage: ImageStorage,
    storage_key: str,
) -> None:
    try:
        await run_in_threadpool(storage.delete, storage_key)
    except Exception:
        logger.exception(
            "Product image compensation delete failed: storage_key=%s",
            storage_key,
        )
