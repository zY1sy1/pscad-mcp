# Fixed LCC Fault/Event Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed preflight contract that identifies whether the fixed LCC blueprint has a complete inverter AC fault/event binding.

**Architecture:** Keep the existing fixed builder and WP1B profile unchanged. Add a side-effect-free validator over blueprint/catalog/inventory records, then expose the result to the planner only through an opt-in `wp1c_dynamic` profile. The current assets intentionally fail this gate with explicit reasons.

**Tech Stack:** Python 3.11, pytest, existing LCC schema/catalog models, JSON evidence records.

---

### Task 1: Event Contract And Capability Inspector

**Files:**
- Create: `pscad_mcp/hvdc/builders/lcc/fault_event.py`
- Test: `tests/test_lcc_fault_event.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/__init__.py`

- [ ] **Step 1: Write failing tests**

Cover valid `inverter_ac_disturbance` timing and `(1, 1, 1)` phase mask, rejection of zero/negative duration and non-inverter targets, and inspection of the current packaged blueprint returning `INCOMPLETE_ANALYSIS` with `fault_timer_missing`, `fault_shunt_missing`, and `fault_channel_missing` reasons.

- [ ] **Step 2: Run tests to verify RED**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_fault_event.py -q`

Expected: import failure because `fault_event.py` does not exist.

- [ ] **Step 3: Implement the pure validator**

Define:

```python
@dataclass(frozen=True)
class FixedLccFaultEvent:
    kind: str
    target_bus: str
    time_s: float
    duration_s: float
    phase_mask: tuple[int, int, int]

validate_fixed_lcc_fault_event(event: Mapping[str, Any] | FixedLccFaultEvent) -> dict[str, Any]
inspect_fixed_lcc_fault_capability(blueprint: Mapping[str, Any], catalog: Mapping[str, Any], inventory: Mapping[str, Any]) -> dict[str, Any]
```

Require exact event fields and explicit inventory definitions/ports. Return `PASS` only when every required binding is uniquely present and connected; otherwise return `INCOMPLETE_ANALYSIS` with stable reason codes and observed counts.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_fault_event.py -q`

Expected: all event and current-asset gate tests pass.

- [ ] **Step 5: Commit**

```text
git add pscad_mcp/hvdc/builders/lcc/fault_event.py pscad_mcp/hvdc/builders/lcc/__init__.py tests/test_lcc_fault_event.py
git commit -m "feat: add fixed LCC fault event capability gate"
```

### Task 2: Opt-In Planner Profile

**Files:**
- Modify: `pscad_mcp/hvdc/builders/lcc/planner.py`
- Modify: `tests/test_lcc_planner.py`

- [ ] **Step 1: Add failing planner tests**

Assert that `wp1c_dynamic` is recognized as an opt-in profile, the current asset/inventory rejects it with `LCC_DYNAMIC_EVENT_UNAVAILABLE`, and `wp1b_smoke` still produces the exact existing operations and hash behavior.

- [ ] **Step 2: Run tests to verify RED**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_planner.py -q -k dynamic`

Expected: the profile is unsupported or the dynamic gate is not called.

- [ ] **Step 3: Implement the profile gate**

Add `WP1C_DYNAMIC_PROFILE = "wp1c_dynamic"` to `VERIFICATION_PROFILES`. Before operation expansion, call `inspect_fixed_lcc_fault_capability()` for this profile and raise `LCC_DYNAMIC_EVENT_UNAVAILABLE` with the structured reasons when the result is not `PASS`. Do not change the default profile or WP1B branch.

- [ ] **Step 4: Run planner tests to verify GREEN**

Run: `D:/pscad-mcp/.venv/Scripts/python.exe -m pytest tests/test_lcc_planner.py -q`

Expected: planner tests pass with existing profile behavior unchanged.

- [ ] **Step 5: Commit**

```text
git add pscad_mcp/hvdc/builders/lcc/planner.py tests/test_lcc_planner.py
git commit -m "feat: gate fixed LCC dynamic planner profile"
```

### Task 3: Documentation And Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md`

- [ ] **Step 1: Document the explicit blocker**

Describe `wp1c_dynamic` as opt-in and fail-closed, list the required timer/shunt/event/channel bindings, and state that the current fixed companion returns `INCOMPLETE_ANALYSIS` until those bindings exist.

- [ ] **Step 2: Verify**

Run focused fault-event/planner tests, fatal Ruff, PowerShell parser checks, `git diff --check`, and the full repository suite. Record that no baseline promotion or licensed run occurs in this step.

- [ ] **Step 3: Commit documentation**

```text
git add README.md docs/zh-CN/README.md docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md
git commit -m "docs: define fixed LCC fault event gate"
```
