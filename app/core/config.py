"""应用配置。

通过 pydantic-settings 从 .env 文件和环境变量读取配置。
环境变量优先级高于 .env 文件。

全项目通过 `from app.core.config import settings` 使用同一个实例。
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置。

    所有字段自动从 .env / 环境变量读取，pydantic-settings 负责类型转换。
    每个字段都有开发环境的合理默认值，生产环境通过环境变量覆盖。
    """

    # ═══════════════════════════════════════════════
    # 应用
    # ═══════════════════════════════════════════════
    app_name: str = "pinkdooHub"
    app_version: str = "0.1.0"
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

    # ═══════════════════════════════════════════════
    # JWT
    # ═══════════════════════════════════════════════
    jwt_secret_key: str = ""            # 生产环境必须设置为强随机字符串
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire: int = 7200     # 2 小时
    jwt_refresh_token_expire: int = 604800   # 7 天

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
