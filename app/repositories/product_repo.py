"""Product Repository —— 封装 Product 聚合的数据访问。"""

from datetime import datetime
from decimal import Decimal
from typing import TypeVar

from tortoise import timezone
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.query_utils import Prefetch

from app.common.constants.product import (
    BEAD_COLOR_SLOT_COUNT,
    BEAD_COLOR_SLOT_MIN,
    MIN_IMAGE_SORT,
    MIN_STOCK,
)
from app.common.enums.product import DayType, KitKind, ProductStatus, ProductType
from app.common.pagination import Page
from app.models.base import BaseModel
from app.models.bead_color import BeadColor
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.models.product_kit_color import ProductKitColor


ModelT = TypeVar("ModelT", bound=BaseModel)


async def _update_instance(
    instance: ModelT,
    *,
    fields: dict[str, object],
    using_db: BaseDBAsyncClient | None = None,
) -> ModelT:
    """部分更新 Model，并确保自动时间戳包含在指定保存字段中。"""

    if not fields:
        return instance

    instance.update_from_dict(fields)
    update_fields = list(fields)
    if "updated_at" not in fields:
        update_fields.append("updated_at")
    await instance.save(using_db=using_db, update_fields=update_fields)
    return instance


class ProductRepository:
    """Product 数据访问层，不包含状态判断、权限判断或业务异常。"""

    async def create_product(
        self,
        *,
        name: str,
        product_type: ProductType,
        description: str | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Product:
        """创建 Draft Product，并加入调用方提供的事务连接。"""

        return await Product.create(
            name=name,
            product_type=product_type,
            description=description,
            using_db=using_db,
        )

    async def update_product(
        self,
        product: Product,
        *,
        using_db: BaseDBAsyncClient | None = None,
        **fields: object,
    ) -> Product:
        """部分更新 Product，并加入调用方提供的事务连接。"""

        return await _update_instance(
            product,
            fields=fields,
            using_db=using_db,
        )

    async def get_product_by_id(
        self,
        product_id: int,
        *,
        include_deleted: bool = False,
    ) -> Product | None:
        """按主键查询 Product，默认排除逻辑删除记录。"""

        query = Product.filter(id=product_id)
        if not include_deleted:
            query = query.filter(is_deleted=False)
        return await query.first()

    async def get_product_for_update(
        self,
        product_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> Product | None:
        """在调用方事务中锁定 Product 行，用于串行化聚合级写入。"""

        return await (
            Product.filter(id=product_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_products_by_ids(
        self,
        product_ids: set[int],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[Product]:
        """一次查询加载指定 Product，包含逻辑删除记录供 Service 判定。"""

        if not product_ids:
            return []
        query = Product.filter(id__in=product_ids).order_by("id")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query

    async def get_kits_by_product_ids(
        self,
        product_ids: set[int],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[ProductKit]:
        """一次查询加载指定 Product 的 Kit 扩展，供订单候选快照使用。"""

        if not product_ids:
            return []
        query = ProductKit.filter(product_id__in=product_ids).order_by(
            "product_id"
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query

    async def get_product_detail(
        self,
        product_id: int,
        *,
        include_deleted: bool = False,
        using_db: BaseDBAsyncClient | None = None,
    ) -> Product | None:
        """查询 Product 聚合详情，并在指定连接批量预加载有效子记录。"""

        option_image_query = ProductImage.filter(is_deleted=False).order_by(
            "sort",
            "id",
        )
        public_image_query = ProductImage.filter(
            is_deleted=False,
            experience_option_id=None,
        ).order_by("sort", "id")
        kit_color_query = (
            ProductKitColor.all()
            .select_related("bead_color")
            .order_by("bead_color__sort", "bead_color__slot_no", "id")
        )
        if using_db is not None:
            option_image_query = option_image_query.using_db(using_db)
            public_image_query = public_image_query.using_db(using_db)
            kit_color_query = kit_color_query.using_db(using_db)
        option_query = (
            ExperienceOption.filter(is_deleted=False)
            .order_by(
                "duration",
                "participants",
                "day_type",
                "id",
            )
            .prefetch_related(Prefetch("images", option_image_query))
        )
        if using_db is not None:
            option_query = option_query.using_db(using_db)

        query = (
            Product.filter(id=product_id)
            .select_related("kit")
            .prefetch_related(
                Prefetch("experience_options", option_query),
                Prefetch("images", public_image_query),
                Prefetch("kit_colors", kit_color_query),
            )
        )
        if not include_deleted:
            query = query.filter(is_deleted=False)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def list_products(
        self,
        *,
        page: int,
        page_size: int,
        product_type: ProductType | None = None,
        status: ProductStatus | None = None,
        keyword: str | None = None,
        include_deleted: bool = False,
        search_description: bool = False,
    ) -> Page[Product]:
        """分页查询 Product，支持类型、状态、关键字和删除范围筛选。"""

        query = Product.all()
        if not include_deleted:
            query = query.filter(is_deleted=False)
        if product_type is not None:
            query = query.filter(product_type=product_type)
        if status is not None:
            query = query.filter(status=status)
        if keyword is not None:
            keyword_filter = Q(name__icontains=keyword)
            if search_description:
                keyword_filter |= Q(description__icontains=keyword)
            query = query.filter(keyword_filter)

        total = await query.count()
        offset = (page - 1) * page_size
        option_query = ExperienceOption.filter(is_deleted=False).order_by(
            "duration",
            "participants",
            "day_type",
            "id",
        )
        public_image_query = ProductImage.filter(
            is_deleted=False,
            experience_option_id=None,
        ).order_by("sort", "id")
        items = await (
            query.select_related("kit")
            .prefetch_related(
                Prefetch("experience_options", option_query),
                Prefetch("images", public_image_query),
            )
            .order_by("-created_at", "-id")
            .offset(offset)
            .limit(page_size)
        )
        pages = (total + page_size - 1) // page_size

        return Page[Product](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def get_option_by_id(
        self,
        option_id: int,
        *,
        include_deleted: bool = False,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ExperienceOption | None:
        """按主键查询 ExperienceOption，默认排除逻辑删除记录。"""

        query = ExperienceOption.filter(id=option_id).select_related("product")
        if not include_deleted:
            query = query.filter(is_deleted=False)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_option_for_update(
        self,
        option_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> ExperienceOption | None:
        """在调用方事务内锁定 ExperienceOption 行。"""

        return await (
            ExperienceOption.filter(id=option_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def get_options_by_ids(
        self,
        option_ids: set[int],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[ExperienceOption]:
        """一次查询加载指定 Option，包含逻辑删除记录供 Service 判定。"""

        if not option_ids:
            return []
        query = ExperienceOption.filter(id__in=option_ids).order_by("id")
        if using_db is not None:
            query = query.using_db(using_db)
        return await query

    async def get_option_detail(
        self,
        option_id: int,
        *,
        include_deleted: bool = False,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ExperienceOption | None:
        """查询 Option、所属 Product 与有效专属图片。"""

        image_query = ProductImage.filter(is_deleted=False).order_by(
            "sort",
            "id",
        )
        query = (
            ExperienceOption.filter(id=option_id)
            .select_related("product")
            .prefetch_related(Prefetch("images", image_query))
        )
        if not include_deleted:
            query = query.filter(is_deleted=False)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_option_by_combination(
        self,
        *,
        product_id: int,
        duration: int,
        participants: int,
        day_type: DayType,
    ) -> ExperienceOption | None:
        """按 Product 内全历史唯一组合查询 ExperienceOption。"""

        return await ExperienceOption.filter(
            product_id=product_id,
            duration=duration,
            participants=participants,
            day_type=day_type,
        ).first()

    async def create_option(
        self,
        *,
        product: Product,
        duration: int,
        participants: int,
        day_type: DayType,
        price: Decimal,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ExperienceOption:
        """创建 ExperienceOption，并加入调用方提供的事务连接。"""

        return await ExperienceOption.create(
            product=product,
            duration=duration,
            participants=participants,
            day_type=day_type,
            price=price,
            using_db=using_db,
        )

    async def update_option(
        self,
        option: ExperienceOption,
        *,
        using_db: BaseDBAsyncClient | None = None,
        **fields: object,
    ) -> ExperienceOption:
        """部分更新 ExperienceOption，并加入调用方提供的事务连接。"""

        return await _update_instance(
            option,
            fields=fields,
            using_db=using_db,
        )

    async def get_kit_by_product_id(
        self,
        product_id: int,
    ) -> ProductKit | None:
        """按 Product 主键查询一对一 ProductKit 扩展记录。"""

        return await ProductKit.filter(product_id=product_id).first()

    async def create_kit(
        self,
        *,
        product: Product,
        price: Decimal,
        stock: int | None = MIN_STOCK,
        kit_kind: KitKind | None = None,
        sale_unit_grams: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ProductKit:
        """创建 ProductKit，并加入调用方提供的事务连接。"""

        fields: dict[str, object] = {
            "product": product,
            "price": price,
            "stock": stock,
            "sale_unit_grams": sale_unit_grams,
        }
        if kit_kind is not None:
            fields["kit_kind"] = kit_kind
        return await ProductKit.create(
            **fields,
            using_db=using_db,
        )

    async def update_kit(
        self,
        kit: ProductKit,
        *,
        using_db: BaseDBAsyncClient | None = None,
        **fields: object,
    ) -> ProductKit:
        """部分更新 ProductKit，并加入调用方提供的事务连接。"""

        return await _update_instance(
            kit,
            fields=fields,
            using_db=using_db,
        )

    async def ensure_bead_color_slots(
        self,
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[BeadColor]:
        """空目录时幂等建立 1..221 占位槽；已有目录原样返回。"""

        existing = await (
            BeadColor.all().using_db(using_db).order_by("slot_no")
        )
        if not existing:
            placeholders = [
                BeadColor(slot_no=slot_no, sort=slot_no, is_active=False)
                for slot_no in range(
                    BEAD_COLOR_SLOT_MIN,
                    BEAD_COLOR_SLOT_COUNT + 1,
                )
            ]
            await BeadColor.bulk_create(
                placeholders,
                ignore_conflicts=True,
                using_db=using_db,
            )
        return await (
            BeadColor.all()
            .using_db(using_db)
            .order_by("slot_no")
        )

    async def list_bead_colors_for_update(
        self,
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[BeadColor]:
        """按槽位锁定全局颜色目录，供受控批量发布使用。"""

        return await (
            BeadColor.all()
            .using_db(using_db)
            .order_by("slot_no")
            .select_for_update()
        )

    async def list_all_bead_colors(self) -> list[BeadColor]:
        """按槽位只读加载完整颜色目录，供离线发布预检使用。"""

        return await BeadColor.all().order_by("slot_no")

    async def bulk_update_bead_colors(
        self,
        bead_colors: list[BeadColor],
        *,
        using_db: BaseDBAsyncClient,
    ) -> None:
        """在调用方事务中批量保存颜色目录展示字段。"""

        await BeadColor.bulk_update(
            bead_colors,
            fields=(
                "color_code",
                "name",
                "swatch_image_url",
                "sort",
                "is_active",
                "updated_at",
            ),
            using_db=using_db,
        )

    async def has_online_product_with_enabled_colors(
        self,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> bool:
        """判断是否已有销售中的商品启用颜色，不加载业务明细。"""

        query = ProductKitColor.filter(
            is_enabled=True,
            product__status=ProductStatus.ONLINE,
            product__is_deleted=False,
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.exists()

    async def list_bead_colors(
        self,
        *,
        page: int,
        page_size: int,
    ) -> Page[BeadColor]:
        """按运营排序分页读取全局颜色目录。"""

        query = BeadColor.all()
        total = await query.count()
        items = await (
            query.order_by("sort", "slot_no", "id")
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return Page[BeadColor](
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size,
        )

    async def get_bead_color_by_id(
        self,
        bead_color_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> BeadColor | None:
        """按主键查询全局颜色槽。"""

        query = BeadColor.filter(id=bead_color_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def get_bead_color_for_update(
        self,
        bead_color_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> BeadColor | None:
        """在调用方事务中锁定一个全局颜色槽。"""

        return await (
            BeadColor.filter(id=bead_color_id)
            .using_db(using_db)
            .select_for_update()
            .first()
        )

    async def list_product_ids_by_bead_color(
        self,
        bead_color_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[int]:
        """稳定读取引用颜色槽的 Product ID，供调用方建立锁集合。"""

        product_ids = await (
            ProductKitColor.filter(bead_color_id=bead_color_id)
            .using_db(using_db)
            .order_by("product_id")
            .values_list("product_id", flat=True)
        )
        return list(product_ids)

    async def get_products_for_update(
        self,
        product_ids: set[int],
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[Product]:
        """按 Product ID 升序锁定集合，作为跨颜色配置的互斥点。"""

        if not product_ids:
            return []
        return await (
            Product.filter(id__in=product_ids)
            .using_db(using_db)
            .order_by("id")
            .select_for_update()
        )

    async def get_enabled_kit_colors_for_update(
        self,
        bead_color_id: int,
        *,
        using_db: BaseDBAsyncClient,
    ) -> list[ProductKitColor]:
        """在 Product/BeadColor 锁后读取并锁定当前启用的引用行。"""

        return await (
            ProductKitColor.filter(
                bead_color_id=bead_color_id,
                is_enabled=True,
            )
            .using_db(using_db)
            .order_by("product_id", "id")
            .select_for_update()
        )

    async def update_bead_color(
        self,
        bead_color: BeadColor,
        *,
        using_db: BaseDBAsyncClient | None = None,
        **fields: object,
    ) -> BeadColor:
        """部分更新全局颜色定义。"""

        return await _update_instance(
            bead_color,
            fields=fields,
            using_db=using_db,
        )

    async def create_product_kit_colors(
        self,
        *,
        product: Product,
        bead_colors: list[BeadColor],
        using_db: BaseDBAsyncClient,
    ) -> list[ProductKitColor]:
        """一次写入一个自选颜色商品的全量颜色关联。"""

        models = [
            ProductKitColor(
                product_id=product.id,
                bead_color_id=bead_color.id,
                is_enabled=False,
                stock_units=MIN_STOCK,
            )
            for bead_color in bead_colors
        ]
        await ProductKitColor.bulk_create(models, using_db=using_db)
        return models

    async def get_kit_colors_by_ids(
        self,
        kit_color_ids: set[int],
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> list[ProductKitColor]:
        """批量读取商品颜色及全局元数据，供订单候选快照使用。"""

        if not kit_color_ids:
            return []
        query = (
            ProductKitColor.filter(id__in=kit_color_ids)
            .select_related("bead_color")
            .order_by("product_id", "bead_color_id")
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query

    async def get_product_kit_color_by_id(
        self,
        kit_color_id: int,
        *,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ProductKitColor | None:
        """读取商品颜色、所属 Product 与全局颜色定义。"""

        query = ProductKitColor.filter(id=kit_color_id).select_related(
            "product",
            "bead_color",
        )
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def update_product_kit_color(
        self,
        kit_color: ProductKitColor,
        *,
        using_db: BaseDBAsyncClient | None = None,
        **fields: object,
    ) -> ProductKitColor:
        """部分更新商品级颜色配置，不提供库存业务入口。"""

        return await _update_instance(
            kit_color,
            fields=fields,
            using_db=using_db,
        )

    async def get_image_by_id(
        self,
        image_id: int,
        *,
        include_deleted: bool = False,
    ) -> ProductImage | None:
        """按主键查询 ProductImage，默认排除逻辑删除记录。"""

        query = ProductImage.filter(id=image_id).select_related(
            "product",
            "experience_option",
        )
        if not include_deleted:
            query = query.filter(is_deleted=False)
        return await query.first()

    async def list_deleted_images_for_cleanup(
        self,
        *,
        before: datetime,
        after_id: int,
        limit: int,
    ) -> list[ProductImage]:
        """按 ID 扫描达到清理时间的逻辑删除图片。"""

        return await (
            ProductImage.filter(
                is_deleted=True,
                updated_at__lte=before,
                id__gt=after_id,
            )
            .only("id", "image_url", "updated_at")
            .order_by("id")
            .limit(limit)
        )

    async def get_active_image_urls(self, image_urls: set[str]) -> set[str]:
        """批量返回仍被有效 ProductImage 引用的 URL。"""

        if not image_urls:
            return set()
        values = await ProductImage.filter(
            image_url__in=image_urls,
            is_deleted=False,
        ).distinct().values_list("image_url", flat=True)
        return set(values)

    async def create_image(
        self,
        *,
        product: Product,
        image_url: str,
        experience_option: ExperienceOption | None = None,
        is_cover: bool = False,
        sort: int = MIN_IMAGE_SORT,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ProductImage:
        """创建 Product 公共图或 ExperienceOption 专属图。"""

        return await ProductImage.create(
            product=product,
            experience_option=experience_option,
            image_url=image_url,
            is_cover=is_cover,
            sort=sort,
            using_db=using_db,
        )

    async def get_product_cover(
        self,
        product_id: int,
        *,
        exclude_image_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ProductImage | None:
        """查询 Product 当前有效公共封面，供封面切换审计使用。"""

        query = ProductImage.filter(
            product_id=product_id,
            experience_option_id=None,
            is_deleted=False,
            is_cover=True,
        ).order_by("id")
        if exclude_image_id is not None:
            query = query.exclude(id=exclude_image_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.first()

    async def update_image(
        self,
        image: ProductImage,
        *,
        using_db: BaseDBAsyncClient | None = None,
        **fields: object,
    ) -> ProductImage:
        """部分更新 ProductImage，并加入调用方提供的事务连接。"""

        return await _update_instance(
            image,
            fields=fields,
            using_db=using_db,
        )

    async def clear_product_covers(
        self,
        product_id: int,
        *,
        exclude_image_id: int | None = None,
        using_db: BaseDBAsyncClient | None = None,
    ) -> int:
        """批量清除同一 Product 的有效公共旧封面。"""

        query = ProductImage.filter(
            product_id=product_id,
            experience_option_id=None,
            is_deleted=False,
            is_cover=True,
        )
        if exclude_image_id is not None:
            query = query.exclude(id=exclude_image_id)
        if using_db is not None:
            query = query.using_db(using_db)
        return await query.update(
            is_cover=False,
            updated_at=timezone.now(),
        )
