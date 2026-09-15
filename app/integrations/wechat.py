"""微信小程序 code2Session 适配器。"""

from dataclasses import dataclass
import logging
from typing import Protocol

import httpx

from app.common.exceptions.user import ExternalIdentityInvalid
from app.core.config import settings
from app.core.exceptions import ServiceUnavailableException
from app.core.security_events import emit_security_event

WECHAT_PROVIDER = "wechat_miniprogram"
_CODE_TO_SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExternalIdentityCredentials:
    """平台换取后的最小身份集，不包含 session_key。"""

    provider: str
    app_id: str
    subject_id: str
    union_id: str | None = None


class ExternalIdentityProvider(Protocol):
    async def exchange_code(self, code: str) -> ExternalIdentityCredentials:
        """消费一次性 code 并返回最小平台身份。"""


class WeChatMiniProgramProvider:
    """通过微信官方 code2Session 换取 OpenID/UnionID。"""

    @property
    def app_id(self) -> str:
        return settings.wechat_app_id

    async def exchange_code(self, code: str) -> ExternalIdentityCredentials:
        if not settings.wechat_login_enabled:
            raise ServiceUnavailableException(message="WeChat login is not enabled")
        try:
            async with httpx.AsyncClient(
                timeout=settings.wechat_api_timeout_seconds,
            ) as client:
                response = await client.get(
                    _CODE_TO_SESSION_URL,
                    params={
                        "appid": settings.wechat_app_id,
                        "secret": settings.wechat_app_secret,
                        "js_code": code,
                        "grant_type": "authorization_code",
                    },
                )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as error:
            emit_security_event(
                "wechat_identity_exchange",
                "unavailable",
                level=logging.ERROR,
                scope=WECHAT_PROVIDER,
            )
            raise ServiceUnavailableException(
                message="WeChat identity service temporarily unavailable"
            ) from error

        if not isinstance(payload, dict) or payload.get("errcode") not in (None, 0):
            emit_security_event(
                "wechat_identity_exchange",
                "rejected",
                level=logging.WARNING,
                scope=WECHAT_PROVIDER,
            )
            raise ExternalIdentityInvalid()
        subject_id = payload.get("openid")
        union_id = payload.get("unionid")
        if not isinstance(subject_id, str) or not 1 <= len(subject_id) <= 128:
            raise ExternalIdentityInvalid()
        if union_id is not None and (
            not isinstance(union_id, str) or not 1 <= len(union_id) <= 128
        ):
            raise ExternalIdentityInvalid()
        return ExternalIdentityCredentials(
            provider=WECHAT_PROVIDER,
            app_id=settings.wechat_app_id,
            subject_id=subject_id,
            union_id=union_id,
        )
