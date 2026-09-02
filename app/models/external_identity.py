"""外部平台身份绑定。

当前只接入微信小程序，但模型保留 provider/app_id 边界，
避免后续平台复制微信专属表。
"""

from tortoise import fields
from tortoise.indexes import Index

from app.db.indexes import UniqueIndex
from app.models.base import BaseModel


class ExternalIdentity(BaseModel):
    """用户与外部平台主体的绑定。"""

    provider = fields.CharField(max_length=32)
    app_id = fields.CharField(max_length=64)
    # 只保存独立 Pepper 生成的 HMAC-SHA256 十六进制键，不保存原始标识。
    subject_id = fields.CharField(max_length=128)
    union_id = fields.CharField(max_length=128, null=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="external_identities",
        on_delete=fields.RESTRICT,
    )

    class Meta:
        table = "external_identities"
        indexes = [
            UniqueIndex(
                fields=("provider", "app_id", "subject_id"),
                name="uidx_external_identity_subject",
            ),
            UniqueIndex(
                fields=("provider", "union_id"),
                name="uidx_external_identity_union",
            ),
            Index(
                fields=("user_id", "provider", "created_at"),
                name="idx_external_identity_user_provider",
            ),
        ]
