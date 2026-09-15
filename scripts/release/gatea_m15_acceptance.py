"""M15 Gate A 管理员辅助验收：只读新契约、直接开台/释放及存量资金保持。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
from typing import Any

from scripts.release import gatea_candidate as candidate
from scripts.release import gatea_m15_upgrade as upgrade
from scripts.release import gatea_m9_acceptance as m9
from scripts.release import gatea_operations as gatea
from scripts.release import gatea_representative_data as auth


DEFAULT_RECORD_DIR = Path("/srv/pinkdoohub/gatea/records/m15-acceptance")
UNCHANGED_TABLES = (frozenset(upgrade.snapshots.model_columns(15)) | {"aerich"}) - {
    "users", "audit_logs", "table_sessions", "table_session_timers", "table_occupancies"}


class M15AcceptanceError(gatea.GateAError):
    """只返回安全的验收步骤标识。"""


def record_path(record_dir: Path, sha: str) -> Path:
    return record_dir / f"gatea-m15-runtime-acceptance-{sha}.json"


def data(document: dict[str, Any], step: str) -> dict[str, Any]:
    value = document.get("data")
    if not isinstance(value, dict):
        raise M15AcceptanceError(f"Gate A M15 {step} response is invalid")
    return value


def _enum(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def check_read_contracts(client: m9.SafeLoopbackClient, token: str) -> dict[str, Any]:
    """读取不创建提醒、跟进或库存余额；未盘点必须保持 null。"""
    for step, path, fields in (
        ("reservations", "/api/v1/admin/reservations?page=1&page_size=20", ("items", "total")),
        ("attention", "/api/v1/admin/attention", ("reservation_total", "order_total", "table_total", "wallet_unread")),
        ("followups", "/api/v1/admin/reservation-followups/summary", ("contact_pending", "overdue_pending")),
    ):
        result = data(client.json_request(step, "GET", path, token=token), step)
        if any(field not in result for field in fields):
            raise M15AcceptanceError(f"Gate A M15 {step} contract is incomplete")
    stock = data(client.json_request("store-stock", "GET", "/api/v1/admin/store-bead-stock?page_size=221", token=token), "store-stock")
    items = stock.get("items")
    if (not isinstance(items, list) or len(items) != 221 or stock.get("total") != 221
            or any(item.get("packs") is not None or type(item.get("revision")) is not int or item["revision"] != 0 for item in items)
            or len({item.get("bead_color_id") for item in items}) != 221):
        raise M15AcceptanceError("Gate A M15 inventory must contain 221 uncounted colors")
    batches = data(client.json_request("stock-history", "GET", "/api/v1/admin/store-bead-stock/batches", token=token), "stock-history")
    if batches.get("total") != 0 or batches.get("items") != []:
        raise M15AcceptanceError("Gate A M15 inventory history is not empty")
    # 未登录拒绝、严格整数校验均在写入前失败，不虚构实际盘点。
    client.json_request("stock-auth-required", "GET", "/api/v1/admin/store-bead-stock", expected_status=401, expected_code=401)
    client.json_request("stock-reject-bool", "POST", "/api/v1/admin/store-bead-stock/batches", token=token,
        payload={"request_key": "8ee99448-97ed-43a2-90db-1a276fbc7274", "items": [
            {"bead_color_id": items[0]["bead_color_id"], "expected_revision": 0, "packs": True}]},
        expected_status=422, expected_code=422)
    return {"reservation_read": True, "attention_read": True, "followup_read": True,
            "uncounted_colors": 221, "stock_batches": 0, "stock_writes_performed": False,
            "authentication_required": True, "strict_integer_validation": True}


def direct_session(client: m9.SafeLoopbackClient, token: str, attempt: str,
                   checkpoint: Any) -> dict[str, Any]:
    tables = data(client.json_request("tables", "GET", "/api/v1/admin/tables", token=token), "tables")
    choices = data(client.json_request("durations", "GET", "/api/v1/admin/table-duration-options", token=token), "durations")
    available = [row for row in tables.get("items", []) if row.get("state") == "available"]
    options = choices.get("items", [])
    if len(tables.get("items", [])) != 30 or not available or not options:
        raise M15AcceptanceError("Gate A M15 direct-session prerequisites are unavailable")
    table, option = available[-1], options[0]
    path = f"/api/v1/admin/tables/{table['id']}/direct-sessions"
    body = {"option_id": option["option_id"], "duration_minutes": option["duration_minutes"],
            "note": "Gate A M15 migration acceptance"}
    key = f"gatea-m15-direct-{attempt}"
    checkpoint({"phase": "direct-session-requested", "table_id": table["id"], "option_id": option["option_id"],
                "duration_minutes": option["duration_minutes"]})
    session = None
    try:
        session = data(client.json_request("direct-create", "POST", path, token=token,
            payload=body, headers={"Idempotency-Key": key}), "direct-create")
        if (session.get("source") != "direct" or _enum(session.get("status")) != "active"
                or session.get("order_id") is not None or session.get("user_id") is not None
                or session.get("payment_deadline_at") is not None
                or len(session.get("timers", [])) != 1
                or session["timers"][0].get("duration_minutes") != option["duration_minutes"]):
            raise M15AcceptanceError("Gate A M15 direct-session shape is invalid")
        repeated = data(client.json_request("direct-replay", "POST", path, token=token,
            payload=body, headers={"Idempotency-Key": key}), "direct-replay")
        if repeated.get("session_no") != session.get("session_no") or repeated.get("started_at") != session.get("started_at"):
            raise M15AcceptanceError("Gate A M15 direct-session replay changed its start")
    finally:
        # 初次响应丢失时用同一意图查回已提交事实，再释放；不换 Key 创建第二条会话。
        if session is None:
            session = data(client.json_request("direct-recover-response", "POST", path, token=token,
                payload=body, headers={"Idempotency-Key": key}), "direct-recover-response")
        number = session.get("session_no")
        if not isinstance(number, str) or not number:
            raise M15AcceptanceError("Gate A M15 direct-session identity is missing")
        closed = data(client.json_request("direct-release", "POST", f"/api/v1/admin/table-sessions/{number}/release",
            token=token, payload={"reason": "Gate A M15 migration acceptance completed"},
            headers={"Idempotency-Key": f"gatea-m15-release-{attempt}"}), "direct-release")
        if _enum(closed.get("status")) != "closed":
            raise M15AcceptanceError("Gate A M15 direct-session was not released")
        checkpoint({"phase": "direct-session-released", "session_no_sha256": hashlib.sha256(number.encode()).hexdigest()})
    return {"created": True, "replayed_without_restart": True, "released": True,
            "session_no_sha256": hashlib.sha256(number.encode()).hexdigest()}


def require_result(payload: dict[str, Any], *, sha: str, image_id: str, upgrade_sha256: str) -> None:
    try:
        if (type(payload.get("schema_version")) is not int or payload["schema_version"] != 1
                or payload.get("record_type") != "gatea-m15-runtime-acceptance"
                or payload.get("candidate_sha") != sha or payload.get("image_id") != image_id
                or payload.get("upgrade_record_sha256") != upgrade_sha256
                or payload.get("passed") is not True or payload.get("admin_session_revoked") is not True
                or payload.get("secret_values_recorded") is not False
                or not candidate._is_utc_timestamp(payload.get("completed_at"))
                or payload["read_contracts"].get("uncounted_colors") != 221
                or payload["read_contracts"].get("stock_batches") != 0
                or any(payload["read_contracts"].get(k) is not True for k in (
                    "reservation_read", "attention_read", "followup_read", "authentication_required", "strict_integer_validation"))
                or payload["read_contracts"].get("stock_writes_performed") is not False
                or any(payload["direct_session"].get(k) is not True for k in ("created", "replayed_without_restart", "released"))
                or payload.get("unchanged_business_tables") != sorted(UNCHANGED_TABLES)
                or payload["log_scan"].get("passed") is not True
                or payload["log_scan"].get("exact_secret_matches") != 0
                or payload["log_scan"].get("forbidden_pattern_matches") != 0
                or payload["table_reconcile"].get("open_sessions") != 0
                or payload["table_reconcile"].get("occupancies") != 0
                or payload["table_reconcile"].get("violations") != 0):
            raise M15AcceptanceError("Gate A M15 acceptance evidence is incomplete")
        upgrade.snapshots.validate_snapshot(payload["after_state"], 15)
        upgrade.snapshots.validate_snapshot(payload["before_state"], 15)
        before, after = payload["before_state"]["complete_content"], payload["after_state"]["complete_content"]
        if (any(before[t] != after[t] for t in UNCHANGED_TABLES)
                or any(after[t]["rows"] != before[t]["rows"] + 1 for t in ("table_sessions", "table_session_timers"))):
            raise M15AcceptanceError("Gate A M15 acceptance data preservation proof differs")
    except (KeyError, TypeError, upgrade.snapshots.M15SnapshotError) as error:
        raise M15AcceptanceError("Gate A M15 acceptance evidence is invalid") from error


def execute(*, config_file: Path, secret_dir: Path, release_root: Path,
            release_record_dir: Path, record_dir: Path) -> dict[str, Any]:
    values = gatea._validated_inputs(config_file=config_file, secret_dir=secret_dir,
                                    mode="loopback", require_available_port=False)
    sha, image_id = gatea._candidate_sha(values), gatea.validate_app_image(values)
    candidate._require_execution_release(release_root, sha)
    gatea.reject_unresolved_candidate_transition_journals(record_dir=release_record_dir)
    gatea.reject_unresolved_m9_acceptance_sidecars(record_dir=gatea.DEFAULT_M9_ACCEPTANCE_RECORD_DIR)
    record = gatea._require_upgrade_record(record_dir=release_record_dir, candidate_sha=sha, image_id=image_id)
    if record.get("transition_kind") != upgrade.TRANSITION_KIND:
        raise M15AcceptanceError("Gate A M15 acceptance requires its own migration")
    upgrade.require_replay(record_dir=release_record_dir, candidate_sha=sha, image_id=image_id, upgrade_record=record)
    candidate._require_root_directory(record_dir, 0o755, "Gate A M15 acceptance records")
    target = record_path(record_dir, sha)
    pending = release_record_dir / f"{sha}.m15-acceptance.pending.json"
    if target.exists() or target.is_symlink() or pending.exists() or pending.is_symlink():
        raise M15AcceptanceError("Gate A M15 acceptance already has evidence; inspect before retrying")
    context = SimpleNamespace(values=values, config_file=config_file, secret_dir=secret_dir)
    m9._ensure_m9_services(context)
    before = upgrade.read_state(values, config_file, secret_dir, 15)
    client = m9.SafeLoopbackClient(int(values.get("GATEA_LOOPBACK_PORT", "18080")))
    username, password = m9._read_admin_identity_from_tty()
    credentials = None
    transient = [username, password]
    started = upgrade.legacy._iso_now()
    attempt = secrets.token_hex(16)
    journal: dict[str, Any] = {"candidate_sha": sha, "attempt_id": attempt, "started_at": started,
                               "phase": "prepared", "secret_values_recorded": False}
    revoked = False
    try:
        credentials = auth._login(client, step="m15-admin-login", username=username,
                                   password=password, expected_role="super_admin")
        transient.extend([credentials["access_token"], credentials["refresh_token"]])
        candidate._write_json_exclusive(pending, journal)
        def checkpoint(item: dict[str, Any]) -> None:
            journal.update(item); candidate._atomic_replace_json(pending, journal, 0o644)
        reads = check_read_contracts(client, credentials["access_token"])
        direct = direct_session(client, credentials["access_token"], attempt, checkpoint)
    finally:
        if credentials is not None:
            auth._logout_and_verify(client, step_prefix="m15-admin", access_token=credentials["access_token"],
                                    refresh_token=credentials["refresh_token"])
            revoked = True
        username = password = ""
    after = upgrade.read_state(values, config_file, secret_dir, 15)
    if any(before["complete_content"][name] != after["complete_content"][name] for name in UNCHANGED_TABLES):
        raise M15AcceptanceError("Gate A M15 acceptance unexpectedly changed existing business data")
    for table in ("table_sessions", "table_session_timers"):
        if after["complete_content"][table]["rows"] != before["complete_content"][table]["rows"] + 1:
            raise M15AcceptanceError("Gate A M15 acceptance created an unexpected number of sessions or timers")
    reconcile = gatea._run_m9_table_reconcile(values=values, config_file=config_file, secret_dir=secret_dir, mode="loopback")
    logs = m9._verify_log_redaction(context, transient_secrets=transient)
    transient.clear(); credentials = None
    payload = {"schema_version": 1, "record_type": "gatea-m15-runtime-acceptance", "candidate_sha": sha,
        "image_id": image_id, "upgrade_record_sha256": upgrade._load(gatea._upgrade_marker(release_record_dir, sha), "M15 upgrade")[1],
        "started_at": started, "completed_at": upgrade.legacy._iso_now(), "read_contracts": reads,
        "direct_session": direct, "unchanged_business_tables": sorted(UNCHANGED_TABLES), "before_state": before, "after_state": after,
        "table_reconcile": reconcile, "log_scan": logs, "admin_session_revoked": revoked,
        "secret_values_recorded": False, "passed": True}
    require_result(payload, sha=sha, image_id=image_id, upgrade_sha256=payload["upgrade_record_sha256"])
    candidate._write_json_exclusive(target, payload)
    pending.unlink(); candidate._fsync_directory(release_record_dir)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name, default in (("config-file", gatea.DEFAULT_CONFIG_FILE), ("secret-dir", gatea.DEFAULT_SECRET_DIR),
        ("release-root", Path("/srv/pinkdoohub/gatea/releases")), ("release-record-dir", gatea.DEFAULT_RECORD_DIR),
        ("record-dir", DEFAULT_RECORD_DIR)):
        parser.add_argument(f"--{name}", type=Path, default=default)
    args = parser.parse_args(argv)
    try:
        with gatea.operation_lock(), gatea.operation_termination_guard():
            result = execute(**vars(args))
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}), file=sys.stderr); return 1
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
