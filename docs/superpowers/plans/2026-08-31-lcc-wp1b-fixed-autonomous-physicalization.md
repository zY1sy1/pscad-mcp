# LCC WP1B Fixed Autonomous Physicalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the structural fixed LCC companion with a licensed-loadable PSCAD 4.6.2 Master composition and promote a current-commit no-fault `lcc.fixed_autonomous -> simulated/PASS` smoke report.

**Architecture:** Extend the existing Master registry with a separately audited companion section, author a real repository-owned PSLX containing two `g6p200` bridges and minimal closed-loop controls, and migrate the fixed blueprint from `GATES[12]` to scalar `AO_Y/AO_D` paths. Preserve the fixed builder lifecycle while adding an immutable `wp1b_smoke` verification profile, a pure smoke evaluator, isolated component gates, and separate report/promotion orchestration.

**Tech Stack:** Python 3.10+, dataclasses, `xml.etree.ElementTree`, JSON/SHA-256, asyncio, existing PSCAD 4.6.2 Legacy backend and `PscadService`, pytest, Ruff, PowerShell.

---

## Execution Preconditions

- Start implementation from commit `fbcf641` or a descendant containing the approved design spec.
- At execution time, use `superpowers:using-git-worktrees` to create an isolated `codex/` worktree.
- Record `git rev-parse HEAD`, `git branch --show-current`, `git status --short`, installed Master SHA-256, compiler identities, and PSCAD process inventory before the first production edit.
- Never edit installed `master.pslx`, the official CIGRE project, a user project, or an existing acceptance workspace.
- Use the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff
```

## Scope Boundaries

This plan implements WP1B only. It must not:

- retain `GATES`, `FPN`, `FDT`, or `fp_int` in the fixed companion contract;
- copy a vendor `Definition`, form, SVG, schematic, or script body;
- introduce VDCOL, current-margin coordination, power reversal, mode switching, or a fault schedule;
- use `acceptance.json` or placeholder `golden.json` to decide the smoke verdict;
- promote disturbance, commutation-failure, independent-golden, MMC, parametric LCC, or final `accepted` scope;
- terminate PSCAD processes by wildcard or delete licensed failure evidence;
- mutate the checked-in program baseline during the `run` action.

## File Map

### Core and asset contracts

- Modify `pscad_mcp/core/master_bindings.py`: schema-v2 `companion_bindings`, parsing, canonical hash, and live companion audit.
- Modify `pscad_mcp/hvdc/builders/lcc/assets.py`: load and expose `smoke.json`.
- Modify `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json`: add companion bindings, preserve all eight project physical identities/shapes, and extend only the DC-meter signal-name mapping.
- Create `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/smoke.json`: WP1B-only channel/time/enable/AO contract.
- Modify `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json`: cover every changed/new asset.

### Physical companion and topology

- Create `pscad_mcp/hvdc/builders/lcc/companion.py`: physical PSLX audit and forbidden-copy/path checks.
- Create `scripts/build_lcc_companion_library.py`: deterministic repository-authored PSCAD 4.6.2 library renderer.
- Replace `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/library/cigre_lcc_v1.pslx`: generated physical library.
- Modify `scripts/audit_lcc_assets.py`: delegate physical checks and report twelve effective valves from two audited bridges.
- Modify `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/catalog-pscad-4.6.2.json`: scalar AO/control/signal contracts.
- Modify `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json`: two transformer groups per terminal, four AO nets, feedback, enable, and smoke outputs.
- Modify `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/PROVENANCE.md`: physical composition and non-copy ledger.
- Modify `pscad_mcp/hvdc/builders/lcc/validator.py`: remove structural valve/gate checks and delegate companion validation.

### Planning, execution, and evidence

- Modify `pscad_mcp/hvdc/builders/lcc/models.py`: `SMOKE_PASSED` state and verification profile.
- Modify `pscad_mcp/hvdc/builders/lcc/planner.py`: profile-aware duration, operations, and plan hash.
- Modify `pscad_mcp/hvdc/builders/lcc/service.py`: explicit profile argument with unchanged default.
- Create `pscad_mcp/hvdc/builders/lcc/smoke.py`: pure smoke contract evaluator.
- Modify `pscad_mcp/hvdc/builders/lcc/executor.py`: smoke operation and fail-closed transition.
- Create `pscad_mcp/hvdc/builders/lcc/companion_gate.py`: isolated Definition fixtures.
- Create `pscad_mcp/hvdc/builders/lcc/fixed_acceptance.py`: strict report, orchestration, file revalidation, and promotion.
- Create `pscad_mcp/hvdc/builders/lcc/fixed_acceptance_cli.py`: explicit `run` and `promote`.
- Create `scripts/run_fixed_lcc_smoke_acceptance.ps1`: clean-commit run-only wrapper.

### Tests and completion evidence

- Modify `tests/test_master_binding_registry.py` and `tests/test_master_definition_bindings.py`.
- Modify `tests/test_lcc_assets.py`, `tests/test_lcc_asset_audit.py`, `tests/test_lcc_catalog.py`, and `tests/test_lcc_planner.py`.
- Modify `tests/test_lcc_validator.py`, `tests/test_lcc_executor.py`, and `tests/test_lcc_real_acceptance.py`.
- Create `tests/test_lcc_companion.py`, `tests/test_lcc_smoke.py`, `tests/test_lcc_companion_gate.py`, `tests/test_lcc_fixed_acceptance.py`, `tests/test_lcc_fixed_acceptance_cli.py`, and `tests/test_lcc_fixed_acceptance_real.py`.
- Modify `tests/test_lcc_mmc_program_baseline.py` and `docs/acceptance/lcc-mmc-program-baseline.json` only after explicit promotion.
- Modify README files, roadmap, and add a WP1B completion record only after all licensed gates pass.

## Shared Identities

Use these exact values throughout:

```python
FULL_ACCEPTANCE_PROFILE = "full_acceptance"
WP1B_SMOKE_PROFILE = "wp1b_smoke"

FIXED_SCOPE = "lcc.fixed_autonomous"
FIXED_BUILDER_PATH = "lcc.fixed_autonomous"
FIXED_KIND = "licensed_simulation"
FIXED_CAPABILITY = "simulated"
FIXED_OWNER = "WP1"
FIXED_EXCLUSIONS = (
    "disturbance_acceptance",
    "commutation_failure_acceptance",
    "independent_golden",
    "final_accepted",
)

SMOKE_DURATION_S = 0.1
SMOKE_TIME_STEP_S = 0.00005
SMOKE_OUTPUT_STEP_S = 0.00005

BRIDGE_PORTS = (
    "ACY_A", "ACY_B", "ACY_C",
    "ACD_A", "ACD_B", "ACD_C",
    "DC_POS", "DC_NEG",
    "AO_Y", "AO_D", "ENABLE",
    "AM_Y", "AM_D", "GM_Y", "GM_D",
)
RECTIFIER_CONTROL_PORTS = (
    "VDC", "IDC", "IORDER", "ENABLE", "AO_Y", "AO_D", "ALPHA",
)
INVERTER_CONTROL_PORTS = (
    "VDC", "IDC", "GM_Y", "GM_D", "GAMMA_ORDER", "ENABLE",
    "AO_Y", "AO_D", "GAMMA",
)
```

## Phase A: Physical Companion Foundation

### Task 1: Add Companion Master Registry Schema and Live Audit

**Files:**
- Modify: `pscad_mcp/core/master_bindings.py`
- Modify: `tests/test_master_binding_registry.py`
- Modify: `tests/test_master_definition_bindings.py`

- [ ] **Step 1: Write failing schema-v2 tests**

Add to `tests/test_master_binding_registry.py`:

```python
def test_schema_v2_keeps_project_and_companion_bindings_separate():
    payload = _registry_payload()
    payload["schema_version"] = 2
    payload["companion_bindings"] = [
        {
            "logical_name": "master:six_pulse_bridge",
            "physical_definition": "g6p200",
            "shape": {"kind": "direct"},
            "ports": [
                {
                    "logical": "AO",
                    "physical": "AO",
                    "kind": "data",
                    "dimension": 1,
                    "occurrence": 1,
                }
            ],
            "parameters": [],
            "fixed_parameters": [
                {
                    "physical": "FP",
                    "value": 0,
                    "contract": {
                        "type": "Choice",
                        "unit": None,
                        "choices": ["0", "1", "2", "3"],
                    },
                }
            ],
            "evidence_parameters": [],
        }
    ]

    registry = parse_master_binding_registry(payload)

    assert len(registry.bindings) == len(payload["bindings"])
    assert registry.companion_by_logical_name[
        "master:six_pulse_bridge"
    ].physical_definition == "g6p200"
    assert registry.to_dict()["companion_bindings"] == payload["companion_bindings"]


def test_schema_v1_has_no_companion_bindings():
    registry = parse_master_binding_registry(_registry_payload())

    assert registry.schema_version == 1
    assert registry.companion_bindings == ()
    assert "companion_bindings" not in registry.to_dict()


def test_companion_logical_names_must_be_unique_and_disjoint():
    payload = _registry_payload()
    payload["schema_version"] = 2
    payload["companion_bindings"] = [copy.deepcopy(payload["bindings"][0])]

    with pytest.raises(BackendError) as failure:
        parse_master_binding_registry(payload)

    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"
```

- [ ] **Step 2: Run the schema tests and verify the expected failures**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_master_binding_registry.py -k "schema_v2 or schema_v1_has or companion_logical" -q
```

Expected: FAIL because schema version 2 and `companion_bindings` are not implemented.

- [ ] **Step 3: Implement schema-v2 parsing without changing schema-v1 serialization**

In `master_bindings.py` add:

```python
_TOP_LEVEL_FIELDS_V1 = {"schema_version", "name", "pscad_version", "bindings"}
_TOP_LEVEL_FIELDS_V2 = {
    "schema_version",
    "name",
    "pscad_version",
    "bindings",
    "companion_bindings",
}


@dataclass(frozen=True)
class MasterBindingRegistry:
    schema_version: int
    name: str
    pscad_version: str
    bindings: tuple[MasterBinding, ...]
    sha256: str
    companion_bindings: tuple[MasterBinding, ...] = ()

    @property
    def by_logical_name(self) -> dict[str, MasterBinding]:
        return {item.logical_name: item for item in self.bindings}

    @property
    def companion_by_logical_name(self) -> dict[str, MasterBinding]:
        return {item.logical_name: item for item in self.companion_bindings}

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "name": self.name,
            "pscad_version": self.pscad_version,
            "bindings": [item.to_dict() for item in self.bindings],
        }
        if self.schema_version == 2:
            result["companion_bindings"] = [
                item.to_dict() for item in self.companion_bindings
            ]
        return result
```

Refactor `_parse_binding()` to accept `field_prefix: str = "bindings"`. In `parse_master_binding_registry()` use:

```python
schema_version = record.get("schema_version")
if isinstance(schema_version, bool) or schema_version not in {1, 2}:
    raise _error(
        "MASTER_BINDING_MISSING",
        "The Master binding registry schema version must be 1 or 2.",
        field="schema_version",
        observed=schema_version,
    )
_exact_fields(
    record,
    _TOP_LEVEL_FIELDS_V1 if schema_version == 1 else _TOP_LEVEL_FIELDS_V2,
    "registry",
)
bindings = tuple(
    _parse_binding(item, index)
    for index, item in enumerate(_sequence(record["bindings"], "bindings"))
)
companion_bindings = tuple(
    _parse_binding(item, index, field_prefix="companion_bindings")
    for index, item in enumerate(
        _sequence(record.get("companion_bindings", ()), "companion_bindings")
    )
)
all_names = [item.logical_name for item in (*bindings, *companion_bindings)]
if len(all_names) != len(set(all_names)):
    raise _error(
        "MASTER_BINDING_AMBIGUOUS",
        "Project and companion logical names must be globally unique.",
        field="bindings.logical_name",
    )
normalized = {
    "schema_version": schema_version,
    "name": _text(record["name"], "name"),
    "pscad_version": _text(record["pscad_version"], "pscad_version"),
    "bindings": [item.to_dict() for item in bindings],
}
if schema_version == 2:
    normalized["companion_bindings"] = [
        item.to_dict() for item in companion_bindings
    ]
canonical = json.dumps(
    normalized,
    ensure_ascii=True,
    sort_keys=True,
    separators=(",", ":"),
).encode("ascii")
return MasterBindingRegistry(
    schema_version=schema_version,
    name=normalized["name"],
    pscad_version=normalized["pscad_version"],
    bindings=bindings,
    companion_bindings=companion_bindings,
    sha256=hashlib.sha256(canonical).hexdigest(),
)
```

- [ ] **Step 4: Write a failing live-audit test for the FP=0 AO occurrence**

Add to `tests/test_master_definition_bindings.py`:

```python
def test_companion_audit_selects_fp0_view1_ao_and_not_fpn(tmp_path):
    master = _write_g6p200_master_fixture(tmp_path)
    registry = _companion_registry_with_g6p200()

    audited = audit_companion_bindings(master, registry)

    bridge = audited.definitions["master:six_pulse_bridge"]
    ao = bridge["selected_ports"]["AO"]
    assert ao["dimension"] == 1
    assert "FP==0" in ao["condition"]
    assert "View==1" in ao["condition"]
    assert "FPN" not in bridge["selected_ports"]
    assert "FDT" not in bridge["selected_ports"]
    assert bridge["selected_ports"]["DP_RECT"]["occurrence"] == 2
    assert bridge["selected_ports"]["DN_RECT"]["occurrence"] == 3
    assert bridge["selected_ports"]["DP_INV"]["occurrence"] == 3
    assert bridge["selected_ports"]["DN_INV"]["occurrence"] == 2
```

The fixture must contain both View=0 and View=1 occurrences of `AO` plus conditional `FPN/FDT` ports, matching installed metadata conditions.

- [ ] **Step 5: Run the audit test and verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_master_definition_bindings.py::test_companion_audit_selects_fp0_view1_ao_and_not_fpn -q
```

Expected: FAIL because `audit_companion_bindings` is undefined.

- [ ] **Step 6: Implement separate companion audit evidence**

Add:

```python
@dataclass(frozen=True)
class AuditedCompanionRegistry:
    registry: MasterBindingRegistry
    master_path: str
    master_sha256: str
    definitions: Mapping[str, Mapping[str, Any]]


def audit_companion_bindings(
    master_path: str | Path,
    registry: MasterBindingRegistry,
) -> AuditedCompanionRegistry:
    if not registry.companion_bindings:
        raise _runtime_error(
            "MASTER_BINDING_MISSING",
            "The registry has no companion bindings.",
            "audit_companion_bindings",
        )
    path, source_hash, metadata_document = _read_master_metadata(master_path)
    definitions = _audit_binding_collection(
        path,
        metadata_document,
        registry.companion_bindings,
        operation="audit_companion_bindings",
    )
    bridge = definitions.get("master:six_pulse_bridge")
    if not isinstance(bridge, Mapping):
        raise _runtime_error(
            "MASTER_BINDING_MISSING",
            "The six-pulse bridge companion binding is absent.",
            "audit_companion_bindings",
        )
    selected = bridge["selected_ports"]
    if "FPN" in selected or "FDT" in selected:
        raise _runtime_error(
            "MASTER_PORT_MISMATCH",
            "FP=0 must not select external firing-vector ports.",
            "audit_companion_bindings",
        )
    expected_profiles = {
        "DP_RECT": (2, "(UP)&&(View==1)"),
        "DN_RECT": (3, "(UP)&&(View==1)"),
        "DP_INV": (3, "!(UP)&&(View==1)"),
        "DN_INV": (2, "!(UP)&&(View==1)"),
    }
    for logical_name, (occurrence, condition) in expected_profiles.items():
        observed = selected.get(logical_name)
        if (
            not isinstance(observed, Mapping)
            or observed.get("occurrence") != occurrence
            or observed.get("condition") != condition
        ):
            raise _runtime_error(
                "MASTER_PORT_MISMATCH",
                "The g6p200 DC terminal profile is not exact.",
                "audit_companion_bindings",
                logical_port=logical_name,
                expected_occurrence=occurrence,
                expected_condition=condition,
                observed=observed,
            )
    return AuditedCompanionRegistry(
        registry=registry,
        master_path=str(path),
        master_sha256=source_hash,
        definitions=_freeze(definitions),
    )
```

Extract the existing source reader and per-binding loop into `_read_master_metadata()` and `_audit_binding_collection()`. Keep `audit_master_bindings()` behavior unchanged by passing only `registry.bindings`.

- [ ] **Step 7: Run Master binding regression and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_master_binding_registry.py tests/test_master_definition_bindings.py tests/test_master_binding_real_acceptance.py -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/core/master_bindings.py tests/test_master_binding_registry.py tests/test_master_definition_bindings.py
git add pscad_mcp/core/master_bindings.py tests/test_master_binding_registry.py tests/test_master_definition_bindings.py
git commit -m "feat: audit LCC companion Master bindings"
```

### Task 2: Add a Focused Physical Companion Auditor

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/companion.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/validator.py`
- Create: `tests/test_lcc_companion.py`
- Modify: `tests/test_lcc_validator.py`

- [ ] **Step 1: Write failing physical-library tests**

Create `tests/test_lcc_companion.py`:

```python
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.companion import audit_companion_library


def test_structural_contract_is_not_a_physical_library(tmp_path):
    path = tmp_path / "structural.pslx"
    path.write_text(
        """<pslx><definitions>
<definition name="cigre_lcc_v1:LCC12PulseBridge">
  <six_pulse_group name="upper" />
  <valve id="V01" definition="master:thyristor_valve" />
</definition>
</definitions></pslx>""",
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as failure:
        audit_companion_library(path)

    assert failure.value.code == "LCC_COMPANION_INVALID"
    assert "structural_only" in {
        item["reason"] for item in failure.value.details["errors"]
    }


def test_physical_bridge_requires_two_g6p200_and_scalar_ao(tmp_path):
    path = write_physical_library_fixture(tmp_path)

    evidence = audit_companion_library(path)

    bridge = evidence["definitions"]["cigre_lcc_v1:LCC12PulseBridge"]
    assert bridge["master_instances"] == {"master:g6p200": 2}
    assert bridge["ports"]["AO_Y"]["dimension"] == 1
    assert bridge["ports"]["AO_D"]["dimension"] == 1
    assert "GATES" not in bridge["ports"]
    assert evidence["effective_valves"] == 12


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("remove_second_bridge", "master_instance_count"),
        ("add_gates_port", "external_port_mismatch"),
        ("remove_ao_wire", "internal_connection_missing"),
        ("copy_master_definition", "vendor_definition_body"),
        ("add_absolute_path", "absolute_path"),
        ("add_foreign_scope", "foreign_scope"),
    ],
)
def test_physical_audit_fails_closed(tmp_path, mutation, reason):
    path = write_physical_library_fixture(tmp_path, mutation=mutation)

    with pytest.raises(BackendError) as failure:
        audit_companion_library(path)

    assert reason in {
        item["reason"] for item in failure.value.details["errors"]
    }
```

Define the fixture helpers exactly:

```python
PHYSICAL_PORTS = {
    "LCC12PulseBridge": (
        "ACY_A", "ACY_B", "ACY_C", "ACD_A", "ACD_B", "ACD_C",
        "DC_POS", "DC_NEG", "AO_Y", "AO_D", "ENABLE",
        "AM_Y", "AM_D", "GM_Y", "GM_D",
    ),
    "RectifierControl": (
        "VDC", "IDC", "IORDER", "ENABLE",
        "AO_Y", "AO_D", "ALPHA",
    ),
    "InverterControl": (
        "VDC", "IDC", "GM_Y", "GM_D", "GAMMA_ORDER", "ENABLE",
        "AO_Y", "AO_D", "GAMMA",
    ),
    "Initialization": (
        "IORDER", "GAMMA_ORDER", "ENABLE_RECT", "ENABLE_INV",
    ),
    "SignalInterface": ("VDC_RECT", "VDC_INV", "IDC"),
}
PHYSICAL_USERS = {
    "LCC12PulseBridge": ("master:g6p200", "master:g6p200"),
    "RectifierControl": (
        "master:sumjct", "master:mult", "master:pi_ctlr",
        "master:hardlimit",
    ),
    "InverterControl": (
        "master:maxmin", "master:sumjct", "master:mult",
        "master:pi_ctlr", "master:hardlimit",
    ),
    "Initialization": (
        "master:const", "master:const",
        "master:consti", "master:consti",
    ),
    "SignalInterface": (
        "master:import", "master:import", "master:import",
    ),
}
PHYSICAL_WIRES = {
    "LCC12PulseBridge": (
        "ACY_TO_Y", "ACD_TO_D", "DC_SERIES",
        "AO_Y_TO_BRIDGE_Y", "AO_D_TO_BRIDGE_D",
        "ENABLE_TO_KB_Y", "ENABLE_TO_KB_D",
        "CB_ZERO_Y", "CB_ZERO_D",
    ),
    "RectifierControl": (
        "CURRENT_ERROR", "ENABLE_PRODUCT", "PI_TO_LIMIT",
        "AO_Y_OUTPUT", "AO_D_OUTPUT", "ALPHA_OUTPUT",
    ),
    "InverterControl": (
        "GAMMA_MIN", "GAMMA_ERROR", "ENABLE_PRODUCT",
        "PI_TO_LIMIT", "AO_Y_OUTPUT", "AO_D_OUTPUT",
        "GAMMA_OUTPUT",
    ),
    "Initialization": (
        "IORDER_OUTPUT", "GAMMA_ORDER_OUTPUT",
        "ENABLE_RECT_OUTPUT", "ENABLE_INV_OUTPUT",
    ),
    "SignalInterface": (
        "VDC_RECT_IMPORT", "VDC_INV_IMPORT", "IDC_IMPORT",
    ),
}


def write_physical_library_fixture(
    tmp_path: Path,
    *,
    mutation: str | None = None,
) -> Path:
    root = ET.Element(
        "project",
        {
            "name": "cigre_lcc_v1",
            "version": "4.6.2",
            "Target": "Library",
        },
    )
    definitions = ET.SubElement(root, "definitions")
    for definition_name in PHYSICAL_PORTS:
        definition = ET.SubElement(
            definitions,
            "Definition",
            {"classid": "UserCmpDefn", "name": definition_name},
        )
        ET.SubElement(definition, "form")
        svg = ET.SubElement(definition, "svg")
        for index, port_name in enumerate(PHYSICAL_PORTS[definition_name]):
            kind = "Natural" if port_name.startswith(("AC", "DC_")) else "Transfer"
            ET.SubElement(
                svg,
                "port",
                {
                    "model": kind,
                    "name": port_name,
                    "x": str(index * 18),
                    "y": "0",
                    "dim": "1",
                    "mode": "Input" if port_name in {
                        "AO_Y", "AO_D", "ENABLE", "VDC", "IDC",
                        "IORDER", "GM_Y", "GM_D", "GAMMA_ORDER",
                    } else "Output",
                    "type": "Real",
                },
            )
        schematic = ET.SubElement(
            definition,
            "schematic",
            {"classid": "UserCanvas"},
        )
        users = list(PHYSICAL_USERS[definition_name])
        if mutation == "remove_second_bridge" and definition_name == "LCC12PulseBridge":
            users.pop()
        for index, scoped_name in enumerate(users):
            ET.SubElement(
                schematic,
                "User",
                {
                    "classid": "UserCmp",
                    "id": str(1000 + index),
                    "defn": scoped_name,
                    "x": str(180 + index * 90),
                    "y": "180",
                },
            )
        wires = list(PHYSICAL_WIRES[definition_name])
        if mutation == "remove_ao_wire" and definition_name == "LCC12PulseBridge":
            wires.remove("AO_D_TO_BRIDGE_D")
        for index, wire_name in enumerate(wires):
            ET.SubElement(
                schematic,
                "Wire",
                {"id": str(2000 + index), "name": wire_name},
            )
    bridge_svg = definitions.find("./Definition[@name='LCC12PulseBridge']/svg")
    if mutation == "add_gates_port":
        ET.SubElement(
            bridge_svg,
            "port",
            {
                "model": "Transfer",
                "name": "GATES",
                "x": "0",
                "y": "90",
                "dim": "12",
                "mode": "Input",
                "type": "Integer",
            },
        )
    if mutation == "copy_master_definition":
        ET.SubElement(
            definitions,
            "Definition",
            {"classid": "UserCmpDefn", "name": "master:g6p200"},
        )
    if mutation == "add_absolute_path":
        root.set("source", r"C:\vendor\master.pslx")
    if mutation == "add_foreign_scope":
        schematic = definitions.find(
            "./Definition[@name='SignalInterface']/schematic"
        )
        ET.SubElement(
            schematic,
            "User",
            {
                "classid": "UserCmp",
                "id": "9999",
                "defn": "foreign:Copied",
            },
        )
    path = tmp_path / "cigre_lcc_v1.pslx"
    ET.ElementTree(root).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )
    return path
```

The auditor and this fixture share only public string contracts; production code must not import the test constants.

- [ ] **Step 2: Run tests and verify collection failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_companion.py -q
```

Expected: collection FAIL because `companion.py` does not exist.

- [ ] **Step 3: Implement physical audit constants and entry point**

Create `companion.py`:

```python
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from ....core.backend.base import BackendError

LIBRARY_SCOPE = "cigre_lcc_v1"
EXPECTED_DEFINITIONS = {
    "cigre_lcc_v1:LCC12PulseBridge",
    "cigre_lcc_v1:RectifierControl",
    "cigre_lcc_v1:InverterControl",
    "cigre_lcc_v1:Initialization",
    "cigre_lcc_v1:SignalInterface",
}
FORBIDDEN_STRUCTURAL_TAGS = {
    "six_pulse_group",
    "sixpulsegroup",
    "valve",
    "control_block",
    "interface_contract",
    "initialization_contract",
}
EXPECTED_MASTER_COUNTS = {
    "cigre_lcc_v1:LCC12PulseBridge": {"master:g6p200": 2},
    "cigre_lcc_v1:RectifierControl": {
        "master:sumjct": 1,
        "master:mult": 1,
        "master:pi_ctlr": 1,
        "master:hardlimit": 1,
    },
    "cigre_lcc_v1:InverterControl": {
        "master:maxmin": 1,
        "master:sumjct": 1,
        "master:mult": 1,
        "master:pi_ctlr": 1,
        "master:hardlimit": 1,
    },
    "cigre_lcc_v1:Initialization": {
        "master:const": 2,
        "master:consti": 2,
    },
    "cigre_lcc_v1:SignalInterface": {"master:import": 3},
}


def audit_companion_library(path: str | Path) -> dict[str, Any]:
    library_path = Path(path).expanduser().resolve()
    payload = library_path.read_bytes()
    root = ET.fromstring(payload)
    errors: list[dict[str, Any]] = []
    if _local(root.tag) != "project" or root.get("Target") != "Library":
        errors.append({"definition": "", "reason": "not_pscad_library"})
    if root.get("name") != LIBRARY_SCOPE or root.get("version") != "4.6.2":
        errors.append({"definition": "", "reason": "library_identity"})
    definitions = _definition_map(root, LIBRARY_SCOPE)
    if set(definitions) != EXPECTED_DEFINITIONS:
        errors.append(
            {
                "definition": "",
                "reason": "definition_set_mismatch",
                "expected": sorted(EXPECTED_DEFINITIONS),
                "observed": sorted(definitions),
            }
        )
    evidence: dict[str, Any] = {}
    for scoped_name in sorted(EXPECTED_DEFINITIONS & set(definitions)):
        definition = definitions[scoped_name]
        ports = _external_ports(definition)
        instances = Counter(
            _scoped_definition(item) for item in _direct_users(definition)
        )
        expected = Counter(EXPECTED_MASTER_COUNTS[scoped_name])
        if instances != expected:
            errors.append(
                {
                    "definition": scoped_name,
                    "reason": "master_instance_count",
                    "expected": dict(expected),
                    "observed": dict(instances),
                }
            )
        _validate_definition(scoped_name, definition, ports, errors)
        evidence[scoped_name] = {
            "ports": ports,
            "master_instances": dict(instances),
            "connections": _connection_evidence(definition),
        }
    _scan_forbidden_content(root, errors)
    if errors:
        raise BackendError(
            "LCC_COMPANION_INVALID",
            "The LCC companion is not a physical PSCAD library.",
            "hvdc",
            "audit_lcc_companion_library",
            {
                "path": str(library_path),
                "errors": sorted(
                    errors,
                    key=lambda item: (
                        item.get("definition", ""),
                        item["reason"],
                    ),
                ),
            },
        )
    return {
        "valid": True,
        "library": str(library_path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "scope": LIBRARY_SCOPE,
        "definitions": evidence,
        "effective_valves": 12,
    }
```

Implement the private helpers in the same file. They must inspect direct schematic children only, normalize unscoped Definition names to the library scope, reject duplicate IDs/names, require exact port sets from Shared Identities, require named AO/DC-series wires, reject nested Master Definition bodies, reject foreign scopes, and reject absolute Windows/UNC/POSIX paths in attributes or text.

- [ ] **Step 4: Replace the synthetic compatibility validator**

In `validator.py` delete structural valve/gate helpers and delegate:

```python
from .companion import audit_companion_library


def validate_companion_library(
    path: str | Path,
    *,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    try:
        evidence = audit_companion_library(path)
    except BackendError as error:
        if raise_on_error:
            raise
        return {
            "valid": False,
            "errors": list(error.details.get("errors", ())),
            "warnings": [],
        }
    return {
        "valid": True,
        "errors": [],
        "warnings": [],
        "evidence": evidence,
    }
```

- [ ] **Step 5: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_companion.py tests/test_lcc_validator.py -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/hvdc/builders/lcc/companion.py pscad_mcp/hvdc/builders/lcc/validator.py tests/test_lcc_companion.py tests/test_lcc_validator.py
git add pscad_mcp/hvdc/builders/lcc/companion.py pscad_mcp/hvdc/builders/lcc/validator.py tests/test_lcc_companion.py tests/test_lcc_validator.py
git commit -m "feat: validate physical LCC companion libraries"
```

### Task 3: Implement the Pure WP1B Smoke Contract

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/smoke.py`
- Create: `tests/test_lcc_smoke.py`

- [ ] **Step 1: Write strict red tests**

Create `tests/test_lcc_smoke.py` with these exact identities:

```python
REQUIRED = (
    "Main/IDC",
    "Main/VDC_RECT",
    "Main/VDC_INV",
    "Main/AO_RECT_Y",
    "Main/AO_RECT_D",
    "Main/AO_INV_Y",
    "Main/AO_INV_D",
    "Main/GAMMA_INV",
    "Main/ENABLE_RECT",
    "Main/ENABLE_INV",
)


def contract():
    return {
        "schema_version": 1,
        "identity": "cigre_lcc_monopole_v1/wp1b_smoke",
        "duration_s": 0.1,
        "output_step_s": 0.00005,
        "required_channels": list(REQUIRED),
        "enable_channels": ["Main/ENABLE_RECT", "Main/ENABLE_INV"],
        "ao_limits_rad": {
            "Main/AO_RECT_Y": [0.08726646259971647, 0.5235987755982988],
            "Main/AO_RECT_D": [0.08726646259971647, 0.5235987755982988],
            "Main/AO_INV_Y": [0.52, 1.92],
            "Main/AO_INV_D": [0.52, 1.92],
        },
    }


def test_valid_no_fault_smoke_passes_without_golden_claims():
    result = evaluate_fixed_smoke(valid_samples(), contract())

    assert result["verdict"] == "PASS"
    assert result["checks"] == {
        "time_domain": True,
        "finite_outputs": True,
        "controls_enabled": True,
        "ao_within_limits": True,
    }
    assert "golden" not in result
    assert "disturbance" not in result


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing_channel", "missing_channel"),
        ("non_monotonic_time", "invalid_time_domain"),
        ("short_domain", "invalid_time_domain"),
        ("shifted_domain", "inconsistent_time_domain"),
        ("nan", "nonfinite_output"),
        ("disabled", "control_not_enabled"),
        ("ao_low", "ao_out_of_bounds"),
        ("ao_high", "ao_out_of_bounds"),
    ],
)
def test_smoke_failures_are_structured(mutation, reason):
    with pytest.raises(BackendError) as failure:
        evaluate_fixed_smoke(mutate_samples(valid_samples(), mutation), contract())

    assert failure.value.code == "LCC_FIXED_SMOKE_FAILED"
    assert failure.value.details["reason"] == reason
```

Implement `valid_samples()` as 2001 samples from `0.0` through `0.1` and `mutate_samples()` with one explicit branch per mutation.

- [ ] **Step 2: Run tests and verify import failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_smoke.py -q
```

Expected: collection FAIL because `smoke.py` does not exist.

- [ ] **Step 3: Implement the strict evaluator**

Create `smoke.py`:

```python
import math
from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError

CONTRACT_KEYS = {
    "schema_version",
    "identity",
    "duration_s",
    "output_step_s",
    "required_channels",
    "enable_channels",
    "ao_limits_rad",
}
CHECK_NAMES = (
    "time_domain",
    "finite_outputs",
    "controls_enabled",
    "ao_within_limits",
)


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        code,
        message,
        "hvdc",
        "evaluate_fixed_lcc_smoke",
        details,
    )


def evaluate_fixed_smoke(
    samples: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _parse_contract(contract)
    channels = _parse_channels(samples)
    missing = [
        name for name in normalized["required_channels"] if name not in channels
    ]
    if missing:
        raise _error(
            "LCC_FIXED_SMOKE_FAILED",
            "Required smoke channels are missing.",
            reason="missing_channel",
            channels=missing,
        )
    selected = {
        name: channels[name] for name in normalized["required_channels"]
    }
    common_time = _require_common_time(selected, normalized)
    _require_finite(selected)
    _require_enabled(selected, normalized["enable_channels"])
    _require_ao_limits(selected, normalized["ao_limits_rad"])
    return {
        "verdict": "PASS",
        "checks": {name: True for name in CHECK_NAMES},
        "evidence": {
            "duration_s": normalized["duration_s"],
            "output_step_s": normalized["output_step_s"],
            "domain_start_s": common_time[0],
            "domain_end_s": common_time[-1],
            "samples": len(common_time),
            "channels": {
                name: {
                    "units": selected[name]["units"],
                    "samples": len(selected[name]["values"]),
                    "minimum": min(selected[name]["values"]),
                    "maximum": max(selected[name]["values"]),
                }
                for name in sorted(selected)
            },
        },
    }
```

Implement `_parse_contract()` with exact fields and finite positive numbers; `_parse_channels()` accepts per-channel `time`, `values`, and text `units`; `_require_common_time()` requires identical strictly increasing grids ending within one output step of `duration_s`; `_require_finite()` rejects nonfinite values; `_require_enabled()` requires every enable sample to equal `1.0`; and `_require_ao_limits()` requires `rad` units and inclusive bounds. Every failure uses `LCC_FIXED_SMOKE_FAILED` and one of the tested reasons; malformed contracts use `LCC_FIXED_SMOKE_INVALID`.

- [ ] **Step 4: Run tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_smoke.py -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/hvdc/builders/lcc/smoke.py tests/test_lcc_smoke.py
git add pscad_mcp/hvdc/builders/lcc/smoke.py tests/test_lcc_smoke.py
git commit -m "feat: evaluate fixed LCC smoke outputs"
```

## Phase A Asset Materialization and Phase B Builder Integration

### Task 4: Atomically Migrate the Packaged Companion, Catalog, Blueprint, and Smoke Asset

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/assets.py`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/smoke.json`
- Create: `scripts/build_lcc_companion_library.py`
- Replace: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/library/cigre_lcc_v1.pslx`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/catalog-pscad-4.6.2.json`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/PROVENANCE.md`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json`
- Modify: `scripts/audit_lcc_assets.py`
- Modify: `tests/test_lcc_assets.py`
- Modify: `tests/test_lcc_asset_audit.py`
- Modify: `tests/test_lcc_catalog.py`
- Modify: `tests/test_lcc_planner.py`

This task is one atomic asset commit. Do not commit a library whose catalog/blueprint still exposes `GATES`, and do not commit a manifest that omits a changed file.

- [ ] **Step 1: Write failing packaged-asset assertions**

Add to `tests/test_lcc_assets.py`:

```python
def test_packaged_asset_exposes_hashed_wp1b_smoke_contract():
    assets = load_packaged_asset_set()

    assert assets.smoke["identity"] == "cigre_lcc_monopole_v1/wp1b_smoke"
    assert assets.smoke["duration_s"] == pytest.approx(0.1)
    assert "smoke.json" in assets.hashes
    assert assets.master_bindings is not None
    assert assets.master_bindings.schema_version == 2
    assert set(assets.master_bindings.companion_by_logical_name) == {
        "master:six_pulse_bridge",
        "master:control_sum",
        "master:control_pi",
        "master:control_limiter",
        "master:control_minimum",
        "master:control_product",
        "master:real_constant",
        "master:integer_constant",
        "master:signal_import",
    }
```

Add to `tests/test_lcc_asset_audit.py`:

```python
def test_packaged_companion_is_physical_and_has_no_gate_vector():
    report = audit_asset_root(ASSET_ROOT)

    assert report["valid"] is True
    assert report["effective_valves"] == 12
    assert report["master_instances"]["master:g6p200"] == 2
    assert report["firing_mode"] == {
        "physical_parameter": "FP",
        "value": 0,
        "active_port": "AO",
        "dimension": 1,
    }
    library = (ASSET_ROOT / "library" / "cigre_lcc_v1.pslx").read_text(
        encoding="utf-8"
    )
    assert "GATES" not in library
    assert "FPN" not in library
    assert "master:thyristor_valve" not in library
```

Add to `tests/test_lcc_catalog.py` and `tests/test_lcc_planner.py`:

```python
def test_fixed_catalog_uses_scalar_ao_contracts():
    assets = load_packaged_asset_set()
    catalog = parse_catalog(assets.catalog)
    bridge = require_definition(catalog, "cigre_lcc_v1:LCC12PulseBridge")

    assert {port.name for port in bridge.ports} == set(BRIDGE_PORTS)
    assert require_port(bridge, "AO_Y").dimension == 1
    assert require_port(bridge, "AO_D").dimension == 1
    assert "GATES" not in {port.name for port in bridge.ports}


def test_fixed_blueprint_has_two_transformer_groups_and_four_ao_nets():
    blueprint = load_packaged_asset_set().blueprint
    component_ids = {component.logical_id for component in blueprint.components}
    net_ids = {net.logical_id for net in blueprint.nets}

    assert {
        "rectifier_transformer_y",
        "rectifier_transformer_d",
        "inverter_transformer_y",
        "inverter_transformer_d",
        "initialization",
        "signal_interface",
    } <= component_ids
    assert {
        "rectifier_ao_y",
        "rectifier_ao_d",
        "inverter_ao_y",
        "inverter_ao_d",
    } <= net_ids
    assert not any(
        endpoint.port == "GATES"
        for net in blueprint.nets
        for endpoint in net.endpoints
    )
```

- [ ] **Step 2: Run the asset tests and verify they fail for the old package**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_assets.py tests/test_lcc_asset_audit.py tests/test_lcc_catalog.py tests/test_lcc_planner.py -q
```

Expected: failures for missing `smoke`, schema version 1, structural PSLX, old ports, and missing second transformer groups.

- [ ] **Step 3: Extend the asset loader with a strict smoke record**

Add `smoke: dict[str, Any]` to `LccAssetSet`. Add `smoke.json` to the required set and constructor:

```python
@dataclass(frozen=True)
class LccAssetSet:
    name: str
    schema_version: int
    pscad_version: str
    companion_library: str
    blueprint: LccBlueprint
    catalog: dict[str, Any]
    acceptance: dict[str, Any]
    golden: dict[str, Any]
    smoke: dict[str, Any]
    provenance: str
    hashes: dict[str, str]
    library_bytes: bytes
    files: dict[str, bytes]
    root: None = None
    master_bindings: MasterBindingRegistry | None = None
    master_binding_hash: str | None = None
```

In `load_asset_set()` require and parse `smoke.json`:

```python
required = {
    "blueprint.json",
    "catalog-pscad-4.6.2.json",
    "acceptance.json",
    "golden.json",
    "smoke.json",
    "PROVENANCE.md",
    "master-bindings-pscad-4.6.2.json",
    companion_library,
}

smoke = _json_record(files, "smoke.json")
if smoke.get("identity") != f"{name}/wp1b_smoke":
    raise _asset_error(
        "LCC_ASSET_MISMATCH",
        "The smoke contract identity does not match the asset.",
        "load_lcc_asset_set",
        expected=f"{name}/wp1b_smoke",
        observed=smoke.get("identity"),
    )
```

Pass `smoke=smoke` to `LccAssetSet`. Update all test constructors of `LccAssetSet` with `smoke={}` until their test needs a real contract.

- [ ] **Step 4: Add the exact smoke contract**

Create `smoke.json`:

```json
{
  "schema_version": 1,
  "identity": "cigre_lcc_monopole_v1/wp1b_smoke",
  "duration_s": 0.1,
  "output_step_s": 0.00005,
  "required_channels": [
    "Main/IDC",
    "Main/VDC_RECT",
    "Main/VDC_INV",
    "Main/AO_RECT_Y",
    "Main/AO_RECT_D",
    "Main/AO_INV_Y",
    "Main/AO_INV_D",
    "Main/GAMMA_INV",
    "Main/ENABLE_RECT",
    "Main/ENABLE_INV"
  ],
  "enable_channels": [
    "Main/ENABLE_RECT",
    "Main/ENABLE_INV"
  ],
  "ao_limits_rad": {
    "Main/AO_RECT_Y": [0.08726646259971647, 0.5235987755982988],
    "Main/AO_RECT_D": [0.08726646259971647, 0.5235987755982988],
    "Main/AO_INV_Y": [0.52, 1.92],
    "Main/AO_INV_D": [0.52, 1.92]
  }
}
```

- [ ] **Step 5: Upgrade the packaged registry with exact companion roles**

Set registry `schema_version` to `2` and add nine `companion_bindings`. Preserve the identities, physical Definitions, shapes, and existing transforms of the eight project bindings. Extend only `master:dc_meter` with explicit logical `CurrentSignal`/`VoltageSignal` text mappings to physical `CurI`/`VolI`, because WP1B requires uniquely named producers. The bridge record must select these View=1 occurrences and fixed values:

```json
{
  "logical_name": "master:six_pulse_bridge",
  "physical_definition": "g6p200",
  "shape": {"kind": "direct"},
  "ports": [
    {"logical": "N", "physical": "N", "kind": "electrical", "dimension": 3, "occurrence": 0},
    {"logical": "DP_RECT", "physical": "DP", "kind": "electrical", "dimension": 1, "occurrence": 2},
    {"logical": "DN_RECT", "physical": "DN", "kind": "electrical", "dimension": 1, "occurrence": 3},
    {"logical": "DP_INV", "physical": "DP", "kind": "electrical", "dimension": 1, "occurrence": 3},
    {"logical": "DN_INV", "physical": "DN", "kind": "electrical", "dimension": 1, "occurrence": 2},
    {"logical": "AO", "physical": "AO", "kind": "data", "dimension": 1, "occurrence": 1},
    {"logical": "AM", "physical": "AM", "kind": "data", "dimension": 1, "occurrence": 1},
    {"logical": "GM", "physical": "GM", "kind": "data", "dimension": 1, "occurrence": 1},
    {"logical": "KB", "physical": "KB", "kind": "data", "dimension": 1, "occurrence": 1},
    {"logical": "CB", "physical": "CB", "kind": "data", "dimension": 1, "occurrence": 1}
  ],
  "parameters": [
    {
      "logical": ["UP", "KV"],
      "physical": ["UP", "KV"],
      "transform": {"kind": "identity"},
      "physical_contracts": {
        "UP": {"type": "Choice", "unit": null, "choices": ["0", "1"]},
        "KV": {"type": "Choice", "unit": null, "choices": ["1", "0", "-1", "-2"]}
      }
    }
  ],
  "fixed_parameters": [
    {"physical": "FP", "value": 0, "contract": {"type": "Choice", "unit": null, "choices": ["0", "1", "2", "3"]}},
    {"physical": "SNUB", "value": 1, "contract": {"type": "Choice", "unit": null, "choices": ["0", "1"]}},
    {"physical": "View", "value": 1, "contract": {"type": "Choice", "unit": null, "choices": ["0", "1"]}},
    {"physical": "FR", "value": 50.0, "contract": {"type": "Real", "unit": "Hz", "choices": []}},
    {"physical": "GP", "value": 10.0, "contract": {"type": "Real", "unit": null, "choices": []}},
    {"physical": "GI", "value": 50.0, "contract": {"type": "Real", "unit": null, "choices": []}},
    {"physical": "KP", "value": 0, "contract": {"type": "Choice", "unit": null, "choices": ["1", "0"]}},
    {"physical": "RON", "value": 0.01, "contract": {"type": "Real", "unit": "ohm", "choices": []}},
    {"physical": "ROFF", "value": 100000000.0, "contract": {"type": "Real", "unit": "ohm", "choices": []}},
    {"physical": "EFVD", "value": 0.0, "contract": {"type": "Real", "unit": "kV", "choices": []}},
    {"physical": "EBO", "value": 100000.0, "contract": {"type": "Real", "unit": "kV", "choices": []}},
    {"physical": "TEXT", "value": 0.0, "contract": {"type": "Real", "unit": "us", "choices": []}},
    {"physical": "RD", "value": 5000.0, "contract": {"type": "Real", "unit": "ohm", "choices": []}},
    {"physical": "CD", "value": 0.05, "contract": {"type": "Real", "unit": "uF", "choices": []}},
    {"physical": "Tblock", "value": 0.04, "contract": {"type": "Real", "unit": "s", "choices": []}},
    {"physical": "RWSAFB", "value": 0, "contract": {"type": "Choice", "unit": null, "choices": ["0", "1"]}},
    {"physical": "RWV", "value": 100000.0, "contract": {"type": "Real", "unit": "kV", "choices": []}},
    {"physical": "PFB", "value": 0, "contract": {"type": "Choice", "unit": null, "choices": ["0", "1"]}}
  ],
  "evidence_parameters": []
}
```

Encode the remaining eight records from this exact profile table. Each listed `logical_parameters` entry uses an identity transform and the live type/unit; every `fixed_parameters` entry uses a fixed-parameter contract with the live choices. Unlisted conditional ports are not selected.

```python
REMAINING_COMPANION_PROFILES = {
    "master:control_sum": {
        "physical": "sumjct",
        "ports": (("POS", "IND", 0), ("NEG", "INF", 0), ("OUT", "OUT", 0)),
        "logical_parameters": (),
        "fixed_parameters": {
            "DPath": 1, "A": 0, "B": 0, "C": 0,
            "D": 1, "E": 0, "F": -1, "G": 0,
        },
    },
    "master:control_pi": {
        "physical": "pi_ctlr",
        "ports": (("IN", "IN", 0), ("OUT", "OUT", 0)),
        "logical_parameters": ("GP", "TI", "YHI", "YLO", "YINIT"),
        "fixed_parameters": {"Mthd": 0, "INTR": 0},
    },
    "master:control_limiter": {
        "physical": "hardlimit",
        "ports": (("IN", "I:Dim", 0), ("OUT", "O:Dim", 0)),
        "logical_parameters": ("UL", "LL"),
        "fixed_parameters": {"Dim": 1, "Limit": 0, "COM": "LCC_AO_Limit"},
    },
    "master:control_minimum": {
        "physical": "maxmin",
        "ports": (("LEFT", "IND", 0), ("RIGHT", "INE", 0), ("OUT", "OUT", 0)),
        "logical_parameters": (),
        "fixed_parameters": {
            "DPath": 1, "Type": 0, "A": 0, "B": 0, "C": 0,
            "D": 1, "E": 1, "F": 0, "G": 0,
        },
    },
    "master:control_product": {
        "physical": "mult",
        "ports": (("LEFT", "IN1", 0), ("RIGHT", "IN2", 0), ("OUT", "OUT", 0)),
        "logical_parameters": (),
        "fixed_parameters": {"DPath": 1},
    },
    "master:real_constant": {
        "physical": "const",
        "ports": (("OUT", "OUT", 0),),
        "logical_parameters": ("Name", "Value"),
        "fixed_parameters": {},
    },
    "master:integer_constant": {
        "physical": "consti",
        "ports": (("OUT", "OUT", 0),),
        "logical_parameters": ("Name", "Value"),
        "fixed_parameters": {},
    },
    "master:signal_import": {
        "physical": "import",
        "ports": (("OUT", "N", 0),),
        "logical_parameters": ("Name",),
        "fixed_parameters": {},
    },
}
```

Add a parametrized registry test that compares every parsed record to this table, then run the live metadata audit before accepting the JSON.

- [ ] **Step 6: Write the deterministic library renderer and its exact ledgers**

Create `scripts/build_lcc_companion_library.py`. It must read only the repository-owned `empty_library.pslx` skeleton, replace its namespace/definitions/hierarchy, and write deterministic UTF-8 LF output. Define these bridge profiles exactly:

```python
COMMON_G6P200 = {
    "FP": "0",
    "SNUB": "1",
    "View": "1",
    "FR": "50.0 [Hz]",
    "GP": "10.0",
    "GI": "50.0",
    "KP": "0",
    "RON": "0.01 [ohm]",
    "ROFF": "100000000.0 [ohm]",
    "EFVD": "0.0 [kV]",
    "EBO": "100000.0 [kV]",
    "TEXT": "0.0 [us]",
    "CD": "0.05 [uF]",
    "RD": "5000.0 [ohm]",
    "Tblock": "0.04",
    "RWSAFB": "0",
    "RWV": "1.0E5",
    "PFB": "0",
}
GROUP_PARAMETERS = {
    "Y": {**COMMON_G6P200, "KV": "-2"},
    "D": {**COMMON_G6P200, "KV": "-1"},
}
TERMINAL_UP = {"rectifier": "1", "inverter": "0"}

CONTROL_PARAMETERS = {
    "rectifier_pi": {
        "GP": "1.0989",
        "TI": "0.01092 [s]",
        "YHI": "0.5235987755982988",
        "YLO": "0.08726646259971647",
        "YINIT": "0.2617993877991494",
        "Mthd": "0",
        "INTR": "0",
    },
    "rectifier_limit": {
        "UL": "0.5235987755982988",
        "LL": "0.08726646259971647",
        "Dim": "1",
        "Limit": "0",
    },
    "inverter_pi": {
        "GP": "0.7506",
        "TI": "0.0544 [s]",
        "YHI": "1.92",
        "YLO": "0.52",
        "YINIT": "1.57",
        "Mthd": "0",
        "INTR": "0",
    },
    "inverter_limit": {
        "UL": "1.92",
        "LL": "0.52",
        "Dim": "1",
        "Limit": "0",
    },
    "initialization": {
        "IORDER": "1.0",
        "GAMMA_ORDER": "0.3141592653589793",
        "ENABLE_RECT": "1",
        "ENABLE_INV": "1",
    },
}
```

Define one immutable spec per custom Definition:

```python
DEFINITION_MASTER_INSTANCES = {
    "LCC12PulseBridge": ("master:g6p200", "master:g6p200"),
    "RectifierControl": (
        "master:sumjct",
        "master:mult",
        "master:pi_ctlr",
        "master:hardlimit",
    ),
    "InverterControl": (
        "master:maxmin",
        "master:sumjct",
        "master:mult",
        "master:pi_ctlr",
        "master:hardlimit",
    ),
    "Initialization": (
        "master:const",
        "master:const",
        "master:consti",
        "master:consti",
    ),
    "SignalInterface": (
        "master:import",
        "master:import",
        "master:import",
    ),
}
```

Renderer postconditions:

```python
def render_library() -> bytes:
    root = _library_root("cigre_lcc_v1")
    _append_station(root)
    for name in (
        "LCC12PulseBridge",
        "RectifierControl",
        "InverterControl",
        "Initialization",
        "SignalInterface",
    ):
        _append_definition(root, name)
    _append_hierarchy(root)
    ET.indent(root, space="  ")
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return payload.replace(b"\r\n", b"\n") + (b"" if payload.endswith(b"\n") else b"\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    payload = render_library()
    if args.check:
        return 0 if args.output.read_bytes() == payload else 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    return 0
```

The private appenders must emit real PSCAD `project Target="Library"`, `Definition classid="UserCmpDefn"`, `form`, `svg` ports, `schematic classid="UserCanvas"`, direct `User` children whose `defn` values exactly match `DEFINITION_MASTER_INSTANCES`, page ports, and explicit `Wire` records. Use stable positive IDs derived from `sha256(f"{definition}:{role}")`. Bridge wires must connect ACY/ACD to the two `N[3]` groups, the two DC bridges in series, `AO_Y/AO_D` to physical AO, `KB=1-ENABLE`, and `CB=0`. Control wires must implement the exact equations in the design spec. Do not read or copy the installed Master or official CIGRE XML.

- [ ] **Step 7: Generate and audit the physical PSLX**

```powershell
.\.venv\Scripts\python.exe scripts/build_lcc_companion_library.py --output pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/library/cigre_lcc_v1.pslx
.\.venv\Scripts\python.exe scripts/build_lcc_companion_library.py --output pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/library/cigre_lcc_v1.pslx --check
```

Expected: both commands exit 0 and the second produces no diff.

- [ ] **Step 8: Migrate catalog and blueprint to exact AO topology**

Update catalog ports to the Shared Identities. Add typed parameters:

```json
{
  "BridgeMode": {"type": "enum", "enum": ["rectifier", "inverter"]},
  "AlphaInitial_rad": {"type": "float", "minimum": 0.08726646259971647, "maximum": 0.5235987755982988, "unit": "rad"},
  "GammaOrder_rad": {"type": "float", "minimum": 0.17453292519943295, "maximum": 0.6981317007977318, "unit": "rad"},
  "Enabled": {"type": "int", "minimum": 0, "maximum": 1}
}
```

Add these parameters specifically to `master:dc_meter`:

```json
{
  "CurrentSignal": {"type": "string"},
  "VoltageSignal": {"type": "string"}
}
```

Set the rectifier meter to `CurrentSignal="IDC"`, `VoltageSignal="VDC_RECT"`; set the inverter meter to `CurrentSignal="IDC_INV"`, `VoltageSignal="VDC_INV"`. Only `IDC`, `VDC_RECT`, and `VDC_INV` are imported by `SignalInterface`, so every imported name has exactly one producer.

In the blueprint:

- replace each single transformer with `*_transformer_y` at 0 degrees/Y-Y and `*_transformer_d` at 30 degrees/Y-delta;
- connect each source HV bus to both transformers;
- connect each Y secondary to `ACY_A/B/C` and each delta secondary to `ACD_A/B/C`;
- set bridge `BridgeMode` to `rectifier` or `inverter`;
- instantiate `Initialization` and `SignalInterface`;
- create exactly four AO nets named in the design spec;
- connect two terminal enable nets to both control and bridge;
- connect unique `VDC_RECT`, `VDC_INV`, and `IDC` producers through `SignalInterface`;
- connect inverter `GM_Y/GM_D` directly to `InverterControl`;
- add all ten smoke outputs from `smoke.json` with exact units, using `rad` for AO;
- remove every `GATES` endpoint and structural valve assertion.

- [ ] **Step 9: Update provenance and the asset audit report**

Replace the structural provenance claim with an explicit ledger stating that the library is generated solely from repository-owned tables and Master references. In `audit_lcc_assets.py`, return:

```python
physical = audit_companion_library(library)
result["definitions"] = sorted(physical["definitions"])
result["effective_valves"] = physical["effective_valves"]
result["master_instances"] = dict(
    physical["definitions"][
        "cigre_lcc_v1:LCC12PulseBridge"
    ]["master_instances"]
)
result["firing_mode"] = {
    "physical_parameter": "FP",
    "value": 0,
    "active_port": "AO",
    "dimension": 1,
}
```

Delete the old raw `<valve>` count.

- [ ] **Step 10: Recalculate canonical asset hashes and patch the manifest**

Print canonical LF-normalized hashes without writing the manifest:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import hashlib; r=Path('pscad_mcp/assets/lcc/cigre_lcc_monopole_v1'); [(print(p.relative_to(r).as_posix(), hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n').replace(b'\r',b'\n')).hexdigest())) for p in sorted(r.rglob('*')) if p.is_file() and p.name!='manifest.json']"
```

Use `apply_patch` to replace every manifest digest with the printed value and add `smoke.json`. Do not use a script to partially update JSON.

- [ ] **Step 11: Run the atomic asset gate**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_master_binding_registry.py tests/test_master_definition_bindings.py tests/test_lcc_assets.py tests/test_lcc_asset_audit.py tests/test_lcc_catalog.py tests/test_lcc_planner.py tests/test_lcc_validator.py -q
.\.venv\Scripts\python.exe scripts/audit_lcc_assets.py --asset-root pscad_mcp/assets/lcc/cigre_lcc_monopole_v1
git diff --check
```

Expected: all tests PASS, asset audit returns `"valid": true`, `effective_valves=12`, and no `GATES` appears in library/catalog/blueprint.

- [ ] **Step 12: Commit Task 4**

```powershell
git add pscad_mcp/hvdc/builders/lcc/assets.py pscad_mcp/assets/lcc/cigre_lcc_monopole_v1 scripts/build_lcc_companion_library.py scripts/audit_lcc_assets.py tests/test_lcc_assets.py tests/test_lcc_asset_audit.py tests/test_lcc_catalog.py tests/test_lcc_planner.py
git commit -m "feat: physicalize fixed LCC companion assets"
```

### Task 5: Add an Immutable WP1B Smoke Plan Profile

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/models.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/planner.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/service.py`
- Modify: `tests/test_lcc_planner.py`
- Modify: `tests/test_lcc_builder_service.py`

- [ ] **Step 1: Write failing plan/profile tests**

Add:

```python
def test_wp1b_smoke_plan_uses_smoke_gate_and_hashes_profile(tmp_path):
    assets = packaged_assets_for_planner()
    inventory = packaged_live_inventory(assets)
    smoke_request = LccPlanRequest(
        project_name="WP1B_FIXED_LCC",
        folder=str(tmp_path),
        simulation_duration_s=0.1,
        blueprint=assets.name,
        verification_profile="wp1b_smoke",
    )

    smoke = create_plan(smoke_request, assets, inventory, tmp_path)
    full = create_plan(
        replace(
            smoke_request,
            simulation_duration_s=1.0,
            verification_profile="full_acceptance",
        ),
        assets,
        inventory,
        tmp_path,
    )

    assert smoke.verification_profile == "wp1b_smoke"
    assert smoke.plan_hash != full.plan_hash
    assert [item.kind for item in smoke.operations][-2:] == [
        "smoke_validate",
        "publish",
    ]
    assert "accept" not in [item.kind for item in smoke.operations]
    assert [item.kind for item in full.operations][-2:] == ["accept", "publish"]


def test_wp1b_smoke_profile_requires_exact_duration(tmp_path):
    request = _request(
        verification_profile="wp1b_smoke",
        simulation_duration_s=0.2,
    )

    with pytest.raises(BackendError) as failure:
        create_plan(request, _asset_set(), INVENTORY, tmp_path)

    assert failure.value.code == "LCC_BLUEPRINT_INVALID"
```

- [ ] **Step 2: Run tests and verify profile argument failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_planner.py -k "wp1b_smoke" -q
```

Expected: FAIL because request/plan models do not expose `verification_profile`.

- [ ] **Step 3: Add exact profile fields and state**

In `models.py`:

```python
class LccBuildState(str, Enum):
    VALIDATED = "validated"
    STAGING_CREATED = "staging_created"
    COMPONENTS_PLACED = "components_placed"
    PARAMETERS_VERIFIED = "parameters_verified"
    CONNECTIONS_VERIFIED = "connections_verified"
    STRUCTURE_VERIFIED = "structure_verified"
    STAGING_SAVED = "staging_saved"
    COMPILED = "compiled"
    SIMULATED = "simulated"
    SMOKE_PASSED = "smoke_passed"
    ACCEPTANCE_PASSED = "acceptance_passed"
    PUBLISHED = "published"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class LccBuildPlan(_JsonRecord):
    blueprint: LccBlueprint
    operations: tuple[LccPlanOperation, ...]
    plan_hash: str
    verification_profile: str = "full_acceptance"
    acceptance_checks: tuple[LccAcceptanceCheck, ...] = ()
    target_path: str | None = None
    staging_path: str | None = None
    asset_hashes: dict[str, str] = field(default_factory=dict)
    pscad_version: str | None = None
    catalog_identity: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    master_sha256: str | None = None
    master_binding_registry_sha256: str | None = None
```

In `planner.py`:

```python
FULL_ACCEPTANCE_PROFILE = "full_acceptance"
WP1B_SMOKE_PROFILE = "wp1b_smoke"
VERIFICATION_PROFILES = {FULL_ACCEPTANCE_PROFILE, WP1B_SMOKE_PROFILE}


@dataclass(frozen=True)
class LccPlanRequest:
    project_name: str
    folder: str | None = None
    simulation_duration_s: float | None = None
    blueprint: str = "cigre_lcc_monopole_v1"
    verification_profile: str = FULL_ACCEPTANCE_PROFILE
```

Add `"smoke_validate"` immediately before `"accept"` in `_OPERATION_PHASES`; only one of those phases is emitted in any plan. Validate the profile before resolving paths. For `wp1b_smoke` require `duration == asset_set.smoke["duration_s"]`. Select final operations:

```python
if request.verification_profile == WP1B_SMOKE_PROFILE:
    add(
        "smoke_validate",
        "smoke_validate",
        project_name,
        {
            "contract_sha256": asset_set.hashes["smoke.json"],
            "required_channels": list(asset_set.smoke["required_channels"]),
        },
    )
else:
    add(
        "accept",
        "accept",
        project_name,
        {"required_checks": [check.name for check in checks]},
    )
add("publish", "publish", project_name, {"target_path": str(final_path)})
```

Include `verification_profile` and `smoke_contract_sha256` in the plan-hash payload and returned `LccBuildPlan`.

- [ ] **Step 4: Thread the profile through the service API**

Add `verification_profile: str = FULL_ACCEPTANCE_PROFILE` to `plan_model()` and `build_model()` and pass it to `LccPlanRequest`. Keep the default unchanged so existing callers still get full acceptance.

- [ ] **Step 5: Run planner/service regression and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_planner.py tests/test_lcc_builder_service.py tests/test_lcc_executor.py -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/hvdc/builders/lcc/models.py pscad_mcp/hvdc/builders/lcc/planner.py pscad_mcp/hvdc/builders/lcc/service.py
git add pscad_mcp/hvdc/builders/lcc/models.py pscad_mcp/hvdc/builders/lcc/planner.py pscad_mcp/hvdc/builders/lcc/service.py tests/test_lcc_planner.py tests/test_lcc_builder_service.py
git commit -m "feat: plan fixed LCC smoke verification"
```

### Task 6: Execute the Smoke Gate Without Calling Golden Acceptance

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/executor.py`
- Modify: `tests/test_lcc_executor.py`

- [ ] **Step 1: Write failing executor tests**

Add fake output channels matching `smoke.json` and tests:

```python
def test_executor_uses_smoke_evaluator_and_records_smoke_state(tmp_path):
    service = FixedSmokeRecordingService()
    plan = _plan_with_profile(tmp_path, "wp1b_smoke")

    record = asyncio.run(
        execute_build(
            plan,
            service,
            tmp_path,
            asset_set=_fixed_smoke_assets(),
            build_id="fixed-smoke",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.PUBLISHED
    assert [item["state"] for item in record.history if "state" in item][-3:] == [
        "simulated",
        "smoke_passed",
        "published",
    ]
    assert record.result["smoke"]["verdict"] == "PASS"
    assert "golden_checks" not in record.result["smoke"]


def test_smoke_failure_never_publishes_or_calls_acceptance(tmp_path, monkeypatch):
    service = FixedSmokeRecordingService(mutation="disabled")
    called = []
    monkeypatch.setattr(
        "pscad_mcp.hvdc.builders.lcc.executor.evaluate_acceptance",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    record = asyncio.run(
        execute_build(
            _plan_with_profile(tmp_path, "wp1b_smoke"),
            service,
            tmp_path,
            asset_set=_fixed_smoke_assets(),
            build_id="fixed-smoke-fail",
            poll_interval_s=0,
        )
    )

    assert record.state == LccBuildState.FAILED
    assert record.error["code"] == "LCC_FIXED_SMOKE_FAILED"
    assert called == []
    assert not Path(record.plan.target_path).exists()
```

- [ ] **Step 2: Run tests and verify unknown operation failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_executor.py -k "smoke_evaluator or smoke_failure" -q
```

Expected: FAIL because `smoke_validate` is unknown.

- [ ] **Step 3: Add smoke dispatch and implementation**

In `executor.py` import `evaluate_fixed_smoke` and dispatch:

```python
elif operation.kind == "smoke_validate":
    await self._smoke_validate(operation)
elif operation.kind == "accept":
    await self._accept(operation)
```

Add:

```python
async def _smoke_validate(self, operation: LccPlanOperation) -> None:
    self._operation_started(operation)
    if self.asset_set is None:
        raise _error(
            "LCC_FIXED_SMOKE_INVALID",
            "The smoke gate requires a verified asset set.",
            "evaluate_fixed_lcc_smoke",
        )
    expected_hash = operation.arguments.get("contract_sha256")
    observed_hash = self.asset_set.hashes.get("smoke.json")
    if expected_hash != observed_hash:
        raise _error(
            "LCC_ASSET_MISMATCH",
            "The smoke contract changed after planning.",
            "evaluate_fixed_lcc_smoke",
            expected=expected_hash,
            observed=observed_hash,
        )
    output = await self._acceptance_output()
    smoke = evaluate_fixed_smoke(output, self.asset_set.smoke)
    result = dict(self.result or {})
    result["smoke"] = smoke
    if self.output_file is not None:
        result["output_file"] = self.output_file
        result["output_parts"] = list(
            self.output_parts or [self.output_file]
        )
        result["output_sha256"] = sha256_file(Path(self.output_file))
    self.result = result
    self._record(LccBuildState.SMOKE_PASSED)
```

In `_publish()` preserve the existing smoke result when adding final project/library evidence. Ensure `_validate_graph()` never invokes waveform acceptance for a `wp1b_smoke` plan.

- [ ] **Step 4: Add read-back drift and runtime failure tests**

Add parametrized services for wrong AO port dimension, changed bridge `UP`, connection endpoint drift, runtime terminal failure, missing output, and nonfinite output. Assert each fails before publication and the journal retains the structured code.

- [ ] **Step 5: Run executor regression and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_executor.py tests/test_lcc_planner.py -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/hvdc/builders/lcc/executor.py tests/test_lcc_executor.py
git add pscad_mcp/hvdc/builders/lcc/executor.py tests/test_lcc_executor.py
git commit -m "feat: execute fixed LCC smoke gate"
```

### Task 7: Add Isolated Companion Definition Gates

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/companion_gate.py`
- Create: `tests/test_lcc_companion_gate.py`

- [ ] **Step 1: Write fake-service red tests for exact fixture order and rollback**

Create `tests/test_lcc_companion_gate.py`:

```python
FIXTURES = (
    ("bridge_rectifier", "cigre_lcc_v1:LCC12PulseBridge", {"BridgeMode": "rectifier"}),
    ("bridge_inverter", "cigre_lcc_v1:LCC12PulseBridge", {"BridgeMode": "inverter"}),
    ("rectifier_control", "cigre_lcc_v1:RectifierControl", {}),
    ("inverter_control", "cigre_lcc_v1:InverterControl", {}),
    ("initialization", "cigre_lcc_v1:Initialization", {}),
    ("signal_interface", "cigre_lcc_v1:SignalInterface", {}),
)


def test_component_gate_loads_reads_reloads_and_compiles_every_fixture(tmp_path):
    service = CompanionGateFakeService()
    master_path = _master_fixture(tmp_path)
    registry_path, registry_sha256 = _registry_fixture(tmp_path)

    result = asyncio.run(
        run_companion_component_gate(
            service,
            _assets(),
            tmp_path,
            master_path=master_path,
            registry_path=registry_path,
            expected_master_sha256=hashlib.sha256(
                master_path.read_bytes()
            ).hexdigest(),
            expected_registry_sha256=registry_sha256,
        )
    )

    assert result["status"] == "PASS"
    assert [item["fixture"] for item in result["fixtures"]] == [
        item[0] for item in FIXTURES
    ]
    assert all(item["compile"]["success"] for item in result["fixtures"])
    assert all(item["before_reload"] == item["after_reload"] for item in result["fixtures"])


@pytest.mark.parametrize(
    "failure",
    ["load_projects", "add_canvas_component", "get_component_ports", "reload_project", "build_project"],
)
def test_component_gate_preserves_fail_evidence_and_stops(failure, tmp_path):
    service = CompanionGateFakeService(fail_on=failure)
    master_path = _master_fixture(tmp_path)
    registry_path, registry_sha256 = _registry_fixture(tmp_path)

    result = asyncio.run(
        run_companion_component_gate(
            service,
            _assets(),
            tmp_path,
            master_path=master_path,
            registry_path=registry_path,
            expected_master_sha256=hashlib.sha256(
                master_path.read_bytes()
            ).hexdigest(),
            expected_registry_sha256=registry_sha256,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["operation"] == failure
    assert not any(
        call[0] == "build_project"
        for call in service.calls[service.failure_index + 1 :]
    )
```

- [ ] **Step 2: Run tests and verify import failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_companion_gate.py -q
```

Expected: collection FAIL because `companion_gate.py` does not exist.

- [ ] **Step 3: Implement fixture contracts and runner**

Create `companion_gate.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class CompanionFixture:
    name: str
    definition: str
    parameters: Mapping[str, Any]
    expected_ports: tuple[str, ...]


FIXTURES = (
    CompanionFixture(
        "bridge_rectifier",
        "cigre_lcc_v1:LCC12PulseBridge",
        {"BridgeMode": "rectifier"},
        BRIDGE_PORTS,
    ),
    CompanionFixture(
        "bridge_inverter",
        "cigre_lcc_v1:LCC12PulseBridge",
        {"BridgeMode": "inverter"},
        BRIDGE_PORTS,
    ),
    CompanionFixture(
        "rectifier_control",
        "cigre_lcc_v1:RectifierControl",
        {},
        RECTIFIER_CONTROL_PORTS,
    ),
    CompanionFixture(
        "inverter_control",
        "cigre_lcc_v1:InverterControl",
        {},
        INVERTER_CONTROL_PORTS,
    ),
    CompanionFixture(
        "initialization",
        "cigre_lcc_v1:Initialization",
        {},
        ("IORDER", "GAMMA_ORDER", "ENABLE_RECT", "ENABLE_INV"),
    ),
    CompanionFixture(
        "signal_interface",
        "cigre_lcc_v1:SignalInterface",
        {},
        ("VDC_RECT", "VDC_INV", "IDC"),
    ),
)
```

Implement `run_companion_component_gate(service, assets, workspace, *, master_path, registry_path, expected_master_sha256, expected_registry_sha256)` to materialize and audit the library once, load it, create one fresh case per fixture, instantiate the Definition, read back exact definition/parameters/ports, save, hash, reload, repeat read-back, compile, save, and hash again. On failure, record the current fixture and operation, stop creating later fixtures, retain all files, and return `FAIL`. Re-read `master_path` and `registry_path` before every compile and after the final fixture.

- [ ] **Step 4: Run focused tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_companion_gate.py tests/test_lcc_companion.py -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/hvdc/builders/lcc/companion_gate.py tests/test_lcc_companion_gate.py
git add pscad_mcp/hvdc/builders/lcc/companion_gate.py tests/test_lcc_companion_gate.py
git commit -m "feat: compile isolated LCC companion fixtures"
```

## Phase B: Durable Evidence, Licensed Run, and Promotion

### Task 8: Add the Strict Fixed-Smoke Report and Scoped Promotion

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/fixed_acceptance.py`
- Create: `tests/test_lcc_fixed_acceptance.py`

- [ ] **Step 1: Write failing strict-schema and promotion tests**

Create `tests/test_lcc_fixed_acceptance.py` with a complete `valid_fixed_report()` fixture and these tests:

```python
def test_valid_fixed_report_is_simulated_pass_with_exact_exclusions():
    normalized = validate_fixed_lcc_acceptance_report(valid_fixed_report())

    assert normalized["scope"] == "lcc.fixed_autonomous"
    assert normalized["builder_path"] == "lcc.fixed_autonomous"
    assert normalized["capability_state"] == "simulated"
    assert normalized["status"] == "PASS"
    assert tuple(normalized["explicit_exclusions"]) == FIXED_EXCLUSIONS
    assert normalized["smoke"]["verdict"] == "PASS"
    assert normalized["component_gate"]["status"] == "PASS"


@pytest.mark.parametrize(
    "field",
    [
        "component_gate",
        "smoke",
        "runtime",
        "explicit_exclusions",
        "sources",
    ],
)
def test_pass_report_rejects_missing_evidence(field):
    payload = valid_fixed_report()
    payload.pop(field)

    with pytest.raises(BackendError) as failure:
        validate_fixed_lcc_acceptance_report(payload)

    assert failure.value.code == "LCC_FIXED_REPORT_INVALID"


def test_fail_report_is_durable_but_not_promotable(tmp_path):
    payload = valid_fixed_report()
    payload["status"] = "FAIL"
    payload["capability_state"] = "failed"
    payload["smoke"] = None
    payload["failure"] = {
        "stage": "full_compile",
        "code": "LCC_BUILD_FAILED",
        "message": "compile failed",
    }
    payload["build"]["terminal_state"] = "failed"
    payload["build"]["history"] = ["validated", "compiled", "failed"]
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")

    assert validate_fixed_lcc_acceptance_report(payload)["status"] == "FAIL"
    with pytest.raises(BackendError):
        promote_fixed_lcc_report(tmp_path / "baseline.json", report)


def test_promotion_pins_report_hash_and_fixed_scope(monkeypatch, tmp_path):
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(valid_fixed_report(), sort_keys=True),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        fixed_acceptance,
        "_verify_fixed_report_files",
        lambda payload: None,
    )
    monkeypatch.setattr(
        fixed_acceptance,
        "_validate_fixed_baseline_identities",
        lambda baseline, payload: None,
    )

    promote_fixed_lcc_report(
        tmp_path / "baseline.json",
        report,
        promotion_action=lambda *args, **kwargs: calls.append(
            (args, kwargs)
        ) or {},
    )

    assert calls[0][1]["expected_scope"] == "lcc.fixed_autonomous"
    assert calls[0][1]["expected_builder_path"] == "lcc.fixed_autonomous"
    assert calls[0][1]["expected_report_sha256"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()
```

The valid fixture must populate every exact report key listed below with real 64-character lowercase hashes, six component fixture records, exact success history, finite smoke evidence, and zero remaining processes.

- [ ] **Step 2: Run tests and verify import failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_fixed_acceptance.py -q
```

Expected: collection FAIL because `fixed_acceptance.py` does not exist.

- [ ] **Step 3: Implement constants and exact report key sets**

Create `fixed_acceptance.py`:

```python
FIXED_SCOPE = "lcc.fixed_autonomous"
FIXED_BUILDER_PATH = "lcc.fixed_autonomous"
FIXED_KIND = "licensed_simulation"
FIXED_CAPABILITY = "simulated"
FIXED_OWNER = "WP1"
FIXED_EXCLUSIONS = (
    "disturbance_acceptance",
    "commutation_failure_acceptance",
    "independent_golden",
    "final_accepted",
)
SUCCESS_HISTORY = (
    "validated",
    "staging_created",
    "components_placed",
    "parameters_verified",
    "connections_verified",
    "structure_verified",
    "staging_saved",
    "compiled",
    "simulated",
    "smoke_passed",
    "published",
)
REPORT_KEYS = {
    "schema_version",
    "run_id",
    "scope",
    "builder_path",
    "kind",
    "capability_state",
    "commit",
    "generated_at_utc",
    "status",
    "repository",
    "preflight",
    "sources",
    "component_gate",
    "build",
    "artifacts",
    "smoke",
    "runtime",
    "explicit_exclusions",
    "failure",
}
SOURCE_KEYS = {
    "master",
    "registry",
    "asset_manifest",
    "catalog",
    "blueprint",
    "library",
    "smoke_contract",
    "provenance",
}
BUILD_KEYS = {
    "project_name",
    "workspace",
    "build_id",
    "plan_hash",
    "verification_profile",
    "journal_path",
    "journal_sha256",
    "history",
    "terminal_state",
}
ARTIFACT_KEYS = {
    "project",
    "library",
    "selected_output",
    "output_parts",
    "output_metadata",
}
```

Use the WP1A report as a behavioral reference, but define fixed-owned private helpers in this module: exact mappings, nonempty text, SHA-256, regular path/reparse rejection, UTC metadata, preflight validation, runtime validation, PASS/FAIL artifacts, atomic write, and 16 MiB bounded report load. Do not import private functions from `native_acceptance.py`.

- [ ] **Step 4: Implement status-aware validation**

Implement this entry point:

```python
def validate_fixed_lcc_acceptance_report(value: Any) -> dict[str, Any]:
    report = _exact_record(value, "report", REPORT_KEYS)
    metadata = build_run_metadata(
        run_id=_text(report["run_id"], "run_id"),
        scope=_text(report["scope"], "scope"),
        kind=_text(report["kind"], "kind"),
        capability_state=_text(
            report["capability_state"],
            "capability_state",
        ),
        commit=_text(report["commit"], "commit"),
        generated_at_utc=_text(
            report["generated_at_utc"],
            "generated_at_utc",
        ),
    )
    if (
        metadata["scope"] != FIXED_SCOPE
        or metadata["builder_path"] != FIXED_BUILDER_PATH
        or report["builder_path"] != FIXED_BUILDER_PATH
    ):
        raise _error("scope", "The report is not owned by fixed LCC.")
    status = _text(report["status"], "status")
    if status not in {"PASS", "FAIL"}:
        raise _error("status", "Fixed status must be PASS or FAIL.")
    if tuple(report["explicit_exclusions"]) != FIXED_EXCLUSIONS:
        raise _error(
            "explicit_exclusions",
            "Fixed exclusions are not exact.",
        )
    component_gate = _validate_component_gate(
        report["component_gate"],
        require_pass=status == "PASS",
    )
    build = _validate_build(
        report["build"],
        require_published=status == "PASS",
    )
    runtime = _validate_runtime(
        report["runtime"],
        require_licensed=status == "PASS",
    )
    sources = _validate_sources(
        report["sources"],
        require_immutable=status == "PASS",
    )
    if status == "PASS":
        if metadata["capability_state"] != FIXED_CAPABILITY:
            raise _error("capability_state", "PASS must remain simulated.")
        if tuple(build["history"]) != SUCCESS_HISTORY:
            raise _error("build.history", "PASS history is not exact.")
        smoke = _validate_smoke(report["smoke"])
        artifacts = _validate_pass_artifacts(report["artifacts"])
        if (
            report["failure"] is not None
            or runtime["quit_error"] is not None
            or runtime["remaining_processes"]
        ):
            raise _error("failure", "PASS contains failure evidence.")
        failure = None
    else:
        if metadata["capability_state"] != "failed":
            raise _error("capability_state", "FAIL must use failed.")
        if report["smoke"] is not None:
            raise _error("smoke", "FAIL cannot contain PASS smoke.")
        smoke = None
        artifacts = _validate_fail_artifacts(report["artifacts"])
        failure = _validate_failure(report["failure"])
    return {
        **metadata,
        "status": status,
        "repository": _validate_repository(report["repository"], metadata),
        "preflight": _validate_preflight(
            report["preflight"],
            require_pass=status == "PASS",
        ),
        "sources": sources,
        "component_gate": component_gate,
        "build": build,
        "artifacts": artifacts,
        "smoke": smoke,
        "runtime": runtime,
        "explicit_exclusions": list(FIXED_EXCLUSIONS),
        "failure": failure,
    }
```

- [ ] **Step 5: Implement disk revalidation and fixed-only promotion**

For PASS, verify every source/artifact path and hash against disk, reparse the registry semantic hash, rerun physical companion audit, and require program baseline Master/compiler/fixed-asset identities.

```python
def promote_fixed_lcc_report(
    baseline_path: Path,
    report_path: Path,
    *,
    promotion_action: Callable[..., dict[str, Any]] = promote_program_report,
) -> dict[str, Any]:
    report, indexed = load_fixed_lcc_acceptance_report(report_path)
    if report["status"] != "PASS":
        raise _error("status", "Only PASS fixed reports may be promoted.")
    _verify_fixed_report_files(report)
    _validate_fixed_baseline_identities(baseline_path, report)
    return promotion_action(
        baseline_path,
        report_path,
        expected_scope=FIXED_SCOPE,
        expected_builder_path=FIXED_BUILDER_PATH,
        expected_kind=FIXED_KIND,
        expected_capability_state=FIXED_CAPABILITY,
        expected_owner_work_package=FIXED_OWNER,
        expected_exclusions=FIXED_EXCLUSIONS,
        expected_report_sha256=indexed["sha256"],
    )
```

- [ ] **Step 6: Run report tests and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_fixed_acceptance.py tests/test_program_baseline_promotion.py -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/hvdc/builders/lcc/fixed_acceptance.py tests/test_lcc_fixed_acceptance.py
git add pscad_mcp/hvdc/builders/lcc/fixed_acceptance.py tests/test_lcc_fixed_acceptance.py
git commit -m "feat: report fixed LCC smoke evidence"
```

### Task 9: Add Fixed Acceptance Orchestration, CLI, and Run-Only PowerShell

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/fixed_acceptance.py`
- Create: `pscad_mcp/hvdc/builders/lcc/fixed_acceptance_cli.py`
- Create: `scripts/run_fixed_lcc_smoke_acceptance.ps1`
- Modify: `tests/test_lcc_fixed_acceptance.py`
- Create: `tests/test_lcc_fixed_acceptance_cli.py`

- [ ] **Step 1: Write fake-orchestration red tests**

Add:

```python
def test_orchestrator_runs_component_gate_then_production_smoke(tmp_path):
    request = fixed_request(tmp_path)
    service = FakePscadService()
    builder = FakeFixedBuilder(request.workspace_root)
    calls = []

    result = asyncio.run(
        run_fixed_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            companion_gate_action=lambda *args, **kwargs: calls.append(
                "component_gate"
            ) or valid_component_gate(),
            process_reader=list,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "PASS"
    assert calls == ["component_gate"]
    assert builder.plan_calls[0]["verification_profile"] == "wp1b_smoke"
    assert builder.plan_calls[0]["simulation_duration_s"] == pytest.approx(0.1)
    assert request.report_path.is_file()
    assert service.calls == ["attach_local", ("quit_pscad", True)]


@pytest.mark.parametrize(
    ("failure_stage", "expected_stage"),
    [
        ("attach", "attach"),
        ("component_gate", "component_gate"),
        ("plan", "plan"),
        ("build", "build"),
        ("cleanup", "cleanup"),
        ("report", "report"),
    ],
)
def test_orchestrator_persists_fail_and_never_promotes(
    failure_stage,
    expected_stage,
    tmp_path,
):
    request, service, builder, gate = failing_orchestrator_inputs(
        tmp_path,
        failure_stage,
    )

    result = asyncio.run(
        run_fixed_lcc_acceptance(
            request,
            service=service,
            builder=builder,
            companion_gate_action=gate,
            process_reader=service.processes,
            poll_interval_s=0,
        )
    )

    assert result["status"] == "FAIL"
    assert result["failure"]["stage"] == expected_stage
    assert request.report_path.is_file()
    assert request.baseline_path.read_bytes() == b"unchanged baseline"
```

Define the test helpers in the same file. The fake builder must return a published record with exact `wp1b_smoke` history and real temporary project/library/output/journal files.

- [ ] **Step 2: Run tests and verify missing orchestrator**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_fixed_acceptance.py -k "orchestrator" -q
```

Expected: FAIL because request/orchestrator APIs are undefined.

- [ ] **Step 3: Implement immutable request and orchestration order**

Add:

```python
@dataclass(frozen=True)
class FixedLccAcceptanceRequest:
    repository_root: Path
    workspace_root: Path
    master_path: Path
    registry_path: Path
    asset_manifest_path: Path
    report_path: Path
    baseline_path: Path
    project_name: str
    commit: str
    branch: str
    preflight: Mapping[str, Any]
    simulation_duration_s: float = 0.1


async def run_fixed_lcc_acceptance(
    request: FixedLccAcceptanceRequest,
    *,
    service: Any,
    builder: Any,
    companion_gate_action: Callable[..., Any] = run_companion_component_gate,
    process_reader: Callable[
        [], Sequence[Mapping[str, Any]]
    ] = list_pscad_processes,
    poll_interval_s: float = 0.5,
    timeout_s: float = 900.0,
) -> dict[str, Any]:
    stage = "setup"
    report = _initial_fail_report(request)
    try:
        _validate_request_sources(request)
        stage = "attach"
        await service.attach_local()
        runtime = await service.status()
        _require_licensed_462_runtime(runtime)
        assets = load_packaged_asset_set()
        audited = audit_companion_bindings(
            request.master_path,
            assets.master_bindings,
        )
        stage = "component_gate"
        component_gate = await companion_gate_action(
            service,
            assets,
            request.workspace_root / "component-fixtures",
            master_path=request.master_path,
            registry_path=request.registry_path,
            expected_master_sha256=audited.master_sha256,
            expected_registry_sha256=audited.registry.sha256,
        )
        if component_gate["status"] != "PASS":
            raise BackendError(
                "LCC_COMPANION_COMPILE_FAILED",
                "An isolated companion fixture failed.",
                "hvdc",
                "run_fixed_lcc_acceptance",
                {"component_gate": component_gate},
            )
        stage = "plan"
        plan = builder.plan_model(
            request.project_name,
            folder=str(request.workspace_root / "full-topology"),
            simulation_duration_s=request.simulation_duration_s,
            verification_profile=WP1B_SMOKE_PROFILE,
        )
        stage = "build"
        started = await builder.build_model(
            request.project_name,
            plan["plan_hash"],
            folder=str(request.workspace_root / "full-topology"),
            simulation_duration_s=request.simulation_duration_s,
            verification_profile=WP1B_SMOKE_PROFILE,
            confirm=True,
        )
        record = await _poll_fixed_build(
            builder,
            str(started["build_id"]),
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        if record.get("state") != "published":
            raise BackendError(
                "LCC_FIXED_SMOKE_FAILED",
                "The fixed build did not publish.",
                "hvdc",
                "run_fixed_lcc_acceptance",
                {"record": record},
            )
        report = _pass_report_from_record(
            request,
            runtime,
            assets,
            audited,
            component_gate,
            record,
        )
    except BaseException as error:
        report = _fail_report(request, report, stage, error)
    finally:
        report = await _cleanup_and_finalize(
            request,
            service,
            builder,
            report,
            process_reader,
        )
    try:
        normalized = validate_fixed_lcc_acceptance_report(report)
    except BaseException as error:
        report = _fail_report(request, report, "report", error)
        normalized = validate_fixed_lcc_acceptance_report(report)
    _atomic_write_report(request.report_path, normalized)
    return normalized
```

`_pass_report_from_record()` must normalize the interleaved executor journal to state-only history before report validation:

```python
def _state_history(record: Mapping[str, Any]) -> list[str]:
    history = record.get("history")
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise _error("build.history", "Build history must be an array.")
    return [
        str(item["state"])
        for item in history
        if isinstance(item, Mapping) and isinstance(item.get("state"), str)
    ]
```

The returned list must equal `SUCCESS_HISTORY`; operation records remain in the durable journal but not in the report's state history.

`_cleanup_and_finalize()` must catch and encode every shutdown/quit/hash/process-reader exception rather than raise, call `builder.shutdown()` before `service.quit_pscad(confirm=True)`, rehash every immutable source and compiler input, record quit errors/processes, and force FAIL on any drift or remaining process.

- [ ] **Step 4: Write CLI and PowerShell contract tests**

Create `tests/test_lcc_fixed_acceptance_cli.py`:

```python
def test_run_action_writes_report_and_never_touches_baseline(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes(b"baseline")
    report = tmp_path / "run" / "fixed-lcc-report.json"

    exit_code = main(
        run_arguments(tmp_path, report),
        run_action=fake_pass_run,
        service_factory=fake_service_factory,
        preflight_action=fake_preflight,
    )

    assert exit_code == 0
    assert report.is_file()
    assert baseline.read_bytes() == b"baseline"


def test_promote_action_is_explicit(tmp_path):
    calls = []

    exit_code = main(
        [
            "promote",
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--report",
            str(tmp_path / "report.json"),
        ],
        promote_action=lambda *args, **kwargs: calls.append(
            (args, kwargs)
        ) or {},
    )

    assert exit_code == 0
    assert len(calls) == 1


def test_powershell_runner_is_run_only_and_checks_cleanup():
    script = (
        ROOT / "scripts" / "run_fixed_lcc_smoke_acceptance.ps1"
    ).read_text(encoding="utf-8")

    assert "fixed_acceptance_cli" in script
    assert "'run'" in script
    assert "'promote'" not in script
    assert "FIXED_LCC_REPORT_SHA256=" in script
    assert "Get-Process" in script
    assert "git status --porcelain" in script
    assert "Stop-Process" not in script
```

- [ ] **Step 5: Implement CLI actions**

Create `fixed_acceptance_cli.py` with subparsers `run` and `promote`. `run` requires repository/workspace/Master/compiler/report/commit/branch/project arguments, executes WP0 preflight, creates a Legacy backend with `definition_paths={"master": master_path}`, constructs `LccBuilderService`, and calls `run_fixed_lcc_acceptance()`. `promote` calls only `promote_fixed_lcc_report()`. Return 0 only for PASS or successful promotion.

- [ ] **Step 6: Implement the run-only PowerShell wrapper**

Create `scripts/run_fixed_lcc_smoke_acceptance.ps1`:

```powershell
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,
    [string]$MasterPath = 'C:\Program Files (x86)\PSCAD46\master.pslx',
    [Parameter(Mandatory = $true)]
    [string]$CompilerConfiguration,
    [Parameter(Mandatory = $true)]
    [string]$CompilerExecutable,
    [string]$ProjectName = 'WP1B_FIXED_LCC'
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Dirty = git -C $RepositoryRoot status --porcelain
if ($LASTEXITCODE -ne 0 -or $Dirty) {
    throw 'WP1B licensed run requires a clean named checkout.'
}
$Commit = git -C $RepositoryRoot rev-parse HEAD
$Branch = git -C $RepositoryRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or -not $Branch) {
    throw 'WP1B licensed run requires a named branch.'
}
$Existing = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like 'PSCAD*' })
if ($Existing.Count -ne 0) {
    throw 'Close external PSCAD processes before the WP1B run.'
}
$Stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
$RunRoot = Join-Path $WorkspaceRoot "fixed-lcc-$Stamp"
$Report = Join-Path $RunRoot 'fixed-lcc-acceptance-report.json'
$Python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
& $Python -m pscad_mcp.hvdc.builders.lcc.fixed_acceptance_cli run `
    --repository-root $RepositoryRoot `
    --workspace-root $RunRoot `
    --master-path $MasterPath `
    --compiler-configuration $CompilerConfiguration `
    --compiler-executable $CompilerExecutable `
    --report $Report `
    --commit $Commit `
    --branch $Branch `
    --project-name $ProjectName
if ($LASTEXITCODE -ne 0) {
    throw "WP1B fixed smoke failed; inspect $Report"
}
$Remaining = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like 'PSCAD*' })
if ($Remaining.Count -ne 0) {
    throw 'WP1B report cannot pass with remaining PSCAD processes.'
}
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Report).Hash.ToLowerInvariant()
Write-Output "FIXED_LCC_REPORT=$Report"
Write-Output "FIXED_LCC_REPORT_SHA256=$Hash"
```

- [ ] **Step 7: Run orchestration/CLI tests and parser check**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_fixed_acceptance.py tests/test_lcc_fixed_acceptance_cli.py -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/hvdc/builders/lcc/fixed_acceptance.py pscad_mcp/hvdc/builders/lcc/fixed_acceptance_cli.py tests/test_lcc_fixed_acceptance.py tests/test_lcc_fixed_acceptance_cli.py
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path 'scripts/run_fixed_lcc_smoke_acceptance.ps1'),
    [ref]$null,
    [ref]$errors
) | Out-Null
if ($errors.Count -ne 0) { throw ($errors | Out-String) }
```

Expected: tests PASS and parser reports zero errors.

- [ ] **Step 8: Commit Task 9**

```powershell
git add pscad_mcp/hvdc/builders/lcc/fixed_acceptance.py pscad_mcp/hvdc/builders/lcc/fixed_acceptance_cli.py scripts/run_fixed_lcc_smoke_acceptance.ps1 tests/test_lcc_fixed_acceptance.py tests/test_lcc_fixed_acceptance_cli.py
git commit -m "feat: orchestrate fixed LCC smoke acceptance"
```

### Task 10: Add Opt-In Licensed Phase A and Phase B Tests

**Files:**
- Create: `tests/test_lcc_fixed_acceptance_real.py`
- Modify: `tests/test_lcc_real_acceptance.py`

- [ ] **Step 1: Add one opt-in real test that executes both licensed gates**

Create `tests/test_lcc_fixed_acceptance_real.py`:

```python
@unittest.skipUnless(
    os.getenv("PSCAD_MCP_LCC_WP1B_ACCEPTANCE") == "1",
    "Set PSCAD_MCP_LCC_WP1B_ACCEPTANCE=1 for licensed fixed LCC acceptance.",
)
class TestFixedLccAcceptanceReal(unittest.TestCase):
    def test_current_commit_components_compile_and_full_smoke_passes(self):
        root = Path(__file__).parents[1]
        workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"]).resolve()
        master = Path(os.environ["PSCAD_MCP_MASTER_LIBRARY"]).resolve()
        compiler_configuration = Path(
            os.environ["PSCAD_MCP_COMPILER_CONFIGURATION"]
        ).resolve()
        compiler_executable = Path(
            os.environ["PSCAD_MCP_COMPILER_EXECUTABLE"]
        ).resolve()
        commit = git(root, "rev-parse", "HEAD")
        branch = git(root, "branch", "--show-current")
        run_root = workspace / (
            "fixed-lcc-test-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        )
        report = run_root / "fixed-lcc-acceptance-report.json"
        baseline = (
            root / "docs" / "acceptance" / "lcc-mmc-program-baseline.json"
        )
        baseline_before = sha256_file(baseline)

        exit_code = main(
            [
                "run",
                "--repository-root", str(root),
                "--workspace-root", str(run_root),
                "--master-path", str(master),
                "--compiler-configuration", str(compiler_configuration),
                "--compiler-executable", str(compiler_executable),
                "--report", str(report),
                "--commit", commit,
                "--branch", branch,
                "--project-name", "WP1B_FIXED_LCC_TEST",
            ]
        )

        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0, payload)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["component_gate"]["status"], "PASS")
        self.assertEqual(
            [item["fixture"] for item in payload["component_gate"]["fixtures"]],
            [
                "bridge_rectifier",
                "bridge_inverter",
                "rectifier_control",
                "inverter_control",
                "initialization",
                "signal_interface",
            ],
        )
        self.assertEqual(payload["build"]["terminal_state"], "published")
        self.assertEqual(payload["smoke"]["verdict"], "PASS")
        self.assertTrue(all(payload["smoke"]["checks"].values()))
        self.assertEqual(payload["runtime"]["remaining_processes"], [])
        self.assertEqual(sha256_file(baseline), baseline_before)
```

Implement `git()` locally rather than importing a test helper:

```python
def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
```

- [ ] **Step 2: Keep the old real-acceptance test explicitly full-acceptance only**

In `tests/test_lcc_real_acceptance.py` pass `verification_profile="full_acceptance"` in plan/build calls. Keep its existing environment flag and golden/physical expectations.

- [ ] **Step 3: Run offline collection and verify licensed tests skip**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_fixed_acceptance_real.py tests/test_lcc_real_acceptance.py -q
```

Expected: both licensed tests SKIP without flags, with no collection error.

- [ ] **Step 4: Commit Task 10**

```powershell
git add tests/test_lcc_fixed_acceptance_real.py tests/test_lcc_real_acceptance.py
git commit -m "test: add licensed fixed LCC smoke gate"
```

### Task 11: Run the Licensed Gates on a Clean Evidence Commit

**Files:**
- No production edits unless a licensed failure is first reproduced by an offline regression test.
- External evidence only under a fresh timestamp directory.

- [ ] **Step 1: Run full offline pre-licensed verification**

```powershell
git status --short --branch
git diff --check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/core/master_bindings.py pscad_mcp/hvdc/builders/lcc scripts/build_lcc_companion_library.py tests/test_master_binding_registry.py tests/test_master_definition_bindings.py tests/test_lcc_companion.py tests/test_lcc_smoke.py tests/test_lcc_companion_gate.py tests/test_lcc_fixed_acceptance.py tests/test_lcc_fixed_acceptance_cli.py tests/test_lcc_fixed_acceptance_real.py
```

Expected: offline tests PASS, licensed tests SKIP, Ruff PASS, and worktree clean.

- [ ] **Step 2: Verify runtime inputs and no external PSCAD process**

```powershell
Get-FileHash -Algorithm SHA256 'C:\Program Files (x86)\PSCAD46\master.pslx'
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PSCAD*' }
git rev-parse HEAD
git branch --show-current
```

Expected Master hash:
`062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939`. Expected process output: empty.

- [ ] **Step 3: Execute the run-only licensed wrapper**

```powershell
$env:PSCAD_MCP_LCC_WP1B_ACCEPTANCE = '1'
$RunOutput = @(.\scripts\run_fixed_lcc_smoke_acceptance.ps1 `
    -WorkspaceRoot 'D:\PSCAD-Workspace\lcc-wp1b-fixed-acceptance' `
    -CompilerConfiguration $env:PSCAD_MCP_COMPILER_CONFIGURATION `
    -CompilerExecutable $env:PSCAD_MCP_COMPILER_EXECUTABLE)
$ReportLine = $RunOutput | Where-Object { $_ -like 'FIXED_LCC_REPORT=*' }
$HashLine = $RunOutput | Where-Object { $_ -like 'FIXED_LCC_REPORT_SHA256=*' }
if (@($ReportLine).Count -ne 1 -or @($HashLine).Count -ne 1) {
    throw 'The wrapper did not return one report path and hash.'
}
$ReportPath = ($ReportLine -split '=', 2)[1]
$ReportHash = ($HashLine -split '=', 2)[1]
Write-Output $ReportPath
Write-Output $ReportHash
```

Expected: exit 0, one absolute report path, and one lowercase 64-character SHA-256. Keep `$ReportPath` for Steps 5 and 12. Do not promote yet.

- [ ] **Step 4: Handle any licensed failure through TDD**

For each failure:

1. retain the failed timestamp directory and report;
2. identify the earliest stage/error code;
3. add one minimal offline/fake regression reproducing that exact failure;
4. run it RED;
5. make the smallest production/asset correction;
6. run focused and full offline tests GREEN;
7. commit the correction;
8. rerun the licensed wrapper from the new clean commit.

Never edit a report or reuse a failed run directory.

- [ ] **Step 5: Revalidate the PASS report independently**

```powershell
.\.venv\Scripts\python.exe -c "import json,sys; from pathlib import Path; from pscad_mcp.hvdc.builders.lcc.fixed_acceptance import load_fixed_lcc_acceptance_report; p=Path(sys.argv[1]); r,i=load_fixed_lcc_acceptance_report(p); print(json.dumps({'status':r['status'],'commit':r['commit'],'scope':r['scope'],'report_sha256':i['sha256'],'fixtures':len(r['component_gate']['fixtures']),'smoke':r['smoke']['verdict']},sort_keys=True))" $ReportPath
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PSCAD*' }
```

Expected: PASS, current clean commit, fixed scope, six fixtures, smoke PASS, and zero processes.

### Task 12: Explicitly Promote Fixed Scope and Record Completion

**Files:**
- Modify: `docs/acceptance/lcc-mmc-program-baseline.json`
- Modify: `tests/test_lcc_mmc_program_baseline.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md`
- Create: `docs/superpowers/specs/2026-08-31-lcc-wp1b-fixed-autonomous-physicalization-completion.md`

- [ ] **Step 1: Run explicit promotion with the exact PASS report**

```powershell
.\.venv\Scripts\python.exe -m pscad_mcp.hvdc.builders.lcc.fixed_acceptance_cli promote `
    --baseline docs/acceptance/lcc-mmc-program-baseline.json `
    --report $ReportPath
```

Expected: only the program baseline changes. `lcc.fixed_autonomous` becomes `simulated/PASS` with the new evidence run ID. Existing commit-advancement rules invalidate older current-commit evidence; no other scope gains PASS.

- [ ] **Step 2: Add baseline regression assertions**

Add:

```python
def test_promoted_wp1b_scope_is_simulated_not_accepted():
    baseline = load_checked_in_program_baseline()
    fixed = next(
        item
        for item in baseline["scopes"]
        if item["scope"] == "lcc.fixed_autonomous"
    )

    assert fixed["builder_path"] == "lcc.fixed_autonomous"
    assert fixed["capability_state"] == "simulated"
    assert fixed["licensed_status"] == "PASS"
    assert isinstance(fixed["evidence_run_id"], str)
    assert fixed["explicit_exclusions"] == [
        "disturbance_acceptance",
        "commutation_failure_acceptance",
        "independent_golden",
        "final_accepted",
    ]
    assert not any(
        item["capability_state"] == "accepted"
        for item in baseline["scopes"]
        if item["scope"].startswith("lcc.")
    )
```

- [ ] **Step 3: Write the completion record from immutable evidence**

The completion record must list:

- evidence-bearing commit and branch;
- Master/registry/manifest/compiler before/after hashes;
- every Phase A/Phase B fixture and compile result;
- full-topology plan, journal, project, library, and output hashes;
- exact smoke time domain, sample count, finite/enable/AO checks;
- report path/hash/run ID/commit;
- promotion diff and explicit exclusions;
- focused/full test counts, Ruff result, PowerShell parse result, process count;
- review findings and correction commits;
- WP1C/WP6 handoff and excluded claims.

Do not write PASS until each value comes from the validated report or a fresh command.

- [ ] **Step 4: Update user documentation and roadmap truth**

Document separate run/promote commands and state that WP1B proves no-fault simulation only. WP1C remains responsible for disturbance/commutation/recovery; WP6 remains responsible for independent golden and final acceptance.

- [ ] **Step 5: Run post-promotion focused tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_lcc_mmc_program_baseline.py tests/test_acceptance_status_manifest.py tests/test_lcc_fixed_acceptance.py tests/test_lcc_fixed_acceptance_cli.py -q
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit promotion and completion evidence**

```powershell
git add docs/acceptance/lcc-mmc-program-baseline.json tests/test_lcc_mmc_program_baseline.py README.md docs/zh-CN/README.md docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md docs/superpowers/specs/2026-08-31-lcc-wp1b-fixed-autonomous-physicalization-completion.md
git commit -m "docs: record WP1B fixed LCC acceptance"
```

### Task 13: Final Verification and Independent Review

**Files:**
- No planned production changes; review fixes require their own TDD commit.

- [ ] **Step 1: Run final focused gates**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_master_binding_registry.py tests/test_master_definition_bindings.py tests/test_lcc_assets.py tests/test_lcc_asset_audit.py tests/test_lcc_catalog.py tests/test_lcc_companion.py tests/test_lcc_planner.py tests/test_lcc_smoke.py tests/test_lcc_executor.py tests/test_lcc_companion_gate.py tests/test_lcc_fixed_acceptance.py tests/test_lcc_fixed_acceptance_cli.py tests/test_lcc_fixed_acceptance_real.py tests/test_lcc_mmc_program_baseline.py -q
```

Expected: PASS with only opt-in licensed tests skipped.

- [ ] **Step 2: Run full suite and targeted lint**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check pscad_mcp/core/master_bindings.py pscad_mcp/hvdc/builders/lcc scripts/build_lcc_companion_library.py tests/test_master_binding_registry.py tests/test_master_definition_bindings.py tests/test_lcc_companion.py tests/test_lcc_smoke.py tests/test_lcc_companion_gate.py tests/test_lcc_fixed_acceptance.py tests/test_lcc_fixed_acceptance_cli.py tests/test_lcc_fixed_acceptance_real.py
git diff --check
```

Expected: zero failures, Ruff PASS, and no whitespace errors. Record fresh pass/skip counts.

- [ ] **Step 3: Parse PowerShell and recheck generated assets**

```powershell
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path 'scripts/run_fixed_lcc_smoke_acceptance.ps1'),
    [ref]$null,
    [ref]$errors
) | Out-Null
if ($errors.Count -ne 0) { throw ($errors | Out-String) }
.\.venv\Scripts\python.exe scripts/build_lcc_companion_library.py --output pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/library/cigre_lcc_v1.pslx --check
.\.venv\Scripts\python.exe scripts/audit_lcc_assets.py --asset-root pscad_mcp/assets/lcc/cigre_lcc_monopole_v1
```

Expected: zero parser errors, generator check exit 0, asset audit PASS.

- [ ] **Step 4: Request independent code review**

Use `superpowers:requesting-code-review` and review for:

- no vendor body or absolute path;
- exact FP=0/View=1 conditional AO evidence;
- two g6p200 instances and DC series path;
- four AO nets and no GATES alias;
- full-acceptance default not weakened;
- smoke never invokes golden/disturbance acceptance;
- FAIL/cleanup cannot promote;
- report commit/hash/source/registry/manifest/compiler binding;
- no wildcard process termination.

Every Critical or Important finding receives a failing regression, minimal fix, focused/full rerun, and separate commit.

- [ ] **Step 5: Perform final post-review verification**

```powershell
git status --short --branch
git diff --check
git log --oneline --decorate fbcf641..HEAD
.\.venv\Scripts\python.exe -m pytest -q
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PSCAD*' }
```

Expected: clean named branch, complete small-commit history, full suite PASS, zero PSCAD processes.

## Spec Coverage Matrix

| Approved design requirement | Implemented and verified by |
| --- | --- |
| FP=0/View=1 scalar AO correction and no gate-vector alias | Tasks 1, 2, 4, 13 |
| Two g6p200 groups, terminal UP profiles, and DC series path | Tasks 1, 2, 4, 7, 10 |
| Rectifier current PI and limiter | Tasks 4, 7, 10 |
| Inverter gamma PI, minimum feedback, and limiter | Tasks 4, 7, 10 |
| Deterministic enable, initialization, and real signal imports | Tasks 4, 7, 10 |
| Two transformer groups and four AO topology nets | Tasks 4, 5, 6 |
| Component compile before full compile | Tasks 7, 9, 10, 11 |
| Short no-fault finite/enabled/AO-bounded smoke | Tasks 3, 5, 6, 9, 11 |
| Source/Master/registry/manifest/compiler drift blocking | Tasks 1, 7, 8, 9 |
| Durable FAIL, owned cleanup, and no wildcard termination | Tasks 6, 7, 9, 13 |
| Separate run and fixed-only promotion | Tasks 8, 9, 12 |
| Explicit WP1C/WP6 exclusions and no accepted claim | Tasks 8, 12, 13 |
| Offline, fake-service, licensed, full-suite, lint, parser, and review gates | Tasks 1-13 |

## Completion Definition

Implementation is complete only when:

- the checked-in companion is a real PSCAD 4.6.2 library and passes offline physical audit;
- both bridge parameterizations and all four control/signal Definitions pass licensed load/read-back/reload/compile;
- the full fixed topology compiles from a blank case and completes the 0.1 s no-fault smoke;
- the report is current-commit, hash-complete, re-indexed, and PASS;
- source, Master, registry, manifest, library, compiler, and project identities remain immutable;
- zero PSCAD processes remain;
- explicit promotion changes only `lcc.fixed_autonomous` to `simulated/PASS`;
- disturbance, commutation-failure, independent-golden, and final `accepted` remain excluded;
- full tests, Ruff, PowerShell parsing, generator check, asset audit, and independent review pass;
- the worktree is clean and the completion record contains exact final evidence.
