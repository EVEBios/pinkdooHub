"""User Repository —— 封装 User 表的数据访问。"""

from tortoise.backends.base.client import BaseDBAsyncClient

from app.models.user import User


class UserRepository:
    """User 数据访问层。

    每个方法只做一类查询，不包含业务判断。
    业务规则（如"用户名不能重复"）在 Service 层处理。
    """

    async def get_by_id(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> User | None:
        """根据主键查询用户。"""
        query = User.filter(id=user_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_for_update(
        self,
        user_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> User | None:
        """在调用方事务内锁定用户行。"""

        return await (
            User.filter(id=user_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_by_username(self, username: str) -> User | None:
        """根据用户名查询用户。"""
        return await User.filter(username=username).first()

    async def get_by_phone(self, phone: str) -> User | None:
        """根据手机号查询用户。"""
        return await User.filter(phone=phone).first()

    async def get_by_phone_exclude_id(self, phone: str, user_id: int) -> User | None:
        """根据手机号查询用户，排除指定 ID。

        更新个人信息时使用——不能因为"自己手机号没变"就报重复。
        """
        return await User.filter(phone=phone).exclude(id=user_id).first()

    async def list_filtered(
        self,
        offset: int,
        limit: int,
        status: int | None = None,
        role: int | None = None,
    ) -> tuple[list[User], int]:
        """分页筛选查询用户——只认 offset/limit，不接触分页概念。

        未来扩展游标分页、无限滚动时，Repository 层无需改动。
        """
        qs = User.all()
        if status is not None:
            qs = qs.filter(status=status)
        if role is not None:
            qs = qs.filter(role=role)

        total = await qs.count()
        items = await (
            qs.order_by("-created_at", "-id")
            .offset(offset)
            .limit(limit)
        )
        return items, total

    async def create(self, **kwargs) -> User:
        """创建用户，返回包含 id 的完整 User 对象。"""
        return await User.create(**kwargs)

    async def update(
        self,
        user: User,
        *,
        using_db: BaseDBAsyncClient | None = None,
        **kwargs,
    ) -> User:
        """部分更新用户字段，自动保存。"""
        await user.update_from_dict(kwargs).save(using_db=using_db)
        return user
