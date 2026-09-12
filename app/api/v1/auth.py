"""认证 API —— 注册、登录、刷新、登出。"""

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import get_current_user, get_external_auth_service, security
from app.api.responses import error_responses, success_responses
from app.common.response import success
from app.core.config import settings
from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.schemas.auth import (
    ExternalIdentityListOut,
    ExternalIdentityOut,
    LoginRequest,
    RefreshOut,
    RefreshRequest,
    TokenOut,
    WeChatCodeRequest,
    WeChatUnbindRequest,
)
from app.schemas.user import UserCreate, UserOut
from app.services.auth_service import AuthService
from app.services.external_auth_service import ExternalAuthService
from app.utils.request import get_client_ip

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses=error_responses(400, 401, 403, 422, 429, 503),
)


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
    responses=success_responses(UserOut, status.HTTP_201_CREATED),
)
async def register(
    data: UserCreate,
    request: Request,
    user_repo: UserRepository = Depends(),
) -> dict:
    """用户注册。"""
    service = AuthService(user_repo)
    user = await service.register(data, ip_address=get_client_ip(request))
    return success(data=UserOut.model_validate(user).model_dump())


@router.post(
    "/login",
    response_model=None,
    responses=success_responses(TokenOut),
)
async def login(
    data: LoginRequest,
    request: Request,
    user_repo: UserRepository = Depends(),
) -> dict:
    """用户登录——返回 access_token + refresh_token。"""
    service = AuthService(user_repo)
    result = await service.login(data, ip_address=get_client_ip(request))
    return success(
        data={
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "token_type": "Bearer",
            "expires_in": settings.jwt_access_token_expire,
            "user": UserOut.model_validate(result["user"]).model_dump(),
        }
    )


@router.post(
    "/refresh",
    response_model=None,
    responses=success_responses(RefreshOut),
)
async def refresh(
    data: RefreshRequest,
    request: Request,
    user_repo: UserRepository = Depends(),
) -> dict:
    """用 refresh token 轮换新的双 Token。"""
    service = AuthService(user_repo)
    result = await service.refresh(
        data.refresh_token,
        ip_address=get_client_ip(request),
    )
    return success(
        data={
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "token_type": "Bearer",
            "expires_in": settings.jwt_access_token_expire,
        }
    )


@router.post(
    "/logout",
    response_model=None,
    responses=success_responses(type(None)),
)
async def logout(
    current_user: User = Depends(get_current_user),
    user_repo: UserRepository = Depends(),
    credentials: type = Depends(security),
) -> dict:
    """登出——撤销 refresh token。"""
    service = AuthService(user_repo)
    await service.logout(credentials.credentials)
    return success(message="Logged out")


@router.post(
    "/wechat/login",
    response_model=None,
    responses=success_responses(TokenOut),
)
async def wechat_login(
    data: WeChatCodeRequest,
    request: Request,
    service: ExternalAuthService = Depends(get_external_auth_service),
) -> dict:
    """使用 wx.login 一次性 code 登录；首次自动创建普通用户。"""

    result = await service.login(
        code=data.code,
        ip_address=get_client_ip(request),
    )
    payload = TokenOut(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        user=UserOut.model_validate(result["user"]),
    )
    return success(data=payload.model_dump())


@router.post(
    "/wechat/bind",
    response_model=None,
    responses=success_responses(ExternalIdentityOut),
)
async def bind_wechat(
    data: WeChatCodeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: ExternalAuthService = Depends(get_external_auth_service),
) -> dict:
    """把当前普通用户显式绑定到微信身份。"""

    identity = await service.bind(
        user=current_user,
        code=data.code,
        ip_address=get_client_ip(request),
    )
    payload = ExternalIdentityOut(
        provider="wechat_miniprogram",
        bound_at=identity.created_at,
    )
    return success(data=payload.model_dump())


@router.delete(
    "/wechat/bind",
    response_model=None,
    responses=success_responses(type(None)),
)
async def unbind_wechat(
    data: WeChatUnbindRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: ExternalAuthService = Depends(get_external_auth_service),
) -> dict:
    """密码二次验证后解绑微信，并撤销已有会话。"""

    await service.unbind_wechat(
        user=current_user,
        password=data.password,
        ip_address=get_client_ip(request),
    )
    return success(message="WeChat identity unbound")


@router.get(
    "/identities",
    response_model=None,
    responses=success_responses(ExternalIdentityListOut),
)
async def list_external_identities(
    current_user: User = Depends(get_current_user),
    service: ExternalAuthService = Depends(get_external_auth_service),
) -> dict:
    """返回不含 OpenID/UnionID 的当前用户绑定摘要。"""

    identities = await service.list_identities(current_user.id)
    payload = ExternalIdentityListOut(
        items=[
            ExternalIdentityOut(
                provider="wechat_miniprogram",
                bound_at=identity.created_at,
            )
            for identity in identities
        ]
    )
    return success(data=payload.model_dump())
