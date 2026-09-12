"""数据库连接配置契约测试。"""

from typing import Any

import pytest
from fastapi import FastAPI

import app.db.database as database_module
from app.core.config import settings
from app.db.database import _get_db_config, init_db


def test_sqlite_database_config_uses_development_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite 配置应使用显式开发文件路径并注册全部 Model。"""

    monkeypatch.setattr(settings, "db_engine", "sqlite")
    monkeypatch.setattr(settings, "db_sqlite_path", "./contract.sqlite3")

    config = _get_db_config()

    assert config["connections"]["default"] == "sqlite://./contract.sqlite3"
    assert config["apps"]["models"] == {
        "models": ["app.models", "aerich.models"],
        "default_connection": "default",
    }


def test_mysql_database_config_preserves_reserved_password_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """结构化 credentials 不应把密码中的 URL 保留字符误解析为地址。"""

    monkeypatch.setattr(settings, "db_engine", "mysql")
    monkeypatch.setattr(settings, "db_host", "mysql.internal")
    monkeypatch.setattr(settings, "db_port", 3307)
    monkeypatch.setattr(settings, "db_user", "pinkdoo")
    monkeypatch.setattr(settings, "db_password", "p@ss:word/with#chars")
    monkeypatch.setattr(settings, "db_name", "pinkdoohub")

    config = _get_db_config()
    connection = config["connections"]["default"]

    assert connection["engine"] == "tortoise.backends.mysql"
    assert connection["credentials"] == {
        "host": "mysql.internal",
        "port": 3307,
        "user": "pinkdoo",
        "password": "p@ss:word/with#chars",
        "database": "pinkdoohub",
    }


@pytest.mark.parametrize(
    ("app_env", "expected_generate_schemas"),
    [
        ("development", True),
        ("testing", False),
        ("production", False),
    ],
)
def test_init_db_only_generates_schemas_in_development(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
    expected_generate_schemas: bool,
) -> None:
    """生产和测试环境不得在应用启动时隐式修改数据库结构。"""

    captured: dict[str, Any] = {}

    def capture_registration(app: FastAPI, **kwargs: Any) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(settings, "app_env", app_env)
    monkeypatch.setattr(database_module, "register_tortoise", capture_registration)
    app = FastAPI()

    init_db(app)

    assert captured["app"] is app
    assert captured["generate_schemas"] is expected_generate_schemas
