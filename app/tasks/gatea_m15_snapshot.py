"""M9→M15 的只读内容与结构快照；不输出原始业务行或凭据。

跨版本比较固定 M9 列投影，同版本备份/恢复另比较全部列。每张表按主键分批
读取，整个过程使用同一 MySQL 只读一致性事务，不在 Python 中累计业务行。
"""
from __future__ import annotations

import argparse
import base64
import ast
import asyncio
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import zlib

MIGRATION_SOURCE = Path(__file__).resolve().parents[2] / "migrations/models"
_STEP_SOURCE = Path(__file__).with_name("gatea_migrate_step.py")
# 宿主发布器也要验证快照；仅解释常量，不导入 ORM/驱动或执行候选迁移。
APPROVED_MIGRATIONS = next(ast.literal_eval(node.value) for node in ast.parse(_STEP_SOURCE.read_text()).body
    if isinstance(node, ast.Assign) and len(node.targets) == 1
    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "APPROVED_MIGRATIONS")

SCHEMA_MANIFEST = Path(__file__).parent / "manifests/gatea_m9_m15_schema.json"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
NEW_TABLES = {
    12: ("attention_events",),
    14: ("reservation_followups",),
    15: ("store_bead_stocks", "store_bead_stock_batches", "store_bead_stock_entries"),
}
SCHEMA_QUERIES = {
    "columns": """SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE,
        IS_NULLABLE, COLUMN_DEFAULT, EXTRA, CHARACTER_SET_NAME, COLLATION_NAME
        FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()
        ORDER BY TABLE_NAME, ORDINAL_POSITION""",
    "indexes": """SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX,
        COLUMN_NAME, SUB_PART, INDEX_TYPE FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX""",
    "foreign_keys": """SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, k.COLUMN_NAME,
        k.ORDINAL_POSITION, k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME,
        r.UPDATE_RULE, r.DELETE_RULE FROM information_schema.KEY_COLUMN_USAGE k
        JOIN information_schema.REFERENTIAL_CONSTRAINTS r
        ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.TABLE_NAME=k.TABLE_NAME
        AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME WHERE k.CONSTRAINT_SCHEMA=DATABASE()
        ORDER BY k.TABLE_NAME,k.CONSTRAINT_NAME,k.ORDINAL_POSITION""",
}


class M15SnapshotError(ValueError):
    """只包含规则名称，不回显 SQL、业务值或连接信息。"""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def quote(name: str) -> str:
    if not isinstance(name, str) or IDENTIFIER.fullmatch(name) is None:
        raise M15SnapshotError("invalid database identifier")
    return f"`{name}`"


def model_columns(version: int) -> dict[str, list[str]]:
    """M10 只放宽 NULL，其列集合与 M9 相同；读取常量而不执行迁移。"""
    if type(version) is not int or not 9 <= version <= 15:
        raise M15SnapshotError("unsupported snapshot version")
    path = MIGRATION_SOURCE / APPROVED_MIGRATIONS[max(version, 10)]
    tree = ast.parse(path.read_text())
    states = [ast.literal_eval(node.value) for node in tree.body
              if isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id == "MODELS_STATE"]
    if len(states) != 1:
        raise M15SnapshotError("migration model snapshot is unavailable")
    result = {}
    for model in json.loads(zlib.decompress(base64.b64decode(states[0]))).values():
        table = model["table"]
        if table == "aerich":
            continue  # Aerich 内容/版本随迁移改变，版本链另行精确核验。
        fields = [model["pk_field"], *model["data_fields"]]
        names = sorted(field["db_column"] for field in fields)
        if model["pk_field"]["db_column"] != "id" or len(names) != len(set(names)):
            raise M15SnapshotError("unsupported model primary key or duplicate column")
        quote(table)
        for name in names:
            quote(name)
        result[table] = names
    return dict(sorted(result.items()))


def schema_manifest() -> dict[str, Any]:
    data = json.loads(SCHEMA_MANIFEST.read_text())
    if data.get("schema_version") != 1 or set(data.get("migration_sha256", {})) != set(APPROVED_MIGRATIONS):
        raise M15SnapshotError("schema manifest migration inventory differs")
    for name, digest in data["migration_sha256"].items():
        if hashlib.sha256((MIGRATION_SOURCE / name).read_bytes()).hexdigest() != digest:
            raise M15SnapshotError("schema manifest requires a fresh isolated migration verification")
    return data


def validate_snapshot(value: dict[str, Any], version: int) -> None:
    keys = {"schema_version", "profile", "version", "aerich_versions", "structure_sha256",
            "m9_preserved", "complete_content", "new_session_fields_nondefault",
            "secret_values_recorded", "raw_rows_recorded"}
    if (set(value) != keys or value.get("schema_version") != 1
            or value.get("profile") != "gatea-m9-m15-state-v1" or type(value.get("version")) is not int
            or value["version"] != version
            or value.get("aerich_versions") != list(APPROVED_MIGRATIONS[:version + 1])
            or value.get("structure_sha256") != schema_manifest()["versions"][str(version)]["structure_sha256"]
            or value.get("secret_values_recorded") is not False
            or value.get("raw_rows_recorded") is not False
            or type(value.get("new_session_fields_nondefault")) is not int
            or value["new_session_fields_nondefault"] < 0):
        raise M15SnapshotError("snapshot contract or schema differs")
    for key, expected in [("m9_preserved", model_columns(9)), ("complete_content", {**model_columns(version), "aerich": ["app", "content", "id", "version"]})]:
        tables = value.get(key)
        if not isinstance(tables, dict) or set(tables) != set(expected):
            raise M15SnapshotError("snapshot table inventory differs")
        for item in tables.values():
            if (not isinstance(item, dict) or set(item) != {"rows", "sha256"}
                    or type(item["rows"]) is not int or item["rows"] < 0
                    or not isinstance(item["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
                raise M15SnapshotError("snapshot table content profile differs")


async def _rows(connection: Any, sql: str) -> list[dict[str, Any]]:
    import asyncmy
    async with connection.cursor(asyncmy.cursors.DictCursor) as cursor:
        await cursor.execute(sql)
        return list(await cursor.fetchall())


async def _table_content(connection: Any, table: str, columns: list[str]) -> dict[str, Any]:
    import asyncmy
    # HEX 保留 NULL/空串、精确 Decimal、二进制字符串等差异，无歧义 JSON 分隔。
    expressions = ",".join(f"HEX(CAST({quote(c)} AS BINARY))" for c in columns)
    digest = hashlib.sha256(canonical({"table": table, "columns": columns}) + b"\n")
    count = 0
    async with connection.cursor(asyncmy.cursors.SSCursor) as cursor:
        await cursor.execute(f"SELECT {expressions} FROM {quote(table)} ORDER BY `id`")
        while rows := await cursor.fetchmany(256):
            for row in rows:
                digest.update(canonical(list(row)) + b"\n")
                count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


async def capture(connection: Any, version: int) -> dict[str, Any]:
    """调用方须持有停写窗口；只读事务额外保证表间一致性。"""
    expected = model_columns(version)
    manifest = schema_manifest()
    server = await _rows(connection, "SELECT VERSION() AS version")
    if server != [{"version": manifest["mysql_version"]}]:
        raise M15SnapshotError("snapshot requires the verified MySQL version")
    legacy = model_columns(9)
    async with connection.cursor() as cursor:
        await cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        await cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
    try:
        versions = [row["version"] for row in await _rows(connection,
            "SELECT version FROM aerich WHERE app='models' ORDER BY id")]
        if versions != list(APPROVED_MIGRATIONS[:version + 1]):
            raise M15SnapshotError("database migration chain differs")
        schema = {name: await _rows(connection, sql) for name, sql in SCHEMA_QUERIES.items()}
        actual: dict[str, list[str]] = {}
        for row in schema["columns"]:
            if row["TABLE_NAME"] != "aerich":
                actual.setdefault(row["TABLE_NAME"], []).append(row["COLUMN_NAME"])
        if {t: sorted(cols) for t, cols in actual.items()} != expected:
            raise M15SnapshotError("database columns differ from approved version")
        preserved = {t: await _table_content(connection, t, cols) for t, cols in legacy.items()}
        complete = {t: (preserved[t] if legacy.get(t) == cols else
                       await _table_content(connection, t, cols)) for t, cols in {**expected, "aerich": ["app", "content", "id", "version"]}.items()}
        added_defaults_invalid = 0
        if version >= 11:
            rows = await _rows(connection, """SELECT COUNT(*) AS total FROM table_sessions
                WHERE source <> 'order' OR opened_by_user_id IS NOT NULL
                OR source_option_id IS NOT NULL OR direct_duration_minutes IS NOT NULL
                OR opening_note IS NOT NULL""")
            added_defaults_invalid = rows[0]["total"]
        result = {"schema_version": 1, "profile": "gatea-m9-m15-state-v1", "version": version,
                "aerich_versions": versions,
                "structure_sha256": hashlib.sha256(canonical(schema)).hexdigest(),
                "m9_preserved": preserved, "complete_content": complete,
                "new_session_fields_nondefault": added_defaults_invalid,
                "secret_values_recorded": False, "raw_rows_recorded": False}
        validate_snapshot(result, version)
        return result
    finally:
        await connection.rollback()


def require_preserved(before: dict[str, Any], after: dict[str, Any], *, target: int) -> None:
    """迁移窗口内不允许新业务写入；新增表必须为空，旧字段必须完全保留。"""
    validate_snapshot(before, 9)
    validate_snapshot(after, target)
    if (before.get("version") != 9 or after.get("version") != target
            or not 10 <= target <= 15
            or before.get("m9_preserved") != after.get("m9_preserved")
            or not before.get("m9_preserved")
            or after.get("new_session_fields_nondefault") != 0):
        raise M15SnapshotError("migration changed preserved business content or defaults")
    for version, tables in NEW_TABLES.items():
        if version <= target:
            for table in tables:
                if after.get("complete_content", {}).get(table, {}).get("rows") != 0:
                    raise M15SnapshotError("migration unexpectedly populated a new table")


async def run(version: int) -> dict[str, Any]:
    import asyncmy
    from app.core.config import settings
    if settings.db_engine != "mysql" or settings.app_env not in {"production", "testing"}:
        raise M15SnapshotError("snapshot requires controlled MySQL environment")
    connection = await asyncmy.connect(host=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_password, db=settings.db_name,
        charset="utf8mb4", autocommit=True, connect_timeout=10)
    try:
        return await capture(connection, version)
    finally:
        connection.close()
        await connection.ensure_closed()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, choices=range(9, 16), required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.version))
    except Exception as error:
        print(json.dumps({"passed": False, "error_type": type(error).__name__}))
        return 1
    print(canonical(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
