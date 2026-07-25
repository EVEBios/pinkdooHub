"""用户 API —— 个人信息管理。

Phase 2: GET /users/me（需要 JWT 认证）。
Phase 3: 将加入 PUT /users/me、密码修改、头像上传。
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.common.response import success
from app.models.user import User
from app.schemas.user import UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    """获取当前登录用户信息。

    Header: Authorization: Bearer <access_token>
    """
    return current_user
