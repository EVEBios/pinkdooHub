"""应用存活与就绪探针的公开响应模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class LegacyHealthOut(BaseModel):
    """既有 ``/health`` 兼容响应。"""

    model_config = ConfigDict(extra="forbid")

    app: str
    env: str
    status: Literal["ok"]


class LivenessOut(BaseModel):
    """只表达应用进程可响应，不检查外部依赖。"""

    model_config = ConfigDict(extra="forbid")

    app: str
    status: Literal["alive"]


class DependencyChecksOut(BaseModel):
    """不包含连接目标或凭据的依赖状态。"""

    model_config = ConfigDict(extra="forbid")

    database: Literal["up", "down"]
    redis: Literal["up", "down"]


class ReadinessOut(BaseModel):
    """实例是否具备接收业务流量的条件。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    checks: DependencyChecksOut


class ReadinessErrorResponse(BaseModel):
    """Readiness 失败时的精确 HTTP 503 信封。"""

    model_config = ConfigDict(extra="forbid")

    code: Literal[503] = 503
    message: Literal["Service unavailable"] = "Service unavailable"
    data: ReadinessOut
