"""Gate A MARD 221 preview/apply、持久图片和补偿契约。"""

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tasks import gatea_mard_publish as publisher
from app.tasks.mard_catalog import build_swatch_png, load_manifest


def _placeholder_rows() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            slot_no=slot,
            color_code=None,
            name=None,
            swatch_hex=None,
            swatch_image_url=None,
            sort=slot,
            is_active=False,
            updated_at=None,
        )
        for slot in range(1, 222)
    ]


def _current_rows(base_url: str) -> list[SimpleNamespace]:
    colors = load_manifest(publisher.MANIFEST)
    return [
        SimpleNamespace(
            slot_no=color.slot_no,
            color_code=color.color_code,
            name=color.name,
            swatch_hex=color.hex,
            swatch_image_url=f"{base_url}/{color.image_filename}",
            sort=color.sort,
            is_active=True,
            updated_at=None,
        )
        for color in colors
    ]


def test_row_validation_accepts_only_placeholders_or_exact_manifest() -> None:
    colors = load_manifest(publisher.MANIFEST)
    base_url = "https://api-test.pinkdoohub.cn/uploads/products"

    assert publisher._validate_rows(_placeholder_rows(), colors, base_url) == 221
    m8_placeholders = _placeholder_rows()
    for row, color in zip(m8_placeholders, colors):
        row.swatch_hex = color.hex
    assert publisher._validate_rows(m8_placeholders, colors, base_url) == 221
    assert publisher._validate_rows(_current_rows(base_url), colors, base_url) == 0

    conflicting = _placeholder_rows()
    conflicting[0].color_code = "OTHER"
    with pytest.raises(
        publisher.GateAMardPublishError,
        match="metadata conflicts",
    ):
        publisher._validate_rows(conflicting, colors, base_url)

    active_partial = _placeholder_rows()
    active_partial[0].is_active = True
    with pytest.raises(
        publisher.GateAMardPublishError,
        match="active bead color differs",
    ):
        publisher._validate_rows(active_partial, colors, base_url)


def test_image_publication_is_deterministic_public_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    colors = load_manifest(publisher.MANIFEST)
    monkeypatch.setattr(publisher, "STORAGE_ROOT", tmp_path)

    before = publisher._inspect_images(colors)
    created = publisher._publish_images(colors)
    after = publisher._inspect_images(colors)

    assert before[:3] == (221, 0, 128325)
    assert len(created) == 221
    assert after[:3] == (0, 221, 128325)
    assert before[3] == after[3]
    assert all(path.stat().st_mode & 0o777 == 0o644 for path in created)
    assert publisher._publish_images(colors) == ()

    first = tmp_path / colors[0].image_filename
    first.write_bytes(b"conflict")
    with pytest.raises(
        publisher.GateAMardPublishError,
        match="conflicting content",
    ):
        publisher._inspect_images(colors)


class _Transaction(AbstractAsyncContextManager[object]):
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


async def test_database_failure_removes_only_new_gatea_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    colors = load_manifest(publisher.MANIFEST)
    monkeypatch.setattr(publisher, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(publisher, "_base_url", lambda: "https://api/uploads/products")
    monkeypatch.setattr(publisher, "in_transaction", lambda: _Transaction())

    class FailingRepository:
        async def list_bead_colors_for_update(
            self,
            *,
            using_db: object,
        ) -> list[SimpleNamespace]:
            return _placeholder_rows()

        async def has_online_product_with_enabled_colors(
            self,
            *,
            using_db: object,
        ) -> bool:
            return False

        async def bulk_update_bead_colors(
            self,
            rows: list[SimpleNamespace],
            *,
            using_db: object,
        ) -> None:
            raise RuntimeError("injected database failure")

    plan = publisher.PublishPlan(
        colors=colors,
        manifest_sha256="a" * 64,
        database_changes=221,
        images_to_create=221,
        images_reused=0,
        total_image_bytes=sum(len(build_swatch_png(color.rgb)) for color in colors),
        image_set_sha256="b" * 64,
    )
    with pytest.raises(RuntimeError, match="injected database failure"):
        await publisher.apply_publish(FailingRepository(), plan)  # type: ignore[arg-type]

    assert list(tmp_path.iterdir()) == []


async def test_run_requires_exact_preview_manifest_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    colors = load_manifest(publisher.MANIFEST)
    plan = publisher.PublishPlan(
        colors=colors,
        manifest_sha256="a" * 64,
        database_changes=221,
        images_to_create=221,
        images_reused=0,
        total_image_bytes=128325,
        image_set_sha256="b" * 64,
    )

    async def fake_init(**kwargs: object) -> None:
        return None

    async def fake_close() -> None:
        return None

    async def fake_plan(repository: object) -> publisher.PublishPlan:
        return plan

    monkeypatch.setattr(publisher.Tortoise, "init", fake_init)
    monkeypatch.setattr(publisher.Tortoise, "close_connections", fake_close)
    monkeypatch.setattr(publisher, "ProductRepository", object)
    monkeypatch.setattr(publisher, "plan_publish", fake_plan)

    preview = await publisher.run(apply=False, confirmed_sha256=None)
    assert '"mode": "preview"' in preview
    with pytest.raises(
        publisher.GateAMardPublishError,
        match="exact preview manifest SHA-256",
    ):
        await publisher.run(apply=True, confirmed_sha256="c" * 64)
