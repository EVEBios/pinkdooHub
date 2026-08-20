"""将 FastAPI OpenAPI Schema 导出为前端类型生成输入。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "miniapp" / "openapi" / "openapi.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_openapi_schema() -> dict[str, Any]:
    """在不注册测试数据库的情况下生成当前 FastAPI OpenAPI Schema。"""

    os.environ["TESTING"] = "1"

    from app.main import app

    return app.openapi()


def export_openapi(output_path: Path) -> None:
    """以稳定 UTF-8 JSON 格式原子写入 OpenAPI Schema。"""

    schema = build_openapi_schema()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    logger.info(
        "OpenAPI exported path=%s paths=%d schemas=%d",
        output_path,
        len(schema.get("paths", {})),
        len(schema.get("components", {}).get("schemas", {})),
    )


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"输出文件，默认 {DEFAULT_OUTPUT}",
    )
    return parser.parse_args()


def main() -> None:
    """运行 OpenAPI 导出命令。"""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    export_openapi(args.output.resolve())


if __name__ == "__main__":
    main()
