"""只读核验桌台会话、占用、付款与计时快照的一致性。"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timedelta

from tortoise import Tortoise

from app.common.constants.table_session import TABLE_TIMER_BUFFER_MINUTES
from app.common.enums.table_session import TableSessionCloseReason, TableSessionStatus
from app.common.enums.wallet import PaymentStatus
from app.db.database import TORTOISE_ORM
from app.repositories.table_session_repo import TableSessionRepository

BATCH_SIZE = 100


async def reconcile(repository: TableSessionRepository) -> dict[str, int]:
    counts = await repository.consistency_counts()
    violations = abs(counts["open_sessions"] - counts["occupancies"])
    scanned = 0
    after_id = 0
    while True:
        sessions = await repository.list_consistency_sessions(
            after_id=after_id,
            limit=BATCH_SIZE,
        )
        if not sessions:
            break
        for session in sessions:
            scanned += 1
            after_id = session.id
            status = TableSessionStatus(session.status)
            occupancies = list(session.occupancy)
            timers = list(session.timers)
            payment = session.payment
            violations += int(session.order.user_id != session.user_id)
            if status is TableSessionStatus.CLOSED:
                violations += int(bool(occupancies))
                violations += int(
                    session.closed_at is None or session.close_reason is None
                )
            else:
                violations += int(len(occupancies) != 1)
                if len(occupancies) == 1:
                    occupancy = occupancies[0]
                    violations += int(
                        occupancy.table_id != session.table_id
                        or occupancy.user_id != session.user_id
                        or occupancy.order_id != session.order_id
                    )

            has_activation_fact = any(
                (
                    payment is not None,
                    session.started_at is not None,
                    session.table_release_at is not None,
                    bool(timers),
                )
            )
            if status is TableSessionStatus.AWAITING_PAYMENT or (
                status is TableSessionStatus.CLOSED and not has_activation_fact
            ):
                violations += int(
                    bool(timers)
                    or session.payment_id is not None
                    or session.started_at is not None
                    or session.table_release_at is not None
                )
                if status is TableSessionStatus.CLOSED:
                    violations += int(
                        session.close_reason
                        not in (
                            TableSessionCloseReason.PAYMENT_TIMEOUT,
                            TableSessionCloseReason.ORDER_CANCELLED,
                            TableSessionCloseReason.ADMIN_RELEASED,
                        )
                    )
                    if (
                        session.close_reason is TableSessionCloseReason.PAYMENT_TIMEOUT
                    ):
                        violations += int(
                            session.closed_at != session.payment_deadline_at
                        )
                continue

            if status is TableSessionStatus.CLOSED:
                violations += int(
                    session.close_reason
                    not in (
                        TableSessionCloseReason.TIME_EXPIRED,
                        TableSessionCloseReason.ORDER_COMPLETED,
                        TableSessionCloseReason.REFUNDED,
                        TableSessionCloseReason.ADMIN_RELEASED,
                    )
                )
                if session.close_reason is TableSessionCloseReason.TIME_EXPIRED:
                    violations += int(session.closed_at != session.table_release_at)
            expected_durations = {
                item.option_duration_minutes
                for item in session.order.items
                if item.experience_option_id is not None
            }
            violations += int(
                not timers
                or payment is None
                or PaymentStatus(payment.status) is not PaymentStatus.SUCCEEDED
                or payment.succeeded_at is None
                or session.started_at != payment.succeeded_at
                or payment.order_id != session.order_id
                or payment.user_id != session.user_id
                or {timer.duration_minutes for timer in timers}
                != expected_durations
            )
            if not timers:
                continue
            for timer in timers:
                violations += int(timer.started_at != session.started_at)
                violations += int(
                    timer.duration_minutes <= 0
                    or timer.buffer_minutes != TABLE_TIMER_BUFFER_MINUTES
                )
                violations += int(
                    timer.service_ends_at
                    != timer.started_at + timedelta(minutes=timer.duration_minutes)
                )
                violations += int(
                    timer.grace_ends_at
                    != timer.service_ends_at + timedelta(minutes=timer.buffer_minutes)
                )
            violations += int(
                session.table_release_at
                != max(timer.grace_ends_at for timer in timers)
            )
    return {**counts, "scanned": scanned, "violations": violations}


async def run() -> int:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        result = await reconcile(TableSessionRepository())
        sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
        return 0 if result["violations"] == 0 else 1
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
