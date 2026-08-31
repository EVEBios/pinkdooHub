"""Phase 9.2.3 GitHub Actions 基础门槛契约。"""

import json
from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
MINIAPP_PACKAGE_PATH = REPOSITORY_ROOT / "miniapp" / "package.json"
EXPECTED_JOBS = {
    "backend-sqlite",
    "backend-mysql-release",
    "frontend-quality",
    "openapi-contract",
    "weapp-build",
    "repository-hygiene",
    "python-dependency-audit",
    "npm-dependency-audit",
}


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _top_level_job_names(workflow: str) -> set[str]:
    jobs_section = workflow.split("\njobs:\n", maxsplit=1)[1]
    return set(re.findall(r"^  ([a-z][a-z0-9-]+):$", jobs_section, re.MULTILINE))


def test_workflow_has_only_the_frozen_9_2_5_jobs_and_safe_triggers() -> None:
    workflow = _workflow_text()

    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request_target:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert _top_level_job_names(workflow) == EXPECTED_JOBS
    assert "dependency-audit" not in _top_level_job_names(workflow)


def test_dependency_audit_jobs_fail_closed_and_save_raw_evidence() -> None:
    workflow = _workflow_text()

    assert "pip-audit==2.10.1" in workflow
    assert "python scripts/ci/check_python_audit.py" in workflow
    assert "security/dependency_audit/python-policy.json" in workflow
    assert "artifacts/python-audit.json" in workflow
    assert "artifacts/python-audit-policy.json" in workflow
    assert "npm audit --omit=dev --json" in workflow
    assert "node ../scripts/ci/check_npm_audit.mjs" in workflow
    assert "security/dependency_audit/npm-policy.json" in workflow
    assert "artifacts/npm-audit.json" in workflow
    assert "artifacts/npm-audit-policy.json" in workflow
    assert "registry=https://registry.npmjs.org/" in workflow
    assert "audit fix" not in workflow
    assert "--force" not in workflow


def test_workflow_uses_exact_toolchains_and_current_official_actions() -> None:
    workflow = _workflow_text()

    assert "PYTHON_VERSION: '3.10.9'" in workflow
    assert "NODE_VERSION: '24.13.0'" in workflow
    assert "NPM_VERSION: '11.6.2'" in workflow
    assert "PIP_VERSION: '26.2.1'" in workflow
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/setup-node@v7" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "--outputFile=../artifacts/frontend-jest.json" in workflow


def test_mysql_release_job_uses_disposable_non_default_mysql_and_real_migrations() -> None:
    workflow = _workflow_text()

    assert "image: mysql:8.0.46" in workflow
    assert "13306:3306" in workflow
    assert not re.search(r"^\s*-\s*3306:3306\s*$", workflow, re.MULTILINE)
    assert "INVENTORY_MYSQL_TEST_HOST: 127.0.0.1" in workflow
    assert "INVENTORY_MYSQL_TEST_PORT: '13306'" in workflow
    assert "INVENTORY_MYSQL_TEST_DB: pinkdoohub_inventory_4311_ci" in workflow
    assert "python scripts/ci/check_mysql_gate.py preflight" in workflow
    assert "aerich --app models upgrade" in workflow
    assert "python scripts/ci/check_mysql_gate.py snapshot" in workflow
    assert "python -m pytest tests/inventory/mysql -q" in workflow
    assert "--fake" not in workflow
    assert "init-db" not in workflow
    assert "generate_schemas" not in workflow


def test_mysql_release_job_always_cleans_up_and_saves_evidence() -> None:
    workflow = _workflow_text()

    assert "MYSQL_SERVICE_CONTAINER_ID: ${{ job.services.mysql.id }}" in workflow
    assert "python scripts/ci/check_mysql_gate.py cleanup" in workflow
    assert "if: always()" in workflow
    assert "artifacts/mysql-release.json" in workflow
    assert "artifacts/mysql-cleanup.json" in workflow
    assert "artifacts/backend-mysql-release.xml" in workflow
    assert "backend-mysql-release-${{ github.sha }}-${{ github.run_id }}" in workflow


def test_workflow_keeps_the_weapp_artifact_non_release_and_traceable() -> None:
    workflow = _workflow_text()

    assert "TARO_APP_API_ORIGIN: https://api.ci.pinkdoohub.test" in workflow
    assert "WEAPP_RELEASE_ELIGIBLE: '0'" in workflow
    assert "npm ci --include=dev --legacy-peer-deps" in workflow
    assert "set -o pipefail" in workflow
    assert "mkdir -p dist" in workflow
    assert "npm run build:weapp" in workflow
    assert "npm run build:weapp:check" in workflow
    assert "github.sha" in workflow
    assert "github.run_id" in workflow
    assert "dist/weapp-manifest.json" in workflow
    assert "dist/weapp-manifest.sha256" in workflow
    assert "upload" not in workflow.lower().replace("upload-artifact", "")
    assert "deploy" not in workflow.lower()


def test_package_exposes_ci_policy_and_weapp_check_commands() -> None:
    package = json.loads(MINIAPP_PACKAGE_PATH.read_text(encoding="utf-8"))

    assert package["scripts"]["ci:test"].startswith("node --test ")
    assert package["scripts"]["build:weapp:check"] == (
        "node ../scripts/ci/check_weapp_artifact.mjs "
        "--artifact-root dist/weapp --project-config project.config.json "
        "--manifest dist/weapp-manifest.json"
    )
    assert "rmSync('dist/weapp'" in package["scripts"]["build:weapp"]
