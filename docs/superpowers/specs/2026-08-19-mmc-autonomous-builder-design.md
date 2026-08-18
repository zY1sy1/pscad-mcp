# MMC Autonomous Model Builder Design

## Context

The current HVDC domain layer can classify projects containing MMC-related
names and exposes a read-only generic profile for arm current, equivalent
submodule capacitor voltage, and circulating current. It does not contain an
MMC electrical model, topology blueprint, station controller, initialization
sequence, structural validator, sizing method, or licensed PSCAD acceptance.

The approved delivery sequence has two stages:

1. Stage A constructs and accepts a fixed CIGRE B4-derived, two-terminal,
   symmetrical-monopole half-bridge MMC average-value model in PSCAD 4.6.2.
2. Stage C adds an unrestricted-rating design entry point. Arbitrary finite
   inputs may be submitted, but a final project is published only when the
   derived design passes analytic constraints and its complete PSCAD startup,
   forward-power, reversal, and reverse-power acceptance.

Stage C does not promise that every rating tuple is physically feasible. It
promises deterministic feasibility evidence, bounded candidate evaluation,
clear conflict reporting, and nearest feasible suggestions when no accepted
model can be produced.

## Decisions Already Made

- PSCAD 4.6.2 and the Legacy Automation Library are the first licensed target.
- The fixed system is a two-terminal symmetrical monopole with nominal
  pole-to-pole voltage of 640 kV and nominal transfer of approximately 1000 MW.
- The converter is a half-bridge average-value model, not an equivalent-switch
  or detailed per-submodule switching model.
- The original companion library is packaged and publicly redistributable.
- The companion library exposes an average arm; each station's six arms remain
  visible on the generated main canvas.
- Acceptance covers controlled precharge, deblocking, forward steady state,
  power reversal, and reverse steady state.
- Stage C accepts ratings without a fixed engineering envelope, but invalid or
  infeasible designs are never published.
- Stage C changes numeric ratings and derived parameters only. It remains a
  two-terminal, symmetrical-monopole, half-bridge AVM with `P/Q` control at one
  station and `Vdc/Q` control at the other.
- Planning is read-only; mutation requires exact hashes and explicit
  confirmation.
- Golden results and independent physical invariants are both required.

## Goals

1. Construct the fixed MMC case from an empty `.pscx`, not a copied complete
   project.
2. Keep both stations, all twelve arms, AC interfaces, DC conductors, and
   measurements structurally auditable.
3. Preserve arm energy, upper/lower-arm dynamics, circulating current, and
   modulation limits in the average model.
4. Provide a deterministic startup and bidirectional power-transfer sequence.
5. Reuse only proven generic LCC builder infrastructure while keeping MMC
   topology, control, sizing, and acceptance domain-specific.
6. Add an arbitrary-input design workflow that publishes only dynamically
   accepted candidates.
7. Retain exact input, equation-version, candidate, plan, model, output, and
   acceptance evidence for every published project.
8. Preserve all existing generic, HVDC, and LCC public tool contracts.

## Non-Goals

- Individual IGBT and diode switching behavior.
- Per-submodule capacitor balancing or sorting algorithms.
- Semiconductor thermal design or junction-temperature claims.
- Switching-frequency harmonics, electromagnetic interference, or insulation
  coordination claims from the average-value model.
- DC fault blocking by a half-bridge MMC.
- Grid-forming, black-start, offshore-frequency, or weak-grid stabilization in
  the first fixed profile.
- Multi-terminal coordination in Stage A.
- Guaranteed feasibility for every numeric Stage C input.
- Automatic publication when only compilation or a partial simulation passes.
- Copying vendor or local customer definitions into packaged assets.

## Dependency And Common Builder Extraction

Stage A starts after the fixed LCC builder has passed its licensed PSCAD 4.6.2
acceptance. At that point, shared behavior has two proven consumers, which
justifies extracting these implementation-neutral modules into
`pscad_mcp.hvdc.builders.common`:

- manifest and package-resource validation;
- immutable component, port, parameter, net, operation, and plan records;
- orientation-aware port coordinates and orthogonal routing;
- structured PSCX component and connectivity parsing;
- atomic journals and the cross-process workspace lease;
- asynchronous job state persistence;
- staged mutation and transactional final publication; and
- bounded sampled-channel validation primitives.

The extraction must retain the LCC public API, plan payload, plan hash, state
history, error payload, and licensed behavior. An internal module move is not
permission to weaken LCC tests or to create a universal electrical validator.
LCC and MMC keep separate planners, companion-library auditors, structural
rules, controllers, profiles, and physical acceptance engines.

If MMC work begins before the LCC implementation is accepted, MMC must wait at
this dependency gate. It must not duplicate the planned common executor and
then leave two divergent transactional builders.

## Architecture

```text
fixed packaged profile or Stage C design record
    -> MmcBuilderService
       -> MMC schema and exact component catalog
       -> MMC planner and immutable candidate plan
       -> common staged executor through PscadService
       -> common PSCX graph plus MMC topology validation
       -> compile/run/output capture
       -> MMC golden, dynamic, and physical acceptance
       -> transactional publication
```

MMC-specific modules live under `pscad_mcp.hvdc.builders.mmc`:

- `models.py`: MMC station, arm, control, design, candidate, and acceptance
  records.
- `schema.py`: fixed blueprint and Stage C input validation.
- `planner.py`: expansion of two stations, twelve arms, connections, output
  channels, and candidate attempts.
- `sizing.py`: algebraic Stage C sizing and ranked candidate generation.
- `controls.py`: controller gains, bandwidth separation, limits, and operating
  sequence definitions.
- `validator.py`: saved-project arm, station, polarity, and signal topology
  checks.
- `acceptance.py`: startup, energy, circulating-current, modulation, power, and
  reversal checks.
- `assets.py`: MMC-specific companion-library and parameter-provenance audit.
- `service.py`: public MMC planning, design, build, status, and validation
  operations.

No raw Legacy proxy is exposed through an MCP tool. Mutation remains behind
`PscadService`. A missing service capability must be added to the stable backend
and service protocols with Legacy and Modern fail-closed implementations before
the MMC builder uses it.

## Fixed Packaged Asset Set

Stage A packages:

```text
pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1/
  manifest.json
  blueprint.json
  catalog-pscad-4.6.2.json
  controls.json
  operating-sequence.json
  acceptance.json
  golden.json
  PROVENANCE.md
  library/cigre_mmc_avm_v1.pslx
```

`manifest.json` records schema versions, the required PSCAD version, and the
SHA-256 of every child. The exact recursive file set must match the manifest.
Unknown executable or library content fails asset loading.

The fixed profile is named `cigre_b4_p2p_avm_v1`. It is a CIGRE B4-derived
two-terminal test case, not a claim that the full CIGRE DC grid is implemented.
The asset ledger defines nominal pole-to-pole voltage as 640 kV and nominal
active-power magnitude as approximately 1000 MW. Every exact electrical and
control value must be mapped in `PROVENANCE.md` to a source location or to a
documented original engineering derivation.

Only values whose reproduction is permitted may enter the packaged JSON. If a
required CIGRE value cannot be legally reproduced, the asset must use and
document an independent engineering derivation; it must not silently copy the
restricted value. Release is blocked when provenance or redistribution status
is unresolved.

Golden data is generated from an independently assembled and reviewed
reference case, never from the builder under test. It records the blueprint,
library, control, compiler, EMTDC time-step, output-step, and source-output
hashes.

## Companion Library Boundary

The original `cigre_mmc_avm_v1.pslx` contains only hierarchy and equations the
automation API cannot author safely:

- `MMCAverageArm`;
- `MMCStationControl`;
- `MMCEnergyControl`;
- `MMCInitialization`; and
- dimensioned signal-interface helpers.

It must not contain a complete two-terminal link or a complete six-arm station
as one opaque component. Each station is assembled from six
`MMCAverageArm` instances on the main case canvas. The builder separately
places AC equivalents, converter transformers, AC connection reactors where
required, DC smoothing/current-limiting reactors, two DC conductors, line or
cable sections, buses, grounding references, meters, labels, and output
channels.

The library may reference PSCAD Master Library components by exact scoped name
but must not embed their definition bodies. Original custom code, equations,
forms, symbols, and Fortran fragments are covered by the repository license.
The asset audit rejects foreign scopes, absolute author-machine paths,
unmanifested files, unexpected definitions, and external-port drift.

## Average Arm Electrical Contract

Each station has upper and lower arms for phases A, B, and C. For a phase, the
sign convention is:

```text
i_upper = I_dc / 3 + i_phase / 2 + i_circulating
i_lower = I_dc / 3 - i_phase / 2 + i_circulating
```

Each arm includes arm resistance, arm inductance, a controlled inserted voltage
and an aggregate stored-energy state. The energy state obeys the declared
passive sign convention:

```text
W_arm = 0.5 * C_eq * V_cap_eq^2
dW_arm/dt = v_inserted * i_arm - p_loss_arm
```

The exact implementation may use energy directly as its numerical state, but
reported equivalent capacitor voltage must remain consistent with the equation
and configured `C_eq`. Negative stored energy, non-finite state, or a value
outside the declared protection range is a simulation failure.

Upper and lower inserted-voltage commands derive from the AC modulation,
common-mode energy, and circulating-current terms. Final insertion indices are
bounded to `[0, 1]`. The model outputs unclipped request, clipped value, margin,
and cumulative saturation time. Hidden unlimited modulation is forbidden.

The arm loss model is explicit and versioned. Stage A may use fixed conduction
and equivalent switching-loss coefficients suitable for AVM power balance. It
must not report semiconductor temperature or detailed switching loss.

## Fixed Main-Canvas Topology

The generated case contains two stations, `STATION_P` and `STATION_VDC`.
`STATION_P` controls active and reactive power. `STATION_VDC` controls
pole-to-pole DC voltage and reactive power. Each station contains:

- one three-phase AC equivalent and its impedance;
- one converter-transformer interface;
- upper and lower average arms for phases A, B, and C;
- positive and negative DC buses;
- PLL and dq current control;
- station energy and circulating-current control;
- startup/deblock logic; and
- exact measurement and output labels.

The two positive buses and two negative buses are connected by separate line or
cable paths. Normal current does not use ground as a return conductor. Ground
references required for numerical or measurement purposes may not create a
parallel power-return path.

The structural validator proves twelve unique arms, six phase midpoints, two
positive DC terminals, two negative DC terminals, correct upper/lower polarity,
no AC-to-DC short path, no crossed pole, no missing arm, and no mixed electrical
and data net. It verifies every required controller input and output exactly;
name-based inference is not accepted.

## Control Contract

Both stations use grid-following PLLs and dq current inner loops. The control
hierarchy is:

```text
STATION_P:   P reference, Q reference -> dq current references
STATION_VDC: Vdc reference, Q reference -> dq current references
both:        dq current control -> AC voltage/modulation request
both:        total energy and upper/lower energy difference control
both:        second-harmonic circulating-current suppression
both:        modulation, current, energy, and integrator limits
```

The controller definition records sample time, proportional and integral
gains, feed-forward terms, bandwidth targets, anti-windup method, limit values,
PLL bandwidth, and enable/reset behavior. Gains are never inferred from label
text at runtime.

The fixed controller must maintain bandwidth separation between PLL, outer
power/DC-voltage loops, energy loops, circulating-current loop, and inner
current loop. Exact requirements and margins live in `controls.json` and are
checked before simulation.

During power reversal, `STATION_VDC` remains the DC-voltage regulating terminal
and `STATION_P` ramps active-power order through zero. Control-role swapping is
not part of Stage A.

## Operating Sequence

`operating-sequence.json` declares EMTDC times, conditions, ramps, and output
windows for these phases:

1. `blocked_precharge`: valves blocked, controlled equivalent energy charging,
   bounded inrush, and controller reset.
2. `ready_to_deblock`: PLL locked, arm energies inside the ready band, DC and AC
   measurements valid, and no protection limit active.
3. `forward_ramp`: deblock and ramp `STATION_P` to positive nominal transfer.
4. `forward_steady`: hold and collect the forward acceptance window.
5. `power_reversal`: ramp active-power order through zero to the negative
   nominal transfer while `STATION_VDC` holds DC voltage.
6. `reverse_steady`: hold and collect the reverse acceptance window.

The sequence is implemented by existing project controls and explicit command
bindings, not wall-clock mutation. A condition failure, overcurrent, energy
limit, PLL loss, modulation saturation timeout, or stalled EMTDC clock stops
the remaining sequence and prevents publication.

## Public Tool Contract

Stage A adds four tools:

### `plan_mmc_model`

Read-only inputs are project name, workspace folder, simulation-duration
extension, and `model` defaulting to `cigre_b4_p2p_avm_v1`. In Stage C it may
instead receive a workspace `design_hash`. It returns exact asset/design
hashes, expanded components, nets, settings, sequence, candidate attempts,
acceptance gates, target paths, and `plan_hash`. It performs no write, project
load, or PSCAD mutation.

### `build_mmc_model`

It accepts the planning inputs, exact `expected_plan_hash`, optional exact
`expected_design_hash`, and `confirm=false`. Mutation begins only when
confirmation is true and all hashes recompute exactly. It starts a background
build and returns `build_id` and initial status.

### `get_mmc_build_status`

It returns phase, completed operations, current candidate, PSCAD progress,
read-back evidence, structural findings, acceptance windows, retained evidence
paths, terminal error, and final project/output paths when published.

### `validate_mmc_model`

It reads an existing `.pscx` and optional output without changing, saving,
building, or running the project. It validates the structural profile and, when
output is supplied, all applicable dynamic and physical criteria. No output
means dynamic acceptance is `not_evaluated`, never passed.

Stage C adds one tool:

### `design_mmc_model`

It accepts unit-bearing ratings and design objectives and returns a deterministic
analytic design report, ranked immutable candidates, constraint margins,
nearest feasible suggestions, and `design_hash`. It also accepts
`confirm=false`. Without confirmation it performs no write and returns the
complete bounded design payload for review. With confirmation it recomputes the
same payload and atomically persists it under the configured workspace using
its content hash. It does not call PSCAD and is bounded to complete
synchronously. Expensive candidate simulations occur only inside the confirmed
asynchronous build.

After both LCC and MMC stages are installed, the expected tool inventory is 78
after Stage A and 79 after Stage C.

## Stage C Input Contract

Required unit-bearing inputs are:

- pole-to-pole DC voltage;
- signed active-power rating;
- AC line-to-line RMS voltage at each terminal;
- grid frequency at each terminal;
- short-circuit ratio and X/R at each terminal;
- line/cable kind, length, and distributed or lumped model choice;
- reactive-power objective at each terminal;
- maximum equivalent arm-energy or capacitor-voltage ripple; and
- required forward-to-reverse power-ramp duration.

Optional inputs include preferred equivalent submodule voltage, transformer
ratio, arm inductance, energy-to-power ratio, loss coefficients, control
bandwidth targets, and stricter current/modulation limits. An optional value is
a constraint, not a hint that the solver may silently ignore.

Every numeric value must be finite, have an explicit supported unit, and obey
basic sign/domain rules. There is no fixed engineering rating envelope, but
computational safety limits bound input length, numeric magnitude, candidates,
iterations, simulation duration, and output samples. A magnitude that cannot be
represented safely is invalid input, not an infeasible electrical design.

## Stage C Analytic Sizing

The sizing engine uses versioned equations and unit conversions to derive:

- nominal DC current from power and DC voltage;
- converter-side AC voltage and transformer ratio for target modulation margin;
- AC phase current and upper/lower arm RMS and peak current;
- equivalent submodule count and voltage when requested for reporting;
- aggregate arm energy, equivalent capacitance, and capacitor-voltage target;
- arm inductance and resistance/loss assumptions;
- DC line parameters from the declared line model;
- current, energy, PLL, outer-loop, inner-loop, and circulating-current
  bandwidth candidates; and
- EMTDC time step, output step, startup ramps, and simulation duration.

Core feasibility includes voltage reachability, transformer ratio, modulation
margin, current rating, stored-energy positivity, allowed energy ripple,
capacitor voltage, arm di/dt, line drop, terminal short-circuit strength,
control bandwidth separation, numerical time-step resolution, and power/loss
balance.

The sizing engine generates a deterministic ranked set of no more than 24
analytic candidates. It returns `infeasible` when none passes analytic checks.
It returns `analytically_feasible` when at least one passes, but this status is
not permission to publish a model. The design record contains the complete
candidate set and its ordering; the builder may not invent an unplanned
candidate after confirmation.

Nearest feasible suggestions are computed by projecting failed constraints
onto one or two user-facing variables at a time. Suggestions include the
changed values, units, resolved constraints, remaining conflicts, and distance
from the request. They are advice only and require a new design call and hash.

## Stage C Candidate Simulation

`plan_mmc_model` selects at most eight highest-ranked analytic candidates for
PSCAD evaluation and includes every one in `plan_hash`. A confirmed build uses
separate candidate staging directories and evaluates them in fixed rank order.

Each candidate must complete the same startup, forward, reversal, and reverse
sequence. A candidate that compiles but fails physical acceptance is retained
as evidence and the next planned candidate is attempted. The first candidate
that passes every required criterion is eligible for transactional publication.
If all planned candidates fail, the job terminates with
`MMC_CANDIDATES_EXHAUSTED`; no final project is created.

Simulation results may rank or reject already planned candidates but may not
mutate their parameters. Adaptive parameters would change the accepted design
and require a new `design_mmc_model` call, new design hash, new plan, and new
confirmation.

## Design Record And Hash

Stage C design records are stored immutably under:

```text
.pscad-mcp/mmc-designs/<design_hash>.json
```

They are created only by `design_mmc_model(confirm=true)`. The confirmed call
must recompute the design from the same explicit inputs; it does not accept a
caller-supplied payload as trusted content. `plan_mmc_model` accepts only the
hash of a persisted record and remains read-only.

The hash covers normalized inputs and units, equation and constraint versions,
fixed control rules, all candidates and their order, feasibility findings, and
suggestions. It excludes timestamps and display-only text. An existing matching
record is reused. An existing mismatched record fails closed and is never
overwritten.

`plan_hash` additionally covers project/folder identity, target PSCAD version,
companion asset hashes, expanded components/nets/routes/settings, selected
candidate attempts, operating sequence, output selectors, acceptance contract,
and publication target.

## Build State, Isolation, And Publication

MMC and LCC share one workspace-scoped cross-process builder lease. Concurrent
builders must not manipulate the same PSCAD session or workspace. The MMC
state machine extends common stages with candidate evidence:

```text
validated -> staging_created -> components_placed -> parameters_verified
-> connections_verified -> structure_verified -> staging_saved -> compiled
-> startup_simulated -> forward_simulated -> reversal_simulated
-> reverse_simulated -> acceptance_passed -> published
```

Every nonterminal state can become `failed`, `timed_out`, or `interrupted`.
Stage C may transition from a failed candidate back to `staging_created` only
for the next candidate already listed in the plan; the candidate history itself
is append-only.

All construction occurs under
`.pscad-mcp/mmc-builds/<build_id>/candidates/<rank>/`. The final destination
must not exist. Every component, parameter, port, wire, label, setting, save,
output selector, and project identity is read back. After save, the independent
PSCX graph reader verifies the model instead of trusting accumulated API
responses.

Only an accepted staging candidate is saved as the requested final identity.
The candidate final file is reopened, structurally validated, and compile-smoke
tested. On failure, every builder-created candidate final artifact is moved
back into the evidence directory, leaving the final path absent. Pre-existing
files are never moved, deleted, or overwritten.

## Output Profile

The fixed v2 profile declares exact selectors and units for:

- pole-to-pole and pole-to-ground DC voltages at both terminals;
- positive and negative conductor currents;
- station AC active and reactive power;
- station DC power;
- three-phase AC voltage and current or dq equivalents;
- twelve arm currents;
- twelve arm energies and equivalent capacitor voltages;
- three circulating-current channels per station;
- upper/lower energy difference per phase;
- PLL frequency and lock state;
- active, reactive, and DC-voltage commands and measurements;
- unclipped and clipped modulation indices and margins;
- controller saturation flags and accumulated durations; and
- startup/deblock and reversal state signals.

Stage C emits an immutable project-qualified v2 profile inside the design
record. Generic alias resolution is not used for construction, command binding,
or acceptance.

## Acceptance Windows

The operating sequence declares four required windows:

1. `precharge_ready` before deblock;
2. `forward_steady` after the positive-power ramp;
3. `power_reversal` from ramp start through reverse settling; and
4. `reverse_steady` after negative-power settling.

Samples must be finite, non-empty, strictly increasing, unit-confirmed, and
aligned. Missing or ambiguous required data yields `INCOMPLETE_ANALYSIS` and
prevents publication.

The fixed profile compares bounded, aligned golden waveforms using per-channel
NRMSE and maximum normalized error. Stage C has no golden waveform for arbitrary
ratings; it uses equation-derived expected values, dynamic envelopes, and all
independent physical checks. A custom model cannot pass by comparison with the
fixed CIGRE golden data.

## Physical And Dynamic Acceptance

Every published model must pass:

- DC voltage magnitude, pole symmetry, current direction, and requested power;
- AC P/Q tracking and terminal power/loss balance;
- phase KCL and the declared upper/lower arm-current decomposition;
- total station energy, each arm energy, upper/lower difference, positivity,
  and ripple;
- equivalent capacitor voltage consistency with energy and capacitance;
- circulating-current RMS and second-harmonic bounds;
- modulation reachability, margin, clipping, and maximum saturation duration;
- PLL lock, dq tracking, integrator state, and control-limit duration;
- bounded precharge current and energy convergence before deblock;
- correct deblock order and absence of protection-limit activation;
- power-order zero crossing before measured power direction reversal;
- reversal slope, overshoot, DC-voltage excursion, peak arm current, and
  settling time; and
- complete reverse steady-state repetition of polarity-aware checks.

The acceptance engine distinguishes `observed`, `derived`, `missing`, and
`invalid`. The final verdict is `PASS` only when every required check passes.
It never fabricates zero measurements.

The AVM report explicitly marks individual submodule balance, semiconductor
switching stress, switching harmonics, and DC fault blocking as `not_modeled`.
These cannot be promoted to passing metrics.

## Fixed Golden Acceptance

The fixed golden asset contains all four windows and records source hashes,
units, reference states, and channel-specific scale floors and limits. Sequence
alignment uses declared control-state transitions and an AC positive-going zero
crossing where phase alignment is required. Extrapolation is forbidden.

Golden regeneration is a separate maintainer command requiring literal
confirmation, an independently reviewed reference output, source hashes, and a
new provenance record. Normal planning, building, testing, installation, or
Stage C design never regenerates golden data.

## Errors

Errors use the stable `BackendError` shape with backend `hvdc`, operation,
JSON-safe evidence, retryability, and a concrete suggested action. MMC-specific
codes include:

- `MMC_BLUEPRINT_NOT_FOUND`
- `MMC_BLUEPRINT_INVALID`
- `MMC_MODEL_UNSUPPORTED`
- `MMC_ASSET_MISMATCH`
- `MMC_VERSION_UNSUPPORTED`
- `MMC_DEFINITION_MISSING`
- `MMC_PORT_MISMATCH`
- `MMC_PARAMETER_MISMATCH`
- `MMC_LAYOUT_INVALID`
- `MMC_PLAN_STALE`
- `MMC_DESIGN_INVALID`
- `MMC_DESIGN_STALE`
- `MMC_DESIGN_INFEASIBLE`
- `MMC_MODULATION_INFEASIBLE`
- `MMC_ENERGY_INFEASIBLE`
- `MMC_CONTROL_INFEASIBLE`
- `MMC_BUILD_CONFLICT`
- `MMC_POSTCONDITION_FAILED`
- `MMC_STRUCTURE_INVALID`
- `MMC_OUTPUT_INCOMPLETE`
- `MMC_CANDIDATE_FAILED`
- `MMC_CANDIDATES_EXHAUSTED`
- `MMC_ACCEPTANCE_FAILED`
- `MMC_BUILD_TIMED_OUT`

An infeasible result names failed constraints, requested and required margins,
ranked suggestions, and whether failure was analytic or observed in PSCAD. It
must not be reduced to a generic simulation error.

## Testing

### Common Extraction Regression

- Run every LCC schema, asset, route, graph, journal, executor, service, tool,
  packaging, and licensed acceptance test before and after common extraction.
- Assert unchanged LCC canonical plan payloads and hashes.
- Assert one common workspace lease excludes simultaneous LCC and MMC builds.

### MMC Unit And Structural Tests

- Test units, arm equations, sign conventions, energy/capacitance conversion,
  loss terms, modulation clipping, and saturation duration.
- Test six-arm station and twelve-arm link expansion.
- Test every missing, swapped, duplicated, shorted, unconnected, or
  wrong-polarity topology failure.
- Test startup and reversal state transitions and forbidden transitions.
- Test output-selector completeness and exact units.
- Parse synthetic and real-shape PSCX/PSLX fixtures with structured XML APIs.

### Stage C Sizing Tests

- Test dimensional analysis and deterministic design hashes.
- Test feasible and infeasible voltage/modulation combinations.
- Test energy, ripple, current, line-drop, short-circuit strength, and bandwidth
  conflicts.
- Use metamorphic scaling checks: consistent voltage/power scaling must preserve
  dimensionless margins while scaling currents and stored energy correctly.
- Test nearest-feasible suggestions without mutating the request.
- Test candidate ordering, maximum counts, and no candidate invention after
  planning.
- Test non-finite values, unsupported units, extreme magnitudes, and resource
  bounds.

### Executor And Failure Containment

- Record every service call and postcondition with a fake service.
- Inject failure after each component, parameter, connection, save, compile,
  run phase, output read, acceptance check, publication, and final compile.
- Verify no later operation runs, the final path remains absent, and evidence
  is retained.
- Verify Stage C proceeds only to the next planned candidate.
- Verify restart produces `interrupted`, not silent resume.

### Asset, License, And Packaging Tests

- Audit the original companion library definitions, internal equation code,
  external ports, foreign scopes, and absolute paths.
- Verify every fixed parameter has provenance or an original derivation.
- Build and install the wheel, then load and hash every MMC asset from package
  resources.
- Verify the installed MCP inventory and all previous tools.

## Licensed Acceptance

Stage A requires a real PSCAD 4.6.2 test that:

1. creates an isolated timestamped workspace;
2. plans the fixed model without writes;
3. builds from an empty case through public service boundaries;
4. proves twelve-arm structure and exact controls;
5. compiles and completes all operating-sequence phases;
6. passes fixed golden and physical acceptance;
7. independently revalidates the final project and output;
8. compile-smoke tests the final logical identity;
9. records a bounded JSON report; and
10. verifies packaged assets and pre-existing files are unchanged.

Stage C release requires a licensed matrix with at least six substantially
different analytically feasible requests and six analytically infeasible
requests. Feasible cases must vary voltage, power, AC voltage, frequency, grid
strength, line length/type, ripple objective, and reversal time. Every feasible
case must construct, complete the full sequence, and pass its own derived
acceptance. Every infeasible case must stop before project mutation and return
the expected constraints and suggestions.

This matrix demonstrates the workflow across diverse ratings; it is not a
global proof that every possible input is feasible. The public guarantee remains
per-design: no model is published without its own evidence.

## Documentation And Claims

Documentation distinguishes:

1. `designed`: analytic candidates exist;
2. `planned`: an immutable PSCAD build plan is confirmed;
3. `built`: topology and parameters match the plan;
4. `simulated`: all required operating phases completed; and
5. `accepted`: all required dynamic and physical evidence passed.

Only `accepted` models may be described as autonomously constructed. Stage A
documentation states the fixed CIGRE-derived profile and AVM limitations. Stage
C documentation states that arbitrary inputs may be rejected and that each
published design is validated individually.

The repository must never imply individual submodule, detailed switching,
thermal, DC-fault-blocking, grid-forming, or multi-terminal capability from
this work.

## Delivery Sequence

Implementation is divided into two written plans. The Stage A plan ends with a
working fixed model and licensed acceptance. The Stage C plan begins from that
accepted commit and ends with arbitrary-input feasibility design and its
licensed matrix. This keeps Stage A independently releasable and prevents Stage
C sizing work from delaying the fixed benchmark.

1. Accept the LCC builder and extract common infrastructure with unchanged LCC
   behavior.
2. Implement and unit-test MMC arm, station, control, topology, and acceptance
   contracts.
3. Author and audit the original MMC AVM companion library.
4. Create the fixed CIGRE-derived blueprint, sequence, profile, golden data, and
   four Stage A tools.
5. Pass Stage A licensed PSCAD acceptance and document fixed-model capability.
6. Add analytic sizing, candidate records, nearest-feasible suggestions, and
   `design_mmc_model`.
7. Add planned multi-candidate background evaluation.
8. Pass the Stage C feasible/infeasible licensed matrix and document the
   arbitrary-input feasibility contract.

Stage C cannot begin publication work until Stage A is accepted. It may begin
pure sizing unit tests earlier, but no arbitrary-input capability claim is made.

## Completion Criteria

Stage A is complete only when:

- the companion library is original, auditable, hash-verified, and packaged;
- the generated main canvas exposes two stations and twelve correct arms;
- planning is deterministic and side-effect free;
- confirmed construction verifies every mutation and saved graph;
- controlled startup, forward transfer, reversal, and reverse transfer finish;
- all golden and physical checks pass in licensed PSCAD 4.6.2;
- failed builds never leave a final project; and
- all LCC and existing repository behavior remains unchanged.

Stage C is complete only when:

- arbitrary unit-bearing input produces a deterministic design or explicit
  infeasibility report;
- every candidate and tuning choice is covered by design and plan hashes;
- no unplanned adaptive candidate is executed;
- only a dynamically accepted candidate is published;
- exhausted candidates leave no final project;
- nearest feasible suggestions are reproducible and require a new hash;
- the licensed feasible/infeasible matrix passes; and
- documentation accurately limits the guarantee to each accepted design.
