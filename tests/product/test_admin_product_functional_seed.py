from app.common.enums.product import ProductStatus, ProductType
from app.models.audit_log import AuditLog
from app.models.product import Product
from app.models.product_kit import ProductKit
from app.models.user import User
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.services.product_service import ProductService
from app.tasks.admin_product_functional_seed import (
    DELETED_KIT_NAME,
    DRAFT_EXPERIENCE_NAME,
    DRAFT_KIT_NAME,
    SEED_PREFIX,
    seed_admin_product_samples,
)


async def test_admin_product_samples_are_idempotent_and_use_service_contracts():
    operator = await User.create(
        username="admin-product-seed-admin",
        password="test-password-hash",
        nickname="Admin Product Seed Admin",
        phone="13900009952",
    )
    service = ProductService(
        ProductRepository(),
        AuditLogService(AuditLogRepository()),
    )

    first = await seed_admin_product_samples(service, operator_id=operator.id)
    second = await seed_admin_product_samples(service, operator_id=operator.id)

    assert first.created == 3
    assert first.skipped == 0
    assert second.created == 0
    assert second.skipped == 3
    assert second == first.__class__(
        created=0,
        skipped=3,
        draft_experience_id=first.draft_experience_id,
        draft_kit_id=first.draft_kit_id,
        deleted_kit_id=first.deleted_kit_id,
    )

    products = await Product.filter(name__startswith=SEED_PREFIX).order_by("id")
    assert len(products) == 3
    by_name = {product.name: product for product in products}
    draft_experience = by_name[DRAFT_EXPERIENCE_NAME]
    draft_kit = by_name[DRAFT_KIT_NAME]
    deleted_kit = by_name[DELETED_KIT_NAME]
    assert (draft_experience.product_type, draft_experience.status) == (
        ProductType.EXPERIENCE,
        ProductStatus.DRAFT,
    )
    assert draft_experience.description is None
    assert draft_experience.is_deleted is False
    assert draft_kit.product_type == ProductType.KIT
    assert draft_kit.status == ProductStatus.DRAFT
    assert draft_kit.is_deleted is False
    assert deleted_kit.product_type == ProductType.KIT
    assert deleted_kit.status == ProductStatus.DRAFT
    assert deleted_kit.is_deleted is True
    assert await ProductKit.filter(product_id__in=[draft_kit.id, deleted_kit.id]).count() == 2
    assert await AuditLog.filter(target_type="product").count() == 4
