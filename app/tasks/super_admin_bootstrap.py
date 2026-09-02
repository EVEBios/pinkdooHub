"""安全、幂等地初始化首个 SUPER_ADMIN。

密码只从 ``PINKDOOHUB_BOOTSTRAP_PASSWORD`` 或交互式隐藏输入读取；命令
故意不提供 ``--password`` 参数，避免 Secret 进入 shell history 或进程列表。
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys

from pydantic import ValidationError
from tortoise import Tortoise

from app.common.constants.bootstrap import SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV
from app.core.logging import setup_logging
from app.db.database import TORTOISE_ORM
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.bootstrap_lock_repo import BootstrapLockRepository
from app.repositories.user_repo import UserRepository
from app.schemas.user import UserCreate
from app.services.audit_log_service import AuditLogService
from app.services.super_admin_bootstrap_service import (
    SuperAdminBootstrapResult,
    SuperAdminBootstrapService,
)

logger = logging.getLogger(__name__)


class SecureArgumentParser(argparse.ArgumentParser):
    """拒绝参数时不回显可能被误放在命令行中的 Secret。"""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: invalid arguments\n")


def build_parser() -> argparse.ArgumentParser:
    """构造不接受明文密码参数的 CLI。"""

    parser = SecureArgumentParser(
        description="Create the first SUPER_ADMIN exactly once.",
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--nickname", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Required confirmation that this command may write the database.",
    )
    return parser


def read_password() -> str:
    """优先读取受控环境变量，否则只在 TTY 中交互读取两次。"""

    password = os.environ.get(SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV)
    if password is not None:
        return password
    if not sys.stdin.isatty():
        raise RuntimeError(
            f"{SUPER_ADMIN_BOOTSTRAP_PASSWORD_ENV} is required in non-interactive mode"
        )
    password = getpass.getpass("Bootstrap password: ")
    confirmation = getpass.getpass("Confirm bootstrap password: ")
    if password != confirmation:
        raise RuntimeError("Bootstrap password confirmation does not match")
    return password


def validate_input(
    *,
    username: str,
    password: str,
    nickname: str,
    phone: str,
) -> UserCreate:
    """复用注册字段契约；调用方不得输出 ValidationError 的 input。"""

    return UserCreate(
        username=username,
        password=password,
        nickname=nickname,
        phone=phone,
    )


async def run(data: UserCreate) -> SuperAdminBootstrapResult:
    """初始化 ORM，并通过正式 Service 执行一次性写入。"""

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        service = SuperAdminBootstrapService(
            UserRepository(),
            AuditLogService(AuditLogRepository()),
            BootstrapLockRepository(),
        )
        return await service.bootstrap(
            username=data.username,
            password=data.password,
            nickname=data.nickname,
            phone=data.phone,
        )
    finally:
        await Tortoise.close_connections()


def _safe_validation_summary(error: ValidationError) -> str:
    """只输出字段位置和错误类型，不回显输入值。"""

    return ", ".join(
        f"{'.'.join(str(part) for part in item['loc'])}:{item['type']}"
        for item in error.errors()
    )


def main() -> int:
    """命令入口；所有失败输出都避免用户名、手机号和密码。"""

    args = build_parser().parse_args()
    setup_logging()
    if not args.apply:
        logger.error("SUPER_ADMIN bootstrap refused: --apply is required")
        return 2

    try:
        password = read_password()
        data = validate_input(
            username=args.username,
            password=password,
            nickname=args.nickname,
            phone=args.phone,
        )
        result = asyncio.run(run(data))
    except ValidationError as error:
        logger.error(
            "SUPER_ADMIN bootstrap input rejected: %s",
            _safe_validation_summary(error),
        )
        return 2
    except RuntimeError as error:
        logger.error("SUPER_ADMIN bootstrap refused: %s", error)
        return 2
    except Exception as error:
        logger.error(
            "SUPER_ADMIN bootstrap failed: error_type=%s",
            type(error).__name__,
        )
        return 1

    logger.info(
        "SUPER_ADMIN bootstrap succeeded: user_id=%d created=%s replay=%s",
        result.user_id,
        result.created,
        result.is_replay,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
