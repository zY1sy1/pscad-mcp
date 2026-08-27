# PSCAD Blueprint Builder Design

**Date:** 2026-08-27

**Status:** Approved for implementation planning

## 1. Purpose

Add a general, profile-driven PSCAD Blueprint Builder to PSCAD MCP. The builder creates an isolated staging package from a read-only source package, applies deterministic parameter and graph mutations, saves and reloads the project, compiles and simulates it, evaluates configured outputs, and publishes only evidence-backed deliverables.

The first release supports constrained engineering automation from an audited blueprint. It does not infer arbitrary electrical designs from natural language, invent missing equipment ratings, or equate a runnable model with physical equipment acceptance.

## 2. Scope

The builder must support the following end-to-end workflow:

1. Audit a source PSCX project and its companion libraries.
2. Validate a versioned blueprint against live PSCAD definitions, ports, parameter metadata, and a workspace path policy.
3. Resolve logical component references to unique selectors.
4. Produce an immutable plan with source, blueprint, catalog, and dependency hashes.
5. Require explicit confirmation of that exact plan before mutation.
6. Copy the complete source package into a build-ID staging directory.
7. Apply deterministic component, parameter, routing, connection, and project-setting operations.
8. Read back every operation and independently validate the saved and reloaded project.
9. Compile, simulate, inspect project messages, discover OUT/INF data, and evaluate acceptance rules.
10. Generate a journal, manifest, validation report, and optional delivery package.

The first release supports these mutation operations:

- `clone_component`
- `create_component`
- `set_component_location`
- `rotate_component`
- `set_component_parameters`
- `create_wire`
- `connect_ports`
- `set_project_settings`
- output-channel declaration and verification

The first release does not support deleting source components, overwriting the source package, silently changing unresolved parameters, automatically inventing engineering values, or publishing outside the configured workspace.

## 3. Architecture

Create a domain-neutral package at `pscad_mcp/builders/blueprint/`. It uses `PscadService` for application operations and `PathPolicy` for filesystem containment. It follows the proven LCC builder patterns for immutable plans, asset hashes, journals, build leases, asynchronous status, validation, quarantine, and fail-closed publication without refactoring the existing LCC builder in the first release.

The package contains focused units:

- `models.py`: immutable JSON-safe blueprint, plan, operation, acceptance, and build records.
- `schema.py`: strict parsing and validation for versioned blueprint input.
- `inventory.py`: live definition, port, parameter, and unit resolution.
- `planner.py`: deterministic operation ordering, selector resolution, and plan hashing.
- `executor.py`: staging creation, mutation execution, immediate read-back, lifecycle operations, and journaling.
- `validator.py`: independent graph, parameter, message, output, and source-integrity checks.
- `acceptance.py`: generic finite-value, bounds, exact-state, transition, window, and monotonic rules.
- `output.py`: structured INF metadata and segmented OUT parsing.
- `journal.py`: atomic JSONL journal and manifest projection.
- `service.py`: orchestration, build leases, asynchronous tasks, quarantine, and publication gates.
- `assets.py`: versioned blueprint/profile asset loading and hashing.

Tool wrappers live in `pscad_mcp/tools/blueprint_tools.py` and contain no builder business logic.

## 4. MCP Tools

### `plan_pscad_project_build`

Inputs include a blueprint name or JSON object, source package path, requested target name, and optional non-mutating parameter overrides. The tool validates paths, source hashes, companion files, live inventory, selectors, ports, units, operations, outputs, and acceptance rules.

It returns a JSON-safe plan containing:

- `plan_hash`
- normalized blueprint identity
- source and dependency hashes
- resolved selectors and port contracts
- ordered operations
- acceptance requirements
- warnings, including unresolved but untouched elements
- proposed staging path

Planning never writes the source or staging project.

### `build_pscad_project`

Inputs include the exact `plan_hash` and explicit confirmation. The service reloads all plan assets and rejects execution if any hash or live contract changed. It creates a build-ID staging directory and starts the asynchronous build.

The immediate return contains `build_id`, initial state, and status lookup information.

### `get_pscad_project_build_status`

Returns the current state, completed history, pending operation, structured error, evidence paths, acceptance flags, and publication status. It must remain JSON-safe while a vendor operation is pending or settling.

### `validate_pscad_project_build`

Independently validates a completed build record or workspace-contained staging package. Validation never trusts executor success flags. It re-reads the graph and parameters, checks source integrity and project messages, parses output metadata and values, evaluates required rules, and emits a validation report.

## 5. Blueprint Schema

A blueprint is a strict JSON object with five top-level sections:

```json
{
  "identity": {},
  "source_package": {},
  "operations": [],
  "acceptance": {},
  "publication": {}
}
```

### Identity

`identity` contains `schema_version`, `name`, supported PSCAD versions, and an optional inspection profile. Unknown schema versions are rejected.

### Source Package

`source_package` declares the PSCX entry point, required companion files or directories, expected hashes where supplied, and the source package handling policy. All paths must pass `PathPolicy`, resolve to regular files or directories as required, and remain read-only inputs.

### Operations

Operations use stable `logical_id` values. A later operation references a logical ID rather than a runtime PSCAD component ID. Each operation has a sequence, kind, target, arguments, and an operation ID used by the journal.

Component creation and cloning declare the expected definition, canvas, location, orientation, port contracts, parameters, and units. Wire and connection operations declare endpoint logical IDs and ports plus an explicit or policy-derived orthogonal route. Parameters marked unresolved may be observed but cannot be mutated.

### Acceptance

Acceptance declares required structure, parameters, messages, output channels, and evaluation rules. Supported generic rule kinds are:

- exact value or exact set
- minimum and maximum
- inclusive range
- all values finite
- allowed discrete states
- transition count and transition time
- summary within a relative time window
- monotonic sequence across declared operating points

Every engineering threshold includes a `source_class`. Model-observed or provisional thresholds can support model run-through acceptance but cannot support physical acceptance.

### Publication

Publication declares whether a delivery package is requested, which evidence files are included, and the permitted publication scope. All outputs remain within the workspace. A source directory is never a valid publication target.

## 6. Data Flow

The planning flow is:

```text
blueprint -> strict schema -> source audit -> live inventory
-> selector and port resolution -> deterministic operations
-> acceptance validation -> canonical serialization -> plan_hash
```

The build flow is:

```text
confirmed plan_hash -> revalidate hashes and contracts
-> reserve workspace lease -> create build-ID staging
-> copy complete package -> apply operation/read-back pairs
-> save -> quit/reload -> independent graph and parameter validation
-> compile -> message check -> simulate -> terminal-state check
-> output discovery and parsing -> acceptance evaluation
-> report and manifest -> publication gate
```

The validator flow is independent of the executor:

```text
build record or staging -> source hash check -> graph inspection
-> parameter inspection -> message inspection -> OUT/INF inspection
-> acceptance rules -> explicit acceptance flags and evidence
```

## 7. State Machine

Successful states are ordered:

```text
planned
staging_created
mutations_applied
structure_verified
saved
reloaded
parameters_verified
compiled
simulated
acceptance_passed
published
```

Terminal exception states are:

```text
rejected
failed
timed_out
interrupted
quarantined
```

Invalid transitions are rejected. A failed, timed-out, or interrupted build cannot later become accepted or published. Vendor operations that outlive a timeout retain the application-wide lease until they settle and the staging package is quarantined for review.

## 8. Failure Handling

The builder fails closed under these conditions:

- source, blueprint, dependency, or catalog hashes changed after planning;
- a definition, selector, component, parameter, port, unit, or output channel is missing or ambiguous;
- an operation read-back does not match its plan;
- the saved and reloaded graph differs from the planned graph;
- source files changed at any lifecycle checkpoint;
- compilation contains a configured blocking message;
- simulation does not reach its required terminal state;
- output segments, metadata, rows, units, or finite-value requirements are incomplete;
- any required acceptance rule fails;
- a publication path escapes the workspace;
- physical acceptance relies on a provisional or model-observed threshold.

The source package is never rolled back because it is never written. Builder-owned staging files are retained in quarantine with their journal and failure report. Publication copies only explicitly listed evidence from an accepted staging package.

## 9. Acceptance Boundaries

Reports expose independent flags:

```json
{
  "structure_acceptance": true,
  "run_through_acceptance": true,
  "physical_acceptance": false,
  "published": true,
  "publication_scope": "model_run_through_only"
}
```

Unresolved elements that are present in the source package and untouched by the plan are non-blocking warnings. An operation targeting an unresolved element is rejected.

`run_through_acceptance` requires verified structure, persistence, compilation, simulation, messages, outputs, and all required model rules. `physical_acceptance` additionally requires every physical threshold to carry an accepted engineering source classification. Publication does not imply physical acceptance; its scope is explicit in every report and manifest.

## 10. Journaling and Evidence

The service writes an append-only journal with timestamps, build ID, plan hash, state transitions, operation IDs, normalized requested and observed values, hashes, and structured errors. It does not store credentials or unrelated project content.

The final evidence set includes:

- canonical plan and plan hash
- source and dependency hash manifest
- operation journal
- graph and parameter validation report
- compile and run message summaries
- output metadata and acceptance summary
- final manifest
- publication manifest when requested

Reports use relative evidence paths where possible and contain no machine-specific source path when a package-relative path is sufficient.

## 11. Testing Strategy

### Pure Logic Tests

Test strict schema parsing, canonical plan hashes, immutable records, logical reference resolution, state transitions, acceptance source classes, finite values, bounds, exact states, transition timing, relative windows, monotonic operating points, and JSON-safe serialization.

### Offline Fixture Tests

Use small, repository-owned PSCX/PSLX fixtures to test package discovery, source hashing, component cloning and creation, parameter updates, placement, rotation, wire representation, saved graph validation, and source immutability without requiring a PSCAD license.

### Service and Backend Contract Tests

Use controlled fake services to test exact operation ordering, immediate read-back, fail-fast behavior, workspace leases, timeout settlement, quarantine, blocking messages, publication gates, and independent validation. Fake results never set `live_verified=true`.

### Licensed Acceptance Tests

Add opt-in tests guarded by explicit environment variables. They require a licensed PSCAD runtime and user-provided source package and workspace paths. They verify real save, quit/reload, compile, simulation, messages, outputs, and report generation. A skipped licensed test is not real PSCAD evidence.

Reusable rule parsing and semantic checks from the validated breaker workspace are reimplemented through test-first repository tests. Local absolute paths, random component IDs, copied simulation outputs, and provisional project-specific thresholds are not embedded in the generic core.

## 12. Registration and Documentation

Register the four tools through the shared `register_tool` wrapper. Update tool inventory, English and Chinese capability documentation, and the breaker work document status. Document the distinction among implemented, default-test verified, licensed/live verified, run-through accepted, physically accepted, and published.

## 13. Completion Criteria

The MCP update is complete only when:

1. all four tools are registered and return JSON-safe structured results;
2. blueprint planning is deterministic and side-effect free;
3. source packages remain unchanged across success and failure tests;
4. supported graph and parameter operations are independently read back;
5. save/reload, compile, simulation, message, output, and acceptance stages are represented in the state machine;
6. unresolved untouched elements are warnings and unresolved mutation targets are rejected;
7. provisional thresholds cannot produce physical acceptance;
8. failed builds are quarantined and cannot be published;
9. focused and full default test suites pass;
10. licensed acceptance remains opt-in and is reported separately from default tests.
