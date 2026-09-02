# LCC Program Baseline Gate Granularity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the program baseline so `lcc.fixed_autonomous` can retain current-commit WP1B no-fault PASS, WP1C engineering PASS, and WP6 golden INCOMPLETE as separate evidence gates without misreporting the whole scope as accepted.

**Architecture:** Introduce a backward-readable schema version 2 that adds nullable layered verdicts to report index entries and explicit gates to scopes. Keep the existing one-report promotion path for version 1 and non-gated scopes, while adding an atomic two-report fixed-LCC registration command that pins hashes, checkout identity, and evidence fields. Actual checked-in baseline mutation remains a separate operator action after both reports exist and the user approves promotion.

**Tech Stack:** Python 3.11, pytest, strict JSON schemas, atomic file replacement, Git identity checks.

---

## Scope and dependency

- Execute this plan only after `docs/superpowers/plans/2026-09-02-lcc-wp1c-native-closure.md` has produced independently reviewed same-commit WP1B and WP1C reports.
- Tasks 1-5 implement and offline-test schema/tooling without changing `docs/acceptance/lcc-mmc-program-baseline.json`.
- Task 6 mutates the checked-in baseline and requires separate explicit promotion approval.
- The schema does not create a golden, change a report verdict, merge, push, publish, or mark any LCC scope `accepted`.

## Version 2 records

Every version 2 report index entry adds:

```json
{
  "engineering_verdict": null,
  "golden_verdict": null
}
```

Every version 2 scope adds `gates`. Only `lcc.fixed_autonomous` has gates in this version:

```json
[
  {"name": "wp1b_no_fault", "status": "PASS", "evidence_run_id": "fixed-run-id", "evidence_field": "status", "required": true},
  {"name": "wp1c_dynamic_engineering", "status": "PASS", "evidence_run_id": "dynamic-run-id", "evidence_field": "engineering_verdict", "required": true},
  {"name": "wp6_independent_golden", "status": "INCOMPLETE_ANALYSIS", "evidence_run_id": "dynamic-run-id", "evidence_field": "golden_verdict", "required": true}
]
```

The derived scope status is `FAIL` if a required gate fails, `PASS` only if every required gate passes, otherwise `INCOMPLETE_ANALYSIS`. Therefore the expected post-WP1C fixed scope is `simulated/INCOMPLETE_ANALYSIS`, backed by both reports.

### Task 1: Preserve layered verdicts in the evidence index

**Files:**

- Modify: `pscad_mcp/acceptance/evidence.py`
- Modify: `tests/test_lcc_mmc_evidence_index.py`

- [ ] **Step 1: Write failing index tests**

Extend the existing `write_report()` helper with keyword-only
`engineering_verdict` and `golden_verdict` arguments. Omit each key when its
argument is `None`; this keeps the legacy fixture byte shape distinct from the
WP1C fixture. Return `path` after writing so both new tests pass the actual file
to `index_explicit_reports()`.

```python
def test_dynamic_report_index_preserves_layered_verdicts(tmp_path):
    report = write_report(
        tmp_path / "wp1c.json",
        status="INCOMPLETE_ANALYSIS",
        engineering_verdict="PASS",
        golden_verdict="INCOMPLETE_ANALYSIS",
    )
    indexed = index_explicit_reports([{"path": str(report)}])[0]
    assert indexed["engineering_verdict"] == "PASS"
    assert indexed["golden_verdict"] == "INCOMPLETE_ANALYSIS"


def test_legacy_report_index_uses_null_layered_verdicts(tmp_path):
    indexed = index_explicit_reports([
        {"path": str(write_report(tmp_path / "wp1b.json"))}
    ])[0]
    assert indexed["engineering_verdict"] is None
    assert indexed["golden_verdict"] is None
```

- [ ] **Step 2: Run RED**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_mmc_evidence_index.py -k layered
```

Expected: FAIL because index entries omit both fields.

- [ ] **Step 3: Validate and emit nullable verdicts**

Add a verdict set that deliberately excludes baseline-only
`NOT_RUN_ON_CURRENT_COMMIT`, then add:

```python
_LAYERED_REPORT_VERDICTS = {"PASS", "FAIL", "INCOMPLETE_ANALYSIS"}


def _optional_verdict(payload: Mapping[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if value not in _LAYERED_REPORT_VERDICTS:
        raise _error(
            "unknown_status",
            "Layered report verdict is invalid.",
            field=field,
        )
    return str(value)
```

Include `engineering_verdict` and `golden_verdict` in every indexed record using this helper.

- [ ] **Step 4: Run GREEN and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_mmc_evidence_index.py
git add pscad_mcp/acceptance/evidence.py tests/test_lcc_mmc_evidence_index.py
git commit -m "feat: index layered acceptance verdicts"
```

Expected: all evidence-index tests PASS.

### Task 2: Add backward-readable baseline schema version 2

**Files:**

- Modify: `pscad_mcp/acceptance/baseline.py`
- Modify: `pscad_mcp/acceptance/__init__.py`
- Modify: `tests/test_lcc_mmc_program_baseline.py`

- [ ] **Step 1: Write v1 compatibility and v2 gate tests**

```python
def test_schema_v1_remains_readable_without_gates():
    result = validate_program_baseline(valid_baseline())
    assert result["schema_version"] == 1
    assert "gates" not in result["scopes"][0]


def test_schema_v2_derives_fixed_scope_from_three_gates():
    baseline = valid_v2_baseline()
    result = validate_program_baseline(baseline)
    fixed = next(
        item for item in result["scopes"]
        if item["scope"] == "lcc.fixed_autonomous"
    )
    assert fixed["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert [item["status"] for item in fixed["gates"]] == [
        "PASS", "PASS", "INCOMPLETE_ANALYSIS"
    ]
```

Define `valid_v2_baseline()` beside `valid_baseline()`: migrate the v1 fixture,
append one same-commit `lcc.fixed_autonomous` WP1B index record and one
same-commit WP1C index record, add the fixed scope if absent, and set its three
ordered gate links to the PASS/PASS/INCOMPLETE example in **Version 2
records**. Use `engineering_verdict=None` and `golden_verdict=None` on the WP1B
record; use `engineering_verdict="PASS"` and
`golden_verdict="INCOMPLETE_ANALYSIS"` on the WP1C record. All linked reports
must use `availability="verified_local"`, the baseline `base_commit`, and the
fixed scope/builder pair.

Add rejections for unknown/duplicate/missing gate names, a PASS gate whose report field is not PASS, a historical commit, a non-durable report, and gates on any other scope.

- [ ] **Step 2: Run RED**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_mmc_program_baseline.py -k "schema_v2 or gates"
```

Expected: FAIL because only schema version 1 and the old exact field sets are accepted.

- [ ] **Step 3: Define exact v2 field sets and derivation**

Add:

```python
_REPORT_V2 = _REPORT | {"engineering_verdict", "golden_verdict"}
_SCOPE_V2 = _SCOPE | {"gates"}
_GATE = {"name", "status", "evidence_run_id", "evidence_field", "required"}
_FIXED_GATES = (
    "wp1b_no_fault",
    "wp1c_dynamic_engineering",
    "wp6_independent_golden",
)
_EVIDENCE_FIELDS = {"status", "engineering_verdict", "golden_verdict"}


def _derived_gate_status(gates: Sequence[Mapping[str, Any]]) -> str:
    required = [item for item in gates if item["required"]]
    if any(item["status"] == "FAIL" for item in required):
        return "FAIL"
    if required and all(item["status"] == "PASS" for item in required):
        return "PASS"
    return "INCOMPLETE_ANALYSIS"
```

Branch validation on `schema_version`. Preserve version 1 output byte semantics.
For version 2, require nullable verdict fields on reports, require the exact
three ordered gates only on `lcc.fixed_autonomous`, require `gates=[]`
elsewhere, and require the fixed scope's legacy `evidence_run_id` to be null so
`gates` is the sole evidence authority. For every non-null gate link, require a
same-scope, same-builder, current-`base_commit`, `verified_local` report and
require the report's named field to equal the gate status, whether that status
is PASS, FAIL, or INCOMPLETE. Permit a null link only for
`NOT_RUN_ON_CURRENT_COMMIT` or `INCOMPLETE_ANALYSIS`. Overwrite
`scope.licensed_status` only with `_derived_gate_status(gates)` after all links
validate.

- [ ] **Step 4: Add a pure v1-to-v2 migration**

Implement:

```python
def migrate_program_baseline_v1_to_v2(value: Any) -> dict[str, Any]:
    current = validate_program_baseline(value)
    if current["schema_version"] != 1:
        raise _error(
            "schema_version", "not_v1",
            "Only schema version 1 can be migrated.",
        )
    migrated = copy.deepcopy(current)
    migrated["schema_version"] = 2
    for report in migrated["reports"]:
        report["engineering_verdict"] = None
        report["golden_verdict"] = None
    for scope in migrated["scopes"]:
        scope["gates"] = []
        if scope["scope"] != "lcc.fixed_autonomous":
            continue
        run_id = scope["evidence_run_id"]
        wp1b_status = scope["licensed_status"]
        scope["evidence_run_id"] = None
        scope["gates"] = [
            {"name": "wp1b_no_fault", "status": wp1b_status,
             "evidence_run_id": run_id, "evidence_field": "status",
             "required": True},
            {"name": "wp1c_dynamic_engineering",
             "status": "NOT_RUN_ON_CURRENT_COMMIT", "evidence_run_id": None,
             "evidence_field": "engineering_verdict", "required": True},
            {"name": "wp6_independent_golden",
             "status": "INCOMPLETE_ANALYSIS", "evidence_run_id": None,
             "evidence_field": "golden_verdict", "required": True},
        ]
        scope["licensed_status"] = "INCOMPLETE_ANALYSIS"
    return validate_program_baseline(migrated)
```

- [ ] **Step 5: Run GREEN and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_mmc_program_baseline.py
git add pscad_mcp/acceptance/baseline.py pscad_mcp/acceptance/__init__.py tests/test_lcc_mmc_program_baseline.py
git commit -m "feat: add gate-aware program baseline schema"
```

Expected: all baseline tests PASS and v1 canonical hashes remain unchanged.

### Task 3: Atomically register one report against one named gate

**Files:**

- Modify: `pscad_mcp/acceptance/baseline.py`
- Modify: `pscad_mcp/acceptance/promotion.py`
- Modify: `pscad_mcp/acceptance/__init__.py`
- Modify: `tests/test_program_baseline_promotion.py`

- [ ] **Step 1: Write gate registration tests**

Test that `wp1b_no_fault` reads report `status`, `wp1c_dynamic_engineering` reads `engineering_verdict`, and `wp6_independent_golden` reads `golden_verdict`. Also test wrong scope, wrong field, reused run ID, hash replacement, dirty checkout, branch mismatch, and commit advance invalidating every old gate.

```python
def test_dynamic_incomplete_report_registers_engineering_pass_gate(tmp_path):
    baseline = valid_v2_baseline()
    fixed_before = next(
        item for item in baseline["scopes"]
        if item["scope"] == "lcc.fixed_autonomous"
    )
    dynamic_before = next(
        item for item in fixed_before["gates"]
        if item["name"] == "wp1c_dynamic_engineering"
    )
    dynamic_before.update(
        status="NOT_RUN_ON_CURRENT_COMMIT", evidence_run_id=None
    )
    golden_before = next(
        item for item in fixed_before["gates"]
        if item["name"] == "wp6_independent_golden"
    )
    golden_before.update(
        status="INCOMPLETE_ANALYSIS", evidence_run_id=None
    )
    fixed_before["licensed_status"] = "INCOMPLETE_ANALYSIS"
    baseline["reports"] = [
        item for item in baseline["reports"]
        if item["run_id"] != "dynamic-run-id"
    ]
    report = write_wp1c_report(
        tmp_path / "wp1c.json",
        commit=baseline["repository"]["base_commit"],
        branch=baseline["repository"]["branch"],
    )
    updated = apply_scope_gate_report(
        baseline, report,
        scope="lcc.fixed_autonomous",
        gate_name="wp1c_dynamic_engineering",
        owner_work_package="WP1",
    )
    fixed = next(
        item for item in updated["scopes"]
        if item["scope"] == "lcc.fixed_autonomous"
    )
    gate = next(
        item for item in fixed["gates"]
        if item["name"] == "wp1c_dynamic_engineering"
    )
    assert gate["status"] == "PASS"
    assert fixed["licensed_status"] == "INCOMPLETE_ANALYSIS"
    assert len([
        item for item in updated["reports"]
        if item["scope"] == "lcc.fixed_autonomous"
    ]) == 2
```

Define `write_wp1c_report()` in this test module to write the strict WP1C
durable-report fixture from `tests.lcc_dynamic_fakes.valid_wp1c_report`, changing
only the path-bound commit and repository branch supplied above. Hashing and
index extraction must still be performed by production code.

- [ ] **Step 2: Run RED**

```powershell
& $wp1cPython -m pytest -q tests/test_program_baseline_promotion.py -k gate
```

Expected: FAIL because no gate-aware transition exists and the old promotion rejects top-level INCOMPLETE.

- [ ] **Step 3: Implement pure gate application**

Add `apply_scope_gate_report()` that indexes the report once, pins its hash,
requires schema version 2, same scope/builder/current commit/owner, maps the gate
to its fixed `evidence_field`, requires the selected report value to be in
`_LAYERED_REPORT_VERDICTS`, inserts the indexed report without replacing another
run, updates only the named gate with that exact value, rederives scope status,
and returns a validated deep copy.

Use this mapping, not a caller-provided field:

```python
FIXED_GATE_FIELDS = {
    "wp1b_no_fault": "status",
    "wp1c_dynamic_engineering": "engineering_verdict",
    "wp6_independent_golden": "golden_verdict",
}
```

- [ ] **Step 4: Add commit-aware atomic promotion**

Implement `advance_and_apply_scope_gate_report()` and
`promote_program_gate_report()` with the same two checkout reads and report hash
rechecks as `promote_program_report`. Do not require top-level report PASS; use
the selected field as the gate value and require exact validator agreement.
Never delete the other fixed-LCC report.

- [ ] **Step 5: Run GREEN and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_program_baseline_promotion.py tests/test_lcc_mmc_program_baseline.py
& $wp1cPython -m ruff check pscad_mcp/acceptance tests/test_program_baseline_promotion.py tests/test_lcc_mmc_program_baseline.py
git add pscad_mcp/acceptance tests/test_program_baseline_promotion.py
git commit -m "feat: register program evidence by named gate"
```

Expected: all tests and Ruff PASS; old version 1 promotion cases remain unchanged.

### Task 4: Add an atomic fixed-LCC two-report registration CLI

**Files:**

- Create: `pscad_mcp/acceptance/gate_promotion_cli.py`
- Create: `tests/test_program_gate_promotion_cli.py`

- [ ] **Step 1: Write all-or-nothing CLI tests**

Test `register-fixed` with `--baseline`, `--wp1b-report`, and `--wp1c-report`. A valid pair must migrate v1 to v2 in memory, advance to the common report commit, register WP1B status PASS, WP1C engineering PASS, WP1C golden INCOMPLETE, validate, recheck both hashes and checkout, and write once. If either report fails any check, baseline bytes must remain identical.

- [ ] **Step 2: Run RED**

```powershell
& $wp1cPython -m pytest -q tests/test_program_gate_promotion_cli.py
```

Expected: import failure because the CLI does not exist.

- [ ] **Step 3: Implement the exact command**

The command must hash and index both files, then load them through
`validate_fixed_lcc_acceptance_report()` and
`validate_dynamic_lcc_acceptance_report()` respectively; no field may come from
an unvalidated JSON read. It must require both reports to own the same full
commit, branch, scope, builder, and verified-local availability. It must require WP1B `status=PASS`,
WP1C `engineering_verdict=PASS`, and WP1C
`golden_verdict=INCOMPLETE_ANALYSIS`. It then stores all three gate records,
sets the fixed scope's legacy `evidence_run_id` to null, derives scope
INCOMPLETE, replaces `asset.lcc.fixed.manifest` with the identical manifest hash
attested by both reports, and sets fixed-scope `explicit_exclusions` to exactly
`["independent_golden", "final_accepted"]`. It atomically writes once, reloads,
and validates the bytes.

Print:

```text
PROGRAM_BASELINE_SCHEMA=2
FIXED_LCC_WP1B_GATE=PASS
FIXED_LCC_WP1C_ENGINEERING_GATE=PASS
FIXED_LCC_WP6_GOLDEN_GATE=INCOMPLETE_ANALYSIS
FIXED_LCC_SCOPE_STATUS=INCOMPLETE_ANALYSIS
```

- [ ] **Step 4: Run GREEN and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_program_gate_promotion_cli.py tests/test_program_baseline_promotion.py
git add pscad_mcp/acceptance/gate_promotion_cli.py tests/test_program_gate_promotion_cli.py
git commit -m "feat: add atomic fixed LCC gate registration"
```

Expected: all CLI and promotion tests PASS.

### Task 5: Run offline schema and repository verification without promotion

**Files:**

- No production or baseline file should change

- [ ] **Step 1: Run focused tests**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_mmc_evidence_index.py tests/test_lcc_mmc_program_baseline.py tests/test_program_baseline_promotion.py tests/test_program_gate_promotion_cli.py tests/test_acceptance_status_manifest.py
```

Expected: zero failures.

- [ ] **Step 2: Run fatal static and full offline gates**

```powershell
Remove-Item Env:PSCAD_MCP_ACCEPTANCE -ErrorAction SilentlyContinue
& $wp1cPython -m ruff check --select E9,F63,F7,F82 pscad_mcp tests
& $wp1cPython -m pytest -q
git diff --check
```

Expected: zero failures, licensed cases skipped, and no whitespace errors. Record exact counts.

- [ ] **Step 3: Prove the checked-in baseline was not changed**

```powershell
git diff --exit-code -- docs/acceptance/lcc-mmc-program-baseline.json
git status --short --branch
```

Expected: no baseline diff and a clean branch after focused commits.

### Task 6: Register reviewed current-commit evidence

**Files:**

- Modify after explicit approval: `docs/acceptance/lcc-mmc-program-baseline.json`

> **Promotion gate:** Stop until the user explicitly approves baseline mutation and supplies the independently reviewed exact WP1B and WP1C report paths from the native-closure plan. This approval is separate from licensed-run approval.

- [ ] **Step 1: Pin exact report paths and hashes**

Set `$wp1bReport` and `$wp1cReport` to the two reviewed absolute paths. Reject missing, reparse, cross-commit, cross-branch, or changed files. Print and record both SHA-256 values before proceeding.

- [ ] **Step 2: Run the atomic registration command**

```powershell
& $wp1cPython -m pscad_mcp.acceptance.gate_promotion_cli register-fixed `
  --baseline docs/acceptance/lcc-mmc-program-baseline.json `
  --wp1b-report $wp1bReport `
  --wp1c-report $wp1cReport
```

Expected: the five exact status lines documented in Task 4 and exit zero.

- [ ] **Step 3: Inspect the complete diff and validate**

```powershell
git diff -- docs/acceptance/lcc-mmc-program-baseline.json
& $wp1cPython -m pytest -q tests/test_lcc_mmc_program_baseline.py tests/test_program_gate_promotion_cli.py tests/test_acceptance_status_manifest.py
git diff --check
```

Expected: schema version 2; both report records retained; the three fixed gates
are PASS/PASS/INCOMPLETE; fixed scope status is INCOMPLETE; the fixed manifest
asset hash equals both reports' source attestation; fixed exclusions are exactly
`independent_golden` and `final_accepted`; no other scope changes except
current-commit invalidation required by the existing promotion contract; all
tests pass.

- [ ] **Step 4: Commit only after human diff review**

```powershell
git add docs/acceptance/lcc-mmc-program-baseline.json
git commit -m "test: register fixed LCC layered evidence gates"
```

Do not merge or push. Report the new baseline hash, both report hashes, exact gate states, and the unchanged `final_accepted` exclusion.
