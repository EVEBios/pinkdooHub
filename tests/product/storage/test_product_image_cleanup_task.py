"""ProductImage 清理命令的解析和批处理编排测试。"""

import argparse
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tasks.product_image_cleanup import build_parser, cleanup_all, parse_before


def test_parse_before_requires_explicit_timezone() -> None:
    assert parse_before("2026-08-13T00:00:00Z") == datetime(
        2026,
        8,
        13,
        tzinfo=timezone.utc,
    )
    with pytest.raises(argparse.ArgumentTypeError, match="timezone"):
        parse_before("2026-08-13T00:00:00")


def test_cleanup_command_defaults_to_preview_and_requires_apply_for_delete() -> None:
    parser = build_parser()

    preview = parser.parse_args(["--before", "2026-08-13T00:00:00Z"])
    apply = parser.parse_args(
        ["--before", "2026-08-13T00:00:00Z", "--apply"]
    )

    assert preview.apply is False
    assert apply.apply is True


async def test_cleanup_all_uses_id_cursor_and_aggregates_batches() -> None:
    service = SimpleNamespace(cleanup_batch=AsyncMock())
    service.cleanup_batch.side_effect = [
        SimpleNamespace(
            scanned=2,
            deleted=1,
            already_missing=0,
            skipped_unmanaged=1,
            skipped_active_reference=0,
            would_delete=0,
            failed=0,
            last_image_id=5,
        ),
        SimpleNamespace(
            scanned=1,
            deleted=0,
            already_missing=1,
            skipped_unmanaged=0,
            skipped_active_reference=0,
            would_delete=0,
            failed=1,
            last_image_id=9,
        ),
    ]
    before = datetime(2026, 8, 13, tzinfo=timezone.utc)

    totals = await cleanup_all(
        service,
        before=before,
        batch_size=2,
        dry_run=True,
    )

    assert totals.scanned == 3
    assert totals.deleted == 1
    assert totals.already_missing == 1
    assert totals.skipped_unmanaged == 1
    assert totals.failed == 1
    assert service.cleanup_batch.await_args_list[0].kwargs["after_id"] == 0
    assert service.cleanup_batch.await_args_list[1].kwargs["after_id"] == 5
    assert all(
        call.kwargs["dry_run"] is True
        for call in service.cleanup_batch.await_args_list
    )
