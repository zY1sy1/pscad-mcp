# PSCAD 4.6.2 Parameter Sweep Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable, serial, caller-driven PSCAD parameter-sweep workflow with isolated attempts, verified cleanup, bounded output statistics, restart recovery, and four new MCP tools.

**Architecture:** Add a focused `pscad_mcp.workflows.sweep` package above `PscadService`. The package separates request normalization, durable storage and leases, aggregation, state-machine advancement, and public orchestration. It reuses service/backend capabilities through non-locking internal primitives while a sweep holds the existing service mutation lock and an unforgeable in-process owner token.

**Tech Stack:** Python 3.10+, asyncio, pathlib/shutil/hashlib/json, psutil, FastMCP, pytest/unittest, existing PSCAD backend fakes and PSOUT adapter.

---

### Task 1: Normalize sweep manifests and filesystem-safe scenario identities

**Files:**
- Create: `pscad_mcp/workflows/__init__.py`
- Create: `pscad_mcp/workflows/sweep/__init__.py`
- Create: `pscad_mcp/workflows/sweep/models.py`
- Create: `tests/test_sweep_models.py`

- [ ] Write failing tests for required fields, JSON-scalar parameter values, unique case-insensitive scenario names, duplicate component/parameter updates, baseline membership, timeout/sample/poll bounds, entry/output relative-path containment, supported suffixes, exact non-empty channel selectors, and deterministic case-insensitive collision-free directory keys.
- [ ] Run `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest tests/test_sweep_models.py -q` and confirm failures are caused by the missing package/API.
- [ ] Implement immutable normalized dataclasses and `SweepSpec.parse(raw, path_policy)` that return JSON-safe normalized dictionaries, reject unknown fields and code-like/non-scalar values, resolve `source_root` inside the configured workspace, reject sources below `.pscad-mcp/sweeps`, and assign encoded scenario directory keys derived from UTF-8 name bytes plus a stable digest.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Add atomic campaign storage, safe snapshots, hashes, and durable leases

**Files:**
- Create: `pscad_mcp/workflows/sweep/store.py`
- Create: `pscad_mcp/workflows/sweep/lease.py`
- Create: `tests/test_sweep_store.py`
- Create: `tests/test_sweep_leases.py`

- [ ] Write failing tests for atomic JSON replacement, deterministic file manifests/hashes, managed-tree exclusion, symlink/junction/file-link rejection, source-change detection, immutable baseline verification, append-only attempt numbering, safe campaign IDs, bounded JSON reads, live lease rejection, stale PID/creation-time reclamation, recorded owned-PSCAD blocking, nonce ownership, heartbeat refresh, and campaign/global lease ordering.
- [ ] Run the two focused modules and verify RED.
- [ ] Implement `atomic_write_json`, bounded JSON loading, `hash_tree`, safe copy helpers, `SweepStore.create_campaign`, attempt/evidence/report/checkpoint path helpers, ancestry verification before cleanup, and manifest-hash verification. Use sibling temporary files, flush plus `os.fsync`, then `os.replace`; never follow reparse points and never delete caller-supplied paths.
- [ ] Implement exclusive lease files with `O_CREAT|O_EXCL`, bounded owner records (`nonce`, PID, process creation time, heartbeat, campaign ID, owned PSCAD PID/creation time), liveness checks via `psutil`, exact-owner refresh/release, and conservative stale handling that raises `SWEEP_RESUME_UNCERTAIN` when ownership is ambiguous.
- [ ] Re-run the focused tests and confirm GREEN.

### Task 3: Aggregate verified bounded output statistics and baseline comparisons

**Files:**
- Create: `pscad_mcp/workflows/sweep/aggregate.py`
- Create: `tests/test_sweep_aggregate.py`

- [ ] Write failing tests for channel matching, numeric `count/min/max/mean/first/last`, non-numeric rejection, bounded warnings, successful-scenario selection from latest attempts, absolute deltas, relative deltas using `abs(baseline)`, zero/missing/non-numeric baseline warnings, no delta for count, and full recomputation after a retry changes baseline or scenario results.
- [ ] Run the focused module and verify RED.
- [ ] Implement `SweepResultAggregator` that consumes only result records marked `output_verified`, labels results `statistics_scope: bounded_sample`, records the sample limit, bounds warnings/payloads, and atomically rewrites the report through `SweepStore`.
- [ ] Re-run focused tests and confirm GREEN.

### Task 4: Introduce the workspace mutation gate and sweep error guidance

**Files:**
- Create: `pscad_mcp/workflows/sweep/errors.py`
- Create: `pscad_mcp/workflows/sweep/mutation.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/core/connection_manager.py`
- Create: `tests/test_sweep_mutation_gate.py`
- Modify: `tests/test_service_contract.py`

- [ ] Write failing tests proving ordinary state-changing service calls return `SWEEP_BUSY` while a global campaign lease is active, read-only status/output/status-file operations remain available, a matching unforgeable owner token can use internal primitives, one asyncio mutation lock serializes sweep advancement with ordinary mutations, and every new stable sweep error receives explicit `retryable` and `suggested_action` fields.
- [ ] Run focused tests and verify RED.
- [ ] Implement a mutation coordinator owned by `PscadService`, backed by its existing `asyncio.Lock`, workspace lease inspection, and identity-based owner token authorization. Route all service mutation methods through the coordinator and expose only private non-locking primitives needed by `SweepRunner`; do not change existing public signatures or successful responses.
- [ ] Add guidance for `SWEEP_INVALID_SPEC`, `SWEEP_BUSY`, `SWEEP_DRIFT_DETECTED`, `SWEEP_OUTPUT_MISSING`, `SWEEP_RESTORE_FAILED`, and `SWEEP_RESUME_UNCERTAIN`.
- [ ] Re-run focused tests plus `tests/test_concurrency.py` and confirm GREEN.

### Task 5: Create read-only preflight and campaign initialization

**Files:**
- Create: `pscad_mcp/workflows/sweep/service.py`
- Create: `tests/test_sweep_preflight.py`

- [ ] Write fake-backend failing tests proving creation makes no build/run/parameter writes, snapshots only regular source files, verifies a second source hash, loads only a disposable copy in a temporary owned session, validates target project/component/parameter/range/path containment, rejects any active/external session, verifies shutdown, removes only verified preflight paths, persists manifest/checkpoint/report only after success, and removes an incomplete server-created campaign after failure without changing source hashes.
- [ ] Run the focused module and verify RED.
- [ ] Implement `SweepService.create_parameter_sweep`: parse first, acquire the workspace lease, snapshot/hash, create disposable preflight work, establish a clean MCP-owned session through injected lifecycle hooks, load and validate without writes, verify loaded project paths remain in the copy, close the owned session in `finally`, then atomically write immutable manifest, ready checkpoint, and initial report.
- [ ] Re-run focused tests and confirm GREEN.

### Task 6: Implement persistent scenario execution and verified output collection

**Files:**
- Create: `pscad_mcp/workflows/sweep/runner.py`
- Create: `tests/test_sweep_runner.py`

- [ ] Write failing fake-backend tests for a successful multi-scenario campaign; strict serial execution; fresh append-only attempts; baseline/attempt hash checks; declared-output removal; pre-write validation and snapshots; write/read-back verification; build messages; dispatch checkpoint before non-blocking run; caller-driven polling; wall-clock timeout and verified stop; missing/stale/unstable/malformed/channel-incomplete output rejection; copying outputs before analysis; restoration in `finally`; owned-session shutdown; recoverable build/run/collection failure continuation; and restoration/shutdown failure blocking later scenarios.
- [ ] Run the focused module and verify RED.
- [ ] Implement bounded `advance(max_wait_seconds)` transitions for `pending/preparing/building/running/collecting/restoring`, checkpointing before every side effect. Record intended terminal outcome before restoration; only verified restore plus shutdown converts to `succeeded` or recoverable `failed`.
- [ ] Implement output ownership checks: containment, dispatch-time non-existence, timestamp tolerance, positive/stable size observations, parser success, and exact required-channel matching. Store copied artifacts/evidence and bounded result details under the append-only attempt.
- [ ] Re-run focused tests and confirm GREEN.

### Task 7: Add restart recovery, explicit retry, and concurrency behavior

**Files:**
- Modify: `pscad_mcp/workflows/sweep/runner.py`
- Modify: `pscad_mcp/workflows/sweep/service.py`
- Create: `tests/test_sweep_recovery.py`

- [ ] Write failing tests for resume from every non-running durable state without duplicate side effects, same-process active-run polling, stable owned output after process exit, confirmed absent run without output becoming failed, legacy active process after MCP restart becoming `needs_review` without backend commands, ambiguous identity blocking, drift in manifest/baseline/checkpoint/current attempt, concurrent advancement rejection, retry eligibility, active-process retry rejection, selected scenarios only, and `attempt-N+1` preservation of old evidence.
- [ ] Run the focused module and verify RED.
- [ ] Implement checkpoint reconciliation against owner/process/backend/run/output evidence, fail-closed legacy recovery, blocked campaign handling, exact lease lifecycle, and explicit retry scheduling. Never infer restoration or cleanup from an exception-free absence check.
- [ ] Re-run focused tests and confirm GREEN.

### Task 8: Register four tools and preserve the legacy MCP contract

**Files:**
- Create: `pscad_mcp/tools/sweep_tools.py`
- Modify: `pscad_mcp/main.py`
- Modify: `pscad_mcp/core/connection_manager.py`
- Create: `tests/test_sweep_tools.py`
- Modify: `tests/test_tool_inventory.py`
- Modify: `tests/test_protocol.py`

- [ ] Write failing boundary/schema tests for `create_parameter_sweep(spec)`, `run_parameter_sweep(campaign_id, max_wait_seconds=20)`, `get_parameter_sweep_status(campaign_id, include_report=false)`, and `retry_parameter_sweep(campaign_id, scenario_names)`. Assert tools call only `SweepService`, status never contacts PSCAD, errors use the existing envelope, all prior tool schemas remain byte-for-byte stable, and unique tool count becomes exactly 64.
- [ ] Run focused tests and verify RED.
- [ ] Wire a lazily constructed `SweepService` to the existing manager/service, register the four functions through `register_tool`, bound status/error payloads, and leave all existing tool names, inputs, outputs, and behavior unchanged.
- [ ] Re-run focused tests and confirm GREEN.

### Task 9: Documentation, package verification, and live acceptance gate

**Files:**
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_install_smoke.py`
- Modify: `tests/test_workflow_capabilities.py`

- [ ] Document the four tools, persistent layout, caller-driven polling, bounded-sample semantics, retry/recovery limits, `SWEEP_BUSY`, immutable source guarantee, legacy active-run restart boundary, and a minimal explicit-list example.
- [ ] Update install/tool inventory assertions from 60 to 64 and add a wheel-installed import/protocol probe for the sweep package.
- [ ] Run `D:\pscad-mcp\.venv\Scripts\python.exe -m pytest -q`, `D:\pscad-mcp\.venv\Scripts\python.exe -m pip check`, `D:\pscad-mcp\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests`, `powershell -ExecutionPolicy Bypass -File scripts\verify_package.ps1`, and `git diff --check`; fix regressions with a failing test first.
- [ ] Check for existing PSCAD/EMTDC processes without terminating them. Only if no external process exists and the licensed 4.6.2 environment plus a public example are available, run the three-scenario real acceptance from a copied source and store evidence under the configured workspace campaign directory. Otherwise report the precise environmental gate and do not substitute a fake acceptance claim.

