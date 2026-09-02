#!/usr/bin/env python3
"""创建并验证 Gate A 备份的客户端加密异机副本。"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, BinaryIO, Iterator, Mapping, Sequence

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from scripts.release import gatea_backup
from scripts.release import gatea_operations as gatea


MAGIC = b"PINKDOOHUB-GATEA-OFFSITE-V1\n"
TAG_BYTES = 16
HEADER_LENGTH_BYTES = 4
KEY_BITS = 3072
CHUNK_BYTES = 1024 * 1024
HOST_PATTERN = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?"
    r"|(?:\d{1,3}\.){3}\d{1,3})$"
)
SSH_USER_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
EXPECTED_BUNDLE_MEMBERS = {
    "bundle-manifest.json",
    "records/backup.json",
    "records/restore.json",
    "artifacts/mysql.sql",
    "artifacts/images.tar",
}
REMOTE_ROOT = Path("/srv/pinkdoohub/gatea")


class OffsiteBackupError(RuntimeError):
    """不包含主机、Secret、私钥或原始备份内容的安全错误。"""


class SecureArgumentParser(argparse.ArgumentParser):
    """参数错误不回显可能包含本机或 SSH 信息的命令行。"""

    def error(self, message: str) -> None:
        self.exit(2, "Gate A offsite backup arguments are invalid\n")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_outside_repository(path: Path, description: str) -> Path:
    resolved = path.expanduser().resolve()
    repository = gatea.REPOSITORY_ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise OffsiteBackupError(f"{description} must be outside the repository")
    return resolved


def _validate_private_key_file(path: Path) -> None:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise OffsiteBackupError("Gate A backup private key must be a regular file")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise OffsiteBackupError(
            "Gate A backup private key must be owned by the operator with mode 0600"
        )


def _validate_public_key_file(path: Path) -> None:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise OffsiteBackupError("Gate A backup public key must be a regular file")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o644:
        raise OffsiteBackupError(
            "Gate A backup public key must be owned by the operator with mode 0644"
        )


def _public_key_id(public_key: rsa.RSAPublicKey) -> str:
    der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def generate_keypair(*, private_key_path: Path, public_key_path: Path) -> str:
    """生成与备份目录分离的本机 RSA-OAEP 接收密钥。"""

    private_key_path = _assert_outside_repository(
        private_key_path, "Gate A backup private key"
    )
    public_key_path = _assert_outside_repository(
        public_key_path, "Gate A backup public key"
    )
    if private_key_path.exists() or public_key_path.exists():
        raise OffsiteBackupError("Gate A backup key path already exists")
    if private_key_path.parent != public_key_path.parent:
        raise OffsiteBackupError("Gate A backup keypair must share one protected directory")

    directory = private_key_path.parent
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise OffsiteBackupError("Gate A backup key directory must use mode 0700")

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_BITS)
    private_payload = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_payload = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    try:
        with private_key_path.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(private_payload)
        with public_key_path.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(public_payload)
    except BaseException:
        private_key_path.unlink(missing_ok=True)
        public_key_path.unlink(missing_ok=True)
        raise
    return _public_key_id(private_key.public_key())


def _load_public_key(path: Path) -> rsa.RSAPublicKey:
    _validate_public_key_file(path)
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < KEY_BITS:
        raise OffsiteBackupError("Gate A backup public key is not approved RSA-3072+")
    return key


def _load_private_key(path: Path) -> rsa.RSAPrivateKey:
    _validate_private_key_file(path)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < KEY_BITS:
        raise OffsiteBackupError("Gate A backup private key is not approved RSA-3072+")
    return key


def _ssh_command(
    *, host: str, user: str, identity_file: Path, remote_command: str
) -> tuple[str, ...]:
    if HOST_PATTERN.fullmatch(host) is None:
        raise OffsiteBackupError("Gate A offsite SSH host is invalid")
    if SSH_USER_PATTERN.fullmatch(user) is None:
        raise OffsiteBackupError("Gate A offsite SSH user is invalid")
    identity_file = identity_file.expanduser().resolve()
    metadata = identity_file.stat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise OffsiteBackupError("Gate A offsite SSH identity must use mode 0600")
    return (
        "ssh",
        "-i",
        str(identity_file),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        f"{user}@{host}",
        remote_command,
    )


def _remote_path_map(backup_id: str) -> dict[str, Path]:
    backup_id = gatea_backup._backup_id(backup_id)
    return {
        "records/backup.json": REMOTE_ROOT
        / "records"
        / "backups"
        / f"{backup_id}.json",
        "records/restore.json": REMOTE_ROOT
        / "records"
        / "restores"
        / f"{backup_id}.json",
        "artifacts/mysql.sql": REMOTE_ROOT
        / "backups"
        / "mysql"
        / f"{backup_id}.sql",
        "artifacts/images.tar": REMOTE_ROOT
        / "backups"
        / "images"
        / f"{backup_id}.tar",
    }


def _download_remote_file(
    *,
    host: str,
    user: str,
    identity_file: Path,
    remote_path: Path,
    local_path: Path,
) -> None:
    command = _ssh_command(
        host=host,
        user=user,
        identity_file=identity_file,
        remote_command=f"sudo -n /bin/cat -- {remote_path}",
    )
    with local_path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        result = subprocess.run(command, stdout=stream, stderr=subprocess.PIPE)
    if result.returncode != 0:
        local_path.unlink(missing_ok=True)
        raise OffsiteBackupError("Gate A offsite source download failed")
    if local_path.stat().st_size == 0:
        local_path.unlink(missing_ok=True)
        raise OffsiteBackupError("Gate A offsite source artifact is empty")


def _validate_source_records(
    *,
    backup_id: str,
    local_paths: Mapping[str, Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        backup = json.loads(local_paths["records/backup.json"].read_text())
        restore = json.loads(local_paths["records/restore.json"].read_text())
        if (
            backup.get("schema_version") != 1
            or backup.get("backup_id") != backup_id
            or backup.get("passed") is not True
            or restore.get("schema_version") != 1
            or restore.get("backup_id") != backup_id
            or restore.get("candidate_sha") != backup.get("candidate_sha")
            or restore.get("database_matches") is not True
            or restore.get("images_match") is not True
            or restore.get("restore_app_ready") is not True
            or restore.get("redis_started_empty") is not True
            or restore.get("host_ports_published") is not False
            or restore.get("temporary_resources_removed") is not True
            or restore.get("passed") is not True
        ):
            raise ValueError
        expected_remote = _remote_path_map(backup_id)
        for artifact_name, member_name in (
            ("mysql", "artifacts/mysql.sql"),
            ("images", "artifacts/images.tar"),
        ):
            metadata = backup["artifacts"][artifact_name]
            local_path = local_paths[member_name]
            if metadata["path"] != str(expected_remote[member_name]):
                raise ValueError
            if int(metadata["bytes"]) != local_path.stat().st_size:
                raise ValueError
            if metadata["sha256"] != _sha256_file(local_path):
                raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise OffsiteBackupError("Gate A offsite source records are invalid") from error
    return backup, restore


def _tar_bytes_info(payload: bytes) -> dict[str, object]:
    return {"bytes": len(payload), "sha256": _sha256_bytes(payload)}


def _build_bundle(
    *,
    backup_id: str,
    local_paths: Mapping[str, Path],
    backup: Mapping[str, Any],
    restore: Mapping[str, Any],
    bundle_path: Path,
) -> dict[str, Any]:
    files = {
        member_name: {
            "bytes": local_path.stat().st_size,
            "sha256": _sha256_file(local_path),
        }
        for member_name, local_path in local_paths.items()
    }
    manifest = {
        "schema_version": 1,
        "backup_id": backup_id,
        "candidate_sha": backup["candidate_sha"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_restore_passed": restore["passed"],
        "files": files,
        "pii_recorded": False,
        "secret_values_recorded": False,
    }
    manifest_payload = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    with tarfile.open(bundle_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for member_name in sorted(local_paths):
            local_path = local_paths[member_name]
            info = tarfile.TarInfo(member_name)
            info.size = local_path.stat().st_size
            info.mode = 0o600
            info.mtime = 0
            with local_path.open("rb") as stream:
                archive.addfile(info, stream)
        info = tarfile.TarInfo("bundle-manifest.json")
        info.size = len(manifest_payload)
        info.mode = 0o600
        info.mtime = 0
        archive.addfile(info, BytesIO(manifest_payload))
    os.chmod(bundle_path, 0o600)
    return manifest


def _inspect_bundle(bundle_path: Path) -> dict[str, Any]:
    try:
        with tarfile.open(bundle_path, "r:gz") as archive:
            members = archive.getmembers()
            if {member.name for member in members} != EXPECTED_BUNDLE_MEMBERS:
                raise ValueError
            if any(not member.isfile() or member.mode != 0o600 for member in members):
                raise ValueError
            extracted: dict[str, bytes] = {}
            for member in members:
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError
                extracted[member.name] = stream.read()
        manifest = json.loads(extracted["bundle-manifest.json"])
        if manifest.get("schema_version") != 1:
            raise ValueError
        files = manifest["files"]
        for member_name in EXPECTED_BUNDLE_MEMBERS - {"bundle-manifest.json"}:
            metadata = files[member_name]
            payload = extracted[member_name]
            if metadata != _tar_bytes_info(payload):
                raise ValueError
        backup = json.loads(extracted["records/backup.json"])
        restore = json.loads(extracted["records/restore.json"])
        if (
            backup.get("backup_id") != manifest.get("backup_id")
            or backup.get("candidate_sha") != manifest.get("candidate_sha")
            or backup.get("passed") is not True
            or restore.get("backup_id") != manifest.get("backup_id")
            or restore.get("candidate_sha") != manifest.get("candidate_sha")
            or restore.get("database_matches") is not True
            or restore.get("images_match") is not True
            or restore.get("passed") is not True
        ):
            raise ValueError
        for artifact_name, member_name in (
            ("mysql", "artifacts/mysql.sql"),
            ("images", "artifacts/images.tar"),
        ):
            source = backup["artifacts"][artifact_name]
            copied = files[member_name]
            if int(source["bytes"]) != copied["bytes"]:
                raise ValueError
            if source["sha256"] != copied["sha256"]:
                raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, tarfile.TarError) as error:
        raise OffsiteBackupError("Gate A encrypted backup bundle is invalid") from error
    return manifest


def _encrypt_bundle(
    *, bundle_path: Path, output_path: Path, public_key: rsa.RSAPublicKey
) -> dict[str, Any]:
    plaintext_bytes = bundle_path.stat().st_size
    plaintext_sha256 = _sha256_file(bundle_path)
    data_key = os.urandom(32)
    nonce = os.urandom(12)
    wrapped_key = public_key.encrypt(
        data_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    header = {
        "schema_version": 1,
        "cipher": "AES-256-GCM",
        "key_wrap": "RSA-OAEP-SHA256",
        "key_id": _public_key_id(public_key),
        "nonce": base64.b64encode(nonce).decode(),
        "wrapped_key": base64.b64encode(wrapped_key).decode(),
        "plaintext_bytes": plaintext_bytes,
        "plaintext_sha256": plaintext_sha256,
    }
    header_payload = json.dumps(
        header, sort_keys=True, separators=(",", ":")
    ).encode()
    if len(header_payload) > 64 * 1024:
        raise OffsiteBackupError("Gate A encrypted backup header is too large")

    encryptor = Cipher(algorithms.AES(data_key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header_payload)
    with output_path.open("xb") as target, bundle_path.open("rb") as source:
        os.fchmod(target.fileno(), 0o400)
        target.write(MAGIC)
        target.write(struct.pack(">I", len(header_payload)))
        target.write(header_payload)
        for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
            target.write(encryptor.update(chunk))
        target.write(encryptor.finalize())
        target.write(encryptor.tag)
    data_key = b""
    return header


def _decrypt_copy(
    *, encrypted_path: Path, private_key: rsa.RSAPrivateKey, output_path: Path
) -> dict[str, Any]:
    total_bytes = encrypted_path.stat().st_size
    with encrypted_path.open("rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise OffsiteBackupError("Gate A encrypted backup magic is invalid")
        raw_length = source.read(HEADER_LENGTH_BYTES)
        if len(raw_length) != HEADER_LENGTH_BYTES:
            raise OffsiteBackupError("Gate A encrypted backup header is truncated")
        header_length = struct.unpack(">I", raw_length)[0]
        if not 1 <= header_length <= 64 * 1024:
            raise OffsiteBackupError("Gate A encrypted backup header length is invalid")
        header_payload = source.read(header_length)
        try:
            header = json.loads(header_payload)
            nonce = base64.b64decode(header["nonce"], validate=True)
            wrapped_key = base64.b64decode(header["wrapped_key"], validate=True)
            plaintext_bytes = int(header["plaintext_bytes"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise OffsiteBackupError("Gate A encrypted backup header is invalid") from error
        if (
            header.get("schema_version") != 1
            or header.get("cipher") != "AES-256-GCM"
            or header.get("key_wrap") != "RSA-OAEP-SHA256"
            or header.get("key_id") != _public_key_id(private_key.public_key())
            or len(nonce) != 12
            or plaintext_bytes <= 0
        ):
            raise OffsiteBackupError("Gate A encrypted backup policy does not match")
        ciphertext_bytes = (
            total_bytes
            - len(MAGIC)
            - HEADER_LENGTH_BYTES
            - header_length
            - TAG_BYTES
        )
        if ciphertext_bytes != plaintext_bytes:
            raise OffsiteBackupError("Gate A encrypted backup length does not match")
        source.seek(total_bytes - TAG_BYTES)
        tag = source.read(TAG_BYTES)
        source.seek(len(MAGIC) + HEADER_LENGTH_BYTES + header_length)
        try:
            data_key = private_key.decrypt(
                wrapped_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
            decryptor = Cipher(
                algorithms.AES(data_key), modes.GCM(nonce, tag)
            ).decryptor()
            decryptor.authenticate_additional_data(header_payload)
            remaining = ciphertext_bytes
            with output_path.open("xb") as target:
                os.fchmod(target.fileno(), 0o600)
                while remaining:
                    chunk = source.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise ValueError
                    remaining -= len(chunk)
                    target.write(decryptor.update(chunk))
                target.write(decryptor.finalize())
        except BaseException as error:
            output_path.unlink(missing_ok=True)
            if isinstance(error, OffsiteBackupError):
                raise
            raise OffsiteBackupError(
                "Gate A encrypted backup authentication failed"
            ) from error
    data_key = b""
    if output_path.stat().st_size != plaintext_bytes:
        raise OffsiteBackupError("Gate A decrypted backup length does not match")
    if _sha256_file(output_path) != header.get("plaintext_sha256"):
        raise OffsiteBackupError("Gate A decrypted backup checksum does not match")
    return header


@contextmanager
def _protected_temporary_directory(prefix: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=prefix) as raw_directory:
        directory = Path(raw_directory)
        directory.chmod(0o700)
        yield directory


def export_copy(
    *,
    backup_id: str,
    host: str,
    user: str,
    identity_file: Path,
    public_key_path: Path,
    destination_dir: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    """从精确远端 Backup ID 拉取、验证并生成客户端加密副本。"""

    backup_id = gatea_backup._backup_id(backup_id)
    public_key = _load_public_key(public_key_path.expanduser().resolve())
    destination_dir = _assert_outside_repository(
        destination_dir, "Gate A offsite backup destination"
    )
    destination_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    if stat.S_IMODE(destination_dir.stat().st_mode) != 0o700:
        raise OffsiteBackupError("Gate A offsite backup directory must use mode 0700")
    output_path = destination_dir / f"{backup_id}.pdhb"
    record_path = destination_dir / f"{backup_id}.pdhb.json"
    if output_path.exists() or record_path.exists():
        raise OffsiteBackupError("Gate A encrypted offsite backup already exists")

    with _protected_temporary_directory("pinkdoohub-gatea-offsite-") as temporary:
        local_paths: dict[str, Path] = {}
        for index, (member_name, remote_path) in enumerate(
            sorted(_remote_path_map(backup_id).items())
        ):
            local_path = temporary / f"source-{index}"
            _download_remote_file(
                host=host,
                user=user,
                identity_file=identity_file,
                remote_path=remote_path,
                local_path=local_path,
            )
            local_paths[member_name] = local_path
        backup, restore = _validate_source_records(
            backup_id=backup_id,
            local_paths=local_paths,
        )
        bundle_path = temporary / "verified-bundle.tar.gz"
        bundle_manifest = _build_bundle(
            backup_id=backup_id,
            local_paths=local_paths,
            backup=backup,
            restore=restore,
            bundle_path=bundle_path,
        )
        _inspect_bundle(bundle_path)
        try:
            header = _encrypt_bundle(
                bundle_path=bundle_path,
                output_path=output_path,
                public_key=public_key,
            )
            copy_record = {
                "schema_version": 1,
                "backup_id": backup_id,
                "candidate_sha": backup["candidate_sha"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "copy_file": output_path.name,
                "copy_bytes": output_path.stat().st_size,
                "copy_sha256": _sha256_file(output_path),
                "key_id": header["key_id"],
                "cipher": header["cipher"],
                "key_wrap": header["key_wrap"],
                "source_files": bundle_manifest["files"],
                "source_restore_passed": True,
                "pii_recorded": False,
                "secret_values_recorded": False,
                "verified_after_export": False,
                "passed": False,
            }
            with record_path.open("x", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(copy_record, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        except BaseException:
            output_path.unlink(missing_ok=True)
            record_path.unlink(missing_ok=True)
            raise
    return output_path, record_path, copy_record


def verify_copy(
    *, encrypted_path: Path, private_key_path: Path, record_path: Path
) -> dict[str, Any]:
    """在客户端解密并验证 AEAD、Bundle 与来源 Artifact checksum。"""

    encrypted_path = _assert_outside_repository(
        encrypted_path, "Gate A encrypted backup"
    )
    record_path = _assert_outside_repository(
        record_path, "Gate A encrypted backup record"
    )
    private_key = _load_private_key(private_key_path.expanduser().resolve())
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if (
            record.get("schema_version") != 1
            or record.get("copy_file") != encrypted_path.name
            or int(record["copy_bytes"]) != encrypted_path.stat().st_size
            or record.get("copy_sha256") != _sha256_file(encrypted_path)
            or record.get("key_id") != _public_key_id(private_key.public_key())
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise OffsiteBackupError("Gate A encrypted backup record is invalid") from error

    with _protected_temporary_directory("pinkdoohub-gatea-verify-") as temporary:
        bundle_path = temporary / "decrypted-bundle.tar.gz"
        header = _decrypt_copy(
            encrypted_path=encrypted_path,
            private_key=private_key,
            output_path=bundle_path,
        )
        manifest = _inspect_bundle(bundle_path)
    if (
        manifest.get("backup_id") != record.get("backup_id")
        or manifest.get("candidate_sha") != record.get("candidate_sha")
        or manifest.get("files") != record.get("source_files")
        or header.get("key_id") != record.get("key_id")
    ):
        raise OffsiteBackupError("Gate A encrypted backup evidence does not match")

    record["verified_at"] = datetime.now(timezone.utc).isoformat()
    record["verified_after_export"] = True
    record["passed"] = True
    temporary_record = record_path.with_name(f".{record_path.name}.tmp")
    if temporary_record.exists():
        raise OffsiteBackupError("Gate A encrypted backup record staging exists")
    try:
        with temporary_record.open("x", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_record, record_path)
    finally:
        temporary_record.unlink(missing_ok=True)
    return record


def _parser() -> argparse.ArgumentParser:
    parser = SecureArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen = subparsers.add_parser("keygen")
    keygen.add_argument("--private-key", type=Path, required=True)
    keygen.add_argument("--public-key", type=Path, required=True)

    export = subparsers.add_parser("export")
    export.add_argument("--backup-id", required=True)
    export.add_argument("--host", required=True)
    export.add_argument("--user", required=True)
    export.add_argument("--identity-file", type=Path, required=True)
    export.add_argument("--public-key", type=Path, required=True)
    export.add_argument("--destination-dir", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--copy", type=Path, required=True)
    verify.add_argument("--private-key", type=Path, required=True)
    verify.add_argument("--record", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "keygen":
            key_id = generate_keypair(
                private_key_path=arguments.private_key,
                public_key_path=arguments.public_key,
            )
            print(json.dumps({"key_id": key_id, "passed": True}, sort_keys=True))
        elif arguments.command == "export":
            output_path, record_path, record = export_copy(
                backup_id=arguments.backup_id,
                host=arguments.host,
                user=arguments.user,
                identity_file=arguments.identity_file,
                public_key_path=arguments.public_key,
                destination_dir=arguments.destination_dir,
            )
            print(
                json.dumps(
                    {
                        "backup_id": record["backup_id"],
                        "copy_file": output_path.name,
                        "record_file": record_path.name,
                        "encrypted": True,
                        "passed": True,
                    },
                    sort_keys=True,
                )
            )
        else:
            record = verify_copy(
                encrypted_path=arguments.copy,
                private_key_path=arguments.private_key,
                record_path=arguments.record,
            )
            print(
                json.dumps(
                    {
                        "backup_id": record["backup_id"],
                        "key_id": record["key_id"],
                        "verified_after_export": True,
                        "passed": True,
                    },
                    sort_keys=True,
                )
            )
    except (OffsiteBackupError, OSError, subprocess.SubprocessError) as error:
        print(f"Gate A offsite backup failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
