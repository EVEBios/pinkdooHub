"""API 文档响应声明工具。"""

from typing import Any

from app.schemas.common import ErrorResponse, SuccessResponse


def success_responses(
    data_model: Any,
    *status_codes: int,
) -> dict[int, dict[str, Any]]:
    """为一个或多个成功状态生成统一信封的 OpenAPI 声明。"""

    codes = status_codes or (200,)
    return {
        status_code: {"model": SuccessResponse[data_model]}
        for status_code in codes
    }


def error_responses(*status_codes: int) -> dict[int, dict[str, Any]]:
    """生成使用统一错误信封的 OpenAPI 状态声明。"""

    return {
        status_code: {"model": ErrorResponse}
        for status_code in status_codes
    }
