# PSCAD 4.6.2 Simulation Set Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a verified 60-tool simulation-set workflow for PSCAD 4.6.2, preserve existing callers, complete both backend contracts, run real acceptance, and register the MCP server in Codex.

**Architecture:** Keep MCP tools thin and route all operations through `PscadService` and the normalized `PscadBackend` protocol. Implement vendor-specific simulation-set behavior in `LegacyBackend` and `ModernBackend`, require read-back postconditions for every mutation, and contain multi-field rollback inside each backend.

**Tech Stack:** Python 3.10+, FastMCP 1.x, `mhrc.automation` 1.2.4, `mhi.pscad` 3.1.x, `unittest`, PowerShell, TOML configuration.

---

## File Map

- `pscad_mcp/core/backend/base.py`: JSON-safe simulation-set records and the expanded backend protocol.
- `pscad_mcp/core/backend/legacy.py`: PSCAD 4.6.2 workspace, set, and task operations with XML response and postcondition checks.
- `pscad_mcp/core/backend/modern.py`: modern API mapping and capability handling for fields unavailable through `mhi.pscad`.
- `pscad_mcp/core/service.py`: names, confirmation, task parameter allowlist, compatibility behavior, and JSON normalization.
- `pscad_mcp/tools/simset_tools.py`: seven new thin MCP entry points and registration.
- `tests/test_backend_contract.py`: normalized record serialization.
- `tests/test_backend_projects.py`: cross-backend simulation-set CRUD, task, postcondition, and rollback behavior.
- `tests/test_service_contract.py`: service validation, confirmation, and normalized results.
- `tests/test_enhanced_tools.py`: tool-to-service routing.
- `tests/test_tool_backend_matrix.py`: exact 60-tool and complete-protocol contract.
- `tests/test_legacy_reliability_acceptance.py`: opt-in real PSCAD 4.6.2 workflow and cleanup.
- `scripts/run_legacy_acceptance.ps1`: acceptance input preparation and suite execution.
- `README.md`: English tool coverage and configuration.
- `docs/zh-CN/README.md`: Chinese tool coverage, limits, and acceptance instructions.
- `C:/Users/335/.codex/config.toml`: local Codex registration after repository verification; never commit this file.

## Task 1: Add Normalized Simulation-Set Records

**Files:**
- Modify: `pscad_mcp/core/backend/base.py`
- Test: `tests/test_backend_contract.py`

- [ ] **Step 1: Write the failing record serialization test**

Add imports and records to `test_normalized_records_are_json_compatible`:

```python
from pscad_mcp.core.backend.base import SimulationSetInfo, SimulationTaskInfo

records = [
    BackendInfo("legacy", "4.6.2", True, True, False, True, True),
    ProjectInfo("case", "Case", "Example"),
    ComponentInfo(7, "R1", "master:resistor", {"x": 10, "y": 20}),
    PortInfo("A", 10, 20, 1, "electrical"),
    RunState("running", 25.0),
    SimulationSetInfo("Batch1", None, ("CaseA", "CaseB")),
    SimulationTaskInfo("CaseA", "CaseA", "", 1, 1),
]
```

Assert the new records remain JSON compatible:

```python
self.assertEqual(payload[5]["tasks"], ["CaseA", "CaseB"])
self.assertEqual(payload[6]["volley"], 1)
```

- [ ] **Step 2: Run the test and verify the red state**

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_contract -v
```

Expected: import failure because `SimulationSetInfo` and `SimulationTaskInfo` do not exist.

- [ ] **Step 3: Add immutable normalized records**

Add after `RunState` in `base.py`:

```python
@dataclass(frozen=True)
class SimulationSetInfo:
    name: str
    depends_on: str | None
    tasks: tuple[str, ...]


@dataclass(frozen=True)
class SimulationTaskInfo:
    name: str
    namespace: str | None
    controlgroup: str | None
    volley: int | None
    affinity: int | None
```

Tuples prevent backend callers from mutating the record after validation and serialize as JSON arrays through `asdict` plus `json.dumps`.

- [ ] **Step 4: Run the focused test**

Run the command from Step 2.

Expected: `test_normalized_records_are_json_compatible ... ok` and the module passes.

- [ ] **Step 5: Commit the records**

```powershell
git add pscad_mcp/core/backend/base.py tests/test_backend_contract.py
git commit -m "feat: add simulation set backend records"
```

## Task 2: Implement Legacy Simulation-Set CRUD and Task Reads

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py`
- Test: `tests/test_backend_projects.py`

- [ ] **Step 1: Extend the legacy fakes with real response shapes**

Replace the simple fake set with a stateful fake that returns XML success responses and task proxies:

```python
class FakeSimulationTask:
    def __init__(self, name):
        self.name = name
        self.values = {
            "namespace": name,
            "controlgroup": "",
            "volley": 1,
            "affinity": 1,
        }

    def namespace(self): return self.values["namespace"]
    def controlgroup(self, value=None):
        if value is not None: self.values["controlgroup"] = value
        return self.values["controlgroup"]
    def volley(self, value=None):
        if value is not None: self.values["volley"] = value
        return self.values["volley"]
    def affinity(self, value=None):
        if value is not None: self.values["affinity"] = value
        return self.values["affinity"]


def xml_response(success=True):
    return ET.Element(
        "commandresponse", {"success": "true" if success else "false"}
    )


class FakeSimulationSet:
    def __init__(self, name="set1"):
        self.set_name = name
        self.tasks = {}
        self.ran = False

    def name(self): return self.set_name
    def depends_on(self): return "None"
    def list_tasks(self): return list(self.tasks)
    def task(self, name): return self.tasks[name]
    def add_tasks(self, *names):
        for name in names: self.tasks[name] = FakeSimulationTask(name)
        return xml_response(success=True)
    def remove_tasks(self, *names):
        for name in names: self.tasks.pop(name, None)
        return xml_response(success=True)
```

Add workspace methods:

```python
def create_simulation_set(self, name):
    self.app.simsets[name] = FakeSimulationSet(name)
    return xml_response(success=True)

def remove_simulation_set(self, name):
    self.app.simsets.pop(name, None)
    return xml_response(success=True)

def simulation_set(self, name):
    return self.app.simsets[name]
```

- [ ] **Step 2: Write failing legacy CRUD and read tests**

Add tests for the exact normalized behavior:

```python
async def test_legacy_simulation_set_crud_and_task_reads(self):
    backend, app = (await self.make_backends())[0]

    created = await backend.create_simulation_set("Batch1")
    self.assertEqual(created, SimulationSetInfo("Batch1", None, ()))

    await backend.add_task_to_set("ignored", "Batch1", "case")
    self.assertEqual(
        await backend.list_simulation_set_tasks("Batch1"),
        ["case"],
    )
    self.assertEqual(
        await backend.get_simulation_task_parameters("Batch1", "case"),
        SimulationTaskInfo("case", "case", "", 1, 1),
    )

    details = await backend.get_simulation_set_details("Batch1")
    self.assertEqual(details.tasks, ("case",))

    await backend.remove_tasks_from_set("Batch1", ["case"])
    await backend.remove_simulation_set("Batch1")
    self.assertNotIn("Batch1", app.simsets)
```

Add four table-driven subtests for `create_simulation_set`,
`remove_simulation_set`, `add_task_to_set`, and `remove_tasks_from_set`.
Configure each fake command to return `xml_response(False)` and assert
`PSCAD_COMMAND_FAILED`. Configure each fake to return success without changing
`app.simsets` or `simset.tasks` and assert `POSTCONDITION_FAILED`.

- [ ] **Step 3: Run the focused tests and verify they fail**

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_projects.TestBackendProjectContracts -v
```

Expected: failures because the six new legacy backend methods do not exist and existing add-task does not verify its response.

- [ ] **Step 4: Add focused legacy helpers and methods**

Add a workspace helper and normalized reads near the existing simulation-set methods:

```python
async def _workspace(self) -> Any:
    return await self.executor.run_safe(self._require_app().workspace)

async def _legacy_simulation_set(self, set_name: str) -> Any:
    names = await self.list_simulation_sets("")
    if set_name not in names:
        raise BackendError(
            "NOT_FOUND", f"Simulation set '{set_name}' was not found.",
            self.name, "simulation_set", {"sim_set_name": set_name},
        )
    workspace = await self._workspace()
    method = getattr(workspace, "simulation_set", None)
    if method is None:
        method = self._require_app().simulation_set
    return await self.executor.run_safe(method, set_name)
```

Implement CRUD using `legacy_support.require_success` and fresh listings:

```python
async def create_simulation_set(self, set_name: str) -> SimulationSetInfo:
    if set_name in await self.list_simulation_sets(""):
        raise BackendError("ALREADY_EXISTS", "Simulation set already exists.",
                           self.name, "create_simulation_set",
                           {"sim_set_name": set_name})
    workspace = await self._workspace()
    response = await self.executor.run_safe(workspace.create_simulation_set, set_name)
    legacy_support.require_success(response, "create_simulation_set",
                                   {"sim_set_name": set_name})
    if set_name not in await self.list_simulation_sets(""):
        raise BackendError("POSTCONDITION_FAILED", "Created set was not found.",
                           self.name, "create_simulation_set",
                           {"sim_set_name": set_name})
    return await self.get_simulation_set_details(set_name)
```

Implement removal with a fresh absence check:

```python
async def remove_simulation_set(self, set_name: str) -> None:
    if set_name not in await self.list_simulation_sets(""):
        raise BackendError("NOT_FOUND", "Simulation set was not found.",
                           self.name, "remove_simulation_set",
                           {"sim_set_name": set_name})
    workspace = await self._workspace()
    response = await self.executor.run_safe(workspace.remove_simulation_set, set_name)
    legacy_support.require_success(response, "remove_simulation_set",
                                   {"sim_set_name": set_name})
    if set_name in await self.list_simulation_sets(""):
        raise BackendError("POSTCONDITION_FAILED", "Removed set is still present.",
                           self.name, "remove_simulation_set",
                           {"sim_set_name": set_name})
```

Implement add and batch removal with membership read-back:

```python
async def add_task_to_set(
    self, project_name: str, set_name: str, task_project_name: str
) -> None:
    simset = await self._legacy_simulation_set(set_name)
    response = await self.executor.run_safe(simset.add_tasks, task_project_name)
    legacy_support.require_success(response, "add_task_to_set", {
        "sim_set_name": set_name, "task_project_name": task_project_name,
    })
    if task_project_name not in await self.list_simulation_set_tasks(set_name):
        raise BackendError("POSTCONDITION_FAILED", "Added task was not found.",
                           self.name, "add_task_to_set",
                           {"sim_set_name": set_name,
                            "task_project_name": task_project_name})

async def remove_tasks_from_set(
    self, set_name: str, task_names: Sequence[str]
) -> None:
    simset = await self._legacy_simulation_set(set_name)
    before = await self.list_simulation_set_tasks(set_name)
    missing = [name for name in task_names if name not in before]
    if missing:
        raise BackendError("NOT_FOUND", "Simulation tasks were not found.",
                           self.name, "remove_tasks_from_set",
                           {"sim_set_name": set_name, "missing": missing})
    response = await self.executor.run_safe(simset.remove_tasks, *task_names)
    legacy_support.require_success(response, "remove_tasks_from_set", {
        "sim_set_name": set_name, "task_names": list(task_names),
    })
    remaining = set(await self.list_simulation_set_tasks(set_name))
    unexpected = [name for name in task_names if name in remaining]
    if unexpected:
        raise BackendError("POSTCONDITION_FAILED", "Removed tasks are still present.",
                           self.name, "remove_tasks_from_set",
                           {"sim_set_name": set_name, "remaining": unexpected})
```

Normalize details and task reads:

```python
async def get_simulation_set_details(self, set_name: str) -> SimulationSetInfo:
    simset = await self._legacy_simulation_set(set_name)
    tasks = tuple(await self.executor.run_safe(simset.list_tasks))
    dependency_method = getattr(simset, "depends_on", None)
    dependency = (
        await self.executor.run_safe(dependency_method)
        if dependency_method is not None else None
    )
    dependency = None if dependency in (None, "", "None") else str(dependency)
    return SimulationSetInfo(set_name, dependency, tuple(map(str, tasks)))
```

Read the normalized task record explicitly:

```python
async def get_simulation_task_parameters(
    self, set_name: str, task_name: str
) -> SimulationTaskInfo:
    simset = await self._legacy_simulation_set(set_name)
    if task_name not in await self.list_simulation_set_tasks(set_name):
        raise BackendError("NOT_FOUND", "Simulation task was not found.",
                           self.name, "get_simulation_task_parameters",
                           {"sim_set_name": set_name, "task_name": task_name})
    task = await self.executor.run_safe(simset.task, task_name)
    values = {}
    for key in ("namespace", "controlgroup", "volley", "affinity"):
        method = getattr(task, key, None)
        values[key] = (
            await self.executor.run_safe(method) if method is not None else None
        )
    return SimulationTaskInfo(
        task_name,
        None if values["namespace"] is None else str(values["namespace"]),
        None if values["controlgroup"] is None else str(values["controlgroup"]),
        None if values["volley"] is None else int(values["volley"]),
        None if values["affinity"] is None else int(values["affinity"]),
    )
```

- [ ] **Step 5: Run legacy project tests**

Run the command from Step 3.

Expected: all legacy simulation-set CRUD, response, postcondition, and read tests pass.

- [ ] **Step 6: Commit legacy CRUD and reads**

```powershell
git add pscad_mcp/core/backend/legacy.py tests/test_backend_projects.py
git commit -m "feat: add verified legacy simulation set lifecycle"
```

## Task 3: Implement Legacy Task Parameter Updates and Rollback

**Files:**
- Modify: `pscad_mcp/core/backend/legacy.py`
- Test: `tests/test_backend_projects.py`

- [ ] **Step 1: Add fake task failure controls**

Extend `FakeSimulationTask` so tests can fail a named field and optionally fail restoration:

```python
self.fail_on = set()
self.fail_restore_on = set()
self.original = dict(self.values)

def _set(self, key, value):
    if key in self.fail_on or (
        value == self.original[key] and key in self.fail_restore_on
    ):
        raise RuntimeError(f"failed {key}")
    self.values[key] = value
```

Route `controlgroup`, `volley`, and `affinity` setters through `_set`.
Add this helper to `TestBackendProjectContracts` so every rollback test starts
from the same real backend construction path:

```python
async def legacy_with_task(self, set_name="Batch1", task_name="case"):
    backend, app = (await self.make_backends())[0]
    app.simsets[set_name] = FakeSimulationSet(set_name)
    app.simsets[set_name].tasks[task_name] = FakeSimulationTask(task_name)
    return backend, app
```

- [ ] **Step 2: Write red tests for success and both rollback outcomes**

```python
async def test_legacy_task_parameter_update_reads_back(self):
    backend, app = await self.legacy_with_task("Batch1", "case")
    result = await backend.set_simulation_task_parameters(
        "Batch1", "case", {"volley": 2, "affinity": 3}
    )
    self.assertEqual((result.volley, result.affinity), (2, 3))

async def test_legacy_task_parameter_failure_restores_original_values(self):
    backend, app = await self.legacy_with_task("Batch1", "case")
    task = app.simsets["Batch1"].tasks["case"]
    task.fail_on.add("affinity")
    with self.assertRaises(RuntimeError):
        await backend.set_simulation_task_parameters(
            "Batch1", "case", {"volley": 2, "affinity": 3}
        )
    self.assertEqual(task.values["volley"], 1)

async def test_legacy_task_parameter_failed_restore_is_partial_completion(self):
    backend, app = await self.legacy_with_task("Batch1", "case")
    task = app.simsets["Batch1"].tasks["case"]
    task.fail_on.add("affinity")
    task.fail_restore_on.add("volley")
    with self.assertRaises(BackendError) as raised:
        await backend.set_simulation_task_parameters(
            "Batch1", "case", {"volley": 2, "affinity": 3}
        )
    self.assertEqual(raised.exception.code, "PARTIAL_COMPLETION")
    self.assertEqual(raised.exception.details["observed"]["volley"], 2)
```

- [ ] **Step 3: Run the three tests and verify they fail**

Run each test by dotted name with `python -m unittest ... -v`.

Expected: failure because `set_simulation_task_parameters` does not exist.

- [ ] **Step 4: Implement deterministic update, read-back, and restore**

Use the public field order rather than caller dictionary order:

```python
_TASK_PARAMETER_ORDER = ("controlgroup", "volley", "affinity")

async def set_simulation_task_parameters(
    self, set_name: str, task_name: str, parameters: Mapping[str, Any]
) -> SimulationTaskInfo:
    original_record = await self.get_simulation_task_parameters(set_name, task_name)
    original = {key: getattr(original_record, key) for key in parameters}
    simset = await self._legacy_simulation_set(set_name)
    task = await self.executor.run_safe(simset.task, task_name)
    applied = []
    try:
        for key in self._TASK_PARAMETER_ORDER:
            if key not in parameters:
                continue
            method = getattr(task, key)
            await self.executor.run_safe(method, parameters[key])
            applied.append(key)
        observed = await self.get_simulation_task_parameters(set_name, task_name)
        mismatches = {
            key: getattr(observed, key)
            for key, expected in parameters.items()
            if getattr(observed, key) != expected
        }
        if mismatches:
            raise BackendError(
                "POSTCONDITION_FAILED", "Task parameter read-back differed.",
                self.name, "set_simulation_task_parameters",
                {"expected": dict(parameters), "observed": mismatches},
            )
        return observed
    except Exception as operation_error:
        restore_errors = {}
        for key in reversed(applied):
            try:
                await self.executor.run_safe(getattr(task, key), original[key])
            except Exception as restore_error:
                restore_errors[key] = type(restore_error).__name__
        final = await self.get_simulation_task_parameters(set_name, task_name)
        unrestored = {
            key: getattr(final, key)
            for key, value in original.items()
            if getattr(final, key) != value
        }
        if restore_errors or unrestored:
            raise BackendError(
                "PARTIAL_COMPLETION", "Task parameters could not be restored.",
                self.name, "set_simulation_task_parameters",
                {
                    "requested": dict(parameters), "original": original,
                    "observed": {key: getattr(final, key) for key in original},
                    "restore_errors": restore_errors,
                },
            ) from operation_error
        raise
```

Bound exception diagnostics with existing helpers before placing any text in `details`.

- [ ] **Step 5: Run the focused tests and full backend project module**

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_projects -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit rollback behavior**

```powershell
git add pscad_mcp/core/backend/legacy.py tests/test_backend_projects.py
git commit -m "feat: verify legacy simulation task parameters"
```

## Task 4: Implement Modern Backend Contract Parity

**Files:**
- Modify: `pscad_mcp/core/backend/modern.py`
- Test: `tests/test_backend_projects.py`

- [ ] **Step 1: Extend modern fakes for set and task APIs**

Add `create_simulation_set`, `remove_simulation_set`, `list_tasks`, `task`, and `parameters` methods that model the `mhi.pscad` API. Make `controlgroup` absent by default so capability behavior is tested rather than assumed.

```python
class FakeModernTask:
    def __init__(self, name):
        self.values = {"namespace": name, "volley": 1, "affinity": 1}

    def parameters(self, **updates):
        if updates:
            self.values.update(updates)
            return None
        return dict(self.values)
```

- [ ] **Step 2: Write failing modern parity tests**

Add this modern CRUD test and assert the missing legacy-only field explicitly:

```python
async def test_modern_simulation_set_crud_and_task_reads(self):
    backend, app = (await self.make_backends())[1]
    created = await backend.create_simulation_set("Batch1")
    self.assertEqual(created, SimulationSetInfo("Batch1", None, ()))
    await backend.add_task_to_set("ignored", "Batch1", "case")
    self.assertEqual(await backend.list_simulation_set_tasks("Batch1"), ["case"])
    task = await backend.get_simulation_task_parameters("Batch1", "case")
    self.assertIsNone(task.controlgroup)
    self.assertEqual((task.volley, task.affinity), (1, 1))
    updated = await backend.set_simulation_task_parameters(
        "Batch1", "case", {"volley": 2, "affinity": 3}
    )
    self.assertEqual((updated.volley, updated.affinity), (2, 3))
    await backend.remove_tasks_from_set("Batch1", ["case"])
    await backend.remove_simulation_set("Batch1")
    self.assertNotIn("Batch1", app.simsets)
```

Add the explicit capability assertion below as a separate test:

```python
with self.assertRaises(BackendError) as raised:
    await backend.set_simulation_task_parameters(
        "Batch1", "case", {"controlgroup": "A"}
    )
self.assertEqual(raised.exception.code, "CAPABILITY_UNAVAILABLE")
```

- [ ] **Step 3: Run modern focused tests and verify the red state**

Run the new modern test class with `python -m unittest ... -v`.

Expected: missing modern backend methods.

- [ ] **Step 4: Implement modern CRUD, reads, writes, and restore**

Use `self.adapter.call` exclusively:

```python
async def create_simulation_set(self, set_name: str) -> SimulationSetInfo:
    if set_name in await self.list_simulation_sets(""):
        raise BackendError("ALREADY_EXISTS", "Simulation set already exists.",
                           self.name, "create_simulation_set",
                           {"sim_set_name": set_name})
    await self.adapter.call(self._app, "create_simulation_set", set_name)
    if set_name not in await self.list_simulation_sets(""):
        raise BackendError("POSTCONDITION_FAILED", "Created set was not found.",
                           self.name, "create_simulation_set",
                           {"sim_set_name": set_name})
    return await self.get_simulation_set_details(set_name)
```

For task reads, call `task.parameters()` and construct `SimulationTaskInfo` from
`namespace`, `controlgroup`, `volley`, and `affinity`, using `None` for absent
keys. Before any update, compute:

```python
current = await self.get_simulation_task_parameters(set_name, task_name)
unsupported = [
    key for key in parameters if getattr(current, key, None) is None
]
if unsupported:
    raise BackendError(
        "CAPABILITY_UNAVAILABLE", "Task parameters are unavailable.",
        self.name, "set_simulation_task_parameters",
        {"sim_set_name": set_name, "task_name": task_name,
         "unsupported": unsupported},
    )
```

Then implement the modern update and restore path explicitly:

```python
async def set_simulation_task_parameters(
    self, set_name: str, task_name: str, parameters: Mapping[str, Any]
) -> SimulationTaskInfo:
    original_record = await self.get_simulation_task_parameters(set_name, task_name)
    unsupported = [
        key for key in parameters if getattr(original_record, key, None) is None
    ]
    if unsupported:
        raise BackendError(
            "CAPABILITY_UNAVAILABLE", "Task parameters are unavailable.",
            self.name, "set_simulation_task_parameters",
            {"sim_set_name": set_name, "task_name": task_name,
             "unsupported": unsupported},
        )
    original = {key: getattr(original_record, key) for key in parameters}
    simset = await self.adapter.call(self._app, "simulation_set", set_name)
    task = await self.adapter.call(simset, "task", task_name)
    try:
        await self.adapter.call(task, "parameters", **dict(parameters))
        observed = await self.get_simulation_task_parameters(set_name, task_name)
        mismatches = {
            key: getattr(observed, key)
            for key, expected in parameters.items()
            if getattr(observed, key) != expected
        }
        if mismatches:
            raise BackendError(
                "POSTCONDITION_FAILED", "Task parameter read-back differed.",
                self.name, "set_simulation_task_parameters",
                {"expected": dict(parameters), "observed": mismatches},
            )
        return observed
    except Exception as operation_error:
        restore_error = None
        try:
            await self.adapter.call(task, "parameters", **original)
        except Exception as error:
            restore_error = type(error).__name__
        final = await self.get_simulation_task_parameters(set_name, task_name)
        unrestored = {
            key: getattr(final, key)
            for key, value in original.items()
            if getattr(final, key) != value
        }
        if restore_error is not None or unrestored:
            raise BackendError(
                "PARTIAL_COMPLETION", "Task parameters could not be restored.",
                self.name, "set_simulation_task_parameters",
                {
                    "requested": dict(parameters), "original": original,
                    "observed": {key: getattr(final, key) for key in original},
                    "restore_error": restore_error,
                },
            ) from operation_error
        raise
```

Do not share vendor proxies or add a cross-backend vendor abstraction.

- [ ] **Step 5: Run all backend project tests**

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_projects -v
```

Expected: legacy and modern contract tests pass.

- [ ] **Step 6: Commit modern parity**

```powershell
git add pscad_mcp/core/backend/modern.py tests/test_backend_projects.py
git commit -m "feat: add modern simulation set contract parity"
```

## Task 5: Expand the Backend Protocol and Service Boundary

**Files:**
- Modify: `pscad_mcp/core/backend/base.py`
- Modify: `pscad_mcp/core/service.py`
- Test: `tests/test_backend_contract.py`
- Test: `tests/test_service_contract.py`
- Test: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write service red tests for validation and confirmation**

Create a small async fake backend that records calls. Add tests for empty names, duplicate task removal input, missing confirmation, unknown fields, namespace writes, boolean integers, values below one, and normalized successful results.

```python
async def test_remove_tasks_requires_confirmation_before_backend_call(self):
    backend = FakeSimulationBackend()
    service = service_with_backend(backend)
    with self.assertRaises(ConfirmationRequired):
        await service.remove_tasks_from_set("Batch1", ["case"])
    self.assertEqual(backend.calls, [])

async def test_task_parameters_reject_bool_as_integer(self):
    service = service_with_backend(FakeSimulationBackend())
    with self.assertRaises(BackendError) as raised:
        await service.set_simulation_task_parameters(
            "Batch1", "case", {"volley": True}
        )
    self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")
```

- [ ] **Step 2: Expand the protocol test and verify it remains red**

Add all new method signatures to `SimulationSetBackend` in the test expectation, then run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_contract tests.test_service_contract tests.test_tool_backend_matrix -v
```

Expected: service methods and protocol methods are missing.

- [ ] **Step 3: Add the complete normalized backend protocol**

Replace `SimulationSetBackend` with signatures for all existing and new operations:

```python
class SimulationSetBackend(Protocol):
    async def list_simulation_sets(self, project_name: str) -> list[str]: ...
    async def create_simulation_set(self, set_name: str) -> SimulationSetInfo: ...
    async def remove_simulation_set(self, set_name: str) -> None: ...
    async def get_simulation_set_details(self, set_name: str) -> SimulationSetInfo: ...
    async def list_simulation_set_tasks(self, set_name: str) -> list[str]: ...
    async def run_simulation_set(self, project_name: str, set_name: str) -> None: ...
    async def add_task_to_set(
        self, project_name: str, set_name: str, task_project_name: str
    ) -> None: ...
    async def remove_tasks_from_set(
        self, set_name: str, task_names: Sequence[str]
    ) -> None: ...
    async def get_simulation_task_parameters(
        self, set_name: str, task_name: str
    ) -> SimulationTaskInfo: ...
    async def set_simulation_task_parameters(
        self, set_name: str, task_name: str, parameters: Mapping[str, Any]
    ) -> SimulationTaskInfo: ...
```

- [ ] **Step 4: Add service validation helpers**

Add `ALREADY_EXISTS` and `INVALID_ARGUMENT` guidance to `_ERROR_GUIDANCE`.
Keep the existing `CONFIRMATION_REQUIRED` guidance unchanged, then add:

```python
_TASK_PARAMETER_FIELDS = frozenset({"controlgroup", "volley", "affinity"})

def _require_object_name(value: str, field: str, operation: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackendError(
            "INVALID_ARGUMENT", f"{field} must be a non-empty string.",
            "service", operation, {"field": field},
        )
    return value

def _validated_task_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parameters, dict) or not parameters:
        raise BackendError("INVALID_ARGUMENT", "parameters must not be empty.",
                           "service", "set_simulation_task_parameters")
    if "namespace" in parameters:
        raise BackendError("INVALID_ARGUMENT", "namespace is read-only.",
                           "service", "set_simulation_task_parameters",
                           {"read_only": ["namespace"]})
    unsupported = sorted(set(parameters) - _TASK_PARAMETER_FIELDS)
    if unsupported:
        raise BackendError("INVALID_ARGUMENT", "Unsupported task parameters.",
                           "service", "set_simulation_task_parameters",
                           {"unsupported": unsupported})
    for key in ("volley", "affinity"):
        if key in parameters and (
            isinstance(parameters[key], bool)
            or not isinstance(parameters[key], int)
            or parameters[key] < 1
        ):
            raise BackendError("INVALID_ARGUMENT", f"{key} must be an integer >= 1.",
                               "service", "set_simulation_task_parameters",
                               {"field": key})
    if "controlgroup" in parameters and not isinstance(parameters["controlgroup"], str):
        raise BackendError("INVALID_ARGUMENT", "controlgroup must be a string.",
                           "service", "set_simulation_task_parameters",
                           {"field": "controlgroup"})
    return dict(parameters)
```

The explicit `namespace` branch distinguishes a read-only write from an
unknown parameter while using the same stable `INVALID_ARGUMENT` code.

- [ ] **Step 5: Add service methods and structured outputs**

Use `asdict` for records and confirmation before backend calls:

```python
async def create_simulation_set(self, sim_set_name: str) -> dict[str, Any]:
    name = _require_object_name(sim_set_name, "sim_set_name", "create_simulation_set")
    return asdict(await self.backend.create_simulation_set(name))

async def remove_simulation_set(
    self, sim_set_name: str, *, confirm: bool = False
) -> dict[str, str]:
    if not confirm:
        raise ConfirmationRequired("remove_simulation_set")
    name = _require_object_name(sim_set_name, "sim_set_name", "remove_simulation_set")
    await self.backend.remove_simulation_set(name)
    return {"removed": name}
```

Add these five service methods explicitly:

```python
async def list_simulation_set_tasks(self, sim_set_name: str) -> list[str]:
    name = _require_object_name(sim_set_name, "sim_set_name", "list_simulation_set_tasks")
    return await self.backend.list_simulation_set_tasks(name)

async def remove_tasks_from_set(
    self, sim_set_name: str, task_names: list[str], *, confirm: bool = False
) -> dict[str, list[str]]:
    if not confirm:
        raise ConfirmationRequired("remove_tasks_from_set")
    name = _require_object_name(sim_set_name, "sim_set_name", "remove_tasks_from_set")
    unique = list(dict.fromkeys(task_names))
    if not unique:
        raise BackendError("INVALID_ARGUMENT", "task_names must not be empty.",
                           "service", "remove_tasks_from_set")
    for task_name in unique:
        _require_object_name(task_name, "task_name", "remove_tasks_from_set")
    await self.backend.remove_tasks_from_set(name, unique)
    return {"removed": unique}

async def get_simulation_task_parameters(
    self, sim_set_name: str, task_name: str
) -> dict[str, Any]:
    set_name = _require_object_name(sim_set_name, "sim_set_name", "get_simulation_task_parameters")
    task = _require_object_name(task_name, "task_name", "get_simulation_task_parameters")
    return asdict(await self.backend.get_simulation_task_parameters(set_name, task))

async def set_simulation_task_parameters(
    self, sim_set_name: str, task_name: str, parameters: dict[str, Any]
) -> dict[str, Any]:
    set_name = _require_object_name(sim_set_name, "sim_set_name", "set_simulation_task_parameters")
    task = _require_object_name(task_name, "task_name", "set_simulation_task_parameters")
    values = _validated_task_parameters(parameters)
    return asdict(await self.backend.set_simulation_task_parameters(set_name, task, values))

async def get_simulation_set_details(self, sim_set_name: str) -> dict[str, Any]:
    name = _require_object_name(sim_set_name, "sim_set_name", "get_simulation_set_details")
    return asdict(await self.backend.get_simulation_set_details(name))
```

- [ ] **Step 6: Run service and protocol tests**

Run the command from Step 2.

Expected: service tests pass and both actual backends remain instances of the expanded `PscadBackend` protocol.

- [ ] **Step 7: Commit protocol and service behavior**

```powershell
git add pscad_mcp/core/backend/base.py pscad_mcp/core/service.py tests/test_backend_contract.py tests/test_service_contract.py tests/test_tool_backend_matrix.py
git commit -m "feat: expose safe simulation set service contract"
```

## Task 6: Register Seven MCP Tools

**Files:**
- Modify: `pscad_mcp/tools/simset_tools.py`
- Modify: `tests/test_enhanced_tools.py`
- Modify: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write routing tests for all seven tools**

Import the new functions and assert exact service calls, including keyword-only confirmation:

```python
async def test_remove_simulation_set_routes_confirmation(self):
    self.mock_simset_manager.service.remove_simulation_set = AsyncMock(
        return_value={"removed": "Batch1"}
    )
    result = await remove_simulation_set("Batch1", confirm=True)
    self.assertEqual(result, {"removed": "Batch1"})
    self.mock_simset_manager.service.remove_simulation_set.assert_awaited_once_with(
        "Batch1", confirm=True
    )
```

Add one routing test per remaining function. Each test supplies a distinct
service return value and uses `assert_awaited_once_with` for these exact calls:

```python
create_simulation_set("Batch1")
list_simulation_set_tasks("Batch1")
remove_tasks_from_set("Batch1", ["case"], confirm=True)
get_simulation_task_parameters("Batch1", "case")
set_simulation_task_parameters("Batch1", "case", {"volley": 2})
get_simulation_set_details("Batch1")
```

- [ ] **Step 2: Update the expected tool set first and verify the red state**

Add the seven names to `EXPECTED_TOOLS`, rename the count test to
`test_exact_60_tool_registration`, and assert `len(names) == 60`.

Run:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_enhanced_tools tests.test_tool_backend_matrix -v
```

Expected: missing imports and a 53-versus-60 registration failure.

- [ ] **Step 3: Add thin typed tool functions**

Add functions with no validation or vendor access in the tool module:

```python
async def create_simulation_set(sim_set_name: str) -> dict[str, Any]:
    """Create a workspace-level simulation set."""
    return await pscad_manager.service.create_simulation_set(sim_set_name)

async def remove_simulation_set(
    sim_set_name: str, confirm: bool = False
) -> dict[str, str]:
    """Remove a workspace-level simulation set after confirmation."""
    return await pscad_manager.service.remove_simulation_set(
        sim_set_name, confirm=confirm
    )
```

Add these five typed functions:

```python
async def list_simulation_set_tasks(sim_set_name: str) -> List[str]:
    return await pscad_manager.service.list_simulation_set_tasks(sim_set_name)

async def remove_tasks_from_set(
    sim_set_name: str, task_names: List[str], confirm: bool = False
) -> Dict[str, List[str]]:
    return await pscad_manager.service.remove_tasks_from_set(
        sim_set_name, task_names, confirm=confirm
    )

async def get_simulation_task_parameters(
    sim_set_name: str, task_name: str
) -> Dict[str, Any]:
    return await pscad_manager.service.get_simulation_task_parameters(
        sim_set_name, task_name
    )

async def set_simulation_task_parameters(
    sim_set_name: str, task_name: str, parameters: Dict[str, Any]
) -> Dict[str, Any]:
    return await pscad_manager.service.set_simulation_task_parameters(
        sim_set_name, task_name, parameters
    )

async def get_simulation_set_details(sim_set_name: str) -> Dict[str, Any]:
    return await pscad_manager.service.get_simulation_set_details(sim_set_name)
```

Register all seven names after the existing three calls in
`register_simset_tools`.

- [ ] **Step 4: Run routing and registration tests**

Run the command from Step 2.

Expected: all tests pass and exactly 60 unique tools are registered.

- [ ] **Step 5: Commit MCP tools**

```powershell
git add pscad_mcp/tools/simset_tools.py tests/test_enhanced_tools.py tests/test_tool_backend_matrix.py
git commit -m "feat: register simulation set management tools"
```

## Task 7: Harden Existing Simulation-Set Tools

**Files:**
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Test: `tests/test_service_contract.py`
- Test: `tests/test_backend_projects.py`

- [ ] **Step 1: Write regression tests for old signatures and new checks**

Use `inspect.signature` to freeze the existing public parameters:

```python
self.assertEqual(
    list(inspect.signature(list_simulation_sets).parameters),
    ["project_name"],
)
self.assertEqual(
    list(inspect.signature(run_simulation_set).parameters),
    ["project_name", "sim_set_name"],
)
self.assertEqual(
    list(inspect.signature(add_task_to_set).parameters),
    ["project_name", "sim_set_name", "task_project_name"],
)
```

Add tests that run rejects a missing set, add rejects a missing target project, add rejects a failed vendor response, and add verifies task membership. Assert the compatibility `project_name` does not scope workspace listings.

- [ ] **Step 2: Run focused tests and verify failures**

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_service_contract tests.test_backend_projects -v
```

Expected: new existence and postcondition assertions fail.

- [ ] **Step 3: Strengthen service preconditions without changing signatures**

Before `run_simulation_set`, call `get_simulation_set_details`. Before `add_task_to_set`, verify the set and confirm `task_project_name` appears in `list_projects()`. Do not use the compatibility `project_name` to claim workspace ownership.

```python
await self.backend.get_simulation_set_details(sim_set_name)
projects = {item.name for item in await self.backend.list_projects()}
if task_project_name not in projects:
    raise BackendError(
        "NOT_FOUND", f"Project '{task_project_name}' is not loaded.",
        self.backend.name, "add_task_to_set",
        {"task_project_name": task_project_name},
    )
```

- [ ] **Step 4: Ensure both backends validate run/add vendor outcomes**

Legacy uses `require_success` for XML responses and verifies membership after add. Modern verifies the set before run and membership after add. Preserve existing non-blocking/blocking behavior; this task does not redesign run scheduling.

- [ ] **Step 5: Run backend, service, and tool tests**

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_backend_projects tests.test_service_contract tests.test_enhanced_tools -v
```

Expected: all pass with unchanged old signatures.

- [ ] **Step 6: Commit compatibility hardening**

```powershell
git add pscad_mcp/core/service.py pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/modern.py tests/test_service_contract.py tests/test_backend_projects.py
git commit -m "fix: verify existing simulation set operations"
```

## Task 8: Add PSCAD 4.6.2 Real Acceptance

**Files:**
- Modify: `tests/test_legacy_reliability_acceptance.py`
- Modify: `scripts/run_legacy_acceptance.ps1`

- [ ] **Step 1: Add an opt-in real acceptance test**

Add `test_09_simulation_set_lifecycle_and_task_parameters`. Generate a set name from the timestamped project stem. Use the service for the same boundary exercised by MCP tools.

```python
async def test_09_simulation_set_lifecycle_and_task_parameters(self) -> None:
    path = self._timestamped_project_copy("reliability-simset")
    set_name = f"MCP_{path.parent.name[-24:]}"[:48]
    project_name = path.stem
    service = PscadService(lambda: self.backend, executor=robust_executor)
    service._backend = self.backend
    created = False
    try:
        await service.load_projects([str(path)])
        details = await service.create_simulation_set(set_name)
        created = True
        self.assertEqual(details["tasks"], ())

        await service.add_task_to_set("", set_name, project_name)
        self.assertEqual(
            await service.list_simulation_set_tasks(set_name),
            [project_name],
        )

        original = await service.get_simulation_task_parameters(
            set_name, project_name
        )
        updated_volley = 2 if original["volley"] != 2 else 3
        updated = await service.set_simulation_task_parameters(
            set_name, project_name, {"volley": updated_volley}
        )
        self.assertEqual(updated["volley"], updated_volley)
        restored = await service.set_simulation_task_parameters(
            set_name, project_name, {"volley": original["volley"]}
        )
        self.assertEqual(restored["volley"], original["volley"])

        await service.remove_tasks_from_set(
            set_name, [project_name], confirm=True
        )
        await service.remove_simulation_set(set_name, confirm=True)
        created = False
    finally:
        if created:
            try:
                await service.remove_simulation_set(set_name, confirm=True)
            except Exception as cleanup_error:
                print(
                    "ACCEPTANCE_RELIABILITY=simulation-set-cleanup;FAIL;"
                    f"error_type={type(cleanup_error).__name__}",
                    flush=True,
                )
```

Keep the tuple assertion because `dataclasses.asdict` preserves the backend
tuple until FastMCP performs JSON encoding. Print a pass marker containing the
set name and copied project path after successful cleanup.

- [ ] **Step 2: Verify the test is skipped outside acceptance**

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_legacy_reliability_acceptance -v
```

Expected: the module passes with all real tests skipped when `PSCAD_MCP_ACCEPTANCE` is unset.

- [ ] **Step 3: Update the acceptance runner inputs and summary**

Reuse the existing reliability project copy. Add no broad process termination. Ensure runner output names the new group and still requires:

```powershell
Write-Output "ACCEPTANCE_FINAL_PROCESS_COUNT=0"
Write-Output "ACCEPTANCE_COMPLETE=PASS"
```

- [ ] **Step 4: Run the full non-live suite before PSCAD**

```powershell
& .\.venv\Scripts\python.exe -m unittest discover tests -q
```

Expected: `OK`; real acceptance tests are skipped.

- [ ] **Step 5: Run real PSCAD 4.6.2 acceptance**

Precondition: no unrelated PSCAD process is running.

```powershell
& .\scripts\run_legacy_acceptance.ps1 `
  -Workspace 'D:\PSCAD-Workspace\acceptance' `
  -Version '4.6.2' -X64
```

Expected output includes the simulation-set lifecycle pass marker,
`ACCEPTANCE_FINAL_PROCESS_COUNT=0`, and `ACCEPTANCE_COMPLETE=PASS`.

- [ ] **Step 6: Commit acceptance coverage**

```powershell
git add tests/test_legacy_reliability_acceptance.py scripts/run_legacy_acceptance.ps1
git commit -m "test: cover legacy simulation set lifecycle"
```

## Task 9: Update User Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Test: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Add a documentation assertion**

Add a test that reads both README files and requires `60`,
`create_simulation_set`, `remove_tasks_from_set`, and the Workspace ownership
statement. This prevents the documented count and semantics from drifting.

- [ ] **Step 2: Run the assertion and verify it fails**

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_tool_backend_matrix -v
```

Expected: README content assertion fails while docs still say 53 tools.

- [ ] **Step 3: Update English and Chinese documentation**

Document:

```text
- 60 tools total
- simulation sets are workspace-level resources
- old project_name parameters are retained only for compatibility
- create/delete, task list/remove, task read/write, and details are supported
- destructive removals require confirm=true
- 4.6.2 writable task fields are controlgroup, volley, and affinity
```

Update acceptance counts and examples only after using the actual passing test output. Do not claim Modern real acceptance.

- [ ] **Step 4: Run documentation and matrix tests**

Run the command from Step 2.

Expected: exact 60-tool and documentation assertions pass.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md docs/zh-CN/README.md tests/test_tool_backend_matrix.py
git commit -m "docs: describe simulation set management"
```

## Task 10: Full Verification and Codex Registration

**Files:**
- Modify locally, do not commit: `C:/Users/335/.codex/config.toml`
- Verify: all repository files changed by Tasks 1-9

- [ ] **Step 1: Run the complete automatic verification**

```powershell
& .\.venv\Scripts\python.exe -m unittest discover tests -q
& .\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
& .\.venv\Scripts\python.exe -m pip check
git diff --check
```

Expected: test suite `OK`, compile exit 0, `No broken requirements found.`, and no diff-check output.

- [ ] **Step 2: Verify exact tool and backend contracts**

```powershell
& .\.venv\Scripts\python.exe -c "from pscad_mcp.main import create_server; names={x.name for x in create_server()._tool_manager.list_tools()}; assert len(names)==60; print('TOOLS=60')"
& .\.venv\Scripts\python.exe -m unittest tests.test_tool_backend_matrix -v
```

Expected: `TOOLS=60` and all matrix tests pass.

- [ ] **Step 3: Re-run real acceptance if repository code changed after Task 8**

Run the PowerShell acceptance command from Task 8. Do not reuse an old result after modifying a backend, service, tool, or acceptance file.

Expected: `ACCEPTANCE_COMPLETE=PASS` and zero PSCAD processes.

- [ ] **Step 4: Add the Codex MCP entry without changing existing sections**

First parse the existing file and confirm no `mcp_servers.pscad` table exists:

```powershell
& .\.venv\Scripts\python.exe -c "import tomllib,pathlib; p=pathlib.Path.home()/'.codex'/'config.toml'; d=tomllib.loads(p.read_text(encoding='utf-8')); assert 'pscad' not in d.get('mcp_servers', {}); print('PSCAD_ENTRY_ABSENT=1')"
```

Use `apply_patch` to append exactly the approved `[mcp_servers.pscad]` and
`[mcp_servers.pscad.env]` blocks from the design specification. Do not print,
rewrite, or reformat the rest of the configuration because it may contain
credentials and unrelated MCP settings.

- [ ] **Step 5: Validate the installed configuration and interpreter**

```powershell
& .\.venv\Scripts\python.exe -c "import tomllib,pathlib; p=pathlib.Path.home()/'.codex'/'config.toml'; d=tomllib.loads(p.read_text(encoding='utf-8')); s=d['mcp_servers']['pscad']; assert s['command']==r'D:\pscad-mcp\.venv\Scripts\python.exe'; assert s['env']['PSCAD_MCP_BACKEND']=='legacy'; assert s['env']['PSCAD_MCP_VERSION']=='4.6.2'; print('CODEX_CONFIG=PASS')"
& D:\pscad-mcp\.venv\Scripts\python.exe -c "import pscad_mcp; print('PSCAD_MCP_IMPORT=PASS')"
```

Expected: both pass markers print. Do not launch PSCAD merely to validate TOML.

- [ ] **Step 6: Inspect final repository scope**

```powershell
git status --short --branch
git log --oneline --decorate -12
git diff origin/main...HEAD --stat
```

Expected: no uncommitted repository changes; commits are limited to the approved simulation-set feature, tests, acceptance, and docs. The external Codex configuration does not appear in Git.

- [ ] **Step 7: Verify from a new Codex task**

Create or open a new task after Codex reloads its configuration. Confirm the
PSCAD MCP server starts and exposes the exact 60 tools. Do not call
`get_local_pscad` during this visibility check unless a real PSCAD launch is
intended.

- [ ] **Step 8: Record completion evidence**

Report the automatic test count, real acceptance log path, final process count,
60-tool assertion, Codex config validation, commit list, and any capability
limitations. Do not claim current-task hot loading; only the new-task result
counts as Codex installation verification.
