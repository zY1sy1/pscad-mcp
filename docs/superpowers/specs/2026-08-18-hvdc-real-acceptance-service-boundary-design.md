# HVDC Real Acceptance Service Boundary Design

## Context

The licensed PSCAD 4.6 HVDC acceptance test now runs with the configured
Breaker project, library, and isolated workspace. Its first live execution
failed before simulation because `ensure_output_ready()` received a raw
`LegacyBackend` and called `get_project_settings()`. Raw backends implement the
stable `get_settings()` / `set_settings()` contract; the application-facing
`PscadService` exposes `get_project_settings()` / `set_project_settings()`.

Production HVDC tools already pass `pscad_manager.service`, a `PscadService`,
to `HvdcDomainService`. The acceptance harness was therefore exercising a
different dependency boundary from production.

## Decision

Correct the acceptance harness so it follows the production service boundary:

1. Construct the real `LegacyBackend` through a `PscadService` backend factory.
2. Attach and load the timestamped project copies through `PscadService`.
3. Pass that `PscadService` to `HvdcDomainService` and
   `ensure_output_ready()`.
4. Retain a reference to the selected raw backend only for backend-specific
   output reads, capability evidence, ownership checks, and cleanup evidence.

No aliases will be added to `LegacyBackend` or `ModernBackend`, and
`ensure_output_ready()` will not duck-type both service and backend method
names. Keeping one boundary prevents the acceptance test from masking future
production wiring errors.

## Data Flow

The live path will be:

```text
acceptance paths
    -> PscadService path policy and lifecycle
    -> LegacyBackend PSCAD 4.6 automation
    -> HvdcDomainService scenario preflight and execution
    -> raw backend result/capability evidence
```

All source inputs remain outside `PSCAD_MCP_WORKSPACE`. The test continues to
copy the case, library, and `lib` directory into a new timestamped acceptance
directory before any mutation.

## Error Handling And Cleanup

- A failure at any stage remains captured until source and library hashes are
  rechecked.
- An acceptance-owned PSCAD process is terminated in `finally`; a non-owned
  connection is disconnected.
- The test continues to report safe rejection when strict timed control or an
  approved writable mapping is unavailable.
- The change does not broaden vendor capability claims or infer command
  bindings.

## Verification

The existing licensed acceptance failure is the red test for this defect. After
the wiring correction, verification must include:

1. The real test `tests/test_hvdc_real_acceptance.py` with the four persisted
   acceptance variables loaded into the test process.
2. Confirmation that the acceptance-owned PSCAD process is cleaned up and the
   original source, library, and `lib` hashes remain unchanged.
3. The complete default pytest suite.
4. Python compilation and `git diff --check`.

## Out Of Scope

- Adding service-layer aliases to raw backend classes.
- Changing the `PscadBackend` protocol.
- Adding or renaming MCP tools.
- Claiming timed external-event support when PSCAD does not expose a confirmed
  provider or workspace command binding.
