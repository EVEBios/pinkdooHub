"""ProductImage 清理用例的分层边界测试。"""

import ast
from pathlib import Path


def test_cleanup_service_does_not_depend_on_http_or_models() -> None:
    tree = ast.parse(
        Path("app/services/product_image_cleanup_service.py").read_text(
            encoding="utf-8"
        )
    )
    imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]

    assert not any(
        imported.startswith(("fastapi", "app.api", "app.models"))
        for imported in imports
    )
