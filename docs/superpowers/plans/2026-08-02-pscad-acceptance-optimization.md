# PSCAD Acceptance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove avoidable PSCAD 4.6.2 port-query diagnostics and verify legacy shutdown cleanup without changing vendor packages or supported capabilities.

**Architecture:** Keep all behavior behind `LegacyBackend`. Resolve static definition metadata before the vendor port-location command, using the existing orientation/location transform as the preferred path and retaining vendor lookup only for incomplete metadata. Keep vendor `app.quit()` as the shutdown operation, then preserve backend ownership cleanup and test it explicitly.

**Tech Stack:** Python 3.10+, `unittest.IsolatedAsyncioTestCase`, `mhrc.automation` 1.2.4, `RobustExecutor`, PSCAD 4.6.2 acceptance harness.

---

### Task 1: Add regression tests for the two observed behaviors

**Files:**
- Modify: `tests/test_backend_components.py`
- Modify: `tests/test_backend_application.py`

- [ ] **Step 1: Write the failing static-port-first test**

Add a test to `TestBackendComponentContracts` that uses the existing legacy fake
backend fixture, supplies usable definition metadata and component orientation,
replaces `get_port_location` with a callable that raises if invoked, calls
`get_component_ports("case", 7)`, and asserts the returned ports use the static
offset transform. This captures the required behavior rather than asserting an
internal helper call.

- [ ] **Step 2: Run the focused component test and verify it fails**

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_components.TestBackendComponentContracts.test_legacy_prefers_static_port_metadata -v
```

Expected result: failure because the current implementation calls the vendor
`get_port_location` method before calculating the static fallback.

- [ ] **Step 3: Write the failing shutdown cleanup test**

Add a test to `TestBackendApplicationLifecycle` that attaches a fake legacy
application, calls `backend.quit()`, asserts the fake `quit` method was called,
and asserts `backend.owns_process` is `False` and `backend.heartbeat()` reports
`alive=False`. This protects connection metadata cleanup after shutdown.

- [ ] **Step 4: Run the focused application test and verify it fails if behavior regresses**

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_application.TestBackendApplicationLifecycle.test_quit_clears_legacy_connection_metadata -v
```

Expected result: the test exercises the current cleanup contract and must remain
green after implementation; if the fixture already satisfies it, keep it as a
regression test and use the port test as the red test for the implementation.

### Task 2: Make legacy port resolution prefer static metadata

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py:1388-1445`
- Test: `tests/test_backend_components.py`

- [ ] **Step 1: Implement the smallest production change**

In `LegacyBackend.get_component_ports`, load definition metadata before the
per-port loop when the component has a scoped definition and build `static_ports`
from it. For each port, call `_legacy_static_port_location` first when a static
port exists. Only call `component.get_port_location(port_name)` when no static
port metadata exists. Keep the current metadata lookup, `PortInfo` conversion,
and skip behavior unchanged.

- [ ] **Step 2: Run the focused component tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_components -v
```

Expected result: all component contract tests pass, including the new static
metadata preference test and existing incomplete-metadata fallback tests.

### Task 3: Preserve and verify legacy shutdown cleanup

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py:166-170` only if the focused test identifies a cleanup gap
- Test: `tests/test_backend_application.py`

- [ ] **Step 1: Keep vendor shutdown isolated**

Use `self.executor.run_safe(app.quit)` as the only vendor shutdown call. Do not
read private `_proc` or `_sock` members and do not edit `.venv`. Ensure
`disconnect()` runs after a successful vendor quit so `_app`, ownership,
orientation caches, run tracking, and managed-layer tracking are cleared.

- [ ] **Step 2: Run the focused application tests**

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_application tests.test_service_contract -v
```

Expected result: lifecycle and repair tests pass, including external-process
ownership protections.

### Task 4: Full verification and real acceptance

**Files:**
- Verify only; no additional source files unless a focused test requires a
  minimal correction.

- [ ] **Step 1: Run repository verification**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe -m compileall -q pscad_mcp
& .\.venv\Scripts\python.exe -m unittest discover tests -v
& .\.venv\Scripts\python.exe -c "from pscad_mcp.main import create_server; t=create_server()._tool_manager.list_tools(); print(len(t), len({x.name for x in t}))"
git diff --check
```

Expected result: no dependency or compile errors, all non-acceptance tests pass,
and the tool count is `53 53`.

- [ ] **Step 2: Run licensed PSCAD 4.6.2 acceptance**

Run:

```powershell
& 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -NoProfile -ExecutionPolicy Bypass -File 'D:\pscad-mcp\scripts\run_legacy_acceptance.ps1' -Workspace 'D:\PSCAD-Workspace\acceptance' -Version '4.6.2' -X64
```

Expected result: `Ran 14 tests`, `OK`, `ACCEPTANCE_FINAL_PROCESS_COUNT=0`, and
`ACCEPTANCE_COMPLETE=PASS`.

- [ ] **Step 3: Review the final diff and status**

Run `git diff --stat`, `git diff --check`, and `git status --short --branch`.
Confirm that only the planned source, tests, design, and plan files changed and
that no PSCAD process remains running.
