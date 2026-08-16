# HVDC Domain Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backward-compatible, deterministic HVDC domain layer to PSCAD MCP that scans project evidence, classifies topology, resolves configured semantic mappings, validates and runs safe scenarios, and analyzes normalized outputs.

**Architecture:** Keep the existing 60 generic MCP tools and service boundary unchanged. Add focused modules under `pscad_mcp/hvdc/` for JSON-safe models, XML/evidence scanning, rule-based classification, profile/mapping registries, scenario validation/orchestration, and bounded metrics; expose a separate `pscad_mcp/tools/hvdc_tools.py` group through the existing guarded registration helper.

**Tech Stack:** Python 3.10+, dataclasses, `xml.etree.ElementTree`, JSON-safe dictionaries, pytest, existing `PscadService`/backend protocols and PSOUT reader.

---

### Task 1: Foundation models and deterministic scanner

**Files:**
- Create: `pscad_mcp/hvdc/__init__.py`
- Create: `pscad_mcp/hvdc/models.py`
- Create: `pscad_mcp/hvdc/scanner.py`
- Create: `tests/test_hvdc_scanner.py`

- [ ] **Step 1: Write failing model/scanner tests**

```python
def test_scanner_extracts_definitions_components_labels_and_source(tmp_path):
    path = tmp_path / "difforder_new.pscx"
    path.write_text("""<project version='4.6.2'><definitions>
      <Definition name='RectCC'/><Definition name='InverterPole'/>
      <Definition name='loadbreaker_3'/><Definition name='TL1'/>
      </definitions><canvas name='Main'><component id='7' name='B1'
      definition='master:loadbreaker_3'><parameter name='trip' value='1'/>
      <label>DC breaker</label></component><label>Idc</label></canvas></project>""")
    evidence = scan_project(path, canvas_name="Main")
    assert evidence.project_name == "difforder_new"
    assert evidence.pscad_version == "4.6.2"
    assert "RectCC" in evidence.definitions
    assert evidence.components[0].source.component_id == "7"
    assert any(label.text == "Idc" for label in evidence.labels)
    assert json.loads(json.dumps(asdict(evidence)))
```

- [ ] **Step 2: Run `py -m pytest tests/test_hvdc_scanner.py -q` and verify it fails because the module is missing.**

- [ ] **Step 3: Implement frozen dataclasses and XML extraction**

`models.py` defines `HvdcSourceRef`, `HvdcComponentRecord`, `HvdcLabelRecord`, `HvdcProjectEvidence`, `HvdcAsset`, `HvdcTopologySummary`, `HvdcMapping`, `HvdcScenarioResult`, and `HvdcMetric` with only JSON-safe field values. `scanner.py` parses project identity/version, definitions, `<component>` attributes/parameters/labels, canvas labels, ports, and warnings; malformed XML raises `BackendError("HVDC_SCENARIO_INVALID", ...)` only when used for scenarios and returns a warning for read-only inspection.

- [ ] **Step 4: Run the focused test and then `py -m pytest tests/test_hvdc_scanner.py -q`; expect all pass.**

- [ ] **Step 5: Commit with `git add pscad_mcp/hvdc tests/test_hvdc_scanner.py && git commit -m "feat: add HVDC evidence models and scanner"`.**

### Task 2: Rule-based topology classifier and profile/mapping registry

**Files:**
- Create: `pscad_mcp/hvdc/classifier.py`
- Create: `pscad_mcp/hvdc/profiles.py`
- Create: `pscad_mcp/hvdc/mappings.py`
- Create: `pscad_mcp/hvdc/profiles/*.json`
- Create: `tests/test_hvdc_classifier.py`
- Create: `tests/test_hvdc_mappings.py`

- [ ] **Step 1: Write failing classifier and mapping tests**

```python
def test_classifier_reports_lcc_bipolar_breaker_with_evidence(evidence):
    summary = classify_topology(evidence)
    assert summary.family == "lcc"
    assert summary.polarity == "bipolar"
    assert summary.breaker_protection_present is True
    assert any("RectCC" in item for item in summary.evidence)

def test_classifier_does_not_force_family_from_one_generic_name():
    summary = classify_topology(make_evidence(definitions=["converter"]))
    assert summary.family == "unknown"
    assert summary.unresolved_questions

def test_mapping_aliases_and_unit_conflict_are_explicit():
    result = resolve_mappings(make_evidence(labels=["Idc", "Vdc"]), load_profile("lcc_bipolar_generic"))
    assert result.mappings[0].canonical in {"dc_current", "dc_voltage"}
    assert result.unresolved == []
```

- [ ] **Step 2: Run both focused files and confirm expected RED failures.**

- [ ] **Step 3: Implement classifier evidence scoring and explicit overrides**

Use normalized lower-case tokens. LCC evidence includes `rectcc`, `rectpole`, `inverterpole`, `invctrl`, `rectifier_ac`; VSC evidence includes `vsc`, `igbt`, `pll`, `dq`; MMC evidence includes `mmc`, `submodule`, `arm`, `sm`. Breaker/line/protection tokens populate independent flags. Require at least two family signals or an explicit profile override before returning a non-unknown family.

- [ ] **Step 4: Implement `ProfileRegistry` and JSON profile loading**

Profiles include the four initial names from the design and canonical concepts for DC/AC quantities, controls, angles, PLL/dq, and MMC channels. `load_profile` raises `BackendError("HVDC_PROFILE_NOT_FOUND", ...)` with the requested name and available profiles.

- [ ] **Step 5: Implement alias resolution with observed/inferred status and unit-family conflict warnings.**

- [ ] **Step 6: Run focused tests, then commit `feat: add HVDC topology and mapping profiles`.**

### Task 3: Domain service and read-only MCP tools

**Files:**
- Create: `pscad_mcp/hvdc/service.py`
- Create: `pscad_mcp/tools/hvdc_tools.py`
- Modify: `pscad_mcp/main.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `tests/test_hvdc_tools.py`
- Modify: `tests/test_tool_inventory.py`

- [ ] **Step 1: Write failing tool inventory and service tests**

```python
EXPECTED = {"inspect_hvdc_project", "get_hvdc_assets", "get_hvdc_mappings", "validate_hvdc_project", "run_hvdc_scenario", "get_hvdc_scenario_status", "analyze_hvdc_results", "compare_hvdc_scenarios", "list_hvdc_profiles", "register_hvdc_profile"}

def test_hvdc_tools_are_registered_without_removing_generic_tools():
    names = {tool.name for tool in create_server()._tool_manager.list_tools()}
    assert EXPECTED <= names
    assert len(names) == 70
```

- [ ] **Step 2: Run the focused tests and observe RED (new tools are not registered).**

- [ ] **Step 3: Implement `HvdcDomainService`**

`inspect_project` resolves a `.pscx` through `PathPolicy`, scans it, classifies it, and resolves the auto/profile mappings. `get_assets` and `get_mappings` reuse a cached evidence snapshot keyed by absolute path/mtime. `validate_project` returns checks, warnings, unresolved concepts, and `valid`; it never mutates PSCAD.

- [ ] **Step 4: Register the ten async tool functions with `register_tool` and add the module to `create_server`; update inventory assertion from 60 to 70 while preserving all previous names.**

- [ ] **Step 5: Extend `_ERROR_GUIDANCE` with `HVDC_PROFILE_NOT_FOUND`, `HVDC_TOPOLOGY_AMBIGUOUS`, `HVDC_MAPPING_MISSING`, `HVDC_SCENARIO_INVALID`, `HVDC_CAPABILITY_UNAVAILABLE`, and `INCOMPLETE_ANALYSIS`.**

- [ ] **Step 6: Run `py -m pytest tests/test_hvdc_tools.py tests/test_tool_inventory.py -q` and the existing service/tool contract tests. Commit `feat: expose HVDC inspection and validation tools`.**

### Task 4: Declarative scenario validation and safe orchestration

**Files:**
- Create: `pscad_mcp/hvdc/scenarios.py`
- Modify: `pscad_mcp/hvdc/service.py`
- Create: `tests/test_hvdc_scenarios.py`

- [ ] **Step 1: Write failing scenario tests**

```python
def test_scenario_requires_confirmation_before_parameter_mutation(service):
    scenario = {"name": "trip", "profile": "hvdc_breaker_difforder", "project": "case", "parameter_changes": [{"target": "fault_command", "value": 1}], "events": []}
    result = await service.run_scenario(scenario, confirm=False)
    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"

def test_unsupported_event_is_structured_capability_error(service):
    scenario = {"name": "trip", "profile": "hvdc_breaker_difforder", "project": "case", "parameter_changes": [], "events": [{"time_s": 1, "target": "insert_fault", "value": 1}]}
    result = await service.validate_scenario(scenario)
    assert result["valid"] is False
    assert result["errors"][0]["code"] == "HVDC_CAPABILITY_UNAVAILABLE"
```

- [ ] **Step 2: Run focused tests and verify RED.**

- [ ] **Step 3: Implement strict schema validation**

Validate non-empty `name`, known profile, project name, finite non-negative event times, list-shaped `parameter_changes`/`events`, and only mapped targets. Unsupported insertion/re-wiring events return structured capability errors.

- [ ] **Step 4: Implement orchestration using existing service methods**

With `confirm=True`, apply only mapped parameter changes through `set_component_parameters` or mapped project settings, then call `run_project` or `run_simulation_set`. Store bounded status records in an in-memory registry with run ID, changed parameters, output files, and warnings. Never copy or mutate the source project automatically.

- [ ] **Step 5: Run focused tests and commit `feat: add safe HVDC scenario orchestration`.**

### Task 5: Deterministic metrics and scenario comparison

**Files:**
- Create: `pscad_mcp/hvdc/metrics.py`
- Modify: `pscad_mcp/hvdc/service.py`
- Create: `tests/test_hvdc_metrics.py`

- [ ] **Step 1: Write failing metric tests for extrema, RMS, settling, power, imbalance, trip delay, and missing channels.**

- [ ] **Step 2: Run `py -m pytest tests/test_hvdc_metrics.py -q` and verify RED.**

- [ ] **Step 3: Implement bounded pure functions**

Accept normalized `{time, channels}` samples. Return each metric as `{name, value, units, time_window, source_channels, method, status}`. Use `INCOMPLETE_ANALYSIS` when required channels are absent; never substitute zeros. Calculate `dc_power` only when both `dc_voltage` and `dc_current` are present, pole imbalance only for paired channels, and trip delay only for ordered command/status crossings.

- [ ] **Step 4: Wire `analyze_hvdc_results` to the existing PSOUT reader and `compare_hvdc_scenarios` to aligned metric names.**

- [ ] **Step 5: Run focused tests and commit `feat: add deterministic HVDC result metrics`.**

### Task 6: Breaker fixtures, profile registration, and full regression

**Files:**
- Create: `tests/fixtures/hvdc/difforder_new.pscx`
- Create: `tests/test_hvdc_breaker_fixture.py`
- Create: `tests/test_hvdc_serialization.py`
- Modify: `README.md`

- [ ] **Step 1: Add a minimal XML fixture derived from the documented Breaker vocabulary (no source project copied or modified).**

- [ ] **Step 2: Write integration tests asserting LCC/bipolar classification, rectifier/inverter/pole/breaker/line assets, configured mappings, stable JSON serialization, and unresolved concepts.**

- [ ] **Step 3: Run the fixture tests and verify RED before implementation, then implement any missing profile aliases or scanner extraction.**

- [ ] **Step 4: Document the ten HVDC tools, profile names, safety behavior, and example scenario in `README.md`.**

- [ ] **Step 5: Run the complete suite with `py -m pytest -q`; run `python scripts/verify_package.ps1` only if the repository's PowerShell verification wrapper is executable.**

- [ ] **Step 6: Review the diff against every design section, commit `feat: complete HVDC domain layer baseline`, and report any real-PSCAD acceptance steps that remain unavailable without PSCAD 4.6.2.**

