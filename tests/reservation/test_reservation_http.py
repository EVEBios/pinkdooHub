"""Reservation 用户/管理 HTTP 契约、权限和严格输入测试。"""

import uuid

import pytest
from httpx import AsyncClient

from app.api.deps import get_reservation_service
from app.common.constants.reservation import RESERVATION_CUSTOMER_MESSAGES
from app.common.enums.reservation import (
    ReservationCancellationReason,
    ReservationStatus,
)
from app.common.enums.user import UserRole
from app.core.security import create_access_token
from app.main import app
from app.models.reservation import Reservation
from tests.reservation.support import create_option, create_user, make_service


def _headers(user_id: int, *, auth_version: int = 0) -> dict[str, str]:
    token = create_access_token(
        user_id,
        str(uuid.uuid4()),
        auth_version=auth_version,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fixed_reservation_service() -> None:
    app.dependency_overrides[get_reservation_service] = lambda: make_service()
    yield
    app.dependency_overrides.pop(get_reservation_service, None)


async def test_http_create_query_review_and_customer_cancel_flow(
    client: AsyncClient,
    fixed_reservation_service: None,
) -> None:
    customer = await create_user("http-customer")
    stranger = await create_user("http-stranger", phone="13900139001")
    admin = await create_user(
        "http-admin",
        phone="13700137001",
        role=UserRole.ADMIN,
    )
    product, option = await create_option("http")
    customer_headers = _headers(customer.id, auth_version=customer.auth_version)
    stranger_headers = _headers(stranger.id, auth_version=stranger.auth_version)
    admin_headers = _headers(admin.id, auth_version=admin.auth_version)
    request = {
        "experience_option_id": option.id,
        "reservation_date": "2026-09-09",
        "start_time": "11:30",
    }

    created = await client.post(
        "/api/v1/reservations",
        headers=customer_headers,
        json=request,
    )

    assert created.status_code == 201, created.text
    assert created.json()["message"] == "Reservation submitted for store confirmation"
    created_data = created.json()["data"]
    reservation_id = created_data["id"]
    assert created_data["status"] == {
        "value": "pending",
        "label": "待门店确认",
    }
    assert created_data["customer_message"] == RESERVATION_CUSTOMER_MESSAGES[
        ReservationStatus.PENDING
    ]
    assert created_data["reservation_date"] == "2026-09-09"
    assert created_data["start_time"] == "11:30"
    assert created_data["end_time"] == "12:30"
    assert created_data["price"] == "88.50"
    assert not (
        {"user_id", "user_nickname", "user_phone", "user_phone_masked", "password"}
        & created_data.keys()
    )

    hidden = await client.get(
        f"/api/v1/reservations/{reservation_id}",
        headers=stranger_headers,
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == 40451

    customer_list = await client.get(
        "/api/v1/reservations",
        headers=customer_headers,
        params={"status": "pending", "page": 1, "page_size": 20},
    )
    assert customer_list.status_code == 200
    assert [item["id"] for item in customer_list.json()["data"]["items"]] == [
        reservation_id
    ]

    admin_list = await client.get(
        "/api/v1/admin/reservations",
        headers=admin_headers,
        params={"business_date": "2026-09-09", "user_id": customer.id},
    )
    assert admin_list.status_code == 200, admin_list.text
    admin_list_item = admin_list.json()["data"]["items"][0]
    assert admin_list_item["user_phone_masked"] == "138****8000"
    assert "user_phone" not in admin_list_item

    admin_detail = await client.get(
        f"/api/v1/admin/reservations/{reservation_id}",
        headers=admin_headers,
    )
    assert admin_detail.status_code == 200
    assert admin_detail.json()["data"]["user_phone"] == "13800138000"
    assert "user_phone_masked" not in admin_detail.json()["data"]

    rejected = await client.patch(
        f"/api/v1/admin/reservations/{reservation_id}/reject",
        headers=admin_headers,
    )
    assert rejected.status_code == 200, rejected.text
    rejected_data = rejected.json()["data"]
    assert rejected_data["status"]["value"] == "rejected"
    assert rejected_data["rejection_reason"]["value"] == "no_capacity"
    assert "无空位" in rejected_data["customer_message"]
    assert "重新预约" in rejected_data["customer_message"]
    assert "user_phone" not in rejected_data

    # The MVP intentionally does not auto-block the same slot. A second booking
    # reaches pending and is handled by the store's manual capacity review.
    second = await client.post(
        "/api/v1/reservations",
        headers=customer_headers,
        json=request,
    )
    assert second.status_code == 201
    second_id = second.json()["data"]["id"]
    confirmed = await client.patch(
        f"/api/v1/admin/reservations/{second_id}/confirm",
        headers=admin_headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"]["value"] == "confirmed"

    cancelled = await client.patch(
        f"/api/v1/reservations/{second_id}/cancel",
        headers=customer_headers,
    )
    assert cancelled.status_code == 200
    cancelled_data = cancelled.json()["data"]
    assert cancelled_data["status"]["value"] == "cancelled"
    assert cancelled_data["cancellation_reason"]["value"] == "customer_request"
    assert cancelled_data["customer_message"] == RESERVATION_CUSTOMER_MESSAGES[
        ReservationCancellationReason.CUSTOMER_REQUEST
    ]


async def test_http_admin_can_read_and_change_weekly_closed_day(
    client: AsyncClient,
    fixed_reservation_service: None,
) -> None:
    customer = await create_user("settings-http-customer")
    admin = await create_user(
        "settings-http-admin",
        phone="13900139001",
        role=UserRole.ADMIN,
    )
    customer_headers = _headers(customer.id)
    admin_headers = _headers(admin.id)

    initial = await client.get(
        "/api/v1/admin/reservation-settings",
        headers=admin_headers,
    )
    assert initial.status_code == 200
    assert initial.json()["data"]["weekly_closed_weekday"] == {
        "value": "monday",
        "label": "周一",
    }

    changed = await client.put(
        "/api/v1/admin/reservation-settings/weekly-closed-day",
        headers=admin_headers,
        json={"weekly_closed_weekday": "tuesday"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["previous_weekly_closed_weekday"]["value"] == "monday"
    assert changed.json()["data"]["weekly_closed_weekday"] == {
        "value": "tuesday",
        "label": "周二",
    }

    forbidden = await client.get(
        "/api/v1/admin/reservation-settings",
        headers=customer_headers,
    )
    invalid = await client.put(
        "/api/v1/admin/reservation-settings/weekly-closed-day",
        headers=admin_headers,
        json={"weekly_closed_weekday": "funday", "extra": True},
    )
    assert forbidden.status_code == 403
    assert invalid.status_code == 422


async def test_http_store_closure_first_apply_replay_and_reopen_do_not_revive(
    client: AsyncClient,
    fixed_reservation_service: None,
) -> None:
    customer = await create_user("closure-http-customer")
    admin = await create_user(
        "closure-http-admin",
        phone="13900139001",
        role=UserRole.ADMIN,
    )
    _, option = await create_option("closure-http")
    customer_headers = _headers(customer.id)
    admin_headers = _headers(admin.id)
    create_response = await client.post(
        "/api/v1/reservations",
        headers=customer_headers,
        json={
            "experience_option_id": option.id,
            "reservation_date": "2026-09-10",
            "start_time": "11:00",
        },
    )
    assert create_response.status_code == 201
    reservation_id = create_response.json()["data"]["id"]

    first = await client.put(
        "/api/v1/admin/store-closures/2026-09-10",
        headers=admin_headers,
    )
    replay = await client.put(
        "/api/v1/admin/store-closures/2026-09-10",
        headers=admin_headers,
    )

    assert first.status_code == 201, first.text
    assert {
        "id",
        "business_date",
        "is_closed",
        "newly_cancelled_count",
        "cancelled_pending_count",
        "cancelled_confirmed_count",
        "is_replay",
        "created_at",
        "updated_at",
    } == first.json()["data"].keys()
    assert first.json()["data"]["newly_cancelled_count"] == 1
    assert first.json()["data"]["cancelled_pending_count"] == 1
    assert first.json()["data"]["is_replay"] is False
    assert replay.status_code == 200
    assert replay.json()["data"]["newly_cancelled_count"] == 0
    assert replay.json()["data"]["is_replay"] is True

    reopened = await client.request(
        "DELETE",
        "/api/v1/admin/store-closures/2026-09-10",
        headers=admin_headers,
    )
    detail = await client.get(
        f"/api/v1/reservations/{reservation_id}",
        headers=customer_headers,
    )
    assert reopened.status_code == 200
    assert reopened.json()["data"]["is_closed"] is False
    assert detail.status_code == 200
    assert detail.json()["data"]["status"]["value"] == "cancelled"
    assert detail.json()["data"]["cancellation_reason"]["value"] == "store_closed"
    assert "门店当天休息" in detail.json()["data"]["customer_message"]
    assert (
        await Reservation.get(id=reservation_id)
    ).cancellation_reason == ReservationCancellationReason.STORE_CLOSED


async def test_http_authentication_and_role_boundaries(client: AsyncClient) -> None:
    customer = await create_user("auth-customer")
    admin = await create_user(
        "auth-admin",
        phone="13900139001",
        role=UserRole.ADMIN,
    )
    customer_headers = _headers(customer.id)
    admin_headers = _headers(admin.id)

    for path in ("/api/v1/reservations", "/api/v1/admin/reservations"):
        response = await client.get(path)
        assert response.status_code == 401
        assert response.json()["code"] == 401

    customer_on_admin = await client.get(
        "/api/v1/admin/reservations",
        headers=customer_headers,
    )
    admin_on_customer = await client.get(
        "/api/v1/reservations",
        headers=admin_headers,
    )
    assert customer_on_admin.status_code == 403
    assert customer_on_admin.json()["code"] == 403
    assert admin_on_customer.status_code == 403
    assert admin_on_customer.json()["code"] == 403


@pytest.mark.parametrize(
    ("method", "path", "principal"),
    [
        ("PATCH", "/api/v1/reservations/1/cancel", "customer"),
        ("PATCH", "/api/v1/admin/reservations/1/confirm", "admin"),
        ("PATCH", "/api/v1/admin/reservations/1/reject", "admin"),
        ("PUT", "/api/v1/admin/store-closures/2026-09-10", "admin"),
        ("DELETE", "/api/v1/admin/store-closures/2026-09-10", "admin"),
    ],
)
async def test_bodyless_mutations_reject_even_empty_json_object(
    client: AsyncClient,
    fixed_reservation_service: None,
    method: str,
    path: str,
    principal: str,
) -> None:
    customer = await create_user("strict-customer")
    admin = await create_user(
        "strict-admin",
        phone="13900139001",
        role=UserRole.ADMIN,
    )
    headers = _headers(customer.id if principal == "customer" else admin.id)

    response = await client.request(method, path, headers=headers, json={})

    assert response.status_code == 422
    assert response.json()["code"] == 422


@pytest.mark.parametrize(
    "payload",
    [
        {
            "experience_option_id": True,
            "reservation_date": "2026-09-09",
            "start_time": "11:00",
        },
        {
            "experience_option_id": 1,
            "reservation_date": "2026-9-9",
            "start_time": "11:00",
        },
        {
            "experience_option_id": 1,
            "reservation_date": "2026-09-09",
            "start_time": "11:15",
        },
        {
            "experience_option_id": 1,
            "reservation_date": "2026-09-09",
            "start_time": "11:00",
            "status": "confirmed",
        },
        {
            "experience_option_id": 1,
            "reservation_date": "2026-09-09",
            "start_time": "11:00",
            "phone": "13800138000",
        },
    ],
)
async def test_create_request_strictly_rejects_forged_or_malformed_fields(
    client: AsyncClient,
    fixed_reservation_service: None,
    payload: dict[str, object],
) -> None:
    customer = await create_user("strict-create")

    response = await client.post(
        "/api/v1/reservations",
        headers=_headers(customer.id),
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert not await Reservation.all().exists()


async def test_query_models_reject_unknown_filters_and_foreign_status(
    client: AsyncClient,
    fixed_reservation_service: None,
) -> None:
    customer = await create_user("strict-query")
    admin = await create_user(
        "strict-query-admin",
        phone="13900139001",
        role=UserRole.ADMIN,
    )

    unknown = await client.get(
        "/api/v1/reservations",
        headers=_headers(customer.id),
        params={"phone": "13800138000"},
    )
    foreign_status = await client.get(
        "/api/v1/admin/reservations",
        headers=_headers(admin.id),
        params={"status": "paid"},
    )

    assert unknown.status_code == 422
    assert foreign_status.status_code == 422
