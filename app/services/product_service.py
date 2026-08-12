"""Product Service —— 编排 Product 业务操作。"""

import logging
from decimal import Decimal

from tortoise.transactions import in_transaction

from app.common.enums.product import ProductStatus, ProductType
from app.common.exceptions import (
    ProductAlreadyOffline,
    ProductAlreadyOnline,
    ProductIsDeleted,
    ProductNotFound,
)
from app.common.pagination import Page
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

    async def create_experience_product(
        self,
        *,
        name: str,
        description: str | None,
        operator_id: int,
        ip_address: str,
    ) -> Product:
        """原子创建 Experience Draft Product 并写入审计。"""

        async with in_transaction() as connection:
            product = await self.product_repository.create_product(
                name=name,
                description=description,
                product_type=ProductType.EXPERIENCE,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="CREATE_PRODUCT",
                target_type="product",
                target_id=product.id,
                ip_address=ip_address,
                using_db=connection,
            )

        logger.info(
            "Experience Product created: operator_id=%d product_id=%d",
            operator_id,
            product.id,
        )
        return product

    async def create_kit_product(
        self,
        *,
        name: str,
        description: str | None,
        price: Decimal,
        stock: int,
        operator_id: int,
        ip_address: str,
    ) -> Product:
        """原子创建 Kit Draft 聚合并写入审计。"""

        async with in_transaction() as connection:
            product = await self.product_repository.create_product(
                name=name,
                description=description,
                product_type=ProductType.KIT,
                using_db=connection,
            )
            await self.product_repository.create_kit(
                product=product,
                price=price,
                stock=stock,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="CREATE_PRODUCT",
                target_type="product",
                target_id=product.id,
                ip_address=ip_address,
                using_db=connection,
            )

        logger.info(
            "Kit Product created: operator_id=%d product_id=%d",
            operator_id,
            product.id,
        )
        return product

    async def list_admin_products(
        self,
        *,
        page: int,
        page_size: int,
        product_type: ProductType | None = None,
        status: ProductStatus | None = None,
        keyword: str | None = None,
        include_deleted: bool = False,
    ) -> Page[Product]:
        """查询管理端 Product 列表，保留显式删除范围和筛选条件。"""

        return await self.product_repository.list_products(
            page=page,
            page_size=page_size,
            product_type=product_type,
            status=status,
            keyword=keyword,
            include_deleted=include_deleted,
            search_description=False,
        )

    async def list_online_products(
        self,
        *,
        page: int,
        page_size: int,
        product_type: ProductType | None = None,
        keyword: str | None = None,
    ) -> Page[Product]:
        """查询用户可见的 Online、未删除 Product 列表。"""

        return await self.product_repository.list_products(
            page=page,
            page_size=page_size,
            product_type=product_type,
            status=ProductStatus.ONLINE,
            keyword=keyword,
            include_deleted=False,
            search_description=True,
        )

    async def get_admin_product_detail(
        self,
        product_id: int,
        *,
        product_type: ProductType,
    ) -> Product:
        """查询管理端指定类型详情，包含逻辑删除记录。"""

        product = await self.product_repository.get_product_detail(
            product_id,
            include_deleted=True,
        )
        if product is None or product.product_type != product_type:
            raise ProductNotFound()
        return product

    async def get_online_product_detail(
        self,
        product_id: int,
        *,
        product_type: ProductType,
    ) -> Product:
        """查询用户可见的指定类型 Online Product 详情。"""

        product = await self.product_repository.get_product_detail(
            product_id,
            include_deleted=False,
        )
        if (
            product is None
            or product.is_deleted
            or product.status != ProductStatus.ONLINE
            or product.product_type != product_type
        ):
            raise ProductNotFound()
        return product

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
