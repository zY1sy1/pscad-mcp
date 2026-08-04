# PSCAD 4.6.2 Optimization Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the three review findings in the PSCAD 4.6.2 optimization branch and make the branch cleanly based on the latest `origin/main` without replaying the already-merged delivery-hardening batch.

**Architecture:** Preserve the existing service/backend/adapter boundaries. Normalize vendor messages only inside the modern backend, make executor generation and worker selection one atomic lifecycle operation, and keep PSOUT identification diagnostics inside `PscadAdapter`. No MCP tools or default response shapes are added or removed.

**Tech Stack:** Python 3.10-3.12, `asyncio`, `threading`, `pytest`, MHI PSCAD 3.1.x message records, and Git worktrees.

---

## Task 1: Rebuild the branch on current origin/main

**Files:** Git history only.

- [ ] Preserve `codex/pscad-462-optimization` as `codex/pscad-462-optimization-pre-remediation`.
- [ ] Create a replacement branch from `origin/main`.
- [ ] Cherry-pick the approved design, implementation plan, license-error, runtime-reliability, and workflow-capability commits.
- [ ] Skip the duplicate delivery-hardening commit because `origin/main` already contains that batch.

## Task 2: Normalize real MHI project messages

**Files:**
- Modify: `tests/test_workflow_capabilities.py`
- Modify: `pscad_mcp/core/backend/modern.py`

- [ ] Add a test using a named-tuple-shaped message with the real MHI fields `text`, `label`, `status`, `scope`, `name`, `link`, `group`, and `classid`.
- [ ] Run the focused test and verify it fails because severity becomes `normal` and source metadata is absent.
- [ ] Map `status` to severity and convert exposed source fields to a JSON-safe dictionary while retaining compatibility with existing `severity`, `level`, and `source` objects.
- [ ] Run the focused structured-message tests and commit the fix.

## Task 3: Make executor reset and submission atomic

**Files:**
- Modify: `tests/test_executor_recovery.py`
- Modify: `pscad_mcp/core/executor.py`

- [ ] Add a deterministic concurrency regression test that resets immediately after call state is captured and proves the current worker is not reported as a retiring previous generation.
- [ ] Run the focused test and verify the incorrect `previous_worker_retiring=True` result.
- [ ] Introduce one lifecycle lock boundary that atomically checks health, captures generation/worker/call lock, submits the task, and swaps worker state during reset.
- [ ] Preserve the timeout behavior where an already-running old worker remains visible as retiring after reset.
- [ ] Run all executor recovery tests and commit the fix.

## Task 4: Diagnose unidentified PSOUT traces

**Files:**
- Modify: `tests/test_psout_reader.py`
- Modify: `pscad_mcp/core/pscad_adapter.py`

- [ ] Add a leaf trace fake whose `Name` lookup fails but whose trace data remains readable.
- [ ] Run the focused test and verify the trace is incorrectly returned with an empty path and no diagnostics.
- [ ] Record an `identify` skipped-channel entry with its call ID and bounded reason, then skip that trace.
- [ ] Run the focused PSOUT tests and commit the fix.

## Task 5: Final verification and branch replacement

**Files:** No additional production files.

- [ ] Run `python -m pytest -q`.
- [ ] Run `python -m compileall -q pscad_mcp tests`.
- [ ] Run `python -m pip check`.
- [ ] Run `git diff --check origin/main...HEAD`.
- [ ] Verify the MCP inventory prints `60 60`.
- [ ] Confirm a merge-tree check against `origin/main` has no conflicts.
- [ ] Rename the rebuilt branch to `codex/pscad-462-optimization`, retaining the pre-remediation backup branch.
- [ ] Report licensed PSCAD 4.6.2 acceptance as not run unless its required environment configuration is present.
