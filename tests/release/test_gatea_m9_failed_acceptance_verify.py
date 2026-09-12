"""Gate A M9 pre-claim 失败验收只读核验任务。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.common.constants.inventory import (
    INVENTORY_ADMIN_IDEMPOTENCY_PREFIX,
    INVENTORY_ORDER_DEDUCTION_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_DEDUCTION_REASON,
    INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_RESTORE_REASON,
)
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, KitKind, ProductStatus, ProductType
from app.common.enums.table_session import TableSessionStatus
from app.common.enums.user import UserRole
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    RefundStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.models.experience_option import ExperienceOption
from app.models.inventory_transaction import InventoryTransaction
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.models.table_session import StoreTable, TableSession
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.tasks import gatea_m9_failed_acceptance_verify as verifier


CANDIDATE_SHA = "a" * 40
OTHER_CANDIDATE_SHA = "c" * 40
ACCEPTANCE_ATTEMPT_ID = "b" * 32


def _experience_name(acceptance_attempt_id: str) -> str:
    return f"[GATEA-M9] Runtime experience {acceptance_attempt_id[:12]}"


def _kit_name(acceptance_attempt_id: str) -> str:
    return f"[GATEA-M9] Runtime fixed Kit {acceptance_attempt_id[:12]}"


def _kit_supply_key(acceptance_attempt_id: str) -> str:
    return (
        f"{INVENTORY_ADMIN_IDEMPOTENCY_PREFIX}"
        f"gatea-m9-kit-stock-{acceptance_attempt_id}-v1"
    )


@dataclass(frozen=True, slots=True)
class SeededFailure:
    admin: User
    user: User
    order: Order
    experience_product: Product
    kit_product: Product
    kit: ProductKit
    experience_items: tuple[verifier.ExperienceItemExpectation, ...]
    kit_item_id: int


def _number(prefix: str, sequence: int) -> str:
    return f"{prefix}{sequence:026d}"


async def _seed_clean_failure() -> SeededFailure:
    admin = await User.create(
        id=9002,
        username="gatea-m9-super-admin",
        password="hashed-password",
        nickname="Gate A super admin",
        role=UserRole.SUPER_ADMIN.value,
    )
    user = await User.create(
        id=9001,
        username="gatea-m9-failed-acceptance",
        password="hashed-password",
        nickname="Gate A test",
    )
    experience = await Product.create(
        id=9101,
        name=_experience_name(ACCEPTANCE_ATTEMPT_ID),
        description=verifier.EXPECTED_EXPERIENCE_DESCRIPTION,
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.OFFLINE,
    )
    kit_product = await Product.create(
        id=9102,
        name=_kit_name(ACCEPTANCE_ATTEMPT_ID),
        description=verifier.EXPECTED_KIT_DESCRIPTION,
        product_type=ProductType.KIT,
        status=ProductStatus.OFFLINE,
    )
    kit = await ProductKit.create(
        id=9150,
        product=kit_product,
        price=Decimal("1.00"),
        stock=10,
        kit_kind=KitKind.FIXED,
    )
    option_specs = ((9201, 60, 1), (9202, 60, 2), (9203, 120, 1))
    options = [
        await ExperienceOption.create(
            id=option_id,
            product=experience,
            duration=duration,
            participants=participants,
            day_type=DayType.WEEKDAY,
            price=Decimal("1.00"),
        )
        for option_id, duration, participants in option_specs
    ]
    await ProductImage.create(
        id=9251,
        product=experience,
        image_url="/uploads/products/gatea-experience.png",
        is_cover=True,
        sort=0,
    )
    await ProductImage.create(
        id=9252,
        product=kit_product,
        image_url="/uploads/products/gatea-kit.png",
        is_cover=True,
        sort=0,
    )
    for image_id, option in zip((9253, 9254, 9255), options, strict=True):
        await ProductImage.create(
            id=image_id,
            product=experience,
            experience_option=option,
            image_url=f"/uploads/products/gatea-option-{image_id}.png",
            is_cover=False,
            sort=0,
        )
    order = await Order.create(
        id=9301,
        order_no=_number("OD", 1),
        user=user,
        total_amount=Decimal("5.00"),
        status=OrderStatus.CANCELLED.value,
        remark=verifier.EXPECTED_ORDER_REMARK,
    )
    item_specs = (
        (9401, options[0], 60, 2),
        (9402, options[1], 60, 1),
        (9403, options[2], 120, 1),
    )
    expectations: list[verifier.ExperienceItemExpectation] = []
    for item_id, option, duration, quantity in item_specs:
        await OrderItem.create(
            id=item_id,
            order=order,
            product=experience,
            experience_option=option,
            option_duration_minutes=duration,
            option_participants=option.participants,
            option_day_type=option.day_type,
            product_name=experience.name,
            product_price=Decimal("1.00"),
            quantity=quantity,
            subtotal=Decimal(quantity),
        )
        expectations.append(
            verifier.ExperienceItemExpectation(
                order_item_id=item_id,
                option_id=option.id,
                duration_minutes=duration,
                participants=option.participants,
                day_type=option.day_type,
                price=Decimal("1.00"),
                quantity=quantity,
            )
        )
    kit_item_id = 9404
    await OrderItem.create(
        id=kit_item_id,
        order=order,
        product=kit_product,
        product_name=kit_product.name,
        product_price=Decimal("1.00"),
        quantity=1,
        subtotal=Decimal("1.00"),
    )
    await InventoryTransaction.create(
        id=9500,
        product=kit_product,
        transaction_type=InventoryTransactionType.ADMIN_ADJUSTMENT,
        change_quantity=10,
        before_quantity=0,
        after_quantity=10,
        source_type=InventorySourceType.ADMIN,
        source_id=None,
        operator=admin,
        reason=verifier.EXPECTED_KIT_SUPPLY_REASON,
        idempotency_key=_kit_supply_key(ACCEPTANCE_ATTEMPT_ID),
    )
    await InventoryTransaction.create(
        id=9501,
        product=kit_product,
        transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
        change_quantity=-1,
        before_quantity=10,
        after_quantity=9,
        source_type=InventorySourceType.ORDER,
        source_id=order.id,
        operator=user,
        reason=INVENTORY_ORDER_DEDUCTION_REASON,
        idempotency_key=INVENTORY_ORDER_DEDUCTION_IDEMPOTENCY_KEY.format(
            order_id=order.id,
            product_id=kit_product.id,
        ),
    )
    await InventoryTransaction.create(
        id=9502,
        product=kit_product,
        transaction_type=InventoryTransactionType.ORDER_CANCELLATION_RESTORE,
        change_quantity=1,
        before_quantity=9,
        after_quantity=10,
        source_type=InventorySourceType.ORDER,
        source_id=order.id,
        operator=user,
        reason=INVENTORY_ORDER_RESTORE_REASON,
        idempotency_key=INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY.format(
            order_id=order.id,
            product_id=kit_product.id,
        ),
    )
    return SeededFailure(
        admin=admin,
        user=user,
        order=order,
        experience_product=experience,
        kit_product=kit_product,
        kit=kit,
        experience_items=tuple(expectations),
        kit_item_id=kit_item_id,
    )


async def _verify(
    seed: SeededFailure,
    *,
    candidate_sha: str = CANDIDATE_SHA,
    acceptance_attempt_id: str = ACCEPTANCE_ATTEMPT_ID,
) -> dict[str, object]:
    return await verifier.verify_failed_acceptance(
        candidate_sha=candidate_sha,
        acceptance_attempt_id=acceptance_attempt_id,
        order_id=seed.order.id,
        experience_product_id=seed.experience_product.id,
        kit_product_id=seed.kit_product.id,
        experience_items=seed.experience_items,
        kit_item_id=seed.kit_item_id,
        kit_price=Decimal("1.00"),
    )


async def _read_footprint() -> dict[str, list[dict[str, object]]]:
    models = (
        User,
        Product,
        ExperienceOption,
        ProductImage,
        ProductKit,
        Order,
        OrderItem,
        InventoryTransaction,
        WalletAccount,
        WalletTransaction,
        Payment,
        PaymentSettlement,
        Refund,
        TableSession,
    )
    return {
        model.__name__: list(await model.all().order_by("id").values())
        for model in models
    }


async def test_clean_failure_is_verified_read_only_and_returns_redacted_digest(
) -> None:
    seed = await _seed_clean_failure()
    before = await _read_footprint()

    result = await _verify(seed)

    assert result == {
        "schema_version": 2,
        "passed": True,
        "counts": {
            "orders": 1,
            "fixtures": 2,
            "fixture_images": 5,
            "experience_options": 3,
            "order_items": 4,
            "experience_items": 3,
            "kit_items": 1,
            "payments": 0,
            "settlements": 0,
            "refunds": 0,
            "wallet_transactions": 0,
            "table_sessions": 0,
            "admin_adjustments": 1,
            "order_deductions": 1,
            "cancellation_restores": 1,
        },
        "evidence_sha256": (
            "9f262cb7c7a500cfd3b245f045c9ff8a887a640a6576539b421a61add81c1012"
        ),
        "secret_values_recorded": False,
    }
    encoded = json.dumps(result, sort_keys=True)
    assert not any(
        str(raw_id) in encoded
        for raw_id in (
            seed.order.id,
            seed.experience_product.id,
            seed.kit_product.id,
            *(item.order_item_id for item in seed.experience_items),
            seed.kit_item_id,
        )
    )
    assert await _read_footprint() == before


async def test_candidate_and_attempt_identities_have_distinct_roles() -> None:
    seed = await _seed_clean_failure()

    result = await _verify(seed, candidate_sha=OTHER_CANDIDATE_SHA)

    assert result["passed"] is True
    with pytest.raises(
        verifier.GateAM9FailedAcceptanceVerificationError,
        match="fixture Product roles or saleability",
    ):
        await _verify(seed, acceptance_attempt_id="d" * 32)


@pytest.mark.parametrize(
    "drift",
    (
        "order_status",
        "order_total",
        "order_remark",
        "fixture_online",
        "fixture_draft",
        "fixture_name",
        "fixture_description",
        "fixture_deleted",
        "kit_stock",
        "item_snapshot",
        "item_option",
        "item_participants",
        "item_day_type",
        "item_price",
        "item_subtotal",
        "item_name",
        "item_color_snapshot",
        "item_sale_unit",
        "option_product",
        "option_duration",
        "option_participants",
        "option_day_type",
        "option_price",
        "option_deleted",
        "extra_option",
        "image_deleted",
        "image_binding",
        "cross_product_image",
        "extra_image",
        "missing_inventory_adjustment",
        "inventory_adjustment_chain",
        "inventory_adjustment_identity",
        "inventory_adjustment_source",
        "inventory_adjustment_operator",
        "inventory_chain",
        "extra_order_item",
        "extra_inventory_fact",
    ),
)
async def test_business_drift_fails_closed(drift: str) -> None:
    seed = await _seed_clean_failure()
    if drift == "order_status":
        await Order.filter(id=seed.order.id).update(status=OrderStatus.PENDING.value)
    elif drift == "order_total":
        await Order.filter(id=seed.order.id).update(total_amount=Decimal("4.00"))
    elif drift == "order_remark":
        await Order.filter(id=seed.order.id).update(remark="changed")
    elif drift == "fixture_online":
        await Product.filter(id=seed.experience_product.id).update(
            status=ProductStatus.ONLINE
        )
    elif drift == "fixture_draft":
        await Product.filter(id=seed.experience_product.id).update(
            status=ProductStatus.DRAFT
        )
    elif drift == "fixture_name":
        await Product.filter(id=seed.experience_product.id).update(name="changed")
    elif drift == "fixture_description":
        await Product.filter(id=seed.experience_product.id).update(
            description="changed"
        )
    elif drift == "fixture_deleted":
        await Product.filter(id=seed.experience_product.id).update(is_deleted=True)
    elif drift == "kit_stock":
        await ProductKit.filter(id=seed.kit.id).update(stock=9)
    elif drift == "item_snapshot":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            option_duration_minutes=61
        )
    elif drift == "item_option":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            experience_option_id=seed.experience_items[1].option_id
        )
    elif drift == "item_participants":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            option_participants=3
        )
    elif drift == "item_day_type":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            option_day_type=DayType.HOLIDAY
        )
    elif drift == "item_price":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            product_price=Decimal("2.00")
        )
    elif drift == "item_subtotal":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            subtotal=Decimal("9.00")
        )
    elif drift == "item_name":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            product_name="changed"
        )
    elif drift == "item_color_snapshot":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            kit_color_code="X"
        )
    elif drift == "item_sale_unit":
        await OrderItem.filter(id=seed.experience_items[0].order_item_id).update(
            sale_unit_grams=10
        )
    elif drift == "option_product":
        await ExperienceOption.filter(id=seed.experience_items[0].option_id).update(
            product_id=seed.kit_product.id
        )
    elif drift == "option_duration":
        await ExperienceOption.filter(id=seed.experience_items[0].option_id).update(
            duration=61
        )
    elif drift == "option_participants":
        await ExperienceOption.filter(id=seed.experience_items[0].option_id).update(
            participants=3
        )
    elif drift == "option_day_type":
        await ExperienceOption.filter(id=seed.experience_items[0].option_id).update(
            day_type=DayType.HOLIDAY
        )
    elif drift == "option_price":
        await ExperienceOption.filter(id=seed.experience_items[0].option_id).update(
            price=Decimal("2.00")
        )
    elif drift == "option_deleted":
        await ExperienceOption.filter(id=seed.experience_items[0].option_id).update(
            is_deleted=True
        )
    elif drift == "extra_option":
        await ExperienceOption.create(
            id=9204,
            product=seed.experience_product,
            duration=180,
            participants=1,
            day_type=DayType.WEEKDAY,
            price=Decimal("1.00"),
        )
    elif drift == "image_deleted":
        await ProductImage.filter(id=9251).update(is_deleted=True)
    elif drift == "image_binding":
        await ProductImage.filter(id=9253).update(
            experience_option_id=seed.experience_items[1].option_id
        )
    elif drift == "cross_product_image":
        other_product = await Product.create(
            id=9103,
            name="unrelated product",
            product_type=ProductType.EXPERIENCE,
            status=ProductStatus.DRAFT,
        )
        await ProductImage.create(
            id=9256,
            product=other_product,
            experience_option_id=seed.experience_items[0].option_id,
            image_url="/uploads/products/gatea-cross-product.png",
            is_cover=False,
            sort=0,
        )
    elif drift == "extra_image":
        await ProductImage.create(
            id=9256,
            product=seed.experience_product,
            image_url="/uploads/products/gatea-extra.png",
            is_cover=False,
            sort=1,
        )
    elif drift == "missing_inventory_adjustment":
        await InventoryTransaction.filter(id=9500).delete()
    elif drift == "inventory_adjustment_chain":
        await InventoryTransaction.filter(id=9500).update(before_quantity=1)
    elif drift == "inventory_adjustment_identity":
        await InventoryTransaction.filter(id=9500).update(
            idempotency_key="inventory:admin:adjust:changed"
        )
    elif drift == "inventory_adjustment_source":
        await InventoryTransaction.filter(id=9500).update(
            source_type=InventorySourceType.ORDER,
            source_id=seed.order.id,
        )
    elif drift == "inventory_adjustment_operator":
        await InventoryTransaction.filter(id=9500).update(
            operator_id=seed.user.id
        )
    elif drift == "inventory_chain":
        await InventoryTransaction.filter(id=9501).update(change_quantity=-2)
    elif drift == "extra_order_item":
        await OrderItem.create(
            id=9405,
            order=seed.order,
            product=seed.kit_product,
            product_name=seed.kit_product.name,
            product_price=Decimal("1.00"),
            quantity=1,
            subtotal=Decimal("1.00"),
        )
    else:
        await InventoryTransaction.create(
            id=9503,
            product=seed.kit_product,
            transaction_type=InventoryTransactionType.ORDER_DEDUCTION,
            change_quantity=-1,
            before_quantity=10,
            after_quantity=9,
            source_type=InventorySourceType.ORDER,
            source_id=seed.order.id,
            operator=seed.user,
            reason="unexpected duplicate",
            idempotency_key="inventory:unexpected:duplicate",
        )

    with pytest.raises(verifier.GateAM9FailedAcceptanceVerificationError):
        await _verify(seed)


async def _other_order(user: User) -> Order:
    return await Order.create(
        id=9302,
        order_no=_number("OD", 2),
        user=user,
        total_amount=Decimal("1.00"),
        status=OrderStatus.CANCELLED.value,
    )


async def _payment(user: User, order: Order) -> Payment:
    return await Payment.create(
        id=9601,
        payment_no=_number("PY", 1),
        user=user,
        purpose=PaymentPurpose.ORDER,
        method=PaymentMethod.MANUAL,
        amount=Decimal("1.00"),
        status=PaymentStatus.SUCCEEDED,
        order=order,
        idempotency_key="payment:gatea:test",
        succeeded_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    "dependant",
    ("payment", "settlement", "refund", "wallet_transaction", "table_session"),
)
async def test_any_payment_or_table_session_fact_fails_closed(dependant: str) -> None:
    seed = await _seed_clean_failure()
    if dependant == "payment":
        await _payment(seed.user, seed.order)
    elif dependant == "settlement":
        other = await _other_order(seed.user)
        payment = await _payment(seed.user, other)
        await PaymentSettlement.create(
            id=9701,
            payment=payment,
            order=seed.order,
            amount=Decimal("1.00"),
        )
    elif dependant == "refund":
        other = await _other_order(seed.user)
        payment = await _payment(seed.user, other)
        settlement = await PaymentSettlement.create(
            id=9701,
            payment=payment,
            order=other,
            amount=Decimal("1.00"),
        )
        await Refund.create(
            id=9801,
            refund_no=_number("RF", 1),
            settlement=settlement,
            order=seed.order,
            operator=seed.user,
            amount=Decimal("1.00"),
            status=RefundStatus.SUCCEEDED,
            inventory_restored=False,
            reason="test",
            idempotency_key="refund:gatea:test",
            succeeded_at=datetime.now(timezone.utc),
        )
    elif dependant == "wallet_transaction":
        wallet = await WalletAccount.create(
            id=9851,
            user=seed.user,
            balance=Decimal("1.00"),
        )
        await WalletTransaction.create(
            id=9852,
            wallet_account=wallet,
            transaction_type=WalletTransactionType.ORDER_PAYMENT,
            change_amount=Decimal("-1.00"),
            before_balance=Decimal("2.00"),
            after_balance=Decimal("1.00"),
            source_type=WalletTransactionSourceType.ORDER,
            source_id=seed.order.id,
            reason="unexpected order wallet fact",
            idempotency_key="wallet:gatea:unexpected",
        )
    else:
        table = await StoreTable.create(
            id=9901,
            table_no="T01",
            display_name="T01号桌",
            qr_token="A" * 32,
        )
        claimed_at = datetime.now(timezone.utc)
        await TableSession.create(
            id=9951,
            session_no=_number("TS", 1),
            table=table,
            user=seed.user,
            order=seed.order,
            status=TableSessionStatus.AWAITING_PAYMENT,
            claim_idempotency_key="table:gatea:test",
            claim_request_fingerprint="a" * 64,
            claimed_at=claimed_at,
            payment_deadline_at=claimed_at + timedelta(minutes=15),
        )

    with pytest.raises(
        verifier.GateAM9FailedAcceptanceVerificationError,
        match="dependent funding or table-session facts",
    ):
        await _verify(seed)


def _stdin_contract() -> dict[str, object]:
    return {
        "schema_version": 2,
        "candidate_sha": CANDIDATE_SHA,
        "acceptance_attempt_id": ACCEPTANCE_ATTEMPT_ID,
        "order_id": 9301,
        "experience_product_id": 9101,
        "kit_product_id": 9102,
        "experience_items": [
            {
                "order_item_id": 9401,
                "option_id": 9201,
                "duration_minutes": 60,
                "participants": 1,
                "day_type": "weekday",
                "price": "1.00",
                "quantity": 2,
            },
            {
                "order_item_id": 9402,
                "option_id": 9202,
                "duration_minutes": 60,
                "participants": 2,
                "day_type": "weekday",
                "price": "1.00",
                "quantity": 1,
            },
            {
                "order_item_id": 9403,
                "option_id": 9203,
                "duration_minutes": 120,
                "participants": 1,
                "day_type": "weekday",
                "price": "1.00",
                "quantity": 1,
            },
        ],
        "kit_item_id": 9404,
        "kit_price": "1.00",
    }


def test_stdin_contract_requires_bounded_exact_duplicate_free_json() -> None:
    payload = _stdin_contract()
    parsed = verifier._parse_input_payload(json.dumps(payload).encode())
    assert parsed["candidate_sha"] == CANDIDATE_SHA
    assert parsed["acceptance_attempt_id"] == ACCEPTANCE_ATTEMPT_ID
    assert parsed["order_id"] == 9301
    assert parsed["experience_items"] == (
        verifier.ExperienceItemExpectation(
            9401, 9201, 60, 1, DayType.WEEKDAY, Decimal("1.00"), 2
        ),
        verifier.ExperienceItemExpectation(
            9402, 9202, 60, 2, DayType.WEEKDAY, Decimal("1.00"), 1
        ),
        verifier.ExperienceItemExpectation(
            9403, 9203, 120, 1, DayType.WEEKDAY, Decimal("1.00"), 1
        ),
    )

    invalid_payload = dict(payload)
    invalid_payload["order_id"] = 0
    with pytest.raises(verifier.GateAM9FailedAcceptanceVerificationError):
        verifier._parse_input_payload(json.dumps(invalid_payload).encode())
    with pytest.raises(verifier.GateAM9FailedAcceptanceVerificationError):
        verifier._parse_input_payload(
            b'{"schema_version":1,"schema_version":1}'
        )
    with pytest.raises(verifier.GateAM9FailedAcceptanceVerificationError):
        verifier._parse_input_payload(b"x" * (verifier.MAX_INPUT_BYTES + 1))


@pytest.mark.parametrize("schema_version", (True, 1.0))
def test_stdin_contract_rejects_non_integer_schema_version(
    schema_version: object,
) -> None:
    payload = _stdin_contract()
    payload["schema_version"] = schema_version

    with pytest.raises(verifier.GateAM9FailedAcceptanceVerificationError):
        verifier._parse_input_payload(json.dumps(payload).encode())


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema_version", 1),
        ("candidate_sha", "a" * 39),
        ("candidate_sha", "A" * 40),
        ("acceptance_attempt_id", "b" * 31),
        ("acceptance_attempt_id", "B" * 32),
    ),
)
def test_stdin_contract_requires_both_exact_root_identities(
    field: str,
    value: object,
) -> None:
    payload = _stdin_contract()
    payload[field] = value

    with pytest.raises(verifier.GateAM9FailedAcceptanceVerificationError) as caught:
        verifier._parse_input_payload(json.dumps(payload).encode())

    assert caught.value.reason_code == "INPUT_CONTRACT"


def test_refusal_reason_and_key_allowlist_is_frozen() -> None:
    assert dict(verifier.REFUSAL_KEYS_BY_REASON_CODE) == {
        "INPUT_CONTRACT": "input_contract",
        "ORDER_CONTRACT": "order_contract",
        "FIXTURE_PRODUCT_CONTRACT": "fixture_product_contract",
        "FIXTURE_IMAGE_CONTRACT": "fixture_image_contract",
        "KIT_CONTRACT": "kit_contract",
        "OPTION_CONTRACT": "option_contract",
        "ORDER_ITEM_CONTRACT": "order_item_contract",
        "DEPENDENT_FACTS": "dependent_facts",
        "INVENTORY_SET": "inventory_set",
        "INVENTORY_SUPPLY": "inventory_supply",
        "INVENTORY_ORDER_CHAIN": "inventory_order_chain",
        "INTERNAL_FAILURE": "internal_failure",
    }
    for reason_code, refusal_key in verifier.REFUSAL_KEYS_BY_REASON_CODE.items():
        assert verifier._refusal_payload(reason_code) == {
            "schema_version": 2,
            "passed": False,
            "reason_code": reason_code,
            "refusal_key": refusal_key,
            "secret_values_recorded": False,
        }
    assert verifier._refusal_payload("NOT_ALLOWLISTED") == {
        "schema_version": 2,
        "passed": False,
        "reason_code": "INTERNAL_FAILURE",
        "refusal_key": "internal_failure",
        "secret_values_recorded": False,
    }


def test_expectation_identity_validation_fails_before_database_reads() -> None:
    duplicate = verifier.ExperienceItemExpectation(
        11, 21, 60, 1, DayType.WEEKDAY, Decimal("1.00"), 1
    )
    with pytest.raises(
        verifier.GateAM9FailedAcceptanceVerificationError,
        match="four frozen OrderItem identities",
    ):
        verifier._validate_expectations(
            order_id=3,
            experience_product_id=1,
            kit_product_id=2,
            experience_items=(
                duplicate,
                duplicate,
                verifier.ExperienceItemExpectation(
                    12, 22, 120, 1, DayType.WEEKDAY, Decimal("1.00"), 1
                ),
            ),
            kit_item_id=13,
        )


def test_main_prints_one_redacted_json_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {
        "schema_version": 2,
        "passed": True,
        "counts": {"orders": 1},
        "evidence_sha256": "a" * 64,
        "secret_values_recorded": False,
    }

    async def fake_run(**kwargs: object) -> dict[str, object]:
        assert kwargs["order_id"] == 9301
        assert len(kwargs["experience_items"]) == 3  # type: ignore[arg-type]
        return expected

    monkeypatch.setattr(verifier, "run", fake_run)
    monkeypatch.setattr(
        verifier,
        "_read_stdin_payload",
        lambda: json.dumps(_stdin_contract()).encode(),
    )
    exit_code = verifier.main([])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == expected
    assert captured.out == (
        json.dumps(
            expected,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    assert not any(value in captured.out for value in ("9301", "9101", "9401"))


def test_main_none_rejects_real_process_arguments_before_reading_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_if_read() -> bytes:
        raise AssertionError("stdin must not be read when argv identities exist")

    monkeypatch.setattr(sys, "argv", ["gatea-verifier", "9301"])
    monkeypatch.setattr(verifier, "_read_stdin_payload", fail_if_read)

    assert verifier.main(None) == 2

    captured = capsys.readouterr()
    assert captured.out == (
        '{"passed":false,"reason_code":"INPUT_CONTRACT",'
        '"refusal_key":"input_contract","schema_version":2,'
        '"secret_values_recorded":false}\n'
    )
    assert captured.err == ""
    assert "9301" not in captured.out


def test_main_emits_safe_business_refusal_without_exception_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def refusing_run(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise verifier.GateAM9FailedAcceptanceVerificationError(
            "INVENTORY_SUPPLY",
            "database row 9500 contained secret-value",
        )

    monkeypatch.setattr(verifier, "run", refusing_run)
    monkeypatch.setattr(
        verifier,
        "_read_stdin_payload",
        lambda: json.dumps(_stdin_contract()).encode(),
    )

    assert verifier.main([]) == 2

    captured = capsys.readouterr()
    assert captured.out == (
        '{"passed":false,"reason_code":"INVENTORY_SUPPLY",'
        '"refusal_key":"inventory_supply","schema_version":2,'
        '"secret_values_recorded":false}\n'
    )
    assert captured.err == ""
    assert "9500" not in captured.out
    assert "secret-value" not in captured.out


def test_main_emits_safe_internal_refusal_without_error_or_database_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def failing_run(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise RuntimeError(
            "asyncmy OperationalError mysql://user:password@database/private"
        )

    monkeypatch.setattr(verifier, "run", failing_run)
    monkeypatch.setattr(
        verifier,
        "_read_stdin_payload",
        lambda: json.dumps(_stdin_contract()).encode(),
    )

    assert verifier.main([]) == 2

    captured = capsys.readouterr()
    assert captured.out == (
        '{"passed":false,"reason_code":"INTERNAL_FAILURE",'
        '"refusal_key":"internal_failure","schema_version":2,'
        '"secret_values_recorded":false}\n'
    )
    assert captured.err == ""
    assert not any(
        sensitive in captured.out
        for sensitive in (
            "RuntimeError",
            "OperationalError",
            "mysql",
            "user",
            "password",
            "database",
            "private",
        )
    )
