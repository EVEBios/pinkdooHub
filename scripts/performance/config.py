"""Immutable naming and safety checks for local performance runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import socket
from typing import Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = Path("/tmp/pinkdoohub-performance")
ARTIFACT_ROOT = REPOSITORY_ROOT / "backups" / "performance"
COMPOSE_FILE = REPOSITORY_ROOT / "deploy" / "performance" / "compose.yml"
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}t[0-9]{6}$")
PROJECT_PREFIX = "pinkdoohub-performance-"
DATABASE_NAME = "pinkdoohub_performance"
DATABASE_USER = "pinkdoo_performance"
DEFAULT_HTTP_PORT = 18083
DEFAULT_CPUSET = "0-1"
DEFAULT_BANDWIDTH = "5mbit"
DEFAULT_BURST = "128kbit"
DEFAULT_LATENCY = "400ms"
MAX_WRITE_JOURNEYS_PER_RUN = 3_000
SECRET_NAMES = (
    "mysql_app_password",
    "mysql_root_password",
    "redis_password",
    "jwt_secret",
    "persona_password",
)


class PerformanceConfigError(RuntimeError):
    """Configuration error that never contains a secret value."""


@dataclass(frozen=True, slots=True)
class PerformanceRunConfig:
    """All names and paths owned by one disposable run."""

    run_id: str
    http_port: int = DEFAULT_HTTP_PORT
    cpuset: str = DEFAULT_CPUSET
    bandwidth: str = DEFAULT_BANDWIDTH
    burst: str = DEFAULT_BURST
    latency: str = DEFAULT_LATENCY

    @property
    def project(self) -> str:
        return f"{PROJECT_PREFIX}{self.run_id}"

    @property
    def workspace(self) -> Path:
        return WORKSPACE_ROOT / self.run_id

    @property
    def secret_dir(self) -> Path:
        return self.workspace / "secrets"

    @property
    def raw_evidence_dir(self) -> Path:
        return self.workspace / "evidence"

    @property
    def artifact_dir(self) -> Path:
        return ARTIFACT_ROOT / self.run_id

    @property
    def app_image(self) -> str:
        return f"pinkdoohub-performance-app:{self.run_id}"

    @property
    def shaper_image(self) -> str:
        return f"pinkdoohub-performance-shaper:{self.run_id}"

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.http_port}"

    @property
    def compose_env_path(self) -> Path:
        return self.workspace / "compose.env"

    def compose_environment(self) -> dict[str, str]:
        """Return the complete non-secret Compose interpolation environment."""

        return {
            "PERF_APP_IMAGE": self.app_image,
            "PERF_BANDWIDTH": self.bandwidth,
            "PERF_BURST": self.burst,
            "PERF_COMPOSE_PROJECT": self.project,
            "PERF_CPUSET": self.cpuset,
            "PERF_DATABASE_NAME": DATABASE_NAME,
            "PERF_DATABASE_USER": DATABASE_USER,
            "PERF_HTTP_PORT": str(self.http_port),
            "PERF_LATENCY": self.latency,
            "PERF_RUN_ID": self.run_id,
            "PERF_SECRET_DIR": str(self.secret_dir),
            "PERF_SHAPER_IMAGE": self.shaper_image,
        }

    def safe_summary(self) -> dict[str, object]:
        """Return identifiers that are safe to persist in a report."""

        return {
            "app_image": self.app_image,
            "bandwidth": self.bandwidth,
            "base_url": self.base_url,
            "burst": self.burst,
            "cpuset": self.cpuset,
            "database_name": DATABASE_NAME,
            "http_port": self.http_port,
            "latency": self.latency,
            "project": self.project,
            "run_id": self.run_id,
            "secret_categories": list(SECRET_NAMES),
            "shaper_image": self.shaper_image,
            "workspace": str(self.workspace),
        }


def config_for_run(
    run_id: str,
    *,
    http_port: int = DEFAULT_HTTP_PORT,
    cpuset: str = DEFAULT_CPUSET,
) -> PerformanceRunConfig:
    """Build a config only from strict, non-ambiguous identifiers."""

    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise PerformanceConfigError(
            "run ID must use lowercase YYYYMMDDtHHMMSS"
        )
    try:
        datetime.strptime(run_id, "%Y%m%dt%H%M%S")
    except ValueError as error:
        raise PerformanceConfigError("run ID is not a valid timestamp") from error
    if not 1024 <= http_port <= 65535:
        raise PerformanceConfigError("HTTP port must be between 1024 and 65535")
    if http_port in (3306, 6379, 8000):
        raise PerformanceConfigError("default or developer service port is forbidden")
    match = re.fullmatch(r"([0-9]+)-([0-9]+)", cpuset)
    if match is None or int(match.group(2)) != int(match.group(1)) + 1:
        raise PerformanceConfigError(
            "cpuset must identify exactly two consecutive CPUs"
        )

    for root, label in (
        (WORKSPACE_ROOT, "workspace"),
        (ARTIFACT_ROOT, "artifact"),
    ):
        if root.is_symlink():
            raise PerformanceConfigError(f"performance {label} root must not be a symlink")

    config = PerformanceRunConfig(
        run_id=run_id,
        http_port=http_port,
        cpuset=cpuset,
    )
    workspace = config.workspace.resolve()
    artifact = config.artifact_dir.resolve()
    if not workspace.is_relative_to(WORKSPACE_ROOT.resolve()):
        raise PerformanceConfigError("run workspace escaped its private root")
    if not artifact.is_relative_to(ARTIFACT_ROOT.resolve()):
        raise PerformanceConfigError("artifact path escaped its repository root")
    return config


def port_is_available(port: int) -> bool:
    """Reject active/bound owners while allowing a released TIME_WAIT socket."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        # This mirrors a normal server restart: TIME_WAIT from completed
        # connections is not an active owner.  bind still rejects an active
        # listener and any bound non-listening socket without probing the service.
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def write_private(path: Path, value: str) -> None:
    """Create a new 0600 file and refuse replacement."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
        if not value.endswith("\n"):
            stream.write("\n")


def content_digest(paths: Iterable[Path]) -> str:
    """Hash path names, modes and bytes deterministically."""

    digest = hashlib.sha256()
    normalized: list[Path] = []
    for candidate in paths:
        if candidate.is_dir():
            normalized.extend(
                path
                for path in candidate.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix not in {".pyc", ".pyo"}
            )
        elif candidate.is_file():
            normalized.append(candidate)
        else:
            raise PerformanceConfigError("a digest input path is unavailable")
    for path in sorted(set(normalized)):
        resolved = path.resolve()
        if not resolved.is_relative_to(REPOSITORY_ROOT.resolve()):
            raise PerformanceConfigError("a digest input escaped the repository")
        relative = resolved.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f"{path.stat().st_mode & 0o777:o}".encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()
