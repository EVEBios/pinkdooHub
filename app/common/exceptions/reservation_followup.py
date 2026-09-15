"""跟进冲突保持明确的可恢复语义。"""
from app.core.exceptions import ConflictException


class FollowupConflict(ConflictException):
    def __init__(self) -> None:
        super().__init__(code=40972, message="跟进记录或预约状态已变化，请刷新核对后再操作")
