# LCC WP1C Fixed Dynamic Acceptance Implementation Plan

> **状态：已被取代。** 2026-09-02 的现场核查发现公开工具 profile、`breaker1.NAME` variable binding、1.5 s 恢复窗口、原始 OUT/INF 派生和多证据 baseline 语义均未在本计划中闭环。不得继续执行本文件；使用 `docs/superpowers/plans/2026-09-02-lcc-wp1c-native-closure.md`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable licensed dynamic acceptance path for the fixed LCC builder that records disturbance, commutation-failure indication, bounded DC response, and recovery evidence without promoting final `accepted` status before WP6 independent golden review.

**Architecture:** Keep WP1B's strict smoke report and promotion code unchanged. Add a focused dynamic report module that validates shared repository/source identity fields, evaluates dynamic channels through the existing `acceptance.py` functions, and emits `PASS`, `FAIL`, or `INCOMPLETE_ANALYSIS`. A CLI and PowerShell wrapper will reuse the existing fixed builder lifecycle and persist all failures.

**Tech Stack:** Python 3.11, pytest, existing PSCAD Legacy backend, PowerShell 7, JSON evidence contracts.

---

### Task 1: Define The Dynamic Evidence Contract

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py`
- Test: `tests/test_lcc_dynamic_acceptance.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/__init__.py`

- [ ] **Step 1: Write the failing tests**

Add tests that construct a complete dynamic report and assert:

```python
def test_dynamic_report_requires_event_and_recovery_evidence():
    report = valid_dynamic_report()
    assert validate_dynamic_lcc_acceptance_report(report)["status"] == "INCOMPLETE_ANALYSIS"
    report["dynamic"]["recovery"] = None
    with pytest.raises(BackendError):
        validate_dynamic_lcc_acceptance_report(report)

def test_dynamic_report_does_not_promote_placeholder_golden():
    result = evaluate_fixed_lcc_dynamic_samples(
        valid_dynamic_samples(), placeholder_golden(), dynamic_contract()
    )
    assert result["verdict"] == "INCOMPLETE_ANALYSIS"

def test_dynamic_report_fails_when_required_channel_is_missing():
    samples = valid_dynamic_samples()
    del samples["Main/IDC"]
    result = evaluate_fixed_lcc_dynamic_samples(samples, {}, dynamic_contract())
    assert result["verdict"] == "FAIL"
    assert result["missing_channels"] == ["Main/IDC"]
```

The helpers must create real finite time/value vectors and use the production `acceptance.py` evaluator; do not assert only on mocks.

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_dynamic_acceptance.py -q`

Expected: collection or import failure because the new module and API do not exist.

- [ ] **Step 3: Implement the minimal contract and evaluator**

Implement:

```python
@dataclass(frozen=True)
class DynamicLccAcceptanceRequest:
    repository_root: Path
    workspace_root: Path
    master_path: Path
    compiler_configuration: Path
    compiler_executable: Path
    report_path: Path
    commit: str
    branch: str
    project_name: str
    simulation_duration_s: float
    output_step_s: float
    disturbance_time_s: float
    disturbance_duration_s: float

validate_dynamic_lcc_acceptance_report(value: Any) -> dict[str, Any]
evaluate_fixed_lcc_dynamic_samples(
    samples: Mapping[str, Any],
    golden: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]
```

The validator must enforce exact top-level fields, current commit/branch identity, a `dynamic.event` record with `time_s`, `duration_s`, and `kind`, explicit required channel names, a `dynamic.recovery` record, physical evidence, and a golden source record. The evaluator must return `FAIL` for absent required channels or failed physical checks, `INCOMPLETE_ANALYSIS` when physical evidence passes but the golden source is absent/unreviewed, and `PASS` only when both physical and independent-golden checks pass.

- [ ] **Step 4: Run the focused tests to verify GREEN**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_dynamic_acceptance.py -q`

Expected: all dynamic contract tests pass.

- [ ] **Step 5: Commit the contract**

```text
git add pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py pscad_mcp/hvdc/builders/lcc/__init__.py tests/test_lcc_dynamic_acceptance.py
git commit -m "feat: add fixed LCC dynamic acceptance contract"
```

### Task 2: Add CLI And Licensed Runner

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance_cli.py`
- Create: `scripts/run_fixed_lcc_dynamic_acceptance.ps1`
- Test: `tests/test_lcc_dynamic_acceptance_cli.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py`

- [ ] **Step 1: Write failing CLI and failure-persistence tests**

Cover argument parsing, clean named checkout requirements, current commit/branch binding, report path creation, and a simulated setup/build/cleanup failure that leaves a durable `FAIL` report with `failure.stage` and zero fabricated PASS fields.

- [ ] **Step 2: Run the tests to verify RED**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_dynamic_acceptance_cli.py -q`

Expected: import or command-not-found failures for the new CLI.

- [ ] **Step 3: Implement CLI and wrapper**

Reuse the fixed acceptance request/source hashing and Legacy backend factory. Add explicit dynamic request options for workspace, compiler, project name, simulation duration, output step, disturbance time, disturbance duration, and report. Use the existing cleanup/process-inventory helpers and never terminate processes outside the managed PSCAD PID. The runner must reject dirty or detached checkouts and write a durable report on every failure.

- [ ] **Step 4: Run CLI tests to verify GREEN**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_dynamic_acceptance_cli.py -q`

Expected: all CLI and failure-persistence tests pass.

- [ ] **Step 5: Commit the runner**

```text
git add pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py pscad_mcp/hvdc/builders/lcc/dynamic_acceptance_cli.py scripts/run_fixed_lcc_dynamic_acceptance.ps1 tests/test_lcc_dynamic_acceptance_cli.py
git commit -m "feat: add fixed LCC dynamic acceptance runner"
```

### Task 3: Update Program Documentation And Status Rules

**Files:**
- Modify: `docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md`
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Test: `tests/test_lcc_dynamic_acceptance.py`

- [ ] **Step 1: Add failing documentation/status assertions**

Assert that the roadmap's next step names WP1C, the fixed dynamic report is explicitly `INCOMPLETE_ANALYSIS` before independent golden review, and the baseline promotion helper refuses a dynamic report whose source is the packaged placeholder golden.

- [ ] **Step 2: Run the assertions to verify RED**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_dynamic_acceptance.py -q -k documentation`

Expected: the assertions fail against the stale roadmap wording or missing dynamic status text.

- [ ] **Step 3: Update the documents and tests**

Replace the stale roadmap §22 text with the WP1C execution order, document the new runner command and its status semantics in both READMEs, and keep the final-accepted exclusion tied to WP6. Do not change the WP1B evidence identity or claim a reviewed golden.

- [ ] **Step 4: Run the focused documentation tests**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_dynamic_acceptance.py -q`

Expected: all contract, evaluator, and documentation assertions pass.

- [ ] **Step 5: Commit documentation**

```text
git add docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md README.md docs/zh-CN/README.md tests/test_lcc_dynamic_acceptance.py
git commit -m "docs: record WP1C dynamic acceptance status"
```

### Task 4: Licensed Verification And Handoff

**Files:**
- Modify: `docs/acceptance/lcc-mmc-program-baseline.json` only if a current-commit report is produced and validated
- Create: external report under `D:/PSCAD-Workspace/lcc-wp1c-fixed-acceptance/`

- [ ] **Step 1: Run focused and fatal-static checks**

```text
D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_dynamic_acceptance.py tests/test_lcc_dynamic_acceptance_cli.py tests/test_lcc_fixed_acceptance.py -q
D:/pscad-mcp/.venv/Scripts/python.exe -m ruff check --select E9,F63,F7,F82 pscad_mcp/hvdc/builders/lcc tests/test_lcc_dynamic_acceptance.py tests/test_lcc_dynamic_acceptance_cli.py
git diff --check
```

Expected: focused tests pass, fatal Ruff checks pass, and no whitespace errors exist.

- [ ] **Step 2: Run the full repository suite**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest -q`

Expected: no regressions; record the exact passed/skipped counts.

- [ ] **Step 3: Run the licensed WP1C wrapper when PSCAD prerequisites are available**

Run the wrapper from the named clean worktree with the installed PSCAD 4.6.2 Master, compiler XML, and GFortran executable. Verify the report's commit equals the worktree HEAD, the event/recovery channels have exact domains, and no PSCAD process remains. A missing reviewed golden must produce `INCOMPLETE_ANALYSIS`, not `PASS` or `accepted`.

- [ ] **Step 4: Record evidence and inspect status**

Validate and hash the durable report. Update the baseline only if its schema accepts the current-commit report; otherwise retain the report as historical evidence and state the blocking reason.

- [ ] **Step 5: Commit the final verification record**

```text
git add docs/acceptance/lcc-mmc-program-baseline.json
git commit -m "test: record WP1C dynamic acceptance evidence"
```
