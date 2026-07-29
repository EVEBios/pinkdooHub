"""AuditLog Model —— 操作审计日志。"""

from tortoise import fields

from app.models.base import BaseModel


class AuditLog(BaseModel):
    """记录所有关键操作的审计日志。

    action 使用 AuditAction 枚举值（DB 存字符串），确保全项目统一。
    """

    operator_id = fields.BigIntField()
    action = fields.CharField(max_length=50)
    target_type = fields.CharField(max_length=50)
    target_id = fields.BigIntField()
    description = fields.CharField(max_length=256, null=True)
    ip_address = fields.CharField(max_length=45)  # IPv6 max

    class Meta:
        table = "audit_logs"
