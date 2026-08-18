# HVDC Complete Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Complete the HVDC domain layer so real PSCAD backends expose verified EMTDC-time control and output-channel inspection where supported, while expanding VSC/MMC semantics and preserving fail-closed safety.

**Architecture:** Keep the generic 60-tool contract stable and extend the existing backend capability contract with explicit timed-control and output-channel metadata methods. Keep strict orchestration, preflight, bindings, metrics, and audit evidence in the HVDC domain package; real backends report only verified capabilities and otherwise return structured safety errors. Add profile-driven VSC/MMC semantics without inferring unconfirmed writable controls.

**Tech Stack:** Python 3.10+, pytest, asyncio, PSCAD 4.6 legacy adapter, PSCAD 5.x modern adapter, XML/PSOUT readers, JSON Profiles.

---

### Task 1: Freeze the current baseline and backend capability matrix

**Files:**
- Create: `tests/test_hvdc_backend_capabilities.py`
- Modify: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write failing capability tests**

Add tests asserting that both adapters expose structured capability dictionaries, that unsupported capabilities return `False`, and that unsupported scheduling/clock methods raise `CAPABILITY_UNAVAILABLE` with backend/version details.

- [ ] **Step 2: Run the focused tests**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_backend_capabilities.py -q`

Expected: the new tests pass against the existing conservative contract; this establishes the baseline before adding verified provider hooks.

- [ ] **Step 3: Run the complete baseline**

Run: `\.venv\Scripts\python.exe -m pytest -q`

Expected: `516 passed, 18 skipped, 127 subtests passed`.

### Task 2: Add explicit output-channel metadata to backend adapters

**Files:**
- Modify: `pscad_mcp/core/backend/base.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `pscad_mcp/core/service.py`
- Create: `tests/test_hvdc_output_channels_backend.py`

- [ ] **Step 1: Write failing adapter tests**

Define fake vendor projects exposing output metadata and assert normalization to `{path, call_id, units, description}`. Add a negative test for unavailable vendor metadata that must raise `CAPABILITY_UNAVAILABLE` rather than infer from aliases.

- [ ] **Step 2: Run the tests and confirm the expected failure**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_output_channels_backend.py -q`

Expected: FAIL because the adapter methods do not yet exist.

- [ ] **Step 3: Implement the backend contract**

Add `get_output_channels(project_name)` to the base/service contract. Implement only documented vendor entry points in Legacy/Modern; when unavailable, raise a structured `CAPABILITY_UNAVAILABLE` error with `project_name`, backend name, and version.

- [ ] **Step 4: Verify the focused tests**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_output_channels_backend.py tests\test_hvdc_preflight.py -q`

Expected: PASS with preflight continuing to reject missing or ambiguous selectors before writes.

### Task 3: Implement verified real-backend EMTDC timing providers

**Files:**
- Modify: `pscad_mcp/core/backend/base.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `pscad_mcp/hvdc/timing.py`
- Modify: `pscad_mcp/hvdc/scenarios.py`
- Create: `tests/test_hvdc_backend_timing_providers.py`
- Modify: `tests/test_hvdc_timing.py`

- [ ] **Step 1: Write provider contract tests**

Cover native scheduling acknowledgements, simulation-clock monotonicity, unsupported capability rejection, liveness timeout, and duplicate event prevention. Include a test proving no call to `asyncio` wall-clock time determines event dispatch.

- [ ] **Step 2: Run the tests and confirm failure**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_backend_timing_providers.py tests\test_hvdc_timing.py -q`

Expected: FAIL for the new adapter provider hooks.

- [ ] **Step 3: Implement the minimal verified provider hooks**

Use only documented vendor APIs. Native scheduling must return one acknowledgement per event. Simulation-clock polling must report finite monotonic EMTDC time. If the vendor API cannot prove either capability, retain `False` flags and structured rejection.

- [ ] **Step 4: Improve polling behavior**

Add a bounded polling interval with `asyncio.sleep(interval)` and detect a non-advancing clock after a configurable number of polls. Keep wall-clock time only as a liveness deadline.

- [ ] **Step 5: Verify timing and containment tests**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_timing.py tests\test_hvdc_scenarios.py tests\test_hvdc_scenario_containment.py -q`

Expected: PASS; unsupported real adapters must fail before parameter writes or run dispatch.

### Task 4: Harden command/event idempotency and audit evidence

**Files:**
- Modify: `pscad_mcp/hvdc/scenarios.py`
- Modify: `pscad_mcp/hvdc/audit.py`
- Create: `tests/test_hvdc_event_idempotency.py`
- Modify: `tests/test_hvdc_audit.py`

- [ ] **Step 1: Write failing idempotency and audit tests**

Assert each event receives a stable event ID, is written at most once, records requested/observed time and read-back, and that retry/containment records preserve all warnings and JSON-safe values.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_event_idempotency.py tests\test_hvdc_audit.py -q`

Expected: FAIL because event IDs and duplicate suppression are not yet present.

- [ ] **Step 3: Implement event IDs and bounded retries**

Derive event IDs from scenario ID plus sorted event index, store dispatch state in the scenario record, and retry only transient backend errors. Never retry a successful write or a failed read-back without first verifying current value.

- [ ] **Step 4: Verify audit serialization**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_event_idempotency.py tests\test_hvdc_audit.py -q`

Expected: PASS with source/derived hash semantics unchanged.

### Task 5: Expand VSC 2-level and MMC profiles and metric semantics

**Files:**
- Modify: `pscad_mcp/hvdc/profiles.py`
- Modify: `pscad_mcp/hvdc/metrics.py`
- Modify: `pscad_mcp/hvdc/classifier.py`
- Create: `tests/test_hvdc_vsc_mmc_profiles.py`
- Modify: `tests/test_hvdc_metrics.py`

- [ ] **Step 1: Write failing profile and metric tests**

Require explicit VSC selectors for `dc_voltage`, `dc_current`, `active_power`, `reactive_power`, `pll_frequency`, `dq_current`, and `dq_voltage`; require MMC selectors for arm current, submodule capacitor voltage, and circulating current. Add unit-aware metric tests and missing-channel tests.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_vsc_mmc_profiles.py tests\test_hvdc_metrics.py -q`

Expected: FAIL because the generic VSC/MMC Profiles do not define the full selector/role contracts.

- [ ] **Step 3: Add explicit Profile v2 semantics**

Extend built-in profiles with result selectors, metric roles, units, direction, and no writable commands unless a project-qualified binding exists. Update classifier evidence for VSC/PLL/dq and MMC/submodule/arm signatures.

- [ ] **Step 4: Implement derived metrics**

Add unit-safe VSC P/Q and dq metrics plus MMC arm/circulating-current metrics. Return `missing` or `INCOMPLETE_ANALYSIS` when required channels, units, or semantic roles are absent.

- [ ] **Step 5: Verify profile and metric tests**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_vsc_mmc_profiles.py tests\test_hvdc_metrics.py tests\test_hvdc_results.py -q`

Expected: PASS.

### Task 6: Complete licensed PSCAD 4.6 acceptance coverage

**Files:**
- Modify: `tests/test_hvdc_real_acceptance.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add acceptance assertions for all branches**

Require baseline terminal state, selector resolution, source/library hash preservation, safe rejection when strict timing or bindings are unavailable, and requested/observed event times when capabilities are available.

- [ ] **Step 2: Run the acceptance test without credentials**

Run: `\.venv\Scripts\python.exe -m pytest tests\test_hvdc_real_acceptance.py -q -rs`

Expected: unit helper tests pass and the licensed test is explicitly skipped with the required environment message.

- [ ] **Step 3: Update documentation**

Document which capabilities are contract-tested, which are verified only with licensed PSCAD, and which conditions produce a safe rejection.

### Task 7: Full regression, package checks, and delivery audit

**Files:**
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run all tests**

Run: `\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass; only environment-gated licensed acceptance remains skipped.

- [ ] **Step 2: Run static checks**

Run: `\.venv\Scripts\python.exe -m compileall pscad_mcp`; `git diff --check`

Expected: both commands exit successfully with no whitespace errors.

- [ ] **Step 3: Review safety invariants**

Confirm source projects remain read-only, derived projects require confirmation, timed events never use wall-clock time as event time, ambiguous selectors fail before mutation, and one active HVDC scenario lease remains enforced.

- [ ] **Step 4: Commit the completed optimization**

Run:

```powershell
git add pscad_mcp tests README.md docs CHANGELOG.md
git commit -m "feat: complete HVDC backend and topology optimization"
```
