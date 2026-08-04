# PSCAD 4.6.2 MCP Optimization Design

**Date:** 2026-08-04

**Status:** Approved for implementation

## Goal

Incrementally harden the PSCAD 4.6.2 MCP for release use while preserving the
existing 60-tool contract, dual-backend architecture, safety boundaries, and
the documented limitation that PSCAD 4.6.2 legacy automation launches a new
Automation instance rather than attaching to an already-open GUI.

## Scope and delivery order

The work is split into four independently testable batches:

1. **Delivery hardening**: align package metadata, add development dependency
   declarations, portable configuration examples, changelog coverage, and a
   Windows CI matrix.
2. **Error-contract consistency**: represent license failures as the same
   structured error payload used by other MCP failures, without changing the
   existing FastMCP wrapper shape.
3. **Runtime reliability**: add service-level serialization for state-changing
   operations, improve executor timeout/reset diagnostics, and expose PSOUT
   skipped-channel warnings instead of silently returning partial data.
4. **4.6.2 workflow capability**: add structured project messages, focused
   PSOUT analysis, and a minimal parameter-grid workflow only after the first
   three batches are green. Unsupported layer operations remain explicit
   capability failures.

Each batch must have its own focused tests and can be reverted independently.

## Architecture

The existing layering remains the system boundary:

`FastMCP tools -> PscadService -> PscadBackend protocol -> LegacyBackend /
ModernBackend -> vendor API`

Delivery metadata and CI changes stay outside runtime code. Runtime behavior is
implemented in the service, executor, adapter, and backend contract layers so
tool modules remain thin and continue to avoid raw vendor proxies.

### Delivery hardening

`pyproject.toml` and `pscad_mcp/__init__.py` use the same `0.2.0` development
version. The `dev` extra provides the test and Python 3.10 TOML compatibility
dependencies used by CI. A portable `config.example.toml` documents stdio
startup and the PSCAD 4.6.2 environment variables. Windows CI runs the
contract suite on Python 3.10, 3.11, and 3.12, then performs dependency,
compile, and tool-inventory checks.

### Error contract

Add a vendor-neutral `NOT_LICENSED` `BackendError`. `PscadService.run_project`
raises it when the backend explicitly reports `licensed=False`; the existing
registration wrapper serializes it as `{ "error": { ... } }`. An unknown
license state (`None`) does not block the operation and vendor failures remain
unchanged.

### Runtime serialization and recovery

The executor continues to serialize individual vendor calls and mark itself
unhealthy after a watchdog timeout. `PscadService` adds a mutation lock around
multi-call state-changing workflows, while independent read-only status calls
remain available. Lock boundaries must avoid nested acquisition when service
methods delegate to one another.

Executor diagnostics remain JSON-safe and bounded. They include the last
operation, timeout duration, reset generation, and whether a previous worker
was still being retired. Reset continues to create a fresh single-worker
executor and never exposes vendor objects through status.

### PSOUT diagnostics

`PscadAdapter.read_psout` keeps the current channel payload compatible and adds
an optional `warnings` list plus `skipped_channels` records. A trace that cannot
be read, sampled, or identified is recorded with its path/call ID and a bounded
reason. Domain failures remain distinguishable from value failures. Successful
channels are still returned even when some channels are unavailable.

### 4.6.2 workflow capabilities

Structured project messages are represented as JSON records with severity,
text, and optional source metadata when the vendor object exposes them; legacy
fallbacks preserve the current text output. PSOUT analysis accepts an optional
channel selector and returns bounded summary statistics without loading an
unbounded result into the MCP response. Parameter-grid support is restricted
to an explicit, validated input model and must report unsupported vendor
operations as `CAPABILITY_UNAVAILABLE`.

No implementation will claim support for layer creation or disabled-layer
membership while the tested PSCAD 4.6.2 Automation Library rejects those
commands. Modern PSCAD 5.x remains contract-tested until a licensed 5.x
end-to-end acceptance environment exists.

## Testing strategy

All behavior changes follow red-green-refactor:

- add one focused failing test;
- run that test and confirm the expected failure;
- implement the smallest behavior;
- run the focused test and then the full suite;
- refactor only while tests remain green.

Required gates before claiming a batch complete:

- `python -m pytest -q`;
- `python -m compileall -q pscad_mcp tests`;
- `python -m pip check`;
- `git diff --check`;
- package metadata and exact 60-tool inventory tests;
- licensed PSCAD 4.6.2 acceptance when the required environment variables and
  installation are available.

## Out of scope for this cycle

- Replacing the vendor Automation Library or changing PSCAD process ownership
  semantics;
- attaching the legacy backend to an already-open PSCAD GUI;
- broad refactoring of all 2,900+ lines of `legacy.py` before behavior is
  protected by additional tests;
- claiming PSCAD 5.x end-to-end support without a licensed installation.

