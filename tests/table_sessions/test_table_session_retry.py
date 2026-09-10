from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tortoise.exceptions import OperationalError

from app.repositories.order_repo import OrderRepository
from app.repositories.payment_repo import PaymentRepository
from app.repositories.table_session_repo import TableSessionRepository
from app.repositories.user_repo import UserRepository
from app.services.audit_log_service import AuditLogService
from app.services.table_session_service import (
    TableSessionReleaseResult,
    TableSessionService,
)


def _service() -> TableSessionService:
    return TableSessionService(
        AsyncMock(spec=TableSessionRepository),
        AsyncMock(spec=OrderRepository),
        AsyncMock(spec=UserRepository),
        AsyncMock(spec=PaymentRepository),
        AsyncMock(spec=AuditLogService),
    )


@pytest.mark.parametrize("error_code", [1205, 1213])
async def test_convergence_retries_the_complete_transaction(error_code: int) -> None:
    service = _service()
    converge_once = AsyncMock(
        side_effect=[OperationalError(error_code, "transient"), True]
    )
    service._converge_session_once = converge_once  # type: ignore[method-assign]
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)

    assert await service.converge_session(7, now=now) is True
    assert converge_once.await_count == 2
    converge_once.assert_awaited_with(session_id=7, current_time=now)


@pytest.mark.parametrize("error_code", [1205, 1213])
async def test_admin_release_retries_the_complete_transaction(error_code: int) -> None:
    service = _service()
    visible = SimpleNamespace(id=11, user_id=3, order_id=5, table_id=7)
    expected = TableSessionReleaseResult(session=visible, is_replay=False)  # type: ignore[arg-type]
    service._resolve_release_replay = AsyncMock(  # type: ignore[method-assign]
        return_value=None
    )
    service.table_repository.get_session_detail_by_no.return_value = visible
    service.converge_session = AsyncMock(return_value=False)  # type: ignore[method-assign]
    release_once = AsyncMock(
        side_effect=[OperationalError(error_code, "transient"), expected]
    )
    service._release_session_once = release_once  # type: ignore[method-assign]

    result = await service.release_session(
        session_no=f"TS{'1' * 26}",
        operator_id=9,
        reason="  应急释放  ",
        idempotency_key="release-retry",
        ip_address="127.0.0.1",
    )

    assert result is expected
    assert release_once.await_count == 2
    assert release_once.await_args_list[0] == release_once.await_args_list[1]


async def test_admin_release_does_not_retry_non_transient_database_error() -> None:
    service = _service()
    visible = SimpleNamespace(id=11, user_id=3, order_id=5, table_id=7)
    failure = OperationalError(2006, "server gone")
    service._resolve_release_replay = AsyncMock(  # type: ignore[method-assign]
        return_value=None
    )
    service.table_repository.get_session_detail_by_no.return_value = visible
    service.converge_session = AsyncMock(return_value=False)  # type: ignore[method-assign]
    service._release_session_once = AsyncMock(  # type: ignore[method-assign]
        side_effect=failure
    )

    with pytest.raises(OperationalError) as caught:
        await service.release_session(
            session_no=f"TS{'1' * 26}",
            operator_id=9,
            reason="应急释放",
            idempotency_key="release-no-retry",
            ip_address="127.0.0.1",
        )

    assert caught.value is failure
    service._release_session_once.assert_awaited_once()  # type: ignore[attr-defined]
