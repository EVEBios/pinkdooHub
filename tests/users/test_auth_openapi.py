"""认证接口 OpenAPI 成功信封契约。"""

from typing import Any

from app.main import app


def _success_schema(path: str, method: str, status_code: int = 200) -> dict[str, Any]:
    operation = app.openapi()["paths"][path][method]
    return operation["responses"][str(status_code)]["content"]["application/json"][
        "schema"
    ]


def test_auth_success_responses_are_not_unknown() -> None:
    """登录链路必须向类型生成器公开具体的统一成功信封。"""

    assert _success_schema("/api/v1/auth/login", "post")["$ref"].endswith(
        "/SuccessResponse_TokenOut_"
    )
    assert _success_schema("/api/v1/auth/refresh", "post")["$ref"].endswith(
        "/SuccessResponse_RefreshOut_"
    )
    assert _success_schema("/api/v1/auth/logout", "post")["$ref"].endswith(
        "/SuccessResponse_NoneType_"
    )
    assert _success_schema("/api/v1/users/me", "get")["$ref"].endswith(
        "/SuccessResponse_UserOut_"
    )


def test_login_response_excludes_password() -> None:
    """认证成功契约只能引用公开 UserOut，不能暴露密码字段。"""

    schemas = app.openapi()["components"]["schemas"]
    token_properties = schemas["TokenOut"]["properties"]
    user_ref = token_properties["user"]["$ref"].rsplit("/", maxsplit=1)[-1]

    assert "password" not in schemas[user_ref]["properties"]


def test_user_output_enums_match_serialized_http_values() -> None:
    """OpenAPI 必须描述 HTTP 字符串，而不是数据库中的 IntEnum 数字。"""

    user_properties = app.openapi()["components"]["schemas"]["UserOut"][
        "properties"
    ]

    assert user_properties["role"]["enum"] == ["user", "admin", "super_admin"]
    assert user_properties["status"]["enum"] == ["normal", "disabled", "deleted"]
