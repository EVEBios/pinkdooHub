"""Phase 4.3.1 Inventory 文档冻结与当前实现边界契约。"""

from pathlib import Path

from app.schemas.order import OrderItemCreate
from app.schemas.product import KitProductCreate


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_REQUIREMENTS = REPOSITORY_ROOT / "docs/01_requirements/inventory_module.md"
INVENTORY_API = REPOSITORY_ROOT / "docs/03_api/inventory_api.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_inventory_contract_freezes_balance_lifecycle_and_mixed_orders() -> None:
    """权威文档固定余额来源、发生时点、混合订单与状态行为。"""

    contract = _read(INVENTORY_REQUIREMENTS)

    assert "ProductKit.stock = 唯一的当前可售库存" in contract
    assert "创建纯 Kit 订单" in contract
    assert "创建混合订单" in contract
    assert "pending -> cancelled" in contract
    assert "pending -> paid" in contract
    assert "paid -> completed" in contract
    assert "不改变库存" in contract
    assert "所有 Kit 扣减、Order、OrderItem、InventoryTransaction" in contract


def test_inventory_contract_freezes_adjustment_and_idempotency_boundaries() -> None:
    """调整输入、兼容决策、流水类型与幂等规则不得漂移。"""

    contract = _read(INVENTORY_REQUIREMENTS)
    api = _read(INVENTORY_API)

    assert "`0 <= stock <= 999999`" in contract
    assert "长度为 `1..256`" in contract
    assert "Idempotency-Key" in contract
    assert "相同管理员、相同 key、相同 Product/change/reason" in contract
    assert "opening_balance" in contract
    assert "admin_adjustment" in contract
    assert "order_deduction" in contract
    assert "order_cancellation_restore" in contract
    assert "PATCH /api/v1/admin/products/kit/{product_id}/stock" in contract
    assert "不做兼容包装" in contract
    assert "HTTP 201" in api
    assert "已提交重试返回 HTTP 200" in api


def test_inventory_contract_freezes_error_privacy_locking_and_release_gate() -> None:
    """用户隐私、稳定锁序、错误号与 MySQL 发布门槛保持明确。"""

    contract = _read(INVENTORY_REQUIREMENTS)
    api = _read(INVENTORY_API)

    assert "不暴露精确可用量" in contract
    assert "按升序排序" in contract
    assert "先创建 Pending Order 取得 ID" in contract
    assert "订单号唯一冲突发生在任何库存锁/写之前" in contract
    assert "最多 3 次（含首次）" in contract
    assert "40931" in api
    assert "40932" in api
    assert "40933" in api
    assert "MySQL 8+ 真实并发测试" in contract
    assert "真实 MySQL 竞争、1205 重试和 EXPLAIN 已通过" in contract


def test_phase_4312_records_final_review_and_persistent_database_boundary() -> None:
    """最终 Review 已完成，但不能误报持久迁移或正式发布。"""

    requirements = _read(INVENTORY_REQUIREMENTS)
    api = _read(INVENTORY_API)

    assert "Final-Review Complete" in requirements
    assert "Final-Review Complete" in api
    assert "Phase 4.3.12" in requirements
    assert "order_cancellation_restore" in requirements
    assert "MySQL 8.0.46 隔离 Schema 使用真实 Aerich 0 → 1 → 2" in api
    assert "未应用任何持久、共享或生产环境" in api
    assert "三个管理端点均已注册" in api
    assert "真实 MySQL 竞争/1205 重试/EXPLAIN" in api
    assert "v0.6.0 未发布候选" in api
    assert "stock <= 999999" in api

    assert "experience_option_id" in OrderItemCreate.model_fields
    assert not OrderItemCreate.model_fields["experience_option_id"].is_required()
    assert "stock" not in KitProductCreate.model_fields
