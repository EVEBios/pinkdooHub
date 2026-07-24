"""应用配置。

从 .env 文件和环境变量读取配置，提供默认值。
Phase 1 仅包含最基础的配置项，后续阶段按需扩展。
"""

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """应用配置（单例）。

    配置读取优先级：环境变量 > .env 文件 > 默认值
    """

    # ── 应用 ──────────────────────────────────
    app_name: str
    app_version: str
    app_env: str
    app_debug: bool

    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "pinkdooHub")
        self.app_version = os.getenv("APP_VERSION", "0.0.0")
        self.app_env = os.getenv("APP_ENV", "development")
        self.app_debug = os.getenv("APP_DEBUG", "true").lower() == "true"


settings = Settings()
