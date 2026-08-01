# PSCAD 4.6.2 Reliability Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the nine PSCAD 4.6.2 reliability defects confirmed by real-machine acceptance while preserving the existing 53 MCP tool names, parameters, confirmation rules, and modern-backend behavior.

**Architecture:** Keep the MCP tool layer stable. Put PSCAD 4.6.2 command, XML, geometry, and postcondition logic in `LegacyBackend`, add only the internal batch-delete contract needed by the service, and keep lifecycle ownership decisions in `PscadService`. Every vendor mutation is accepted only after an explicit response or observable postcondition succeeds.

**Tech Stack:** Python 3.10+, `asyncio`, `unittest`, `xml.etree.ElementTree`, `importlib.resources`, `pathlib`, `mhrc.automation` 1.2.4, `psutil`, licensed PSCAD 4.6.2 x64 on Windows.

---

## Fixed constraints

- Public surface remains exactly 53 uniquely registered MCP tools.
- No simulation-set tools or other new public features are added.
- Do not edit the installed `mhrc.automation` wheel or PSCAD installation.
- Do not modify public PSCAD examples; all real acceptance work uses timestamped copies below `D:\PSCAD-Workspace\acceptance`.
- `LegacyBackend.attach()` remains launch-only and owns the process it launches.
- Run, pause, and stop retain PSCAD 4.6.2's application-wide pause/stop semantics.
- Every implementation task follows red/green/refactor: add the failing test, run it and observe the intended failure, make the smallest production change, run the focused and regression tests, then commit.

## Task 1: Add reusable response, XML, and geometry primitives

**Files:**

- Create: `pscad_mcp/core/backend/legacy_support.py`
- Create: `tests/test_legacy_support.py`

- [ ] Add failing tests for successful and failed vendor XML responses.

```python
import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy_support import require_success


def test_require_success_returns_true_response():
    response = ET.fromstring('<response success="true" />')
    assert require_success(response, "save-as", {"project": "case"}) is response


def test_require_success_rejects_false_response():
    response = ET.fromstring('<response success="false"><message>denied</message></response>')
    try:
        require_success(response, "save-as", {"project": "case"})
    except BackendError as error:
        assert error.code == "PSCAD_COMMAND_FAILED"
        assert error.backend == "legacy"
        assert error.operation == "save-as"
        assert error.details["project"] == "case"
        assert error.details["response"]["success"] == "false"
    else:
        raise AssertionError("false PSCAD response was accepted")
```

- [ ] Add failing tests that rewrite only the root project identity and matching output name, retain unrelated text, parse the result, and use atomic replacement.

```python
from pathlib import Path
import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.legacy_support import rewrite_project_identity


def test_rewrite_project_identity_preserves_unrelated_content(tmp_path: Path):
    source = tmp_path / "old.pscx"
    target = tmp_path / "new.pscx"
    source.write_text(
        '<?xml version="1.0"?><project name="old"><output name="old" />'
        '<param value="old must remain" /></project>',
        encoding="utf-8",
    )
    rewrite_project_identity(source, target, "new", expected_root="project")
    root = ET.parse(target).getroot()
    assert root.get("name") == "new"
    assert root.find("output").get("name") == "new"
    assert root.find("param").get("value") == "old must remain"
    assert not target.with_suffix(target.suffix + ".tmp").exists()
```

- [ ] Add failing tests for rectangle overlap with margin, 18-unit grid snapping, and deterministic outward candidates.

```python
from pscad_mcp.core.backend.legacy_support import Rect, candidate_rectangles, snap_to_grid


def test_rectangles_touching_margin_are_not_empty():
    occupied = Rect(18, 18, 36, 18)
    candidate = Rect(54, 18, 18, 18)
    assert occupied.intersects(candidate, margin=18)


def test_candidates_start_near_and_stay_on_grid():
    candidates = list(candidate_rectangles((19, 20), 18, 36, grid=18, rings=1))
    assert candidates[0] == Rect(18, 18, 18, 36)
    assert all(rect.x % 18 == 0 and rect.y % 18 == 0 for rect in candidates)
    assert len(candidates) == len(set(candidates))
    assert snap_to_grid(26, 18) == 18
```

- [ ] Run the new tests and confirm import failures before implementation.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_legacy_support -v`

Expected: FAIL because `legacy_support` does not exist.

- [ ] Implement JSON-safe response extraction, strict response validation, identity rewriting through a same-directory temporary file plus `os.replace`, and immutable geometry helpers.

```python
@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def intersects(self, other: "Rect", *, margin: int = 0) -> bool:
        return not (
            self.x + self.width + margin <= other.x
            or other.x + other.width + margin <= self.x
            or self.y + self.height + margin <= other.y
            or other.y + other.height + margin <= self.y
        )


def require_success(response: Any, operation: str, details: Mapping[str, Any]) -> Any:
    success = response.get("success") if hasattr(response, "get") else None
    if str(success).casefold() != "true":
        raise BackendError(
            "PSCAD_COMMAND_FAILED",
            f"PSCAD 4.6.2 command '{operation}' failed.",
            "legacy",
            operation,
            {**dict(details), "response": response_payload(response)},
        )
    return response
```

`response_payload()` must include only bounded strings, attributes, tag, and child text; it must never expose vendor proxy objects. `rewrite_project_identity()` must leave the source untouched, fsync/close the temporary file before replacement, and delete the temporary file on error.

Also implement `project_kind(root, suffix)` here. It returns only `"case"` or `"library"`, accepts the root kind marker produced by the two PSCAD-captured templates, uses `.pscx`/`.pslx` as a consistency check, and raises `ValueError` when XML and suffix disagree.

- [ ] Run helper tests and the existing suite.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_legacy_support -v`

Expected: PASS.

Run: `\.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: 135 existing tests plus the new helper tests pass; 5 acceptance tests remain skipped without the opt-in variable.

- [ ] Commit.

```powershell
git add pscad_mcp/core/backend/legacy_support.py tests/test_legacy_support.py
git commit -m "test: add legacy reliability primitives"
```

## Task 2: Route project settings to the selected project

**Files:**

- Modify: `tests/test_backend_projects.py`
- Modify: `pscad_mcp/core/backend/legacy.py`

- [ ] Replace the legacy fake's application-global settings expectation with project parameter methods and add failure/postcondition cases.

```python
class FakeProject:
    def __init__(self, name="case", kind="Case"):
        self.name = name
        self.type = kind
        self.description = "Example"
        self.filename = f"{name}.pscx"
        self.calls = []
        self.settings_data = {"time_duration": "0.5", "time_step": "50 [us]"}
        self.accept_settings = True

    def parameters(self):
        return dict(self.settings_data)

    def set_parameters(self, values):
        if not self.accept_settings:
            return False
        self.settings_data.update(values)
        return True
```

Tests must assert:

- `get_settings("case")` returns `FakeProject.settings_data` and never calls `app.settings()`;
- `set_settings()` returns normally only when `set_parameters()` is true and every requested value is present on reread;
- `False` raises `BackendError` with code `INVALID_PARAMETER`;
- a reread mismatch raises `POSTCONDITION_FAILED` and includes expected/actual values.

- [ ] Run the focused tests and observe failure against the current application-global implementation.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_backend_projects -v`

Expected: FAIL in the new project-settings tests.

- [ ] Implement project-scoped reads and verified writes.

```python
async def get_settings(self, project_name: str) -> dict[str, Any]:
    project = await self._project(project_name)
    values = await self.executor.run_safe(project.parameters)
    return dict(values)


async def set_settings(self, project_name: str, settings: Mapping[str, Any]) -> None:
    project = await self._project(project_name)
    requested = dict(settings)
    accepted = await self.executor.run_safe(project.set_parameters, requested)
    if accepted is not True:
        raise BackendError(
            "INVALID_PARAMETER",
            "PSCAD rejected one or more project settings.",
            self.name,
            "set_project_settings",
            {"project": project_name, "keys": sorted(requested)},
        )
    actual = dict(await self.executor.run_safe(project.parameters))
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in requested.items()
        if actual.get(key) != value
    }
    if mismatches:
        raise BackendError(
            "POSTCONDITION_FAILED",
            "Project settings did not match after update.",
            self.name,
            "set_project_settings",
            {"project": project_name, "mismatches": mismatches},
        )
```

If PSCAD normalizes a numeric string, compare via a small local normalizer that treats equal numeric values as equal but does not collapse units or arbitrary text.

- [ ] Run focused and full tests, then commit.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_backend_projects -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git add pscad_mcp/core/backend/legacy.py tests/test_backend_projects.py
git commit -m "fix: use project-scoped PSCAD settings"
```

## Task 3: Package PSCAD-validated blank case and library templates

**Files:**

- Create: `pscad_mcp/assets/templates/empty_case.pscx`
- Create: `pscad_mcp/assets/templates/empty_library.pslx`
- Modify: `pyproject.toml`
- Create: `tests/test_legacy_templates.py`

- [ ] Add tests that require both assets through `importlib.resources`, parse them, verify their root name/type/suffix, and ensure neither contains user example components.

```python
from importlib.resources import as_file, files
from pathlib import Path
import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.legacy_support import project_kind


def test_blank_templates_are_installed_and_parseable():
    for filename, expected_kind in (
        ("empty_case.pscx", "case"),
        ("empty_library.pslx", "library"),
    ):
        resource = files("pscad_mcp").joinpath("assets", "templates", filename)
        with as_file(resource) as path:
            root = ET.parse(path).getroot()
            assert root.tag == "project"
            assert root.get("name") in {"empty_case", "empty_library"}
            assert expected_kind in project_kind(root, Path(path).suffix)
            assert not root.findall(".//UserCmp")
```

- [ ] Run and observe missing assets.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_legacy_templates -v`

Expected: FAIL because templates are not present.

- [ ] Produce the assets from PSCAD 4.6.2 itself, not by copying a public example.

Use a clean acceptance-owned PSCAD process and create one blank Case and one blank Library in a new directory named `D:\PSCAD-Workspace\acceptance\template-capture-<timestamp>`. Save both in PSCAD, close the owned process, copy only those two files into `pscad_mcp/assets/templates`, and record the source path and SHA-256 hashes in the test output. Open each packaged copy in a second clean PSCAD 4.6.2 process before accepting it. Do not commit any `.pswx`, output, cache, build, or generated result files.

- [ ] Register the assets as package data.

```toml
[tool.setuptools.package-data]
pscad_mcp = ["assets/templates/*.pscx", "assets/templates/*.pslx"]
```

- [ ] Verify source-tree and built-wheel access.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_legacy_templates -v
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir build\template-wheel-check
.\.venv\Scripts\python.exe -c "import pathlib,zipfile; p=next(pathlib.Path('build/template-wheel-check').glob('*.whl')); z=zipfile.ZipFile(p); names=set(z.namelist()); assert 'pscad_mcp/assets/templates/empty_case.pscx' in names; assert 'pscad_mcp/assets/templates/empty_library.pslx' in names"
```

Expected: PASS and both asset paths exist in the wheel.

- [ ] Commit only the package metadata, templates, and tests.

```powershell
git add pyproject.toml pscad_mcp/assets/templates tests/test_legacy_templates.py
git commit -m "feat: package PSCAD 4.6.2 blank templates"
```

## Task 4: Repair project creation and save-as postconditions

**Files:**

- Modify: `tests/test_backend_projects.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/legacy_support.py`

- [ ] Add a fake application that loads a file only when its XML root is valid and exposes it through `list_projects()`/`project()`.

- [ ] Add red tests for case creation, library creation, cleanup on load failure, native save-as success, native `success=false` fallback, and cleanup on fallback verification failure.

The tests must assert all of the following:

- the requested `.pscx` or `.pslx` exists only after successful load/list verification;
- the root project name and `<output name>` match the destination stem;
- `definition_paths` changes only after success;
- an existing destination is replaced atomically, never deleted before the new file parses;
- `save_as` receiving `<response success="false"/>` cannot return success without the verified file fallback;
- failed creation/fallback removes only a file created by this operation and preserves a pre-existing destination.

- [ ] Run and observe failures in current `workspace.create_project()` and unchecked `project.save_as()` behavior.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_backend_projects -v`

Expected: FAIL in new creation/save-as tests.

- [ ] Implement `_load_and_verify_project(destination, kind, operation)` and template-based creation.

```python
async def _load_and_verify_project(
    self, destination: Path, kind: str, operation: str
) -> ProjectInfo:
    await self.load_projects([str(destination)])
    expected_name = destination.stem
    expected_type = "Case" if kind == "case" else "Library"
    projects = await self.list_projects()
    match = next((item for item in projects if item.name == expected_name), None)
    if match is None or match.type.casefold() != expected_type.casefold():
        raise BackendError(
            "POSTCONDITION_FAILED",
            "PSCAD did not load the expected project.",
            self.name,
            operation,
            {"path": str(destination), "expected_name": expected_name, "expected_type": expected_type},
        )
    return match
```

Creation copies the packaged template to a uniquely named same-directory temporary path, calls `rewrite_project_identity`, parses and validates the temporary file, atomically replaces the destination, loads it, verifies name/type, and only then updates `definition_paths`. On failure it restores any prior destination from a backup created in the same directory and removes only operation-owned temporary artifacts.

- [ ] Implement save-as with native response validation and controlled fallback.

```python
response = await self.executor.run_safe(project.save_as, str(destination))
if response is not None and str(response.get("success")).casefold() == "true" and destination.is_file():
    info = await self._load_and_verify_project(destination, kind, "save_project_as")
    self.definition_paths[info.name] = destination
    return

await self.save_project(project_name)
source = self.definition_paths.get(project_name)
if source is None or not source.is_file():
    raise BackendError(
        "CAPABILITY_UNAVAILABLE",
        "The source project file is unavailable for the PSCAD 4.6.2 save-as fallback.",
        self.name,
        "save_project_as",
        {"project": project_name, "destination": str(destination)},
    )
await self._copy_rewrite_load_verify(source, destination, kind, "save_project_as")
```

The native branch must call `require_success()` when a response is present. Catch only its `PSCAD_COMMAND_FAILED` to enter the documented fallback; do not swallow parse, I/O, timeout, or postcondition errors. Derive `kind` from the loaded project's type/suffix and reject a mismatched destination suffix.

- [ ] Run project tests, template tests, full tests, and `git diff --check`; then commit.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_backend_projects tests.test_legacy_templates -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
git add pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/legacy_support.py tests/test_backend_projects.py
git commit -m "fix: verify legacy project creation and save as"
```

## Task 5: Make run non-blocking and bridge status, pause, and stop safely

**Files:**

- Modify: `tests/test_backend_projects.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `tests/test_legacy_acceptance.py`

- [ ] Add fake command/project behavior for `command("run").execute(False)`, callback-style `get_run_status(callback)`, and application command IDs.

Tests must cover:

- `run_project()` calls `execute(False)` and returns before a blocking build/run consumer would finish;
- `project_run_state()` maps callback XML/tuple/dict values to `RunState`;
- a callback that never arrives raises `BackendError(code="PSCAD_COMMAND_TIMEOUT")`;
- callback error/failed response raises `PSCAD_COMMAND_FAILED`;
- pause calls `_command_id_cmd("ID_RIBBON_HOME_RUN_PAUSE")` and produces no stdout;
- stop calls `_command_id_cmd("ID_RIBBON_HOME_RUN_STOP")`;
- pause/stop failed responses never produce success;
- a state request can enter the single-worker executor immediately after starting a run.

- [ ] Run and confirm the current blocking `project.run()`, `unknown` status, and stdout behavior fail these tests.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_backend_projects -v`

Expected: FAIL in new run-control cases.

- [ ] Implement non-blocking run submission.

```python
async def run_project(self, project_name: str) -> None:
    project = await self._project(project_name)

    def start() -> None:
        command = project.command("run")
        command.execute(False)

    await self.executor.run_safe(start)
    self._running_projects.add(project_name)
```

Initialize and clear `_running_projects` on construction/disconnect. Do not call the vendor `execute_build_run_cmd()` path for project runs.

- [ ] Implement a thread-safe bounded callback bridge.

```python
async def project_run_state(self, project_name: str) -> RunState:
    project = await self._project(project_name)
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()

    def receive(response: Any, *callback_args: Any, **callback_kwargs: Any) -> None:
        payload = (response, callback_args, callback_kwargs)
        loop.call_soon_threadsafe(_resolve_future_once, future, payload)

    await self.executor.run_safe(project.get_run_status, receive)
    try:
        response, callback_args, callback_kwargs = await asyncio.wait_for(future, 5.0)
    except asyncio.TimeoutError as error:
        raise BackendError(
            "PSCAD_COMMAND_TIMEOUT",
            "PSCAD did not return run status within 5 seconds.",
            self.name,
            "get_run_status",
            {"project": project_name},
        ) from error
    state = parse_run_state(response, callback_args, callback_kwargs)
    if state.status.casefold() in {"complete", "completed", "stopped", "failed", "idle"}:
        self._running_projects.discard(project_name)
    return state
```

`parse_run_state()` must support the actual PSCAD 4.6.2 callback shape captured by the red test plus tuple/dict fakes; if status cannot be extracted, return `BackendError(code="UNEXPECTED_RESPONSE")`, not `unknown`.

- [ ] Implement direct pause/stop commands and response validation.

```python
async def _run_control_command(self, command_id: str, operation: str) -> None:
    app = self._require_app()
    command = await self.executor.run_safe(app._command_id_cmd, command_id)
    response = await self.executor.run_safe(command.execute)
    require_success(response, operation, {"scope": "all-running-projects"})
```

- [ ] Update simulation acceptance to poll status until completion and add a fast run/pause/status/stop case. Capture stdout around pause and assert it is empty.

- [ ] Run focused/full tests and commit.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_backend_projects -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git add pscad_mcp/core/backend/legacy.py tests/test_backend_projects.py tests/test_legacy_acceptance.py
git commit -m "fix: repair legacy simulation control"
```

## Task 6: Implement verifiable component enable/disable with a dedicated layer

**Files:**

- Modify: `tests/test_backend_components.py`
- Modify: `pscad_mcp/core/backend/legacy.py`

- [ ] Extend component/project/canvas fakes with layer command responses and `list_components()` XML membership.

Add tests for:

- first disable creates `PSCAD_MCP_DISABLED`, sets it to `disabled`, and adds the component;
- repeated disable is idempotent and does not fail on an existing layer;
- enable removes only `PSCAD_MCP_DISABLED` membership and retains unrelated layer names;
- `success=false` from create/set/add/remove raises `PSCAD_COMMAND_FAILED`;
- missing membership change after a success response raises `POSTCONDITION_FAILED`;
- no `enabled` component parameter is written.

- [ ] Run and confirm current parameter-based fallback fails.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_backend_components -v`

Expected: FAIL in layer-state tests.

- [ ] Implement `_component_layers()` from the `canvas.list_components()` XML and dedicated-layer mutation.

```python
_disabled_layer = "PSCAD_MCP_DISABLED"


async def set_component_enabled(self, project_name: str, component_id: int, enabled: bool) -> None:
    canvas, component = await self._component_proxy(project_name, component_id)
    project = await self._project(project_name)
    before = await self._component_layers(canvas, component_id)
    if enabled:
        if self._disabled_layer in before:
            response = await self.executor.run_safe(component.remove_from_layer, self._disabled_layer)
            require_success(response, "enable_component", {"project": project_name, "component_id": component_id})
    else:
        if not await self._layer_is_known(project_name, self._disabled_layer):
            require_success(
                await self.executor.run_safe(project.create_layer, self._disabled_layer),
                "disable_component",
                {"project": project_name, "component_id": component_id},
            )
            self._known_managed_layers.add((project_name, self._disabled_layer))
        require_success(
            await self.executor.run_safe(project.set_layer, self._disabled_layer, "disabled"),
            "disable_component",
            {"project": project_name, "component_id": component_id},
        )
        if self._disabled_layer not in before:
            require_success(
                await self.executor.run_safe(component.add_to_layer, self._disabled_layer),
                "disable_component",
                {"project": project_name, "component_id": component_id},
            )
    after = await self._component_layers(canvas, component_id)
    if (self._disabled_layer not in after) is not enabled:
        raise BackendError(
            "POSTCONDITION_FAILED",
            "Component layer state did not change as requested.",
            self.name,
            "set_component_enabled",
            {"project": project_name, "component_id": component_id, "layers": sorted(after)},
        )
```

Because 4.6.2 has no layer-list API, `_layer_is_known()` must use the loaded project XML, a verified component membership, or the backend's `_known_managed_layers` cache populated only after a successful create response. Clear the cache on disconnect. It must not treat every failed `create_layer` response as “already exists.” Split `layer` attributes on semicolon/comma/whitespace without changing original unrelated layer memberships.

- [ ] Run focused/full tests and commit.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_backend_components -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git add pscad_mcp/core/backend/legacy.py tests/test_backend_components.py
git commit -m "fix: verify legacy component enabled state"
```

## Task 7: Delete connected components with a precomputed batch plan

**Files:**

- Modify: `pscad_mcp/core/backend/base.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `tests/test_backend_components.py`
- Modify: `tests/test_safety_contract.py`

- [ ] Add the internal aggregate method to the backend protocol and change service tests to require one prevalidated backend batch call.

```python
class ComponentBackend(Protocol):
    async def delete_components(self, project_name: str, component_ids: Sequence[int]) -> None: pass
```

`PscadService.delete_component()` calls `backend.delete_components(project_name, [component_id])`. `PscadService.delete_components()` deduplicates/nonempty-validates IDs and calls the same method once. Confirmation messages and public parameters remain unchanged.

- [ ] Add fake connected components and `WireOrthogonal` objects with absolute `vertices`. Red tests must prove:

- all target IDs are validated before the first wire/component deletion;
- only wires whose first or last vertex equals a target port coordinate are deleted;
- shared wires are deleted once;
- wires are deleted before target components;
- unconnected single and batch deletion still pass;
- postcondition checks both target and planned wire IDs;
- mid-operation failure contains `deleted_component_ids`, `deleted_wire_ids`, and `remaining_component_ids` in `BackendError.details`.

- [ ] Run focused tests and observe connected deletion failure.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_backend_components tests.test_safety_contract -v`

Expected: FAIL until the aggregate method and wire-first plan exist.

- [ ] Implement legacy planning before mutation.

```python
async def delete_components(self, project_name: str, component_ids: Sequence[int]) -> None:
    unique_ids = list(dict.fromkeys(int(value) for value in component_ids))
    canvas = await self._canvas(project_name, "Main")
    targets = [await self._component_proxy(project_name, value) for value in unique_ids]
    target_ports = {
        (port.x, port.y)
        for component_id in unique_ids
        for port in await self.get_component_ports(project_name, component_id)
    }
    objects = list(await self.executor.run_safe(canvas.find_all))
    wires = []
    seen_wire_ids = set()
    for value in objects:
        if type(value).__name__ != "WireOrthogonal":
            continue
        vertices = list(await self.executor.run_safe(lambda item=value: item.vertices))
        if vertices and ({vertices[0], vertices[-1]} & target_ports):
            wire_id = self._component_id(value)
            if wire_id not in seen_wire_ids:
                seen_wire_ids.add(wire_id)
                wires.append(value)
    await self._execute_deletion_plan(project_name, canvas, targets, wires)
```

Do not match intermediate wire vertices; only electrical endpoints attach to ports. `_execute_deletion_plan()` deletes planned wires first, then components, rereads `canvas.list_components()`, and raises a structured partial-completion error if any mutation or postcondition fails.

- [ ] Implement modern `delete_components()` as prevalidation followed by its existing per-component deletion path; do not change modern external behavior.

- [ ] Run focused/full tests and commit.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_backend_components tests.test_safety_contract -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git add pscad_mcp/core/backend/base.py pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/modern.py pscad_mcp/core/service.py tests/test_backend_components.py tests/test_safety_contract.py
git commit -m "fix: delete connected components safely"
```

## Task 8: Replace anchor-only empty-space search with rectangle collision checks

**Files:**

- Modify: `tests/test_backend_canvas.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/legacy_support.py`

- [ ] Add Canvas XML fixtures containing `x`, `y`, `w`, `h`, objects without dimensions, and objects not returned by `find_all()`.

Tests must assert:

- a candidate overlapping any part of an occupied rectangle is rejected;
- a candidate inside the safety margin is rejected;
- missing `w`/`h` uses conservative 36-by-36 defaults;
- all returned coordinates align to 18;
- search proceeds outward deterministically from `near`;
- the returned rectangle remains clear after a second Canvas read;
- an entirely occupied configured search bound raises `NO_EMPTY_SPACE`.

- [ ] Run and confirm the current anchor-set fallback fails.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_backend_canvas -v`

Expected: FAIL in rectangle collision cases.

- [ ] Parse occupied rectangles directly from `canvas.list_components()` and use the helper candidates.

```python
async def _occupied_rectangles(self, canvas: Any) -> list[Rect]:
    response = await self.executor.run_safe(canvas.list_components)
    result = []
    for node in response.findall("components/*"):
        x = int(node.get("x", "0"))
        y = int(node.get("y", "0"))
        width = max(int(node.get("w", "36")), 1)
        height = max(int(node.get("h", "36")), 1)
        result.append(Rect(x, y, width, height))
    return result
```

Search at most 100 grid rings with an 18-unit safety margin. If `closest_empty_rect()` exists, snap and independently verify its answer against the same occupied rectangles; reject and fall back to the ring search when it overlaps.

- [ ] Before returning, reread occupied rectangles once and recheck the selected candidate. Continue searching if it became occupied; raise `NO_EMPTY_SPACE` when no candidate remains.

- [ ] Run focused/full tests and commit.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_backend_canvas tests.test_legacy_support -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git add pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/legacy_support.py tests/test_backend_canvas.py
git commit -m "fix: prevent legacy canvas overlap"
```

## Task 9: Make connection repair honor process ownership

**Files:**

- Modify: `tests/test_service_contract.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`

- [ ] Give `FakeLifecycleBackend` an independent `owns_process` constructor flag and ordered event log.

Add tests for:

- an owned process receives `quit`, then executor reset, then a fresh attach;
- a non-owned process receives `disconnect`, never `quit`, then reset/attach;
- quit/disconnect failure leaves the original backend selected, does not reset, and does not call the backend factory again;
- fresh attach failure leaves `_backend` as `None` and returns the underlying structured error;
- the status/help wording for legacy 4.6.2 says a new automation instance is launched rather than attached to an existing GUI.

- [ ] Run and confirm current unconditional disconnect behavior fails the ownership tests.

Run: `\.venv\Scripts\python.exe -m unittest tests.test_service_contract -v`

Expected: FAIL for the owned-process path.

- [ ] Implement ordered lifecycle repair without calling the public `disconnect()` helper, because that helper clears `_backend` before shutdown is known to have succeeded.

```python
async def repair_connection(self) -> str:
    current = self._backend
    if current is not None:
        info = await current.heartbeat()
        if info.owns_process:
            await current.quit()
        else:
            await current.disconnect()
        self._backend = None
    self.executor.reset()
    return await self.attach_local()
```

If shutdown raises, leave `_backend` pointing at `current` so status/error reporting remains coherent. If new attach raises after selection, clear the failed candidate in `attach_local()` or `repair_connection()` before re-raising.

- [ ] Update English and Chinese README lifecycle wording without changing tool signatures.

- [ ] Run focused/full tests and commit.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_service_contract -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git add pscad_mcp/core/service.py tests/test_service_contract.py README.md docs/zh-CN/README.md
git commit -m "fix: preserve PSCAD process ownership on repair"
```

## Task 10: Extend real PSCAD 4.6.2 acceptance and complete verification

**Files:**

- Modify: `tests/test_legacy_acceptance.py`
- Create: `tests/test_legacy_reliability_acceptance.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`

- [ ] Add shared acceptance helpers for timestamped workspace copies, stdout capture, bounded polling, XML inspection, and owned-process teardown. Keep default skip behavior when `PSCAD_MCP_ACCEPTANCE` is not `1`.

- [ ] Add one ordered reliability acceptance class covering:

1. create blank case and library, save, close, reload, and verify project name/type;
2. native-failure save-as fallback, target XML identity, close/reload, and source untouched hash;
3. non-blocking run followed by status polling, stdout-clean pause, resume/run if supported, and stop;
4. project `time_duration` read/write/reread/restore, with application-global settings unchanged;
5. disable/save/inspect `PSCAD_MCP_DISABLED`, enable/save/inspect membership removal;
6. create two resistors and a connecting wire, delete both in one batch, and verify all planned IDs absent;
7. add a known-size object, request an empty rectangle near it, add at the returned position, and verify XML rectangles do not overlap;
8. service `repair_connection()` while owning the process, verify the first PID exits before the second appears, and finish with zero acceptance-owned PIDs.

- [ ] Preserve and rerun the five original acceptance groups: read-only, mutation/canvas, build, simulation/output, and PSOUT.

- [ ] Run all non-live verification first.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "from pscad_mcp.main import create_server; names=[tool.name for tool in create_server()._tool_manager.list_tools()]; assert len(names)==53; assert len(names)==len(set(names)); print('TOOLS=53;UNIQUE=PASS')"
git diff --check
```

Expected: all non-acceptance tests pass, 5 or more live classes/tests skip without opt-in, compile/dependency/diff checks pass, and `TOOLS=53;UNIQUE=PASS` prints.

- [ ] Confirm there is no unrelated PSCAD process, create fresh timestamped source copies under `D:\PSCAD-Workspace\acceptance`, then run licensed acceptance with the already established environment variables.

```powershell
$env:PSCAD_MCP_ACCEPTANCE='1'
$env:PSCAD_MCP_ACCEPTANCE_VERSION='4.6.2'
$env:PSCAD_MCP_ACCEPTANCE_X64='true'
.\.venv\Scripts\python.exe -m unittest tests.test_legacy_acceptance tests.test_legacy_reliability_acceptance -v
```

Expected: the five original groups and all eight reliability groups print `PASS`; no test operates on an original example path.

- [ ] After teardown, verify no PSCAD process remains and record evidence paths/hashes in the test log.

```powershell
Get-Process -Name 'PSCAD*' -ErrorAction SilentlyContinue
```

Expected: no output.

- [ ] Update English and Chinese README files with the PSCAD 4.6.2 guarantees and limits: template-backed create/save-as, project-scoped settings, application-wide pause/stop, dedicated disabled layer, connected-delete behavior, 18-unit collision search, launch-only legacy attachment, and opt-in acceptance command.

- [ ] Run final verification one last time after documentation changes.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
.\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short
```

- [ ] Commit the acceptance and documentation work.

```powershell
git add tests/test_legacy_acceptance.py tests/test_legacy_reliability_acceptance.py README.md docs/zh-CN/README.md
git commit -m "test: accept PSCAD 4.6.2 reliability repairs"
```

## Final review gate

- [ ] Compare the final diff against `docs/superpowers/specs/2026-08-01-pscad-462-reliability-repair-design.zh-CN.md` and account for every one of the nine defects.
- [ ] Confirm `git diff origin/main -- pscad_mcp/tools pscad_mcp/server.py` contains no public tool name or parameter changes.
- [ ] Confirm no vendor-wheel, PSCAD-installation, public-example, build-wheel, cache, or acceptance-output file is staged.
- [ ] Confirm all error details are JSON serializable and no raw XML/proxy/exception object crosses the backend boundary.
- [ ] Confirm the final real acceptance log names the owned PIDs and ends with zero PSCAD processes.
- [ ] Invoke the `verification-before-completion` skill before claiming the repair is complete.
