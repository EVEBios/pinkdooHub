"""Product 普通 JSON API 的真实 SQLite 端到端测试。"""

from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from pathlib import Path

from app.api.deps import get_current_admin, get_product_image_storage
from app.main import app
from app.models.audit_log import AuditLog
from app.models.product_image import ProductImage
from app.repositories.product_repo import ProductRepository
from app.storage.image import LocalImageStorage


@pytest.fixture
def admin_api() -> None:
    """仅替换认证边界；Product Service/Repository/事务均使用真实实现。"""

    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=71)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def image_upload_api(tmp_path: Path) -> Path:
    """使用真实 Service/Repository 与临时本地图片目录。"""

    upload_root = tmp_path / "products"
    storage = LocalImageStorage(
        root=upload_root,
        base_url="/uploads/products",
    )
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(id=72)
    app.dependency_overrides[get_product_image_storage] = lambda: storage

    static_mount = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/uploads/products"
    )
    static_files = static_mount.app
    previous_directory = static_files.directory
    previous_directories = static_files.all_directories
    previous_checked = static_files.config_checked
    static_files.directory = str(upload_root)
    static_files.all_directories = [str(upload_root)]
    static_files.config_checked = False

    yield upload_root

    app.dependency_overrides.clear()
    static_files.directory = previous_directory
    static_files.all_directories = previous_directories
    static_files.config_checked = previous_checked


async def test_experience_http_lifecycle_uses_real_service_and_mapper(
    client: AsyncClient,
    admin_api: None,
) -> None:
    create_response = await client.post(
        "/api/v1/admin/products/experience",
        json={"name": "API 体验", "description": "真实 HTTP 流程"},
    )
    assert create_response.status_code == 201
    product_id = create_response.json()["data"]["id"]

    admin_draft = await client.get(
        f"/api/v1/admin/products/experience/{product_id}"
    )
    assert admin_draft.status_code == 200
    assert admin_draft.json()["data"]["options"] == []
    assert admin_draft.json()["data"]["images"] == []

    option_response = await client.post(
        f"/api/v1/admin/products/experience/{product_id}/options",
        json={
            "duration_minutes": 90,
            "participants": 2,
            "day_type": "holiday",
            "price": "399.00",
        },
    )
    assert option_response.status_code == 201
    option_id = option_response.json()["data"]["id"]
    assert option_response.json()["data"]["images"] == []

    repository = ProductRepository()
    product = await repository.get_product_by_id(product_id)
    option = await repository.get_option_by_id(option_id)
    assert product is not None
    assert option is not None
    cover = await repository.create_image(
        product=product,
        image_url="https://example.com/api-cover.jpg",
        is_cover=True,
    )
    await repository.create_image(
        product=product,
        experience_option=option,
        image_url="https://example.com/api-option.jpg",
    )

    online_response = await client.patch(
        f"/api/v1/admin/products/{product_id}/online"
    )
    assert online_response.status_code == 200
    assert online_response.json()["data"]["status"]["value"] == "online"

    public_list = await client.get("/api/v1/products?product_type=experience")
    assert public_list.status_code == 200
    assert public_list.json()["data"]["items"] == [
        {
            "id": product_id,
            "name": "API 体验",
            "product_type": {"value": "experience", "label": "拼豆体验"},
            "cover_image": "https://example.com/api-cover.jpg",
            "display_price": "399.00",
        }
    ]

    public_detail = await client.get(
        f"/api/v1/products/experience/{product_id}"
    )
    assert public_detail.status_code == 200
    detail = public_detail.json()["data"]
    assert detail["dimensions"] == {
        "durations": [{"value": 90, "label": "90分钟"}],
        "participants": [{"value": 2, "label": "2人"}],
        "day_types": [{"value": "holiday", "label": "节假日"}],
    }
    assert detail["options"][0]["images"][0]["image_url"] == (
        "https://example.com/api-option.jpg"
    )

    offline_response = await client.patch(
        f"/api/v1/admin/products/{product_id}/offline"
    )
    assert offline_response.status_code == 200

    update_response = await client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"description": None},
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["description"] is None

    option_update = await client.patch(
        f"/api/v1/admin/options/{option_id}",
        json={"price": "499.00"},
    )
    assert option_update.status_code == 200
    assert option_update.json()["data"]["price"] == "499.00"

    image_update = await client.patch(
        f"/api/v1/admin/product-images/{cover.id}",
        json={"sort": 10},
    )
    assert image_update.status_code == 200
    assert image_update.json()["data"]["sort"] == 10

    option_delete = await client.delete(f"/api/v1/admin/options/{option_id}")
    assert option_delete.status_code == 200
    assert option_delete.json()["data"] == {
        "id": option_id,
        "is_deleted": True,
    }

    image_delete = await client.delete(
        f"/api/v1/admin/product-images/{cover.id}"
    )
    assert image_delete.status_code == 200
    assert image_delete.json()["data"]["is_deleted"] is True

    product_delete = await client.delete(
        f"/api/v1/admin/products/{product_id}"
    )
    assert product_delete.status_code == 200
    assert product_delete.json()["data"]["is_deleted"] is True

    actions = await AuditLog.filter(target_id=product_id).values_list(
        "action",
        flat=True,
    )
    assert actions == [
        "CREATE_PRODUCT",
        "CREATE_OPTION",
        "ONLINE_PRODUCT",
        "OFFLINE_PRODUCT",
        "UPDATE_PRODUCT",
        "UPDATE_PRICE",
        "UPDATE_PRODUCT_IMAGE",
        "DELETE_OPTION",
        "DELETE_PRODUCT_IMAGE",
        "DELETE_PRODUCT",
    ]


async def test_kit_http_lifecycle_preserves_product_id_and_availability(
    client: AsyncClient,
    admin_api: None,
) -> None:
    create_response = await client.post(
        "/api/v1/admin/products/kit",
        json={
            "name": "API 套装",
            "description": "真实 Kit HTTP 流程",
            "price": "599.00",
        },
    )
    assert create_response.status_code == 201
    product_id = create_response.json()["data"]["id"]

    price_response = await client.patch(
        f"/api/v1/admin/products/kit/{product_id}/price",
        json={"price": "699.00"},
    )
    stock_response = await client.patch(
        f"/api/v1/admin/products/kit/{product_id}/stock",
        json={"stock": 3},
    )
    assert price_response.status_code == 200
    assert price_response.json()["data"] == {
        "id": product_id,
        "price": "699.00",
    }
    assert stock_response.status_code == 200
    assert stock_response.json()["data"] == {
        "id": product_id,
        "stock": 3,
    }

    repository = ProductRepository()
    product = await repository.get_product_by_id(product_id)
    assert product is not None
    await repository.create_image(
        product=product,
        image_url="https://example.com/kit-cover.jpg",
        is_cover=True,
    )

    online_response = await client.patch(
        f"/api/v1/admin/products/{product_id}/online"
    )
    assert online_response.status_code == 200

    public_detail = await client.get(f"/api/v1/products/kit/{product_id}")
    assert public_detail.status_code == 200
    assert public_detail.json()["data"] == {
        "id": product_id,
        "name": "API 套装",
        "product_type": {"value": "kit", "label": "拼豆套装"},
        "description": "真实 Kit HTTP 流程",
        "images": [
            {
                "id": public_detail.json()["data"]["images"][0]["id"],
                "image_url": "https://example.com/kit-cover.jpg",
                "is_cover": True,
                "sort": 0,
            }
        ],
        "price": "699.00",
        "stock": 3,
        "available": True,
    }


async def test_online_business_validation_returns_product_422_envelope(
    client: AsyncClient,
    admin_api: None,
) -> None:
    create_response = await client.post(
        "/api/v1/admin/products/experience",
        json={"name": "不完整体验"},
    )
    product_id = create_response.json()["data"]["id"]

    response = await client.patch(
        f"/api/v1/admin/products/{product_id}/online"
    )

    assert response.status_code == 422
    assert response.json()["code"] == 42201
    assert response.json()["message"] == "Product is not ready to go online"
    assert response.json()["data"]["issues"] == [
        "product description is required",
        "product cover image is required",
        "at least one product image is required",
        "at least one experience option is required",
    ]


async def test_product_audit_history_supports_deleted_product_and_pagination(
    client: AsyncClient,
    admin_api: None,
) -> None:
    create_response = await client.post(
        "/api/v1/admin/products/experience",
        json={"name": "审计历史商品"},
    )
    product_id = create_response.json()["data"]["id"]
    update_response = await client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"description": "保留操作轨迹"},
    )
    delete_response = await client.delete(
        f"/api/v1/admin/products/{product_id}"
    )
    assert update_response.status_code == 200
    assert delete_response.status_code == 200

    response = await client.get(
        f"/api/v1/admin/products/{product_id}/audit-logs?page=1&page_size=2"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["action"] for item in data["items"]] == [
        "DELETE_PRODUCT",
        "UPDATE_PRODUCT",
    ]
    assert data | {"items": []} == {
        "items": [],
        "total": 3,
        "page": 1,
        "page_size": 2,
        "pages": 2,
    }
    assert all(item["target_id"] == product_id for item in data["items"])


async def test_product_audit_history_returns_40401_for_missing_product(
    client: AsyncClient,
    admin_api: None,
) -> None:
    response = await client.get(
        "/api/v1/admin/products/999999/audit-logs"
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": 40401,
        "message": "Product not found",
        "data": None,
    }


async def test_image_upload_http_flow_persists_ownership_audit_and_static_files(
    client: AsyncClient,
    image_upload_api: Path,
) -> None:
    missing_response = await client.get("/uploads/products/missing.png")
    assert missing_response.status_code == 404

    product_response = await client.post(
        "/api/v1/admin/products/experience",
        json={"name": "上传测试体验", "description": "真实 multipart 流程"},
    )
    assert product_response.status_code == 201
    product_id = product_response.json()["data"]["id"]

    option_response = await client.post(
        f"/api/v1/admin/products/experience/{product_id}/options",
        json={
            "duration_minutes": 60,
            "participants": 1,
            "day_type": "weekday",
            "price": "299.00",
        },
    )
    option_id = option_response.json()["data"]["id"]

    public_content = (
        b"\x89PNG\r\n\x1a\npublic\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    option_content = b"\xff\xd8\xffoption\xff\xd9"
    public_response = await client.post(
        f"/api/v1/admin/products/{product_id}/images",
        data={"is_cover": "true", "sort": "4"},
        files={"file": ("../../unsafe.png", public_content, "image/png")},
    )
    option_image_response = await client.post(
        f"/api/v1/admin/options/{option_id}/images",
        data={"sort": "2"},
        files={"file": ("unsafe.jpg", option_content, "image/jpeg")},
    )

    assert public_response.status_code == 201
    assert option_image_response.status_code == 201
    public_data = public_response.json()["data"]
    option_data = option_image_response.json()["data"]
    assert public_data["is_cover"] is True
    assert public_data["sort"] == 4
    assert option_data == {
        "id": option_data["id"],
        "image_url": option_data["image_url"],
        "sort": 2,
    }
    assert "unsafe" not in public_data["image_url"]
    assert "unsafe" not in option_data["image_url"]

    public_image = await ProductImage.get(id=public_data["id"])
    option_image = await ProductImage.get(id=option_data["id"])
    assert public_image.product_id == product_id
    assert public_image.experience_option_id is None
    assert public_image.image_url == public_data["image_url"]
    assert option_image.product_id == product_id
    assert option_image.experience_option_id == option_id
    assert option_image.is_cover is False

    public_file_response = await client.get(public_data["image_url"])
    option_file_response = await client.get(option_data["image_url"])
    assert public_file_response.status_code == 200
    assert public_file_response.content == public_content
    assert public_file_response.headers["content-type"] == "image/png"
    assert option_file_response.status_code == 200
    assert option_file_response.content == option_content
    assert option_file_response.headers["content-type"] == "image/jpeg"

    stored_names = sorted(path.name for path in image_upload_api.iterdir())
    assert len(stored_names) == 2
    assert all("unsafe" not in name for name in stored_names)

    actions = await AuditLog.filter(target_id=product_id).values_list(
        "action",
        flat=True,
    )
    assert actions == [
        "CREATE_PRODUCT",
        "CREATE_OPTION",
        "CREATE_PRODUCT_IMAGE",
        "CREATE_OPTION_IMAGE",
    ]
