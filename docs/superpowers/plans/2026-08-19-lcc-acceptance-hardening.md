# LCC Acceptance Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add verified output creation, live definition inventory, strict measurement contracts, evidence-gated assets, and staging-only publication semantics for the fixed LCC acceptance path.

**Architecture:** Extend the vendor-neutral backend/service contract with two explicit runtime capabilities. Keep measurement and asset evidence validation in small pure-Python modules so they can run without PSCAD. Gate accepted/publish states on live evidence and a verified publication primitive; unsupported vendor APIs return stable structured errors.

**Tech Stack:** Python 3.10+, asyncio, dataclasses, JSON, SHA-256, pathlib, pytest, existing PSCAD legacy/modern adapters.

---

### Task 1: Freeze focused baseline and record existing failures

**Files:**
- Create: `tests/test_lcc_acceptance_hardening_baseline.py`
- Modify: none

- [ ] **Step 1: Write a baseline test for strict acceptance prerequisites**

```python
def test_acceptance_prerequisites_are_not_satisfied_by_packaged_catalog_only():
    from pscad_mcp.hvdc.builders.lcc.evidence import AcceptanceEvidence

    evidence = AcceptanceEvidence(live_inventory_hash=None, golden_placeholder=True, library_compiled=False)
    assert evidence.accepted is False
    assert set(evidence.missing) == {"live_definition_inventory", "golden_reference", "library_compile"}
```

- [ ] **Step 2: Run the new test and verify the expected missing-module failure**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_acceptance_hardening_baseline.py -q`

Expected: FAIL with `ModuleNotFoundError` for the not-yet-created evidence module.

- [ ] **Step 3: Run the existing focused baseline**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_hvdc_output_channels_backend.py tests\\test_hvdc_preflight.py tests\\test_hvdc_scenarios.py -q`

Expected: capture the current output-capability and path-policy failures without changing them yet.

---

### Task 2: Add output-channel creation to the stable backend contract

**Files:**
- Modify: `pscad_mcp/core/backend/base.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Create: `tests/test_output_channel_creation.py`

- [ ] **Step 1: Write failing service and adapter tests**

Cover: one normalized channel is created and read back; duplicate canonical/path is rejected; missing vendor provider raises `CAPABILITY_UNAVAILABLE`; no vendor proxy escapes the service.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_output_channel_creation.py -q`

Expected: FAIL because `create_output_channel` is absent from the service and adapters.

- [ ] **Step 3: Implement the minimal contract**

Add `create_output_channel(project_name, channel)` to `ResultBackend`, `PscadService`, and both adapters. Accept only a JSON object with non-empty `path`, optional positive integer `call_id`, optional string `units`, and optional `description`. Call only a documented vendor provider named `create_output_channel` or `add_output_channel`; normalize the provider result, then inspect the channel list and require exactly one matching record.

- [ ] **Step 4: Verify focused tests and existing output inspection tests**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_output_channel_creation.py tests\\test_hvdc_output_channels_backend.py tests\\test_hvdc_preflight.py -q`

Expected: PASS for the new contract and fail-closed behavior.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/core/backend/base.py pscad_mcp/core/service.py pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/modern.py tests/test_output_channel_creation.py
git commit -m "feat: add verified output channel creation"
```

---

### Task 3: Add live definition inventory and separate it from packaged catalog

**Files:**
- Modify: `pscad_mcp/core/backend/base.py`
- Modify: `pscad_mcp/core/service.py`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Create: `pscad_mcp/hvdc/builders/lcc/inventory.py`
- Create: `tests/test_lcc_definition_inventory.py`

- [ ] **Step 1: Write failing inventory tests**

Assert that a provider snapshot is canonicalized and hashed deterministically, that packaged catalog data never satisfies `require_live=True`, and that an unavailable provider raises `CAPABILITY_UNAVAILABLE`.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_definition_inventory.py -q`

Expected: FAIL because the inventory module and service method do not exist.

- [ ] **Step 3: Implement canonical inventory records**

Add `get_definition_inventory(project_name)` to the backend/service contract. Normalize each definition to scoped name, ports, parameter ranges/enums, and bounding box; sort all collections; hash `canonical_json(snapshot)` with SHA-256. Do not fall back to `project_definitions()` names or packaged catalog when `require_live=True`.

- [ ] **Step 4: Verify focused inventory tests**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_definition_inventory.py tests\\test_output_channel_creation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/core/backend/base.py pscad_mcp/core/service.py pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/modern.py pscad_mcp/hvdc/builders/lcc/inventory.py tests/test_lcc_definition_inventory.py
git commit -m "feat: require live PSCAD definition inventory"
```

---

### Task 4: Enforce unique observed and explicit derived measurements

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/measurements.py`
- Modify: `pscad_mcp/hvdc/profiles.py`
- Modify: `pscad_mcp/hvdc/preflight.py`
- Create: `tests/test_lcc_measurement_contract.py`

- [ ] **Step 1: Write failing measurement tests**

Cover duplicate canonical IDs, duplicate observed `(path, call_id)` endpoints, incomplete derived records, and valid one-to-one observed/derived selectors. Assert errors use `MEASUREMENT_CONTRACT_INVALID` before any mutation.

- [ ] **Step 2: Run tests and verify failure**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_measurement_contract.py -q`

Expected: FAIL because the contract validator is absent and duplicate endpoints are currently accepted by the LCC path.

- [ ] **Step 3: Implement pure validation and normalization**

Implement `validate_measurements(items)` returning a new sorted list. Observed records require `canonical`, `path`, `units`; derived records require `canonical`, `sources`, `expression`, `units`, and `time_domain`. Reject canonical collisions and observed endpoint collisions. Update profile loading/preflight to call the validator before output inspection or mutation.

- [ ] **Step 4: Verify focused and existing profile tests**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_measurement_contract.py tests\\test_hvdc_preflight.py tests\\test_hvdc_vsc_mmc_profiles.py -q`

Expected: PASS with existing valid profiles unchanged.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/lcc/measurements.py pscad_mcp/hvdc/profiles.py pscad_mcp/hvdc/preflight.py tests/test_lcc_measurement_contract.py
git commit -m "fix: reject ambiguous LCC measurement endpoints"
```

---

### Task 5: Add evidence-gated production assets

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/evidence.py`
- Create: `pscad_mcp/hvdc/builders/lcc/assets.py`
- Create: `tests/test_lcc_asset_evidence.py`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/PROVENANCE.md`
- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json`

- [ ] **Step 1: Write failing asset evidence tests**

Assert that placeholder golden data, missing library compile evidence, missing live inventory hash, and absent provenance all return `ASSET_EVIDENCE_MISSING`; assert that only a fully populated evidence record can be `accepted`.

- [ ] **Step 2: Run tests and verify failure**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_asset_evidence.py -q`

Expected: FAIL because evidence and asset loaders are absent.

- [ ] **Step 3: Implement evidence records and manifest checks**

Add immutable JSON-safe records for live inventory hash, catalog hash, library hash, compile status, reference-run status, golden source hash, and reviewer/provenance metadata. Reject empty, sentinel, or structurally incomplete golden files. Keep catalog hash separate from live inventory hash.

- [ ] **Step 4: Add non-placeholder asset stubs only where evidence is real**

Create the provenance/manifest scaffolding with explicit `unverified` status; do not fabricate a `.pslx` or waveform. The loader must keep the profile in `planned`/`simulated` and reject `accepted` until the licensed evidence is populated.

- [ ] **Step 5: Verify focused tests**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_asset_evidence.py tests\\test_lcc_definition_inventory.py -q`

Expected: PASS and no test treats the scaffolding as accepted.

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/hvdc/builders/lcc pscad_mcp/assets/lcc/cigre_lcc_monopole_v1 tests/test_lcc_asset_evidence.py
git commit -m "feat: gate LCC acceptance on independent evidence"
```

---

### Task 6: Enforce staging-only publication when atomic no-replace is unproven

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/publication.py`
- Create: `tests/test_lcc_publication_safety.py`
- Modify: `pscad_mcp/hvdc/service.py`

- [ ] **Step 1: Write failing publication tests**

Cover existing destination rejection, staging candidate retention, unproven vendor save-as returning `PUBLISH_REQUIRES_VERIFIED_ATOMIC_MOVE`, and proven exclusive reservation allowing publication only when the destination was absent before reservation.

- [ ] **Step 2: Run tests and verify failure**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_publication_safety.py -q`

Expected: FAIL because the publication helper and error code do not exist.

- [ ] **Step 3: Implement safe publication helper**

Write candidate files only beneath a unique staging directory. Add `reserve_final_path()` using exclusive creation of a sibling reservation marker; if the final path or reservation exists, raise a structured conflict. When the vendor API cannot be proven atomic, return the new safe-rejection code and keep staging/evidence intact. Never call an overwrite-capable fallback.

- [ ] **Step 4: Verify focused publication and path-policy tests**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_publication_safety.py tests\\test_path_safety.py tests\\test_hvdc_scenarios.py -q`

Expected: PASS except for any pre-existing licensed acceptance failure, which must remain explicitly reported.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/builders/lcc/publication.py pscad_mcp/hvdc/service.py tests/test_lcc_publication_safety.py
git commit -m "fix: make LCC publication staging-only by default"
```

---

### Task 7: Add explicit licensed acceptance gate and documentation

**Files:**
- Modify: `tests/test_hvdc_real_acceptance.py`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `CHANGELOG.md`
- Create: `tests/test_lcc_acceptance_gate.py`

- [ ] **Step 1: Write failing gate tests**

Assert that missing `mhrc.automation`, missing PSCAD, missing library compile/reference evidence, or missing live inventory cannot produce `accepted`; assert the test is skipped rather than falsely passed when the opt-in variables are absent.

- [ ] **Step 2: Implement the gate and status vocabulary**

Use `planned`, `built`, `simulated`, `accepted`, `unverified`, and `blocked`. Document that only the licensed PSCAD run can transition to `accepted`; catalog-only and placeholder data cannot.

- [ ] **Step 3: Verify documentation and focused acceptance tests**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_lcc_acceptance_gate.py tests\\test_hvdc_real_acceptance.py -q -rs`

Expected: helper tests pass and environment-gated tests are skipped or report structured unverified status.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_hvdc_real_acceptance.py tests/test_lcc_acceptance_gate.py README.md docs/zh-CN/README.md CHANGELOG.md
git commit -m "docs: expose LCC acceptance gates"
```

---

### Task 8: Full verification and delivery audit

**Files:**
- Modify: none unless verification exposes a regression

- [ ] **Step 1: Run focused nonlicensed suite**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest tests\\test_output_channel_creation.py tests\\test_lcc_definition_inventory.py tests\\test_lcc_measurement_contract.py tests\\test_lcc_asset_evidence.py tests\\test_lcc_publication_safety.py tests\\test_lcc_acceptance_gate.py -q`

Expected: all focused tests pass.

- [ ] **Step 2: Run the full suite**

Run: `..\\..\\.venv\\Scripts\\python.exe -m pytest -q`

Expected: no new failures; licensed acceptance is skipped unless explicitly configured.

- [ ] **Step 3: Run static checks**

Run: `..\\..\\.venv\\Scripts\\python.exe -m compileall -q pscad_mcp tests`; `git diff --check`; `..\\..\\.venv\\Scripts\\python.exe -m pip check`

Expected: all commands exit 0.

- [ ] **Step 4: Review acceptance invariants**

Confirm source projects remain read-only, duplicate measurements fail before mutation, catalog-only evidence cannot become accepted, existing destinations are never overwritten, and missing licensed PSCAD is reported as unverified rather than success.
