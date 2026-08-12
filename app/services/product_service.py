"""Product Service —— 编排 Product 业务操作。"""

import logging

from tortoise.transactions import in_transaction

from app.common.enums.product import ProductStatus
from app.common.exceptions import (
    ProductAlreadyOffline,
    ProductAlreadyOnline,
    ProductIsDeleted,
    ProductNotFound,
)
from app.models.product import Product
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.validators.product_validator import ProductValidator


logger = logging.getLogger(__name__)


class ProductService:
    """Product 业务编排层。"""

    def __init__(
        self,
        product_repository: ProductRepository,
        audit_log_service: AuditLogService,
    ) -> None:
        self.product_repository = product_repository
        self.audit_log_service = audit_log_service

    async def online_product(
        self,
        product_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Product:
        """校验 Product 聚合，并原子完成上架状态更新和审计。"""

        product = await self.product_repository.get_product_detail(
            product_id,
            include_deleted=True,
        )
        if product is None:
            raise ProductNotFound()
        if product.is_deleted:
            raise ProductIsDeleted()
        if product.status == ProductStatus.ONLINE:
            raise ProductAlreadyOnline()

        ProductValidator.validate_before_online(product)

        async with in_transaction() as connection:
            updated = await self.product_repository.update_product(
                product,
                status=ProductStatus.ONLINE,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="ONLINE_PRODUCT",
                target_type="product",
                target_id=product.id,
                ip_address=ip_address,
                using_db=connection,
            )

        logger.info(
            "Product online: operator_id=%d product_id=%d",
            operator_id,
            product.id,
        )
        return updated

    async def offline_product(
        self,
        product_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Product:
        """将 Online Product 原子下架并写入审计。"""

        product = await self.product_repository.get_product_by_id(
            product_id,
            include_deleted=True,
        )
        if product is None:
            raise ProductNotFound()
        if product.is_deleted:
            raise ProductIsDeleted()
        if product.status != ProductStatus.ONLINE:
            raise ProductAlreadyOffline()

        async with in_transaction() as connection:
            updated = await self.product_repository.update_product(
                product,
                status=ProductStatus.OFFLINE,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="OFFLINE_PRODUCT",
                target_type="product",
                target_id=product.id,
                ip_address=ip_address,
                using_db=connection,
            )

        logger.info(
            "Product offline: operator_id=%d product_id=%d",
            operator_id,
            product.id,
        )
        return updated
