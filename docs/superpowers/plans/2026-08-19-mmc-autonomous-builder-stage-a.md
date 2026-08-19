# MMC Autonomous Builder Stage A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fixed, hash-verified CIGRE B4-derived two-terminal symmetrical-monopole half-bridge MMC average-value builder for PSCAD 4.6.2, including deterministic planning, guarded construction, structural validation, dynamic acceptance contracts, and four public Stage A MCP tools.

**Architecture:** Reuse the accepted LCC builder's stable service boundary and extract only implementation-neutral serialization, routing, journal, and workspace-lease primitives into `hvdc.builders.common`. Keep MMC equations, controls, topology, assets, planner, validator, acceptance, and lifecycle state machine in `hvdc.builders.mmc`. Planning is pure and hash-addressed; confirmed builds run in staged candidate directories and publish only after independent graph and acceptance checks pass.

**Tech Stack:** Python 3.10+, dataclasses, `json`, `hashlib`, `pathlib`, `xml.etree.ElementTree`, `asyncio`, FastMCP, pytest, PSCAD/EMTDC 4.6.2 Legacy Automation Library.

---

## Scope and execution gates

- Start from the current `main` descendant containing the LCC builder; preserve its four public tools, plan payloads, plan hashes, journals, asset hashes, and test behavior.
- The implementation target is Stage A only. Stage C sizing and `design_mmc_model` require a separate plan after Stage A's licensed acceptance gate.
- No packaged asset may copy customer/vendor definitions. The companion library must contain only repository-authored MMC AVM definitions and declared Master Library references.
- No tool may expose a raw PSCAD proxy or mutate PSCAD during planning or validation.
- Run the deterministic baseline from the isolated worktree with licensed acceptance variables removed:

```powershell
Remove-Item Env:PSCAD_MCP_ACCEPTANCE -ErrorAction SilentlyContinue
Remove-Item Env:PSCAD_MCP_HVDC_SOURCE -ErrorAction SilentlyContinue
Remove-Item Env:PSCAD_MCP_HVDC_LIBRARY -ErrorAction SilentlyContinue
Remove-Item Env:PSCAD_MCP_WORKSPACE -ErrorAction SilentlyContinue
& .venv\Scripts\python.exe -m pytest -q
& .venv\Scripts\python.exe -m compileall -q pscad_mcp tests
git diff --check
```

- Licensed acceptance is opt-in and must use a separate timestamped workspace. If PSCAD 4.6.2, the Legacy Automation Library, or the original engineering reference output is unavailable, record the exact skipped command and do not claim `accepted`.

## File map

Create:

- `pscad_mcp/hvdc/builders/common/__init__.py`: common builder exports.
- `pscad_mcp/hvdc/builders/common/records.py`: JSON-safe canonical serialization and content hashing.
- `pscad_mcp/hvdc/builders/common/journal.py`: generic atomic journal and workspace-scoped cross-process lease.
- `pscad_mcp/hvdc/builders/common/routing.py`: orientation transforms and orthogonal route checks independent of electrical family.
- `pscad_mcp/hvdc/builders/mmc/__init__.py`: supported blueprint and public service exports.
- `pscad_mcp/hvdc/builders/mmc/models.py`: immutable MMC arm, station, topology, control, plan, build, output, and acceptance records.
- `pscad_mcp/hvdc/builders/mmc/schema.py`: strict fixed-blueprint, control, sequence, and acceptance parsing.
- `pscad_mcp/hvdc/builders/mmc/assets.py`: recursive manifest verification, provenance checks, and workspace library materialization.
- `pscad_mcp/hvdc/builders/mmc/electrical.py`: arm-current, energy, capacitance, loss, modulation, and saturation calculations.
- `pscad_mcp/hvdc/builders/mmc/controls.py`: fixed control contract and operating-sequence transition rules.
- `pscad_mcp/hvdc/builders/mmc/planner.py`: deterministic two-station/twelve-arm expansion and plan hashing.
- `pscad_mcp/hvdc/builders/mmc/project_graph.py`: structured PSCX graph reader for MMC components, ports, and nets.
- `pscad_mcp/hvdc/builders/mmc/validator.py`: exact topology, polarity, port, signal, and saved-project checks.
- `pscad_mcp/hvdc/builders/mmc/acceptance.py`: finite-window, golden, dynamic, and physical acceptance engine.
- `pscad_mcp/hvdc/builders/mmc/journal.py`: MMC journal paths and candidate evidence helpers using the common lease.
- `pscad_mcp/hvdc/builders/mmc/executor.py`: staged mutation, read-back postconditions, compilation, simulation, and publication containment.
- `pscad_mcp/hvdc/builders/mmc/service.py`: public planning, build lifecycle, status, and validation service.
- `pscad_mcp/tools/mmc_tools.py`: the four Stage A wrappers `plan_mmc_model`, `build_mmc_model`, `get_mmc_build_status`, and `validate_mmc_model`.
- `pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1/`: manifest, blueprint, catalog, controls, sequence, acceptance, golden, provenance, and original companion library.
- `scripts/audit_mmc_assets.py`: maintainer audit for XML scopes, definitions, ports, paths, and provenance.
- `tests/mmc_builder_fakes.py`: fake PSCAD service and controlled output fixtures.
- `tests/test_mmc_*.py`: unit, structural, service, containment, packaging, and contract tests.

Modify:

- `pscad_mcp/hvdc/builders/lcc/journal.py`: re-export common journal/lease primitives while preserving LCC names and error payloads.
- `pscad_mcp/main.py`: register the MMC tool group after LCC tools.
- `pscad_mcp/hvdc/profiles.py`: add the fixed project-qualified v2 MMC result profile.
- `pyproject.toml`: package all fixed MMC asset files recursively.
- `tests/test_tool_inventory.py`, `tests/test_tool_backend_matrix.py`, and `tests/test_hvdc_tools.py`: extend exact inventory assertions from 77 to 81 without weakening existing names; Stage C will add the 82nd tool.
- `README.md`, `docs/zh-CN/README.md`, and `CHANGELOG.md`: document Stage A limits and the designed/planned/built/simulated/accepted status distinction.
- `scripts/verify_package.ps1` and `tests/test_install_smoke.py`: verify installed MMC resources and hashes.

## Task 1: Extract common primitives without changing LCC behavior

**Files:** common records/journal/routing modules, LCC journal, common regression tests.

- [ ] Write failing tests that import `canonical_json`, `content_hash`, `AtomicJournal`, `WorkspaceBuildLease`, `transform_offset`, and `validate_orthogonal_route` from `pscad_mcp.hvdc.builders.common`; acquire a common lease from two processes/threads and assert the second acquisition returns the existing owner evidence.
- [ ] Run the focused tests and observe import failure before adding production code.
- [ ] Implement the common functions by moving only implementation-neutral behavior from the LCC modules. Preserve `LccBuildState`, `LccBuilderService`, `LccBuildPlan.to_dict()`, all LCC error codes, and the LCC journal path as a compatibility alias.
- [ ] Add a regression fixture that computes an LCC plan twice before and after the extraction and asserts equal canonical payload and `plan_hash`.
- [ ] Run `pytest tests/test_lcc_journal.py tests/test_lcc_planner.py tests/test_lcc_builder_service.py tests/test_common_builder.py -q` and commit the extraction.

## Task 2: Define immutable MMC records and strict schema contracts

**Files:** `mmc/models.py`, `mmc/schema.py`, `tests/test_mmc_schema.py`, `tests/test_mmc_models.py`.

- [ ] Write tests for a valid fixed blueprint containing two stations, six arms per station, exact arm equations, settings, output selectors, and four acceptance windows; assert JSON-safe serialization rejects `NaN`, `Infinity`, non-string mapping keys, unknown fields, duplicate logical IDs, duplicate ports, and missing required fields.
- [ ] Run the focused tests and confirm the new MMC imports/contracts fail.
- [ ] Implement frozen records for `MmcArmSpec`, `MmcStationSpec`, `MmcComponentSpec`, `MmcNetSpec`, `MmcOutputSpec`, `MmcControlContract`, `MmcSequencePhase`, `MmcAcceptanceCheck`, `MmcBlueprint`, `MmcPlanOperation`, `MmcBuildPlan`, `MmcBuildRecord`, and `MmcBuildState` with states `validated`, `staging_created`, `components_placed`, `parameters_verified`, `connections_verified`, `structure_verified`, `staging_saved`, `compiled`, `startup_simulated`, `forward_simulated`, `reversal_simulated`, `reverse_simulated`, `acceptance_passed`, `published`, `failed`, `timed_out`, and `interrupted`.
- [ ] Implement schema parsing with closed key sets, finite numbers, positive simulation steps, exact station roles (`P` and `VDC`), exactly six unique phase/upper-lower arms per station, and exact output unit declarations.
- [ ] Run the focused tests and commit the records/schema contract.

## Task 3: Implement and test the average-arm electrical contract

**Files:** `mmc/electrical.py`, `tests/test_mmc_electrical.py`.

- [ ] Write tests for the declared equations:

```python
assert arm_currents(9.0, 3.0, 0.2) == (4.7, 2.3)
assert equivalent_capacitor_voltage(2_000_000.0, 10_000.0) == pytest.approx(20.0)
assert arm_energy(10_000.0, 20.0) == pytest.approx(2_000_000.0)
assert clip_modulation(1.2) == (1.2, 1.0, 0.0, True)
```

- [ ] Add failing cases for negative/non-finite energy, non-positive capacitance, invalid current inputs, loss greater than inserted power, and saturation-duration accumulation over non-monotonic time.
- [ ] Run the tests red, then implement finite checked calculations for upper/lower currents, energy/capacitance conversion, explicit conduction/equivalent switching loss, modulation clipping/margin, and cumulative saturation duration.
- [ ] Run `pytest tests/test_mmc_electrical.py -q` and commit only after all equation and failure tests pass.

## Task 4: Define fixed controls and operating sequence transitions

**Files:** `mmc/controls.py`, `tests/test_mmc_controls.py`.

- [ ] Write tests asserting station `STATION_P` uses P/Q control, `STATION_VDC` uses Vdc/Q control, PLL/outer/energy/circulating/inner bandwidths are strictly separated, all anti-windup limits are finite, and the sequence has exactly `blocked_precharge`, `ready_to_deblock`, `forward_ramp`, `forward_steady`, `power_reversal`, and `reverse_steady`.
- [ ] Write transition tests that allow only `blocked_precharge -> ready_to_deblock -> forward_ramp -> forward_steady -> power_reversal -> reverse_steady`, reject deblock before readiness, reject reverse steady before reversal, and stop on protection, PLL, energy, current, or modulation failures.
- [ ] Implement immutable control/sequence loaders and a pure transition reducer that records observed conditions and never changes a command by wall-clock mutation.
- [ ] Run `pytest tests/test_mmc_controls.py -q` and commit.

## Task 5: Author the original MMC AVM companion library and asset audit

**Files:** fixed `assets/mmc/...` files, `scripts/audit_mmc_assets.py`, `tests/test_mmc_asset_audit.py`, `tests/test_mmc_production_assets.py`.

- [ ] Write fixture tests using structured XML parsing that reject missing definitions, duplicate definitions, foreign scopes, absolute author-machine paths, unexpected files, missing provenance, and port drift. Assert the expected custom definitions are exactly `MMCAverageArm`, `MMCStationControl`, `MMCEnergyControl`, `MMCInitialization`, and the declared signal helpers.
- [ ] Create the repository-authored `.pslx` with only hierarchy/equation contracts and exact external ports; do not embed a complete station or link and do not copy a customer project.
- [ ] Create `PROVENANCE.md` mapping every fixed value to a public source or labeled original derivation and explicitly recording AVM limitations.
- [ ] Implement the auditor, manifest hash verification, exact recursive file-set check, version check (`4.6.2`), and safe materialization into `.pscad-mcp/mmc-libraries/` using atomic replacement.
- [ ] Run `python scripts/audit_mmc_assets.py --asset-root pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1` and focused asset tests; commit only when the audit is green.

## Task 6: Encode the fixed blueprint, catalog, sequence, acceptance contract, and golden asset

**Files:** `blueprint.json`, `catalog-pscad-4.6.2.json`, `controls.json`, `operating-sequence.json`, `acceptance.json`, `golden.json`, `manifest.json`, `tests/test_mmc_production_assets.py`.

- [ ] Write tests asserting nominal 640 kV pole-to-pole voltage, approximately 1000 MW transfer, two stations, twelve unique arms, positive/negative buses, two conductor paths, exact custom definitions, fixed settings, four required acceptance windows, and complete output selector/unit coverage.
- [ ] Encode the two-terminal symmetrical-monopole topology with six visible `MMCAverageArm` instances in each station, explicit upper/lower phase labels, no ground return net, controller components, line/cable path, meters, and all output endpoints.
- [ ] Encode a fixed v2 result profile with project-qualified paths for every required category in the design document; no generic alias is used for planning or command binding.
- [ ] Build the manifest only from SHA-256 values of the exact child file set and assert loading fails closed if any file is added, removed, or changed.
- [ ] Use independently reviewed reference data for `golden.json`; if no licensed reference output is available, keep the asset explicitly non-accepted and do not synthesize a passing waveform.
- [ ] Run all production-asset and profile tests and commit.

## Task 7: Build the deterministic MMC planner

**Files:** `mmc/planner.py`, `mmc/catalog.py` if needed, `tests/test_mmc_planner.py`.

- [ ] Write a test that calls `create_plan()` twice with the same project identity, workspace, blueprint, and live inventory and asserts identical JSON payload, operation sequence, target paths, asset hashes, and `plan_hash`; assert the workspace and PSCAD inventory are unchanged.
- [ ] Write topology expansion tests asserting exactly 12 arms, six phase midpoints, two positive and two negative DC terminals, station-specific control roles, all planned output selectors, and no implicit or adaptive operation.
- [ ] Add failure tests for unsupported blueprint/version, missing live definition, missing port, wrong port kind/dimension, invalid parameter, existing final path, overlapping components, diagonal route, AC/DC short path, crossed pole, and output not backed by a declared measurement endpoint.
- [ ] Implement planner expansion through the stable `PscadService` boundary, exact catalog lookups, orientation-aware port positions, deterministic orthogonal routes, output/acceptance operation ordering, and canonical plan hashing.
- [ ] Run `pytest tests/test_mmc_planner.py -q` and commit.

## Task 8: Parse and independently validate the saved PSCX graph

**Files:** `mmc/project_graph.py`, `mmc/validator.py`, `tests/test_mmc_project_graph.py`, `tests/test_mmc_validator.py`, `tests/fixtures/mmc/*.pscx`.

- [ ] Write structured XML fixture tests for namespaces, component definitions, exact ports, orientations, wires, electrical/data net kinds, labels, and output selectors; never parse PSCX with regular expressions.
- [ ] Write mutation tests for every required failure: missing, swapped, duplicated, shorted, unconnected, and wrong-polarity arm; missing phase midpoint; crossed pole; AC-to-DC path; mixed electrical/data net; missing controller signal; wrong port dimension; and duplicate output selector.
- [ ] Implement a graph reader that normalizes only schema fields and retains source evidence for every observed component/net/finding.
- [ ] Implement exact blueprint-to-graph validation with `MMC_*` structural error codes and bounded JSON findings; acceptance must not trust accumulated API return values.
- [ ] Run focused graph/validator tests and commit.

## Task 9: Implement the MMC acceptance engine

**Files:** `mmc/acceptance.py`, `tests/test_mmc_acceptance.py`.

- [ ] Write tests for finite non-empty strictly increasing aligned samples, exact unit matching, four required windows, missing/ambiguous channels, and no extrapolation; assert states are `observed`, `derived`, `missing`, or `invalid`.
- [ ] Write physical tests for DC polarity/symmetry/current direction/power, AC P/Q and loss balance, phase KCL, arm equations, station/arm energy positivity and ripple, capacitance consistency, circulating RMS/second-harmonic bounds, modulation margin/clipping/saturation duration, PLL lock/dq/integrator limits, precharge/deblock order, reversal zero crossing/slope/overshoot/settling, and reverse steady state.
- [ ] Write tests asserting AVM-only limitations are always reported as `not_modeled` and cannot become passing metrics; no missing measurement may be replaced by zero.
- [ ] Implement fixed golden NRMSE/max-error comparison with channel scale floors and Stage A provenance checks, plus independent physical checks. Return `PASS` only when every required check passes.
- [ ] Run `pytest tests/test_mmc_acceptance.py -q` and commit.

## Task 10: Implement journals, staged executor, failure containment, and lifecycle service

**Files:** `mmc/journal.py`, `mmc/executor.py`, `mmc/service.py`, `tests/test_mmc_executor.py`, `tests/test_mmc_service.py`, `tests/test_mmc_containment.py`.

- [ ] Write fake-service tests that record every component, parameter, port, connection, save, compile, run, output-read, acceptance, publication, and final compile operation; inject a failure after each operation and assert no subsequent operation runs, evidence is retained, and the final path remains absent.
- [ ] Write tests for exact expected plan hash, asset hash drift, pre-existing final destination, common LCC/MMC lease conflict, restart/interruption, timeout classification, candidate state history, and terminal journal reads.
- [ ] Implement staged directories under `.pscad-mcp/mmc-builds/<build_id>/candidates/0/`, atomic journals, common lease ownership, read-back postconditions, compile/run/output capture, independent graph/acceptance calls, and publication only after the accepted candidate is reopened and compile-smoke tested.
- [ ] Implement read-only `plan_model()` and `validate_model()`, confirmed asynchronous `build_model()`, and bounded `get_build_status()` with all required evidence fields and stable `BackendError` codes.
- [ ] Run focused service/executor/containment tests and commit.

## Task 11: Register the four Stage A tools and preserve the exact inventory

**Files:** `pscad_mcp/tools/mmc_tools.py`, `pscad_mcp/main.py`, `tests/test_mmc_tools.py`, inventory tests.

- [ ] Write tests for tool signatures, service routing, confirmation requirements, serialized errors, and the four names: `plan_mmc_model`, `build_mmc_model`, `get_mmc_build_status`, and `validate_mmc_model`. Do not register `design_mmc_model` until the separate Stage C plan.
- [ ] Implement wrappers that obtain the stable service from `pscad_manager.service`, never access vendor proxies, and preserve structured `BackendError` payloads through `register_tool`.
- [ ] Register the tool group and update exact inventory counts from 77 to 81 for Stage A while asserting all previous generic/HVDC/LCC/learning names remain present; Stage C will raise the inventory to 82 when `design_mmc_model` is added.
- [ ] Run `pytest tests/test_mmc_tools.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py -q` and commit.

## Task 12: Packaging, documentation, and install smoke coverage

**Files:** `pyproject.toml`, `scripts/verify_package.ps1`, `tests/test_install_smoke.py`, `README.md`, `docs/zh-CN/README.md`, `CHANGELOG.md`.

- [ ] Write packaging tests that build a wheel, install it into a clean virtual environment, load every MMC asset through package resources, recompute the manifest hashes, and verify all 81 Stage A tools are registered.
- [ ] Add recursive MMC asset package data without dropping existing templates or LCC assets.
- [ ] Document status vocabulary (`designed`, `planned`, `built`, `simulated`, `accepted`), fixed CIGRE-derived scope, AVM limitations, and the fact that submodule balance, switching stress/harmonics, thermal, DC fault blocking, grid-forming, and multi-terminal behavior are `not_modeled`.
- [ ] Run the package verification script and the focused installation tests; commit.

## Task 13: Licensed PSCAD 4.6.2 Stage A acceptance

**Files:** `tests/test_mmc_real_acceptance.py`, `tests/test_mmc_real_acceptance_contract.py`, `scripts/prepare_acceptance_workspace.ps1` if a helper is needed, acceptance evidence outside the repository.

- [ ] Write contract tests requiring an absolute disjoint timestamped workspace, Legacy backend, PSCAD 4.6.2, bounded JSON report, source/asset hashes, final project hash, twelve-arm structural evidence, all four sequence windows, independent validation, and final compile-smoke evidence.
- [ ] Implement the opt-in test to plan from an empty `.pscx`, build through public service boundaries, poll all lifecycle phases, independently validate the final project/output, verify the requested logical identity, and confirm every pre-existing source/asset file is unchanged.
- [ ] Run the exact licensed command only when the environment is available:

```powershell
$env:PSCAD_MCP_MMC_ACCEPTANCE = "1"
$env:PSCAD_MCP_BACKEND = "legacy"
$env:PSCAD_MCP_VERSION = "4.6.2"
$env:PSCAD_MCP_WORKSPACE = "D:\PSCAD-Workspace"
& .venv\Scripts\python.exe -m pytest tests/test_mmc_real_acceptance.py -q -s
```

- [ ] If the command is skipped or fails because PSCAD/license/reference output is unavailable, retain the failure report and mark Stage A as not accepted; do not change code or assets to manufacture a passing report.
- [ ] Run the full deterministic suite again with all licensed acceptance variables removed and `compileall`/`git diff --check`; review every plan requirement against the resulting evidence.

## Self-review checklist

- [ ] Every design section maps to a task: common extraction (1), records/schema (2), arm equations (3), controls/sequence (4), assets (5-6), planning (7), graph/structure (8), acceptance/golden (9), isolation/execution/publication (10), tools (11), packaging/claims (12), and licensed gate (13).
- [ ] Search the implementation instructions (excluding this self-review sentence) for `TBD`, `TODO`, `later`, `fill in`, and vague instructions; none may remain.
- [ ] Confirm the public names, MMC build-state values, asset paths, error prefixes, and inventory count are consistent across all tasks.
- [ ] Confirm no task adds Stage C `design_mmc_model`; that work must begin only from a separate Stage C plan after Stage A acceptance.
