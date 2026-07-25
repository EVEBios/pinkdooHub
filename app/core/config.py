"""应用配置。

从 .env 文件和环境变量读取配置，提供开发默认值。

配置读取优先级：环境变量 > .env 文件 > 默认值

架构：
    .env            ← 开发者私有，不入 git（含密钥）
    .env.example    ← 配置模板，提交到 git（无密钥）
    config.py       ← Settings 单例，全项目通过 settings.xxx 使用
"""

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """应用配置（单例）。

    所有配置项按分组组织。每个字段都有开发环境的合理默认值，
    生产环境通过环境变量覆盖。
    """

    # ═══════════════════════════════════════════════
    # 应用
    # ═══════════════════════════════════════════════
    app_name: str
    app_version: str
    app_env: str
    app_debug: bool

    # ═══════════════════════════════════════════════
    # 数据库
    # ═══════════════════════════════════════════════
    db_engine: str          # sqlite | mysql
    db_sqlite_path: str     # SQLite 文件路径
    db_host: str            # MySQL 主机
    db_port: int            # MySQL 端口
    db_user: str            # MySQL 用户
    db_password: str        # MySQL 密码
    db_name: str            # MySQL 库名

    # ═══════════════════════════════════════════════
    # Redis
    # ═══════════════════════════════════════════════
    redis_url: str

    # ═══════════════════════════════════════════════
    # JWT
    # ═══════════════════════════════════════════════
    jwt_secret_key: str     # 生产环境必须设置为强随机字符串
    jwt_algorithm: str
    jwt_access_token_expire: int    # 秒
    jwt_refresh_token_expire: int   # 秒

    def __init__(self) -> None:
        # ── 应用 ──────────────────────────────
        self.app_name = os.getenv("APP_NAME", "pinkdooHub")
        self.app_version = os.getenv("APP_VERSION", "0.0.0")
        self.app_env = os.getenv("APP_ENV", "development")
        self.app_debug = os.getenv("APP_DEBUG", "true").lower() == "true"

        # ── 数据库 ────────────────────────────
        self.db_engine = os.getenv("DB_ENGINE", "sqlite")
        self.db_sqlite_path = os.getenv("DB_SQLITE_PATH", "./db.sqlite3")
        self.db_host = os.getenv("DB_HOST", "127.0.0.1")
        self.db_port = int(os.getenv("DB_PORT", "3306"))
        self.db_user = os.getenv("DB_USER", "root")
        self.db_password = os.getenv("DB_PASSWORD", "")
        self.db_name = os.getenv("DB_NAME", "pinkdoohub")

        # ── Redis ─────────────────────────────
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # ── JWT ───────────────────────────────
        self.jwt_secret_key = os.getenv("JWT_SECRET_KEY", "")
        self.jwt_algorithm = os.getenv("JWT_ALGORITHM", "HS256")
        self.jwt_access_token_expire = int(
            os.getenv("JWT_ACCESS_TOKEN_EXPIRE", "7200")
        )
        self.jwt_refresh_token_expire = int(
            os.getenv("JWT_REFRESH_TOKEN_EXPIRE", "604800")
        )


settings = Settings()
