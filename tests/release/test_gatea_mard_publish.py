"""Gate A MARD 221 preview/apply、持久图片和补偿契约。"""

from contextlib import AbstractAsyncContextManager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tasks import gatea_mard_publish as publisher
from app.tasks.mard_catalog import ManifestColor, build_swatch_png, load_manifest


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


def _configure_gatea(
    monkeypatch: pytest.MonkeyPatch,
    image_root: Path,
) -> str:
    base_url = "https://api-test.pinkdoohub.cn/uploads/products"
    monkeypatch.setattr(publisher, "STORAGE_ROOT", image_root)
    monkeypatch.setattr(
        publisher,
        "settings",
        SimpleNamespace(
            app_env="production",
            db_engine="mysql",
            product_image_upload_dir=str(image_root),
            product_image_base_url=base_url,
        ),
    )
    return base_url


def _current_plan(colors: tuple[ManifestColor, ...]) -> publisher.PublishPlan:
    images_to_create, images_reused, total_bytes, image_digest = (
        publisher._inspect_images(colors)
    )
    return publisher.PublishPlan(
        colors=colors,
        manifest_sha256="a" * 64,
        database_changes=0,
        images_to_create=images_to_create,
        images_reused=images_reused,
        total_image_bytes=total_bytes,
        image_set_sha256=image_digest,
    )


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


async def test_preview_allows_online_enabled_colors_only_for_exact_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    base_url = _configure_gatea(monkeypatch, image_root)
    colors = load_manifest(publisher.MANIFEST)
    publisher._publish_images(colors)

    class CurrentOnlineRepository:
        async def list_all_bead_colors(self) -> list[SimpleNamespace]:
            return _current_rows(base_url)

        async def has_online_product_with_enabled_colors(self) -> bool:
            return True

    plan = await publisher.plan_publish(CurrentOnlineRepository())  # type: ignore[arg-type]

    assert plan.already_current is True
    assert plan.database_changes == 0
    assert plan.images_to_create == 0
    assert plan.images_reused == 221


@pytest.mark.parametrize(
    ("database_current", "images_current"),
    ((False, True), (True, False)),
)
async def test_preview_rejects_online_enabled_colors_when_changes_are_needed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_current: bool,
    images_current: bool,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    base_url = _configure_gatea(monkeypatch, image_root)
    colors = load_manifest(publisher.MANIFEST)
    if images_current:
        publisher._publish_images(colors)

    class ChangedOnlineRepository:
        async def list_all_bead_colors(self) -> list[SimpleNamespace]:
            if database_current:
                return _current_rows(base_url)
            return _placeholder_rows()

        async def has_online_product_with_enabled_colors(self) -> bool:
            return True

    with pytest.raises(
        publisher.GateAMardPublishError,
        match="refuse catalog changes while an Online product enables colors",
    ):
        await publisher.plan_publish(ChangedOnlineRepository())  # type: ignore[arg-type]


@pytest.mark.parametrize("change_kind", ("database", "images"))
async def test_apply_rejects_online_reference_added_after_change_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    change_kind: str,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    base_url = _configure_gatea(monkeypatch, image_root)
    colors = load_manifest(publisher.MANIFEST)
    rows = (
        _placeholder_rows()
        if change_kind == "database"
        else _current_rows(base_url)
    )
    if change_kind == "database":
        publisher._publish_images(colors)
    online = False
    monkeypatch.setattr(publisher, "in_transaction", lambda: _Transaction())

    class Repository:
        async def list_all_bead_colors(self) -> list[SimpleNamespace]:
            return rows

        async def list_all_products_for_update(
            self,
            *,
            using_db: object,
        ) -> list[SimpleNamespace]:
            return []

        async def list_bead_colors_for_update(
            self,
            *,
            using_db: object,
        ) -> list[SimpleNamespace]:
            return rows

        async def has_online_product_with_enabled_colors(
            self,
            *,
            using_db: object | None = None,
        ) -> bool:
            return online

        async def bulk_update_bead_colors(
            self,
            *args: object,
            **kwargs: object,
        ) -> None:
            raise AssertionError("apply must fail before database writes")

    repository = Repository()
    plan = await publisher.plan_publish(repository)  # type: ignore[arg-type]
    assert plan.already_current is False
    online = True

    with pytest.raises(
        publisher.GateAMardPublishError,
        match="changed after preview while an Online product",
    ):
        await publisher.apply_publish(repository, plan)  # type: ignore[arg-type]

    if change_kind == "images":
        assert list(image_root.iterdir()) == []
    else:
        assert all(row.updated_at is None for row in rows)


class _Transaction(AbstractAsyncContextManager[object]):
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


async def test_noop_apply_revalidates_online_catalog_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    base_url = _configure_gatea(monkeypatch, image_root)
    colors = load_manifest(publisher.MANIFEST)
    publisher._publish_images(colors)
    plan = _current_plan(colors)
    rows = _current_rows(base_url)
    before_images = {
        path.name: (path.stat().st_mtime_ns, path.read_bytes())
        for path in image_root.iterdir()
    }
    calls: list[str] = []
    monkeypatch.setattr(publisher, "in_transaction", lambda: _Transaction())

    class CurrentOnlineRepository:
        async def list_all_products_for_update(
            self,
            *,
            using_db: object,
        ) -> list[SimpleNamespace]:
            calls.append("products")
            return []

        async def list_bead_colors_for_update(
            self,
            *,
            using_db: object,
        ) -> list[SimpleNamespace]:
            calls.append("bead_colors")
            return rows

        async def has_online_product_with_enabled_colors(
            self,
            *,
            using_db: object,
        ) -> bool:
            calls.append("online")
            return True

        async def bulk_update_bead_colors(
            self,
            *args: object,
            **kwargs: object,
        ) -> None:
            raise AssertionError("no-op apply must not update bead colors")

    assert (
        await publisher.apply_publish(  # type: ignore[arg-type]
            CurrentOnlineRepository(),
            plan,
        )
        == 0
    )

    assert calls == ["products", "bead_colors", "online"]
    assert all(row.updated_at is None for row in rows)
    assert {
        path.name: (path.stat().st_mtime_ns, path.read_bytes())
        for path in image_root.iterdir()
    } == before_images


@pytest.mark.parametrize(
    ("drift", "error_pattern"),
    (
        ("database", "changed after preview while an Online product"),
        ("missing_image", "changed after preview while an Online product"),
        ("conflicting_image", "conflicting content"),
    ),
)
async def test_noop_apply_fails_closed_on_preview_drift_with_online_colors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
    error_pattern: str,
) -> None:
    image_root = tmp_path / "images"
    image_root.mkdir()
    base_url = _configure_gatea(monkeypatch, image_root)
    colors = load_manifest(publisher.MANIFEST)
    publisher._publish_images(colors)
    plan = _current_plan(colors)
    rows = _current_rows(base_url)
    first_image = image_root / colors[0].image_filename
    if drift == "database":
        rows[0].color_code = None
        rows[0].name = None
        rows[0].swatch_image_url = None
        rows[0].is_active = False
    elif drift == "missing_image":
        first_image.unlink()
    else:
        first_image.write_bytes(b"conflict")
    monkeypatch.setattr(publisher, "in_transaction", lambda: _Transaction())

    class DriftedOnlineRepository:
        async def list_all_products_for_update(
            self,
            *,
            using_db: object,
        ) -> list[SimpleNamespace]:
            return []

        async def list_bead_colors_for_update(
            self,
            *,
            using_db: object,
        ) -> list[SimpleNamespace]:
            return rows

        async def has_online_product_with_enabled_colors(
            self,
            *,
            using_db: object,
        ) -> bool:
            return True

        async def bulk_update_bead_colors(
            self,
            *args: object,
            **kwargs: object,
        ) -> None:
            raise AssertionError("drifted no-op apply must not update bead colors")

    with pytest.raises(publisher.GateAMardPublishError, match=error_pattern):
        await publisher.apply_publish(  # type: ignore[arg-type]
            DriftedOnlineRepository(),
            plan,
        )

    if drift == "missing_image":
        assert not first_image.exists()
    elif drift == "conflicting_image":
        assert first_image.read_bytes() == b"conflict"


async def test_database_failure_removes_only_new_gatea_images(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    colors = load_manifest(publisher.MANIFEST)
    monkeypatch.setattr(publisher, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(publisher, "_base_url", lambda: "https://api/uploads/products")
    monkeypatch.setattr(publisher, "in_transaction", lambda: _Transaction())

    class FailingRepository:
        async def list_all_products_for_update(
            self,
            *,
            using_db: object,
        ) -> list[SimpleNamespace]:
            return []

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
