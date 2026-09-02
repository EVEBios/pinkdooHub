"""Phase 9.2 生产环境启动配置契约。"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


PRODUCTION_SETTINGS: dict[str, Any] = {
    "app_env": "production",
    "app_debug": False,
    "db_engine": "mysql",
    "jwt_algorithm": "HS256",
    "jwt_secret_key": "a-strong-production-secret-with-32-chars",
    "redis_url": "rediss://cache.internal:6380/0",
    "product_image_base_url": "https://cdn.example.com/products",
}


def _build_production_settings(**overrides: Any) -> Settings:
    values = {**PRODUCTION_SETTINGS, **overrides}
    return Settings(_env_file=None, **values)


def test_production_settings_accept_the_frozen_secure_contract() -> None:
    settings = _build_production_settings()

    assert settings.app_env == "production"
    assert settings.app_debug is False
    assert settings.db_engine == "mysql"


def test_development_settings_keep_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.app_debug is True
    assert settings.db_engine == "sqlite"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.product_image_base_url == "/uploads/products"


@pytest.mark.parametrize(
    ("overrides", "error_message"),
    [
        ({"app_debug": True}, "APP_DEBUG must be false"),
        ({"db_engine": "sqlite"}, "DB_ENGINE must be mysql"),
        ({"jwt_algorithm": "HS512"}, "JWT_ALGORITHM must be HS256"),
        ({"jwt_secret_key": "short-secret"}, "at least 32"),
        ({"redis_url": "http://cache.internal/0"}, "redis or rediss"),
        ({"redis_url": "redis://localhost:6379/0"}, "non-loopback host"),
        ({"redis_url": "redis://cache.localhost:6379/0"}, "non-loopback host"),
        ({"redis_url": "redis://127.0.0.1:6379/0"}, "non-loopback host"),
        ({"redis_url": "redis://0.0.0.0:6379/0"}, "non-loopback host"),
        ({"redis_url": "redis://[::1]:6379/0"}, "non-loopback host"),
        ({"redis_url": "redis:///0"}, "non-loopback host"),
        (
            {"product_image_base_url": "http://cdn.example.com/products"},
            "absolute HTTPS URL",
        ),
        (
            {"product_image_base_url": "https://user:pass@cdn.example.com/products"},
            "must not include credentials",
        ),
    ],
)
def test_production_settings_reject_unsafe_values(
    overrides: dict[str, Any],
    error_message: str,
) -> None:
    with pytest.raises(ValidationError, match=error_message):
        _build_production_settings(**overrides)


def test_production_validation_error_does_not_echo_sensitive_input() -> None:
    sensitive_value = "do-not-echo-this-production-secret"

    with pytest.raises(ValidationError) as error:
        _build_production_settings(
            redis_url=f"http://operator:{sensitive_value}@cache.internal/0",
            jwt_secret_key=sensitive_value,
        )

    assert sensitive_value not in str(error.value)


def test_production_wechat_login_requires_server_only_identity_secrets() -> None:
    settings = _build_production_settings(
        wechat_login_enabled=True,
        wechat_app_id="wx-public-id",
        wechat_app_secret="server-only-wechat-secret",
        external_identity_pepper="stable-identity-pepper-with-at-least-32-chars",
    )

    assert settings.wechat_login_enabled is True

    for overrides, message in [
        ({"wechat_app_id": ""}, "WECHAT_APP_ID"),
        ({"wechat_app_secret": ""}, "WECHAT_APP_SECRET"),
        ({"external_identity_pepper": "short"}, "EXTERNAL_IDENTITY_PEPPER"),
    ]:
        with pytest.raises(ValidationError, match=message):
            values = {
                "wechat_login_enabled": True,
                "wechat_app_id": "wx-public-id",
                "wechat_app_secret": "server-only-wechat-secret",
                "external_identity_pepper": (
                    "stable-identity-pepper-with-at-least-32-chars"
                ),
                **overrides,
            }
            _build_production_settings(
                **values,
            )
