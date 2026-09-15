"""WalletAccount、WalletTransaction 与 Repository 数据契约测试。"""

from decimal import Decimal

import pytest
from tortoise import fields
from tortoise.exceptions import IntegrityError, ValidationError
from tortoise.fields.relational import ForeignKeyFieldInstance, OneToOneFieldInstance
from tortoise.transactions import in_transaction

from app.common.constants.wallet import (
    MONEY_AMOUNT_DECIMAL_PLACES,
    MONEY_AMOUNT_MAX_DIGITS,
    WALLET_BALANCE_MAX,
    WALLET_IDEMPOTENCY_KEY_DB_MAX_LENGTH,
    WALLET_REASON_MAX_LENGTH,
)
from app.common.enums.wallet import (
    WalletStatus,
    WalletTransactionSourceType,
    WalletTransactionType,
)
from app.db.indexes import UniqueIndex
from app.models.fields import AsciiBinaryCharField, StrictDecimalField
from app.models.order import Order
from app.models.user import User
from app.models.wallet import WalletAccount, WalletTransaction
from app.repositories.wallet_repo import (
    WalletRepository,
    WalletTransactionCreateData,
)


async def _create_user(username: str) -> User:
    return await User.create(
        username=username,
        password="hashed-password",
        nickname=username,
    )


async def _create_account(
    username: str = "wallet-user",
    *,
    balance: Decimal = Decimal("0.00"),
) -> tuple[User, WalletAccount]:
    user = await _create_user(username)
    account = await WalletAccount.create(user=user, balance=balance)
    return user, account


async def _create_transaction(
    account: WalletAccount,
    *,
    key: str = "wallet:test:transaction:1",
    change_amount: Decimal = Decimal("10.00"),
    before_balance: Decimal = Decimal("0.00"),
    after_balance: Decimal = Decimal("10.00"),
    source_type: WalletTransactionSourceType = WalletTransactionSourceType.ADMIN,
    source_id: int | None = None,
    operator: User | None = None,
) -> WalletTransaction:
    return await WalletTransaction.create(
        wallet_account=account,
        transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
        change_amount=change_amount,
        before_balance=before_balance,
        after_balance=after_balance,
        source_type=source_type,
        source_id=source_id,
        operator=operator,
        reason="测试资金变化",
        idempotency_key=key,
    )


def test_wallet_account_metadata_matches_contract() -> None:
    fields_map = WalletAccount._meta.fields_map
    user_field = fields_map["user"]
    balance_field = fields_map["balance"]
    status_field = fields_map["status"]

    assert WalletAccount._meta.db_table == "wallet_accounts"
    assert isinstance(user_field, OneToOneFieldInstance)
    assert user_field.source_field == "user_id"
    assert user_field.related_name == "wallet_account"
    assert user_field.on_delete == fields.RESTRICT
    assert user_field.null is False
    assert user_field.unique is True

    assert isinstance(balance_field, StrictDecimalField)
    assert balance_field.max_digits == MONEY_AMOUNT_MAX_DIGITS
    assert balance_field.decimal_places == MONEY_AMOUNT_DECIMAL_PLACES
    assert balance_field.default == Decimal("0.00")
    assert balance_field.db_default == Decimal("0.00")
    assert status_field.enum_type is WalletStatus
    assert status_field.default is WalletStatus.ACTIVE
    assert status_field.db_default == WalletStatus.ACTIVE.value
    assert WalletAccount._meta.indexes == ()


def test_wallet_transaction_metadata_and_indexes_match_contract() -> None:
    fields_map = WalletTransaction._meta.fields_map
    account_field = fields_map["wallet_account"]
    operator_field = fields_map["operator"]

    assert WalletTransaction._meta.db_table == "wallet_transactions"
    assert isinstance(account_field, ForeignKeyFieldInstance)
    assert account_field.source_field == "wallet_account_id"
    assert account_field.related_name == "transactions"
    assert account_field.on_delete == fields.RESTRICT
    assert account_field.null is False
    assert fields_map["transaction_type"].enum_type is WalletTransactionType
    assert fields_map["source_type"].enum_type is WalletTransactionSourceType

    for field_name in ("change_amount", "before_balance", "after_balance"):
        amount_field = fields_map[field_name]
        assert isinstance(amount_field, StrictDecimalField)
        assert amount_field.max_digits == MONEY_AMOUNT_MAX_DIGITS
        assert amount_field.decimal_places == MONEY_AMOUNT_DECIMAL_PLACES

    assert fields_map["source_id"].null is True
    assert isinstance(operator_field, ForeignKeyFieldInstance)
    assert operator_field.source_field == "operator_id"
    assert operator_field.related_name == "operated_wallet_transactions"
    assert operator_field.on_delete == fields.RESTRICT
    assert operator_field.null is True
    assert fields_map["reason"].max_length == WALLET_REASON_MAX_LENGTH
    assert (
        fields_map["idempotency_key"].max_length
        == WALLET_IDEMPOTENCY_KEY_DB_MAX_LENGTH
    )
    assert isinstance(fields_map["idempotency_key"], AsciiBinaryCharField)
    assert fields_map["idempotency_key"].get_db_field_types()["mysql"] == (
        "VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin"
    )

    indexes = WalletTransaction._meta.indexes
    assert isinstance(indexes[0], UniqueIndex)
    assert [(index.name, index.fields) for index in indexes] == [
        ("uidx_wallet_transaction_idempotency", ["idempotency_key"]),
        (
            "idx_wallet_transaction_wallet_created_id",
            ["wallet_account_id", "created_at", "id"],
        ),
        (
            "idx_wallet_transaction_source_created_id",
            ["source_type", "source_id", "created_at", "id"],
        ),
        (
            "idx_wallet_transaction_type_created_id",
            ["transaction_type", "created_at", "id"],
        ),
        ("idx_wallet_transaction_created_id", ["created_at", "id"]),
    ]


async def test_wallet_account_defaults_boundaries_and_one_per_user() -> None:
    user = await _create_user("wallet-boundary-user")
    account = await WalletAccount.create(user=user)
    loaded = await WalletAccount.get(id=account.id)

    assert loaded.balance == Decimal("0.00")
    assert loaded.status is WalletStatus.ACTIVE

    max_user = await _create_user("wallet-max-user")
    maximum = await WalletAccount.create(user=max_user, balance=WALLET_BALANCE_MAX)
    assert (await WalletAccount.get(id=maximum.id)).balance == Decimal("1000.00")

    with pytest.raises(IntegrityError):
        await WalletAccount.create(user=user)


@pytest.mark.parametrize(
    ("balance", "expected_message"),
    [
        (Decimal("-0.01"), "greater or equal"),
        (Decimal("1000.01"), "less or equal"),
        (Decimal("1.001"), "Decimal places should be less or equal to 2"),
    ],
)
async def test_wallet_account_rejects_invalid_balances(
    balance: Decimal,
    expected_message: str,
) -> None:
    user = await _create_user(f"wallet-invalid-{str(balance).replace('.', '-')}")
    with pytest.raises(ValidationError, match=expected_message):
        await WalletAccount.create(user=user, balance=balance)


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"change_amount": Decimal("0.00")}, "must not be zero"),
        ({"change_amount": Decimal("-1000.01")}, "greater or equal"),
        ({"change_amount": Decimal("1000.01")}, "less or equal"),
        (
            {"change_amount": Decimal("1.001")},
            "Decimal places should be less or equal to 2",
        ),
        ({"before_balance": Decimal("-0.01")}, "greater or equal"),
        ({"after_balance": Decimal("1000.01")}, "less or equal"),
        ({"source_id": 0}, "greater or equal"),
        ({"reason": ""}, "Length of '' 0 < 1"),
        ({"idempotency_key": ""}, "Length of '' 0 < 1"),
    ],
)
async def test_wallet_transaction_rejects_invalid_field_boundaries(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    _, account = await _create_account(
        f"wallet-invalid-{abs(hash(repr(overrides))) % 1_000_000}"
    )
    payload: dict[str, object] = {
        "change_amount": Decimal("10.00"),
        "before_balance": Decimal("0.00"),
        "after_balance": Decimal("10.00"),
        "source_id": None,
        "reason": "测试资金变化",
        "idempotency_key": "wallet:test:invalid",
    }
    payload.update(overrides)

    with pytest.raises(ValidationError, match=expected_message):
        await WalletTransaction.create(
            wallet_account=account,
            transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
            source_type=WalletTransactionSourceType.ADMIN,
            operator=None,
            **payload,
        )


async def test_wallet_transaction_is_unique_and_restricts_foreign_keys() -> None:
    operator = await _create_user("wallet-operator")
    _, account = await _create_account("wallet-owner")
    key = "wallet:test:unique"
    await _create_transaction(account, key=key, operator=operator)

    with pytest.raises(IntegrityError):
        await _create_transaction(account, key=key, operator=operator)
    with pytest.raises(IntegrityError):
        await account.delete()
    with pytest.raises(IntegrityError):
        await operator.delete()

    assert await WalletTransaction.filter(idempotency_key=key).count() == 1


async def test_wallet_repository_writes_and_attaches_order_number() -> None:
    user = await _create_user("wallet-repository-user")
    operator = await _create_user("wallet-repository-admin")
    order = await Order.create(
        order_no="OD01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user=user,
        total_amount=Decimal("12.00"),
    )
    repository = WalletRepository()

    async with in_transaction() as connection:
        account = await repository.create_account(
            user_id=user.id,
            using_db=connection,
        )
        locked = await repository.get_account_for_update(
            user.id,
            using_db=connection,
        )
        assert locked is not None
        await repository.update_balance(
            locked,
            balance=Decimal("20.00"),
            using_db=connection,
        )
        transaction = await repository.create_transaction(
            data=WalletTransactionCreateData(
                wallet_account_id=account.id,
                transaction_type=WalletTransactionType.ORDER_PAYMENT,
                change_amount=Decimal("-12.00"),
                before_balance=Decimal("20.00"),
                after_balance=Decimal("8.00"),
                source_type=WalletTransactionSourceType.ORDER,
                source_id=order.id,
                operator_id=operator.id,
                reason="订单钱包支付",
                idempotency_key="wallet:test:order-source",
            ),
            using_db=connection,
        )

    detail = await repository.get_transaction_detail(transaction.id)
    page = await repository.list_transactions(
        user_id=user.id,
        page=1,
        page_size=10,
    )
    account = await repository.get_account_by_user_id(user.id)

    assert detail is not None
    assert detail.source_order_no == order.order_no
    assert detail.operator.id == operator.id
    assert page.total == 1
    assert page.pages == 1
    assert page.items[0].source_order_no == order.order_no
    assert account is not None
    assert account.balance == Decimal("20.00")

    async with in_transaction() as connection:
        await repository.close_account(account, using_db=connection)
    assert (await WalletAccount.get(id=account.id)).status is WalletStatus.CLOSED


async def test_wallet_repository_writes_follow_caller_transaction() -> None:
    user = await _create_user("wallet-rollback-user")
    repository = WalletRepository()

    with pytest.raises(RuntimeError, match="force rollback"):
        async with in_transaction() as connection:
            await repository.create_account(user_id=user.id, using_db=connection)
            raise RuntimeError("force rollback")

    assert await WalletAccount.filter(user_id=user.id).exists() is False


def test_wallet_transaction_repository_exposes_no_mutation_or_delete_primitive(
) -> None:
    repository = WalletRepository()
    assert not hasattr(repository, "update_transaction")
    assert not hasattr(repository, "delete_transaction")
