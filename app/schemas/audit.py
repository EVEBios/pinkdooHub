"""Audit Log 共享请求/响应 Schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.common.pagination import PageParams


class AuditLogListQuery(PageParams):
    """审计日志分页查询参数。"""

    model_config = ConfigDict(extra="forbid")


class AuditLogOut(BaseModel):
    """审计日志公开字段白名单。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    operator_id: int
    action: str
    target_type: str
    target_id: int
    description: str | None
    ip_address: str
    created_at: datetime
