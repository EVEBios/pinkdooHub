"""Order 创建 API 的真实 HTTP 业务边界与防伪契约测试。"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.product_kit import ProductKit


def _headers(auth_user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_user['token']}"}


async def _create_product(
    *,
    name: str = "HTTP 创建边界体验",
    status: ProductStatus = ProductStatus.ONLINE,
    product_type: ProductType = ProductType.EXPERIENCE,
    is_deleted: bool = False,
) -> Product:
    return await Product.create(
        name=name,
        product_type=product_type,
        status=status,
        is_deleted=is_deleted,
    )


async def _create_option(
    product: Product,
    *,
    duration: int = 90,
    participants: int = 2,
    day_type: DayType = DayType.WEEKDAY,
    price: Decimal = Decimal("12.34"),
    is_deleted: bool = False,
) -> ExperienceOption:
    return await ExperienceOption.create(
        product=product,
        duration=duration,
        participants=participants,
        day_type=day_type,
        price=price,
        is_deleted=is_deleted,
    )


async def _post_order(
    client: AsyncClient,
    auth_user: dict,
    *,
    items: list[dict],
    remark: str | None = None,
) -> object:
    payload: dict[str, object] = {"items": items}
    if remark is not None:
        payload["remark"] = remark
    return await client.post(
        "/api/v1/orders",
        json=payload,
        headers=_headers(auth_user),
    )


async def _assert_no_order_side_effects() -> None:
    assert await Order.all().count() == 0
    assert await OrderItem.all().count() == 0
    assert await AuditLog.filter(target_type="order").count() == 0


async def test_multiple_options_use_exact_server_amounts_and_immutable_snapshots(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    """多 Option 金额按 Decimal 精确计算，后续目录修改不改变订单快照。"""

    product = await _create_product(name="原始拼豆体验")
    weekday = await _create_option(
        product,
        duration=60,
        participants=1,
        price=Decimal("0.10"),
    )
    holiday = await _create_option(
        product,
        duration=120,
        participants=4,
        day_type=DayType.HOLIDAY,
        price=Decimal("0.20"),
    )

    response = await _post_order(
        client,
        auth_user,
        items=[
            {
                "product_id": product.id,
                "experience_option_id": weekday.id,
                "quantity": 3,
            },
            {
                "product_id": product.id,
                "experience_option_id": holiday.id,
                "quantity": 2,
            },
        ],
        remark="  保留两侧之外的备注  ",
    )

    assert response.status_code == 201, response.text
    created = response.json()["data"]
    assert created["total_amount"] == "0.70"
    assert created["remark"] == "保留两侧之外的备注"
    assert [item["subtotal"] for item in created["items"]] == ["0.30", "0.40"]
    assert [item["product_price"] for item in created["items"]] == ["0.10", "0.20"]
    assert created["items"][0]["product_name"] == "原始拼豆体验"
    assert created["items"][0]["option_duration_minutes"] == 60
    assert created["items"][1]["option_day_type"] == {
        "value": "holiday",
        "label": "节假日",
    }

    product.name = "已修改的目录名称"
    weekday.duration = 180
    weekday.price = Decimal("99.99")
    await product.save(update_fields=["name", "updated_at"])
    await weekday.save(update_fields=["duration", "price", "updated_at"])

    detail_response = await client.get(
        f"/api/v1/orders/{created['id']}",
        headers=_headers(auth_user),
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["total_amount"] == "0.70"
    assert detail["items"][0]["product_name"] == "原始拼豆体验"
    assert detail["items"][0]["product_price"] == "0.10"
    assert detail["items"][0]["option_duration_minutes"] == 60


@pytest.mark.parametrize(
    ("status", "is_deleted"),
    [
        (ProductStatus.DRAFT, False),
        (ProductStatus.OFFLINE, False),
        (ProductStatus.ONLINE, True),
    ],
)
async def test_unavailable_product_is_rejected_without_partial_writes(
    client: AsyncClient,
    auth_user: dict,
    status: ProductStatus,
    is_deleted: bool,
) -> None:
    product = await _create_product(status=status, is_deleted=is_deleted)
    option = await _create_option(product)

    response = await _post_order(
        client,
        auth_user,
        items=[
            {
                "product_id": product.id,
                "experience_option_id": option.id,
                "quantity": 1,
            }
        ],
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": 42231,
        "message": "Order product is unavailable",
        "data": {"product_id": product.id},
    }
    await _assert_no_order_side_effects()


async def test_missing_product_is_rejected_without_partial_writes(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    response = await _post_order(
        client,
        auth_user,
        items=[
            {
                "product_id": 99999,
                "experience_option_id": 99999,
                "quantity": 1,
            }
        ],
    )

    assert response.status_code == 422
    assert response.json()["code"] == 42231
    assert response.json()["data"] == {"product_id": 99999}
    await _assert_no_order_side_effects()


@pytest.mark.parametrize("option_case", ["missing", "deleted", "wrong_product"])
async def test_unavailable_option_is_rejected_without_partial_writes(
    client: AsyncClient,
    auth_user: dict,
    option_case: str,
) -> None:
    product = await _create_product(name="目标体验")
    if option_case == "missing":
        option_id = 99999
    elif option_case == "deleted":
        option_id = (await _create_option(product, is_deleted=True)).id
    else:
        other_product = await _create_product(name="其他体验")
        option_id = (await _create_option(other_product)).id

    response = await _post_order(
        client,
        auth_user,
        items=[
            {
                "product_id": product.id,
                "experience_option_id": option_id,
                "quantity": 1,
            }
        ],
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": 42232,
        "message": "Order experience option is unavailable",
        "data": {
            "product_id": product.id,
            "experience_option_id": option_id,
        },
    }
    await _assert_no_order_side_effects()


async def test_kit_ordering_is_rejected_and_stock_is_untouched(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    kit = await _create_product(
        name="暂不可下单套装",
        product_type=ProductType.KIT,
    )
    kit_data = await ProductKit.create(
        product=kit,
        price=Decimal("66.00"),
        stock=8,
    )

    response = await _post_order(
        client,
        auth_user,
        items=[
            {
                "product_id": kit.id,
                "experience_option_id": 99999,
                "quantity": 2,
            }
        ],
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": 40922,
        "message": "Kit ordering requires inventory support",
        "data": {"product_id": kit.id, "required_phase": "4.3"},
    }
    await kit_data.refresh_from_db()
    assert kit_data.stock == 8
    await _assert_no_order_side_effects()


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {
            "items": [
                {"product_id": index, "experience_option_id": index, "quantity": 1}
                for index in range(1, 12)
            ]
        },
        {
            "items": [
                {"product_id": 1, "experience_option_id": 1, "quantity": 1},
                {"product_id": 1, "experience_option_id": 1, "quantity": 2},
            ]
        },
        {"items": [{"product_id": 1, "experience_option_id": 1, "quantity": 0}]},
        {"items": [{"product_id": 1, "experience_option_id": 1, "quantity": 100}]},
        {"items": [{"product_id": True, "experience_option_id": 1, "quantity": 1}]},
        {"items": [{"product_id": 1, "experience_option_id": 1, "quantity": "1"}]},
        {
            "items": [{"product_id": 1, "experience_option_id": 1, "quantity": 1}],
            "total_amount": "0.01",
        },
        {
            "items": [
                {
                    "product_id": 1,
                    "experience_option_id": 1,
                    "quantity": 1,
                    "product_price": "0.01",
                }
            ]
        },
        {
            "items": [{"product_id": 1, "experience_option_id": 1, "quantity": 1}],
            "user_id": 999,
            "status": "paid",
        },
        {
            "items": [{"product_id": 1, "experience_option_id": 1, "quantity": 1}],
            "remark": "x" * 501,
        },
    ],
)
async def test_invalid_or_forged_create_body_returns_unified_422_before_writes(
    client: AsyncClient,
    auth_user: dict,
    payload: dict,
) -> None:
    response = await client.post(
        "/api/v1/orders",
        json=payload,
        headers=_headers(auth_user),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 422
    assert body["message"] == "Validation failed"
    assert body["data"]["errors"]
    await _assert_no_order_side_effects()


async def test_quantity_and_remark_boundaries_are_accepted(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    product = await _create_product()
    first = await _create_option(product, price=Decimal("1.00"))
    second = await _create_option(
        product,
        duration=120,
        price=Decimal("2.00"),
    )

    response = await _post_order(
        client,
        auth_user,
        items=[
            {
                "product_id": product.id,
                "experience_option_id": first.id,
                "quantity": 1,
            },
            {
                "product_id": product.id,
                "experience_option_id": second.id,
                "quantity": 99,
            },
        ],
        remark="界" * 500,
    )

    assert response.status_code == 201, response.text
    assert response.json()["data"]["total_amount"] == "199.00"
    assert response.json()["data"]["remark"] == "界" * 500


@pytest.mark.parametrize("remark", ["", "   "])
async def test_empty_or_whitespace_remark_is_normalized_to_null(
    client: AsyncClient,
    auth_user: dict,
    remark: str,
) -> None:
    product = await _create_product()
    option = await _create_option(product)

    response = await _post_order(
        client,
        auth_user,
        items=[
            {
                "product_id": product.id,
                "experience_option_id": option.id,
                "quantity": 1,
            }
        ],
        remark=remark,
    )

    assert response.status_code == 201
    assert response.json()["data"]["remark"] is None
