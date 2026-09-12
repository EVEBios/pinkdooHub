"""InventoryService 管理员调整的真实事务与幂等集成测试。"""

import json
from decimal import Decimal

import pytest
from pytest import MonkeyPatch

from app.common.constants.inventory import (
    INVENTORY_ADMIN_IDEMPOTENCY_PREFIX,
    INVENTORY_AUDIT_ACTION_ADJUST,
    INVENTORY_AUDIT_TARGET_TYPE,
    INVENTORY_STOCK_MAX,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import (
    InventoryBalanceExceeded,
    InventoryTransactionConflict,
    ProductIsDeleted,
    ProductKitNotFound,
    ProductNotFound,
    ProductTypeMismatch,
)
from app.models.audit_log import AuditLog
from app.models.inventory_transaction import InventoryTransaction
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.inventory_repo import InventoryRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.inventory_service import InventoryAdjustmentResult, InventoryService


async def _create_operator(number: int = 1) -> User:
    return await User.create(
        username=f"inventory-service-operator-{number}",
        password="hashed-password",
        nickname=f"库存操作人 {number}",
        phone=f"1390014{number:04d}",
    )


async def _create_kit(
    number: int = 1,
    *,
    stock: int = 10,
    status: ProductStatus = ProductStatus.DRAFT,
    is_deleted: bool = False,
) -> tuple[Product, ProductKit]:
    product = await Product.create(
        name=f"库存调整 Kit {number}",
        product_type=ProductType.KIT,
        status=status,
        is_deleted=is_deleted,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("99.00"),
        stock=stock,
    )
    return product, kit


def _service(
    *,
    audit_service: AuditLogService | None = None,
    inventory_repository: InventoryRepository | None = None,
) -> InventoryService:
    return InventoryService(
        inventory_repository or InventoryRepository(),
        ProductRepository(),
        audit_service or AuditLogService(AuditLogRepository()),
    )


async def _adjust(
    service: InventoryService,
    *,
    product_id: int,
    operator_id: int,
    change: int = 5,
    reason: str = "采购入库",
    key: str = "adjustment-1",
) -> InventoryAdjustmentResult:
    return await service.adjust_stock(
        product_id,
        change=change,
        reason=reason,
        operator_id=operator_id,
        ip_address="127.0.0.1",
        idempotency_key=key,
    )


@pytest.mark.parametrize(
    "status",
    [ProductStatus.DRAFT, ProductStatus.ONLINE, ProductStatus.OFFLINE],
)
async def test_adjustment_atomically_updates_balance_ledger_and_audit(
    status: ProductStatus,
) -> None:
    operator = await _create_operator()
    product, kit = await _create_kit(status=status)

    result = await _adjust(
        _service(),
        product_id=product.id,
        operator_id=operator.id,
    )

    stored_kit = await ProductKit.get(id=kit.id)
    stored_transaction = await InventoryTransaction.get(id=result.transaction.id)
    audit = await AuditLog.get(
        action=INVENTORY_AUDIT_ACTION_ADJUST,
        target_id=product.id,
    )
    assert result.product_id == product.id
    assert result.stock == 15
    assert result.is_replay is False
    assert result.transaction.operator.id == operator.id
    assert result.transaction.operator.nickname == operator.nickname
    assert result.transaction.source_order_no is None
    assert stored_kit.stock == 15
    assert stored_transaction.transaction_type is (
        InventoryTransactionType.ADMIN_ADJUSTMENT
    )
    assert stored_transaction.source_type is InventorySourceType.ADMIN
    assert stored_transaction.source_id is None
    assert stored_transaction.operator_id == operator.id
    assert stored_transaction.change_quantity == 5
    assert stored_transaction.before_quantity == 10
    assert stored_transaction.after_quantity == 15
    assert stored_transaction.reason == "采购入库"
    assert stored_transaction.idempotency_key == (
        f"{INVENTORY_ADMIN_IDEMPOTENCY_PREFIX}adjustment-1"
    )
    assert audit.operator_id == operator.id
    assert audit.target_type == INVENTORY_AUDIT_TARGET_TYPE
    assert audit.ip_address == "127.0.0.1"
    assert json.loads(audit.description) == {
        "transaction_id": stored_transaction.id,
        "before_quantity": 10,
        "change_quantity": 5,
        "after_quantity": 15,
    }
    assert "adjustment-1" not in audit.description
    assert "采购入库" not in audit.description


@pytest.mark.parametrize(
    ("stock", "change", "expected"),
    [
        (0, INVENTORY_STOCK_MAX, INVENTORY_STOCK_MAX),
        (INVENTORY_STOCK_MAX, -INVENTORY_STOCK_MAX, 0),
        (10, -10, 0),
    ],
)
async def test_adjustment_accepts_closed_balance_boundaries(
    stock: int,
    change: int,
    expected: int,
) -> None:
    operator = await _create_operator()
    product, _ = await _create_kit(stock=stock)

    result = await _adjust(
        _service(),
        product_id=product.id,
        operator_id=operator.id,
        change=change,
    )

    assert result.stock == expected
    assert result.transaction.after_quantity == expected


@pytest.mark.parametrize(
    ("stock", "change"),
    [(0, -1), (INVENTORY_STOCK_MAX, 1)],
)
async def test_out_of_range_adjustment_rolls_back_without_ledger_or_audit(
    stock: int,
    change: int,
) -> None:
    operator = await _create_operator()
    product, kit = await _create_kit(stock=stock)

    with pytest.raises(InventoryBalanceExceeded) as caught:
        await _adjust(
            _service(),
            product_id=product.id,
            operator_id=operator.id,
            change=change,
        )

    assert caught.value.data == {
        "product_id": product.id,
        "before_quantity": stock,
        "change_quantity": change,
        "minimum": 0,
        "maximum": INVENTORY_STOCK_MAX,
    }
    assert (await ProductKit.get(id=kit.id)).stock == stock
    assert await InventoryTransaction.all().count() == 0
    assert await AuditLog.all().count() == 0


async def test_identical_idempotent_retry_replays_original_result() -> None:
    operator = await _create_operator()
    product, _ = await _create_kit(stock=10)
    service = _service()

    first = await _adjust(
        service,
        product_id=product.id,
        operator_id=operator.id,
    )
    replay = await _adjust(
        service,
        product_id=product.id,
        operator_id=operator.id,
    )

    assert replay.is_replay is True
    assert replay.transaction.id == first.transaction.id
    assert replay.stock == first.stock == 15
    assert (await ProductKit.get(product_id=product.id)).stock == 15
    assert await InventoryTransaction.all().count() == 1
    assert await AuditLog.all().count() == 1


async def test_replay_preserves_original_result_after_later_adjustment() -> None:
    operator = await _create_operator()
    product, _ = await _create_kit(stock=10)
    service = _service()
    first = await _adjust(
        service,
        product_id=product.id,
        operator_id=operator.id,
        key="first-key",
    )
    later = await _adjust(
        service,
        product_id=product.id,
        operator_id=operator.id,
        change=2,
        reason="追加到货",
        key="later-key",
    )

    replay = await _adjust(
        service,
        product_id=product.id,
        operator_id=operator.id,
        key="first-key",
    )

    assert first.stock == replay.stock == 15
    assert replay.transaction.id == first.transaction.id
    assert replay.is_replay is True
    assert later.stock == 17
    assert (await ProductKit.get(product_id=product.id)).stock == 17
    assert await InventoryTransaction.all().count() == 2
    assert await AuditLog.all().count() == 2


async def test_maximum_client_key_fits_internal_idempotency_identity() -> None:
    operator = await _create_operator()
    product, _ = await _create_kit()
    client_key = "k" * 128

    result = await _adjust(
        _service(),
        product_id=product.id,
        operator_id=operator.id,
        key=client_key,
    )

    stored = await InventoryTransaction.get(id=result.transaction.id)
    assert stored.idempotency_key == (
        f"{INVENTORY_ADMIN_IDEMPOTENCY_PREFIX}{client_key}"
    )
    assert len(stored.idempotency_key) <= 256


@pytest.mark.parametrize("conflict_kind", ["change", "reason", "operator", "product"])
async def test_same_key_with_different_normalized_payload_conflicts(
    conflict_kind: str,
) -> None:
    operator = await _create_operator(1)
    other_operator = await _create_operator(2)
    product, _ = await _create_kit(1)
    other_product, _ = await _create_kit(2)
    service = _service()
    await _adjust(
        service,
        product_id=product.id,
        operator_id=operator.id,
    )
    arguments = {
        "product_id": product.id,
        "operator_id": operator.id,
        "change": 5,
        "reason": "采购入库",
    }
    if conflict_kind == "change":
        arguments["change"] = 6
    elif conflict_kind == "reason":
        arguments["reason"] = "盘点修正"
    elif conflict_kind == "operator":
        arguments["operator_id"] = other_operator.id
    else:
        arguments["product_id"] = other_product.id

    with pytest.raises(InventoryTransactionConflict):
        await _adjust(service, **arguments)

    assert (await ProductKit.get(product_id=product.id)).stock == 15
    assert (await ProductKit.get(product_id=other_product.id)).stock == 10
    assert await InventoryTransaction.all().count() == 1
    assert await AuditLog.all().count() == 1


async def test_audit_failure_rolls_back_and_does_not_consume_key(
    monkeypatch: MonkeyPatch,
) -> None:
    operator = await _create_operator()
    product, kit = await _create_kit(stock=10)
    audit_service = AuditLogService(AuditLogRepository())

    async def fail_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(audit_service, "log", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await _adjust(
            _service(audit_service=audit_service),
            product_id=product.id,
            operator_id=operator.id,
        )

    assert (await ProductKit.get(id=kit.id)).stock == 10
    assert await InventoryTransaction.all().count() == 0
    assert await AuditLog.all().count() == 0

    retry = await _adjust(
        _service(),
        product_id=product.id,
        operator_id=operator.id,
    )
    assert retry.is_replay is False
    assert retry.stock == 15


async def test_detail_reload_failure_rolls_back_balance_ledger_and_audit(
    monkeypatch: MonkeyPatch,
) -> None:
    operator = await _create_operator()
    product, kit = await _create_kit(stock=10)
    inventory_repository = InventoryRepository()

    async def missing_detail(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        inventory_repository,
        "get_transaction_detail",
        missing_detail,
    )
    with pytest.raises(RuntimeError, match="Created inventory transaction not found"):
        await _adjust(
            _service(inventory_repository=inventory_repository),
            product_id=product.id,
            operator_id=operator.id,
        )

    assert (await ProductKit.get(id=kit.id)).stock == 10
    assert await InventoryTransaction.all().count() == 0
    assert await AuditLog.all().count() == 0


async def test_missing_product_uses_product_not_found_without_writes() -> None:
    operator = await _create_operator()

    with pytest.raises(ProductNotFound):
        await _adjust(
            _service(),
            product_id=999,
            operator_id=operator.id,
        )

    assert await InventoryTransaction.all().count() == 0
    assert await AuditLog.all().count() == 0


async def test_deleted_product_precedes_balance_and_idempotency() -> None:
    operator = await _create_operator()
    product, kit = await _create_kit(is_deleted=True)

    with pytest.raises(ProductIsDeleted):
        await _adjust(
            _service(),
            product_id=product.id,
            operator_id=operator.id,
        )

    assert (await ProductKit.get(id=kit.id)).stock == 10


async def test_experience_product_uses_product_type_mismatch() -> None:
    operator = await _create_operator()
    product = await Product.create(
        name="不能调整的体验",
        product_type=ProductType.EXPERIENCE,
    )

    with pytest.raises(ProductTypeMismatch) as caught:
        await _adjust(
            _service(),
            product_id=product.id,
            operator_id=operator.id,
        )

    assert caught.value.data == {"expected": "kit", "actual": "experience"}


async def test_missing_kit_extension_uses_registered_product_error() -> None:
    operator = await _create_operator()
    product = await Product.create(
        name="缺少扩展的 Kit",
        product_type=ProductType.KIT,
    )

    with pytest.raises(ProductKitNotFound):
        await _adjust(
            _service(),
            product_id=product.id,
            operator_id=operator.id,
        )
