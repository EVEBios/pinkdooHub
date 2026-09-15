"""验收脚本通过真实 ASGI API 验证契约，包含响应丢失后的清理。"""

import asyncio
from uuid import uuid4

import pytest

from app.common.enums.user import UserRole
from app.core.security import create_access_token
from app.models.bead_color import BeadColor
from app.models.store_bead_stock import StoreBeadStock, StoreBeadStockBatch, StoreBeadStockEntry
from app.models.table_session import StoreTable, TableSession, TableSessionTimer, TableOccupancy
from app.models.payment import Payment
from scripts.release import gatea_m15_acceptance as acceptance
from tests.reservation.support import create_user
from tests.release.test_gatea_m15_snapshot import snapshot


class ApiBridge:
    def __init__(self, client, loop, *, lost_response=False):
        self.client, self.loop = client, loop
        self.lost_response = lost_response

    def json_request(self, step, method, path, *, token=None, payload=None,
                     headers=None, expected_status=200, expected_code=0):
        request_headers = dict(headers or {})
        if token is not None: request_headers["Authorization"] = "Bearer " + token
        response = asyncio.run_coroutine_threadsafe(self.client.request(
            method, path, headers=request_headers, json=payload), self.loop).result(timeout=10)
        assert response.status_code == expected_status, (step, response.text)
        assert response.json()["code"] == expected_code, (step, response.text)
        if self.lost_response and step == "direct-create":
            self.lost_response = False
            raise OSError("response lost after commit")
        return response.json()


async def test_read_acceptance_matches_real_contract_without_inventory_writes(client):
    admin = await create_user("m15-read-admin", role=UserRole.SUPER_ADMIN, phone=None)
    await BeadColor.bulk_create([BeadColor(slot_no=i, color_code=f"A{i}", name=f"A{i}", sort=i) for i in range(1, 222)])
    bridge = ApiBridge(client, asyncio.get_running_loop())
    result = await asyncio.to_thread(acceptance.check_read_contracts, bridge, create_access_token(admin.id, str(uuid4()), auth_version=admin.auth_version))
    assert result["uncounted_colors"] == 221
    for model in (StoreBeadStock, StoreBeadStockBatch, StoreBeadStockEntry):
        assert await model.all().count() == 0


@pytest.mark.parametrize("lost_response", (False, True))
async def test_direct_acceptance_releases_its_only_session_even_after_response_loss(client, lost_response):
    from tests.table_sessions.test_direct_table_session import setup_direct
    admin, table, _, _ = await setup_direct()
    await StoreTable.bulk_create([StoreTable(table_no=f"T{i:02d}", display_name=f"T{i:02d}", qr_token=f"{i:032d}") for i in range(2, 31)])
    bridge = ApiBridge(client, asyncio.get_running_loop(), lost_response=lost_response)
    journal = []
    args = (bridge, create_access_token(admin.id, str(uuid4()), auth_version=admin.auth_version), "b" * 32, journal.append)
    if lost_response:
        with pytest.raises(OSError): await asyncio.to_thread(acceptance.direct_session, *args)
    else:
        result = await asyncio.to_thread(acceptance.direct_session, *args)
        assert result["released"] is True and result["replayed_without_restart"] is True
    assert await TableSession.all().count() == 1
    assert await TableSessionTimer.all().count() == 1
    assert await TableOccupancy.all().count() == 0
    assert (await TableSession.first()).status.value == "closed"
    assert await Payment.all().count() == 0
    assert journal[-1]["phase"] == "direct-session-released"


@pytest.mark.parametrize("change", (None, "money", "stock", "read", "logout", "logs", "session"))
def test_acceptance_record_requires_preserved_business_and_completed_cleanup(change):
    before, after = snapshot(15), snapshot(15)
    for table in ("table_sessions", "table_session_timers"): after["complete_content"][table]["rows"] += 1
    payload = {"schema_version": 1, "record_type": "gatea-m15-runtime-acceptance", "candidate_sha": "a" * 40,
        "image_id": "sha256:abc", "upgrade_record_sha256": "b" * 64, "passed": True,
        "admin_session_revoked": True, "secret_values_recorded": False, "completed_at": "2026-09-15T18:00:00+00:00",
        "read_contracts": {"uncounted_colors": 221, "stock_batches": 0, "stock_writes_performed": False,
            **{k: True for k in ("reservation_read", "attention_read", "followup_read", "authentication_required", "strict_integer_validation")}},
        "direct_session": {"created": True, "replayed_without_restart": True, "released": True},
        "unchanged_business_tables": sorted(acceptance.UNCHANGED_TABLES), "before_state": before, "after_state": after,
        "log_scan": {"passed": True, "exact_secret_matches": 0, "forbidden_pattern_matches": 0},
        "table_reconcile": {"open_sessions": 0, "occupancies": 0, "violations": 0}}
    if change == "money": after["complete_content"]["payments"]["sha256"] = "c" * 64
    if change == "stock": payload["read_contracts"]["stock_writes_performed"] = True
    if change == "read": payload["read_contracts"]["followup_read"] = False
    if change == "logout": payload["admin_session_revoked"] = False
    if change == "logs": payload["log_scan"]["exact_secret_matches"] = 1
    if change == "session": after["complete_content"]["table_sessions"]["rows"] += 1
    args = dict(sha="a" * 40, image_id="sha256:abc", upgrade_sha256="b" * 64)
    if change:
        with pytest.raises(acceptance.M15AcceptanceError): acceptance.require_result(payload, **args)
    else: acceptance.require_result(payload, **args)
