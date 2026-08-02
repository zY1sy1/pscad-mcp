# PSCAD 4.6.2 Fault Recovery and Diagnostics Design

## Scope

This change hardens the existing PSCAD 4.6.x legacy backend after command
failures. It covers executor recovery, MCP error serialization, diagnostics,
logging, and regression tests. It does not add PSCAD 5.x behavior, automatic
operation retries, process termination by PID, or a new MCP tool.

The existing 53-tool contract remains unchanged.

## Goals

- Make `repair_connection` usable after a PSCAD command times out.
- Never query process ownership through an executor that is already unhealthy.
- Never launch a second legacy PSCAD instance when cleanup of an owned instance
  has failed.
- Preserve structured backend errors across the MCP boundary for every tool.
- Expose bounded executor diagnostics through `get_pscad_status`.
- Improve server-side failure logs without writing protocol-breaking data to
  standard output.

## Non-Goals

- No PSCAD 5.x feature or recovery work.
- No automatic retry of project mutations, builds, or simulations.
- No forced process termination or PID discovery.
- No persistent log store or new diagnostics MCP tool.
- No automatic execution of licensed PSCAD acceptance tests.

## Architecture

### Executor Diagnostics

`RobustExecutor` remains the single-threaded COM execution boundary. It records
bounded, JSON-safe state for the most recent call:

- `healthy`
- `last_operation`
- `last_error`
- `last_timeout_seconds`

The state is updated when a call starts, succeeds, raises, or times out. A reset
clears the failure and timeout fields while retaining no vendor proxy values.
The executor exposes a snapshot method so the service does not read mutable
fields individually.

### Recovery State Machine

`PscadService.repair_connection` uses the backend's cached `owns_process`
property. It does not call `heartbeat` to rediscover ownership.

For a healthy executor:

1. If the current backend owns PSCAD, request a normal backend quit.
2. Otherwise, disconnect without terminating PSCAD.
3. Clear the backend, reset the executor, and attach a fresh backend.

For an unhealthy executor:

1. Read cached ownership without making a COM call.
2. If the backend does not own PSCAD, disconnect it, reset the executor, and
   attach again.
3. If the backend owns PSCAD, reset the executor first so a fresh COM worker can
   attempt the normal quit operation.
4. If quit succeeds, clear the backend, reset once more to discard the cleanup
   worker, and attach a fresh backend.
5. If quit fails or times out, clear stale in-process backend references, reset
   the executor to a usable state, and raise `REPAIR_CLEANUP_FAILED`. Do not
   launch another PSCAD instance. The error tells the caller to close the owned
   PSCAD process manually and retry `repair_connection`.

This ordering preserves the existing process-ownership safety rule while
removing the dependency on a failed executor during ownership detection.

## MCP Error Boundary

Tool registration uses one shared wrapper around every registered function.
The original tool signature, name, annotations, and documentation remain
visible to FastMCP.

Successful values pass through unchanged. On failure, the wrapper returns the
existing service error payload instead of allowing FastMCP to reduce the error
to an unstructured `ToolError` string.

Every error payload contains:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Project 'case' was not found.",
    "backend": "legacy",
    "operation": "run_project",
    "details": {},
    "retryable": false,
    "suggested_action": "Check the project name and list loaded projects."
  }
}
```

Existing `BackendError` fields are preserved. `retryable` and
`suggested_action` are derived from a small explicit mapping of known codes.
Unknown exceptions use `INTERNAL_ERROR`, are not automatically retryable, and
tell the caller to inspect status and server logs. Exception class names and
tracebacks are not returned to MCP clients.

Direct Python calls to tool functions retain their current behavior and may
raise exceptions. Serialization occurs only at the MCP registration boundary.

## Status and Logging

`get_pscad_status` keeps all current top-level fields and adds an `executor`
object containing the diagnostic snapshot. Status remains safe before the first
connection and after a failed repair.

Executor logs include operation name and elapsed time. Unexpected exceptions
include a traceback through `logger.exception`; timeouts retain a concise error
record. Python logging continues to use standard error, which is safe for the
MCP stdio transport.

No project parameter values, vendor proxy representations, or unbounded vendor
responses are logged or returned.

## Testing

Implementation follows red-green-refactor cycles.

Regression tests cover:

- recovery from an unhealthy executor without calling heartbeat;
- owned-process cleanup after an executor reset;
- cleanup failure returning `REPAIR_CLEANUP_FAILED` without a fresh attach;
- non-owned process disconnection without termination;
- structured `BackendError` preservation through a real FastMCP tool call;
- normalization of an unexpected exception;
- unchanged tool names, schemas, and exact count of 53;
- executor diagnostic state across success, error, timeout, and reset;
- status diagnostics before connection and after executor failure;
- logging to standard error without protocol output on standard output.

All repository tests must pass. Licensed PSCAD 4.6.x acceptance remains opt-in
through `PSCAD_MCP_ACCEPTANCE=1` and is not run automatically because it launches
PSCAD and mutates timestamped project copies.

## Compatibility

The change is backward compatible for successful tool calls and tool discovery.
Failure calls become more structured: callers receive a normal tool result with
an `error` object instead of an MCP execution exception. Existing clients that
only display text can still use `error.message`; clients that understand the
schema can make deterministic recovery decisions.
