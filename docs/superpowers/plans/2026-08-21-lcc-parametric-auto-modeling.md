# LCC Parametric Auto Modeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fail-closed, parameterized LCC model generator for monopole and bipolar 12-pulse systems, including steady-state validation, operating-mode variants, optional EMTDC-time switching, and audited user-template substitution.

**Architecture:** Keep the existing fixed CIGRE builder and its four public tools unchanged. Add focused parameter, blueprint, operating-mode, template-audit, and lifecycle modules behind a new `ParametricLccBuilderService`; expose six new tools only after the service contract is complete. Reuse the existing LCC catalog, planner, executor, graph validator, acceptance, workspace policy, journal, lease, and structured error boundaries.

**Tech Stack:** Python 3.10+, dataclasses, JSON assets, `BackendError`, existing PSCAD service/backend boundary, pytest/unittest fixtures, PSCX graph fixtures, and opt-in licensed PSCAD 4.6.2 acceptance.

---

## Scope decomposition

The implementation is divided into four independently testable tracks:

1. **Parametric foundation:** request schema, unit-aware ratings, derivation report, feasibility gates.
2. **Topology generation:** separate monopole and bipolar blueprints, catalog contracts, deterministic plans.
3. **Operating modes:** independent mode copies, mode-specific validation, EMTDC-time event schedules.
4. **Template audit:** read-only user-library/project audit and standard-role mapping.

The public service and MCP tools integrate the tracks only after each track has passing focused tests. Existing fixed LCC behavior is regression-tested after every integration task.

## File map before implementation

### New production files

- `pscad_mcp/hvdc/builders/lcc/parametric_models.py` — immutable request, rating, override, derived-report, mode, event, and template-mapping records.
- `pscad_mcp/hvdc/builders/lcc/derivation.py` — unit normalization, parameter formulas, feasibility checks, and structured diagnostics.
- `pscad_mcp/hvdc/builders/lcc/modes.py` — mode definitions, independent-copy derivation, event validation, and mode result contracts.
- `pscad_mcp/hvdc/builders/lcc/template_audit.py` — read-only project/library inspection and standard-role mapping.
- `pscad_mcp/hvdc/builders/lcc/parametric_service.py` — public lifecycle composition over derivation, blueprint planning, existing executor, mode execution, and template audit.
- `pscad_mcp/tools/lcc_parametric_tools.py` — six MCP wrappers and guarded registration.
- `pscad_mcp/assets/lcc/lcc_monopole_parametric_v1/blueprint.json` — fixed-directory monopole parameterized topology contract.
- `pscad_mcp/assets/lcc/lcc_bipole_parametric_v1/blueprint.json` — fixed-directory bipolar topology with explicit neutral/return paths.
- `pscad_mcp/assets/lcc/lcc_parametric_catalog_v1.json` — role-to-definition, port, parameter, unit, and range contracts.

### Modified production files

- `pscad_mcp/hvdc/builders/lcc/schema.py` — parse and validate parametric records while preserving existing fixed-blueprint records.
- `pscad_mcp/hvdc/builders/lcc/planner.py` — accept normalized parametric blueprints and retain deterministic plan hashing.
- `pscad_mcp/hvdc/builders/lcc/validator.py` — validate bipolar neutral/return contracts and mode-specific graph assertions.
- `pscad_mcp/hvdc/builders/lcc/acceptance.py` — add pole-balance, return-current, mode-transition, and derived-parameter evidence checks.
- `pscad_mcp/hvdc/builders/lcc/service.py` — expose shared read-only validation helpers without changing the four fixed-tool signatures.
- `pscad_mcp/hvdc/scenarios.py` — reuse strict timed dispatch only through explicit capability and binding checks.
- `pscad_mcp/main.py` — register the new tool group after fixed LCC registration.
- `CHANGELOG.md`, `docs/zh-CN/README.md` — document the new capability levels and preserve fixed-builder limits.

### New test files

- `tests/test_lcc_parametric_models.py`
- `tests/test_lcc_derivation.py`
- `tests/test_lcc_parametric_blueprints.py`
- `tests/test_lcc_operating_modes.py`
- `tests/test_lcc_template_audit.py`
- `tests/test_lcc_parametric_service.py`
- `tests/test_lcc_parametric_tools.py`
- `tests/test_lcc_parametric_acceptance_contract.py`
- `tests/fixtures/lcc_parametric/monopole_template.pscx`
- `tests/fixtures/lcc_parametric/bipole_template.pscx`
- `tests/fixtures/lcc_parametric/ambiguous_template.pscx`
- `tests/fixtures/lcc_parametric/incompatible_template.pscx`

## Task 1: Add parametric records and strict input validation

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/parametric_models.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/schema.py`
- Test: `tests/test_lcc_parametric_models.py`

- [ ] **Step 1: Write failing record and validation tests.**

Add tests for immutable JSON-safe records with this contract:

```python
request = ParametricLccRequest(
    topology="bipolar",
    ratings=LccRatings(
        rated_power_mw=1200.0,
        dc_voltage_kv=500.0,
        dc_current_ka=2.4,
        ac_voltage_kv=500.0,
        frequency_hz=50.0,
        scr=3.0,
    ),
    engineering_overrides={"smoothing_reactor_mh": 120.0},
    operation_modes=("bipolar_run", "monopolar_earth_return"),
)
payload = request.to_dict()
assert payload["topology"] == "bipolar"
assert payload["ratings"]["dc_current_ka"] == 2.4
```

Reject unknown fields, booleans in numeric positions, non-finite values, unsupported topology/mode names, non-positive ratings, and event times that are negative or not strictly increasing.

- [ ] **Step 2: Run the focused tests and verify the failure.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_models.py`

Expected: collection or assertion failure because the parametric records do not exist.

- [ ] **Step 3: Implement the records and schema parser.**

Define frozen dataclasses `LccRatings`, `LccParameterOverride`, `ParametricLccRequest`, `DerivedParameter`, `DerivedParameterReport`, `LccModeRequest`, `LccModeEvent`, and `LccTemplateMapping`. Each record must normalize nested mappings to immutable JSON-safe values and raise `BackendError("LCC_RATING_INVALID", ...)` or `BackendError("LCC_OPERATING_MODE_INVALID", ...)` at the public parser boundary.

Extend `parse_blueprint()` only through a separate `parse_parametric_request()` path; existing `parse_blueprint()` behavior and error codes must remain unchanged.

- [ ] **Step 4: Run the focused tests and verify they pass.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_models.py tests/test_lcc_schema.py`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the foundation records.**

```powershell
git add pscad_mcp/hvdc/builders/lcc/parametric_models.py pscad_mcp/hvdc/builders/lcc/schema.py tests/test_lcc_parametric_models.py
git commit -m "feat: add parametric LCC request records"
```

## Task 2: Implement parameter derivation and feasibility gates

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/derivation.py`
- Test: `tests/test_lcc_derivation.py`

- [ ] **Step 1: Write failing derivation tests.**

Cover user precedence, deterministic formulas, unit normalization, and fail-closed feasibility:

```python
report = derive_lcc_parameters(request)
assert report.parameters["dc_power_mw"].value == pytest.approx(1200.0)
assert report.parameters["dc_power_mw"].source == "derived"
assert report.parameters["smoothing_reactor_mh"].source == "user"
assert report.feasible is True
```

Add negative cases for inconsistent `P != V * I`, invalid SCR, impossible angle intervals, missing bipolar return assets, unsupported override names, and overrides outside catalog ranges. Assert exact stable codes and no filesystem writes.

- [ ] **Step 2: Run tests to observe the failure.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_derivation.py`

Expected: failure because `derive_lcc_parameters` is not defined.

- [ ] **Step 3: Implement deterministic derivation.**

Implement `derive_lcc_parameters(request, catalog)` with only formulas declared in the versioned catalog/provenance assets. The first formula is the dimensional identity `dc_power_mw = dc_voltage_kv * dc_current_ka`; component defaults such as overlap angle, smoothing reactor, filter, and control limits must come from reviewed asset declarations or be supplied as explicit user overrides. If a required engineering value has no reviewed formula or override, return `LCC_PARAMETER_DERIVATION_FAILED` instead of inventing a value.

The implementation must record the exact formula text and source asset for every derived value, apply user overrides after validated defaults, and return sorted diagnostics. Use explicit unit conversion helpers; never infer units from a free-form name.

- [ ] **Step 4: Run derivation tests.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_derivation.py`

Expected: all derivation tests pass.

- [ ] **Step 5: Commit the derivation layer.**

```powershell
git add pscad_mcp/hvdc/builders/lcc/derivation.py tests/test_lcc_derivation.py
git commit -m "feat: derive and validate LCC engineering parameters"
```

## Task 3: Add separate monopole and bipolar parametric blueprints

**Files:**
- Create: `pscad_mcp/assets/lcc/lcc_monopole_parametric_v1/blueprint.json`
- Create: `pscad_mcp/assets/lcc/lcc_bipole_parametric_v1/blueprint.json`
- Create: `pscad_mcp/assets/lcc/lcc_parametric_catalog_v1.json`
- Modify: `pscad_mcp/hvdc/builders/lcc/planner.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/validator.py`
- Test: `tests/test_lcc_parametric_blueprints.py`

- [ ] **Step 1: Write failing blueprint tests.**

Assert that the two blueprints have distinct identities and topology contracts:

```python
mono = load_parametric_blueprint("lcc_monopole_parametric_v1")
bipole = load_parametric_blueprint("lcc_bipole_parametric_v1")
assert mono["topology"] == "lcc" and mono["poles"] == 1
assert bipole["topology"] == "lcc" and bipole["poles"] == 2
assert {"positive_pole", "negative_pole", "neutral_bus"} <= set(bipole["required_assets"])
```

Add tests for deterministic expansion, exact catalog role contracts, explicit earth/metallic return nets, plan hash changes when a derived parameter changes, and rejection of a bipolar blueprint missing neutral or return evidence.

- [ ] **Step 2: Run tests to observe the failure.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_blueprints.py`

Expected: failure because the assets and loader are not present.

- [ ] **Step 3: Add assets and planner adapters.**

Create JSON assets using the existing LCC schema shape. Add `load_parametric_blueprint()` and `load_parametric_catalog()` resource loaders that verify package paths and hashes. Extend planner normalization so the derived report becomes explicit component parameters, never implicit name matching. Keep `create_plan()` side-effect free and reject a topology/blueprint mismatch with `LCC_BLUEPRINT_INVALID`.

Extend validator checks with:

- exact positive/negative pole roles for bipolar;
- neutral bus and earth/metallic return endpoint contracts;
- pole-specific result channels;
- no extra observed components or nets.

- [ ] **Step 4: Run blueprint and legacy LCC tests.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_blueprints.py tests/test_lcc_planner.py tests/test_lcc_validator.py`

Expected: all selected tests pass and fixed CIGRE planner/validator behavior remains unchanged.

- [ ] **Step 5: Commit the topology layer.**

```powershell
git add pscad_mcp/assets/lcc/lcc_monopole_parametric_v1 pscad_mcp/assets/lcc/lcc_bipole_parametric_v1 pscad_mcp/assets/lcc/lcc_parametric_catalog_v1.json pscad_mcp/hvdc/builders/lcc/planner.py pscad_mcp/hvdc/builders/lcc/validator.py tests/test_lcc_parametric_blueprints.py
git commit -m "feat: add monopole and bipolar LCC parametric blueprints"
```

## Task 4: Implement operating-mode copies and strict switching schedules

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/modes.py`
- Modify: `pscad_mcp/hvdc/scenarios.py`
- Modify: `pscad_mcp/hvdc/preflight.py`
- Modify: `pscad_mcp/hvdc/metrics.py`
- Test: `tests/test_lcc_operating_modes.py`

- [ ] **Step 1: Write failing mode and schedule tests.**

Cover independent mode plans and safe rejection:

```python
copies = derive_mode_copies(base_plan, ("bipolar_run", "metallic_return"))
assert [item.mode for item in copies] == ["bipolar_run", "metallic_return"]
schedule = validate_lcc_schedule([
    {"event_id": "e1", "time_s": 1.0, "target": "metallic_return", "value": 1}
])
assert schedule[0].event_id == "e1"
```

Reject duplicate IDs, non-increasing times, unknown modes, missing command bindings, wall-clock timestamps, and a backend without strict simulation-clock/output-channel capabilities. Add metrics tests for return-current closure, pole imbalance, mode transition recovery, and mode mismatch.

- [ ] **Step 2: Run tests to observe the failure.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_operating_modes.py`

Expected: failure because mode records and validation functions do not exist.

- [ ] **Step 3: Implement mode derivation and preflight integration.**

Implement `derive_mode_copies()`, `validate_lcc_schedule()`, and `mode_acceptance_contract()`. Reuse existing binding resolution and timing providers; do not introduce alias-based writable command authorization. Require `confirm=true` at the service boundary for all writes. Route all `time_s` values through the existing EMTDC-time provider and return `LCC_SWITCHING_UNAVAILABLE` before any parameter write when capability checks fail.

- [ ] **Step 4: Run mode, timing, and scenario containment tests.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_operating_modes.py tests/test_hvdc_timing.py tests/test_hvdc_scenario_containment.py tests/test_hvdc_scenarios.py`

Expected: all selected tests pass; existing HVDC scenario behavior remains unchanged.

- [ ] **Step 5: Commit operating-mode support.**

```powershell
git add pscad_mcp/hvdc/builders/lcc/modes.py pscad_mcp/hvdc/scenarios.py pscad_mcp/hvdc/preflight.py pscad_mcp/hvdc/metrics.py tests/test_lcc_operating_modes.py
git commit -m "feat: add LCC operating modes and strict switching schedules"
```

## Task 5: Add read-only user template auditing

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/template_audit.py`
- Test: `tests/test_lcc_template_audit.py`
- Create: `tests/fixtures/lcc_parametric/monopole_template.pscx`
- Create: `tests/fixtures/lcc_parametric/bipole_template.pscx`
- Create: `tests/fixtures/lcc_parametric/ambiguous_template.pscx`
- Create: `tests/fixtures/lcc_parametric/incompatible_template.pscx`

- [ ] **Step 1: Write failing audit tests.**

Assert standard-role mappings and fail-closed cases:

```python
audit = audit_lcc_template("tests/fixtures/lcc_parametric/bipole_template.pscx")
assert audit.compatible is True
assert audit.roles["rectifier_valve_group"].definition == "cigre_lcc_v1:LCC12PulseBridge"
assert audit.roles["earth_electrode"].confidence == 1.0
```

Assert `LCC_TEMPLATE_AMBIGUOUS` for duplicate candidates, `LCC_TEMPLATE_INCOMPATIBLE` for missing ports/units, and that auditing never calls a mutating service method or writes to the input directory.

- [ ] **Step 2: Run tests to observe the failure.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_template_audit.py`

Expected: failure because the auditor and fixtures do not exist.

- [ ] **Step 3: Implement the read-only auditor.**

Parse through the existing project graph/scanner boundary. Match only exact definition, port, parameter, unit, and role declarations from `lcc_parametric_catalog_v1.json`. Return a bounded report containing source references, observed values, missing contracts, conflicts, and a deterministic template fingerprint. Never rewrite the source file and never use substring matching as a construction authorization.

- [ ] **Step 4: Run audit and graph safety tests.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_template_audit.py tests/test_lcc_project_graph.py tests/test_hvdc_scanner.py`

Expected: all selected tests pass.

- [ ] **Step 5: Commit template auditing.**

```powershell
git add pscad_mcp/hvdc/builders/lcc/template_audit.py tests/test_lcc_template_audit.py tests/fixtures/lcc_parametric
git commit -m "feat: audit LCC user templates without mutation"
```

## Task 6: Compose the parametric lifecycle service

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/parametric_service.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/acceptance.py`
- Test: `tests/test_lcc_parametric_service.py`

- [ ] **Step 1: Write failing service contract tests.**

Cover read-only derivation/planning, confirmation and stale hash rejection before staging/lease, asset/template fingerprint checks, mode-copy isolation, status serialization, failure containment, and validation without mutation:

```python
plan = await service.plan_parametric_model(request)
assert plan["plan_hash"]
with pytest.raises(BackendError) as error:
    await service.build_parametric_model(request, expected_plan_hash="wrong", confirm=True)
assert error.value.code == "LCC_PLAN_STALE"
assert not list((tmp_path / ".pscad-mcp" / "lcc-builds").glob("*"))
```

- [ ] **Step 2: Run tests to observe the failure.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_service.py`

Expected: failure because the service class and lifecycle methods do not exist.

- [ ] **Step 3: Implement service composition.**

Add `ParametricLccBuilderService` with methods `derive_parameters()`, `audit_template()`, `plan_parametric_model()`, `build_parametric_model()`, `get_status()`, and `validate_operating_modes()`. Reuse the existing `LccBuilderService` executor factory and journal/lease facilities. The service must:

- resolve every path through `PathPolicy`;
- rederive and refingerprint at build start;
- require exact plan hash and explicit confirmation before staging;
- reject existing final targets;
- preserve staging evidence after failure;
- publish only after structural, compile, steady-state, and required mode gates pass;
- serialize only bounded JSON-safe status and evidence metadata.

Extend acceptance with mode-specific declarations; missing samples, missing return channels, unknown units, or incomplete mode evidence produce `INCOMPLETE_ANALYSIS`, never a fabricated pass.

- [ ] **Step 4: Run service and all fixed LCC lifecycle tests.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_service.py tests/test_lcc_builder_service.py tests/test_lcc_executor.py tests/test_lcc_acceptance.py`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the service integration.**

```powershell
git add pscad_mcp/hvdc/builders/lcc/parametric_service.py pscad_mcp/hvdc/builders/lcc/acceptance.py tests/test_lcc_parametric_service.py
git commit -m "feat: compose parameterized LCC build lifecycle"
```

## Task 7: Register MCP tools and document contracts

**Files:**
- Create: `pscad_mcp/tools/lcc_parametric_tools.py`
- Modify: `pscad_mcp/main.py`
- Modify: `tests/test_lcc_parametric_tools.py`
- Modify: `tests/test_tool_inventory.py`
- Modify: `tests/test_changelog.py`
- Modify: `CHANGELOG.md`
- Modify: `docs/zh-CN/README.md`

- [ ] **Step 1: Write failing registration and forwarding tests.**

Assert exact names and forwarding for:

```python
EXPECTED = {
    "derive_lcc_parameters",
    "audit_lcc_template",
    "plan_parametric_lcc_model",
    "build_parametric_lcc_model",
    "get_parametric_lcc_build_status",
    "validate_lcc_operating_modes",
}
assert EXPECTED <= {tool.name for tool in create_server()._tool_manager.list_tools()}
```

Assert the inventory increases from 77 to 83 only when all six tools are registered, and fixed tool names/default response shapes remain unchanged.

- [ ] **Step 2: Run tests to observe the failure.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_tools.py tests/test_tool_inventory.py`

Expected: failure because the new module is not registered.

- [ ] **Step 3: Implement wrappers and registration.**

Use the existing guarded registration helper. Keep wrappers thin: parse public arguments, call the singleton service, and return the existing normalized result/error shape. Register the new group after `register_lcc_tools(mcp)` and do not alter fixed-tool wrappers.

- [ ] **Step 4: Update documentation and inventory assertions.**

Document capability levels, the six new tools, required inputs, fixed PSCAD 4.6.2 boundary, template read-only audit, and the fact that real acceptance is opt-in. Update changelog text without claiming licensed acceptance until the opt-in test passes.

- [ ] **Step 5: Run tool and packaging checks.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_tools.py tests/test_tool_inventory.py tests/test_changelog.py tests/test_install_smoke.py`

Expected: all selected tests pass and the inventory reports `83 83`.

- [ ] **Step 6: Commit the public boundary.**

```powershell
git add pscad_mcp/tools/lcc_parametric_tools.py pscad_mcp/main.py tests/test_lcc_parametric_tools.py tests/test_tool_inventory.py tests/test_changelog.py CHANGELOG.md docs/zh-CN/README.md
git commit -m "feat: expose parametric LCC modeling tools"
```

## Task 8: Add real-acceptance contract and final verification

**Files:**
- Create: `tests/test_lcc_parametric_acceptance_contract.py`
- Modify: `tests/test_lcc_real_acceptance.py`
- Modify: `tests/test_lcc_real_acceptance_contract.py`

- [ ] **Step 1: Write failing acceptance-contract tests.**

Require absolute isolated workspace, opt-in environment, timestamped owned evidence directory, source/template/asset hashes, final project hash, per-mode reports, and rejection of PASS without compile, waveform, and mode evidence.

- [ ] **Step 2: Run contract tests to observe the failure.**

Run: `& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_parametric_acceptance_contract.py`

Expected: failure because the parametric acceptance report schema does not exist.

- [ ] **Step 3: Implement the report contract and opt-in test flow.**

Reuse the existing LCC real-acceptance helpers. The opt-in flow must copy source assets into a timestamped workspace, call the six public parametric tools through the production service boundary, poll until terminal state, independently validate each requested mode, persist bounded JSON evidence, and clean only owned PSCAD processes/artifacts. Default runs must skip without launching PSCAD.

- [ ] **Step 4: Run the complete non-licensed verification suite.**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m compileall pscad_mcp
& .\.venv\Scripts\python.exe -m pytest -q tests/test_lcc_*.py tests/test_hvdc_*.py
& .\.venv\Scripts\python.exe -c "from pscad_mcp.main import create_server; t=create_server()._tool_manager.list_tools(); print(len(t), len({x.name for x in t}))"
git diff --check
```

Expected: selected tests pass, compilation succeeds, and the inventory prints `83 83`. Any pre-existing unrelated dirty files must remain untouched and be reported separately.

- [ ] **Step 5: Run licensed acceptance only when explicitly enabled.**

Set `PSCAD_MCP_LCC_ACCEPTANCE=1`, an absolute `PSCAD_MCP_WORKSPACE`, the licensed PSCAD 4.6.2 backend settings, and the approved source/template asset paths. Run the dedicated acceptance test and require a persisted report with final `PASS` for every declared gate before describing the feature as accepted.

- [ ] **Step 6: Commit the acceptance contract and verification updates.**

```powershell
git add tests/test_lcc_parametric_acceptance_contract.py tests/test_lcc_real_acceptance.py tests/test_lcc_real_acceptance_contract.py
git commit -m "test: add parameterized LCC acceptance contract"
```

## Plan self-review

- **Spec coverage:** Input records and derivation are covered by Tasks 1-2; separate monopole/bipolar blueprints by Task 3; independent copies and EMTDC-time switching by Task 4; template audit by Task 5; lifecycle/safety/acceptance by Task 6 and Task 8; public tools and compatibility documentation by Task 7.
- **Placeholder scan:** No task depends on an unresolved placeholder or unspecified follow-up. Every task names files, tests, commands, expected outcomes, and commit boundaries.
- **Type consistency:** `ParametricLccRequest`, `DerivedParameterReport`, `LccModeEvent`, `LccTemplateMapping`, and `ParametricLccBuilderService` are introduced before their consumers. Existing fixed LCC records and tools remain separate.
- **Scope boundary:** User-template substitution and timed switching are intentionally later tasks and cannot weaken fixed-directory or fail-closed behavior.
