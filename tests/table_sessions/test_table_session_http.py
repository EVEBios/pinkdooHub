import logging
import uuid
from decimal import Decimal

from httpx import AsyncClient

from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductType
from app.common.enums.user import UserRole
from app.core.security import create_access_token
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.table_session import StoreTable, TableOccupancy, TableSession
from app.models.user import User
from app.models.wallet import WalletAccount
from app.tasks.table_bootstrap import seed_tables
from app.repositories.table_session_repo import TableSessionRepository


def _headers(user: User, *, key: str | None = None) -> dict[str, str]:
    token = create_access_token(
        user.id,
        uuid.uuid4().hex,
        auth_version=user.auth_version,
    )
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


async def _user(name: str, *, role: UserRole = UserRole.USER) -> User:
    return await User.create(
        username=name,
        password="hashed-password",
        nickname=name,
        role=role.value,
    )


async def _experience_order(user: User, *, sequence: int = 4) -> Order:
    order = await Order.create(
        order_no=f"OD{sequence:026d}",
        user=user,
        total_amount=Decimal("80.00"),
        status=OrderStatus.PENDING.value,
    )
    for item_sequence, duration in enumerate((60, 120, 120), start=1):
        product = await Product.create(
            name=f"HTTP 桌台体验 {item_sequence}-{duration}",
            product_type=ProductType.EXPERIENCE,
        )
        option = await ExperienceOption.create(
            product=product,
            duration=duration,
            participants=2,
            day_type=DayType.WEEKDAY,
            price=Decimal("20.00"),
        )
        await OrderItem.create(
            order=order,
            product=product,
            experience_option=option,
            product_name=product.name,
            product_price=Decimal("20.00"),
            option_duration_minutes=duration,
            option_participants=2,
            option_day_type=DayType.WEEKDAY,
            quantity=2,
            subtotal=Decimal("40.00"),
        )
    return order


async def test_public_claim_wallet_timer_and_admin_visibility(client: AsyncClient) -> None:
    await seed_tables(TableSessionRepository())
    table = await StoreTable.get(table_no="T01")
    customer = await _user("table-http-customer")
    admin = await _user("table-http-admin", role=UserRole.ADMIN)
    await WalletAccount.create(user=customer, balance=Decimal("500.00"))
    order = await _experience_order(customer)

    resolved = await client.get(f"/api/v1/table-codes/{table.qr_token}")
    assert resolved.status_code == 200
    assert resolved.json()["data"] == {
        "table_no": "T01",
        "display_name": "T01号桌",
        "is_enabled": True,
        "is_available": True,
    }
    assert "qr_token" not in resolved.text

    unauthorized = await client.get("/api/v1/table-sessions/eligible-orders")
    assert unauthorized.status_code == 401

    customer_headers = _headers(customer, key="http-table-claim")
    eligible = await client.get(
        "/api/v1/table-sessions/eligible-orders",
        headers=customer_headers,
    )
    assert eligible.status_code == 200
    groups = eligible.json()["data"]["items"][0]["duration_groups"]
    assert [group["duration_minutes"] for group in groups] == [60, 120]

    created = await client.post(
        "/api/v1/table-sessions",
        headers=customer_headers,
        json={"qr_token": table.qr_token, "order_id": order.id},
    )
    assert created.status_code == 201
    session = created.json()["data"]
    assert session["status"]["value"] == "awaiting_payment"
    assert session["timers"] == []

    other_customer = await _user("table-http-other-customer")
    hidden = await client.get(
        f"/api/v1/orders/{order.id}/table-session",
        headers=_headers(other_customer),
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == 40411
    assert session["session_no"] not in hidden.text

    payment_headers = _headers(customer, key="http-table-wallet")
    payment_headers["Table-Session-No"] = session["session_no"]
    paid = await client.post(
        f"/api/v1/orders/{order.id}/payments/wallet",
        headers=payment_headers,
    )
    assert paid.status_code == 201

    current = await client.get(
        "/api/v1/table-sessions/current",
        headers=_headers(customer),
    )
    assert current.status_code == 200
    active = current.json()["data"]
    assert active["status"]["value"] == "active"
    assert [timer["duration_minutes"] for timer in active["timers"]] == [60, 120]
    assert all(timer["buffer_minutes"] == 10 for timer in active["timers"])

    denied = await client.get(
        "/api/v1/admin/tables",
        headers=_headers(customer),
    )
    assert denied.status_code == 403
    admin_tables = await client.get(
        "/api/v1/admin/tables",
        headers=_headers(admin),
    )
    assert admin_tables.status_code == 200
    assert len(admin_tables.json()["data"]["items"]) == 30
    assert admin_tables.json()["data"]["items"][0]["state"] == "active"

    completed = await client.patch(
        f"/api/v1/admin/orders/{order.id}/complete",
        headers=_headers(admin),
    )
    assert completed.status_code == 200
    assert not await TableOccupancy.filter(order_id=order.id).exists()
    completed_session = await TableSession.get(order_id=order.id)
    assert completed_session.close_reason == "order_completed"

    refund_order = await _experience_order(customer, sequence=5)
    table_two = await StoreTable.get(table_no="T02")
    refund_claim = await client.post(
        "/api/v1/table-sessions",
        headers=_headers(customer, key="http-refund-claim"),
        json={"qr_token": table_two.qr_token, "order_id": refund_order.id},
    )
    refund_session = refund_claim.json()["data"]
    refund_payment_headers = _headers(customer, key="http-refund-wallet")
    refund_payment_headers["Table-Session-No"] = refund_session["session_no"]
    assert (await client.post(
        f"/api/v1/orders/{refund_order.id}/payments/wallet",
        headers=refund_payment_headers,
    )).status_code == 201
    refunded = await client.post(
        f"/api/v1/admin/orders/{refund_order.id}/refunds",
        headers=_headers(admin, key="http-table-refund"),
        json={"reason": "顾客现场退款"},
    )
    assert refunded.status_code == 201
    assert not await TableOccupancy.filter(order_id=refund_order.id).exists()
    refunded_session = await TableSession.get(order_id=refund_order.id)
    assert refunded_session.close_reason == "refunded"

    cancel_order = await _experience_order(customer, sequence=6)
    table_three = await StoreTable.get(table_no="T03")
    cancel_claim = await client.post(
        "/api/v1/table-sessions",
        headers=_headers(customer, key="http-cancel-claim"),
        json={"qr_token": table_three.qr_token, "order_id": cancel_order.id},
    )
    assert cancel_claim.status_code == 201
    cancelled = await client.patch(
        f"/api/v1/orders/{cancel_order.id}/cancel",
        headers=_headers(customer),
    )
    assert cancelled.status_code == 200
    assert not await TableOccupancy.filter(order_id=cancel_order.id).exists()
    cancelled_session = await TableSession.get(order_id=cancel_order.id)
    assert cancelled_session.close_reason == "order_cancelled"


async def test_table_request_schemas_are_strict(client: AsyncClient) -> None:
    user = await _user("table-http-strict")
    response = await client.post(
        "/api/v1/table-sessions",
        headers=_headers(user, key="strict-table"),
        json={"qr_token": "A" * 32, "order_id": 1, "extra": True},
    )
    assert response.status_code == 422
    assert response.json()["code"] == 422

    admin = await _user("table-http-strict-admin", role=UserRole.ADMIN)
    non_utc = await client.get(
        "/api/v1/admin/table-sessions"
        "?claimed_from=2026-09-10T12%3A00%3A00%2B08%3A00",
        headers=_headers(admin),
    )
    assert non_utc.status_code == 422
    assert non_utc.json()["code"] == 422


async def test_missing_table_code_is_redacted_from_application_logs(
    client: AsyncClient,
    caplog,
) -> None:
    qr_token = "SensitivePublicTableCode12345678"
    assert len(qr_token) == 32

    with caplog.at_level(logging.WARNING, logger="app.middleware.exception"):
        response = await client.get(f"/api/v1/table-codes/{qr_token}")

    assert response.status_code == 404
    assert qr_token not in caplog.text
    assert "/api/v1/table-codes/<redacted>" in caplog.text
