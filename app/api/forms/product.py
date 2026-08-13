"""Product multipart 图片上传表单契约。"""

from fastapi import UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.constants.product import MIN_IMAGE_SORT


class _ImageUploadForm(BaseModel):
    """multipart 图片表单公共契约，拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid")

    file: UploadFile = Field(description="jpg/png/webp image, maximum 2 MiB")
    sort: int = Field(default=MIN_IMAGE_SORT, ge=MIN_IMAGE_SORT)


class ProductImageUploadForm(_ImageUploadForm):
    """Product 公共图片上传表单。"""

    is_cover: bool = False

    @field_validator("is_cover", mode="before")
    @classmethod
    def parse_cover_flag(cls, value: object) -> bool:
        """表单布尔值只允许 true/false，拒绝 1/yes 等宽松表示。"""

        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "true":
                return True
            if normalized == "false":
                return False
        raise ValueError("is_cover must be true or false")


class OptionImageUploadForm(_ImageUploadForm):
    """Option 专属图片上传表单，不接收 is_cover。"""
