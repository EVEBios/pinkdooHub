"""共享 AuditLog 事务连接透传与回滚契约测试。"""

from unittest.mock import AsyncMock

import pytest
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.transactions import in_transaction

from app.models.audit_log import AuditLog
from app.repositories.audit_log_repo import AuditLogRepository
from app.services.audit_log_service import AuditLogService


AUDIT_FIELDS = {
    "operator_id": 101,
    "action": "ONLINE_PRODUCT",
    "target_type": "product",
    "target_id": 202,
    "ip_address": "127.0.0.1",
    "description": "Product brought online",
}


async def test_repository_create_without_transaction_remains_supported(
) -> None:
    created = await AuditLogRepository().create(**AUDIT_FIELDS)

    persisted = await AuditLog.get(id=created.id)
    assert persisted.operator_id == AUDIT_FIELDS["operator_id"]
    assert persisted.action == AUDIT_FIELDS["action"]
    assert persisted.target_type == AUDIT_FIELDS["target_type"]
    assert persisted.target_id == AUDIT_FIELDS["target_id"]
    assert persisted.ip_address == AUDIT_FIELDS["ip_address"]
    assert persisted.description == AUDIT_FIELDS["description"]


async def test_repository_create_joins_caller_transaction_and_rolls_back(
) -> None:
    created_id: int | None = None

    with pytest.raises(RuntimeError, match="rollback audit repository"):
        async with in_transaction() as connection:
            created = await AuditLogRepository().create(
                **AUDIT_FIELDS,
                using_db=connection,
            )
            created_id = created.id
            assert await AuditLog.filter(id=created_id).using_db(
                connection,
            ).exists()
            raise RuntimeError("rollback audit repository")

    assert created_id is not None
    assert not await AuditLog.filter(id=created_id).exists()


async def test_service_forwards_transaction_connection() -> None:
    repository = AsyncMock(spec=AuditLogRepository)
    service = AuditLogService(repository)
    connection = AsyncMock(spec=BaseDBAsyncClient)

    result = await service.log(
        **AUDIT_FIELDS,
        using_db=connection,
    )

    assert result is None
    repository.create.assert_awaited_once_with(
        **AUDIT_FIELDS,
        using_db=connection,
    )


async def test_service_without_transaction_forwards_none() -> None:
    repository = AsyncMock(spec=AuditLogRepository)
    service = AuditLogService(repository)

    result = await service.log(**AUDIT_FIELDS)

    assert result is None
    repository.create.assert_awaited_once_with(
        **AUDIT_FIELDS,
        using_db=None,
    )


async def test_service_audit_joins_caller_transaction_and_rolls_back(
) -> None:
    with pytest.raises(RuntimeError, match="rollback audit service"):
        async with in_transaction() as connection:
            await AuditLogService(AuditLogRepository()).log(
                **AUDIT_FIELDS,
                using_db=connection,
            )
            assert await AuditLog.filter(
                action=AUDIT_FIELDS["action"],
                target_id=AUDIT_FIELDS["target_id"],
            ).using_db(connection).exists()
            raise RuntimeError("rollback audit service")

    assert not await AuditLog.filter(
        action=AUDIT_FIELDS["action"],
        target_id=AUDIT_FIELDS["target_id"],
    ).exists()
