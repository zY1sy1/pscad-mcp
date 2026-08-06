# PSCAD MCP Code Review Remediation Plan

> **For agentic workers:** Implement this plan task-by-task in the existing worktree. Use test-driven development: write each failing test, run it to confirm RED, implement the smallest fix, then run the focused and full verification commands.

**Goal:** Close the four code-review gaps found in the foundation-hardening branch before merge: complete the workspace error contract, make package verification genuinely isolated, remove environment-dependent path tests, and update the installer to explain/configure the required workspace boundary.

**Base branch:** `codex/pscad-foundation-hardening`

**Current implementation commit:** `d9d998e`

**Architecture:** Preserve the current `PathPolicy` and `PscadService` boundaries. Add only the missing `candidate_is_relative` field to the existing structured error details. Replace the target-directory package probe with a temporary virtual environment so runtime dependencies are installed and exercised independently. Keep installer configuration non-destructive: it may print or generate guidance, but must not edit the user’s global Codex/Copilot files.

**Tech Stack:** Python 3.10+, pytest/unittest, setuptools, PowerShell, FastMCP 1.x, Windows CI.

---

## Review findings being addressed

1. `WORKSPACE_NOT_CONFIGURED` does not report whether the candidate was relative.
2. `scripts/verify_package.ps1` installs with `--no-deps --target` and probes with the already provisioned development interpreter, so missing runtime dependencies can be hidden.
3. `tests/test_path_safety.py` inherits a caller’s `PSCAD_MCP_WORKSPACE`; with that variable set, the fail-closed tests fail or assert the wrong base directory.
4. `mcp_installer.py` prints a setup that omits the newly required workspace configuration, so users can see a successful installation while file tools remain unusable.

The same pass should add the planned regression coverage for boolean aliases (`1`/`0`) and symlink/junction escape where the Windows test environment permits it.

## Task 1: Complete the structured workspace error contract

**Files:**
- Modify: `pscad_mcp/core/service.py`
- Modify: `tests/test_service_contract.py`
- Modify: `tests/test_protocol.py` if a FastMCP-level assertion is needed

- [x] **Step 1: Add failing service tests**

Add two tests that create `PscadService` with an explicitly unconfigured `PathPolicy` and call `load_projects`:

```python
async def test_workspace_error_marks_relative_candidate():
    service = service_with_unconfigured_path_policy()
    with self.assertRaises(BackendError) as raised:
        await service.load_projects(["case.pscx"])
    self.assertTrue(raised.exception.details["candidate_is_relative"])


async def test_workspace_error_marks_absolute_candidate():
    service = service_with_unconfigured_path_policy()
    with self.assertRaises(BackendError) as raised:
        await service.load_projects([str(Path.cwd() / "case.pscx")])
    self.assertFalse(raised.exception.details["candidate_is_relative"])
```

The helper must clear `PSCAD_MCP_WORKSPACE` and set `PSCAD_MCP_ALLOW_UNSCOPED_PATHS=false` so the tests are deterministic.

- [x] **Step 2: Run the focused tests and verify RED**

```powershell
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_service_contract.py -k workspace_error
```

Expected: failure because `candidate_is_relative` is absent.

- [x] **Step 3: Add the field in the existing error boundary**

In `PscadService._resolve_path`, preserve the existing error code/message and add:

```python
"candidate_is_relative": not Path(candidate).expanduser().is_absolute(),
```

Do not change other error codes or catch unrelated exceptions.

- [x] **Step 4: Run service and protocol tests**

```powershell
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_service_contract.py tests/test_protocol.py
```

Expected: PASS.

## Task 2: Replace target-directory smoke with a clean temporary venv

**Files:**
- Modify: `scripts/verify_package.ps1`
- Modify: `tests/test_install_smoke.py`
- Modify: `tests/test_verify_package_script.py`
- Modify: `.github/workflows/windows-ci.yml` only if the script invocation needs an explicit interpreter variable

- [x] **Step 1: Add a failing script contract test**

Extend `tests/test_verify_package_script.py` to require the script contains:

```text
python -m venv
Scripts\python.exe
pip install
```

Also assert the script does not contain `pip install --no-deps --target`.

- [x] **Step 2: Run the script contract test and verify RED**

```powershell
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_verify_package_script.py
```

Expected: failure because the current script uses `--target` and does not create a venv.

- [x] **Step 3: Implement isolated package verification**

The script must:

1. Build a wheel into an explicit temporary directory.
2. Create a second explicit temporary directory containing a venv with `python -m venv`.
3. Use the venv’s `Scripts\python.exe` and `-m pip install <wheel>` without `--no-deps`.
4. Run the probe with the venv’s Python, from a temporary working directory outside the repository.
5. Assert that installed metadata equals `pscad_mcp.__version__` and that the server exposes 60 unique tools.
6. Restore any modified environment variables and remove only the generated temporary root in `finally`.

Do not rely on the caller’s editable installation or `PYTHONPATH` to import project code.

- [x] **Step 4: Make the Python smoke test use the same contract**

When `PSCAD_MCP_SMOKE_WHEEL` is set, `tests/test_install_smoke.py` should create a temporary venv or invoke the shared PowerShell script with an explicit wheel path. It must not silently use the current editable package. Keep the test skipped when no wheel path is supplied for normal unit runs.

- [x] **Step 5: Run isolated packaging verification**

```powershell
$env:PSCAD_MCP_PYTHON = 'D:\pscad-mcp\.venv\Scripts\python.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_package.ps1
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_install_smoke.py tests/test_verify_package_script.py
```

Expected: the script prints `0.2.0 60`; the tests pass or explicitly skip only the wheel-path test.

## Task 3: Make path-safety tests independent of caller environment

**Files:**
- Modify: `tests/test_path_safety.py`
- Modify: `tests/test_service_contract.py` if its workspace helper also inherits process environment

- [x] **Step 1: Add failing environment-contamination reproduction**

Run the existing path tests with a configured external workspace:

```powershell
$env:PSCAD_MCP_WORKSPACE = 'D:\\pscad-mcp'
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py
```

Expected: current tests fail because `PathPolicy(workspace_root=None)` reads the process environment.

- [x] **Step 2: Isolate every test that expects no workspace**

Wrap unconfigured and unscoped tests with `patch.dict` that explicitly sets:

```python
{
    "PSCAD_MCP_WORKSPACE": "",
    "PSCAD_MCP_ALLOW_UNSCOPED_PATHS": "false",
}
```

For the explicit development override, set workspace to empty and allow to `true`. For configured-root tests, pass `workspace_root=tmp` and clear the environment so the test proves the explicit argument wins.

Do not change the production meaning of `workspace_root=None` in this task; existing users may rely on environment-based configuration.

- [x] **Step 3: Add planned alias and link-escape coverage**

Test `1`, `yes`, and `on` as true aliases, and `0`, `no`, and `off` as false aliases. Add a symlink or junction escape test using a temporary workspace and outside directory; skip only when the Windows environment refuses link creation. The assertion must prove `PathPolicy.resolve()` rejects the resolved outside target.

- [x] **Step 4: Re-run with and without workspace environment**

```powershell
Remove-Item Env:PSCAD_MCP_WORKSPACE -ErrorAction SilentlyContinue
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py tests/test_service_contract.py
$env:PSCAD_MCP_WORKSPACE = 'D:\\pscad-mcp'
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_path_safety.py tests/test_service_contract.py
```

Expected: both runs pass; the second run must not change the unconfigured test expectations.

## Task 4: Update installer guidance for the new security default

**Files:**
- Modify: `mcp_installer.py`
- Create or modify: `tests/test_installer_setup.py`
- Modify: `README.md` only if installer wording needs to be synchronized

- [x] **Step 1: Add failing installer-output tests**

Test two cases by patching `platform.system`, `sys.executable`, and `os.environ`:

1. When `PSCAD_MCP_WORKSPACE` is set, generated setup JSON includes an `env` mapping with that workspace and `PSCAD_MCP_ALLOW_UNSCOPED_PATHS=false`.
2. When it is absent, the output contains `WORKSPACE_NOT_CONFIGURED` and clearly says file operations are unavailable until the workspace is configured; it must not claim full file-workflow setup without that warning.

Capture the logger output or refactor the pure config rendering into a small helper that returns JSON plus warnings; do not write user config files.

- [x] **Step 2: Run the tests and verify RED**

```powershell
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_installer_setup.py
```

Expected: failure because the current installer JSON has no env mapping or workspace warning.

- [x] **Step 3: Implement non-destructive installer guidance**

Keep installation and documentation sync behavior unchanged. Add explicit workspace guidance before the final setup message. Include the configured workspace in generated JSON only when it is present; otherwise print the exact environment variable the user must set and state that file operations will return `WORKSPACE_NOT_CONFIGURED`. Always emit `PSCAD_MCP_ALLOW_UNSCOPED_PATHS=false` in generated configuration guidance unless the user explicitly chose the development override.

- [x] **Step 4: Run installer and documentation tests**

```powershell
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q tests/test_installer_setup.py tests/test_config_example.py tests/test_changelog.py
```

Expected: PASS.

## Task 5: Remove hardcoded release assumptions and finish verification

**Files:**
- Modify: `scripts/verify_package.ps1`
- Modify: `tests/test_install_smoke.py`
- Modify: `tests/test_packaging_metadata.py` if a reusable expected-version helper is added

- [x] **Step 1: Add a failing version-source test**

Read the version from `pyproject.toml` in the test or probe and assert installed metadata equals that value and `pscad_mcp.__version__`. The test must fail if the script or test hardcodes a different release number.

- [x] **Step 2: Replace literal `0.2.0` in smoke probes**

Pass the expected version into the probe from parsed `pyproject.toml`, or compare installed metadata directly to the package’s runtime `__version__` while a separate test compares runtime to TOML. Avoid adding a third release-version source.

- [x] **Step 3: Run the complete verification suite**

```powershell
D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q
D:\pscad-mcp\.venv\Scripts\python.exe -m pip check
D:\pscad-mcp\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
git diff --check
$env:PSCAD_MCP_PYTHON = 'D:\pscad-mcp\.venv\Scripts\python.exe'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_package.ps1
```

Expected: all non-licensed tests pass, package probe reports matching version and 60 tools, and all commands exit 0 both with and without `PSCAD_MCP_WORKSPACE` in the caller environment.

- [x] **Step 4: Review and commit fixes**

```powershell
git status --short
git diff --stat
git add mcp_installer.py pscad_mcp tests scripts .github README.md docs/superpowers/plans/2026-08-06-pscad-review-remediation.md
git commit -m "fix: close foundation hardening review findings"
```

## Acceptance checklist

- [x] Relative and absolute `WORKSPACE_NOT_CONFIGURED` errors expose the correct `candidate_is_relative` value.
- [x] Package smoke uses a temporary venv and installs dependencies normally.
- [x] Path tests pass with `PSCAD_MCP_WORKSPACE` unset and with it set to an unrelated workspace.
- [x] Boolean aliases and symlink/junction escapes have regression coverage.
- [x] Installer output makes the workspace requirement explicit and does not edit user files.
- [x] Smoke probes derive expected version from package metadata/source rather than a second hardcoded literal.
- [x] Full tests, `pip check`, compileall, diff check, and exact 60-tool inventory pass.
