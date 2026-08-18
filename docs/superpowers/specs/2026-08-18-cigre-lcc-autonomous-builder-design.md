# CIGRE LCC Autonomous Model Builder Design

## Context

The PSCAD MCP server can create case projects, instantiate existing component
definitions, set parameters, connect ports, create wires, build projects, run
simulations, and read outputs. The HVDC domain layer can inspect and classify
LCC projects and can analyze mapped results. These capabilities are necessary
but not sufficient to construct an electrically valid LCC system from an empty
case. There is no domain blueprint, component catalog, topology verifier,
transactional builder, or model-level acceptance gate.

The first autonomous construction milestone is a public, redistributable
PSCAD 4.6.2 implementation of the classic CIGRE single-pole, two-terminal,
12-pulse LCC benchmark. It uses fixed benchmark electrical parameters and an
original companion library. The generated case starts from an empty `.pscx`;
it is not a renamed or modified complete-case template. The first release
accepts only steady-state construction and validation. The schema preserves a
pole-count field for a later bipolar profile, but version 1 rejects any pole
count other than one.

## Goals

1. Plan a deterministic CIGRE LCC build without mutating PSCAD or the file
   system.
2. Create the case from an empty project after explicit confirmation and an
   exact plan-hash match.
3. Use an original, redistributable companion library only for hierarchy that
   the current automation API cannot author safely.
4. Keep the power circuit visible and auditable on the generated main canvas.
5. Verify every mutation through read-back and compare the saved PSCAD graph
   with the declared blueprint.
6. Compile and run the generated model in licensed PSCAD 4.6.2.
7. Require both golden-baseline agreement and independent physical checks
   before publishing the final project.
8. Preserve the existing 60 generic and 10 HVDC tool contracts unchanged.

## Non-Goals

- Designing an LCC system from user-provided ratings.
- Supporting PSCAD 5.x in the first release.
- Generating a bipolar system in the first release.
- Fault, commutation-failure, recovery, or order-step acceptance.
- Regenerating the companion library definitions during each model build.
- Copying definitions, parameters, or schematics from local customer or vendor
  projects.
- Treating successful compilation or simulation completion as proof of an
  electrically valid model.
- Implementing MMC construction in this change.

## Architectural Decision

Add `pscad_mcp.hvdc.builders.lcc` as a focused package over the existing
`PscadService` boundary. Do not embed construction behavior in the existing
scanner, generic canvas tools, or scenario executor.

```text
MCP tools
  -> LccBuilderService
     -> blueprint/catalog/asset validation
     -> deterministic planner
     -> staged executor through PscadService
     -> saved-project graph validation
     -> build/run/output capture
     -> golden and physical acceptance
```

The package contains these modules:

- `schema.py`: strict JSON-safe blueprint, plan, operation, and acceptance
  contracts.
- `assets.py`: package-resource loading, manifest validation, SHA-256 checks,
  and workspace materialization.
- `catalog.py`: exact PSCAD 4.6.2 definition, port, parameter, and value-type
  metadata.
- `planner.py`: deterministic expansion of the fixed blueprint into immutable
  operations and a canonical plan hash.
- `routing.py`: port-coordinate resolution, orientation transforms, keep-out
  checks, and deterministic orthogonal wire routes.
- `project_graph.py`: read-only `.pscx` parsing into normalized components,
  parameters, wires, labels, and electrical/data nets.
- `executor.py`: staged mutation, read-back, journaling, compilation, run
  control, and final publication.
- `validator.py`: blueprint-to-project structural comparison.
- `acceptance.py`: output normalization, golden comparison, and physical
  invariants.
- `service.py`: one-build lease, asynchronous task records, public operations,
  and structured errors.

The generic `PscadService` remains the only application-facing mutation
boundary. Raw Legacy backend calls are allowed only where the existing service
already exposes no equivalent read-only capability, and any such exception
must be added to the backend protocol before use.

## Companion Library Boundary

The companion library is original project content distributed under the
repository license. It may reference PSCAD Master Library definitions by
scoped name, but it must not embed or copy vendor definition bodies. It
contains only hierarchy that the automation API cannot safely create:

- a reusable 12-pulse LCC valve-group definition composed of two six-pulse
  groups with the required phase relationship;
- a rectifier control definition;
- an inverter control definition;
- small signal-interface and initialization helpers required by those three
  definitions.

It must not contain an entire two-terminal HVDC system as one component.
Equivalent AC sources, converter transformers, AC filters, smoothing reactors,
the DC line, grounding, meters, labels, and output channels are instantiated
and connected by the builder on the case canvas.

Before release, an asset audit must prove that every non-Master definition in
the library is authored for this repository. `PROVENANCE.md` maps every fixed
benchmark parameter to a public CIGRE source location and records the PSCAD
version used to author and validate the library. Local files under
`C:\PSCADFiles` may inform API characterization and test setup only; no content
from them may enter a packaged asset.

## Packaged Assets

The package adds this versioned asset set:

```text
pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/
  manifest.json
  blueprint.json
  catalog-pscad-4.6.2.json
  acceptance.json
  golden.json
  PROVENANCE.md
  library/cigre_lcc_v1.pslx
```

`manifest.json` contains the asset-set name, schema version, target PSCAD
version, companion-library identity, and SHA-256 of every other asset. It is
the trust root embedded in the Python package. The builder fails closed when a
file is absent, additional unmanifested executable content is present, or a
hash differs.

`blueprint.json` contains no expression language or code. Its allowed records
are:

- project settings;
- canvases;
- component instances with stable logical IDs, exact scoped definitions,
  integer locations, orientation, and explicit parameters;
- nets with a declared electrical/data kind, named endpoints, and either an
  explicit route or a deterministic routing policy;
- output channels with exact paths, call IDs where PSCAD exposes them, units,
  and semantic roles;
- structural assertions; and
- the fixed `topology`, `poles`, `terminals`, and benchmark profile identity.

The v1 blueprint declares `topology="lcc"`, `poles=1`, and `terminals=2`.
Schema validation accepts a positive pole count so the data model does not
need replacement later, but the v1 planner returns
`LCC_BLUEPRINT_UNSUPPORTED` unless `poles == 1`.

`catalog-pscad-4.6.2.json` contains exact definition, port, parameter, enum,
range, and type metadata for every used Master and companion-library
component. Substring matching and guessed port or parameter names are
forbidden in construction.

`golden.json` contains bounded, down-sampled, unit-bearing waveforms and
derived scalar references from a separately reviewed PSCAD 4.6.2 run. It also
records the source blueprint hash, library hash, compiler identity, EMTDC time
step, output step, alignment channel, comparison window, and generation time.
Tests and normal builds never regenerate golden data automatically.

## Public MCP Tools

Four tools are added, increasing the tool inventory from 70 to 74.

### `plan_lcc_model`

Inputs:

- `project_name: str`
- `folder: str | None = None`
- `simulation_duration_s: float | None = None`
- `blueprint: str = "cigre_lcc_monopole_v1"`

The tool is read-only. `folder` is resolved through `PSCAD_MCP_WORKSPACE`.
`simulation_duration_s` is non-electrical and may only extend the packaged
default; shortening it below the packaged acceptance window is rejected. The
only accepted blueprint in v1 is `cigre_lcc_monopole_v1`.

The result contains resolved target and staging locations, backend and PSCAD
requirements, asset hashes, library dependencies, operation counts, component
and net summaries, required outputs, acceptance gates, warnings, and
`plan_hash`. It performs no directory creation, project loading, component
mutation, or file writes.

The canonical hash covers all normalized inputs, target paths, blueprint and
asset hashes, target PSCAD version, catalog identity, project settings,
expanded operations, and acceptance contract. Timestamps and display-only
diagnostics are excluded.

### `build_lcc_model`

Inputs are the same planning inputs plus:

- `expected_plan_hash: str`
- `confirm: bool = False`

The call fails before mutation unless confirmation is true. It recomputes the
entire plan and requires a constant-time exact hash match. It also repeats
backend, destination, asset, catalog, definition, and port checks immediately
before starting the asynchronous task. On success it returns `build_id`, the
accepted plan hash, and initial status.

### `get_lcc_build_status`

Input:

- `build_id: str`

The result contains state, timestamps, current stage, completed and pending
operation counts, the last verified postcondition, warnings, structured
failure details, staging evidence, final path when published, compilation and
simulation summaries, and the full acceptance verdict. Polling does not alter
the build.

### `validate_lcc_model`

Inputs:

- `project_name: str`
- `blueprint: str = "cigre_lcc_monopole_v1"`
- `output_file: str | None = None`

The tool never builds, runs, saves, or repairs a project. It parses the saved
case and compares structure and parameters with the blueprint. If an existing
output file is supplied, it also evaluates golden and physical acceptance.
Without an output file it reports output acceptance as `not_evaluated`, never
as passed.

## Planning Rules

Planning is deterministic for identical normalized inputs and assets.
Components use fixed blueprint coordinates because the destination canvas is
empty. The planner still evaluates component bounding boxes and net keep-out
regions so an invalid packaged layout cannot reach PSCAD.

Every endpoint is `logical_component_id:port_name`. The catalog and component
orientation determine its absolute grid point. Aligned endpoints may use a
two-point port connection. Other electrical wires use explicit orthogonal
vertices from the blueprint. Data and electrical labels use separate declared
connection kinds. The planner rejects diagonal segments, zero-length
segments, duplicate logical IDs, duplicate required signal labels, overlapping
components, route/component collisions, nets with fewer than two endpoints,
and incompatible port kinds.

The plan operation order is stable:

1. materialize the verified companion library in the workspace;
2. create and load the empty staging case and load the companion library;
3. apply project settings;
4. place power components, control components, and measurements;
5. apply and verify parameters;
6. create electrical nets, data nets, annotations, and output channels;
7. save staging state and validate the normalized project graph;
8. compile, simulate, and evaluate acceptance; and
9. publish and verify the final case.

## Build State And Journaling

One active LCC build is allowed per configured workspace, including across
multiple MCP server processes. The service acquires an atomic workspace lock
whose metadata contains the build ID, owner process, creation time, and
journal path. A live owner causes `LCC_BUILD_CONFLICT`. A stale owner is first
recorded as `interrupted` in its journal before a new build may acquire the
lock. The asynchronous state machine is:

```text
validated
  -> staging_created
  -> components_placed
  -> parameters_verified
  -> connections_verified
  -> structure_verified
  -> staging_saved
  -> compiled
  -> simulated
  -> acceptance_passed
  -> published
```

Every nonterminal state can transition to `failed`, `timed_out`, or
`interrupted`. Terminal transitions cannot be reversed.

The builder writes an atomic JSON journal under
`.pscad-mcp/lcc-builds/<build_id>/journal.json`. A write uses a sibling
temporary file followed by an atomic replace. The journal records the plan and
asset hashes, target identities, stage history, attempted and completed
operations, returned component and wire IDs, read-back evidence, diagnostics,
and output hashes. It never records credentials.

After a server restart, a nonterminal persisted build is reported as
`interrupted`. Version 1 does not resume it because the external PSCAD state
cannot be proven identical. The user may inspect its evidence and start a new
plan. A new build always receives a new staging path and build ID.

## Mutation And Postconditions

All construction occurs in a builder-owned staging directory inside the
configured workspace. The final destination must not exist. `confirm=true`
authorizes creation of the planned new files; it never authorizes overwrite of
an existing destination.

The companion library is materialized once at
`.pscad-mcp/libraries/cigre_lcc_v1.pslx`. An existing matching file is reused.
An existing mismatched file causes `LCC_ASSET_MISMATCH`; it is not replaced.

Each mutation has an immediate postcondition:

- component creation verifies returned ID, definition, position, orientation,
  and supplied parameters;
- parameter mutation reads the exact parameter names back;
- connection creation records returned identity and endpoint coordinates;
- settings mutation reads settings back;
- save verifies a file exists at the expected staging path and that its XML
  project identity is the staging identity; and
- graph validation independently parses the saved file rather than trusting
  accumulated API responses.

If a postcondition fails, no later operation runs. The partial staging project,
journal, and diagnostics remain available. No source or pre-existing project
is mutated.

The final file is published only after staging acceptance passes. Publication
uses the service save-as boundary so PSCAD registers the requested final
logical identity. The builder then reopens or resolves the candidate final
file, repeats structural validation, and performs a final compile smoke check.
The task becomes `published` only after those checks pass. If a publication
check fails, the builder closes the candidate and moves every builder-created
candidate artifact back under the build evidence directory, leaving the
planned final path absent. A pre-existing final path is never moved or
modified. Builder-owned temporary files may be removed after their final
hashes and journal evidence are persisted; failed staging artifacts are
retained.

## Structural Validation

`project_graph.py` parses PSCAD XML with a structured parser. It normalizes
definition scopes, component IDs, names, parameters, locations, orientation,
wire vertices, node labels, and canvas ownership. Port coordinates and kinds
come from the hashed catalog and are transformed by component orientation.
Wires and matching labels are reduced into electrical and data-net connected
components.

The validator requires exact agreement for all blueprint-owned objects and
nets. PSCAD-generated metadata and identifiers may differ and are excluded
through an explicit allow-list. Unexpected electrical connections, duplicate
signals, missing required components, missing endpoints, parameter differences,
unconnected required ports, and electrical/data type mixing fail validation.

The companion library has a separate library-structure validator. Its hashed
definitions must prove that the 12-pulse bridge contains the declared two
six-pulse groups and expected external port contract. The case-level validator
does not infer internal correctness from a component display name.

## Simulation And Output Contract

The build uses fixed packaged project settings for EMTDC time step, output
step, compiler target, simulation duration, and output enablement. Only an
allowed duration extension may override a setting. Runtime events and
wall-clock event timing are not part of v1.

The LCC profile is a version 2 profile with exact result selectors. Required
channels include, at minimum:

- rectifier and inverter DC voltage;
- DC line current;
- rectifier and inverter active and reactive power;
- rectifier firing angle;
- inverter extinction angle;
- commutation overlap evidence where the companion model exposes it; and
- the AC alignment channel used by golden comparison.

Each selector declares a path, call ID when available, units, terminal role,
and measurement direction. Before simulation, the backend must verify every
required output definition. Missing, ambiguous, or unit-mismatched selectors
fail before the run. Sample domains must be finite, non-empty, strictly
increasing, and mutually aligned.

## Golden Baseline Acceptance

The acceptance manifest defines a fixed warm-up exclusion, comparison window,
alignment rule, per-channel scale floor, normalized root-mean-square error
limit, maximum absolute-error limit, and scalar metric tolerances.

Actual samples are aligned to the golden window using the declared positive
going zero crossing of the AC alignment channel. The allowed shift is bounded
to one fundamental cycle. Actual values are linearly interpolated to the
golden time grid; extrapolation is forbidden.

For golden samples `g_i` and aligned actual samples `x_i`, the normalized RMS
error is:

```text
NRMSE = sqrt(mean((x_i - g_i)^2)) / max(percentile95(abs(g_i)), scale_floor)
```

The normalized maximum error uses the same denominator. A channel passes only
when both configured limits pass. Tolerances live in the reviewed acceptance
asset, not in Python code. Missing samples, failed alignment, non-finite data,
or unknown units produce `INCOMPLETE_ANALYSIS` and prevent publication.

Golden updates require a separate maintainer command with explicit
confirmation. It records a new blueprint/library/compiler fingerprint and is
never called by tests, package installation, planning, or normal construction.

## Independent Physical Acceptance

Golden agreement is necessary but cannot be the only oracle. The same steady
state window must also satisfy independently configured checks:

- rectifier and inverter DC voltage magnitude and polarity;
- DC current magnitude and direction;
- transferred DC power against the fixed benchmark rating;
- consistency of measured DC power with `Vdc * Idc` after unit conversion;
- rectifier-to-inverter power balance within the declared loss allowance;
- rectifier firing angle within its operating interval;
- inverter extinction angle above its minimum margin and within its operating
  interval;
- commutation overlap within its declared interval when required by the
  profile;
- bounded DC voltage and current ripple; and
- bounded steady-state control error.

Every threshold and unit is in `acceptance.json` with source or engineering
rationale. A check is `observed`, `derived`, `missing`, or `invalid`. The final
verdict is `PASS` only when all required golden and physical checks pass.
Compilation success, run completion, and partial metric success cannot promote
the verdict.

## Error Contract

Builder errors use the existing stable `BackendError` shape with backend
`hvdc` and the relevant LCC operation. Primary codes are:

- `LCC_BLUEPRINT_NOT_FOUND`
- `LCC_BLUEPRINT_INVALID`
- `LCC_BLUEPRINT_UNSUPPORTED`
- `LCC_ASSET_MISMATCH`
- `LCC_VERSION_UNSUPPORTED`
- `LCC_DEFINITION_MISSING`
- `LCC_PORT_MISMATCH`
- `LCC_PARAMETER_MISMATCH`
- `LCC_LAYOUT_INVALID`
- `LCC_PLAN_STALE`
- `LCC_BUILD_CONFLICT`
- `LCC_POSTCONDITION_FAILED`
- `LCC_BUILD_FAILED`
- `LCC_BUILD_TIMED_OUT`
- `LCC_STRUCTURE_INVALID`
- `LCC_OUTPUT_INCOMPLETE`
- `LCC_ACCEPTANCE_FAILED`

Errors include the plan/build ID, stage, logical object or net, requested and
observed values, retained evidence path, retryability, and a concrete suggested
action. Vendor exception text is preserved as diagnostic detail but is not the
stable public message.

## Testing Strategy

### Unit And Property Tests

- Validate every schema record and reject unknown fields.
- Prove canonical plan serialization and hash stability.
- Reject invalid versions, paths, component overlaps, routing collisions,
  duplicate IDs, incompatible ports, and unsupported pole counts.
- Verify orientation-aware port transforms and net normalization.
- Exercise golden alignment, interpolation, error formulas, unit conversions,
  missing data, and every physical invariant.
- Parse representative empty, partial, valid, and corrupt PSCX fixtures.

### Service And Backend Contract Tests

- Prove planning performs zero writes and zero PSCAD mutations.
- Prove missing confirmation and stale hashes fail before staging creation.
- Record exact `PscadService` calls and enforce mutation order.
- Inject a failure after every stage and verify no later call occurs, the final
  destination does not exist, and staging evidence remains.
- Verify every created component, parameter, setting, and connection is read
  back before the next stage.
- Verify cross-process workspace leasing, stale-lock handling, terminal state
  transitions, timeout handling, and restart-to-interrupted recovery.
- Preserve all existing generic and HVDC contract tests.

### Packaging And Provenance Tests

- Build a wheel and verify all declared LCC assets are included.
- Recompute every manifest hash from the installed wheel.
- Reject unexpected non-Master embedded definition provenance.
- Verify public source references and license declarations are present.
- Keep the portable install smoke test passing without PSCAD installed.

### Licensed PSCAD 4.6.2 Acceptance

The real test is opt-in through `PSCAD_MCP_LCC_ACCEPTANCE=1` and an isolated
absolute `PSCAD_MCP_WORKSPACE`. It must:

1. create a timestamped workspace and record initial hashes;
2. connect through the production `PscadService` and Legacy backend boundary;
3. plan and verify a stable plan hash;
4. build the case through the public builder service;
5. wait for compilation, simulation, and acceptance;
6. independently call `validate_lcc_model` on the final case and output;
7. verify the final logical project identity and compile smoke check;
8. persist a JSON acceptance report and relevant PSCAD diagnostics;
9. verify packaged assets and all pre-existing files remain unchanged; and
10. clean up only the PSCAD process and temporary artifacts owned by the test.

The project must not claim autonomous LCC construction until this exact test
passes in licensed PSCAD 4.6.2. A skipped test, mocked backend, safe rejection,
or compile-only result is not acceptance evidence.

## Observability And Audit

Status and acceptance records are JSON serializable and bounded. Large raw
waveforms remain in normal PSCAD output files; status reports contain channel
identities, hashes, windows, scalar summaries, errors, and evidence paths.
Component and net references retain blueprint logical IDs and PSCAD IDs so a
user can locate a failure on the canvas.

The final report records package version, git/build version when available,
PSCAD version, compiler, backend, blueprint and asset hashes, plan hash,
project hash, output hash, all acceptance results, and unresolved warnings.

## Bipolar And Future Builder Expansion

The later bipolar release will be a separate
`cigre_lcc_bipole_v1` blueprint and golden baseline. It will add two poles,
neutral/ground-electrode topology, pole-specific outputs, pole imbalance
checks, and startup coordination. It may reuse the planner, executor, graph,
and acceptance infrastructure, but it cannot make the monopole profile accept
`poles=2`.

An MMC builder may later share generic plan, journal, graph, and asset
facilities. LCC-specific topology and physical rules remain in the LCC package;
the first implementation must not introduce an unvalidated universal HVDC
builder abstraction.

## Documentation And Release Claims

README documentation will distinguish four capability levels:

1. plan generated;
2. project structurally built;
3. project compiled and simulated; and
4. project accepted against golden and physical criteria.

Only level 4 may be described as an autonomously constructed CIGRE LCC model.
Documentation must state the PSCAD 4.6.2 requirement, fixed electrical
parameters, original companion-library dependency, single-pole limitation,
workspace writes, confirmation requirement, and licensed acceptance status.

## Completion Criteria

The design is complete when all of the following are true:

- the four tool contracts are registered without changing existing names;
- planning is deterministic and side-effect free;
- all assets are original, hash-verified, packaged, and source documented;
- an empty case is populated and connected only through the production service
  boundary;
- all mutations and the final project graph are independently verified;
- no existing destination is overwritten;
- failed builds retain actionable evidence without publishing a final case;
- the real generated project compiles and completes simulation in licensed
  PSCAD 4.6.2;
- all required golden and physical acceptance checks pass;
- the independent validator reproduces the acceptance verdict; and
- the full default test suite, packaging verification, Python compilation, and
  `git diff --check` pass.
