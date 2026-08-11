"""Product Repository —— 封装 Product 聚合的数据访问。"""

from decimal import Decimal
from typing import TypeVar

from tortoise import timezone
from tortoise.backends.base.client import BaseDBAsyncClient
from tortoise.expressions import Q
from tortoise.query_utils import Prefetch

from app.common.constants.product import MIN_IMAGE_SORT, MIN_STOCK
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.pagination import Page
from app.models.base import BaseModel
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit


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

    async def get_product_detail(
        self,
        product_id: int,
        *,
        include_deleted: bool = False,
    ) -> Product | None:
        """查询 Product 聚合详情，并批量预加载有效子记录。"""

        option_image_query = ProductImage.filter(is_deleted=False).order_by(
            "sort",
            "id",
        )
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
        public_image_query = ProductImage.filter(
            is_deleted=False,
            experience_option_id=None,
        ).order_by("sort", "id")

        query = (
            Product.filter(id=product_id)
            .select_related("kit")
            .prefetch_related(
                Prefetch("experience_options", option_query),
                Prefetch("images", public_image_query),
            )
        )
        if not include_deleted:
            query = query.filter(is_deleted=False)
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
    ) -> ExperienceOption | None:
        """按主键查询 ExperienceOption，默认排除逻辑删除记录。"""

        query = ExperienceOption.filter(id=option_id).select_related("product")
        if not include_deleted:
            query = query.filter(is_deleted=False)
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
        stock: int = MIN_STOCK,
        using_db: BaseDBAsyncClient | None = None,
    ) -> ProductKit:
        """创建 ProductKit，并加入调用方提供的事务连接。"""

        return await ProductKit.create(
            product=product,
            price=price,
            stock=stock,
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
