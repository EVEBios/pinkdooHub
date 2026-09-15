"""站内提醒的权限隐藏错误。"""

from app.core.exceptions import NotFoundException


class AttentionNotFound(NotFoundException):
    def __init__(self) -> None:
        super().__init__(code=40471, message="Attention event not found")
