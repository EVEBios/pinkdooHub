"""门店跟进独立于预约和顾客阅读状态。"""
from enum import Enum


class FollowupKind(str, Enum):
    CONTACT = "contact"
    OVERDUE = "overdue"


class FollowupOutcome(str, Enum):
    RETRY = "retry"
    UNREACHABLE = "unreachable"
    CONTACTED = "contacted"
    RESOLVED = "resolved"


FOLLOWUP_COMPLETED = (FollowupOutcome.CONTACTED, FollowupOutcome.RESOLVED)
FOLLOWUP_LABELS = {
    FollowupOutcome.RETRY: "待重试",
    FollowupOutcome.UNREACHABLE: "联系方式不可用",
    FollowupOutcome.CONTACTED: "已联系",
    FollowupOutcome.RESOLVED: "已结束跟进",
}
