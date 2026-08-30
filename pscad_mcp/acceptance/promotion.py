"""Commit-aware promotion of program baseline acceptance evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..core.backend.base import BackendError
from .baseline import apply_scope_report, validate_program_baseline
from .evidence import _read_regular_report, index_explicit_reports


def _error(reason: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        "PROGRAM_PROMOTION_REJECTED",
        message,
        "acceptance",
        "promote_program_report",
        {"reason": reason, **details},
    )


def _git_reader(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "clean": not bool(run("status", "--porcelain")),
    }


def _report_sha256(path: str | Path) -> str:
    _resolved, raw, _identity = _read_regular_report(Path(path))
    return hashlib.sha256(raw).hexdigest()


def _ensure_report_hash(
    path: str | Path,
    expected_sha256: str,
    *,
    cause: BaseException | None = None,
) -> str:
    try:
        actual_sha256 = _report_sha256(path)
    except BackendError as read_error:
        raise _error(
            "report_hash_mismatch",
            "Selected report became unreadable during promotion.",
            expected=expected_sha256,
            actual=None,
        ) from read_error
    if actual_sha256 != expected_sha256:
        raise _error(
            "report_hash_mismatch",
            "Selected report changed during promotion.",
            expected=expected_sha256,
            actual=actual_sha256,
        ) from cause
    return actual_sha256


def _index_pinned_report(
    path: str | Path,
    expected_sha256: str,
) -> dict[str, Any]:
    try:
        indexed = index_explicit_reports([{"path": str(path)}])[0]
    except BackendError as error:
        _ensure_report_hash(path, expected_sha256, cause=error)
        raise
    if indexed["sha256"] != expected_sha256:
        raise _error(
            "report_hash_mismatch",
            "Selected report hash changed while it was being indexed.",
            expected=expected_sha256,
            actual=indexed["sha256"],
        )
    return indexed


def advance_and_apply_scope_report(
    baseline: Mapping[str, Any],
    report_path: str | Path,
    *,
    repository_commit: str,
    repository_branch: str,
    expected_scope: str,
    owner_work_package: str,
    explicit_exclusions: Sequence[str],
    expected_report_sha256: str | None = None,
) -> dict[str, Any]:
    current = validate_program_baseline(baseline)
    raw_hash = _report_sha256(report_path)
    if expected_report_sha256 is not None and raw_hash != expected_report_sha256:
        raise _error(
            "report_hash_mismatch",
            "Selected report hash does not match the expected hash.",
            expected=expected_report_sha256,
            actual=raw_hash,
        )
    indexed = _index_pinned_report(report_path, raw_hash)
    if indexed["status"] != "PASS":
        raise _error("report_not_pass", "Only PASS reports can be promoted.")
    if indexed["commit"] != repository_commit:
        raise _error(
            "commit_mismatch",
            "Selected report commit does not match the repository checkout.",
            report_commit=indexed["commit"],
            repository_commit=repository_commit,
        )
    if indexed["scope"] != expected_scope:
        raise _error(
            "scope_mismatch",
            "Selected report scope does not match the requested scope.",
            report_scope=indexed["scope"],
            expected_scope=expected_scope,
        )

    candidate = copy.deepcopy(current)
    candidate["repository"] = {
        **candidate["repository"],
        "base_commit": repository_commit,
        "branch": repository_branch,
        "worktree_clean": True,
    }
    reports_by_id = {item["run_id"]: item for item in candidate["reports"]}
    for scope in candidate["scopes"]:
        evidence_id = scope["evidence_run_id"]
        report = reports_by_id.get(evidence_id)
        if report is not None and report["commit"] != repository_commit:
            scope["licensed_status"] = "NOT_RUN_ON_CURRENT_COMMIT"
            scope["evidence_run_id"] = None
    candidate["generated_at_utc"] = indexed["generated_at_utc"]
    before_apply = copy.deepcopy(candidate)
    try:
        candidate = apply_scope_report(
            candidate,
            report_path,
            owner_work_package=owner_work_package,
        )
    except BackendError as error:
        _ensure_report_hash(report_path, raw_hash, cause=error)
        raise
    target_scope = next(
        item for item in candidate["scopes"] if item["scope"] == expected_scope
    )
    promoted = next(
        (
            item
            for item in candidate["reports"]
            if item["run_id"] == target_scope["evidence_run_id"]
        ),
        None,
    )
    expected_reports = {
        item["run_id"]: item for item in before_apply["reports"]
    }
    expected_reports[indexed["run_id"]] = indexed
    actual_reports = {item["run_id"]: item for item in candidate["reports"]}
    before_other_scopes = {
        item["scope"]: item
        for item in before_apply["scopes"]
        if item["scope"] != expected_scope
    }
    actual_other_scopes = {
        item["scope"]: item
        for item in candidate["scopes"]
        if item["scope"] != expected_scope
    }
    reindexed = _index_pinned_report(report_path, raw_hash)
    if (
        promoted is None
        or target_scope["licensed_status"] != "PASS"
        or promoted["run_id"] != indexed["run_id"]
        or promoted["sha256"] != raw_hash
        or actual_reports != expected_reports
        or actual_other_scopes != before_other_scopes
        or reindexed != indexed
    ):
        raise _error(
            "report_hash_mismatch",
            "Selected report changed during promotion.",
            expected=raw_hash,
            actual=promoted["sha256"] if promoted is not None else None,
        )
    for scope in candidate["scopes"]:
        if scope["scope"] == expected_scope:
            scope["explicit_exclusions"] = list(explicit_exclusions)
            break
    return validate_program_baseline(candidate)


def write_program_baseline(path: str | Path, payload: Mapping[str, Any]) -> Path:
    destination = Path(path)
    validated = validate_program_baseline(payload)
    raw = (
        json.dumps(validated, allow_nan=False, ensure_ascii=True, sort_keys=False, indent=2)
        + "\n"
    ).encode("ascii")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        raise
    return destination


def promote_program_report(
    baseline_path: str | Path,
    report_path: str | Path,
    *,
    expected_scope: str,
    owner_work_package: str,
    explicit_exclusions: Sequence[str],
    repository_root: str | Path | None = None,
    git_reader: Callable[[Path], Mapping[str, Any]] = _git_reader,
    expected_report_sha256: str | None = None,
) -> dict[str, Any]:
    baseline_file = Path(baseline_path)
    root = (Path(repository_root) if repository_root is not None else baseline_file.parents[2]).resolve()
    identity = dict(git_reader(root))
    if identity.get("clean") is not True:
        raise _error("worktree_not_clean", "Repository worktree must be clean.")
    if not identity.get("branch"):
        raise _error("detached_head", "Repository checkout must be on a named branch.")
    commit = str(identity["commit"])
    branch = str(identity["branch"])
    pinned_report_sha256 = expected_report_sha256 or _report_sha256(report_path)
    with baseline_file.open(encoding="utf-8") as stream:
        baseline = json.load(stream)
    updated = advance_and_apply_scope_report(
        baseline,
        report_path,
        repository_commit=commit,
        repository_branch=branch,
        expected_scope=expected_scope,
        owner_work_package=owner_work_package,
        explicit_exclusions=explicit_exclusions,
        expected_report_sha256=pinned_report_sha256,
    )
    confirmed = dict(git_reader(root))
    if (
        confirmed.get("clean") is not True
        or str(confirmed.get("commit") or "") != commit
        or str(confirmed.get("branch") or "") != branch
    ):
        raise _error(
            "checkout_changed",
            "Repository identity changed during promotion.",
            expected={"commit": commit, "branch": branch, "clean": True},
            observed={
                "commit": confirmed.get("commit"),
                "branch": confirmed.get("branch"),
                "clean": confirmed.get("clean"),
            },
        )
    _index_pinned_report(report_path, pinned_report_sha256)
    write_program_baseline(baseline_file, updated)
    return updated


__all__ = [
    "advance_and_apply_scope_report",
    "promote_program_report",
    "write_program_baseline",
]
