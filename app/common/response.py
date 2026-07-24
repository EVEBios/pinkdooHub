"""统一响应信封。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心知识点：为什么需要统一响应格式
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

问题：
  如果每个 API 端点自己决定返回格式——

    GET /users/1    → {"id": 1, "name": "alice"}
    POST /users     → {"status": "ok", "user_id": 2}
    GET /products   → {"data": [...], "total": 100}
    出错时          → {"error": "not found"}

  前端需要为每个接口写不同的解析逻辑，维护成本爆炸。

解决：
  定义唯一的响应信封，全项目所有接口必须一致——

    {"code": 0, "message": "success", "data": ...}

  code=0 表示成功。
  前端只需检查 code 是否为 0，是 → 取 data，否 → 展示 message。

这种模式贯穿项目始终，第一阶段就养成习惯。

使用规则：
  - API 端点：return success(data=...)   ← 唯一正确写法
  - Service 层：raise BusinessException  ← 异常由中间件统一捕获
  - 禁止：手写 {"code": 0, ...}、裸 dict、自定义格式
"""

from typing import Any


def success(data: Any = None, message: str = "success") -> dict:
    """构造成功响应。

    API 层唯一使用的返回方式。无论有无数据，格式完全一致。

    用法：
        return success(data=user)            # 有数据
        return success(data={"items": [...]}) # 列表/分页
        return success()                      # 无数据 → data 为 null
        return success(message="Deleted")     # 自定义消息

    产生的 JSON：
        {"code": 0, "message": "success", "data": {...}}
        {"code": 0, "message": "success", "data": null}
    """
    return {"code": 0, "message": message, "data": data}


def error(code: int, message: str, data: dict | None = None) -> dict:
    """构造错误响应。

    通常由 middleware/exception.py 调用，API 层不直接使用。
    API 层需要报错时抛 BusinessException，中间件自动转为此格式。

    产生的 JSON：
        {"code": 1001, "message": "Username already exists", "data": null}
    """
    return {"code": code, "message": message, "data": data}
