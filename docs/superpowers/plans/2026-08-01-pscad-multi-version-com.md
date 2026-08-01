# PSCAD Multi-Version COM Connection Implementation Plan

> **已取代：** 真实 PSCAD 4.6.2 验收证明其必须使用 `mhrc.automation`，不能复用 PSCAD 5.x 的 `mhi.pscad` 启动协议。后续实施以 `2026-08-01-pscad-dual-backend.md` 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the MCP connection path work with PSCAD 4.6.2 and remain compatible with PSCAD 5.x by initializing COM on the serialized worker and explicitly selecting installed PSCAD versions.

**Architecture:** Keep `RobustExecutor` as the single-threaded PSCAD call boundary, but initialize COM once in each worker lifetime. Add a focused launch-configuration module and move connect-versus-launch selection into `PscadAdapter`; the connection manager exposes ownership and selected-version information without duplicating version logic.

**Tech Stack:** Python 3.12, `unittest`, FastMCP 1.29, `mhi-pscad` 3.1, `pywin32/pythoncom`, PSCAD 4.6.2 on Windows.

---

## File map

- Create `pscad_mcp/core/pscad_config.py`: parse environment configuration and select an installed PSCAD version/architecture.
- Modify `pscad_mcp/core/executor.py`: initialize COM once per worker and repeat initialization after reset.
- Modify `pscad_mcp/core/pscad_adapter.py`: connect to an existing instance or explicitly launch the selected installed version.
- Modify `pscad_mcp/core/connection_manager.py`: expose connection metadata and keep adapter/manager state synchronized.
- Modify `pscad_mcp/tools/app_tools.py`: report selected version, ownership, and actionable connection failures.
- Create `tests/test_executor_com.py`: regression coverage for COM worker initialization.
- Create `tests/test_pscad_config.py`: environment parsing and installed-version selection coverage.
- Extend `tests/test_adapter_contracts.py`: connect/launch behavior and ownership coverage.
- Create `tests/test_connection_acceptance.py`: opt-in, bounded real PSCAD 4.6.2 acceptance test.
- Modify `README.md`: document multi-version configuration and acceptance command.

### Task 1: Prepare an isolated D-drive runtime

**Files:**
- Existing: `.gitignore`
- Runtime only: `.venv/`

- [ ] **Step 1: Confirm `.venv` is ignored**

Run:

```powershell
git check-ignore .venv
```

Expected: `.venv` is printed.

- [ ] **Step 2: Create the local environment**

Run:

```powershell
& 'C:\Users\335\Documents\Codex\2026-07-31\mu-q\work\pscad-mcp-review\.venv-review\Scripts\python.exe' -m venv .venv
```

Expected: exit code 0 and `.venv\Scripts\python.exe` exists.

- [ ] **Step 3: Install the project and Windows extras**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -e '.[windows]'
```

Expected: `pscad-mcp`, `mcp>=1.29,<2`, `mhi-pscad>=3.1,<4`, and `mhi-psout>=1.3,<2` install successfully.

- [ ] **Step 4: Record the baseline**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover tests -q
```

Expected: 67 tests pass before the new regression tests are added.

### Task 2: Initialize COM on the serialized worker

**Files:**
- Modify: `pscad_mcp/core/executor.py`
- Create: `tests/test_executor_com.py`

- [ ] **Step 1: Write the failing COM initialization tests**

Create tests that inject a callable and record the worker thread identifier:

```python
import threading
import unittest

from pscad_mcp.core.executor import RobustExecutor


class TestExecutorComInitialization(unittest.IsolatedAsyncioTestCase):
    async def test_initializes_com_before_first_worker_call(self):
        events = []

        def initialize_com():
            events.append(("com", threading.get_ident()))

        executor = RobustExecutor(com_initializer=initialize_com)
        try:
            worker_id = await executor.run_safe(threading.get_ident)
            self.assertEqual(events, [("com", worker_id)])
        finally:
            executor.shutdown()

    async def test_reset_initializes_com_on_replacement_worker(self):
        worker_ids = []

        def initialize_com():
            worker_ids.append(threading.get_ident())

        executor = RobustExecutor(com_initializer=initialize_com)
        try:
            await executor.run_safe(lambda: None)
            executor.reset()
            await executor.run_safe(lambda: None)
            self.assertEqual(len(worker_ids), 2)
        finally:
            executor.shutdown()
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_executor_com -v
```

Expected: FAIL because `RobustExecutor` does not accept `com_initializer` and does not initialize COM.

- [ ] **Step 3: Add a Windows-safe default initializer**

Add to `executor.py`:

```python
def _initialize_windows_com() -> None:
    try:
        import pythoncom
    except ImportError:
        return
    pythoncom.CoInitialize()
```

Store the injected initializer and construct the pool through one helper:

```python
def __init__(self, timeout: float = 30.0, com_initializer=None):
    self.timeout = timeout
    self.lock = threading.Lock()
    self.healthy = True
    self._com_initializer = com_initializer or _initialize_windows_com
    self.executor = self._new_executor()

def _new_executor(self) -> ThreadPoolExecutor:
    return ThreadPoolExecutor(
        max_workers=1,
        initializer=self._com_initializer,
        thread_name_prefix="pscad-com",
    )
```

Change `reset()` to call `_new_executor()` instead of constructing an uninitialized pool directly.

- [ ] **Step 4: Run focused and recovery tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_executor_com tests.test_executor_recovery tests.test_concurrency -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the isolated executor fix**

```powershell
git add pscad_mcp/core/executor.py tests/test_executor_com.py
git commit -m "fix: initialize COM on PSCAD worker"
```

If Git identity is still unset, leave the files uncommitted and report the blocker instead of changing global Git configuration.

### Task 3: Parse launch configuration and select installed versions

**Files:**
- Create: `pscad_mcp/core/pscad_config.py`
- Create: `tests/test_pscad_config.py`

- [ ] **Step 1: Write failing configuration tests**

Cover automatic selection, explicit selection, boolean parsing, and missing versions:

```python
import unittest

from pscad_mcp.core.pscad_config import PscadLaunchConfig, select_installation


class TestPscadLaunchConfig(unittest.TestCase):
    def test_prefers_highest_version_then_x64(self):
        config = PscadLaunchConfig.from_environ({})
        self.assertEqual(
            select_installation(
                [("4.6.2", False), ("5.0.1", False), ("5.0.1", True)],
                config,
            ),
            ("5.0.1", True),
        )

    def test_selects_explicit_462_x64(self):
        config = PscadLaunchConfig.from_environ(
            {"PSCAD_MCP_VERSION": "4.6.2", "PSCAD_MCP_X64": "true"}
        )
        self.assertEqual(
            select_installation([("4.6.2", False), ("4.6.2", True)], config),
            ("4.6.2", True),
        )

    def test_rejects_invalid_boolean(self):
        with self.assertRaisesRegex(ValueError, "PSCAD_MCP_X64"):
            PscadLaunchConfig.from_environ({"PSCAD_MCP_X64": "maybe"})

    def test_reports_installed_alternatives(self):
        config = PscadLaunchConfig.from_environ(
            {"PSCAD_MCP_VERSION": "5.0.0"}
        )
        with self.assertRaisesRegex(ValueError, "4.6.2"):
            select_installation([("4.6.2", True)], config)
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_pscad_config -v
```

Expected: import failure because `pscad_config.py` does not exist.

- [ ] **Step 3: Implement the configuration object and selector**

Create:

```python
from dataclasses import dataclass
import os
import re
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class PscadLaunchConfig:
    version: Optional[str] = None
    x64: Optional[bool] = None
    timeout: int = 30

    @classmethod
    def from_environ(cls, environ: Optional[Mapping[str, str]] = None):
        values = os.environ if environ is None else environ
        raw_x64 = values.get("PSCAD_MCP_X64")
        if raw_x64 is None:
            x64 = None
        elif raw_x64.strip().lower() in {"1", "true", "yes", "on"}:
            x64 = True
        elif raw_x64.strip().lower() in {"0", "false", "no", "off"}:
            x64 = False
        else:
            raise ValueError("PSCAD_MCP_X64 must be true or false.")
        timeout = int(values.get("PSCAD_MCP_LAUNCH_TIMEOUT", "30"))
        if timeout < 1:
            raise ValueError("PSCAD_MCP_LAUNCH_TIMEOUT must be positive.")
        return cls(values.get("PSCAD_MCP_VERSION") or None, x64, timeout)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(r"\d+", version))


def select_installation(
    installations: Sequence[tuple[str, bool]],
    config: PscadLaunchConfig,
) -> tuple[str, bool]:
    candidates = list(installations)
    if config.version is not None:
        candidates = [item for item in candidates if item[0] == config.version]
    if config.x64 is not None:
        candidates = [item for item in candidates if item[1] is config.x64]
    if not candidates:
        available = ", ".join(f"{v} ({'x64' if x else 'x86'})" for v, x in installations)
        raise ValueError(f"Requested PSCAD installation is unavailable. Installed: {available or 'none'}")
    return max(candidates, key=lambda item: (_version_key(item[0]), item[1]))
```

- [ ] **Step 4: Run configuration tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_pscad_config -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the configuration unit**

```powershell
git add pscad_mcp/core/pscad_config.py tests/test_pscad_config.py
git commit -m "feat: select installed PSCAD version"
```

If Git identity is unavailable, do not configure it automatically.

### Task 4: Replace default application launch with explicit connect-or-launch

**Files:**
- Modify: `pscad_mcp/core/pscad_adapter.py`
- Extend: `tests/test_adapter_contracts.py`

- [ ] **Step 1: Write failing adapter tests**

Add fake modules that record connection and launch calls:

```python
class FakePscadModule:
    def __init__(self, *, connected=None, installations=None):
        self.connected = connected
        self.installations = installations or [("4.6.2", True)]
        self.launch_kwargs = None

    def connect(self):
        if self.connected is None:
            raise ProcessLookupError("no automation instance")
        return self.connected

    def versions(self):
        return self.installations

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return FakePscad()
```

Test these behaviors separately:

```python
async def test_attach_reuses_existing_instance(self):
    existing = FakePscad()
    module = FakePscadModule(connected=existing)
    adapter = PscadAdapter(ImmediateExecutor(), pscad_module=module, environ={})
    self.assertIs(await adapter.attach_local(), existing)
    self.assertFalse(adapter.owns_process)

async def test_attach_launches_explicit_462(self):
    module = FakePscadModule(installations=[("4.6.2", True)])
    adapter = PscadAdapter(ImmediateExecutor(), pscad_module=module, environ={})
    await adapter.attach_local()
    self.assertEqual(
        module.launch_kwargs,
        {
            "version": "4.6.2",
            "x64": True,
            "minimum": "4.6.2",
            "timeout": 30,
        },
    )
    self.assertTrue(adapter.owns_process)
```

Add an explicit environment test for a 5.x installation:

```python
async def test_attach_launches_explicit_5x(self):
    module = FakePscadModule(installations=[("4.6.2", True), ("5.0.1", False)])
    adapter = PscadAdapter(
        ImmediateExecutor(),
        pscad_module=module,
        environ={
            "PSCAD_MCP_VERSION": "5.0.1",
            "PSCAD_MCP_X64": "false",
        },
    )
    await adapter.attach_local()
    self.assertEqual(module.launch_kwargs["version"], "5.0.1")
    self.assertFalse(module.launch_kwargs["x64"])
    self.assertEqual(module.launch_kwargs["minimum"], "5.0.1")
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_adapter_contracts -v
```

Expected: FAIL because the adapter still calls `application()` and exposes no ownership state.

- [ ] **Step 3: Implement connect-or-launch**

Update the constructor to accept `environ`, parse `PscadLaunchConfig`, and initialize metadata:

```python
self.config = PscadLaunchConfig.from_environ(environ)
self.owns_process = False
self.selected_installation = None
```

Implement `attach_local()` so an existing instance is tried first when no exact version or architecture override is requested. Otherwise, or after `ProcessLookupError`, enumerate and select an installation, then call:

```python
self._pscad = await self.executor.run_safe(
    self.pscad_module.launch,
    version=version,
    x64=x64,
    minimum=version,
    timeout=self.config.timeout,
)
self.owns_process = True
self.selected_installation = (version, x64)
```

Use `timeout=self.config.timeout + 5` as the executor watchdog while passing the configured timeout to MHI under a distinct keyword assembled inside a zero-argument callable, so `RobustExecutor.run_safe()` does not consume MHI's `timeout` argument.

- [ ] **Step 4: Keep disconnect non-destructive**

`disconnect()` clears `_pscad`, `owns_process`, and `selected_installation`; it does not call `quit()`.

- [ ] **Step 5: Run adapter, configuration, and executor tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_adapter_contracts tests.test_pscad_config tests.test_executor_com -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit the adapter fix**

```powershell
git add pscad_mcp/core/pscad_adapter.py tests/test_adapter_contracts.py
git commit -m "fix: launch compatible PSCAD versions explicitly"
```

### Task 5: Synchronize connection metadata and status reporting

**Files:**
- Modify: `pscad_mcp/core/connection_manager.py`
- Modify: `pscad_mcp/tools/app_tools.py`
- Create: `tests/test_connection_metadata.py`

- [ ] **Step 1: Write failing metadata tests**

Test that connection status reports source and selected installation without directly making unguarded COM calls:

```python
async def test_status_uses_manager_heartbeat_and_metadata(self):
    manager.heartbeat = AsyncMock(return_value={"alive": True, "busy": False})
    manager.connection_info = {
        "owns_process": True,
        "selected_version": "4.6.2",
        "x64": True,
    }
    result = await get_pscad_status()
    self.assertTrue(result["connected"])
    self.assertEqual(result["selected_version"], "4.6.2")
```

- [ ] **Step 2: Run the test and confirm RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_connection_metadata -v
```

Expected: FAIL because metadata is not exposed and status bypasses `heartbeat()`.

- [ ] **Step 3: Add manager metadata**

Expose a JSON-compatible property:

```python
@property
def connection_info(self) -> dict:
    selected = self.adapter.selected_installation
    return {
        "owns_process": self.adapter.owns_process,
        "selected_version": selected[0] if selected else None,
        "x64": selected[1] if selected else None,
    }
```

When the OS process check fails, call `adapter.disconnect()` so manager and adapter proxies cannot diverge.

- [ ] **Step 4: Route status through the manager heartbeat**

Change `get_pscad_status()` to call `await pscad_manager.heartbeat()`, merge `connection_info`, and serialize version/workspace fields with `str()`.

- [ ] **Step 5: Run app and metadata tests**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_connection_metadata tests.test_tools tests.test_protocol -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit metadata changes**

```powershell
git add pscad_mcp/core/connection_manager.py pscad_mcp/tools/app_tools.py tests/test_connection_metadata.py
git commit -m "fix: report PSCAD connection metadata"
```

### Task 6: Add a bounded real PSCAD acceptance test

**Files:**
- Create: `tests/test_connection_acceptance.py`
- Modify: `README.md`

- [ ] **Step 1: Add an opt-in acceptance test**

Create a test skipped unless `PSCAD_MCP_ACCEPTANCE=1` is set:

```python
import json
import os
import unittest

from pscad_mcp.core.connection_manager import pscad_manager


@unittest.skipUnless(
    os.getenv("PSCAD_MCP_ACCEPTANCE") == "1",
    "Set PSCAD_MCP_ACCEPTANCE=1 for real PSCAD validation.",
)
class TestRealPscadConnection(unittest.IsolatedAsyncioTestCase):
    async def test_connects_and_reads_application_state(self):
        await pscad_manager.attach_local()
        adapter = pscad_manager.adapter
        app = pscad_manager.pscad
        try:
            heartbeat = await pscad_manager.heartbeat()
            licensed = await adapter.call(app, "licensed")
            projects = await adapter.projects()
            settings = await adapter.settings()
            simulation_sets = await adapter.simulation_set_names()
            payload = {
                "heartbeat": heartbeat,
                "licensed": bool(licensed),
                "projects": projects,
                "settings": settings,
                "simulation_sets": simulation_sets,
            }
            json.dumps(payload, default=str)
            self.assertTrue(heartbeat["alive"])
        finally:
            if adapter.owns_process:
                await adapter.call(app, "quit", timeout=15)
            pscad_manager.disconnect()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Confirm the test is skipped by default**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m unittest tests.test_connection_acceptance -v
```

Expected: one skipped test and no PSCAD process launched.

- [ ] **Step 3: Document configuration and acceptance**

Add README examples for `PSCAD_MCP_VERSION`, `PSCAD_MCP_X64`, `PSCAD_MCP_LAUNCH_TIMEOUT`, and the opt-in acceptance command.

- [ ] **Step 4: Run the bounded real acceptance test**

Run from a fresh PowerShell process:

```powershell
$env:PSCAD_MCP_ACCEPTANCE = '1'
$env:PSCAD_MCP_VERSION = '4.6.2'
$env:PSCAD_MCP_X64 = 'true'
& '.\.venv\Scripts\python.exe' -m unittest tests.test_connection_acceptance -v
```

Expected: PASS with PSCAD 4.6.2 launched, queried, and closed. If it times out, stop only processes whose command line contains `/startup:au` and whose executable path is the detected PSCAD 4.6.2 binary.

- [ ] **Step 5: Verify process cleanup**

Run:

```powershell
Get-CimInstance Win32_Process |
    Where-Object {
        $_.ExecutablePath -eq 'C:\Program Files (x86)\PSCAD46\bin\win64\PSCAD.exe' -and
        $_.CommandLine -match '/startup:au'
    } |
    Select-Object ProcessId, CommandLine
```

Expected: no process created by the acceptance test remains.

- [ ] **Step 6: Commit acceptance coverage and documentation**

```powershell
git add tests/test_connection_acceptance.py README.md
git commit -m "test: add PSCAD connection acceptance coverage"
```

### Task 7: Final verification

**Files:**
- No new production files.

- [ ] **Step 1: Run the complete unit suite**

```powershell
& '.\.venv\Scripts\python.exe' -m unittest discover tests -v
```

Expected: all unit tests pass; the real acceptance test is skipped unless explicitly enabled.

- [ ] **Step 2: Compile all production modules**

```powershell
& '.\.venv\Scripts\python.exe' -m compileall pscad_mcp
```

Expected: exit code 0 with no syntax errors.

- [ ] **Step 3: Verify MCP registration**

```powershell
& '.\.venv\Scripts\python.exe' -c "from pscad_mcp.main import create_server; print(len(create_server()._tool_manager.list_tools()))"
```

Expected: `53`.

- [ ] **Step 4: Re-run the real PSCAD acceptance test**

Run the opt-in command from Task 6 and confirm it passes without leaving automation processes.

- [ ] **Step 5: Inspect the final change set**

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only the intended source, test, and documentation files are modified or added.

- [ ] **Step 6: Report the PSCAD 5.x boundary accurately**

State that 4.6.2 passed real end-to-end connection acceptance. State that 5.x version selection and launch arguments passed automated contract tests, but real 5.x execution remains unverified until a 5.x installation is available.
