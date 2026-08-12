"""Product Service —— 编排 Product 业务操作。"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.exceptions import (
    ExperienceOptionAlreadyDeleted,
    ExperienceOptionAlreadyExists,
    ExperienceOptionNotFound,
    OptionImageCannotBeCover,
    OnlineProductCannotBeModified,
    ProductAlreadyOffline,
    ProductAlreadyOnline,
    ProductIsDeleted,
    ProductImageNotFound,
    ProductKitNotFound,
    ProductMustBeOfflineBeforeDelete,
    ProductNotFound,
    ProductTypeMismatch,
)
from app.common.pagination import Page
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.repositories.product_repo import ProductRepository
from app.services.audit_log_service import AuditLogService
from app.validators.product_validator import ProductValidator


logger = logging.getLogger(__name__)

_BASIC_PRODUCT_UPDATE_FIELDS = frozenset({"name", "description"})
_OPTION_UPDATE_FIELDS = frozenset(
    {"duration_minutes", "participants", "day_type", "price"},
)
_OPTION_DIMENSION_UPDATE_FIELDS = frozenset(
    {"duration_minutes", "participants", "day_type"},
)


@dataclass(frozen=True, slots=True)
class ExperienceOptionCreationResult:
    """Option POST 的领域结果，供 API 区分新建与恢复状态码。"""

    option: ExperienceOption
    restored: bool


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

    async def update_product(
        self,
        product_id: int,
        *,
        updates: Mapping[str, object],
        operator_id: int,
        ip_address: str,
    ) -> Product:
        """原子修改非 Online Product 的显式基础信息字段并写入审计。"""

        update_fields = dict(updates)
        if (
            not update_fields
            or not update_fields.keys() <= _BASIC_PRODUCT_UPDATE_FIELDS
        ):
            raise ValueError(
                "updates must contain only name or description",
            )

        product = await self.product_repository.get_product_by_id(
            product_id,
            include_deleted=True,
        )
        if product is None:
            raise ProductNotFound()
        if product.is_deleted:
            raise ProductIsDeleted()
        if product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()

        async with in_transaction() as connection:
            updated = await self.product_repository.update_product(
                product,
                using_db=connection,
                **update_fields,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="UPDATE_PRODUCT",
                target_type="product",
                target_id=product.id,
                ip_address=ip_address,
                using_db=connection,
            )

        logger.info(
            "Product updated: operator_id=%d product_id=%d",
            operator_id,
            product.id,
        )
        return updated

    async def delete_product(
        self,
        product_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> Product:
        """原子逻辑删除 Draft/Offline Product 并写入审计。"""

        product = await self.product_repository.get_product_by_id(
            product_id,
            include_deleted=True,
        )
        if product is None:
            raise ProductNotFound()
        if product.is_deleted:
            raise ProductIsDeleted()
        if product.status == ProductStatus.ONLINE:
            raise ProductMustBeOfflineBeforeDelete()

        async with in_transaction() as connection:
            updated = await self.product_repository.update_product(
                product,
                is_deleted=True,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="DELETE_PRODUCT",
                target_type="product",
                target_id=product.id,
                ip_address=ip_address,
                using_db=connection,
            )

        logger.info(
            "Product deleted: operator_id=%d product_id=%d",
            operator_id,
            product.id,
        )
        return updated

    async def create_experience_option(
        self,
        product_id: int,
        *,
        duration_minutes: int,
        participants: int,
        day_type: DayType,
        price: Decimal,
        operator_id: int,
        ip_address: str,
    ) -> ExperienceOptionCreationResult:
        """原子创建新 Option，或恢复相同的已删除历史记录。"""

        product = await self.product_repository.get_product_by_id(
            product_id,
            include_deleted=True,
        )
        if product is None:
            raise ProductNotFound()
        if product.is_deleted:
            raise ProductIsDeleted()
        if product.product_type != ProductType.EXPERIENCE:
            raise ProductTypeMismatch(
                expected=ProductType.EXPERIENCE,
                actual=product.product_type,
            )
        if product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()

        existing = await self.product_repository.get_option_by_combination(
            product_id=product.id,
            duration=duration_minutes,
            participants=participants,
            day_type=day_type,
        )
        if existing is not None and not existing.is_deleted:
            raise ExperienceOptionAlreadyExists(
                duration_minutes=duration_minutes,
                participants=participants,
                day_type=day_type,
            )

        restored = existing is not None
        async with in_transaction() as connection:
            if existing is None:
                try:
                    option = await self.product_repository.create_option(
                        product=product,
                        duration=duration_minutes,
                        participants=participants,
                        day_type=day_type,
                        price=price,
                        using_db=connection,
                    )
                except IntegrityError as exc:
                    raise ExperienceOptionAlreadyExists(
                        duration_minutes=duration_minutes,
                        participants=participants,
                        day_type=day_type,
                    ) from exc
                action = "CREATE_OPTION"
                audit_description = None
            else:
                previous_price = existing.price
                option = await self.product_repository.update_option(
                    existing,
                    price=price,
                    is_deleted=False,
                    using_db=connection,
                )
                action = "RESTORE_OPTION"
                audit_description = json.dumps(
                    {
                        "option_id": option.id,
                        "before": {"price": f"{previous_price:.2f}"},
                        "after": {"price": f"{price:.2f}"},
                    },
                    separators=(",", ":"),
                )

            await self.audit_log_service.log(
                operator_id=operator_id,
                action=action,
                target_type="product",
                target_id=product.id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )

            loaded_option = await self.product_repository.get_option_detail(
                option.id,
                using_db=connection,
            )
            if loaded_option is None:
                raise RuntimeError("Persisted experience option not found")

        logger.info(
            "Experience Option %s: operator_id=%d product_id=%d option_id=%d",
            "restored" if restored else "created",
            operator_id,
            product.id,
            option.id,
        )
        return ExperienceOptionCreationResult(
            option=loaded_option,
            restored=restored,
        )

    async def update_experience_option(
        self,
        option_id: int,
        *,
        updates: Mapping[str, object],
        operator_id: int,
        ip_address: str,
    ) -> ExperienceOption:
        """原子部分更新非 Online Product 的有效 ExperienceOption。"""

        update_fields = dict(updates)
        if (
            not update_fields
            or not update_fields.keys() <= _OPTION_UPDATE_FIELDS
        ):
            raise ValueError(
                "updates must contain only option fields",
            )

        option = await self.product_repository.get_option_by_id(
            option_id,
            include_deleted=True,
        )
        if option is None:
            raise ExperienceOptionNotFound()
        if option.is_deleted:
            raise ExperienceOptionAlreadyDeleted()
        if option.product.is_deleted:
            raise ExperienceOptionNotFound()
        if option.product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()

        final_duration = cast(
            int,
            update_fields["duration_minutes"]
            if "duration_minutes" in update_fields
            else option.duration,
        )
        final_participants = cast(
            int,
            update_fields["participants"]
            if "participants" in update_fields
            else option.participants,
        )
        final_day_type = cast(
            DayType,
            update_fields["day_type"]
            if "day_type" in update_fields
            else option.day_type,
        )
        collision = await self.product_repository.get_option_by_combination(
            product_id=option.product_id,
            duration=final_duration,
            participants=final_participants,
            day_type=final_day_type,
        )
        if collision is not None and collision.id != option.id:
            raise ExperienceOptionAlreadyExists(
                duration_minutes=final_duration,
                participants=final_participants,
                day_type=final_day_type,
            )

        before_dimensions = {
            "duration_minutes": option.duration,
            "participants": option.participants,
            "day_type": option.day_type.value,
        }
        after_dimensions = {
            "duration_minutes": final_duration,
            "participants": final_participants,
            "day_type": final_day_type.value,
        }
        previous_price = option.price
        final_price = cast(
            Decimal,
            update_fields["price"]
            if "price" in update_fields
            else previous_price,
        )
        repository_fields = {
            (
                "duration"
                if field_name == "duration_minutes"
                else field_name
            ): value
            for field_name, value in update_fields.items()
        }

        async with in_transaction() as connection:
            try:
                updated = await self.product_repository.update_option(
                    option,
                    using_db=connection,
                    **repository_fields,
                )
            except IntegrityError as exc:
                raise ExperienceOptionAlreadyExists(
                    duration_minutes=final_duration,
                    participants=final_participants,
                    day_type=final_day_type,
                ) from exc

            if update_fields.keys() & _OPTION_DIMENSION_UPDATE_FIELDS:
                await self.audit_log_service.log(
                    operator_id=operator_id,
                    action="UPDATE_OPTION",
                    target_type="product",
                    target_id=option.product_id,
                    ip_address=ip_address,
                    description=json.dumps(
                        {
                            "option_id": option.id,
                            "before": before_dimensions,
                            "after": after_dimensions,
                        },
                        separators=(",", ":"),
                    ),
                    using_db=connection,
                )
            if "price" in update_fields:
                await self.audit_log_service.log(
                    operator_id=operator_id,
                    action="UPDATE_PRICE",
                    target_type="product",
                    target_id=option.product_id,
                    ip_address=ip_address,
                    description=json.dumps(
                        {
                            "option_id": option.id,
                            "before": {"price": f"{previous_price:.2f}"},
                            "after": {"price": f"{final_price:.2f}"},
                        },
                        separators=(",", ":"),
                    ),
                    using_db=connection,
                )

            loaded_option = await self.product_repository.get_option_detail(
                updated.id,
                using_db=connection,
            )
            if loaded_option is None:
                raise RuntimeError("Updated experience option not found")

        logger.info(
            "Experience Option updated: operator_id=%d product_id=%d "
            "option_id=%d",
            operator_id,
            option.product_id,
            option.id,
        )
        return loaded_option

    async def delete_experience_option(
        self,
        option_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> ExperienceOption:
        """原子逻辑删除非 Online Product 的有效 ExperienceOption。"""

        option = await self.product_repository.get_option_by_id(
            option_id,
            include_deleted=True,
        )
        if option is None:
            raise ExperienceOptionNotFound()
        if option.is_deleted:
            raise ExperienceOptionAlreadyDeleted()
        if option.product.is_deleted:
            raise ExperienceOptionNotFound()
        if option.product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()

        audit_description = json.dumps(
            {
                "option_id": option.id,
                "duration_minutes": option.duration,
                "participants": option.participants,
                "day_type": option.day_type.value,
                "price": f"{option.price:.2f}",
            },
            separators=(",", ":"),
        )
        async with in_transaction() as connection:
            deleted = await self.product_repository.update_option(
                option,
                is_deleted=True,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="DELETE_OPTION",
                target_type="product",
                target_id=option.product_id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )

        logger.info(
            "Experience Option deleted: operator_id=%d product_id=%d "
            "option_id=%d",
            operator_id,
            option.product_id,
            option.id,
        )
        return deleted

    async def update_kit_price(
        self,
        product_id: int,
        *,
        price: Decimal,
        operator_id: int,
        ip_address: str,
    ) -> ProductKit:
        """原子修改非 Online Kit Product 的当前售价。"""

        kit = await self._get_mutable_kit(product_id)
        audit_description = json.dumps(
            {
                "before": {"price": f"{kit.price:.2f}"},
                "after": {"price": f"{price:.2f}"},
            },
            separators=(",", ":"),
        )
        async with in_transaction() as connection:
            updated = await self.product_repository.update_kit(
                kit,
                price=price,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="UPDATE_PRICE",
                target_type="product",
                target_id=product_id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )

        logger.info(
            "Kit price updated: operator_id=%d product_id=%d",
            operator_id,
            product_id,
        )
        return updated

    async def update_kit_stock(
        self,
        product_id: int,
        *,
        stock: int,
        operator_id: int,
        ip_address: str,
    ) -> ProductKit:
        """原子设置非 Online Kit Product 的当前库存最终值。"""

        kit = await self._get_mutable_kit(product_id)
        audit_description = json.dumps(
            {
                "before": {"stock": kit.stock},
                "after": {"stock": stock},
            },
            separators=(",", ":"),
        )
        async with in_transaction() as connection:
            updated = await self.product_repository.update_kit(
                kit,
                stock=stock,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="UPDATE_STOCK",
                target_type="product",
                target_id=product_id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )

        logger.info(
            "Kit stock updated: operator_id=%d product_id=%d",
            operator_id,
            product_id,
        )
        return updated

    async def _get_mutable_kit(self, product_id: int) -> ProductKit:
        """加载可编辑 Kit，并按稳定顺序检查 Product 聚合状态。"""

        product = await self.product_repository.get_product_by_id(
            product_id,
            include_deleted=True,
        )
        if product is None:
            raise ProductNotFound()
        if product.is_deleted:
            raise ProductIsDeleted()
        if product.product_type != ProductType.KIT:
            raise ProductTypeMismatch(
                expected=ProductType.KIT,
                actual=product.product_type,
            )
        if product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()

        kit = await self.product_repository.get_kit_by_product_id(product.id)
        if kit is None:
            raise ProductKitNotFound()
        return kit

    async def create_product_image(
        self,
        product_id: int,
        *,
        image_url: str,
        is_cover: bool,
        sort: int,
        operator_id: int,
        ip_address: str,
    ) -> ProductImage:
        """原子创建非 Online Product 的公共图片并维护封面互斥。"""

        product = await self.product_repository.get_product_by_id(
            product_id,
            include_deleted=True,
        )
        if product is None:
            raise ProductNotFound()
        if product.is_deleted:
            raise ProductIsDeleted()
        if product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()

        async with in_transaction() as connection:
            if is_cover:
                product = await self._lock_mutable_product(
                    product.id,
                    using_db=connection,
                )
                await self.product_repository.clear_product_covers(
                    product.id,
                    using_db=connection,
                )
            image = await self.product_repository.create_image(
                product=product,
                image_url=image_url,
                is_cover=is_cover,
                sort=sort,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="CREATE_PRODUCT_IMAGE",
                target_type="product",
                target_id=product.id,
                ip_address=ip_address,
                description=json.dumps(
                    {"image_id": image.id, "is_cover": is_cover},
                    separators=(",", ":"),
                ),
                using_db=connection,
            )

        logger.info(
            "Product image created: operator_id=%d product_id=%d image_id=%d",
            operator_id,
            product.id,
            image.id,
        )
        return image

    async def create_option_image(
        self,
        option_id: int,
        *,
        image_url: str,
        sort: int,
        operator_id: int,
        ip_address: str,
    ) -> ProductImage:
        """原子创建有效 ExperienceOption 的专属图片。"""

        option = await self.product_repository.get_option_by_id(
            option_id,
            include_deleted=True,
        )
        if option is None:
            raise ExperienceOptionNotFound()
        if option.is_deleted:
            raise ExperienceOptionAlreadyDeleted()
        if option.product.is_deleted:
            raise ExperienceOptionNotFound()
        if option.product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()

        async with in_transaction() as connection:
            image = await self.product_repository.create_image(
                product=option.product,
                experience_option=option,
                image_url=image_url,
                is_cover=False,
                sort=sort,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="CREATE_OPTION_IMAGE",
                target_type="product",
                target_id=option.product_id,
                ip_address=ip_address,
                description=json.dumps(
                    {"image_id": image.id, "option_id": option.id},
                    separators=(",", ":"),
                ),
                using_db=connection,
            )

        logger.info(
            "Option image created: operator_id=%d product_id=%d "
            "option_id=%d image_id=%d",
            operator_id,
            option.product_id,
            option.id,
            image.id,
        )
        return image

    async def update_product_image(
        self,
        image_id: int,
        *,
        updates: Mapping[str, object],
        operator_id: int,
        ip_address: str,
    ) -> ProductImage:
        """原子修改图片排序或将公共图片设为 Product 封面。"""

        update_fields = dict(updates)
        if not update_fields or not update_fields.keys() <= {"sort", "is_cover"}:
            raise ValueError("updates must contain only sort or is_cover")
        if "is_cover" in update_fields and update_fields["is_cover"] is not True:
            raise ValueError("is_cover only accepts true")

        image = await self._get_mutable_image(image_id)
        wants_cover = "is_cover" in update_fields
        if wants_cover and image.experience_option_id is not None:
            raise OptionImageCannotBeCover()

        before = {
            field: getattr(image, field)
            for field in update_fields
        }
        after = dict(update_fields)
        cover_changed = wants_cover and not image.is_cover

        async with in_transaction() as connection:
            old_cover = None
            if wants_cover:
                await self._lock_mutable_product(
                    image.product_id,
                    using_db=connection,
                )
                old_cover = await self.product_repository.get_product_cover(
                    image.product_id,
                    exclude_image_id=image.id,
                    using_db=connection,
                )
                await self.product_repository.clear_product_covers(
                    image.product_id,
                    exclude_image_id=image.id,
                    using_db=connection,
                )
            updated = await self.product_repository.update_image(
                image,
                using_db=connection,
                **update_fields,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="UPDATE_PRODUCT_IMAGE",
                target_type="product",
                target_id=image.product_id,
                ip_address=ip_address,
                description=json.dumps(
                    {
                        "image_id": image.id,
                        "before": before,
                        "after": after,
                    },
                    separators=(",", ":"),
                ),
                using_db=connection,
            )
            if cover_changed:
                await self.audit_log_service.log(
                    operator_id=operator_id,
                    action="SET_PRODUCT_COVER",
                    target_type="product",
                    target_id=image.product_id,
                    ip_address=ip_address,
                    description=json.dumps(
                        {
                            "old_cover_image_id": (
                                old_cover.id if old_cover is not None else None
                            ),
                            "new_cover_image_id": image.id,
                        },
                        separators=(",", ":"),
                    ),
                    using_db=connection,
                )

        logger.info(
            "Product image updated: operator_id=%d product_id=%d image_id=%d",
            operator_id,
            image.product_id,
            image.id,
        )
        return updated

    async def delete_product_image(
        self,
        image_id: int,
        *,
        operator_id: int,
        ip_address: str,
    ) -> ProductImage:
        """原子逻辑删除非 Online Product 的有效图片。"""

        image = await self._get_mutable_image(image_id)
        audit_description = json.dumps(
            {
                "image_id": image.id,
                "product_id": image.product_id,
                "experience_option_id": image.experience_option_id,
                "is_cover": image.is_cover,
                "sort": image.sort,
            },
            separators=(",", ":"),
        )
        async with in_transaction() as connection:
            deleted = await self.product_repository.update_image(
                image,
                is_deleted=True,
                using_db=connection,
            )
            await self.audit_log_service.log(
                operator_id=operator_id,
                action="DELETE_PRODUCT_IMAGE",
                target_type="product",
                target_id=image.product_id,
                ip_address=ip_address,
                description=audit_description,
                using_db=connection,
            )

        logger.info(
            "Product image deleted: operator_id=%d product_id=%d image_id=%d",
            operator_id,
            image.product_id,
            image.id,
        )
        return deleted

    async def _get_mutable_image(self, image_id: int) -> ProductImage:
        """加载可编辑图片，并隐藏已删除图片和已删除所属资源。"""

        image = await self.product_repository.get_image_by_id(
            image_id,
            include_deleted=True,
        )
        if image is None or image.is_deleted or image.product.is_deleted:
            raise ProductImageNotFound()
        if (
            image.experience_option_id is not None
            and image.experience_option.is_deleted
        ):
            raise ProductImageNotFound()
        if image.product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()
        return image

    async def _lock_mutable_product(
        self,
        product_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> Product:
        """锁定并复核 Product，串行化同一聚合的封面切换。"""

        product = await self.product_repository.get_product_for_update(
            product_id,
            using_db=using_db,
        )
        if product is None:
            raise ProductNotFound()
        if product.is_deleted:
            raise ProductIsDeleted()
        if product.status == ProductStatus.ONLINE:
            raise OnlineProductCannotBeModified()
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
