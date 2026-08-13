"""Product 模块字段校验常量。"""

from decimal import Decimal

from app.common.enums.product import DayType, ProductStatus, ProductType

# 商品基本信息
PRODUCT_NAME_MIN_LENGTH = 1
PRODUCT_NAME_MAX_LENGTH = 100
PRODUCT_DESCRIPTION_MAX_LENGTH = 2000
PRODUCT_SEARCH_KEYWORD_MAX_LENGTH = 100
PRODUCT_ENUM_MAX_LENGTH = 20

# 金额（单位：元）
PRODUCT_PRICE_MIN_EXCLUSIVE = Decimal("0.00")
PRODUCT_PRICE_MIN = Decimal("0.01")
PRODUCT_PRICE_MAX = Decimal("99999.00")
PRODUCT_PRICE_DECIMAL_PLACES = 2
PRODUCT_PRICE_PATTERN = r"^\d+(?:\.\d{1,2})?$"

# 体验 Option
MIN_DURATION_MINUTES = 1
MIN_PARTICIPANTS = 1

# 套装库存与图片排序
MIN_STOCK = 0
PRODUCT_IMAGE_URL_MIN_LENGTH = 1
PRODUCT_IMAGE_URL_MAX_LENGTH = 2048
MIN_IMAGE_SORT = 0

# Product 图片上传（与部署环境无关的固定业务边界）
PRODUCT_IMAGE_MAX_BYTES = 2 * 1024 * 1024
PRODUCT_IMAGE_READ_CHUNK_BYTES = 64 * 1024
PRODUCT_IMAGE_MEDIA_TYPE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# API 展示文案
PRODUCT_TYPE_LABELS = {
    ProductType.EXPERIENCE: "拼豆体验",
    ProductType.KIT: "拼豆套装",
}
PRODUCT_STATUS_LABELS = {
    ProductStatus.DRAFT: "草稿",
    ProductStatus.ONLINE: "已上架",
    ProductStatus.OFFLINE: "已下架",
}
DAY_TYPE_LABELS = {
    DayType.WEEKDAY: "工作日",
    DayType.HOLIDAY: "节假日",
}
FULL_DAY_DURATION_MINUTES = 540
FULL_DAY_DURATION_LABEL = "全天"
