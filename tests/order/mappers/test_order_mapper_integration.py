"""Order Mapper 与真实 Repository 聚合的零 SQL、零修改测试。"""

from decimal import Decimal

import pytest
from tortoise import connections

from app.api.mappers.order import (
    map_admin_order_detail,
    map_admin_order_page,
    map_order_detail,
    map_order_page,
    map_order_status_response,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductType
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.repositories.order_repo import OrderRepository


async def _create_aggregate() -> tuple[User, Order]:
    user = await User.create(
        username="order-mapper-user",
        password="hashed-password",
        nickname="Mapper 用户",
        phone="13800138000",
    )
    product = await Product.create(
        name="Mapper 体验",
        product_type=ProductType.EXPERIENCE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=90,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("88.50"),
    )
    order = await Order.create(
        order_no="OD01K2M7Y0J7A3N5Q8T4V6W9X2BC",
        user=user,
        total_amount=Decimal("177.00"),
        remark="真实聚合",
    )
    await OrderItem.create(
        order=order,
        product=product,
        experience_option=option,
        option_duration_minutes=90,
        option_participants=2,
        option_day_type=DayType.HOLIDAY,
        product_name="Mapper 体验",
        product_price=Decimal("88.50"),
        quantity=2,
        subtotal=Decimal("177.00"),
    )
    return user, order


def _detail_snapshot(order: Order) -> tuple[object, ...]:
    return (
        order.id,
        order.order_no,
        order.user_id,
        order.total_amount,
        order.status,
        order.remark,
        order.created_at,
        order.updated_at,
        order.user.id,
        order.user.nickname,
        tuple(
            (
                item.id,
                item.order_id,
                item.product_id,
                item.experience_option_id,
                item.product_name,
                item.option_duration_minutes,
                item.option_participants,
                item.option_day_type,
                item.product_price,
                item.quantity,
                item.subtotal,
            )
            for item in order.items
        ),
    )


async def test_repository_detail_maps_without_sql_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, order = await _create_aggregate()
    loaded = await OrderRepository().get_order_detail(order.id)
    assert loaded is not None
    before = _detail_snapshot(loaded)
    connection = connections.get("default")

    def fail_on_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("Order Mapper must not execute SQL")

    monkeypatch.setattr(connection, "execute_query", fail_on_query)

    user_data = map_order_detail(loaded).model_dump(mode="json")
    admin_data = map_admin_order_detail(loaded).model_dump(mode="json")

    assert user_data["total_amount"] == "177.00"
    assert user_data["items"][0]["option_day_type"] == {
        "value": "holiday",
        "label": "节假日",
    }
    assert "user_id" not in user_data
    assert admin_data["user_nickname"] == "Mapper 用户"
    assert _detail_snapshot(loaded) == before


async def test_repository_pages_map_without_additional_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await _create_aggregate()
    repository = OrderRepository()
    user_page = await repository.list_user_orders(
        user_id=user.id,
        page=1,
        page_size=20,
    )
    admin_page = await repository.list_admin_orders(page=1, page_size=20)
    user_before = tuple(
        (
            order.id,
            order.order_no,
            order.total_amount,
            order.status,
            order.item_count,
            order.created_at,
            order.updated_at,
        )
        for order in user_page.items
    )
    admin_before = tuple(
        (
            order.id,
            order.order_no,
            order.user_id,
            order.user.nickname,
            order.total_amount,
            order.status,
            order.item_count,
            order.created_at,
            order.updated_at,
        )
        for order in admin_page.items
    )
    connection = connections.get("default")

    def fail_on_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("Order Mapper must not execute SQL")

    monkeypatch.setattr(connection, "execute_query", fail_on_query)

    user_data = map_order_page(user_page).model_dump(mode="json")
    admin_data = map_admin_order_page(admin_page).model_dump(mode="json")

    assert user_data["items"][0]["item_count"] == 1
    assert "user_id" not in user_data["items"][0]
    assert admin_data["items"][0]["user_nickname"] == "Mapper 用户"
    assert user_before == tuple(
        (
            order.id,
            order.order_no,
            order.total_amount,
            order.status,
            order.item_count,
            order.created_at,
            order.updated_at,
        )
        for order in user_page.items
    )
    assert admin_before == tuple(
        (
            order.id,
            order.order_no,
            order.user_id,
            order.user.nickname,
            order.total_amount,
            order.status,
            order.item_count,
            order.created_at,
            order.updated_at,
        )
        for order in admin_page.items
    )


async def test_lightweight_status_model_maps_without_relations_or_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, order = await _create_aggregate()
    order.status = OrderStatus.PAID
    await order.save(update_fields=["status", "updated_at"])
    loaded = await OrderRepository().get_order_by_id(order.id)
    assert loaded is not None
    connection = connections.get("default")

    def fail_on_query(*args: object, **kwargs: object) -> None:
        raise AssertionError("Order Mapper must not execute SQL")

    monkeypatch.setattr(connection, "execute_query", fail_on_query)

    data = map_order_status_response(loaded).model_dump(mode="json")

    assert data["status"] == {"value": "paid", "label": "已支付"}
    assert set(data) == {"id", "order_no", "status", "updated_at"}
