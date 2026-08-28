# PSCAD Topology Acceptance Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create six PSCAD 4.6.2-loadable topology acceptance projects and an independently audited `D:\PSCAD-Workspace\topology-truth.json`, then resume the licensed Task 12 gate without deriving truth from the implementation under test.

**Architecture:** A standard-library-only recipe module owns construction truth, PSCX generation, normalized-file auditing, deterministic manifest projection, and atomic publication. A separate licensed normalizer owns PSCAD process lifecycle and may import the Legacy backend, but neither module imports `pscad_mcp.topology`; a PowerShell runner composes both stages and refuses unsafe workspaces or existing PSCAD processes.

**Tech Stack:** Python 3.10+, frozen dataclasses, `xml.etree.ElementTree`, `hashlib`, `json`, `tempfile`, asyncio, PSCAD 4.6.2 Automation Library, PowerShell, pytest.

---

## Execution Invariants

- Continue in `D:\pscad-mcp\.worktrees\codex-unified-topology-diagnostics` on branch `codex/unified-topology-diagnostics`.
- Preserve the existing uncommitted Task 12 runner, real acceptance test, and README changes; stage only the files listed by the current task.
- Never import `pscad_mcp.topology` from the truth builder, auditor, or licensed normalizer.
- Never derive expected nets, codes, unresolved references, or capabilities from `TopologyService`, `PscxSnapshotProvider`, `build_connectivity`, `diagnose_generic`, or the MCP topology tools.
- Build and normalize only in a timestamped staging directory. Refuse existing final `topology-sources` and `topology-truth.json` destinations.
- Refuse to start construction or acceptance while any PSCAD process is open.
- Quit and verify only the PSCAD PIDs owned by the preparation or acceptance process.
- Stop after the licensed semantic probe if PSCAD does not preserve or expose the required port, namespace, dimension, label, and hierarchy evidence exactly.
- Do not update `docs/acceptance-status.json` or start Phase 2 until the current implementation commit has a validated licensed `PASS` report.

## File Map

### New repository files

- `scripts/topology_truth.py`: stdlib-only recipes, structured PSCX generation, normalized-file audit, manifest projection, hashing, and atomic publication.
- `scripts/normalize_topology_truth.py`: licensed Legacy process ownership, staged project load/save normalization, reopen verification, and preparation evidence.
- `scripts/prepare_topology_truth.ps1`: guarded end-to-end preparation command.
- `tests/test_topology_truth.py`: recipes, generator, auditor, manifest, scale, import isolation, and atomic publication.
- `tests/test_topology_truth_normalization.py`: normalization service-boundary and process cleanup tests.
- `tests/test_topology_truth_runner.py`: PowerShell guard and environment-scope contract tests.

### Existing repository files modified after real evidence

- `tests/test_topology_real_acceptance.py`: only if normalized PSCAD identity or manifest fields require a proven compatibility correction.
- `README.md`: preparation and review commands.
- `docs/zh-CN/README.md`: Chinese preparation and review commands.
- `docs/acceptance-status.json`: `unified_topology_462` evidence, after PASS only.
- `tests/test_acceptance_status_manifest.py`: exact named scope, after PASS only.

### External generated evidence

- `D:\PSCAD-Workspace\topology-sources\<case>\<case>.pscx`
- `D:\PSCAD-Workspace\topology-sources\construction-record.json`
- `D:\PSCAD-Workspace\topology-sources\preparation-report.json`
- `D:\PSCAD-Workspace\topology-truth.json`
- `D:\PSCAD-Workspace\topology-acceptance\topology-acceptance-<timestamp>\topology-acceptance-report.json`

## Task 1: Declarative Recipe And Deterministic Truth Contracts

**Files:**
- Create: `scripts/topology_truth.py`
- Create: `tests/test_topology_truth.py`

- [ ] **Step 1: Write failing recipe and manifest tests**

Add import loading that does not make `scripts` a package:

```python
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "topology_truth.py"
SPEC = importlib.util.spec_from_file_location("topology_truth", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
topology_truth = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = topology_truth
SPEC.loader.exec_module(topology_truth)


def test_truth_module_has_no_topology_implementation_imports():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name.startswith("pscad_mcp.topology") for name in imported)


def test_case_recipes_are_complete_and_have_exact_scale_counts():
    cases = topology_truth.case_recipes()
    assert [case.name for case in cases] == [
        "ordinary",
        "seeded-defects",
        "custom-library",
        "hierarchy-uncertain",
        "scale-500",
        "scale-2000",
    ]
    by_name = {case.name: case for case in cases}
    assert by_name["scale-500"].object_count == 500
    assert by_name["scale-2000"].object_count == 2000
    assert by_name["seeded-defects"].expected_error_codes == (
        "LABEL_CONFLICT",
        "PORT_DIMENSION_MISMATCH",
        "PORT_KIND_MISMATCH",
        "REQUIRED_PORT_UNCONNECTED",
        "WIRE_DANGLING_ENDPOINT",
    )
    assert by_name["hierarchy-uncertain"].expected_unresolved_codes == (
        "hierarchy_boundary_unresolved:Main:410:IN->Main/410:Child:IN",
    )


def test_manifest_is_projected_only_from_declared_truth(tmp_path):
    cases = topology_truth.case_recipes()
    sources = {}
    for case in cases:
        path = tmp_path / case.name / f"{case.name}.pscx"
        path.parent.mkdir()
        path.write_text(f'<project name="{case.name}"/>', encoding="utf-8")
        sources[case.name] = path

    manifest = topology_truth.manifest_from_recipes(cases, sources)

    assert manifest["schema_version"] == 1
    assert [item["name"] for item in manifest["cases"]] == [
        case.name for case in cases
    ]
    scale = next(item for item in manifest["cases"] if item["name"] == "scale-2000")
    assert scale["minimum_object_count"] == 2000
    assert Path(scale["source_project"]).is_absolute()
    assert scale["expected_confirmed_edges"] == sorted(scale["expected_confirmed_edges"])
    json.dumps(manifest, allow_nan=False)
```

- [ ] **Step 2: Run the recipe tests and observe the missing module failure**

Run:

```powershell
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pytest -q tests\test_topology_truth.py
```

Expected: FAIL during import because `scripts/topology_truth.py` does not exist.

- [ ] **Step 3: Add immutable recipe records and all six recipes**

Implement these exact public records and entry points in
`scripts/topology_truth.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


Point = tuple[int, int]
Namespace = Literal["electrical", "data"]


@dataclass(frozen=True)
class PortRecipe:
    name: str
    offset: Point
    kind: Namespace
    dimension: int
    required: bool = False
    page: bool = False


@dataclass(frozen=True)
class DefinitionRecipe:
    name: str
    ports: tuple[PortRecipe, ...]
    conductors: tuple["ConductorRecipe", ...] = ()


@dataclass(frozen=True)
class ComponentRecipe:
    object_id: str
    definition: str
    location: Point
    orientation: int = 0
    name: str | None = None
    explicit_ports: tuple[PortRecipe, ...] = ()


@dataclass(frozen=True)
class ConductorRecipe:
    object_id: str
    vertices: tuple[Point, ...]
    namespace: Namespace = "electrical"
    kind: Literal["wire", "bus"] = "wire"


@dataclass(frozen=True)
class LabelRecipe:
    object_id: str
    name: str
    location: Point
    namespace: Namespace
    scope: str = "Main"


@dataclass(frozen=True)
class NetTruth:
    namespace: Namespace
    port_keys: tuple[str, ...]
    conductor_keys: tuple[str, ...]
    label_keys: tuple[str, ...] = ()

    def text(self) -> str:
        return (
            f"{self.namespace}|ports={','.join(sorted(self.port_keys))}"
            f"|conductors={','.join(sorted(self.conductor_keys))}"
            f"|labels={','.join(sorted(self.label_keys))}"
        )


@dataclass(frozen=True)
class CaseRecipe:
    name: str
    healthy: bool
    definitions: tuple[DefinitionRecipe, ...]
    components: tuple[ComponentRecipe, ...]
    conductors: tuple[ConductorRecipe, ...]
    labels: tuple[LabelRecipe, ...]
    nets: tuple[NetTruth, ...]
    expected_error_codes: tuple[str, ...] = ()
    expected_unresolved_codes: tuple[str, ...] = ()
    required_source_capabilities: tuple[tuple[str, bool], ...] = (
        ("live.components", True),
        ("live.conductors", True),
        ("live.labels", True),
        ("live.ports", True),
    )

    @property
    def object_count(self) -> int:
        return len(self.components) + len(self.conductors) + len(self.labels)

    @property
    def project_name(self) -> str:
        return self.name.replace("-", "_")


def _port(
    name: str,
    offset: Point,
    *,
    kind: Namespace = "electrical",
    dimension: int = 1,
    required: bool = False,
    page: bool = False,
) -> PortRecipe:
    return PortRecipe(name, offset, kind, dimension, required, page)


def _net(
    *ports: str,
    conductor: str,
    namespace: Namespace = "electrical",
    labels: tuple[str, ...] = (),
) -> NetTruth:
    return NetTruth(namespace, tuple(ports), (conductor,), labels)


def _scale_case(object_count: int) -> CaseRecipe:
    component_count = object_count // 2
    components = tuple(
        ComponentRecipe(
            str(1_000_000 + index),
            "Link",
            (72 + index * 72, 180),
            name=f"L{index:04d}",
        )
        for index in range(component_count)
    )
    conductors = []
    nets = []
    for index in range(component_count):
        next_index = (index + 1) % component_count
        start = (components[index].location[0] + 18, 180)
        end = (components[next_index].location[0] - 18, 180)
        vertices = (
            (start, end)
            if next_index
            else (start, (start[0], 72), (end[0], 72), end)
        )
        conductor_id = str(2_000_000 + index)
        conductors.append(ConductorRecipe(conductor_id, vertices))
        nets.append(
            _net(
                f"Main:{components[index].object_id}:OUT",
                f"Main:{components[next_index].object_id}:IN",
                conductor=f"Main:{conductor_id}",
            )
        )
    return CaseRecipe(
        name=f"scale-{object_count}",
        healthy=True,
        definitions=(
            DefinitionRecipe(
                "Link",
                (_port("IN", (-18, 0)), _port("OUT", (18, 0))),
            ),
        ),
        components=components,
        conductors=tuple(conductors),
        labels=(),
        nets=tuple(nets),
    )


def case_recipes() -> tuple[CaseRecipe, ...]:
    electrical_pair = (
        _port("A", (-18, 0)),
        _port("B", (18, 0)),
    )
    ordinary = CaseRecipe(
        name="ordinary",
        healthy=True,
        definitions=(),
        components=(
            ComponentRecipe(
                "101", "master:resistor", (72, 72), 0, "R1", electrical_pair
            ),
            ComponentRecipe(
                "102", "master:resistor", (180, 72), 0, "R2", electrical_pair
            ),
        ),
        conductors=(
            ConductorRecipe("201", ((90, 72), (162, 72))),
            ConductorRecipe(
                "202", ((198, 72), (198, 36), (54, 36), (54, 72))
            ),
        ),
        labels=(),
        nets=(
            _net("Main:101:B", "Main:102:A", conductor="Main:201"),
            _net("Main:101:A", "Main:102:B", conductor="Main:202"),
        ),
    )
    seeded = CaseRecipe(
        name="seeded-defects",
        healthy=False,
        definitions=(
            DefinitionRecipe("Dim1", (_port("P", (0, 0)),)),
            DefinitionRecipe("Dim3", (_port("P", (0, 0), dimension=3),)),
            DefinitionRecipe(
                "DataTap", (_port("P", (0, 0), kind="data"),)
            ),
            DefinitionRecipe("ElectricalEnd", (_port("P", (0, 0)),)),
            DefinitionRecipe(
                "RequiredOne", (_port("P", (0, 0), required=True),)
            ),
            DefinitionRecipe("SingleTerminal", (_port("P", (0, 0)),)),
        ),
        components=(
            ComponentRecipe("210", "Dim1", (72, 216)),
            ComponentRecipe("211", "Dim3", (144, 216)),
            ComponentRecipe("310", "DataTap", (108, 360)),
            ComponentRecipe("311", "ElectricalEnd", (72, 360)),
            ComponentRecipe("313", "ElectricalEnd", (144, 360)),
            ComponentRecipe("410", "RequiredOne", (72, 504)),
            ComponentRecipe("510", "SingleTerminal", (72, 648)),
        ),
        conductors=(
            ConductorRecipe("212", ((72, 216), (144, 216))),
            ConductorRecipe("312", ((72, 360), (108, 360), (144, 360))),
            ConductorRecipe("511", ((72, 648), (144, 648))),
        ),
        labels=(
            LabelRecipe("110", "CONFLICT", (72, 72), "electrical"),
            LabelRecipe("111", "CONFLICT", (72, 108), "data"),
        ),
        nets=(
            _net("Main:210:P", "Main:211:P", conductor="Main:212"),
            _net("Main:311:P", "Main:313:P", conductor="Main:312"),
            _net("Main:510:P", conductor="Main:511"),
        ),
        expected_error_codes=(
            "LABEL_CONFLICT",
            "PORT_DIMENSION_MISMATCH",
            "PORT_KIND_MISMATCH",
            "REQUIRED_PORT_UNCONNECTED",
            "WIRE_DANGLING_ENDPOINT",
        ),
    )
    meter_ports = (_port("IN", (-18, 0)), _port("OUT", (18, 0)))
    custom_library = CaseRecipe(
        name="custom-library",
        healthy=True,
        definitions=(DefinitionRecipe("Meter", meter_ports),),
        components=(
            ComponentRecipe("301", "Meter", (72, 72), name="M1"),
            ComponentRecipe("302", "Meter", (180, 72), name="M2"),
        ),
        conductors=(
            ConductorRecipe("601", ((90, 72), (162, 72))),
            ConductorRecipe(
                "602", ((198, 72), (198, 36), (54, 36), (54, 72))
            ),
        ),
        labels=(),
        nets=(
            _net("Main:301:OUT", "Main:302:IN", conductor="Main:601"),
            _net("Main:301:IN", "Main:302:OUT", conductor="Main:602"),
        ),
    )
    hierarchy = CaseRecipe(
        name="hierarchy-uncertain",
        healthy=False,
        definitions=(
            DefinitionRecipe(
                "Child", (_port("IN", (0, 0), required=True, page=True),)
            ),
        ),
        components=(ComponentRecipe("410", "Child", (72, 72)),),
        conductors=(),
        labels=(),
        nets=(),
        expected_unresolved_codes=(
            "hierarchy_boundary_unresolved:Main:410:IN->Main/410:Child:IN",
        ),
    )
    return (
        ordinary,
        seeded,
        custom_library,
        hierarchy,
        _scale_case(500),
        _scale_case(2000),
    )


def manifest_from_recipes(
    cases: tuple[CaseRecipe, ...], sources: dict[str, Path]
) -> dict[str, object]:
    expected_names = {case.name for case in cases}
    if set(sources) != expected_names:
        raise ValueError("source projects do not match recipe names")
    projected_cases = []
    for case in cases:
        source = sources[case.name].resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        projected_cases.append(
            {
                "name": case.name,
                "source_project": str(source),
                "canvas": "Main",
                "healthy": case.healthy,
                "minimum_object_count": case.object_count,
                "expected_confirmed_edges": sorted(
                    net.text() for net in case.nets
                ),
                "expected_error_codes": sorted(case.expected_error_codes),
                "expected_unresolved_codes": sorted(
                    case.expected_unresolved_codes
                ),
                "required_source_capabilities": dict(
                    case.required_source_capabilities
                ),
            }
        )
    return {"schema_version": 1, "cases": projected_cases}
```

`case_recipes()` must encode these identities:

- Ordinary: components `101`, `102`; conductors `201`, `202`; one declared
  electrical net for each conductor and no expected findings.
- Seeded defects: object IDs by zone `110-119`, `210-219`, `310-319`,
  `410-419`, `510-519`; declared nets prevent incidental isolated or dangling
  results; the five exact error occurrences are the sorted tuple shown in the
  test.
- Custom library: definition `Meter` with ports `IN=(-18,0)` and `OUT=(18,0)`,
  components `301`, `302`, and conductors `601`, `602` connecting all ports.
- Hierarchy uncertainty: definition `Child` with required page port `IN`,
  component `410` without the matching outer instance port, and the exact
  unresolved reference shown in the test.
- Scale cases: PSCAD-preservable numeric component IDs start at `1000000`
  and conductor IDs start at `2000000`; the ranges contain 250 entries for
  500 objects and 1,000 entries for 2,000 objects; every
  two-port component `OUT` connects to the next component `IN`, with the last
  conductor routed above the chain back to the first component. The declared
  `NetTruth` records enumerate every ring edge exactly.

- [ ] **Step 4: Run the recipe tests and verify GREEN**

Run the Step 2 command.

Expected: PASS with 3 tests and exact 500/2,000 object counts.

- [ ] **Step 5: Commit the recipe contracts**

```powershell
git add scripts/topology_truth.py tests/test_topology_truth.py
git commit -m "test: define independent topology truth recipes"
```

## Task 2: Structured PSCX Generation And Independent Audit

**Files:**
- Modify: `scripts/topology_truth.py`
- Modify: `tests/test_topology_truth.py`

- [ ] **Step 1: Add failing generation and audit tests**

Append:

```python
import hashlib
import xml.etree.ElementTree as ET


SEED = ROOT / "pscad_mcp" / "assets" / "templates" / "empty_case.pscx"


def test_generation_uses_native_seed_and_audits_every_declared_record(tmp_path):
    cases = topology_truth.case_recipes()
    generated = topology_truth.generate_cases(SEED, tmp_path, cases)
    assert set(generated) == {case.name for case in cases}
    for case in cases:
        path = generated[case.name]
        root = ET.parse(path).getroot()
        assert root.get("name") == case.project_name
        assert path.name == f"{case.name}.pscx"
        audit = topology_truth.audit_case(path, case)
        assert audit["object_count"] == case.object_count
        assert audit["confirmed_edges"] == sorted(net.text() for net in case.nets)
        assert len(audit["sha256"]) == 64


def test_audit_rejects_pscad_normalization_drift(tmp_path):
    case = topology_truth.case_recipes()[0]
    path = topology_truth.generate_cases(SEED, tmp_path, (case,))[case.name]
    root = ET.parse(path)
    wire = next(node for node in root.getroot().iter() if node.get("id") == "201")
    wire.set("id", "999")
    root.write(path, encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="conductor identities"):
        topology_truth.audit_case(path, case)


def test_generation_is_byte_deterministic(tmp_path):
    cases = topology_truth.case_recipes()
    first = topology_truth.generate_cases(SEED, tmp_path / "first", cases)
    second = topology_truth.generate_cases(SEED, tmp_path / "second", cases)
    assert {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in first.items()
    } == {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in second.items()
    }
```

- [ ] **Step 2: Run the new tests and observe missing generation functions**

Run:

```powershell
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pytest -q `
  tests\test_topology_truth.py::test_generation_uses_native_seed_and_audits_every_declared_record `
  tests\test_topology_truth.py::test_audit_rejects_pscad_normalization_drift `
  tests\test_topology_truth.py::test_generation_is_byte_deterministic
```

Expected: FAIL because `generate_cases` and `audit_case` are absent.

- [ ] **Step 3: Implement structured PSCX generation**

Add these entry points:

```python
def generate_cases(
    seed: Path,
    destination: Path,
    cases: tuple[CaseRecipe, ...],
) -> dict[str, Path]:
    if destination.exists():
        raise FileExistsError(f"refusing existing generation directory: {destination}")
    destination.mkdir(parents=True)
    result = {}
    for case in cases:
        case_directory = destination / case.name
        case_directory.mkdir()
        tree = ET.parse(seed)
        root = tree.getroot()
        _rewrite_identity(root, case.project_name)
        _replace_definitions(root, case)
        _replace_main_schematic(root, case)
        _replace_hierarchy(root, case)
        path = case_directory / f"{case.name}.pscx"
        ET.indent(tree, space="  ")
        tree.write(path, encoding="utf-8", xml_declaration=True)
        result[case.name] = path.resolve()
    return result
```

Use native PSCAD elements observed in saved 4.6.2 projects:

- local definition contracts use lowercase `<port>` elements with
  `dim`, `mode`, `type`, offsets, and a true text value;
- instance ports use `<Port classid="Port">` plus their parameter record;
- wires use `<Wire classid="WireOrthogonal">` and relative vertices;
- labels use their real `NodeLabel` or `DataLabel` class ID;
- `required="true"` is added only to the dedicated required-port contract so
  the licensed semantic probe can determine whether PSCAD preserves it.

Every XML mutation uses `ElementTree` creation and attribute APIs. Sort
definitions and schematic records by declared identity before serialization.

- [ ] **Step 4: Implement the standalone normalized-file auditor**

Add:

```python
def audit_case(path: Path, case: CaseRecipe) -> dict[str, object]:
    payload = path.read_bytes()
    root = ET.fromstring(payload)
    if root.get("name") != case.project_name:
        raise ValueError(f"project identity changed for {case.name}")
    observed_components = _audit_components(root, case)
    observed_conductors = _audit_conductors(root, case)
    observed_labels = _audit_labels(root, case)
    _audit_definitions(root, case)
    if observed_components != {item.object_id for item in case.components}:
        raise ValueError(f"component identities changed for {case.name}")
    if observed_conductors != {item.object_id for item in case.conductors}:
        raise ValueError(f"conductor identities changed for {case.name}")
    if observed_labels != {item.object_id for item in case.labels}:
        raise ValueError(f"label identities changed for {case.name}")
    return {
        "name": case.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "object_count": case.object_count,
        "confirmed_edges": sorted(net.text() for net in case.nets),
        "expected_error_codes": list(case.expected_error_codes),
        "expected_unresolved_codes": list(case.expected_unresolved_codes),
    }
```

The `_audit_*` helpers compare exact definition, orientation, location, port
offset, dimension, namespace, required flag, conductor kind/vertices, label
name/namespace/scope, and hierarchy parent-child records. They must reject
extra and missing records, not only count mismatches.

- [ ] **Step 5: Run the complete truth module suite**

Run:

```powershell
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pytest -q tests\test_topology_truth.py
```

Expected: PASS with deterministic generated bytes, exact audit, and no topology
implementation imports.

- [ ] **Step 6: Commit generation and audit**

```powershell
git add scripts/topology_truth.py tests/test_topology_truth.py
git commit -m "test: generate audited topology acceptance projects"
```

## Task 3: Licensed PSCAD Normalization Boundary And Semantic Probe

**Files:**
- Create: `scripts/normalize_topology_truth.py`
- Create: `tests/test_topology_truth_normalization.py`
- Modify: `scripts/topology_truth.py`
- Modify: `tests/test_topology_truth.py`

- [ ] **Step 1: Write failing normalization-boundary tests**

```python
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from scripts.normalize_topology_truth import normalize_projects


@pytest.mark.asyncio
async def test_normalizer_uses_only_load_save_list_and_disconnect(tmp_path):
    projects = tuple(tmp_path / f"case-{index}.pscx" for index in range(2))
    for path in projects:
        path.write_text(f'<project name="{path.stem}"/>', encoding="utf-8")
    backend = AsyncMock()
    backend.attach.return_value = type(
        "Info", (), {"alive": True, "licensed": True, "owns_process": True}
    )()
    backend.list_projects.return_value = [
        type("Project", (), {"name": path.stem})() for path in projects
    ]

    result = await normalize_projects(projects, backend)

    assert result == projects
    backend.attach.assert_awaited_once()
    backend.load_projects.assert_awaited_once_with([str(path) for path in projects])
    assert backend.save_project.await_count == len(projects)
    backend.quit.assert_awaited_once()
    backend.disconnect.assert_awaited_once()
    assert not backend.method_calls or {
        call[0] for call in backend.method_calls
    } <= {
        "attach", "load_projects", "list_projects", "save_project", "quit", "disconnect"
    }


@pytest.mark.asyncio
async def test_normalizer_disconnects_when_save_fails(tmp_path):
    project = tmp_path / "case.pscx"
    project.write_text('<project name="case"/>', encoding="utf-8")
    backend = AsyncMock()
    backend.attach.return_value = type(
        "Info", (), {"alive": True, "licensed": True, "owns_process": True}
    )()
    backend.list_projects.return_value = [type("Project", (), {"name": "case"})()]
    backend.save_project.side_effect = RuntimeError("save failed")

    with pytest.raises(RuntimeError, match="save failed"):
        await normalize_projects((project,), backend)

    backend.quit.assert_awaited_once()
    backend.disconnect.assert_awaited_once()
```

- [ ] **Step 2: Run the tests and observe the missing normalizer failure**

Run:

```powershell
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pytest -q tests\test_topology_truth_normalization.py
```

Expected: FAIL during collection for missing `scripts.normalize_topology_truth`.

- [ ] **Step 3: Implement normalization with explicit backend injection**

Create:

```python
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.executor import robust_executor


async def normalize_projects(
    projects: tuple[Path, ...], backend: Any
) -> tuple[Path, ...]:
    info = await backend.attach()
    if not info.alive or not info.licensed or not info.owns_process:
        raise RuntimeError("normalization requires an owned licensed PSCAD process")
    try:
        await backend.load_projects([str(path) for path in projects])
        loaded = {item.name for item in await backend.list_projects()}
        missing = sorted(path.stem for path in projects if path.stem not in loaded)
        if missing:
            raise RuntimeError(f"PSCAD did not load generated projects: {missing}")
        for path in projects:
            await backend.save_project(path.stem)
        return projects
    finally:
        try:
            if backend.owns_process:
                await backend.quit()
        finally:
            await backend.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects-json", type=Path, required=True)
    parser.add_argument("--version", default="4.6.2")
    parser.add_argument("--x64", action="store_true")
    arguments = parser.parse_args()
    projects = tuple(
        Path(value).resolve()
        for value in json.loads(arguments.projects_json.read_text(encoding="utf-8"))
    )
    backend = LegacyBackend(
        robust_executor, version=arguments.version, x64=arguments.x64
    )
    asyncio.run(normalize_projects(projects, backend))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add a semantic probe projection and test**

Add `semantic_probe(case_path, recipe)` to `scripts/topology_truth.py`. It
audits the PSCAD-saved XML and emits exactly:

```python
{
    "required_port_preserved": True,
    "electrical_namespace_preserved": True,
    "data_namespace_preserved": True,
    "dimensions_preserved": [1, 3],
    "label_namespaces_preserved": ["data", "electrical"],
    "hierarchy_boundary_preserved": True,
}
```

Write a test that removes each evidence attribute or node in turn and expects
the corresponding value to become false rather than being guessed.

- [ ] **Step 5: Run non-licensed normalization tests**

Run:

```powershell
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pytest -q `
  tests\test_topology_truth.py `
  tests\test_topology_truth_normalization.py
```

Expected: PASS.

- [ ] **Step 6: Commit the normalization boundary**

```powershell
git add scripts/topology_truth.py scripts/normalize_topology_truth.py tests/test_topology_truth.py tests/test_topology_truth_normalization.py
git commit -m "test: normalize topology truth with owned PSCAD"
```

- [ ] **Step 7: Run the licensed semantic probe before full generation**

Generate only `seeded-defects`, `custom-library`, and
`hierarchy-uncertain` into a timestamped probe directory, normalize them, and
run `semantic_probe`.

Run:

```powershell
$probeStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$probeRoot = Join-Path 'D:\PSCAD-Workspace' "topology-probe-$probeStamp"
& .\.venv\Scripts\python.exe scripts\topology_truth.py build `
  --seed pscad_mcp\assets\templates\empty_case.pscx `
  --destination $probeRoot `
  --cases seeded-defects,custom-library,hierarchy-uncertain
& .\.venv\Scripts\python.exe scripts\normalize_topology_truth.py `
  --projects-json (Join-Path $probeRoot 'projects.json') `
  --version 4.6.2 --x64
& .\.venv\Scripts\python.exe scripts\topology_truth.py probe `
  --directory $probeRoot
```

Expected: all six semantic probe fields are true, PSCAD exits, and each
normalized project reopens. If any field is false, stop here, preserve the
probe directory as `INCOMPLETE` evidence, and revise the fixture design before
creating final sources.

## Task 4: Guarded Preparation Runner And Atomic Publication

**Files:**
- Create: `scripts/prepare_topology_truth.ps1`
- Create: `tests/test_topology_truth_runner.py`
- Modify: `scripts/topology_truth.py`
- Modify: `tests/test_topology_truth.py`

- [ ] **Step 1: Write failing publication and runner guard tests**

```python
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "scripts" / "prepare_topology_truth.ps1"


def test_runner_declares_isolated_paths_and_only_owned_process_cleanup():
    text = RUNNER.read_text(encoding="utf-8")
    assert "topology-sources" in text
    assert "topology-truth.json" in text
    assert "Get-Process" in text
    assert "PSCAD*" in text
    assert "Stop-Process" not in text
    assert "normalize_topology_truth.py" in text
    assert "topology_truth.py" in text


def test_atomic_publication_refuses_existing_destinations(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    sources = tmp_path / "topology-sources"
    sources.mkdir()
    with pytest.raises(FileExistsError, match="topology-sources"):
        topology_truth.publish_truth_set(
            staging, sources, tmp_path / "topology-truth.json"
        )


def test_failed_audit_publishes_nothing(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    sources = tmp_path / "topology-sources"
    manifest = tmp_path / "topology-truth.json"
    monkeypatch.setattr(
        topology_truth, "audit_generated_set", lambda *_: (_ for _ in ()).throw(ValueError("drift"))
    )
    with pytest.raises(ValueError, match="drift"):
        topology_truth.publish_truth_set(staging, sources, manifest)
    assert not sources.exists()
    assert not manifest.exists()
```

- [ ] **Step 2: Run the tests and observe missing runner/publication failures**

Run:

```powershell
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pytest -q `
  tests\test_topology_truth_runner.py `
  tests\test_topology_truth.py::test_atomic_publication_refuses_existing_destinations `
  tests\test_topology_truth.py::test_failed_audit_publishes_nothing
```

Expected: FAIL because the runner and `publish_truth_set` are absent.

- [ ] **Step 3: Implement atomic publication**

`publish_truth_set(staging, source_destination, manifest_destination)` must:

1. Resolve all three absolute paths.
2. Reject existing source or manifest destinations.
3. Run `audit_generated_set` and `manifest_from_recipes` before creating a
   final destination.
4. Copy audited files to sibling temporary paths.
5. Write `construction-record.json`, `preparation-report.json`, and the
   manifest with UTF-8, sorted keys, `allow_nan=False`, and trailing newline.
6. Publish the source directory with a single directory rename and the
   manifest with `Path.replace`.
7. If manifest publication fails after source publication, rename the source
   directory back to the temporary sibling and remove it so neither final path
   remains.

- [ ] **Step 4: Implement the PowerShell preparation runner**

The runner parameters are:

```powershell
[CmdletBinding()]
param(
    [string]$SourceRoot = 'D:\PSCAD-Workspace\topology-sources',
    [string]$Manifest = 'D:\PSCAD-Workspace\topology-truth.json',
    [string]$Version = '4.6.2',
    [switch]$X64
)
```

It must validate the repository Python, reject non-4.6.2 versions, reject
existing final paths, reject any open PSCAD process, create a timestamped
staging directory with `New-Item`, run build, normalization, probe, audit, and
publish in that order, collect printed `ACCEPTANCE_PID` values, verify only
those PIDs exited, and print final source/manifest hashes. It must never call
`Stop-Process` or delete a pre-existing directory.

- [ ] **Step 5: Run all preparation contract tests and parse PowerShell**

Run:

```powershell
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pytest -q `
  tests\test_topology_truth.py `
  tests\test_topology_truth_normalization.py `
  tests\test_topology_truth_runner.py
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path 'scripts\prepare_topology_truth.ps1'),
  [ref]$null,
  [ref]$errors
) | Out-Null
if ($errors.Count -gt 0) { $errors | ForEach-Object Message; exit 1 }
```

Expected: all tests PASS and the parser reports no errors.

- [ ] **Step 6: Commit preparation automation**

```powershell
git add scripts/topology_truth.py scripts/prepare_topology_truth.ps1 tests/test_topology_truth.py tests/test_topology_truth_runner.py
git commit -m "test: prepare topology acceptance truth safely"
```

## Task 5: Create And Review The Licensed Source Set

**Files:**
- Generate externally: `D:\PSCAD-Workspace\topology-sources`
- Generate externally: `D:\PSCAD-Workspace\topology-truth.json`

- [ ] **Step 1: Re-run all non-licensed preparation tests**

Run the Task 4 Step 5 pytest command.

Expected: PASS with zero failures.

- [ ] **Step 2: Verify no PSCAD process is already open**

Run:

```powershell
$existing = @(Get-Process -ErrorAction SilentlyContinue |
  Where-Object { $_.ProcessName -like 'PSCAD*' })
if ($existing.Count -gt 0) { throw "Close PSCAD before truth preparation." }
```

Expected: no process output and no exception.

- [ ] **Step 3: Run the licensed preparation command**

```powershell
& .\scripts\prepare_topology_truth.ps1 `
  -SourceRoot 'D:\PSCAD-Workspace\topology-sources' `
  -Manifest 'D:\PSCAD-Workspace\topology-truth.json' `
  -Version '4.6.2' -X64
```

Expected: all six projects load, save, and reopen; semantic probe fields are
true; final source and manifest hashes are printed; owned PSCAD process count
is zero.

- [ ] **Step 4: Produce the immutable human review summary**

Run:

```powershell
& .\.venv\Scripts\python.exe scripts\topology_truth.py review `
  --sources 'D:\PSCAD-Workspace\topology-sources' `
  --manifest 'D:\PSCAD-Workspace\topology-truth.json'
```

The output must list, for all six cases, the source SHA-256, object count,
complete confirmed-net membership, every seeded error occurrence, unresolved
references, required capabilities, semantic probe result, PSCAD version, and
owned process evidence. Save the same content as
`D:\PSCAD-Workspace\topology-sources\truth-review.json` without changing the
already published manifest.

- [ ] **Step 5: Pause for explicit user approval**

Present `truth-review.json` and its SHA-256. Do not run topology acceptance
until the user explicitly approves this truth set.

## Task 6: Resume Task 12 Licensed Gate

**Files:**
- Existing uncommitted: `tests/test_topology_real_acceptance.py`
- Existing uncommitted: `scripts/run_topology_acceptance.ps1`
- Existing uncommitted: `README.md`
- Existing uncommitted: `docs/zh-CN/README.md`
- Modify after PASS: `docs/acceptance-status.json`
- Modify after PASS: `tests/test_acceptance_status_manifest.py`

- [ ] **Step 1: Run the complete Phase 1 non-licensed suite**

Run the exact Task 12 Phase 1 command from
`2026-08-27-unified-topology-diagnostics.md`.

Expected: PASS with zero failures and 85 registered tools.

- [ ] **Step 2: Run licensed topology acceptance**

```powershell
& .\scripts\run_topology_acceptance.ps1 `
  -Workspace 'D:\PSCAD-Workspace\topology-acceptance' `
  -Manifest 'D:\PSCAD-Workspace\topology-truth.json' `
  -Version '4.6.2' -X64
```

Expected: `TOPOLOGY_ACCEPTANCE_COMPLETE=PASS`, zero owned PSCAD processes,
unchanged project and inventory hashes, exact net/error/unresolved truth, and
performance within 3,000/10,000 ms.

- [ ] **Step 3: Record current-commit PASS evidence**

Add `unified_topology_462` to `docs/acceptance-status.json` with the exact
implementation commit, immutable report path, report SHA-256, version 4.6.2,
and `licensed_status: PASS`. Add the scope to the exact set in
`tests/test_acceptance_status_manifest.py` and assert the evidence commit and
64-character report hash.

- [ ] **Step 4: Run acceptance status and documentation tests**

```powershell
$env:PYTHONPATH = "$PWD\tests"
& .\.venv\Scripts\python.exe -m pytest -q `
  tests\test_acceptance_status_manifest.py `
  tests\test_config_example.py `
  tests\test_delivery_hardening.py
git diff --check
```

Expected: PASS and no whitespace errors.

- [ ] **Step 5: Commit the completed Phase 1 gate**

```powershell
git add tests/test_topology_real_acceptance.py tests/test_acceptance_status_manifest.py scripts/run_topology_acceptance.ps1 README.md docs/zh-CN/README.md docs/acceptance-status.json
git commit -m "test: accept read-only topology inspection on 4.6.2"
```

## Completion Checkpoint

- [ ] Six PSCAD-normalized source projects exist outside the acceptance run workspace.
- [ ] The truth builder and auditor contain no topology implementation imports.
- [ ] `required`, namespace, dimension, label, and hierarchy semantics survive licensed normalization.
- [ ] The user approved the immutable `truth-review.json` and hash.
- [ ] The current implementation commit has a validated licensed `PASS` report.
- [ ] `docs/acceptance-status.json` points to that exact report and commit.
- [ ] Phase 2 remains untouched until every checkpoint above passes.
