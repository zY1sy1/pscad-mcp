# MMC Parametric Dual-Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PSCAD 4.6.2 MMC inspection, parameterized detailed-PWM and average-value model construction, executable simulation recommendations, and bounded diagnosis-driven adjustment through seven stable MCP tools.

**Architecture:** Preserve the current `PscadService -> backend -> domain service` boundary and selectively transplant only the tested internal MMC Stage A foundation from `codex/mmc-autonomous-builder`. Build a new parameterized parent lifecycle above two separate engines: an audited installed-example PWM adapter and a repository-owned AVM builder. Both engines share request, plan, scenario, journal, and reporting contracts, while retaining separate derivation and acceptance logic.

**Tech Stack:** Python 3.10+, frozen dataclasses, `xml.etree.ElementTree`, `pathlib`, `hashlib`, `asyncio`, FastMCP, pytest, PSCAD 4.6.2 Legacy Automation Library.

---

## Execution Gates

- Create an isolated worktree before implementation with `using-git-worktrees`.
- Execute this plan with `subagent-driven-development` only when the user explicitly authorizes subagents; otherwise use `executing-plans` inline.
- Use `test-driven-development` for every behavior change: add one focused failing test, observe the expected failure, then add production code.
- Never modify the installed files under `C:\Users\Public\Documents\PSCAD\4.6\Examples`.
- Never import official PSCX/PSLX content into Git history or package data.
- Keep the current 83 tool names and LCC canonical hashes unchanged until Task 14 adds exactly seven MMC tools.
- Default tests must run with licensed acceptance disabled:

```powershell
Remove-Item Env:PSCAD_MCP_ACCEPTANCE -ErrorAction SilentlyContinue
Remove-Item Env:PSCAD_MCP_MMC_ACCEPTANCE -ErrorAction SilentlyContinue
Remove-Item Env:PSCAD_MCP_MMC_TEMPLATE -ErrorAction SilentlyContinue
Remove-Item Env:PSCAD_MCP_MMC_LIBRARY -ErrorAction SilentlyContinue
& .venv\Scripts\python.exe -m pytest -q
& .venv\Scripts\python.exe -m compileall -q pscad_mcp tests
git diff --check
```

## File Map

Import and adapt from `codex/mmc-autonomous-builder`:

- `pscad_mcp/hvdc/builders/common/`: finite serialization, records, routing, journals, and workspace lease.
- `pscad_mcp/hvdc/builders/mmc/models.py`: immutable fixed-builder records extended by parametric records.
- `pscad_mcp/hvdc/builders/mmc/schema.py`: fixed AVM asset parsing retained behind the AVM engine.
- `pscad_mcp/hvdc/builders/mmc/electrical.py`: average-arm equations and finite checks.
- `pscad_mcp/hvdc/builders/mmc/controls.py`: controls and operating-sequence reducer.
- `pscad_mcp/hvdc/builders/mmc/assets.py`, `catalog.py`, `planner.py`, `project_graph.py`, `validator.py`, `acceptance.py`, `journal.py`, `executor.py`, `service.py`: internal Stage A base.
- `pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1/`: repository-authored AVM assets, subject to renewed audit.
- `scripts/audit_mmc_assets.py`: AVM asset audit.

Create:

- `pscad_mcp/hvdc/pscad_graph.py`: PSCAD 4.6 definition/instance/port/Wire graph parser used by generic inspection.
- `pscad_mcp/hvdc/builders/mmc/inspection.py`: MMC-specific structural interpretation.
- `pscad_mcp/hvdc/builders/mmc/template_audit.py`: installed official template discovery and read-only audit.
- `pscad_mcp/hvdc/builders/mmc/parametric_models.py`: request, design, candidate, parent plan, scenario, and adjustment records.
- `pscad_mcp/hvdc/builders/mmc/derivation.py`: common and per-engine deterministic derivation.
- `pscad_mcp/hvdc/builders/mmc/parametric_planner.py`: immutable parent/child plan composition.
- `pscad_mcp/hvdc/builders/mmc/engines/__init__.py`: engine protocol exports.
- `pscad_mcp/hvdc/builders/mmc/engines/pwm.py`: installed-example staging and parameter application.
- `pscad_mcp/hvdc/builders/mmc/engines/avm.py`: parametric AVM blueprint materialization.
- `pscad_mcp/hvdc/builders/mmc/scenarios.py`: executable normal/fault recommendations.
- `pscad_mcp/hvdc/builders/mmc/diagnostics.py`: stable failure classification.
- `pscad_mcp/hvdc/builders/mmc/adjustment.py`: preplanned bounded candidate selection.
- `pscad_mcp/hvdc/builders/mmc/parametric_service.py`: public dual-engine lifecycle.
- `pscad_mcp/tools/mmc_tools.py`: seven MCP wrappers from the approved design.
- `tests/fixtures/mmc_synthetic/`: independently authored compact XML and waveform fixtures.
- `tests/mmc_parametric_fakes.py`: shared deterministic request, audit, plan, service, and hashing fixtures used by the focused tests.
- `tests/test_pscad_graph.py`, `test_mmc_inspection.py`, `test_mmc_template_audit.py`, `test_mmc_parametric_models.py`, `test_mmc_derivation.py`, `test_mmc_parametric_planner.py`, `test_mmc_pwm_engine.py`, `test_mmc_avm_engine.py`, `test_mmc_scenarios.py`, `test_mmc_diagnostics.py`, `test_mmc_adjustment.py`, `test_mmc_parametric_service.py`, and `test_mmc_parametric_tools.py`.
- `tests/test_mmc_parametric_real_acceptance.py`: opt-in PSCAD 4.6.2 matrix.

Modify:

- `pscad_mcp/hvdc/scanner.py`, `classifier.py`, `models.py`, and `service.py`: consume structured port/Wire evidence and attach MMC interpretation.
- `pscad_mcp/hvdc/builders/lcc/journal.py`: use the shared cross-builder lock while preserving LCC journal paths and errors.
- `pscad_mcp/hvdc/profiles.py`: add project-qualified MMC scenario selectors and command roles.
- `pscad_mcp/main.py`: register the seven MMC tools.
- `pyproject.toml`: package only repository-owned MMC assets.
- `tests/test_tool_inventory.py`, `test_tool_backend_matrix.py`, `test_install_smoke.py`, `test_packaging_metadata.py`: assert 90 tools and package boundaries.
- `README.md`, `docs/zh-CN/README.md`, `CHANGELOG.md`, `docs/acceptance-status.json`: document scope and real evidence honestly.

## Shared Test Support Contract

Create `tests/mmc_parametric_fakes.py` when Task 5 first needs it, then extend it in the task that first consumes each production record. This prevents examples in later tasks from depending on unnamed fixtures. Its base helpers are:

```python
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from pscad_mcp.hvdc.scanner import scan_project


FIXTURES = Path(__file__).parent / "fixtures" / "mmc_synthetic"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "model_fidelity": "both",
        "topology": "two_terminal_symmetrical_monopole",
        "converter": "half_bridge",
        "dc_voltage_kv": 640.0,
        "active_power_mw": 1000.0,
        "reactive_power_mvar": 0.0,
        "frequency_hz": 60.0,
        "station_p": {"ac_voltage_kv": 230.0, "short_circuit_ratio": 5.0, "x_over_r": 10.0},
        "station_vdc": {"ac_voltage_kv": 230.0, "short_circuit_ratio": 5.0, "x_over_r": 10.0},
        "dc_link": {"kind": "overhead_line", "length_km": 200.0},
        "power_reversal_time_s": 0.5,
        "engineering_overrides": {},
    }
    payload.update(overrides)
    return payload


def load_mmc_synthetic_evidence(name: str):
    return scan_project(FIXTURES / f"{name}.pscx")


def make_synthetic_official_shape(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    project = root / "H_MMC_Mono_DC.pscx"
    library = root / "intermediate.pslx"
    shutil.copy2(FIXTURES / "official_shape.pscx", project)
    shutil.copy2(FIXTURES / "official_shape.pslx", library)
    return project, library
```

Later tasks add these exact fixture functions to the same module when their referenced production records exist:

- Task 9: `pwm_audit()` returns a compatible audit with source hashes and confirmed bindings; `avm_assets()` loads the repository-owned asset set.
- Task 10: `pwm_plan(project, library, workspace)` returns an `MmcEnginePlan` whose first candidate is executable; `pwm_plan_with_unresolved_line_constants(workspace)` returns one blocking `requires_verified_rebind` dependency; `RecordingMmcService` records public service calls and writes only under its supplied workspace.
- Task 11: `avm_parametric_plan(workspace, dc_voltage_kv, active_power_mw)` returns an AVM `MmcEnginePlan` derived from `valid_request()`.
- Task 12: `pwm_design()` and `avm_design()` return `MmcDerivedParameters` for the nominal request with their respective fidelity.
- Task 13: `error_with_code(code)`, `numerical_failure()`, and `repeated_failure()` return stable `BackendError` evidence; `parent_plan_with_four_candidates()` returns an immutable parent plan with four ordered candidates per engine.
- Task 14: `make_parametric_service(workspace, pwm_verdict, avm_verdict)` injects recording engines into `ParametricMmcBuilderService`; `wait_for_terminal(service, build_id)` advances the event loop until `published|failed|interrupted` with a five-second test timeout.
- Task 15: `built_wheel_names()` builds the current repository with `python -m build --wheel`, opens the single wheel with `zipfile.ZipFile`, and returns its `set[str]` member names.

Every helper must construct the real frozen production records. It must not use `SimpleNamespace`, bypass validation, mutate a source file, or add test-only methods to production classes.

## Task 1: Establish an Isolated Baseline

**Files:** No production changes.

- [ ] **Step 1: Create the implementation worktree and branch**

Use `using-git-worktrees`, starting from commit `5be19c5`, and name the branch `codex/mmc-parametric-dual-engine`.

- [ ] **Step 2: Record the exact baseline**

Run:

```powershell
git status --short --branch
& .venv\Scripts\python.exe -m pytest -q
& .venv\Scripts\python.exe -m compileall -q pscad_mcp tests
git diff --check
```

Expected: the test suite passes, compileall exits `0`, and `git diff --check` emits no errors. Record the test count in the execution notes.

- [ ] **Step 3: Commit only if the worktree bootstrap created tracked metadata**

```powershell
git status --short
```

Expected: no tracked changes. Do not make an empty commit.

## Task 2: Transplant the Tested Internal MMC Stage A Foundation

**Files:** Import the internal files listed in the File Map; do not import old public tool registration, inventory counts, README changes, or acceptance claims.

- [ ] **Step 1: Apply the old-branch internal tests first**

Apply the complete test versions from `8872a96f72c039ebca1925b8e6a6cfa8763e7d19` using a binary Git patch. The path list is deliberately limited to tests for internal modules:

```powershell
git diff --binary --no-renames a3984bb983ed0b9de95b9aa45ea5fbdf4f263f6e 8872a96f72c039ebca1925b8e6a6cfa8763e7d19 -- `
  tests/mmc_builder_fakes.py `
  tests/test_mmc_acceptance.py `
  tests/test_mmc_asset_audit.py `
  tests/test_mmc_assets_loader.py `
  tests/test_mmc_containment.py `
  tests/test_mmc_controls.py `
  tests/test_mmc_electrical.py `
  tests/test_mmc_executor.py `
  tests/test_mmc_journal.py `
  tests/test_mmc_models.py `
  tests/test_mmc_planner.py `
  tests/test_mmc_production_assets.py `
  tests/test_mmc_project_graph.py `
  tests/test_mmc_schema.py `
  tests/test_mmc_service.py `
  tests/test_mmc_validator.py | git apply --3way
```

- [ ] **Step 2: Run the tests and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_models.py tests/test_mmc_schema.py -q
```

Expected: collection fails because `pscad_mcp.hvdc.builders.mmc` does not exist.

- [ ] **Step 3: Apply the complete internal implementation and repository-owned assets**

```powershell
git diff --binary --no-renames a3984bb983ed0b9de95b9aa45ea5fbdf4f263f6e 8872a96f72c039ebca1925b8e6a6cfa8763e7d19 -- `
  pscad_mcp/hvdc/builders/common `
  pscad_mcp/hvdc/builders/mmc `
  pscad_mcp/assets/mmc `
  scripts/audit_mmc_assets.py | git apply --3way
```

Do not apply `pscad_mcp/tools/mmc_tools.py`, `pscad_mcp/main.py`, README files, profiles, package metadata, inventory tests, or real-acceptance files from the old branch.

- [ ] **Step 4: Run the internal foundation tests and verify GREEN**

```powershell
& .venv\Scripts\python.exe -m pytest `
  tests/test_mmc_models.py tests/test_mmc_schema.py tests/test_mmc_electrical.py `
  tests/test_mmc_controls.py tests/test_mmc_asset_audit.py tests/test_mmc_assets_loader.py `
  tests/test_mmc_production_assets.py tests/test_mmc_planner.py `
  tests/test_mmc_project_graph.py tests/test_mmc_validator.py tests/test_mmc_acceptance.py `
  tests/test_mmc_journal.py tests/test_mmc_executor.py tests/test_mmc_service.py `
  tests/test_mmc_containment.py -q
```

Expected: all imported tests pass. If a test depends on an old main-branch tool count, remove that dependency rather than changing the current inventory.

- [ ] **Step 5: Re-audit provenance and package content**

```powershell
& .venv\Scripts\python.exe scripts/audit_mmc_assets.py --asset-root pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1
rg -n -i "C:\\|E:\\|H_MMC_Mono_DC|intermediate\.pslx" pscad_mcp/assets/mmc
```

Expected: the asset audit passes and the search finds no official-example content or author-machine path.

- [ ] **Step 6: Commit the internal foundation**

```powershell
git add pscad_mcp/hvdc/builders/common pscad_mcp/hvdc/builders/mmc pscad_mcp/assets/mmc scripts/audit_mmc_assets.py tests/mmc_builder_fakes.py tests/test_mmc_*.py
git commit -m "feat(mmc): integrate tested internal builder foundation"
```

## Task 3: Share One LCC/MMC Workspace Lease Without Changing LCC Hashes

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/journal.py`
- Test: `tests/test_common_builder.py`
- Test: existing `tests/test_lcc_journal.py`, `tests/test_lcc_planner.py`, `tests/test_lcc_parametric_service.py`

- [ ] **Step 1: Write the failing cross-builder lock test**

Create `tests/test_common_builder.py` with this focused behavior in addition to canonical serialization tests:

```python
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.journal import WorkspaceBuildLease as LccLease
from pscad_mcp.hvdc.builders.mmc.journal import WorkspaceBuildLease as MmcLease


def test_lcc_and_mmc_use_one_workspace_lock(tmp_path: Path) -> None:
    lcc = LccLease.acquire(tmp_path, "lcc-1")
    try:
        with pytest.raises(BackendError) as raised:
            MmcLease.acquire(tmp_path, "mmc-1")
        assert raised.value.code in {"BUILDER_BUILD_CONFLICT", "MMC_BUILD_CONFLICT"}
        assert raised.value.details["build_id"] == "lcc-1"
    finally:
        assert lcc.release(lcc.token) is True
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_common_builder.py::test_lcc_and_mmc_use_one_workspace_lock -q
```

Expected: the MMC lease can be acquired because the current LCC lock uses `lcc-build.lock`.

- [ ] **Step 3: Replace only the LCC lease implementation with a compatibility subclass**

Retain `AtomicJournal` and every LCC error shape. Make the LCC lease use the common lock filename:

```python
from ..common.journal import WorkspaceBuildLease as CommonWorkspaceBuildLease


class WorkspaceBuildLease(CommonWorkspaceBuildLease):
    journal_class = AtomicJournal
    lock_filename = "builder-build.lock"
    guard_filename = "builder-build.guard"
    lock_description = "LCC/MMC builder lock"
    owner_description = "LCC or MMC builder"

    @classmethod
    def _build_conflict(cls, message: str, **details: Any) -> BackendError:
        return BackendError(
            "LCC_BUILD_CONFLICT",
            message,
            "hvdc",
            "acquire_lcc_build_lease",
            details,
        )
```

The MMC lease must use the same `builder-build.lock`; do not change either journal directory.

- [ ] **Step 4: Verify GREEN and all LCC compatibility contracts**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_common_builder.py tests/test_lcc_journal.py tests/test_lcc_planner.py tests/test_lcc_parametric_service.py -q
```

Expected: the cross-builder test passes and all existing LCC hashes/status records remain unchanged.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/lcc/journal.py tests/test_common_builder.py
git commit -m "refactor(hvdc): share one LCC MMC build lease"
```

## Task 4: Parse PSCAD 4.6 Ports and Vertex Wires

**Files:**
- Create: `pscad_mcp/hvdc/pscad_graph.py`
- Modify: `pscad_mcp/hvdc/models.py`
- Modify: `pscad_mcp/hvdc/scanner.py`
- Test: `tests/test_pscad_graph.py`
- Test: `tests/test_hvdc_scanner.py`

- [ ] **Step 1: Add an independently authored compact PSCX fixture and failing test**

Create `tests/fixtures/mmc_synthetic/two_terminal_wire_graph.pscx` with two local definitions, ports at `(-54, 0)` and `(54, 0)`, two instances, and one Wire whose absolute endpoint coordinates match the transformed ports. Do not copy any official expression or component body.

```python
from pathlib import Path

from pscad_mcp.hvdc.scanner import scan_project


FIXTURE = Path(__file__).parent / "fixtures" / "mmc_synthetic" / "two_terminal_wire_graph.pscx"


def test_scanner_resolves_pscad_vertex_wire_to_component_ports() -> None:
    evidence = scan_project(FIXTURE)
    assert len(evidence.connections) == 1
    connection = evidence.connections[0]
    assert (connection.source_component_id, connection.source_port) == ("station-p", "dc")
    assert (connection.target_component_id, connection.target_port) == ("station-vdc", "dc")
    assert connection.evidence == ("WireOrthogonal", "vertex_coordinates")
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_pscad_graph.py -q
```

Expected: `connections` is empty.

- [ ] **Step 3: Implement coordinate-aware graph parsing**

`pscad_graph.py` must provide these complete public records and functions:

```python
from dataclasses import dataclass
from xml.etree.ElementTree import Element


@dataclass(frozen=True)
class PscadPortPoint:
    component_id: str
    port_name: str
    point: tuple[int, int]
    mode: str
    dimension: str


@dataclass(frozen=True)
class PscadWirePath:
    wire_id: str
    class_id: str
    vertices: tuple[tuple[int, int], ...]


def absolute_vertices(wire: Element) -> tuple[tuple[int, int], ...]:
    origin_x = int(wire.attrib.get("x", "0"))
    origin_y = int(wire.attrib.get("y", "0"))
    points = tuple(
        (origin_x + int(vertex.attrib["x"]), origin_y + int(vertex.attrib["y"]))
        for vertex in wire
        if vertex.tag.rsplit("}", 1)[-1].casefold() == "vertex"
    )
    if len(points) < 2:
        raise ValueError("PSCAD Wire requires at least two vertices")
    return points
```

Use the imported common `transform_offset()` for instance orientation. Index every external definition port by absolute coordinate, union touching/intersecting orthogonal Wire segments, and emit a connection only when a net has exactly two unambiguous compatible component ports. Retain ambiguous/multi-drop nets as structured warnings rather than inventing endpoints.

- [ ] **Step 4: Integrate with `scan_project`**

Replace `_connection_records()` for PSCAD vertex Wires with `scan_pscad_connections(root, project_path, scopes)` from `pscad_graph.py`. Preserve the existing explicit `from_component`/`to_component` parser for current synthetic fixtures.

- [ ] **Step 5: Verify GREEN and scanner regression**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_pscad_graph.py tests/test_hvdc_scanner.py tests/test_hvdc_classifier.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/hvdc/pscad_graph.py pscad_mcp/hvdc/models.py pscad_mcp/hvdc/scanner.py tests/fixtures/mmc_synthetic/two_terminal_wire_graph.pscx tests/test_pscad_graph.py tests/test_hvdc_scanner.py
git commit -m "feat(hvdc): parse PSCAD vertex wire connectivity"
```

## Task 5: Add MMC-Specific Inspection and Correct Topology Classification

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/inspection.py`
- Modify: `pscad_mcp/hvdc/classifier.py`
- Modify: `pscad_mcp/hvdc/service.py`
- Create: `tests/mmc_parametric_fakes.py`
- Test: `tests/test_mmc_inspection.py`
- Test: `tests/test_hvdc_classifier.py`

- [ ] **Step 1: Write failing interpretation tests**

Create independently authored `tests/fixtures/mmc_synthetic/two_terminal_monopole.pscx` and `incomplete_mmc.pscx`. The first contains two station definitions connected to explicit positive/negative conductors, twelve arm-role instances, PWM cell/carrier/firing evidence, controls, protection, and measurements. The second omits one station arm and its current measurement so the report must remain incomplete.

```python
from pscad_mcp.hvdc.builders.mmc.inspection import inspect_mmc_evidence
from tests.mmc_parametric_fakes import load_mmc_synthetic_evidence


def test_mmc_inspection_uses_structure_for_terminal_and_polarity() -> None:
    report = inspect_mmc_evidence(load_mmc_synthetic_evidence("two_terminal_monopole"))
    assert report["family"] == "mmc"
    assert report["topology"] == "two_terminal_symmetrical_monopole"
    assert report["terminal_count"] == 2
    assert report["model_fidelity"] == "detailed_pwm"
    assert report["stations"] == ["STATION_P", "STATION_VDC"]
    assert report["unresolved_questions"] == []


def test_mmc_inspection_does_not_emit_lcc_return_path_questions() -> None:
    report = inspect_mmc_evidence(load_mmc_synthetic_evidence("incomplete_mmc"))
    assert all("LCC" not in item for item in report["unresolved_questions"])
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_inspection.py -q
```

Expected: the module does not exist.

- [ ] **Step 3: Implement evidence-based MMC interpretation**

Return exactly these top-level keys: `family`, `topology`, `terminal_count`, `converter`, `model_fidelity`, `stations`, `arms`, `controls`, `protection`, `measurements`, `confidence`, `evidence`, and `unresolved_questions`. Determine `detailed_pwm` only from explicit cell/carrier/firing structure and `average_value` only from declared average-arm definitions. Determine symmetrical monopole from positive and negative conductors shared by two stations, not from the number of names containing `pole`.

- [ ] **Step 4: Attach the MMC report and fix the generic classifier**

When the family is MMC, `HvdcDomainService._inspection()` adds `mmc` from `inspect_mmc_evidence()`. `classify_topology()` must use its `terminal_count` and polarity result and must skip `analyze_return_paths()` for MMC/VSC families.

- [ ] **Step 5: Verify GREEN**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_inspection.py tests/test_hvdc_classifier.py tests/test_hvdc_tools.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/inspection.py pscad_mcp/hvdc/classifier.py pscad_mcp/hvdc/service.py tests/test_mmc_inspection.py tests/test_hvdc_classifier.py tests/mmc_parametric_fakes.py tests/fixtures/mmc_synthetic
git commit -m "feat(mmc): add structure-backed model inspection"
```

## Task 6: Discover and Audit the Installed Official PWM Example

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/template_audit.py`
- Test: `tests/test_mmc_template_audit.py`

- [ ] **Step 1: Write failing discovery, hash, and immutability tests**

Create independently authored `tests/fixtures/mmc_synthetic/official_shape.pscx` and `official_shape.pslx`. They reproduce only the minimum PSCAD XML shapes needed for audit: version metadata, two converter roles, two PWM converter roles, a sibling library namespace, confirmed parameter names, one missing startup snapshot, one line database path, and one line-constants path. They must not copy official equations, graphics, labels, numeric parameter sets, or component bodies.

```python
from pathlib import Path

from pscad_mcp.hvdc.builders.mmc.template_audit import audit_mmc_template


def test_audit_reports_sources_roles_and_absolute_paths_without_writes(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    before = (project.read_bytes(), library.read_bytes())
    report = audit_mmc_template(project, library)
    assert report["compatible"] is True
    assert report["pscad_version"] == "4.6.2"
    assert report["model_fidelity"] == "detailed_pwm"
    assert report["source_hashes"] == {
        "project": sha256(project),
        "library": sha256(library),
    }
    assert {item["kind"] for item in report["absolute_paths"]} == {
        "startup_snapshot",
        "line_database",
        "line_constants",
    }
    assert before == (project.read_bytes(), library.read_bytes())
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_template_audit.py -q
```

- [ ] **Step 3: Implement bounded discovery and structured audit**

The public functions are:

```python
def discover_official_mmc_template(public_root: str | Path | None = None) -> tuple[Path, Path]:
    root = Path(public_root) if public_root is not None else Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    directory = root / "Documents" / "PSCAD" / "4.6" / "Examples" / "ModelsInProgress"
    project = directory / "H_MMC_Mono_DC.pscx"
    library = directory / "intermediate.pslx"
    if not project.is_file() or not library.is_file():
        raise BackendError("MMC_TEMPLATE_NOT_FOUND", "The installed PSCAD 4.6 MMC example was not found.", "hvdc", "audit_mmc_template", {"project": str(project), "library": str(library)})
    return project.resolve(), library.resolve()


def audit_mmc_template(
    template_path: str | Path | None = None,
    library_path: str | Path | None = None,
) -> dict[str, object]:
    project, library = resolve_template_pair(template_path, library_path)
    return build_template_audit(project, library).to_dict()
```

Parse XML with ElementTree. Record definitions, dependencies, role bindings, writable parameter bindings, source hashes, and every absolute path with `kind`, `owner`, `parameter`, `value`, and `repair_policy`. Only a missing startup snapshot is directly removable. Line database/constants paths are `requires_verified_rebind` until a same-identity installed file or public line-constant regeneration capability is proven.

- [ ] **Step 4: Add the real installed-example read-only contract test**

Mark it skip-only when the two official files are absent. Assert the known hashes on this machine only when `PSCAD_MCP_MMC_ACCEPTANCE=1`; default CI must not depend on those exact hashes.

- [ ] **Step 5: Verify GREEN**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_template_audit.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/template_audit.py tests/test_mmc_template_audit.py tests/fixtures/mmc_synthetic
git commit -m "feat(mmc): audit installed PSCAD PWM example"
```

## Task 7: Define the Unified Parametric Request and Immutable Records

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/parametric_models.py`
- Test: `tests/test_mmc_parametric_models.py`

- [ ] **Step 1: Write failing request parsing and immutability tests**

```python
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request


def test_parse_dual_engine_request_is_finite_and_immutable() -> None:
    request = parse_parametric_request(valid_request(model_fidelity="both"))
    assert request.model_fidelity == "both"
    assert request.topology == "two_terminal_symmetrical_monopole"
    assert request.converter == "half_bridge"
    assert request.dc_voltage_kv == 640.0
    assert request.station_p.short_circuit_ratio == 5.0
    with pytest.raises(TypeError):
        request.engineering_overrides["arm_inductance_h"] = 1.0


@pytest.mark.parametrize("field", ["dc_voltage_kv", "active_power_mw", "frequency_hz"])
def test_request_rejects_non_finite_values(field: str) -> None:
    payload = valid_request()
    payload[field] = float("nan")
    with pytest.raises(BackendError) as raised:
        parse_parametric_request(payload)
    assert raised.value.code == "MMC_REQUEST_INVALID"
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_models.py -q
```

- [ ] **Step 3: Implement exact records**

Implement frozen records `MmcGridRequest`, `MmcDcLinkRequest`, `MmcParametricRequest`, `MmcConstraintResult`, `MmcDerivedParameters`, `MmcCandidate`, `MmcEnginePlan`, `MmcParentPlan`, `MmcScenarioRecommendation`, `MmcAdjustment`, and `MmcParametricBuildRecord`. Every record extends the imported finite `JsonRecord` contract.

`parse_parametric_request()` accepts only the fields and enum values in the approved design. `engineering_overrides` values have shape `{"value": finite_number, "unit": non_empty_string}`. Reject unknown keys, booleans as numbers, unsupported units, non-positive ratings, topology other than `two_terminal_symmetrical_monopole`, converter other than `half_bridge`, and fidelity outside `detailed_pwm|average_value|both`.

- [ ] **Step 4: Verify GREEN**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_models.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/parametric_models.py tests/test_mmc_parametric_models.py
git commit -m "feat(mmc): define unified parametric request records"
```

## Task 8: Derive Deterministic PWM and AVM Candidates

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/derivation.py`
- Test: `tests/test_mmc_derivation.py`

- [ ] **Step 1: Write failing formula, scaling, and infeasibility tests**

```python
from pscad_mcp.hvdc.builders.mmc.derivation import derive_mmc_parameters


def test_common_base_quantities_are_dimensionally_correct() -> None:
    report = derive_mmc_parameters(parse_parametric_request(valid_request()))
    assert report.common["dc_current_ka"] == pytest.approx(1000.0 / 640.0)
    assert report.common["station_p_grid_impedance_ohm"] == pytest.approx(
        230.0**2 / (5.0 * 1000.0)
    )
    assert {candidate.engine for candidate in report.candidates} == {"detailed_pwm", "average_value"}


def test_voltage_and_power_scaling_preserves_dimensionless_margin() -> None:
    base = derive_mmc_parameters(parse_parametric_request(valid_request()))
    scaled = derive_mmc_parameters(parse_parametric_request(valid_request(dc_voltage_kv=1280.0, active_power_mw=2000.0)))
    assert scaled.common["dc_current_ka"] == pytest.approx(base.common["dc_current_ka"])
    assert scaled.common["station_p_grid_impedance_ohm"] == pytest.approx(2.0 * base.common["station_p_grid_impedance_ohm"])
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_derivation.py -q
```

- [ ] **Step 3: Implement versioned derivation**

Use `equation_version="mmc-parametric-v1"`. Compute common DC current, station base impedances, grid R/X, line drop, transformer rating, requested reversal slope, and power/loss budget. Generate per-engine candidates from explicit reference evidence:

```python
dc_current_ka = request.active_power_mw / request.dc_voltage_kv
z_base_ohm = station.ac_voltage_kv**2 / request.active_power_mw
z_grid_ohm = z_base_ohm / station.short_circuit_ratio
r_grid_ohm = z_grid_ohm / math.sqrt(1.0 + station.x_over_r**2)
x_grid_ohm = r_grid_ohm * station.x_over_r
impedance_scale = (request.dc_voltage_kv / 640.0) ** 2 / (request.active_power_mw / 1000.0)
power_scale = request.active_power_mw / 1000.0
voltage_scale = request.dc_voltage_kv / 640.0
```

PWM reference values must come from the audited template record, not constants hidden in the executor. Scale cell count with `ceil(reference_cells * voltage_scale)`, arm inductance with `impedance_scale`, and energy storage with `power_scale`. AVM uses the repository asset reference and the same dimensionless margins. Emit failed `MmcConstraintResult` values for modulation, energy ripple, current, line drop, grid strength, bandwidth, non-positive cell count, and resource limits.

Generate at most four immutable candidates per engine: nominal, numerical-stability, control-margin, and energy-margin. The candidates may change derived engineering values and solver settings but never request ratings or acceptance thresholds.

- [ ] **Step 4: Verify GREEN and metamorphic coverage**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_derivation.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/derivation.py tests/test_mmc_derivation.py
git commit -m "feat(mmc): derive bounded dual-engine candidates"
```

## Task 9: Compose Immutable Parent and Child Plans

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/parametric_planner.py`
- Test: `tests/test_mmc_parametric_planner.py`

- [ ] **Step 1: Write failing determinism and no-side-effect tests**

```python
def test_parent_plan_is_deterministic_and_contains_two_independent_children(tmp_path: Path) -> None:
    request = parse_parametric_request(valid_request(model_fidelity="both"))
    before = list(tmp_path.iterdir())
    first = create_parametric_plan(request, "MMC_CASE", tmp_path, pwm_audit(), avm_assets())
    second = create_parametric_plan(request, "MMC_CASE", tmp_path, pwm_audit(), avm_assets())
    assert first.to_dict() == second.to_dict()
    assert first.plan_hash == second.plan_hash
    assert [plan.engine for plan in first.engine_plans] == ["detailed_pwm", "average_value"]
    assert [plan.target_name for plan in first.engine_plans] == ["MMC_CASE_pwm", "MMC_CASE_avm"]
    assert before == list(tmp_path.iterdir())
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_planner.py -q
```

- [ ] **Step 3: Implement canonical plan composition**

Bind request, equation version, template/asset hashes, ordered candidates, output paths, source bindings, standard scenarios, and per-engine operations. Hash each child payload with `content_hash()`, then hash the parent payload containing the ordered child hashes. Reject an existing `_pwm` or `_avm` final target, unresolved PWM path dependency, unavailable live definition inventory, candidate count outside 1-8, and any source/asset not covered by SHA-256 evidence.

Planning remains read-only. The only absolute external paths allowed in a plan are read-only source paths under the audited installed example; all staging/final/output paths must resolve inside `PSCAD_MCP_WORKSPACE`.

- [ ] **Step 4: Verify GREEN**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_planner.py tests/test_mmc_planner.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/parametric_planner.py tests/test_mmc_parametric_planner.py
git commit -m "feat(mmc): plan immutable dual-engine builds"
```

## Task 10: Implement the Detailed PWM Template Engine

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/engines/__init__.py`
- Create: `pscad_mcp/hvdc/builders/mmc/engines/pwm.py`
- Test: `tests/test_mmc_pwm_engine.py`

- [ ] **Step 1: Write failure-containment and source-immutability tests**

```python
def test_pwm_engine_copies_then_mutates_only_staging(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path / "source")
    source_hashes = (sha256(project), sha256(library))
    service = RecordingMmcService()
    result = asyncio.run(execute_pwm_candidate(pwm_plan(project, library, tmp_path), service))
    assert result["state"] == "accepted"
    assert (sha256(project), sha256(library)) == source_hashes
    assert all(Path(path).is_relative_to(tmp_path) for path in result["written_paths"])


def test_pwm_engine_stops_before_pscad_when_line_dependency_is_unresolved(tmp_path: Path) -> None:
    plan = pwm_plan_with_unresolved_line_constants(tmp_path)
    with pytest.raises(BackendError) as raised:
        asyncio.run(execute_pwm_candidate(plan, RecordingMmcService()))
    assert raised.value.code == "MMC_ABSOLUTE_PATH_UNRESOLVED"
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_pwm_engine.py -q
```

- [ ] **Step 3: Implement staged copy and exact binding application**

The engine protocol is:

```python
from typing import Protocol


class MmcEngine(Protocol):
    name: str

    async def execute_candidate(self, plan: MmcEnginePlan, service: object) -> dict[str, object]:
        raise NotImplementedError

    def validate(self, plan: MmcEnginePlan, project_path: Path, outputs: dict[str, object]) -> dict[str, object]:
        raise NotImplementedError
```

Concrete PWM and AVM engines implement both methods.

`PwmTemplateEngine` verifies source hashes immediately before copying, copies the project and sibling library into a candidate directory, verifies copy hashes, changes only audited parameter bindings through `PscadService`, reads each value back, saves, rereads the graph, compiles, and runs scenarios. A missing startup snapshot may be disabled in the staging project. A line database or `.tlo` path may only be rebound when a discovered file has the expected identity or a public PSCAD line-constant regeneration call succeeds; otherwise stop before loading PSCAD.

- [ ] **Step 4: Inject a failure after every mutation boundary**

Cover copy, load, startup setting, library binding, each parameter group, save, compile, scenario, output read, validation, and publication. Assert no later call runs and no final target exists.

- [ ] **Step 5: Verify GREEN**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_pwm_engine.py tests/test_mmc_template_audit.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/engines tests/test_mmc_pwm_engine.py
git commit -m "feat(mmc): execute audited PWM template candidates"
```

## Task 11: Parameterize the Repository-Owned AVM Engine

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/engines/avm.py`
- Modify: `pscad_mcp/hvdc/builders/mmc/planner.py`
- Test: `tests/test_mmc_avm_engine.py`
- Test: existing internal MMC tests.

- [ ] **Step 1: Write failing AVM materialization tests**

```python
def test_avm_engine_applies_derived_parameters_to_twelve_visible_arms(tmp_path: Path) -> None:
    plan = avm_parametric_plan(tmp_path, dc_voltage_kv=500.0, active_power_mw=750.0)
    blueprint = materialize_parametric_blueprint(plan)
    arms = [component for component in blueprint.components if component.role == "arm"]
    assert len(arms) == 12
    assert {arm.parameters["rated_dc_voltage_kv"] for arm in arms} == {500.0}
    assert {arm.parameters["rated_power_mw"] for arm in arms} == {750.0}
    assert blueprint.settings["time_step_s"] == plan.settings["time_step_s"]
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_avm_engine.py -q
```

- [ ] **Step 3: Add a parametric blueprint entry point**

Keep the fixed `create_plan()` behavior and hashes unchanged. Add `create_parametric_avm_plan(engine_plan, asset_set, inventory, path_policy)` that clones the loaded immutable blueprint with derived transformer, grid, line, arm R/L/C, energy, loss, control, timing, and output values before using the existing topology expansion and executor. Every derived value must be present in the child plan and read back after placement.

Represent the half-bridge blocked-state diode-equivalent path explicitly in the AVM asset/blueprint and output `intrinsic_dc_fault_blocking=false`. Do not add device-stress, switching-harmonic, thermal, or individual-cell acceptance fields.

- [ ] **Step 4: Verify GREEN and fixed Stage A regression**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_avm_engine.py tests/test_mmc_planner.py tests/test_mmc_executor.py tests/test_mmc_acceptance.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/engines/avm.py pscad_mcp/hvdc/builders/mmc/planner.py pscad_mcp/assets/mmc tests/test_mmc_avm_engine.py tests/test_mmc_planner.py tests/test_mmc_production_assets.py
git commit -m "feat(mmc): parameterize the average-value engine"
```

## Task 12: Generate Executable Normal and Fault Scenarios

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/scenarios.py`
- Modify: `pscad_mcp/hvdc/profiles.py`
- Test: `tests/test_mmc_scenarios.py`
- Test: `tests/test_mmc_profile.py`

- [ ] **Step 1: Write failing scenario completeness tests**

```python
REQUIRED = {
    "startup",
    "forward_steady",
    "active_power_step",
    "reactive_power_step",
    "power_reversal",
    "reverse_steady",
    "ac_three_phase_fault",
    "ac_single_line_ground_fault",
    "dc_pole_to_pole_fault",
    "dc_pole_to_ground_fault",
    "post_fault_recovery",
}


def test_recommendations_are_directly_runnable_and_model_aware() -> None:
    pwm = recommend_scenarios(pwm_design())
    avm = recommend_scenarios(avm_design())
    assert {item.name for item in pwm} == REQUIRED
    assert {item.name for item in avm} == REQUIRED
    assert all(item.scenario["profile"].startswith("mmc_") for item in pwm + avm)
    assert max(item.time_step_s for item in pwm) < max(item.time_step_s for item in avm)
    assert all(item.capabilities["intrinsic_dc_fault_blocking"] is False for item in pwm + avm)
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_scenarios.py -q
```

- [ ] **Step 3: Implement deterministic recommendations**

Calculate PWM time step from the minimum of the declared control sample time and a bounded fraction of switching period; calculate AVM time step from control and line dynamics. Each recommendation contains exact EMTDC event times, required command bindings, result selectors, units, preconditions, metrics, thresholds, and model limitations. Use only project-qualified v2 profile bindings; no writable alias inference.

DC-fault verdicts require fault application, block command, breaker action, diode-equivalent current evidence, clearing, and declared recovery/final state. They never require or report intrinsic half-bridge blocking.

- [ ] **Step 4: Verify GREEN and generic scenario compatibility**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_scenarios.py tests/test_mmc_profile.py tests/test_hvdc_scenarios.py tests/test_hvdc_preflight.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/scenarios.py pscad_mcp/hvdc/profiles.py tests/test_mmc_scenarios.py tests/test_mmc_profile.py
git commit -m "feat(mmc): recommend executable normal and fault scenarios"
```

## Task 13: Classify Failures and Select Bounded Preplanned Adjustments

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/diagnostics.py`
- Create: `pscad_mcp/hvdc/builders/mmc/adjustment.py`
- Test: `tests/test_mmc_diagnostics.py`
- Test: `tests/test_mmc_adjustment.py`

- [ ] **Step 1: Write failing diagnostic policy tests**

```python
@pytest.mark.parametrize(
    ("code", "category", "retryable"),
    [
        ("MMC_ABSOLUTE_PATH_UNRESOLVED", "binding_repair", False),
        ("MMC_NUMERICAL_UNSTABLE", "numerical_stability", True),
        ("MMC_CONTROL_UNSTABLE", "control_stability", True),
        ("MMC_ACCEPTANCE_FAILED", "acceptance", False),
        ("LICENSE_UNAVAILABLE", "environment", False),
        ("EXECUTOR_UNHEALTHY", "environment", False),
    ],
)
def test_failure_classification_is_explicit(code: str, category: str, retryable: bool) -> None:
    result = classify_mmc_failure(error_with_code(code))
    assert result.category == category
    assert result.retryable is retryable
```

- [ ] **Step 2: Write failing bounded-candidate tests**

```python
def test_adjustment_uses_only_next_preplanned_candidate() -> None:
    plan = parent_plan_with_four_candidates()
    decision = choose_next_candidate(plan, "detailed_pwm", attempted=("pwm-0",), failure=numerical_failure())
    assert decision.candidate_id == "pwm-1"
    assert decision.adjustment.category == "numerical_stability"


def test_same_signature_and_candidate_state_stops_loop() -> None:
    with pytest.raises(BackendError) as raised:
        choose_next_candidate(parent_plan_with_four_candidates(), "detailed_pwm", attempted=("pwm-0", "pwm-1"), failure=repeated_failure())
    assert raised.value.code == "MMC_CANDIDATES_EXHAUSTED"
```

- [ ] **Step 3: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_diagnostics.py tests/test_mmc_adjustment.py -q
```

- [ ] **Step 4: Implement closed diagnostic and adjustment tables**

Map known errors to `binding_repair`, `numerical_stability`, `control_stability`, `modulation_margin`, `energy_balance`, `initialization`, `physical_infeasible`, `environment`, or `containment`. Only the six approved adjustment categories may advance. License, connection, source/asset/plan drift, ambiguous bindings, physical infeasibility, protection inadequacy, containment uncertainty, and requested-rating changes stop immediately.

`choose_next_candidate()` may return only an existing candidate in the immutable child plan whose declared purpose matches the diagnostic category. Enforce 1-8 candidates, default four, stable order, unique parameter hashes, and repeated-signature stop.

- [ ] **Step 5: Verify GREEN**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_diagnostics.py tests/test_mmc_adjustment.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/diagnostics.py pscad_mcp/hvdc/builders/mmc/adjustment.py tests/test_mmc_diagnostics.py tests/test_mmc_adjustment.py
git commit -m "feat(mmc): add bounded diagnosis-driven adjustment"
```

## Task 14: Compose the Public Parametric Lifecycle and Seven Tools

**Files:**
- Create: `pscad_mcp/hvdc/builders/mmc/parametric_service.py`
- Create: `pscad_mcp/tools/mmc_tools.py`
- Modify: `pscad_mcp/main.py`
- Modify: inventory tests.
- Test: `tests/test_mmc_parametric_service.py`
- Test: `tests/test_mmc_parametric_tools.py`

- [ ] **Step 1: Write failing lifecycle tests**

Cover pure derivation, read-only audit/plan, confirmation, exact parent hash, source/asset drift, shared lease, serial child execution, candidate history, one-child failure, both-child independence, validation without output, full acceptance, interruption, and no final path on failure.

```python
def test_both_engines_publish_only_after_independent_acceptance(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path, pwm_verdict="PASS", avm_verdict="PASS")
    request = valid_request(model_fidelity="both")
    plan = service.plan_model(request, project_name="MMC_CASE", folder=str(tmp_path))
    started = asyncio.run(service.build_model(request, plan["plan_hash"], "MMC_CASE", str(tmp_path), confirm=True))
    terminal = wait_for_terminal(service, started["build_id"])
    assert terminal["state"] == "published"
    assert [item["capability_level"] for item in terminal["engines"]] == ["accepted", "accepted"]
    assert (tmp_path / "MMC_CASE_pwm.pscx").is_file()
    assert (tmp_path / "MMC_CASE_avm.pscx").is_file()
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_service.py -q
```

- [ ] **Step 3: Implement `ParametricMmcBuilderService`**

Expose methods `audit_template`, `derive_parameters`, `plan_model`, `build_model`, `get_status`, `recommend_simulation`, and `validate_model`. Planning caches a bounded copy by parent hash. Build recomposes and constant-time compares the plan hash before lease acquisition. Execute PWM then AVM serially under one shared lease, walk only preplanned candidates, retain bounded evidence, and atomically publish each final path only after independent acceptance and reopen/compile smoke verification.

If one engine fails, do not claim the parent published. A previously accepted child remains in its candidate directory until the entire parent transaction is ready; parent publication moves both final paths as one compensated operation, reverting the first move if the second cannot complete.

- [ ] **Step 4: Write the seven wrapper tests and verify RED**

```python
EXPECTED_MMC_TOOLS = {
    "audit_mmc_template",
    "derive_mmc_parameters",
    "plan_parametric_mmc_model",
    "build_parametric_mmc_model",
    "get_parametric_mmc_build_status",
    "recommend_mmc_simulation",
    "validate_mmc_model",
}


def test_exact_mmc_tools_are_registered() -> None:
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}
    assert EXPECTED_MMC_TOOLS <= names
    assert len(names) == 90
```

Run:

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_tools.py -q
```

Expected: the seven names are absent.

- [ ] **Step 5: Implement wrappers and register once**

Use the same cached-service pattern as `lcc_parametric_tools.py`. Wrappers accept JSON mappings and call `parse_parametric_request()` before the service. `build_parametric_mmc_model` requires `confirm=False` by default. Do not register the old fixed names `plan_mmc_model`, `build_mmc_model`, or `get_mmc_build_status`.

- [ ] **Step 6: Update exact inventories from 83 to 90 and verify GREEN**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_service.py tests/test_mmc_parametric_tools.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py tests/test_hvdc_tools.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add pscad_mcp/hvdc/builders/mmc/parametric_service.py pscad_mcp/tools/mmc_tools.py pscad_mcp/main.py tests/test_mmc_parametric_service.py tests/test_mmc_parametric_tools.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py tests/test_hvdc_tools.py
git commit -m "feat(mmc): expose the dual-engine parametric lifecycle"
```

## Task 15: Package Only Owned Assets and Add Real Acceptance Contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_packaging_metadata.py`
- Modify: `tests/test_install_smoke.py`
- Create: `tests/test_mmc_parametric_real_acceptance.py`
- Modify: `docs/acceptance-status.json`

- [ ] **Step 1: Write failing package-boundary tests**

```python
def test_wheel_contains_owned_avm_assets_and_no_official_example() -> None:
    names = built_wheel_names()
    assert any(name.endswith("assets/mmc/cigre_b4_p2p_avm_v1/manifest.json") for name in names)
    assert not any("H_MMC_Mono_DC" in name or name.endswith("intermediate.pslx") for name in names)
```

- [ ] **Step 2: Run and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_packaging_metadata.py tests/test_install_smoke.py -q
```

Expected: owned MMC assets are missing from the wheel metadata.

- [ ] **Step 3: Add exact package-data patterns**

Add only:

```toml
"assets/mmc/*/*.json",
"assets/mmc/*/*.md",
"assets/mmc/*/library/*.pslx",
```

Build/install a wheel in a temporary virtual environment, load and hash all AVM resources through `importlib.resources`, and assert all 90 tools register.

- [ ] **Step 4: Write the opt-in acceptance contract**

The test requires all of:

```text
PSCAD_MCP_MMC_ACCEPTANCE=1
PSCAD_MCP_BACKEND=legacy
PSCAD_MCP_VERSION=4.6.2
PSCAD_MCP_WORKSPACE=<absolute isolated workspace>
PSCAD_MCP_MMC_TEMPLATE=<absolute H_MMC_Mono_DC.pscx>
PSCAD_MCP_MMC_LIBRARY=<absolute intermediate.pslx>
```

It validates three feasible PWM requests, three feasible AVM requests, and six analytic-infeasible requests. Every feasible request runs its complete standard scenario set. The report records commit, runtime/compiler versions, source/asset/plan/project/output hashes, per-engine capability levels, source immutability, and pre-existing-workspace immutability.

- [ ] **Step 5: Verify default skip behavior and report validation**

```powershell
Remove-Item Env:PSCAD_MCP_MMC_ACCEPTANCE -ErrorAction SilentlyContinue
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_real_acceptance.py -q
```

Expected: one clean skip and no PSCAD process launch.

- [ ] **Step 6: Commit**

```powershell
git add pyproject.toml tests/test_packaging_metadata.py tests/test_install_smoke.py tests/test_mmc_parametric_real_acceptance.py docs/acceptance-status.json
git commit -m "test(mmc): add packaging and licensed acceptance gates"
```

## Task 16: Documentation, Full Verification, and Honest Capability Status

**Files:**
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`
- Modify: `scripts/verify_package.ps1`

- [ ] **Step 1: Update documentation assertions first**

Add tests asserting documentation contains all seven tools, 90-tool inventory, two fidelity modes, official-template read-only boundary, AVM limitations, half-bridge `intrinsic_dc_fault_blocking=false`, bounded four-candidate default, PSCAD 4.6.2 scope, and the distinction between `inspected`, `designed`, `planned`, `built`, `simulated`, and `accepted`.

- [ ] **Step 2: Run documentation tests and verify RED**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_delivery_hardening.py tests/test_tool_inventory.py tests/test_acceptance_status_manifest.py -q
```

- [ ] **Step 3: Update English/Chinese docs and changelog**

Document the exact request example from the design, plan/build/status/validate workflow, direct scenario recommendation output, default discovery path, source immutability, and recovery limits. State `NOT_RUN`, `INCOMPLETE_ANALYSIS`, or `PASS` exactly as supported by `docs/acceptance-status.json`; do not inherit LCC or historical MMC evidence.

- [ ] **Step 4: Run focused and full verification**

```powershell
& .venv\Scripts\python.exe -m pytest tests/test_pscad_graph.py tests/test_mmc_*.py -q
& .venv\Scripts\python.exe -m pytest -q
& .venv\Scripts\python.exe -m compileall -q pscad_mcp tests
& .venv\Scripts\python.exe -m build
& .venv\Scripts\python.exe -m pip check
git diff --check
git status --short
```

Expected: all default tests pass, licensed acceptance is skipped unless explicitly enabled, build and dependency checks pass, no whitespace errors exist, and only intentional tracked files are changed.

- [ ] **Step 5: Run licensed acceptance when the environment is ready**

```powershell
$env:PSCAD_MCP_MMC_ACCEPTANCE='1'
$env:PSCAD_MCP_BACKEND='legacy'
$env:PSCAD_MCP_VERSION='4.6.2'
$env:PSCAD_MCP_WORKSPACE='D:\PSCAD-Workspace\mmc-parametric-acceptance'
$env:PSCAD_MCP_MMC_TEMPLATE='C:\Users\Public\Documents\PSCAD\4.6\Examples\ModelsInProgress\H_MMC_Mono_DC.pscx'
$env:PSCAD_MCP_MMC_LIBRARY='C:\Users\Public\Documents\PSCAD\4.6\Examples\ModelsInProgress\intermediate.pslx'
& .venv\Scripts\python.exe -m pytest tests/test_mmc_parametric_real_acceptance.py -q -s
```

Expected: either a scope-specific `PASS` with complete hashes and scenario evidence, or a bounded `FAIL`/`INCOMPLETE_ANALYSIS` with the exact failure stage. A failure does not justify weakening tests or claims.

- [ ] **Step 6: Commit documentation and final status**

```powershell
git add README.md docs/zh-CN/README.md CHANGELOG.md scripts/verify_package.ps1 docs/acceptance-status.json tests/test_delivery_hardening.py tests/test_acceptance_status_manifest.py
git commit -m "docs: describe parameterized dual-engine MMC capability"
```

## Plan Self-Review Checklist

- Every approved design requirement maps to at least one task.
- The old branch is used only for repository-owned internal AVM foundations; old public tool counts and claims are excluded.
- The official PWM source remains external and read-only in every phase.
- Both engines share request/plan/status while retaining separate derivation and acceptance.
- Fault advice and bounded recovery are implemented before public registration.
- Existing LCC hashes and 83 tool contracts are explicitly regression-tested.
- The final public inventory is exactly 90.
- Licensed success is never inferred from default tests, compilation alone, or another scope.
