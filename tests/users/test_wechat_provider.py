"""微信 code2Session 基础设施适配器契约。"""

import logging

import pytest

from app.common.exceptions.user import ExternalIdentityInvalid
from app.core.config import settings
from app.integrations import wechat
from app.integrations.wechat import WeChatMiniProgramProvider


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _Client:
    payload: object = {}
    requests: list[dict[str, object]] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, *, params: dict[str, str]) -> _Response:
        self.requests.append({"url": url, "params": params})
        return _Response(self.payload)


@pytest.fixture(autouse=True)
def _wechat_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "wechat_login_enabled", True)
    monkeypatch.setattr(settings, "wechat_app_id", "wx-test-app")
    monkeypatch.setattr(settings, "wechat_app_secret", "wechat-server-only-secret")
    monkeypatch.setattr(wechat.httpx, "AsyncClient", _Client)
    _Client.requests = []


async def test_code2session_returns_only_minimum_identity_fields() -> None:
    _Client.payload = {
        "openid": "platform-openid",
        "unionid": "platform-unionid",
        "session_key": "must-not-cross-provider-boundary",
    }

    credentials = await WeChatMiniProgramProvider().exchange_code("one-time-code")

    assert credentials.provider == "wechat_miniprogram"
    assert credentials.app_id == "wx-test-app"
    assert credentials.subject_id == "platform-openid"
    assert credentials.union_id == "platform-unionid"
    assert not hasattr(credentials, "session_key")
    request = _Client.requests[0]
    assert request["url"] == "https://api.weixin.qq.com/sns/jscode2session"
    assert request["params"] == {
        "appid": "wx-test-app",
        "secret": "wechat-server-only-secret",
        "js_code": "one-time-code",
        "grant_type": "authorization_code",
    }


async def test_platform_rejection_emits_only_stable_security_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _Client.payload = {
        "errcode": 40029,
        "errmsg": "invalid code containing-sensitive-upstream-detail",
    }
    caplog.set_level(logging.WARNING, logger="app.security")

    with pytest.raises(ExternalIdentityInvalid):
        await WeChatMiniProgramProvider().exchange_code("sensitive-one-time-code")

    logs = caplog.text
    assert "security_event=wechat_identity_exchange outcome=rejected" in logs
    assert "sensitive-one-time-code" not in logs
    assert "containing-sensitive-upstream-detail" not in logs
