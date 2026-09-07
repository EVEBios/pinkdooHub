"""综合本地演示数据命令的安全性、覆盖面与重放契约。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import stat
import sys

import pytest

from app.common.enums.reservation import ReservationWeekday
from app.common.enums.user import UserRole, UserStatus
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit_color import ProductKitColor
from app.models.reservation import Reservation, ReservationSettings, StoreBusinessDay
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.tasks import local_demo_seed, local_demo_support


pytestmark = pytest.mark.asyncio


async def _create_operator() -> User:
    operator = await User.create(
        username="local-demo-operator",
        password=hash_password("test-only-operator-password"),
        nickname="本地演示操作者",
        phone="13900006100",
        role=UserRole.SUPER_ADMIN.value,
        status=UserStatus.NORMAL.value,
    )
    await ReservationSettings.create()
    return operator


async def _seed_counts() -> dict[str, int]:
    models = (
        User,
        Product,
        ProductImage,
        ProductKitColor,
        Order,
        OrderItem,
        InventoryTransaction,
        WalletAccount,
        WalletTransaction,
        Payment,
        PaymentSettlement,
        Refund,
        Reservation,
        StoreBusinessDay,
        ReservationSettings,
        AuditLog,
    )
    return {model._meta.db_table: await model.all().count() for model in models}


async def test_credentials_are_private_atomic_and_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_demo_support, "REPOSITORY_ROOT", tmp_path)
    path = tmp_path / "backups/local-demo-data/synthetic-credentials.json"

    first = await local_demo_seed.prepare_credentials(path)
    stored_first = path.read_bytes()
    second = await local_demo_seed.prepare_credentials(path)

    assert first.created is True
    assert second.created is False
    assert first.passwords == second.passwords
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert set(json.loads(stored_first)["users"]) == set(
        local_demo_support.USER_SPEC_BY_USERNAME
    )
    assert path.read_bytes() == stored_first
    assert not list(path.parent.glob(".*.tmp"))


async def test_missing_credentials_refuses_existing_reserved_users(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_demo_support, "REPOSITORY_ROOT", tmp_path)
    spec = local_demo_support.SYNTHETIC_USER_SPECS[0]
    await User.create(
        username=spec.username,
        password=hash_password("unknown-existing-password"),
        nickname=spec.nickname,
        phone=spec.phone,
        role=UserRole.USER.value,
        status=UserStatus.NORMAL.value,
    )

    with pytest.raises(
        local_demo_seed.LocalDemoSeedError,
        match="credentials file is missing",
    ):
        await local_demo_seed.prepare_credentials(
            tmp_path / "backups/local-demo-data/synthetic-credentials.json"
        )


async def test_sqlite_backup_includes_committed_wal_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_demo_support, "REPOSITORY_ROOT", tmp_path)
    verified_backups: list[Path] = []
    verify_integrity = local_demo_support.verify_sqlite_integrity

    def track_backup_verification(path: Path) -> None:
        verify_integrity(path)
        verified_backups.append(path)

    monkeypatch.setattr(
        local_demo_support,
        "verify_sqlite_integrity",
        track_backup_verification,
    )
    database = tmp_path / "db.sqlite3"
    source = sqlite3.connect(database)
    try:
        assert source.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        source.execute(
            "CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        source.execute("INSERT INTO demo(value) VALUES (?)", ("committed-in-wal",))
        source.commit()

        backup = local_demo_seed.create_sqlite_backup(
            database,
            tmp_path / "backups/local-demo-data",
        )
    finally:
        source.close()

    restored = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        assert verified_backups == [backup]
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        assert restored.execute("SELECT value FROM demo").fetchall() == [
            ("committed-in-wal",)
        ]
        assert restored.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    finally:
        restored.close()


async def test_sqlite_backup_removes_snapshot_that_fails_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_demo_support, "REPOSITORY_ROOT", tmp_path)
    database = tmp_path / "db.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY)")
        connection.commit()
    finally:
        connection.close()

    def reject_snapshot(path: Path) -> None:
        raise local_demo_seed.LocalDemoSeedError(
            f"Synthetic verification failure for {path.name}"
        )

    monkeypatch.setattr(
        local_demo_support,
        "verify_sqlite_integrity",
        reject_snapshot,
    )
    backup_dir = tmp_path / "backups/local-demo-data"
    with pytest.raises(
        local_demo_seed.LocalDemoSeedError,
        match="Synthetic verification failure",
    ):
        local_demo_seed.create_sqlite_backup(database, backup_dir)

    assert not list(backup_dir.glob("*.bak"))


async def test_comprehensive_seed_is_idempotent_and_verifiable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_demo_support, "REPOSITORY_ROOT", tmp_path)
    operator = await _create_operator()
    credentials_file = (
        tmp_path / "backups/local-demo-data/synthetic-credentials.json"
    )
    fixed_now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
    kwargs = {
        "operator_username": operator.username,
        "credentials_file": credentials_file,
        "storage_root": tmp_path / "uploads/products",
        "storage_base_url": "/uploads/products",
        "now_provider": lambda: fixed_now,
    }
    image_storage = local_demo_seed.LocalImageStorage(
        root=kwargs["storage_root"],
        base_url=kwargs["storage_base_url"],
    )

    first = await local_demo_seed.seed_local_demo_data(**kwargs)
    counts_after_first = await _seed_counts()
    credential_bytes = credentials_file.read_bytes()
    second = await local_demo_seed.seed_local_demo_data(**kwargs)
    counts_after_second = await _seed_counts()

    assert second == first
    assert counts_after_second == counts_after_first
    assert credentials_file.read_bytes() == credential_bytes
    assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o600
    assert first.synthetic_users == 9
    assert first.disabled_users == 1
    assert first.products_by_status == {"draft": 3, "offline": 1, "online": 14}
    assert first.products_by_type == {"experience": 8, "kit": 10}
    assert first.fixed_kits == 9
    assert first.color_selectable_kits == 1
    assert first.deleted_products == 1
    assert first.enabled_demo_colors == 3
    assert first.orders_by_status == {
        "cancelled": 1,
        "completed": 2,
        "paid": 4,
        "pending": 1,
    }
    assert first.payments_by_method == {"manual": 2, "wallet": 4}
    assert first.settlements == 6
    assert first.refunds == 2
    assert first.reservations_by_status == {
        "cancelled": 3,
        "confirmed": 1,
        "pending": 1,
        "rejected": 1,
    }
    assert first.reservation_cancellation_reasons == {
        "customer_request": 1,
        "store_closed": 2,
    }
    assert first.closed_business_days == 1
    assert first.reopened_business_days == 1
    assert first.weekly_cancelled_reservations == 1
    assert first.weekly_closed_weekday == "wednesday"
    assert counts_after_first["users"] == 10
    assert counts_after_first["products"] == 18
    assert counts_after_first["orders"] == 8
    assert counts_after_first["payments"] == 6
    assert counts_after_first["payment_settlements"] == 6
    assert counts_after_first["refunds"] == 2
    assert counts_after_first["reservations"] == 6
    assert counts_after_first["reservation_settings"] == 1
    assert await local_demo_seed.verify_demo_data(
        now_utc=fixed_now,
        image_storage=image_storage,
    ) == first
    disabled_user = await User.get(username="localdemo_v1_disabled")
    disabled_wallet = await WalletAccount.get(user_id=disabled_user.id)
    assert disabled_wallet.balance == 0
    assert not await WalletTransaction.filter(
        wallet_account_id=disabled_wallet.id
    ).exists()
    pending_user = await User.get(username="localdemo_v1_res_pending")
    pending_reservation = await Reservation.get(user_id=pending_user.id)
    pending_business_day = await StoreBusinessDay.get(
        id=pending_reservation.business_day_id
    )
    with pytest.raises(
        local_demo_seed.LocalDemoSeedError,
        match="would affect non-demo Reservations",
    ):
        await local_demo_seed._assert_store_day_close_is_demo_only(
            pending_business_day.business_date,
            allowed_reservation_ids=frozenset(),
            now_utc=fixed_now,
        )

    original_start = pending_reservation.scheduled_start_at
    original_end = pending_reservation.scheduled_end_at
    pending_reservation.scheduled_start_at = fixed_now + timedelta(hours=2)
    pending_reservation.scheduled_end_at = fixed_now + timedelta(hours=3)
    await pending_reservation.save(
        update_fields=["scheduled_start_at", "scheduled_end_at"]
    )
    with pytest.raises(
        local_demo_seed.LocalDemoSeedError,
        match="outside the current booking window",
    ):
        await local_demo_seed.verify_demo_data(
            now_utc=fixed_now,
            image_storage=image_storage,
        )
    pending_reservation.scheduled_start_at = original_start
    pending_reservation.scheduled_end_at = original_end
    await pending_reservation.save(
        update_fields=["scheduled_start_at", "scheduled_end_at"]
    )

    image_row = await ProductImage.filter(is_deleted=False).first()
    assert image_row is not None
    image_key = image_storage.key_from_url(image_row.image_url)
    assert image_key is not None
    image_path = image_storage.root / image_key
    image_path.write_bytes(b"x")
    with pytest.raises(
        local_demo_seed.LocalDemoSeedError,
        match="Product image file is invalid",
    ):
        await local_demo_seed.verify_demo_data(
            now_utc=fixed_now,
            image_storage=image_storage,
        )

    image_path.unlink()
    with pytest.raises(
        local_demo_seed.LocalDemoSeedError,
        match="Product image file is missing",
    ):
        await local_demo_seed.verify_demo_data(
            now_utc=fixed_now,
            image_storage=image_storage,
        )
    assert not list((tmp_path / "backups/local-demo-data").glob(".*.tmp"))
    assert os.access(credentials_file, os.R_OK | os.W_OK)


async def test_seed_refuses_to_overwrite_existing_weekly_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_demo_support, "REPOSITORY_ROOT", tmp_path)
    operator = await _create_operator()
    settings_row = await ReservationSettings.get(singleton_key=True)
    settings_row.weekly_closed_weekday = ReservationWeekday.FRIDAY
    await settings_row.save(update_fields=["weekly_closed_weekday", "updated_at"])
    credentials_file = (
        tmp_path / "backups/local-demo-data/synthetic-credentials.json"
    )

    with pytest.raises(
        local_demo_seed.LocalDemoSeedError,
        match="must not be overwritten",
    ):
        await local_demo_seed.seed_local_demo_data(
            operator_username=operator.username,
            credentials_file=credentials_file,
            storage_root=tmp_path / "uploads/products",
            storage_base_url="/uploads/products",
            now_provider=lambda: datetime(
                2026,
                9,
                8,
                0,
                0,
                tzinfo=timezone.utc,
            ),
        )

    await settings_row.refresh_from_db()
    assert settings_row.weekly_closed_weekday == ReservationWeekday.FRIDAY
    assert await AuditLog.all().count() == 0
    assert await User.all().count() == 1
    assert not credentials_file.exists()


async def test_verify_mode_does_not_create_a_missing_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_database = tmp_path / "missing.sqlite3"
    monkeypatch.setattr(local_demo_support, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        local_demo_seed.settings,
        "db_sqlite_path",
        str(missing_database),
    )
    monkeypatch.setattr(
        local_demo_seed.settings,
        "product_image_upload_dir",
        str(tmp_path / "uploads/products"),
    )
    monkeypatch.setattr(sys, "argv", ["local_demo_seed", "--verify"])

    assert local_demo_seed.main() == 2
    assert not missing_database.exists()


async def test_command_suppresses_dependency_bind_parameter_logs() -> None:
    dependency_loggers = [
        logging.getLogger(name) for name in ("aiosqlite", "passlib", "tortoise")
    ]
    for dependency_logger in dependency_loggers:
        dependency_logger.setLevel(logging.DEBUG)

    local_demo_seed._suppress_dependency_debug_logs()

    assert all(
        dependency_logger.getEffectiveLevel() >= logging.WARNING
        for dependency_logger in dependency_loggers
    )
