"""Payment、Settlement、RechargeOrder、Refund 与 Repository 契约测试。"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from tortoise import connections, fields
from tortoise.exceptions import IntegrityError, ValidationError
from tortoise.fields.relational import ForeignKeyFieldInstance, OneToOneFieldInstance
from tortoise.transactions import in_transaction

from app.common.constants.wallet import (
    FINANCIAL_NUMBER_LENGTH,
    MONEY_AMOUNT_DECIMAL_PLACES,
    MONEY_AMOUNT_MAX_DIGITS,
    PAYMENT_PROVIDER_REFERENCE_MAX_LENGTH,
    RECHARGE_AMOUNT_MAX,
    RECHARGE_AMOUNT_MIN,
)
from app.common.enums.wallet import (
    PaymentMethod,
    PaymentPurpose,
    PaymentStatus,
    RechargeOrderStatus,
    RefundStatus,
)
from app.db.indexes import UniqueIndex
from app.models.fields import AsciiBinaryCharField, StrictDecimalField
from app.models.order import Order
from app.models.payment import Payment, PaymentSettlement, RechargeOrder, Refund
from app.models.user import User
from app.models.wallet import WalletAccount
from app.repositories.payment_repo import (
    PaymentCreateData,
    PaymentRepository,
    RechargeOrderCreateData,
    RefundCreateData,
)


def _financial_no(prefix: str, sequence: int) -> str:
    return f"{prefix}{sequence:026d}"


async def _create_user(username: str) -> User:
    return await User.create(
        username=username,
        password="hashed-password",
        nickname=username,
    )


async def _create_order(user: User, sequence: int = 1) -> Order:
    return await Order.create(
        order_no=_financial_no("OD", sequence),
        user=user,
        total_amount=Decimal("50.00"),
    )


async def _create_wallet(user: User) -> WalletAccount:
    return await WalletAccount.create(user=user)


async def _create_payment(
    user: User,
    *,
    sequence: int = 1,
    order: Order | None = None,
    recharge_order: RechargeOrder | None = None,
    purpose: PaymentPurpose = PaymentPurpose.ORDER,
    method: PaymentMethod = PaymentMethod.WALLET,
    key: str | None = None,
    provider_transaction_id: str | None = None,
) -> Payment:
    return await Payment.create(
        payment_no=_financial_no("PY", sequence),
        user=user,
        purpose=purpose,
        method=method,
        amount=Decimal("50.00"),
        order=order,
        recharge_order=recharge_order,
        idempotency_key=key or f"payment:test:{sequence}",
        provider_transaction_id=provider_transaction_id,
    )


def _assert_restrict_relation(
    relation: ForeignKeyFieldInstance,
    *,
    source_field: str,
    nullable: bool,
) -> None:
    assert relation.source_field == source_field
    assert relation.on_delete == fields.RESTRICT
    assert relation.null is nullable


def test_recharge_and_payment_metadata_matches_contract() -> None:
    recharge_fields = RechargeOrder._meta.fields_map
    payment_fields = Payment._meta.fields_map

    assert RechargeOrder._meta.db_table == "recharge_orders"
    assert recharge_fields["recharge_no"].max_length == FINANCIAL_NUMBER_LENGTH
    assert recharge_fields["recharge_no"].unique is True
    _assert_restrict_relation(
        recharge_fields["user"], source_field="user_id", nullable=False
    )
    _assert_restrict_relation(
        recharge_fields["wallet_account"],
        source_field="wallet_account_id",
        nullable=False,
    )
    assert isinstance(recharge_fields["amount"], StrictDecimalField)
    assert recharge_fields["status"].enum_type is RechargeOrderStatus
    assert recharge_fields["status"].default is RechargeOrderStatus.PENDING
    assert isinstance(recharge_fields["idempotency_key"], AsciiBinaryCharField)

    assert Payment._meta.db_table == "payments"
    assert payment_fields["payment_no"].max_length == FINANCIAL_NUMBER_LENGTH
    assert payment_fields["payment_no"].unique is True
    _assert_restrict_relation(
        payment_fields["user"], source_field="user_id", nullable=False
    )
    _assert_restrict_relation(
        payment_fields["order"], source_field="order_id", nullable=True
    )
    _assert_restrict_relation(
        payment_fields["recharge_order"],
        source_field="recharge_order_id",
        nullable=True,
    )
    assert payment_fields["purpose"].enum_type is PaymentPurpose
    assert payment_fields["method"].enum_type is PaymentMethod
    assert payment_fields["status"].enum_type is PaymentStatus
    assert payment_fields["status"].default is PaymentStatus.PENDING
    assert isinstance(payment_fields["idempotency_key"], AsciiBinaryCharField)
    assert (
        payment_fields["provider_transaction_id"].max_length
        == PAYMENT_PROVIDER_REFERENCE_MAX_LENGTH
    )
    assert payment_fields["provider_transaction_id"].null is True

    for amount_field in (recharge_fields["amount"], payment_fields["amount"]):
        assert isinstance(amount_field, StrictDecimalField)
        assert amount_field.max_digits == MONEY_AMOUNT_MAX_DIGITS
        assert amount_field.decimal_places == MONEY_AMOUNT_DECIMAL_PLACES

    assert [(index.name, index.fields) for index in RechargeOrder._meta.indexes] == [
        ("uidx_recharge_order_idempotency", ["idempotency_key"]),
        (
            "idx_recharge_order_user_created_id",
            ["user_id", "created_at", "id"],
        ),
        (
            "idx_recharge_order_status_created_id",
            ["status", "created_at", "id"],
        ),
    ]
    assert all(isinstance(index, UniqueIndex) for index in Payment._meta.indexes[:2])
    assert [(index.name, index.fields) for index in Payment._meta.indexes] == [
        ("uidx_payment_idempotency", ["idempotency_key"]),
        ("uidx_payment_provider_transaction", ["provider_transaction_id"]),
        ("idx_payment_user_created_id", ["user_id", "created_at", "id"]),
        ("idx_payment_order_created_id", ["order_id", "created_at", "id"]),
        (
            "idx_payment_recharge_created_id",
            ["recharge_order_id", "created_at", "id"],
        ),
        ("idx_payment_status_created_id", ["status", "created_at", "id"]),
    ]


def test_settlement_and_refund_metadata_matches_contract() -> None:
    settlement_fields = PaymentSettlement._meta.fields_map
    refund_fields = Refund._meta.fields_map

    assert PaymentSettlement._meta.db_table == "payment_settlements"
    for name, source_field in (("payment", "payment_id"), ("order", "order_id")):
        relation = settlement_fields[name]
        assert isinstance(relation, OneToOneFieldInstance)
        _assert_restrict_relation(
            relation,
            source_field=source_field,
            nullable=False,
        )
        assert relation.unique is True

    assert Refund._meta.db_table == "refunds"
    for name, source_field in (
        ("settlement", "settlement_id"),
        ("order", "order_id"),
    ):
        relation = refund_fields[name]
        assert isinstance(relation, OneToOneFieldInstance)
        _assert_restrict_relation(
            relation,
            source_field=source_field,
            nullable=False,
        )
        assert relation.unique is True
    assert isinstance(refund_fields["operator"], ForeignKeyFieldInstance)
    _assert_restrict_relation(
        refund_fields["operator"],
        source_field="operator_id",
        nullable=False,
    )
    assert refund_fields["status"].enum_type is RefundStatus
    assert refund_fields["status"].default is RefundStatus.PENDING
    assert isinstance(refund_fields["idempotency_key"], AsciiBinaryCharField)
    assert isinstance(refund_fields["inventory_restored"], fields.BooleanField)
    assert refund_fields["inventory_restored"].default is False
    assert refund_fields["inventory_restored"].db_default is False
    assert refund_fields["provider_refund_id"].null is True

    assert [(index.name, index.fields) for index in Refund._meta.indexes] == [
        ("uidx_refund_idempotency", ["idempotency_key"]),
        ("uidx_refund_provider_reference", ["provider_refund_id"]),
        ("idx_refund_order_created_id", ["order_id", "created_at", "id"]),
        ("idx_refund_status_created_id", ["status", "created_at", "id"]),
    ]


@pytest.mark.parametrize(
    ("amount", "expected_message"),
    [
        (RECHARGE_AMOUNT_MIN - Decimal("0.01"), "greater or equal"),
        (RECHARGE_AMOUNT_MAX + Decimal("0.01"), "less or equal"),
        (Decimal("1.001"), "Decimal places should be less or equal to 2"),
    ],
)
async def test_recharge_order_rejects_invalid_amounts(
    amount: Decimal,
    expected_message: str,
) -> None:
    user = await _create_user(f"recharge-invalid-{abs(hash(amount)) % 100000}")
    wallet = await _create_wallet(user)

    with pytest.raises(ValidationError, match=expected_message):
        await RechargeOrder.create(
            recharge_no=_financial_no("RC", 1),
            user=user,
            wallet_account=wallet,
            amount=amount,
            idempotency_key="recharge:test:invalid",
        )


async def test_recharge_boundaries_and_number_prefix_validation() -> None:
    minimum_user = await _create_user("recharge-min-user")
    minimum_wallet = await _create_wallet(minimum_user)
    maximum_user = await _create_user("recharge-max-user")
    maximum_wallet = await _create_wallet(maximum_user)

    minimum = await RechargeOrder.create(
        recharge_no=_financial_no("RC", 1),
        user=minimum_user,
        wallet_account=minimum_wallet,
        amount=RECHARGE_AMOUNT_MIN,
        idempotency_key="recharge:test:min",
    )
    maximum = await RechargeOrder.create(
        recharge_no=_financial_no("RC", 2),
        user=maximum_user,
        wallet_account=maximum_wallet,
        amount=RECHARGE_AMOUNT_MAX,
        idempotency_key="recharge:test:max",
    )

    assert minimum.amount == Decimal("1.00")
    assert maximum.amount == Decimal("1000.00")
    with pytest.raises(ValidationError, match="does not match regex"):
        await RechargeOrder.create(
            recharge_no=_financial_no("PY", 3),
            user=minimum_user,
            wallet_account=minimum_wallet,
            amount=Decimal("1.00"),
            idempotency_key="recharge:test:wrong-prefix",
        )


async def test_nullable_provider_references_are_unique_when_present() -> None:
    user = await _create_user("payment-provider-user")
    first_order = await _create_order(user, 10)
    second_order = await _create_order(user, 11)
    third_order = await _create_order(user, 12)

    await _create_payment(user, sequence=10, order=first_order)
    await _create_payment(user, sequence=11, order=second_order)
    await _create_payment(
        user,
        sequence=12,
        order=third_order,
        provider_transaction_id="wechat-transaction-1",
    )

    fourth_order = await _create_order(user, 13)
    with pytest.raises(IntegrityError):
        await _create_payment(
            user,
            sequence=13,
            order=fourth_order,
            provider_transaction_id="wechat-transaction-1",
        )

    fifth_order = await _create_order(user, 14)
    with pytest.raises(ValidationError, match="Length of '' 0 < 1"):
        await _create_payment(
            user,
            sequence=14,
            order=fifth_order,
            provider_transaction_id="",
        )


async def test_settlement_and_refund_unique_facts_round_trip() -> None:
    user = await _create_user("refund-owner")
    operator = await _create_user("refund-operator")
    order = await _create_order(user, 20)
    payment = await _create_payment(user, sequence=20, order=order)
    await Payment.filter(id=payment.id).update(status=PaymentStatus.SUCCEEDED)
    settlement = await PaymentSettlement.create(
        payment=payment,
        order=order,
        amount=Decimal("50.00"),
    )
    refund = await Refund.create(
        refund_no=_financial_no("RF", 20),
        settlement=settlement,
        order=order,
        operator=operator,
        amount=Decimal("50.00"),
        inventory_restored=True,
        reason="全额退款",
        idempotency_key="refund:test:20",
    )
    loaded = await Refund.get(id=refund.id)

    assert loaded.status is RefundStatus.PENDING
    assert loaded.inventory_restored is True
    assert loaded.amount == Decimal("50.00")

    with pytest.raises(IntegrityError):
        await Refund.create(
            refund_no=_financial_no("RF", 21),
            settlement=settlement,
            order=order,
            operator=operator,
            amount=Decimal("50.00"),
            inventory_restored=False,
            reason="重复退款",
            idempotency_key="refund:test:21",
        )


async def test_payment_repository_crud_locks_and_in_flight_query() -> None:
    user = await _create_user("payment-repository-user")
    operator = await _create_user("payment-repository-admin")
    wallet = await _create_wallet(user)
    order = await _create_order(user, 30)
    repository = PaymentRepository()
    succeeded_at = datetime.now(timezone.utc)

    async with in_transaction() as connection:
        recharge = await repository.create_recharge_order(
            data=RechargeOrderCreateData(
                recharge_no=_financial_no("RC", 30),
                user_id=user.id,
                wallet_account_id=wallet.id,
                amount=Decimal("50.00"),
                idempotency_key="recharge:test:repository",
            ),
            using_db=connection,
        )
        assert await repository.has_in_flight_for_user(
            user.id,
            using_db=connection,
        )
        await repository.update_recharge_order_status(
            recharge,
            status=RechargeOrderStatus.PAID,
            succeeded_at=succeeded_at,
            using_db=connection,
        )
        payment = await repository.create_payment(
            data=PaymentCreateData(
                payment_no=_financial_no("PY", 30),
                user_id=user.id,
                purpose=PaymentPurpose.ORDER,
                method=PaymentMethod.WALLET,
                amount=Decimal("50.00"),
                order_id=order.id,
                recharge_order_id=None,
                idempotency_key="payment:test:repository",
            ),
            using_db=connection,
        )
        assert await repository.has_in_flight_for_user(
            user.id,
            using_db=connection,
        )
        await repository.update_payment_status(
            payment,
            status=PaymentStatus.SUCCEEDED,
            provider_transaction_id=None,
            succeeded_at=succeeded_at,
            using_db=connection,
        )
        settlement = await repository.create_settlement(
            payment_id=payment.id,
            order_id=order.id,
            amount=payment.amount,
            using_db=connection,
        )
        refund = await repository.create_refund(
            data=RefundCreateData(
                refund_no=_financial_no("RF", 30),
                settlement_id=settlement.id,
                order_id=order.id,
                operator_id=operator.id,
                amount=settlement.amount,
                inventory_restored=False,
                reason="仓储退款测试",
                idempotency_key="refund:test:repository",
            ),
            using_db=connection,
        )
        assert await repository.has_in_flight_for_user(
            user.id,
            using_db=connection,
        )
        await repository.update_refund_status(
            refund,
            status=RefundStatus.SUCCEEDED,
            provider_refund_id=None,
            succeeded_at=succeeded_at,
            using_db=connection,
        )

        assert (await repository.get_recharge_order_for_update(
            recharge.id,
            using_db=connection,
        )).id == recharge.id
        assert (await repository.get_payment_for_update(
            payment.id,
            using_db=connection,
        )).id == payment.id
        assert (await repository.get_payment_by_order_id_for_update(
            order.id,
            using_db=connection,
        )).id == payment.id
        assert (await repository.get_settlement_for_update(
            settlement.id,
            using_db=connection,
        )).id == settlement.id
        assert (await repository.get_settlement_by_order_id_for_update(
            order.id,
            using_db=connection,
        )).id == settlement.id
        assert (await repository.get_refund_for_update(
            refund.id,
            using_db=connection,
        )).id == refund.id
        assert (await repository.get_refund_by_order_id_for_update(
            order.id,
            using_db=connection,
        )).id == refund.id
        assert not await repository.has_in_flight_for_user(
            user.id,
            using_db=connection,
        )

    assert (await repository.get_payment_by_id(payment.id)).id == payment.id
    assert (await repository.get_payment_by_order_id(order.id)).id == payment.id
    assert (
        await repository.get_payment_by_idempotency_key(payment.idempotency_key)
    ).id == payment.id
    settlement_by_order = await repository.get_settlement_by_order_id(order.id)
    assert settlement_by_order is not None
    assert settlement_by_order.payment.id == payment.id
    assert (
        await repository.get_settlement_by_payment_id(payment.id)
    ).order.id == order.id
    assert (await repository.get_refund_by_order_id(order.id)).id == refund.id
    assert (
        await repository.get_refund_by_settlement_id(settlement.id)
    ).id == refund.id
    assert (
        await repository.get_refund_by_idempotency_key(refund.idempotency_key)
    ).id == refund.id


async def test_payment_repository_writes_follow_caller_transaction() -> None:
    user = await _create_user("payment-rollback-user")
    order = await _create_order(user, 40)
    repository = PaymentRepository()

    with pytest.raises(RuntimeError, match="force rollback"):
        async with in_transaction() as connection:
            await repository.create_payment(
                data=PaymentCreateData(
                    payment_no=_financial_no("PY", 40),
                    user_id=user.id,
                    purpose=PaymentPurpose.ORDER,
                    method=PaymentMethod.WALLET,
                    amount=Decimal("50.00"),
                    order_id=order.id,
                    recharge_order_id=None,
                    idempotency_key="payment:test:rollback",
                ),
                using_db=connection,
            )
            raise RuntimeError("force rollback")

    rolled_back = await Payment.filter(
        idempotency_key="payment:test:rollback"
    ).exists()
    assert rolled_back is False


async def test_all_payment_foreign_keys_physically_restrict_deletion() -> None:
    user = await _create_user("payment-restrict-user")
    wallet = await _create_wallet(user)
    recharge = await RechargeOrder.create(
        recharge_no=_financial_no("RC", 50),
        user=user,
        wallet_account=wallet,
        amount=Decimal("1.00"),
        idempotency_key="recharge:test:restrict",
    )

    with pytest.raises(IntegrityError):
        await wallet.delete()
    with pytest.raises(IntegrityError):
        await user.delete()

    connection = connections.get("default")
    foreign_keys = []
    for table in (
        "wallet_accounts",
        "wallet_transactions",
        "recharge_orders",
        "payments",
        "payment_settlements",
        "refunds",
    ):
        foreign_keys.extend(
            await connection.execute_query_dict(f"PRAGMA foreign_key_list('{table}')")
        )
    assert len(foreign_keys) == 13
    assert {row["on_delete"] for row in foreign_keys} == {"RESTRICT"}
