from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _tracked(pattern: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", pattern],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def test_repository_tracks_no_python_bytecode():
    assert _tracked("*.pyc") == []


def test_repository_tracks_no_cache_or_temporary_worktree_artifacts():
    forbidden_patterns = (
        "*__pycache__*",
        "*.pytest_cache*",
        "*.ruff_cache*",
        "*.mypy_cache*",
        ".worktrees/*",
    )

    tracked = {
        path
        for pattern in forbidden_patterns
        for path in _tracked(pattern)
    }

    assert tracked == set()


def test_repository_has_one_ci_workflow():
    assert _tracked(".github/workflows/*") == [".github/workflows/ci.yml"]


def test_ci_covers_declared_python_range_and_catalog_parity():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
        assert f'"{version}"' in workflow
    for required_text in (
        r"scripts\verify_package.ps1",
        "ruff check",
        "git ls-files",
        "*.pyc",
        "*__pycache__*",
        "*.pytest_cache*",
        "*.ruff_cache*",
        "*.mypy_cache*",
        ".worktrees/*",
    ):
        assert required_text in workflow
    assert "== 83" not in workflow
