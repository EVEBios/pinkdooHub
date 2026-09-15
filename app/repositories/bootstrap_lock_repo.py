"""首个管理员初始化所需的数据库互斥锁适配。"""

import asyncio

from tortoise.backends.base.client import BaseDBAsyncClient

from app.common.constants.bootstrap import SUPER_ADMIN_BOOTSTRAP_LOCK_NAME


class BootstrapLockRepository:
    """封装进程内互斥与 MySQL session advisory lock。

    进程锁负责同一应用进程以及 SQLite 开发/测试；production 强制 MySQL，
    再由数据库锁覆盖多个命令进程或应用实例。
    """

    _process_lock: asyncio.Lock | None = None
    _process_lock_loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def _get_process_lock(cls) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if cls._process_lock is None or cls._process_lock_loop is not loop:
            cls._process_lock = asyncio.Lock()
            cls._process_lock_loop = loop
        return cls._process_lock

    async def acquire_process_lock(self, timeout_seconds: int) -> bool:
        """在当前进程内串行化初始化尝试。"""

        try:
            await asyncio.wait_for(
                self._get_process_lock().acquire(),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return False
        return True

    def release_process_lock(self) -> None:
        """释放当前进程的初始化互斥锁。"""

        lock = self._get_process_lock()
        if lock.locked():
            lock.release()

    async def acquire_database_lock(
        self,
        *,
        using_db: BaseDBAsyncClient,
        timeout_seconds: int,
    ) -> bool:
        """MySQL 使用命名锁；SQLite 由进程锁提供本地串行化。"""

        dialect = using_db.capabilities.dialect
        if dialect == "sqlite":
            return True
        if dialect != "mysql":
            raise RuntimeError(f"Unsupported bootstrap database dialect: {dialect}")

        rows = await using_db.execute_query_dict(
            "SELECT GET_LOCK(%s, %s) AS acquired",
            [SUPER_ADMIN_BOOTSTRAP_LOCK_NAME, timeout_seconds],
        )
        return bool(rows and rows[0].get("acquired") == 1)

    async def release_database_lock(
        self,
        *,
        using_db: BaseDBAsyncClient,
    ) -> None:
        """在事务连接归还连接池前释放 MySQL 命名锁。"""

        if using_db.capabilities.dialect != "mysql":
            return
        rows = await using_db.execute_query_dict(
            "SELECT RELEASE_LOCK(%s) AS released",
            [SUPER_ADMIN_BOOTSTRAP_LOCK_NAME],
        )
        if not rows or rows[0].get("released") != 1:
            raise RuntimeError("SUPER_ADMIN bootstrap database lock was not released")
