# PSCAD Session and Run Control Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PSCAD 4.6.2 launch as a visible, safely owned automation session, prevent application-wide pause/stop from affecting another active project, register the server in Codex, and prove the result with a real-machine smoke test.

**Architecture:** Parse the legacy launch policy once at the configuration boundary, inventory existing PSCAD processes through a small read-only helper, and inject those settings into `LegacyBackend`. Keep the existing 60-tool MCP contract while adding run-state preconditions and postcondition polling around vendor commands; use the modern API's explicit single-project stop entry point when available. The component enable/disable implementation is deliberately untouched.

**Tech Stack:** Python 3.10+, asyncio, psutil, mhrc.automation 1.2.4, mhi.pscad 3.1.2, FastMCP/MCP 1.29, pytest/unittest, PowerShell, Codex TOML configuration.

---

## File map

- Create `pscad_mcp/core/process_inventory.py`: bounded, read-only PSCAD process discovery and PID description.
- Create `pscad_mcp/core/backend/run_control.py`: shared active/terminal status constants and structured scope validation.
- Modify `pscad_mcp/core/pscad_config.py`: parse visible/minimized launch mode and existing-process policy.
- Modify `pscad_mcp/core/connection_manager.py`: inject parsed legacy settings into the selected backend.
- Modify `pscad_mcp/core/backend/legacy.py`: preflight existing processes, record the owned PID, guard global pause/stop, and verify outcomes.
- Modify `pscad_mcp/core/backend/modern.py`: guard global pause and prefer `stop_single_project(project)`.
- Modify `pscad_mcp/core/service.py`: serialize pause/stop mutations, expose bounded session diagnostics, and add guidance for new error codes.
- Modify `tests/backend_fakes.py`, `tests/test_backend_application.py`, `tests/test_backend_projects.py`, `tests/test_pscad_config.py`, and `tests/test_service_contract.py`: deterministic red/green coverage.
- Modify `config.example.toml`, `README.md`, `README.zh-CN.md` if present, and `CHANGELOG.md`: document actual capabilities and remaining 4.6.2 boundary.
- Modify `C:\Users\335\.codex\config.toml`: register the verified local stdio server after all repository tests pass.

### Task 1: Parse legacy launch policy

**Files:**
- Modify: `pscad_mcp/core/pscad_config.py`
- Modify: `pscad_mcp/core/connection_manager.py`
- Test: `tests/test_pscad_config.py`

- [ ] **Step 1: Write failing configuration tests**

```python
def test_legacy_session_defaults_are_visible_and_reject_external_processes(self):
    config = PscadLaunchConfig.from_environ({})
    self.assertFalse(config.legacy_minimize)
    self.assertEqual(config.legacy_existing_policy, "reject")

def test_legacy_session_policy_accepts_explicit_values(self):
    config = PscadLaunchConfig.from_environ({
        "PSCAD_MCP_LEGACY_MINIMIZE": "true",
        "PSCAD_MCP_LEGACY_EXISTING_POLICY": "allow",
    })
    self.assertTrue(config.legacy_minimize)
    self.assertEqual(config.legacy_existing_policy, "allow")

def test_legacy_session_policy_rejects_invalid_values(self):
    with self.assertRaisesRegex(ValueError, "PSCAD_MCP_LEGACY_MINIMIZE"):
        PscadLaunchConfig.from_environ({"PSCAD_MCP_LEGACY_MINIMIZE": "maybe"})
    with self.assertRaisesRegex(ValueError, "PSCAD_MCP_LEGACY_EXISTING_POLICY"):
        PscadLaunchConfig.from_environ({"PSCAD_MCP_LEGACY_EXISTING_POLICY": "attach"})
```

- [ ] **Step 2: Run the tests and confirm the red state**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_pscad_config.py -q`

Expected: FAIL because `PscadLaunchConfig` has no `legacy_minimize` or `legacy_existing_policy` fields.

- [ ] **Step 3: Add strict parsing and inject it into the backend**

```python
@dataclass(frozen=True)
class PscadLaunchConfig:
    # existing fields stay unchanged
    legacy_minimize: bool = False
    legacy_existing_policy: Literal["reject", "allow"] = "reject"

    @staticmethod
    def _boolean(values: Mapping[str, str], name: str, default: bool) -> bool:
        raw = values.get(name)
        if raw is None:
            return default
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{name} must be true or false.")
```

In `_default_backend_factory`, call `PscadLaunchConfig.from_environ(os.environ)` once and pass:

```python
legacy_minimize=config.legacy_minimize,
legacy_existing_policy=config.legacy_existing_policy,
```

- [ ] **Step 4: Run the focused tests**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_pscad_config.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit the configuration boundary**

```powershell
git add pscad_mcp/core/pscad_config.py pscad_mcp/core/connection_manager.py tests/test_pscad_config.py
git commit -m "feat: configure legacy PSCAD session policy"
```

### Task 2: Reject unmanaged GUI sessions and record the owned process

**Files:**
- Create: `pscad_mcp/core/process_inventory.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Test: `tests/test_backend_application.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
async def test_legacy_launch_is_visible_by_default(self):
    module = FakeLegacyAutomation()
    backend = LegacyBackend(
        ImmediateExecutor(), version="4.6.2", x64=True,
        automation_module=module, process_probe=lambda: [],
    )
    await backend.attach()
    self.assertFalse(module.launch_kwargs["minimize"])

async def test_legacy_rejects_existing_unmanaged_pscad_before_launch(self):
    module = FakeLegacyAutomation()
    backend = LegacyBackend(
        ImmediateExecutor(), version="4.6.2", x64=True,
        automation_module=module,
        process_probe=lambda: [{"pid": 4321, "name": "Pscad.exe", "exe": r"C:\Program Files (x86)\PSCAD46\bin\win64\Pscad.exe"}],
    )
    with self.assertRaises(BackendError) as raised:
        await backend.attach()
    self.assertEqual(raised.exception.code, "EXTERNAL_PSCAD_PRESENT")
    self.assertIsNone(module.launch_kwargs)

async def test_explicit_allow_policy_starts_a_separate_owned_instance(self):
    module = FakeLegacyAutomation()
    backend = LegacyBackend(
        ImmediateExecutor(), version="4.6.2", x64=True,
        automation_module=module, legacy_existing_policy="allow",
        process_probe=lambda: [{"pid": 4321, "name": "Pscad.exe", "exe": "Pscad.exe"}],
    )
    await backend.attach()
    self.assertTrue(backend.owns_process)
```

- [ ] **Step 2: Verify lifecycle tests fail for the intended reasons**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_backend_application.py -q`

Expected: FAIL on unknown constructor keywords/default `minimize=True` and absent `EXTERNAL_PSCAD_PRESENT` behavior.

- [ ] **Step 3: Implement bounded process inventory**

```python
def list_pscad_processes() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for process in psutil.process_iter(("pid", "name", "exe")):
        try:
            name = str(process.info.get("name") or "")
            exe = str(process.info.get("exe") or "")
            if "pscad" not in name.casefold() and "pscad" not in Path(exe).name.casefold():
                continue
            records.append({"pid": int(process.info["pid"]), "name": name[:128], "exe": exe[:512]})
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, TypeError, ValueError):
            continue
    return sorted(records, key=lambda item: int(item["pid"]))[:16]
```

- [ ] **Step 4: Add preflight and owned-session metadata**

`LegacyBackend.attach()` must call the injected probe before `launch_pscad`, raise `BackendError` with code `EXTERNAL_PSCAD_PRESENT` and the bounded process records under the default `reject` policy, launch with `minimize=self.legacy_minimize`, and capture `self._app._proc.pid` when available. Expose only this bounded property:

```python
@property
def session_details(self) -> dict[str, object]:
    return {
        "mode": "managed-launch",
        "managed_pid": self._managed_pid,
        "legacy_minimize": self.legacy_minimize,
        "existing_process_policy": self.legacy_existing_policy,
        "ordinary_gui_attach_supported": False,
    }
```

- [ ] **Step 5: Run lifecycle and dependency tests**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_backend_application.py tests/test_pscad_config.py -q`

Expected: all tests PASS, and no real PSCAD process is launched because the tests use fakes.

- [ ] **Step 6: Commit the owned-session implementation**

```powershell
git add pscad_mcp/core/process_inventory.py pscad_mcp/core/backend/legacy.py tests/test_backend_application.py
git commit -m "feat: manage visible legacy PSCAD sessions safely"
```

### Task 3: Guard and verify legacy application-wide pause/stop

**Files:**
- Create: `pscad_mcp/core/backend/run_control.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `tests/test_backend_projects.py`
- Test: `tests/test_backend_projects.py`

- [ ] **Step 1: Write failing run-control safety tests**

```python
async def test_pause_rejects_two_active_projects_without_sending_command(self):
    backend, app, project = await self.make_backend()
    app.project_map["other"] = FakeProject("other")
    project.run_status_response = ("running", 20)
    app.project_map["other"].run_status_response = ("building", None)
    with self.assertRaises(BackendError) as raised:
        await backend.pause_project("case")
    self.assertEqual(raised.exception.code, "RUN_CONTROL_SCOPE_CONFLICT")
    self.assertEqual(app.command_calls, [])

async def test_stop_rejects_inactive_target_without_sending_command(self):
    backend, app, project = await self.make_backend()
    project.run_status_response = ("idle", None)
    with self.assertRaises(BackendError) as raised:
        await backend.stop_project("case")
    self.assertEqual(raised.exception.code, "RUN_NOT_ACTIVE")
    self.assertEqual(app.command_calls, [])

async def test_pause_and_stop_verify_postconditions(self):
    backend, app, project = await self.make_backend()
    project.run_status_response = ("running", 25)
    await backend.pause_project("case")
    self.assertEqual((await backend.project_run_state("case")).status, "paused")
    await backend.stop_project("case")
    self.assertIn((await backend.project_run_state("case")).status, {"stopped", "idle", "completed"})
```

- [ ] **Step 2: Confirm the unsafe baseline fails**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_backend_projects.py::TestLegacyRunControl -q`

Expected: FAIL because the current backend sends global commands without checking other projects or verifying the result.

- [ ] **Step 3: Implement shared scope validation**

```python
ACTIVE_RUN_STATUSES = frozenset({"starting", "building", "running", "paused"})
STOPPED_RUN_STATUSES = frozenset({"idle", "stopped", "complete", "completed"})

def require_single_active_target(project_name, states, *, backend, operation):
    target = states.get(project_name)
    active = {name: state.status for name, state in states.items() if state.status.casefold() in ACTIVE_RUN_STATUSES}
    if target is None or target.status.casefold() not in ACTIVE_RUN_STATUSES:
        raise BackendError("RUN_NOT_ACTIVE", f"Project '{project_name}' is not active.", backend, operation,
                           {"project_name": project_name, "state": getattr(target, "status", None)})
    if set(active) != {project_name}:
        raise BackendError("RUN_CONTROL_SCOPE_CONFLICT", "The vendor command would affect more than the requested project.", backend, operation,
                           {"project_name": project_name, "active_projects": active, "scope": "all-running-projects"})
    return target
```

- [ ] **Step 4: Guard the vendor command and poll the postcondition**

Implement `_case_run_states()`, `_wait_for_project_state()`, and use them in `pause_project`/`stop_project`. Do not send a command on a precondition failure. `pause_project` succeeds only after `paused`; `stop_project` succeeds after a stopped terminal state and clears tracking only for the target. Raise `POSTCONDITION_FAILED` with the last state and bounded timeout when polling expires.

- [ ] **Step 5: Make test commands model the vendor's global effect**

Extend `FakeCommand.execute()` to invoke an optional `owner.command_effects[name]`; configure `FakeLegacyApp` pause to set all active fake cases to `("paused", progress)` and stop to set them to `("stopped", progress)`. This makes both happy-path verification and the multi-project hazard deterministic.

- [ ] **Step 6: Run all project backend tests**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_backend_projects.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit the legacy run-control guard**

```powershell
git add pscad_mcp/core/backend/run_control.py pscad_mcp/core/backend/legacy.py tests/test_backend_projects.py
git commit -m "feat: guard legacy PSCAD run control scope"
```

### Task 4: Use the safest modern run-control entry points

**Files:**
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `tests/test_backend_projects.py`
- Test: `tests/test_backend_projects.py`

- [ ] **Step 1: Write failing modern tests**

```python
async def test_modern_stop_prefers_single_project_api(self):
    backend, app = (await self.make_backends())[1]
    app.single_stop_calls = []
    app.stop_single_project = lambda project: app.single_stop_calls.append(project.name) or True
    await backend.stop_project("case")
    self.assertEqual(app.single_stop_calls, ["case"])
    self.assertNotIn(("stop",), app.project_map["case"].calls)

async def test_modern_pause_rejects_multiple_active_projects(self):
    backend, app = (await self.make_backends())[1]
    app.project_map["other"] = FakeProject("other")
    with self.assertRaises(BackendError) as raised:
        await backend.pause_project("case")
    self.assertEqual(raised.exception.code, "RUN_CONTROL_SCOPE_CONFLICT")
```

- [ ] **Step 2: Confirm the tests fail**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_backend_projects.py -k "modern and (stop or pause)" -q`

Expected: FAIL because `Project.stop()` is used directly and pause has no scope guard.

- [ ] **Step 3: Implement modern behavior**

Before modern pause, collect loaded case states and call `require_single_active_target`. For stop, require the target to be active, then call:

```python
project = await self._project(project_name)
single_stop = getattr(self._app, "stop_single_project", None)
if callable(single_stop):
    result = await self.adapter.call(self._app, "stop_single_project", project)
    if result is False:
        raise BackendError("PSCAD_COMMAND_FAILED", "PSCAD rejected the single-project stop command.", self.name, "stop_project", {"project_name": project_name, "scope": "single-project"})
else:
    await self.adapter.call(project, "stop")
```

Poll the same postconditions used by the legacy backend. Report the fallback scope in error details; do not claim a 5.x live test.

- [ ] **Step 4: Run backend contract tests**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_backend_projects.py tests/test_backend_application.py -q`

Expected: all tests PASS.

- [ ] **Step 5: Commit modern run-control routing**

```powershell
git add pscad_mcp/core/backend/modern.py tests/test_backend_projects.py
git commit -m "feat: prefer scoped modern PSCAD stop"
```

### Task 5: Preserve the MCP contract and expose actionable diagnostics

**Files:**
- Modify: `pscad_mcp/core/service.py`
- Modify: `tests/test_service_contract.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md` if present
- Modify: `config.example.toml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Write failing service tests**

```python
async def test_status_includes_bounded_session_details(self):
    backend = FakeLifecycleBackend()
    backend.session_details = {"mode": "managed-launch", "managed_pid": 1234}
    service = PscadService(lambda: backend, executor=ImmediateExecutor())
    await service.attach_local()
    status = await service.status()
    self.assertEqual(status["session"]["managed_pid"], 1234)

async def test_pause_and_stop_are_serialized_by_mutation_lock(self):
    class SerialRunControlBackend(FakeLifecycleBackend):
        def __init__(self):
            super().__init__()
            self.active_calls = 0
            self.max_active = 0
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def _record(self):
            self.active_calls += 1
            self.max_active = max(self.max_active, self.active_calls)
            self.entered.set()
            await self.release.wait()
            self.active_calls -= 1

        async def pause_project(self, project_name):
            await self._record()

        async def stop_project(self, project_name):
            await self._record()

    backend = SerialRunControlBackend()
    service = PscadService(lambda: backend, executor=ImmediateExecutor())
    await service.attach_local()
    pause = asyncio.create_task(service.pause_simulation("case"))
    await backend.entered.wait()
    stop = asyncio.create_task(service.stop_simulation("case"))
    await asyncio.sleep(0)
    backend.release.set()
    self.assertEqual(
        await asyncio.gather(pause, stop),
        ["Simulation paused for 'case'.", "Simulation stopped for 'case'."],
    )
    self.assertEqual(backend.max_active, 1)
```

- [ ] **Step 2: Verify the service tests fail**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_service_contract.py -q`

Expected: FAIL because status does not include `session` and pause/stop do not acquire `_mutation_lock`.

- [ ] **Step 3: Add service behavior and error guidance**

Add `_ERROR_GUIDANCE` entries for `EXTERNAL_PSCAD_PRESENT`, `RUN_CONTROL_SCOPE_CONFLICT`, and `RUN_NOT_ACTIVE`. Add a JSON-safe copy of `backend.session_details` to status when present. Wrap both methods:

```python
async def pause_simulation(self, project_name: str) -> str:
    async with self._mutation_lock:
        await self.backend.pause_project(project_name)
        return f"Simulation paused for '{project_name}'."
```

Use the same pattern for stop.

- [ ] **Step 4: Document exact scope and unchanged component limitation**

Document these facts without changing any tool name or input schema:

- PSCAD 4.6.2 cannot attach to an ordinary already-open GUI; MCP starts a visible owned automation instance.
- The default rejects an existing PSCAD process; `PSCAD_MCP_LEGACY_EXISTING_POLICY=allow` explicitly permits a parallel owned instance.
- Legacy pause/stop are sent only when the target is the sole active case and the resulting state is verified.
- Modern stop prefers `stop_single_project`; modern pause remains globally scoped and is guarded.
- Component disable remains unsupported/reliability-limited in 4.6.2 and is unchanged in this release.

- [ ] **Step 5: Verify service tests and the 60-tool inventory**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_service_contract.py tests/test_tool_inventory.py -q`

Expected: all tests PASS and the inventory remains exactly 60 tools.

- [ ] **Step 6: Commit service and documentation changes**

```powershell
git add pscad_mcp/core/service.py tests/test_service_contract.py README.md config.example.toml CHANGELOG.md
if (Test-Path README.zh-CN.md) { git add README.zh-CN.md }
git commit -m "docs: explain managed PSCAD command control"
```

### Task 6: Run repository-level verification

**Files:**
- Verify only; fix any regression in the smallest owning file and add a regression test before continuing.

- [ ] **Step 1: Run the complete unit suite**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q`

Expected: all unit tests PASS; only environment-gated live acceptance tests are skipped.

- [ ] **Step 2: Run syntax, dependency, and diff checks**

```powershell
D:\pscad-mcp\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
D:\pscad-mcp\.venv\Scripts\python.exe -m pip check
git diff --check
```

Expected: each command exits 0 and `pip check` reports no broken requirements.

- [ ] **Step 3: Build and reinstall the package with the project interpreter**

Run: `$env:PSCAD_MCP_PYTHON='D:\pscad-mcp\.venv\Scripts\python.exe'; powershell -ExecutionPolicy Bypass -File scripts\verify_package.ps1`

Expected: wheel build/install succeeds and the installed package reports version `0.2.0` with 60 tools.

- [ ] **Step 4: Commit any verification-only regression fix**

If no fix was needed, do not create an empty commit. If a fix was needed, stage only its owning code and regression test and use a concrete message naming that regression, for example `fix: preserve legacy run-status callback pumping`.

### Task 7: Register Codex and run one real PSCAD 4.6.2 smoke test

**Files:**
- Modify: `C:\Users\335\.codex\config.toml`
- Create during test: timestamped copy under `D:\PSCAD-Workspace\acceptance`
- Create: `artifacts\live-smoke\<timestamp>\smoke-result.json`

- [ ] **Step 1: Prove no pre-existing PSCAD process is in scope**

Run: `Get-Process | Where-Object { $_.ProcessName -like '*PSCAD*' } | Select-Object Id,ProcessName,Path`

Expected: no rows. If rows exist, stop and report `EXTERNAL_PSCAD_PRESENT`; do not terminate them.

- [ ] **Step 2: Back up and patch the Codex TOML registration**

Create a timestamped sibling backup of `C:\Users\335\.codex\config.toml`, then use a bounded text patch to add exactly:

```toml
[mcp_servers.pscad]
type = "stdio"
command = 'D:\pscad-mcp\.venv\Scripts\python.exe'
args = ["-m", "pscad_mcp.main"]
tools = ["*"]
startup_timeout_sec = 120
tool_timeout_sec = 600

[mcp_servers.pscad.env]
PSCAD_MCP_BACKEND = "legacy"
PSCAD_MCP_VERSION = "4.6.2"
PSCAD_MCP_X64 = "true"
PSCAD_MCP_LAUNCH_TIMEOUT = "30"
PSCAD_MCP_WORKSPACE = 'D:\PSCAD-Workspace'
PSCAD_MCP_ALLOW_UNSCOPED_PATHS = "false"
PSCAD_MCP_LEGACY_MINIMIZE = "false"
PSCAD_MCP_LEGACY_EXISTING_POLICY = "reject"
```

- [ ] **Step 3: Validate registration without relying on the current task's cached MCP list**

Run: `D:\pscad-mcp\.venv\Scripts\python.exe -c "import tomllib,pathlib; d=tomllib.loads(pathlib.Path(r'C:\Users\335\.codex\config.toml').read_text(encoding='utf-8')); s=d['mcp_servers']['pscad']; assert s['command'].endswith(r'pscad-mcp\.venv\Scripts\python.exe'); print(s['env'])"`

Run: `codex mcp list`

Expected: TOML parse exits 0 and `pscad` is listed. A new Codex task/restart is still required before the app injects the newly registered tools into a task.

- [ ] **Step 4: Prepare a disposable acceptance project**

Run: `powershell -ExecutionPolicy Bypass -File scripts\prepare_acceptance_workspace.ps1`

Expected: a timestamped project path under `D:\PSCAD-Workspace\acceptance`; never operate on the public example original.

- [ ] **Step 5: Run the MCP stdio smoke sequence**

Use `mcp.client.stdio.stdio_client` and `ClientSession` with the same command/env as the registration. Record every call result and error as JSON. Required order:

1. initialize and `list_tools` -> exactly 60 tools;
2. `get_local_pscad` -> legacy 4.6.2 x64 managed launch;
3. `get_pscad_status` -> connected, alive, licensed, owns_process, managed PID;
4. `load_projects` on the timestamped copy and `list_projects` -> target case present;
5. `run_simulation`, poll `get_run_status` until starting/building/running;
6. `pause_simulation`, verify status `paused`;
7. resume by `run_simulation`, verify active again;
8. `stop_simulation`, verify stopped/idle/completed;
9. `quit_pscad` with `confirm=true`.

Expected: every call returns success and the JSON artifact contains the observed state sequence. If the project completes before pause, lengthen only the disposable project's duration through the supported settings tool and rerun once.

- [ ] **Step 6: Prove cleanup and inspect the artifact**

Run: `Get-Process | Where-Object { $_.ProcessName -like '*PSCAD*' } | Select-Object Id,ProcessName,Path`

Expected: no rows. Inspect the JSON and require `tool_count=60`, `backend=legacy`, `version=4.6.2`, `x64=true`, pause state `paused`, terminal stop state, and `remaining_pscad_processes=0`.

- [ ] **Step 7: Final repository check**

Run: `git status --short; git log --oneline -8`

Expected: no unintended files or modifications; live smoke artifacts may remain untracked only if the repository's established artifact policy permits them. Report the exact commits, Codex restart requirement, real status sequence, and the still-unsupported ordinary-GUI attach boundary.
