"""门店共享跟进：预约锁串行写入，精确版本防覆盖，请求键防重复。"""
from collections.abc import Callable
from datetime import datetime, timezone
from tortoise.transactions import in_transaction
from app.common.enums.reservation_followup import FOLLOWUP_COMPLETED, FOLLOWUP_LABELS, FollowupKind, FollowupOutcome
from app.common.exceptions.reservation import ReservationNotFound
from app.common.exceptions.reservation_followup import FollowupConflict
from app.common.pagination import Page
from app.models.reservation import Reservation
from app.models.reservation_followup import ReservationFollowup
from app.repositories.reservation_repo import ReservationRepository
from app.repositories.reservation_followup_repo import ReservationFollowupRepository
from app.schemas.reservation_followup import FollowupCounts, FollowupItemOut, FollowupRecordOut, FollowupSnapshotOut, FollowupWrite


def eligible(reservation: Reservation, kind: FollowupKind, now: datetime) -> bool:
    if kind == FollowupKind.CONTACT:
        return reservation.status == "cancelled" and reservation.cancellation_reason == "store_closed"
    return reservation.status == "pending" and reservation.scheduled_start_at <= now


def record_out(record: ReservationFollowup | None) -> FollowupRecordOut | None:
    return None if record is None else FollowupRecordOut(id=record.id, revision=record.revision, outcome=record.outcome, label=FOLLOWUP_LABELS[record.outcome], note=record.note, operator_id=record.operator_id, created_at=record.created_at)


def snapshot(reservation: Reservation, kind: FollowupKind, record: ReservationFollowup | None, now: datetime) -> FollowupSnapshotOut:
    return FollowupSnapshotOut(reservation_id=reservation.id, kind=kind, eligible=eligible(reservation, kind, now), completed=record is not None and record.outcome in FOLLOWUP_COMPLETED, revision=record.revision if record else 0, latest=record_out(record), server_now=now)


class ReservationFollowupService:
    def __init__(self, repository: ReservationFollowupRepository, reservations: ReservationRepository, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self.repository = repository
        self.reservations = reservations
        self.now = now_provider or (lambda: datetime.now(timezone.utc))

    async def counts(self) -> FollowupCounts:
        now = self.now()
        async with in_transaction() as db:
            contact = await self.repository.count(FollowupKind.CONTACT, now, using_db=db)
            overdue = await self.repository.count(FollowupKind.OVERDUE, now, using_db=db)
        return FollowupCounts(server_now=now, contact_pending=contact, overdue_pending=overdue)

    async def list_queue(self, kind: FollowupKind, view: str, page: int, page_size: int) -> Page[FollowupItemOut]:
        now = self.now()
        async with in_transaction() as db:
            rows, total, latest = await self.repository.list_queue(kind, view == "completed", now, page, page_size, using_db=db)
            items = [FollowupItemOut(**snapshot(row, kind, latest.get(row.id), now).model_dump(), product_name=row.product_name, customer_name=row.user.nickname or f"顾客 #{row.user_id}", scheduled_start_at=row.scheduled_start_at) for row in rows]
        return Page(items=items, total=total, page=page, page_size=page_size, pages=(total + page_size - 1) // page_size)

    async def detail(self, reservation_id: int, kind: FollowupKind) -> FollowupSnapshotOut:
        async with in_transaction() as db:
            reservation = await self.reservations.get_reservation_detail(reservation_id, using_db=db)
            if reservation is None:
                raise ReservationNotFound()
            latest = await self.repository.latest(reservation_id, kind, using_db=db)
            return snapshot(reservation, kind, latest, self.now())

    async def history(self, reservation_id: int, kind: FollowupKind, page: int, page_size: int) -> Page[FollowupRecordOut]:
        async with in_transaction() as db:
            if await self.reservations.get_reservation_detail(reservation_id, using_db=db) is None:
                raise ReservationNotFound()
            rows, total = await self.repository.history(reservation_id, kind, page, page_size, using_db=db)
        return Page(items=[record_out(row) for row in rows], total=total, page=page, page_size=page_size, pages=(total + page_size - 1) // page_size)

    async def write(self, reservation_id: int, kind: FollowupKind, data: FollowupWrite, operator_id: int) -> FollowupSnapshotOut:
        async with in_transaction() as db:
            reservation = await self.reservations.get_reservation_for_update(reservation_id, using_db=db)
            if reservation is None:
                raise ReservationNotFound()
            # 锁后当前读，不能复用等待预约锁之前的 MySQL RR 快照。
            replay = await self.repository.replay(reservation_id, kind, str(data.request_key), using_db=db)
            latest = await self.repository.latest(reservation_id, kind, using_db=db, lock=True)
            if replay is not None:
                if (replay.outcome, replay.note, replay.operator_id, replay.revision) != (data.outcome, data.note, operator_id, data.expected_revision + 1):
                    raise FollowupConflict()
                return snapshot(reservation, kind, latest, self.now())
            if not eligible(reservation, kind, self.now()) or (latest and latest.outcome in FOLLOWUP_COMPLETED) or data.expected_revision != (latest.revision if latest else 0):
                raise FollowupConflict()
            if kind == FollowupKind.OVERDUE and data.outcome == FollowupOutcome.CONTACTED:
                raise FollowupConflict()
            latest = await self.repository.append(reservation_id, kind, data.outcome, data.note, data.expected_revision + 1, str(data.request_key), operator_id, using_db=db)
            return snapshot(reservation, kind, latest, self.now())
