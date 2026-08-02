# PSCAD 4.6.2 Fault Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PSCAD 4.6.x timeout recovery reliable and preserve actionable structured errors across all 53 MCP tools.

**Architecture:** Extend the shared COM executor with bounded diagnostics, turn repair into an ownership-aware state machine that does not depend on an unhealthy COM channel, and wrap tool registration with one MCP-only error boundary. Keep direct Python tool behavior and the exact 53-tool surface unchanged.

**Tech Stack:** Python 3.10+, asyncio, `concurrent.futures.ThreadPoolExecutor`, FastMCP 1.x, unittest/pytest.

---

## File Structure

- Modify `pscad_mcp/core/executor.py`: typed executor failures, diagnostic snapshot, elapsed-time and traceback logging.
- Modify `pscad_mcp/core/service.py`: recovery state machine, error classification, status diagnostics.
- Create `pscad_mcp/tools/registration.py`: shared MCP registration and error serialization boundary.
- Modify all seven `pscad_mcp/tools/*_tools.py` registration functions to use the shared boundary.
- Modify `tests/backend_fakes.py`: keep the shared fake executor compatible with the diagnostic contract.
- Modify `tests/test_executor_recovery.py`: executor diagnostic and logging regression tests.
- Modify `tests/test_service_contract.py`: unhealthy recovery and normalized error contract tests.
- Modify `tests/test_protocol.py`: real FastMCP structured-error and schema preservation tests.
- Modify `tests/test_app_service_routing.py`: status diagnostic routing expectations where needed.
- Modify `README.md` and `docs/zh-CN/README.md`: document structured errors and recovery behavior.

### Task 1: Executor Diagnostics and Typed Failures

**Files:**
- Modify: `tests/test_executor_recovery.py`
- Modify: `pscad_mcp/core/executor.py`

- [ ] **Step 1: Write failing diagnostic tests**

Add tests that use a real `RobustExecutor` and assert:

```python
snapshot = executor.snapshot()
self.assertTrue(snapshot["healthy"])
self.assertEqual(snapshot["last_operation"], "<lambda>")
self.assertIsNone(snapshot["last_error"])
```

Add an exception test that expects `last_error` to contain only a bounded
message, and a timeout test that expects `ExecutorTimeoutError`,
`healthy=False`, and the effective timeout in `last_timeout_seconds`. Add a
reset assertion that the executor becomes healthy and clears failure fields.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests\test_executor_recovery.py
```

Expected: failures because `snapshot` and `ExecutorTimeoutError` do not exist.

- [ ] **Step 3: Implement the minimal executor contract**

In `executor.py`, add:

```python
class ExecutorTimeoutError(RuntimeError):
    pass


class ExecutorUnhealthyError(RuntimeError):
    pass
```

Track `last_operation`, bounded `last_error`, and `last_timeout_seconds` under a
small state lock. Return copies through `snapshot()`. Raise the typed failures,
log elapsed operation time, use `logger.exception` for unexpected exceptions,
and keep all logging free of function arguments and vendor proxy values.

- [ ] **Step 4: Run executor tests and verify GREEN**

Run the Task 1 command. Expected: all executor recovery tests pass.

- [ ] **Step 5: Commit executor diagnostics**

```powershell
git add pscad_mcp/core/executor.py tests/test_executor_recovery.py
git commit -m "fix: expose executor failure diagnostics"
```

### Task 2: Unhealthy Executor Recovery State Machine

**Files:**
- Modify: `tests/backend_fakes.py`
- Modify: `tests/test_service_contract.py`
- Modify: `pscad_mcp/core/service.py`

- [ ] **Step 1: Extend the fake executor contract**

Give `ImmediateExecutor` a `snapshot()` method returning the same four keys as
`RobustExecutor`. Keep `reset_count` behavior unchanged.

- [ ] **Step 2: Write failing recovery tests**

Add tests for these exact event sequences:

```python
# unhealthy, owned, successful cleanup
[
    ("reset", "executor"),
    ("quit", "backend-1"),
    ("reset", "executor"),
    ("factory", "backend-2"),
    ("attach", "backend-2"),
]

# unhealthy, external
[
    ("disconnect", "backend-1"),
    ("reset", "executor"),
    ("factory", "backend-2"),
    ("attach", "backend-2"),
]
```

Make backend heartbeat raise if called so the tests prove repair does not use
it. Add an unhealthy-owned cleanup failure test asserting:

```python
self.assertEqual(error.code, "REPAIR_CLEANUP_FAILED")
self.assertIsNone(service._backend)
self.assertTrue(executor.healthy)
self.assertEqual(len(created_backends), 1)
```

Retain the existing healthy cleanup-failure test, which must preserve the old
backend and must not reset the executor.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests\test_service_contract.py
```

Expected: unhealthy recovery tests fail because repair calls heartbeat before
reset and does not emit `REPAIR_CLEANUP_FAILED`.

- [ ] **Step 4: Implement ownership-aware recovery**

Read `current.owns_process` directly. For an unhealthy owned backend, reset
before quit and reset again before fresh attach. On a second cleanup failure,
disconnect local references without another COM request, clear `_backend`,
reset the executor, and raise a legacy `BackendError` with code
`REPAIR_CLEANUP_FAILED`, bounded cleanup error details, and operation
`repair_connection`. Never call the backend factory in that failure branch.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Task 2 command. Expected: all service contract tests pass.

- [ ] **Step 6: Commit recovery state machine**

```powershell
git add pscad_mcp/core/service.py tests/backend_fakes.py tests/test_service_contract.py
git commit -m "fix: recover legacy executor after timeout"
```

### Task 3: Actionable Error Classification

**Files:**
- Modify: `tests/test_service_contract.py`
- Modify: `pscad_mcp/core/service.py`

- [ ] **Step 1: Write failing payload tests**

Assert that a `BackendError("NOT_FOUND", ...)` retains all existing fields and
adds:

```python
{"retryable": False, "suggested_action": "Check names and list the current PSCAD objects."}
```

Assert that `ExecutorTimeoutError` maps to `TIMEOUT` with `retryable=True`, an
unhealthy executor maps to `EXECUTOR_UNHEALTHY`, confirmation remains
non-retryable, partial completion instructs inspection before retry, and an
unknown exception maps to a non-retryable `INTERNAL_ERROR` without a traceback.

- [ ] **Step 2: Run payload tests and verify RED**

Run the Task 2 command. Expected: failures because action metadata and typed
executor mappings are absent.

- [ ] **Step 3: Implement explicit classifications**

Add a small constant mapping in `service.py` for known codes. Keep mapping
values static and bounded. Update `error_payload` to preserve `BackendError`
payloads, normalize typed executor errors, and add `retryable` plus
`suggested_action` to every error.

- [ ] **Step 4: Run payload tests and verify GREEN**

Run the Task 2 command. Expected: all service error tests pass.

- [ ] **Step 5: Commit actionable error metadata**

```powershell
git add pscad_mcp/core/service.py tests/test_service_contract.py
git commit -m "fix: classify actionable PSCAD errors"
```

### Task 4: Shared MCP Error Boundary

**Files:**
- Create: `pscad_mcp/tools/registration.py`
- Modify: `pscad_mcp/tools/app_tools.py`
- Modify: `pscad_mcp/tools/project_tools.py`
- Modify: `pscad_mcp/tools/data_tools.py`
- Modify: `pscad_mcp/tools/simset_tools.py`
- Modify: `pscad_mcp/tools/creation_tools.py`
- Modify: `pscad_mcp/tools/canvas_tools.py`
- Modify: `pscad_mcp/tools/component_tools.py`
- Modify: `tests/test_protocol.py`
- Modify: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write failing FastMCP boundary tests**

Create a real server, replace the relevant service operation with an async
failure, and call `server._tool_manager.call_tool`. Assert a `BackendError`
returns a normal tool result containing the full error object instead of raising
`ToolError`. Repeat with `ValueError` to verify `INTERNAL_ERROR`. Assert direct
calls to `run_project` still raise. Retain exact tool-name and count assertions.

- [ ] **Step 2: Run protocol tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests\test_protocol.py tests\test_tool_backend_matrix.py
```

Expected: the FastMCP call raises `ToolError` and loses structured fields.

- [ ] **Step 3: Implement shared registration**

Create a `register_tool(mcp, function)` helper using `functools.wraps`. Its async
wrapper catches `Exception` only and returns
`pscad_manager.error_payload(error, function.__name__)`. Register that wrapper
with FastMCP. Replace each `mcp.tool()(function)` call in the seven registration
functions with `register_tool(mcp, function)`.

Do not catch `BaseException`, do not alter direct tool functions, and do not
change registered names or signatures.

- [ ] **Step 4: Run protocol tests and verify GREEN**

Run the Task 4 command. Expected: structured result tests pass and tool count is
exactly 53.

- [ ] **Step 5: Commit the MCP error boundary**

```powershell
git add pscad_mcp/tools tests/test_protocol.py tests/test_tool_backend_matrix.py
git commit -m "fix: preserve structured MCP tool errors"
```

### Task 5: Status Diagnostics and Documentation

**Files:**
- Modify: `tests/test_service_contract.py`
- Modify: `tests/test_app_service_routing.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`

- [ ] **Step 1: Write failing status tests**

Assert `service.status()` includes:

```python
"executor": {
    "healthy": True,
    "last_operation": None,
    "last_error": None,
    "last_timeout_seconds": None,
}
```

Cover both pre-attach status and a failed heartbeat path through
`get_pscad_status`.

- [ ] **Step 2: Run status tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests\test_service_contract.py tests\test_app_service_routing.py tests\test_tools.py
```

Expected: diagnostics assertions fail because status omits the executor object.

- [ ] **Step 3: Implement status diagnostics**

Add the executor snapshot to both disconnected and connected status results.
When heartbeat fails, `get_pscad_status` retains `connected=False`, returns the
structured error, and includes the executor snapshot.

- [ ] **Step 4: Update user documentation**

Document that all tool failures return a stable `error` object, show the new
executor status fields, and explain that `REPAIR_CLEANUP_FAILED` requires the
owned PSCAD process to be closed manually before retrying repair.

- [ ] **Step 5: Run status tests and verify GREEN**

Run the Task 5 command. Expected: all focused tests pass.

- [ ] **Step 6: Commit status and documentation**

```powershell
git add pscad_mcp/core/service.py tests/test_service_contract.py tests/test_app_service_routing.py README.md docs/zh-CN/README.md
git commit -m "docs: describe PSCAD recovery diagnostics"
```

### Task 6: Full Verification

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run the default repository suite**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q -rs
```

Expected: all non-acceptance tests pass; only licensed PSCAD 4.6.x acceptance
tests are skipped.

- [ ] **Step 2: Run the documented unittest command**

```powershell
& .\.venv\Scripts\python.exe -m unittest discover tests
```

Expected: exit code 0.

- [ ] **Step 3: Verify the original reproductions**

Run the unhealthy-executor repair regression and real FastMCP error-boundary
tests individually. Expected: repair reaches a fresh backend after successful
cleanup, and FastMCP returns structured `code` and `details` fields.

- [ ] **Step 4: Check repository hygiene**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; status lists only intentional implementation,
test, plan, and documentation changes.

- [ ] **Step 5: Review the diff against the design**

Confirm no PSCAD 5.x-specific behavior, no PID termination, no automatic
mutation retry, no new MCP tool, and an exact tool count of 53.
