# PSCAD MCP Horizontal Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden PSCAD MCP delivery, tool metadata, optional profiles, runtime shutdown, local documentation, and large-result handling while preserving every existing tool's default call behavior.

**Architecture:** A canonical catalog becomes the source of public tool names and metadata, while `register_tool` applies profile filtering and MCP annotations without changing existing wrappers. A testable runtime lifecycle coordinates domain-task cancellation, learning-store closure, owned PSCAD cleanup, and executor shutdown. Documentation moves to lazy local state with MCP resources, and optional slice arguments bound large results without changing their result types.

**Tech Stack:** Python 3.10+, FastMCP from `mcp>=1.29,<2`, asyncio, Pydantic-backed MCP types, pytest, PowerShell, GitHub Actions, Ruff correctness rules.

---

## File Map

### New production files

- `pscad_mcp/tools/catalog.py`: immutable tool metadata, exact groups, profile parsing, and canonical name-set helpers.
- `pscad_mcp/tools/capability_tools.py`: additive `get_pscad_capabilities` wrapper and bounded capability serialization.
- `pscad_mcp/tools/pagination.py`: shared optional slice validation that preserves list and string result types.
- `pscad_mcp/runtime.py`: idempotent ordered runtime cleanup and FastMCP lifespan adapter.

### Existing production files to modify

- `pscad_mcp/main.py`: construct the selected profile, register the capability tool and documentation resources, and install the lifespan.
- `pscad_mcp/tools/registration.py`: resolve catalog descriptions and annotations before FastMCP registration and skip inactive groups.
- `pscad_mcp/tools/app_tools.py`: async documentation sync plus bounded listing and reads.
- `pscad_mcp/tools/project_tools.py`: optional pagination for projects and components.
- `pscad_mcp/tools/creation_tools.py`: optional pagination for definitions.
- `pscad_mcp/tools/canvas_tools.py`: optional pagination for canvas objects.
- `pscad_mcp/tools/hvdc_tools.py`: expose non-initializing domain shutdown.
- `pscad_mcp/tools/lcc_tools.py`: expose non-initializing builder shutdown.
- `pscad_mcp/tools/lcc_parametric_tools.py`: expose non-initializing parametric-builder shutdown.
- `pscad_mcp/hvdc/service.py`: bounded cancellation of tracked scenario tasks.
- `pscad_mcp/hvdc/builders/lcc/service.py`: bounded cancellation of fixed-builder tasks.
- `pscad_mcp/hvdc/builders/lcc/parametric_service.py`: bounded cancellation of parametric-builder tasks.
- `pscad_mcp/learning/service.py`: idempotent closure of the lazy SQLite service.
- `pscad_mcp/core/service.py`: ownership-aware backend shutdown.
- `pscad_mcp/core/connection_manager.py`: one runtime shutdown entry point.
- `pscad_mcp/utils/doc_manager.py`: lazy local-state configuration, atomic writes, and path-redacted generation.

### Delivery and documentation files

- `.github/workflows/ci.yml`: sole Windows CI workflow and Python 3.10-3.14 matrix.
- `.github/workflows/windows-ci.yml`: remove the duplicate workflow.
- `.gitignore`: ignore generated documentation roots.
- `pyproject.toml`: add Ruff to development dependencies and configure narrow correctness rules.
- `scripts/verify_package.ps1`: compare installed server names with the installed canonical catalog.
- `README.md`, `docs/zh-CN/README.md`, `CHANGELOG.md`, `NOTICE`, `config.example.toml`: document the new additive behavior and generated-document boundary.
- `docs/raw/*`, `docs/md/*`: remove generated vendor snapshots from Git tracking.

### New and focused tests

- `tests/test_tool_catalog.py`
- `tests/test_tool_profiles.py`
- `tests/test_capability_tools.py`
- `tests/test_runtime_lifecycle.py`
- `tests/test_documentation_runtime.py`
- `tests/test_tool_pagination.py`
- `tests/test_repository_hygiene.py`
- Existing inventory, package, configuration, tool-wrapper, and documentation tests listed in the tasks below.

---

### Task 1: Canonical Inventory And Installed-Package Parity

**Files:**
- Create: `pscad_mcp/tools/catalog.py`
- Create: `tests/test_tool_catalog.py`
- Modify: `scripts/verify_package.ps1:48-61`
- Modify: `tests/test_verify_package_script.py`
- Modify: `tests/test_install_smoke.py:69-93`
- Modify: `tests/test_tool_inventory.py`
- Modify: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write failing catalog and script tests**

Add tests that express exact name-set parity without a numeric literal:

```python
from pathlib import Path

from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
)


def test_catalog_matches_the_default_server_and_compatibility_set():
    server_names = {
        tool.name for tool in create_server()._tool_manager.list_tools()
    }
    assert server_names == FULL_TOOL_NAMES
    assert COMPATIBILITY_TOOL_NAMES <= server_names
    assert set().union(*TOOL_GROUPS.values()) == COMPATIBILITY_TOOL_NAMES
    assert sum(len(names) for names in TOOL_GROUPS.values()) == len(
        COMPATIBILITY_TOOL_NAMES
    )


def test_package_verification_uses_catalog_not_a_numeric_inventory():
    text = (Path(__file__).parents[1] / "scripts" / "verify_package.ps1").read_text(
        encoding="utf-8"
    )
    assert "FULL_TOOL_NAMES" in text
    assert "set(tool.name for tool in tools)" in text
    assert "PSCAD_MCP_TOOL_PROFILE" in text
    assert "== 77" not in text
    assert "== 83" not in text
```

Update existing compatibility tests so their expected set imports
`COMPATIBILITY_TOOL_NAMES` rather than asserting `len(names) == 83`. Package
and server parity checks use `FULL_TOOL_NAMES`, which initially aliases the
compatibility set and expands only when Task 5 adds capability discovery.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_tool_catalog.py tests/test_verify_package_script.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py
```

Expected: collection fails because `pscad_mcp.tools.catalog` does not exist,
and the script still contains `assert len(tools) == 77`.

- [ ] **Step 3: Add the exact current catalog**

Create `catalog.py` with immutable group sets. Move the exact 83-name set from
`tests/test_tool_backend_matrix.py::EXPECTED_TOOLS` into these groups without
renaming an entry:

```python
from __future__ import annotations

from types import MappingProxyType


TOOL_GROUPS = MappingProxyType(
    {
        "core": frozenset(
            {
                "get_local_pscad", "get_pscad_status", "sync_documentation",
                "list_documentation", "read_documentation", "repair_connection",
                "quit_pscad", "load_projects", "list_projects", "run_project",
                "get_run_status", "find_components", "get_component_parameters",
                "set_component_parameters", "validate_component_parameters",
                "pause_simulation", "stop_simulation", "get_project_settings",
                "set_project_settings", "get_project_output", "read_output_file",
                "list_simulation_sets", "run_simulation_set", "add_task_to_set",
                "create_simulation_set", "remove_simulation_set",
                "list_simulation_set_tasks", "remove_tasks_from_set",
                "get_simulation_task_parameters", "set_simulation_task_parameters",
                "get_simulation_set_details", "create_case", "create_library",
                "save_project", "save_project_as", "build_project",
                "build_all_projects", "get_project_definitions", "add_component",
                "create_component", "create_wire", "create_bus",
                "create_connection", "connect_ports", "create_annotation",
                "create_graph_frame", "create_control_frame",
                "list_canvas_components", "find_empty_space", "delete_components",
                "get_component_location", "set_component_location",
                "rotate_component", "mirror_component", "clone_component",
                "get_component_ports", "get_component_port", "enable_component",
                "disable_component", "delete_component",
            }
        ),
        "hvdc": frozenset(
            {
                "inspect_hvdc_project", "get_hvdc_assets", "get_hvdc_mappings",
                "validate_hvdc_project", "run_hvdc_scenario",
                "get_hvdc_scenario_status", "analyze_hvdc_results",
                "compare_hvdc_scenarios", "list_hvdc_profiles",
                "register_hvdc_profile",
            }
        ),
        "lcc": frozenset(
            {
                "plan_lcc_model", "build_lcc_model", "get_lcc_build_status",
                "validate_lcc_model",
            }
        ),
        "parametric_lcc": frozenset(
            {
                "derive_lcc_parameters", "audit_lcc_template",
                "plan_parametric_lcc_model", "build_parametric_lcc_model",
                "get_parametric_lcc_build_status", "validate_lcc_operating_modes",
            }
        ),
        "learning": frozenset(
            {
                "record_goal_failure", "review_improvement_backlog",
                "clear_learning_history",
            }
        ),
    }
)
COMPATIBILITY_TOOL_NAMES = frozenset().union(*TOOL_GROUPS.values())
FULL_TOOL_NAMES = COMPATIBILITY_TOOL_NAMES
```

In both installed-package probes, remove `PSCAD_MCP_TOOL_PROFILE` from the
child-process environment, import `FULL_TOOL_NAMES`, compare the set returned
by `create_server()` with the catalog, and print `len(FULL_TOOL_NAMES)` only
for diagnostics. Do not embed a count in an assertion or expected output
string. The
`FULL_TOOL_NAMES` alias deliberately keeps this Task 1 commit self-consistent;
Task 5 expands it together with the server registration.

- [ ] **Step 4: Run focused and package-script contract tests**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_tool_catalog.py tests/test_verify_package_script.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py tests/test_install_smoke.py
```

Expected: PASS; the wheel smoke test remains skipped without
`PSCAD_MCP_SMOKE_WHEEL`.

- [ ] **Step 5: Commit the inventory root cause**

```powershell
git add pscad_mcp/tools/catalog.py scripts/verify_package.ps1 tests/test_tool_catalog.py tests/test_verify_package_script.py tests/test_install_smoke.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py
git commit -m "fix: derive package inventory from one catalog"
```

---

### Task 2: Repository Hygiene And One CI Workflow

**Files:**
- Create: `tests/test_repository_hygiene.py`
- Modify: `.github/workflows/ci.yml`
- Delete: `.github/workflows/windows-ci.yml`
- Modify: `pyproject.toml`
- Modify: `tests/test_delivery_hardening.py`
- Remove from Git: the 14 tracked `*.pyc` files reported by `git ls-files`

- [ ] **Step 1: Write failing hygiene tests**

```python
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[1]


def _tracked(pattern: str) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", pattern], cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def test_repository_tracks_no_python_bytecode():
    assert _tracked("*.pyc") == []


def test_repository_tracks_no_cache_or_temporary_worktree_artifacts():
    tracked = _tracked("*")
    assert not any("__pycache__" in path.split("/") for path in tracked)
    assert not any(
        {".pytest_cache", ".ruff_cache", ".mypy_cache"} & set(path.split("/"))
        for path in tracked
    )
    assert not any(path.startswith(".worktrees/") for path in tracked)


def test_repository_has_one_ci_workflow():
    workflow_root = ROOT / ".github" / "workflows"
    workflows = sorted(
        [*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")]
    )
    assert [path.name for path in workflows] == ["ci.yml"]


def test_ci_covers_declared_python_range_and_catalog_parity():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
        assert f'"{version}"' in text
    assert "scripts\\verify_package.ps1" in text
    assert "ruff check" in text
    assert "git ls-files" in text
    for forbidden in (
        "*.pyc", "*__pycache__*", "*.pytest_cache*", "*.ruff_cache*",
        "*.mypy_cache*", ".worktrees/*",
    ):
        assert forbidden in text
    assert "== 83" not in text
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_repository_hygiene.py tests/test_delivery_hardening.py
```

Expected: FAIL because two workflows and 14 tracked bytecode files exist and
the matrix stops at Python 3.12.

- [ ] **Step 3: Consolidate CI and remove tracked artifacts**

Keep `.github/workflows/ci.yml` as the sole workflow. Use the 3.10-3.14 matrix,
install `.[dev]`, run pytest, `scripts\verify_package.ps1`, `compileall`,
`pip check`, and:

```yaml
      - name: Run correctness lint
        run: python -m ruff check --select E9,F63,F7,F82 pscad_mcp tests
      - name: Reject tracked generated artifacts
        shell: pwsh
        run: |
          $tracked = @(
            git ls-files '*.pyc'
            git ls-files '*__pycache__*'
            git ls-files '*.pytest_cache*'
            git ls-files '*.ruff_cache*'
            git ls-files '*.mypy_cache*'
            git ls-files '.worktrees/*'
          ) | Where-Object { $_ }
          if ($tracked) { throw "Tracked generated artifact detected." }
```

Add `ruff>=0.12,<1` to `project.optional-dependencies.dev`. Remove the duplicate
workflow and remove only the exact tracked bytecode files from the Git index;
do not delete or modify source files.

```powershell
git rm -- .github/workflows/windows-ci.yml
git rm -- `
  __pycache__/pscad_mcp_server.cpython-313.pyc `
  pscad_mcp/__pycache__/__init__.cpython-313.pyc `
  pscad_mcp/__pycache__/main.cpython-313.pyc `
  pscad_mcp/core/__pycache__/connection_manager.cpython-313.pyc `
  pscad_mcp/core/__pycache__/executor.cpython-313.pyc `
  pscad_mcp/tools/__pycache__/app_tools.cpython-313.pyc `
  pscad_mcp/tools/__pycache__/data_tools.cpython-313.pyc `
  pscad_mcp/tools/__pycache__/project_tools.cpython-313.pyc `
  pscad_mcp/tools/__pycache__/simset_tools.cpython-313.pyc `
  pscad_mcp/utils/__pycache__/doc_manager.cpython-313.pyc `
  tests/__pycache__/test_concurrency.cpython-313.pyc `
  tests/__pycache__/test_enhanced_tools.cpython-313.pyc `
  tests/__pycache__/test_protocol.cpython-313.pyc `
  tests/__pycache__/test_tools.cpython-313.pyc
```

- [ ] **Step 4: Verify hygiene and the narrow Ruff gate**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_repository_hygiene.py tests/test_delivery_hardening.py
& '.\.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 pscad_mcp tests
git ls-files '*.pyc'
```

Expected: both commands exit 0 and the final command prints nothing.

- [ ] **Step 5: Commit delivery hygiene**

```powershell
git add -u -- .github '*.pyc'
git add pyproject.toml tests/test_delivery_hardening.py
git add tests/test_repository_hygiene.py
git commit -m "chore: consolidate CI and reject tracked artifacts"
```

---

### Task 3: Complete Tool Descriptions And MCP Safety Annotations

**Files:**
- Modify: `pscad_mcp/tools/catalog.py`
- Modify: `pscad_mcp/tools/registration.py:168-291`
- Modify: `pscad_mcp/tools/hvdc_tools.py`
- Modify: `pscad_mcp/tools/lcc_tools.py`
- Modify: `pscad_mcp/tools/lcc_parametric_tools.py`
- Modify: `pscad_mcp/tools/learning_tools.py`
- Modify: `pscad_mcp/tools/project_tools.py`
- Modify: `pscad_mcp/tools/simset_tools.py`
- Modify: `pscad_mcp/tools/canvas_tools.py`
- Modify: `tests/test_tool_catalog.py`
- Modify: `tests/test_hvdc_tools.py`
- Modify: `tests/test_lcc_tools.py`
- Modify: `tests/test_lcc_parametric_tools.py`
- Modify: `tests/test_learning_tools.py`

- [ ] **Step 1: Write failing metadata tests**

```python
import pytest
from mcp.server.fastmcp import FastMCP

from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    TOOL_GROUPS,
    TOOL_SPECS,
)
from pscad_mcp.tools.project_tools import list_projects
from pscad_mcp.tools.registration import register_tool


def test_every_catalog_tool_has_bounded_description_and_annotations():
    assert set(TOOL_SPECS) == COMPATIBILITY_TOOL_NAMES
    for name, spec in TOOL_SPECS.items():
        assert spec.name == name
        assert name in TOOL_GROUPS[spec.group]
        assert 12 <= len(spec.description) <= 240, name
        assert isinstance(spec.read_only, bool), name
        assert isinstance(spec.destructive, bool), name
        assert isinstance(spec.idempotent, bool), name
        assert isinstance(spec.open_world, bool), name
        assert spec.limitation_code is None or (
            spec.limitation_code.isascii()
            and spec.limitation_code.replace("_", "").isalnum()
            and spec.limitation_code == spec.limitation_code.upper()
            and len(spec.limitation_code) <= 64
        )


def test_fastmcp_exposes_catalog_metadata_for_every_tool():
    by_name = {tool.name: tool for tool in create_server()._tool_manager.list_tools()}
    for name, spec in TOOL_SPECS.items():
        tool = by_name[name]
        assert tool.description == spec.description
        assert tool.annotations.readOnlyHint is spec.read_only
        assert tool.annotations.destructiveHint is spec.destructive
        assert tool.annotations.idempotentHint is spec.idempotent
        assert tool.annotations.openWorldHint is spec.open_world


def test_registration_rejects_duplicate_and_uncatalogued_primary_tools():
    server = FastMCP("catalog-contract")
    register_tool(server, list_projects, record_learning=False)
    with pytest.raises(ValueError, match="list_projects"):
        register_tool(server, list_projects, record_learning=False)

    async def uncatalogued_primary_tool() -> str:
        return "never registered"

    with pytest.raises(ValueError, match="uncatalogued_primary_tool"):
        register_tool(server, uncatalogued_primary_tool, record_learning=False)


def test_complex_inputs_have_model_facing_shape_examples():
    by_name = {tool.name: tool for tool in create_server()._tool_manager.list_tools()}
    assert "changes" in by_name["run_hvdc_scenario"].parameters[
        "properties"
    ]["scenario"]["description"]
    assert "base_mva" in by_name["derive_lcc_parameters"].parameters[
        "properties"
    ]["request"]["description"]
    assert "controlgroup" in by_name["set_simulation_task_parameters"].parameters[
        "properties"
    ]["parameters"]["description"]
```

Add focused assertions that `run_hvdc_scenario` is mutating and non-idempotent,
`delete_component` is destructive, `inspect_hvdc_project` is read-only, and
`clear_learning_history` is destructive. Assert the existing fixed LCC build
boundary explicitly:

```python
lcc_build = TOOL_SPECS["build_lcc_model"]
assert lcc_build.backend_support == frozenset({"legacy"})
assert lcc_build.limitation_code == "LCC_BUILD_UNAVAILABLE"
```

- [ ] **Step 2: Run metadata tests and verify RED**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_tool_catalog.py tests/test_hvdc_tools.py tests/test_lcc_tools.py tests/test_lcc_parametric_tools.py tests/test_learning_tools.py
```

Expected: FAIL because `TOOL_SPECS` and FastMCP annotations are absent and 23
domain/learning wrappers have no descriptions.

- [ ] **Step 3: Implement immutable metadata**

Add:

```python
from dataclasses import dataclass
from mcp.types import ToolAnnotations


@dataclass(frozen=True)
class ToolSpec:
    name: str
    group: str
    description: str
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool
    backend_support: frozenset[str] = frozenset({"legacy", "modern"})
    limitation_code: str | None = None

    def annotations(self) -> ToolAnnotations:
        return ToolAnnotations(
            title=self.name.replace("_", " ").title(),
            readOnlyHint=self.read_only,
            destructiveHint=self.destructive,
            idempotentHint=self.idempotent,
            openWorldHint=self.open_world,
        )
```

Populate an immutable `COMPATIBILITY_TOOL_SPECS` mapping with one `ToolSpec`
for every name in `COMPATIBILITY_TOOL_NAMES`, then initially set
`TOOL_SPECS = COMPATIBILITY_TOOL_SPECS`. Reuse the exact
existing generic docstring sentence as the catalog description. Add explicit
12-240 character descriptions to the 23 wrappers that currently lack one.
Classify getters, list operations, inspections, audits, validations, analyses,
comparisons, derivations, planning, and status reads as read-only. Classify
delete/remove/clear/quit operations as destructive. Mark simulation runs,
build starts, creation, mutation, registration, synchronization, repair, and
recording as non-idempotent unless the operation is an exact setter with a
verified postcondition. Mark PSCAD and filesystem operations open-world and
pure local catalog/learning inspection closed-world. Set `backend_support` to
an empty set for operations that are entirely server-local, and attach a
bounded uppercase `limitation_code` only where the repository already has a
documented backend limitation; do not infer support from missing real PSCAD
5.x acceptance evidence.

Use `typing.Annotated` with `pydantic.Field(description=...)` for the existing
complex `dict[str, Any]` inputs in project settings, component parameters,
simulation task parameters, canvas creation, HVDC scenarios, parametric LCC
requests, and operating-mode events. Each description names the accepted
nested keys and includes one compact JSON example. Add description metadata
only: do not add `Field` constraints, new Pydantic models, coercion, or runtime
validation beyond the existing service parsers.

Before learning registration, resolve the function name in `TOOL_SPECS` and
check a private registered-name set attached to the FastMCP instance. Raise a
bounded `ValueError` naming only the function when the spec is absent or the
name is already present. Add the name to the set only after FastMCP
registration succeeds. Change `_register_with_original_result` to call:

```python
spec = TOOL_SPECS[guarded.__name__]
mcp.add_tool(
    guarded,
    description=spec.description,
    annotations=spec.annotations(),
)
```

Catalog lookup errors must name only the missing function name and fail server
construction; do not silently register an undocumented primary tool.

- [ ] **Step 4: Run metadata and registration regression tests**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_tool_catalog.py tests/test_tool_inventory.py tests/test_tools.py tests/test_hvdc_tools.py tests/test_lcc_tools.py tests/test_lcc_parametric_tools.py tests/test_learning_tools.py
```

Expected: PASS with the same 83 names, parameter names, types, and defaults;
schema changes are limited to additive parameter descriptions.

- [ ] **Step 5: Commit tool metadata**

```powershell
git add pscad_mcp/tools tests/test_tool_catalog.py tests/test_hvdc_tools.py tests/test_lcc_tools.py tests/test_lcc_parametric_tools.py tests/test_learning_tools.py
git commit -m "feat: expose complete MCP tool metadata"
```

---

### Task 4: Optional Tool Profiles

**Files:**
- Modify: `pscad_mcp/tools/catalog.py`
- Modify: `pscad_mcp/tools/registration.py`
- Modify: `pscad_mcp/main.py`
- Create: `tests/test_tool_profiles.py`
- Modify: `tests/test_learning_registration.py`
- Modify: `tests/test_tool_catalog.py`
- Modify: `tests/test_tool_inventory.py`
- Modify: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write failing profile tests**

```python
import pytest

from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
    parse_tool_profile,
)


def _names(server):
    return {tool.name for tool in server._tool_manager.list_tools()}


def test_unset_profile_preserves_the_compatibility_inventory():
    names = _names(create_server(environ={}))
    assert names == COMPATIBILITY_TOOL_NAMES == FULL_TOOL_NAMES


def test_core_profile_is_explicitly_smaller():
    names = _names(create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "core"}))
    assert names == TOOL_GROUPS["core"]


def test_invalid_profile_does_not_echo_the_value():
    secret = "SECRET_PROFILE_VALUE"
    with pytest.raises(ValueError) as raised:
        parse_tool_profile({"PSCAD_MCP_TOOL_PROFILE": secret})
    assert str(raised.value) == "INVALID_TOOL_PROFILE: PSCAD_MCP_TOOL_PROFILE"
    assert secret not in str(raised.value)


@pytest.mark.parametrize("raw", ["", " , ", "core,unknown"])
def test_empty_or_unknown_profile_is_rejected(raw):
    with pytest.raises(
        ValueError,
        match=r"^INVALID_TOOL_PROFILE: PSCAD_MCP_TOOL_PROFILE$",
    ):
        parse_tool_profile({"PSCAD_MCP_TOOL_PROFILE": raw})


def test_profile_normalizes_whitespace_case_order_and_duplicates():
    profile = parse_tool_profile(
        {"PSCAD_MCP_TOOL_PROFILE": " HVDC, core,CORE "}
    )
    assert profile.label == "core,hvdc"
    assert profile.groups == frozenset({"core", "hvdc"})
```

Add a learning-recorder assertion that inactive group names are never
registered when `PSCAD_MCP_TOOL_PROFILE=core`.

- [ ] **Step 2: Run focused profile tests and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_tool_profiles.py tests/test_learning_registration.py
```

Expected: FAIL because profile parsing and `create_server(environ=...)` do not
exist and all groups are always registered.

- [ ] **Step 3: Implement profile parsing and pre-registration filtering**

```python
@dataclass(frozen=True)
class ToolProfile:
    label: str
    groups: frozenset[str]

    def includes(self, tool_name: str) -> bool:
        return any(tool_name in TOOL_GROUPS[group] for group in self.groups)


def parse_tool_profile(environ: Mapping[str, str]) -> ToolProfile:
    raw = environ.get("PSCAD_MCP_TOOL_PROFILE")
    if raw is None or raw.strip().casefold() == "full":
        return ToolProfile("full", frozenset(TOOL_GROUPS))
    groups = frozenset(
        part.strip().casefold() for part in raw.split(",") if part.strip()
    )
    if not groups or not groups <= TOOL_GROUPS.keys():
        raise ValueError("INVALID_TOOL_PROFILE: PSCAD_MCP_TOOL_PROFILE")
    return ToolProfile(",".join(sorted(groups)), groups)
```

Attach the profile to the FastMCP instance before calling the unchanged group
registration functions. `register_tool` checks it before learning or FastMCP
registration and returns for inactive tools. A bare FastMCP instance in
focused tests retains full behavior when the private profile attribute is
absent. Update exact default-inventory tests to call `create_server(environ={})`
so a developer's opt-in shell setting cannot make the test suite
nondeterministic. Use this factory boundary:

```python
def create_server(environ: Mapping[str, str] | None = None) -> FastMCP:
    profile = parse_tool_profile(os.environ if environ is None else environ)
    mcp = FastMCP("PSCAD-Modular", instructions=SERVER_INSTRUCTIONS)
    mcp._pscad_tool_profile = profile
    register_app_tools(mcp)
    register_project_tools(mcp)
    register_data_tools(mcp)
    register_simset_tools(mcp)
    register_creation_tools(mcp)
    register_canvas_tools(mcp)
    register_component_tools(mcp)
    register_hvdc_tools(mcp)
    register_lcc_tools(mcp)
    register_lcc_parametric_tools(mcp)
    register_learning_tools(mcp)
    return mcp
```

- [ ] **Step 4: Verify profile compatibility and isolation**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_tool_profiles.py tests/test_learning_registration.py tests/test_tool_catalog.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py
```

Expected: PASS; unset and `full` keep all 83 compatibility names, while a
selected profile neither registers nor records inactive tools.

- [ ] **Step 5: Commit the profile root cause**

```powershell
git add pscad_mcp/main.py pscad_mcp/tools/catalog.py pscad_mcp/tools/registration.py tests/test_tool_profiles.py tests/test_learning_registration.py tests/test_tool_catalog.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py
git commit -m "feat: add opt-in MCP tool profiles"
```

---

### Task 5: Always-On Capability Discovery

**Files:**
- Modify: `pscad_mcp/tools/catalog.py`
- Create: `pscad_mcp/tools/capability_tools.py`
- Modify: `pscad_mcp/tools/registration.py`
- Modify: `pscad_mcp/main.py`
- Create: `tests/test_capability_tools.py`
- Modify: `tests/test_tool_profiles.py`
- Modify: `tests/test_tool_catalog.py`
- Modify: `tests/test_tool_inventory.py`
- Modify: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write failing additive-inventory and capability tests**

```python
import json

from pscad_mcp.main import create_server
from pscad_mcp.tools.capability_tools import build_capability_payload
from pscad_mcp.tools.catalog import (
    COMPATIBILITY_TOOL_NAMES,
    FULL_TOOL_NAMES,
    TOOL_GROUPS,
    TOOL_SPECS,
    parse_tool_profile,
)


def _names(server):
    return {tool.name for tool in server._tool_manager.list_tools()}


def _state(payload, name):
    return next(item for item in payload["capabilities"] if item["name"] == name)


def test_capability_tool_is_additive_and_always_on():
    default_names = _names(create_server(environ={}))
    core_names = _names(create_server(environ={"PSCAD_MCP_TOOL_PROFILE": "core"}))
    assert default_names == FULL_TOOL_NAMES
    assert default_names - COMPATIBILITY_TOOL_NAMES == {"get_pscad_capabilities"}
    assert core_names == TOOL_GROUPS["core"] | {"get_pscad_capabilities"}
    assert set(TOOL_SPECS) == FULL_TOOL_NAMES


def test_capability_states_are_bounded_and_backend_aware():
    disconnected = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={"connected": False, "backend": None, "version": None},
    )
    assert _state(disconnected, "list_projects")["state"] == "unknown"
    assert _state(disconnected, "review_improvement_backlog")["state"] == "supported"

    legacy = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={"connected": True, "backend": "legacy", "version": "4.6.2"},
    )
    assert _state(legacy, "build_lcc_model")["state"] == "supported"

    modern = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={"connected": True, "backend": "modern", "version": "5.0.2"},
    )
    assert _state(modern, "build_lcc_model") == {
        "name": "build_lcc_model",
        "group": "lcc",
        "state": "unavailable",
        "limitation_code": "LCC_BUILD_UNAVAILABLE",
    }


def test_capability_payload_never_serializes_vendor_objects_or_raw_values():
    class VendorObject:
        def __repr__(self):
            return "SECRET_VENDOR_REPR"

    payload = build_capability_payload(
        profile=parse_tool_profile({}),
        registered_names=FULL_TOOL_NAMES,
        connection={
            "connected": True,
            "backend": VendorObject(),
            "version": "SECRET INVALID VERSION",
        },
    )
    encoded = json.dumps(payload)
    assert payload["connection"] == {
        "connected": False,
        "backend": None,
        "version": None,
    }
    assert "SECRET" not in encoded
```

The LCC limitation is taken from the repository's existing explicit modern
backend boundary, not inferred from missing licensed PSCAD 5.x evidence.

- [ ] **Step 2: Run capability tests and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_capability_tools.py tests/test_tool_profiles.py
```

Expected: FAIL because the module, additive catalog entry, and capability tool
do not exist.

- [ ] **Step 3: Expand the final catalog and forced registration contract**

```python
CAPABILITY_TOOL_NAME = "get_pscad_capabilities"
FULL_TOOL_NAMES = COMPATIBILITY_TOOL_NAMES | {CAPABILITY_TOOL_NAME}
TOOL_SPECS = MappingProxyType(
    {
        **COMPATIBILITY_TOOL_SPECS,
        CAPABILITY_TOOL_NAME: ToolSpec(
            name=CAPABILITY_TOOL_NAME,
            group="core",
            description="Discover the active PSCAD MCP profile and bounded backend capabilities.",
            read_only=True,
            destructive=False,
            idempotent=True,
            open_world=False,
            backend_support=frozenset(),
        ),
    }
)
```

Keep `TOOL_GROUPS["core"]` as the original compatibility group. Update catalog
tests to compare `TOOL_SPECS` with final `FULL_TOOL_NAMES` and treat the
always-on capability spec as the sole group-membership exception. Add
`force: bool = False` to `register_tool`; `force=True` bypasses profile
filtering only, never catalog or duplicate-name checks.

- [ ] **Step 4: Implement the bounded capability tool**

Create a closure whose async function is explicitly named
`get_pscad_capabilities`. It reads the current server name set and a bounded
connection snapshot. Server-local specs with empty `backend_support` are
`supported`; disconnected backend-dependent specs are `unknown`; a connected
backend absent from a spec's support set is `unavailable` with the existing
limitation code or `CAPABILITY_UNAVAILABLE`. Sort records by name and include
only `name`, `group`, `state`, and `limitation_code`.

Normalize backend and version through the existing identifier rules. A status
probe failure becomes an unknown connection. Never include vendor objects,
exception text, paths, or environment values. Return exactly:

```python
{
    "profile": profile.label,
    "registered_groups": sorted(profile.groups),
    "registered_tools": sorted(registered_names),
    "inactive_tools": sorted(FULL_TOOL_NAMES - registered_names),
    "connection": {"connected": connected, "backend": backend, "version": version},
    "capabilities": capability_records,
}
```

Register the closure after all compatibility groups with `force=True` and
`record_learning=False`.

- [ ] **Step 5: Verify final inventory, states, and package parity**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_capability_tools.py tests/test_tool_profiles.py tests/test_tool_catalog.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py tests/test_learning_registration.py tests/test_verify_package_script.py tests/test_install_smoke.py
```

Expected: PASS; the default inventory is the original 83 plus the capability
tool, `FULL_TOOL_NAMES` equals that final server set, and installed-package
probes derive parity from the expanded catalog without a numeric assertion.

- [ ] **Step 6: Commit capability discovery independently**

```powershell
git add pscad_mcp/main.py pscad_mcp/tools/catalog.py pscad_mcp/tools/capability_tools.py pscad_mcp/tools/registration.py tests/test_capability_tools.py tests/test_tool_profiles.py tests/test_tool_catalog.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py
git commit -m "feat: add bounded MCP capability discovery"
```

---

### Task 6: Idempotent Runtime Lifespan And Background-Task Shutdown

**Files:**
- Create: `pscad_mcp/runtime.py`
- Create: `tests/test_runtime_lifecycle.py`
- Modify: `pscad_mcp/main.py`
- Modify: `pscad_mcp/tools/hvdc_tools.py`
- Modify: `pscad_mcp/tools/lcc_tools.py`
- Modify: `pscad_mcp/tools/lcc_parametric_tools.py`
- Modify: `pscad_mcp/hvdc/service.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/service.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/parametric_service.py`
- Modify: `pscad_mcp/learning/service.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/core/connection_manager.py`
- Modify: `pscad_mcp/core/executor.py`
- Modify: `tests/test_executor_recovery.py`

- [ ] **Step 1: Write failing ordered-cleanup tests**

```python
import asyncio

from pscad_mcp.runtime import RuntimeLifecycle


def test_runtime_shutdown_is_ordered_idempotent_and_fail_contained():
    calls = []

    async def action(name, fail=False):
        calls.append(name)
        if fail:
            raise RuntimeError(name)
        return True

    runtime = RuntimeLifecycle(
        domain_shutdown=lambda: action("domain"),
        settlement_wait=lambda: action("settlement"),
        learning_close=lambda: action("learning", fail=True),
        connection_shutdown=lambda: action("connection"),
        executor_shutdown=lambda: calls.append("executor"),
        timeout_s=0.2,
    )
    first = asyncio.run(runtime.shutdown())
    second = asyncio.run(runtime.shutdown())

    assert calls == ["domain", "settlement", "learning", "connection", "executor"]
    assert first["code"] == "SHUTDOWN_INCOMPLETE"
    assert first["failures"] == [{"operation": "learning", "exception": "RuntimeError"}]
    assert second == first
```

Add async tests proving fixed and parametric builder task cancellation writes
`interrupted`, releases leases through existing `finally` blocks, and does not
initialize a service when its module singleton is `None`. Add backend tests
proving owned backends call `quit` while unowned backends call `disconnect`.
Add an executor test with one unsettled token proving the bounded settlement
wait returns `False`; in that state both the connection and executor shutdown
attempts raise a bounded `PendingSettlementError`, the owned backend is not
quit or disconnected, and the lifecycle summary names only operation labels
and exception type names. Capture logs and assert the secret exception message
is absent while later cleanup operations are still attempted.

- [ ] **Step 2: Run focused lifecycle tests and verify RED**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_runtime_lifecycle.py tests/test_executor_recovery.py tests/test_lcc_builder_service.py tests/test_lcc_parametric_service.py tests/test_hvdc_scenario_containment.py
```

Expected: FAIL because no runtime lifespan or service shutdown methods exist.

- [ ] **Step 3: Implement reusable bounded cancellation**

Each domain service adds `_closing = False`, rejects new work with its existing
conflict/error family after closing begins, and implements:

```python
async def shutdown(self, timeout_s: float = 5.0) -> None:
    self._closing = True
    tasks = tuple(task for task in self._tasks.values() if not task.done())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout_s,
        )
```

HVDC includes scenario, run, operation, and cleanup task registries. Mark each
non-terminal record `interrupted` before cancellation, then preserve its
existing containment and lease-release `finally` paths. Fixed and parametric
builders reject new builds after `_closing` is set using their existing
conflict error family. HVDC rejects new scenarios after closing begins.

Tool modules expose `shutdown_*_service()` functions that return immediately
when their singleton is `None` and clear singleton/backend references only
after shutdown. A runtime-level `shutdown_domain_services()` invokes HVDC,
fixed LCC, and parametric LCC shutdown in a fixed order and attempts all three
even when one fails.

- [ ] **Step 4: Implement learning, backend, and lifecycle closure**

Add `LearningService.close()` delegating to `LearningStore.close()` and
`LearningRuntime.close()` that closes only an already initialized service.
Add `PscadService.shutdown()` under the mutation lock: call `quit` for an owned
backend and `disconnect` otherwise, then clear `_backend`. Add
`RobustExecutor.wait_for_settlements(timeout_s)` using settlement-token
callbacks rather than blocking the event loop. Add `shutdown_if_settled()`
that raises `PendingSettlementError` without touching the worker when tokens
remain. `PSCADConnectionManager.shutdown_connection()` refuses to release a
backend while executor settlements remain, and `shutdown_executor()` delegates
to the guarded executor method. Its public `shutdown()` composes those methods
for direct callers without duplicating lifecycle closure.

`RuntimeLifecycle.shutdown()` attempts the five ordered actions shown in the
test: domain stop/cancellation, executor settlement wait, learning close,
connection release, and executor closure. It bounds async actions with
`asyncio.wait_for`, records only operation labels and exception type names,
logs the same bounded fields through the existing stderr logging handler, and
caches its result behind an async lock. A false settlement result becomes a
bounded settlement failure; connection and executor guards are still invoked
and preserve process ownership. Its `@asynccontextmanager` lifespan yields an
empty mapping and invokes shutdown in `finally`. Pass this lifespan to
`FastMCP(...)` in `create_server`.

- [ ] **Step 5: Verify lifecycle behavior and existing recovery contracts**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_runtime_lifecycle.py tests/test_executor_recovery.py tests/test_service_contract.py tests/test_hvdc_scenario_containment.py tests/test_lcc_builder_service.py tests/test_lcc_parametric_service.py
```

Expected: PASS with no unhandled-task warnings.

- [ ] **Step 6: Commit runtime lifecycle**

```powershell
git add pscad_mcp/runtime.py pscad_mcp/main.py pscad_mcp/tools/hvdc_tools.py pscad_mcp/tools/lcc_tools.py pscad_mcp/tools/lcc_parametric_tools.py pscad_mcp/hvdc/service.py pscad_mcp/hvdc/builders/lcc/service.py pscad_mcp/hvdc/builders/lcc/parametric_service.py pscad_mcp/learning/service.py pscad_mcp/core/service.py pscad_mcp/core/connection_manager.py pscad_mcp/core/executor.py tests/test_runtime_lifecycle.py tests/test_executor_recovery.py tests/test_lcc_builder_service.py tests/test_lcc_parametric_service.py tests/test_hvdc_scenario_containment.py
git commit -m "feat: close MCP runtime resources deterministically"
```

---

### Task 7: Lazy Local Documentation And MCP Resources

**Files:**
- Create: `tests/test_documentation_runtime.py`
- Modify: `pscad_mcp/utils/doc_manager.py`
- Modify: `pscad_mcp/tools/app_tools.py`
- Modify: `pscad_mcp/main.py`
- Modify: `.gitignore`
- Modify: `.github/workflows/ci.yml`
- Modify: `NOTICE`
- Modify: `tests/test_repository_hygiene.py`
- Remove from Git: `docs/raw/*`, `docs/md/*`

- [ ] **Step 1: Write failing documentation-boundary tests**

```python
import os
from pathlib import Path

from pscad_mcp.utils.doc_manager import DocumentationManager


def test_manager_construction_does_not_write(tmp_path):
    root = tmp_path / "generated"
    manager = DocumentationManager(root)
    assert manager.base_dir == root.resolve()
    assert not root.exists()


def test_localappdata_default_is_lazy(tmp_path):
    manager = DocumentationManager.from_environ({"LOCALAPPDATA": str(tmp_path)})
    assert manager.base_dir == (tmp_path / "pscad-mcp" / "docs").resolve()
    assert not manager.base_dir.exists()


def test_generated_markdown_redacts_source_path(tmp_path):
    source = tmp_path / "private-user" / "module.py"
    manager = DocumentationManager(tmp_path / "docs")
    analyzer = type("Analyzer", (), {"file_path": str(source), "classes": {}, "functions": {}})()
    rendered = manager._extract_enriched_markdown("mhi.pscad.fake", "NAME\n", analyzer)
    assert str(source) not in rendered
    assert "mhi.pscad.fake" in rendered


def test_atomic_write_replaces_destination_without_temp_residue(tmp_path, monkeypatch):
    target = tmp_path / "module.md"
    target.write_text("old", encoding="utf-8")
    replacements = []
    real_replace = os.replace

    def record_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", record_replace)
    DocumentationManager._atomic_write(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert replacements[0][1] == target
    assert list(tmp_path.iterdir()) == [target]


def test_invalid_documentation_override_names_only_the_setting():
    secret = "SECRET_RELATIVE_PATH"
    manager = DocumentationManager.from_environ({"PSCAD_MCP_DOCUMENTATION_DIR": secret})
    assert manager.issue == "PSCAD_MCP_DOCUMENTATION_DIR"
    assert secret not in repr(manager)
```

Also assert `manager.sync()`, `list_documentation()`, and
`read_documentation()` surface `DOCUMENTATION_CONFIG_INVALID` through the
existing bounded backend-error envelope and never echo the invalid override.
Add a subprocess import test with an unused `LOCALAPPDATA` root to prove
importing `pscad_mcp.main` creates no documentation directories. Add an async
wrapper test patching `asyncio.to_thread` and a server test that reads the
registered resource template `pscad-docs://modules/{module_name}` through the
FastMCP resource manager.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_documentation_runtime.py
```

Expected: FAIL because construction creates directories, source paths are
rendered, configuration parsing is absent, and no MCP resource is registered.

- [ ] **Step 3: Make documentation lazy, local, redacted, and atomic**

Refactor paths to `Path`. Constructor resolution performs no `mkdir`. The
default is `%LOCALAPPDATA%/pscad-mcp/docs`; when unavailable, use
`Path.home() / ".local" / "state" / "pscad-mcp" / "docs"`. An explicit
override must be absolute. Store only the setting name as the manager issue;
operations raise `BackendError("DOCUMENTATION_CONFIG_INVALID", ...)` with the
setting name in bounded details and no raw value.

At `sync()` start, create `md` and `raw`. Replace direct writes with an atomic
helper using `NamedTemporaryFile` in the destination directory, flush,
`os.fsync`, and `os.replace`, deleting only its own surviving temporary file.
Remove the source path line from generated Markdown. Resolve the installed
distribution version with `importlib.metadata.version("pscad-mcp")`, falling
back to the package's existing version metadata without exposing a filesystem
location, and include only module name and package version in the generated
heading.

Change `sync_documentation` to `return await asyncio.to_thread(doc_manager.sync)`.
Register:

```python
def register_documentation_resources(mcp: FastMCP) -> None:
    @mcp.resource(
        "pscad-docs://modules/{module_name}",
        name="pscad_documentation_module",
        description="Read one locally generated PSCAD API documentation module.",
        mime_type="text/markdown",
    )
    async def documentation_module(module_name: str) -> str:
        return await read_documentation(module_name)
```

- [ ] **Step 4: Remove generated snapshots from tracking safely**

First verify targets:

```powershell
$generatedDocs = @(git ls-files docs/raw docs/md)
if ($generatedDocs.Count -ne 62) {
    throw "Expected 62 tracked generated documentation snapshots."
}
$generatedDocs
```

Expected: exactly the generated reference snapshots under those two
directories. Remove those tracked files, add `docs/raw/` and `docs/md/` to
`.gitignore`, and update `NOTICE` to say the directories are generated locally
rather than distributed. Do not remove `docs/superpowers`, `docs/zh-CN`, or
other authored documentation. Extend `tests/test_repository_hygiene.py` and
the CI artifact check with `docs/raw/*` and `docs/md/*` only in this task, after
their tracked files are removed, so every root-cause commit remains green.

```powershell
git rm -r -- docs/raw docs/md
```

- [ ] **Step 5: Verify documentation behavior and package imports**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_documentation_runtime.py tests/test_repository_hygiene.py tests/test_install_smoke.py tests/test_tool_backend_matrix.py
git ls-files docs/raw docs/md
```

Expected: tests pass and the final command prints nothing.

- [ ] **Step 6: Commit documentation boundary**

```powershell
git add -u docs/raw docs/md NOTICE
git add .gitignore .github/workflows/ci.yml pscad_mcp/utils/doc_manager.py pscad_mcp/tools/app_tools.py pscad_mcp/main.py tests/test_documentation_runtime.py tests/test_repository_hygiene.py
git commit -m "feat: serve PSCAD docs from lazy local state"
```

---

### Task 8: Compatible Pagination For Large Results

**Files:**
- Create: `pscad_mcp/tools/pagination.py`
- Create: `tests/test_tool_pagination.py`
- Modify: `pscad_mcp/tools/app_tools.py`
- Modify: `pscad_mcp/tools/project_tools.py`
- Modify: `pscad_mcp/tools/creation_tools.py`
- Modify: `pscad_mcp/tools/canvas_tools.py`
- Modify: `tests/test_tools.py`
- Modify: `tests/test_component_service_boundary.py`
- Modify: `tests/test_canvas_service_boundary.py`
- Modify: `tests/test_project_tool_service_boundary.py`
- Modify: `tests/test_creation_tools.py`
- Modify: `tests/test_canvas_tools.py`

- [ ] **Step 1: Write failing default-compatibility and slice tests**

```python
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.main import create_server
from pscad_mcp.tools.project_tools import list_projects


def test_list_projects_keeps_default_result_and_supports_slices():
    values = [{"name": f"case-{index}"} for index in range(5)]
    with patch("pscad_mcp.tools.project_tools.pscad_manager") as manager:
        manager.service.list_projects = AsyncMock(return_value=values)
        assert asyncio.run(list_projects()) == values
        assert asyncio.run(list_projects(offset=1, limit=2)) == values[1:3]


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, None), (0, 0), (0, 1001), (True, 1)],
)
def test_list_projects_rejects_invalid_slice_bounds(offset, limit):
    with pytest.raises(BackendError) as raised:
        asyncio.run(list_projects(offset=offset, limit=limit))
    assert raised.value.code == "INVALID_ARGUMENT"


def test_registered_tool_does_not_coerce_boolean_offset_to_one():
    server = create_server(environ={})
    tool = server._tool_manager.get_tool("list_projects")
    with patch("pscad_mcp.tools.project_tools.pscad_manager") as manager:
        manager.service.list_projects = AsyncMock(return_value=[])
        result = asyncio.run(tool.run({"offset": True}))
    assert result["error"]["code"] == "INVALID_ARGUMENT"
```

Add equivalent tests for `find_components`, `get_project_definitions`,
`list_canvas_components`, `list_documentation`, and string slicing in
`read_documentation`. Assert direct calls without new arguments are identical
to pre-change results. Read each of these documentation URIs through the
FastMCP resource manager and compare it with the corresponding direct call:

```python
"pscad-docs://modules/mhi.pscad.types"
"pscad-docs://modules/mhi.pscad.types?offset=10"
"pscad-docs://modules/mhi.pscad.types?max_chars=100"
"pscad-docs://modules/mhi.pscad.types?offset=10&max_chars=100"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_tool_pagination.py
```

Expected: FAIL because wrappers do not accept `offset`, `limit`, or
`max_chars`.

- [ ] **Step 3: Add one shared validator and preserve result types**

```python
from typing import TypeVar

from pydantic import SkipValidation

from ..core.backend.base import BackendError

T = TypeVar("T")
PaginationOffset = SkipValidation[int]
PaginationLimit = SkipValidation[int | None]


def slice_items(values: list[T], offset: int, limit: int | None, operation: str) -> list[T]:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise BackendError("INVALID_ARGUMENT", "offset must be a non-negative integer.", "service", operation)
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000
    ):
        raise BackendError("INVALID_ARGUMENT", "limit must be between 1 and 1000.", "service", operation)
    return values[offset:] if limit is None else values[offset:offset + limit]


def slice_text(value: str, offset: int, max_chars: int | None, operation: str) -> str:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise BackendError("INVALID_ARGUMENT", "offset must be a non-negative integer.", "service", operation)
    if max_chars is not None and (
        isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 100000
    ):
        raise BackendError("INVALID_ARGUMENT", "max_chars must be between 1 and 100000.", "service", operation)
    return value[offset:] if max_chars is None else value[offset:offset + max_chars]
```

Add optional parameters only at the end of each existing signature. Fetch the
same full result as before, then call the helper. Do not change sorting or
backend calls in the default path. Annotate the new tool parameters with
`PaginationOffset` and `PaginationLimit`: `SkipValidation` preserves the
integer/null JSON Schema while preventing Pydantic from coercing `True` to
`1`, leaving the shared helper responsible for the stable `INVALID_ARGUMENT`
contract. Resource template functions keep ordinary `int` annotations so URI
strings are parsed before reaching the same helper.

In `register_documentation_resources`, register the three query templates
before the unbounded template because FastMCP 1.29 matches templates in
registration order and a path placeholder can otherwise consume the query.
Use exact function signatures matching every URI placeholder:

```python
@mcp.resource("pscad-docs://modules/{module_name}?offset={offset}&max_chars={max_chars}")
async def documentation_slice(module_name: str, offset: int, max_chars: int) -> str:
    return await read_documentation(module_name, offset=offset, max_chars=max_chars)

@mcp.resource("pscad-docs://modules/{module_name}?offset={offset}")
async def documentation_from_offset(module_name: str, offset: int) -> str:
    return await read_documentation(module_name, offset=offset)

@mcp.resource("pscad-docs://modules/{module_name}?max_chars={max_chars}")
async def documentation_max_chars(module_name: str, max_chars: int) -> str:
    return await read_documentation(module_name, max_chars=max_chars)
```

Keep the Task 7 unbounded template last. Validate resource query values through
the same `slice_text` helper so tool and resource reads have identical content
bounds.

- [ ] **Step 4: Verify wrappers, schemas, and backend boundaries**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_tool_pagination.py tests/test_tools.py tests/test_component_service_boundary.py tests/test_canvas_service_boundary.py tests/test_project_tool_service_boundary.py tests/test_creation_tools.py tests/test_canvas_tools.py
```

Expected: PASS and result types remain lists or strings.

- [ ] **Step 5: Commit compatible bounds**

```powershell
git add pscad_mcp/tools/pagination.py pscad_mcp/tools/app_tools.py pscad_mcp/tools/project_tools.py pscad_mcp/tools/creation_tools.py pscad_mcp/tools/canvas_tools.py tests/test_tool_pagination.py tests/test_tools.py tests/test_component_service_boundary.py tests/test_canvas_service_boundary.py tests/test_project_tool_service_boundary.py tests/test_creation_tools.py tests/test_canvas_tools.py
git commit -m "feat: bound large tool results compatibly"
```

---

### Task 9: User Documentation, Configuration, And Unreleased Status

**Files:**
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`
- Modify: `config.example.toml`
- Modify: `tests/test_config_example.py`
- Modify: `tests/test_changelog.py`
- Modify: `tests/test_delivery_hardening.py`

- [ ] **Step 1: Write failing documentation contract tests**

Add assertions requiring both languages to describe:

```python
required = (
    "get_pscad_capabilities",
    "PSCAD_MCP_TOOL_PROFILE",
    "PSCAD_MCP_DOCUMENTATION_DIR",
    "84",
    "offset",
    "limit",
    "pscad-docs://modules/",
    "PSCAD 5.x",
    "contract-tested",
)
```

The configuration test requires `PSCAD_MCP_TOOL_PROFILE = 'full'` and omits a
machine-specific documentation directory by default. The changelog test
requires `horizontal hardening`, `tool annotations`, `runtime lifecycle`, and
`local documentation` under Unreleased.

- [ ] **Step 2: Run documentation tests and verify RED**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_config_example.py tests/test_changelog.py tests/test_delivery_hardening.py
```

Expected: FAIL because the new tool, settings, resource, and inventory are not
documented.

- [ ] **Step 3: Update English, Chinese, config, and changelog text**

Document 84 as the current-branch inventory: 83 compatibility tools plus one
capability tool. Explain that `full` is the unchanged default, profile
selection is opt-in, invalid values fail startup, pagination is optional, and
generated documentation lives in local state. Preserve the explicit PSCAD 5.x
contract-tested-only statement and do not add a real acceptance PASS.

Add only this portable environment default:

```toml
PSCAD_MCP_TOOL_PROFILE = 'full'
```

Do not place an absolute documentation path in the example.

- [ ] **Step 4: Run docs contracts and complete tool inventory tests**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_config_example.py tests/test_changelog.py tests/test_delivery_hardening.py tests/test_tool_inventory.py tests/test_tool_backend_matrix.py
```

Expected: PASS.

- [ ] **Step 5: Commit user-facing contracts**

```powershell
git add README.md docs/zh-CN/README.md CHANGELOG.md config.example.toml tests/test_config_example.py tests/test_changelog.py tests/test_delivery_hardening.py
git commit -m "docs: describe compatible MCP hardening"
```

---

### Task 10: Installed-Wheel And Full Non-Licensed Verification

**Files:**
- Modify only files required by a reproduced verification failure
- Do not modify generated `improvement-backlog.md`
- Do not enable licensed acceptance variables

- [ ] **Step 1: Verify the installed wheel in isolation**

Run:

```powershell
& '.\scripts\verify_package.ps1'
```

Expected: exit 0; the isolated installed server name set equals its installed
catalog and the packaged LCC asset set loads.

- [ ] **Step 2: Run the complete default suite**

Run:

```powershell
$env:PYTHONPATH='.;tests'
& '.\.venv\Scripts\python.exe' -m pytest -q
```

Expected: all non-licensed tests pass and licensed tests retain their skips.

- [ ] **Step 3: Run static and repository checks**

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m compileall -q pscad_mcp tests
& '.\.venv\Scripts\python.exe' -m ruff check --select E9,F63,F7,F82 pscad_mcp tests
& '.\.venv\Scripts\python.exe' -m pip check
git diff --check
git ls-files '*.pyc'
git ls-files docs/raw docs/md
git status --short --branch
```

Expected: every command exits 0; tracked-bytecode and generated-document
commands print nothing; after any reproduced verification fix is committed,
status is clean on `codex/mcp-horizontal-hardening`.

- [ ] **Step 4: Audit spec coverage and active-branch compatibility**

Compare `FULL_TOOL_NAMES` with the exact current branch server set. Record that
Blueprint Builder, unified topology diagnostics, and MMC tools must receive
catalog entries when those branches are integrated. Confirm no default call
to the original 83 tools changes parameter defaults or result types.

- [ ] **Step 5: Commit only reproduced final-gate fixes**

If verification exposed a reproducible root cause, add its failing regression
test, observe RED, implement the smallest correction, rerun the affected and
full checks, and commit that root cause alone. If no verification failure is
present, create no empty commit.

Real PSCAD 5.x acceptance remains `needs_evidence`; do not create a speculative
patch or acceptance report.
