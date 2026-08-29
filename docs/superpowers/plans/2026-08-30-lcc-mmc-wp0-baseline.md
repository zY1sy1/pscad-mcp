# LCC/MMC WP0 Evidence Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a strict, machine-readable LCC/MMC program baseline that records current repository, PSCAD environment, source, asset, report, and scope evidence without changing any electrical model.

**Architecture:** Add a small `pscad_mcp.acceptance` package with four responsibilities: strict baseline validation and state rules, report-owned run metadata plus explicit evidence-file indexing, static/licensed environment preflight, and a durable report-producing CLI. A checked-in baseline JSON records only scoped truth; a PowerShell runner writes timestamped preflight evidence without creating PSCAD projects or mutating source files.

**Tech Stack:** Python 3.10+, dataclasses, `json`, `hashlib`, `xml.etree.ElementTree`, `importlib.util`, `subprocess`, `psutil`, existing `PscadService`/`LegacyBackend`, pytest, PowerShell.

---

## Scope Boundaries

This WP creates evidence infrastructure only. It must not:

- modify LCC/MMC blueprints, catalogs, companion libraries, planners, or executors;
- update `docs/acceptance-status.json` scope meanings;
- launch a simulation or create a PSCAD project;
- infer PASS from a journal/report whose commit is absent or different;
- recursively trust arbitrary workspace JSON files;
- copy acceptance projects or output files into the repository.

## File Map

- Create `pscad_mcp/acceptance/__init__.py`: public WP0 API exports.
- Create `pscad_mcp/acceptance/baseline.py`: strict schema, canonical serialization, scope transition rules.
- Create `pscad_mcp/acceptance/evidence.py`: explicit report descriptors, regular-file/hash/JSON indexing.
- Create `pscad_mcp/acceptance/preflight.py`: static and licensed-session preflight.
- Create `pscad_mcp/acceptance/preflight_cli.py`: report-producing command-line entry point.
- Create `docs/acceptance/lcc-mmc-program-baseline.json`: checked-in current truth for LCC/MMC program scopes.
- Create `scripts/run_lcc_mmc_program_preflight.ps1`: timestamped licensed preflight runner.
- Create `tests/test_lcc_mmc_program_baseline.py`: schema and scope truth tests.
- Create `tests/test_lcc_mmc_evidence_index.py`: report indexing and path safety tests.
- Create `tests/test_lcc_mmc_preflight.py`: static/session preflight unit tests.
- Create `tests/test_lcc_mmc_preflight_cli.py`: CLI containment, output, and exit-code tests.
- Create `tests/test_lcc_mmc_preflight_real.py`: opt-in PSCAD 4.6.2 session probe.
- Create `docs/superpowers/specs/2026-08-30-lcc-mmc-wp0-baseline-design.md`: actual WP0 completion evidence and unlock decision.
- Modify `README.md`: link to program baseline and state its scope.
- Modify `docs/zh-CN/README.md`: Chinese usage/status explanation.

## Shared Constants

Use these exact program scopes:

```python
PROGRAM_SCOPES = frozenset(
    {
        "lcc.master_bindings",
        "lcc.blank_native",
        "lcc.fixed_autonomous",
        "lcc.parametric",
        "mmc.blank_native_full_bridge",
        "mmc.detailed_pwm_full_bridge",
        "mmc.avm_full_bridge",
        "mmc.avm_half_bridge",
        "mmc.parametric",
    }
)
```

Use this exact scope-to-builder ownership map. A report may update a scope only
when its report-owned `builder_path` equals the mapped value:

```python
SCOPE_BUILDER_PATHS = {
    "lcc.master_bindings": "lcc.master_binding_registry",
    "lcc.blank_native": "lcc.blank_native",
    "lcc.fixed_autonomous": "lcc.fixed_autonomous",
    "lcc.parametric": "lcc.parametric",
    "mmc.blank_native_full_bridge": "mmc.blank_native_full_bridge",
    "mmc.detailed_pwm_full_bridge": "mmc.detailed_pwm_full_bridge",
    "mmc.avm_full_bridge": "mmc.avm_full_bridge",
    "mmc.avm_half_bridge": "mmc.avm_half_bridge",
    "mmc.parametric": "mmc.parametric_orchestrator",
}
```

Use these exact capability states:

```python
CAPABILITY_STATES = frozenset(
    {
        "inspected",
        "planned",
        "built",
        "compiled",
        "simulated",
        "accepted",
        "INCOMPLETE_ANALYSIS",
        "failed",
    }
)
```

Use these exact licensed statuses:

```python
LICENSED_STATUSES = frozenset(
    {
        "PASS",
        "FAIL",
        "INCOMPLETE_ANALYSIS",
        "NOT_RUN_ON_CURRENT_COMMIT",
    }
)
```

### Task 1: Strict Program Baseline Schema

**Files:**
- Create: `pscad_mcp/acceptance/__init__.py`
- Create: `pscad_mcp/acceptance/baseline.py`
- Test: `tests/test_lcc_mmc_program_baseline.py`

- [ ] **Step 1: Write the failing baseline parser tests**

Create `tests/test_lcc_mmc_program_baseline.py` with this initial fixture and tests:

```python
from __future__ import annotations

import copy

import pytest

from pscad_mcp.core.backend.base import BackendError


def valid_baseline() -> dict[str, object]:
    return {
        "schema_version": 1,
        "baseline_id": "lcc-mmc-program-2026-08-30",
        "generated_at_utc": "2026-08-30T00:00:00Z",
        "repository": {
            "base_commit": "dadd739e2abc14dcc7de73149da7fd7f0c0ca763",
            "branch": "main",
            "worktree_clean": True,
        },
        "environment": {
            "backend": "legacy",
            "pscad_version": "4.6.2",
            "x64": True,
            "automation_module": "mhrc.automation",
            "master_path": "C:/Program Files (x86)/PSCAD46/master.pslx",
            "master_sha256": "0" * 64,
            "compiler": {
                "identity": "gfortran",
                "configuration_path": "C:/Program Files (x86)/PSCAD46/fortran_compilers.xml",
                "configuration_sha256": "1" * 64,
                "executable_path": "C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe",
                "executable_sha256": "3" * 64,
            },
        },
        "sources": [],
        "assets": [],
        "reports": [
            {
                "run_id": "master-binding-20260829-173320-618412",
                "scope": "lcc.master_bindings",
                "builder_path": "lcc.master_binding_registry",
                "kind": "licensed_compile",
                "capability_state": "compiled",
                "status": "PASS",
                "commit": "dadd739e2abc14dcc7de73149da7fd7f0c0ca763",
                "generated_at_utc": "2026-08-29T17:33:20Z",
                "path": "D:/PSCAD-Workspace/master-binding-acceptance/report.json",
                "sha256": "2" * 64,
                "availability": "verified_local",
            }
        ],
        "scopes": [
            {
                "scope": "lcc.master_bindings",
                "builder_path": "lcc.master_binding_registry",
                "owner_work_package": "WP1",
                "capability_state": "compiled",
                "licensed_status": "PASS",
                "evidence_run_id": "master-binding-20260829-173320-618412",
                "explicit_exclusions": ["full_lcc_waveform_acceptance"],
            }
        ],
    }


def subject():
    from pscad_mcp.acceptance.baseline import validate_program_baseline

    return validate_program_baseline


def test_valid_baseline_is_canonical_and_does_not_mutate_input():
    payload = valid_baseline()
    original = copy.deepcopy(payload)

    result = subject()(payload)

    assert payload == original
    assert result["schema_version"] == 1
    assert result["scopes"][0]["scope"] == "lcc.master_bindings"


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        (lambda value: value.update(extra=True), "baseline"),
        (lambda value: value["repository"].update(extra=True), "repository"),
        (lambda value: value["environment"].update(extra=True), "environment"),
        (lambda value: value["reports"][0].update(extra=True), "reports[0]"),
        (lambda value: value["scopes"][0].update(extra=True), "scopes[0]"),
    ],
)
def test_unknown_fields_are_rejected(mutation, field):
    payload = valid_baseline()
    mutation(payload)

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.code == "PROGRAM_BASELINE_INVALID"
    assert failure.value.details["field"] == field


def test_pass_requires_same_scope_same_commit_durable_report():
    payload = valid_baseline()
    payload["reports"][0]["commit"] = "f" * 40

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.code == "PROGRAM_BASELINE_INVALID"
    assert failure.value.details["reason"] == "pass_commit_mismatch"


def test_pass_rejects_non_durable_report_availability():
    payload = valid_baseline()
    payload["reports"][0]["availability"] = "historical_commit_unknown"

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.details["reason"] == "pass_evidence_not_durable"


def test_compile_report_cannot_claim_accepted_capability():
    payload = valid_baseline()
    payload["reports"][0]["capability_state"] = "accepted"
    payload["scopes"][0]["capability_state"] = "accepted"

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.details["reason"] == "kind_state_mismatch"


def test_duplicate_scope_and_run_id_are_rejected():
    payload = valid_baseline()
    payload["reports"].append(copy.deepcopy(payload["reports"][0]))

    with pytest.raises(BackendError) as failure:
        subject()(payload)

    assert failure.value.details["reason"] == "duplicate_run_id"
```

- [ ] **Step 2: Run the parser tests and verify RED**

Run:

```powershell
pytest -q tests/test_lcc_mmc_program_baseline.py
```

Expected: tests fail because `pscad_mcp.acceptance.baseline` does not exist.

- [ ] **Step 3: Implement the strict parser and canonical serializer**

Create `pscad_mcp/acceptance/__init__.py`:

```python
"""Scoped LCC/MMC acceptance evidence and environment preflight."""

from .baseline import (
    CAPABILITY_STATES,
    LICENSED_STATUSES,
    PROGRAM_SCOPES,
    SCOPE_BUILDER_PATHS,
    canonical_program_baseline,
    program_baseline_sha256,
    validate_program_baseline,
)

__all__ = [
    "CAPABILITY_STATES",
    "LICENSED_STATUSES",
    "PROGRAM_SCOPES",
    "SCOPE_BUILDER_PATHS",
    "canonical_program_baseline",
    "program_baseline_sha256",
    "validate_program_baseline",
]
```

Create `pscad_mcp/acceptance/baseline.py` with these public constants and APIs:

```python
"""Strict current-truth baseline for LCC/MMC implementation scopes."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from ..core.backend.base import BackendError


PROGRAM_SCOPES = frozenset(
    {
        "lcc.master_bindings",
        "lcc.blank_native",
        "lcc.fixed_autonomous",
        "lcc.parametric",
        "mmc.blank_native_full_bridge",
        "mmc.detailed_pwm_full_bridge",
        "mmc.avm_full_bridge",
        "mmc.avm_half_bridge",
        "mmc.parametric",
    }
)
SCOPE_BUILDER_PATHS = {
    "lcc.master_bindings": "lcc.master_binding_registry",
    "lcc.blank_native": "lcc.blank_native",
    "lcc.fixed_autonomous": "lcc.fixed_autonomous",
    "lcc.parametric": "lcc.parametric",
    "mmc.blank_native_full_bridge": "mmc.blank_native_full_bridge",
    "mmc.detailed_pwm_full_bridge": "mmc.detailed_pwm_full_bridge",
    "mmc.avm_full_bridge": "mmc.avm_full_bridge",
    "mmc.avm_half_bridge": "mmc.avm_half_bridge",
    "mmc.parametric": "mmc.parametric_orchestrator",
}
CAPABILITY_STATES = frozenset(
    {
        "inspected",
        "planned",
        "built",
        "compiled",
        "simulated",
        "accepted",
        "INCOMPLETE_ANALYSIS",
        "failed",
    }
)
LICENSED_STATUSES = frozenset(
    {"PASS", "FAIL", "INCOMPLETE_ANALYSIS", "NOT_RUN_ON_CURRENT_COMMIT"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TOP = {
    "schema_version",
    "baseline_id",
    "generated_at_utc",
    "repository",
    "environment",
    "sources",
    "assets",
    "reports",
    "scopes",
}
_REPOSITORY = {"base_commit", "branch", "worktree_clean"}
_ENVIRONMENT = {
    "backend",
    "pscad_version",
    "x64",
    "automation_module",
    "master_path",
    "master_sha256",
    "compiler",
}
_COMPILER = {
    "identity",
    "configuration_path",
    "configuration_sha256",
    "executable_path",
    "executable_sha256",
}
_SOURCE = {"source_id", "kind", "path", "sha256", "availability"}
_ASSET = {"asset_id", "scope", "path", "sha256"}
_REPORT = {
    "run_id",
    "scope",
    "builder_path",
    "kind",
    "capability_state",
    "status",
    "commit",
    "generated_at_utc",
    "path",
    "sha256",
    "availability",
}
_SCOPE = {
    "scope",
    "builder_path",
    "owner_work_package",
    "capability_state",
    "licensed_status",
    "evidence_run_id",
    "explicit_exclusions",
}


def _error(field: str, reason: str, message: str) -> BackendError:
    return BackendError(
        "PROGRAM_BASELINE_INVALID",
        message,
        "acceptance",
        "validate_program_baseline",
        {"field": field, "reason": reason},
    )


def _record(value: Any, field: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(field, "not_object", f"{field} must be an object.")
    unknown = sorted(set(value) - keys)
    missing = sorted(keys - set(value))
    if unknown or missing:
        failure = _error(field, "field_set", f"{field} has an invalid field set.")
        failure.details.update({"unknown": unknown, "missing": missing})
        raise failure
    return dict(value)


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _error(field, "not_array", f"{field} must be an array.")
    return list(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(field, "not_text", f"{field} must be non-empty text.")
    return value.strip()


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if _SHA256.fullmatch(text) is None:
        raise _error(field, "not_sha256", f"{field} must be lowercase SHA-256.")
    return text


def _commit(value: Any, field: str) -> str:
    text = _text(value, field)
    if _COMMIT.fullmatch(text) is None:
        raise _error(field, "not_commit", f"{field} must be a full git commit.")
    return text


def validate_program_baseline(value: Any) -> dict[str, Any]:
    top = _record(value, "baseline", _TOP)
    if top["schema_version"] != 1 or isinstance(top["schema_version"], bool):
        raise _error("schema_version", "unsupported", "schema_version must be 1.")
    repository = _record(top["repository"], "repository", _REPOSITORY)
    repository["base_commit"] = _commit(repository["base_commit"], "repository.base_commit")
    repository["branch"] = _text(repository["branch"], "repository.branch")
    if not isinstance(repository["worktree_clean"], bool):
        raise _error("repository.worktree_clean", "not_boolean", "worktree_clean must be boolean.")

    environment = _record(top["environment"], "environment", _ENVIRONMENT)
    environment["backend"] = _text(environment["backend"], "environment.backend")
    environment["pscad_version"] = _text(environment["pscad_version"], "environment.pscad_version")
    if environment["backend"] != "legacy" or environment["pscad_version"] != "4.6.2":
        raise _error("environment", "unsupported_runtime", "WP0 requires Legacy PSCAD 4.6.2.")
    if not isinstance(environment["x64"], bool):
        raise _error("environment.x64", "not_boolean", "x64 must be boolean.")
    environment["automation_module"] = _text(environment["automation_module"], "environment.automation_module")
    environment["master_path"] = _text(environment["master_path"], "environment.master_path")
    environment["master_sha256"] = _sha(environment["master_sha256"], "environment.master_sha256")
    compiler = _record(environment["compiler"], "environment.compiler", _COMPILER)
    compiler["identity"] = _text(compiler["identity"], "environment.compiler.identity")
    compiler["configuration_path"] = _text(compiler["configuration_path"], "environment.compiler.configuration_path")
    compiler["configuration_sha256"] = _sha(
        compiler["configuration_sha256"], "environment.compiler.configuration_sha256"
    )
    compiler["executable_path"] = _text(
        compiler["executable_path"], "environment.compiler.executable_path"
    )
    compiler["executable_sha256"] = _sha(
        compiler["executable_sha256"], "environment.compiler.executable_sha256"
    )
    environment["compiler"] = compiler

    sources = []
    source_ids = set()
    for index, raw in enumerate(_array(top["sources"], "sources")):
        item = _record(raw, f"sources[{index}]", _SOURCE)
        item["source_id"] = _text(item["source_id"], f"sources[{index}].source_id")
        if item["source_id"] in source_ids:
            raise _error(f"sources[{index}]", "duplicate_source_id", "source_id must be unique.")
        source_ids.add(item["source_id"])
        item["kind"] = _text(item["kind"], f"sources[{index}].kind")
        item["path"] = _text(item["path"], f"sources[{index}].path")
        item["sha256"] = _sha(item["sha256"], f"sources[{index}].sha256")
        item["availability"] = _text(item["availability"], f"sources[{index}].availability")
        sources.append(item)

    assets = []
    asset_ids = set()
    for index, raw in enumerate(_array(top["assets"], "assets")):
        item = _record(raw, f"assets[{index}]", _ASSET)
        item["asset_id"] = _text(item["asset_id"], f"assets[{index}].asset_id")
        if item["asset_id"] in asset_ids:
            raise _error(f"assets[{index}]", "duplicate_asset_id", "asset_id must be unique.")
        asset_ids.add(item["asset_id"])
        item["scope"] = _text(item["scope"], f"assets[{index}].scope")
        item["path"] = _text(item["path"], f"assets[{index}].path")
        item["sha256"] = _sha(item["sha256"], f"assets[{index}].sha256")
        assets.append(item)

    reports = []
    reports_by_id = {}
    for index, raw in enumerate(_array(top["reports"], "reports")):
        item = _record(raw, f"reports[{index}]", _REPORT)
        item["run_id"] = _text(item["run_id"], f"reports[{index}].run_id")
        if item["run_id"] in reports_by_id:
            raise _error(f"reports[{index}]", "duplicate_run_id", "run_id must be unique.")
        item["scope"] = _text(item["scope"], f"reports[{index}].scope")
        if item["scope"] not in PROGRAM_SCOPES:
            raise _error(f"reports[{index}].scope", "unknown_scope", "Report scope is unknown.")
        item["builder_path"] = _text(
            item["builder_path"], f"reports[{index}].builder_path"
        )
        if item["builder_path"] != SCOPE_BUILDER_PATHS[item["scope"]]:
            raise _error(
                f"reports[{index}].builder_path",
                "builder_path_mismatch",
                "Report builder_path does not own its scope.",
            )
        item["kind"] = _text(item["kind"], f"reports[{index}].kind")
        item["capability_state"] = _text(
            item["capability_state"], f"reports[{index}].capability_state"
        )
        if item["capability_state"] not in CAPABILITY_STATES:
            raise _error(
                f"reports[{index}].capability_state",
                "unknown_state",
                "Report capability state is invalid.",
            )
        required_kind = {
            "compiled": "licensed_compile",
            "simulated": "licensed_simulation",
            "accepted": "licensed_acceptance",
        }.get(item["capability_state"])
        if required_kind is not None and item["kind"] != required_kind:
            raise _error(
                f"reports[{index}]",
                "kind_state_mismatch",
                "Report kind and capability state are inconsistent.",
            )
        item["status"] = _text(item["status"], f"reports[{index}].status")
        if item["status"] not in LICENSED_STATUSES:
            raise _error(f"reports[{index}].status", "unknown_status", "Report status is invalid.")
        item["commit"] = _commit(item["commit"], f"reports[{index}].commit")
        item["generated_at_utc"] = _text(
            item["generated_at_utc"], f"reports[{index}].generated_at_utc"
        )
        item["path"] = _text(item["path"], f"reports[{index}].path")
        item["sha256"] = _sha(item["sha256"], f"reports[{index}].sha256")
        item["availability"] = _text(item["availability"], f"reports[{index}].availability")
        reports_by_id[item["run_id"]] = item
        reports.append(item)

    scopes = []
    scope_names = set()
    for index, raw in enumerate(_array(top["scopes"], "scopes")):
        item = _record(raw, f"scopes[{index}]", _SCOPE)
        item["scope"] = _text(item["scope"], f"scopes[{index}].scope")
        if item["scope"] not in PROGRAM_SCOPES or item["scope"] in scope_names:
            reason = "duplicate_scope" if item["scope"] in scope_names else "unknown_scope"
            raise _error(f"scopes[{index}].scope", reason, "Scope must be known and unique.")
        scope_names.add(item["scope"])
        item["builder_path"] = _text(
            item["builder_path"], f"scopes[{index}].builder_path"
        )
        if item["builder_path"] != SCOPE_BUILDER_PATHS[item["scope"]]:
            raise _error(
                f"scopes[{index}].builder_path",
                "builder_path_mismatch",
                "Scope builder_path is invalid.",
            )
        item["owner_work_package"] = _text(
            item["owner_work_package"], f"scopes[{index}].owner_work_package"
        )
        item["capability_state"] = _text(item["capability_state"], f"scopes[{index}].capability_state")
        item["licensed_status"] = _text(item["licensed_status"], f"scopes[{index}].licensed_status")
        if item["capability_state"] not in CAPABILITY_STATES:
            raise _error(f"scopes[{index}].capability_state", "unknown_state", "Capability state is invalid.")
        if item["licensed_status"] not in LICENSED_STATUSES:
            raise _error(f"scopes[{index}].licensed_status", "unknown_status", "Licensed status is invalid.")
        evidence_run_id = item["evidence_run_id"]
        if evidence_run_id is not None:
            evidence_run_id = _text(evidence_run_id, f"scopes[{index}].evidence_run_id")
        item["evidence_run_id"] = evidence_run_id
        exclusions = [
            _text(entry, f"scopes[{index}].explicit_exclusions")
            for entry in _array(item["explicit_exclusions"], f"scopes[{index}].explicit_exclusions")
        ]
        item["explicit_exclusions"] = exclusions
        if item["licensed_status"] == "PASS":
            report = reports_by_id.get(str(evidence_run_id))
            if (
                report is None
                or report["status"] != "PASS"
                or report["scope"] != item["scope"]
                or report["builder_path"] != item["builder_path"]
                or report["capability_state"] != item["capability_state"]
            ):
                raise _error(f"scopes[{index}]", "pass_evidence_mismatch", "PASS requires same-scope PASS evidence.")
            if report["commit"] != repository["base_commit"]:
                raise _error(f"scopes[{index}]", "pass_commit_mismatch", "PASS evidence commit must match base_commit.")
            if report["availability"] != "verified_local":
                raise _error(
                    f"scopes[{index}]",
                    "pass_evidence_not_durable",
                    "PASS evidence must be a locally verified durable report.",
                )
        scopes.append(item)

    normalized = {
        "schema_version": 1,
        "baseline_id": _text(top["baseline_id"], "baseline_id"),
        "generated_at_utc": _text(top["generated_at_utc"], "generated_at_utc"),
        "repository": repository,
        "environment": environment,
        "sources": sources,
        "assets": assets,
        "reports": reports,
        "scopes": scopes,
    }
    return copy.deepcopy(normalized)


def canonical_program_baseline(value: Any) -> bytes:
    normalized = validate_program_baseline(value)
    return json.dumps(
        normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def program_baseline_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_program_baseline(value)).hexdigest()
```

- [ ] **Step 4: Run parser tests and verify GREEN**

Run:

```powershell
pytest -q tests/test_lcc_mmc_program_baseline.py
ruff check pscad_mcp/acceptance/baseline.py tests/test_lcc_mmc_program_baseline.py
```

Expected: all tests and lint checks pass.

- [ ] **Step 5: Commit the strict baseline schema**

```powershell
git add pscad_mcp/acceptance tests/test_lcc_mmc_program_baseline.py
git commit -m "feat: add strict LCC MMC program baseline schema"
```

### Task 2: Scope Transition and Ownership Rules

**Files:**
- Modify: `pscad_mcp/acceptance/baseline.py`
- Test: `tests/test_lcc_mmc_program_baseline.py`

- [ ] **Step 1: Add failing scope transition tests**

Append:

```python
def transition_subject():
    from pscad_mcp.acceptance.baseline import apply_scope_report

    return apply_scope_report


def test_report_updates_only_its_owned_scope():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["run_id"] = "master-binding-20260830-new"
    report["sha256"] = "3" * 64
    report["status"] = "INCOMPLETE_ANALYSIS"

    updated = transition_subject()(baseline, report, owner_work_package="WP1")

    assert updated["scopes"][0]["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert baseline["scopes"][0]["licensed_status"] == "PASS"


def test_cross_scope_or_wrong_owner_transition_is_rejected():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["scope"] = "mmc.parametric"

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.code == "PROGRAM_SCOPE_CONFLICT"


def test_cross_builder_transition_is_rejected():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["builder_path"] = "lcc.parametric"

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "builder_path_mismatch"


def test_historical_commit_never_updates_current_scope():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["commit"] = "f" * 40

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "historical_commit"


def test_run_id_cannot_be_reused_with_different_evidence():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["sha256"] = "f" * 64

    with pytest.raises(BackendError) as failure:
        transition_subject()(baseline, report, owner_work_package="WP1")

    assert failure.value.details["reason"] == "run_id_reuse"


def test_compile_pass_does_not_promote_scope_to_accepted():
    baseline = valid_baseline()
    report = copy.deepcopy(baseline["reports"][0])
    report["run_id"] = "compile-run-2"
    report["sha256"] = "4" * 64

    updated = transition_subject()(baseline, report, owner_work_package="WP1")

    assert updated["scopes"][0]["licensed_status"] == "PASS"
    assert updated["scopes"][0]["capability_state"] == "compiled"
```

- [ ] **Step 2: Run and confirm RED**

Run:

```powershell
pytest -q tests/test_lcc_mmc_program_baseline.py -k transition
```

Expected: failures because `apply_scope_report` is absent.

- [ ] **Step 3: Implement the transition function**

Add to `baseline.py`:

```python
def apply_scope_report(
    baseline: Any,
    report: Mapping[str, Any],
    *,
    owner_work_package: str,
) -> dict[str, Any]:
    current = validate_program_baseline(baseline)
    candidate = _record(report, "report", _REPORT)
    scope_name = _text(candidate["scope"], "report.scope")
    builder_path = _text(candidate["builder_path"], "report.builder_path")
    if (
        scope_name not in SCOPE_BUILDER_PATHS
        or builder_path != SCOPE_BUILDER_PATHS[scope_name]
    ):
        raise BackendError(
            "PROGRAM_SCOPE_CONFLICT",
            "The report builder_path does not own the requested scope.",
            "acceptance",
            "apply_scope_report",
            {"reason": "builder_path_mismatch", "scope": scope_name},
        )
    commit = _commit(candidate["commit"], "report.commit")
    if commit != current["repository"]["base_commit"]:
        raise BackendError(
            "PROGRAM_SCOPE_CONFLICT",
            "Historical evidence cannot update current program truth.",
            "acceptance",
            "apply_scope_report",
            {"reason": "historical_commit", "scope": scope_name},
        )
    matching = [item for item in current["scopes"] if item["scope"] == scope_name]
    if len(matching) != 1 or matching[0]["owner_work_package"] != owner_work_package:
        raise BackendError(
            "PROGRAM_SCOPE_CONFLICT",
            "The report does not belong to the requested work package scope.",
            "acceptance",
            "apply_scope_report",
            {"reason": "scope_owner_mismatch", "scope": scope_name},
        )
    status = _text(candidate["status"], "report.status")
    if status not in LICENSED_STATUSES:
        raise _error("report.status", "unknown_status", "Report status is invalid.")
    run_id = _text(candidate["run_id"], "report.run_id")
    previous = next(
        (item for item in current["reports"] if item["run_id"] == run_id),
        None,
    )
    if previous is not None and previous != candidate:
        raise BackendError(
            "PROGRAM_SCOPE_CONFLICT",
            "A run_id cannot be reused for different evidence.",
            "acceptance",
            "apply_scope_report",
            {"reason": "run_id_reuse", "run_id": run_id},
        )
    reports = [item for item in current["reports"] if item["run_id"] != run_id]
    reports.append(dict(candidate))
    scope = matching[0]
    scope["licensed_status"] = status
    scope["evidence_run_id"] = run_id
    scope["capability_state"] = _text(
        candidate["capability_state"], "report.capability_state"
    )
    updated = dict(current)
    updated["reports"] = reports
    updated["scopes"] = current["scopes"]
    return validate_program_baseline(updated)
```

- [ ] **Step 4: Run transition and parser tests**

Run:

```powershell
pytest -q tests/test_lcc_mmc_program_baseline.py
```

Expected: all pass.

- [ ] **Step 5: Commit scope ownership rules**

```powershell
git add pscad_mcp/acceptance/baseline.py tests/test_lcc_mmc_program_baseline.py
git commit -m "feat: enforce scoped acceptance status transitions"
```

### Task 3: Explicit Evidence Index

**Files:**
- Create: `pscad_mcp/acceptance/evidence.py`
- Modify: `pscad_mcp/acceptance/__init__.py`
- Test: `tests/test_lcc_mmc_evidence_index.py`

- [ ] **Step 1: Write failing evidence indexing tests**

Create `tests/test_lcc_mmc_evidence_index.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError


COMMIT = "dadd739e2abc14dcc7de73149da7fd7f0c0ca763"


def descriptor(path: Path) -> dict[str, str]:
    return {"path": str(path)}


def write_report(
    path: Path,
    status: str = "PASS",
    *,
    commit: str | None = COMMIT,
) -> None:
    payload = {"schema_version": 1, "status": status}
    payload.update(
        {
            "run_id": "run-1",
            "scope": "lcc.master_bindings",
            "builder_path": "lcc.master_binding_registry",
            "kind": "licensed_compile",
            "capability_state": "compiled",
            "generated_at_utc": "2026-08-29T17:33:20Z",
        }
    )
    if commit is not None:
        payload["commit"] = commit
    path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


def subject():
    from pscad_mcp.acceptance.evidence import index_explicit_reports

    return index_explicit_reports


def test_explicit_report_is_hashed_and_indexed(tmp_path):
    report = tmp_path / "report.json"
    write_report(report)

    indexed = subject()([descriptor(report)])

    assert indexed[0]["status"] == "PASS"
    assert indexed[0]["builder_path"] == "lcc.master_binding_registry"
    assert indexed[0]["availability"] == "verified_local"
    assert len(indexed[0]["sha256"]) == 64


def test_missing_symlink_and_duplicate_run_ids_are_rejected(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(BackendError) as failure:
        subject()([descriptor(missing)])
    assert failure.value.code == "PROGRAM_EVIDENCE_INVALID"

    target = tmp_path / "target.json"
    write_report(target)
    alias = tmp_path / "alias.json"
    try:
        alias.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    with pytest.raises(BackendError):
        subject()([descriptor(alias)])

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(target), descriptor(target)])
    assert failure.value.details["reason"] == "duplicate_run_id"


def test_report_without_self_attested_commit_is_historical_only(tmp_path):
    report = tmp_path / "report.json"
    write_report(report, commit=None)

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(report)])

    assert failure.value.details["reason"] == "missing_durable_commit"


def test_descriptor_cannot_supply_or_override_report_commit(tmp_path):
    report = tmp_path / "report.json"
    write_report(report)
    value = descriptor(report)
    value["commit"] = COMMIT

    with pytest.raises(BackendError) as failure:
        subject()([value])

    assert failure.value.details["reason"] == "field_set"


def test_report_commit_must_be_full_lowercase_git_identity(tmp_path):
    report = tmp_path / "report.json"
    write_report(report, commit="dadd739")

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(report)])

    assert failure.value.details["reason"] == "invalid_durable_commit"


def test_report_owned_scope_and_builder_path_must_match(tmp_path):
    report = tmp_path / "report.json"
    write_report(report)
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["builder_path"] = "lcc.parametric"
    report.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackendError) as failure:
        subject()([descriptor(report)])

    assert failure.value.details["reason"] == "builder_path_mismatch"


def test_shared_run_metadata_owns_scope_commit_and_builder_path():
    from pscad_mcp.acceptance.evidence import build_run_metadata

    metadata = build_run_metadata(
        run_id="run-2",
        scope="mmc.detailed_pwm_full_bridge",
        kind="licensed_simulation",
        capability_state="simulated",
        commit=COMMIT,
        generated_at_utc="2026-08-30T00:00:00Z",
    )

    assert metadata == {
        "schema_version": 1,
        "run_id": "run-2",
        "scope": "mmc.detailed_pwm_full_bridge",
        "builder_path": "mmc.detailed_pwm_full_bridge",
        "kind": "licensed_simulation",
        "capability_state": "simulated",
        "commit": COMMIT,
        "generated_at_utc": "2026-08-30T00:00:00Z",
    }
```

- [ ] **Step 2: Run and confirm RED**

Run:

```powershell
pytest -q tests/test_lcc_mmc_evidence_index.py
```

Expected: import failure for `pscad_mcp.acceptance.evidence`.

- [ ] **Step 3: Implement explicit-only indexing**

Create `pscad_mcp/acceptance/evidence.py`:

```python
"""Index only caller-declared acceptance reports as regular files."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..core.backend.base import BackendError
from .baseline import (
    CAPABILITY_STATES,
    LICENSED_STATUSES,
    PROGRAM_SCOPES,
    SCOPE_BUILDER_PATHS,
)


_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _error(reason: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        "PROGRAM_EVIDENCE_INVALID",
        message,
        "acceptance",
        "index_program_evidence",
        {"reason": reason, **details},
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _owned_text(payload: Mapping[str, Any], field: str, path: Path) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _error(
            "missing_report_metadata",
            f"Evidence report must own non-empty {field}.",
            field=field,
            path=str(path),
        )
    return value.strip()


def build_run_metadata(
    *,
    run_id: str,
    scope: str,
    kind: str,
    capability_state: str,
    commit: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    if scope not in PROGRAM_SCOPES:
        raise _error("unknown_scope", "Run metadata scope is unknown.", scope=scope)
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (run_id, kind, capability_state, generated_at_utc)
    ):
        raise _error("missing_report_metadata", "Run metadata text is required.")
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise _error("invalid_durable_commit", "Run metadata requires a full commit.")
    if capability_state not in CAPABILITY_STATES:
        raise _error("unknown_state", "Run metadata capability state is invalid.")
    required_kind = {
        "compiled": "licensed_compile",
        "simulated": "licensed_simulation",
        "accepted": "licensed_acceptance",
    }.get(capability_state)
    if required_kind is not None and kind.strip() != required_kind:
        raise _error("kind_state_mismatch", "Run metadata kind and state differ.")
    return {
        "schema_version": 1,
        "run_id": run_id.strip(),
        "scope": scope,
        "builder_path": SCOPE_BUILDER_PATHS[scope],
        "kind": kind.strip(),
        "capability_state": capability_state,
        "commit": commit,
        "generated_at_utc": generated_at_utc.strip(),
    }


def index_explicit_reports(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise _error("not_array", "Evidence descriptors must be an array.")
    result = []
    run_ids = set()
    for index, descriptor in enumerate(values):
        if not isinstance(descriptor, Mapping):
            raise _error("not_object", "Evidence descriptor must be an object.", index=index)
        expected = {"path"}
        if set(descriptor) != expected:
            raise _error("field_set", "Evidence descriptor fields are invalid.", index=index)
        path = Path(str(descriptor["path"])).expanduser()
        if path.is_symlink() or not path.is_file():
            raise _error("not_regular_file", "Evidence path must be a regular file.", path=str(path))
        resolved = path.resolve()
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _error("invalid_json", "Evidence report must be UTF-8 JSON.", path=str(resolved)) from error
        if not isinstance(payload, Mapping):
            raise _error("not_object", "Evidence report root must be an object.", path=str(resolved))
        if payload.get("schema_version") != 1 or isinstance(
            payload.get("schema_version"), bool
        ):
            raise _error(
                "unsupported_schema",
                "Evidence report schema_version must be 1.",
                path=str(resolved),
            )
        run_id = _owned_text(payload, "run_id", resolved)
        if run_id in run_ids:
            raise _error("duplicate_run_id", "run_id must be unique.", run_id=run_id)
        run_ids.add(run_id)
        scope = _owned_text(payload, "scope", resolved)
        if scope not in PROGRAM_SCOPES:
            raise _error("unknown_scope", "Evidence scope is unknown.", scope=scope)
        builder_path = _owned_text(payload, "builder_path", resolved)
        if builder_path != SCOPE_BUILDER_PATHS[scope]:
            raise _error(
                "builder_path_mismatch",
                "Evidence builder_path does not own its scope.",
                scope=scope,
                builder_path=builder_path,
            )
        kind = _owned_text(payload, "kind", resolved)
        capability_state = _owned_text(payload, "capability_state", resolved)
        if capability_state not in CAPABILITY_STATES:
            raise _error(
                "unknown_state",
                "Evidence report capability state is invalid.",
                path=str(resolved),
            )
        required_kind = {
            "compiled": "licensed_compile",
            "simulated": "licensed_simulation",
            "accepted": "licensed_acceptance",
        }.get(capability_state)
        if required_kind is not None and kind != required_kind:
            raise _error(
                "kind_state_mismatch",
                "Evidence report kind and capability state differ.",
                path=str(resolved),
            )
        generated_at_utc = _owned_text(payload, "generated_at_utc", resolved)
        status = payload.get("status")
        if status not in LICENSED_STATUSES:
            raise _error("unknown_status", "Evidence report status is invalid.", path=str(resolved))
        report_commit = payload.get("commit")
        if report_commit is None:
            raise _error(
                "missing_durable_commit",
                "Evidence without a report-owned commit is historical only.",
                path=str(resolved),
            )
        if not isinstance(report_commit, str) or _COMMIT.fullmatch(report_commit) is None:
            raise _error(
                "invalid_durable_commit",
                "Evidence report commit must be a full lowercase git identity.",
                path=str(resolved),
            )
        result.append(
            {
                "run_id": run_id,
                "scope": scope,
                "builder_path": builder_path,
                "kind": kind,
                "capability_state": capability_state,
                "status": str(status),
                "commit": report_commit,
                "generated_at_utc": generated_at_utc,
                "path": resolved.as_posix(),
                "sha256": _sha256(resolved),
                "availability": "verified_local",
            }
        )
    return result
```

Export `build_run_metadata` and `index_explicit_reports` from
`pscad_mcp/acceptance/__init__.py`. Future WP1-WP6 licensed reports must merge
the returned metadata into the report root before writing any status or
evidence fields.

- [ ] **Step 4: Run evidence tests and lint**

Run:

```powershell
pytest -q tests/test_lcc_mmc_evidence_index.py
ruff check pscad_mcp/acceptance/evidence.py tests/test_lcc_mmc_evidence_index.py
```

Expected: all pass.

- [ ] **Step 5: Commit the explicit evidence index**

```powershell
git add pscad_mcp/acceptance tests/test_lcc_mmc_evidence_index.py
git commit -m "feat: index explicit LCC MMC acceptance evidence"
```

### Task 4: Static Environment Preflight

**Files:**
- Create: `pscad_mcp/acceptance/preflight.py`
- Modify: `pscad_mcp/acceptance/__init__.py`
- Test: `tests/test_lcc_mmc_preflight.py`

- [ ] **Step 1: Write failing static preflight tests**

Create `tests/test_lcc_mmc_preflight.py`:

```python
from __future__ import annotations

from pathlib import Path

from pscad_mcp.acceptance.preflight import PreflightRequest, run_static_preflight


def request(tmp_path: Path) -> PreflightRequest:
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    install = tmp_path / "PSCAD46"
    repo.mkdir()
    workspace.mkdir()
    install.mkdir()
    master = install / "master.pslx"
    master.write_text("<pslx />", encoding="utf-8")
    compiler = install / "fortran_compilers.xml"
    compiler.write_text(
        "<compilers><compiler name='MHRC' version='4.6.2' "
        "exe_name='gfortran.exe' emtdc='gf46' compiler_type='x86'/></compilers>",
        encoding="utf-8",
    )
    compiler_executable = install / "gfortran.exe"
    compiler_executable.write_bytes(b"fake-gfortran")
    return PreflightRequest(
        repository_root=repo,
        workspace_root=workspace,
        master_path=master,
        compiler_configuration=compiler,
        compiler_executable=compiler_executable,
        expected_commit="dadd739e2abc14dcc7de73149da7fd7f0c0ca763",
        expected_branch="main",
    )


def test_static_preflight_reports_all_required_checks(tmp_path):
    value = request(tmp_path)

    report = run_static_preflight(
        value,
        git_reader=lambda root: {
            "commit": value.expected_commit,
            "branch": "main",
            "clean": True,
        },
        module_finder=lambda name: name == "mhrc.automation",
        process_reader=lambda: [],
        output_discovery_probe=lambda workspace: True,
    )

    assert report["status"] == "PASS"
    assert report["checks"] == {
        "repository": "PASS",
        "workspace": "PASS",
        "master": "PASS",
        "compiler": "PASS",
        "automation": "PASS",
        "processes": "PASS",
        "legacy_numbered_output_discovery": "PASS",
    }
    assert len(report["master_sha256"]) == 64
    assert len(report["compiler_configuration_sha256"]) == 64
    assert len(report["compiler_executable_sha256"]) == 64


def test_source_inside_workspace_and_external_pscad_are_failures(tmp_path):
    value = request(tmp_path)
    source_inside = value.workspace_root / "master.pslx"
    source_inside.write_text("<pslx />", encoding="utf-8")
    value = PreflightRequest(
        repository_root=value.repository_root,
        workspace_root=value.workspace_root,
        master_path=source_inside,
        compiler_configuration=value.compiler_configuration,
        compiler_executable=value.compiler_executable,
        expected_commit=value.expected_commit,
        expected_branch=value.expected_branch,
    )

    report = run_static_preflight(
        value,
        git_reader=lambda root: {
            "commit": value.expected_commit,
            "branch": "main",
            "clean": True,
        },
        module_finder=lambda name: True,
        process_reader=lambda: [{"pid": 12, "name": "PSCAD.exe"}],
        output_discovery_probe=lambda workspace: True,
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["workspace"] == "FAIL"
    assert report["checks"]["processes"] == "FAIL"


def test_dirty_or_wrong_commit_repository_fails(tmp_path):
    value = request(tmp_path)

    report = run_static_preflight(
        value,
        git_reader=lambda root: {
            "commit": "f" * 40,
            "branch": "feature",
            "clean": False,
        },
        module_finder=lambda name: True,
        process_reader=lambda: [],
        output_discovery_probe=lambda workspace: True,
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["repository"] == "FAIL"


def test_legacy_numbered_output_discovery_failure_is_explicit(tmp_path):
    value = request(tmp_path)

    report = run_static_preflight(
        value,
        git_reader=lambda root: {
            "commit": value.expected_commit,
            "branch": value.expected_branch,
            "clean": True,
        },
        module_finder=lambda name: True,
        process_reader=lambda: [],
        output_discovery_probe=lambda workspace: False,
    )

    assert report["status"] == "FAIL"
    assert report["checks"]["legacy_numbered_output_discovery"] == "FAIL"
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
pytest -q tests/test_lcc_mmc_preflight.py
```

Expected: import failure because preflight module is absent.

- [ ] **Step 3: Implement static preflight with injected readers**

Create `pscad_mcp/acceptance/preflight.py`:

```python
"""Read-only static and licensed session checks for LCC/MMC work packages."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.path_policy import PathPolicy
from ..core.process_inventory import list_pscad_processes
from ..core.service import PscadService


@dataclass(frozen=True)
class PreflightRequest:
    repository_root: Path
    workspace_root: Path
    master_path: Path
    compiler_configuration: Path
    compiler_executable: Path
    expected_commit: str
    expected_branch: str
    backend: str = "legacy"
    pscad_version: str = "4.6.2"
    x64: bool = True
    automation_module: str = "mhrc.automation"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_reader(root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "branch": branch, "clean": not status.strip()}


def _module_finder(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _process_reader() -> list[dict[str, Any]]:
    return list_pscad_processes()


def _workspace_write_probe(workspace: Path) -> bool:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".pscad-mcp-preflight-",
            suffix=".tmp",
            dir=workspace,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(b"preflight\n")
        return temporary.is_file()
    except OSError:
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _compiler_identities(path: Path) -> list[dict[str, str]]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return []
    return [
        {
            "name": item.get("name", ""),
            "version": item.get("version", ""),
            "exe_name": item.get("exe_name", ""),
            "emtdc": item.get("emtdc", ""),
            "compiler_type": item.get("compiler_type", ""),
        }
        for item in root.findall("compiler")
    ]


def _legacy_numbered_output_probe(workspace: Path) -> bool:
    with tempfile.TemporaryDirectory(
        prefix=".pscad-mcp-output-probe-", dir=workspace
    ) as raw_probe:
        probe = Path(raw_probe)
        project = probe / "PREFLIGHT_CASE.pscx"
        project.write_text("<project />", encoding="ascii")
        generated = probe / "PREFLIGHT_CASE.gf42"
        generated.mkdir()
        output = generated / "PREFLIGHT_CASE_01.out"
        output.write_bytes(b"preflight")
        started_after = time.time() - 1.0
        service = PscadService(
            lambda: object(),
            path_policy=PathPolicy(workspace_root=str(workspace)),
        )
        discovered = asyncio.run(
            service.discover_output_files(
                str(project), started_after=started_after, max_files=10
            )
        )
        return discovered == [str(output.resolve())]


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def run_static_preflight(
    request: PreflightRequest,
    *,
    git_reader: Callable[[Path], Mapping[str, Any]] = _git_reader,
    module_finder: Callable[[str], bool] = _module_finder,
    process_reader: Callable[[], Sequence[Mapping[str, Any]]] = _process_reader,
    workspace_write_probe: Callable[[Path], bool] = _workspace_write_probe,
    output_discovery_probe: Callable[[Path], bool] = _legacy_numbered_output_probe,
) -> dict[str, Any]:
    repo = request.repository_root.resolve()
    workspace = request.workspace_root.resolve()
    master = request.master_path.resolve()
    compiler = request.compiler_configuration.resolve()
    compiler_executable = request.compiler_executable.resolve()
    git = dict(git_reader(repo))
    processes = [dict(item) for item in process_reader()]
    compiler_identities = _compiler_identities(compiler) if compiler.is_file() else []
    repository_ok = (
        git.get("commit") == request.expected_commit
        and git.get("branch") == request.expected_branch
        and git.get("clean") is True
    )
    workspace_ok = (
        workspace.is_dir()
        and workspace_write_probe(workspace)
        and not _inside(repo, workspace)
        and not _inside(workspace, repo)
        and not _inside(master, workspace)
        and not _inside(compiler, workspace)
        and not _inside(compiler_executable, workspace)
    )
    master_ok = master.is_file() and not master.is_symlink()
    compiler_ok = (
        compiler.is_file()
        and not compiler.is_symlink()
        and compiler_executable.is_file()
        and not compiler_executable.is_symlink()
        and any(
            item["exe_name"].casefold() == compiler_executable.name.casefold()
            for item in compiler_identities
        )
    )
    automation_ok = module_finder(request.automation_module)
    processes_ok = not processes
    output_discovery_ok = workspace_ok and output_discovery_probe(workspace)
    checks = {
        "repository": "PASS" if repository_ok else "FAIL",
        "workspace": "PASS" if workspace_ok else "FAIL",
        "master": "PASS" if master_ok else "FAIL",
        "compiler": "PASS" if compiler_ok else "FAIL",
        "automation": "PASS" if automation_ok else "FAIL",
        "processes": "PASS" if processes_ok else "FAIL",
        "legacy_numbered_output_discovery": "PASS" if output_discovery_ok else "FAIL",
    }
    return {
        "schema_version": 1,
        "status": "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL",
        "checks": checks,
        "repository": git,
        "workspace_root": str(workspace),
        "master_path": str(master),
        "master_sha256": _sha256(master) if master_ok else None,
        "compiler_configuration": str(compiler),
        "compiler_configuration_sha256": _sha256(compiler) if compiler_ok else None,
        "compiler_executable": str(compiler_executable),
        "compiler_executable_sha256": (
            _sha256(compiler_executable) if compiler_ok else None
        ),
        "compiler_identities": compiler_identities,
        "automation_module": request.automation_module,
        "external_pscad_processes": processes,
        "backend": request.backend,
        "pscad_version": request.pscad_version,
        "x64": request.x64,
    }
```

Export `PreflightRequest` and `run_static_preflight` from `__init__.py`.

- [ ] **Step 4: Run static preflight tests and lint**

Run:

```powershell
pytest -q tests/test_lcc_mmc_preflight.py
ruff check pscad_mcp/acceptance/preflight.py tests/test_lcc_mmc_preflight.py
```

Expected: all pass.

- [ ] **Step 5: Commit static preflight**

```powershell
git add pscad_mcp/acceptance tests/test_lcc_mmc_preflight.py
git commit -m "feat: add static LCC MMC environment preflight"
```

### Task 5: Licensed PSCAD Session Preflight

**Files:**
- Modify: `pscad_mcp/acceptance/preflight.py`
- Create: `pscad_mcp/acceptance/preflight_cli.py`
- Create: `scripts/run_lcc_mmc_program_preflight.ps1`
- Create: `tests/test_lcc_mmc_preflight_real.py`
- Modify: `tests/test_lcc_mmc_preflight.py`
- Create: `tests/test_lcc_mmc_preflight_cli.py`

- [ ] **Step 1: Add failing session probe unit tests**

Append to `tests/test_lcc_mmc_preflight.py`:

```python
import asyncio
import hashlib


class SessionService:
    def __init__(self, *, alive: bool = True) -> None:
        self.alive = alive
        self.calls = []

    async def attach_local(self):
        self.calls.append("attach_local")
        return "attached"

    async def status(self):
        self.calls.append("status")
        return {
            "connected": self.alive,
            "licensed": True,
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "alive": self.alive,
            "busy": False,
            "owns_process": True,
        }

    async def quit_pscad(self, *, confirm=False):
        self.calls.append(("quit_pscad", confirm))
        return "quit"


def test_licensed_session_probe_attaches_reads_and_quits_without_project_creation(tmp_path):
    from pscad_mcp.acceptance.preflight import run_licensed_session_preflight

    service = SessionService()
    result = asyncio.run(
        run_licensed_session_preflight(
            service,
            workspace_root=tmp_path,
            process_reader=lambda: [],
        )
    )

    assert result["status"] == "PASS"
    assert service.calls == ["attach_local", "status", ("quit_pscad", True)]
    assert "create_project" not in service.calls
    assert result["projects_before"] == result["projects_after"] == {}


def test_licensed_session_probe_reports_runtime_and_cleanup_failure(tmp_path):
    from pscad_mcp.acceptance.preflight import run_licensed_session_preflight

    service = SessionService(alive=False)
    process_snapshots = iter(
        [[], [{"pid": 99, "name": "PSCAD.exe", "exe": "C:/PSCAD.exe"}]]
    )
    result = asyncio.run(
        run_licensed_session_preflight(
            service,
            workspace_root=tmp_path,
            process_reader=lambda: next(process_snapshots),
        )
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["runtime"] == "FAIL"
    assert result["checks"]["cleanup"] == "FAIL"


def test_preexisting_pscad_process_prevents_attach(tmp_path):
    from pscad_mcp.acceptance.preflight import run_licensed_session_preflight

    service = SessionService()
    result = asyncio.run(
        run_licensed_session_preflight(
            service,
            workspace_root=tmp_path,
            process_reader=lambda: [
                {"pid": 12, "name": "PSCAD.exe", "exe": "C:/PSCAD.exe"}
            ],
        )
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["process_conflict"] == "FAIL"
    assert service.calls == []


def test_program_preflight_combines_commit_session_and_source_immutability(tmp_path):
    from pscad_mcp.acceptance.preflight import run_program_preflight

    value = request(tmp_path)
    master_hash = hashlib.sha256(value.master_path.read_bytes()).hexdigest()
    compiler_hash = hashlib.sha256(
        value.compiler_configuration.read_bytes()
    ).hexdigest()
    compiler_executable_hash = hashlib.sha256(
        value.compiler_executable.read_bytes()
    ).hexdigest()

    def static_runner(candidate):
        assert candidate == value
        return {
            "status": "PASS",
            "master_sha256": master_hash,
            "compiler_configuration_sha256": compiler_hash,
            "compiler_executable_sha256": compiler_executable_hash,
        }

    async def session_runner(service, *, workspace_root):
        assert workspace_root == value.workspace_root
        return {"status": "PASS"}

    result = asyncio.run(
        run_program_preflight(
            value,
            object(),
            static_runner=static_runner,
            session_runner=session_runner,
        )
    )

    assert result["status"] == "PASS"
    assert result["commit"] == value.expected_commit
    assert result["source_immutability_status"] == "PASS"
```

- [ ] **Step 2: Run session tests and verify RED**

Run:

```powershell
pytest -q tests/test_lcc_mmc_preflight.py -k licensed_session
```

Expected: failures because `run_licensed_session_preflight` is absent.

- [ ] **Step 3: Implement the session probe and atomic report writer**

Add to `preflight.py`:

```python
from datetime import datetime, timezone
import json
import os


def _project_inventory(workspace: Path) -> dict[str, str]:
    result = {}
    for path in sorted(workspace.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.casefold() not in {".pscx", ".pslx", ".pswx"}:
            continue
        result[path.relative_to(workspace).as_posix()] = _sha256(path)
    return result


async def run_licensed_session_preflight(
    service: Any,
    *,
    workspace_root: Path,
    process_reader: Callable[[], Sequence[Mapping[str, Any]]] = _process_reader,
) -> dict[str, Any]:
    workspace = workspace_root.resolve()
    existing = [dict(item) for item in process_reader()]
    projects_before = _project_inventory(workspace)
    if existing:
        return {
            "schema_version": 1,
            "status": "FAIL",
            "checks": {
                "process_conflict": "FAIL",
                "runtime": "FAIL",
                "cleanup": "FAIL",
                "no_project_mutation": "PASS",
            },
            "runtime": {},
            "attach_error": None,
            "quit_error": None,
            "processes_before": existing,
            "remaining_processes": existing,
            "projects_before": projects_before,
            "projects_after": projects_before,
        }
    attach_error = None
    runtime: Mapping[str, Any] = {}
    quit_error = None
    attached = False
    try:
        await service.attach_local()
        attached = True
        value = await service.status()
        runtime = value if isinstance(value, Mapping) else {}
    except Exception as error:  # noqa: BLE001 - report vendor attach/read failure
        attach_error = {"type": type(error).__name__, "message": str(error)}
    finally:
        if attached:
            try:
                await service.quit_pscad(confirm=True)
            except Exception as error:  # noqa: BLE001 - report vendor cleanup failure
                quit_error = {"type": type(error).__name__, "message": str(error)}
    remaining = [dict(item) for item in process_reader()]
    projects_after = _project_inventory(workspace)
    runtime_ok = (
        attach_error is None
        and runtime.get("connected") is True
        and runtime.get("alive") is True
        and runtime.get("licensed") is True
        and runtime.get("backend") == "legacy"
        and runtime.get("version") == "4.6.2"
        and runtime.get("x64") is True
    )
    cleanup_ok = quit_error is None and not remaining
    projects_ok = projects_before == projects_after
    checks = {
        "process_conflict": "PASS",
        "runtime": "PASS" if runtime_ok else "FAIL",
        "cleanup": "PASS" if cleanup_ok else "FAIL",
        "no_project_mutation": "PASS" if projects_ok else "FAIL",
    }
    return {
        "schema_version": 1,
        "status": "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL",
        "checks": checks,
        "runtime": dict(runtime),
        "attach_error": attach_error,
        "quit_error": quit_error,
        "processes_before": existing,
        "remaining_processes": remaining,
        "projects_before": projects_before,
        "projects_after": projects_after,
    }


async def run_program_preflight(
    request: PreflightRequest,
    service: Any,
    *,
    static_runner: Callable[[PreflightRequest], dict[str, Any]] = run_static_preflight,
    session_runner: Callable[..., Any] = run_licensed_session_preflight,
) -> dict[str, Any]:
    static = static_runner(request)
    if static["status"] == "PASS":
        licensed = await session_runner(
            service,
            workspace_root=request.workspace_root,
        )
    else:
        licensed = {
            "schema_version": 1,
            "status": "NOT_RUN",
            "reason": "static_preflight_failed",
        }
    master_after = _sha256(request.master_path) if request.master_path.is_file() else None
    compiler_after = (
        _sha256(request.compiler_configuration)
        if request.compiler_configuration.is_file()
        else None
    )
    compiler_executable_after = (
        _sha256(request.compiler_executable)
        if request.compiler_executable.is_file()
        else None
    )
    source_immutability = {
        "master_before": static.get("master_sha256"),
        "master_after": master_after,
        "compiler_before": static.get("compiler_configuration_sha256"),
        "compiler_after": compiler_after,
        "compiler_executable_before": static.get("compiler_executable_sha256"),
        "compiler_executable_after": compiler_executable_after,
    }
    immutable = (
        source_immutability["master_before"] == source_immutability["master_after"]
        and source_immutability["compiler_before"]
        == source_immutability["compiler_after"]
        and source_immutability["compiler_executable_before"]
        == source_immutability["compiler_executable_after"]
    )
    return {
        "schema_version": 1,
        "kind": "lcc_mmc_program_preflight",
        "commit": request.expected_commit,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": (
            "PASS"
            if static["status"] == licensed["status"] == "PASS" and immutable
            else "FAIL"
        ),
        "static": static,
        "licensed_session": licensed,
        "source_immutability": source_immutability,
        "source_immutability_status": "PASS" if immutable else "FAIL",
    }


def write_preflight_report(path: Path, payload: Mapping[str, Any]) -> Path:
    encoded = json.dumps(
        dict(payload), allow_nan=False, ensure_ascii=True, sort_keys=True, indent=2
    ).encode("ascii") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
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
```

Export `run_licensed_session_preflight`, `run_program_preflight`, and
`write_preflight_report` from `pscad_mcp/acceptance/__init__.py`.

- [ ] **Step 4: Add and unit-test the report-producing CLI**

Create `pscad_mcp/acceptance/preflight_cli.py`:

```python
"""Command-line entry point for a durable LCC/MMC program preflight report."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from ..core.backend.legacy import LegacyBackend
from ..core.executor import robust_executor
from ..core.path_policy import PathPolicy
from ..core.process_inventory import list_pscad_processes
from ..core.service import PscadService
from .preflight import PreflightRequest, run_program_preflight, write_preflight_report


def _service(workspace: Path) -> PscadService:
    backend = LegacyBackend(
        robust_executor,
        version="4.6.2",
        x64=True,
        process_probe=list_pscad_processes,
    )
    return PscadService(
        lambda: backend,
        executor=robust_executor,
        path_policy=PathPolicy(workspace_root=str(workspace)),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--master-path", type=Path, required=True)
    parser.add_argument("--compiler-configuration", type=Path, required=True)
    parser.add_argument("--compiler-executable", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-branch", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[[PreflightRequest, Any], Awaitable[dict[str, Any]]] = run_program_preflight,
    service_factory: Callable[[Path], Any] = _service,
) -> int:
    args = _parser().parse_args(argv)
    workspace = args.workspace_root.resolve()
    output = args.output.resolve()
    try:
        output.relative_to(workspace)
    except ValueError as error:
        raise SystemExit("--output must be contained by --workspace-root") from error
    request = PreflightRequest(
        repository_root=args.repository_root,
        workspace_root=workspace,
        master_path=args.master_path,
        compiler_configuration=args.compiler_configuration,
        compiler_executable=args.compiler_executable,
        expected_commit=args.expected_commit,
        expected_branch=args.expected_branch,
    )
    payload = asyncio.run(runner(request, service_factory(workspace)))
    write_preflight_report(output, payload)
    print(f"PROGRAM_PREFLIGHT={payload['status']}")
    print(f"PROGRAM_PREFLIGHT_REPORT={output}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `tests/test_lcc_mmc_preflight_cli.py`:

```python
from __future__ import annotations

import json

from pscad_mcp.acceptance.preflight_cli import main


def test_cli_writes_commit_owned_report_and_returns_status(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = workspace / "run-1" / "program-preflight-report.json"
    commit = "dadd739e2abc14dcc7de73149da7fd7f0c0ca763"

    async def runner(request, service):
        assert request.expected_commit == commit
        return {
            "schema_version": 1,
            "kind": "lcc_mmc_program_preflight",
            "commit": request.expected_commit,
            "status": "PASS",
        }

    result = main(
        [
            "--repository-root", str(tmp_path),
            "--workspace-root", str(workspace),
            "--master-path", str(tmp_path / "master.pslx"),
            "--compiler-configuration", str(tmp_path / "fortran_compilers.xml"),
            "--compiler-executable", str(tmp_path / "gfortran.exe"),
            "--expected-commit", commit,
            "--expected-branch", "codex/lcc-mmc-wp0-baseline",
            "--output", str(output),
        ],
        runner=runner,
        service_factory=lambda root: object(),
    )

    assert result == 0
    assert json.loads(output.read_text(encoding="ascii"))["commit"] == commit
```

Run:

```powershell
pytest -q tests/test_lcc_mmc_preflight_cli.py
```

Expected: pass, and the test-created report is inside the requested workspace.

- [ ] **Step 5: Add the opt-in real session test**

Create `tests/test_lcc_mmc_preflight_real.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
import unittest

from pscad_mcp.acceptance.preflight import run_licensed_session_preflight
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.core.service import PscadService


@unittest.skipUnless(
    os.getenv("PSCAD_MCP_PROGRAM_PREFLIGHT") == "1",
    "Set PSCAD_MCP_PROGRAM_PREFLIGHT=1 for licensed PSCAD preflight.",
)
class TestLccMmcProgramPreflightReal(unittest.IsolatedAsyncioTestCase):
    async def test_attach_license_runtime_and_cleanup(self):
        workspace = os.environ["PSCAD_MCP_WORKSPACE"]
        backend = LegacyBackend(
            robust_executor,
            version="4.6.2",
            x64=True,
            process_probe=list_pscad_processes,
        )
        service = PscadService(
            lambda: backend,
            path_policy=PathPolicy(workspace_root=workspace),
        )

        result = await run_licensed_session_preflight(
            service,
            workspace_root=Path(workspace),
        )

        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["remaining_processes"], [])
```

- [ ] **Step 6: Add the PowerShell runner**

Append this contract test to `tests/test_lcc_mmc_preflight_cli.py`:

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_powershell_runner_uses_report_cli_and_checks_cleanup():
    script = (
        ROOT / "scripts" / "run_lcc_mmc_program_preflight.ps1"
    ).read_text(encoding="utf-8")

    assert "-m pscad_mcp.acceptance.preflight_cli" in script
    assert "--expected-commit $commit" in script
    assert "program-preflight-report.json" in script
    assert "ConvertFrom-Json" in script
    assert "PROGRAM_PREFLIGHT_SHA256=" in script
    assert "Get-Process" in script
    assert "'.pscx', '.pslx', '.pswx'" in script
```

Run `pytest -q tests/test_lcc_mmc_preflight_cli.py` and verify RED because the
runner does not exist. Then create the runner below.

Create `scripts/run_lcc_mmc_program_preflight.ps1` with this behavior:

```powershell
[CmdletBinding()]
param(
    [string]$Workspace = 'D:\PSCAD-Workspace\lcc-mmc-program-preflight',
    [string]$MasterLibrary = 'C:\Program Files (x86)\PSCAD46\master.pslx',
    [string]$CompilerConfiguration = 'C:\Program Files (x86)\PSCAD46\fortran_compilers.xml',
    [string]$CompilerExecutable = 'C:\Program Files (x86)\GFortran\4.6\bin\gfortran.exe'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual-environment Python was not found: $python"
}
if (-not (Test-Path -LiteralPath $MasterLibrary -PathType Leaf)) {
    throw "Master Library was not found: $MasterLibrary"
}
if (-not (Test-Path -LiteralPath $CompilerConfiguration -PathType Leaf)) {
    throw "Compiler configuration was not found: $CompilerConfiguration"
}
if (-not (Test-Path -LiteralPath $CompilerExecutable -PathType Leaf)) {
    throw "Compiler executable was not found: $CompilerExecutable"
}
$commit = (& git -C $repoRoot rev-parse HEAD).Trim()
$branch = (& git -C $repoRoot branch --show-current).Trim()
if (-not $branch) {
    throw 'Program preflight requires a named branch.'
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($dirty.Count -ne 0) {
    throw 'Commit or remove repository changes before licensed preflight.'
}
$processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object ProcessName -Like 'PSCAD*')
if ($processes.Count -gt 0) {
    throw "Close existing PSCAD processes before preflight."
}
$null = New-Item -ItemType Directory -Path $Workspace -Force
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runRoot = Join-Path $Workspace "preflight-$stamp"
New-Item -ItemType Directory -Path $runRoot -Force:$false | Out-Null
$report = Join-Path $runRoot 'program-preflight-report.json'

$hadProgramPreflight = Test-Path Env:PSCAD_MCP_PROGRAM_PREFLIGHT
$previousProgramPreflight = $env:PSCAD_MCP_PROGRAM_PREFLIGHT
$hadWorkspace = Test-Path Env:PSCAD_MCP_WORKSPACE
$previousWorkspace = $env:PSCAD_MCP_WORKSPACE
$env:PSCAD_MCP_PROGRAM_PREFLIGHT = '1'
$env:PSCAD_MCP_WORKSPACE = $Workspace
try {
    Push-Location $repoRoot
    try {
        & $python -m pscad_mcp.acceptance.preflight_cli `
          --repository-root $repoRoot `
          --workspace-root $Workspace `
          --master-path $MasterLibrary `
          --compiler-configuration $CompilerConfiguration `
          --compiler-executable $CompilerExecutable `
          --expected-commit $commit `
          --expected-branch $branch `
          --output $report
        $preflightExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    if ($hadProgramPreflight) {
        $env:PSCAD_MCP_PROGRAM_PREFLIGHT = $previousProgramPreflight
    } else {
        Remove-Item Env:PSCAD_MCP_PROGRAM_PREFLIGHT -ErrorAction SilentlyContinue
    }
    if ($hadWorkspace) {
        $env:PSCAD_MCP_WORKSPACE = $previousWorkspace
    } else {
        Remove-Item Env:PSCAD_MCP_WORKSPACE -ErrorAction SilentlyContinue
    }
}
if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
    throw "Licensed preflight did not write its report: $report"
}
$payload = Get-Content -Raw -LiteralPath $report | ConvertFrom-Json
if ($preflightExitCode -ne 0 -or $payload.status -ne 'PASS') {
    throw "Licensed program preflight failed; inspect $report"
}

$remaining = @(Get-Process -ErrorAction SilentlyContinue | Where-Object ProcessName -Like 'PSCAD*')
if ($remaining.Count -ne 0) {
    throw "Licensed program preflight left PSCAD processes running."
}
$projectFiles = @(
    Get-ChildItem -LiteralPath $runRoot -Recurse -File |
      Where-Object { $_.Extension -in '.pscx', '.pslx', '.pswx' }
)
if ($projectFiles.Count -ne 0) {
    throw "Licensed program preflight created a PSCAD project under $runRoot"
}
$reportHash = (Get-FileHash -LiteralPath $report -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "PROGRAM_PREFLIGHT=PASS"
Write-Output "PROGRAM_PREFLIGHT_DIRECTORY=$runRoot"
Write-Output "PROGRAM_PREFLIGHT_REPORT=$report"
Write-Output "PROGRAM_PREFLIGHT_SHA256=$reportHash"
Write-Output "PROGRAM_PREFLIGHT_COMMIT=$commit"
```

Run `pytest -q tests/test_lcc_mmc_preflight_cli.py` again and verify GREEN.

- [ ] **Step 7: Run offline unit tests**

Run offline:

```powershell
pytest -q tests/test_lcc_mmc_preflight.py tests/test_lcc_mmc_preflight_cli.py tests/test_lcc_mmc_preflight_real.py
```

Expected: unit tests pass; real test skips without the environment flag.

- [ ] **Step 8: Commit the licensed preflight implementation**

```powershell
git add pscad_mcp/acceptance/preflight.py pscad_mcp/acceptance/preflight_cli.py scripts/run_lcc_mmc_program_preflight.ps1 tests/test_lcc_mmc_preflight.py tests/test_lcc_mmc_preflight_cli.py tests/test_lcc_mmc_preflight_real.py
git commit -m "test: add licensed LCC MMC program preflight"
```

- [ ] **Step 9: Run licensed preflight on the clean implementation commit**

```powershell
& .\scripts\run_lcc_mmc_program_preflight.ps1 `
  -Workspace 'D:\PSCAD-Workspace\lcc-mmc-program-preflight'
```

Expected:

```text
PROGRAM_PREFLIGHT=PASS
PROGRAM_PREFLIGHT_DIRECTORY=D:\PSCAD-Workspace\lcc-mmc-program-preflight\preflight-<run-id>
PROGRAM_PREFLIGHT_REPORT=D:\PSCAD-Workspace\lcc-mmc-program-preflight\preflight-<run-id>\program-preflight-report.json
PROGRAM_PREFLIGHT_SHA256=<64 lowercase hex characters>
PROGRAM_PREFLIGHT_COMMIT=<40 lowercase hex characters>
```

The report JSON has `status=PASS` and its `commit` equals
`PROGRAM_PREFLIGHT_COMMIT`. No PSCAD process remains, and the run directory
contains no `.pscx`, `.pslx`, or `.pswx` file.

### Task 6: Seed the Current Program Baseline

**Files:**
- Create: `docs/acceptance/lcc-mmc-program-baseline.json`
- Modify: `tests/test_lcc_mmc_program_baseline.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`

- [ ] **Step 1: Add the failing checked-in baseline test**

Append:

```python
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
PROGRAM_BASELINE = ROOT / "docs" / "acceptance" / "lcc-mmc-program-baseline.json"


def test_checked_in_program_baseline_is_valid_and_scoped():
    payload = json.loads(PROGRAM_BASELINE.read_text(encoding="utf-8"))

    result = subject()(payload)
    scopes = {item["scope"]: item for item in result["scopes"]}

    assert set(scopes) == {
        "lcc.master_bindings",
        "lcc.blank_native",
        "lcc.fixed_autonomous",
        "lcc.parametric",
        "mmc.blank_native_full_bridge",
        "mmc.detailed_pwm_full_bridge",
        "mmc.avm_full_bridge",
        "mmc.avm_half_bridge",
        "mmc.parametric",
    }
    assert scopes["lcc.master_bindings"]["licensed_status"] == "NOT_RUN_ON_CURRENT_COMMIT"
    assert scopes["lcc.blank_native"]["licensed_status"] == "NOT_RUN_ON_CURRENT_COMMIT"
    assert scopes["mmc.blank_native_full_bridge"]["licensed_status"] == "NOT_RUN_ON_CURRENT_COMMIT"
    assert scopes["mmc.parametric"]["licensed_status"] == "INCOMPLETE_ANALYSIS"


def test_program_baseline_does_not_replace_topology_status_manifest():
    topology = json.loads((ROOT / "docs" / "acceptance-status.json").read_text(encoding="utf-8"))
    program = json.loads(PROGRAM_BASELINE.read_text(encoding="utf-8"))

    assert {item["scope"] for item in topology["scopes"]}.isdisjoint(
        {item["scope"] for item in program["scopes"]}
    )
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
pytest -q tests/test_lcc_mmc_program_baseline.py -k checked_in
```

Expected: failure because the checked-in baseline file is absent.

- [ ] **Step 3: Create the baseline with exact current evidence**

Create `docs/acceptance/lcc-mmc-program-baseline.json`. Generate hashes from
the files rather than retyping them. The known evidence inventory must use
these verified identities:

| Scope | Report path | SHA-256 | Status | Commit |
| --- | --- | --- | --- | --- |
| `lcc.master_bindings` | `D:/PSCAD-Workspace/master-binding-acceptance/master-binding-acceptance-20260829-173320-618412/master-binding-acceptance-report.json` | `e541947b914ca78b919b7c4796ee2b7e589fbb9868a47261538ca86106f7b38e` | `PASS` historical only | commit unknown |
| `lcc.blank_native` | `D:/PSCAD-Workspace/blank-lcc-native-acceptance2-20260829/.pscad-mcp/lcc-builds/9b2fb1415a6b4f59a306b532c8b6f873/journal.json` | `edfb882a9f709b703e2b8625b23ef9eb94b4101e2d6466abe0afaadb9a2108f1` | `PASS` historical only | commit unknown |
| `mmc.blank_native_full_bridge` | `D:/PSCAD-Workspace/blank-mmc-native-acceptance-20260829/.pscad-mcp/mmc-builds/b260eaf5c5004b5dab39c9368ed1023c/journal.json` | `ad6ec80ac2223ba5c68740566bd60d15ae13e31b5bdce8c6f3cbe4dd76e394a9` | `INCOMPLETE_ANALYSIS` | commit unknown |
| `mmc.parametric` | `D:/PSCAD-Workspace/mmc-parametric-acceptance/mmc-parametric-acceptance-20260828T080837223737Z/mmc-parametric-acceptance-report.json` | `18975323c2b563d308a81d6e1743ef866bfb66d193be2de04cd4284917d5d4e5` | `INCOMPLETE_ANALYSIS` | `aec74dd52f8f4e6d523aba652eff3eec1456198c` |

Because the schema requires report-owned `run_id`, `scope`, `builder_path`,
`kind`, full commit, and generation time for every durable report, none of the
four files above qualifies for the initial `reports` array. Record the Master
report with `kind="master_binding_compile_run"`, the blank LCC journal with
`kind="official_lcc_template_run"`, and the blank MMC journal with
`kind="official_mmc_template_run"`; all three use
`availability="verified_local_historical_commit_unknown"`. Record the MMC
parametric report with `kind="mmc_parametric_orchestrator_run"` and
`availability="verified_local_historical_commit"`; its commit is durable but
it predates `repository.base_commit` and lacks the other report-owned routing
metadata. The initial `reports` array is therefore empty. The Master report's
external descriptor, filename, prior test invocation, and surrounding git
history are not commit attestations. Their corresponding current scopes must
remain `NOT_RUN_ON_CURRENT_COMMIT` unless a separate current-commit report is
generated later.

Read `PROGRAM_PREFLIGHT_COMMIT` from the PASS report created in Task 5. Set
`repository.base_commit` to that exact full commit, set `repository.branch` to
the report's `static.repository.branch`, and set `worktree_clean=true`. Verify
the identity before creating the JSON:

```powershell
$preflight = Get-Content -Raw -LiteralPath $env:PSCAD_MCP_PROGRAM_PREFLIGHT_REPORT | ConvertFrom-Json
git cat-file -e "$($preflight.commit)^{commit}"
if ($preflight.status -ne 'PASS' -or $preflight.static.repository.clean -ne $true) {
    throw 'The seed baseline requires a clean PASS preflight report.'
}
```

Set `PSCAD_MCP_PROGRAM_PREFLIGHT_REPORT` to the exact report path printed by
Task 5 before running this command. Do not infer the commit from the branch tip
after additional commits.

The Master hash is exactly:

```text
062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939
```

Generate the compiler configuration hash during implementation:

```powershell
(Get-FileHash -LiteralPath 'C:\Program Files (x86)\PSCAD46\fortran_compilers.xml' -Algorithm SHA256).Hash.ToLowerInvariant()
```

Expected compiler configuration SHA-256 on this machine:

```text
bd6183220badfa7a32f5419e8563d9b5c598fc370d50970d9e0bfaba092f6ca1
```

Record compiler identity `gfortran`, executable path
`C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe`, and executable SHA-256:

```text
fd179ba3ddb0df54ddc59911042947d97a20f039297279eb6cbf9554b32c8665
```

Register these official read-only sources with `kind="official_template"` and
their exact current hashes:

| Source ID | Path | SHA-256 |
| --- | --- | --- |
| `official.lcc.cigre_bidirectional.project` | `D:/pscad-mcp-example-inspection-20260829/cigre_lcc_bidirectional/Cigre_LCC_Bidirectional.pscx` | `f36738fbec4c9bdb0995ca73726e16d18e85c10166eaa893e6599a591d5c4a43` |
| `official.mmc.half_bridge.project` | `C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress/H_MMC_Mono_DC.pscx` | `1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd` |
| `official.mmc.half_bridge.library` | `C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress/intermediate.pslx` | `08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b` |

Register the Task 5 preflight report as
`kind="environment_preflight"`, with its actual path/hash and
`availability="verified_local_current_commit"`.

Register these packaged asset identities:

| Asset ID | Scope | Path | SHA-256 |
| --- | --- | --- | --- |
| `asset.lcc.fixed.manifest` | `lcc.fixed_autonomous` | `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json` | `ee62e0dcbef5a9d89e1ef23964179b0a3b78aca6f412efcc0dac6bcb914f12ad` |
| `asset.lcc.parametric.catalog` | `lcc.parametric` | `pscad_mcp/assets/lcc/lcc_parametric_catalog_v1.json` | `f9bfd55f0f89a748f298a8e13d1190a98a218976496d45ad45a190a04536e03d` |
| `asset.lcc.parametric.monopole` | `lcc.parametric` | `pscad_mcp/assets/lcc/lcc_monopole_parametric_v1/blueprint.json` | `d48b7bdd5472f81e4913e86ebcfccaaaee8bb48859586646f8f0a7e16301fdca` |
| `asset.lcc.parametric.bipole` | `lcc.parametric` | `pscad_mcp/assets/lcc/lcc_bipole_parametric_v1/blueprint.json` | `4c40c0c908a5e0ff7f3b2e5630502a3d3221a6e3c7fed0cac33783628d4f8b37` |
| `asset.mmc.fixed.manifest` | `mmc.avm_full_bridge` | `pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1/manifest.json` | `96a0a3f3f61f47ad0b11d7dc5ba14f44fdca7b0edfa5f98ef9fe9ce226fe49fd` |

Set current scope truth as follows:

Every scope record uses the exact `builder_path` from `SCOPE_BUILDER_PATHS` and
starts with `evidence_run_id=null`; historical source entries never populate
that field.

| Scope | Capability | Licensed status | Exclusions |
| --- | --- | --- | --- |
| `lcc.master_bindings` | `compiled` | `NOT_RUN_ON_CURRENT_COMMIT` | current-commit compile and full LCC waveform acceptance |
| `lcc.blank_native` | `simulated` | `NOT_RUN_ON_CURRENT_COMMIT` | autonomous fixed and current-commit acceptance |
| `lcc.fixed_autonomous` | `planned` | `INCOMPLETE_ANALYSIS` | reviewed golden and physical companion |
| `lcc.parametric` | `planned` | `NOT_RUN_ON_CURRENT_COMMIT` | licensed parameter matrix |
| `mmc.blank_native_full_bridge` | `simulated` | `NOT_RUN_ON_CURRENT_COMMIT` | current-commit negative insertion, blocking, recovery |
| `mmc.detailed_pwm_full_bridge` | `planned` | `INCOMPLETE_ANALYSIS` | strict EMTDC timed control |
| `mmc.avm_full_bridge` | `planned` | `INCOMPLETE_ANALYSIS` | physical full-bridge AVM |
| `mmc.avm_half_bridge` | `planned` | `INCOMPLETE_ANALYSIS` | physical AVM and reviewed golden |
| `mmc.parametric` | `planned` | `INCOMPLETE_ANALYSIS` | timed control and `master:dc_bus` mapping |

- [ ] **Step 4: Validate hashes and checked-in baseline**

Run:

```powershell
pytest -q tests/test_lcc_mmc_program_baseline.py
python -c "import json; from pathlib import Path; from pscad_mcp.acceptance import program_baseline_sha256, validate_program_baseline; p=Path('docs/acceptance/lcc-mmc-program-baseline.json'); v=json.loads(p.read_text(encoding='utf-8')); validate_program_baseline(v); print(program_baseline_sha256(v))"
```

Expected: tests pass and the command prints one lowercase 64-character SHA-256.

- [ ] **Step 5: Document the baseline scope**

Add to `README.md` near the acceptance sections:

```markdown
The LCC/MMC implementation program has a separate scoped current-truth baseline at
`docs/acceptance/lcc-mmc-program-baseline.json`. It does not replace the read-only
topology status manifest, and no PASS transfers between scopes or commits.
PASS also never transfers between builder paths within an orchestration family.
```

Add the equivalent Chinese statement to `docs/zh-CN/README.md`:

```markdown
LCC/MMC 实现计划使用独立的当前真值基线
`docs/acceptance/lcc-mmc-program-baseline.json`。它不替代只读拓扑验收清单，
任何 PASS 都不能跨 scope 或跨 commit 继承。
同一编排族中的不同 builder path 也不能互相继承 PASS。
```

- [ ] **Step 6: Run documentation and manifest tests**

Run:

```powershell
pytest -q tests/test_lcc_mmc_program_baseline.py tests/test_acceptance_status_manifest.py
git diff --check
```

Expected: all pass with no whitespace errors.

- [ ] **Step 7: Commit the seeded baseline**

```powershell
git add docs/acceptance/lcc-mmc-program-baseline.json README.md docs/zh-CN/README.md tests/test_lcc_mmc_program_baseline.py
git commit -m "docs: seed scoped LCC MMC program baseline"
```

### Task 7: WP0 End-to-End Verification and Handoff

**Files:**
- Modify: `docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md`
- Create: `docs/superpowers/specs/2026-08-30-lcc-mmc-wp0-baseline-design.md`

- [ ] **Step 1: Run all focused WP0 tests**

Run:

```powershell
pytest -q `
  tests/test_lcc_mmc_program_baseline.py `
  tests/test_lcc_mmc_evidence_index.py `
  tests/test_lcc_mmc_preflight.py `
  tests/test_lcc_mmc_preflight_cli.py `
  tests/test_lcc_mmc_preflight_real.py `
  tests/test_acceptance_status_manifest.py
```

Expected: all non-licensed tests pass and the real preflight test skips unless explicitly enabled.

- [ ] **Step 2: Run targeted lint**

Run:

```powershell
ruff check `
  pscad_mcp/acceptance `
  tests/test_lcc_mmc_program_baseline.py `
  tests/test_lcc_mmc_evidence_index.py `
  tests/test_lcc_mmc_preflight.py `
  tests/test_lcc_mmc_preflight_cli.py `
  tests/test_lcc_mmc_preflight_real.py
```

Expected: no lint violations.

- [ ] **Step 3: Run the full repository suite**

Run:

```powershell
pytest -q
```

Expected: all tests pass; licensed suites without explicit environment flags skip.

- [ ] **Step 4: Run licensed preflight on the clean seeded-baseline commit**

Run:

```powershell
& .\scripts\run_lcc_mmc_program_preflight.ps1 `
  -Workspace 'D:\PSCAD-Workspace\lcc-mmc-program-preflight'
```

Expected: `PROGRAM_PREFLIGHT=PASS`, no project files created by the probe, and no PSCAD process remains.

- [ ] **Step 5: Write the WP0 completion record from actual evidence**

Create the WP0 child design/completion document with these exact sections:

```markdown
# LCC/MMC WP0 Baseline Design and Completion Record

**Scope:** WP0 only

## Inputs

## Schema

## Evidence Index Rules

## Static Preflight

## Licensed Session Preflight

## Current Baseline Identity

## Verification Evidence

## Explicit Exclusions

## WP1 Unlock Decision
```

Fill every section from the Step 1-4 command output and the exact final
preflight report. Do not include empty headings, unspecified placeholder text,
or a PASS claim without the report's absolute path, SHA-256, full commit,
Master hash, and compiler-configuration hash. Update the parent roadmap's
status and WP0 unlock line only to match this evidence; do not change WP1-WP6
requirements.

- [ ] **Step 6: Request code review**

Review `main..HEAD` against:

- `docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md`
- this implementation plan;
- the generated WP0 completion record.

Critical review questions:

1. Can a historical or cross-scope report create current PASS?
2. Can a descriptor supply a missing report commit?
3. Can symlinked or undeclared evidence enter the index?
4. Can preflight mutate a PSCAD project or source?
5. Is process cleanup proven after vendor failure?
6. Does WP0 leave `docs/acceptance-status.json` topology semantics unchanged?

Resolve all Critical and Important findings before continuing.

- [ ] **Step 7: Verify worktree and diff**

Run:

```powershell
git status --short
git diff --check
git log --oneline main..HEAD
```

Expected: only the two completion-document edits are uncommitted, whitespace is
clean, and the log contains task-sized commits.

- [ ] **Step 8: Commit the completion record**

```powershell
git add docs/superpowers/specs/2026-08-30-lcc-mmc-wp0-baseline-design.md docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md
git commit -m "docs: record WP0 baseline verification"
```

- [ ] **Step 9: Run final post-commit verification**

```powershell
pytest -q `
  tests/test_lcc_mmc_program_baseline.py `
  tests/test_lcc_mmc_evidence_index.py `
  tests/test_lcc_mmc_preflight.py `
  tests/test_lcc_mmc_preflight_cli.py `
  tests/test_lcc_mmc_preflight_real.py `
  tests/test_acceptance_status_manifest.py
ruff check pscad_mcp/acceptance tests/test_lcc_mmc_program_baseline.py tests/test_lcc_mmc_evidence_index.py tests/test_lcc_mmc_preflight.py tests/test_lcc_mmc_preflight_cli.py tests/test_lcc_mmc_preflight_real.py
git status --short
git diff --check
```

Expected: tests and lint pass, the opt-in real test skips in this offline run,
and the worktree is clean.

## WP0 Exit Criteria

WP0 is complete only when:

- strict schema and canonical hash tests pass;
- current and historical evidence cannot be confused;
- only explicit regular report files can be indexed;
- static preflight validates repository, writable isolated workspace, Master,
  compiler inventory, automation, processes, and legacy numbered output discovery;
- licensed preflight attaches, proves license/runtime, creates no project, quits, and leaves no process;
- checked-in baseline validates and contains all nine scopes;
- existing topology acceptance semantics remain unchanged;
- full tests and targeted lint pass;
- code review has no unresolved Critical or Important finding;
- the generated completion record includes actual paths, hashes, commit, and preflight report.

## Self-Review Checklist

- Spec coverage: Tasks 1-7 cover WP0 schema, report index, preflight, seed data, documentation, verification, review, and handoff.
- Placeholder scan: Angle-bracket text appears only in expected command-output notation; no implementation step delegates an unspecified implementation decision.
- Type consistency: `validate_program_baseline`, `apply_scope_report`, `index_explicit_reports`, `PreflightRequest`, `run_static_preflight`, `run_licensed_session_preflight`, `run_program_preflight`, `write_preflight_report`, and `preflight_cli.main` retain the same names across tasks and tests.
- Scope check: No LCC/MMC electrical model, planner, executor, asset, or acceptance algorithm changes are included.
