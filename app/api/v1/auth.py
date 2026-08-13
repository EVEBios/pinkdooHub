"""认证 API —— 注册、登录、刷新、登出。"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_user, security
from app.common.response import success
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import LoginRequest, RefreshOut, RefreshRequest, TokenOut
from app.schemas.user import UserCreate, UserOut
from app.services.auth_service import AuthService
from app.utils.request import get_client_ip

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(
    data: UserCreate,
    request: Request,
    user_repo: UserRepository = Depends(),
):
    """用户注册。"""
    service = AuthService(user_repo)
    user = await service.register(data, ip_address=get_client_ip(request))
    return success(data=UserOut.model_validate(user).model_dump())


@router.post("/login")
async def login(
    data: LoginRequest,
    request: Request,
    user_repo: UserRepository = Depends(),
):
    """用户登录——返回 access_token + refresh_token。"""
    service = AuthService(user_repo)
    result = await service.login(data, ip_address=get_client_ip(request))
    return success(
        data={
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "token_type": "Bearer",
            "expires_in": 7200,
            "user": UserOut.model_validate(result["user"]).model_dump(),
        }
    )


@router.post("/refresh")
async def refresh(
    data: RefreshRequest,
    user_repo: UserRepository = Depends(),
):
    """用 refresh token 换取新的 access token。"""
    service = AuthService(user_repo)
    result = await service.refresh(data.refresh_token)
    return success(
        data={
            "access_token": result["access_token"],
            "token_type": "Bearer",
            "expires_in": 7200,
        }
    )


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(),
    credentials: type = Depends(security),
):
    """登出——撤销 refresh token。"""
    service = AuthService(user_repo)
    await service.logout(credentials.credentials)
    return success(message="Logged out")
