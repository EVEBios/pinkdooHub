"""Phase 9.3 Restore App Smoke 的 Secret 失败边界。"""

import pytest

from app.tasks import phase93_restore_smoke as restore_smoke


def test_restore_smoke_refuses_missing_rotated_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        restore_smoke,
        "ROTATED_PASSWORD_PATH",
        tmp_path / "missing",
    )

    with pytest.raises(restore_smoke.RestoreSmokeError):
        restore_smoke.run()
