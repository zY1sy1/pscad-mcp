# Blank LCC and MMC Builder Design

**Date:** 2026-08-28

**Status:** Approved design, pending implementation plan review

## Goal

Build fixed reference LCC and MMC systems from a blank PSCAD 4.6.2 project, using
the installed Master Library where possible and a repository-owned companion
library for missing converter-specific definitions. The first milestone must
compile, run a short steady-state simulation, validate an LCC commutation
failure, and validate intrinsic DC-fault blocking for a full-bridge MMC. The
design must leave a stable extension point for later rating parameterization and
half-bridge MMC support.

## Scope and Decisions

- The first licensed end-to-end target is PSCAD 4.6.2 only.
- LCC and MMC are separate builders over shared blank-project assembly services.
- The first LCC is a fixed CIGRE-style single-pole 12-pulse reference system.
- The first MMC is a fixed two-terminal symmetrical-monopole full-bridge MMC.
- The first release uses canonical benchmark ratings stored in blueprints and
  records, while request schemas reserve fields for future parameterized input.
- The output is both a reusable companion library and a top-level PSCX project
  that references it.
- Fault acceptance is in scope: controlled inverter-side AC disturbance and
  commutation-failure recovery for LCC; DC-fault blocking and recovery for MMC.
- Half-bridge is a later selectable submodule topology. It shares the MMC
  assembly contract but explicitly does not claim intrinsic DC-fault blocking.

## Architecture

### Blank Project Factory

Creates a new PSCX project, configures simulation settings, creates the required
canvas, and establishes the project-to-library references. It never mutates an
existing destination.

### Component Library Resolver

Resolves every requested definition against the installed PSCAD Master Library
first. Missing converter-specific definitions are resolved from the audited
companion library. Resolution records the source, definition identity, ports,
parameter contract, and source hash in the immutable build plan.

### Topology Assembler

Instantiates components, places them on the canvas, creates typed ports and nets,
and verifies connectivity. LCC and MMC topology recipes are separate and share
only the component-placement and connection primitives.

### Control Assembler

Creates control components and exact bindings for the selected reference model.
Control bindings are explicit, readable, and included in the plan and acceptance
report. No control is inferred from a component name during a mutating build.

### Scenario and Acceptance Runner

Creates named scenario-source copies, schedules EMTDC-time events, runs PSCAD,
reads `.out`/`.psout` results, and evaluates model-specific acceptance checks.
Structural, compiled, simulated, and accepted states remain distinct.

## LCC Reference Model

The blank LCC project contains:

- sending and receiving AC systems;
- converter transformers;
- two six-pulse thyristor bridges forming a twelve-pulse valve group;
- smoothing reactor;
- DC line;
- AC filters and reactive compensation;
- rectifier and inverter firing-angle, DC-current, and DC-voltage controls;
- explicit DC voltage, DC current, power, firing-angle, and extinction-angle
  measurements;
- a controlled inverter-side AC voltage or phase disturbance;
- commutation-failure detection and recovery logic.

The first blueprint uses fixed CIGRE reference ratings. The assembler reads them
from the blueprint rather than embedding values in component code. Fixed-builder
scope intentionally excludes arbitrary user ratings, fixed-builder bipole output,
PSCAD 5.x acceptance, and automatic fault-component insertion into unrelated
existing projects.

The LCC fault acceptance must demonstrate the disturbance, an extinction-angle
or commutation-failure indication, bounded DC response, and controlled recovery.
All required channels, units, event times, and verdicts are recorded.

## MMC Reference Model

The blank MMC project contains:

- two AC systems and converter transformers;
- six MMC arms with arm inductors;
- serial full-bridge submodules with capacitor states;
- submodule capacitor-voltage, arm-current, circulating-current, DC-voltage,
  DC-current, power, and gate-state measurements;
- active/reactive power and AC-voltage control;
- circulating-current suppression;
- capacitor-voltage balancing and sorting;
- a DC line and an explicit DC-fault event source.

The full-bridge submodule contract exposes common DC and AC terminals, capacitor
state, switch state, gate vector, output voltage, and fault capability. A DC fault
must cause negative-voltage insertion, bounded fault current, a verified blocking
state, and a controlled recovery after fault removal. The acceptance capability
field is `intrinsic_dc_fault_blocking=true` for this model.

### Half-Bridge Extension

`SubmoduleTopology` is a selectable contract with `full_bridge` as the first
implementation and `half_bridge` as the next implementation. The MMC arm,
topology, measurement, scenario, and publication layers remain shared. The
half-bridge implementation supplies its own electrical equations, gate mapping,
and fault policy, and reports `intrinsic_dc_fault_blocking=false`. Full-bridge
fault acceptance is never reused for half-bridge projects.

## MCP Interface

The builders expose independent lifecycle tools:

- `plan_blank_lcc_model`
- `build_blank_lcc_model`
- `get_blank_lcc_build_status`
- `validate_blank_lcc_model`
- `plan_blank_mmc_model`
- `build_blank_mmc_model`
- `get_blank_mmc_build_status`
- `validate_blank_mmc_model`

LCC request fields include `topology`, `ratings`, `operation_modes`, and future
parameterization fields. MMC request fields include `submodule_topology`,
`ratings`, `control_profile`, and `fault_profile`.

Plans contain component definitions, locations, ports, nets, parameters, output
channels, control bindings, fault events, source hashes, and the expected project
hash. Builds require the exact plan hash and `confirm=true`.

## Filesystem and Failure Semantics

- All writes are contained by `PSCAD_MCP_WORKSPACE`.
- Existing destinations are rejected rather than overwritten.
- Master Library and companion-library sources remain immutable.
- Staging is isolated by build ID and uses atomic publication.
- Any failed precondition or postcondition prevents publication of partial output.
- Missing definitions, unreadable bindings, unavailable timing/output capabilities,
  and failed read-back produce structured fail-closed errors.
- Every published project includes a companion library, scenario-source copies,
  a build journal, and an acceptance report.

## Verification Strategy

1. Pure unit tests cover request schemas, component contracts, placement,
   connectivity, gate mapping, fault logic, and capability declarations.
2. Fake-backend tests cover plan hashing, source immutability, staging, rollback,
   project identity, output-channel read-back, and lifecycle state transitions.
3. Licensed PSCAD 4.6.2 tests create both models from blank projects, compile,
   run steady-state cases, and run the LCC and MMC fault scenarios.
4. Half-bridge contract tests verify reuse of the MMC assembly while checking its
   distinct fault capability and acceptance limits.

The first milestone is accepted only when PSCAD loads and compiles both blank
projects, steady-state outputs satisfy the canonical reference bounds, LCC
commutation-failure checks pass, full-bridge MMC DC-fault-blocking checks pass,
all output and project hashes are reproducible, and pre-existing workspace and
library files remain unchanged.

## Risks and Follow-up

- The installed Master Library may lack definitions required by the reference
  recipes. The resolver must report the exact missing identity; it must not treat
  a packaged catalog as live evidence.
- PSCAD 4.6.2 backend support for timed control and public output-channel creation
  is a release blocker for dynamic acceptance.
- Full-bridge MMC simulation cost may require a reduced canonical submodule count
  for the first acceptance fixture, while keeping the count configurable in the
  blueprint.
- PSCAD 5.x support and arbitrary user-rated generation remain later milestones.
