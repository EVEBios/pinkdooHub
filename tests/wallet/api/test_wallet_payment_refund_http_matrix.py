"""Wallet/Payment/Refund HTTP 认证、状态、幂等与零写入矩阵。"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.common.enums.inventory import InventoryTransactionType
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.enums.user import UserRole, UserStatus
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    WalletStatus,
    WalletTransactionType,
)
from app.core.security import create_access_token
from app.models.audit_log import AuditLog
from app.models.experience_option import ExperienceOption
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement, RechargeOrder, Refund
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction


def _number(prefix: str, sequence: int) -> str:
    return f"{prefix}{sequence:026d}"


def _headers(user: User, *, idempotency_key: str | None = None) -> dict[str, str]:
    token = create_access_token(
        user.id,
        uuid.uuid4().hex,
        auth_version=user.auth_version,
    )
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _create_user(
    username: str,
    *,
    role: UserRole = UserRole.USER,
    status: UserStatus = UserStatus.NORMAL,
) -> User:
    return await User.create(
        username=username,
        password="hashed-password",
        nickname=username,
        role=role.value,
        status=status.value,
    )


async def _create_order(
    user: User,
    *,
    sequence: int,
    amount: Decimal = Decimal("50.00"),
    status: OrderStatus = OrderStatus.PENDING,
) -> Order:
    return await Order.create(
        order_no=_number("OD", sequence),
        user=user,
        total_amount=amount,
        status=status.value,
    )


async def _seed_refundable_order(
    *,
    user: User,
    wallet: WalletAccount,
    sequence: int,
    status: OrderStatus,
    product_type: ProductType,
) -> tuple[Order, ProductKit | None]:
    amount = Decimal("50.00")
    order = await _create_order(
        user,
        sequence=sequence,
        amount=amount,
        status=status,
    )
    product = await Product.create(
        name=f"HTTP 退款商品 {sequence}",
        product_type=product_type,
    )
    kit: ProductKit | None = None
    option: ExperienceOption | None = None
    if product_type is ProductType.KIT:
        kit = await ProductKit.create(
            product=product,
            price=amount,
            stock=6,
        )
    else:
        option = await ExperienceOption.create(
            product=product,
            duration=60,
            participants=1,
            day_type=DayType.WEEKDAY,
            price=amount,
        )
    await OrderItem.create(
        order=order,
        product=product,
        experience_option=option,
        option_duration_minutes=option.duration if option is not None else None,
        option_participants=option.participants if option is not None else None,
        option_day_type=option.day_type if option is not None else None,
        product_name=product.name,
        product_price=amount,
        quantity=1,
        subtotal=amount,
    )
    payment = await Payment.create(
        payment_no=_number("PY", sequence),
        user=user,
        purpose=PaymentPurpose.ORDER,
        method=PaymentMethod.WALLET,
        amount=amount,
        status=PaymentStatus.SUCCEEDED,
        order=order,
        recharge_order=None,
        idempotency_key=f"payment:http:seed:{sequence}",
        succeeded_at=datetime.now(timezone.utc),
    )
    await PaymentSettlement.create(
        payment=payment,
        order=order,
        amount=amount,
    )
    await WalletTransaction.create(
        wallet_account=wallet,
        transaction_type=WalletTransactionType.ORDER_PAYMENT,
        change_amount=-amount,
        before_balance=wallet.balance + amount,
        after_balance=wallet.balance,
        source_type="order",
        source_id=order.id,
        operator=user,
        reason="Order paid with wallet balance",
        idempotency_key=f"wallet:http:seed:{sequence}",
    )
    return order, kit


async def test_registration_creates_zero_wallet_and_member_endpoints(
    client: AsyncClient,
) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "wallet-http-member",
            "password": "12345678",
            "nickname": "钱包会员",
            "phone": "13800660001",
        },
    )
    assert registered.status_code == 201
    user = await User.get(username="wallet-http-member")
    [wallet] = await WalletAccount.filter(user_id=user.id)

    summary = await client.get("/api/v1/wallet", headers=_headers(user))
    transactions = await client.get(
        "/api/v1/wallet/transactions",
        headers=_headers(user),
    )

    assert wallet.balance == Decimal("0.00")
    assert wallet.status is WalletStatus.ACTIVE
    assert summary.status_code == 200
    assert summary.json()["data"]["wallet"] == {
        "wallet_id": wallet.id,
        "user_id": user.id,
        "balance": "0.00",
        "balance_limit": "1000.00",
        "status": "active",
        "capabilities": {
            "topup_enabled": False,
            "wallet_payment_enabled": True,
            "refund_enabled": True,
        },
        "created_at": wallet.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": wallet.updated_at.isoformat().replace("+00:00", "Z"),
    }
    assert summary.json()["data"]["user"]["username"] == user.username
    assert "password" not in summary.text
    assert transactions.status_code == 200
    assert transactions.json()["data"] == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
        "pages": 0,
    }


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.SUPER_ADMIN])
async def test_customer_wallet_and_payment_endpoints_reject_staff_roles(
    client: AsyncClient,
    role: UserRole,
) -> None:
    staff = await _create_user(f"wallet-http-customer-boundary-{role.value}", role=role)
    headers = _headers(staff, idempotency_key="staff-customer-endpoint")

    responses = [
        await client.get("/api/v1/wallet", headers=headers),
        await client.get("/api/v1/wallet/transactions", headers=headers),
        await client.post(
            "/api/v1/wallet/recharges",
            headers=headers,
            json={"amount": "10.00"},
        ),
        await client.get("/api/v1/orders/999/financials", headers=headers),
        await client.post(
            "/api/v1/orders/999/payments/wallet",
            headers=headers,
        ),
        await client.post(
            "/api/v1/orders/999/payments/wechat",
            headers=headers,
        ),
    ]

    assert [response.status_code for response in responses] == [403] * len(responses)
    assert all(response.json()["code"] == 403 for response in responses)


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.SUPER_ADMIN])
async def test_admin_plus_can_adjust_and_both_sides_can_query_transactions(
    client: AsyncClient,
    role: UserRole,
) -> None:
    operator = await _create_user(f"wallet-http-operator-{role.value}", role=role)
    target = await _create_user(f"wallet-http-target-{role.value}")
    wallet = await WalletAccount.create(user=target)
    path = f"/api/v1/admin/users/{target.id}/wallet-adjustments"

    response = await client.post(
        path,
        headers=_headers(operator, idempotency_key="query-visible"),
        json={"change": "25.00", "reason": "  会员补偿  "},
    )
    member_page = await client.get(
        "/api/v1/wallet/transactions?page=1&page_size=10",
        headers=_headers(target),
    )
    admin_page = await client.get(
        f"/api/v1/admin/users/{target.id}/wallet-transactions?page_size=10",
        headers=_headers(operator),
    )
    admin_summary = await client.get(
        f"/api/v1/admin/users/{target.id}/wallet",
        headers=_headers(operator),
    )

    assert response.status_code == 201
    assert response.json()["data"]["wallet"]["balance"] == "25.00"
    for page in (member_page, admin_page):
        assert page.status_code == 200
        assert page.json()["data"]["total"] == 1
        [item] = page.json()["data"]["items"]
        assert item["transaction_type"] == "admin_adjustment"
        assert item["change_amount"] == "25.00"
        assert item["before_balance"] == "0.00"
        assert item["after_balance"] == "25.00"
        assert item["operator_id"] == operator.id
        assert item["operator_nickname"] == operator.nickname
        assert item["reason"] == "会员补偿"
        assert "idempotency_key" not in item
    assert admin_summary.status_code == 200
    assert admin_summary.json()["data"]["wallet"]["wallet_id"] == wallet.id


async def test_wallet_admin_http_permission_boundaries_and_disabled_correction(
    client: AsyncClient,
) -> None:
    admin = await _create_user("wallet-http-boundary-admin", role=UserRole.ADMIN)
    non_admin = await _create_user("wallet-http-boundary-user")
    target = await _create_user("wallet-http-boundary-target")
    wallet = await WalletAccount.create(user=target)
    path = f"/api/v1/admin/users/{target.id}/wallet-adjustments"

    forbidden = await client.post(
        path,
        headers=_headers(non_admin, idempotency_key="forbidden"),
        json={"change": "1.00", "reason": "无权限"},
    )
    underflow = await client.post(
        path,
        headers=_headers(admin, idempotency_key="underflow"),
        json={"change": "-0.01", "reason": "越过下界"},
    )
    invalid_zero = await client.post(
        path,
        headers=_headers(admin, idempotency_key="zero"),
        json={"change": "0.00", "reason": "零变化"},
    )
    first = await client.post(
        path,
        headers=_headers(admin, idempotency_key="fill"),
        json={"change": "1000.00", "reason": "填满余额"},
    )
    replay = await client.post(
        path,
        headers=_headers(admin, idempotency_key="  fill  "),
        json={"change": "1000.00", "reason": "  填满余额  "},
    )
    conflict = await client.post(
        path,
        headers=_headers(admin, idempotency_key="fill"),
        json={"change": "1000.00", "reason": "不同原因"},
    )
    overflow = await client.post(
        path,
        headers=_headers(admin, idempotency_key="overflow"),
        json={"change": "0.01", "reason": "越过上界"},
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 403
    assert underflow.status_code == 409
    assert underflow.json()["code"] == 40941
    assert invalid_zero.status_code == 422
    assert invalid_zero.json()["code"] == 422
    assert first.status_code == 201
    assert first.json()["data"]["wallet"]["balance"] == "1000.00"
    assert replay.status_code == 200
    assert replay.json()["data"] == first.json()["data"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 40943
    assert overflow.status_code == 409
    assert overflow.json()["code"] == 40941

    await wallet.refresh_from_db()
    assert wallet.balance == Decimal("1000.00")
    assert await WalletTransaction.all().count() == 1
    assert await AuditLog.filter(action="ADJUST_WALLET").count() == 1

    disabled = await _create_user(
        "wallet-http-disabled-target",
        status=UserStatus.DISABLED,
    )
    disabled_wallet = await WalletAccount.create(user=disabled)
    correction = await client.post(
        f"/api/v1/admin/users/{disabled.id}/wallet-adjustments",
        headers=_headers(admin, idempotency_key="disabled"),
        json={"change": "1.00", "reason": "禁用用户人工调账"},
    )
    assert correction.status_code == 201
    assert correction.json()["data"]["wallet"]["balance"] == "1.00"
    await disabled_wallet.refresh_from_db()
    assert disabled_wallet.balance == Decimal("1.00")


async def test_wallet_payment_http_success_replay_financials_and_conflicts(
    client: AsyncClient,
) -> None:
    user = await _create_user("wallet-http-payment-user")
    wallet = await WalletAccount.create(user=user, balance=Decimal("80.00"))
    order = await _create_order(user, sequence=500)
    path = f"/api/v1/orders/{order.id}/payments/wallet"

    first = await client.post(
        path,
        headers=_headers(user, idempotency_key="pay-http"),
    )
    replay = await client.post(
        path,
        headers=_headers(user, idempotency_key="pay-http"),
    )
    second_key = await client.post(
        path,
        headers=_headers(user, idempotency_key="pay-http-second"),
    )
    financials = await client.get(
        f"/api/v1/orders/{order.id}/financials",
        headers=_headers(user),
    )

    assert first.status_code == 201
    assert first.json()["message"] == "Order paid with wallet"
    assert first.json()["data"]["order_status"]["value"] == "paid"
    assert first.json()["data"]["post_payment_balance"] == "30.00"
    assert first.json()["data"]["payment"]["method"] == "wallet"
    assert first.json()["data"]["payment"]["amount"] == "50.00"
    assert first.json()["data"]["payment"]["status"] == "succeeded"
    assert replay.status_code == 200
    assert replay.json()["data"] == first.json()["data"]
    assert second_key.status_code == 409
    assert second_key.json()["code"] == 40921
    assert financials.status_code == 200
    assert financials.json()["data"]["payment"]["id"] == (
        first.json()["data"]["payment"]["id"]
    )
    assert financials.json()["data"]["refund"] is None

    await wallet.refresh_from_db()
    await order.refresh_from_db()
    assert wallet.balance == Decimal("30.00")
    assert OrderStatus(order.status) is OrderStatus.PAID
    assert await Payment.all().count() == 1
    assert await PaymentSettlement.all().count() == 1
    assert await WalletTransaction.filter(
        transaction_type=WalletTransactionType.ORDER_PAYMENT
    ).count() == 1


async def test_admin_assisted_wallet_order_creates_real_order_and_replays(
    client: AsyncClient,
) -> None:
    admin = await _create_user("wallet-http-assisted-admin", role=UserRole.ADMIN)
    customer = await _create_user("wallet-http-assisted-customer")
    wallet = await WalletAccount.create(
        user=customer,
        balance=Decimal("100.00"),
    )
    product = await Product.create(
        name="HTTP 代客扣款套装",
        product_type=ProductType.KIT,
        status=ProductStatus.ONLINE,
    )
    kit = await ProductKit.create(
        product=product,
        price=Decimal("25.00"),
        stock=3,
    )
    path = f"/api/v1/admin/users/{customer.id}/wallet-orders"
    body = {
        "items": [
            {
                "product_id": product.id,
                "experience_option_id": None,
                "quantity": 2,
            }
        ],
        "remark": "门店代客下单",
    }

    first = await client.post(
        path,
        headers=_headers(admin, idempotency_key="assisted-http"),
        json=body,
    )
    replay = await client.post(
        path,
        headers=_headers(admin, idempotency_key="assisted-http"),
        json=body,
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"] == first.json()["data"]
    data = first.json()["data"]
    assert data["order"]["user_id"] == customer.id
    assert data["order"]["status"]["value"] == "paid"
    assert data["order"]["total_amount"] == "50.00"
    assert data["payment"]["method"] == "wallet"
    assert data["payment"]["status"] == "succeeded"
    assert data["post_payment_balance"] == "50.00"

    await wallet.refresh_from_db()
    await kit.refresh_from_db()
    assert wallet.balance == Decimal("50.00")
    assert kit.stock == 1
    assert await Order.all().count() == 1
    assert await Payment.all().count() == 1
    assert await PaymentSettlement.all().count() == 1
    assert await WalletTransaction.all().count() == 1
    assert await InventoryTransaction.all().count() == 1


async def test_wallet_payment_http_insufficient_disabled_and_closed_are_zero_write(
    client: AsyncClient,
) -> None:
    insufficient_user = await _create_user("wallet-http-insufficient")
    insufficient_wallet = await WalletAccount.create(
        user=insufficient_user,
        balance=Decimal("49.99"),
    )
    insufficient_order = await _create_order(insufficient_user, sequence=510)
    insufficient = await client.post(
        f"/api/v1/orders/{insufficient_order.id}/payments/wallet",
        headers=_headers(insufficient_user, idempotency_key="insufficient"),
    )
    assert insufficient.status_code == 409
    assert insufficient.json()["code"] == 40942

    disabled_user = await _create_user(
        "wallet-http-pay-disabled",
        status=UserStatus.DISABLED,
    )
    disabled_wallet = await WalletAccount.create(
        user=disabled_user,
        balance=Decimal("100.00"),
    )
    disabled_order = await _create_order(disabled_user, sequence=511)
    disabled = await client.post(
        f"/api/v1/orders/{disabled_order.id}/payments/wallet",
        headers=_headers(disabled_user, idempotency_key="disabled"),
    )
    assert disabled.status_code == 400
    assert disabled.json()["code"] == 1005

    closed_user = await _create_user("wallet-http-pay-closed")
    closed_wallet = await WalletAccount.create(
        user=closed_user,
        balance=Decimal("100.00"),
        status=WalletStatus.CLOSED,
    )
    closed_order = await _create_order(closed_user, sequence=512)
    closed = await client.post(
        f"/api/v1/orders/{closed_order.id}/payments/wallet",
        headers=_headers(closed_user, idempotency_key="closed"),
    )
    assert closed.status_code == 403
    assert closed.json()["code"] == 403

    for wallet, expected in (
        (insufficient_wallet, Decimal("49.99")),
        (disabled_wallet, Decimal("100.00")),
        (closed_wallet, Decimal("100.00")),
    ):
        await wallet.refresh_from_db()
        assert wallet.balance == expected
    assert not await Payment.all().exists()
    assert not await PaymentSettlement.all().exists()
    assert not await WalletTransaction.all().exists()


@pytest.mark.parametrize(
    ("status", "product_type", "inventory_restored"),
    [
        (OrderStatus.PAID, ProductType.KIT, True),
        (OrderStatus.PAID, ProductType.EXPERIENCE, False),
        (OrderStatus.COMPLETED, ProductType.KIT, False),
    ],
)
async def test_admin_full_refund_http_inventory_matrix_and_replay(
    client: AsyncClient,
    status: OrderStatus,
    product_type: ProductType,
    inventory_restored: bool,
) -> None:
    admin = await _create_user(
        f"refund-http-admin-{status.value}-{product_type.value}",
        role=UserRole.ADMIN,
    )
    user = await _create_user(
        f"refund-http-user-{status.value}-{product_type.value}"
    )
    wallet = await WalletAccount.create(user=user, balance=Decimal("950.00"))
    sequence = 600 + status.value * 10 + (
        1 if product_type is ProductType.KIT else 2
    )
    order, kit = await _seed_refundable_order(
        user=user,
        wallet=wallet,
        sequence=sequence,
        status=status,
        product_type=product_type,
    )
    path = f"/api/v1/admin/orders/{order.id}/refunds"

    first = await client.post(
        path,
        headers=_headers(admin, idempotency_key="refund-http"),
        json={"reason": "  顾客申请退款  "},
    )
    replay = await client.post(
        path,
        headers=_headers(admin, idempotency_key="refund-http"),
        json={"reason": "顾客申请退款"},
    )
    financials = await client.get(
        f"/api/v1/orders/{order.id}/financials",
        headers=_headers(user),
    )

    assert first.status_code == 201
    assert first.json()["message"] == "Order refunded"
    assert first.json()["data"]["status"] == "succeeded"
    assert first.json()["data"]["amount"] == "50.00"
    assert first.json()["data"]["method"] == "wallet"
    assert first.json()["data"]["inventory_restored"] is inventory_restored
    assert replay.status_code == 200
    assert replay.json()["data"] == first.json()["data"]
    assert financials.status_code == 200
    assert financials.json()["data"]["order_status"]["value"] == (
        "paid" if status is OrderStatus.PAID else "completed"
    )
    assert financials.json()["data"]["refund"]["inventory_restored"] is (
        inventory_restored
    )

    await wallet.refresh_from_db()
    await order.refresh_from_db()
    assert wallet.balance == Decimal("1000.00")
    assert OrderStatus(order.status) is status
    assert await Refund.all().count() == 1
    assert await WalletTransaction.filter(
        transaction_type=WalletTransactionType.REFUND
    ).count() == 1
    assert await InventoryTransaction.filter(
        transaction_type=InventoryTransactionType.ORDER_REFUND_RESTORE
    ).count() == int(inventory_restored)
    if kit is not None:
        await kit.refresh_from_db()
        assert kit.stock == (7 if inventory_restored else 6)


async def test_wechat_entrypoints_return_503_without_creating_financial_facts(
    client: AsyncClient,
) -> None:
    user = await _create_user("wallet-http-wechat-disabled")
    wallet = await WalletAccount.create(user=user, balance=Decimal("10.00"))
    order = await _create_order(user, sequence=700)

    recharge = await client.post(
        "/api/v1/wallet/recharges",
        headers=_headers(user, idempotency_key="wechat-recharge"),
        json={"amount": "100.00"},
    )
    payment = await client.post(
        f"/api/v1/orders/{order.id}/payments/wechat",
        headers=_headers(user, idempotency_key="wechat-payment"),
    )

    assert recharge.status_code == 503
    assert recharge.json() == {
        "code": 503,
        "message": (
            "Wallet top-up is not available until the supervised payment "
            "channel and WeChat merchant account are ready"
        ),
        "data": None,
    }
    assert payment.status_code == 503
    assert payment.json() == {
        "code": 503,
        "message": "WeChat order payment is not available yet",
        "data": None,
    }
    await wallet.refresh_from_db()
    await order.refresh_from_db()
    assert wallet.balance == Decimal("10.00")
    assert OrderStatus(order.status) is OrderStatus.PENDING
    assert not await RechargeOrder.all().exists()
    assert not await Payment.all().exists()
    assert not await PaymentSettlement.all().exists()
    assert not await WalletTransaction.all().exists()


async def test_account_deletion_http_is_blocked_by_balance_then_pending_payment(
    client: AsyncClient,
) -> None:
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "wallet-http-delete",
            "password": "12345678",
            "nickname": "待注销会员",
            "phone": "13800660002",
        },
    )
    assert registered.status_code == 201
    user = await User.get(username="wallet-http-delete")
    wallet = await WalletAccount.get(user_id=user.id)
    wallet.balance = Decimal("1.00")
    await wallet.save(update_fields=["balance", "updated_at"])
    payload = {"confirmation": "DELETE", "password": "12345678"}

    balance_blocked = await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=_headers(user),
        json=payload,
    )
    assert balance_blocked.status_code == 400
    assert balance_blocked.json()["code"] == 1015

    wallet.balance = Decimal("0.00")
    await wallet.save(update_fields=["balance", "updated_at"])
    order = await _create_order(
        user,
        sequence=800,
        status=OrderStatus.COMPLETED,
    )
    await Payment.create(
        payment_no=_number("PY", 800),
        user=user,
        purpose=PaymentPurpose.ORDER,
        method=PaymentMethod.WECHAT,
        amount=order.total_amount,
        status=PaymentStatus.PENDING,
        order=order,
        recharge_order=None,
        idempotency_key="payment:http:delete-pending",
    )
    financial_blocked = await client.request(
        "DELETE",
        "/api/v1/users/me",
        headers=_headers(user),
        json=payload,
    )

    assert financial_blocked.status_code == 400
    assert financial_blocked.json()["code"] == 1015
    await user.refresh_from_db()
    await wallet.refresh_from_db()
    assert UserStatus(user.status) is UserStatus.NORMAL
    assert wallet.status is WalletStatus.ACTIVE
    assert not await AuditLog.filter(action="DELETE_ACCOUNT").exists()
