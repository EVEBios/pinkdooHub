"""应用配置。

通过 pydantic-settings 从 .env 文件和环境变量读取配置。
环境变量优先级高于 .env 文件。

全项目通过 `from app.core.config import settings` 使用同一个实例。
"""

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

# 开发环境默认密钥——生产环境必须用环境变量覆盖
_DEV_JWT_SECRET = "dev-secret-change-in-production"
_UNSAFE_JWT_VALUES = {"", _DEV_JWT_SECRET, "change-me"}

# .env 路径 —— 从 config.py 位置推导项目根目录
_ENV_FILE = str(Path(__file__).resolve().parent.parent.parent / ".env")


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

    model_config = {
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
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

        # ── JWT 密钥（仅生产环境）──────────────
        if self.app_env == "production":
            if self.jwt_secret_key in _UNSAFE_JWT_VALUES:
                raise ValueError(
                    "JWT_SECRET_KEY must be set to a strong random string "
                    "in production. Use `openssl rand -hex 32` to generate one."
                )

        return self


settings = Settings()
