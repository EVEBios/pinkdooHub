from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
import errno
import json
import os
from pathlib import Path
import signal
import stat
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.release import gatea_m9_acceptance as acceptance
from scripts.release import gatea_candidate


CANDIDATE_SHA = "c" * 40
SOURCE_SHA = "b" * 40
IMAGE_ID = "sha256:" + "d" * 64
SESSION_NO = "TS" + "0" * 26
QR_TOKEN = "A" * 32
STARTED_AT = "2026-09-10T01:00:00+00:00"


@pytest.fixture(autouse=True)
def _use_current_process_as_record_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试不以 root 运行时仍精确覆盖 owner/mode/nlink 约束。"""

    monkeypatch.setattr(acceptance, "ROOT_UID", os.geteuid())
    monkeypatch.setattr(acceptance, "ROOT_GID", os.getegid())


def _zero_reconcile(*, scanned: int = 0) -> dict[str, int]:
    return {
        "open_sessions": 0,
        "occupancies": 0,
        "closed_with_occupancy": 0,
        "awaiting_with_timers": 0,
        "active_without_timers": 0,
        "scanned": scanned,
        "violations": 0,
    }


def _wallet_reconcile(*, scanned: int = 11) -> dict[str, int]:
    return {"scanned": scanned, "mismatches": 0, "violations": 0}


def _context(tmp_path: Path) -> acceptance.PreparedContext:
    tmp_path.chmod(0o755)
    return acceptance.PreparedContext(
        values={"GATEA_LOOPBACK_PORT": "18080"},
        config_file=tmp_path / "gatea.env",
        secret_dir=tmp_path / "secrets",
        release_record_dir=tmp_path / "release",
        record_dir=tmp_path,
        credentials_file=tmp_path / "credentials.json",
        representative_record=tmp_path / "m7.json",
        candidate_sha=CANDIDATE_SHA,
        image_id=IMAGE_ID,
        operations_sha=CANDIDATE_SHA,
        ci_run_id="34481317426",
        source_candidate_sha=SOURCE_SHA,
        source_image_id="sha256:" + "e" * 64,
        upgrade_record_sha256="1" * 64,
        upgrade_plan_replay_record_sha256="2" * 64,
        representative_record_sha256="3" * 64,
        credentials_sha256="4" * 64,
        pre_reconcile=_zero_reconcile(),
        pre_wallet_reconcile=_wallet_reconcile(),
        started_at="2026-09-10T00:59:00+00:00",
        attempt_id="a" * 32,
    )


def _timer(
    *,
    duration: int,
    service_ends_at: str,
    grace_ends_at: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": duration,
        "duration_minutes": duration,
        "buffer_minutes": 10,
        "started_at": STARTED_AT,
        "service_ends_at": service_ends_at,
        "grace_ends_at": grace_ends_at,
        "phase": {"value": "service", "label": "制作中"},
        "ended_at": None,
        "experience_items": items,
    }


def _active_session() -> dict[str, Any]:
    return {
        "session_no": SESSION_NO,
        "table": {
            "id": 1,
            "table_no": "T01",
            "display_name": "T01号桌",
            "is_enabled": True,
        },
        "order_id": 91,
        "order_no": "OD" + "0" * 26,
        "status": {"value": "active", "label": "计时中"},
        "claimed_at": "2026-09-10T00:45:00+00:00",
        "payment_deadline_at": STARTED_AT,
        "started_at": STARTED_AT,
        "table_release_at": "2026-09-10T03:10:00+00:00",
        "closed_at": None,
        "close_reason": None,
        "server_now": "2026-09-10T01:00:01+00:00",
        "timers": [
            _timer(
                duration=60,
                service_ends_at="2026-09-10T02:00:00+00:00",
                grace_ends_at="2026-09-10T02:10:00+00:00",
                items=[
                    {
                        "order_item_id": 101,
                        "product_id": 11,
                        "product_name": "Experience",
                        "quantity": 2,
                        "participants_per_unit": 1,
                        "total_participants": 2,
                    },
                    {
                        "order_item_id": 102,
                        "product_id": 11,
                        "product_name": "Experience",
                        "quantity": 1,
                        "participants_per_unit": 2,
                        "total_participants": 2,
                    },
                ],
            ),
            _timer(
                duration=120,
                service_ends_at="2026-09-10T03:00:00+00:00",
                grace_ends_at="2026-09-10T03:10:00+00:00",
                items=[
                    {
                        "order_item_id": 103,
                        "product_id": 11,
                        "product_name": "Experience",
                        "quantity": 1,
                        "participants_per_unit": 1,
                        "total_participants": 1,
                    }
                ],
            ),
        ],
    }


def _awaiting_session() -> dict[str, Any]:
    payload = _active_session()
    payload.update(
        {
            "status": {"value": "awaiting_payment", "label": "待支付"},
            "claimed_at": "2026-09-10T00:45:00+00:00",
            "payment_deadline_at": STARTED_AT,
            "started_at": None,
            "table_release_at": None,
            "timers": [],
        }
    )
    return payload


def _mixed_order(*, status: str = "paid") -> dict[str, Any]:
    return {
        "id": 91,
        "order_no": "OD" + "0" * 26,
        "total_amount": "5.00",
        "status": {"value": status, "label": "已支付" if status == "paid" else "待支付"},
        "items": [
            {
                "id": 101,
                "product_id": 11,
                "experience_option_id": 21,
                "option_duration_minutes": 60,
                "product_price": "1.00",
                "quantity": 2,
                "subtotal": "2.00",
            },
            {
                "id": 102,
                "product_id": 11,
                "experience_option_id": 22,
                "option_duration_minutes": 60,
                "product_price": "1.00",
                "quantity": 1,
                "subtotal": "1.00",
            },
            {
                "id": 103,
                "product_id": 11,
                "experience_option_id": 23,
                "option_duration_minutes": 120,
                "product_price": "1.00",
                "quantity": 1,
                "subtotal": "1.00",
            },
            {
                "id": 104,
                "product_id": 12,
                "experience_option_id": None,
                "option_duration_minutes": None,
                "product_price": "1.00",
                "quantity": 1,
                "subtotal": "1.00",
            },
        ],
    }


def _payment() -> dict[str, Any]:
    return {
        "id": 92,
        "payment_no": "PY" + "0" * 26,
        "order_id": 91,
        "recharge_order_id": None,
        "purpose": "order",
        "amount": "5.00",
        "method": "wallet",
        "status": "succeeded",
        "succeeded_at": STARTED_AT,
    }


def test_prepare_runs_global_transition_guard_before_config_or_api_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / CANDIDATE_SHA
    repository_root.mkdir()
    guard_calls: list[tuple[Path, Path, str]] = []

    def block_release_state(**kwargs: Any) -> None:
        guard_calls.append(
            (
                kwargs["release_record_dir"],
                kwargs["record_dir"],
                kwargs["candidate_sha"],
            )
        )
        raise acceptance.M9AcceptanceError("injected unresolved transition")

    def reject_late_input(**kwargs: Any) -> dict[str, str]:
        del kwargs
        raise AssertionError("config inputs must not be read before global guard")

    monkeypatch.setattr(acceptance.os, "geteuid", lambda: 0)
    monkeypatch.setattr(acceptance.gatea, "REPOSITORY_ROOT", repository_root)
    monkeypatch.setattr(
        acceptance,
        "_reject_unresolved_release_state",
        block_release_state,
    )
    monkeypatch.setattr(acceptance.gatea, "_validated_inputs", reject_late_input)

    with pytest.raises(acceptance.M9AcceptanceError, match="unresolved transition"):
        acceptance.prepare(
            config_file=tmp_path / "gatea.env",
            secret_dir=tmp_path / "secrets",
            release_record_dir=tmp_path / "release",
            record_dir=tmp_path / "acceptance",
            credentials_file=tmp_path / "credentials.json",
        )

    assert guard_calls == [
        (
            tmp_path / "release",
            tmp_path / "acceptance",
            CANDIDATE_SHA,
        )
    ]


def test_global_guard_allows_only_exact_current_acceptance_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_dir = tmp_path / "release"
    record_dir = tmp_path / "acceptance"
    release_dir.mkdir()
    record_dir.mkdir(mode=0o755)
    pending_path = record_dir / (
        f"{acceptance.RECORD_PREFIX}-{CANDIDATE_SHA}.json.pending"
    )
    complete_path = record_dir / (
        f"{acceptance.RECORD_PREFIX}-{CANDIDATE_SHA}.json.complete"
    )
    pending_path.write_text("{}\n", encoding="utf-8")
    pending_path.chmod(0o600)
    complete_path.write_text("{}\n", encoding="utf-8")
    complete_path.chmod(0o644)
    release_calls: list[dict[str, Any]] = []
    acceptance_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        acceptance.gatea,
        "reject_unresolved_candidate_transition_journals",
        lambda **kwargs: release_calls.append(kwargs),
    )
    monkeypatch.setattr(
        acceptance.gatea,
        "reject_unresolved_m9_acceptance_sidecars",
        lambda **kwargs: acceptance_calls.append(kwargs),
    )

    acceptance._reject_unresolved_release_state(
        release_record_dir=release_dir,
        record_dir=record_dir,
        candidate_sha=CANDIDATE_SHA,
    )

    assert release_calls == [{"record_dir": release_dir}]
    assert len(acceptance_calls) == 1
    allowance = acceptance_calls[0]["recovery_allowance"]
    assert isinstance(
        allowance,
        acceptance.gatea.M9AcceptanceSidecarRecoveryAllowance,
    )
    assert allowance.candidate_sha == CANDIDATE_SHA
    assert allowance.pending_path == pending_path
    assert allowance.complete_path == complete_path


def test_global_guard_rejects_other_acceptance_candidate_and_release_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_dir = tmp_path / "release"
    record_dir = tmp_path / "acceptance"
    release_dir.mkdir()
    record_dir.mkdir(mode=0o755)
    own_pending = record_dir / (
        f"{acceptance.RECORD_PREFIX}-{CANDIDATE_SHA}.json.pending"
    )
    other_complete = record_dir / (
        f"{acceptance.RECORD_PREFIX}-{'d' * 40}.json.complete"
    )
    for path in (own_pending, other_complete):
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)
    monkeypatch.setattr(
        acceptance.gatea,
        "_validate_root_directory",
        lambda *args, **kwargs: None,
    )

    def root_sidecar_metadata(path: Path) -> SimpleNamespace:
        metadata = path.lstat()
        return SimpleNamespace(
            st_mode=metadata.st_mode,
            st_uid=0,
            st_gid=0,
        )

    monkeypatch.setattr(
        acceptance.gatea,
        "_m9_acceptance_sidecar_lstat",
        root_sidecar_metadata,
    )

    with pytest.raises(acceptance.M9AcceptanceError, match="unresolved release state"):
        acceptance._reject_unresolved_release_state(
            release_record_dir=release_dir,
            record_dir=record_dir,
            candidate_sha=CANDIDATE_SHA,
        )

    other_complete.unlink()
    (release_dir / f"{CANDIDATE_SHA}.candidate-stage.pending.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    with pytest.raises(acceptance.M9AcceptanceError, match="unresolved release state"):
        acceptance._reject_unresolved_release_state(
            release_record_dir=release_dir,
            record_dir=record_dir,
            candidate_sha=CANDIDATE_SHA,
        )


def test_global_guard_treats_missing_acceptance_directory_as_empty(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()

    acceptance._reject_unresolved_release_state(
        release_record_dir=release_dir,
        record_dir=tmp_path / "not-created-yet",
        candidate_sha=CANDIDATE_SHA,
    )


def test_upgrade_plan_replay_sidecar_is_strictly_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade_record_path = tmp_path / f"{CANDIDATE_SHA}.existing-database-upgrade.json"
    evidence_path = tmp_path / (
        f"{CANDIDATE_SHA}.existing-database-upgrade.evidence.json"
    )
    database_snapshot = {
        "aerich_versions": list(acceptance.gatea.APPROVED_TARGET_M9_CHAIN)
    }
    image_manifest = {"count": 2, "sha256": "5" * 64}
    table_reconcile = _zero_reconcile()
    evidence_path.write_text('{"status":"succeeded"}\n', encoding="utf-8")
    upgrade_record = {
        "source_candidate_sha": SOURCE_SHA,
        "backup_id": "20260910t010000z",
        "manifest_sha256": "6" * 64,
        "final_database_snapshot": database_snapshot,
        "final_image_manifest": image_manifest,
        "table_reconcile": table_reconcile,
        "evidence_sha256": acceptance._sha256(evidence_path),
    }
    upgrade_record_path.write_text(
        json.dumps(upgrade_record) + "\n", encoding="utf-8"
    )
    sidecar = {
        "schema_version": 1,
        "record_type": "gatea-m9-upgrade-plan-replay",
        "passed": True,
        "candidate_sha": CANDIDATE_SHA,
        "source_candidate_sha": SOURCE_SHA,
        "source_version": 7,
        "image_id": IMAGE_ID,
        "backup_id": upgrade_record["backup_id"],
        "manifest_sha256": upgrade_record["manifest_sha256"],
        "database_snapshot": database_snapshot,
        "image_manifest": image_manifest,
        "table_reconcile": table_reconcile,
        "upgrade_record_sha256": acceptance._sha256(upgrade_record_path),
        "evidence_sha256": acceptance._sha256(evidence_path),
        "result": {
            "already_current": True,
            "backup_id": upgrade_record["backup_id"],
            "candidate_sha": CANDIDATE_SHA,
            "manifest_sha256": upgrade_record["manifest_sha256"],
            "mode": "plan-replay",
            "source_aerich_versions": list(
                acceptance.gatea.APPROVED_TARGET_M7_CHAIN
            ),
            "source_version": 7,
            "target_aerich_versions": list(
                acceptance.gatea.APPROVED_TARGET_M9_CHAIN
            ),
            "target_version": 9,
        },
        "completed_at": "2026-09-10T00:50:00+00:00",
        "secret_values_recorded": False,
    }
    sidecar_path = tmp_path / f"{CANDIDATE_SHA}.upgrade-plan-replay.json"
    sidecar_path.write_text(json.dumps(sidecar) + "\n", encoding="utf-8")
    monkeypatch.setattr(acceptance, "_validate_root_file", lambda *args: None)

    assert acceptance._load_upgrade_plan_replay(
        path=sidecar_path,
        upgrade_record_path=upgrade_record_path,
        upgrade_record=upgrade_record,
        candidate_sha=CANDIDATE_SHA,
        image_id=IMAGE_ID,
    ) == acceptance._sha256(sidecar_path)

    sidecar["result"]["mode"] = "apply-replay"
    sidecar_path.write_text(json.dumps(sidecar) + "\n", encoding="utf-8")
    with pytest.raises(acceptance.M9AcceptanceError, match="does not match"):
        acceptance._load_upgrade_plan_replay(
            path=sidecar_path,
            upgrade_record_path=upgrade_record_path,
            upgrade_record=upgrade_record,
            candidate_sha=CANDIDATE_SHA,
            image_id=IMAGE_ID,
        )


def test_representative_credentials_must_match_the_strict_m7_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_path = tmp_path / "m7.json"
    credentials_path = tmp_path / "credentials.json"
    accounts = [
        {
            "purpose": str(item["purpose"]),
            "username": str(item["username"]),
            "password": "synthetic-password",
        }
        for item in acceptance.m7_data.SYNTHETIC_ACCOUNTS
    ]
    credentials_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "environment": "gatea",
                "candidate_sha": SOURCE_SHA,
                "created_at": "2026-09-10T00:00:00+00:00",
                "accounts": accounts,
            }
        ),
        encoding="utf-8",
    )
    record_path.write_text("{}", encoding="utf-8")
    record = {
        "credentials_file": str(credentials_path),
        "credentials_file_mode": "0600",
        "credentials_sha256": acceptance._sha256(credentials_path),
        "synthetic_sessions_revoked": True,
        "super_admin_session_revoked": True,
        "super_admin_credentials_recorded": False,
        "request_or_response_bodies_recorded": False,
        "passed": True,
    }
    monkeypatch.setattr(
        acceptance.resilience,
        "_validate_representative_record_file",
        lambda path: None,
    )
    monkeypatch.setattr(
        acceptance.resilience,
        "_load_representative_record",
        lambda *args, **kwargs: record,
    )
    monkeypatch.setattr(
        acceptance.resilience,
        "_validate_m7_credentials_artifact",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(acceptance, "_validate_root_file", lambda *args: None)

    assert acceptance._load_representative_evidence(
        representative_record=record_path,
        credentials_file=credentials_path,
        source_candidate_sha=SOURCE_SHA,
        source_image_id="sha256:" + "e" * 64,
    ) == (
        acceptance._sha256(record_path),
        acceptance._sha256(credentials_path),
    )

    record["credentials_file"] = str(tmp_path / "different.json")
    with pytest.raises(acceptance.M9AcceptanceError, match="does not match"):
        acceptance._load_representative_evidence(
            representative_record=record_path,
            credentials_file=credentials_path,
            source_candidate_sha=SOURCE_SHA,
            source_image_id="sha256:" + "e" * 64,
        )


def test_active_timer_verifier_proves_grouping_quantity_and_kit_exclusion() -> None:
    result = acceptance._verify_active_session(
        _active_session(),
        order_id=91,
        table_no="T01",
        session_no=SESSION_NO,
        payment_succeeded_at=datetime.fromisoformat(STARTED_AT),
        expected_timer_items={101: (60, 2), 102: (60, 1), 103: (120, 1)},
        kit_order_item_id=104,
    )

    assert result == {
        "durations": [60, 120],
        "buffers": [10, 10],
        "item_counts": [2, 1],
        "quantities": [3, 1],
        "service_offsets": [3600, 7200],
        "grace_offsets": [4200, 7800],
        "release_offset": 7800,
    }

    invalid = _active_session()
    invalid["timers"][0]["experience_items"].append(
        {
            "order_item_id": 104,
            "product_id": 12,
            "product_name": "Kit",
            "quantity": 1,
        }
    )
    with pytest.raises(acceptance.M9AcceptanceError, match="grouping"):
        acceptance._verify_active_session(
            invalid,
            order_id=91,
            table_no="T01",
            session_no=SESSION_NO,
            payment_succeeded_at=datetime.fromisoformat(STARTED_AT),
            expected_timer_items={101: (60, 2), 102: (60, 1), 103: (120, 1)},
            kit_order_item_id=104,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param(
            "payment_deadline_at",
            "2026-09-10T01:00:00.000001+00:00",
            id="payment-window-plus-one-microsecond",
        ),
        pytest.param(
            "payment_deadline_at",
            "2026-09-10T00:59:59.999999+00:00",
            id="payment-window-minus-one-microsecond",
        ),
    ],
)
def test_awaiting_timer_window_rejects_subsecond_drift(
    field: str,
    value: str,
) -> None:
    payload = _awaiting_session()
    payload[field] = value

    with pytest.raises(acceptance.M9AcceptanceError, match="15 minutes"):
        acceptance._verify_awaiting_session(
            payload,
            order_id=91,
            table_no="T01",
        )


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        pytest.param(
            0,
            "service_ends_at",
            "2026-09-10T02:00:00.000001+00:00",
            id="service-end-plus-one-microsecond",
        ),
        pytest.param(
            1,
            "grace_ends_at",
            "2026-09-10T03:09:59.999999+00:00",
            id="grace-end-minus-one-microsecond",
        ),
        pytest.param(
            None,
            "table_release_at",
            "2026-09-10T03:10:00.000001+00:00",
            id="table-release-plus-one-microsecond",
        ),
    ],
)
def test_active_timer_offsets_reject_subsecond_drift(
    location: int | None,
    field: str,
    value: str,
) -> None:
    payload = _active_session()
    if location is None:
        payload[field] = value
    else:
        payload["timers"][location][field] = value

    with pytest.raises(acceptance.M9AcceptanceError, match="semantics"):
        acceptance._verify_active_session(
            payload,
            order_id=91,
            table_no="T01",
            session_no=SESSION_NO,
            payment_succeeded_at=datetime.fromisoformat(STARTED_AT),
            expected_timer_items={101: (60, 2), 102: (60, 1), 103: (120, 1)},
            kit_order_item_id=104,
        )


class _FakeClient:
    instances: list["_FakeClient"] = []
    resume_closed = False

    def __init__(self, port: int) -> None:
        self.port = port
        self.results: list[dict[str, object]] = []
        self.steps: list[str] = []
        self.session_closed = False
        self.__class__.instances.append(self)

    def json_request(
        self,
        step: str,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del method, path, kwargs
        self.steps.append(step)
        self.results.append({"step": step, "passed": True})
        if step == "login-super-admin":
            return {
                "code": 0,
                "data": {
                    "access_token": "admin-access-token-secret",
                    "refresh_token": "admin-refresh-token-secret",
                    "user": {"id": 1, "role": "super_admin", "status": "normal"},
                },
            }
        if step == "login-orders-and-wallet-user":
            return {
                "code": 0,
                "data": {
                    "access_token": "user-access-token-secret",
                    "refresh_token": "user-refresh-token-secret",
                    "user": {"id": 2, "role": "user", "status": "normal"},
                },
            }
        if step == "read-pre-payment-wallet":
            return {
                "code": 0,
                "data": {
                    "wallet": {
                        "balance": "155.00" if self.resume_closed else "160.00",
                        "status": "active",
                    }
                },
            }
        if step == "resolve-available-table-code":
            return {
                "code": 0,
                "data": {
                    "table_no": "T01",
                    "display_name": "T01号桌",
                    "is_enabled": True,
                    "is_available": True,
                },
            }
        if step == "resume-read-order-session":
            if not self.resume_closed:
                return {"code": 0, "data": None}
            payload = _active_session()
            payload["status"] = {"value": "closed", "label": "已关闭"}
            return {"code": 0, "data": payload}
        if step == "resume-read-mixed-order":
            return {"code": 0, "data": _mixed_order()}
        if step == "read-order-financials":
            if self.resume_closed:
                return {
                    "code": 0,
                    "data": {
                        "order_id": 91,
                        "order_status": {"value": "paid", "label": "已支付"},
                        "payment": _payment(),
                        "refund": None,
                    },
                }
            return {
                "code": 0,
                "data": {
                    "order_id": 91,
                    "order_status": {"value": "pending", "label": "待支付"},
                    "payment": None,
                    "refund": None,
                },
            }
        if step == "replay-table-claim" and self.resume_closed:
            payload = _active_session()
            payload["status"] = {"value": "closed", "label": "已关闭"}
            return {"code": 0, "data": payload}
        if step in {"claim-table", "replay-table-claim", "read-awaiting-order-session"}:
            return {"code": 0, "data": _awaiting_session()}
        if step in {"pay-mixed-order-with-wallet", "replay-wallet-payment"}:
            return {
                "code": 0,
                "data": {
                    "order_id": 91,
                    "order_status": {"value": "paid", "label": "已支付"},
                    "post_payment_balance": "155.00",
                    "payment": _payment(),
                },
            }
        if step in {"read-active-current-session", "read-active-order-session"}:
            payload = _active_session()
            if self.resume_closed:
                payload["status"] = {"value": "closed", "label": "已关闭"}
            return {"code": 0, "data": payload}
        if step == "cleanup-read-session":
            payload = _active_session()
            if self.session_closed:
                payload["status"] = {"value": "closed", "label": "已关闭"}
            return {"code": 0, "data": payload}
        if step == "cleanup-verify-session-closed":
            payload = _active_session()
            payload["status"] = {"value": "closed", "label": "已关闭"}
            return {"code": 0, "data": payload}
        if step == "cleanup-verify-table-available":
            return {
                "code": 0,
                "data": {
                    "items": [
                        {
                            "table_no": "T01",
                            "state": "available",
                            "current_session_no": None,
                        }
                    ]
                },
            }
        if step == "read-post-payment-wallet":
            return {"code": 0, "data": {"wallet": {"balance": "155.00"}}}
        if step == "read-experience-before-fixture-offline":
            return {
                "code": 0,
                "data": {"id": 11, "status": {"value": "online"}},
            }
        if step == "resume-read-experience-fixture":
            return {
                "code": 0,
                "data": {"id": 11, "status": {"value": "online"}},
            }
        if step == "offline-fixture-experience":
            return {
                "code": 0,
                "data": {"id": 11, "status": {"value": "offline"}},
            }
        if step == "verify-experience-fixture-not-online":
            return {
                "code": 0,
                "data": {"id": 11, "status": {"value": "offline"}},
            }
        if step == "read-kit-before-fixture-offline":
            return {
                "code": 0,
                "data": {"id": 12, "status": {"value": "online"}},
            }
        if step == "resume-read-kit-fixture":
            return {
                "code": 0,
                "data": {"id": 12, "status": {"value": "online"}},
            }
        if step == "offline-fixture-kit":
            return {
                "code": 0,
                "data": {"id": 12, "status": {"value": "offline"}},
            }
        if step == "verify-kit-fixture-not-online":
            return {
                "code": 0,
                "data": {"id": 12, "status": {"value": "offline"}},
            }
        if step.endswith("-logout"):
            return {"code": 0, "data": None}
        if step.endswith("-refresh-revoked"):
            return {"code": 1006, "data": None}
        raise AssertionError(f"unexpected fake API step: {step}")


def _fixture() -> dict[str, Any]:
    return {
        "experience_product_id": 11,
        "kit_product_id": 12,
        "option_ids": [21, 22, 23],
        "option_durations_minutes": [60, 60, 120],
        "option_participants": [1, 2, 1],
        "option_price": "1.00",
        "kit_price": "1.00",
        "kit_opening_stock": 10,
        "product_images_created": 2,
        "option_images_created": 3,
        "products_online": True,
    }


def _released_pending_context(
    tmp_path: Path,
    *,
    verified: bool = False,
    failure: bool = True,
) -> acceptance.PreparedContext:
    context = _context(tmp_path)
    acceptance._create_pending(context)
    fixture = _fixture()
    order_evidence = acceptance._build_order_evidence(
        order_id=91,
        expected_timer_items={101: (60, 2), 102: (60, 1), 103: (120, 1)},
        kit_order_item_id=104,
        eligible_duration_groups=acceptance._expected_duration_groups(),
    )
    payment_evidence = {
        "payment_id": 92,
        "payment_no_sha256": acceptance._sha256_text("PY" + "0" * 26),
        "succeeded_at": "2026-09-10T01:00:00+00:00",
    }
    timer_evidence = {
        "durations": [60, 120],
        "buffers": [10, 10],
        "item_counts": [2, 1],
        "quantities": [3, 1],
        "service_offsets": [3600, 7200],
        "grace_offsets": [4200, 7800],
        "release_offset": 7800,
    }
    acceptance._update_pending(
        context,
        stage="released",
        fixture_ids=(11, 12),
        fixture=fixture,
        order_evidence=order_evidence,
        table_no="T01",
        session_no=SESSION_NO,
        payment_deadline_offset_seconds=900,
        payment_evidence=payment_evidence,
        timer_evidence=timer_evidence,
        claim_replay_verified=True,
        payment_replay_verified=True,
        admin_visibility_verified=True,
        release_replay_verified=True,
        payment_committed=True,
        session_released=True,
        cleanup_updates={
            "synthetic_session_revoked": failure,
            "super_admin_session_revoked": failure,
        },
        failure=failure,
    )
    if verified:
        acceptance._update_pending(
            context,
            stage="verified",
            cleanup_updates={
                "fixture_products_offline": True,
                "synthetic_session_revoked": True,
                "super_admin_session_revoked": True,
            },
        )
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    return replace(context, pending=pending)


def _fixtures_offline_pending_context(
    tmp_path: Path,
    *,
    failure: bool,
) -> acceptance.PreparedContext:
    context = _released_pending_context(tmp_path, failure=failure)
    acceptance._update_pending(
        context,
        stage="fixtures_offline",
        cleanup_updates={"fixture_products_offline": True},
    )
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    return replace(context, pending=pending)


def _patch_execute_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_admin_visibility: bool = False,
    resume_closed: bool = False,
) -> list[str]:
    _FakeClient.instances.clear()
    _FakeClient.resume_closed = resume_closed
    monkeypatch.setattr(acceptance, "SafeLoopbackClient", _FakeClient)
    monkeypatch.setattr(
        acceptance,
        "_read_synthetic_user",
        lambda context: ("synthetic-user-secret", "synthetic-password-secret"),
    )
    monkeypatch.setattr(
        acceptance,
        "_create_fixture",
        lambda *args, **kwargs: _fixture(),
    )
    monkeypatch.setattr(
        acceptance,
        "_create_mixed_order",
        lambda *args, **kwargs: (
            {"id": 91},
            {101: (60, 2), 102: (60, 1), 103: (120, 1)},
            104,
        ),
    )
    monkeypatch.setattr(
        acceptance,
        "_verify_eligible_order",
        lambda *args, **kwargs: [
            {
                "duration_minutes": 60,
                "buffer_minutes": 10,
                "experience_item_count": 2,
                "total_quantity": 3,
            },
            {
                "duration_minutes": 120,
                "buffer_minutes": 10,
                "experience_item_count": 1,
                "total_quantity": 1,
            },
        ],
    )
    monkeypatch.setattr(
        acceptance, "_read_table_secret", lambda context: ("T01", QR_TOKEN)
    )
    monkeypatch.setattr(
        acceptance,
        "_verify_admin_visibility",
        (
            lambda *args, **kwargs: (_ for _ in ()).throw(
                acceptance.M9AcceptanceError("injected admin visibility failure")
            )
            if fail_admin_visibility
            else lambda *args, **kwargs: None
        ),
    )
    releases: list[str] = []

    def release(*args: Any, **kwargs: Any) -> dict[str, Any]:
        client = args[0]
        assert isinstance(client, _FakeClient)
        client.session_closed = True
        releases.append(str(kwargs["step"]))
        return {
            "session_no": SESSION_NO,
            "order_id": 91,
            "status": {"value": "closed"},
            "close_reason": {"value": "admin_released"},
            "closed_at": "2026-09-10T01:01:00+00:00",
            "closed_by_user_id": 1,
            "admin_close_reason": "Gate A M9 controlled internal acceptance release",
            "timers": [{}, {}],
        }

    monkeypatch.setattr(acceptance, "_release_session", release)
    monkeypatch.setattr(
        acceptance,
        "_verify_released_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        acceptance,
        "_run_table_sweep",
        lambda context: {"status": "ok", "closed": 0},
    )
    monkeypatch.setattr(
        acceptance,
        "_run_table_reconcile",
        lambda context: _zero_reconcile(scanned=1),
    )
    monkeypatch.setattr(
        acceptance,
        "_run_wallet_reconcile",
        lambda context: _wallet_reconcile(scanned=11),
    )
    monkeypatch.setattr(
        acceptance,
        "_verify_log_redaction",
        lambda *args, **kwargs: {
            "window": "24h",
            "combined_line_count": 50,
            "services_scanned": list(acceptance.M9_SERVICES),
            "exact_secret_matches": 0,
            "forbidden_pattern_matches": 0,
            "raw_log_content_recorded": False,
            "passed": True,
        },
    )
    monkeypatch.setattr(acceptance, "_ensure_m9_services", lambda context: None)
    return releases


def _valid_success_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    context = _context(tmp_path)
    _patch_execute_dependencies(monkeypatch)
    record = acceptance.execute(
        context,
        admin_username="admin-user-secret",
        admin_password="admin-password-secret",
    )
    context.record_path.unlink()
    return record


def test_execute_writes_installer_compatible_redacted_record_exclusively(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    releases = _patch_execute_dependencies(monkeypatch)

    record = acceptance.execute(
        context,
        admin_username="admin-user-secret",
        admin_password="admin-password-secret",
    )

    assert releases == ["admin-release-session", "replay-admin-release"]
    assert record["record_type"] == "gatea-m9-runtime-acceptance"
    assert record["runtime_services"] == list(acceptance.M9_SERVICES)
    for field in (
        "upgrade_plan_replayed",
        "wallet_reconcile_passed",
        "table_reconcile_passed",
        "table_sweep_passed",
        "log_redaction_passed",
        "passed",
    ):
        assert record[field] is True
    for field in ("pii_recorded", "secret_values_recorded", "table_tokens_recorded"):
        assert record[field] is False
    assert record["scenario"]["active_timer_total_quantities"] == [3, 1]
    assert record["scenario"]["payment_no_sha256"] == acceptance._sha256_text(
        "PY" + "0" * 26
    )
    assert record["scenario"]["payment_succeeded_at"] == STARTED_AT
    assert record["cleanup"]["fixture_products_offline"] is True
    assert record["scenario"]["session_no_sha256"] == acceptance._sha256_text(
        SESSION_NO
    )
    serialized = context.record_path.read_text(encoding="utf-8")
    for secret in (
        "admin-user-secret",
        "admin-password-secret",
        "synthetic-user-secret",
        "synthetic-password-secret",
        "admin-access-token-secret",
        "user-access-token-secret",
        QR_TOKEN,
        SESSION_NO,
    ):
        assert secret not in serialized
    assert stat.S_IMODE(context.record_path.stat().st_mode) == 0o644
    assert context.record_path.stat().st_nlink == 1
    assert not context.pending_path.exists()
    assert not context.complete_path.exists()
    monkeypatch.setattr(gatea_candidate, "_require_root_file", lambda *args: None)
    assert gatea_candidate._validate_acceptance_record(
        context.record_path,
        expected_sha256=acceptance._sha256(context.record_path),
        source_sha=SOURCE_SHA,
        target_sha=CANDIDATE_SHA,
        image_id=IMAGE_ID,
        ci_run_id=context.ci_run_id,
        upgrade_record_sha256=context.upgrade_record_sha256,
        upgrade_replay_record_sha256=(
            context.upgrade_plan_replay_record_sha256
        ),
    )["passed"] is True


def test_failure_after_payment_releases_session_and_retains_redacted_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    releases = _patch_execute_dependencies(
        monkeypatch,
        fail_admin_visibility=True,
    )

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="injected admin visibility failure",
    ):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    assert releases == ["cleanup-release-session"]
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert pending["failure"] is True
    assert pending["payment_committed"] is True
    assert pending["session_released"] is True
    assert pending["passed"] is False
    assert SESSION_NO not in context.pending_path.read_text(encoding="utf-8")
    assert not context.record_path.exists()
    assert "cleanup-cancel-pending-order" not in _FakeClient.instances[-1].steps


@pytest.mark.parametrize("signum", [signal.SIGHUP, signal.SIGTERM])
def test_main_termination_guard_routes_hup_and_term_through_execute_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signum: signal.Signals,
) -> None:
    context = _context(tmp_path)
    releases = _patch_execute_dependencies(monkeypatch)
    lock_active = False
    observed_guard = False
    previous_handler = signal.getsignal(signum)

    @contextmanager
    def controlled_lock() -> Any:
        nonlocal lock_active
        lock_active = True
        try:
            yield
        finally:
            lock_active = False

    def interrupt_during_acceptance(*args: Any, **kwargs: Any) -> None:
        nonlocal observed_guard
        del args, kwargs
        assert lock_active is True
        handler = signal.getsignal(signum)
        assert callable(handler)
        assert handler is not previous_handler
        observed_guard = True
        handler(signum, None)

    monkeypatch.setattr(acceptance.gatea, "operation_lock", controlled_lock)
    monkeypatch.setattr(acceptance, "prepare", lambda **kwargs: context)
    monkeypatch.setattr(
        acceptance,
        "_read_admin_identity_from_tty",
        lambda: ("admin-user-secret", "admin-password-secret"),
    )
    monkeypatch.setattr(
        acceptance,
        "_verify_admin_visibility",
        interrupt_during_acceptance,
    )

    assert acceptance.main(["--apply-admin-assisted"]) == 1

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert observed_guard is True
    assert lock_active is False
    assert signal.getsignal(signum) is previous_handler
    assert releases == ["cleanup-release-session"]
    assert pending["failure"] is True
    assert pending["session_released"] is True
    assert pending["cleanup"]["synthetic_session_revoked"] is True
    assert pending["cleanup"]["super_admin_session_revoked"] is True
    assert not context.complete_path.exists()
    assert not context.record_path.exists()


def test_main_preserves_sigint_keyboard_interrupt_semantics_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    releases = _patch_execute_dependencies(monkeypatch)
    previous_handler = signal.getsignal(signal.SIGINT)
    work_interruptions: list[BaseException] = []

    @contextmanager
    def controlled_lock() -> Any:
        yield

    def interrupt_during_acceptance(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        assert handler is not previous_handler
        try:
            handler(signal.SIGINT, None)
        except KeyboardInterrupt as error:
            work_interruptions.append(error)
            raise

    monkeypatch.setattr(acceptance.gatea, "operation_lock", controlled_lock)
    monkeypatch.setattr(acceptance, "prepare", lambda **kwargs: context)
    monkeypatch.setattr(
        acceptance,
        "_read_admin_identity_from_tty",
        lambda: ("admin-user-secret", "admin-password-secret"),
    )
    monkeypatch.setattr(
        acceptance,
        "_verify_admin_visibility",
        interrupt_during_acceptance,
    )

    with pytest.raises(KeyboardInterrupt) as raised:
        acceptance.main(["--apply-admin-assisted"])

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert raised.value is work_interruptions[0]
    assert signal.getsignal(signal.SIGINT) is previous_handler
    assert releases == ["cleanup-release-session"]
    assert pending["failure"] is True
    assert pending["session_released"] is True
    assert pending["cleanup"]["synthetic_session_revoked"] is True
    assert pending["cleanup"]["super_admin_session_revoked"] is True


@pytest.mark.parametrize(
    ("first_control_error", "second_control_error"),
    [
        pytest.param(
            KeyboardInterrupt("first cleanup interrupt"),
            SystemExit(71),
            id="keyboard-interrupt-first",
        ),
        pytest.param(
            SystemExit(72),
            KeyboardInterrupt("second cleanup interrupt"),
            id="system-exit-first",
        ),
    ],
)
def test_cleanup_preserves_first_control_exception_and_continues_journaling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_control_error: KeyboardInterrupt | SystemExit,
    second_control_error: KeyboardInterrupt | SystemExit,
) -> None:
    context = _context(tmp_path)
    releases = _patch_execute_dependencies(
        monkeypatch,
        fail_admin_visibility=True,
    )
    cleanup_calls: list[str] = []

    def interrupt_both_session_cleanups(
        client: _FakeClient,
        *,
        step_prefix: str,
        access_token: str,
        refresh_token: str,
    ) -> None:
        del client, access_token, refresh_token
        cleanup_calls.append(step_prefix)
        if len(cleanup_calls) == 1:
            raise first_control_error
        raise second_control_error

    monkeypatch.setattr(
        acceptance.base_data,
        "_logout_and_verify",
        interrupt_both_session_cleanups,
    )

    with pytest.raises(type(first_control_error)) as raised:
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert raised.value is first_control_error
    assert cleanup_calls == [
        "cleanup-orders-and-wallet-user",
        "cleanup-super-admin",
    ]
    assert releases == ["cleanup-release-session"]
    assert pending["failure"] is True
    assert pending["session_released"] is True
    assert pending["cleanup"]["synthetic_session_revoked"] is False
    assert pending["cleanup"]["super_admin_session_revoked"] is False


@pytest.mark.parametrize(
    ("signum", "expected_type"),
    [
        pytest.param(
            signal.SIGHUP,
            acceptance.gatea.GateAOperationInterrupted,
            id="sighup",
        ),
        pytest.param(
            signal.SIGTERM,
            acceptance.gatea.GateAOperationInterrupted,
            id="sigterm",
        ),
        pytest.param(signal.SIGINT, KeyboardInterrupt, id="sigint"),
    ],
)
def test_first_cleanup_termination_signal_is_deferred_until_all_cleanup_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signum: signal.Signals,
    expected_type: type[BaseException],
) -> None:
    context = _context(tmp_path)
    releases = _patch_execute_dependencies(
        monkeypatch,
        fail_admin_visibility=True,
    )
    original_release = acceptance._release_session
    previous_handler = signal.getsignal(signum)
    cleanup_continued: list[str] = []
    deferred: list[BaseException] = []

    def interrupt_at_first_cleanup(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("step") == "cleanup-release-session":
            handler = signal.getsignal(signum)
            assert callable(handler)
            handler(signum, None)
            controller = getattr(handler, "__self__")
            assert isinstance(
                controller,
                acceptance.backup._RecoveryTerminationController,
            )
            assert controller.deferred_interruptions
            deferred.append(controller.deferred_interruptions[0])
            cleanup_continued.append("after-signal")
        return original_release(*args, **kwargs)

    monkeypatch.setattr(
        acceptance,
        "_release_session",
        interrupt_at_first_cleanup,
    )

    with pytest.raises(expected_type) as caught:
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert cleanup_continued == ["after-signal"]
    assert caught.value is deferred[0]
    assert releases == ["cleanup-release-session"]
    assert pending["failure"] is True
    assert pending["session_released"] is True
    assert pending["cleanup"]["fixture_products_offline"] is True
    assert pending["cleanup"]["synthetic_session_revoked"] is True
    assert pending["cleanup"]["super_admin_session_revoked"] is True
    assert signal.getsignal(signum) is previous_handler


def test_finally_entry_transition_defers_signal_after_phase_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    releases = _patch_execute_dependencies(
        monkeypatch,
        fail_admin_visibility=True,
    )
    original_controller = acceptance.backup._RecoveryTerminationController
    injected: list[str] = []

    class _BoundaryController(original_controller):
        def begin_recovery(self) -> None:
            was_recovering = self.recovery_started
            super().begin_recovery()
            if not was_recovering and not injected:
                injected.append("boundary")
                self.interrupt(signal.SIGTERM, None)

    monkeypatch.setattr(
        acceptance.backup,
        "_RecoveryTerminationController",
        _BoundaryController,
    )

    with pytest.raises(acceptance.gatea.GateAOperationInterrupted):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert injected == ["boundary"]
    assert releases == ["cleanup-release-session"]
    assert pending["failure"] is True
    assert pending["session_released"] is True
    assert pending["cleanup"]["synthetic_session_revoked"] is True
    assert pending["cleanup"]["super_admin_session_revoked"] is True


@pytest.mark.parametrize(
    ("work_control", "cleanup_control"),
    [
        pytest.param(
            KeyboardInterrupt("work keyboard interrupt"),
            SystemExit(73),
            id="keyboard-before-system-exit",
        ),
        pytest.param(
            SystemExit(74),
            KeyboardInterrupt("cleanup keyboard interrupt"),
            id="system-exit-before-keyboard",
        ),
    ],
)
def test_work_control_exception_object_precedes_later_cleanup_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    work_control: KeyboardInterrupt | SystemExit,
    cleanup_control: KeyboardInterrupt | SystemExit,
) -> None:
    context = _context(tmp_path)
    _patch_execute_dependencies(monkeypatch)

    def interrupt_work(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise work_control

    def interrupt_session_cleanup(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise cleanup_control

    monkeypatch.setattr(acceptance, "_verify_admin_visibility", interrupt_work)
    monkeypatch.setattr(acceptance, "_release_session", interrupt_session_cleanup)

    with pytest.raises(type(work_control)) as raised:
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert raised.value is work_control
    assert pending["failure"] is True
    assert pending["cleanup"]["fixture_products_offline"] is True
    assert pending["cleanup"]["synthetic_session_revoked"] is True
    assert pending["cleanup"]["super_admin_session_revoked"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("candidate_sha", "f" * 40, id="candidate"),
        pytest.param("operations_sha", "f" * 40, id="operations"),
        pytest.param("ci_run_id", "1", id="ci-run"),
        pytest.param("image_id", "sha256:" + "f" * 64, id="image"),
        pytest.param("attempt_id", "f" * 32, id="attempt"),
        pytest.param("stage", "unknown", id="stage"),
        pytest.param("schema_version", 2, id="obsolete-pending-schema"),
    ],
)
def test_pending_journal_rejects_cross_attempt_or_cross_candidate_binding(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    context = _context(tmp_path)
    payload = acceptance._pending_payload(context)
    payload[field] = value

    with pytest.raises(acceptance.M9AcceptanceError, match="binding"):
        acceptance._validate_pending_payload(context, payload)


def test_pending_journal_rejects_fixture_and_order_hash_tampering(
    tmp_path: Path,
) -> None:
    context = _released_pending_context(tmp_path)
    payload = json.loads(context.pending_path.read_text(encoding="utf-8"))
    payload["fixture"]["kit_opening_stock"] = 9

    with pytest.raises(acceptance.M9AcceptanceError, match="fixture binding"):
        acceptance._validate_pending_payload(context, payload)

    payload = json.loads(context.pending_path.read_text(encoding="utf-8"))
    payload["order_evidence"]["expected_timer_items"][0]["quantity"] = 9
    with pytest.raises(acceptance.M9AcceptanceError, match="Order binding"):
        acceptance._validate_pending_payload(context, payload)


def test_pending_journal_session_hash_is_checked_against_live_resume_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _released_pending_context(tmp_path)
    payload = json.loads(context.pending_path.read_text(encoding="utf-8"))
    payload["session_no_sha256"] = "f" * 64
    context.pending_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    context = replace(context, pending=payload)
    _patch_execute_dependencies(monkeypatch, resume_closed=True)

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="live Session does not match pending evidence",
    ):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )


def test_pending_irreversible_evidence_and_flags_cannot_move_back_or_rebind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _released_pending_context(tmp_path)
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    changed_fixture = dict(pending["fixture"])
    changed_fixture["kit_opening_stock"] = 9
    changed_order = json.loads(json.dumps(pending["order_evidence"]))
    changed_order["expected_timer_items"][0]["quantity"] = 9
    changed_payment = dict(pending["payment_evidence"])
    changed_payment["payment_no_sha256"] = "f" * 64
    changed_timer = dict(pending["timer_evidence"])
    changed_timer["release_offset"] = 7799
    attempts = (
        {"stage": "released", "fixture_ids": (11,)},
        {"stage": "released", "fixture": changed_fixture},
        {"stage": "released", "order_evidence": changed_order},
        {
            "stage": "released",
            "table_no": "T01",
            "session_no": "TS" + "1" * 26,
            "payment_deadline_offset_seconds": 900,
        },
        {"stage": "released", "payment_evidence": changed_payment},
        {"stage": "released", "timer_evidence": changed_timer},
        {"stage": "released", "claim_replay_verified": False},
        {"stage": "released", "payment_committed": False},
        {"stage": "released", "session_released": False},
        {
            "stage": "released",
            "cleanup_updates": {"synthetic_session_revoked": False},
        },
        {"stage": "paid"},
        {"stage": "released", "failure": False},
    )

    for update in attempts:
        before = context.pending_path.read_bytes()
        with pytest.raises(acceptance.M9AcceptanceError):
            acceptance._update_pending(context, **update)
        assert context.pending_path.read_bytes() == before

    monkeypatch.setattr(
        acceptance,
        "_utc_now",
        lambda: "2026-09-10T00:59:00+00:00",
    )
    before = context.pending_path.read_bytes()
    with pytest.raises(acceptance.M9AcceptanceError, match="timestamp cannot move"):
        acceptance._update_pending(context, stage="released")
    assert context.pending_path.read_bytes() == before


def test_clean_no_write_failure_retries_with_the_same_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    acceptance._create_pending(context)
    acceptance._update_pending(
        context,
        stage="authenticated",
        cleanup_updates={
            "synthetic_session_revoked": True,
            "super_admin_session_revoked": True,
        },
        failure=True,
    )
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    context = replace(context, pending=pending)
    _patch_execute_dependencies(monkeypatch)
    original_login = acceptance.base_data._login
    authentication_checkpoints: list[tuple[bool, bool]] = []

    def login_after_durable_cleanup_reset(*args: Any, **kwargs: Any) -> dict[str, Any]:
        current = json.loads(context.pending_path.read_text(encoding="utf-8"))
        authentication_checkpoints.append(
            (
                current["cleanup"]["synthetic_session_revoked"],
                current["cleanup"]["super_admin_session_revoked"],
            )
        )
        return original_login(*args, **kwargs)

    monkeypatch.setattr(
        acceptance.base_data,
        "_login",
        login_after_durable_cleanup_reset,
    )

    record = acceptance.execute(
        context,
        admin_username="admin-user-secret",
        admin_password="admin-password-secret",
    )

    assert record["attempt_id_sha256"] == acceptance._sha256_text("a" * 32)
    assert authentication_checkpoints == [(False, False), (False, False)]
    assert not context.pending_path.exists()


def test_no_write_pending_without_complete_session_cleanup_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    acceptance._create_pending(context)
    acceptance._update_pending(
        context,
        stage="authenticated",
        failure=True,
    )
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    context = replace(context, pending=pending)
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("fail-closed recovery must not call the API")
        ),
    )

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="lacks complete session cleanup",
    ):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )


@pytest.mark.parametrize("stage", ["authentication_started", "admin_authenticated"])
def test_interrupted_authentication_is_retained_and_fails_closed_before_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    context = _context(tmp_path)
    acceptance._create_pending(context)
    acceptance._update_pending(context, stage=stage)
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    context = replace(context, pending=pending)
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("ambiguous authentication must not call the API")
        ),
    )

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="lacks complete session cleanup",
    ):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    retained = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert retained["stage"] == stage
    assert retained["failure"] is False


@pytest.mark.parametrize(
    ("stage", "include_fixture", "message"),
    [
        pytest.param(
            "fixture_creation_started",
            False,
            "uncertain fixture creation",
            id="fixture-mutation-gap",
        ),
        pytest.param(
            "order_creation_started",
            True,
            "uncertain Order creation",
            id="order-mutation-gap",
        ),
    ],
)
def test_unidentifiable_creation_gap_is_retained_for_operator_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    include_fixture: bool,
    message: str,
) -> None:
    context = _context(tmp_path)
    acceptance._create_pending(context)
    update: dict[str, Any] = {
        "stage": stage,
        "failure": True,
        "cleanup_updates": {
            "synthetic_session_revoked": True,
            "super_admin_session_revoked": True,
        },
    }
    if include_fixture:
        update.update(
            {
                "fixture_ids": (11, 12),
                "fixture": _fixture(),
            }
        )
    acceptance._update_pending(context, **update)
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    context = replace(context, pending=pending)
    _patch_execute_dependencies(monkeypatch)
    monkeypatch.setattr(
        acceptance,
        "_create_fixture",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("uncertain mutation must not be repeated")
        ),
    )
    monkeypatch.setattr(
        acceptance,
        "_create_mixed_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("uncertain mutation must not be repeated")
        ),
    )

    with pytest.raises(acceptance.M9AcceptanceError, match=message):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    retained = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert retained["stage"] == stage
    assert retained["failure"] is True


def test_released_pending_resumes_from_formal_api_facts_without_new_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _released_pending_context(tmp_path)
    releases = _patch_execute_dependencies(monkeypatch, resume_closed=True)
    monkeypatch.setattr(
        acceptance,
        "_create_fixture",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("resume must not create a new fixture")
        ),
    )
    monkeypatch.setattr(
        acceptance,
        "_create_mixed_order",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("resume must not create a new Order")
        ),
    )

    record = acceptance.execute(
        context,
        admin_username="admin-user-secret",
        admin_password="admin-password-secret",
    )

    assert record["passed"] is True
    assert record["attempt_id_sha256"] == acceptance._sha256_text("a" * 32)
    assert releases == ["admin-release-session", "replay-admin-release"]
    assert "resume-read-mixed-order" in _FakeClient.instances[-1].steps
    assert "read-order-financials" in _FakeClient.instances[-1].steps
    assert not context.pending_path.exists()


def test_staged_success_publication_recovers_without_credentials_or_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _patch_execute_dependencies(monkeypatch)
    record = acceptance.execute(
        context,
        admin_username="admin-user-secret",
        admin_password="admin-password-secret",
    )
    context.record_path.unlink()
    recovery = _released_pending_context(
        tmp_path,
        verified=True,
        failure=False,
    )
    recovery.complete_path.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    recovery.complete_path.chmod(0o600)
    recovery = replace(recovery, staged_success=record)
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("staged publication recovery must not call the API")
        ),
    )

    recovered = acceptance.execute(
        recovery,
        admin_username="",
        admin_password="",
    )

    assert recovered == record
    assert stat.S_IMODE(recovery.record_path.stat().st_mode) == 0o644
    assert not recovery.pending_path.exists()
    assert not recovery.complete_path.exists()


def test_partial_success_temp_is_removed_when_write_runs_out_of_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _context(tmp_path)

    def fail_after_partial_write(path: Path, serialized: str) -> None:
        path.write_text(serialized[:23], encoding="utf-8")
        raise OSError(errno.ENOSPC, "injected full filesystem")

    monkeypatch.setattr(
        acceptance,
        "_write_success_temp_exclusive",
        fail_after_partial_write,
    )

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="could not be staged safely",
    ):
        acceptance._stage_success_record_exclusive(
            context,
            record,
            secret_values=(),
        )

    assert not context.complete_path.exists()
    assert not context.record_path.exists()
    assert not list(
        tmp_path.glob(f".{context.complete_path.name}.*.tmp")
    )


def test_stage_preserves_earlier_control_exception_when_temp_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _context(tmp_path)
    control_error = KeyboardInterrupt("injected staging interrupt")

    def interrupt_partial_write(path: Path, serialized: str) -> None:
        path.write_text(serialized[:17], encoding="utf-8")
        path.chmod(0o600)
        raise control_error

    def fail_cleanup(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError(errno.ENOSPC, "injected cleanup failure")

    monkeypatch.setattr(
        acceptance,
        "_write_success_temp_exclusive",
        interrupt_partial_write,
    )
    monkeypatch.setattr(acceptance, "_unlink_exact_file", fail_cleanup)

    with pytest.raises(KeyboardInterrupt) as raised:
        acceptance._stage_success_record_exclusive(
            context,
            record,
            secret_values=(),
        )

    assert raised.value is control_error
    assert not context.complete_path.exists()
    assert not context.record_path.exists()


def test_complete_publication_is_no_clobber_and_cleans_its_random_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _context(tmp_path)
    context.complete_path.write_text("do-not-overwrite\n", encoding="utf-8")

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="could not be staged safely",
    ):
        acceptance._stage_success_record_exclusive(
            context,
            record,
            secret_values=(),
        )

    assert context.complete_path.read_text(encoding="utf-8") == "do-not-overwrite\n"
    assert not context.record_path.exists()
    assert not list(
        tmp_path.glob(f".{context.complete_path.name}.*.tmp")
    )


def test_crash_after_complete_link_cleans_temp_alias_before_replay_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _released_pending_context(
        tmp_path,
        verified=True,
        failure=False,
    )
    temporary_path = context.record_dir / (
        f".{context.complete_path.name}.{'f' * 32}.tmp"
    )
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    acceptance._write_success_temp_exclusive(temporary_path, serialized)
    os.link(temporary_path, context.complete_path)
    acceptance._fsync_directory(context.record_dir)
    assert context.complete_path.stat().st_nlink == 2
    recovery = replace(context, staged_success=record)

    assert acceptance._publish_staged_success(recovery) == record

    assert context.record_path.stat().st_nlink == 1
    assert stat.S_IMODE(context.record_path.stat().st_mode) == 0o644
    assert not temporary_path.exists()
    assert not context.complete_path.exists()
    assert not context.pending_path.exists()


def test_publication_fsyncs_final_mode_inode_and_each_directory_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _released_pending_context(
        tmp_path,
        verified=True,
        failure=False,
    )
    acceptance._stage_success_record_exclusive(
        context,
        record,
        secret_values=(),
    )
    original_fsync = os.fsync
    synced_file_modes: list[int] = []
    synced_directories = 0

    def track_fsync(descriptor: int) -> None:
        nonlocal synced_directories
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode):
            synced_directories += 1
        elif stat.S_ISREG(metadata.st_mode):
            synced_file_modes.append(stat.S_IMODE(metadata.st_mode))
        original_fsync(descriptor)

    monkeypatch.setattr(acceptance.os, "fsync", track_fsync)

    assert acceptance._publish_staged_success(
        replace(context, staged_success=record)
    ) == record

    assert 0o644 in synced_file_modes
    assert synced_directories >= 3
    assert context.record_path.stat().st_nlink == 1


def test_publication_revalidates_complete_identity_before_final_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _released_pending_context(
        tmp_path,
        verified=True,
        failure=False,
    )
    acceptance._stage_success_record_exclusive(
        context,
        record,
        secret_values=(),
    )
    original_promote = acceptance._promote_success_inode

    def replace_before_promotion(
        path: Path,
        expected_identity: tuple[int, ...],
        **kwargs: Any,
    ) -> tuple[int, ...]:
        content = path.read_bytes()
        path.unlink()
        path.write_bytes(content)
        path.chmod(0o600)
        return original_promote(path, expected_identity, **kwargs)

    monkeypatch.setattr(
        acceptance,
        "_promote_success_inode",
        replace_before_promotion,
    )

    with pytest.raises(acceptance.M9AcceptanceError, match="changed before publication"):
        acceptance._publish_staged_success(
            replace(context, staged_success=record)
        )

    assert context.pending_path.exists()
    assert context.complete_path.exists()
    assert not context.record_path.exists()


def test_publication_rejects_existing_final_instead_of_clobbering_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _released_pending_context(
        tmp_path,
        verified=True,
        failure=False,
    )
    acceptance._stage_success_record_exclusive(
        context,
        record,
        secret_values=(),
    )
    existing = b'{"existing":true}\n'
    context.record_path.write_bytes(existing)
    context.record_path.chmod(0o644)

    with pytest.raises(acceptance.M9AcceptanceError, match="protected root-owned file"):
        acceptance._publish_staged_success(
            replace(context, staged_success=record)
        )

    assert context.record_path.read_bytes() == existing
    assert context.complete_path.exists()
    assert context.pending_path.exists()


def test_publication_rejects_symlinked_complete_and_unprotected_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _released_pending_context(
        tmp_path,
        verified=True,
        failure=False,
    )
    target = tmp_path / "staged-target.json"
    target.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    target.chmod(0o600)
    context.complete_path.symlink_to(target)

    with pytest.raises(acceptance.M9AcceptanceError, match="protected root-owned file"):
        acceptance._publish_staged_success(
            replace(context, staged_success=record)
        )

    context.complete_path.unlink()
    tmp_path.chmod(0o700)
    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="protected root-owned directory",
    ):
        acceptance._stage_success_record_exclusive(
            context,
            record,
            secret_values=(),
        )


def test_complete_before_pending_commit_recovers_without_api_or_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _patch_execute_dependencies(monkeypatch)
    original_update = acceptance._update_pending
    rejected_verified_commit = False

    def fail_first_verified_commit(*args: Any, **kwargs: Any) -> None:
        nonlocal rejected_verified_commit
        if kwargs.get("stage") == "verified" and not rejected_verified_commit:
            rejected_verified_commit = True
            raise OSError(errno.ENOSPC, "injected pending commit failure")
        original_update(*args, **kwargs)

    monkeypatch.setattr(
        acceptance,
        "_update_pending",
        fail_first_verified_commit,
    )

    with pytest.raises(acceptance.M9AcceptanceError, match="failed safely"):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    staged = json.loads(context.complete_path.read_text(encoding="utf-8"))
    assert pending["stage"] == "fixtures_offline"
    assert pending["failure"] is True
    assert context.complete_path.exists()
    assert stat.S_IMODE(context.complete_path.stat().st_mode) == 0o600
    assert not context.record_path.exists()
    assert not list(
        tmp_path.glob(f".{context.complete_path.name}.*.tmp")
    )

    recovery = replace(context, pending=pending, staged_success=staged)
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("complete recovery must not call the API")
        ),
    )
    recovered = acceptance.execute(
        recovery,
        admin_username="",
        admin_password="",
    )

    assert recovered == staged
    assert context.record_path.exists()
    assert not context.pending_path.exists()
    assert not context.complete_path.exists()


def test_complete_recovers_verified_pending_marked_failed_after_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _released_pending_context(
        tmp_path,
        verified=True,
        failure=False,
    )
    acceptance._update_pending(
        context,
        stage="verified",
        failure=True,
    )
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    acceptance._stage_success_record_exclusive(
        context,
        record,
        secret_values=(),
    )
    recovery = replace(context, pending=pending, staged_success=record)
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("committed complete recovery must not call the API")
        ),
    )

    assert acceptance.execute(
        recovery,
        admin_username="",
        admin_password="",
    ) == record
    assert context.record_path.exists()
    assert not context.pending_path.exists()
    assert not context.complete_path.exists()


def test_verified_pending_before_final_link_recovers_without_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _patch_execute_dependencies(monkeypatch)
    original_link = acceptance.os.link
    rejected_final_link = False

    def fail_first_final_link(
        source: str | bytes | Path,
        target: str | bytes | Path,
        **kwargs: Any,
    ) -> None:
        nonlocal rejected_final_link
        if Path(target).name == context.record_path.name and not rejected_final_link:
            rejected_final_link = True
            raise OSError(errno.ENOSPC, "injected final link failure")
        original_link(source, target, **kwargs)

    monkeypatch.setattr(acceptance.os, "link", fail_first_final_link)

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="could not be recovered safely",
    ):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    staged = json.loads(context.complete_path.read_text(encoding="utf-8"))
    assert pending["stage"] == "verified"
    assert pending["failure"] is False
    assert stat.S_IMODE(context.complete_path.stat().st_mode) == 0o644
    assert context.complete_path.stat().st_nlink == 1
    assert not context.record_path.exists()
    assert not list(
        tmp_path.glob(f".{context.complete_path.name}.*.tmp")
    )

    recovery = replace(context, pending=pending, staged_success=staged)
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("verified recovery must not call the API")
        ),
    )
    assert acceptance.execute(
        recovery,
        admin_username="",
        admin_password="",
    ) == staged
    assert context.record_path.exists()
    assert not context.pending_path.exists()
    assert not context.complete_path.exists()


def test_final_link_before_pending_cleanup_is_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    _patch_execute_dependencies(monkeypatch)
    original_unlink = os.unlink
    rejected_pending_unlink = False

    def fail_first_pending_unlink(
        path: str | bytes,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        nonlocal rejected_pending_unlink
        if Path(path).name == context.pending_path.name and not rejected_pending_unlink:
            rejected_pending_unlink = True
            raise OSError(errno.ENOSPC, "injected pending unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(acceptance.os, "unlink", fail_first_pending_unlink)

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="could not be removed safely",
    ):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    staged = json.loads(context.complete_path.read_text(encoding="utf-8"))
    assert pending["stage"] == "verified"
    assert context.record_path.exists()
    assert context.record_path.stat().st_ino == context.complete_path.stat().st_ino

    recovery = replace(context, pending=pending, staged_success=staged)
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("publication cleanup must not call the API")
        ),
    )
    assert acceptance.execute(
        recovery,
        admin_username="",
        admin_password="",
    ) == staged
    assert context.record_path.exists()
    assert not context.pending_path.exists()
    assert not context.complete_path.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("payment_id", 93, id="payment-id"),
        pytest.param("payment_no_sha256", "f" * 64, id="payment-number-digest"),
        pytest.param(
            "succeeded_at",
            "2026-09-10T01:00:01+00:00",
            id="payment-succeeded-at",
        ),
    ],
)
def test_complete_recovery_rejects_payment_binding_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    context = _fixtures_offline_pending_context(tmp_path, failure=True)
    acceptance._stage_success_record_exclusive(
        context,
        record,
        secret_values=(),
    )
    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    pending["payment_evidence"][field] = value
    context.pending_path.write_text(json.dumps(pending) + "\n", encoding="utf-8")
    recovery = replace(context, pending=pending, staged_success=record)

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="does not match its pending journal",
    ):
        acceptance._publish_staged_success(recovery)

    assert context.complete_path.exists()
    assert context.pending_path.exists()
    assert not context.record_path.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("payment_no_sha256", "not-sha256", id="payment-number-digest"),
        pytest.param(
            "payment_succeeded_at",
            "2026-09-10T00:58:59+00:00",
            id="payment-before-attempt",
        ),
        pytest.param(
            "payment_succeeded_at",
            "after-completion",
            id="payment-after-completion",
        ),
    ],
)
def test_success_record_strictly_validates_payment_identity_and_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    record = _valid_success_record(tmp_path, monkeypatch)
    if value == "after-completion":
        value = (
            datetime.fromisoformat(record["completed_at"]) + timedelta(seconds=1)
        ).isoformat()
    record["scenario"][field] = value

    with pytest.raises(acceptance.M9AcceptanceError, match="evidence is invalid"):
        acceptance._validate_success_record(record)


def test_verified_pending_without_complete_does_not_resume_via_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _released_pending_context(
        tmp_path,
        verified=True,
        failure=False,
    )
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("verified journal without complete must not call the API")
        ),
    )

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="lacks complete session cleanup",
    ):
        acceptance.execute(
            context,
            admin_username="",
            admin_password="",
        )


def test_invalid_admin_credentials_remove_only_fresh_preauth_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(acceptance, "SafeLoopbackClient", _FakeClient)
    monkeypatch.setattr(
        acceptance,
        "_read_synthetic_user",
        lambda context: ("synthetic-user-secret", "synthetic-password-secret"),
    )
    observed_checkpoint: dict[str, Any] = {}

    def reject_login(
        client: _FakeClient,
        *,
        step: str,
        username: str,
        password: str,
        expected_role: str,
    ) -> None:
        del username, password, expected_role
        observed_checkpoint.update(
            json.loads(context.pending_path.read_text(encoding="utf-8"))
        )
        client.results.append(
            {
                "step": step,
                "status": 400,
                "code": 1003,
                "passed": False,
            }
        )
        raise acceptance.base_data.RepresentativeDataError(
            "login rejected without response content"
        )

    monkeypatch.setattr(acceptance.base_data, "_login", reject_login)

    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="SUPER_ADMIN credentials were rejected",
    ):
        acceptance.execute(
            context,
            admin_username="wrong-admin",
            admin_password="wrong-password",
        )

    assert observed_checkpoint["schema_version"] == 3
    assert observed_checkpoint["stage"] == "authentication_started"
    assert observed_checkpoint["failure"] is False
    assert not context.pending_path.exists()
    assert not context.complete_path.exists()
    assert not context.record_path.exists()


def test_ambiguous_admin_login_failure_retains_checkpoint_and_blocks_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(acceptance, "SafeLoopbackClient", _FakeClient)
    monkeypatch.setattr(
        acceptance,
        "_read_synthetic_user",
        lambda context: ("synthetic-user-secret", "synthetic-password-secret"),
    )

    def fail_without_confirmed_response(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        assert context.pending_path.exists()
        raise acceptance.base_data.RepresentativeDataError(
            "login result is ambiguous"
        )

    monkeypatch.setattr(
        acceptance.base_data,
        "_login",
        fail_without_confirmed_response,
    )

    with pytest.raises(acceptance.M9AcceptanceError, match="result is ambiguous"):
        acceptance.execute(
            context,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )

    pending = json.loads(context.pending_path.read_text(encoding="utf-8"))
    assert pending["stage"] == "authentication_started"
    assert pending["failure"] is True
    assert pending["cleanup"]["synthetic_session_revoked"] is True
    assert pending["cleanup"]["super_admin_session_revoked"] is False

    recovery = replace(context, pending=pending)
    monkeypatch.setattr(
        acceptance,
        "SafeLoopbackClient",
        lambda port: (_ for _ in ()).throw(
            AssertionError("ambiguous authentication must not be retried")
        ),
    )
    with pytest.raises(
        acceptance.M9AcceptanceError,
        match="lacks complete session cleanup",
    ):
        acceptance.execute(
            recovery,
            admin_username="admin-user-secret",
            admin_password="admin-password-secret",
        )


def test_success_record_rejects_missing_installer_gate() -> None:
    payload = {key: None for key in acceptance.SUCCESS_RECORD_KEYS}
    payload.update(
        {
            "schema_version": 1,
            "record_type": "gatea-m9-runtime-acceptance",
            "environment": "gatea",
            "ci_job_name": acceptance.CI_JOB_NAME,
            "fixture": {key: None for key in acceptance.FIXTURE_RECORD_KEYS},
            "scenario": {key: None for key in acceptance.SCENARIO_RECORD_KEYS},
            "pre_reconcile": _zero_reconcile(),
            "post_reconcile": _zero_reconcile(scanned=1),
            "pre_wallet_reconcile": _wallet_reconcile(),
            "post_wallet_reconcile": _wallet_reconcile(),
            "cleanup": {key: None for key in acceptance.CLEANUP_RECORD_KEYS},
            "table_sweep": {"status": "ok", "closed": 0},
            "log_redaction": {
                "window": "24h",
                "combined_line_count": 1,
                "services_scanned": list(acceptance.M9_SERVICES),
                "exact_secret_matches": 0,
                "forbidden_pattern_matches": 0,
                "raw_log_content_recorded": False,
                "passed": True,
            },
            "runtime_services": list(acceptance.M9_SERVICES),
            "upgrade_plan_replayed": True,
            "wallet_reconcile_passed": True,
            "table_reconcile_passed": True,
            "table_sweep_passed": True,
            "log_redaction_passed": False,
            "pii_recorded": False,
            "secret_values_recorded": False,
            "table_tokens_recorded": False,
            "super_admin_credentials_recorded": False,
            "synthetic_credentials_recorded": False,
            "token_values_recorded": False,
            "qr_token_values_recorded": False,
            "request_or_response_bodies_recorded": False,
            "raw_dynamic_paths_recorded": False,
            "source_volume_restored": False,
            "loopback_only": True,
            "passed": True,
        }
    )

    with pytest.raises(acceptance.M9AcceptanceError, match="shape"):
        acceptance._validate_success_record(payload)


def test_admin_identity_is_read_only_from_hidden_confirmed_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []
    answers = iter(
        (
            "gatea_super_admin",
            "gatea_super_admin",
            "correct-horse-battery-staple",
            "correct-horse-battery-staple",
        )
    )

    class _TTY:
        def __enter__(self) -> "_TTY":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def fileno(self) -> int:
            return 99

    def hidden(prompt: str, *, stream: object) -> str:
        assert isinstance(stream, _TTY)
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: _TTY())
    monkeypatch.setattr(acceptance.os, "isatty", lambda descriptor: descriptor == 99)
    monkeypatch.setattr(acceptance.getpass, "getpass", hidden)

    assert acceptance._read_admin_identity_from_tty() == (
        "gatea_super_admin",
        "correct-horse-battery-staple",
    )
    assert len(prompts) == 4


def test_cli_exposes_no_credential_argument() -> None:
    parser = acceptance._parser()
    destinations = {action.dest for action in parser._actions}

    assert "admin_username" not in destinations
    assert "admin_password" not in destinations
    assert "password" not in destinations


def test_compose_failure_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_output = "Bearer should-never-be-reported"

    def fail(**kwargs: Any) -> None:
        del kwargs
        raise acceptance.subprocess.CalledProcessError(
            1,
            ["docker", "compose"],
            output=secret_output,
            stderr=secret_output,
        )

    monkeypatch.setattr(acceptance.gatea, "_run_compose", fail)

    with pytest.raises(acceptance.M9AcceptanceError) as raised:
        acceptance._run_compose_safely("table reconcile", values={})

    assert secret_output not in str(raised.value)
    assert "command failed safely" in str(raised.value)
