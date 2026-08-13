"""OrderService 创建聚合、原子回滚与编号冲突的真实 SQLite 测试。"""

import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.order_repo import OrderRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.order_service import OrderItemInput, OrderService


def _order_no(suffix: int) -> str:
    return f"OD{'0' * 24}{suffix:02d}"


async def _create_user() -> User:
    return await User.create(
        username="order-create-user",
        password="hashed-password",
        nickname="创建订单用户",
        phone="13800138000",
    )


async def _create_experience(
    number: int,
    *,
    name: str,
    duration: int,
    participants: int,
    day_type: DayType,
    price: str,
) -> tuple[Product, ExperienceOption]:
    product = await Product.create(
        name=name,
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=duration,
        participants=participants,
        day_type=day_type,
        price=Decimal(price),
    )
    assert product.id == number
    return product, option


def _service(
    order_numbers: Iterator[str],
    *,
    order_repository: OrderRepository | None = None,
    audit_service: AuditLogService | None = None,
) -> OrderService:
    return OrderService(
        order_repository or OrderRepository(),
        ProductRepository(),
        audit_service or AuditLogService(AuditLogRepository()),
        lambda: next(order_numbers),
    )


async def test_create_persists_authoritative_immutable_snapshots_and_audit() -> None:
    """真实创建保留 DB 快照、精确 Decimal 金额和非敏感审计摘要。"""

    user = await _create_user()
    first_product, first_option = await _create_experience(
        1,
        name="经典拼豆体验",
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price="99.90",
    )
    second_product, second_option = await _create_experience(
        2,
        name="亲子拼豆体验",
        duration=120,
        participants=2,
        day_type=DayType.HOLIDAY,
        price="150.05",
    )

    created = await _service(iter([_order_no(1)])).create_order(
        user_id=user.id,
        items=[
            OrderItemInput(first_product.id, first_option.id, 2),
            OrderItemInput(second_product.id, second_option.id, 1),
        ],
        remark="周末到店；不要写入审计 description",
        ip_address="203.0.113.8",
    )

    assert created.order_no == _order_no(1)
    assert created.user.id == user.id
    assert created.total_amount == Decimal("349.85")
    assert created.remark == "周末到店；不要写入审计 description"
    assert [item.product_name for item in created.items] == [
        "经典拼豆体验",
        "亲子拼豆体验",
    ]
    assert [item.product_price for item in created.items] == [
        Decimal("99.90"),
        Decimal("150.05"),
    ]
    assert [item.subtotal for item in created.items] == [
        Decimal("199.80"),
        Decimal("150.05"),
    ]
    assert created.items[1].option_duration_minutes == 120
    assert created.items[1].option_participants == 2
    assert created.items[1].option_day_type is DayType.HOLIDAY

    audit = await AuditLog.get(
        target_type="order",
        target_id=created.id,
    )
    assert audit.operator_id == user.id
    assert audit.action == "CREATE_ORDER"
    assert audit.ip_address == "203.0.113.8"
    assert json.loads(audit.description or "") == {
        "item_count": 2,
        "total_amount": "349.85",
    }
    assert "周末" not in (audit.description or "")

    first_product.name = "后来改过的名称"
    await first_product.save(update_fields=["name", "updated_at"])
    first_option.price = Decimal("888.88")
    first_option.duration = 180
    await first_option.save(
        update_fields=["price", "duration", "updated_at"]
    )
    reloaded = await OrderRepository().get_order_detail(created.id)
    assert reloaded is not None
    assert reloaded.items[0].product_name == "经典拼豆体验"
    assert reloaded.items[0].product_price == Decimal("99.90")
    assert reloaded.items[0].option_duration_minutes == 60
    assert reloaded.total_amount == Decimal("349.85")


class _FailAfterAudit(AuditLogService):
    async def log(
        self,
        operator_id: int,
        action: str,
        target_type: str,
        target_id: int,
        ip_address: str,
        description: str | None = None,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> None:
        await super().log(
            operator_id,
            action,
            target_type,
            target_id,
            ip_address,
            description,
            using_db=using_db,
        )
        raise RuntimeError("fail after audit write")


class _MissingReloadOrderRepository(OrderRepository):
    async def get_order_detail(
        self,
        order_id: int,
        *,
        user_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Order | None:
        return None


@pytest.mark.parametrize("failure_stage", ["audit", "reload"])
async def test_any_transaction_stage_failure_rolls_back_entire_aggregate(
    failure_stage: str,
) -> None:
    """审计已写或最终重载失败时，Order、Items、审计均不得残留。"""

    user = await _create_user()
    product, option = await _create_experience(
        1,
        name="回滚体验",
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price="99.00",
    )
    audit_service: AuditLogService | None = None
    repository: OrderRepository | None = None
    expected_message = "Persisted order not found"
    if failure_stage == "audit":
        audit_service = _FailAfterAudit(AuditLogRepository())
        expected_message = "fail after audit write"
    else:
        repository = _MissingReloadOrderRepository()

    with pytest.raises(RuntimeError, match=expected_message):
        await _service(
            iter([_order_no(1)]),
            order_repository=repository,
            audit_service=audit_service,
        ).create_order(
            user_id=user.id,
            items=[OrderItemInput(product.id, option.id, 1)],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert await Order.all().count() == 0
    assert await OrderItem.all().count() == 0
    assert await AuditLog.filter(target_type="order").count() == 0


async def test_order_number_collision_retries_with_a_fresh_transaction() -> None:
    """唯一冲突回滚后，用新编号和全新事务成功创建完整聚合。"""

    user = await _create_user()
    product, option = await _create_experience(
        1,
        name="冲突重试体验",
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price="88.00",
    )
    await Order.create(
        order_no=_order_no(1),
        user=user,
        total_amount=Decimal("1.00"),
    )

    created = await _service(iter([_order_no(1), _order_no(2)])).create_order(
        user_id=user.id,
        items=[OrderItemInput(product.id, option.id, 1)],
        remark=None,
        ip_address="127.0.0.1",
    )

    assert created.order_no == _order_no(2)
    assert await Order.all().count() == 2
    assert await OrderItem.filter(order_id=created.id).count() == 1
    assert await AuditLog.filter(
        target_type="order",
        target_id=created.id,
        action="CREATE_ORDER",
    ).count() == 1


async def test_third_order_number_collision_preserves_integrity_error() -> None:
    """连续三次冲突后保留数据库根因，且不产生半成品或审计。"""

    user = await _create_user()
    product, option = await _create_experience(
        1,
        name="三次冲突体验",
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price="88.00",
    )
    for suffix in (1, 2, 3):
        await Order.create(
            order_no=_order_no(suffix),
            user=user,
            total_amount=Decimal("1.00"),
        )

    with pytest.raises(IntegrityError):
        await _service(
            iter([_order_no(1), _order_no(2), _order_no(3)])
        ).create_order(
            user_id=user.id,
            items=[OrderItemInput(product.id, option.id, 1)],
            remark=None,
            ip_address="127.0.0.1",
        )

    assert await Order.all().count() == 3
    assert await OrderItem.all().count() == 0
    assert await AuditLog.filter(target_type="order").count() == 0
