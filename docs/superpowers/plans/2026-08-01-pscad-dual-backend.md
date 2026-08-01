# PSCAD 4.6.2 / 5.x Dual-Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all 53 registered MCP tools use one stable service contract backed by `mhrc.automation` for PSCAD 4.6.2 and `mhi.pscad` for PSCAD 5.x.

**Architecture:** Keep FastMCP registration and public tool names stable. Route every PSCAD operation through `PscadService`, which owns safety and normalization, then through a selected `LegacyBackend` or `ModernBackend`; both backends execute COM calls on the existing serialized worker. Result-file parsing remains a dedicated adapter because it does not require a live PSCAD process.

**Tech Stack:** Python 3.12, FastMCP 1.29, `unittest`, `mhrc.automation` 1.2.4, `mhi.pscad` 3.1.x, `mhi.psout` 1.3.x, pywin32, PSCAD 4.6.2 x64.

---

## File map

- Create `pscad_mcp/core/backend/base.py`: shared dataclasses, backend error types, and runtime-checkable backend protocols.
- Create `pscad_mcp/core/backend/selector.py`: parse backend configuration, discover installed versions, and choose legacy or modern without silent fallback.
- Create `pscad_mcp/core/backend/legacy.py`: PSCAD 4.6.2 implementation using `mhrc.automation`.
- Create `pscad_mcp/core/backend/modern.py`: PSCAD 5.x implementation using `mhi.pscad` and the corrected current API shapes.
- Create `pscad_mcp/core/service.py`: stable operation facade, lookup helpers, JSON normalization, path checks, and destructive-action confirmation.
- Modify `pscad_mcp/core/connection_manager.py`: own one service/backend lifecycle instead of exposing raw PSCAD proxies.
- Modify every module under `pscad_mcp/tools/`: validate MCP parameters and call the service only.
- Create `tests/backend_fakes.py`: stateful in-memory legacy and modern API doubles.
- Create `tests/test_backend_selector.py`, `tests/test_backend_contract.py`, `tests/test_service_contract.py`, `tests/test_tool_backend_matrix.py`, and `tests/test_legacy_acceptance.py`.
- Modify `README.md` and create `docs/zh-CN/README.md`: install, configure, secure, and accept both backends in English and Chinese.

## Compatibility groups

The matrix test must contain these exact 53 names:

```python
EXPECTED_TOOLS = {
    "get_local_pscad", "get_pscad_status", "sync_documentation",
    "list_documentation", "read_documentation", "repair_connection",
    "quit_pscad", "load_projects", "list_projects", "run_project",
    "get_run_status", "find_components", "get_component_parameters",
    "set_component_parameters", "validate_component_parameters",
    "pause_simulation", "stop_simulation", "get_project_settings",
    "set_project_settings", "get_project_output", "read_output_file",
    "list_simulation_sets", "run_simulation_set", "add_task_to_set",
    "create_case", "create_library", "save_project", "save_project_as",
    "build_project", "build_all_projects", "get_project_definitions",
    "add_component", "create_component", "create_wire", "create_bus",
    "create_connection", "connect_ports", "create_annotation",
    "create_graph_frame", "create_control_frame", "list_canvas_components",
    "find_empty_space", "delete_components", "get_component_location",
    "set_component_location", "rotate_component", "mirror_component",
    "clone_component", "get_component_ports", "get_component_port",
    "enable_component", "disable_component", "delete_component",
}
```

### Task 1: Freeze public contracts and normalized data types

**Files:**
- Create: `pscad_mcp/core/backend/__init__.py`
- Create: `pscad_mcp/core/backend/base.py`
- Create: `tests/test_backend_contract.py`

- [ ] **Step 1: Write failing protocol and serialization tests**

Create tests that import `BackendInfo`, `ProjectInfo`, `ComponentInfo`, `PortInfo`, `RunState`, `BackendError`, and `PscadBackend`, serialize every dataclass with `dataclasses.asdict()`, and assert a deliberately incomplete class is not an instance of the runtime-checkable protocol.

```python
def test_backend_info_is_json_compatible(self):
    value = BackendInfo("legacy", "4.6.2", True, True, False, True, True)
    self.assertEqual(json.loads(json.dumps(asdict(value)))["version"], "4.6.2")

def test_backend_error_has_stable_payload(self):
    error = BackendError("NOT_FOUND", "missing", "legacy", "project", {"name": "x"})
    self.assertEqual(error.to_dict()["code"], "NOT_FOUND")
```

- [ ] **Step 2: Run and observe RED**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_contract -v`

Expected: import failure because `pscad_mcp.core.backend.base` does not exist.

- [ ] **Step 3: Implement immutable normalized records and focused protocols**

Define frozen dataclasses with the fields from the design, `BackendError(Exception).to_dict()`, plus `ApplicationBackend`, `ProjectBackend`, `SimulationSetBackend`, `ComponentBackend`, `CanvasBackend`, `ResultBackend`, and aggregate `PscadBackend`. All public protocol methods are async and return dataclasses, primitives, lists, or dictionaries only.

```python
@dataclass(frozen=True)
class BackendInfo:
    backend: str
    version: str | None
    x64: bool | None
    alive: bool
    busy: bool
    licensed: bool | None
    owns_process: bool

class BackendError(RuntimeError):
    def __init__(self, code, message, backend, operation, details=None):
        super().__init__(message)
        self.code, self.backend, self.operation = code, backend, operation
        self.details = details or {}

    def to_dict(self):
        return {"code": self.code, "message": str(self), "backend": self.backend,
                "operation": self.operation, "details": self.details}
```

- [ ] **Step 4: Run focused tests and compile the package**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_contract -v`

Run: `& '.\.venv\Scripts\python.exe' -m compileall pscad_mcp\core\backend`

Expected: all focused tests pass and compilation exits 0.

### Task 2: Select legacy or modern deterministically

**Files:**
- Create: `pscad_mcp/core/backend/selector.py`
- Modify: `pscad_mcp/core/pscad_config.py`
- Create: `tests/test_backend_selector.py`

- [ ] **Step 1: Write failing selection tests**

Cover `auto`, explicit `legacy`, explicit `modern`, explicit 4.6.x and 5.x, invalid backend text, missing requested version, and x64 preference. Inject discovery functions so tests do not launch PSCAD.

```python
def test_462_selects_legacy(self):
    choice = select_backend({"PSCAD_MCP_VERSION": "4.6.2"},
                            legacy_versions=lambda: [("4.6.2", True)],
                            modern_versions=lambda: [])
    self.assertEqual(choice, BackendChoice("legacy", "4.6.2", True))

def test_explicit_backend_never_silently_falls_back(self):
    with self.assertRaisesRegex(BackendSelectionError, "modern"):
        select_backend({"PSCAD_MCP_BACKEND": "modern"},
                       legacy_versions=lambda: [("4.6.2", True)],
                       modern_versions=lambda: [])
```

- [ ] **Step 2: Run and observe RED**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_selector -v`

Expected: import failure for the selector module.

- [ ] **Step 3: Implement configuration and discovery normalization**

Extend `PscadLaunchConfig` with `backend: Literal["auto", "legacy", "modern"]` and `legacy_wheel: str | None`. Normalize legacy display strings such as `PSCAD 4.6.2 (x64)` to `(version, x64)` and ensure modern candidates are restricted to major version 5 or later.

- [ ] **Step 4: Pass selector and existing configuration tests**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_selector tests.test_pscad_config -v`

Expected: all tests pass.

### Task 3: Implement application lifecycle for both backends

**Files:**
- Create: `pscad_mcp/core/backend/legacy.py`
- Create: `pscad_mcp/core/backend/modern.py`
- Create: `tests/backend_fakes.py`
- Create: `tests/test_backend_application.py`
- Modify: `pscad_mcp/core/executor.py`

- [ ] **Step 1: Write failing lifecycle tests against both backend factories**

Use two stateful fakes and run the same assertions for each factory: attach reports normalized metadata, heartbeat changes after close, disconnect does not quit, `quit(confirm=True)` closes the currently connected instance, and timeout recovery creates a new COM worker. Ownership remains metadata used by acceptance cleanup; it is not a substitute for explicit user confirmation.

```python
for factory in backend_factories():
    with self.subTest(factory=factory.name):
        backend = factory.create()
        info = await backend.attach()
        self.assertTrue(info.alive)
        self.assertIn(info.backend, {"legacy", "modern"})
        await backend.disconnect()
        self.assertFalse(factory.app.quit_called)
```

- [ ] **Step 2: Run and observe RED**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_application -v`

Expected: both concrete backend imports fail.

- [ ] **Step 3: Implement legacy lifecycle**

Inject the automation module. Discover with `settings.PSCAD_VERSIONS`, launch with `launch_pscad(pscad_version="PSCAD {version} (x64|x86)", silence=True, minimize=True, certificate=False)`, and normalize `is_alive()`, `is_busy()`, and `licensed()`. Missing `mhrc.automation` raises `BackendError("DEPENDENCY_MISSING", ...)` with the configured wheel hint.

- [ ] **Step 4: Implement modern lifecycle**

Reuse the corrected `mhi.pscad` connect/launch behavior, but reject versions below 5.0 before launch. Ensure all calls pass through `RobustExecutor` and no raw proxy crosses the backend boundary.

- [ ] **Step 5: Run lifecycle, COM, and recovery tests**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_application tests.test_executor_com tests.test_executor_recovery tests.test_concurrency -v`

Expected: all tests pass.

### Task 4: Add the service boundary and migrate application tools

**Files:**
- Create: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/core/connection_manager.py`
- Modify: `pscad_mcp/tools/app_tools.py`
- Create: `tests/test_service_contract.py`
- Modify: `tests/test_connection_metadata.py`

- [ ] **Step 1: Write failing service tests**

Assert lazy backend selection, stable error dictionaries, JSON-safe status, dependency guidance, repair by resetting the executor and reconnecting, and confirmation for quitting an owned process.

```python
async def test_quit_requires_confirmation(self):
    with self.assertRaisesRegex(ConfirmationRequired, "confirm=true"):
        await self.service.quit_pscad(confirm=False)
```

- [ ] **Step 2: Run and observe RED**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_service_contract -v`

Expected: import failure for `PscadService`.

- [ ] **Step 3: Implement service lifecycle and manager delegation**

`PscadService` receives a backend factory and `PathPolicy`; `ConnectionManager` owns one service and exposes service operations. Keep the existing raw `pscad` property temporarily functional only for tool groups that have not yet migrated; remove it in Task 8 after the source scan proves no tool uses it.

- [ ] **Step 4: Route seven application/documentation tools**

Migrate `get_local_pscad`, `get_pscad_status`, `repair_connection`, and `quit_pscad`; documentation tools remain local but use `PathPolicy.resolve_child()`. Add `confirm: bool = False` to `quit_pscad`.

- [ ] **Step 5: Pass focused and protocol tests**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_service_contract tests.test_connection_metadata tests.test_tools tests.test_protocol -v`

Expected: all tests pass.

### Task 5: Implement project, settings, simulation-set, and result contracts

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/tools/project_tools.py`
- Modify: `pscad_mcp/tools/creation_tools.py`
- Modify: `pscad_mcp/tools/simset_tools.py`
- Modify: `pscad_mcp/tools/data_tools.py`
- Create: `tests/test_backend_projects.py`
- Create: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write paired failing contract tests**

Run identical behavior checks for both fake backends over these 20 operations: load/list/run/status/pause/stop projects; get/set settings; create case/library; save/save-as/build/build-all/definitions; list/run/add-task simulation sets; project output and `.psout` reading. Require normalized output and matching errors.

- [ ] **Step 2: Run and observe RED**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_projects -v`

Expected: failures for unimplemented backend methods.

- [ ] **Step 3: Implement legacy mappings**

Use application/workspace/project/simset APIs discovered in `mhrc.automation`; re-query by name after create/load, and verify postconditions after save-as and add-task. Never return XML, COM, or proxy objects.

- [ ] **Step 4: Implement modern mappings**

Use `PSCAD.settings()`, `PSCAD.simulation_sets()`, `PSCAD.simulation_set()`, string-returning `Project.definitions()`, and `mhi.psout.File`. Keep `max_samples` bounded to `1..1_000_000`.

- [ ] **Step 5: Route the corresponding tool modules through `PscadService`**

Remove direct calls to `pscad_manager.pscad`, `.project()`, `.canvas()`, and adapter proxies from the four modules. Add `confirm` to overwrite save operations and validate every create/load/save/output path through the workspace policy.

- [ ] **Step 6: Run focused plus existing regression tests**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_projects tests.test_creation_tools tests.test_enhanced_tools tests.test_psout_reader tests.test_path_safety -v`

Expected: all tests pass.

### Task 6: Implement component read/write/transform contracts

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/tools/component_tools.py`
- Modify: `pscad_mcp/tools/project_tools.py`
- Create: `tests/test_backend_components.py`

- [ ] **Step 1: Write paired failing tests for 14 component tool behaviors**

Cover find, get/set/validate parameters, get/set location, rotate, horizontal/vertical mirror, clone, list/get ports, enable, disable, single delete, and batch delete. Each mutation asserts a postcondition, not only a method call.

```python
clone = await backend.clone_component("case", 7, (12, 18))
self.assertNotEqual(clone.id, 7)
self.assertEqual(clone.location, (12, 18))
self.assertEqual(clone.definition, source.definition)
```

- [ ] **Step 2: Run and observe RED**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_components -v`

Expected: unimplemented-operation failures for both backend families.

- [ ] **Step 3: Implement direct mappings and normalization**

Modern uses `defn_name`; legacy uses project component lookup, parameter dictionaries, location, delete, and `get_port_location()`. Normalize IDs to integers and locations to `{x, y}`.

- [ ] **Step 4: Implement verified legacy command bridges**

Load command identifiers from the installed legacy package resources instead of hard-coding undocumented numbers in tools. Rotation/mirror must re-read orientation/location; clone must compare pre/post component ID sets; enable/disable must re-read the parameter or layer state. If a postcondition cannot be verified, raise `BackendError("POSTCONDITION_FAILED", ...)`.

- [ ] **Step 5: Add destructive confirmation and route tools**

`delete_component` and `delete_components` require `confirm=true`; batch deletion validates and captures all target IDs before the first mutation.

- [ ] **Step 6: Run component and protocol tests**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_components tests.test_component_tools tests.test_canvas_tools tests.test_protocol -v`

Expected: all tests pass.

### Task 7: Implement all Canvas creation and connection contracts

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/tools/canvas_tools.py`
- Create: `tests/test_backend_canvas.py`

- [ ] **Step 1: Write paired failing tests for 12 Canvas behaviors**

Cover add/create component, wire, bus, connection, connect ports, annotation, graph frame, control frame, list components, find empty space, and batch delete. Use a stateful geometry fake so created objects change subsequent list/space results.

- [ ] **Step 2: Run and observe RED**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_canvas -v`

Expected: failures for missing Canvas implementations.

- [ ] **Step 3: Implement modern Canvas mappings**

Call methods only on a `UserCanvas`, normalize returned proxy values immediately, and validate coordinates, positive frame dimensions, non-empty points, and port compatibility before mutation.

- [ ] **Step 4: Implement legacy direct mappings and command bridge**

Use direct `add_component` and `add_wire` where available. For bus, connection, annotation, graph frame, and control frame, encapsulate command/mouse sequences in private legacy helpers; snapshot component/wire state before the command and confirm exactly the requested object appears afterward.

- [ ] **Step 5: Implement deterministic empty-space search**

Build occupied rectangles from component locations/bounds, search the requested grid row-major inside a bounded canvas region, and re-check the winning rectangle immediately before a following create operation.

- [ ] **Step 6: Route Canvas tools and pass tests**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_backend_canvas tests.test_canvas_tools tests.test_tool_backend_matrix -v`

Expected: all tests pass and no tool module imports either vendor automation package.

### Task 8: Enforce the 53-tool parity and safety matrix

**Files:**
- Modify: `tests/test_tool_backend_matrix.py`
- Create: `tests/test_safety_contract.py`
- Modify: `pscad_mcp/core/path_policy.py`

- [ ] **Step 1: Write failing exhaustive matrix tests**

Assert the registered set equals `EXPECTED_TOOLS`, every tool can run against both stateful backend fakes, output passes `json.dumps`, errors contain the five stable fields, and no source under `pscad_mcp/tools` contains `mhi.pscad`, `mhrc.automation`, or `.pscad` proxy access. At this point remove the temporary raw `ConnectionManager.pscad` compatibility property.

- [ ] **Step 2: Write path and confirmation attack tests**

Cover absolute paths outside the workspace, `..`, symlink/junction escape, case-insensitive Windows paths, unsupported suffixes, overwrite without confirmation, delete without confirmation, quit without confirmation, and batch mutation with a missing ID.

- [ ] **Step 3: Run and observe RED**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_tool_backend_matrix tests.test_safety_contract -v`

Expected: failures identify every remaining direct proxy call or missing safety gate.

- [ ] **Step 4: Make the minimum routing and policy corrections**

Resolve paths before and after creation, compare with `os.path.commonpath()` on normalized Windows paths, reject reparse-point escapes, use an explicit suffix allow-list per operation, and centralize confirmation in the service.

- [ ] **Step 5: Pass the full fake-backend suite**

Run: `& '.\.venv\Scripts\python.exe' -m unittest discover tests -v`

Expected: all unit and contract tests pass; real acceptance remains skipped by default.

### Task 9: Run bounded real PSCAD 4.6.2 acceptance

**Files:**
- Create: `tests/test_legacy_acceptance.py`
- Create: `scripts/prepare_acceptance_workspace.ps1`
- Create: `scripts/run_legacy_acceptance.ps1`

- [ ] **Step 1: Write opt-in read-only acceptance tests**

Gate with `PSCAD_MCP_ACCEPTANCE=1`. Attach 4.6.2 x64, verify licensed/alive, list projects, inspect master definitions, list components, read settings, then quit only the owned process.

- [ ] **Step 2: Confirm default runs skip real PSCAD**

Run: `& '.\.venv\Scripts\python.exe' -m unittest tests.test_legacy_acceptance -v`

Expected: skipped tests and no new PSCAD process.

- [ ] **Step 3: Prepare reversible example copies**

The PowerShell script accepts explicit `-Source` and `-Destination`, validates that source is under `C:\Users\Public\Documents\PSCAD\4.6\Examples` and destination is under `D:\PSCAD-Workspace\acceptance`, creates a timestamped destination, and uses `Copy-Item` without deleting or overwriting prior runs.

- [ ] **Step 4: Add mutation, build, simulation, and output acceptance groups**

Each group opens its own copied project. Mutations assert their postconditions and save only inside that copy. Build/simulation uses a small bundled example, enforces a finite timeout, and reads the produced output with the same result adapter.

- [ ] **Step 5: Run the real acceptance command**

Run: `& '.\scripts\run_legacy_acceptance.ps1' -Workspace 'D:\PSCAD-Workspace\acceptance' -Version '4.6.2' -X64`

Expected: read-only, mutation, build, simulation, and result groups report PASS; the script prints the exact copied workspace and launched PID.

- [ ] **Step 6: Verify process cleanup without broad termination**

Inspect only the PID recorded by the script and its executable path. If cleanup fails, report it and leave unrelated PSCAD instances untouched.

### Task 10: Chinese/English documentation and final verification

**Files:**
- Modify: `README.md`
- Create: `docs/zh-CN/README.md`
- Modify: `pyproject.toml`

- [ ] **Step 1: Document both installations and honest support boundaries**

Explain D-drive venv setup, legal installation of the legacy wheel, all five environment variables, workspace safety, confirmation flags, Codex MCP configuration, troubleshooting, the 53-tool groups, and the exact acceptance commands. State that 5.x is contract-tested until a real 5.x installation is available.

- [ ] **Step 2: Run dependency and source checks**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pip check
& '.\.venv\Scripts\python.exe' -m compileall pscad_mcp
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 3: Run the complete test suite freshly**

Run: `& '.\.venv\Scripts\python.exe' -m unittest discover tests -v`

Expected: no failures; real PSCAD tests skip unless acceptance is enabled.

- [ ] **Step 4: Verify exact MCP registration**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -c "from pscad_mcp.main import create_server; tools=create_server()._tool_manager.list_tools(); print(len(tools)); print(len({t.name for t in tools}))"
```

Expected: `53` and `53`.

- [ ] **Step 5: Re-run real legacy acceptance and inspect cleanup**

Run the Task 9 acceptance script on a fresh copied workspace, verify all five groups, then confirm the recorded test PID no longer exists.

- [ ] **Step 6: Inspect scope and report remaining environmental boundary**

Run: `git status --short --branch`

Report modified/untracked files, the Git identity blocker if still present, PSCAD 4.6.2 real results, and the lack of real PSCAD 5.x evidence. Do not claim 5.x end-to-end success without installing and running it.
