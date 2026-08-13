"""Audit Log API 响应映射。"""

from app.common.pagination import Page
from app.models.audit_log import AuditLog
from app.schemas.audit import AuditLogOut


def map_audit_log_page(page: Page[AuditLog]) -> Page[AuditLogOut]:
    """按共享白名单映射审计分页结果并保留分页元数据。"""

    return Page[AuditLogOut](
        items=[AuditLogOut.model_validate(item) for item in page.items],
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
    )
