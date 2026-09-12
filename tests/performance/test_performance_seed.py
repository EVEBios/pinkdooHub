"""隔离性能数据的固定计数与 Audit 增量契约。"""

import pytest

from scripts.performance.seed import (
    WriteJourneyIdentity,
    _parse_write_payment_identity,
    _write_payment_pairs_are_complete,
    expected_audit_action_counts,
    expected_reconciliation_counts,
)
from scripts.performance.config import MAX_WRITE_JOURNEYS_PER_RUN


def test_zero_journey_fixture_counts_cover_all_side_effect_domains() -> None:
    counts = expected_reconciliation_counts(0)
    actions = expected_audit_action_counts(0)

    assert counts["users"] == 11
    assert counts["products"] == 10
    assert counts["product_kits"] == 10
    assert counts["product_kit_colors"] == 224
    assert counts["product_images"] == 10
    assert counts["bead_colors"] == 221
    assert counts["wallet_accounts"] == 10
    assert counts["recharge_orders"] == 0
    assert counts["refunds"] == 0
    assert counts["reservations"] == 0
    assert actions == {"LOGIN": 11}


def test_every_completed_write_journey_has_exact_rows_and_six_audits() -> None:
    baseline = expected_reconciliation_counts(0)
    after = expected_reconciliation_counts(7)
    actions = expected_audit_action_counts(7)

    assert after["orders"] - baseline["orders"] == 21
    assert after["order_items"] - baseline["order_items"] == 21
    assert after["payments"] - baseline["payments"] == 14
    assert after["settlements"] - baseline["settlements"] == 14
    assert after["wallet_transactions"] - baseline["wallet_transactions"] == 14
    assert after["inventory_transactions"] - baseline["inventory_transactions"] == 28
    assert after["audit_logs"] - baseline["audit_logs"] == 42
    assert actions == {
        "LOGIN": 11,
        "CREATE_ORDER": 21,
        "CANCEL_ORDER": 7,
        "PAY_ORDER": 14,
    }
    assert MAX_WRITE_JOURNEYS_PER_RUN == 3000


def test_write_payment_keys_bind_full_journey_identity() -> None:
    run_id = "20260909t120000"
    normal = _parse_write_payment_identity(
        "payment:wallet:"
        "perf-20260909t120000-measured-r3-v10-u9-j600-pay",
        run_id=run_id,
    )
    assisted = _parse_write_payment_identity(
        "payment:admin-assisted:"
        "perf-20260909t120000-measured-r3-v10-u9-j600-assisted",
        run_id=run_id,
    )
    identity = WriteJourneyIdentity(
        phase="measured",
        round_number=3,
        vus=10,
        user_index=9,
        journey_number=600,
    )

    assert normal == (identity, "pay")
    assert assisted == (identity, "assisted")
    assert not _write_payment_pairs_are_complete(
        {normal[0]}, {assisted[0]}, expected_write_journeys=1
    )

    first_identity = WriteJourneyIdentity(
        phase="measured",
        round_number=3,
        vus=10,
        user_index=9,
        journey_number=1,
    )
    assert _write_payment_pairs_are_complete(
        {first_identity}, {first_identity}, expected_write_journeys=1
    )


@pytest.mark.parametrize(
    "key",
    (
        "payment:wallet:perf-20260908t120000-measured-r3-v10-u9-j1-pay",
        "payment:wallet:perf-20260909t120000-other-r3-v10-u9-j1-pay",
        "payment:wallet:perf-20260909t120000-measured-r0-v10-u9-j1-pay",
        "payment:wallet:perf-20260909t120000-measured-r3-v6-u5-j1-pay",
        "payment:wallet:perf-20260909t120000-measured-r3-v5-u5-j1-pay",
        "payment:wallet:perf-20260909t120000-measured-r3-v10-u9-j0-pay",
        "payment:wallet:perf-20260909t120000-measured-r3-v10-u9-j601-pay",
        "payment:wallet:perf-20260909t120000-measured-r3-v10-u9-j1-assisted",
        "payment:admin-assisted:perf-20260909t120000-measured-r3-v10-u9-j1-pay",
        "payment:wallet:perf-20260909t120000-measured-r3-v10-u09-j1-pay",
    ),
)
def test_write_payment_key_parser_rejects_wrong_or_ambiguous_identity(
    key: str,
) -> None:
    assert _parse_write_payment_identity(
        key,
        run_id="20260909t120000",
    ) is None


def test_write_payment_pair_check_rejects_missing_or_crossed_journeys() -> None:
    first = WriteJourneyIdentity("warmup", 1, 5, 0, 1)
    second = WriteJourneyIdentity("warmup", 1, 5, 0, 2)
    third = WriteJourneyIdentity("warmup", 1, 5, 0, 3)

    assert not _write_payment_pairs_are_complete(
        {first},
        set(),
        expected_write_journeys=1,
    )
    assert not _write_payment_pairs_are_complete(
        {first},
        {second},
        expected_write_journeys=1,
    )
    assert not _write_payment_pairs_are_complete(
        {first, third},
        {first, third},
        expected_write_journeys=2,
    )
