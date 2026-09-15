"""UserRepository 并发安全的部分更新契约。"""

from datetime import datetime, timezone

from app.common.enums.user import UserRole, UserStatus
from app.models.user import User
from app.repositories.user_repo import UserRepository


async def test_partial_update_does_not_overwrite_concurrent_user_state() -> None:
    user = await User.create(
        username="stale-user-update",
        password="hashed-password",
        nickname="更新前昵称",
        role=UserRole.USER.value,
        status=UserStatus.NORMAL.value,
    )
    stale_user = await UserRepository().get_by_id(user.id)
    assert stale_user is not None

    await User.filter(id=user.id).update(
        nickname="并发更新后的昵称",
        status=UserStatus.DISABLED.value,
    )
    await UserRepository().update(
        stale_user,
        last_login_at=datetime.now(timezone.utc),
    )

    stored = await User.get(id=user.id)
    assert stored.nickname == "并发更新后的昵称"
    assert stored.status == UserStatus.DISABLED
    assert stored.last_login_at is not None
