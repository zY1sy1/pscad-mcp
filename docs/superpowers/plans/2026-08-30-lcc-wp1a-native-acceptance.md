# LCC WP1A Native Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce and promote a current-commit licensed `simulated/PASS` report for the existing blank/native LCC builder without changing its electrical model.

**Architecture:** Keep `BlankLccBuilderService` as the only project lifecycle implementation. Add a native LCC acceptance orchestrator that writes a strict external report, plus a generic explicit promotion helper that advances program-baseline commit truth and applies only the named scope after a separate operator action.

**Tech Stack:** Python 3.10+, asyncio, dataclasses, JSON/SHA-256, existing PSCAD 4.6.2 Legacy backend, WP0 acceptance package, pytest, PowerShell.

---

## Scope Boundaries

This plan implements only WP1A. It must not:

- edit the official LCC template, installed `master.pslx`, or compiler files;
- alter LCC topology, controls, component parameters, or waveform algorithms;
- promote `lcc.master_bindings`, `lcc.fixed_autonomous`, `lcc.parametric`, or MMC scopes;
- claim `accepted` or independent-golden evidence;
- run promotion implicitly inside the licensed `run` action;
- reuse the historical blank LCC journal as current evidence.

## File Map

- Create `pscad_mcp/acceptance/promotion.py`: commit advancement, stale-evidence invalidation, scoped report application, atomic baseline write.
- Modify `pscad_mcp/acceptance/__init__.py`: export promotion APIs.
- Create `pscad_mcp/hvdc/builders/lcc/native_acceptance.py`: strict report schema and licensed orchestration.
- Create `pscad_mcp/hvdc/builders/lcc/native_acceptance_cli.py`: explicit `run` and `promote` actions.
- Modify `pscad_mcp/hvdc/builders/lcc/native_template.py`: add observed channel identity to existing verdict evidence without changing thresholds.
- Create `scripts/run_blank_lcc_native_acceptance.ps1`: clean-commit licensed runner.
- Create `tests/test_program_baseline_promotion.py`: commit/scope/promotion regression tests.
- Create `tests/test_lcc_native_acceptance.py`: report and fake-service orchestration tests.
- Create `tests/test_lcc_native_acceptance_cli.py`: CLI and PowerShell contract tests.
- Create `tests/test_lcc_native_acceptance_real.py`: opt-in PSCAD 4.6.2 gate.
- Modify `tests/test_lcc_native_template.py`: channel path/unit/domain/sample evidence regression.
- Modify `tests/test_lcc_mmc_program_baseline.py`: current native scope assertions after promotion.
- Modify `docs/acceptance/lcc-mmc-program-baseline.json`: only after a licensed PASS and explicit promotion.
- Modify `README.md` and `docs/zh-CN/README.md`: document report/promotion workflow after PASS.
- Modify `docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md`: record WP1A completion only after all gates pass.

## Shared Constants

Use these exact identities throughout:

```python
NATIVE_SCOPE = "lcc.blank_native"
NATIVE_BUILDER_PATH = "lcc.blank_native"
NATIVE_KIND = "licensed_simulation"
NATIVE_CAPABILITY = "simulated"
NATIVE_OWNER = "WP1"
NATIVE_EXCLUSIONS = (
    "fixed_autonomous",
    "parametric_lcc",
    "independent_golden",
    "final_accepted",
)
SUCCESS_HISTORY = (
    "validated",
    "staging_created",
    "compiled",
    "simulated",
    "acceptance_passed",
    "published",
)
REQUIRED_CHECKS = (
    "disturbance",
    "failure_indication",
    "bounded_dc_response",
    "recovered",
)
```

### Task 1: Commit-Aware Program Baseline Promotion

**Files:**
- Create: `pscad_mcp/acceptance/promotion.py`
- Modify: `pscad_mcp/acceptance/__init__.py`
- Test: `tests/test_program_baseline_promotion.py`

- [ ] **Step 1: Write failing promotion tests**

Create `tests/test_program_baseline_promotion.py`:

```python
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from tests.test_lcc_mmc_program_baseline import valid_baseline


OLD_COMMIT = "dadd739e2abc14dcc7de73149da7fd7f0c0ca763"
NEW_COMMIT = "a" * 40
EXCLUSIONS = (
    "fixed_autonomous",
    "parametric_lcc",
    "independent_golden",
    "final_accepted",
)


def baseline_with_blank_scope() -> dict[str, object]:
    baseline = valid_baseline()
    baseline["scopes"].append(
        {
            "scope": "lcc.blank_native",
            "builder_path": "lcc.blank_native",
            "owner_work_package": "WP1",
            "capability_state": "simulated",
            "licensed_status": "NOT_RUN_ON_CURRENT_COMMIT",
            "evidence_run_id": None,
            "explicit_exclusions": ["current_commit_acceptance"],
        }
    )
    return baseline


def write_report(path: Path, *, status: str = "PASS", commit: str = NEW_COMMIT) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "native-run-1",
                "scope": "lcc.blank_native",
                "builder_path": "lcc.blank_native",
                "kind": "licensed_simulation",
                "capability_state": "simulated" if status == "PASS" else "failed",
                "commit": commit,
                "generated_at_utc": "2026-08-30T01:00:00Z",
                "status": status,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def test_promotion_advances_commit_invalidates_old_pass_and_updates_only_target(tmp_path):
    from pscad_mcp.acceptance.promotion import advance_and_apply_scope_report

    baseline = baseline_with_blank_scope()
    original = copy.deepcopy(baseline)
    report = write_report(tmp_path / "report.json")

    updated = advance_and_apply_scope_report(
        baseline,
        report,
        repository_commit=NEW_COMMIT,
        repository_branch="codex/lcc-wp1a-native-acceptance",
        expected_scope="lcc.blank_native",
        owner_work_package="WP1",
        explicit_exclusions=EXCLUSIONS,
    )

    scopes = {item["scope"]: item for item in updated["scopes"]}
    assert baseline == original
    assert updated["repository"]["base_commit"] == NEW_COMMIT
    assert scopes["lcc.master_bindings"]["licensed_status"] == "NOT_RUN_ON_CURRENT_COMMIT"
    assert scopes["lcc.master_bindings"]["evidence_run_id"] is None
    assert scopes["lcc.blank_native"]["licensed_status"] == "PASS"
    assert scopes["lcc.blank_native"]["capability_state"] == "simulated"
    assert scopes["lcc.blank_native"]["explicit_exclusions"] == list(EXCLUSIONS)


@pytest.mark.parametrize(
    ("status", "commit", "scope", "reason"),
    [
        ("FAIL", NEW_COMMIT, "lcc.blank_native", "report_not_pass"),
        ("PASS", OLD_COMMIT, "lcc.blank_native", "commit_mismatch"),
        ("PASS", NEW_COMMIT, "lcc.parametric", "scope_mismatch"),
    ],
)
def test_promotion_rejects_fail_historical_and_cross_scope_reports(
    tmp_path, status, commit, scope, reason
):
    from pscad_mcp.acceptance.promotion import advance_and_apply_scope_report

    report = write_report(tmp_path / "report.json", status=status, commit=commit)
    if scope != "lcc.blank_native":
        payload = json.loads(report.read_text(encoding="utf-8"))
        payload["scope"] = scope
        payload["builder_path"] = scope
        report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackendError) as failure:
        advance_and_apply_scope_report(
            baseline_with_blank_scope(),
            report,
            repository_commit=NEW_COMMIT,
            repository_branch="codex/lcc-wp1a-native-acceptance",
            expected_scope="lcc.blank_native",
            owner_work_package="WP1",
            explicit_exclusions=EXCLUSIONS,
        )

    assert failure.value.code == "PROGRAM_PROMOTION_REJECTED"
    assert failure.value.details["reason"] == reason


def test_promote_program_report_requires_clean_exact_checkout(monkeypatch, tmp_path):
    from pscad_mcp.acceptance.promotion import promote_program_report

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline_with_blank_scope()), encoding="utf-8")
    report = write_report(tmp_path / "report.json")

    with pytest.raises(BackendError) as failure:
        promote_program_report(
            baseline_path,
            report,
            expected_scope="lcc.blank_native",
            owner_work_package="WP1",
            explicit_exclusions=EXCLUSIONS,
            git_reader=lambda root: {
                "commit": NEW_COMMIT,
                "branch": "codex/lcc-wp1a-native-acceptance",
                "clean": False,
            },
        )

    assert failure.value.details["reason"] == "worktree_not_clean"


def test_promotion_rejects_report_hash_selected_before_domain_validation(tmp_path):
    from pscad_mcp.acceptance.promotion import advance_and_apply_scope_report

    report = write_report(tmp_path / "report.json")
    with pytest.raises(BackendError) as failure:
        advance_and_apply_scope_report(
            baseline_with_blank_scope(),
            report,
            repository_commit=NEW_COMMIT,
            repository_branch="codex/lcc-wp1a-native-acceptance",
            expected_scope="lcc.blank_native",
            owner_work_package="WP1",
            explicit_exclusions=EXCLUSIONS,
            expected_report_sha256="f" * 64,
        )
    assert failure.value.details["reason"] == "report_hash_mismatch"
```

- [ ] **Step 2: Run promotion tests and verify RED**

Run:

```powershell
pytest -q tests/test_program_baseline_promotion.py
```

Expected: collection fails because `pscad_mcp.acceptance.promotion` does not exist.

- [ ] **Step 3: Implement commit advancement and scoped promotion**

Create `pscad_mcp/acceptance/promotion.py`:

```python
"""Explicit, commit-aware promotion of durable reports into program truth."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..core.backend.base import BackendError
from .baseline import apply_scope_report, validate_program_baseline
from .evidence import index_explicit_reports


def _error(reason: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        "PROGRAM_PROMOTION_REJECTED",
        message,
        "acceptance",
        "promote_program_report",
        {"reason": reason, **details},
    )


def _git_reader(root: Path) -> dict[str, object]:
    def read(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    return {
        "commit": read("rev-parse", "HEAD"),
        "branch": read("branch", "--show-current"),
        "clean": not read("status", "--porcelain"),
    }


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
    indexed = index_explicit_reports([{"path": str(report_path)}])[0]
    expected_hash = expected_report_sha256 or indexed["sha256"]
    if indexed["sha256"] != expected_hash:
        raise _error("report_hash_mismatch", "Report hash changed before promotion.")
    if indexed["status"] != "PASS":
        raise _error("report_not_pass", "Only a PASS report can update program truth.")
    if indexed["commit"] != repository_commit:
        raise _error("commit_mismatch", "Report and checkout commits differ.")
    if indexed["scope"] != expected_scope:
        raise _error("scope_mismatch", "Report scope is not the requested promotion scope.")

    candidate = copy.deepcopy(current)
    candidate["repository"] = {
        "base_commit": repository_commit,
        "branch": repository_branch,
        "worktree_clean": True,
    }
    reports = {item["run_id"]: item for item in candidate["reports"]}
    for scope in candidate["scopes"]:
        evidence_run_id = scope["evidence_run_id"]
        evidence = reports.get(evidence_run_id) if evidence_run_id else None
        if evidence is not None and evidence["commit"] != repository_commit:
            scope["licensed_status"] = "NOT_RUN_ON_CURRENT_COMMIT"
            scope["evidence_run_id"] = None
    candidate["generated_at_utc"] = indexed["generated_at_utc"]
    candidate = validate_program_baseline(candidate)
    updated = apply_scope_report(
        candidate,
        report_path,
        owner_work_package=owner_work_package,
    )
    promoted = next(item for item in updated["reports"] if item["run_id"] == indexed["run_id"])
    if promoted["sha256"] != expected_hash:
        raise _error("report_hash_mismatch", "Report hash changed during promotion.")
    for scope in updated["scopes"]:
        if scope["scope"] == expected_scope:
            scope["explicit_exclusions"] = [str(value) for value in explicit_exclusions]
    return validate_program_baseline(updated)


def write_program_baseline(path: Path, payload: Mapping[str, Any]) -> Path:
    normalized = validate_program_baseline(payload)
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=False,
        indent=2,
    ).encode("ascii") + b"\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def promote_program_report(
    baseline_path: Path,
    report_path: Path,
    *,
    expected_scope: str,
    owner_work_package: str,
    explicit_exclusions: Sequence[str],
    repository_root: Path | None = None,
    git_reader: Callable[[Path], Mapping[str, Any]] = _git_reader,
    expected_report_sha256: str | None = None,
) -> dict[str, Any]:
    root = (repository_root or baseline_path.parents[2]).resolve()
    git = dict(git_reader(root))
    if git.get("clean") is not True:
        raise _error("worktree_not_clean", "Promotion requires a clean worktree.")
    commit = str(git.get("commit") or "")
    branch = str(git.get("branch") or "")
    if not branch:
        raise _error("detached_head", "Promotion requires a named branch.")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    updated = advance_and_apply_scope_report(
        baseline,
        report_path,
        repository_commit=commit,
        repository_branch=branch,
        expected_scope=expected_scope,
        owner_work_package=owner_work_package,
        explicit_exclusions=explicit_exclusions,
        expected_report_sha256=expected_report_sha256,
    )
    write_program_baseline(baseline_path, updated)
    return updated
```

Export `advance_and_apply_scope_report`, `promote_program_report`, and
`write_program_baseline` from `pscad_mcp/acceptance/__init__.py`.

- [ ] **Step 4: Run promotion tests and lint**

Run:

```powershell
pytest -q tests/test_program_baseline_promotion.py tests/test_lcc_mmc_program_baseline.py
ruff check pscad_mcp/acceptance tests/test_program_baseline_promotion.py
```

Expected: all pass.

- [ ] **Step 5: Commit promotion infrastructure**

```powershell
git add pscad_mcp/acceptance tests/test_program_baseline_promotion.py
git commit -m "feat: add commit-aware program evidence promotion"
```

### Task 2: Strict Native LCC Acceptance Report

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/native_acceptance.py`
- Test: `tests/test_lcc_native_acceptance.py`

- [ ] **Step 1: Write failing report-contract tests**

Create `tests/test_lcc_native_acceptance.py` with the report fixture and schema tests:

```python
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from pscad_mcp.core.backend.base import BackendError


COMMIT = "a" * 40
HASH = "b" * 64
PREFLIGHT_SNAPSHOT = {"status": "PASS", "checks": {"repository": "PASS"}}
PREFLIGHT_HASH = hashlib.sha256(
    json.dumps(
        PREFLIGHT_SNAPSHOT,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()
SUCCESS_HISTORY = [
    "validated",
    "staging_created",
    "compiled",
    "simulated",
    "acceptance_passed",
    "published",
]


def valid_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "native-run-1",
        "scope": "lcc.blank_native",
        "builder_path": "lcc.blank_native",
        "kind": "licensed_simulation",
        "capability_state": "simulated",
        "commit": COMMIT,
        "generated_at_utc": "2026-08-30T01:00:00Z",
        "status": "PASS",
        "repository": {"branch": "codex/lcc-wp1a", "commit": COMMIT, "clean": True},
        "preflight": {
            "status": "PASS",
            "sha256": PREFLIGHT_HASH,
            "snapshot": PREFLIGHT_SNAPSHOT,
        },
        "sources": {
            "template": {"path": "D:/official.pscx", "before": HASH, "after": HASH},
            "master": {"path": "C:/PSCAD46/master.pslx", "before": HASH, "after": HASH},
            "registry": {
                "path": "D:/repo/master-bindings.json",
                "file_sha256": HASH,
                "registry_sha256": "c" * 64,
            },
            "asset_manifest": {"path": "D:/repo/manifest.json", "sha256": HASH},
        },
        "build": {
            "project_name": "WP1A_NATIVE_LCC",
            "workspace": "D:/PSCAD-Workspace/lcc-wp1a/run-1",
            "build_id": "build-1",
            "plan_hash": HASH,
            "journal_path": "D:/run/journal.json",
            "journal_sha256": HASH,
            "history": SUCCESS_HISTORY,
            "terminal_state": "published",
        },
        "artifacts": {
            "project": {"path": "D:/run/case.pscx", "sha256": HASH},
            "library": {"path": "D:/run/cigre_lcc_v1.pslx", "sha256": HASH},
            "scenario": {"path": "D:/run/case_scenario_source.pscx", "sha256": HASH},
            "selected_output": {"path": "D:/run/case_01.out", "sha256": HASH},
            "output_parts": [{"path": "D:/run/case_01.out", "sha256": HASH}],
            "output_metadata": [],
        },
        "acceptance": {
            "verdict": "PASS",
            "checks": {
                "disturbance": True,
                "failure_indication": True,
                "bounded_dc_response": True,
                "recovered": True,
            },
            "evidence": {
                "fault_time_s": 0.8,
                "fault_duration_s": 0.1,
                "current_limit_pu": 3.0,
                "dc_current_peak_pu": 2.5,
                "recovery_window_s": 0.5,
                "channels": {
                    "fault_active": {"path": "Fault/LCC Fault Active", "units": "state", "samples": 5, "domain_start_s": 0.0, "domain_end_s": 2.0},
                    "dc_current": {"path": "Inverter/DC Current", "units": "pu", "samples": 5, "domain_start_s": 0.0, "domain_end_s": 2.0},
                    "failure_indicator": {"path": "Inverter/Gamma", "units": "deg", "samples": 5, "domain_start_s": 0.0, "domain_end_s": 2.0},
                },
            },
        },
        "runtime": {
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "licensed": True,
            "managed_pid": 1234,
            "quit_error": None,
            "remaining_processes": [],
        },
        "explicit_exclusions": [
            "fixed_autonomous",
            "parametric_lcc",
            "independent_golden",
            "final_accepted",
        ],
        "failure": None,
    }


def subject():
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        validate_native_lcc_acceptance_report,
    )

    return validate_native_lcc_acceptance_report


def test_valid_pass_report_is_normalized_without_mutation():
    payload = valid_report()
    original = copy.deepcopy(payload)
    assert subject()(payload)["status"] == "PASS"
    assert payload == original


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(extra=True),
        lambda value: value["build"].update(extra=True),
        lambda value: value["acceptance"]["checks"].pop("recovered"),
        lambda value: value["artifacts"].update(project=None),
        lambda value: value.update(capability_state="accepted"),
        lambda value: value["build"].update(history=list(reversed(SUCCESS_HISTORY))),
    ],
)
def test_pass_report_rejects_unknown_missing_or_false_claims(mutation):
    payload = valid_report()
    mutation(payload)
    with pytest.raises(BackendError) as failure:
        subject()(payload)
    assert failure.value.code == "LCC_NATIVE_REPORT_INVALID"


def test_fail_report_requires_failure_and_rejects_pass_artifacts():
    payload = valid_report()
    payload["status"] = "FAIL"
    payload["capability_state"] = "failed"
    payload["failure"] = {"stage": "compile", "code": "LCC_BUILD_FAILED", "message": "failed"}
    payload["build"]["terminal_state"] = "failed"
    payload["build"]["history"] = ["validated", "failed"]
    payload["artifacts"] = {
        "project": None,
        "library": None,
        "scenario": None,
        "selected_output": None,
        "output_parts": [],
        "output_metadata": [],
    }
    payload["acceptance"] = None

    assert subject()(payload)["failure"]["stage"] == "compile"


def test_native_promotion_revalidates_domain_report_before_generic_promotion(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        promote_native_lcc_report,
    )

    payload = valid_report()
    payload["acceptance"]["checks"]["recovered"] = False
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    called = []

    with pytest.raises(BackendError):
        promote_native_lcc_report(
            tmp_path / "baseline.json",
            report,
            promotion_action=lambda *args, **kwargs: called.append((args, kwargs)),
        )

    assert called == []


def test_native_promotion_pins_validated_report_hash(monkeypatch, tmp_path):
    from pscad_mcp.hvdc.builders.lcc import native_acceptance

    report = tmp_path / "report.json"
    report.write_text(json.dumps(valid_report(), sort_keys=True), encoding="utf-8")
    calls = []
    monkeypatch.setattr(native_acceptance, "_verify_native_report_files", lambda payload: None)

    native_acceptance.promote_native_lcc_report(
        tmp_path / "baseline.json",
        report,
        promotion_action=lambda *args, **kwargs: calls.append((args, kwargs)) or {},
    )

    assert calls[0][1]["expected_report_sha256"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()
```

- [ ] **Step 2: Run report tests and verify RED**

Run `pytest -q tests/test_lcc_native_acceptance.py -k report`.

Expected: import failure for `native_acceptance`.

- [ ] **Step 3: Implement strict status-aware report validation**

Create `pscad_mcp/hvdc/builders/lcc/native_acceptance.py` with constants from
`Shared Constants`, an `_error()` returning `BackendError` code
`LCC_NATIVE_REPORT_INVALID`, and these exact helpers:

```python
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ....acceptance.evidence import build_run_metadata, index_explicit_reports
from ....acceptance.promotion import promote_program_report
from ....core.backend.base import BackendError
from ....core.master_bindings import parse_master_binding_registry

_HASH = re.compile(r"^[0-9a-f]{64}$")
REPORT_KEYS = {
    "schema_version", "run_id", "scope", "builder_path", "kind",
    "capability_state", "commit", "generated_at_utc", "status",
    "repository", "preflight", "sources", "build", "artifacts",
    "acceptance", "runtime", "explicit_exclusions", "failure",
}
BUILD_KEYS = {
    "project_name", "workspace", "build_id", "plan_hash", "journal_path",
    "journal_sha256", "history", "terminal_state",
}
ARTIFACT_KEYS = {
    "project", "library", "scenario", "selected_output",
    "output_parts", "output_metadata",
}


def _error(field: str, message: str) -> BackendError:
    return BackendError(
        "LCC_NATIVE_REPORT_INVALID",
        message,
        "hvdc",
        "validate_native_lcc_acceptance_report",
        {"field": field},
    )


def _exact_record(value: Any, field: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _error(field, f"{field} fields are not exact.")
    return dict(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(field, f"{field} must be non-empty text.")
    return value.strip()


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if _HASH.fullmatch(text) is None:
        raise _error(field, f"{field} must be lowercase SHA-256.")
    return text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_path(value: str | Path, field: str) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    marker = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    for component in [*reversed(path.parents), path]:
        try:
            observed = os.lstat(component)
        except OSError as error:
            raise _error(field, f"{field} is not a regular file.") from error
        attributes = int(getattr(observed, "st_file_attributes", 0))
        if stat.S_ISLNK(observed.st_mode) or attributes & marker:
            raise _error(field, f"{field} contains a symlink/reparse component.")
    if not path.is_file():
        raise _error(field, f"{field} is not a regular file.")
    return path


def _path_hash(value: Any, field: str) -> dict[str, str]:
    item = _exact_record(value, field, {"path", "sha256"})
    return {
        "path": _text(item["path"], f"{field}.path"),
        "sha256": _hash(item["sha256"], f"{field}.sha256"),
    }


def _validate_preflight(value: Any, *, require_pass: bool) -> dict[str, Any]:
    item = _exact_record(value, "preflight", {"status", "sha256", "snapshot"})
    if item["status"] not in {"PASS", "FAIL"}:
        raise _error("preflight.status", "Preflight status must be PASS or FAIL.")
    if require_pass and item["status"] != "PASS":
        raise _error("preflight.status", "Preflight must pass.")
    if not isinstance(item["snapshot"], Mapping):
        raise _error("preflight.snapshot", "Preflight snapshot must be an object.")
    expected = hashlib.sha256(
        json.dumps(
            item["snapshot"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    observed = _hash(item["sha256"], "preflight.sha256")
    if observed != expected:
        raise _error("preflight.sha256", "Preflight snapshot hash is invalid.")
    return {"status": str(item["status"]), "sha256": observed, "snapshot": copy.deepcopy(item["snapshot"])}


def _validate_sources(value: Any, *, require_immutable: bool) -> dict[str, Any]:
    item = _exact_record(
        value,
        "sources",
        {"template", "master", "registry", "asset_manifest"},
    )
    registry = _exact_record(
        item["registry"],
        "sources.registry",
        {"path", "file_sha256", "registry_sha256"},
    )
    result: dict[str, Any] = {
        "registry": {
            "path": _text(registry["path"], "sources.registry.path"),
            "file_sha256": _hash(registry["file_sha256"], "sources.registry.file_sha256"),
            "registry_sha256": _hash(registry["registry_sha256"], "sources.registry.registry_sha256"),
        },
        "asset_manifest": _path_hash(item["asset_manifest"], "sources.asset_manifest"),
    }
    for name in ("template", "master"):
        source = _exact_record(item[name], f"sources.{name}", {"path", "before", "after"})
        before = _hash(source["before"], f"sources.{name}.before")
        after = _hash(source["after"], f"sources.{name}.after")
        if require_immutable and before != after:
            raise _error(f"sources.{name}", f"{name} changed during acceptance.")
        result[name] = {
            "path": _text(source["path"], f"sources.{name}.path"),
            "before": before,
            "after": after,
        }
    return result


def _validate_build(value: Any, *, require_published: bool) -> dict[str, Any]:
    item = _exact_record(value, "build", BUILD_KEYS)
    history = item["history"]
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise _error("build.history", "Build history must be an array.")
    result = {
        "project_name": _text(item["project_name"], "build.project_name"),
        "workspace": _text(item["workspace"], "build.workspace"),
        "build_id": None if item["build_id"] is None else _text(item["build_id"], "build.build_id"),
        "plan_hash": None if item["plan_hash"] is None else _hash(item["plan_hash"], "build.plan_hash"),
        "journal_path": None if item["journal_path"] is None else _text(item["journal_path"], "build.journal_path"),
        "journal_sha256": None if item["journal_sha256"] is None else _hash(item["journal_sha256"], "build.journal_sha256"),
        "history": [_text(entry, "build.history") for entry in history],
        "terminal_state": _text(item["terminal_state"], "build.terminal_state"),
    }
    if require_published and (
        any(result[name] is None for name in ("build_id", "plan_hash", "journal_path", "journal_sha256"))
        or tuple(result["history"]) != SUCCESS_HISTORY
        or result["terminal_state"] != "published"
    ):
        raise _error("build", "PASS requires complete published build evidence.")
    return result


def _validate_pass_artifacts(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "artifacts", ARTIFACT_KEYS)
    output_parts = item["output_parts"]
    metadata = item["output_metadata"]
    if not isinstance(output_parts, Sequence) or not output_parts:
        raise _error("artifacts.output_parts", "PASS requires output parts.")
    if not isinstance(metadata, Sequence) or isinstance(metadata, (str, bytes)):
        raise _error("artifacts.output_metadata", "Output metadata must be an array.")
    return {
        "project": _path_hash(item["project"], "artifacts.project"),
        "library": _path_hash(item["library"], "artifacts.library"),
        "scenario": _path_hash(item["scenario"], "artifacts.scenario"),
        "selected_output": _path_hash(item["selected_output"], "artifacts.selected_output"),
        "output_parts": [
            _path_hash(entry, f"artifacts.output_parts[{index}]")
            for index, entry in enumerate(output_parts)
        ],
        "output_metadata": [
            _path_hash(entry, f"artifacts.output_metadata[{index}]")
            for index, entry in enumerate(metadata)
        ],
    }


def _validate_fail_artifacts(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "artifacts", ARTIFACT_KEYS)
    if not isinstance(item["output_parts"], Sequence) or isinstance(item["output_parts"], (str, bytes)):
        raise _error("artifacts.output_parts", "FAIL output parts must be an array.")
    if not isinstance(item["output_metadata"], Sequence) or isinstance(item["output_metadata"], (str, bytes)):
        raise _error("artifacts.output_metadata", "FAIL metadata must be an array.")
    return {
        **{
            name: None if item[name] is None else _path_hash(item[name], f"artifacts.{name}")
            for name in ("project", "library", "scenario", "selected_output")
        },
        "output_parts": [
            _path_hash(entry, f"artifacts.output_parts[{index}]")
            for index, entry in enumerate(item["output_parts"])
        ],
        "output_metadata": [
            _path_hash(entry, f"artifacts.output_metadata[{index}]")
            for index, entry in enumerate(item["output_metadata"])
        ],
    }


def _validate_acceptance(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "acceptance", {"verdict", "checks", "evidence"})
    checks = _exact_record(item["checks"], "acceptance.checks", set(REQUIRED_CHECKS))
    if item["verdict"] != "PASS" or any(checks[name] is not True for name in REQUIRED_CHECKS):
        raise _error("acceptance", "All four native checks must pass.")
    evidence = _exact_record(
        item["evidence"],
        "acceptance.evidence",
        {
            "fault_time_s", "fault_duration_s", "current_limit_pu",
            "dc_current_peak_pu", "recovery_window_s", "channels",
        },
    )
    for field in (
        "fault_time_s", "fault_duration_s", "current_limit_pu",
        "dc_current_peak_pu", "recovery_window_s",
    ):
        if isinstance(evidence[field], bool) or not isinstance(evidence[field], (int, float)) or not math.isfinite(float(evidence[field])):
            raise _error(f"acceptance.evidence.{field}", "Numeric evidence must be finite.")
    channels = _exact_record(
        evidence["channels"],
        "acceptance.evidence.channels",
        {"fault_active", "dc_current", "failure_indicator"},
    )
    normalized_channels = {}
    for name, value in channels.items():
        channel = _exact_record(
            value,
            f"acceptance.evidence.channels.{name}",
            {"path", "units", "samples", "domain_start_s", "domain_end_s"},
        )
        samples = channel["samples"]
        start = channel["domain_start_s"]
        end = channel["domain_end_s"]
        if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
            raise _error(f"acceptance.evidence.channels.{name}.samples", "Channel samples must be positive integer.")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for item in (start, end)) or float(end) <= float(start):
            raise _error(f"acceptance.evidence.channels.{name}.domain", "Channel domain must be finite and increasing.")
        normalized_channels[name] = {
            "path": _text(channel["path"], f"acceptance.evidence.channels.{name}.path"),
            "units": _text(channel["units"], f"acceptance.evidence.channels.{name}.units"),
            "samples": samples,
            "domain_start_s": float(start),
            "domain_end_s": float(end),
        }
    evidence["channels"] = normalized_channels
    return {"verdict": "PASS", "checks": dict(checks), "evidence": dict(evidence)}


def _validate_runtime(value: Any, *, require_licensed: bool) -> dict[str, Any]:
    item = _exact_record(
        value,
        "runtime",
        {"backend", "version", "x64", "licensed", "managed_pid", "quit_error", "remaining_processes"},
    )
    if item["backend"] != "legacy" or item["version"] != "4.6.2" or item["x64"] is not True:
        raise _error("runtime", "Runtime identity is not Legacy 4.6.2 x64.")
    if require_licensed and item["licensed"] is not True:
        raise _error("runtime.licensed", "PASS requires a licensed runtime.")
    if item["managed_pid"] is not None and (isinstance(item["managed_pid"], bool) or not isinstance(item["managed_pid"], int)):
        raise _error("runtime.managed_pid", "managed_pid must be integer or null.")
    if item["quit_error"] is not None and not isinstance(item["quit_error"], str):
        raise _error("runtime.quit_error", "quit_error must be text or null.")
    if not isinstance(item["remaining_processes"], Sequence) or isinstance(item["remaining_processes"], (str, bytes)):
        raise _error("runtime.remaining_processes", "Remaining processes must be an array.")
    if any(not isinstance(process, Mapping) for process in item["remaining_processes"]):
        raise _error("runtime.remaining_processes", "Process entries must be objects.")
    return copy.deepcopy(item)


def _validate_failure(value: Any) -> dict[str, str]:
    item = _exact_record(value, "failure", {"stage", "code", "message"})
    return {name: _text(item[name], f"failure.{name}") for name in ("stage", "code", "message")}
```

Then add the public validator:

```python
def validate_native_lcc_acceptance_report(value: Any) -> dict[str, Any]:
    report = _exact_record(value, "report", REPORT_KEYS)
    if report["schema_version"] != 1 or isinstance(report["schema_version"], bool):
        raise _error("schema_version", "schema_version must be 1.")
    metadata = build_run_metadata(
        run_id=_text(report["run_id"], "run_id"),
        scope=_text(report["scope"], "scope"),
        kind=_text(report["kind"], "kind"),
        capability_state=_text(report["capability_state"], "capability_state"),
        commit=_text(report["commit"], "commit"),
        generated_at_utc=_text(report["generated_at_utc"], "generated_at_utc"),
    )
    if (
        metadata["scope"] != NATIVE_SCOPE
        or metadata["builder_path"] != NATIVE_BUILDER_PATH
        or _text(report["builder_path"], "builder_path") != metadata["builder_path"]
    ):
        raise _error("scope", "The report is not owned by blank/native LCC.")
    if report["repository"] != {
        "branch": _text(report["repository"].get("branch"), "repository.branch"),
        "commit": metadata["commit"],
        "clean": True,
    }:
        raise _error("repository", "Repository evidence is not exact and clean.")
    if tuple(report["explicit_exclusions"]) != NATIVE_EXCLUSIONS:
        raise _error("explicit_exclusions", "Native exclusions are not exact.")

    status = _text(report["status"], "status")
    if status not in {"PASS", "FAIL"}:
        raise _error("status", "Native acceptance status must be PASS or FAIL.")
    build = _validate_build(report["build"], require_published=status == "PASS")
    runtime = _validate_runtime(report["runtime"], require_licensed=status == "PASS")
    sources = _validate_sources(report["sources"], require_immutable=status == "PASS")
    if status == "PASS":
        if metadata["capability_state"] != NATIVE_CAPABILITY:
            raise _error("capability_state", "PASS must remain simulated.")
        if tuple(build["history"]) != SUCCESS_HISTORY or build["terminal_state"] != "published":
            raise _error("build.history", "PASS requires the exact published history.")
        artifacts = _validate_pass_artifacts(report["artifacts"])
        acceptance = _validate_acceptance(report["acceptance"])
        if report["failure"] is not None or runtime["remaining_processes"]:
            raise _error("failure", "PASS cannot contain failure or remaining processes.")
    elif status == "FAIL":
        if metadata["capability_state"] != "failed":
            raise _error("capability_state", "FAIL must use failed capability state.")
        artifacts = _validate_fail_artifacts(report["artifacts"])
        acceptance = None
        _validate_failure(report["failure"])
    normalized = {
        **metadata,
        "status": status,
        "repository": copy.deepcopy(report["repository"]),
        "preflight": _validate_preflight(report["preflight"], require_pass=status == "PASS"),
        "sources": sources,
        "build": build,
        "artifacts": artifacts,
        "acceptance": acceptance,
        "runtime": runtime,
        "explicit_exclusions": list(NATIVE_EXCLUSIONS),
        "failure": copy.deepcopy(report["failure"]),
    }
    return copy.deepcopy(normalized)
```

Add domain validation at the promotion boundary:

```python
def _verify_file(path_value: str, expected_sha256: str, field: str) -> None:
    path = _regular_path(path_value, field)
    if _sha256(path) != expected_sha256:
        raise _error(field, f"{field} file/hash evidence does not match disk.")


def _verify_native_report_files(report: Mapping[str, Any]) -> None:
    sources = report["sources"]
    _verify_file(sources["template"]["path"], sources["template"]["after"], "sources.template")
    _verify_file(sources["master"]["path"], sources["master"]["after"], "sources.master")
    _verify_file(sources["registry"]["path"], sources["registry"]["file_sha256"], "sources.registry")
    registry_path = _regular_path(sources["registry"]["path"], "sources.registry")
    registry = parse_master_binding_registry(
        json.loads(registry_path.read_text(encoding="utf-8"))
    )
    if registry.sha256 != sources["registry"]["registry_sha256"]:
        raise _error("sources.registry.registry_sha256", "Registry semantic hash does not match disk.")
    _verify_file(sources["asset_manifest"]["path"], sources["asset_manifest"]["sha256"], "sources.asset_manifest")
    build = report["build"]
    _verify_file(build["journal_path"], build["journal_sha256"], "build.journal")
    artifacts = report["artifacts"]
    for name in ("project", "library", "scenario", "selected_output"):
        _verify_file(artifacts[name]["path"], artifacts[name]["sha256"], f"artifacts.{name}")
    for group in ("output_parts", "output_metadata"):
        for index, item in enumerate(artifacts[group]):
            _verify_file(item["path"], item["sha256"], f"artifacts.{group}[{index}]")


def load_native_lcc_acceptance_report(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = path.read_bytes()
    if len(raw) > 16 * 1024 * 1024:
        raise _error("report", "Native report exceeds 16 MiB.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error("report", "Native report is not UTF-8 JSON.") from error
    normalized = validate_native_lcc_acceptance_report(payload)
    if normalized["status"] == "PASS":
        _verify_native_report_files(normalized)
    indexed = index_explicit_reports([{"path": str(path)}])[0]
    if indexed["sha256"] != hashlib.sha256(raw).hexdigest():
        raise _error("report", "Native report changed during validation.")
    return normalized, indexed


def promote_native_lcc_report(
    baseline_path: Path,
    report_path: Path,
    *,
    promotion_action: Callable[..., dict[str, Any]] = promote_program_report,
) -> dict[str, Any]:
    report, indexed = load_native_lcc_acceptance_report(report_path)
    if report["status"] != "PASS" or indexed["capability_state"] != NATIVE_CAPABILITY:
        raise _error("status", "Only native simulated/PASS evidence can be promoted.")
    return promotion_action(
        baseline_path,
        report_path,
        expected_scope=NATIVE_SCOPE,
        owner_work_package=NATIVE_OWNER,
        explicit_exclusions=NATIVE_EXCLUSIONS,
        expected_report_sha256=indexed["sha256"],
    )
```

- [ ] **Step 4: Run report tests and lint**

Run:

```powershell
pytest -q tests/test_lcc_native_acceptance.py -k report
ruff check pscad_mcp/hvdc/builders/lcc/native_acceptance.py tests/test_lcc_native_acceptance.py
```

Expected: all report tests pass.

- [ ] **Step 5: Commit the report contract**

```powershell
git add pscad_mcp/hvdc/builders/lcc/native_acceptance.py tests/test_lcc_native_acceptance.py
git commit -m "feat: define native LCC acceptance report contract"
```

### Task 3: Native Acceptance Orchestration

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/native_acceptance.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/native_template.py`
- Test: `tests/test_lcc_native_acceptance.py`
- Test: `tests/test_lcc_native_template.py`

- [ ] **Step 1: Add failing physical-channel identity test**

Append to `tests/test_lcc_native_template.py`:

```python
def test_native_commutation_evidence_names_indicator_and_recovery_window():
    from pscad_mcp.hvdc.builders.lcc.native_template import (
        evaluate_native_lcc_commutation,
    )

    domain = [0.0, 0.7, 0.8, 0.85, 0.9, 1.5]
    result = evaluate_native_lcc_commutation(
        {
            "channels": [
                {"path": "Fault/LCC Fault Active", "units": "state", "domain": domain, "values": [0, 0, 1, 1, 0, 0]},
                {"path": "Inverter/DC Current", "units": "pu", "domain": domain, "values": [1, 1, 2, 2, 1, 1]},
                {"path": "Inverter/Gamma", "units": "deg", "domain": domain, "values": [18, 18, 5, 6, 17, 18]},
            ]
        },
        fault_time_s=0.8,
        fault_duration_s=0.1,
        current_limit_pu=3.0,
        recovery_delay_s=0.5,
    )

    assert result["verdict"] == "PASS"
    channels = result["evidence"]["channels"]
    assert channels["fault_active"]["path"] == "Fault/LCC Fault Active"
    assert channels["dc_current"]["units"] == "pu"
    assert channels["failure_indicator"]["path"] == "Inverter/Gamma"
    assert channels["failure_indicator"]["units"] == "deg"
    assert channels["failure_indicator"]["samples"] == len(domain)
    assert result["evidence"]["recovery_window_s"] == 0.5
```

Run `pytest -q tests/test_lcc_native_template.py -k indicator_and_recovery` and
verify failure because these evidence fields are absent.

- [ ] **Step 2: Add observed channel identity without changing verdict logic**

In `evaluate_native_lcc_commutation`, initialize:

```python
evidence["recovery_window_s"] = float(recovery_delay_s)
indicator_record: Mapping[str, Any] | None = None
channels: dict[str, dict[str, Any]] = {}


def channel_identity(channel):
    record, times, _values = channel
    return {
        "path": str(record.get("path") or record.get("name") or ""),
        "units": str(record.get("units", record.get("unit", ""))),
        "samples": len(times),
        "domain_start_s": float(times[0]),
        "domain_end_s": float(times[-1]),
    }


if fault is not None:
    channels["fault_active"] = channel_identity(fault)
if current is not None:
    channels["dc_current"] = channel_identity(current)
```

When gamma produces `failure_indication=True`, set `indicator_record = gamma[0]`.
When the DC-voltage fallback produces it, set `indicator_record = dc_voltage[0]`;
when the AC-RMS fallback produces it, set `indicator_record = ac_rms[0]`.
Before returning, add:

```python
if indicator_record is not None:
    indicator_sample = _sample(indicator_record)
    if indicator_sample is not None:
        channels["failure_indicator"] = {
            "path": str(indicator_record.get("path") or indicator_record.get("name") or ""),
            "units": str(indicator_record.get("units", indicator_record.get("unit", ""))),
            "samples": len(indicator_sample[0]),
            "domain_start_s": float(indicator_sample[0][0]),
            "domain_end_s": float(indicator_sample[0][-1]),
        }
evidence["channels"] = channels
```

Run the focused test and all `tests/test_lcc_native_template.py`; expect pass.

- [ ] **Step 3: Add failing fake-service orchestration tests**

Append tests using an injected builder/service:

```python
import asyncio
import json
from dataclasses import replace
from pathlib import Path


class FakePscadService:
    def __init__(self) -> None:
        self.calls = []

    async def attach_local(self):
        self.calls.append("attach_local")

    async def status(self):
        return {"backend": "legacy", "version": "4.6.2", "x64": True, "licensed": True, "session": {"managed_pid": 42}}

    async def quit_pscad(self, *, confirm=False):
        self.calls.append(("quit_pscad", confirm))


class FakeBuilder:
    def __init__(self, workspace: Path, source: Path) -> None:
        self.workspace = workspace
        self.source = source
        self.build_id = "build-1"
        self.polls = 0

    def plan_model(self, project_name, folder, simulation_duration_s, template_path):
        return {
            "plan_hash": HASH,
            "native_template": {"source": str(self.source), "source_sha256": HASH},
            "target_path": str(self.workspace / f"{project_name}.pscx"),
        }

    async def build_model(self, project_name, expected_plan_hash, folder, simulation_duration_s, confirm, template_path):
        return {"build_id": self.build_id}

    def get_build_status(self, build_id):
        self.polls += 1
        return self._published_record()

    def _published_record(self):
        project = self.workspace / "WP1A_NATIVE_LCC.pscx"
        library = self.workspace / "cigre_lcc_v1.pslx"
        scenario = self.workspace / "WP1A_NATIVE_LCC_scenario_source.pscx"
        output = self.workspace / "WP1A_NATIVE_LCC.outputs" / "WP1A_NATIVE_LCC_01.out"
        for path in (project, library, scenario, output):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"evidence")
        journal = self.workspace / ".pscad-mcp" / "lcc-builds" / self.build_id / "journal.json"
        journal.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "build_id": self.build_id,
            "state": "published",
            "plan_hash": HASH,
            "target_path": str(project),
            "history": [{"state": state} for state in SUCCESS_HISTORY],
            "error": None,
            "result": {
                "output_file": str(output),
                "output_parts": [str(output)],
                "acceptance": {
                    "verdict": "PASS",
                    "checks": {name: True for name in REQUIRED_CHECKS},
                    "evidence": {
                        "fault_time_s": 0.8,
                        "fault_duration_s": 0.1,
                        "current_limit_pu": 3.0,
                        "dc_current_peak_pu": 2.5,
                        "recovery_window_s": 0.5,
                        "channels": {
                            "fault_active": {"path": "Fault/LCC Fault Active", "units": "state", "samples": 5, "domain_start_s": 0.0, "domain_end_s": 2.0},
                            "dc_current": {"path": "Inverter/DC Current", "units": "pu", "samples": 5, "domain_start_s": 0.0, "domain_end_s": 2.0},
                            "failure_indicator": {"path": "Inverter/Gamma", "units": "deg", "samples": 5, "domain_start_s": 0.0, "domain_end_s": 2.0},
                        },
                    },
                },
                "final_project_sha256": HASH,
                "final_library_path": str(library),
                "final_library_sha256": HASH,
                "scenario_source": str(scenario),
            },
        }
        journal.write_text(json.dumps(record), encoding="utf-8")
        return record

    async def shutdown(self, timeout_s=5.0):
        return None


def test_orchestrator_uses_builder_and_writes_indexable_pass_report(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        NativeLccAcceptanceRequest,
        run_native_lcc_acceptance,
    )

    source = tmp_path / "official.pscx"
    source.write_bytes(b"official")
    master = tmp_path / "master.pslx"
    master.write_bytes(b"master")
    report = tmp_path / "native-report.json"
    request = NativeLccAcceptanceRequest(
        repository_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        template_path=source,
        master_path=master,
        report_path=report,
        project_name="WP1A_NATIVE_LCC",
        commit=COMMIT,
        branch="codex/lcc-wp1a",
        registry_sha256=HASH,
        registry_file_sha256=HASH,
        asset_manifest_sha256=HASH,
        preflight={"status": "PASS", "sha256": PREFLIGHT_HASH, "snapshot": PREFLIGHT_SNAPSHOT},
    )
    service = FakePscadService()
    builder = FakeBuilder(request.workspace_root, source)

    result = asyncio.run(
        run_native_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            process_reader=list,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "PASS"
    assert report.is_file()
    assert service.calls == ["attach_local", ("quit_pscad", True)]


def test_orchestrator_writes_fail_report_and_never_claims_pass_on_cleanup_failure(tmp_path):
    from pscad_mcp.hvdc.builders.lcc.native_acceptance import (
        NativeLccAcceptanceRequest,
        run_native_lcc_acceptance,
    )

    source = tmp_path / "official.pscx"
    source.write_bytes(b"official")
    master = tmp_path / "master.pslx"
    master.write_bytes(b"master")
    request = NativeLccAcceptanceRequest(
        repository_root=tmp_path,
        workspace_root=tmp_path / "workspace",
        template_path=source,
        master_path=master,
        report_path=tmp_path / "report.json",
        project_name="WP1A_NATIVE_LCC",
        commit=COMMIT,
        branch="codex/lcc-wp1a",
        registry_sha256=HASH,
        registry_file_sha256=HASH,
        asset_manifest_sha256=HASH,
        preflight={"status": "PASS", "sha256": PREFLIGHT_HASH, "snapshot": PREFLIGHT_SNAPSHOT},
    )
    service = FakePscadService()

    async def fail_quit(*, confirm=False):
        raise RuntimeError("quit failed")

    service.quit_pscad = fail_quit
    result = asyncio.run(
        run_native_lcc_acceptance(
            request,
            service=service,
            builder=FakeBuilder(request.workspace_root, source),
            process_reader=lambda: [{"pid": 42, "name": "Pscad.exe", "exe": "Pscad.exe"}],
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["capability_state"] == "failed"
    assert result["failure"]["stage"] == "cleanup"
```

- [ ] **Step 4: Run orchestration tests and verify RED**

Run `pytest -q tests/test_lcc_native_acceptance.py -k orchestrator`.

Expected: missing `NativeLccAcceptanceRequest` and `run_native_lcc_acceptance`.

- [ ] **Step 5: Implement the injected orchestration API**

Add to `native_acceptance.py`:

```python
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from ....acceptance.preflight import write_preflight_report
from ....core.process_inventory import list_pscad_processes
from .journal import AtomicJournal


@dataclass(frozen=True)
class NativeLccAcceptanceRequest:
    repository_root: Path
    workspace_root: Path
    template_path: Path
    master_path: Path
    report_path: Path
    project_name: str
    commit: str
    branch: str
    registry_sha256: str
    registry_file_sha256: str
    asset_manifest_sha256: str
    preflight: Mapping[str, Any]
    simulation_duration_s: float = 2.5
```

Add these complete helpers before the orchestrator:

```python
def _artifact(path: Path) -> dict[str, str]:
    resolved = _regular_path(path, "artifact")
    return {"path": resolved.as_posix(), "sha256": _sha256(resolved)}


def _history(record: Mapping[str, Any]) -> list[str]:
    values = record.get("history")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise BackendError(
            "LCC_NATIVE_HISTORY_INVALID",
            "Native build history is not an array.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    result = []
    for item in values:
        if not isinstance(item, Mapping) or not isinstance(item.get("state"), str):
            raise BackendError(
                "LCC_NATIVE_HISTORY_INVALID",
                "Native build history entry has no state.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
        result.append(str(item["state"]))
    return result


def _journal_path(workspace: Path, build_id: str) -> Path:
    return AtomicJournal(workspace, build_id).path
def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
```

Add the exact report constructors:

```python
def _metadata(
    request: NativeLccAcceptanceRequest,
    run_id: str,
    capability_state: str,
) -> dict[str, Any]:
    return build_run_metadata(
        run_id=run_id,
        scope=NATIVE_SCOPE,
        kind=NATIVE_KIND,
        capability_state=capability_state,
        commit=request.commit,
        generated_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _initial_fail_report(
    request: NativeLccAcceptanceRequest,
    run_id: str,
    template_before: str,
    master_before: str,
) -> dict[str, Any]:
    return {
        **_metadata(request, run_id, "failed"),
        "status": "FAIL",
        "repository": {"branch": request.branch, "commit": request.commit, "clean": True},
        "preflight": {
            "status": str(request.preflight["status"]),
            "sha256": str(request.preflight["sha256"]),
            "snapshot": copy.deepcopy(request.preflight["snapshot"]),
        },
        "sources": {
            "template": {"path": request.template_path.resolve().as_posix(), "before": template_before, "after": template_before},
            "master": {"path": request.master_path.resolve().as_posix(), "before": master_before, "after": master_before},
            "registry": {
                "path": (request.repository_root / "pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json").resolve().as_posix(),
                "file_sha256": request.registry_file_sha256,
                "registry_sha256": request.registry_sha256,
            },
            "asset_manifest": {
                "path": (request.repository_root / "pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json").resolve().as_posix(),
                "sha256": request.asset_manifest_sha256,
            },
        },
        "build": {
            "project_name": request.project_name,
            "workspace": request.workspace_root.resolve().as_posix(),
            "build_id": None,
            "plan_hash": None,
            "journal_path": None,
            "journal_sha256": None,
            "history": [],
            "terminal_state": "not_started",
        },
        "artifacts": {
            "project": None,
            "library": None,
            "scenario": None,
            "selected_output": None,
            "output_parts": [],
            "output_metadata": [],
        },
        "acceptance": None,
        "runtime": {
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "licensed": False,
            "managed_pid": None,
            "quit_error": None,
            "remaining_processes": [],
        },
        "explicit_exclusions": list(NATIVE_EXCLUSIONS),
        "failure": {"stage": "not_started", "code": "NOT_STARTED", "message": "Acceptance has not completed."},
    }


def _fail_report(
    request: NativeLccAcceptanceRequest,
    current: Mapping[str, Any],
    stage: str,
    error: BaseException,
) -> dict[str, Any]:
    report = copy.deepcopy(dict(current))
    report.update(_metadata(request, str(report["run_id"]), "failed"))
    report["status"] = "FAIL"
    report["acceptance"] = None
    report["failure"] = {
        "stage": stage,
        "code": error.code if isinstance(error, BackendError) else type(error).__name__,
        "message": str(error)[:1024] or type(error).__name__,
    }
    if report["build"]["terminal_state"] == "published":
        report["build"]["terminal_state"] = "failed"
    return report


def write_native_lcc_setup_failure_report(
    request: NativeLccAcceptanceRequest,
    error: BaseException,
    *,
    process_reader: Callable[[], Sequence[Mapping[str, Any]]] = list_pscad_processes,
) -> dict[str, Any]:
    template_before = _sha256(_regular_path(request.template_path, "sources.template"))
    master_before = _sha256(_regular_path(request.master_path, "sources.master"))
    report = _initial_fail_report(
        request,
        request.report_path.parent.name,
        template_before,
        master_before,
    )
    report = _fail_report(request, report, "setup", error)
    report["runtime"]["remaining_processes"] = [dict(value) for value in process_reader()]
    normalized = validate_native_lcc_acceptance_report(report)
    write_preflight_report(request.report_path, normalized)
    index_explicit_reports([{"path": str(request.report_path)}])
    return normalized


def _build_evidence_from_record(
    request: NativeLccAcceptanceRequest,
    plan: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    build_id = str(record["build_id"])
    journal = _journal_path(request.workspace_root, build_id)
    return {
        "project_name": request.project_name,
        "workspace": request.workspace_root.resolve().as_posix(),
        "build_id": build_id,
        "plan_hash": str(plan["plan_hash"]),
        "journal_path": journal.resolve().as_posix() if journal.is_file() else None,
        "journal_sha256": _sha256(journal) if journal.is_file() else None,
        "history": _history(record),
        "terminal_state": str(record.get("state") or "unknown"),
    }


async def _pass_report_from_record(
    request: NativeLccAcceptanceRequest,
    plan: Mapping[str, Any],
    record: Mapping[str, Any],
    service: Any,
    template_before: str,
    master_before: str,
) -> dict[str, Any]:
    if record.get("state") != "published" or tuple(_history(record)) != SUCCESS_HISTORY:
        raise BackendError(
            "LCC_NATIVE_HISTORY_INVALID",
            "Native build did not reach the exact published history.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    result = record.get("result")
    if not isinstance(result, Mapping) or not isinstance(result.get("acceptance"), Mapping):
        raise BackendError("LCC_NATIVE_RESULT_INVALID", "Native result is incomplete.", "hvdc", "run_native_lcc_acceptance")
    acceptance = result["acceptance"]
    checks = acceptance.get("checks")
    evidence = acceptance.get("evidence")
    if acceptance.get("verdict") != "PASS" or not isinstance(checks, Mapping) or not isinstance(evidence, Mapping):
        raise BackendError("LCC_ACCEPTANCE_FAILED", "Native physical checks did not pass.", "hvdc", "run_native_lcc_acceptance")
    if any(checks.get(name) is not True for name in REQUIRED_CHECKS):
        raise BackendError("LCC_ACCEPTANCE_FAILED", "A required native check is false.", "hvdc", "run_native_lcc_acceptance")

    build = _build_evidence_from_record(request, plan, record)
    selected_output = Path(str(result["output_file"]))
    output_parts = [Path(str(value)) for value in result["output_parts"]]
    output_base = re.sub(r"_\d{2}$", "", selected_output.stem)
    output_metadata = [
        selected_output.with_name(output_base + suffix)
        for suffix in (".inf", ".infx")
        if selected_output.with_name(output_base + suffix).is_file()
    ]
    runtime = await service.status()
    session = runtime.get("session") if isinstance(runtime, Mapping) else None
    managed_pid = session.get("managed_pid") if isinstance(session, Mapping) else None
    acceptance_evidence = {
        "fault_time_s": float(evidence["fault_time_s"]),
        "fault_duration_s": float(evidence["fault_duration_s"]),
        "current_limit_pu": float(evidence["current_limit_pu"]),
        "dc_current_peak_pu": float(evidence["dc_current_peak_pu"]),
        "recovery_window_s": float(evidence["recovery_window_s"]),
        "channels": copy.deepcopy(evidence["channels"]),
    }
    return {
        **_metadata(request, request.report_path.parent.name, NATIVE_CAPABILITY),
        "status": "PASS",
        "repository": {"branch": request.branch, "commit": request.commit, "clean": True},
        "preflight": {
            "status": str(request.preflight["status"]),
            "sha256": str(request.preflight["sha256"]),
            "snapshot": copy.deepcopy(request.preflight["snapshot"]),
        },
        "sources": {
            "template": {"path": request.template_path.resolve().as_posix(), "before": template_before, "after": _sha256(request.template_path)},
            "master": {"path": request.master_path.resolve().as_posix(), "before": master_before, "after": _sha256(request.master_path)},
            "registry": {
                "path": (request.repository_root / "pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json").resolve().as_posix(),
                "file_sha256": request.registry_file_sha256,
                "registry_sha256": request.registry_sha256,
            },
            "asset_manifest": {
                "path": (request.repository_root / "pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json").resolve().as_posix(),
                "sha256": request.asset_manifest_sha256,
            },
        },
        "build": {
            "project_name": request.project_name,
            "workspace": request.workspace_root.resolve().as_posix(),
            **build,
        },
        "artifacts": {
            "project": _artifact(Path(str(record["target_path"]))),
            "library": _artifact(Path(str(result["final_library_path"]))),
            "scenario": _artifact(Path(str(result["scenario_source"]))),
            "selected_output": _artifact(selected_output),
            "output_parts": [_artifact(path) for path in output_parts],
            "output_metadata": [_artifact(path) for path in output_metadata],
        },
        "acceptance": {"verdict": "PASS", "checks": {name: True for name in REQUIRED_CHECKS}, "evidence": acceptance_evidence},
        "runtime": {
            "backend": str(runtime.get("backend")),
            "version": str(runtime.get("version")),
            "x64": runtime.get("x64") is True,
            "licensed": runtime.get("licensed") is True,
            "managed_pid": managed_pid,
            "quit_error": None,
            "remaining_processes": [],
        },
        "explicit_exclusions": list(NATIVE_EXCLUSIONS),
        "failure": None,
    }
```

Implement `run_native_lcc_acceptance()` as one `try/except/finally` lifecycle:

```python
async def run_native_lcc_acceptance(
    request: NativeLccAcceptanceRequest,
    *,
    service: Any,
    builder: Any,
    process_reader: Callable[[], Sequence[Mapping[str, Any]]] = list_pscad_processes,
    poll_interval_s: float = 0.25,
    timeout_s: float = 1200.0,
) -> dict[str, Any]:
    template_path = _regular_path(request.template_path, "sources.template")
    master_path = _regular_path(request.master_path, "sources.master")
    template_before = _sha256(template_path)
    master_before = _sha256(master_path)
    run_id = request.report_path.parent.name
    report = _initial_fail_report(request, run_id, template_before, master_before)
    failure: BaseException | None = None
    failure_stage = "preflight"
    try:
        if request.preflight.get("status") != "PASS":
            raise BackendError(
                "LCC_NATIVE_PREFLIGHT_FAILED",
                "Native acceptance preflight failed.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
        failure_stage = "attach"
        await service.attach_local()
        runtime_status = await service.status()
        runtime_session = runtime_status.get("session") if isinstance(runtime_status, Mapping) else None
        report["runtime"].update(
            {
                "backend": str(runtime_status.get("backend")),
                "version": str(runtime_status.get("version")),
                "x64": runtime_status.get("x64") is True,
                "licensed": runtime_status.get("licensed") is True,
                "managed_pid": (
                    runtime_session.get("managed_pid")
                    if isinstance(runtime_session, Mapping)
                    else None
                ),
            }
        )
        if report["runtime"]["licensed"] is not True:
            raise BackendError(
                "NOT_LICENSED",
                "Native acceptance requires a licensed PSCAD runtime.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
        failure_stage = "plan"
        plan = builder.plan_model(
            request.project_name,
            folder=str(request.workspace_root),
            simulation_duration_s=request.simulation_duration_s,
            template_path=str(request.template_path),
        )
        failure_stage = "build"
        started = await builder.build_model(
            request.project_name,
            str(plan["plan_hash"]),
            folder=str(request.workspace_root),
            simulation_duration_s=request.simulation_duration_s,
            confirm=True,
            template_path=str(request.template_path),
        )
        build_id = str(started["build_id"])
        deadline = time.monotonic() + timeout_s
        while True:
            record = builder.get_build_status(build_id)
            if record.get("state") in {"published", "failed", "interrupted"}:
                break
            if time.monotonic() >= deadline:
                raise BackendError("LCC_BUILD_TIMED_OUT", "Native acceptance timed out.", "hvdc", "run_native_lcc_acceptance")
            await asyncio.sleep(poll_interval_s)
        report["build"] = _build_evidence_from_record(request, plan, record)
        if record.get("state") != "published":
            error = record.get("error") if isinstance(record.get("error"), Mapping) else {}
            raise BackendError(
                str(error.get("code") or "LCC_BUILD_FAILED"),
                str(error.get("message") or "Native LCC build failed."),
                "hvdc",
                "run_native_lcc_acceptance",
                dict(error.get("details") or {}),
            )
        failure_stage = "validate"
        report = await _pass_report_from_record(
            request,
            plan,
            record,
            service,
            template_before,
            master_before,
        )
    except BaseException as error:  # noqa: BLE001 - persist all lifecycle failures
        failure = error
        report = _fail_report(request, report, failure_stage, error)
    finally:
        cleanup_error: BaseException | None = None
        try:
            await builder.shutdown(timeout_s=5.0)
        except BaseException as error:  # noqa: BLE001 - cleanup controls verdict
            cleanup_error = error
        try:
            await service.quit_pscad(confirm=True)
        except BaseException as error:  # noqa: BLE001 - cleanup controls verdict
            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            report["runtime"]["quit_error"] = str(cleanup_error)[:1024]
            if failure is None:
                failure = cleanup_error
                report = _fail_report(request, report, "cleanup", cleanup_error)
        report["sources"]["template"]["after"] = _sha256(request.template_path)
        report["sources"]["master"]["after"] = _sha256(request.master_path)
        report["runtime"]["remaining_processes"] = [dict(value) for value in process_reader()]
        if (
            report["sources"]["template"]["before"] != report["sources"]["template"]["after"]
            or report["sources"]["master"]["before"] != report["sources"]["master"]["after"]
            or report["runtime"]["remaining_processes"]
        ):
            report = _fail_report(request, report, "cleanup", RuntimeError("source or process cleanup mismatch"))
        normalized = validate_native_lcc_acceptance_report(report)
        write_preflight_report(request.report_path, normalized)
        indexed = index_explicit_reports([{"path": str(request.report_path)}])[0]
        if indexed["status"] != normalized["status"] or indexed["commit"] != request.commit:
            raise BackendError("LCC_NATIVE_REPORT_INVALID", "Written report did not re-index.", "hvdc", "run_native_lcc_acceptance")
    return normalized
```

- [ ] **Step 6: Run orchestration/report tests and lint**

Run:

```powershell
pytest -q tests/test_lcc_native_acceptance.py
ruff check pscad_mcp/hvdc/builders/lcc/native_acceptance.py tests/test_lcc_native_acceptance.py
```

Expected: all pass.

- [ ] **Step 7: Commit orchestration**

```powershell
git add pscad_mcp/hvdc/builders/lcc/native_acceptance.py pscad_mcp/hvdc/builders/lcc/native_template.py tests/test_lcc_native_acceptance.py tests/test_lcc_native_template.py
git commit -m "feat: orchestrate native LCC licensed evidence"
```

### Task 4: CLI and Service Factory

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/native_acceptance_cli.py`
- Create: `tests/test_lcc_native_acceptance_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_lcc_native_acceptance_cli.py`:

```python
from __future__ import annotations

import json

from pscad_mcp.hvdc.builders.lcc.native_acceptance_cli import main


def test_run_action_writes_external_report_without_touching_baseline(monkeypatch, tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text("baseline", encoding="ascii")
    report = tmp_path / "workspace" / "run" / "report.json"

    async def runner(request, **kwargs):
        request.report_path.parent.mkdir(parents=True)
        request.report_path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
        return {"status": "PASS", "commit": request.commit}

    result = main(
        [
            "run",
            "--repository-root", str(tmp_path),
            "--workspace-root", str(tmp_path / "workspace"),
            "--template-path", str(tmp_path / "official.pscx"),
            "--master-path", str(tmp_path / "master.pslx"),
            "--compiler-configuration", str(tmp_path / "fortran_compilers.xml"),
            "--compiler-executable", str(tmp_path / "gfortran.exe"),
            "--report", str(report),
            "--commit", "a" * 40,
            "--branch", "codex/lcc-wp1a",
        ],
        run_action=runner,
        service_factory=lambda request: (object(), object(), "b" * 64, "c" * 64, "d" * 64),
        preflight_action=lambda arguments: {"status": "PASS", "sha256": "d" * 64, "snapshot": {}},
    )

    assert result == 0
    assert baseline.read_text(encoding="ascii") == "baseline"


def test_run_action_persists_service_factory_failure(tmp_path):
    report = tmp_path / "workspace" / "run" / "report.json"

    def setup_failure(request, error):
        request.report_path.parent.mkdir(parents=True)
        payload = {"status": "FAIL", "commit": request.commit}
        request.report_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def fail_factory(request):
        raise RuntimeError("factory failed")

    result = main(
        [
            "run",
            "--repository-root", str(tmp_path),
            "--workspace-root", str(tmp_path / "workspace"),
            "--template-path", str(tmp_path / "official.pscx"),
            "--master-path", str(tmp_path / "master.pslx"),
            "--compiler-configuration", str(tmp_path / "fortran_compilers.xml"),
            "--compiler-executable", str(tmp_path / "gfortran.exe"),
            "--report", str(report),
            "--commit", "a" * 40,
            "--branch", "codex/lcc-wp1a",
        ],
        service_factory=fail_factory,
        preflight_action=lambda arguments: {"status": "PASS", "sha256": "d" * 64, "snapshot": {}},
        setup_failure_action=setup_failure,
    )

    assert result == 1
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "FAIL"


def test_promote_action_calls_explicit_baseline_promotion(monkeypatch, tmp_path):
    calls = []

    def promote(baseline, report, **kwargs):
        calls.append((baseline, report, kwargs))
        return {"scopes": []}

    result = main(
        [
            "promote",
            "--baseline", str(tmp_path / "baseline.json"),
            "--report", str(tmp_path / "report.json"),
        ],
        promote_action=promote,
    )

    assert result == 0
    assert calls[0][0] == tmp_path / "baseline.json"
    assert calls[0][1] == tmp_path / "report.json"
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run `pytest -q tests/test_lcc_native_acceptance_cli.py`.

Expected: module import failure.

- [ ] **Step 3: Implement CLI and real service factory**

Create `native_acceptance_cli.py` with this header, parser, preflight, and factory:

```python
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ....acceptance.preflight import PreflightRequest, run_static_preflight
from ....core.backend.legacy import LegacyBackend
from ....core.executor import robust_executor
from ....core.master_bindings import audit_master_bindings
from ....core.path_policy import PathPolicy
from ....core.process_inventory import list_pscad_processes
from ....core.service import PscadService
from .assets import load_packaged_asset_set, sha256_file
from .blank_service import BlankLccBuilderService
from .native_acceptance import (
    NATIVE_SCOPE,
    NativeLccAcceptanceRequest,
    promote_native_lcc_report,
    run_native_lcc_acceptance,
    write_native_lcc_setup_failure_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="action", required=True)
    run = subcommands.add_parser("run")
    run.add_argument("--repository-root", type=Path, required=True)
    run.add_argument("--workspace-root", type=Path, required=True)
    run.add_argument("--template-path", type=Path, required=True)
    run.add_argument("--master-path", type=Path, required=True)
    run.add_argument("--compiler-configuration", type=Path, required=True)
    run.add_argument("--compiler-executable", type=Path, required=True)
    run.add_argument("--report", type=Path, required=True)
    run.add_argument("--commit", required=True)
    run.add_argument("--branch", required=True)
    run.add_argument("--project-name", default="WP1A_NATIVE_LCC")
    promote = subcommands.add_parser("promote")
    promote.add_argument("--baseline", type=Path, required=True)
    promote.add_argument("--report", type=Path, required=True)
    return parser


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _preflight(arguments: argparse.Namespace) -> dict[str, Any]:
    try:
        report = run_static_preflight(
            PreflightRequest(
                repository_root=arguments.repository_root,
                workspace_root=arguments.workspace_root,
                master_path=arguments.master_path,
                compiler_configuration=arguments.compiler_configuration,
                compiler_executable=arguments.compiler_executable,
                expected_commit=arguments.commit,
                expected_branch=arguments.branch,
                read_only_sources=(arguments.template_path,),
            )
        )
    except Exception as error:  # noqa: BLE001 - persist setup failure evidence
        report = {
            "schema_version": 1,
            "status": "FAIL",
            "error": {"type": type(error).__name__, "message": str(error)[:1024]},
        }
    return {
        "status": str(report["status"]),
        "sha256": _canonical_hash(report),
        "snapshot": report,
    }


def _service_factory(request: NativeLccAcceptanceRequest):
    assets = load_packaged_asset_set()
    if assets.master_bindings is None:
        raise RuntimeError("Packaged Master registry is unavailable.")
    audited = audit_master_bindings(request.master_path, assets.master_bindings)
    backend = LegacyBackend(
        robust_executor,
        version="4.6.2",
        x64=True,
        definition_paths={"master": request.master_path},
        process_probe=list_pscad_processes,
    )
    service = PscadService(
        lambda: backend,
        executor=robust_executor,
        path_policy=PathPolicy(workspace_root=str(request.workspace_root)),
    )
    builder = BlankLccBuilderService(
        service,
        workspace_root=request.workspace_root,
        master_registry=audited,
    )
    manifest = (
        request.repository_root
        / "pscad_mcp"
        / "assets"
        / "lcc"
        / "cigre_lcc_monopole_v1"
        / "manifest.json"
    )
    registry_path = (
        request.repository_root
        / "pscad_mcp"
        / "assets"
        / "lcc"
        / "cigre_lcc_monopole_v1"
        / "master-bindings-pscad-4.6.2.json"
    )
    return (
        service,
        builder,
        audited.registry.sha256,
        sha256_file(registry_path),
        sha256_file(manifest),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    run_action: Callable[..., Any] = run_native_lcc_acceptance,
    promote_action: Callable[..., Any] = promote_native_lcc_report,
    service_factory: Callable[[NativeLccAcceptanceRequest], tuple[Any, Any, str, str, str]] = _service_factory,
    preflight_action: Callable[[argparse.Namespace], dict[str, Any]] = _preflight,
    setup_failure_action: Callable[..., dict[str, Any]] = write_native_lcc_setup_failure_report,
) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.action == "promote":
        promote_action(
            arguments.baseline,
            arguments.report,
        )
        print(f"NATIVE_LCC_PROMOTED={NATIVE_SCOPE}")
        return 0

    workspace = arguments.workspace_root.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    report_path = arguments.report.resolve()
    try:
        report_path.relative_to(workspace)
    except ValueError as error:
        raise SystemExit("--report must be inside --workspace-root") from error
    preflight = preflight_action(arguments)
    request = NativeLccAcceptanceRequest(
        repository_root=arguments.repository_root.resolve(),
        workspace_root=workspace,
        template_path=arguments.template_path.resolve(),
        master_path=arguments.master_path.resolve(),
        report_path=report_path,
        project_name=arguments.project_name,
        commit=arguments.commit,
        branch=arguments.branch,
        registry_sha256="0" * 64,
        registry_file_sha256="0" * 64,
        asset_manifest_sha256="0" * 64,
        preflight=preflight,
    )
    try:
        service, builder, registry_hash, registry_file_hash, manifest_hash = service_factory(request)
    except Exception as error:  # noqa: BLE001 - persist setup failure evidence
        result = setup_failure_action(request, error)
        print(f"NATIVE_LCC_ACCEPTANCE={result['status']}")
        print(f"NATIVE_LCC_REPORT={report_path}")
        print(f"NATIVE_LCC_REPORT_SHA256={sha256_file(report_path)}")
        print(f"NATIVE_LCC_COMMIT={result['commit']}")
        return 1
    request = NativeLccAcceptanceRequest(
        **{
            **request.__dict__,
            "registry_sha256": registry_hash,
            "registry_file_sha256": registry_file_hash,
            "asset_manifest_sha256": manifest_hash,
        }
    )
    result = asyncio.run(run_action(request, service=service, builder=builder))
    print(f"NATIVE_LCC_ACCEPTANCE={result['status']}")
    print(f"NATIVE_LCC_REPORT={report_path}")
    print(f"NATIVE_LCC_REPORT_SHA256={sha256_file(report_path)}")
    print(f"NATIVE_LCC_COMMIT={result['commit']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI and focused tests**

Run:

```powershell
pytest -q tests/test_lcc_native_acceptance_cli.py tests/test_lcc_native_acceptance.py tests/test_program_baseline_promotion.py
ruff check pscad_mcp/hvdc/builders/lcc/native_acceptance*.py tests/test_lcc_native_acceptance*.py
```

Expected: all pass.

- [ ] **Step 5: Commit CLI**

```powershell
git add pscad_mcp/hvdc/builders/lcc/native_acceptance_cli.py tests/test_lcc_native_acceptance_cli.py
git commit -m "feat: add native LCC acceptance CLI"
```

### Task 5: PowerShell Runner and Opt-In Licensed Gate

**Files:**
- Create: `scripts/run_blank_lcc_native_acceptance.ps1`
- Create: `tests/test_lcc_native_acceptance_real.py`
- Modify: `tests/test_lcc_native_acceptance_cli.py`

- [ ] **Step 1: Add failing runner contract test**

Append:

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_powershell_runner_is_run_only_and_checks_cleanup():
    script = (ROOT / "scripts" / "run_blank_lcc_native_acceptance.ps1").read_text(encoding="utf-8")
    assert "native_acceptance_cli" in script
    assert "'run'" in script
    assert "'promote'" not in script
    assert "NATIVE_LCC_REPORT_SHA256=" in script
    assert "Get-Process" in script
    assert "source_after" in script or "sources.template.after" in script
```

Run `pytest -q tests/test_lcc_native_acceptance_cli.py -k powershell` and verify
failure because the script is absent.

- [ ] **Step 2: Create the PowerShell runner**

Create `scripts/run_blank_lcc_native_acceptance.ps1`:

```powershell
[CmdletBinding()]
param(
    [string]$Workspace = 'D:\PSCAD-Workspace\lcc-wp1a-native-acceptance',
    [string]$Template = 'D:\pscad-mcp-example-inspection-20260829\cigre_lcc_bidirectional\Cigre_LCC_Bidirectional.pscx',
    [string]$MasterLibrary = 'C:\Program Files (x86)\PSCAD46\master.pslx',
    [string]$CompilerConfiguration = 'C:\Program Files (x86)\PSCAD46\fortran_compilers.xml',
    [string]$CompilerExecutable = 'C:\Program Files (x86)\GFortran\4.6\bin\gfortran.exe',
    [string]$ProjectName = 'WP1A_NATIVE_LCC',
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $localPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    $commonDirectory = (& git -C $repoRoot rev-parse --path-format=absolute --git-common-dir).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve Git common directory.' }
    $commonPython = Join-Path (Split-Path -Parent $commonDirectory) '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $Python = $localPython
    } elseif (Test-Path -LiteralPath $commonPython -PathType Leaf) {
        $Python = $commonPython
    } else {
        throw 'Virtual-environment Python was not found.'
    }
}
foreach ($path in @($Python, $Template, $MasterLibrary, $CompilerConfiguration, $CompilerExecutable)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required file was not found: $path"
    }
}
$commit = (& git -C $repoRoot rev-parse HEAD).Trim()
$branch = (& git -C $repoRoot branch --show-current).Trim()
if (-not $branch) { throw 'Native acceptance requires a named branch.' }
if (@(& git -C $repoRoot status --porcelain).Count -ne 0) {
    throw 'Commit or remove repository changes before native acceptance.'
}
if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object ProcessName -Like 'PSCAD*').Count -ne 0) {
    throw 'Close existing PSCAD processes before native acceptance.'
}
$null = New-Item -ItemType Directory -Path $Workspace -Force
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runRoot = Join-Path $Workspace "native-lcc-$stamp"
New-Item -ItemType Directory -Path $runRoot -Force:$false | Out-Null
$report = Join-Path $runRoot 'native-lcc-acceptance-report.json'

Push-Location $repoRoot
try {
    $arguments = @(
        '-m', 'pscad_mcp.hvdc.builders.lcc.native_acceptance_cli',
        'run',
        '--repository-root', $repoRoot,
        '--workspace-root', $runRoot,
        '--template-path', $Template,
        '--master-path', $MasterLibrary,
        '--compiler-configuration', $CompilerConfiguration,
        '--compiler-executable', $CompilerExecutable,
        '--report', $report,
        '--project-name', $ProjectName,
        '--commit', $commit,
        '--branch', $branch
    )
    & $Python @arguments
    $nativeExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
    throw "Native LCC report was not written: $report"
}
$payload = Get-Content -Raw -LiteralPath $report | ConvertFrom-Json
if ($nativeExitCode -ne 0 -or $payload.status -ne 'PASS') {
    throw "Native LCC acceptance failed; inspect $report"
}
if ($payload.commit -ne $commit -or $payload.capability_state -ne 'simulated') {
    throw 'Native LCC report commit or capability is invalid.'
}
foreach ($name in @('disturbance', 'failure_indication', 'bounded_dc_response', 'recovered')) {
    if ($payload.acceptance.checks.$name -ne $true) {
        throw "Native LCC check failed: $name"
    }
}
if (
    $payload.sources.template.before -ne $payload.sources.template.after -or
    $payload.sources.master.before -ne $payload.sources.master.after
) {
    throw 'Native LCC source_after evidence differs from source_before.'
}
if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object ProcessName -Like 'PSCAD*').Count -ne 0) {
    throw 'Native LCC acceptance left PSCAD processes running.'
}
$reportHash = (Get-FileHash -LiteralPath $report -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output 'NATIVE_LCC_ACCEPTANCE=PASS'
Write-Output "NATIVE_LCC_REPORT=$report"
Write-Output "NATIVE_LCC_REPORT_SHA256=$reportHash"
Write-Output "NATIVE_LCC_COMMIT=$commit"
```

- [ ] **Step 3: Add the opt-in real test**

Create `tests/test_lcc_native_acceptance_real.py`:

```python
from __future__ import annotations

import json
import os
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pscad_mcp.acceptance import index_explicit_reports
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.lcc.assets import sha256_file
from pscad_mcp.hvdc.builders.lcc.native_acceptance_cli import main


@unittest.skipUnless(
    os.getenv("PSCAD_MCP_LCC_WP1A_ACCEPTANCE") == "1",
    "Set PSCAD_MCP_LCC_WP1A_ACCEPTANCE=1 for licensed native LCC acceptance.",
)
class TestNativeLccAcceptanceReal(unittest.TestCase):
    def test_current_commit_native_build_simulates_and_reports_pass(self):
        root = Path(__file__).parents[1]
        workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"])
        template = Path(os.environ["PSCAD_MCP_LCC_TEMPLATE"])
        master = Path(os.environ["PSCAD_MCP_MASTER_LIBRARY"])
        compiler_configuration = Path(os.environ["PSCAD_MCP_COMPILER_CONFIGURATION"])
        compiler_executable = Path(os.environ["PSCAD_MCP_COMPILER_EXECUTABLE"])
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        run_root = workspace / (
            "native-lcc-test-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        )
        report_path = run_root / "native-lcc-acceptance-report.json"
        baseline = root / "docs" / "acceptance" / "lcc-mmc-program-baseline.json"
        baseline_before = sha256_file(baseline)

        exit_code = main(
            [
                "run",
                "--repository-root", str(root),
                "--workspace-root", str(run_root),
                "--template-path", str(template),
                "--master-path", str(master),
                "--compiler-configuration", str(compiler_configuration),
                "--compiler-executable", str(compiler_executable),
                "--report", str(report_path),
                "--commit", commit,
                "--branch", branch,
                "--project-name", "WP1A_NATIVE_LCC_TEST",
            ]
        )

        payload = json.loads(report_path.read_text(encoding="utf-8"))
        indexed = index_explicit_reports([{"path": str(report_path)}])[0]
        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(indexed["status"], "PASS")
        self.assertEqual(indexed["commit"], commit)
        self.assertEqual(payload["build"]["terminal_state"], "published")
        self.assertTrue(all(payload["acceptance"]["checks"].values()))
        self.assertEqual(payload["sources"]["template"]["before"], payload["sources"]["template"]["after"])
        self.assertEqual(payload["sources"]["master"]["before"], payload["sources"]["master"]["after"])
        self.assertEqual(list_pscad_processes(), [])
        self.assertEqual(sha256_file(baseline), baseline_before)
```

- [ ] **Step 4: Run offline runner tests and parse the script**

Run:

```powershell
pytest -q tests/test_lcc_native_acceptance_cli.py tests/test_lcc_native_acceptance_real.py
$tokens=$null; $errors=$null
[void][System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path 'scripts/run_blank_lcc_native_acceptance.ps1'),
  [ref]$tokens,
  [ref]$errors
)
if ($errors.Count) { $errors | Format-List; exit 1 }
```

Expected: CLI tests pass, real test skips, PowerShell parse has zero errors.

- [ ] **Step 5: Commit runner and real gate**

```powershell
git add scripts/run_blank_lcc_native_acceptance.ps1 tests/test_lcc_native_acceptance_cli.py tests/test_lcc_native_acceptance_real.py
git commit -m "test: add licensed native LCC acceptance runner"
```

### Task 6: Licensed Run and Explicit Baseline Promotion

**Files:**
- Modify after PASS: `docs/acceptance/lcc-mmc-program-baseline.json`
- Modify after PASS: `README.md`
- Modify after PASS: `docs/zh-CN/README.md`
- Modify after PASS: `tests/test_lcc_mmc_program_baseline.py`
- Test: existing and new focused tests

- [ ] **Step 1: Run all offline gates on a clean implementation commit**

Run:

```powershell
pytest -q `
  tests/test_program_baseline_promotion.py `
  tests/test_lcc_native_acceptance.py `
  tests/test_lcc_native_acceptance_cli.py `
  tests/test_lcc_native_acceptance_real.py `
  tests/test_blank_lcc_service.py `
  tests/test_lcc_native_template.py `
  tests/test_lcc_acceptance.py `
  tests/test_lcc_mmc_program_baseline.py
ruff check `
  pscad_mcp/acceptance `
  pscad_mcp/hvdc/builders/lcc/native_acceptance.py `
  pscad_mcp/hvdc/builders/lcc/native_acceptance_cli.py `
  tests/test_program_baseline_promotion.py `
  tests/test_lcc_native_acceptance.py `
  tests/test_lcc_native_acceptance_cli.py `
  tests/test_lcc_native_acceptance_real.py
git status --short
```

Expected: tests/lint pass, real test skips, worktree is clean.

- [ ] **Step 2: Run licensed native acceptance**

Run:

```powershell
& .\scripts\run_blank_lcc_native_acceptance.ps1 `
  -Workspace 'D:\PSCAD-Workspace\lcc-wp1a-native-acceptance'
```

Expected: the four `NATIVE_LCC_*` identity lines, PASS report, published journal,
immutable source/Master, and zero remaining processes.

- [ ] **Step 3: Inspect and re-index the exact report before promotion**

Set the exact path printed by Step 2, then run:

```powershell
$env:PSCAD_MCP_LCC_WP1A_REPORT = 'D:\PSCAD-Workspace\lcc-wp1a-native-acceptance\native-lcc-run\native-lcc-acceptance-report.json'
python -c "import os; from pscad_mcp.acceptance import index_explicit_reports; print(index_explicit_reports([{'path': os.environ['PSCAD_MCP_LCC_WP1A_REPORT']}])[0])"
```

Replace the example environment value with the exact printed path. Expected:
scope `lcc.blank_native`, kind `licensed_simulation`, capability `simulated`,
status `PASS`, and commit equal to clean HEAD.

- [ ] **Step 4: Promote only the native scope**

Run on the same still-clean checkout and exact report:

```powershell
python -m pscad_mcp.hvdc.builders.lcc.native_acceptance_cli promote `
  --baseline docs/acceptance/lcc-mmc-program-baseline.json `
  --report $env:PSCAD_MCP_LCC_WP1A_REPORT
```

Expected: only the baseline becomes modified. Its `lcc.blank_native` record is
`simulated/PASS`; every other scope has no new evidence, and older-commit PASS
records are invalidated.

- [ ] **Step 5: Verify and document the promoted baseline**

Run:

```powershell
pytest -q tests/test_program_baseline_promotion.py tests/test_lcc_mmc_program_baseline.py tests/test_acceptance_status_manifest.py
git diff --check
```

Update `test_checked_in_program_baseline_is_valid_and_scoped()` in
`tests/test_lcc_mmc_program_baseline.py`: remove the initial `reports == []` and
native `NOT_RUN_ON_CURRENT_COMMIT` assertions, then assert:

```python
native = scopes["lcc.blank_native"]
assert native["capability_state"] == "simulated"
assert native["licensed_status"] == "PASS"
assert isinstance(native["evidence_run_id"], str)
reports = {item["run_id"]: item for item in result["reports"]}
evidence = reports[native["evidence_run_id"]]
assert evidence["scope"] == "lcc.blank_native"
assert evidence["builder_path"] == "lcc.blank_native"
assert evidence["kind"] == "licensed_simulation"
assert evidence["status"] == "PASS"
assert evidence["commit"] == result["repository"]["base_commit"]
```

Add to `README.md` near the LCC acceptance section:

```markdown
The blank/native LCC path has current-commit licensed simulation evidence only
when `docs/acceptance/lcc-mmc-program-baseline.json` names an indexed PASS
report for `lcc.blank_native`. This is `simulated`, not fixed-autonomous or final
`accepted` evidence; independent-golden acceptance remains a WP6 gate.
```

Add to `docs/zh-CN/README.md`:

```markdown
blank/native LCC 只有在
`docs/acceptance/lcc-mmc-program-baseline.json` 为 `lcc.blank_native` 指向当前
提交的 indexed PASS report 时，才具有 licensed simulation evidence。该状态是
`simulated`，不代表 fixed autonomous 或最终 `accepted`；independent golden
仍由 WP6 验收。
```

- [ ] **Step 6: Commit promotion evidence**

```powershell
git add docs/acceptance/lcc-mmc-program-baseline.json README.md docs/zh-CN/README.md tests/test_lcc_mmc_program_baseline.py
git commit -m "docs: promote current native LCC simulation evidence"
```

### Task 7: WP1A Completion, Review, and Full Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md`
- Create: `docs/superpowers/specs/2026-08-30-lcc-wp1a-native-acceptance-completion.md`

- [ ] **Step 1: Run the full repository suite**

Run `pytest -q`.

Expected: all tests pass; only explicitly opt-in licensed suites skip.

- [ ] **Step 2: Request independent code review**

Review the implementation range against:

- `docs/superpowers/specs/2026-08-30-lcc-wp1a-native-acceptance-design.md`;
- this plan;
- the licensed report and promoted baseline.

Critical questions:

1. Can run mutate the checked-in baseline?
2. Can FAIL, historical, cross-scope, or cross-builder evidence be promoted?
3. Can a changed template/Master/report race create PASS?
4. Can a partial attach/build leave PSCAD running?
5. Does PASS remain `simulated`, not `accepted`?

Resolve all Critical and Important findings and rerun affected tests.

- [ ] **Step 3: Refresh licensed evidence only when review changes executable code**

If review changes Python or PowerShell execution behavior, commit those fixes,
rerun the PowerShell runner on that clean commit, re-index the new report, run
the explicit promotion again, and commit the refreshed baseline before writing
the completion record. If review produces no executable-code change, retain the
exact Task 6 report already promoted; do not create an unpromoted later-commit
report merely to change documentation. In both cases the completion record must
name the report whose commit equals `baseline.repository.base_commit`.

- [ ] **Step 4: Write the completion record**

Create the completion document with exact sections:

```markdown
# LCC WP1A Native Acceptance Completion Record

## Implementation Commit
## Official and Master Inputs
## Build and Journal Evidence
## Physical Acceptance Evidence
## Durable Report Identity
## Baseline Transition
## Test and Review Evidence
## Explicit Exclusions
## WP1B Unlock Decision
```

Every section must contain actual values. No PASS claim may omit report path,
hash, commit, all four checks, source/Master immutability, and cleanup evidence.
Update the roadmap only to mark WP1A complete and WP1B unlocked.

- [ ] **Step 5: Commit completion record**

```powershell
git add `
  docs/superpowers/specs/2026-08-30-lcc-wp1a-native-acceptance-completion.md `
  docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md
git commit -m "docs: record WP1A native LCC acceptance"
```

- [ ] **Step 6: Run final post-commit verification**

Run:

```powershell
pytest -q `
  tests/test_program_baseline_promotion.py `
  tests/test_lcc_native_acceptance.py `
  tests/test_lcc_native_acceptance_cli.py `
  tests/test_lcc_native_acceptance_real.py `
  tests/test_lcc_mmc_program_baseline.py `
  tests/test_acceptance_status_manifest.py
ruff check `
  pscad_mcp/acceptance `
  pscad_mcp/hvdc/builders/lcc/native_acceptance.py `
  pscad_mcp/hvdc/builders/lcc/native_acceptance_cli.py `
  tests/test_program_baseline_promotion.py `
  tests/test_lcc_native_acceptance.py `
  tests/test_lcc_native_acceptance_cli.py `
  tests/test_lcc_native_acceptance_real.py
git status --short
git diff --check
```

Expected: tests/lint pass, offline real test skips, and worktree is clean.

## WP1A Exit Criteria

- strict report and promotion tests pass;
- run phase never modifies repository files;
- official source and Master/registry hashes remain unchanged;
- production blank/native builder reaches `published` with exact history;
- real outputs support all four required checks;
- durable report re-indexes on its exact commit;
- PSCAD cleanup leaves zero processes;
- explicit promotion changes only `lcc.blank_native` to `simulated/PASS`;
- no `accepted`, fixed, parametric, golden, Master-scope, or MMC claim is added;
- full suite, lint, independent review, and final licensed rerun pass.

## Self-Review Checklist

- Spec coverage: Tasks 1-7 cover two-phase run/promotion, report schema, lifecycle orchestration, CLI/runner, licensed evidence, baseline update, review, and completion.
- Placeholder scan: Dynamic licensed identities are obtained from exact runner output; implementation steps contain no unspecified code work.
- Type consistency: `NativeLccAcceptanceRequest`, `validate_native_lcc_acceptance_report`, `run_native_lcc_acceptance`, `advance_and_apply_scope_report`, and `promote_program_report` retain identical names across code, tests, CLI, and runner.
- Scope check: No electrical-model, fixed-builder, parametric, golden, MMC, or PSCAD 5.x implementation is included.
