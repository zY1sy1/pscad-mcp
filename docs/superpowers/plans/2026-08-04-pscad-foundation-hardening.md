# PSCAD MCP Foundation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the released package version self-consistent and make filesystem access fail closed unless a workspace or explicit development override is configured, without changing the existing 60-tool contract.

**Architecture:** Keep `pyproject.toml` as the release version source, add independent metadata/install smoke checks, and extend `PathPolicy` with an explicit unscoped-path mode. Pass path-policy failures through the existing `BackendError`/FastMCP serialization boundary. Update documentation and Windows CI only after the behavior is protected by tests.

**Tech Stack:** Python 3.10+, setuptools, FastMCP 1.x, pytest/unittest, PowerShell CI.

---

### Task 1: Establish baseline and test fixtures

**Files:**
- Modify: `tests/test_path_safety.py`
- Modify: `tests/test_packaging_metadata.py`
- Create: `tests/test_install_smoke.py`

- [ ] **Step 1: Run the current focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py tests/test_packaging_metadata.py tests/test_tool_inventory.py
```

Expected: the existing tests pass; this records the pre-change baseline before adding new assertions.

- [ ] **Step 2: Add failing path-policy tests**

Add tests covering the new contract:

```python
def test_unconfigured_workspace_rejects_relative_path():
    policy = PathPolicy(workspace_root=None, allow_unscoped_paths=False)
    with self.assertRaises(WorkspaceNotConfiguredError):
        policy.resolve("cases/demo.pscx")


def test_unconfigured_workspace_rejects_absolute_path():
    policy = PathPolicy(workspace_root=None, allow_unscoped_paths=False)
    with self.assertRaises(WorkspaceNotConfiguredError):
        policy.resolve(str(Path.cwd() / "cases" / "demo.pscx"))


def test_explicit_unscoped_mode_preserves_development_resolution():
    policy = PathPolicy(workspace_root=None, allow_unscoped_paths=True)
    assert policy.resolve("cases/demo.pscx") == (Path.cwd() / "cases" / "demo.pscx").resolve()


def test_child_resolution_stays_contained_in_all_modes(tmp_path):
    policy = PathPolicy(workspace_root=None, allow_unscoped_paths=True)
    with self.assertRaises(ValueError):
        policy.resolve_child(str(tmp_path), "../escape.pscx")
```

The test imports the not-yet-created `WorkspaceNotConfiguredError`, so it must fail because the new API is absent.

- [ ] **Step 3: Add failing version/install assertions**

Extend `tests/test_packaging_metadata.py` to compare the TOML version and runtime package version. Add `tests/test_install_smoke.py` with a subprocess-level test that accepts a wheel path through `PSCAD_MCP_SMOKE_WHEEL`, installs it into a temporary target directory, imports `pscad_mcp`, and creates a server with 60 unique tools. Skip only when the wheel variable is not set, so normal unit runs do not require a prebuilt artifact.

- [ ] **Step 4: Run the new focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py tests/test_packaging_metadata.py tests/test_install_smoke.py
```

Expected: failures identify the missing `allow_unscoped_paths` behavior and missing install-smoke implementation, not syntax errors in the tests.

### Task 2: Implement fail-closed PathPolicy

**Files:**
- Modify: `pscad_mcp/core/path_policy.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `tests/test_path_safety.py`
- Modify: `tests/test_service_contract.py`

- [ ] **Step 1: Add the minimal policy exception and constructor flag**

Define `WorkspaceNotConfiguredError(ValueError)` in `path_policy.py`. Extend the constructor to accept `allow_unscoped_paths: bool | None = None`; when omitted, parse `PSCAD_MCP_ALLOW_UNSCOPED_PATHS` using the existing true/false vocabulary and default to `False`.

- [ ] **Step 2: Gate `resolve()` when no workspace is configured**

At the start of `resolve()`, if `workspace_root is None` and `allow_unscoped_paths` is false, raise `WorkspaceNotConfiguredError` with the candidate path and the environment variable name. Keep suffix and existence checks unchanged for configured or explicitly unscoped modes.

- [ ] **Step 3: Preserve `resolve_child()` containment**

Do not bypass the existing base-directory containment check. Add only the minimum validation needed to preserve the child-directory invariant when unscoped mode is enabled.

- [ ] **Step 4: Normalize path-policy failures at the service boundary**

Catch `WorkspaceNotConfiguredError` in the existing path-resolution helper(s) in `PscadService` and raise `BackendError` with:

```python
BackendError(
    "WORKSPACE_NOT_CONFIGURED",
    "PSCAD_MCP_WORKSPACE must be configured before file operations.",
    "service",
    operation,
    {"environment": "PSCAD_MCP_WORKSPACE", "allow_override": "PSCAD_MCP_ALLOW_UNSCOPED_PATHS"},
)
```

Do not catch unrelated `ValueError`, `FileNotFoundError`, or backend failures.

- [ ] **Step 5: Add service-level error tests and run them**

Add a test invoking a file-path service operation without workspace configuration and assert the serialized error code is `WORKSPACE_NOT_CONFIGURED`. Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py tests/test_service_contract.py tests/test_protocol.py
```

Expected: PASS.

### Task 3: Keep explicit workspace and development compatibility

**Files:**
- Modify: `tests/test_path_safety.py`
- Modify: `tests/test_pscad_config.py` if environment parsing is shared
- Modify: `pscad_mcp/core/path_policy.py` only if RED tests require a small refactor

- [ ] **Step 1: Add environment parsing tests**

Cover unset, `true`, `false`, `1`, `0`, and invalid values for `PSCAD_MCP_ALLOW_UNSCOPED_PATHS`. Invalid values must fail during policy construction with an actionable `ValueError`.

- [ ] **Step 2: Add configured workspace regression tests**

Verify that a configured workspace still resolves relative paths, rejects traversal outside the root, rejects wrong suffixes, and rejects symlink/junction escape where supported by the existing test environment.

- [ ] **Step 3: Run all path and safety tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py tests/test_safety_contract.py tests/test_project_tool_service_boundary.py
```

Expected: PASS with the existing destructive-operation safety contract unchanged.

### Task 4: Add version consistency and install smoke verification

**Files:**
- Modify: `tests/test_packaging_metadata.py`
- Create: `tests/test_install_smoke.py`
- Modify: `.github/workflows/windows-ci.yml`
- Modify: `pyproject.toml` only if build metadata needs a missing test dependency

- [ ] **Step 1: Add a build-and-install helper script**

Create `scripts/verify_package.ps1` that:

1. creates a temporary directory;
2. runs `python -m pip wheel . --no-deps --wheel-dir <temp>`;
3. installs the generated wheel into a second temporary target directory;
4. runs a Python one-liner with `PYTHONPATH` pointing at that target;
5. asserts package version `0.2.0` and exactly 60 unique tools;
6. removes only the two generated temporary directories in a `finally` block.

The script must use explicit resolved temporary paths and must not touch the repository `.venv`.

- [ ] **Step 2: Run the helper against the working tree**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_package.ps1
```

Expected: exit code 0 and output showing the installed version and `60` unique tools.

- [ ] **Step 3: Add the helper to Windows CI**

Add a CI step after dependency installation and before the full test run:

```yaml
- name: Verify built package
  shell: pwsh
  run: .\scripts\verify_package.ps1
```

- [ ] **Step 4: Run packaging and protocol tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_packaging_metadata.py tests/test_install_smoke.py tests/test_protocol.py tests/test_tool_inventory.py
```

Expected: PASS.

### Task 5: Update user-facing configuration documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `config.example.toml`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_config_example.py`

- [ ] **Step 1: Add the environment variable to the example config**

Add:

```toml
PSCAD_MCP_ALLOW_UNSCOPED_PATHS = 'false'
```

Keep `PSCAD_MCP_WORKSPACE` as the recommended required production setting and use placeholder paths only.

- [ ] **Step 2: Document fail-closed behavior and recovery**

Explain that file operations return `WORKSPACE_NOT_CONFIGURED` until a workspace is configured, and that the unscoped override is for controlled development only. Document that MCP clients must restart the server connection after changing environment variables.

- [ ] **Step 3: Add documentation assertions**

Extend the config/documentation tests to require both environment variable names, the error code, and the production recommendation in English and Chinese docs.

- [ ] **Step 4: Run documentation and configuration tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_config_example.py tests/test_changelog.py tests/test_tool_backend_matrix.py
```

Expected: PASS.

### Task 6: Full verification and handoff

**Files:**
- No new production files; inspect all changed files and the final diff.

- [ ] **Step 1: Run the complete test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all non-acceptance tests pass; licensed PSCAD acceptance tests remain skipped when their environment variables are absent.

- [ ] **Step 2: Run static and packaging checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
git diff --check
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_package.ps1
```

Expected: all commands exit 0.

- [ ] **Step 3: Verify the exact contract**

Run:

```powershell
@'
from pscad_mcp.main import create_server
tools = create_server()._tool_manager.list_tools()
assert len(tools) == 60
assert len({tool.name for tool in tools}) == 60
print('60 unique tools')
'@ | .\.venv\Scripts\python.exe -
```

Expected: `60 unique tools`.

- [ ] **Step 4: Inspect status and commit implementation**

Run:

```powershell
git status --short
git diff --stat
```

Review every changed file, then commit with:

```powershell
git add pyproject.toml pscad_mcp tests scripts .github README.md docs/zh-CN CHANGELOG.md config.example.toml
git commit -m "feat: harden package version and workspace paths"
```

