# HVDC Domain Layer for PSCAD MCP

## 1. Goal

Upgrade the existing PSCAD MCP from a generic PSCAD automation surface into a
domain-aware HVDC assistant that can inspect HVDC projects, map PSCAD objects
to engineering concepts, execute repeatable operating/fault scenarios, and
extract engineering metrics from simulation outputs.

The first real acceptance baseline is the user's project family under
`C:\PSCADFiles\Breaker`, especially:

- `HVDC_Bipolar5kA500kVdifforder.pscx`;
- `TEST1\difforder_new.pscx`;
- `TEST1\difforder_change.pscx`;
- `TEST1\difforder.pscx`.

The design must not modify or copy these source projects automatically. Any
mutation must continue to flow through the existing confirmation and workspace
path policies.

## 2. Observed baseline

The repository currently exposes 60 generic tools for PSCAD lifecycle,
projects, simulation control, component/canvas operations, simulation sets,
parameter grids, and PSOUT reading. Both legacy PSCAD 4.6.x and modern PSCAD
5.x implement the structural backend contract. Real acceptance is documented
for PSCAD 4.6.2; PSCAD 5.x is currently contract-tested rather than verified
end to end.

The Breaker project family provides a concrete domain vocabulary. A read-only
XML inspection of `TEST1\difforder_new.pscx` found a PSCAD 4.6.2 EMTDC project
with definitions including `Rectifier_AC`, `Inverter_AC`, `RectCC`,
`RectPole`, `InverterPole`, `InvCtrl`, `Station`, `TransLine`, `TL1`, `TL2`,
`loadbreaker_3`, and `DC_Model_XS800`. The canvas also contains named breaker,
pole, line, measurement, and control components. This makes it a suitable
first regression fixture for bipolar HVDC and breaker/protection workflows.

## 3. Design principles

1. Keep the existing 60 generic tools backward compatible.
2. Add a separate HVDC domain layer rather than teaching every generic tool
   about every HVDC topology.
3. Preserve provenance: every inferred engineering object must retain the
   source project, canvas, component ID, definition, and parameter names used
   for the inference.
4. Distinguish observed values from inferred values. The MCP must never present
   a heuristic topology or metric as a directly measured fact.
5. Start with deterministic rules and explicit configuration. LLM reasoning
   may explain or compose workflows, but domain calculations must be
   reproducible Python code.
6. Fail closed when required channels, components, or mappings are missing.

## 4. Proposed architecture

```text
PSCAD MCP
├── Existing generic PSCAD tools (unchanged contract)
└── HVDC domain package
    ├── project scanner and evidence model
    ├── topology classifier
    ├── semantic mapping registry
    ├── scenario compiler/runner
    ├── result channel resolver
    ├── metric calculators and verdicts
    └── HVDC MCP tool registration
```

### 4.1 Evidence model

Create JSON-safe dataclasses/models for:

- `HvdcProjectEvidence`: project identity, PSCAD version, definitions,
  component records, labels, ports, parameters, and warnings;
- `HvdcAsset`: normalized asset kind (`rectifier`, `inverter`, `converter`,
  `pole`, `dc_line`, `breaker`, `controller`, `measurement`, `ac_system`,
  `filter`, `other`), source references, confidence, and evidence strings;
- `HvdcTopologySummary`: topology family (`lcc`, `vsc_2level`, `mmc`,
  `unknown`), polarity (`bipolar`, `monopolar`, `unknown`), terminal count,
  breaker/protection presence, and unresolved questions;
- `HvdcMapping`: canonical signal/parameter name, source component/parameter,
  units, observed/inferred status, and confidence;
- `HvdcScenarioResult`: run identity, changed parameters, output files,
  resolved channels, calculated metrics, warnings, and verdict.

All records must be JSON serializable and retain source IDs for auditability.

### 4.2 Topology classification

The first classifier is rule-based and evidence-driven:

- `RectCC`, `RectPole`, `InverterPole`, `InvCtrl`, and `Rectifier_AC` are
  strong LCC/bipolar evidence;
- `MMC`, `submodule`, `arm`, `SM`, or vendor-specific MMC definitions are
  strong MMC evidence;
- `VSC`, `IGBT`, `PLL`, `dq`, and two-level bridge definitions are VSC
  evidence;
- `breaker`, `loadbreaker`, `DC breaker`, `diff`, `protection`, and line
  definitions identify breaker/protection and DC-line evidence;
- explicit project/definition/annotation labels can override weak name-based
  evidence, but overrides must be recorded.

The classifier returns `unknown` with evidence and unresolved questions when
confidence is insufficient. It must not force LCC/VSC/MMC based only on a
single generic component name.

### 4.3 Semantic mapping registry

Mappings are configuration-driven, not hard-coded into the scanner. A mapping
entry contains:

```json
{
  "canonical": "dc_current",
  "aliases": ["Idc", "IDC", "RECTIFIER CURRENT"],
  "source_kinds": ["datalabel", "meter", "control"],
  "unit_family": "current",
  "direction": "measurement"
}
```

Initial canonical concepts:

- `dc_voltage`, `dc_current`, `dc_power`;
- `ac_voltage_rms`, `ac_current_rms`, `active_power`, `reactive_power`;
- `firing_angle`, `extinction_angle`, `commutation_overlap`;
- `power_order`, `current_order`, `voltage_order`, `dc_voltage_order`;
- `breaker_command`, `breaker_status`, `fault_command`, `protection_trip`;
- `pll_angle`, `pll_frequency`, `dq_current`, `dq_voltage`;
- `submodule_capacitor_voltage`, `arm_current`, `arm_energy`.

The first Breaker fixture is expected to resolve at least DC current, rectifier
and inverter assets, pole labels, breaker components, line interfaces, and
protection/control signals where the source labels expose them. Unresolved
concepts are returned explicitly.

## 5. HVDC domain tools

Add a new tool group without removing or renaming the current 60 tools.
Initial tools:

1. `inspect_hvdc_project(project_name, canvas_name="Main")`
   - returns evidence, topology summary, assets, mappings, confidence, and
     warnings;
2. `get_hvdc_assets(project_name, kind=None)`
   - filters normalized assets while preserving source references;
3. `get_hvdc_mappings(project_name, canonical=None)`
   - returns semantic parameter/signal mappings and unresolved concepts;
4. `validate_hvdc_project(project_name, profile="auto")`
   - checks required assets, duplicate mappings, missing channels, unit
     conflicts, and profile-specific prerequisites;
5. `run_hvdc_scenario(project_name, scenario, confirm=False)`
   - validates a declarative scenario, applies only approved changes, runs the
     project or simulation set, and returns a scenario ID;
6. `get_hvdc_scenario_status(scenario_id)`
   - reports run status and structured project messages;
7. `analyze_hvdc_results(scenario_id, metrics=None)`
   - resolves configured channels and calculates bounded metrics;
8. `compare_hvdc_scenarios(scenario_ids, metrics=None)`
   - returns aligned metric comparisons and verdict differences;
9. `list_hvdc_profiles()`
   - lists supported profiles and their prerequisites;
10. `register_hvdc_profile(profile_name, mapping_file, confirm=False)`
    - adds a user-scoped mapping/profile file under the configured workspace.

The exact tool count is intentionally not fixed to 60 after this upgrade; the
existing 60-tool compatibility test remains, while a separate domain inventory
test enforces the new names.

## 6. Profiles and scenarios

Initial profiles:

- `lcc_bipolar_generic`;
- `vsc_2level_generic`;
- `mmc_bipolar_generic`;
- `hvdc_breaker_difforder` for the user's Breaker project family.

Scenario schema:

```json
{
  "name": "dc_fault_breaker_trip",
  "profile": "hvdc_breaker_difforder",
  "project": "difforder_new",
  "parameter_changes": [],
  "events": [
    {"time_s": 1.0, "target": "fault_command", "value": 1},
    {"time_s": 1.05, "target": "breaker_command", "value": 1}
  ],
  "run": {"timeout_s": 300},
  "analysis": {
    "metrics": ["dc_current_peak", "dc_voltage_min", "trip_delay_s"]
  }
}
```

The scenario runner does not invent controls or insert new fault components in
the first release. It can only set mapped parameters/controls that already
exist in the project, and it must report unsupported events as structured
capability errors.

## 7. Result metrics

Implement deterministic, bounded metrics over normalized sampled channels:

- extrema and steady-state mean/RMS;
- step response peak, undershoot, settling time, and recovery time;
- threshold crossing and trip delay;
- DC power as `Vdc * Idc` when both channels are available;
- voltage/current imbalance between poles when paired channels are mapped;
- breaker/protection sequence ordering;
- LCC angle metrics only when angle channels are explicitly mapped;
- MMC capacitor/arm imbalance only when the corresponding channels are
  explicitly mapped.

Each metric returns value, units, time window, source channels, method, and
`observed`/`derived` status. Missing channels produce warnings and an
`INCOMPLETE_ANALYSIS` verdict rather than fabricated zeros.

## 8. Safety and error handling

- Source projects under `C:\PSCADFiles\Breaker` are read-only inputs unless the
  user configures that directory as the MCP workspace and confirms a mutation.
- Scenario execution must use copied/derived project targets for destructive
  parameter sweeps when possible.
- Existing path policy, confirmation gates, executor recovery, and backend
  error serialization remain authoritative.
- New errors include `HVDC_PROFILE_NOT_FOUND`, `HVDC_TOPOLOGY_AMBIGUOUS`,
  `HVDC_MAPPING_MISSING`, `HVDC_SCENARIO_INVALID`,
  `HVDC_CAPABILITY_UNAVAILABLE`, and `INCOMPLETE_ANALYSIS`.
- Every error includes the unresolved concept, source evidence, and a
  suggested action where available.

## 9. Testing and acceptance

### Unit tests

- XML/evidence extraction from small fixtures derived from the Breaker project;
- topology classification for LCC, VSC, MMC, bipolar, and unknown cases;
- mapping alias resolution and unit conflict handling;
- scenario schema validation and confirmation behavior;
- metric calculations with complete and missing channels;
- JSON serialization and stable error payloads.

### Integration tests

- inspect `TEST1\difforder_new.pscx` without PSCAD;
- validate that breaker/line/pole/control evidence is found;
- resolve configured Breaker profile mappings;
- run mock scenario orchestration against the existing backend fakes;
- preserve the exact existing 60-tool inventory.

### Real acceptance, when PSCAD 4.6.2 is available

1. Load a copied `difforder_new` project.
2. Inspect and report bipolar/LCC/breaker evidence.
3. Run a baseline scenario.
4. Run one user-approved breaker/fault scenario using existing controls.
5. Read the generated PSOUT and report at least DC current, DC voltage,
   breaker/protection sequence, and any unresolved mappings.
6. Verify the source project remains unchanged.

PSCAD 5.x acceptance remains a follow-up until a licensed installation is
available.

## 10. Non-goals for the first release

- automatic redesign of the HVDC control system;
- claiming compliance with a grid code or protection standard;
- inserting arbitrary PSCAD components or rewiring a user's project;
- inferring exact physical units from ambiguous labels;
- replacing PSCAD's native parameter-grid or simulation-set features;
- supporting every vendor's custom MMC or protection naming convention without
  a profile mapping.

## 11. Delivery phases

1. **Foundation:** evidence models, XML scanner, profile registry, and
   deterministic classifier.
2. **Domain API:** semantic mappings, validation, and new read-only tools.
3. **Scenario execution:** declarative scenarios and safe orchestration on top
   of existing run/settings/output tools.
4. **Analysis:** metrics, comparisons, and structured verdicts.
5. **Breaker acceptance:** profile and regression fixtures for
   `C:\PSCADFiles\Breaker`.
6. **Expansion:** official PSCAD example projects for generic LCC, VSC, and
   MMC profiles.
