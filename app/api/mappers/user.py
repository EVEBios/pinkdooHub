"""User ORM Model 到管理端响应 Schema 的同步纯映射。"""

from app.common.pagination import Page
from app.models.user import User
from app.schemas.user import UserListItem


def map_admin_user_page(page: Page[User]) -> Page[UserListItem]:
    """只投影管理列表允许公开的用户字段。"""

    return Page[UserListItem](
        items=[UserListItem.model_validate(user) for user in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )
