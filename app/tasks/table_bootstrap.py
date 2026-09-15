"""幂等初始化 30 张桌台，并生成仅供内部验收的普通二维码。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import secrets
import sys
from pathlib import Path

import segno
from tortoise import Tortoise
from tortoise.transactions import in_transaction

from app.common.constants.table_session import (
    TABLE_COUNT,
    TABLE_NO_PREFIX,
    TABLE_QR_TOKEN_ALPHABET,
    TABLE_QR_TOKEN_LENGTH,
)
from app.db.database import TORTOISE_ORM
from app.models.table_session import StoreTable
from app.repositories.table_session_repo import TableSessionRepository


class TableBootstrapError(RuntimeError):
    """桌台初始化或占位码生成不满足冻结约束。"""


def expected_table_numbers() -> tuple[str, ...]:
    return tuple(f"{TABLE_NO_PREFIX}{index:02d}" for index in range(1, TABLE_COUNT + 1))


def generate_qr_token() -> str:
    return "".join(
        secrets.choice(TABLE_QR_TOKEN_ALPHABET) for _ in range(TABLE_QR_TOKEN_LENGTH)
    )


async def verify_tables(repository: TableSessionRepository) -> list[StoreTable]:
    tables = await repository.list_table_definitions()
    actual_numbers = tuple(table.table_no for table in tables)
    if actual_numbers != expected_table_numbers():
        raise TableBootstrapError(
            "store_tables must contain exactly T01 through T30 before acceptance"
        )
    if any(table.display_name != f"{table.table_no}号桌" for table in tables):
        raise TableBootstrapError("store table display names do not match table numbers")
    if len({table.qr_token for table in tables}) != TABLE_COUNT:
        raise TableBootstrapError("all 30 table QR tokens must be unique")
    if any(
        len(table.qr_token) != TABLE_QR_TOKEN_LENGTH
        or any(character not in TABLE_QR_TOKEN_ALPHABET for character in table.qr_token)
        for table in tables
    ):
        raise TableBootstrapError("table QR token violates the 32-character contract")
    return list(tables)


async def seed_tables(repository: TableSessionRepository) -> None:
    existing = await repository.list_table_definitions()
    if existing:
        await verify_tables(repository)
        return
    definitions = [
        (table_no, f"{table_no}号桌", generate_qr_token())
        for table_no in expected_table_numbers()
    ]
    if len({definition[2] for definition in definitions}) != TABLE_COUNT:
        raise TableBootstrapError("generated duplicate QR token; rerun the command")
    async with in_transaction() as connection:
        await repository.bulk_create_tables(
            tables=definitions,
            using_db=connection,
        )
    await verify_tables(repository)


def write_placeholder_qr_artifacts(
    tables: list[StoreTable],
    output_dir: Path,
) -> None:
    if output_dir.is_symlink():
        raise TableBootstrapError("QR output directory must not be a symbolic link")
    if output_dir.exists():
        raise TableBootstrapError("QR output directory must be a new path")
    output_dir.mkdir(parents=True, exist_ok=False)
    if not output_dir.is_dir():
        raise TableBootstrapError("QR output path must be a directory")
    output_dir.chmod(0o700)
    expected_files: set[str] = {"manifest.json"}
    manifest_items: list[dict[str, str | int]] = []
    for table in tables:
        filename = f"{table.table_no}.png"
        expected_files.add(filename)
        payload = f"PINKDOOHUB_TABLE:v1:{table.qr_token}"
        path = output_dir / filename
        if path.is_symlink():
            raise TableBootstrapError(
                f"QR artifact must not be a symbolic link: {filename}"
            )
        segno.make(payload, error="h", micro=False).save(
            path,
            kind="png",
            scale=12,
            border=4,
            dark="#191014",
            light="#ffffff",
        )
        path.chmod(0o600)
        content = path.read_bytes()
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise TableBootstrapError(f"QR artifact is not a PNG file: {filename}")
        manifest_items.append(
            {
                "table_no": table.table_no,
                "display_name": table.display_name,
                "filename": filename,
                "file_sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "payload_sha256": hashlib.sha256(payload.encode("ascii")).hexdigest(),
                "qr_token_sha256": hashlib.sha256(
                    table.qr_token.encode("ascii")
                ).hexdigest(),
            }
        )
    unexpected = {path.name for path in output_dir.iterdir()} - expected_files
    if unexpected:
        raise TableBootstrapError(
            f"output directory contains unexpected files: {sorted(unexpected)}"
        )
    manifest = {
        "schema_version": 1,
        "kind": "placeholder_qr",
        "wechat_environment": "develop",
        "replace_before_wechat_distribution": True,
        "payload_format": "PINKDOOHUB_TABLE:v1:<32-char token>",
        "launch_path": "pages/table-entry/index",
        "count": TABLE_COUNT,
        "items": manifest_items,
    }
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_symlink():
        raise TableBootstrapError("QR manifest must not be a symbolic link")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
    actual_files = {path.name for path in output_dir.iterdir()}
    if actual_files != expected_files:
        raise TableBootstrapError("QR output file inventory is incomplete")
    if any((output_dir / filename).stat().st_mode & 0o077 for filename in actual_files):
        raise TableBootstrapError("QR artifacts must not be group/world accessible")


async def run(*, apply: bool, output_dir: Path | None) -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        repository = TableSessionRepository()
        if apply:
            await seed_tables(repository)
        tables = await verify_tables(repository)
        if output_dir is not None:
            write_placeholder_qr_artifacts(tables, output_dir)
        sys.stdout.write(
            json.dumps(
                {
                    "status": "ok",
                    "table_count": len(tables),
                    "placeholder_qr_count": len(tables) if output_dir else 0,
                    "wechat_environment": "develop",
                },
                separators=(",", ":"),
            )
            + "\n"
        )
    finally:
        await Tortoise.close_connections()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="create T01-T30 only when store_tables is empty",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="write 30 internal-only ordinary QR PNG files and a redacted manifest",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(run(apply=arguments.apply, output_dir=arguments.output_dir))
