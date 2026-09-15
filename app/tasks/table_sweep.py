"""短事务批量收敛已超时或到期的桌台会话。"""

from __future__ import annotations

import asyncio
import json
import sys

from tortoise import Tortoise

from app.db.database import TORTOISE_ORM
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.table_session_repo import TableSessionRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.table_session_service import TableSessionService


async def run() -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    closed = 0
    try:
        service = TableSessionService(
            TableSessionRepository(),
            OrderRepository(),
            UserRepository(),
            PaymentRepository(),
            AuditLogService(AuditLogRepository()),
        )
        while True:
            count = await service.sweep_due_sessions()
            closed += count
            if count == 0:
                break
        sys.stdout.write(
            json.dumps({"status": "ok", "closed": closed}, separators=(",", ":"))
            + "\n"
        )
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(run())
