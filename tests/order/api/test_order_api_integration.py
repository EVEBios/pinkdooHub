"""Order API 的真实 JWT、SQLite、Service、Mapper 与审计流程测试。"""

import json
import uuid
from decimal import Decimal

from httpx import AsyncClient

from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.user import UserRole
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.order import Order
from app.models.product import Product
from app.models.user import User


def _headers(token: str, *, ip: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if ip is not None:
        headers["X-Forwarded-For"] = ip
    return headers


async def _create_admin() -> tuple[User, str]:
    admin = await User.create(
        username="order-api-admin",
        password="hashed-password",
        nickname="订单管理员",
        phone="13900139000",
        role=UserRole.ADMIN,
    )
    return admin, create_access_token(admin.id, str(uuid.uuid4()))


async def _create_online_option() -> tuple[Product, ExperienceOption]:
    product = await Product.create(
        name="HTTP 真实拼豆体验",
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.ONLINE,
    )
    option = await ExperienceOption.create(
        product=product,
        duration=90,
        participants=2,
        day_type=DayType.HOLIDAY,
        price=Decimal("88.50"),
    )
    return product, option


async def test_complete_order_http_lifecycle_and_visibility(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    """创建、查询、权限、支付、完成与审计通过真实 HTTP 链路贯通。"""

    user_token = auth_user["token"]
    product, option = await _create_online_option()
    admin, admin_token = await _create_admin()

    created_response = await client.post(
        "/api/v1/orders",
        json={
            "items": [
                {
                    "product_id": product.id,
                    "experience_option_id": option.id,
                    "quantity": 2,
                }
            ],
            "remark": "真实备注不得进入审计",
        },
        headers=_headers(user_token, ip="203.0.113.10, 10.0.0.1"),
    )

    assert created_response.status_code == 201
    created_data = created_response.json()["data"]
    order_id = created_data["id"]
    assert created_response.json()["message"] == "Order created"
    assert created_data["total_amount"] == "177.00"
    assert created_data["status"] == {"value": "pending", "label": "待支付"}
    assert created_data["items"][0]["product_name"] == "HTTP 真实拼豆体验"
    assert "user_id" not in created_data

    user_list = await client.get(
        "/api/v1/orders?status=pending",
        headers=_headers(user_token),
    )
    assert user_list.status_code == 200
    assert user_list.json()["data"]["items"][0]["id"] == order_id
    assert user_list.json()["data"]["items"][0]["item_count"] == 1

    normal_admin_attempt = await client.get(
        "/api/v1/admin/orders",
        headers=_headers(user_token),
    )
    assert normal_admin_attempt.status_code == 403

    admin_list = await client.get(
        f"/api/v1/admin/orders?order_no={created_data['order_no']}",
        headers=_headers(admin_token),
    )
    assert admin_list.status_code == 200
    assert admin_list.json()["data"]["items"][0]["user_nickname"] == "Alice"

    admin_detail = await client.get(
        f"/api/v1/admin/orders/{order_id}",
        headers=_headers(admin_token),
    )
    assert admin_detail.status_code == 200
    assert admin_detail.json()["data"]["user_id"] == auth_user["user"]["id"]
    assert "phone" not in admin_detail.json()["data"]

    paid = await client.patch(
        f"/api/v1/admin/orders/{order_id}/paid",
        headers=_headers(admin_token, ip="198.51.100.70"),
    )
    assert paid.status_code == 200
    assert paid.json()["data"]["status"]["value"] == "paid"

    completed = await client.patch(
        f"/api/v1/admin/orders/{order_id}/complete",
        headers=_headers(admin_token, ip="198.51.100.71"),
    )
    assert completed.status_code == 200
    assert completed.json()["message"] == "Order completed"
    assert completed.json()["data"]["status"]["value"] == "completed"

    repeated_complete = await client.patch(
        f"/api/v1/admin/orders/{order_id}/complete",
        headers=_headers(admin_token),
    )
    assert repeated_complete.status_code == 409
    assert repeated_complete.json()["data"] == {
        "operation": "complete",
        "current_status": "completed",
        "required_status": "paid",
    }

    audit_response = await client.get(
        f"/api/v1/admin/orders/{order_id}/audit-logs",
        headers=_headers(admin_token),
    )
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["data"]["items"]
    assert [item["action"] for item in audit_items] == [
        "COMPLETE_ORDER",
        "MARK_ORDER_PAID",
        "CREATE_ORDER",
    ]
    assert audit_items[0]["operator_id"] == admin.id
    assert audit_items[0]["ip_address"] == "198.51.100.71"
    assert audit_items[1]["ip_address"] == "198.51.100.70"
    assert audit_items[2]["ip_address"] == "203.0.113.10"
    assert "真实备注" not in "".join(item["description"] or "" for item in audit_items)
    assert json.loads(audit_items[1]["description"]) == {
        "before_status": "pending",
        "after_status": "paid",
    }
    assert (await Order.get(id=order_id)).status == OrderStatus.COMPLETED
    assert await AuditLog.filter(target_type="order", target_id=order_id).count() == 3


async def test_owner_cancel_and_foreign_visibility_through_http(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    """他人详情与取消均为 404，所属用户取消成功且只写一条审计。"""

    product, option = await _create_online_option()
    owner_token = auth_user["token"]
    created = await client.post(
        "/api/v1/orders",
        json={
            "items": [
                {
                    "product_id": product.id,
                    "experience_option_id": option.id,
                    "quantity": 1,
                }
            ]
        },
        headers=_headers(owner_token),
    )
    order_id = created.json()["data"]["id"]
    stranger = await User.create(
        username="order-api-stranger",
        password="hashed-password",
        nickname="陌生用户",
        phone="13900139001",
    )
    stranger_token = create_access_token(stranger.id, str(uuid.uuid4()))

    hidden_detail = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=_headers(stranger_token),
    )
    hidden_cancel = await client.patch(
        f"/api/v1/orders/{order_id}/cancel",
        headers=_headers(stranger_token),
    )

    assert hidden_detail.status_code == 404
    assert hidden_cancel.status_code == 404
    assert hidden_detail.json()["code"] == 40411
    assert hidden_cancel.json()["code"] == 40411

    cancelled = await client.patch(
        f"/api/v1/orders/{order_id}/cancel",
        headers=_headers(owner_token, ip="192.0.2.8"),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"]["value"] == "cancelled"
    assert (await Order.get(id=order_id)).status == OrderStatus.CANCELLED
    audits = await AuditLog.filter(
        target_type="order",
        target_id=order_id,
    ).order_by("id")
    assert [audit.action for audit in audits] == ["CREATE_ORDER", "CANCEL_ORDER"]
    assert audits[1].ip_address == "192.0.2.8"


async def test_invalid_forwarded_ip_cannot_break_order_audit_write(
    client: AsyncClient,
    auth_user: dict,
) -> None:
    """非法代理头回退到直连地址，不得让创建和审计事务失败。"""

    product, option = await _create_online_option()

    response = await client.post(
        "/api/v1/orders",
        json={
            "items": [
                {
                    "product_id": product.id,
                    "experience_option_id": option.id,
                    "quantity": 1,
                }
            ]
        },
        headers=_headers(auth_user["token"], ip="malformed-" * 30),
    )

    assert response.status_code == 201
    order_id = response.json()["data"]["id"]
    audit = await AuditLog.get(target_type="order", target_id=order_id)
    assert audit.action == "CREATE_ORDER"
    assert audit.ip_address == "127.0.0.1"
