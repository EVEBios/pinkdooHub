"""本地综合演示数据命令的凭据、路径与 SQLite 安全边界。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from typing import Final

from app.common.constants.product import PRODUCT_IMAGE_MAX_BYTES
from app.common.enums.user import UserStatus
from app.models.user import User


REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_CREDENTIALS_FILE: Final = Path(
    "backups/local-demo-data/synthetic-credentials.json"
)
DEFAULT_BACKUP_DIR: Final = Path("backups/local-demo-data")
CREDENTIAL_SCHEMA_VERSION: Final = 1


class LocalDemoSeedError(RuntimeError):
    """可安全展示且永不携带密码的本地 seed 拒绝。"""


def is_valid_local_image_file(path: Path) -> bool:
    """Validate the same bounded signatures accepted by local image storage."""

    try:
        if path.is_symlink() or not path.is_file():
            return False
        size = path.stat().st_size
        if size <= 0 or size > PRODUCT_IMAGE_MAX_BYTES:
            return False
        content = path.read_bytes()
    except OSError:
        return False

    extension = path.suffix.lower()
    if extension == ".jpg":
        return content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9")
    if extension == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n") and content.endswith(
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    if extension == ".webp":
        return (
            len(content) >= 16
            and content.startswith(b"RIFF")
            and int.from_bytes(content[4:8], "little") == len(content) - 8
            and content[8:12] == b"WEBP"
            and content[12:16] in {b"VP8 ", b"VP8L", b"VP8X"}
        )
    return False


@dataclass(frozen=True, slots=True)
class SyntheticUserSpec:
    username: str
    nickname: str
    phone: str
    expected_status: UserStatus = UserStatus.NORMAL


SYNTHETIC_USER_SPECS: Final = (
    SyntheticUserSpec("localdemo_v1_orders", "本地演示·订单", "18800006101"),
    SyntheticUserSpec("localdemo_v1_assisted", "本地演示·代客", "18800006102"),
    SyntheticUserSpec(
        "localdemo_v1_disabled",
        "本地演示·禁用",
        "18800006103",
        UserStatus.DISABLED,
    ),
    SyntheticUserSpec(
        "localdemo_v1_res_pending",
        "本地演示·待确认",
        "18800006104",
    ),
    SyntheticUserSpec(
        "localdemo_v1_res_confirmed",
        "本地演示·已确认",
        "18800006105",
    ),
    SyntheticUserSpec(
        "localdemo_v1_res_rejected",
        "本地演示·已拒绝",
        "18800006106",
    ),
    SyntheticUserSpec(
        "localdemo_v1_res_cancel",
        "本地演示·顾客取消",
        "18800006107",
    ),
    SyntheticUserSpec(
        "localdemo_v1_res_closed",
        "本地演示·店休取消",
        "18800006108",
    ),
    SyntheticUserSpec(
        "localdemo_v1_res_weekly",
        "本地演示·周店休取消",
        "18800006109",
    ),
)
USER_SPEC_BY_USERNAME: Final = {
    spec.username: spec for spec in SYNTHETIC_USER_SPECS
}


@dataclass(frozen=True, slots=True)
class CredentialBundle:
    passwords: dict[str, str]
    created: bool


def assert_path_in_repository(path: Path, *, label: str) -> Path:
    root = REPOSITORY_ROOT.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise LocalDemoSeedError(f"{label} must be inside the repository")
    return resolved


def validate_credentials_path(path: Path) -> Path:
    resolved = assert_path_in_repository(path, label="Credentials file")
    expected_parent = (REPOSITORY_ROOT / "backups/local-demo-data").resolve()
    if resolved.parent != expected_parent:
        raise LocalDemoSeedError(
            "Credentials file must be directly under backups/local-demo-data"
        )
    if path.is_symlink():
        raise LocalDemoSeedError("Credentials file must not be a symlink")
    return resolved


def _validate_credential_document(document: object) -> dict[str, str]:
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != CREDENTIAL_SCHEMA_VERSION
    ):
        raise LocalDemoSeedError("Synthetic credentials schema is invalid")
    users = document.get("users")
    if not isinstance(users, dict) or set(users) != set(USER_SPEC_BY_USERNAME):
        raise LocalDemoSeedError("Synthetic credentials user set is invalid")
    passwords: dict[str, str] = {}
    for username, password in users.items():
        if not isinstance(username, str) or not isinstance(password, str):
            raise LocalDemoSeedError("Synthetic credentials entries are invalid")
        if not 16 <= len(password) <= 128:
            raise LocalDemoSeedError("Synthetic credential length is invalid")
        passwords[username] = password
    return passwords


def _load_credentials(path: Path) -> dict[str, str]:
    if path.is_symlink():
        raise LocalDemoSeedError("Credentials file must not be a symlink")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise LocalDemoSeedError(
            "Cannot inspect synthetic credentials file"
        ) from error
    if mode != 0o600:
        raise LocalDemoSeedError(
            "Synthetic credentials file permissions must be exactly 0600"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LocalDemoSeedError("Cannot read synthetic credentials file") from error
    return _validate_credential_document(document)


def _write_credentials(path: Path) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    passwords = {
        spec.username: f"{secrets.token_urlsafe(24)}Aa1!"
        for spec in SYNTHETIC_USER_SPECS
    }
    payload = {
        "schema_version": CREDENTIAL_SCHEMA_VERSION,
        "users": passwords,
    }
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            descriptor = None
            os.fchmod(output.fileno(), 0o600)
            json.dump(payload, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise LocalDemoSeedError(
                "Synthetic credentials file appeared concurrently"
            ) from error
        temporary.unlink()
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    return passwords


async def prepare_credentials(path: Path) -> CredentialBundle:
    """只在首个保留用户名落库前创建一次凭据。"""

    resolved = validate_credentials_path(path)
    reserved_user_count = await User.filter(
        username__in=set(USER_SPEC_BY_USERNAME)
    ).count()
    if resolved.exists():
        return CredentialBundle(_load_credentials(resolved), created=False)
    if reserved_user_count:
        raise LocalDemoSeedError(
            "Reserved synthetic users exist but their credentials file is missing"
        )
    return CredentialBundle(_write_credentials(resolved), created=True)


def create_sqlite_backup(database: Path, backup_dir: Path) -> Path:
    """通过 SQLite Backup API 创建包含 WAL 已提交内容的 0600 快照。"""

    database = assert_path_in_repository(database, label="SQLite database")
    backup_dir = assert_path_in_repository(backup_dir, label="Backup directory")
    expected_backup_dir = (REPOSITORY_ROOT / "backups/local-demo-data").resolve()
    if backup_dir != expected_backup_dir:
        raise LocalDemoSeedError(
            "Backup directory must be backups/local-demo-data"
        )
    if not database.is_file():
        raise LocalDemoSeedError("SQLite database does not exist")
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    destination_path = backup_dir / (
        f"{database.name}.pre-local-demo-{timestamp}.bak"
    )
    descriptor = os.open(
        destination_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    os.fchmod(descriptor, 0o600)
    os.close(descriptor)
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    succeeded = False
    try:
        source = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        destination = sqlite3.connect(destination_path)
        source.execute("PRAGMA query_only = ON")
        source.backup(destination)
        succeeded = True
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        if not succeeded:
            destination_path.unlink(missing_ok=True)
    try:
        os.chmod(destination_path, 0o600)
        verify_sqlite_integrity(destination_path)
    except BaseException:
        destination_path.unlink(missing_ok=True)
        raise
    return destination_path


def verify_sqlite_integrity(database: Path) -> None:
    """在 ORM 连接关闭后执行只读物理完整性与外键检查。"""

    database = assert_path_in_repository(database, label="SQLite database")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity_rows != [("ok",)]:
            raise LocalDemoSeedError("SQLite integrity_check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise LocalDemoSeedError("SQLite foreign_key_check failed")
    finally:
        connection.close()
