"""复用已核验的隔离 MySQL 连接门槛；绝不自动建/改持久 Schema。"""
from tests.reservation.mysql.conftest import setup_db  # noqa: F401
