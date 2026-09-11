"""只读核验 Gate A M9 pre-claim 失败验收留下的业务数据。"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from tortoise import Tortoise
from tortoise.expressions import Q

from app.common.constants.inventory import (
    INVENTORY_ADMIN_IDEMPOTENCY_PREFIX,
    INVENTORY_ORDER_DEDUCTION_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_DEDUCTION_REASON,
    INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY,
    INVENTORY_ORDER_RESTORE_REASON,
)
from app.common.constants.order import ORDER_ITEM_QUANTITY_MAX
from app.common.enums.inventory import (
    InventorySourceType,
    InventoryTransactionType,
)
from app.common.enums.order import OrderStatus
from app.common.enums.product import DayType, KitKind, ProductStatus, ProductType
from app.common.enums.user import UserRole
from app.common.enums.wallet import WalletTransactionSourceType
from app.db.database import TORTOISE_ORM
from app.models.inventory_transaction import InventoryTransaction
from app.models.experience_option import ExperienceOption
from app.models.order import Order, OrderItem
from app.models.payment import Payment, PaymentSettlement, Refund
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.models.table_session import TableSession
from app.models.user import User
from app.models.wallet import WalletTransaction

INPUT_SCHEMA_VERSION = 2
RESULT_SCHEMA_VERSION = 2
EXPECTED_KIT_STOCK = 10
MAX_DATABASE_ID = 2**63 - 1
MAX_DURATION_MINUTES = 2**31 - 1
MAX_INPUT_BYTES = 4096
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ACCEPTANCE_ATTEMPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
EXPECTED_ORDER_TOTAL = Decimal("5.00")
EXPECTED_ORDER_REMARK = "[GATEA-M9] same/different duration and Kit acceptance"
EXPECTED_EXPERIENCE_DESCRIPTION = (
    "Controlled M9 multi-duration timer acceptance fixture"
)
EXPECTED_KIT_DESCRIPTION = "Controlled M9 non-timer Kit fixture"
EXPECTED_KIT_SUPPLY_REASON = "Gate A M9 controlled fixture supply"
INPUT_KEYS = frozenset(
    {
        "schema_version",
        "order_id",
        "experience_product_id",
        "kit_product_id",
        "experience_items",
        "kit_item_id",
        "kit_price",
        "candidate_sha",
        "acceptance_attempt_id",
    }
)
EXPERIENCE_ITEM_KEYS = frozenset(
    {
        "order_item_id",
        "option_id",
        "duration_minutes",
        "participants",
        "day_type",
        "price",
        "quantity",
    }
)
PRICE_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{2}$")
REFUSAL_KEYS_BY_REASON_CODE: Mapping[str, str] = MappingProxyType(
    {
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
)
REFUSAL_REASON_CODES = frozenset(REFUSAL_KEYS_BY_REASON_CODE)


class GateAM9FailedAcceptanceVerificationError(RuntimeError):
    """不包含原始 ID、Token、PII 或业务 Secret 的核验错误。"""

    def __init__(self, reason_code: str, message: str) -> None:
        if reason_code not in REFUSAL_REASON_CODES:
            reason_code = "INTERNAL_FAILURE"
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ExperienceItemExpectation:
    """pre-claim pending 冻结的一条 Experience OrderItem 快照。"""

    order_item_id: int
    option_id: int
    duration_minutes: int
    participants: int
    day_type: DayType
    price: Decimal
    quantity: int


def _experience_fixture_name(acceptance_attempt_id: str) -> str:
    return f"[GATEA-M9] Runtime experience {acceptance_attempt_id[:12]}"


def _kit_fixture_name(acceptance_attempt_id: str) -> str:
    return f"[GATEA-M9] Runtime fixed Kit {acceptance_attempt_id[:12]}"


def _kit_supply_idempotency_key(acceptance_attempt_id: str) -> str:
    return (
        f"{INVENTORY_ADMIN_IDEMPOTENCY_PREFIX}"
        f"gatea-m9-kit-stock-{acceptance_attempt_id}-v1"
    )


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_protocol_line(payload: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _refusal_payload(reason_code: str) -> dict[str, Any]:
    if reason_code not in REFUSAL_REASON_CODES:
        reason_code = "INTERNAL_FAILURE"
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "passed": False,
        "reason_code": reason_code,
        "refusal_key": REFUSAL_KEYS_BY_REASON_CODE[reason_code],
        "secret_values_recorded": False,
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise GateAM9FailedAcceptanceVerificationError(
                "INPUT_CONTRACT",
                "the verifier input contains a duplicate field"
            )
        payload[key] = value
    return payload


def _positive_id(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_DATABASE_ID:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "a verifier database identity is outside the positive BIGINT range"
        )
    return value


def _positive_bounded_int(value: object, maximum: int, description: str) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            f"the verifier {description} is outside its contract"
        )
    return value


def _price(value: object) -> Decimal:
    if not isinstance(value, str) or PRICE_PATTERN.fullmatch(value) is None:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "a verifier price is not canonical"
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "a verifier price is invalid"
        ) from error
    if parsed <= 0:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "a verifier price is outside the Product contract"
        )
    return parsed


def _validate_root_identities(
    *,
    candidate_sha: str,
    acceptance_attempt_id: str,
) -> None:
    if not isinstance(candidate_sha, str) or GIT_SHA_PATTERN.fullmatch(
        candidate_sha
    ) is None:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "the verifier candidate identity is invalid",
        )
    if not isinstance(acceptance_attempt_id, str) or (
        ACCEPTANCE_ATTEMPT_ID_PATTERN.fullmatch(acceptance_attempt_id) is None
    ):
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "the verifier acceptance attempt identity is invalid",
        )


def _parse_input_payload(raw_payload: bytes) -> dict[str, Any]:
    """Parse the bounded root-only stdin contract without echoing identities."""

    if not raw_payload or len(raw_payload) > MAX_INPUT_BYTES:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "the verifier input size is invalid"
        )
    try:
        payload = json.loads(
            raw_payload,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "the verifier input is invalid JSON"
        ) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != INPUT_KEYS
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != INPUT_SCHEMA_VERSION
        or not isinstance(payload.get("experience_items"), list)
    ):
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "the verifier input shape is invalid"
        )
    parsed_items: list[ExperienceItemExpectation] = []
    for item in payload["experience_items"]:
        if not isinstance(item, dict) or set(item) != EXPERIENCE_ITEM_KEYS:
            raise GateAM9FailedAcceptanceVerificationError(
                "INPUT_CONTRACT",
                "an Experience expectation shape is invalid"
            )
        try:
            day_type = DayType(item["day_type"])
        except (TypeError, ValueError) as error:
            raise GateAM9FailedAcceptanceVerificationError(
                "INPUT_CONTRACT",
                "an Experience expectation day type is invalid"
            ) from error
        parsed_items.append(
            ExperienceItemExpectation(
                order_item_id=_positive_id(item["order_item_id"]),
                option_id=_positive_id(item["option_id"]),
                duration_minutes=_positive_bounded_int(
                    item["duration_minutes"],
                    MAX_DURATION_MINUTES,
                    "duration",
                ),
                participants=_positive_bounded_int(
                    item["participants"],
                    MAX_DATABASE_ID,
                    "participants",
                ),
                day_type=day_type,
                price=_price(item["price"]),
                quantity=_positive_bounded_int(
                    item["quantity"],
                    ORDER_ITEM_QUANTITY_MAX,
                    "quantity",
                ),
            )
        )
    candidate_sha = payload["candidate_sha"]
    acceptance_attempt_id = payload["acceptance_attempt_id"]
    _validate_root_identities(
        candidate_sha=candidate_sha,
        acceptance_attempt_id=acceptance_attempt_id,
    )
    return {
        "candidate_sha": candidate_sha,
        "acceptance_attempt_id": acceptance_attempt_id,
        "order_id": _positive_id(payload["order_id"]),
        "experience_product_id": _positive_id(
            payload["experience_product_id"]
        ),
        "kit_product_id": _positive_id(payload["kit_product_id"]),
        "experience_items": tuple(parsed_items),
        "kit_item_id": _positive_id(payload["kit_item_id"]),
        "kit_price": _price(payload["kit_price"]),
    }


def _read_stdin_payload() -> bytes:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    value = stream.read(MAX_INPUT_BYTES + 1)
    if isinstance(value, str):
        return value.encode("utf-8")
    return value


def _validate_expectations(
    *,
    order_id: int,
    experience_product_id: int,
    kit_product_id: int,
    experience_items: Sequence[ExperienceItemExpectation],
    kit_item_id: int,
) -> tuple[ExperienceItemExpectation, ...]:
    frozen_items = tuple(experience_items)
    item_ids = [item.order_item_id for item in frozen_items]
    database_ids = (
        order_id,
        experience_product_id,
        kit_product_id,
        kit_item_id,
        *item_ids,
        *(item.option_id for item in frozen_items),
    )
    if any(
        type(database_id) is not int
        or not 1 <= database_id <= MAX_DATABASE_ID
        for database_id in database_ids
    ):
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "a frozen database identity is outside the positive BIGINT range"
        )
    if experience_product_id == kit_product_id:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "fixture Product roles are not distinct"
        )
    if len(frozen_items) != 3:
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "exactly three Experience item expectations are required"
        )
    if (
        len(set(item_ids)) != 3
        or kit_item_id in item_ids
        or len({item.option_id for item in frozen_items}) != 3
    ):
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "the four frozen OrderItem identities are not distinct"
        )
    if any(
        type(item.duration_minutes) is not int
        or not 1 <= item.duration_minutes <= MAX_DURATION_MINUTES
        or type(item.quantity) is not int
        or not 1 <= item.quantity <= ORDER_ITEM_QUANTITY_MAX
        or type(item.participants) is not int
        or item.participants <= 0
        or not isinstance(item.day_type, DayType)
        or not isinstance(item.price, Decimal)
        or item.price <= 0
        for item in frozen_items
    ):
        raise GateAM9FailedAcceptanceVerificationError(
            "INPUT_CONTRACT",
            "a frozen Experience snapshot is outside the Order contract"
        )
    return frozen_items


async def _verify_order(order_id: int) -> dict[str, Any]:
    rows = await Order.filter(id=order_id).values(
        "id", "user_id", "status", "total_amount", "remark"
    )
    try:
        is_cancelled = (
            len(rows) == 1
            and int(rows[0]["status"]) == OrderStatus.CANCELLED.value
            and rows[0]["total_amount"] == EXPECTED_ORDER_TOTAL
            and rows[0]["remark"] == EXPECTED_ORDER_REMARK
        )
    except (TypeError, ValueError):
        is_cancelled = False
    if not is_cancelled:
        raise GateAM9FailedAcceptanceVerificationError(
            "ORDER_CONTRACT",
            "the frozen Order is missing or not cancelled"
        )
    return rows[0]


async def _verify_fixtures(
    *,
    experience_product_id: int,
    kit_product_id: int,
    acceptance_attempt_id: str,
) -> None:
    rows = await Product.filter(
        id__in=(experience_product_id, kit_product_id)
    ).values(
        "id",
        "name",
        "description",
        "product_type",
        "status",
        "is_deleted",
    )
    if len(rows) != 2:
        raise GateAM9FailedAcceptanceVerificationError(
            "FIXTURE_PRODUCT_CONTRACT",
            "the frozen fixture Product set is incomplete"
        )
    by_id = {int(row["id"]): row for row in rows}
    experience = by_id.get(experience_product_id)
    kit = by_id.get(kit_product_id)
    if experience is None or kit is None:
        raise GateAM9FailedAcceptanceVerificationError(
            "FIXTURE_PRODUCT_CONTRACT",
            "the frozen fixture Product identities changed"
        )
    try:
        fixture_is_valid = (
            ProductType(experience["product_type"]) is ProductType.EXPERIENCE
            and ProductType(kit["product_type"]) is ProductType.KIT
            and ProductStatus(experience["status"]) is ProductStatus.OFFLINE
            and ProductStatus(kit["status"]) is ProductStatus.OFFLINE
            and experience["name"]
            == _experience_fixture_name(acceptance_attempt_id)
            and experience["description"] == EXPECTED_EXPERIENCE_DESCRIPTION
            and kit["name"] == _kit_fixture_name(acceptance_attempt_id)
            and kit["description"] == EXPECTED_KIT_DESCRIPTION
            and experience["is_deleted"] is False
            and kit["is_deleted"] is False
        )
    except (TypeError, ValueError):
        fixture_is_valid = False
    if not fixture_is_valid:
        raise GateAM9FailedAcceptanceVerificationError(
            "FIXTURE_PRODUCT_CONTRACT",
            "the frozen fixture Product roles or saleability are invalid"
        )


async def _verify_fixture_images(
    *,
    experience_product_id: int,
    kit_product_id: int,
    experience_items: Sequence[ExperienceItemExpectation],
) -> None:
    option_ids = tuple(item.option_id for item in experience_items)
    rows = await ProductImage.filter(
        Q(product_id__in=(experience_product_id, kit_product_id))
        | Q(experience_option_id__in=option_ids)
    ).values(
        "product_id",
        "experience_option_id",
        "is_cover",
        "sort",
        "is_deleted",
    )
    if len(rows) != 5:
        raise GateAM9FailedAcceptanceVerificationError(
            "FIXTURE_IMAGE_CONTRACT",
            "the frozen fixture image set is incomplete"
        )
    product_images = [
        row for row in rows if row["experience_option_id"] is None
    ]
    option_images = [
        row for row in rows if row["experience_option_id"] is not None
    ]
    if (
        len(product_images) != 2
        or {row["product_id"] for row in product_images}
        != {experience_product_id, kit_product_id}
        or any(
            row["is_cover"] is not True
            or row["sort"] != 0
            or row["is_deleted"] is not False
            for row in product_images
        )
        or len(option_images) != 3
        or {row["product_id"] for row in option_images}
        != {experience_product_id}
        or {row["experience_option_id"] for row in option_images}
        != set(option_ids)
        or any(
            row["is_cover"] is not False
            or row["sort"] != 0
            or row["is_deleted"] is not False
            for row in option_images
        )
    ):
        raise GateAM9FailedAcceptanceVerificationError(
            "FIXTURE_IMAGE_CONTRACT",
            "the frozen fixture image bindings changed"
        )


async def _verify_kit(*, kit_product_id: int, kit_price: Decimal) -> None:
    rows = await ProductKit.filter(product_id=kit_product_id).values(
        "product_id",
        "kit_kind",
        "price",
        "stock",
    )
    try:
        kit_is_valid = (
            len(rows) == 1
            and KitKind(rows[0]["kit_kind"]) is KitKind.FIXED
            and rows[0]["price"] == kit_price
            and rows[0]["stock"] == EXPECTED_KIT_STOCK
        )
    except (TypeError, ValueError):
        kit_is_valid = False
    if not kit_is_valid:
        raise GateAM9FailedAcceptanceVerificationError(
            "KIT_CONTRACT",
            "the frozen fixed Kit stock is not fully restored"
        )


async def _verify_experience_options(
    *,
    experience_product_id: int,
    experience_items: Sequence[ExperienceItemExpectation],
) -> None:
    """Require the three live Options to match every frozen sale field."""

    rows = await ExperienceOption.filter(product_id=experience_product_id).values(
        "id",
        "product_id",
        "duration",
        "participants",
        "day_type",
        "price",
        "is_deleted",
    )
    if len(rows) != 3:
        raise GateAM9FailedAcceptanceVerificationError(
            "OPTION_CONTRACT",
            "the frozen ExperienceOption set is incomplete"
        )
    by_id = {int(row["id"]): row for row in rows}
    for expectation in experience_items:
        row = by_id.get(expectation.option_id)
        try:
            is_valid = (
                row is not None
                and row["product_id"] == experience_product_id
                and row["duration"] == expectation.duration_minutes
                and row["participants"] == expectation.participants
                and DayType(row["day_type"]) is expectation.day_type
                and row["price"] == expectation.price
                and row["is_deleted"] is False
            )
        except (TypeError, ValueError):
            is_valid = False
        if not is_valid:
            raise GateAM9FailedAcceptanceVerificationError(
                "OPTION_CONTRACT",
                "a frozen ExperienceOption changed"
            )


async def _verify_order_items(
    *,
    order_id: int,
    experience_product_id: int,
    kit_product_id: int,
    experience_items: Sequence[ExperienceItemExpectation],
    kit_item_id: int,
    kit_price: Decimal,
    acceptance_attempt_id: str,
) -> list[dict[str, int]]:
    rows = await OrderItem.filter(order_id=order_id).values(
        "id",
        "product_id",
        "experience_option_id",
        "kit_color_id",
        "option_duration_minutes",
        "option_participants",
        "option_day_type",
        "product_name",
        "kit_color_code",
        "kit_color_name",
        "kit_color_slot_no",
        "sale_unit_grams",
        "product_price",
        "quantity",
        "subtotal",
    )
    expected_ids = {
        *(item.order_item_id for item in experience_items),
        kit_item_id,
    }
    if len(rows) != 4 or {int(row["id"]) for row in rows} != expected_ids:
        raise GateAM9FailedAcceptanceVerificationError(
            "ORDER_ITEM_CONTRACT",
            "the frozen OrderItem identity set is incomplete"
        )

    by_id = {int(row["id"]): row for row in rows}
    option_ids: set[int] = set()
    snapshots: list[dict[str, int]] = []
    for expectation in experience_items:
        row = by_id[expectation.order_item_id]
        option_id = row["experience_option_id"]
        if (
            row["product_id"] != experience_product_id
            or option_id != expectation.option_id
            or row["kit_color_id"] is not None
            or row["option_duration_minutes"] != expectation.duration_minutes
            or row["option_participants"] != expectation.participants
            or row["option_day_type"] != expectation.day_type
            or row["product_name"]
            != _experience_fixture_name(acceptance_attempt_id)
            or row["kit_color_code"] is not None
            or row["kit_color_name"] is not None
            or row["kit_color_slot_no"] is not None
            or row["sale_unit_grams"] is not None
            or row["product_price"] != expectation.price
            or row["quantity"] != expectation.quantity
            or row["subtotal"]
            != expectation.price * expectation.quantity
        ):
            raise GateAM9FailedAcceptanceVerificationError(
                "ORDER_ITEM_CONTRACT",
                "an Experience OrderItem snapshot changed"
            )
        option_ids.add(option_id)
        snapshots.append(
            {
                "duration_minutes": expectation.duration_minutes,
                "quantity": expectation.quantity,
            }
        )
    if len(option_ids) != 3:
        raise GateAM9FailedAcceptanceVerificationError(
            "ORDER_ITEM_CONTRACT",
            "the Experience OrderItem option identities are not distinct"
        )

    kit_row = by_id[kit_item_id]
    if (
        kit_row["product_id"] != kit_product_id
        or kit_row["experience_option_id"] is not None
        or kit_row["kit_color_id"] is not None
        or kit_row["option_duration_minutes"] is not None
        or kit_row["option_participants"] is not None
        or kit_row["option_day_type"] is not None
        or kit_row["product_name"] != _kit_fixture_name(acceptance_attempt_id)
        or kit_row["kit_color_code"] is not None
        or kit_row["kit_color_name"] is not None
        or kit_row["kit_color_slot_no"] is not None
        or kit_row["sale_unit_grams"] is not None
        or kit_row["product_price"] != kit_price
        or kit_row["quantity"] != 1
        or kit_row["subtotal"] != kit_price
    ):
        raise GateAM9FailedAcceptanceVerificationError(
            "ORDER_ITEM_CONTRACT",
            "the fixed Kit OrderItem snapshot changed"
        )
    return sorted(
        snapshots,
        key=lambda item: (item["duration_minutes"], item["quantity"]),
    )


async def _verify_absent_dependants(order_id: int) -> dict[str, int]:
    counts = {
        "payments": await Payment.filter(order_id=order_id).count(),
        "settlements": await PaymentSettlement.filter(order_id=order_id).count(),
        "refunds": await Refund.filter(order_id=order_id).count(),
        "wallet_transactions": await WalletTransaction.filter(
            source_type=WalletTransactionSourceType.ORDER,
            source_id=order_id,
        ).count(),
        "table_sessions": await TableSession.filter(order_id=order_id).count(),
    }
    if any(counts.values()):
        raise GateAM9FailedAcceptanceVerificationError(
            "DEPENDENT_FACTS",
            "the frozen Order has dependent funding or table-session facts"
        )
    return counts


async def _verify_inventory(
    *,
    acceptance_attempt_id: str,
    order_id: int,
    kit_product_id: int,
    order_user_id: int,
) -> None:
    rows = await InventoryTransaction.filter(product_id=kit_product_id).values(
        "id",
        "product_id",
        "kit_color_id",
        "transaction_type",
        "change_quantity",
        "before_quantity",
        "after_quantity",
        "source_type",
        "source_id",
        "operator_id",
        "reason",
        "idempotency_key",
        "created_at",
    )
    if len(rows) != 3:
        raise GateAM9FailedAcceptanceVerificationError(
            "INVENTORY_SET",
            "the frozen Kit inventory footprint is not exact"
        )
    by_type: dict[InventoryTransactionType, dict[str, Any]] = {}
    for row in rows:
        try:
            transaction_type = InventoryTransactionType(row["transaction_type"])
        except (TypeError, ValueError) as error:
            raise GateAM9FailedAcceptanceVerificationError(
                "INVENTORY_SET",
                "the frozen Order inventory fact types are invalid"
            ) from error
        if transaction_type in by_type:
            raise GateAM9FailedAcceptanceVerificationError(
                "INVENTORY_SET",
                "the frozen Order has duplicate inventory facts"
            )
        by_type[transaction_type] = row
    if set(by_type) != {
        InventoryTransactionType.ADMIN_ADJUSTMENT,
        InventoryTransactionType.ORDER_DEDUCTION,
        InventoryTransactionType.ORDER_CANCELLATION_RESTORE,
    }:
        raise GateAM9FailedAcceptanceVerificationError(
            "INVENTORY_SET",
            "the frozen Order inventory fact types are invalid"
        )

    adjustment = by_type[InventoryTransactionType.ADMIN_ADJUSTMENT]
    deduction = by_type[InventoryTransactionType.ORDER_DEDUCTION]
    restore = by_type[InventoryTransactionType.ORDER_CANCELLATION_RESTORE]
    try:
        common_is_valid = all(
            row["product_id"] == kit_product_id
            and row["kit_color_id"] is None
            and InventorySourceType(row["source_type"])
            is InventorySourceType.ORDER
            and row["source_id"] == order_id
            and row["operator_id"] == order_user_id
            for row in (deduction, restore)
        )
        adjustment_common_is_valid = (
            adjustment["product_id"] == kit_product_id
            and adjustment["kit_color_id"] is None
            and InventorySourceType(adjustment["source_type"])
            is InventorySourceType.ADMIN
            and adjustment["source_id"] is None
        )
    except (TypeError, ValueError):
        common_is_valid = False
        adjustment_common_is_valid = False
    adjustment_operator_id = adjustment["operator_id"]
    adjustment_operator_is_valid = (
        type(adjustment_operator_id) is int
        and adjustment_operator_id > 0
        and await User.filter(
            id=adjustment_operator_id,
            role=UserRole.SUPER_ADMIN.value,
        ).count()
        == 1
    )
    supply_is_valid = (
        adjustment_common_is_valid
        and adjustment_operator_is_valid
        and adjustment["change_quantity"] == EXPECTED_KIT_STOCK
        and adjustment["before_quantity"] == 0
        and adjustment["after_quantity"] == EXPECTED_KIT_STOCK
        and adjustment["reason"] == EXPECTED_KIT_SUPPLY_REASON
        and adjustment["idempotency_key"]
        == _kit_supply_idempotency_key(acceptance_attempt_id)
    )
    if not supply_is_valid:
        raise GateAM9FailedAcceptanceVerificationError(
            "INVENTORY_SUPPLY",
            "the frozen Kit supply adjustment is invalid",
        )

    if (
        not common_is_valid
        or adjustment["change_quantity"] != EXPECTED_KIT_STOCK
        or adjustment["before_quantity"] != 0
        or adjustment["after_quantity"] != EXPECTED_KIT_STOCK
        or deduction["change_quantity"] != -1
        or deduction["before_quantity"] != EXPECTED_KIT_STOCK
        or deduction["after_quantity"] != EXPECTED_KIT_STOCK - 1
        or deduction["reason"] != INVENTORY_ORDER_DEDUCTION_REASON
        or deduction["idempotency_key"]
        != INVENTORY_ORDER_DEDUCTION_IDEMPOTENCY_KEY.format(
            order_id=order_id,
            product_id=kit_product_id,
        )
        or restore["change_quantity"] != 1
        or restore["before_quantity"] != EXPECTED_KIT_STOCK - 1
        or restore["after_quantity"] != EXPECTED_KIT_STOCK
        or restore["reason"] != INVENTORY_ORDER_RESTORE_REASON
        or restore["idempotency_key"]
        != INVENTORY_ORDER_RESTORE_IDEMPOTENCY_KEY.format(
            order_id=order_id,
            product_id=kit_product_id,
        )
        or deduction["after_quantity"] != restore["before_quantity"]
        or deduction["change_quantity"] + restore["change_quantity"] != 0
        or not int(adjustment["id"]) < int(deduction["id"]) < int(restore["id"])
        or not adjustment["created_at"]
        <= deduction["created_at"]
        <= restore["created_at"]
    ):
        raise GateAM9FailedAcceptanceVerificationError(
            "INVENTORY_ORDER_CHAIN",
            "the frozen Order inventory balance chain is invalid"
        )


async def verify_failed_acceptance(
    *,
    candidate_sha: str,
    acceptance_attempt_id: str,
    order_id: int,
    experience_product_id: int,
    kit_product_id: int,
    experience_items: Sequence[ExperienceItemExpectation],
    kit_item_id: int,
    kit_price: Decimal,
) -> dict[str, Any]:
    """只读核验一个已由 pre-claim pending 冻结的失败验收足迹。"""

    _validate_root_identities(
        candidate_sha=candidate_sha,
        acceptance_attempt_id=acceptance_attempt_id,
    )
    frozen_items = _validate_expectations(
        order_id=order_id,
        experience_product_id=experience_product_id,
        kit_product_id=kit_product_id,
        experience_items=experience_items,
        kit_item_id=kit_item_id,
    )
    order = await _verify_order(order_id)
    await _verify_fixtures(
        experience_product_id=experience_product_id,
        kit_product_id=kit_product_id,
        acceptance_attempt_id=acceptance_attempt_id,
    )
    await _verify_kit(kit_product_id=kit_product_id, kit_price=kit_price)
    await _verify_experience_options(
        experience_product_id=experience_product_id,
        experience_items=frozen_items,
    )
    await _verify_fixture_images(
        experience_product_id=experience_product_id,
        kit_product_id=kit_product_id,
        experience_items=frozen_items,
    )
    experience_snapshots = await _verify_order_items(
        order_id=order_id,
        experience_product_id=experience_product_id,
        kit_product_id=kit_product_id,
        experience_items=frozen_items,
        kit_item_id=kit_item_id,
        kit_price=kit_price,
        acceptance_attempt_id=acceptance_attempt_id,
    )
    absent_counts = await _verify_absent_dependants(order_id)
    await _verify_inventory(
        acceptance_attempt_id=acceptance_attempt_id,
        order_id=order_id,
        kit_product_id=kit_product_id,
        order_user_id=int(order["user_id"]),
    )

    counts = {
        "orders": 1,
        "fixtures": 2,
        "fixture_images": 5,
        "experience_options": 3,
        "order_items": 4,
        "experience_items": 3,
        "kit_items": 1,
        **absent_counts,
        "admin_adjustments": 1,
        "order_deductions": 1,
        "cancellation_restores": 1,
    }
    evidence = {
        "order": {
            "count": 1,
            "status": "cancelled",
            "total_amount": "5.00",
            "remark_matches": True,
        },
        "fixtures": {
            "count": 2,
            "experience": {"product_type": "experience", "online": False},
            "kit": {
                "product_type": "kit",
                "kit_kind": "fixed",
                "online": False,
                "stock": EXPECTED_KIT_STOCK,
            },
        },
        "experience_options": {"count": 3},
        "fixture_images": {"count": 5},
        "order_items": {
            "count": 4,
            "experience_snapshots": experience_snapshots,
            "kit_snapshot": {"duration_minutes": None, "quantity": 1},
        },
        "dependent_records": dict(absent_counts),
        "inventory": {
            "admin_adjustment": {
                "count": 1,
                "change_quantity": EXPECTED_KIT_STOCK,
                "before_quantity": 0,
                "after_quantity": EXPECTED_KIT_STOCK,
            },
            "order_deduction": {
                "count": 1,
                "change_quantity": -1,
                "before_quantity": EXPECTED_KIT_STOCK,
                "after_quantity": EXPECTED_KIT_STOCK - 1,
            },
            "cancellation_restore": {
                "count": 1,
                "change_quantity": 1,
                "before_quantity": EXPECTED_KIT_STOCK - 1,
                "after_quantity": EXPECTED_KIT_STOCK,
            },
            "net_change_quantity": 0,
        },
    }
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "passed": True,
        "counts": counts,
        "evidence_sha256": _canonical_sha256(evidence),
        "secret_values_recorded": False,
    }


async def run(
    *,
    candidate_sha: str,
    acceptance_attempt_id: str,
    order_id: int,
    experience_product_id: int,
    kit_product_id: int,
    experience_items: Sequence[ExperienceItemExpectation],
    kit_item_id: int,
    kit_price: Decimal,
) -> dict[str, Any]:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        return await verify_failed_acceptance(
            candidate_sha=candidate_sha,
            acceptance_attempt_id=acceptance_attempt_id,
            order_id=order_id,
            experience_product_id=experience_product_id,
            kit_product_id=kit_product_id,
            experience_items=experience_items,
            kit_item_id=kit_item_id,
            kit_price=kit_price,
        )
    finally:
        await Tortoise.close_connections()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        effective_argv = tuple(sys.argv[1:] if argv is None else argv)
        if effective_argv:
            raise GateAM9FailedAcceptanceVerificationError(
                "INPUT_CONTRACT",
                "command-line identities are forbidden"
            )
        arguments = _parse_input_payload(_read_stdin_payload())
        arguments["experience_items"] = _validate_expectations(
            order_id=arguments["order_id"],
            experience_product_id=arguments["experience_product_id"],
            kit_product_id=arguments["kit_product_id"],
            experience_items=arguments["experience_items"],
            kit_item_id=arguments["kit_item_id"],
        )
        result = asyncio.run(run(**arguments))
        output_line = _json_protocol_line(result)
    except GateAM9FailedAcceptanceVerificationError as error:
        sys.stdout.write(_json_protocol_line(_refusal_payload(error.reason_code)))
        return 2
    except Exception:
        sys.stdout.write(_json_protocol_line(_refusal_payload("INTERNAL_FAILURE")))
        return 2
    sys.stdout.write(output_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
