"""在 Gate A 停写窗口中一次只应用一条经批准的 Aerich 迁移。

Aerich 0.9.3 的 CLI 不提供目标版本参数。本任务在容器 ``/tmp`` 中创建只包含
目标及更早迁移的短期目录，再调用 Aerich 的公开 ``Command.upgrade()``；数据库
版本链必须精确等于目标的前一版本或已经等于目标，禁止 fake、downgrade、跳级
和未知起点。
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import tempfile

from aerich import Command
from aerich.models import Aerich

from app.core.config import settings
from app.db.database import TORTOISE_ORM


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SOURCE = REPOSITORY_ROOT / "migrations" / "models"
APPROVED_MIGRATIONS = (
    "0_20260810101218_init.py",
    "1_20260813130455_add_order_tables.py",
    "2_20260814104655_add_inventory_transactions.py",
    "3_20260902125032_phase95_external_identity.py",
    "4_20260905162243_add_wallet_payment_refund.py",
    "5_20260906094653_add_reservations.py",
    "6_20260906123000_add_color_selectable_kits.py",
    "7_20260907190000_add_reservation_settings.py",
    "8_20260908140000_add_bead_color_swatch_hex.py",
    "9_20260910180000_add_table_sessions.py",
)
APPROVED_TARGETS = tuple(range(3, len(APPROVED_MIGRATIONS)))


class GateAMigrationStepError(RuntimeError):
    """不包含连接串、Secret 或业务数据的单步迁移错误。"""


@dataclass(frozen=True, slots=True)
class MigrationStepResult:
    target_version: int
    migration: str
    applied: bool
    aerich_versions: tuple[str, ...]


def _validate_sources() -> None:
    actual = tuple(
        sorted(path.name for path in MIGRATION_SOURCE.glob("[0-9]*_*.py"))
    )
    if actual != APPROVED_MIGRATIONS:
        raise GateAMigrationStepError(
            "repository migration files do not match the approved M0-M9 chain"
        )


async def _current_versions() -> tuple[str, ...]:
    return tuple(
        await Aerich.filter(app="models").order_by("id").values_list(
            "version",
            flat=True,
        )
    )


async def apply_migration_step(target_version: int) -> MigrationStepResult:
    """从精确前一版本应用目标迁移；已在目标版本时严格 no-op。"""

    if target_version not in APPROVED_TARGETS:
        raise GateAMigrationStepError("target version must be one of M3 through M9")
    if settings.app_env != "production" or settings.db_engine != "mysql":
        raise GateAMigrationStepError(
            "Gate A migration steps require production MySQL semantics"
        )
    _validate_sources()

    expected_before = APPROVED_MIGRATIONS[:target_version]
    expected_after = APPROVED_MIGRATIONS[: target_version + 1]
    with tempfile.TemporaryDirectory(prefix="pinkdoohub-gatea-migration-") as root:
        migration_root = Path(root) / "migrations"
        target_directory = migration_root / "models"
        target_directory.mkdir(parents=True, mode=0o700)
        for migration in expected_after:
            shutil.copy2(MIGRATION_SOURCE / migration, target_directory / migration)

        command = Command(
            tortoise_config=TORTOISE_ORM,
            app="models",
            location=str(migration_root),
        )
        try:
            await command.init()
            before = await _current_versions()
            if before == expected_after:
                return MigrationStepResult(
                    target_version=target_version,
                    migration=APPROVED_MIGRATIONS[target_version],
                    applied=False,
                    aerich_versions=before,
                )
            if before != expected_before:
                raise GateAMigrationStepError(
                    "database Aerich chain is not the approved preceding version"
                )

            migrated = await command.upgrade()
            if migrated != [APPROVED_MIGRATIONS[target_version]]:
                raise GateAMigrationStepError(
                    "Aerich did not apply exactly the approved target migration"
                )
            after = await _current_versions()
            if after != expected_after:
                raise GateAMigrationStepError(
                    "database Aerich chain does not match the approved target"
                )
            return MigrationStepResult(
                target_version=target_version,
                migration=APPROVED_MIGRATIONS[target_version],
                applied=True,
                aerich_versions=after,
            )
        finally:
            await command.aclose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply exactly one approved Gate A Aerich migration step.",
    )
    parser.add_argument(
        "--target-version",
        type=int,
        choices=APPROVED_TARGETS,
        required=True,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(apply_migration_step(args.target_version))
    except GateAMigrationStepError as error:
        print(f"Gate A migration step failed: {error}")
        return 1
    except Exception as error:
        print(
            "Gate A migration step failed: " f"error_type={type(error).__name__}"
        )
        return 1
    print(
        json.dumps(
            {
                "aerich_versions": list(result.aerich_versions),
                "applied": result.applied,
                "migration": result.migration,
                "target_version": result.target_version,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
