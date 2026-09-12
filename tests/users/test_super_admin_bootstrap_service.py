"""首个 SUPER_ADMIN Bootstrap 的事务、幂等和并发契约。"""

import asyncio

import pytest

from app.common.constants.bootstrap import SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
from app.common.enums.user import UserRole, UserStatus
from app.core.security import hash_password, verify_password
from app.models.audit_log import AuditLog
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.bootstrap_lock_repo import BootstrapLockRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.super_admin_bootstrap_service import (
    SuperAdminBootstrapConflict,
    SuperAdminBootstrapLockUnavailable,
    SuperAdminBootstrapService,
)

BOOTSTRAP_DATA = {
    "username": "initial_owner",
    "password": "bootstrap-secret-123",
    "nickname": "Initial Owner",
    "phone": "13800000101",
}


def _service(
    lock_repo: BootstrapLockRepository | None = None,
) -> SuperAdminBootstrapService:
    return SuperAdminBootstrapService(
        UserRepository(),
        AuditLogService(AuditLogRepository()),
        lock_repo or BootstrapLockRepository(),
    )


async def test_bootstrap_creates_super_admin_and_audit_atomically() -> None:
    result = await _service().bootstrap(**BOOTSTRAP_DATA)

    user = await User.get(id=result.user_id)
    logs = await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION,
        target_type="user",
        target_id=user.id,
    )

    assert result.created is True
    assert result.is_replay is False
    assert user.role == UserRole.SUPER_ADMIN
    assert user.status == UserStatus.NORMAL
    assert verify_password(BOOTSTRAP_DATA["password"], user.password)
    assert len(logs) == 1
    assert logs[0].operator_id == user.id
    assert logs[0].ip_address == "0.0.0.0"
    assert BOOTSTRAP_DATA["password"] not in (logs[0].description or "")


async def test_identical_bootstrap_is_strict_replay_without_mutation() -> None:
    first = await _service().bootstrap(**BOOTSTRAP_DATA)
    before = await User.get(id=first.user_id)
    original_hash = before.password
    original_updated_at = before.updated_at

    second = await _service().bootstrap(**BOOTSTRAP_DATA)
    after = await User.get(id=first.user_id)

    assert second.user_id == first.user_id
    assert second.created is False
    assert second.is_replay is True
    assert after.password == original_hash
    assert after.updated_at == original_updated_at
    assert await User.filter(role=int(UserRole.SUPER_ADMIN)).count() == 1
    assert await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
    ).count() == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("username", "different_owner"),
        ("password", "different-secret-456"),
        ("nickname", "Different Owner"),
        ("phone", "13800000102"),
    ],
)
async def test_existing_bootstrap_rejects_changed_identity_or_password(
    field: str,
    replacement: str,
) -> None:
    await _service().bootstrap(**BOOTSTRAP_DATA)
    changed = {**BOOTSTRAP_DATA, field: replacement}

    with pytest.raises(SuperAdminBootstrapConflict):
        await _service().bootstrap(**changed)

    assert await User.filter(role=int(UserRole.SUPER_ADMIN)).count() == 1
    assert await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
    ).count() == 1


@pytest.mark.parametrize("occupied_field", ["username", "phone"])
async def test_bootstrap_never_promotes_existing_user(occupied_field: str) -> None:
    ordinary_data = {
        "username": "ordinary" if occupied_field == "username" else "another",
        "phone": "13800000109" if occupied_field == "phone" else "13800000108",
    }
    if occupied_field == "username":
        ordinary_data["username"] = BOOTSTRAP_DATA["username"]
    else:
        ordinary_data["phone"] = BOOTSTRAP_DATA["phone"]
    ordinary = await User.create(
        **ordinary_data,
        password=hash_password("ordinary-secret"),
        nickname="Ordinary",
        role=int(UserRole.USER),
        status=int(UserStatus.NORMAL),
    )

    with pytest.raises(SuperAdminBootstrapConflict):
        await _service().bootstrap(**BOOTSTRAP_DATA)

    await ordinary.refresh_from_db()
    assert ordinary.role == UserRole.USER
    assert await User.filter(role=int(UserRole.SUPER_ADMIN)).count() == 0
    assert await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
    ).count() == 0


async def test_manual_super_admin_without_bootstrap_audit_is_rejected() -> None:
    manual = await User.create(
        username=BOOTSTRAP_DATA["username"],
        password=hash_password(BOOTSTRAP_DATA["password"]),
        nickname=BOOTSTRAP_DATA["nickname"],
        phone=BOOTSTRAP_DATA["phone"],
        role=int(UserRole.SUPER_ADMIN),
        status=int(UserStatus.NORMAL),
    )

    with pytest.raises(SuperAdminBootstrapConflict):
        await _service().bootstrap(**BOOTSTRAP_DATA)

    assert await User.filter(id=manual.id).count() == 1
    assert await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
    ).count() == 0


async def test_bootstrap_audit_without_super_admin_is_rejected() -> None:
    await AuditLog.create(
        operator_id=99,
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION,
        target_type="user",
        target_id=99,
        ip_address="0.0.0.0",
    )

    with pytest.raises(SuperAdminBootstrapConflict):
        await _service().bootstrap(**BOOTSTRAP_DATA)

    assert await User.filter(role=int(UserRole.SUPER_ADMIN)).count() == 0
    assert await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
    ).count() == 1


async def test_disabled_bootstrap_identity_is_not_silently_enabled() -> None:
    result = await _service().bootstrap(**BOOTSTRAP_DATA)
    user = await User.get(id=result.user_id)
    user.status = int(UserStatus.DISABLED)
    await user.save(update_fields=["status"])

    with pytest.raises(SuperAdminBootstrapConflict):
        await _service().bootstrap(**BOOTSTRAP_DATA)

    await user.refresh_from_db()
    assert user.status == UserStatus.DISABLED
    assert await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
    ).count() == 1


async def test_audit_failure_rolls_back_created_user(monkeypatch) -> None:
    service = _service()

    async def fail_audit(*args, **kwargs) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service.audit_log_service, "log", fail_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await service.bootstrap(**BOOTSTRAP_DATA)

    assert await User.all().count() == 0
    assert await AuditLog.all().count() == 0


async def test_concurrent_identical_bootstrap_creates_only_once() -> None:
    first, second = await asyncio.gather(
        _service().bootstrap(**BOOTSTRAP_DATA),
        _service().bootstrap(**BOOTSTRAP_DATA),
    )

    assert {first.created, second.created} == {True, False}
    assert first.user_id == second.user_id
    assert await User.filter(role=int(UserRole.SUPER_ADMIN)).count() == 1
    assert await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
    ).count() == 1


async def test_concurrent_different_bootstrap_allows_only_one_identity() -> None:
    results = await asyncio.gather(
        _service().bootstrap(**BOOTSTRAP_DATA),
        _service().bootstrap(
            **{
                **BOOTSTRAP_DATA,
                "username": "competing_owner",
                "phone": "13800000103",
            }
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert sum(isinstance(item, SuperAdminBootstrapConflict) for item in results) == 1
    assert await User.filter(role=int(UserRole.SUPER_ADMIN)).count() == 1
    assert await AuditLog.filter(
        action=SUPER_ADMIN_BOOTSTRAP_AUDIT_ACTION
    ).count() == 1


async def test_lock_timeout_does_not_touch_database() -> None:
    class UnavailableLockRepository(BootstrapLockRepository):
        async def acquire_process_lock(self, timeout_seconds: int) -> bool:
            return False

    with pytest.raises(SuperAdminBootstrapLockUnavailable):
        await _service(UnavailableLockRepository()).bootstrap(**BOOTSTRAP_DATA)

    assert await User.all().count() == 0
    assert await AuditLog.all().count() == 0
