"""Phase 9.5 公开身份、Token 轮换、限流与注销契约。"""

import asyncio
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.api.deps import get_account_lifecycle_service, get_external_auth_service
from app.integrations.wechat import ExternalIdentityCredentials
from app.main import app
from app.models.external_identity import ExternalIdentity
from app.models.order import Order
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.external_identity_repo import ExternalIdentityRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.user_repo import UserRepository
from app.services.account_lifecycle_service import AccountLifecycleService
from app.services.audit_log_service import AuditLogService
from app.services.external_auth_service import ExternalAuthService


class FakeWeChatProvider:
    def __init__(
        self,
        subject_id: str = "openid-test-user",
        *,
        union_id: str | None = "unionid-test-user",
        app_id: str = "wx-test-app",
    ) -> None:
        self.subject_id = subject_id
        self.union_id = union_id
        self.app_id = app_id

    async def exchange_code(self, code: str) -> ExternalIdentityCredentials:
        assert code
        return ExternalIdentityCredentials(
            provider="wechat_miniprogram",
            app_id=self.app_id,
            subject_id=self.subject_id,
            union_id=self.union_id,
        )


def _external_service(provider: FakeWeChatProvider) -> ExternalAuthService:
    return ExternalAuthService(
        UserRepository(),
        ExternalIdentityRepository(),
        AuditLogService(AuditLogRepository()),
        provider,
    )


def _account_service(provider: FakeWeChatProvider) -> AccountLifecycleService:
    return AccountLifecycleService(
        UserRepository(),
        OrderRepository(),
        ExternalIdentityRepository(),
        AuditLogService(AuditLogRepository()),
        provider,
    )


async def _register_and_login(
    client: AsyncClient,
    *,
    username: str = "phase95user",
    phone: str = "13800000951",
) -> dict:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "12345678",
            "nickname": "Phase 9.5",
            "phone": phone,
        },
    )
    assert registered.status_code == 201, registered.text
    logged_in = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "12345678"},
    )
    assert logged_in.status_code == 200, logged_in.text
    return logged_in.json()["data"]


async def test_refresh_rotates_both_tokens_and_reuse_revokes_family(
    client: AsyncClient,
) -> None:
    login = await _register_and_login(client)

    rotated = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    assert rotated.status_code == 200, rotated.text
    rotated_data = rotated.json()["data"]
    assert rotated_data["access_token"] != login["access_token"]
    assert rotated_data["refresh_token"] != login["refresh_token"]

    reuse = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": login["refresh_token"]},
    )
    family_after_reuse = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated_data["refresh_token"]},
    )
    assert (reuse.status_code, reuse.json()["code"]) == (400, 1006)
    assert (family_after_reuse.status_code, family_after_reuse.json()["code"]) == (
        400,
        1006,
    )


async def test_refresh_rate_limit_follows_ip_across_rotated_tokens(
    client: AsyncClient,
) -> None:
    login = await _register_and_login(client)
    refresh_token = login["refresh_token"]

    for _attempt in range(30):
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200, response.text
        refresh_token = response.json()["data"]["refresh_token"]

    limited = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert (limited.status_code, limited.json()["code"]) == (429, 42901)


async def test_concurrent_refresh_allows_one_rotation_and_revokes_family(
    client: AsyncClient,
) -> None:
    login = await _register_and_login(client)
    request = {"refresh_token": login["refresh_token"]}

    first, second = await asyncio.gather(
        client.post("/api/v1/auth/refresh", json=request),
        client.post("/api/v1/auth/refresh", json=request),
    )

    assert sorted(response.status_code for response in (first, second)) == [200, 400]
    successful = first if first.status_code == 200 else second
    rejected = second if first.status_code == 200 else first
    assert rejected.json()["code"] == 1006

    family_after_reuse = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": successful.json()["data"]["refresh_token"]},
    )
    assert (family_after_reuse.status_code, family_after_reuse.json()["code"]) == (
        400,
        1006,
    )


async def test_login_rate_limit_returns_uniform_429_without_echoing_subject(
    client: AsyncClient,
) -> None:
    for _attempt in range(8):
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "rate-limited-user", "password": "not-a-secret"},
        )
        assert response.status_code == 400

    limited = await client.post(
        "/api/v1/auth/login",
        json={"username": "rate-limited-user", "password": "not-a-secret"},
    )
    assert (limited.status_code, limited.json()["code"]) == (429, 42901)
    assert "rate-limited-user" not in limited.text


async def test_password_login_does_not_enumerate_missing_or_wechat_only_users(
    client: AsyncClient,
) -> None:
    password_login = await _register_and_login(client)
    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"username": password_login["user"]["username"], "password": "wrong"},
    )
    missing_user = await client.post(
        "/api/v1/auth/login",
        json={"username": "missing-user", "password": "wrong"},
    )

    provider = FakeWeChatProvider(subject_id="openid-enumeration", union_id=None)
    app.dependency_overrides[get_external_auth_service] = lambda: _external_service(provider)
    try:
        wechat_login = await client.post(
            "/api/v1/auth/wechat/login",
            json={"code": "wechat-code"},
        )
    finally:
        app.dependency_overrides.pop(get_external_auth_service, None)
    wechat_only = await client.post(
        "/api/v1/auth/login",
        json={
            "username": wechat_login.json()["data"]["user"]["username"],
            "password": "wrong",
        },
    )

    for response in (wrong_password, missing_user, wechat_only):
        assert (response.status_code, response.json()["code"]) == (400, 1003)
        assert response.json()["message"] == "Incorrect password"


async def test_wechat_first_login_auto_creates_passwordless_user_and_reuses_binding(
    client: AsyncClient,
) -> None:
    provider = FakeWeChatProvider()
    app.dependency_overrides[get_external_auth_service] = lambda: _external_service(provider)
    try:
        first = await client.post(
            "/api/v1/auth/wechat/login",
            json={"code": "one-time-code"},
        )
        second = await client.post(
            "/api/v1/auth/wechat/login",
            json={"code": "another-one-time-code"},
        )
    finally:
        app.dependency_overrides.pop(get_external_auth_service, None)

    assert first.status_code == second.status_code == 200
    first_user = first.json()["data"]["user"]
    second_user = second.json()["data"]["user"]
    assert first_user["id"] == second_user["id"]
    assert first_user["username"].startswith("wx_")
    assert first_user["phone"] is None
    assert "openid" not in first.text.lower()
    assert "unionid" not in first.text.lower()

    user = await UserRepository().get_by_id(first_user["id"])
    assert user is not None
    assert user.password is None
    identity = await ExternalIdentity.all().first()
    assert identity is not None
    assert identity.subject_id != provider.subject_id
    assert identity.union_id != provider.union_id
    assert len(identity.subject_id) == len(identity.union_id or "") == 64


async def test_existing_user_can_bind_list_and_password_unbind(
    client: AsyncClient,
) -> None:
    login = await _register_and_login(client)
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    provider = FakeWeChatProvider(subject_id="openid-bind", union_id="union-bind")
    app.dependency_overrides[get_external_auth_service] = lambda: _external_service(provider)
    try:
        bound = await client.post(
            "/api/v1/auth/wechat/bind",
            json={"code": "bind-code"},
            headers=headers,
        )
        listed = await client.get("/api/v1/auth/identities", headers=headers)
        unbound = await client.request(
            "DELETE",
            "/api/v1/auth/wechat/bind",
            json={"password": "12345678"},
            headers=headers,
        )
        old_access = await client.get("/api/v1/users/me", headers=headers)
    finally:
        app.dependency_overrides.pop(get_external_auth_service, None)

    assert bound.status_code == 200, bound.text
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["provider"] == "wechat_miniprogram"
    assert "openid" not in listed.text.lower()
    assert "union" not in listed.text.lower()
    assert unbound.status_code == 200
    assert (old_access.status_code, old_access.json()["code"]) == (400, 1006)
    assert await ExternalIdentity.all().count() == 0


async def test_wechat_identity_cannot_be_bound_to_two_users(
    client: AsyncClient,
) -> None:
    first = await _register_and_login(
        client,
        username="identityowner",
        phone="13800000961",
    )
    second = await _register_and_login(
        client,
        username="identityclaimant",
        phone="13800000962",
    )
    provider = FakeWeChatProvider(subject_id="openid-shared", union_id="union-shared")
    app.dependency_overrides[get_external_auth_service] = lambda: _external_service(provider)
    try:
        first_bind = await client.post(
            "/api/v1/auth/wechat/bind",
            json={"code": "owner-code"},
            headers={"Authorization": f"Bearer {first['access_token']}"},
        )
        conflicting_bind = await client.post(
            "/api/v1/auth/wechat/bind",
            json={"code": "claimant-code"},
            headers={"Authorization": f"Bearer {second['access_token']}"},
        )
    finally:
        app.dependency_overrides.pop(get_external_auth_service, None)

    assert first_bind.status_code == 200
    assert (conflicting_bind.status_code, conflicting_bind.json()["code"]) == (
        400,
        1012,
    )
    assert await ExternalIdentity.all().count() == 1


async def test_passwordless_wechat_user_cannot_unlink_only_login_method(
    client: AsyncClient,
) -> None:
    provider = FakeWeChatProvider(subject_id="openid-no-fallback", union_id=None)
    app.dependency_overrides[get_external_auth_service] = lambda: _external_service(provider)
    try:
        login = await client.post(
            "/api/v1/auth/wechat/login",
            json={"code": "login-code"},
        )
        token = login.json()["data"]["access_token"]
        response = await client.request(
            "DELETE",
            "/api/v1/auth/wechat/bind",
            json={"password": "unknown"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.pop(get_external_auth_service, None)

    assert (response.status_code, response.json()["code"]) == (400, 1014)


async def test_account_deletion_anonymizes_user_and_preserves_row(
    client: AsyncClient,
) -> None:
    login = await _register_and_login(client)
    user_id = login["user"]["id"]
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    provider = FakeWeChatProvider()
    app.dependency_overrides[get_account_lifecycle_service] = lambda: _account_service(
        provider
    )
    try:
        deleted = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"confirmation": "DELETE", "password": "12345678"},
            headers=headers,
        )
        old_access = await client.get("/api/v1/users/me", headers=headers)
    finally:
        app.dependency_overrides.pop(get_account_lifecycle_service, None)

    assert deleted.status_code == 200, deleted.text
    assert (old_access.status_code, old_access.json()["code"]) == (400, 1009)
    user = await UserRepository().get_by_id(user_id)
    assert user is not None
    assert user.status == 3
    assert user.username.startswith("deleted_")
    assert user.nickname == "已注销用户"
    assert user.password is user.phone is user.avatar is None
    assert user.deleted_at is not None


async def test_account_deletion_is_blocked_by_non_terminal_order(
    client: AsyncClient,
) -> None:
    login = await _register_and_login(client)
    user = await UserRepository().get_by_id(login["user"]["id"])
    assert user is not None
    await Order.create(
        order_no="OD00000000000000000000000000",
        user_id=user.id,
        total_amount=Decimal("1.00"),
    )
    app.dependency_overrides[get_account_lifecycle_service] = lambda: _account_service(
        FakeWeChatProvider()
    )
    try:
        response = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"confirmation": "DELETE", "password": "12345678"},
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
    finally:
        app.dependency_overrides.pop(get_account_lifecycle_service, None)

    assert (response.status_code, response.json()["code"]) == (400, 1015)
    await user.refresh_from_db()
    assert user.status == 1
    assert user.password is not None


@pytest.mark.parametrize("role", [2, 3])
async def test_privileged_accounts_cannot_bind_wechat_or_self_delete(
    client: AsyncClient,
    role: int,
) -> None:
    login = await _register_and_login(
        client,
        username=f"privileged{role}",
        phone=f"1380000095{role}",
    )
    user = await UserRepository().get_by_id(login["user"]["id"])
    assert user is not None
    user.role = role
    await user.save(update_fields=["role"])
    provider = FakeWeChatProvider(subject_id=f"openid-role-{role}", union_id=None)
    app.dependency_overrides[get_external_auth_service] = lambda: _external_service(provider)
    app.dependency_overrides[get_account_lifecycle_service] = lambda: _account_service(
        provider
    )
    try:
        bind_response = await client.post(
            "/api/v1/auth/wechat/bind",
            json={"code": "bind-code"},
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
        delete_response = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"confirmation": "DELETE", "password": "12345678"},
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
    finally:
        app.dependency_overrides.pop(get_external_auth_service, None)
        app.dependency_overrides.pop(get_account_lifecycle_service, None)

    assert bind_response.status_code == 403
    assert delete_response.status_code == 403
