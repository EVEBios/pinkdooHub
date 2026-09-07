"""向 Gate A M6 MySQL 和持久图片卷发布冻结的 MARD 221 色卡。

默认只预览；apply 必须显式确认版本化 manifest 的 SHA-256。流程拒绝销售中已启用
颜色、部分冲突元数据和内容冲突图片。新图片以 ``0644`` 原子发布，数据库在单事务
内批量更新；数据库失败时删除本轮新图片，完全相同重放保持零写入。
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit

from tortoise import Tortoise, timezone
from tortoise.transactions import in_transaction

from app.core.config import settings
from app.db.database import TORTOISE_ORM
from app.models.bead_color import BeadColor
from app.repositories.product_repo import ProductRepository
from app.tasks.mard_catalog import (
    EXPECTED_COLOR_COUNT,
    ManifestColor,
    MardCatalogError,
    build_swatch_png,
    load_manifest,
)


MANIFEST = Path(__file__).resolve().parent / "manifests" / "mard_221.json"
STORAGE_ROOT = Path("/data/images")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class GateAMardPublishError(RuntimeError):
    """不包含 Secret、PII 或业务明细的 Gate A 色卡发布错误。"""


@dataclass(frozen=True, slots=True)
class PublishPlan:
    colors: tuple[ManifestColor, ...]
    manifest_sha256: str
    database_changes: int
    images_to_create: int
    images_reused: int
    total_image_bytes: int
    image_set_sha256: str

    @property
    def already_current(self) -> bool:
        return self.database_changes == 0 and self.images_to_create == 0


def _manifest_sha256() -> str:
    return hashlib.sha256(MANIFEST.read_bytes()).hexdigest()


def _base_url() -> str:
    value = settings.product_image_base_url.rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/uploads/products"
    ):
        raise GateAMardPublishError(
            "Gate A image base URL must use the approved HTTPS path"
        )
    return value


def _desired(color: ManifestColor, base_url: str) -> tuple[object, ...]:
    return (
        color.slot_no,
        color.color_code,
        color.name,
        f"{base_url}/{color.image_filename}",
        color.sort,
        True,
    )


def _row(row: BeadColor) -> tuple[object, ...]:
    return (
        row.slot_no,
        row.color_code,
        row.name,
        row.swatch_image_url,
        row.sort,
        row.is_active,
    )


def _validate_rows(
    rows: list[BeadColor],
    colors: tuple[ManifestColor, ...],
    base_url: str,
) -> int:
    if len(rows) != EXPECTED_COLOR_COUNT or tuple(row.slot_no for row in rows) != tuple(
        range(1, EXPECTED_COLOR_COUNT + 1)
    ):
        raise GateAMardPublishError("database must contain exactly slots 1 through 221")

    changes = 0
    for row, color in zip(rows, colors):
        desired = _desired(color, base_url)
        current = _row(row)
        if current == desired:
            continue
        if row.is_active:
            raise GateAMardPublishError("an active bead color differs from the manifest")
        for existing, target in zip(current[1:5], desired[1:5]):
            if existing is not None and existing != target:
                raise GateAMardPublishError(
                    "bead color metadata conflicts with the manifest"
                )
        changes += 1
    return changes


def _inspect_images(colors: tuple[ManifestColor, ...]) -> tuple[int, int, int, str]:
    if not STORAGE_ROOT.is_dir() or STORAGE_ROOT.is_symlink():
        raise GateAMardPublishError("Gate A image storage root is unavailable")
    images_to_create = 0
    images_reused = 0
    total_bytes = 0
    digest = hashlib.sha256()
    for color in colors:
        content = build_swatch_png(color.rgb)
        total_bytes += len(content)
        digest.update(color.image_filename.encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
        target = STORAGE_ROOT / color.image_filename
        if target.is_symlink():
            raise GateAMardPublishError("a MARD image target must not be a symlink")
        if not target.exists():
            images_to_create += 1
        elif (
            not target.is_file()
            or stat.S_IMODE(target.stat().st_mode) != 0o644
            or target.read_bytes() != content
        ):
            raise GateAMardPublishError("an existing MARD image has conflicting content")
        else:
            images_reused += 1
    return images_to_create, images_reused, total_bytes, digest.hexdigest()


async def plan_publish(repository: ProductRepository) -> PublishPlan:
    """只读验证 M6 目录、manifest、HTTPS URL 和持久图片卷。"""

    if (
        settings.app_env != "production"
        or settings.db_engine != "mysql"
        or Path(settings.product_image_upload_dir) != STORAGE_ROOT
    ):
        raise GateAMardPublishError(
            "Gate A MARD publication requires production MySQL and /data/images"
        )
    try:
        colors = load_manifest(MANIFEST)
    except MardCatalogError as error:
        raise GateAMardPublishError(str(error)) from error
    base_url = _base_url()
    rows = await repository.list_all_bead_colors()
    database_changes = _validate_rows(rows, colors, base_url)
    if await repository.has_online_product_with_enabled_colors():
        raise GateAMardPublishError(
            "refuse catalog publication while an Online product enables colors"
        )
    images_to_create, images_reused, total_bytes, image_digest = _inspect_images(
        colors
    )
    return PublishPlan(
        colors=colors,
        manifest_sha256=_manifest_sha256(),
        database_changes=database_changes,
        images_to_create=images_to_create,
        images_reused=images_reused,
        total_image_bytes=total_bytes,
        image_set_sha256=image_digest,
    )


def _publish_images(colors: tuple[ManifestColor, ...]) -> tuple[Path, ...]:
    created: list[Path] = []
    try:
        for color in colors:
            content = build_swatch_png(color.rgb)
            target = STORAGE_ROOT / color.image_filename
            if target.exists():
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or stat.S_IMODE(target.stat().st_mode) != 0o644
                    or target.read_bytes() != content
                ):
                    raise GateAMardPublishError(
                        "an existing MARD image changed after preview"
                    )
                continue
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=STORAGE_ROOT,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    os.fchmod(output.fileno(), 0o644)
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                try:
                    os.link(temporary, target)
                    created.append(target)
                except FileExistsError:
                    if target.is_symlink() or target.read_bytes() != content:
                        raise GateAMardPublishError(
                            "MARD image publication raced with conflicting content"
                        )
            finally:
                temporary.unlink(missing_ok=True)
    except BaseException:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    return tuple(created)


async def apply_publish(repository: ProductRepository, plan: PublishPlan) -> int:
    """原子发布图片并事务更新 221 槽；失败时补偿本轮文件。"""

    if plan.already_current:
        return 0
    base_url = _base_url()
    created = _publish_images(plan.colors)
    try:
        if plan.database_changes:
            async with in_transaction() as connection:
                rows = await repository.list_bead_colors_for_update(
                    using_db=connection
                )
                _validate_rows(rows, plan.colors, base_url)
                if await repository.has_online_product_with_enabled_colors(
                    using_db=connection
                ):
                    raise GateAMardPublishError(
                        "an Online product enabled colors after preview"
                    )
                now = timezone.now()
                for row, color in zip(rows, plan.colors):
                    desired = _desired(color, base_url)
                    (
                        _,
                        row.color_code,
                        row.name,
                        row.swatch_image_url,
                        row.sort,
                        row.is_active,
                    ) = desired
                    row.updated_at = now
                await repository.bulk_update_bead_colors(
                    rows,
                    using_db=connection,
                )
                verified = await repository.list_bead_colors_for_update(
                    using_db=connection
                )
                if _validate_rows(verified, plan.colors, base_url) != 0:
                    raise GateAMardPublishError(
                        "database catalog verification did not converge"
                    )
    except BaseException:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise

    replay = await plan_publish(repository)
    if not replay.already_current:
        raise GateAMardPublishError("MARD publication replay verification failed")
    return len(created)


def _result(plan: PublishPlan, *, mode: str, created_images: int = 0) -> str:
    return json.dumps(
        {
            "already_current": plan.already_current,
            "colors": len(plan.colors),
            "created_images": created_images,
            "database_changes": plan.database_changes,
            "image_set_sha256": plan.image_set_sha256,
            "images_reused": plan.images_reused,
            "images_to_create": plan.images_to_create,
            "manifest_sha256": plan.manifest_sha256,
            "mode": mode,
            "total_image_bytes": plan.total_image_bytes,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or apply the frozen MARD 221 catalog to Gate A.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-manifest-sha256")
    return parser


async def run(*, apply: bool, confirmed_sha256: str | None) -> str:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        repository = ProductRepository()
        plan = await plan_publish(repository)
        if not apply:
            if confirmed_sha256 is not None:
                raise GateAMardPublishError(
                    "preview does not accept manifest confirmation"
                )
            return _result(plan, mode="preview")
        if (
            confirmed_sha256 is None
            or SHA256_PATTERN.fullmatch(confirmed_sha256) is None
            or confirmed_sha256 != plan.manifest_sha256
        ):
            raise GateAMardPublishError(
                "apply requires the exact preview manifest SHA-256"
            )
        created = await apply_publish(repository, plan)
        return _result(plan, mode="apply", created_images=created)
    finally:
        await Tortoise.close_connections()


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = asyncio.run(
            run(
                apply=args.apply,
                confirmed_sha256=args.confirm_manifest_sha256,
            )
        )
    except GateAMardPublishError as error:
        print(f"Gate A MARD publication failed: {error}")
        return 1
    except Exception as error:
        print(
            "Gate A MARD publication failed: "
            f"error_type={type(error).__name__}"
        )
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
