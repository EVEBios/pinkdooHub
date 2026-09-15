from datetime import datetime, timedelta, timezone

import pytest

from app.common.enums.table_session import (
    TableSessionCloseReason,
    TableSessionStatus,
)
from app.domain.table_session import automatic_close_for, build_timer_specs


def test_timer_specs_group_exact_durations_and_add_ten_minute_buffer() -> None:
    started_at = datetime(2026, 9, 10, 4, 0, tzinfo=timezone.utc)

    specs = build_timer_specs([120, 60, 120], started_at=started_at)

    assert [spec.duration_minutes for spec in specs] == [60, 120]
    assert all(spec.buffer_minutes == 10 for spec in specs)
    assert specs[0].service_ends_at == started_at + timedelta(minutes=60)
    assert specs[0].grace_ends_at == started_at + timedelta(minutes=70)
    assert specs[1].grace_ends_at == started_at + timedelta(minutes=130)


@pytest.mark.parametrize("durations", [[], [None], [0], [-1], [True]])
def test_timer_specs_reject_missing_or_invalid_experience_duration(
    durations: list[int | None],
) -> None:
    with pytest.raises(ValueError):
        build_timer_specs(
            durations,
            started_at=datetime.now(timezone.utc),
        )


def test_automatic_close_boundaries_are_frozen() -> None:
    deadline = datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc)
    assert (
        automatic_close_for(
            status=TableSessionStatus.AWAITING_PAYMENT,
            now=deadline,
            payment_deadline_at=deadline,
            table_release_at=None,
        )
        is None
    )
    timeout = automatic_close_for(
        status=TableSessionStatus.AWAITING_PAYMENT,
        now=deadline + timedelta(microseconds=1),
        payment_deadline_at=deadline,
        table_release_at=None,
    )
    assert timeout is not None
    assert timeout.reason is TableSessionCloseReason.PAYMENT_TIMEOUT
    assert timeout.closed_at == deadline

    expiry = automatic_close_for(
        status=TableSessionStatus.ACTIVE,
        now=deadline,
        payment_deadline_at=deadline - timedelta(hours=1),
        table_release_at=deadline,
    )
    assert expiry is not None
    assert expiry.reason is TableSessionCloseReason.TIME_EXPIRED
    assert expiry.closed_at == deadline
