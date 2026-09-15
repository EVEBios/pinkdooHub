"""快速源码门槛必须读取真实 Git 树，拒绝业务迁移超出发布器能力。"""
from pathlib import Path

import pytest

from scripts.ci import check_gatea_source_contract as contract


def test_current_git_tree_matches_release_contract():
    report = contract.check(Path(__file__).resolve().parents[2])
    assert report["migration_count"] == 10
    assert report["operations_git_mode"] == "100755"
    assert report["operations_extracted_mode"] == "0755"
    assert report["deployment_evidence"] is False


def test_new_migration_is_rejected_without_executing_candidate(monkeypatch):
    original = contract._git
    def git(repository, *arguments):
        output = original(repository, *arguments)
        if arguments[:3] == ("ls-tree", "-r", "--name-only"):
            output += "migrations/models/10_20990101000000_unapproved.py\n"
        return output
    monkeypatch.setattr(contract, "_git", git)
    with pytest.raises(contract.SourceContractError, match="exact M0-M9"):
        contract.check(Path(__file__).resolve().parents[2])


@pytest.mark.parametrize("source", (
    "A = B\nB = A", "A = __import__('os').getcwd()", "B = ()", "A = 'a' + 'b'",
))
def test_constant_reader_rejects_code_and_invalid_dependencies(source):
    with pytest.raises(ValueError):
        contract._constant(source, "A")


def test_constant_reader_resolves_only_requested_tuple():
    assert contract._constant("raise SystemExit(1)\nBASE = ('0',)\nA = BASE + ('1',)", "A") == ('0', '1')
