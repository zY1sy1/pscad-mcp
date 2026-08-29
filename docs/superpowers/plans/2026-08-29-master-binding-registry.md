# Master Binding Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all eight logical `master:*` definitions in the fixed LCC catalog to semantically correct PSCAD 4.6.2 Master components, instantiate them with deterministic transforms, verify live read-back, and pass a licensed compile smoke test.

**Architecture:** A manifest-hashed JSON registry is the single source of logical-to-physical bindings. A strict core parser and live resolver audit that registry against the immutable installed `master.pslx`; the LCC planner embeds registry/source hashes and per-component physical evidence, while the Legacy backend applies the same evidence and reverses physical read-back to logical values. Conditional ports and the three-instance C-filter are handled explicitly rather than inferred from catalog labels.

**Tech Stack:** Python 3.10+, dataclasses, `xml.etree.ElementTree`, SHA-256, pytest, existing PSCAD 4.6.2 Legacy automation (`mhi-pscad`).

---

## File Map

- Create `pscad_mcp/core/master_bindings.py`: strict registry model, transforms, live audit, forward/reverse resolution, structured errors.
- Modify `pscad_mcp/core/definition_metadata.py`: preserve definition multiplicity, parameter type/unit/default/intent, port occurrence/model/mode/condition.
- Create `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json`: reviewed bindings for exactly eight logical Master entries.
- Modify `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json`: hash and package the registry.
- Modify `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/catalog-pscad-4.6.2.json`: remove duplicated physical mapping claims and point to the registry contract.
- Modify `pscad_mcp/hvdc/builders/lcc/assets.py`: load the verified registry into `LccAssetSet`.
- Modify `pscad_mcp/hvdc/builders/lcc/models.py`: retain binding/source hashes and evidence in serialized plans.
- Modify `pscad_mcp/hvdc/builders/lcc/planner.py`: require verified live evidence, resolve physical parameters, and hash all binding evidence.
- Modify `pscad_mcp/core/service.py`: pass the verified registry to live inventory and preserve its evidence.
- Modify `pscad_mcp/hvdc/builders/lcc/service.py`: re-audit source/registry during confirmed replanning.
- Modify `pscad_mcp/core/backend/legacy.py`: replace hard-coded maps, instantiate physical definitions, expand/ground filters, and reverse read-back.
- Modify `pscad_mcp/hvdc/builders/lcc/executor.py`: compare requested logical values plus expected physical binding evidence without special-case drops.
- Modify `pscad_mcp/hvdc/builders/lcc/native_template.py`: audit retained Master references through the same resolver.
- Create/update focused tests under `tests/test_master_binding_registry.py`, `tests/test_definition_metadata.py`, `tests/test_master_definition_bindings.py`, `tests/test_lcc_assets.py`, `tests/test_lcc_inventory.py`, `tests/test_lcc_planner.py`, `tests/test_lcc_executor.py`, and `tests/test_lcc_real_acceptance.py`.

### Task 1: Strict Registry Model and Packaged Contract

**Files:**
- Create: `pscad_mcp/core/master_bindings.py`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json`
- Test: `tests/test_master_binding_registry.py`

- [ ] **Step 1: Write failing parser tests**

```python
def test_registry_rejects_unknown_fields_and_duplicate_names():
    payload = valid_registry_payload()
    payload["unexpected"] = True
    with pytest.raises(BackendError, match="unknown") as failure:
        parse_master_binding_registry(payload)
    assert failure.value.code == "MASTER_BINDING_MISSING"

    payload = valid_registry_payload()
    payload["bindings"].append(dict(payload["bindings"][0]))
    with pytest.raises(BackendError) as failure:
        parse_master_binding_registry(payload)
    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"


def test_registry_contains_exact_fixed_catalog_bindings(packaged_assets):
    registry = packaged_assets.master_bindings
    assert set(registry.by_logical_name) == {
        "master:three_phase_source", "master:converter_transformer",
        "master:ac_filter_branch", "master:smoothing_reactor",
        "master:dc_line_section", "master:ac_meter",
        "master:dc_meter", "master:ground",
    }
    assert registry.by_logical_name["master:dc_line_section"].physical_definition == "resistor"
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `pytest -q tests/test_master_binding_registry.py`

Expected: collection fails because `pscad_mcp.core.master_bindings` and the registry asset do not exist.

- [ ] **Step 3: Implement immutable models and strict parsing**

Implement these public records and entry point; every object parser must compare `set(value)` to its exact allowed-key set, reject booleans as numbers, require positive dimensions/instance counts, and reject duplicate logical names:

```python
@dataclass(frozen=True)
class MasterPortBinding:
    logical: str
    physical: str
    kind: str
    dimension: int
    occurrence: int
    instance: str | None = None

@dataclass(frozen=True)
class MasterParameterBinding:
    logical: tuple[str, ...]
    physical: tuple[str, ...]
    transform: Mapping[str, Any]
    physical_contracts: Mapping[str, Mapping[str, Any]]

@dataclass(frozen=True)
class MasterBinding:
    logical_name: str
    physical_definition: str
    ports: tuple[MasterPortBinding, ...]
    parameters: tuple[MasterParameterBinding, ...]
    fixed_parameters: Mapping[str, Any]
    evidence_parameters: Mapping[str, Mapping[str, Any]]
    shape: Mapping[str, Any]

@dataclass(frozen=True)
class MasterBindingRegistry:
    schema_version: int
    name: str
    pscad_version: str
    bindings: tuple[MasterBinding, ...]
    sha256: str

    @property
    def by_logical_name(self) -> dict[str, MasterBinding]:
        return {item.logical_name: item for item in self.bindings}

```

Expose `parse_master_binding_registry(value: Any) -> MasterBindingRegistry` as
the only construction entry point; its exact accepted fields are the fields in
the records above plus the top-level `bindings` array.

The registry must encode these reviewed physical identities: `source3`, `xfmr-3p2w`, `cfilter`, `inductor`, `resistor`, `multimeter`, `multimeter`, and `ground`. It must also encode `View=0` for source/transformer, `Inductance_mH * 0.001 -> L`, transformer lookup tuples, filter phase expansion, `Resistance_ohm -> R`, and `Length_km` as hash-covered `evidence_parameters` rather than a PSCAD argument.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `pytest -q tests/test_master_binding_registry.py`

Expected: all registry parser and fixed-entry assertions pass.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/core/master_bindings.py pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/master-bindings-pscad-4.6.2.json tests/test_master_binding_registry.py
git commit -m "feat: add strict PSCAD master binding registry"
```

### Task 2: Lossless Master Metadata Reader

**Files:**
- Modify: `pscad_mcp/core/definition_metadata.py`
- Test: `tests/test_definition_metadata.py`

- [ ] **Step 1: Add failing metadata tests**

```python
def test_reader_preserves_duplicate_port_occurrences_and_parameter_contracts(tmp_path):
    path = write_definition_fixture(tmp_path)
    matches = read_definition_metadata_matches(path, "multimeter")
    assert len(matches) == 1
    assert [(p.name, p.occurrence) for p in matches[0].ports] == [("A", 0), ("A", 1)]
    assert matches[0].ports[1].condition == "MeasV!=0"
    parameter = matches[0].parameters["MeasV"]
    assert (parameter.type, parameter.unit, parameter.choices, parameter.default) == (
        "Choice", None, ("0", "1"), 0,
    )
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `pytest -q tests/test_definition_metadata.py`

Expected: missing `read_definition_metadata_matches`, occurrence, condition, and parameter metadata.

- [ ] **Step 3: Implement complete metadata records**

```python
@dataclass(frozen=True)
class ParameterMetadata:
    name: str
    type: str | None
    unit: str | None
    minimum: int | float | None
    maximum: int | float | None
    choices: tuple[str, ...]
    default: object
    intent: str | None
    readonly: bool

@dataclass(frozen=True)
class PortMetadata:
    name: str
    x: int
    y: int
    dim: int | None
    type: str | None
    model: str | None = None
    kind: str | None = None
    mode: str | None = None
    condition: str | None = None
    occurrence: int = 0
    page: bool = False

@dataclass(frozen=True)
class DefinitionMetadata:
    name: str
    description: str | None
    ports: tuple[PortMetadata, ...]
    parameters: dict[str, ParameterMetadata]
    parameter_ranges: dict[str, object]

```

Add `read_definition_metadata_matches(path, name)` returning every matching
`DefinitionMetadata` in source order.

Keep `read_definition_metadata()` as a compatibility wrapper that requires exactly one match. Normalize neither kind nor dimension in the XML reader; normalization belongs to the binding auditor and remains visible in evidence.

- [ ] **Step 4: Run reader and compatibility tests**

Run: `pytest -q tests/test_definition_metadata.py tests/test_legacy_support.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/core/definition_metadata.py tests/test_definition_metadata.py
git commit -m "feat: preserve complete PSCAD definition metadata"
```

### Task 3: Live Audit and Deterministic Transforms

**Files:**
- Modify: `pscad_mcp/core/master_bindings.py`
- Test: `tests/test_master_binding_registry.py`
- Test: `tests/test_master_definition_bindings.py`

- [ ] **Step 1: Add failing live-audit and transform tests**

```python
def test_audit_rejects_ambiguous_and_wrong_kind_ports(master_fixture, registry):
    with pytest.raises(BackendError) as failure:
        audit_master_bindings(master_fixture, registry_with_missing_occurrence(registry))
    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"


def test_transform_round_trips_fixed_blueprint_values(audited_registry):
    reactor = audited_registry.resolve_component(
        "master:smoothing_reactor", {"Inductance_mH": 100.0}
    )
    assert reactor.physical_parameters["L"] == pytest.approx(0.1)
    assert reactor.logical_parameters({"L": 0.1})["Inductance_mH"] == pytest.approx(100.0)

    transformer = audited_registry.resolve_component(
        "master:converter_transformer",
        {"Ratio": 1.0, "Connection": "Y-delta", "PhaseShift_deg": 30.0},
    )
    assert transformer.physical_parameters | {"View": 0} >= {
        "V1": 230.0, "V2": 230.0, "YD1": 0, "YD2": 1, "Lead": 1,
    }


def test_filter_transform_is_per_phase_and_uses_harmonic_order(audited_registry):
    resolved = audited_registry.resolve_component(
        "master:ac_filter_branch",
        {"Branch_MVAR": 50.0, "Tuning_Hz": 300.0},
    )
    assert resolved.instances == ("A", "B", "C")
    assert resolved.physical_parameters["Q"] == pytest.approx(50.0 / 3.0)
    assert resolved.physical_parameters["f0"] == 50.0
    assert resolved.physical_parameters["h"] == 6.0
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/test_master_binding_registry.py tests/test_master_definition_bindings.py`

Expected: audit and resolution APIs are absent.

- [ ] **Step 3: Implement audit, hashes, and supported transforms**

Implement `audit_master_bindings(master_path, registry)` so it computes the raw file SHA-256 before parsing, requires one physical definition, selects ports by zero-based occurrence, maps `Natural -> electrical` and scalar `dim in {None, 0} -> 1`, validates parameter type/unit/choice contracts, and returns immutable evidence. Support only these transform kinds: `identity`, `scale`, `lookup_bundle`, `ratio_from_fixed_base`, `harmonic_order`, and `evidence_only`. Unknown or non-invertible values raise `MASTER_TRANSFORM_UNSUPPORTED`.

```python
@dataclass(frozen=True)
class AuditedMasterRegistry:
    registry: MasterBindingRegistry
    master_path: str
    master_sha256: str
    definitions: Mapping[str, Mapping[str, Any]]
```

Its `resolve_component(logical_name, parameters)` method returns a
`ResolvedMasterComponent` with physical definition, physical parameters,
logical evidence-only values, instances, selected ports, forward evidence, and
an inverse read-back callable represented by the same typed transform records.

Use the exact error codes from the design: `MASTER_BINDING_MISSING`, `MASTER_BINDING_AMBIGUOUS`, `MASTER_PORT_MISMATCH`, `MASTER_PARAMETER_MISMATCH`, and `MASTER_TRANSFORM_UNSUPPORTED`.

- [ ] **Step 4: Run transform/audit tests and confirm GREEN**

Run: `pytest -q tests/test_master_binding_registry.py tests/test_master_definition_bindings.py`

Expected: all pass, including reverse transforms and unsupported tuple failures.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/core/master_bindings.py tests/test_master_binding_registry.py tests/test_master_definition_bindings.py
git commit -m "feat: audit and resolve live master bindings"
```

### Task 4: Asset Loader and Manifest Integration

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/assets.py`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/catalog-pscad-4.6.2.json`
- Test: `tests/test_lcc_assets.py`
- Test: `tests/test_lcc_asset_audit.py`

- [ ] **Step 1: Add failing asset tests**

```python
def test_asset_set_loads_manifest_hashed_master_registry():
    assets = load_packaged_asset_set()
    assert assets.master_bindings.schema_version == 1
    assert assets.master_binding_hash == assets.hashes["master-bindings-pscad-4.6.2.json"]


def test_asset_loader_rejects_registry_hash_or_catalog_reference_drift(asset_copy):
    mutate_registry_without_updating_manifest(asset_copy)
    with pytest.raises(BackendError) as failure:
        load_asset_set(asset_copy)
    assert failure.value.code == "LCC_ASSET_MISMATCH"
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/test_lcc_assets.py tests/test_lcc_asset_audit.py`

Expected: `LccAssetSet` has no registry fields and the manifest does not list the file.

- [ ] **Step 3: Load the registry only after manifest verification**

Add `master_bindings: MasterBindingRegistry` and `master_binding_hash: str` to `LccAssetSet`, require `master-bindings-pscad-4.6.2.json`, parse its already-hash-verified bytes, and require catalog metadata `master_binding_registry` to name the same asset. Remove `master_definition`, `port_mapping`, and numeric pseudo-parameters from per-definition catalog metadata so there is one authority.

- [ ] **Step 4: Recompute canonical manifest hashes**

Run the repository's canonical JSON hash helper from a one-line Python command and update only changed entries in `manifest.json`.

Run: `pytest -q tests/test_lcc_assets.py tests/test_lcc_asset_audit.py tests/test_lcc_production_assets.py`

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/lcc/assets.py pscad_mcp/assets/lcc/cigre_lcc_monopole_v1 tests/test_lcc_assets.py tests/test_lcc_asset_audit.py
git commit -m "feat: package LCC master binding registry"
```

### Task 5: Live Inventory Evidence

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/service.py`
- Test: `tests/test_lcc_inventory.py`
- Test: `tests/test_lcc_builder_service.py`

- [ ] **Step 1: Add failing inventory tests**

```python
def test_legacy_inventory_reports_registry_and_live_master_evidence(master_fixture, registry):
    inventory = asyncio.run(backend(master_fixture).lcc_definition_inventory(CATALOG, registry.to_dict()))
    assert inventory["master_sha256"] == sha256_file(master_fixture)
    assert inventory["master_binding_registry_sha256"] == registry.sha256
    source = inventory["definitions"]["master:three_phase_source"]
    assert source["physical_definition"] == "source3"
    assert source["selected_ports"]["A"]["occurrence"] == 0
    assert source["verification_state"] == "verified"
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/test_lcc_inventory.py tests/test_lcc_builder_service.py`

Expected: inventory methods accept no registry and expose no hashes/evidence.

- [ ] **Step 3: Wire the audited registry through service inventory**

Change the optional signatures to `get_lcc_inventory(catalog, master_binding_registry=None)` and `lcc_definition_inventory(catalog, master_binding_registry=None)`. The LCC builder always supplies `asset_set.master_bindings.to_dict()`. Legacy must call `audit_master_bindings`; catalog ports remain logical contracts, never live evidence. Preserve the existing one-argument path for unrelated callers.

- [ ] **Step 4: Run inventory/service tests**

Run: `pytest -q tests/test_lcc_inventory.py tests/test_lcc_builder_service.py tests/test_lcc_tools.py`

Expected: all pass and all eight definitions are `verified` against one Master hash.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/core/backend/legacy.py pscad_mcp/core/service.py pscad_mcp/hvdc/builders/lcc/service.py tests/test_lcc_inventory.py tests/test_lcc_builder_service.py
git commit -m "feat: expose audited live master inventory"
```

### Task 6: Planner Physical Evidence and Hash Invalidation

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/models.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/planner.py`
- Test: `tests/test_lcc_planner.py`

- [ ] **Step 1: Add failing planner tests**

```python
def test_plan_contains_resolved_master_evidence(asset_set, live_inventory, tmp_path):
    plan = create_plan(request(tmp_path), asset_set, live_inventory, tmp_path)
    source = next(op for op in plan.operations if op.target == "rectifier_source")
    assert source.arguments["binding"]["physical_definition"] == "source3"
    assert source.arguments["binding"]["physical_parameters"]["View"] == 0
    assert plan.master_sha256 == live_inventory["master_sha256"]
    assert plan.master_binding_registry_sha256 == asset_set.master_binding_hash


def test_plan_hash_changes_with_registry_or_master_source(asset_set, live_inventory, tmp_path):
    first = create_plan(request(tmp_path), asset_set, live_inventory, tmp_path)
    second = create_plan(request(tmp_path), changed_registry(asset_set), live_inventory, tmp_path)
    third = create_plan(request(tmp_path), asset_set, changed_master_hash(live_inventory), tmp_path)
    assert len({first.plan_hash, second.plan_hash, third.plan_hash}) == 3
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/test_lcc_planner.py`

Expected: plan fields/evidence are absent.

- [ ] **Step 3: Resolve every Master component before operation generation**

Reject inventories without matching registry/master hashes or per-definition verified evidence. Add serialized `binding` evidence to every Master `place_component` and `verify_parameters` operation. Keep the public logical definition in `definition`; include physical definition, selected occurrences, physical parameters, reverse expectations, shape adapter, registry hash, and Master hash under `binding`. Add both hashes to `LccBuildPlan` and the canonical plan-hash payload.

- [ ] **Step 4: Run planner tests and confirm GREEN**

Run: `pytest -q tests/test_lcc_planner.py tests/test_lcc_inventory.py`

Expected: all pass; stale/missing/ambiguous evidence fails before any build mutation.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/lcc/models.py pscad_mcp/hvdc/builders/lcc/planner.py tests/test_lcc_planner.py
git commit -m "feat: bind LCC plans to physical master evidence"
```

### Task 7: Legacy Instantiation and Reverse Read-back

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/executor.py`
- Test: `tests/test_master_definition_bindings.py`
- Test: `tests/test_lcc_executor.py`

- [ ] **Step 1: Add failing runtime tests**

```python
@pytest.mark.parametrize("logical,physical", [
    ("three_phase_source", "source3"),
    ("converter_transformer", "xfmr-3p2w"),
    ("smoothing_reactor", "inductor"),
    ("dc_line_section", "resistor"),
    ("ac_meter", "multimeter"),
    ("dc_meter", "multimeter"),
    ("ground", "ground"),
])
def test_legacy_adds_real_physical_definition_and_round_trips(logical, physical, legacy_fake):
    created = asyncio.run(add_bound_component(legacy_fake, logical))
    assert legacy_fake.canvas.created[-1].definition == physical
    assert created.definition == f"master:{logical}"


def test_reactor_readback_is_returned_in_logical_millihenries(legacy_fake):
    created = asyncio.run(add_bound_component(legacy_fake, "smoothing_reactor", {"Inductance_mH": 100.0}))
    assert legacy_fake.component(created.id).parameters["L"] == pytest.approx(0.1)
    assert asyncio.run(legacy_fake.backend.get_component_parameters("case", created.id))["Inductance_mH"] == pytest.approx(100.0)
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `pytest -q tests/test_master_definition_bindings.py tests/test_lcc_executor.py`

Expected: hard-coded maps still choose incorrect definitions/drop values and reverse scaling fails.

- [ ] **Step 3: Replace hard-coded binding logic**

Store a typed runtime binding state per logical component containing physical IDs, exact port occurrences, forward/reverse transforms, registry hash, and Master hash. `add_component` must resolve and set all physical parameters before applying orientation, verify physical definition/location/parameters, then expose the logical identity. `get_component_parameters` must apply reverse transforms; `get_component_ports` must use the selected occurrence's static offset instead of collapsing duplicate names.

Remove the executor's `Connection` special case. A mismatch in definition, transformed parameter, selected port, registry hash, or source hash raises `MASTER_READBACK_FAILED` before save/compile/publication.

- [ ] **Step 4: Run runtime/executor tests and confirm GREEN**

Run: `pytest -q tests/test_master_definition_bindings.py tests/test_lcc_executor.py tests/test_legacy_support.py`

Expected: all direct bindings instantiate/read back and no parameter is silently dropped.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/core/backend/legacy.py pscad_mcp/core/service.py pscad_mcp/hvdc/builders/lcc/executor.py tests/test_master_definition_bindings.py tests/test_lcc_executor.py
git commit -m "feat: instantiate and verify physical master components"
```

### Task 8: Three-phase C-filter Expansion and Neutral Grounding

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py`
- Test: `tests/test_master_definition_bindings.py`

- [ ] **Step 1: Add failing expansion tests**

```python
def test_filter_expands_three_instances_and_grounds_every_neutral(legacy_fake):
    created = asyncio.run(add_bound_component(
        legacy_fake, "ac_filter_branch", {"Branch_MVAR": 50.0, "Tuning_Hz": 300.0}
    ))
    assert [item.definition for item in legacy_fake.canvas.created].count("cfilter") == 3
    assert [item.definition for item in legacy_fake.canvas.created].count("ground") == 3
    assert legacy_fake.neutral_connections == [
        ("A", "N", "ground", "A"),
        ("B", "N", "ground", "A"),
        ("C", "N", "ground", "A"),
    ]
    assert set(asyncio.run(legacy_fake.backend.get_component_ports("case", created.id))) >= {
        "IN_A", "OUT_A", "IN_B", "OUT_B", "IN_C", "OUT_C"
    }
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `pytest -q tests/test_master_definition_bindings.py -k filter`

Expected: current expansion has no grounds/wires and applies wrong `f0/Q` values.

- [ ] **Step 3: Implement registry-driven expansion**

Create one `cfilter` and one `ground` per declared phase at registry offsets. Set `dentry=1`, `f0=50`, `h=Tuning_Hz/50`, `V=230/sqrt(3)`, and `Q=Branch_MVAR/3` on each filter. Connect each selected `N` occurrence to its ground `A` using real port coordinates and store all created IDs in the runtime binding state. Roll back newly created expansion members if any creation, parameter, port, or wire postcondition fails.

- [ ] **Step 4: Run expansion and related routing tests**

Run: `pytest -q tests/test_master_definition_bindings.py -k filter tests/test_lcc_routing.py tests/test_lcc_executor.py`

Expected: all pass with explicit neutral evidence.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/core/backend/legacy.py tests/test_master_definition_bindings.py
git commit -m "feat: expand and ground physical C filters"
```

### Task 9: Native Blank Audit and Licensed Compile Gate

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/native_template.py`
- Modify: `tests/test_lcc_native_template.py`
- Modify: `tests/test_lcc_real_acceptance.py`
- Modify: `tests/test_lcc_real_acceptance_contract.py`

- [ ] **Step 1: Add failing native/source-integrity contract tests**

```python
def test_native_template_master_references_are_audited(native_fixture, audited_registry):
    report = audit_native_lcc_template(native_fixture, master_registry=audited_registry)
    assert report.master_binding_registry_sha256 == audited_registry.registry.sha256
    assert report.master_sha256 == audited_registry.master_sha256


def test_master_compile_report_requires_all_eight_and_source_unchanged(tmp_path):
    report = complete_master_compile_report(tmp_path)
    assert validate_master_compile_report(report)["status"] == "PASS"
    report["master_after_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Master source"):
        validate_master_compile_report(report)
```

- [ ] **Step 2: Run contract tests and confirm RED**

Run: `pytest -q tests/test_lcc_native_template.py tests/test_lcc_real_acceptance_contract.py`

Expected: native audit/report fields are absent.

- [ ] **Step 3: Implement the compile-only binding smoke path**

Add an opt-in licensed test selected by `PSCAD_MCP_MASTER_BINDING_ACCEPTANCE=1`. It must snapshot `master.pslx`, create a timestamped project under `PSCAD_MCP_WORKSPACE`, audit all eight logical bindings, instantiate seven direct logical components plus all three physical filters/grounds, read back definitions/ports/physical parameters, save, compile, and write `master-binding-acceptance-report.json`. A PASS report requires build success, every binding's read-back evidence, matching registry/master hashes, and identical Master hash before/after. It must not claim waveform or commutation-fault acceptance.

- [ ] **Step 4: Run offline contracts, then licensed smoke**

Run: `pytest -q tests/test_lcc_native_template.py tests/test_lcc_real_acceptance_contract.py`

Expected: pass.

Run (licensed machine):

```powershell
$env:PSCAD_MCP_MASTER_BINDING_ACCEPTANCE='1'
$env:PSCAD_MCP_WORKSPACE='D:\PSCAD-Workspace\master-binding-acceptance'
$env:PSCAD_MCP_VERSION='4.6.2'
$env:PSCAD_MCP_X64='true'
pytest -q tests/test_lcc_real_acceptance.py -k master_binding_compile -s
```

Expected: one PASS; report lists eight verified logical bindings, three `cfilter` instances, compile success, and unchanged Master SHA-256.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/lcc/native_template.py tests/test_lcc_native_template.py tests/test_lcc_real_acceptance.py tests/test_lcc_real_acceptance_contract.py
git commit -m "test: gate master bindings with licensed compile evidence"
```

### Task 10: Documentation, Full Regression, and Branch Review

**Files:**
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/PROVENANCE.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-29-master-binding-registry-design.md`

- [ ] **Step 1: Document the authoritative registry and corrected mappings**

Document that `dc_mac_2w` is rejected because it is a DC machine, `resistor:R` is the fixed blueprint's total-resistance line model, `xfmr-3p2w` is backed by official CIGRE LCC examples, `Length_km` is evidence-only, and only a fresh licensed compile report may be called accepted.

- [ ] **Step 2: Run focused verification**

Run:

```powershell
pytest -q tests/test_master_binding_registry.py tests/test_definition_metadata.py tests/test_master_definition_bindings.py tests/test_lcc_assets.py tests/test_lcc_asset_audit.py tests/test_lcc_inventory.py tests/test_lcc_planner.py tests/test_lcc_executor.py tests/test_lcc_native_template.py tests/test_lcc_real_acceptance_contract.py
```

Expected: all pass.

- [ ] **Step 3: Run lint and full suite**

Run: `ruff check pscad_mcp tests`

Expected: no violations.

Run: `pytest -q`

Expected: all non-licensed tests pass; only explicitly licensed acceptance tests skip.

- [ ] **Step 4: Inspect branch evidence**

Run:

```powershell
git status --short
git diff --check main...HEAD
git log --oneline main..HEAD
```

Expected: no whitespace errors, no uncommitted implementation files, and task-sized commits.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/PROVENANCE.md docs/superpowers/specs/2026-08-29-master-binding-registry-design.md
git commit -m "docs: explain verified master binding runtime"
```

## Self-review Results

- Spec coverage: registry/version/hash, exact eight-entry scope, full metadata, ambiguity handling, transforms, filter expansion/grounding, planner evidence, read-back, stale-source failure, native audit, and licensed compile/source-integrity gate are each assigned to a task.
- Placeholder scan: no executable ellipsis, `TBD`, deferred implementation, or unspecified generic error-handling step remains. The `tuple[T, ...]` occurrences are Python variadic tuple type syntax, not placeholders.
- Type consistency: `MasterBindingRegistry`, `AuditedMasterRegistry`, `ResolvedMasterComponent`, `master_binding_registry_sha256`, and `master_sha256` keep the same names from asset loading through inventory, planning, runtime, and acceptance.
