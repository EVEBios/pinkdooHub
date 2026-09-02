"""Product 普通 JSON FastAPI 路由契约测试。"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import status
from httpx import AsyncClient

from app.api.deps import (
    get_current_admin,
    get_product_image_storage,
    get_product_service,
)
from app.api.v1.admin_products import router as admin_products_router
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.pagination import Page
from app.main import app
from app.services.product_service import (
    ExperienceOptionCreationResult,
    ProductService,
)
from app.storage.image import LocalImageStorage
from app.storage.image import StoredImage


NOW = datetime(2026, 8, 13, 9, 0, tzinfo=timezone.utc)


def _image(
    image_id: int,
    *,
    product_id: int,
    option_id: int | None = None,
    is_cover: bool = False,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=image_id,
        product_id=product_id,
        experience_option_id=option_id,
        image_url=f"https://cdn.example.com/{image_id}.jpg",
        is_cover=is_cover,
        sort=0,
        is_deleted=is_deleted,
    )


def _option(
    option_id: int = 11,
    *,
    product_id: int = 1,
    is_deleted: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=option_id,
        product_id=product_id,
        duration=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
        images=[
            _image(
                20,
                product_id=product_id,
                option_id=option_id,
            )
        ],
        is_deleted=is_deleted,
    )


def _product(
    *,
    product_id: int = 1,
    product_type: ProductType = ProductType.EXPERIENCE,
    status_value: ProductStatus = ProductStatus.ONLINE,
    is_deleted: bool = False,
    description: str | None = "商品说明",
) -> SimpleNamespace:
    images = [
        _image(10, product_id=product_id, is_cover=True),
    ]
    options = [_option(product_id=product_id)]
    kit = None
    if product_type is ProductType.KIT:
        options = []
        kit = SimpleNamespace(
            id=900,
            product_id=product_id,
            price=Decimal("699.00"),
            stock=5,
        )
    return SimpleNamespace(
        id=product_id,
        name="拼豆商品",
        product_type=product_type,
        description=description,
        status=status_value,
        is_deleted=is_deleted,
        images=images,
        experience_options=options,
        kit=kit,
        created_at=NOW,
        updated_at=NOW,
    )


def _service() -> Mock:
    service = Mock(spec=ProductService)
    for name in (
        "list_admin_products",
        "list_product_audit_logs",
        "list_online_products",
        "get_admin_product_detail",
        "get_online_product_detail",
        "create_experience_product",
        "create_kit_product",
        "update_product",
        "delete_product",
        "create_experience_option",
        "update_experience_option",
        "delete_experience_option",
        "create_product_image",
        "create_option_image",
        "update_kit_price",
        "update_product_image",
        "delete_product_image",
        "online_product",
        "offline_product",
    ):
        setattr(service, name, AsyncMock())
    return service


@pytest.fixture
def routed_service() -> Mock:
    service = _service()
    app.dependency_overrides[get_product_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


@pytest.fixture
def admin_routed_service(routed_service: Mock) -> Mock:
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=7)
    yield routed_service
    app.dependency_overrides.clear()


async def test_public_list_translates_query_and_serializes_page(
    client: AsyncClient,
    routed_service: Mock,
) -> None:
    product = _product()
    routed_service.list_online_products.return_value = Page(
        items=[product], total=1, page=2, page_size=5, pages=1
    )

    response = await client.get(
        "/api/v1/products?page=2&page_size=5&product_type=experience&keyword=%E6%8B%BC%E8%B1%86"
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [
            {
                "id": 1,
                "name": "拼豆商品",
                "product_type": {
                    "value": "experience",
                    "label": "拼豆体验",
                },
                "cover_image": "https://cdn.example.com/10.jpg",
                "display_price": "299.00",
            }
        ],
        "total": 1,
        "page": 2,
        "page_size": 5,
        "pages": 1,
    }
    routed_service.list_online_products.assert_awaited_once_with(
        page=2,
        page_size=5,
        product_type=ProductType.EXPERIENCE,
        keyword="拼豆",
    )


@pytest.mark.parametrize(
    "path,product_type",
    [
        ("/api/v1/products/experience/1", ProductType.EXPERIENCE),
        ("/api/v1/products/kit/2", ProductType.KIT),
    ],
)
async def test_public_detail_routes_are_type_isolated(
    client: AsyncClient,
    routed_service: Mock,
    path: str,
    product_type: ProductType,
) -> None:
    product_id = 1 if product_type is ProductType.EXPERIENCE else 2
    routed_service.get_online_product_detail.return_value = _product(
        product_id=product_id,
        product_type=product_type,
    )

    response = await client.get(path)

    assert response.status_code == 200
    assert response.json()["data"]["product_type"]["value"] == product_type.value
    routed_service.get_online_product_detail.assert_awaited_once_with(
        product_id,
        product_type=product_type,
    )


async def test_request_validation_uses_unified_envelope_without_input_echo(
    client: AsyncClient,
    routed_service: Mock,
) -> None:
    response = await client.get("/api/v1/products?page=0&keyword=secret-value")

    assert response.status_code == 422
    assert response.json() == {
        "code": 422,
        "message": "Validation failed",
        "data": {
            "errors": [
                {
                    "location": ["query", "page"],
                    "message": "Input should be greater than or equal to 1",
                    "type": "greater_than_equal",
                }
            ]
        },
    }
    assert "secret-value" not in response.text
    routed_service.list_online_products.assert_not_awaited()


async def test_unknown_query_parameter_is_rejected(
    client: AsyncClient,
    routed_service: Mock,
) -> None:
    response = await client.get("/api/v1/products?unknown=value")

    assert response.status_code == 422
    error_item = response.json()["data"]["errors"][0]
    assert error_item["location"] == ["query", "unknown"]
    assert error_item["type"] == "extra_forbidden"
    routed_service.list_online_products.assert_not_awaited()


async def test_admin_products_require_admin_permission(
    client: AsyncClient,
    auth_user: dict,
    routed_service: Mock,
) -> None:
    response = await client.get(
        "/api/v1/admin/products",
        headers={"Authorization": f"Bearer {auth_user['token']}"},
    )

    assert response.status_code == 403
    routed_service.list_admin_products.assert_not_awaited()


async def test_admin_list_translates_all_filters(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    product = _product(status_value=ProductStatus.DRAFT)
    admin_routed_service.list_admin_products.return_value = Page(
        items=[product], total=1, page=1, page_size=20, pages=1
    )

    response = await client.get(
        "/api/v1/admin/products?product_type=experience&status=draft&keyword=x&include_deleted=true"
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["status"]["value"] == "draft"
    admin_routed_service.list_admin_products.assert_awaited_once_with(
        page=1,
        page_size=20,
        product_type=ProductType.EXPERIENCE,
        status=ProductStatus.DRAFT,
        keyword="x",
        include_deleted=True,
    )


async def test_product_audit_route_serializes_shared_page(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    admin_routed_service.list_product_audit_logs.return_value = Page(
        items=[
            SimpleNamespace(
                id=9,
                operator_id=7,
                action="CREATE_PRODUCT",
                target_type="product",
                target_id=1,
                description=None,
                ip_address="127.0.0.1",
                created_at=NOW,
            )
        ],
        total=1,
        page=2,
        page_size=5,
        pages=1,
    )

    response = await client.get(
        "/api/v1/admin/products/1/audit-logs?page=2&page_size=5"
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [
            {
                "id": 9,
                "operator_id": 7,
                "action": "CREATE_PRODUCT",
                "target_type": "product",
                "target_id": 1,
                "description": None,
                "ip_address": "127.0.0.1",
                "created_at": "2026-08-13T09:00:00Z",
            }
        ],
        "total": 1,
        "page": 2,
        "page_size": 5,
        "pages": 1,
    }
    admin_routed_service.list_product_audit_logs.assert_awaited_once_with(
        1,
        page=2,
        page_size=5,
    )


async def test_product_audit_route_requires_admin_permission(
    client: AsyncClient,
    auth_user: dict,
    routed_service: Mock,
) -> None:
    response = await client.get(
        "/api/v1/admin/products/1/audit-logs",
        headers={"Authorization": f"Bearer {auth_user['token']}"},
    )

    assert response.status_code == 403
    routed_service.list_product_audit_logs.assert_not_awaited()


async def test_product_audit_route_rejects_unknown_query_parameter(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    response = await client.get(
        "/api/v1/admin/products/1/audit-logs?action=DELETE_PRODUCT"
    )

    assert response.status_code == 422
    error_item = response.json()["data"]["errors"][0]
    assert error_item["location"] == ["query", "action"]
    assert error_item["type"] == "extra_forbidden"
    admin_routed_service.list_product_audit_logs.assert_not_awaited()


@pytest.mark.parametrize(
    "path,product_type",
    [
        ("/api/v1/admin/products/experience/1", ProductType.EXPERIENCE),
        ("/api/v1/admin/products/kit/2", ProductType.KIT),
    ],
)
async def test_admin_detail_routes_are_type_isolated(
    client: AsyncClient,
    admin_routed_service: Mock,
    path: str,
    product_type: ProductType,
) -> None:
    product_id = 1 if product_type is ProductType.EXPERIENCE else 2
    admin_routed_service.get_admin_product_detail.return_value = _product(
        product_id=product_id,
        product_type=product_type,
        status_value=ProductStatus.DRAFT,
    )

    response = await client.get(path)

    assert response.status_code == 200
    assert response.json()["data"]["status"]["value"] == "draft"
    admin_routed_service.get_admin_product_detail.assert_awaited_once_with(
        product_id,
        product_type=product_type,
    )


@pytest.mark.parametrize(
    "path,payload,method_name,product_type",
    [
        (
            "/api/v1/admin/products/experience",
            {"name": "体验", "description": "说明"},
            "create_experience_product",
            ProductType.EXPERIENCE,
        ),
        (
            "/api/v1/admin/products/kit",
            {"name": "套装", "price": "699.00"},
            "create_kit_product",
            ProductType.KIT,
        ),
    ],
)
async def test_product_create_routes_return_201(
    client: AsyncClient,
    admin_routed_service: Mock,
    path: str,
    payload: dict,
    method_name: str,
    product_type: ProductType,
) -> None:
    method = getattr(admin_routed_service, method_name)
    method.return_value = _product(
        product_id=3,
        product_type=product_type,
        status_value=ProductStatus.DRAFT,
    )

    response = await client.post(path, json=payload)

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["data"]["status"] == {
        "value": "draft",
        "label": "草稿",
    }
    kwargs = method.await_args.kwargs
    assert kwargs["operator_id"] == 7
    assert kwargs["ip_address"] == "127.0.0.1"
    if product_type is ProductType.KIT:
        assert kwargs["price"] == Decimal("699.00")
        assert "stock" not in kwargs


@pytest.mark.parametrize("restored,expected_status", [(False, 201), (True, 200)])
async def test_option_create_status_depends_on_restore_result(
    client: AsyncClient,
    admin_routed_service: Mock,
    restored: bool,
    expected_status: int,
) -> None:
    option = _option()
    admin_routed_service.create_experience_option.return_value = (
        ExperienceOptionCreationResult(option=option, restored=restored)
    )

    response = await client.post(
        "/api/v1/admin/products/experience/1/options",
        json={
            "duration_minutes": 60,
            "participants": 1,
            "day_type": "weekday",
            "price": "299.00",
        },
    )

    assert response.status_code == expected_status
    assert response.json()["data"]["images"][0]["id"] == 20
    admin_routed_service.create_experience_option.assert_awaited_once_with(
        1,
        duration_minutes=60,
        participants=1,
        day_type=DayType.WEEKDAY,
        price=Decimal("299.00"),
        operator_id=7,
        ip_address="127.0.0.1",
    )


@pytest.mark.parametrize(
    "method,path,payload,service_method,result,expected_data",
    [
        (
            "PATCH",
            "/api/v1/admin/products/1",
            {"description": None},
            "update_product",
            _product(status_value=ProductStatus.DRAFT, description=None),
            {"description": None},
        ),
        (
            "DELETE",
            "/api/v1/admin/products/1",
            None,
            "delete_product",
            _product(status_value=ProductStatus.DRAFT, is_deleted=True),
            {"is_deleted": True},
        ),
        (
            "PATCH",
            "/api/v1/admin/products/1/online",
            None,
            "online_product",
            _product(status_value=ProductStatus.ONLINE),
            {"status": {"value": "online", "label": "已上架"}},
        ),
        (
            "PATCH",
            "/api/v1/admin/products/1/offline",
            None,
            "offline_product",
            _product(status_value=ProductStatus.OFFLINE),
            {"status": {"value": "offline", "label": "已下架"}},
        ),
        (
            "PATCH",
            "/api/v1/admin/options/11",
            {"price": "399.00"},
            "update_experience_option",
            _option(),
            {"price": "299.00"},
        ),
        (
            "DELETE",
            "/api/v1/admin/options/11",
            None,
            "delete_experience_option",
            _option(is_deleted=True),
            {"is_deleted": True},
        ),
        (
            "PATCH",
            "/api/v1/admin/product-images/10",
            {"sort": 5},
            "update_product_image",
            _image(10, product_id=1, is_cover=True),
            {"sort": 0},
        ),
        (
            "DELETE",
            "/api/v1/admin/product-images/10",
            None,
            "delete_product_image",
            _image(10, product_id=1, is_deleted=True),
            {"is_deleted": True},
        ),
        (
            "PATCH",
            "/api/v1/admin/products/kit/2/price",
            {"price": "799.00"},
            "update_kit_price",
            SimpleNamespace(id=900, product_id=2, price=Decimal("799.00"), stock=5),
            {"id": 2, "price": "799.00"},
        ),
    ],
)
async def test_json_mutation_routes_call_service_and_map_response(
    client: AsyncClient,
    admin_routed_service: Mock,
    method: str,
    path: str,
    payload: dict | None,
    service_method: str,
    result: SimpleNamespace,
    expected_data: dict,
) -> None:
    service_call = getattr(admin_routed_service, service_method)
    service_call.return_value = result

    response = await client.request(method, path, json=payload)

    assert response.status_code == 200
    data = response.json()["data"]
    for key, value in expected_data.items():
        assert data[key] == value
    assert service_call.await_count == 1
    assert service_call.await_args.kwargs["operator_id"] == 7
    assert service_call.await_args.kwargs["ip_address"] == "127.0.0.1"

    if service_method == "update_product":
        assert service_call.await_args.kwargs["updates"] == {"description": None}
    if service_method == "update_experience_option":
        assert service_call.await_args.kwargs["updates"] == {
            "price": Decimal("399.00")
        }
    if service_method == "update_product_image":
        assert service_call.await_args.kwargs["updates"] == {"sort": 5}


async def test_json_request_rejects_unknown_fields_before_service(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    response = await client.post(
        "/api/v1/admin/products/experience",
        json={"name": "体验", "status": "online"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == 422
    assert response.json()["message"] == "Validation failed"
    admin_routed_service.create_experience_product.assert_not_awaited()


async def test_kit_create_rejects_legacy_stock_field(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    response = await client.post(
        "/api/v1/admin/products/kit",
        json={"name": "套装", "price": "699.00", "stock": 8},
    )

    assert response.status_code == 422
    error = response.json()["data"]["errors"][0]
    assert error["location"] == ["body", "stock"]
    assert error["type"] == "extra_forbidden"
    admin_routed_service.create_kit_product.assert_not_awaited()


async def test_legacy_stock_route_is_removed(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    response = await client.patch(
        "/api/v1/admin/products/kit/2/stock",
        json={"stock": 20},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("path", "service_method", "expected_data"),
    [
        (
            "/api/v1/admin/products/1/images",
            "create_product_image",
            {
                "id": 30,
                "image_url": "/uploads/products/test.png",
                "is_cover": True,
                "sort": 3,
            },
        ),
        (
            "/api/v1/admin/options/11/images",
            "create_option_image",
            {
                "id": 31,
                "image_url": "/uploads/products/test.png",
                "sort": 3,
            },
        ),
    ],
)
async def test_image_upload_routes_store_call_service_and_return_201(
    client: AsyncClient,
    admin_routed_service: Mock,
    tmp_path,
    path: str,
    service_method: str,
    expected_data: dict,
) -> None:
    storage = LocalImageStorage(
        root=tmp_path,
        base_url="/uploads/products",
        key_factory=lambda: "a" * 32,
    )
    app.dependency_overrides[get_product_image_storage] = lambda: storage
    service_call = getattr(admin_routed_service, service_method)
    service_call.return_value = _image(
        expected_data["id"],
        product_id=1,
        option_id=11 if service_method == "create_option_image" else None,
        is_cover=service_method == "create_product_image",
    )
    service_call.return_value.image_url = "/uploads/products/test.png"
    service_call.return_value.sort = 3

    form_data = {"sort": "3"}
    if service_method == "create_product_image":
        form_data["is_cover"] = "true"

    response = await client.post(
        path,
        data=form_data,
        files={
            "file": (
                "ignored.png",
                b"\x89PNG\r\n\x1a\nbody\x00\x00\x00\x00IEND\xaeB`\x82",
                "image/png",
            )
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["data"] == expected_data
    assert service_call.await_args.kwargs["image_url"].endswith(
        f"/{'a' * 32}.png"
    )
    assert service_call.await_args.kwargs["sort"] == 3
    assert service_call.await_args.kwargs["operator_id"] == 7
    if service_method == "create_product_image":
        assert service_call.await_args.kwargs["is_cover"] is True
    else:
        assert "is_cover" not in service_call.await_args.kwargs


async def test_option_upload_rejects_is_cover_as_unknown_form_field(
    client: AsyncClient,
    admin_routed_service: Mock,
) -> None:
    response = await client.post(
        "/api/v1/admin/options/11/images",
        data={"is_cover": "true"},
        files={"file": ("image.png", b"not-read", "image/png")},
    )

    assert response.status_code == 422
    error_item = response.json()["data"]["errors"][0]
    assert error_item["location"] == ["body", "is_cover"]
    assert error_item["type"] == "extra_forbidden"
    admin_routed_service.create_option_image.assert_not_awaited()


@pytest.mark.parametrize("value", ["1", "yes", "on", ""])
async def test_product_upload_rejects_ambiguous_cover_flags(
    client: AsyncClient,
    admin_routed_service: Mock,
    value: str,
) -> None:
    response = await client.post(
        "/api/v1/admin/products/1/images",
        data={"is_cover": value},
        files={"file": ("image.png", b"not-read", "image/png")},
    )

    assert response.status_code == 422
    admin_routed_service.create_product_image.assert_not_awaited()


async def test_invalid_uploaded_image_returns_42221_before_service(
    client: AsyncClient,
    admin_routed_service: Mock,
    tmp_path,
) -> None:
    storage = LocalImageStorage(root=tmp_path, base_url="/uploads/products")
    app.dependency_overrides[get_product_image_storage] = lambda: storage

    response = await client.post(
        "/api/v1/admin/products/1/images",
        files={"file": ("fake.png", b"not-an-image", "image/png")},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": 42221,
        "message": "Invalid image file",
        "data": {"reason": "invalid_image_content"},
    }
    admin_routed_service.create_product_image.assert_not_awaited()
    assert not list(tmp_path.iterdir())


async def test_upload_service_failure_removes_stored_file_and_preserves_error(
    client: AsyncClient,
    admin_routed_service: Mock,
    tmp_path,
) -> None:
    from app.common.exceptions import ProductNotFound

    storage = LocalImageStorage(root=tmp_path, base_url="/uploads/products")
    app.dependency_overrides[get_product_image_storage] = lambda: storage
    admin_routed_service.create_product_image.side_effect = ProductNotFound()

    response = await client.post(
        "/api/v1/admin/products/1/images",
        files={
            "file": (
                "image.png",
                b"\x89PNG\r\n\x1a\nbody\x00\x00\x00\x00IEND\xaeB`\x82",
                "image/png",
            )
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == 40401
    assert list(tmp_path.iterdir()) == []


async def test_compensation_failure_does_not_mask_original_service_error(
    client: AsyncClient,
    admin_routed_service: Mock,
    caplog,
) -> None:
    from app.common.exceptions import ProductNotFound

    storage = Mock(spec=LocalImageStorage)
    storage.save.return_value = StoredImage(
        key=f"{'a' * 32}.png",
        url=f"/uploads/products/{'a' * 32}.png",
        media_type="image/png",
        size=20,
    )
    storage.delete.side_effect = OSError("simulated cleanup failure")
    app.dependency_overrides[get_product_image_storage] = lambda: storage
    admin_routed_service.create_product_image.side_effect = ProductNotFound()

    response = await client.post(
        "/api/v1/admin/products/1/images",
        files={"file": ("image.png", b"ignored", "image/png")},
    )

    assert response.status_code == 404
    assert response.json()["code"] == 40401
    storage.delete.assert_called_once_with(f"{'a' * 32}.png")
    assert "Product image compensation delete failed" in caplog.text
    assert f"{'a' * 32}.png" in caplog.text


async def test_image_upload_requires_admin_permission(
    client: AsyncClient,
    auth_user: dict,
    routed_service: Mock,
) -> None:
    response = await client.post(
        "/api/v1/admin/products/1/images",
        headers={"Authorization": f"Bearer {auth_user['token']}"},
        files={"file": ("image.png", b"not-read", "image/png")},
    )

    assert response.status_code == 403
    routed_service.create_product_image.assert_not_awaited()


def test_upload_and_audit_routes_are_registered() -> None:
    route_methods = {
        (f"/api/v1{route.path}", method)
        for route in admin_products_router.routes
        for method in getattr(route, "methods", set())
    }

    assert ("/api/v1/admin/products/{product_id}/images", "POST") in route_methods
    assert ("/api/v1/admin/options/{option_id}/images", "POST") in route_methods
    assert ("/api/v1/admin/products/{product_id}/audit-logs", "GET") in route_methods
