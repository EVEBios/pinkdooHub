"""Product ORM 聚合到 API Out Schema 的同步纯映射。"""

from typing import TypeVar

from app.common.constants.product import (
    DAY_TYPE_LABELS,
    FULL_DAY_DURATION_LABEL,
    FULL_DAY_DURATION_MINUTES,
    MIN_STOCK,
    PRODUCT_STATUS_LABELS,
    PRODUCT_TYPE_LABELS,
)
from app.common.enums.product import DayType, ProductStatus, ProductType
from app.common.pagination import Page
from app.models.experience_option import ExperienceOption
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_kit import ProductKit
from app.schemas.product_response import (
    AdminExperienceProductDetailOut,
    AdminKitProductDetailOut,
    AdminProductListItemOut,
    DeletedResourceOut,
    ExperienceDimensionsOut,
    ExperienceOptionBaseOut,
    ExperienceOptionOut,
    ExperienceProductCreateOut,
    ExperienceProductDetailOut,
    KitPriceOut,
    KitProductCreateOut,
    KitProductDetailOut,
    KitStockOut,
    LabeledValue,
    OptionImageOut,
    ProductBasicInfoOut,
    ProductImageOut,
    ProductListItemOut,
    ProductOfflineOut,
    ProductOnlineOut,
)


EnumValueT = TypeVar("EnumValueT", ProductType, ProductStatus, DayType)
DeletedModel = Product | ExperienceOption | ProductImage


def _enum_labeled_value(
    value: EnumValueT,
    labels: dict[EnumValueT, str],
) -> LabeledValue[EnumValueT]:
    """使用权威常量构造固定枚举展示值。"""

    return LabeledValue[EnumValueT].model_validate(
        {"value": value, "label": labels[value]}
    )


def map_product_type(value: ProductType) -> LabeledValue[ProductType]:
    """映射商品类型展示值。"""

    normalized = ProductType(value)
    return _enum_labeled_value(normalized, PRODUCT_TYPE_LABELS)


def map_product_status(value: ProductStatus) -> LabeledValue[ProductStatus]:
    """映射商品状态展示值。"""

    normalized = ProductStatus(value)
    return _enum_labeled_value(normalized, PRODUCT_STATUS_LABELS)


def map_day_type(value: DayType) -> LabeledValue[DayType]:
    """映射体验日期类型展示值。"""

    normalized = DayType(value)
    return _enum_labeled_value(normalized, DAY_TYPE_LABELS)


def map_duration(value: int) -> LabeledValue[int]:
    """将开放的分钟数转换为稳定展示值。"""

    if value == FULL_DAY_DURATION_MINUTES:
        label = FULL_DAY_DURATION_LABEL
    elif value % 60 == 0:
        label = f"{value // 60}小时"
    else:
        label = f"{value}分钟"
    return LabeledValue[int].model_validate({"value": value, "label": label})


def map_participants(value: int) -> LabeledValue[int]:
    """将开放的参与人数转换为稳定展示值。"""

    return LabeledValue[int].model_validate(
        {"value": value, "label": f"{value}人"}
    )


def map_product_image(image: ProductImage) -> ProductImageOut:
    """映射 Product 公共图片，不输出内部关联与删除字段。"""

    if image.experience_option_id is not None:
        raise ValueError("Expected a product public image")
    if image.is_deleted:
        raise ValueError("Cannot map a deleted product image")
    return ProductImageOut.model_validate(
        {
            "id": image.id,
            "image_url": image.image_url,
            "is_cover": image.is_cover,
            "sort": image.sort,
        }
    )


def map_option_image(image: ProductImage) -> OptionImageOut:
    """映射 Option 专属图片，不输出 is_cover 与内部关联字段。"""

    if image.experience_option_id is None:
        raise ValueError("Expected an option image")
    if image.is_deleted:
        raise ValueError("Cannot map a deleted option image")
    return OptionImageOut.model_validate(
        {
            "id": image.id,
            "image_url": image.image_url,
            "sort": image.sort,
        }
    )


def map_product_image_by_owner(
    image: ProductImage,
) -> ProductImageOut | OptionImageOut:
    """按图片归属选择公共图或 Option 图响应。"""

    if image.experience_option_id is None:
        return map_product_image(image)
    return map_option_image(image)


def _option_base_payload(option: ExperienceOption) -> dict[str, object]:
    """构造 Option 基础字段白名单。"""

    return {
        "id": option.id,
        "duration": map_duration(option.duration),
        "participants": map_participants(option.participants),
        "day_type": map_day_type(option.day_type),
        "price": option.price,
    }


def _option_images(option: ExperienceOption) -> list[OptionImageOut]:
    """消费已预加载且已排序的 Option 图片。"""

    images: list[OptionImageOut] = []
    for image in option.images:
        if image.experience_option_id != option.id:
            raise ValueError("Option image belongs to a different option")
        images.append(map_option_image(image))
    return images


def map_experience_option_base(
    option: ExperienceOption,
) -> ExperienceOptionBaseOut:
    """映射不包含图片的 Option mutation 响应。"""

    if option.is_deleted:
        raise ValueError("Cannot map a deleted experience option")
    return ExperienceOptionBaseOut.model_validate(_option_base_payload(option))


def map_experience_option(option: ExperienceOption) -> ExperienceOptionOut:
    """映射包含已预加载图片的完整 Option 响应。"""

    if option.is_deleted:
        raise ValueError("Cannot map a deleted experience option")
    payload = _option_base_payload(option)
    payload["images"] = _option_images(option)
    return ExperienceOptionOut.model_validate(payload)


def map_experience_dimensions(
    options: list[ExperienceOption],
) -> ExperienceDimensionsOut:
    """从有效 Option 派生去重且稳定排序的选择维度。"""

    if any(option.is_deleted for option in options):
        raise ValueError("Cannot derive dimensions from a deleted option")
    durations = sorted({option.duration for option in options})
    participants = sorted({option.participants for option in options})
    present_day_types = {DayType(option.day_type) for option in options}
    day_types = [value for value in DayType if value in present_day_types]
    return ExperienceDimensionsOut.model_validate(
        {
            "durations": [map_duration(value) for value in durations],
            "participants": [map_participants(value) for value in participants],
            "day_types": [map_day_type(value) for value in day_types],
        }
    )


def _product_identity_payload(product: Product) -> dict[str, object]:
    """构造 Product 公共身份字段白名单。"""

    return {
        "id": product.id,
        "name": product.name,
        "product_type": map_product_type(product.product_type),
    }


def _public_images(product: Product) -> list[ProductImageOut]:
    """消费已预加载且已排序的 Product 公共图片。"""

    images: list[ProductImageOut] = []
    for image in product.images:
        if image.product_id != product.id:
            raise ValueError("Product image belongs to a different product")
        images.append(map_product_image(image))
    return images


def _cover_image(product: Product, *, required: bool) -> str | None:
    """从已预加载公共图片中选择唯一封面。"""

    for image in product.images:
        if image.product_id != product.id:
            raise ValueError("Product image belongs to a different product")
        if image.is_deleted:
            raise ValueError("Product aggregate contains a deleted image")
        if image.experience_option_id is not None:
            raise ValueError("Product aggregate contains an option image")
    covers = [image for image in product.images if image.is_cover]
    if len(covers) > 1:
        raise ValueError("Product aggregate contains multiple cover images")
    if not covers:
        if required:
            raise ValueError("Online product aggregate has no cover image")
        return None
    return covers[0].image_url


def _kit(product: Product) -> ProductKit:
    """读取已通过 select_related 加载的 Kit 扩展。"""

    kit = product.kit
    if kit is None:
        raise ValueError("Kit product aggregate has no kit extension")
    return kit


def _require_product_type(product: Product, expected: ProductType) -> None:
    """阻止类型不匹配的聚合进入专用响应。"""

    if ProductType(product.product_type) is not expected:
        raise ValueError(f"Expected {expected.value} product aggregate")


def _require_online_product(product: Product) -> None:
    """用户端 Mapper 只接受 Online 且未删除聚合。"""

    if ProductStatus(product.status) is not ProductStatus.ONLINE:
        raise ValueError("User mapper requires an online product")
    if product.is_deleted:
        raise ValueError("User mapper cannot expose a deleted product")


def _validate_product_options(
    product: Product,
    options: list[ExperienceOption],
) -> None:
    """确认预加载 Option 的归属和有效状态。"""

    for option in options:
        if option.product_id != product.id:
            raise ValueError("Experience option belongs to a different product")
        if option.is_deleted:
            raise ValueError("Product aggregate contains a deleted option")


def _display_price(product: Product, *, required: bool):
    """从已预加载类型扩展计算列表展示价。"""

    product_type = ProductType(product.product_type)
    if product_type is ProductType.KIT:
        kit = product.kit
        if kit is None:
            if required:
                raise ValueError("Kit product aggregate has no kit extension")
            return None
        return kit.price

    options = list(product.experience_options)
    for option in options:
        if option.product_id != product.id:
            raise ValueError("Experience option belongs to a different product")
        if option.is_deleted:
            raise ValueError("Product aggregate contains a deleted option")
    if not options:
        if required:
            raise ValueError("Online experience aggregate has no option")
        return None
    return min(option.price for option in options)


def map_product_list_item(product: Product) -> ProductListItemOut:
    """映射完整 Online 商品的用户端列表项。"""

    _require_online_product(product)
    payload = _product_identity_payload(product)
    payload.update(
        {
            "cover_image": _cover_image(product, required=True),
            "display_price": _display_price(product, required=True),
        }
    )
    return ProductListItemOut.model_validate(payload)


def map_admin_product_list_item(product: Product) -> AdminProductListItemOut:
    """映射允许不完整 Draft 聚合的管理端列表项。"""

    payload = _product_identity_payload(product)
    payload.update(
        {
            "status": map_product_status(product.status),
            "cover_image": _cover_image(product, required=False),
            "display_price": _display_price(product, required=False),
            "updated_at": product.updated_at,
            "is_deleted": product.is_deleted,
        }
    )
    return AdminProductListItemOut.model_validate(payload)


def map_product_page(page: Page[Product]) -> Page[ProductListItemOut]:
    """保留分页元数据并映射用户端列表项。"""

    return Page[ProductListItemOut](
        items=[map_product_list_item(product) for product in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def map_admin_product_page(
    page: Page[Product],
) -> Page[AdminProductListItemOut]:
    """保留分页元数据并映射管理端列表项。"""

    return Page[AdminProductListItemOut](
        items=[map_admin_product_list_item(product) for product in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )


def _user_detail_payload(product: Product) -> dict[str, object]:
    """构造用户端 Product 详情公共字段。"""

    _require_online_product(product)
    _cover_image(product, required=True)
    payload = _product_identity_payload(product)
    payload.update(
        {
            "description": product.description,
            "images": _public_images(product),
        }
    )
    return payload


def _admin_detail_payload(product: Product) -> dict[str, object]:
    """构造管理端 Product 详情公共字段。"""

    payload = _product_identity_payload(product)
    payload.update(
        {
            "description": product.description,
            "status": map_product_status(product.status),
            "images": _public_images(product),
            "created_at": product.created_at,
            "updated_at": product.updated_at,
            "is_deleted": product.is_deleted,
        }
    )
    return payload


def map_experience_product_detail(
    product: Product,
) -> ExperienceProductDetailOut:
    """映射用户端完整 Online Experience 详情。"""

    _require_product_type(product, ProductType.EXPERIENCE)
    options = list(product.experience_options)
    _validate_product_options(product, options)
    payload = _user_detail_payload(product)
    payload.update(
        {
            "dimensions": map_experience_dimensions(options),
            "options": [map_experience_option(option) for option in options],
        }
    )
    return ExperienceProductDetailOut.model_validate(payload)


def map_admin_experience_product_detail(
    product: Product,
) -> AdminExperienceProductDetailOut:
    """映射允许空聚合的管理端 Experience 详情。"""

    _require_product_type(product, ProductType.EXPERIENCE)
    options = list(product.experience_options)
    _validate_product_options(product, options)
    payload = _admin_detail_payload(product)
    payload.update(
        {
            "dimensions": map_experience_dimensions(options),
            "options": [map_experience_option(option) for option in options],
        }
    )
    return AdminExperienceProductDetailOut.model_validate(payload)


def map_kit_product_detail(product: Product) -> KitProductDetailOut:
    """映射用户端完整 Online Kit 详情。"""

    _require_product_type(product, ProductType.KIT)
    kit = _kit(product)
    payload = _user_detail_payload(product)
    payload.update(
        {
            "price": kit.price,
            "stock": kit.stock,
            "available": kit.stock > MIN_STOCK,
        }
    )
    return KitProductDetailOut.model_validate(payload)


def map_admin_kit_product_detail(product: Product) -> AdminKitProductDetailOut:
    """映射管理端 Kit 详情。"""

    _require_product_type(product, ProductType.KIT)
    kit = _kit(product)
    payload = _admin_detail_payload(product)
    payload.update({"price": kit.price, "stock": kit.stock})
    return AdminKitProductDetailOut.model_validate(payload)


def map_experience_product_create(
    product: Product,
) -> ExperienceProductCreateOut:
    """映射 Experience 草稿创建响应。"""

    _require_product_type(product, ProductType.EXPERIENCE)
    payload = _product_identity_payload(product)
    payload["status"] = map_product_status(product.status)
    return ExperienceProductCreateOut.model_validate(payload)


def map_kit_product_create(product: Product) -> KitProductCreateOut:
    """映射 Kit 草稿创建响应。"""

    _require_product_type(product, ProductType.KIT)
    payload = _product_identity_payload(product)
    payload["status"] = map_product_status(product.status)
    return KitProductCreateOut.model_validate(payload)


def map_product_basic_info(product: Product) -> ProductBasicInfoOut:
    """映射 Product 基础信息修改响应。"""

    return ProductBasicInfoOut.model_validate(
        {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "updated_at": product.updated_at,
        }
    )


def map_product_online(product: Product) -> ProductOnlineOut:
    """映射 Product 上架响应。"""

    return ProductOnlineOut.model_validate(
        {"id": product.id, "status": map_product_status(product.status)}
    )


def map_product_offline(product: Product) -> ProductOfflineOut:
    """映射 Product 下架响应。"""

    return ProductOfflineOut.model_validate(
        {"id": product.id, "status": map_product_status(product.status)}
    )


def map_deleted_resource(resource: DeletedModel) -> DeletedResourceOut:
    """映射 Product、Option 或 Image 的逻辑删除响应。"""

    return DeletedResourceOut.model_validate(
        {"id": resource.id, "is_deleted": resource.is_deleted}
    )


def map_kit_price(kit: ProductKit) -> KitPriceOut:
    """映射 Kit 价格修改响应，响应 ID 使用 Product ID。"""

    return KitPriceOut.model_validate(
        {"id": kit.product_id, "price": kit.price}
    )


def map_kit_stock(kit: ProductKit) -> KitStockOut:
    """映射 Kit 库存修改响应，响应 ID 使用 Product ID。"""

    return KitStockOut.model_validate(
        {"id": kit.product_id, "stock": kit.stock}
    )
