"""共享 AuditLog 分页查询测试。"""

from app.repositories.audit_log_repo import AuditLogRepository
from app.services.audit_log_service import AuditLogService


async def _create_log(
    repository: AuditLogRepository,
    *,
    action: str,
    target_type: str = "product",
    target_id: int = 1,
) -> None:
    await repository.create(
        operator_id=7,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip_address="127.0.0.1",
    )


async def test_list_logs_filters_target_and_returns_stable_reverse_page() -> None:
    repository = AuditLogRepository()
    for action in ("FIRST", "SECOND", "THIRD"):
        await _create_log(repository, action=action)
    await _create_log(repository, action="OTHER_PRODUCT", target_id=2)
    await _create_log(
        repository,
        action="OTHER_TYPE",
        target_type="user",
    )

    result = await repository.list_logs(
        target_type="product",
        target_id=1,
        page=2,
        page_size=2,
    )

    assert [item.action for item in result.items] == ["FIRST"]
    assert result.total == 3
    assert result.page == 2
    assert result.page_size == 2
    assert result.pages == 2


async def test_audit_service_delegates_shared_query() -> None:
    repository = AuditLogRepository()
    await _create_log(repository, action="CREATE_PRODUCT", target_id=9)

    result = await AuditLogService(repository).list_logs(
        target_type="product",
        target_id=9,
        page=1,
        page_size=20,
    )

    assert [item.action for item in result.items] == ["CREATE_PRODUCT"]
    assert result.total == 1
