"""隔离演练不得接管已有资源、伪装 CI 或清理不属于本轮的目录。"""

import json
from pathlib import Path

import pytest

from scripts.ci import gatea_m9_m15_drill as drill


@pytest.mark.parametrize("profile,change", (("ci", None), ("local", None), ("ci", "self-hosted"),
    ("local", "daemon-id"), ("local", "label"), ("local", "name"), ("ci", "resources"), ("local", "endpoint")))
def test_host_requires_real_ci_or_exact_private_daemon(monkeypatch, profile, change):
    monkeypatch.setenv(drill.SENTINEL, "disposable-only-v1")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted" if change == "self-hosted" else "github-hosted")
    monkeypatch.delenv("DOCKER_HOST", raising=False); monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(drill.os, "geteuid", lambda: 0)
    monkeypatch.setattr(drill.platform, "system", lambda: "Linux")
    monkeypatch.setattr(drill.candidate, "_require_root_file", lambda *args: None)
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: json.dumps({"daemon_id": "private-id", "name": "pinkdoo-m15-private-test"}))
    info = {"ID": "private-id", "Name": "pinkdoo-m15-private-test", "OSType": "linux",
            "Labels": ["com.pinkdoohub.disposable=m15"]}
    if change == "daemon-id": info["ID"] = "another-daemon"
    if change == "label": info["Labels"] = []
    if change == "name": info["Name"] = "production"
    def checked(*args, **kwargs):
        if args[1:] == ("context", "show"): return "default"
        if args[1] == "context": return "tcp://remote:2375" if change == "endpoint" else "unix:///var/run/docker.sock"
        return json.dumps(info)
    monkeypatch.setattr(drill, "checked", checked)
    monkeypatch.setattr(drill.shared, "docker_inventory", lambda _: {"containers": ["existing"] if change == "resources" else []})
    monkeypatch.setattr(drill.shared, "_port_available", lambda _: True)
    if change:
        with pytest.raises(drill.shared.DrillError): drill.validate_host(profile, clean=True)
    else: drill.validate_host(profile, clean=True)


@pytest.mark.parametrize("change", (None, "inside-workspace", "invalid-run"))
def test_paths_bind_run_and_keep_cleanup_outside_checkout(monkeypatch, tmp_path, change):
    root = tmp_path / "checkout"; root.mkdir()
    monkeypatch.setattr(drill, "ROOT", root)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(root))
    monkeypatch.setenv("RUNNER_TEMP", str(root / "temp" if change == "inside-workspace" else tmp_path / "temp"))
    monkeypatch.setenv("GITHUB_RUN_ID", "../other" if change == "invalid-run" else "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    if change:
        with pytest.raises(drill.shared.DrillError): drill.paths()
    else:
        p = drill.paths()
        assert p.work_root == tmp_path / "temp/pinkdoohub-gatea-m9-m15-123-1"
        assert not p.artifact_dir.is_relative_to(p.work_root)


def test_local_rehearsal_cannot_be_presented_as_ci_artifact(tmp_path):
    from tests.release.test_gatea_m15_artifact import artifact_records, write_artifact
    files = artifact_records()
    files["summary.json"]["scope"] = drill.SCOPES["local"]
    path = tmp_path / "local.zip"
    write_artifact(path, files)
    with pytest.raises(drill.candidate.GateACandidateError):
        drill.candidate._validate_ci_artifact(path, target_sha="a" * 40, source_head_sha="b" * 40,
            run_id="123", run_attempt=1, target_version=15)


def test_cleanup_rejects_mismatched_owner_before_docker_or_filesystem(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(drill, "validate_host", lambda *args, **kwargs: None)
    monkeypatch.setattr(drill, "paths", lambda: SimpleNamespace(work_root=tmp_path / "owned"))
    monkeypatch.setattr(drill.candidate, "_load_json", lambda *args, **kwargs: {"work_root": str(tmp_path / "another")})
    monkeypatch.setattr(drill.shared, "_remove_exact_resources", lambda _: pytest.fail("must reject before Docker cleanup"))
    with pytest.raises(drill.shared.DrillError, match="ownership"):
        drill.cleanup(SimpleNamespace(target_sha="a" * 40), "local")
