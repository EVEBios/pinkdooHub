"""用官方 Nginx 镜像验证实际访问日志；不启动数据库、不读取真实凭据。"""

from __future__ import annotations

import http.client
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import time
import uuid

from scripts.release.gatea_resilience import inspect_log_text


ROOT = Path(__file__).resolve().parents[2]
IMAGE = "nginx:1.27.5-alpine"
TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"
QUERY = "fixture-query-must-not-be-logged"


def _run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"Log runtime fixture command failed: {args[0]}")
    return result.stdout + result.stderr if len(args) > 1 and args[1] == "logs" else result.stdout


def check_config(*, tls: bool) -> dict[str, object]:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker is required for the real log runtime check")
    name = "pinkdoo-log-check-" + uuid.uuid4().hex[:12]
    creation_attempted = False
    ownership = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="pinkdoo-log-check-") as temp:
        directory = Path(temp)
        cert = directory / "fullchain.pem"
        key = directory / "privkey.pem"
        if tls:
            _run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(key), "-out", str(cert), "-days", "1",
                 "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost")
        filename = "tls.conf.template" if tls else "loopback.conf"
        config = (ROOT / "deploy/gatea/nginx" / filename).read_text()
        (directory / "default.conf").write_text(config.replace("${GATEA_API_HOST}", "localhost"))
        # 与镜像默认 nginx.conf 一起加载，真实覆盖默认 main 日志继承。
        (directory / "upstream.conf").write_text(
            'server { listen 8000; access_log off; location / { '
            'if ($arg_status = 503) { return 503; } return 200 "{}"; } }\n'
        )
        args = [docker, "create", "--name", name, "--label", f"pinkdoo.log-check={ownership}", "--add-host", "app:127.0.0.1",
                "-p", "127.0.0.1::8080",
                "-v", f"{directory / 'default.conf'}:/etc/nginx/conf.d/default.conf:ro",
                "-v", f"{directory / 'upstream.conf'}:/etc/nginx/conf.d/upstream.conf:ro"]
        if tls:
            args += ["-p", "127.0.0.1::8443", "-v",
                     f"{directory}:/etc/letsencrypt/live/localhost:ro"]
        try:
            creation_attempted = True
            _run(*args, IMAGE)
            _run(docker, "start", name)
            metadata = json.loads(_run(docker, "inspect", name))[0]
            ports = metadata["NetworkSettings"]["Ports"]
            deadline = time.monotonic() + 20
            while True:
                try:
                    _run(docker, "exec", name, "nginx", "-t")
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.1)
            requests = 0
            for secure in ([False, True] if tls else [False]):
                port = int(ports["8443/tcp" if secure else "8080/tcp"][0]["HostPort"])
                for status in (200, 503):
                    if secure:
                        connection = http.client.HTTPSConnection(
                            "localhost", port, timeout=5,
                            context=ssl.create_default_context(cafile=str(cert)),
                        )
                    else:
                        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    try:
                        connection.request(
                            "GET", f"/api/v1/table-codes/{TOKEN}?probe={QUERY}&status={status}",
                            headers={"Host": "localhost", "Authorization": "Bearer fixture-authorization"},
                        )
                        response = connection.getresponse()
                        response.read()
                        expected = 308 if tls and not secure else status
                        if response.status != expected:
                            raise RuntimeError("Nginx fixture response differs from expected status")
                        requests += 1
                    finally:
                        connection.close()
            logs = _run(docker, "logs", name)
            scan = inspect_log_text(logs, (TOKEN, QUERY, "fixture-authorization"))
            if scan["exact_secret_matches"] or scan["forbidden_pattern_matches"]:
                raise RuntimeError("Nginx real access logs contain a fixture sensitive value")
            lines = [line for line in logs.splitlines() if "/api/v1/table-codes/" in line]
            if len(lines) != requests or any(
                "/api/v1/table-codes/<redacted>" not in line or "request_time=" not in line
                for line in lines
            ):
                raise RuntimeError("Nginx must emit exactly one redacted access line per request")
            return {"configuration": filename, "requests": requests, "scan": scan, "passed": True}
        finally:
            if creation_attempted:
                inspection = subprocess.run([docker, "inspect", name], capture_output=True, text=True, timeout=10)
                if inspection.returncode == 0:
                    owned = json.loads(inspection.stdout)[0]
                    if owned["Config"]["Labels"].get("pinkdoo.log-check") != ownership:
                        raise RuntimeError("Log runtime container ownership differs; cleanup refused")
                    if owned["State"]["Running"]:
                        _run(docker, "stop", "--time", "5", name)
                    _run(docker, "rm", name)
                elif inspection.returncode != 1 or "no such object" not in inspection.stderr.lower():
                    raise RuntimeError("Log runtime fixture cleanup state is unavailable")
                result = subprocess.run([docker, "inspect", name], capture_output=True, text=True, timeout=10)
                if result.returncode != 1 or "no such object" not in result.stderr.lower():
                    raise RuntimeError("Log runtime fixture container cleanup was not verified")


def main() -> None:
    results = [check_config(tls=False), check_config(tls=True)]
    print(json.dumps({"checks": results, "production_secrets_used": False,
                      "persistent_gatea_touched": False, "cleanup_verified": True}))


if __name__ == "__main__":
    main()
