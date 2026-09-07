"""Gate A MARD 221 在真实 MySQL 的事务、文件和重放门槛。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from tortoise import connections

from app.repositories.product_repo import ProductRepository
from app.tasks import gatea_mard_publish as publisher


pytestmark = pytest.mark.mysql


async def test_gatea_mard_publish_updates_mysql_and_replays_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    monkeypatch.setattr(publisher, "STORAGE_ROOT", image_root)
    monkeypatch.setattr(
        publisher,
        "settings",
        SimpleNamespace(
            app_env="production",
            db_engine="mysql",
            product_image_upload_dir=str(image_root),
            product_image_base_url=(
                "https://api-test.pinkdoohub.cn/uploads/products"
            ),
        ),
    )
    repository = ProductRepository()
    connection = connections.get("default")
    try:
        preview = await publisher.plan_publish(repository)
        assert preview.database_changes == 221
        assert preview.images_to_create == 221
        assert preview.images_reused == 0

        assert await publisher.apply_publish(repository, preview) == 221
        replay = await publisher.plan_publish(repository)
        assert replay.already_current is True
        assert replay.database_changes == 0
        assert replay.images_to_create == 0
        assert replay.images_reused == 221
        assert await publisher.apply_publish(repository, replay) == 0

        rows = await connection.execute_query_dict(
            "SELECT COUNT(*) AS total, SUM(is_active <> 0) AS active, "
            "COUNT(DISTINCT color_code) AS codes, "
            "COUNT(DISTINCT swatch_image_url) AS urls "
            "FROM bead_colors"
        )
        assert {key: int(value) for key, value in rows[0].items()} == {
            "total": 221,
            "active": 221,
            "codes": 221,
            "urls": 221,
        }
        assert len(list(image_root.glob("*.png"))) == 221
        assert all(
            path.stat().st_mode & 0o777 == 0o644
            for path in image_root.glob("*.png")
        )
    finally:
        await connection.execute_query(
            "UPDATE bead_colors SET color_code = NULL, name = NULL, "
            "swatch_image_url = NULL, sort = slot_no, is_active = 0"
        )
