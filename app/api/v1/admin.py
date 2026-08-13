"""管理端共享 API —— 仅保留跨模块的超级管理员配置端点。"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_super_admin
from app.common.response import success
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/config")
async def system_config(
    super_admin: User = Depends(get_current_super_admin),
):
    """系统配置——仅超级管理员可访问。"""
    return success(data={"message": "System config: super admin only"})
