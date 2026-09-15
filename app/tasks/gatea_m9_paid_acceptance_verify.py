"""只读核验已付款、已释放的 M9 验收失败；身份仅由有界 stdin 提供。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re
import sys

from tortoise import Tortoise

from app.common.constants.wallet import WALLET_ORDER_PAYMENT_REASON, WALLET_ORDER_TRANSACTION_KEY
from app.common.enums.order import OrderStatus
from app.common.enums.table_session import TableSessionCloseReason, TableSessionStatus
from app.common.enums.wallet import PaymentMethod, PaymentPurpose, PaymentStatus, WalletTransactionType, WalletStatus
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.table_session import StoreTable, TableSession, TableSessionTimer, TableOccupancy
from app.models.wallet import WalletAccount, WalletTransaction
from app.tasks import gatea_m9_failed_acceptance_verify as base


PAID_KEYS = {"payment_id", "payment_no_sha256", "succeeded_at", "session_no_sha256"}


def _require(condition: bool) -> None:
    if not condition:
        raise base.GateAM9FailedAcceptanceVerificationError(
            "DEPENDENT_FACTS", "paid acceptance facts do not match the frozen checkpoint"
        )


def parse_input(raw: bytes) -> dict:
    _require(0 < len(raw) <= base.MAX_INPUT_BYTES)
    payload = json.loads(raw, object_pairs_hook=base._reject_duplicate_keys)
    _require(isinstance(payload, dict) and set(payload) == base.INPUT_KEYS | PAID_KEYS)
    _require(type(payload["schema_version"]) is int and payload["schema_version"] == 3)
    common = {key: payload[key] for key in base.INPUT_KEYS}
    common["schema_version"] = base.INPUT_SCHEMA_VERSION
    parsed = base._parse_input_payload(json.dumps(common).encode())
    parsed["payment_id"] = base._positive_id(payload["payment_id"])
    for key in ("payment_no_sha256", "session_no_sha256"):
        _require(isinstance(payload[key], str) and re.fullmatch(r"[0-9a-f]{64}", payload[key]) is not None)
        parsed[key] = payload[key]
    paid_at = datetime.fromisoformat(payload["succeeded_at"])
    _require(paid_at.utcoffset() is not None and paid_at.utcoffset().total_seconds() == 0)
    parsed["succeeded_at"] = paid_at
    return parsed


async def verify_paid_acceptance(**data) -> dict:
    items = base._validate_expectations(**{key: data[key] for key in (
        "order_id", "experience_product_id", "kit_product_id", "experience_items", "kit_item_id"
    )})
    order = await base._verify_order(data["order_id"], expected_status=OrderStatus.PAID)
    await base._verify_fixtures(**{key: data[key] for key in (
        "experience_product_id", "kit_product_id", "acceptance_attempt_id"
    )})
    await base._verify_kit(kit_product_id=data["kit_product_id"], kit_price=data["kit_price"], expected_stock=9)
    await base._verify_experience_options(experience_product_id=data["experience_product_id"], experience_items=items)
    await base._verify_fixture_images(experience_product_id=data["experience_product_id"],
                                     kit_product_id=data["kit_product_id"], experience_items=items)
    await base._verify_order_items(**{key: data[key] for key in (
        "order_id", "experience_product_id", "kit_product_id", "experience_items",
        "kit_item_id", "kit_price", "acceptance_attempt_id"
    )})
    await base._verify_inventory(acceptance_attempt_id=data["acceptance_attempt_id"],
                                order_id=data["order_id"], kit_product_id=data["kit_product_id"],
                                order_user_id=order["user_id"], paid=True)
    payments = await Payment.filter(order_id=data["order_id"])
    _require(len(payments) == 1)
    payment = payments[0]
    _require(payment.id == data["payment_id"] and payment.user_id == order["user_id"]
             and payment.method == PaymentMethod.WALLET and payment.purpose == PaymentPurpose.ORDER
             and payment.status == PaymentStatus.SUCCEEDED and payment.amount == Decimal("5.00")
             and payment.succeeded_at == data["succeeded_at"]
             and hashlib.sha256(payment.payment_no.encode()).hexdigest() == data["payment_no_sha256"]
             and payment.idempotency_key == f"gatea-m9-wallet-{data['acceptance_attempt_id']}-v1"
             and payment.recharge_order_id is None and payment.provider_transaction_id is None)
    settlements = await PaymentSettlement.filter(order_id=data["order_id"])
    _require(len(settlements) == 1 and settlements[0].payment_id == payment.id
             and settlements[0].amount == Decimal("5.00"))
    _require(await Refund.filter(order_id=data["order_id"]).count() == 0)
    wallets = await WalletAccount.filter(user_id=order["user_id"])
    _require(len(wallets) == 1 and wallets[0].status == WalletStatus.ACTIVE and wallets[0].balance == Decimal("155.00"))
    transactions = await WalletTransaction.filter(source_type="order", source_id=data["order_id"])
    _require(len(transactions) == 1)
    txn = transactions[0]
    _require(txn.wallet_account_id == wallets[0].id and txn.transaction_type == WalletTransactionType.ORDER_PAYMENT
             and txn.change_amount == Decimal("-5.00") and txn.before_balance == Decimal("160.00")
             and txn.after_balance == Decimal("155.00") and txn.operator_id == order["user_id"]
             and txn.reason == WALLET_ORDER_PAYMENT_REASON
             and txn.idempotency_key == WALLET_ORDER_TRANSACTION_KEY.format(payment_id=payment.id, order_id=data["order_id"]))
    sessions = await TableSession.filter(order_id=data["order_id"])
    _require(len(sessions) == 1)
    session = sessions[0]
    table = await StoreTable.get(id=session.table_id)
    _require(table.table_no == "T01" and session.user_id == order["user_id"]
             and session.payment_id == payment.id and session.status == TableSessionStatus.CLOSED
             and session.close_reason == TableSessionCloseReason.ADMIN_RELEASED
             and session.started_at == payment.succeeded_at and session.closed_at is not None
             and session.closed_by_user_id is not None
             and session.claimed_at <= payment.succeeded_at < session.payment_deadline_at
             and payment.succeeded_at <= session.closed_at
             and session.claim_idempotency_key == f"gatea-m9-claim-{data['acceptance_attempt_id']}-v1"
             and session.release_idempotency_key == f"gatea-m9-release-{data['acceptance_attempt_id']}-v1"
             and session.admin_close_reason == "Gate A M9 controlled internal acceptance release"
             and hashlib.sha256(session.session_no.encode()).hexdigest() == data["session_no_sha256"]
             and (session.payment_deadline_at - session.claimed_at).total_seconds() == 900
             and session.table_release_at is not None
             and (session.table_release_at - payment.succeeded_at).total_seconds() == 7800)
    _require(await base.User.filter(id=session.closed_by_user_id, role=base.UserRole.SUPER_ADMIN.value).exists())
    timers = await TableSessionTimer.filter(session_id=session.id).order_by("duration_minutes")
    _require(len(timers) == 2)
    for timer, minutes in zip(timers, (60, 120), strict=True):
        _require(timer.duration_minutes == minutes and timer.buffer_minutes == 10
                 and timer.started_at == payment.succeeded_at
                 and (timer.service_ends_at - payment.succeeded_at).total_seconds() == minutes * 60
                 and (timer.grace_ends_at - payment.succeeded_at).total_seconds() == (minutes + 10) * 60)
    _require(await TableOccupancy.all().count() == 0)
    _require(await TableSession.exclude(status=TableSessionStatus.CLOSED).count() == 0)
    counts = {"orders": 1, "fixtures": 2, "fixture_images": 5, "experience_options": 3,
              "order_items": 4, "experience_items": 3, "kit_items": 1, "payments": 1,
              "settlements": 1, "refunds": 0, "wallet_transactions": 1, "table_sessions": 1,
              "admin_adjustments": 1, "order_deductions": 1, "cancellation_restores": 0}
    return {"schema_version": 3, "passed": True, "counts": counts,
            "evidence_sha256": base._canonical_sha256(counts), "secret_values_recorded": False}


async def run(data: dict) -> dict:
    await Tortoise.init(config=base.TORTOISE_ORM)
    try:
        return await verify_paid_acceptance(**data)
    finally:
        await Tortoise.close_connections()


def main() -> int:
    try:
        _require(len(sys.argv) == 1)
        result = asyncio.run(run(parse_input(base._read_stdin_payload())))
    except Exception:
        sys.stdout.write(base._json_protocol_line(base._refusal_payload("DEPENDENT_FACTS")))
        return 2
    sys.stdout.write(base._json_protocol_line(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
