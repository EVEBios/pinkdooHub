"""User Repository —— 封装 User 表的数据访问。"""

from app.models.user import User


class UserRepository:
    """User 数据访问层。

    每个方法只做一类查询，不包含业务判断。
    业务规则（如"用户名不能重复"）在 Service 层处理。
    """

    async def get_by_id(self, user_id: int) -> User | None:
        """根据主键查询用户。"""
        return await User.filter(id=user_id).first()

    async def get_by_username(self, username: str) -> User | None:
        """根据用户名查询用户。"""
        return await User.filter(username=username).first()

    async def get_by_phone(self, phone: str) -> User | None:
        """根据手机号查询用户。"""
        return await User.filter(phone=phone).first()

    async def create(self, **kwargs) -> User:
        """创建用户，返回包含 id 的完整 User 对象。"""
        return await User.create(**kwargs)
