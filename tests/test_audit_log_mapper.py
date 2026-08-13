"""共享 AuditLog API Mapper 契约测试。"""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.mappers.audit import map_audit_log_page
from app.common.pagination import Page


def test_audit_log_page_uses_public_whitelist_and_preserves_metadata() -> None:
    created_at = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)
    item = SimpleNamespace(
        id=8,
        operator_id=7,
        action="UPDATE_PRODUCT",
        target_type="product",
        target_id=3,
        description='{"before":{"name":"旧"}}',
        ip_address="2001:db8::1",
        created_at=created_at,
        updated_at=created_at,
        internal_marker="must-not-leak",
    )

    result = map_audit_log_page(
        Page(items=[item], total=1, page=1, page_size=20, pages=1)
    ).model_dump(mode="json")

    assert result == {
        "items": [
            {
                "id": 8,
                "operator_id": 7,
                "action": "UPDATE_PRODUCT",
                "target_type": "product",
                "target_id": 3,
                "description": '{"before":{"name":"旧"}}',
                "ip_address": "2001:db8::1",
                "created_at": "2026-08-13T09:00:00Z",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 20,
        "pages": 1,
    }
