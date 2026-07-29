"""管理端 API —— RBAC 权限演示。

Phase 3.3: 管理员/超级管理员端点，通过 Depends 链式组合实现权限控制。
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin, get_current_super_admin
from app.common.response import success
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserListItem

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    admin: User = Depends(get_current_admin),
    user_repo: UserRepository = Depends(),
):
    """用户列表——管理员及以上可访问。

    演示权限依赖注入的效果：一行 Depends(get_current_admin) 即完成
    Token 解析 → 用户查询 → 角色校验。
    """
    # Phase 3 仅返回前 20 条，Phase 4 加入分页
    users = await User.filter().limit(20)
    items = [UserListItem.model_validate(u).model_dump() for u in users]
    return success(data={"items": items, "total": len(items)})


@router.get("/config")
async def system_config(
    super_admin: User = Depends(get_current_super_admin),
):
    """系统配置——仅超级管理员可访问。"""
    return success(data={"message": "System config: super admin only"})
