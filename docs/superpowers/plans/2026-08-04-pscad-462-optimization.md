# PSCAD 4.6.2 MCP Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the PSCAD 4.6.2 MCP for release use while preserving the dual-backend boundary, safety rules, legacy launch-only semantics, and the exact existing 60-tool inventory.

**Architecture:** Keep FastMCP tool functions thin. Add release metadata and CI outside runtime code; add structured error behavior and service-level mutation serialization in `PscadService`; keep executor diagnostics bounded and vendor-neutral; keep PSOUT parsing inside `PscadAdapter`; expose the workflow extensions through backward-compatible optional service/tool arguments and backend protocol records.

**Tech Stack:** Python 3.10-3.12, `asyncio`, `pytest`, `tomllib`/`tomli`, FastMCP 1.x, PSCAD legacy/modern adapter protocols, Windows GitHub Actions.

---

## Baseline and execution rules

- Worktree: `D:\pscad-mcp\.worktrees\pscad-462-optimization`.
- Branch: `codex/pscad-462-optimization`.
- Baseline: `265 passed, 15 skipped, 111 subtests passed` with `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q`.
- Every runtime change follows RED -> focused failure -> minimal implementation -> focused pass -> full suite.
- Do not add a 61st MCP tool. Existing tool names must remain exactly 60.
- Do not claim legacy attachment to an already-open GUI or PSCAD 5.x end-to-end support.

## File map

- `pyproject.toml`, `pscad_mcp/__init__.py`: release version and development dependencies.
- `config.example.toml`, `CHANGELOG.md`, `.github/workflows/ci.yml`: portable setup, release notes, and Windows CI.
- `tests/test_delivery_hardening.py`: metadata/config/changelog/CI contract checks.
- `pscad_mcp/core/service.py`, `tests/test_service_contract.py`: license contract, mutation lock, backward-compatible workflow entry points.
- `pscad_mcp/core/executor.py`, `tests/test_executor_recovery.py`: reset generation and retiring-worker diagnostics.
- `pscad_mcp/core/pscad_adapter.py`, `tests/test_psout_reader.py`: bounded PSOUT warnings, channel selection, and summaries.
- `pscad_mcp/core/backend/base.py`: `ProjectMessage`, `ParameterGridRequest`, and expanded backend contracts.
- `pscad_mcp/core/backend/legacy.py`, `pscad_mcp/core/backend/modern.py`: message normalization, PSOUT forwarding, and parameter-grid capability behavior.
- `pscad_mcp/tools/project_tools.py`, `pscad_mcp/tools/data_tools.py`: optional structured-output and analysis arguments without changing tool count.
- `tests/test_backend_projects.py`, `tests/test_backend_contract.py`, `tests/test_tool_backend_matrix.py`, `tests/test_concurrency.py`: backend, protocol, inventory, and serialization coverage.
- `README.md`, `docs/zh-CN/README.md`: document the new optional arguments, configuration example, and unsupported capabilities.

### Task 1: Delivery hardening

**Files:**
- Modify: `pyproject.toml`
- Modify: `pscad_mcp/__init__.py`
- Create: `config.example.toml`
- Create: `CHANGELOG.md`
- Create: `.github/workflows/ci.yml`
- Create: `tests/test_delivery_hardening.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`

- [ ] **Step 1: Write failing metadata and artifact tests.**

  Add tests that load `pyproject.toml` with `tomllib` on Python 3.11+ and `tomli` on Python 3.10, then assert:

  ```python
  assert project["project"]["version"] == "0.2.0"
  assert project["project"]["requires-python"] == ">=3.10"
  assert "pytest" in " ".join(project["project"]["optional-dependencies"]["dev"])
  assert any("tomli" in item for item in project["project"]["optional-dependencies"]["dev"])
  assert importlib.import_module("pscad_mcp").__version__ == "0.2.0"
  ```

  Add tests that parse `config.example.toml`, require a stdio command invoking `-m pscad_mcp.main`, and require `PSCAD_MCP_BACKEND`, `PSCAD_MCP_VERSION`, `PSCAD_MCP_X64`, and `PSCAD_MCP_WORKSPACE` entries. Assert `CHANGELOG.md` contains the `0.2.0` release heading and all four delivery batches. Assert `.github/workflows/ci.yml` contains Python versions `3.10`, `3.11`, and `3.12`, `pip check`, `compileall`, and the exact 60-tool inventory command.

- [ ] **Step 2: Run the focused tests and verify the expected RED failure.**

  Run:

  ```powershell
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q tests/test_delivery_hardening.py
  ```

  Expected: failures for the old `0.1.0`/`1.0.0` versions and missing release artifacts.

- [ ] **Step 3: Implement the release artifacts.**

  Change `pyproject.toml` and `pscad_mcp/__init__.py` to `0.2.0`. Add a `dev` extra containing `pytest>=8,<9` and `tomli>=2,<3; python_version < '3.11'`; keep the existing `windows` extra unchanged. Create `config.example.toml` with portable placeholders and the documented PSCAD 4.6.2 environment variables. Create `CHANGELOG.md` with a dated `0.2.0` section covering delivery hardening, `NOT_LICENSED`, mutation/executor/PSOUT reliability, and the 4.6.2 workflow extensions. Create a Windows workflow with a `3.10/3.11/3.12` matrix that installs `.[dev]`, runs `python -m pytest -q`, `python -m compileall -q pscad_mcp tests`, `python -m pip check`, and a `create_server()` inventory assertion requiring `60 60`. Link the example config and release notes from both README files without changing the existing tool inventory claim.

- [ ] **Step 4: Run the focused tests and the delivery gate.**

  Run:

  ```powershell
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q tests/test_delivery_hardening.py tests/test_tool_backend_matrix.py
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m compileall -q pscad_mcp tests
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pip check
  git diff --check
  ```

  Expected: all focused tests pass, compile and dependency checks exit zero, and the diff has no whitespace errors.

- [ ] **Step 5: Commit the delivery batch.**

  ```powershell
  git add pyproject.toml pscad_mcp/__init__.py config.example.toml CHANGELOG.md .github/workflows/ci.yml tests/test_delivery_hardening.py README.md docs/zh-CN/README.md
  git commit -m "chore: harden PSCAD MCP delivery metadata"
  ```

### Task 2: Consistent license error contract

**Files:**
- Modify: `pscad_mcp/core/service.py`
- Modify: `tests/test_service_contract.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write failing license-contract tests.**

  Extend the lifecycle fake with a configurable `licensed` value and add these behaviors:

  ```python
  async def test_run_project_raises_structured_error_when_license_is_false(self):
      backend = FakeLifecycleBackend(licensed=False)
      service = service_with_backend(backend)
      with self.assertRaises(BackendError) as raised:
          await service.run_project("case")
      self.assertEqual(raised.exception.code, "NOT_LICENSED")
      self.assertEqual(raised.exception.operation, "run_project")
      self.assertEqual(backend.run_calls, [])

  async def test_run_project_allows_unknown_license_state(self):
      backend = FakeLifecycleBackend(licensed=None)
      service = service_with_backend(backend)
      self.assertIn("Simulation started", await service.run_project("case"))
      self.assertEqual(backend.run_calls, ["case"])
  ```

  Add an error-payload assertion that `NOT_LICENSED` is non-retryable and tells the caller to activate/check the PSCAD license. Keep a tool-boundary test proving `register_tool` returns `{"error": { ... }}` for the raised error.

- [ ] **Step 2: Run the focused tests and verify RED.**

  ```powershell
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q tests/test_service_contract.py -k license
  ```

  Expected: the old service returns a string instead of raising `BackendError`, and `NOT_LICENSED` has no guidance entry.

- [ ] **Step 3: Implement the smallest service change.**

  Add `NOT_LICENSED` to `_ERROR_GUIDANCE` as non-retryable. In `PscadService.run_project`, call `backend.heartbeat()` once, raise:

  ```python
  BackendError(
      "NOT_LICENSED",
      "PSCAD is not licensed; simulation was not started.",
      getattr(backend, "name", "backend"),
      "run_project",
      {"project_name": project_name},
  )
  ```

  only when `info.licensed is False`; continue to run when it is `True` or `None`. Leave the FastMCP wrapper shape unchanged.

- [ ] **Step 4: Run focused and regression tests.**

  ```powershell
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q tests/test_service_contract.py tests/test_tools.py tests/test_project_tool_service_boundary.py
  ```

- [ ] **Step 5: Commit the error-contract batch.**

  ```powershell
  git add pscad_mcp/core/service.py tests/test_service_contract.py tests/test_tools.py
  git commit -m "fix: serialize unlicensed PSCAD runs"
  ```

### Task 3: Runtime serialization, executor recovery, and PSOUT diagnostics

**Files:**
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/core/executor.py`
- Modify: `pscad_mcp/core/pscad_adapter.py`
- Modify: `pscad_mcp/core/backend/base.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `tests/test_concurrency.py`
- Modify: `tests/test_executor_recovery.py`
- Modify: `tests/test_psout_reader.py`
- Modify: `tests/test_backend_projects.py`

- [ ] **Step 1: Write failing mutation-lock tests.**

  Add a fake backend whose `run_project` records entry/exit and waits on an `asyncio.Event`. Start two concurrent `service.run_project()` calls and assert the second cannot enter until the first releases. While the mutation is held, call `service.status()` and assert the heartbeat completes, proving read-only status does not use the mutation lock. Add a test for `run_simulation_set` or `add_task_to_set` that verifies the multi-call validation and mutation sequence is one critical section.

- [ ] **Step 2: Implement a non-nested service mutation boundary.**

  Add `self._mutation_lock = asyncio.Lock()` in `PscadService`. Use the lock only around service-level multi-call state-changing workflows (`repair_connection`, `run_project`, `run_simulation_set`, `add_task_to_set`, and `connect_ports`); keep `status`, list/read methods, and backend single-call operations outside it. Do not acquire the lock in methods that delegate to another locked method; factor any such delegation into a private backend call or leave the outer workflow as the only lock boundary. The executor remains the lower-level serialization boundary for every vendor call.

- [ ] **Step 3: Write failing executor diagnostic tests.**

  Extend timeout/recovery coverage with:

  ```python
  await executor.run_safe(blocked_call, timeout=0.01)
  before_reset = executor.snapshot()
  self.assertEqual(before_reset["reset_generation"], 0)
  executor.reset()
  during_retirement = executor.snapshot()
  self.assertEqual(during_retirement["reset_generation"], 1)
  self.assertTrue(during_retirement["previous_worker_retiring"])
  release.set()
  await asyncio.sleep(0.05)
  self.assertFalse(executor.snapshot()["previous_worker_retiring"])
  ```

- [ ] **Step 4: Implement bounded generation-aware executor diagnostics.**

  Track a monotonically increasing `reset_generation` and a set of active worker generations under `_state_lock`. Capture the current generation when scheduling a call; add it to the active set in the worker and remove it in `finally`. `snapshot()` must return only JSON-safe values: `healthy`, `last_operation`, bounded `last_error`, `last_timeout_seconds`, `reset_generation`, and `previous_worker_retiring` computed from active generations older than the current generation. `reset()` creates a fresh one-worker executor, increments the generation, resets health/error/timeout state, and calls `shutdown(wait=False, cancel_futures=True)` on the old executor. Never include an executor, thread, future, or vendor proxy in the payload.

- [ ] **Step 5: Write failing PSOUT warning tests.**

  Add fake traces that fail independently during trace read, values sampling, and domain sampling. Assert successful channels remain in `channels`; each unavailable part creates a bounded `skipped_channels` record with `path`, `call_id`, `stage`, and `reason`; and the stage distinguishes `trace`, `values`, and `domain`. Assert `warnings` is JSON serializable and every reason is bounded to 256 characters.

- [ ] **Step 6: Implement PSOUT skipped-channel diagnostics.**

  Extend `_read_psout_sync()` and `_collect_traces()` with bounded `warnings` and `skipped_channels` accumulators. Preserve the existing `path`, `runs`, `run_index`, `channels`, values, and domain fields. A trace failure skips the channel; a values failure skips the channel; a domain failure records a warning but returns the channel with an empty domain. Convert exception text to a bounded string and keep the current fallback behavior for readable channels. Both backend `read_output_file()` methods forward the unchanged default behavior.

- [ ] **Step 7: Run focused runtime tests and the full suite.**

  ```powershell
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q tests/test_concurrency.py tests/test_executor_recovery.py tests/test_psout_reader.py tests/test_service_contract.py
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q
  ```

- [ ] **Step 8: Commit the runtime reliability batch.**

  ```powershell
  git add pscad_mcp/core/service.py pscad_mcp/core/executor.py pscad_mcp/core/pscad_adapter.py pscad_mcp/core/backend/base.py pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/modern.py tests/test_concurrency.py tests/test_executor_recovery.py tests/test_psout_reader.py tests/test_backend_projects.py
  git commit -m "fix: serialize PSCAD workflows and expose PSOUT diagnostics"
  ```

### Task 4: PSCAD 4.6.2 workflow capabilities

**Files:**
- Modify: `pscad_mcp/core/backend/base.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `pscad_mcp/core/pscad_adapter.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/tools/project_tools.py`
- Modify: `pscad_mcp/tools/data_tools.py`
- Modify: `tests/test_backend_contract.py`
- Modify: `tests/test_backend_projects.py`
- Modify: `tests/test_psout_reader.py`
- Modify: `tests/test_project_tool_service_boundary.py`
- Modify: `tests/test_tool_backend_matrix.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`

- [ ] **Step 1: Write failing structured-message contract tests.**

  Add a frozen `ProjectMessage` record expectation with `severity`, `text`, and optional `source`. Add legacy tuple and modern object fakes, then assert both backends normalize them to JSON-safe records. Keep `service.get_project_output("case")` returning the existing text string by default and add `structured=True` coverage that returns `[{"severity": ..., "text": ..., "source": ...}]`.

- [ ] **Step 2: Implement structured project messages with text fallback.**

  Add `ProjectMessage` and `project_messages()` to the backend protocol. Legacy parsing must treat the first tuple item as text, use available severity/source tuple fields when present, and omit unavailable source metadata. Modern parsing must use `messages`, `output`, or a text fallback without exposing vendor objects. Update `PscadService.get_project_output(project_name, structured=False)` and the existing `get_project_output` tool with the optional flag; default behavior remains the current string output.

- [ ] **Step 3: Write failing focused-PSOUT analysis tests.**

  Add tests that call `read_output_file(..., channel="Root/Voltage/PGB:Data", summary_only=True)` and assert only bounded per-channel summaries are returned:

  ```python
  assert result["channels"] == [{
      "path": "Root/Voltage/PGB:Data",
      "call_id": 1,
      "summary": {
          "count": 3, "min": 1.0, "max": 3.0,
          "mean": 2.0, "first": 1.0, "last": 3.0,
      },
  }]
  assert "values" not in result["channels"][0]
  ```

  Add a no-selector test proving the normal sampled payload is unchanged, a selector-miss test returning an empty channel list plus a warning, and a non-numeric trace test returning a bounded `numeric=False` summary.

- [ ] **Step 4: Implement channel selection and bounded summaries.**

  Add optional `channel` and `summary_only` arguments through the existing `read_output_file` tool/service/backend/adapter path. Match a selector against the normalized channel path. In summary mode compute only `count`, `min`, `max`, `mean`, `first`, and `last` for numeric samples; omit raw values/domain and cap the number of returned channels and warning records at a fixed constant. Preserve the existing default response when both options are omitted.

- [ ] **Step 5: Write failing parameter-grid capability tests.**

  Add a validated `ParameterGridRequest` input model with only these actions: `view_project`, `load`, and `save`. Require a non-empty project for `view_project`, require a `.csv` filename for `load`/`save`, and reject unknown actions or extra fields with `INVALID_ARGUMENT`. Assert the legacy backend raises `CAPABILITY_UNAVAILABLE` without touching vendor objects. Assert the modern fake grid receives `view`, `load`, and `save` calls and returns JSON-safe action metadata. Verify the optional `mode="parameter_grid"` path on the existing settings tools leaves the 60-tool inventory unchanged.

- [ ] **Step 6: Implement the minimal parameter-grid workflow.**

  Add `ParameterGridRequest` and a `parameter_grid()` backend protocol method. Validate and normalize request mappings in `PscadService`; resolve load/save files through `PathPolicy` with the `.csv` suffix and workspace boundary. Implement `ModernBackend.parameter_grid()` using the available `parameter_grid` proxy/factory and return only bounded metadata (`action`, `project`, `filename`, `supported`). Implement `LegacyBackend.parameter_grid()` as a vendor-neutral `CAPABILITY_UNAVAILABLE` error explaining that PSCAD 4.6.2 legacy automation does not expose this operation. Extend `get_project_settings`/`set_project_settings` with optional `mode="parameter_grid"` and request mapping dispatch so no new MCP tool is registered.

- [ ] **Step 7: Preserve explicit unsupported layer behavior.**

  Add a contract assertion that current legacy layer/disable operations remain an explicit capability/command failure and never claim a dedicated disabled layer was applied when the vendor rejects it. Do not broaden layer support or change the documented launch-only/PSCAD 5.x limitation.

- [ ] **Step 8: Update documentation and run all gates.**

  Document `structured`, `channel`, `summary_only`, and `mode="parameter_grid"` optional arguments, the bounded result shape, and the explicit legacy capability failure in both README files. Run:

  ```powershell
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pytest -q
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m compileall -q pscad_mcp tests
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -m pip check
  git diff --check
  & 'D:\pscad-mcp\.venv\Scripts\python.exe' -c "from pscad_mcp.main import create_server; t=create_server()._tool_manager.list_tools(); print(len(t), len({x.name for x in t}))"
  ```

  Expected: all tests pass, compile/dependency/whitespace checks exit zero, and the final inventory prints `60 60`.

- [ ] **Step 9: Commit the workflow batch.**

  ```powershell
  git add pscad_mcp/core/backend/base.py pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/modern.py pscad_mcp/core/pscad_adapter.py pscad_mcp/core/service.py pscad_mcp/tools/project_tools.py pscad_mcp/tools/data_tools.py tests README.md docs/zh-CN/README.md
  git commit -m "feat: add structured PSCAD workflow diagnostics"
  ```

## Final verification and handoff

- [ ] Run `python -m pytest -q`, `python -m compileall -q pscad_mcp tests`, `python -m pip check`, `git diff --check`, and the exact `60 60` inventory command from the isolated worktree.
- [ ] If PSCAD 4.6.2 environment variables and a licensed installation are available, run `scripts/run_legacy_acceptance.ps1` against a timestamped acceptance workspace; otherwise report the real-environment gate as not run rather than claiming it passed.
- [ ] Inspect `git status --short --branch` and summarize commits, test results, and any skipped licensed acceptance work.
