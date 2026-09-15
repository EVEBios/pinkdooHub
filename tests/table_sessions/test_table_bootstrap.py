import json

import pytest

from app.models.table_session import StoreTable
from app.repositories.table_session_repo import TableSessionRepository
from app.tasks.table_bootstrap import (
    TableBootstrapError,
    seed_tables,
    verify_tables,
    write_placeholder_qr_artifacts,
)


async def test_seed_is_idempotent_and_writes_exactly_thirty_tables(tmp_path) -> None:
    repository = TableSessionRepository()

    await seed_tables(repository)
    await seed_tables(repository)
    tables = await verify_tables(repository)

    assert len(tables) == 30
    assert tables[0].table_no == "T01"
    assert tables[-1].table_no == "T30"
    assert len({table.qr_token for table in tables}) == 30

    output_dir = tmp_path / "develop-table-codes"
    write_placeholder_qr_artifacts(tables, output_dir)
    manifest = json.loads((output_dir / "manifest.json").read_text("utf-8"))
    assert manifest["kind"] == "placeholder_qr"
    assert manifest["wechat_environment"] == "develop"
    assert manifest["replace_before_wechat_distribution"] is True
    assert manifest["launch_path"] == "pages/table-entry/index"
    assert manifest["count"] == 30
    assert len(list(output_dir.glob("T*.png"))) == 30
    assert all("qr_token" not in item for item in manifest["items"])
    assert all(len(item["file_sha256"]) == 64 for item in manifest["items"])
    assert all(int(item["size_bytes"]) > 0 for item in manifest["items"])
    assert not any(path.stat().st_mode & 0o077 for path in output_dir.iterdir())


async def test_seed_fails_closed_on_partial_existing_inventory() -> None:
    await StoreTable.create(
        table_no="T01",
        display_name="T01号桌",
        qr_token="A" * 32,
    )

    try:
        await seed_tables(TableSessionRepository())
    except TableBootstrapError as exc:
        assert "exactly T01 through T30" in str(exc)
    else:
        raise AssertionError("partial table inventory must fail closed")


async def test_verify_fails_closed_on_drifted_display_name() -> None:
    await seed_tables(TableSessionRepository())
    await StoreTable.filter(table_no="T07").update(display_name="wrong")

    with pytest.raises(TableBootstrapError, match="display names"):
        await verify_tables(TableSessionRepository())


async def test_placeholder_qr_generation_rejects_symlink_output(tmp_path) -> None:
    await seed_tables(TableSessionRepository())
    tables = await verify_tables(TableSessionRepository())
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "linked"
    link_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(TableBootstrapError, match="symbolic link"):
        write_placeholder_qr_artifacts(tables, link_dir)


async def test_placeholder_qr_generation_refuses_to_overwrite_existing_path(
    tmp_path,
) -> None:
    await seed_tables(TableSessionRepository())
    tables = await verify_tables(TableSessionRepository())
    output_dir = tmp_path / "existing"
    output_dir.mkdir()
    sentinel = output_dir / "T01.png"
    sentinel.write_bytes(b"operator-owned")

    with pytest.raises(TableBootstrapError, match="new path"):
        write_placeholder_qr_artifacts(tables, output_dir)

    assert sentinel.read_bytes() == b"operator-owned"
