"""应用配置。

通过 pydantic-settings 从 .env 文件和环境变量读取配置。
环境变量优先级高于 .env 文件。

全项目通过 `from app.core.config import settings` 使用同一个实例。
"""

from ipaddress import ip_address
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings

# 开发环境默认密钥——生产环境必须用环境变量覆盖
_DEV_JWT_SECRET = "dev-secret-change-in-production"
_DEV_EXTERNAL_IDENTITY_PEPPER = "dev-external-identity-pepper-change-in-production"
_UNSAFE_JWT_VALUES = {"", _DEV_JWT_SECRET, "change-me"}

# .env 路径 —— 从 config.py 位置推导项目根目录
_ENV_FILE = str(Path(__file__).resolve().parent.parent.parent / ".env")


def _parse_url(value: str, setting_name: str) -> SplitResult:
    """解析 URL，并将解析失败转换为不包含原值的配置错误。"""

    try:
        parsed = urlsplit(value)
        # 访问 port 才会触发非法端口格式校验。
        parsed.port
    except ValueError as error:
        raise ValueError(f"{setting_name} must be a valid URL") from error
    return parsed


def _is_local_redis_host(host: str) -> bool:
    """判断 Redis host 是否为本机回环或未指定地址。"""

    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        return True

    try:
        address = ip_address(normalized_host)
    except ValueError:
        return False

    if address.is_loopback or address.is_unspecified:
        return True
    if address.version == 6:
        mapped_address = address.ipv4_mapped
        return bool(mapped_address and mapped_address.is_loopback)
    return False


class Settings(BaseSettings):
    """应用配置。

    所有字段自动从 .env / 环境变量读取，pydantic-settings 负责类型转换。
    每个字段都有开发环境的合理默认值，生产环境通过环境变量覆盖。
    """

    # ═══════════════════════════════════════════════
    # 应用
    # ═══════════════════════════════════════════════
    app_name: str = "pinkdooHub"
    app_version: str = "0.6.0"
    app_env: str = "development"
    app_debug: bool = True

    # ═══════════════════════════════════════════════
    # 数据库
    # ═══════════════════════════════════════════════
    db_engine: str = "sqlite"          # sqlite | mysql
    db_sqlite_path: str = "./db.sqlite3"
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "pinkdoohub"

    # ═══════════════════════════════════════════════
    # Redis
    # ═══════════════════════════════════════════════
    redis_url: str = "redis://localhost:6379/0"

    # ═══════════════════════
    # 本地图片存储
    # ═══════════════════════
    product_image_upload_dir: str = "./uploads/products"
    product_image_base_url: str = "/uploads/products"

    # ═══════════════════════════════════════════════
    # JWT
    # ═══════════════════════════════════════════════
    jwt_secret_key: str = _DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire: int = 7200     # 2 小时
    jwt_refresh_token_expire: int = 604800   # 7 天

    # ═══════════════════════
    # Phase 9.5 公开身份与认证安全
    # ═══════════════════════
    password_registration_enabled: bool = True
    wechat_login_enabled: bool = False
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    external_identity_pepper: str = _DEV_EXTERNAL_IDENTITY_PEPPER
    wechat_api_timeout_seconds: float = 5.0

    auth_login_ip_limit: int = 20
    auth_login_subject_limit: int = 8
    auth_login_window_seconds: int = 300
    auth_register_ip_limit: int = 5
    auth_register_window_seconds: int = 3600
    auth_refresh_limit: int = 30
    auth_refresh_window_seconds: int = 60
    auth_wechat_login_limit: int = 10
    auth_wechat_login_window_seconds: int = 300
    auth_wechat_bind_limit: int = 5
    auth_wechat_bind_window_seconds: int = 600

    model_config = {
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "hide_input_in_errors": True,
    }

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        """配置合法性校验。

        在 .env 加载完毕后执行，检查所有配置项是否合法。
        越早发现配置错误越好——不要等到运行时报错。
        """

        # ── 环境名 ────────────────────────────
        if self.app_env not in ("development", "testing", "production"):
            raise ValueError(
                f"APP_ENV must be development/testing/production, got '{self.app_env}'"
            )

        # ── 数据库引擎 ────────────────────────
        if self.db_engine not in ("sqlite", "mysql"):
            raise ValueError(
                f"DB_ENGINE must be sqlite or mysql, got '{self.db_engine}'"
            )

        if self.wechat_login_enabled:
            if not self.wechat_app_id.strip():
                raise ValueError("WECHAT_APP_ID is required when WeChat login is enabled")
            if not self.wechat_app_secret.strip():
                raise ValueError(
                    "WECHAT_APP_SECRET is required when WeChat login is enabled"
                )
            normalized_pepper = self.external_identity_pepper.strip()
            if (
                self.app_env == "production"
                and (
                    normalized_pepper == _DEV_EXTERNAL_IDENTITY_PEPPER
                    or len(normalized_pepper) < 32
                )
            ):
                raise ValueError(
                    "EXTERNAL_IDENTITY_PEPPER must contain at least 32 "
                    "non-padding characters in production"
                )
        if not 0.5 <= self.wechat_api_timeout_seconds <= 30:
            raise ValueError("WECHAT_API_TIMEOUT_SECONDS must be between 0.5 and 30")

        positive_limits = {
            "AUTH_LOGIN_IP_LIMIT": self.auth_login_ip_limit,
            "AUTH_LOGIN_SUBJECT_LIMIT": self.auth_login_subject_limit,
            "AUTH_LOGIN_WINDOW_SECONDS": self.auth_login_window_seconds,
            "AUTH_REGISTER_IP_LIMIT": self.auth_register_ip_limit,
            "AUTH_REGISTER_WINDOW_SECONDS": self.auth_register_window_seconds,
            "AUTH_REFRESH_LIMIT": self.auth_refresh_limit,
            "AUTH_REFRESH_WINDOW_SECONDS": self.auth_refresh_window_seconds,
            "AUTH_WECHAT_LOGIN_LIMIT": self.auth_wechat_login_limit,
            "AUTH_WECHAT_LOGIN_WINDOW_SECONDS": self.auth_wechat_login_window_seconds,
            "AUTH_WECHAT_BIND_LIMIT": self.auth_wechat_bind_limit,
            "AUTH_WECHAT_BIND_WINDOW_SECONDS": self.auth_wechat_bind_window_seconds,
        }
        for name, value in positive_limits.items():
            if value < 1:
                raise ValueError(f"{name} must be positive")

        # ── 生产环境启动契约 ──────────────────
        if self.app_env == "production":
            if self.app_debug:
                raise ValueError("APP_DEBUG must be false in production")

            if self.db_engine != "mysql":
                raise ValueError("DB_ENGINE must be mysql in production")

            if self.jwt_algorithm != "HS256":
                raise ValueError("JWT_ALGORITHM must be HS256 in production")

            normalized_secret = self.jwt_secret_key.strip()
            if (
                normalized_secret in _UNSAFE_JWT_VALUES
                or len(normalized_secret) < 32
            ):
                raise ValueError(
                    "JWT_SECRET_KEY must contain at least 32 non-padding characters "
                    "in production. Use `openssl rand -hex 32` to generate one."
                )

            redis_url = _parse_url(self.redis_url, "REDIS_URL")
            if redis_url.scheme not in ("redis", "rediss"):
                raise ValueError(
                    "REDIS_URL scheme must be redis or rediss in production"
                )
            if not redis_url.hostname or _is_local_redis_host(redis_url.hostname):
                raise ValueError("REDIS_URL must use a non-loopback host in production")

            image_base_url = _parse_url(
                self.product_image_base_url,
                "PRODUCT_IMAGE_BASE_URL",
            )
            if image_base_url.scheme != "https" or not image_base_url.hostname:
                raise ValueError(
                    "PRODUCT_IMAGE_BASE_URL must be an absolute HTTPS URL "
                    "in production"
                )
            if (
                image_base_url.username is not None
                or image_base_url.password is not None
            ):
                raise ValueError(
                    "PRODUCT_IMAGE_BASE_URL must not include credentials in production"
                )

        return self


settings = Settings()
