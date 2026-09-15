"""Product 图片存储边界的分层契约。"""

import ast
from pathlib import Path


STORAGE_PATH = Path("app/storage/image.py")
FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "app.api",
    "app.models",
    "app.repositories",
    "app.services",
)


def _tree() -> ast.Module:
    return ast.parse(STORAGE_PATH.read_text(encoding="utf-8"))


def test_storage_adapter_does_not_depend_on_http_or_application_layers() -> None:
    imports: list[str] = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)

    assert not any(
        imported.startswith(prefix)
        for imported in imports
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )


def test_storage_adapter_does_not_trust_a_client_filename() -> None:
    public_methods = {
        child.name: [argument.arg for argument in child.args.args]
        for node in _tree().body
        if isinstance(node, ast.ClassDef) and node.name == "LocalImageStorage"
        for child in node.body
        if isinstance(child, ast.FunctionDef) and not child.name.startswith("_")
    }

    assert "filename" not in public_methods["save"]
