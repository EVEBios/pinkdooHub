"""历史普通用户钱包补建任务测试。"""

import pytest

from app.common.enums.user import UserRole, UserStatus
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.wallet_repo import WalletRepository
from app.repositories.user_repo import UserRepository
from app.tasks.wallet_account_backfill import backfill_all


async def _user(
    username: str,
    role: UserRole,
    *,
    status: UserStatus = UserStatus.NORMAL,
) -> User:
    return await User.create(
        username=username,
        password="hashed-password",
        nickname=username,
        role=role.value,
        status=status.value,
    )


async def test_backfill_preview_and_apply_only_create_missing_customer_wallets() -> None:
    existing_customer = await _user("backfill-existing", UserRole.USER)
    first_missing = await _user("backfill-first", UserRole.USER)
    second_missing = await _user("backfill-second", UserRole.USER)
    disabled_missing = await _user(
        "backfill-disabled",
        UserRole.USER,
        status=UserStatus.DISABLED,
    )
    deleted = await _user(
        "backfill-deleted",
        UserRole.USER,
        status=UserStatus.DELETED,
    )
    admin = await _user("backfill-admin", UserRole.ADMIN)
    existing_wallet = await WalletAccount.create(user=existing_customer)
    repository = WalletRepository()

    user_repository = UserRepository()
    preview = await backfill_all(
        repository,
        user_repository,
        batch_size=1,
        dry_run=True,
    )
    assert preview.through_user_id == admin.id
    assert preview.scanned == 3
    assert preview.would_create == 3
    assert preview.created == 0
    assert await WalletAccount.all().count() == 1

    applied = await backfill_all(
        repository,
        user_repository,
        batch_size=1,
        dry_run=False,
        through_user_id=preview.through_user_id,
    )
    assert applied.through_user_id == preview.through_user_id
    assert applied.scanned == 3
    assert applied.created == 3
    assert applied.would_create == 0
    assert await WalletAccount.filter(
        user_id__in=[first_missing.id, second_missing.id, disabled_missing.id]
    ).count() == 3
    assert await WalletAccount.filter(user_id=admin.id).count() == 0
    assert await WalletAccount.filter(user_id=deleted.id).count() == 0
    assert await WalletAccount.filter(id=existing_wallet.id).count() == 1
    assert await WalletTransaction.all().count() == 0

    replay = await backfill_all(
        repository,
        user_repository,
        batch_size=5,
        dry_run=False,
        through_user_id=preview.through_user_id,
    )
    assert replay.scanned == replay.created == replay.would_create == 0


async def test_backfill_apply_requires_preview_scope_and_rechecks_locked_user() -> None:
    target = await _user("backfill-race-target", UserRole.USER)
    repository = WalletRepository()

    class StatusChangingUserRepository(UserRepository):
        async def list_by_ids_for_update(self, user_ids, *, using_db):
            await User.filter(id=target.id).using_db(using_db).update(
                status=UserStatus.DELETED.value,
            )
            return await super().list_by_ids_for_update(
                user_ids,
                using_db=using_db,
            )

    user_repository = StatusChangingUserRepository()
    with pytest.raises(ValueError, match="through_user_id"):
        await backfill_all(
            repository,
            user_repository,
            batch_size=10,
            dry_run=False,
        )

    result = await backfill_all(
        repository,
        user_repository,
        batch_size=10,
        dry_run=False,
        through_user_id=target.id,
    )

    assert result.through_user_id == target.id
    assert result.scanned == 1
    assert result.created == 0
    assert not await WalletAccount.filter(user_id=target.id).exists()
