# HVDC Simulation-Time Scheduling and Explicit Bindings Design

## 1. Purpose

The existing HVDC domain layer can inspect the real `difforder_new` project,
run a PSCAD 4.6 baseline, and read legacy `.inf` plus segmented `.out` results.
Real acceptance also exposed four remaining integrity gaps:

- timed events are dispatched from wall-clock elapsed time instead of EMTDC
  simulation time;
- semantic aliases do not prove that a mapped source is a writable PSCAD
  command parameter;
- several physically different voltage outputs map to the single
  `dc_voltage` canonical and are therefore rejected as ambiguous;
- a derived project can complete successfully without result files when its
  output setting remains disabled.

This design closes those gaps without weakening the existing source-project,
path-policy, confirmation, timeout, or application-wide scenario-lock safety
boundaries.

## 2. Scope

The implementation covers:

1. strict simulation-time event scheduling;
2. explicit, project-qualified command bindings;
3. explicit result-channel selectors and retained legacy metadata;
4. preflight validation of timing, commands, output settings, and result
   channels;
5. profile-driven breaker/protection edge and sequence semantics;
6. reproducible scenario and acceptance evidence.

The implementation does not insert new PSCAD components, rewire a canvas,
modify a source project, infer per-unit base values, or claim an external
breaker/fault injection succeeded without a confirmed writable binding.

## 3. Scheduling Architecture

The scenario orchestrator delegates every timed event to a dedicated
simulation-time scheduler. It must never use wall-clock elapsed time as the
meaning of `events[].time_s`.

The scheduler selects capabilities in this order:

1. **Backend-native scheduled events.** The backend accepts a set of commands
   associated with EMTDC simulation timestamps and reports whether each event
   was registered.
2. **Simulation-clock polling.** When native scheduling is unavailable, the
   backend exposes the current EMTDC simulation time. The scheduler polls that
   value and dispatches a command only when the reported time reaches the
   requested timestamp.
3. **Structured rejection.** If neither capability exists, preflight raises
   `HVDC_TIMED_CONTROL_UNAVAILABLE` before any component parameter is written
   or the project is run.

There is no wall-clock compatibility mode. Wall-clock deadlines remain valid
only for containment, vendor-call timeout, and liveness checks; they do not
represent EMTDC event time.

Every applied event records:

- requested simulation time;
- observed simulation time at dispatch or backend acknowledgement;
- timing error;
- scheduling mode (`native` or `simulation_clock_polling`);
- component and parameter binding identity;
- write/read-back outcome.

## 4. Profile Schema

Existing `mappings` remain a read-only evidence mechanism for topology,
labels, measurements, and unresolved concepts. They are not sufficient to
authorize a mutation or select a final result channel.

Profiles may add these sections:

```json
{
  "profile_version": 2,
  "project_fingerprints": [],
  "command_bindings": [],
  "result_channels": [],
  "sequences": []
}
```

### 4.1 Project fingerprints

A fingerprint associates project-specific bindings with observed project
structure. It contains stable evidence such as project stem, PSCAD version,
reachable definition names, component definition, canvas name, and selected
parameter names. A source-file hash may be recorded for audit but must not be
the only matching mechanism because the derived project can legitimately
change output settings.

Preflight rejects project-specific bindings when the current derived project
does not satisfy their fingerprint.

### 4.2 Command bindings

Each command binding contains:

- canonical command name;
- component selector using canvas, definition, stable component evidence, and
  optionally an exact component ID;
- exact writable parameter name;
- allowed values or numeric range;
- command semantics such as `active_high`, `active_low`, `open`, `close`,
  `enable`, or `disable`;
- whether read-back is required;
- optional backend-native scheduling metadata.

The binding resolver must return exactly one component parameter. Zero or
multiple matches produce `HVDC_MAPPING_MISSING` without mutation. Display and
identity parameters such as `Name`, `Text`, `Caption`, `Comment`, `Title`,
`Description`, and unit metadata remain prohibited even if a profile names
them.

Before an initial parameter change, the runner reads the old value, writes the
new value, and reads it back when the backend supports parameter reads. A
failed read-back triggers restoration of the old value and aborts the run.
For timed events, a failed dispatch or read-back triggers containment and an
unknown or failed outcome; it is never recorded as successfully applied.

### 4.3 Result channels

Each result selector contains:

- canonical result name;
- exact group/path and description, with optional legacy `call_id`;
- expected units;
- station, pole, terminal, or breaker location;
- polarity and sign convention when applicable;
- optional per-unit base reference.

Aliases may help diagnostics, but final result selection requires the explicit
selector. Multiple matches remain an error.

The Breaker profile separates at least these channels:

- `dc_voltage_breaker`: `loadbreaker_3/UMC`, `kV`;
- `dc_current_breaker`: `loadbreaker_3/IMC`, `kA`;
- `breaker_command_observed`: `loadbreaker_3/BrkOrd1`;
- `dc_voltage_rectifier_pole1`: `Main/VDCRp1`, `pu`;
- `dc_voltage_inverter_pole1`: `Main/VDCIp1`, `pu`;
- `dc_voltage_rectifier_pole2`: `Main/VDCRp2`, `pu`;
- `dc_voltage_inverter_pole2`: `Main/VDCIp2`, `pu`.

The profile must not convert a per-unit result to `kV` unless an explicit base
value is present.

## 5. Legacy Output Metadata

The legacy reader retains `call_id`, description, group, path, `Units`, `Max`,
and `Min` from every `PGB` record in the `.inf` file. Result-channel resolution
can select by exact path and optionally verify `call_id`.

Metrics consume normalized channel records that retain unit and semantic
metadata. A derived metric is unavailable when its required units, direction,
polarity, or base values are unconfirmed.

## 6. Preflight and Scenario Data Flow

Scenario execution follows this order:

1. Validate the scenario schema, confirmation flag, workspace path, source
   project, and pre-existing derived target.
2. Load the profile and validate its schema and inheritance.
3. Inspect the derived project and verify the selected project fingerprint.
4. Resolve every command binding uniquely and validate every requested value.
5. Select a simulation-time scheduling capability. Reject timed events if no
   strict capability exists.
6. Inspect output settings and required output channels.
7. If output is disabled, change the output setting only on the derived
   project and only when `confirm=true`; verify the value before continuing.
8. Apply initial parameter changes with old-value capture and read-back.
9. Start the run and dispatch timed events through the simulation-time
   scheduler.
10. Confirm the terminal project state, discover outputs constrained by target
    path and run start time, and validate companion files.
11. Resolve explicit result selectors and calculate only metrics supported by
    confirmed metadata.
12. Release the application-wide scenario lease only after all vendor
    operations and settlement tokens finish.

Any failure before step 8 is side-effect free. A failure after a vendor run or
mutation begins uses the existing containment logic and preserves
`needs_review` or `unknown_outcome` when the final external state cannot be
proved.

## 7. Output Readiness

Output preflight determines whether the derived project is configured to
write a supported result format. `PlotType=0` is considered disabled.

When output is disabled:

- the source project is never changed;
- an unconfirmed scenario fails with a structured suggested action;
- a confirmed scenario may set the supported legacy OUT value on the derived
  project, then read it back;
- the previous value is recorded in the scenario audit record;
- absence of expected `.inf` and segmented `.out` files after a successful run
  produces `INCOMPLETE_ANALYSIS`, not a successful empty analysis.

Preflight also reports whether the selected result paths are present in the
project's output definitions. Missing result selectors do not authorize the
runner to add graphs or output channels automatically.

## 8. Breaker and Protection Metrics

Binary channel semantics are profile-driven. Each relevant result selector
defines active level and transition direction. Both rising and falling edges
are supported.

Sequence metrics use a named sequence from the profile rather than a hard-coded
tuple. A Breaker project sequence can, for example, require:

```text
protection_trip -> breaker_command_observed -> breaker_open
```

The implementation does not assume that this example applies until the real
project's channels and active levels are confirmed.

`trip_delay_s` identifies the configured initiating and completing edges. A
missing edge, reversed order, ambiguous active level, or incompatible time
domain produces an invalid metric and `INCOMPLETE_ANALYSIS`.

`dc_power` is calculated only when voltage and current units and sign
conventions are compatible. `kV * kA` yields `MW`; per-unit values require
explicit base data.

## 9. Audit and Reproducibility

Each scenario record includes:

- source and derived project paths and hashes;
- profile name, version, and hash;
- matched project fingerprint;
- PSCAD, compiler, and backend version details when available;
- run settings and output-setting changes;
- resolved command and result bindings;
- requested and observed event times;
- terminal status, containment status, and pending vendor operations;
- output file paths, sizes, modification times, and hashes;
- metric definitions and warnings.

Records remain JSON-safe. Persistent storage of scenario records is optional
for this change; the full audit payload must nevertheless be returned and be
suitable for later persistence.

## 10. Error Model

The implementation reuses existing structured errors and adds focused details:

- `HVDC_TIMED_CONTROL_UNAVAILABLE`: strict simulation-time scheduling is not
  available;
- `HVDC_MAPPING_MISSING`: command or result binding is absent, ambiguous, or
  does not match the project fingerprint;
- `HVDC_SCENARIO_INVALID`: value, profile schema, or timing request is invalid;
- `HVDC_CAPABILITY_UNAVAILABLE`: the requested output correction or native
  schedule feature is unsupported;
- `INCOMPLETE_ANALYSIS`: outputs or confirmed metric inputs are missing.

Errors include the unresolved canonical, selector evidence, project target,
the stage that failed, and a suggested action where possible.

## 11. Testing Strategy

### Unit tests

- profile v2 schema validation and inheritance;
- unique command binding and fingerprint resolution;
- rejection of display/identity parameters;
- result selection by path, units, and `call_id`;
- rising/falling edge detection and profile-defined sequence ordering;
- unit-aware power calculation and per-unit refusal;
- legacy INF metadata retention.

### Scenario integration tests

- native scheduling is preferred when available;
- simulation-clock polling is used only with an EMTDC time capability;
- absence of both capabilities fails before any mutation;
- no path uses wall-clock elapsed time as event time;
- output-disabled preflight is side-effect free without confirmation;
- confirmed output correction affects only the derived project;
- failed write/read-back restores the initial parameter;
- scenario lease and containment behavior remain safe across timeouts and
  unsettled vendor calls.

### Legacy output regression

The real PSCAD 4.6 `.inf` plus segmented `.out` layout is exercised with
selectors for `UMC`, `IMC`, `BrkOrd1`, and the four station/pole voltage
channels. The previous single-`dc_voltage` ambiguity must not recur.

### Real PSCAD 4.6 acceptance

1. Hash the source project and dependencies.
2. Create or reuse a workspace-scoped derived copy.
3. Run a baseline with output readiness verified.
4. Resolve and display the proposed writable breaker/fault bindings.
5. Run one confirmed external event scenario only when the binding and strict
   simulation-time capability are both available.
6. Report requested event time, observed EMTDC time, and error.
7. Resolve `UMC`, `IMC`, `BrkOrd1`, and the station/pole voltage channels.
8. Report breaker/protection metrics only for confirmed active levels and
   sequence semantics.
9. Verify source hashes are unchanged and no PSCAD or simulation processes
   remain.

If the writable binding or strict timing capability cannot be confirmed, the
acceptance result is a successful safety rejection, not a successful external
injection.

## 12. Completion Criteria

The change is complete when:

- all existing generic and HVDC tests pass;
- regression tests prove wall-clock event timing is absent;
- a timed event without strict simulation-time capability fails before any
  write or run;
- unconfirmed command mappings cannot mutate a project;
- a confirmed derived project can correct disabled output settings safely;
- explicit selectors resolve the seven named Breaker result channels without
  `dc_voltage` ambiguity;
- units and edge semantics control metric availability;
- fresh PSCAD 4.6 acceptance either completes one real external event scenario
  or records a structured safety rejection with the missing capability;
- source files remain unchanged.
