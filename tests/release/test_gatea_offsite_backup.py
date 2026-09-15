"""Gate A 客户端加密异机备份边界。"""

import json
import os
from pathlib import Path
import tarfile

import pytest

from scripts.release import gatea_offsite_backup as offsite


BACKUP_ID = "20260902t014211z"
CANDIDATE_SHA = "a" * 40


def _m7_content_snapshot(digest: str = "7" * 64) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "profile": offsite.gatea_backup.M7_CONTENT_SNAPSHOT_PROFILE,
        "schema_version": (
            offsite.gatea_backup.M7_CONTENT_SNAPSHOT_SCHEMA_VERSION
        ),
    }


def _m8_swatch_content_snapshot(
    digest: str = "8" * 64,
) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "profile": offsite.gatea_backup.M8_SWATCH_CONTENT_SNAPSHOT_PROFILE,
        "schema_version": (
            offsite.gatea_backup.M8_SWATCH_CONTENT_SNAPSHOT_SCHEMA_VERSION
        ),
    }


def _m9_table_content_snapshot(digest: str = "9" * 64) -> dict[str, object]:
    return {
        "content_sha256": digest,
        "profile": offsite.gatea_backup.M9_TABLE_CONTENT_SNAPSHOT_PROFILE,
        "schema_version": (
            offsite.gatea_backup.M9_TABLE_CONTENT_SNAPSHOT_SCHEMA_VERSION
        ),
    }


def _persist_source_records(
    local_paths: dict[str, Path], backup: dict, restore: dict
) -> None:
    local_paths["records/backup.json"].write_text(
        json.dumps(backup), encoding="utf-8"
    )
    local_paths["records/restore.json"].write_text(
        json.dumps(restore), encoding="utf-8"
    )


def _add_m9_content_evidence(backup: dict, restore: dict) -> None:
    backup["database_snapshot"] = {
        "aerich_versions": ",".join(offsite.gatea.APPROVED_TARGET_M9_CHAIN),
        "tables": 27,
    }
    backup["m7_content_snapshot"] = _m7_content_snapshot()
    backup["m8_swatch_content_snapshot"] = _m8_swatch_content_snapshot()
    backup["m9_table_content_snapshot"] = _m9_table_content_snapshot()
    restore["m7_content_matches"] = True
    restore["m7_content_snapshot"] = _m7_content_snapshot()
    restore["m8_swatch_content_matches"] = True
    restore["m8_swatch_content_snapshot"] = _m8_swatch_content_snapshot()
    restore["m9_table_content_matches"] = True
    restore["m9_table_content_snapshot"] = _m9_table_content_snapshot()


def _source_fixture(tmp_path: Path) -> tuple[dict[str, Path], dict, dict]:
    remote = offsite._remote_path_map(BACKUP_ID)
    mysql = tmp_path / "mysql.sql"
    images = tmp_path / "images.tar"
    mysql.write_bytes(b"verified mysql backup")
    images.write_bytes(b"verified image backup")
    mysql.chmod(0o600)
    images.chmod(0o600)
    backup = {
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "candidate_sha": CANDIDATE_SHA,
        "database_snapshot": {
            "aerich_versions": ",".join(
                offsite.gatea.APPROVED_SOURCE_M2_CHAIN
            ),
            "tables": 10,
        },
        "artifacts": {
            "mysql": {
                "path": str(remote["artifacts/mysql.sql"]),
                "bytes": mysql.stat().st_size,
                "sha256": offsite._sha256_file(mysql),
            },
            "images": {
                "path": str(remote["artifacts/images.tar"]),
                "bytes": images.stat().st_size,
                "sha256": offsite._sha256_file(images),
            },
        },
        "passed": True,
    }
    restore = {
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "candidate_sha": CANDIDATE_SHA,
        "database_matches": True,
        "images_match": True,
        "restore_app_ready": True,
        "redis_started_empty": True,
        "host_ports_published": False,
        "temporary_resources_removed": True,
        "passed": True,
    }
    backup_record = tmp_path / "backup.json"
    restore_record = tmp_path / "restore.json"
    backup_record.write_text(json.dumps(backup), encoding="utf-8")
    restore_record.write_text(json.dumps(restore), encoding="utf-8")
    backup_record.chmod(0o600)
    restore_record.chmod(0o600)
    return (
        {
            "records/backup.json": backup_record,
            "records/restore.json": restore_record,
            "artifacts/mysql.sql": mysql,
            "artifacts/images.tar": images,
        },
        backup,
        restore,
    )


def _keypair(tmp_path: Path) -> tuple[Path, Path, str]:
    key_dir = tmp_path / "keys"
    private_key = key_dir / "private.pem"
    public_key = key_dir / "public.pem"
    key_id = offsite.generate_keypair(
        private_key_path=private_key,
        public_key_path=public_key,
    )
    return private_key, public_key, key_id


def test_keygen_uses_separate_protected_files_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    private_key, public_key, key_id = _keypair(tmp_path)

    assert len(key_id) == 64
    assert private_key.stat().st_mode & 0o777 == 0o600
    assert public_key.stat().st_mode & 0o777 == 0o644
    assert private_key.parent.stat().st_mode & 0o777 == 0o700

    with pytest.raises(offsite.OffsiteBackupError, match="already exists"):
        offsite.generate_keypair(
            private_key_path=private_key,
            public_key_path=public_key,
        )


def test_source_records_require_successful_isolated_restore_and_checksums(
    tmp_path: Path,
) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)

    assert offsite._validate_source_records(
        backup_id=BACKUP_ID,
        local_paths=local_paths,
    ) == (backup, restore)

    local_paths["artifacts/mysql.sql"].write_bytes(b"tampered")
    with pytest.raises(offsite.OffsiteBackupError, match="source records"):
        offsite._validate_source_records(
            backup_id=BACKUP_ID,
            local_paths=local_paths,
        )


def test_m9_source_records_and_bundle_round_trip_with_versioned_content_evidence(
    tmp_path: Path,
) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    _add_m9_content_evidence(backup, restore)
    _persist_source_records(local_paths, backup, restore)

    assert offsite._validate_source_records(
        backup_id=BACKUP_ID,
        local_paths=local_paths,
    ) == (backup, restore)

    bundle = tmp_path / "m9-bundle.tar.gz"
    manifest = offsite._build_bundle(
        backup_id=BACKUP_ID,
        local_paths=local_paths,
        backup=backup,
        restore=restore,
        bundle_path=bundle,
    )
    assert offsite._inspect_bundle(bundle) == manifest


def test_historical_m9_source_pair_without_swatch_evidence_remains_valid(
    tmp_path: Path,
) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    _add_m9_content_evidence(backup, restore)
    backup.pop("m8_swatch_content_snapshot")
    restore.pop("m8_swatch_content_matches")
    restore.pop("m8_swatch_content_snapshot")
    _persist_source_records(local_paths, backup, restore)

    assert offsite._validate_source_records(
        backup_id=BACKUP_ID,
        local_paths=local_paths,
    ) == (backup, restore)

    bundle = tmp_path / "historical-m9-bundle.tar.gz"
    manifest = offsite._build_bundle(
        backup_id=BACKUP_ID,
        local_paths=local_paths,
        backup=backup,
        restore=restore,
        bundle_path=bundle,
    )
    assert offsite._inspect_bundle(bundle) == manifest


@pytest.mark.parametrize(
    "case",
    (
        "missing_m7_backup",
        "missing_m8_swatch_backup",
        "missing_m9_restore",
        "m7_match_false",
        "m8_swatch_match_false",
        "m9_match_false",
        "m7_snapshot_mismatch",
        "m8_swatch_snapshot_mismatch",
        "m9_snapshot_mismatch",
    ),
)
def test_m9_source_records_fail_closed_on_incomplete_or_mismatched_evidence(
    tmp_path: Path,
    case: str,
) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    _add_m9_content_evidence(backup, restore)
    if case == "missing_m7_backup":
        backup.pop("m7_content_snapshot")
    elif case == "missing_m8_swatch_backup":
        backup.pop("m8_swatch_content_snapshot")
    elif case == "missing_m9_restore":
        restore.pop("m9_table_content_snapshot")
    elif case == "m7_match_false":
        restore["m7_content_matches"] = False
    elif case == "m8_swatch_match_false":
        restore["m8_swatch_content_matches"] = False
    elif case == "m9_match_false":
        restore["m9_table_content_matches"] = False
    elif case == "m7_snapshot_mismatch":
        restore["m7_content_snapshot"] = _m7_content_snapshot("8" * 64)
    elif case == "m8_swatch_snapshot_mismatch":
        restore["m8_swatch_content_snapshot"] = (
            _m8_swatch_content_snapshot("a" * 64)
        )
    else:
        restore["m9_table_content_snapshot"] = _m9_table_content_snapshot(
            "a" * 64
        )
    _persist_source_records(local_paths, backup, restore)

    with pytest.raises(offsite.OffsiteBackupError, match="source records"):
        offsite._validate_source_records(
            backup_id=BACKUP_ID,
            local_paths=local_paths,
        )


@pytest.mark.parametrize("database_snapshot", (None, [], {}))
def test_source_records_require_an_approved_database_snapshot_object(
    tmp_path: Path,
    database_snapshot: object,
) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    if database_snapshot is None:
        backup.pop("database_snapshot")
    else:
        backup["database_snapshot"] = database_snapshot
    _persist_source_records(local_paths, backup, restore)

    with pytest.raises(offsite.OffsiteBackupError, match="source records"):
        offsite._validate_source_records(
            backup_id=BACKUP_ID,
            local_paths=local_paths,
        )


def test_source_records_reject_unknown_migration_chain_without_echoing_it(
    tmp_path: Path,
) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    unknown_chain = "unapproved-sensitive-chain"
    backup["database_snapshot"] = {"aerich_versions": unknown_chain}
    _persist_source_records(local_paths, backup, restore)

    with pytest.raises(offsite.OffsiteBackupError) as captured:
        offsite._validate_source_records(
            backup_id=BACKUP_ID,
            local_paths=local_paths,
        )
    assert "source records are invalid" in str(captured.value)
    assert unknown_chain not in str(captured.value)


def test_non_m9_source_records_reject_any_m9_evidence(tmp_path: Path) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    backup["m9_table_content_snapshot"] = _m9_table_content_snapshot()
    restore["m9_table_content_matches"] = True
    restore["m9_table_content_snapshot"] = _m9_table_content_snapshot()
    _persist_source_records(local_paths, backup, restore)

    with pytest.raises(offsite.OffsiteBackupError, match="source records"):
        offsite._validate_source_records(
            backup_id=BACKUP_ID,
            local_paths=local_paths,
        )


def test_pre_m8_source_records_reject_any_swatch_evidence(tmp_path: Path) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    backup["m8_swatch_content_snapshot"] = _m8_swatch_content_snapshot()
    restore["m8_swatch_content_matches"] = True
    restore["m8_swatch_content_snapshot"] = _m8_swatch_content_snapshot()
    _persist_source_records(local_paths, backup, restore)

    with pytest.raises(offsite.OffsiteBackupError, match="source records"):
        offsite._validate_source_records(
            backup_id=BACKUP_ID,
            local_paths=local_paths,
        )


def test_bundle_contains_only_fixed_regular_members_and_verified_manifest(
    tmp_path: Path,
) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    bundle = tmp_path / "bundle.tar.gz"

    manifest = offsite._build_bundle(
        backup_id=BACKUP_ID,
        local_paths=local_paths,
        backup=backup,
        restore=restore,
        bundle_path=bundle,
    )

    assert offsite._inspect_bundle(bundle) == manifest
    with tarfile.open(bundle, "r:gz") as archive:
        assert {member.name for member in archive.getmembers()} == (
            offsite.EXPECTED_BUNDLE_MEMBERS
        )
        assert all(member.isfile() for member in archive.getmembers())


def test_bundle_rejects_self_consistent_but_semantically_invalid_m9_evidence(
    tmp_path: Path,
) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    _add_m9_content_evidence(backup, restore)
    invalid_snapshot = {
        "content_sha256": "not-a-sha256",
        "profile": offsite.gatea_backup.M9_TABLE_CONTENT_SNAPSHOT_PROFILE,
        "schema_version": (
            offsite.gatea_backup.M9_TABLE_CONTENT_SNAPSHOT_SCHEMA_VERSION
        ),
    }
    backup["m9_table_content_snapshot"] = invalid_snapshot
    restore["m9_table_content_snapshot"] = invalid_snapshot.copy()
    _persist_source_records(local_paths, backup, restore)
    bundle = tmp_path / "semantically-invalid.tar.gz"
    offsite._build_bundle(
        backup_id=BACKUP_ID,
        local_paths=local_paths,
        backup=backup,
        restore=restore,
        bundle_path=bundle,
    )

    with pytest.raises(offsite.OffsiteBackupError, match="bundle is invalid"):
        offsite._inspect_bundle(bundle)


def test_bundle_rejects_unexpected_member(tmp_path: Path) -> None:
    bundle = tmp_path / "invalid.tar.gz"
    extra = tmp_path / "extra"
    extra.write_text("unexpected", encoding="utf-8")
    with tarfile.open(bundle, "w:gz") as archive:
        archive.add(extra, arcname="../escape")

    with pytest.raises(offsite.OffsiteBackupError, match="bundle is invalid"):
        offsite._inspect_bundle(bundle)


def test_encrypted_copy_round_trip_updates_safe_record(tmp_path: Path) -> None:
    local_paths, backup, restore = _source_fixture(tmp_path)
    private_key_path, public_key_path, key_id = _keypair(tmp_path)
    public_key = offsite._load_public_key(public_key_path)
    bundle = tmp_path / "bundle.tar.gz"
    manifest = offsite._build_bundle(
        backup_id=BACKUP_ID,
        local_paths=local_paths,
        backup=backup,
        restore=restore,
        bundle_path=bundle,
    )
    encrypted = tmp_path / f"{BACKUP_ID}.pdhb"
    header = offsite._encrypt_bundle(
        bundle_path=bundle,
        output_path=encrypted,
        public_key=public_key,
    )
    record_path = tmp_path / f"{BACKUP_ID}.pdhb.json"
    record = {
        "schema_version": 1,
        "backup_id": BACKUP_ID,
        "candidate_sha": CANDIDATE_SHA,
        "copy_file": encrypted.name,
        "copy_bytes": encrypted.stat().st_size,
        "copy_sha256": offsite._sha256_file(encrypted),
        "key_id": key_id,
        "cipher": header["cipher"],
        "key_wrap": header["key_wrap"],
        "source_files": manifest["files"],
        "verified_after_export": False,
        "passed": False,
    }
    record_path.write_text(json.dumps(record), encoding="utf-8")
    record_path.chmod(0o600)

    verified = offsite.verify_copy(
        encrypted_path=encrypted,
        private_key_path=private_key_path,
        record_path=record_path,
    )

    assert encrypted.stat().st_mode & 0o777 == 0o400
    assert verified["key_id"] == key_id
    assert verified["verified_after_export"] is True
    assert verified["passed"] is True
    persisted = json.loads(record_path.read_text(encoding="utf-8"))
    assert persisted["passed"] is True
    assert "private" not in json.dumps(persisted).lower()


def test_encrypted_copy_detects_ciphertext_tampering(tmp_path: Path) -> None:
    private_key_path, public_key_path, _ = _keypair(tmp_path)
    bundle = tmp_path / "bundle"
    bundle.write_bytes(b"authenticated plaintext")
    encrypted = tmp_path / "copy.pdhb"
    offsite._encrypt_bundle(
        bundle_path=bundle,
        output_path=encrypted,
        public_key=offsite._load_public_key(public_key_path),
    )
    payload = bytearray(encrypted.read_bytes())
    payload[-offsite.TAG_BYTES - 1] ^= 1
    encrypted.chmod(0o600)
    encrypted.write_bytes(payload)
    encrypted.chmod(0o400)

    with pytest.raises(offsite.OffsiteBackupError, match="authentication failed"):
        with offsite._protected_temporary_directory("tamper-test-") as temporary:
            offsite._decrypt_copy(
                encrypted_path=encrypted,
                private_key=offsite._load_private_key(private_key_path),
                output_path=temporary / "plain",
            )


def test_ssh_command_rejects_injection_and_requires_protected_identity(
    tmp_path: Path,
) -> None:
    identity = tmp_path / "identity"
    identity.write_text("test-only", encoding="utf-8")
    identity.chmod(0o600)

    command = offsite._ssh_command(
        host="192.0.2.10",
        user="ubuntu",
        identity_file=identity,
        remote_command="true",
    )
    assert command[-2:] == ("ubuntu@192.0.2.10", "true")

    with pytest.raises(offsite.OffsiteBackupError, match="host is invalid"):
        offsite._ssh_command(
            host="host;id",
            user="ubuntu",
            identity_file=identity,
            remote_command="true",
        )

    identity.chmod(0o644)
    with pytest.raises(offsite.OffsiteBackupError, match="mode 0600"):
        offsite._ssh_command(
            host="192.0.2.10",
            user="ubuntu",
            identity_file=identity,
            remote_command="true",
        )


def test_key_and_copy_paths_must_not_enter_repository() -> None:
    private_key = offsite.gatea.REPOSITORY_ROOT / "private.pem"
    public_key = offsite.gatea.REPOSITORY_ROOT / "public.pem"

    with pytest.raises(offsite.OffsiteBackupError, match="outside the repository"):
        offsite.generate_keypair(
            private_key_path=private_key,
            public_key_path=public_key,
        )
