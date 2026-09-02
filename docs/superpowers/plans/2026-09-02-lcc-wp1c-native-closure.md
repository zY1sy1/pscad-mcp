# LCC WP1C Native Dynamic Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a current-commit, fail-closed `lcc.fixed_autonomous` WP1C path that uses an embedded EMTDC timer to drive three inverter-side fault breakers, derives dynamic engineering evidence from raw PSCAD output, and writes a durable report while keeping independent golden and final `accepted` status incomplete.

**Architecture:** Keep the existing fixed builder plan/hash/confirm boundary and WP1B runner intact. Extend the packaged fixed-LCC asset with an explicit timer-symbol contract, make `wp1c_dynamic` plan a post-compile binding check plus engineering-only dynamic acceptance, and put raw-waveform derivation, durable report orchestration, and CLI concerns in separate focused modules. The generic program-baseline schema is deliberately excluded from this implementation and is covered by the companion plan `docs/superpowers/plans/2026-09-02-lcc-program-baseline-gates.md`.

**Tech Stack:** Python 3.11, pytest, `mhi-pscad`/Legacy PSCAD 4.6.2, `mhi-psout`, JSON asset/report contracts, PowerShell 7, Git worktrees.

---

## Authority, starting point, and non-goals

- Approved design: `docs/superpowers/specs/2026-09-02-lcc-wp1c-native-closure-design.md`.
- Investigation baseline: `a2c725c` contains the approved design; execution starts from the commit containing this plan, on a new `codex/` worktree, and records the full HEAD before any licensed run.
- This plan supersedes `docs/superpowers/plans/2026-09-01-lcc-wp1c-fixed-dynamic-acceptance.md`.
- Tasks 1-11 are implementation and offline verification. Tasks 12-13 launch licensed PSCAD and require a separate explicit authorization at execution time.
- Baseline registration, merge, push, publication, package installation, WP1D rating sweeps, WP6 independent golden generation, and final `accepted` are not authorized by this plan.
- A successful pre-WP6 WP1C report is exactly `capability_state=simulated`, `engineering_verdict=PASS`, `golden_verdict=INCOMPLETE_ANALYSIS`, `status=INCOMPLETE_ANALYSIS`.

## File responsibility map

| File | Responsibility after implementation |
| --- | --- |
| `pscad_mcp/tools/lcc_tools.py` | Public MCP-compatible profile forwarding; no domain logic |
| `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/dynamic.json` | Hashed WP1C event, channel, threshold, window, and provenance contract |
| `pscad_mcp/hvdc/builders/lcc/assets.py` | Hash-verified loading of `dynamic.json` |
| `pscad_mcp/hvdc/builders/lcc/schema.py` | Exact JSON field/type parsing only |
| `pscad_mcp/hvdc/builders/lcc/fault_event.py` | Side-effect-free topology/control capability proof |
| `pscad_mcp/hvdc/builders/lcc/planner.py` | Deterministic operation selection and minimum-duration gate |
| `pscad_mcp/hvdc/builders/lcc/executor.py` | Saved/compiled binding readback and engineering gate before publish |
| `pscad_mcp/hvdc/builders/lcc/dynamic_evidence.py` | Exact-selector raw channel normalization and numerical derivation |
| `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py` | Result composition and exact durable report validation |
| `pscad_mcp/hvdc/builders/lcc/dynamic_runner.py` | Licensed lifecycle, artifact hashes, failure persistence, and owned-process cleanup |
| `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance_cli.py` | `evaluate` diagnostic compatibility and complete `run` command |
| `scripts/run_fixed_lcc_dynamic_acceptance.ps1` | Clean-checkout operator entry point for `run`; no hand-authored samples |
| `tests/lcc_dynamic_fakes.py` | Shared finite waveforms and exact dynamic test fixtures |

## Execution prerequisite

Before Task 1, use `superpowers:using-git-worktrees` to create an isolated worktree on branch `codex/lcc-wp1c-native-closure`. Run all commands from that worktree. Resolve the shared interpreter once and keep it in a task-specific variable:

```powershell
$wp1cPython = 'D:\pscad-mcp\.venv\Scripts\python.exe'
& $wp1cPython --version
git status --short --branch
git rev-parse HEAD
```

Expected: Python 3.11.x, a named `codex/lcc-wp1c-native-closure` branch, a clean worktree, and the commit that contains this plan. Do not copy `.venv` into the worktree.

### Task 1: Preserve the public plan/build API while exposing `wp1c_dynamic`

**Files:**

- Modify: `pscad_mcp/tools/lcc_tools.py`
- Modify: `tests/test_lcc_tools.py`
- Test: `tests/test_lcc_builder_service.py`

- [ ] **Step 1: Replace the positional-forwarding test with an exact keyword contract**

In `tests/test_lcc_tools.py`, replace `test_lcc_wrappers_forward_values_through_builder_service` with:

```python
def test_lcc_wrappers_preserve_old_positions_and_forward_profile_by_keyword(monkeypatch):
    calls = []

    class FakeBuilder:
        def plan_model(self, **kwargs):
            calls.append(("plan", kwargs))
            return {"plan_hash": "hash"}

        async def build_model(self, **kwargs):
            calls.append(("build", kwargs))
            return {"build_id": "build"}

        def get_build_status(self, *args):
            return {"state": "published"}

        def validate_model(self, *args):
            return {"valid": True}

    monkeypatch.setattr(lcc_tools, "_service", lambda: FakeBuilder())

    assert asyncio.run(
        lcc_tools.plan_lcc_model("Project", "Folder", 2.0, "bp")
    ) == {"plan_hash": "hash"}
    assert asyncio.run(
        lcc_tools.build_lcc_model(
            "Project", "hash", "Folder", 2.0, "bp", True
        )
    ) == {"build_id": "build"}
    assert asyncio.run(
        lcc_tools.plan_lcc_model(
            "Dynamic", verification_profile="wp1c_dynamic"
        )
    ) == {"plan_hash": "hash"}
    assert calls == [
        ("plan", {
            "project_name": "Project", "folder": "Folder",
            "simulation_duration_s": 2.0, "blueprint": "bp",
            "verification_profile": "full_acceptance",
        }),
        ("build", {
            "project_name": "Project", "expected_plan_hash": "hash",
            "folder": "Folder", "simulation_duration_s": 2.0,
            "blueprint": "bp", "verification_profile": "full_acceptance",
            "confirm": True,
        }),
        ("plan", {
            "project_name": "Dynamic", "folder": None,
            "simulation_duration_s": None,
            "blueprint": "cigre_lcc_monopole_v1",
            "verification_profile": "wp1c_dynamic",
        }),
    ]
```

- [ ] **Step 2: Run the test and verify the current positional bug is RED**

Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_tools.py::test_lcc_wrappers_preserve_old_positions_and_forward_profile_by_keyword
```

Expected: FAIL because the public functions do not accept `verification_profile`; the old build wrapper also binds positional `confirm` to the service's `verification_profile` slot.

- [ ] **Step 3: Append the public parameter and forward every service argument by keyword**

Use this implementation in `pscad_mcp/tools/lcc_tools.py`:

```python
async def plan_lcc_model(
    project_name: str,
    folder: str | None = None,
    simulation_duration_s: float | None = None,
    blueprint: str = "cigre_lcc_monopole_v1",
    verification_profile: str = "full_acceptance",
) -> dict[str, Any]:
    """Plan a fixed CIGRE LCC model build without changing the workspace."""
    return _service().plan_model(
        project_name=project_name,
        folder=folder,
        simulation_duration_s=simulation_duration_s,
        blueprint=blueprint,
        verification_profile=verification_profile,
    )


async def build_lcc_model(
    project_name: str,
    expected_plan_hash: str,
    folder: str | None = None,
    simulation_duration_s: float | None = None,
    blueprint: str = "cigre_lcc_monopole_v1",
    confirm: bool = False,
    verification_profile: str = "full_acceptance",
) -> dict[str, Any]:
    """Start a confirmed fixed CIGRE LCC model build from a matching plan."""
    return await _service().build_model(
        project_name=project_name,
        expected_plan_hash=expected_plan_hash,
        folder=folder,
        simulation_duration_s=simulation_duration_s,
        blueprint=blueprint,
        verification_profile=verification_profile,
        confirm=confirm,
    )
```

`verification_profile` stays after `confirm` in `build_lcc_model`; this preserves all six historical positional arguments.

- [ ] **Step 4: Run tool and service compatibility tests**

Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_tools.py tests/test_lcc_builder_service.py
```

Expected: all tests PASS; existing calls still resolve to `full_acceptance`, and explicit `wp1c_dynamic` reaches `LccBuilderService`.

- [ ] **Step 5: Commit the public boundary fix**

```powershell
git add pscad_mcp/tools/lcc_tools.py tests/test_lcc_tools.py
git commit -m "fix: preserve LCC build wrapper argument semantics"
```

### Task 2: Add the hashed embedded-event engineering contract

**Files:**

- Create: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/dynamic.json`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/catalog-pscad-4.6.2.json`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/PROVENANCE.md`
- Modify: `pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/manifest.json`
- Modify: `pscad_mcp/hvdc/builders/lcc/assets.py`
- Modify: `tests/test_lcc_assets.py`
- Modify: `tests/test_lcc_fault_shunt_assets.py`

- [ ] **Step 1: Write failing asset tests for the timer symbol and threshold provenance**

Add these assertions:

```python
def test_packaged_wp1c_contract_binds_one_timer_symbol_to_three_breakers():
    assets = load_packaged_asset_set()
    blueprint = assets.blueprint.to_dict()
    event = blueprint["dynamic_events"][0]
    components = {
        item["logical_id"]: item for item in blueprint["components"]
    }
    nets = {item["logical_id"]: item for item in blueprint["nets"]}

    assert assets.dynamic["identity"] == (
        "cigre_lcc_monopole_v1/wp1c_dynamic"
    )
    assert event["control_mode"] == "embedded_emtdc"
    assert event["control_signal"] == "LCC_FAULT_ACTIVE"
    assert event["recovery_window_s"] == pytest.approx(0.5)
    assert {
        components[name]["parameters"]["NAME"]
        for name in event["control_components"]
    } == {event["control_signal"]}
    assert nets["inverter_fault_active_integer"]["label"] == (
        event["control_signal"]
    )
    assert assets.dynamic["bounded_dc_response"][
        "maximum_peak_to_prefault_ratio"
    ] == pytest.approx(3.0)
    assert assets.dynamic["threshold_source"]["scope"] == "engineering_only"
```

- [ ] **Step 2: Run the asset tests and verify RED**

Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_assets.py tests/test_lcc_fault_shunt_assets.py -k "wp1c or timer_symbol"
```

Expected: FAIL because `LccAssetSet` has no `dynamic` member and the three breaker `NAME` values are numeric zero.

- [ ] **Step 3: Create the exact dynamic contract**

Create `dynamic.json` with this content:

```json
{
  "schema_version": 1,
  "identity": "cigre_lcc_monopole_v1/wp1c_dynamic",
  "event": {
    "kind": "inverter_ac_disturbance",
    "time_s": 0.8,
    "duration_s": 0.1,
    "recovery_window_s": 0.5,
    "control_mode": "embedded_emtdc",
    "control_signal": "LCC_FAULT_ACTIVE"
  },
  "required_channels": [
    {"path": "Fault/LCC Fault Active", "units": "state"},
    {"path": "Main/IDC", "units": "kA"},
    {"path": "Main/VDC_RECT", "units": "kV"},
    {"path": "Main/VDC_INV", "units": "kV"},
    {"path": "Main/GAMMA_INV", "units": "rad"}
  ],
  "disturbance": {
    "inactive_max": 0.1,
    "active_min": 0.9,
    "maximum_edge_error_s": 0.0001
  },
  "failure_indication": {
    "kind": "gamma_drop",
    "channel": "Main/GAMMA_INV",
    "units": "rad",
    "minimum_drop_rad": 0.017453292519943295
  },
  "bounded_dc_response": {
    "channel": "Main/IDC",
    "units": "kA",
    "prefault_window_s": 0.1,
    "minimum_prefault_magnitude_ka": 0.001,
    "maximum_peak_to_prefault_ratio": 3.0
  },
  "recovery": {
    "window_s": 0.5,
    "minimum_hold_s": 0.1,
    "channels": [
      {"path": "Main/IDC", "units": "kA", "relative_band": 0.2, "absolute_floor": 0.05},
      {"path": "Main/VDC_RECT", "units": "kV", "relative_band": 0.2, "absolute_floor": 5.0},
      {"path": "Main/VDC_INV", "units": "kV", "relative_band": 0.2, "absolute_floor": 5.0},
      {"path": "Main/GAMMA_INV", "units": "rad", "relative_band": 0.2, "absolute_floor": 0.03490658503988659}
    ]
  },
  "threshold_source": {
    "kind": "approved_repository_engineering_contract",
    "locator": "docs/superpowers/specs/2026-08-30-lcc-wp1a-native-acceptance-completion.md",
    "sha256": "7d76cfc0a8a9350bec512d3b5d732cea52304cd074e6ef90ed8cd885ff1116ff",
    "source_commit": "c6ad59f3f7638f8b884ea4b95e44c21cd31ff56c",
    "scope": "engineering_only"
  }
}
```

The `3.0` current ratio, `0.5 s` recovery window, one-degree indication drop, and 20%/two-degree recovery logic carry forward the reviewed WP1A engineering contract. They do not become an independent golden.

- [ ] **Step 4: Bind the blueprint and catalog to the exact symbol**

Apply these exact JSON changes:

```json
{
  "control_mode": "embedded_emtdc",
  "control_signal": "LCC_FAULT_ACTIVE",
  "recovery_window_s": 0.5
}
```

Add those fields to the single dynamic event; set `parameters.NAME` on `inverter_fault_breaker_a`, `_b`, and `_c` to `"LCC_FAULT_ACTIVE"`; set `inverter_fault_active_integer.label` to `"LCC_FAULT_ACTIVE"`. Change the catalog declaration for `master:breaker1.NAME` to:

```json
"NAME": {"type": "string", "required": true}
```

Do not change `master-bindings-pscad-4.6.2.json`'s physical contract `{"type":"Real"}`: PSCAD declares the parameter as a Real variable expression, while its logical value is the expression text. In `PROVENANCE.md`, record the installed `master.pslx` `content_type="Variable"` evidence and the official example pattern `breaker1.NAME=LCC_FAULT_ACTIVE` plus a matching data label; do not copy a protected Definition body.

- [ ] **Step 5: Load `dynamic.json` only after manifest verification**

Extend the dataclass and loader exactly as follows:

```python
@dataclass(frozen=True)
class LccAssetSet:
    name: str
    schema_version: int
    pscad_version: str
    companion_library: str
    blueprint: LccBlueprint
    catalog: dict[str, Any]
    acceptance: dict[str, Any]
    golden: dict[str, Any]
    smoke: dict[str, Any]
    provenance: str
    hashes: dict[str, str]
    library_bytes: bytes
    files: dict[str, bytes]
    dynamic: dict[str, Any] = field(default_factory=dict)
    root: None = None
    master_bindings: MasterBindingRegistry | None = None
    master_binding_hash: str | None = None
```

Import `field` from `dataclasses`. Add `dynamic.json` to `required`, parse it with `_json_record`, require identity `f"{name}/wp1c_dynamic"`, and pass it as `dynamic=dynamic` to `LccAssetSet`. Keeping the new field after the existing required fields with a default preserves keyword construction in isolated tests; the WP1C planner still rejects an empty dynamic contract.

- [ ] **Step 6: Refresh manifest hashes mechanically and verify GREEN**

First run this read-only canonical hash command:

```powershell
& $wp1cPython -c "from pathlib import Path; import hashlib; from pscad_mcp.hvdc.builders.lcc.assets import _canonical_asset_payload; r=Path('pscad_mcp/assets/lcc/cigre_lcc_monopole_v1'); [print(f'{p.relative_to(r).as_posix()}={hashlib.sha256(_canonical_asset_payload(p.relative_to(r).as_posix(), p.read_bytes())).hexdigest()}') for p in sorted(r.rglob('*')) if p.is_file() and p.name != 'manifest.json']"
```

Use `apply_patch` to replace the manifest's complete `hashes` object with exactly the emitted path/hash pairs. Then run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_assets.py tests/test_lcc_fault_shunt_assets.py tests/test_lcc_asset_audit.py
& $wp1cPython scripts/audit_lcc_assets.py
```

Expected: all tests PASS and the audit returns status `PASS` with no missing, unexpected, or mismatched asset.

- [ ] **Step 7: Commit the asset contract**

```powershell
git add pscad_mcp/assets/lcc/cigre_lcc_monopole_v1 pscad_mcp/hvdc/builders/lcc/assets.py tests/test_lcc_assets.py tests/test_lcc_fault_shunt_assets.py
git commit -m "feat: bind fixed LCC fault timer to breaker variables"
```

### Task 3: Make the WP1C preflight exact and side-effect-free

**Files:**

- Modify: `pscad_mcp/hvdc/builders/lcc/schema.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/fault_event.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/planner.py`
- Modify: `tests/test_lcc_schema.py`
- Modify: `tests/test_lcc_fault_event.py`
- Modify: `tests/test_lcc_planner.py`

- [ ] **Step 1: Add strict schema and capability failures**

Add parameterized tests that mutate one field at a time:

```python
@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("control_mode", "wall_clock", "fault_control_mode_invalid"),
        ("control_signal", "bad signal", "fault_control_signal_invalid"),
        ("recovery_window_s", 0.0, "fault_recovery_window_invalid"),
    ],
)
def test_wp1c_fault_contract_fails_closed(field, value, reason):
    blueprint = _asset("blueprint.json")
    catalog = _asset("catalog-pscad-4.6.2.json")
    inventory = _production_inventory()
    blueprint["dynamic_events"][0][field] = value

    result = inspect_fixed_lcc_fault_capability(
        blueprint, catalog, inventory
    )

    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert reason in result["reasons"]
```

Add a planner test that passes a duration of `1.39995` and a path policy rooted at an empty directory, then asserts `LCC_DYNAMIC_EVENT_UNAVAILABLE` and that the directory remains empty. Add a positive test for `1.4` and the recommended default `1.5`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_schema.py tests/test_lcc_fault_event.py tests/test_lcc_planner.py -k "wp1c or fault_contract or duration"
```

Expected: FAIL because the new event fields are rejected as unknown and duration is not tied to the recovery window.

- [ ] **Step 3: Extend exact parsing without hidden defaults**

Add these fields to `_DYNAMIC_EVENT_KEYS`; the existing derived `_DYNAMIC_EVENT_REQUIRED_KEYS` expression then makes all three mandatory:

```python
{
    "control_mode",
    "control_signal",
    "recovery_window_s",
}
```

In the dynamic event parser, validate them with:

```python
normalized["control_mode"] = _text(
    event["control_mode"], f"{context}.control_mode"
)
normalized["control_signal"] = _text(
    event["control_signal"], f"{context}.control_signal"
)
normalized["recovery_window_s"] = _number(
    event["recovery_window_s"],
    f"{context}.recovery_window_s",
    positive=True,
)
```

Do not default any of the three values in Python; the hashed asset owns them.

- [ ] **Step 4: Validate one selected mode, one producer, and three consumers**

In `fault_event.py`, add:

```python
_CONTROL_MODES = {"embedded_emtdc", "native_scheduler"}
_SIGNAL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _embedded_control_reasons(
    event: Mapping[str, Any],
    components: Mapping[str, Mapping[str, Any]],
    nets: Sequence[Mapping[str, Any]],
    inventory: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    mode = event.get("control_mode")
    signal = event.get("control_signal")
    if mode not in _CONTROL_MODES:
        reasons.append("fault_control_mode_invalid")
    if not isinstance(signal, str) or _SIGNAL.fullmatch(signal) is None:
        reasons.append("fault_control_signal_invalid")
    recovery = event.get("recovery_window_s")
    if (
        isinstance(recovery, bool)
        or not isinstance(recovery, (int, float))
        or not math.isfinite(float(recovery))
        or float(recovery) <= 0
    ):
        reasons.append("fault_recovery_window_invalid")
    if mode == "native_scheduler":
        capability = inventory.get("timed_control_capabilities")
        if (
            not isinstance(capability, Mapping)
            or capability.get("native_schedule") is not True
            or capability.get("simulation_clock") is not True
            or capability.get("time_basis") != "EMTDC"
        ):
            reasons.append("native_scheduler_unavailable")
        return reasons
    if mode != "embedded_emtdc" or not isinstance(signal, str):
        return reasons
    consumers = event.get("control_components", ())
    if len(consumers) != 3 or any(
        components.get(name, {}).get("parameters", {}).get("NAME") != signal
        for name in consumers
    ):
        reasons.append("fault_control_consumer_mismatch")
    producer_nets = [net for net in nets if net.get("label") == signal]
    endpoints = (
        {
            f"{item.get('component')}:{item.get('port')}"
            for item in producer_nets[0].get("endpoints", ())
            if isinstance(item, Mapping)
        }
        if len(producer_nets) == 1
        else set()
    )
    if len(producer_nets) != 1 or not (
        {"inverter_fault_timer:Y", "fault_active_adapter:IN"} <= endpoints
    ):
        reasons.append("fault_control_producer_mismatch")
    return reasons
```

Import `re`, call the helper from `inspect_fixed_lcc_fault_capability`, require the timer's logical `FaultTime_s`/`FaultDuration_s` values to equal the event, require each A-phase/B-phase/C-phase bus connection and grounded resistor branch to be unique, require the unique fault output to have `units == "state"`, and return `control_mode`, `control_signal`, `recovery_window_s`, timer, consumers, and output under `bindings` on PASS. Add one mutation test for every new reason, including `native_scheduler_unavailable`, timer/event mismatch, duplicated phase branch, and a second net carrying the control label.

- [ ] **Step 5: Enforce the duration before path resolution**

Immediately after `_duration(request, asset_set)` and before `_resolve_paths`, add:

```python
if request.verification_profile == WP1C_DYNAMIC_PROFILE:
    event = capability["bindings"]["event"]
    minimum_duration = (
        float(event["time_s"])
        + float(event["duration_s"])
        + float(capability["bindings"]["recovery_window_s"])
    )
    if duration + 1.0e-12 < minimum_duration:
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Simulation duration does not cover the complete recovery window.",
            simulation_duration_s=duration,
            minimum_duration_s=minimum_duration,
        )
```

Make the WP1C effective default `1.5` by having `_duration` use `1.5` when `simulation_duration_s is None` and profile is `wp1c_dynamic`; keep the packaged blueprint setting and every old profile's effective default unchanged.

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_schema.py tests/test_lcc_fault_event.py tests/test_lcc_planner.py
```

Expected: all tests PASS, including the no-files-on-preflight-failure assertion.

```powershell
git add pscad_mcp/hvdc/builders/lcc/schema.py pscad_mcp/hvdc/builders/lcc/fault_event.py pscad_mcp/hvdc/builders/lcc/planner.py tests/test_lcc_schema.py tests/test_lcc_fault_event.py tests/test_lcc_planner.py
git commit -m "feat: enforce fixed LCC dynamic capability gate"
```

### Task 4: Plan embedded control verification instead of requiring a scheduler

**Files:**

- Modify: `pscad_mcp/hvdc/builders/lcc/planner.py`
- Modify: `tests/test_lcc_planner.py`
- Modify: `tests/fixtures/lcc/lcc_plan_pre_common_baseline.json` only if an unchanged historical profile fixture legitimately changes; otherwise leave it byte-identical

- [ ] **Step 1: Specify exact WP1C operation order and legacy-profile stability**

Add these deterministic helpers first; they derive every definition and port from
the packaged assets and do not read an installed PSCAD tree:

```python
def packaged_dynamic_asset_set(
    *, control_mode: str = "embedded_emtdc"
) -> LccAssetSet:
    assets = load_packaged_asset_set()
    if control_mode == "embedded_emtdc":
        return assets
    blueprint = assets.blueprint.to_dict()
    blueprint["dynamic_events"][0]["control_mode"] = control_mode
    return replace(assets, blueprint=parse_blueprint(blueprint))


def complete_live_inventory(
    assets: LccAssetSet, *, native_schedule: bool = False
) -> dict[str, object]:
    registry = assets.master_bindings
    assert registry is not None
    definitions = {
        item["scoped_name"]: {"ports": copy.deepcopy(item["ports"])}
        for item in assets.catalog["definitions"]
    }
    for binding in registry.bindings:
        definitions[binding.logical_name].update({
            "physical_definition": binding.physical_definition,
            "verification_state": "verified",
            "selected_ports": {
                port.logical: {
                    "physical": port.physical,
                    "occurrence": port.occurrence,
                    "kind": port.kind,
                    "dimension": port.dimension,
                    "raw_dimension": port.dimension,
                    "model": None,
                    "type": None,
                    "mode": None,
                    "condition": None,
                    "offset": [0, 0],
                    "instance": port.instance,
                }
                for port in binding.ports
            },
        })
    return {
        "pscad_version": "4.6.2",
        "master_path": "C:/PSCAD46/master.pslx",
        "master_sha256": "a" * 64,
        "master_binding_registry_sha256": registry.sha256,
        "definitions": definitions,
        "timed_control_capabilities": {
            "native_schedule": native_schedule,
            "simulation_clock": native_schedule,
            "time_basis": "EMTDC" if native_schedule else "none",
        },
    }
```

`copy`, `replace`, `LccAssetSet`, `load_packaged_asset_set`, and
`parse_blueprint` already belong in this test module; retain those imports. Then
add:

```python
def test_wp1c_embedded_plan_verifies_control_then_dynamically_accepts(tmp_path):
    assets = packaged_dynamic_asset_set()
    plan = create_plan(
        _request(verification_profile=WP1C_DYNAMIC_PROFILE),
        assets,
        complete_live_inventory(assets),
        tmp_path,
    )
    kinds = [item.kind for item in plan.operations]

    assert kinds[kinds.index("compile") + 1] == "verify_dynamic_control"
    assert "register_dynamic_events" not in kinds
    assert kinds[-3:] == ["simulate", "dynamic_accept", "publish"]
    assert plan.metadata["dynamic_control"]["mode"] == "embedded_emtdc"


def test_native_scheduler_is_only_planned_when_explicitly_selected(tmp_path):
    assets = packaged_dynamic_asset_set(control_mode="native_scheduler")
    plan = create_plan(
        _request(verification_profile=WP1C_DYNAMIC_PROFILE),
        assets,
        complete_live_inventory(assets, native_schedule=True),
        tmp_path,
    )
    kinds = [item.kind for item in plan.operations]
    assert kinds[kinds.index("compile") + 1] == "register_dynamic_events"
    assert kinds[-3:] == ["simulate", "dynamic_accept", "publish"]
```

Also snapshot `full_acceptance` and `wp1b_smoke` plan hashes/operations before the implementation and assert those snapshots remain unchanged.

- [ ] **Step 2: Run planner tests and verify RED**

Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_planner.py -k "embedded_plan or native_scheduler or pre_common"
```

Expected: embedded plan test FAIL because every WP1C plan currently contains `register_dynamic_events` and generic `accept`.

- [ ] **Step 3: Add the two operation phases and exact branch**

Add `verify_dynamic_control`, `register_dynamic_events`, and `dynamic_accept` to `PHASES` between compile, simulate, and publish. Replace the unconditional WP1C registration block with:

```python
if request.verification_profile == WP1C_DYNAMIC_PROFILE:
    dynamic_control = capability["bindings"]
    if dynamic_control["control_mode"] == "embedded_emtdc":
        add(
            "verify_dynamic_control",
            "verify_dynamic_control",
            project_name,
            dynamic_control,
        )
    else:
        add(
            "register_dynamic_events",
            "register_dynamic_events",
            project_name,
            {"events": _dynamic_schedule_events(blueprint.dynamic_events)},
        )
```

Replace the post-simulation acceptance branch with:

```python
if request.verification_profile == WP1B_SMOKE_PROFILE:
    add("smoke_validate", "smoke_validate", project_name, smoke_arguments)
elif request.verification_profile == WP1C_DYNAMIC_PROFILE:
    add(
        "dynamic_accept",
        "dynamic_accept",
        project_name,
        {
            "contract_sha256": asset_set.hashes["dynamic.json"],
            "event": capability["bindings"]["event"],
        },
    )
else:
    add(
        "accept", "accept", project_name,
        {"required_checks": [check.name for check in checks]},
    )
```

Store `dynamic_control` in plan metadata only for WP1C. Do not change plan payloads for the other profiles.

- [ ] **Step 4: Run all planner tests and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_planner.py tests/test_common_builder.py
git diff -- tests/fixtures/lcc/lcc_plan_pre_common_baseline.json
```

Expected: all tests PASS and the pre-common fixture has no diff unless an already-documented wrapper bug requires it; WP1B/full operation order and hashes remain stable.

```powershell
git add pscad_mcp/hvdc/builders/lcc/planner.py tests/test_lcc_planner.py
git commit -m "feat: plan embedded fixed LCC dynamic control"
```

### Task 5: Verify the saved and compiled timer-to-breaker binding

**Files:**

- Modify: `pscad_mcp/hvdc/builders/lcc/executor.py`
- Modify: `tests/lcc_builder_fakes.py`
- Modify: `tests/test_lcc_executor.py`

- [ ] **Step 1: Add a fake-backed post-compile readback test**

Add:

```python
def test_executor_verifies_embedded_dynamic_control_after_compile(tmp_path):
    service = RecordingPscadService()
    plan = replace(_plan(tmp_path), verification_profile="wp1c_dynamic")
    executor = LccExecutor(
        plan, service, tmp_path,
    )
    executor.history.append({"state": "compiled"})
    executor.component_ids = {
        "inverter_fault_timer": 10,
        "inverter_fault_breaker_a": 11,
        "inverter_fault_breaker_b": 12,
        "inverter_fault_breaker_c": 13,
    }
    service.components = {
        10: {"parameters": {"FaultTime_s": 0.8,
                            "FaultDuration_s": 0.1}},
        11: {"parameters": {"NAME": "LCC_FAULT_ACTIVE"}},
        12: {"parameters": {"NAME": "LCC_FAULT_ACTIVE"}},
        13: {"parameters": {"NAME": "LCC_FAULT_ACTIVE"}},
    }
    operation = LccPlanOperation(
        sequence=1,
        kind="verify_dynamic_control",
        target="CIGRE_LCC",
        arguments={
            "control_mode": "embedded_emtdc",
            "control_signal": "LCC_FAULT_ACTIVE",
            "timer_component": "inverter_fault_timer",
            "control_components": [
                "inverter_fault_breaker_a",
                "inverter_fault_breaker_b",
                "inverter_fault_breaker_c",
            ],
            "channel": "Fault/LCC Fault Active",
            "event": {"time_s": 0.8, "duration_s": 0.1},
        },
    )

    asyncio.run(executor._verify_dynamic_control(operation))

    assert executor.result["dynamic_control"] == {
        "status": "PASS",
        "mode": "embedded_emtdc",
        "signal": "LCC_FAULT_ACTIVE",
        "timer_component_id": 10,
        "consumer_component_ids": [11, 12, 13],
        "output": "Fault/LCC Fault Active",
        "source": "compiled_project_readback",
    }
```

Add negative tests for one numeric `NAME`, one differing symbol, a missing timer ID, a timer/event timing mismatch, invocation before the `compiled` history state, and a `verify_master_binding_state` failure on a plan with pinned Master hashes. Each must raise `LCC_DYNAMIC_EVENT_UNAVAILABLE` and must not call `run_project`.

- [ ] **Step 2: Run the new executor tests and verify RED**

Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_executor.py -k "embedded_dynamic_control"
```

Expected: FAIL because `_verify_dynamic_control` and dispatch support do not exist.

- [ ] **Step 3: Implement exact readback and dispatch**

Add to `_dispatch`:

```text
elif operation.kind == "verify_dynamic_control":
    await self._verify_dynamic_control(operation)
```

Add this focused method:

```python
async def _verify_dynamic_control(
    self, operation: LccPlanOperation
) -> None:
    self._operation_started(operation)
    arguments = dict(operation.arguments)
    if (
        self.plan.verification_profile != "wp1c_dynamic"
        or arguments.get("control_mode") != "embedded_emtdc"
    ):
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Embedded dynamic control verification was not selected.",
            "verify_lcc_dynamic_control",
        )
    if not any(
        item.get("state") == LccBuildState.COMPILED.value
        for item in self.history
    ):
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Dynamic control verification requires a compiled project.",
            "verify_lcc_dynamic_control",
        )
    signal = arguments.get("control_signal")
    timer_name = arguments.get("timer_component")
    consumers = arguments.get("control_components")
    if not isinstance(signal, str) or not isinstance(timer_name, str):
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Dynamic control identity is incomplete.",
            "verify_lcc_dynamic_control",
        )
    if not isinstance(consumers, Sequence) or len(consumers) != 3:
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Dynamic control requires three breaker consumers.",
            "verify_lcc_dynamic_control",
        )
    await self._verify_master_binding_state(refresh_components=True)
    timer_id = self.component_ids.get(timer_name)
    consumer_ids = [self.component_ids.get(name) for name in consumers]
    if timer_id is None or any(value is None for value in consumer_ids):
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Dynamic control components are absent after compile.",
            "verify_lcc_dynamic_control",
        )
    timer_parameters = await self.service.get_component_parameters(
        self.project_name, int(timer_id)
    )
    event = arguments.get("event")
    if (
        not isinstance(event, Mapping)
        or not _same_setting(
            event.get("time_s"), timer_parameters.get("FaultTime_s")
        )
        or not _same_setting(
            event.get("duration_s"),
            timer_parameters.get("FaultDuration_s"),
        )
    ):
        raise _error(
            "LCC_DYNAMIC_EVENT_UNAVAILABLE",
            "Compiled fault timer parameters differ from the event contract.",
            "verify_lcc_dynamic_control",
        )
    for name, component_id in zip(consumers, consumer_ids):
        parameters = await self.service.get_component_parameters(
            self.project_name, int(component_id)
        )
        if parameters.get("NAME") != signal:
            raise _error(
                "LCC_DYNAMIC_EVENT_UNAVAILABLE",
                "A compiled fault breaker does not reference the timer signal.",
                "verify_lcc_dynamic_control",
                logical_id=name,
                expected=signal,
                observed=parameters.get("NAME"),
            )
    result = dict(self.result or {})
    result["dynamic_control"] = {
        "status": "PASS",
        "mode": "embedded_emtdc",
        "signal": signal,
        "timer_component_id": timer_id,
        "consumer_component_ids": [int(value) for value in consumer_ids],
        "output": arguments["channel"],
        "source": "compiled_project_readback",
    }
    self.result = result
    self._operation_completed()
```

`_verify_master_binding_state` already accepts `refresh_components`; use that exact keyword and do not bypass it. The earlier `save_and_validate` operation proves the saved label/net topology, while this post-compile operation proves that the component identities and variable/timer values survived compilation.

- [ ] **Step 4: Make the fake persist symbolic parameter values and run GREEN**

Ensure `RecordingPscadService._write_project()` writes the exact string and `get_component_parameters()` returns it unchanged. Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_executor.py tests/test_lcc_project_graph.py tests/test_lcc_template_bindings.py
```

Expected: all tests PASS; native scheduler tests remain PASS and are not used by the embedded plan.

- [ ] **Step 5: Commit the compiled binding gate**

```powershell
git add pscad_mcp/hvdc/builders/lcc/executor.py tests/lcc_builder_fakes.py tests/test_lcc_executor.py
git commit -m "feat: verify compiled LCC timer breaker binding"
```

### Task 6: Derive auditable dynamic evidence from exact raw channels

**Files:**

- Create: `pscad_mcp/hvdc/builders/lcc/dynamic_evidence.py`
- Create: `tests/lcc_dynamic_fakes.py`
- Create: `tests/test_lcc_dynamic_evidence.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/__init__.py`

- [ ] **Step 1: Create one shared, finite dynamic waveform fixture**

Create `tests/lcc_dynamic_fakes.py` with a loader for the production contract and this deterministic signal generator:

```python
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
DYNAMIC_CONTRACT = (
    ROOT
    / "pscad_mcp"
    / "assets"
    / "lcc"
    / "cigre_lcc_monopole_v1"
    / "dynamic.json"
)


def dynamic_contract() -> dict[str, Any]:
    return json.loads(DYNAMIC_CONTRACT.read_text(encoding="utf-8"))


def passing_raw_channels(
    *, step_s: float = 0.00005, end_s: float = 1.5
) -> dict[str, Any]:
    count = int(round(end_s / step_s)) + 1
    time = [round(index * step_s, 10) for index in range(count)]
    fault = [1.0 if 0.8 <= item < 0.9 else 0.0 for item in time]
    disturbed = [0.8 <= item < 0.9 for item in time]

    def channel(path: str, units: str, values: list[float]):
        return {"path": path, "units": units,
                "domain": time, "values": values}

    def constant(value: float) -> list[float]:
        return [float(value) for _item in time]
    return {
        "channels": [
            channel("Fault/LCC Fault Active", "state", fault),
            channel("Main/IDC", "kA", [
                1.5 if active else 1.0 for active in disturbed
            ]),
            channel("Main/VDC_RECT", "kV", [
                350.0 if active else 500.0 for active in disturbed
            ]),
            channel("Main/VDC_INV", "kV", [
                -250.0 if active else -480.0 for active in disturbed
            ]),
            channel("Main/GAMMA_INV", "rad", [
                math.radians(5.0 if active else 18.0)
                for active in disturbed
            ]),
            channel("Main/P_RECT", "MW", constant(500.0)),
            channel("Main/P_INV", "MW", constant(-480.0)),
            channel("Main/ALPHA_RECT", "rad", constant(math.radians(15.0))),
            channel("Main/MU_RECT", "rad", constant(math.radians(10.0))),
        ]
    }
```

Do not include a `dynamic` object in this fixture; every boolean and metric must come from the traces.

- [ ] **Step 2: Write a complete synthetic waveform test**

Use a 50 microsecond grid from `0.0` through `1.5 s`; generate exact paths and units. The passing fixture must hold fault state at one from `0.8` through the sample before `0.9`, drop gamma by at least one degree, keep `IDC` below three times the pre-fault median, and return all recovery channels to their pre-fault bands for `1.3-1.4 s`.

```python
def test_dynamic_evidence_derives_every_engineering_check_from_raw_channels():
    result = derive_fixed_lcc_dynamic_evidence(
        passing_raw_channels(), dynamic_contract(), output_step_s=0.00005
    )

    assert result["engineering_verdict"] == "PASS"
    assert set(result["checks"]) == {
        "disturbance", "failure_indication",
        "bounded_dc_response", "recovery",
    }
    for check in result["checks"].values():
        assert check["outcome"] == "PASS"
        assert check["selectors"]
        assert check["window_s"][1] > check["window_s"][0]
        assert check["sample_count"] > 0
        assert check["metrics"]
```

Import both helpers from `tests.lcc_dynamic_fakes`. Add tests with exact expected verdicts:

- missing required channel -> `FAIL`;
- duplicate exact selector -> `FAIL`;
- `Main/GAMMA_INV` unit `deg` when contract says `rad` -> `FAIL`;
- last timestamp `1.39995` -> `INCOMPLETE_ANALYSIS`;
- fault-active never rises -> `FAIL`;
- gamma does not drop -> `FAIL`;
- current peak ratio `3.01` -> `FAIL`;
- one recovery sample outside its band -> `FAIL`;
- a caller-supplied `dynamic` object is ignored.

- [ ] **Step 3: Run the new module and verify RED**

Run:

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_evidence.py
```

Expected: collection FAIL because `dynamic_evidence.py` does not exist.

- [ ] **Step 4: Implement exact selector and trace normalization**

Create immutable traces and reject fuzzy matching:

```python
@dataclass(frozen=True)
class Trace:
    path: str
    units: str
    time: Sequence[float]
    values: Sequence[float]


def normalize_exact_channels(
    value: Mapping[str, Any], required: Sequence[Mapping[str, Any]]
) -> dict[str, Trace]:
    raw = value.get("channels")
    records = (
        [{"path": name, **dict(item)} for name, item in raw.items()]
        if isinstance(raw, Mapping)
        else list(raw) if isinstance(raw, Sequence) and not isinstance(
            raw, (str, bytes, bytearray)
        ) else []
    )
    by_path: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        if isinstance(record, Mapping) and isinstance(record.get("path"), str):
            by_path.setdefault(record["path"], []).append(record)
    traces: dict[str, Trace] = {}
    for declaration in required:
        path = str(declaration["path"])
        matches = by_path.get(path, [])
        if len(matches) != 1:
            raise DynamicEvidenceError("selector_count", path)
        record = matches[0]
        units = record.get("units", record.get("unit"))
        if units != declaration["units"]:
            raise DynamicEvidenceError("unit_mismatch", path)
        domain = record.get("domain", record.get("time"))
        samples = record.get("values", record.get("samples"))
        times = tuple(float(item) for item in domain)
        values = tuple(float(item) for item in samples)
        if (
            not times or len(times) != len(values)
            or not all(math.isfinite(item) for item in (*times, *values))
            or any(right <= left for left, right in pairwise(times))
        ):
            raise DynamicEvidenceError("invalid_trace", path)
        traces[path] = Trace(path, str(units), times, values)
    return traces
```

Define `DynamicEvidenceError` as a private exception carrying `reason` and `selector`; translate it into a `FAIL` check rather than leaking it from the public derivation function.

- [ ] **Step 5: Implement the four deterministic checks**

Use `statistics.median` for the `0.7-0.8 s` pre-fault reference. Apply these exact rules:

```python
clear_s = event_time_s + event_duration_s
domain_end_s = clear_s + recovery_window_s
edge_tolerance_s = max(
    float(contract["disturbance"]["maximum_edge_error_s"]),
    2.0 * output_step_s,
)

# disturbance
# pre-fault values <= inactive_max, event values >= active_min,
# post-clear values <= inactive_max, and measured threshold crossings are
# within edge_tolerance_s of event_time_s and clear_s.

# failure_indication
# median gamma over [event_time_s - 0.1, event_time_s) minus the minimum
# gamma over [event_time_s, clear_s) >= minimum_drop_rad.

# bounded_dc_response
# max(abs(IDC)) over [event_time_s, domain_end_s] divided by
# abs(median(IDC over [event_time_s - prefault_window_s, event_time_s)))
# is <= maximum_peak_to_prefault_ratio; prefault magnitude below the
# declared minimum is FAIL.

# recovery
# for every declared recovery channel, every sample in
# [domain_end_s - minimum_hold_s, domain_end_s] differs from its pre-fault
# median by no more than max(abs(median) * relative_band, absolute_floor).
```

Each check record must have exactly `outcome`, `selectors`, `units`, `window_s`, `sample_count`, and `metrics`. Return `INCOMPLETE_ANALYSIS` only for insufficient time-domain coverage; return `FAIL` for selector, unit, finite-value, or engineering-bound failures.

- [ ] **Step 6: Run all derivation cases and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_evidence.py
& $wp1cPython -m ruff check pscad_mcp/hvdc/builders/lcc/dynamic_evidence.py tests/test_lcc_dynamic_evidence.py
```

Expected: all tests and Ruff PASS.

```powershell
git add pscad_mcp/hvdc/builders/lcc/dynamic_evidence.py pscad_mcp/hvdc/builders/lcc/__init__.py tests/lcc_dynamic_fakes.py tests/test_lcc_dynamic_evidence.py
git commit -m "feat: derive fixed LCC dynamic waveform evidence"
```

### Task 7: Add an engineering-only dynamic executor gate

**Files:**

- Modify: `pscad_mcp/hvdc/builders/lcc/models.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/executor.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/acceptance.py`
- Modify: `tests/test_lcc_acceptance.py`
- Modify: `tests/test_lcc_executor.py`

- [ ] **Step 1: Test that engineering PASS may publish while total status stays incomplete**

Add an executor test with real finite channel vectors:

```python
def test_wp1c_executor_accepts_engineering_pass_without_forging_total_pass(
    tmp_path,
):
    assets = load_packaged_asset_set()
    base = _plan(tmp_path)
    plan = replace(
        base,
        blueprint=replace(
            base.blueprint,
            settings={"simulation_duration_s": 1.5,
                      "output_step_s": 0.00005},
        ),
        verification_profile="wp1c_dynamic",
        asset_hashes={"dynamic.json": assets.hashes["dynamic.json"]},
    )
    service = RecordingPscadService(output=passing_raw_channels())
    executor = LccExecutor(
        plan, service, tmp_path, asset_set=assets,
    )
    operation = LccPlanOperation(
        sequence=1,
        kind="dynamic_accept",
        target="executor",
        arguments={
            "contract_sha256": assets.hashes["dynamic.json"],
            "event": {"time_s": 0.8, "duration_s": 0.1},
        },
    )

    asyncio.run(executor._dynamic_accept(operation))

    assert executor.result["engineering_verdict"] == "PASS"
    assert executor.result["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert executor.result["status"] == "INCOMPLETE_ANALYSIS"
    assert any(
        item.get("state") == "dynamic_engineering_passed"
        for item in executor.history
    )
```

Import `passing_raw_channels` from `tests.lcc_dynamic_fakes`. Add a failing-current fixture, call `_dynamic_accept`, assert error code `LCC_DYNAMIC_ACCEPTANCE_FAILED`, and assert there is no `save_project_as` call. Planner ordering plus these two cases proves publication cannot be reached until the gate succeeds.

Add a focused `tests/test_lcc_acceptance.py` case whose raw
`Main/GAMMA_INV` trace is in radians and whose physical `angle_interval`
contract is in degrees. Assert that 18 degrees expressed as radians passes and
5 degrees expressed as radians fails the 10-40 degree interval. This pins the
unit conversion used by the production WP1C fixture.

- [ ] **Step 2: Run the executor cases and verify RED**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_executor.py -k "wp1c_executor"
```

Expected: FAIL because `_dynamic_accept` and the state enum are absent.

- [ ] **Step 3: Add the non-final state and dynamic dispatcher**

Add to `LccBuildState`:

```python
DYNAMIC_ENGINEERING_PASSED = "dynamic_engineering_passed"
```

Extend the existing `_UNIT_TO_SI` table in `acceptance.py` with the exact
angle conversion scale:

```python
_UNIT_TO_SI["rad"] = ("angle", 180.0 / math.pi)
```

Keep `"deg": ("angle", 1.0)` unchanged. This makes the existing `_convert`
path convert the blueprint-declared radian outputs into the physical
contract's degrees; it does not relabel the raw evidence.

Add to `_dispatch`:

```text
elif operation.kind == "dynamic_accept":
    await self._dynamic_accept(operation)
```

Implement:

```python
async def _dynamic_accept(self, operation: LccPlanOperation) -> None:
    self._operation_started(operation)
    if self.plan.verification_profile != "wp1c_dynamic" or self.asset_set is None:
        raise _error(
            "LCC_DYNAMIC_ACCEPTANCE_FAILED",
            "Dynamic acceptance requires a verified WP1C asset set.",
            "evaluate_lcc_dynamic_acceptance",
        )
    expected_hash = operation.arguments.get("contract_sha256")
    if expected_hash != self.asset_set.hashes.get("dynamic.json"):
        raise _error(
            "LCC_ASSET_MISMATCH",
            "The dynamic contract changed after planning.",
            "evaluate_lcc_dynamic_acceptance",
        )
    output = await self._acceptance_output()
    dynamic = derive_fixed_lcc_dynamic_evidence(
        output,
        self.asset_set.dynamic,
        output_step_s=float(self.plan.blueprint.settings["output_step_s"]),
    )
    physical_contract = dict(self.asset_set.acceptance)
    physical_contract["golden"] = {"channels": []}
    physical_contract["checks"] = [
        item for item in self.asset_set.acceptance.get("checks", ())
        if isinstance(item, Mapping) and item.get("kind") == "physical"
    ]
    physical = evaluate_acceptance(output, {}, physical_contract)
    engineering = (
        "FAIL" if "FAIL" in {
            dynamic["engineering_verdict"], physical["verdict"]
        }
        else "INCOMPLETE_ANALYSIS"
        if "INCOMPLETE_ANALYSIS" in {
            dynamic["engineering_verdict"], physical["verdict"]
        }
        else "PASS"
    )
    result = dict(self.result or {})
    result.update({
        "dynamic": dynamic,
        "physical": physical,
        "engineering_verdict": engineering,
        "golden_verdict": "INCOMPLETE_ANALYSIS",
        "status": "FAIL" if engineering == "FAIL" else "INCOMPLETE_ANALYSIS",
        "output_file": self.output_file,
        "output_parts": list(self.output_parts or ()),
    })
    self.result = result
    if engineering != "PASS":
        raise _error(
            "LCC_DYNAMIC_ACCEPTANCE_FAILED",
            "The fixed LCC dynamic engineering contract did not pass.",
            "evaluate_lcc_dynamic_acceptance",
            acceptance=result,
        )
    self._record(LccBuildState.DYNAMIC_ENGINEERING_PASSED)
```

Hash every selected output part, not only the first file, and store `{path, sha256}` records under `output_artifacts`.

- [ ] **Step 4: Run executor regression and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_executor.py tests/test_lcc_acceptance.py tests/test_lcc_smoke.py
```

Expected: all tests PASS; full acceptance still requires total PASS, WP1B still records `smoke_passed`, and only WP1C uses `dynamic_engineering_passed`.

```powershell
git add pscad_mcp/hvdc/builders/lcc/models.py pscad_mcp/hvdc/builders/lcc/executor.py pscad_mcp/hvdc/builders/lcc/acceptance.py tests/test_lcc_acceptance.py tests/test_lcc_executor.py
git commit -m "feat: gate fixed LCC publication on dynamic engineering"
```

### Task 8: Finalize the durable WP1C report and licensed orchestrator

**Files:**

- Create: `pscad_mcp/hvdc/builders/lcc/dynamic_runner.py`
- Modify: `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py`
- Modify: `tests/lcc_dynamic_fakes.py`
- Modify: `tests/test_lcc_dynamic_acceptance.py`
- Create: `tests/test_lcc_dynamic_runner.py`

- [ ] **Step 1: Replace caller-boolean tests with layered report tests**

Rename the existing `valid_dynamic_report()` helper to
`valid_wp1c_report()` and replace its body with a runner-shaped report. The
fixture must use `kind="licensed_simulation"`,
`capability_state="simulated"`, a clean same-commit repository record,
`preflight.status="PASS"`, unchanged `before`/`after` hashes for every source,
a published build with `dynamic_engineering_passed` in its history, at least
one hashed OUT part plus one hashed INF or INFX metadata part, a hashed
`normalized-samples.json`, `dynamic.evidence_source="raw_pscad_output"`,
`physical.verdict="PASS"`, an unreviewed placeholder golden, an empty
`runtime.remaining_processes`, and `failure=None`. Its top-level keys are
exactly:

```python
REPORT_KEYS = {
    "schema_version", "run_id", "scope", "builder_path", "kind",
    "capability_state", "commit", "generated_at_utc",
    "engineering_verdict", "golden_verdict", "status",
    "repository", "preflight", "sources", "build", "artifacts",
    "dynamic", "physical", "golden", "runtime",
    "explicit_exclusions", "failure",
}
```

Add tests that enforce:

```python
def test_wp1c_report_allows_engineering_pass_with_incomplete_golden():
    report = valid_wp1c_report()
    normalized = validate_dynamic_lcc_acceptance_report(report)
    assert normalized["capability_state"] == "simulated"
    assert normalized["kind"] == "licensed_simulation"
    assert normalized["engineering_verdict"] == "PASS"
    assert normalized["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert normalized["status"] == "INCOMPLETE_ANALYSIS"


def test_wp1c_report_rejects_total_pass_without_reviewed_golden():
    report = valid_wp1c_report()
    report["status"] = "PASS"
    with pytest.raises(BackendError) as raised:
        validate_dynamic_lcc_acceptance_report(report)
    assert raised.value.code == "LCC_DYNAMIC_REPORT_INVALID"
```

Also reject a mismatched commit/branch, missing part hash, absence of both INF
and INFX metadata, source before/after drift, engineering FAIL with total
INCOMPLETE, cleanup residue, and caller-supplied diagnostic evidence marked as
runner evidence. Put the shared factory in `tests/lcc_dynamic_fakes.py` so the
runner tests use exactly the same envelope.

- [ ] **Step 2: Run report tests and verify RED**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_acceptance.py
```

Expected: FAIL because the current report schema has no layered verdicts and allows `capability_state=accepted`.

- [ ] **Step 3: Make `dynamic_acceptance.py` a strict composition/validation module**

Keep `evaluate_fixed_lcc_dynamic_samples()` as a diagnostic compatibility function, but mark its return with:

```python
{"evidence_source": "caller_supplied_diagnostic", "durable": False}
```

Add:

```python
def combine_dynamic_verdicts(
    engineering_verdict: str, golden_verdict: str
) -> str:
    if "FAIL" in {engineering_verdict, golden_verdict}:
        return "FAIL"
    if {engineering_verdict, golden_verdict} == {"PASS"}:
        return "PASS"
    return "INCOMPLETE_ANALYSIS"
```

The report validator must require `kind="licensed_simulation"`, `capability_state="simulated"`, `dynamic.evidence_source="raw_pscad_output"`, `engineering_verdict` equal to the combined dynamic/physical result, and total status equal to `combine_dynamic_verdicts`. It must require both `independent_golden` and `final_accepted` in exclusions until `golden.reviewed is True` and its source is not a placeholder.

- [ ] **Step 4: Write runner tests for every lifecycle terminal path**

In `tests/test_lcc_dynamic_runner.py`, add `valid_request(tmp_path)`,
`PassingDynamicService`, and `PassingDynamicBuilder` locally. The request must
point every input to a regular file below `tmp_path`, pin the current synthetic
commit/branch, and place the report below a separate workspace directory.
`PassingDynamicService` must record setup/attach/quit and expose the raw OUT
dataset produced by `passing_raw_channels()`; `PassingDynamicBuilder` must
record keyword arguments, return a fixed plan hash, return a fixed build id,
and then return `published` with a history containing
`dynamic_engineering_passed`. Neither fake may return a precomputed dynamic
verdict. Cover:

```python
def test_runner_rederives_output_and_persists_incomplete_success(tmp_path):
    report = asyncio.run(
        run_fixed_lcc_dynamic_acceptance(
            valid_request(tmp_path),
            service=PassingDynamicService(),
            builder=PassingDynamicBuilder(),
            process_reader=lambda: [],
            poll_interval_s=0,
        )
    )
    assert report["engineering_verdict"] == "PASS"
    assert report["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert report["status"] == "INCOMPLETE_ANALYSIS"
    assert report["dynamic"]["evidence_source"] == "raw_pscad_output"
    assert report["runtime"]["remaining_processes"] == []
```

Add setup, attach, plan, build, poll timeout, output re-read, evidence mismatch, report validation, quit, source drift, and remaining-owned-process failures. Every case that passes static preflight must write a strict `FAIL` report with the exact `failure.stage`; a static/capability preflight failure must write a strict report without creating a project.

- [ ] **Step 5: Implement the request and runner state machine**

Create:

```python
@dataclass(frozen=True)
class DynamicLccRunRequest:
    repository_root: Path
    workspace_root: Path
    master_path: Path
    compiler_configuration: Path
    compiler_executable: Path
    report_path: Path
    commit: str
    branch: str
    project_name: str = "WP1C_FIXED_LCC"
    simulation_duration_s: float = 1.5
    output_step_s: float = 0.00005
    preflight: Mapping[str, Any] = field(default_factory=dict)
```

Implement `run_fixed_lcc_dynamic_acceptance()` with stages `setup`, `attach`, `plan`, `build`, `poll`, `output`, `derive`, `report`, and `cleanup`. The runner must:

1. hash blueprint, catalog, dynamic contract, registry, manifest, companion, installed Master, compiler configuration, and compiler executable before attach;
2. call `plan_model(project_name=request.project_name, folder=str(request.workspace_root), simulation_duration_s=request.simulation_duration_s, blueprint="cigre_lcc_monopole_v1", verification_profile="wp1c_dynamic")` and call `build_model` with the returned plan hash, the same named arguments, and `confirm=True`;
3. require terminal state `published` and history state `dynamic_engineering_passed`;
4. re-read the selected output dataset with `summary_only=False`; normalize the selected numbered OUT path to its dataset stem; enumerate only regular files named by that exact stem (`stem_*.out`, `stem.inf`, and `stem.infx`) inside the staging directory; reject symlinks, path escapes, stale mtimes, a missing OUT part, or absence of both INF and INFX metadata; hash every selected part; write canonical `normalized-samples.json`; rederive evidence; and byte-compare its canonical form with executor evidence;
5. validate, atomically write, reload, hash, and revalidate the report;
6. quit the builder/service, terminate only runner-owned PIDs, and require an empty owned-process remainder;
7. hash all read-only sources again and convert any drift or cleanup error to total `FAIL`.

Use the existing bounded polling and output-dataset rules as contracts; do not import private underscore helpers from `fixed_acceptance.py`.

- [ ] **Step 6: Run report/runner tests and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_acceptance.py tests/test_lcc_dynamic_runner.py tests/test_lcc_fixed_acceptance.py
& $wp1cPython -m ruff check pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py pscad_mcp/hvdc/builders/lcc/dynamic_runner.py tests/test_lcc_dynamic_acceptance.py tests/test_lcc_dynamic_runner.py
```

Expected: all tests and Ruff PASS; WP1B report validation remains unchanged.

```powershell
git add pscad_mcp/hvdc/builders/lcc/dynamic_acceptance.py pscad_mcp/hvdc/builders/lcc/dynamic_runner.py tests/lcc_dynamic_fakes.py tests/test_lcc_dynamic_acceptance.py tests/test_lcc_dynamic_runner.py
git commit -m "feat: orchestrate fixed LCC dynamic evidence"
```

### Task 9: Add `run` CLI semantics and replace the manual-samples wrapper

**Files:**

- Modify: `pscad_mcp/hvdc/builders/lcc/dynamic_acceptance_cli.py`
- Modify: `scripts/run_fixed_lcc_dynamic_acceptance.ps1`
- Modify: `tests/test_lcc_dynamic_acceptance_cli.py`
- Create: `tests/test_lcc_dynamic_acceptance_real.py`

- [ ] **Step 1: Write exact exit-code and wrapper tests**

Add the pure exit-code helper and tests first:

```python
@pytest.mark.parametrize(
    ("preflight", "engineering", "expected"),
    [
        ("FAIL", "FAIL", 2),
        ("PASS", "FAIL", 1),
        ("PASS", "PASS", 0),
    ],
)
def test_run_exit_code_separates_preflight_and_engineering(
    preflight, engineering, expected
):
    assert (
        run_exit_code(
            preflight_status=preflight,
            engineering_verdict=engineering,
        )
        == expected
    )
```

For the engineering PASS fixture, assert top-level status is still `INCOMPLETE_ANALYSIS`. Add a test that reads the PowerShell file and asserts it contains `dynamic_acceptance_cli 'run'` and does not contain mandatory `Samples`, `Golden`, or `Contract` parameters.

- [ ] **Step 2: Run CLI tests and verify RED**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_acceptance_cli.py
```

Expected: FAIL because the CLI supports only `evaluate` and returns nonzero for all incomplete reports.

- [ ] **Step 3: Add the complete `run` parser and dependency seams**

Add required arguments:

```python
run = commands.add_parser("run")
run.add_argument("--repository-root", type=Path, required=True)
run.add_argument("--workspace-root", type=Path, required=True)
run.add_argument("--master-path", type=Path, required=True)
run.add_argument("--compiler-configuration", type=Path, required=True)
run.add_argument("--compiler-executable", type=Path, required=True)
run.add_argument("--report", type=Path, required=True)
run.add_argument("--commit", required=True)
run.add_argument("--branch", required=True)
run.add_argument("--project-name", default="WP1C_FIXED_LCC")
run.add_argument("--simulation-duration", type=float, default=1.5)
run.add_argument("--output-step", type=float, default=0.00005)
```

Keep `evaluate` as a diagnostic command with its historical exit behavior. For `run`, return `2` when preflight/capability fails before service creation, `1` for lifecycle/report/cleanup or engineering failure, and `0` only when report validation passes and `engineering_verdict == "PASS"`; do not require total status PASS.

Implement and call this helper from the `run` branch after report validation:

```python
def run_exit_code(
    *, preflight_status: str, engineering_verdict: str
) -> int:
    if preflight_status != "PASS":
        return 2
    return 0 if engineering_verdict == "PASS" else 1
```

Add one `main()` integration test per row using local call-recording fakes for
the preflight action, runner action, and service factory. Assert the service
factory is never called on exit 2 and that engineering PASS still returns a
validated top-level `status="INCOMPLETE_ANALYSIS"` report.

- [ ] **Step 4: Rewrite the PowerShell operator entry point**

Use parameters `WorkspaceRoot`, `MasterPath`, `CompilerConfiguration`, `CompilerExecutable`, and `ProjectName`. Require `PSCAD_MCP_ACCEPTANCE=1`, a clean named checkout, exact HEAD/branch discovery, no pre-existing PSCAD process, a timestamped run root, and then call:

```powershell
& $wp1cPython -m pscad_mcp.hvdc.builders.lcc.dynamic_acceptance_cli 'run' `
    --repository-root $RepositoryRoot `
    --workspace-root $RunRoot `
    --master-path $MasterPath `
    --compiler-configuration $CompilerConfiguration `
    --compiler-executable $CompilerExecutable `
    --report $Report `
    --commit $Commit `
    --branch $Branch `
    --project-name $ProjectName `
    --simulation-duration 1.5 `
    --output-step 0.00005
```

Afterward require no PSCAD process and print `FIXED_LCC_DYNAMIC_REPORT`, `FIXED_LCC_DYNAMIC_REPORT_SHA256`, `FIXED_LCC_DYNAMIC_ENGINEERING_VERDICT`, and `FIXED_LCC_DYNAMIC_STATUS`.

- [ ] **Step 5: Add an opt-in real test that is skipped offline**

Create:

```python
pytestmark = pytest.mark.skipif(
    os.getenv("PSCAD_MCP_ACCEPTANCE") != "1",
    reason="Set PSCAD_MCP_ACCEPTANCE=1 for licensed WP1C validation.",
)


def test_fixed_lcc_dynamic_runner_uses_current_named_checkout(tmp_path):
    result = invoke_real_dynamic_cli_from_environment(tmp_path)
    assert result.exit_code == 0
    assert result.report["engineering_verdict"] == "PASS"
    assert result.report["golden_verdict"] == "INCOMPLETE_ANALYSIS"
    assert result.report["status"] == "INCOMPLETE_ANALYSIS"
    assert result.report["commit"] == git_head()
    assert result.report["runtime"]["remaining_processes"] == []
```

Define `invoke_real_dynamic_cli_from_environment()` and `git_head()` in the same test file. They must require explicit compiler/Master/workspace environment paths and call the production CLI; they may not fabricate samples.

- [ ] **Step 6: Run offline CLI and skip tests, then commit**

```powershell
Remove-Item Env:PSCAD_MCP_ACCEPTANCE -ErrorAction SilentlyContinue
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_acceptance_cli.py tests/test_lcc_dynamic_acceptance_real.py -rs
```

Expected: CLI tests PASS and the one real test is reported SKIPPED for the explicit opt-in reason.

```powershell
git add pscad_mcp/hvdc/builders/lcc/dynamic_acceptance_cli.py scripts/run_fixed_lcc_dynamic_acceptance.ps1 tests/test_lcc_dynamic_acceptance_cli.py tests/test_lcc_dynamic_acceptance_real.py
git commit -m "feat: add fixed LCC dynamic licensed runner"
```

### Task 10: Document truthful WP1B/WP1C/WP6 status and commands

**Files:**

- Modify: `README.md`
- Modify: `docs/zh-CN/README.md`
- Modify: `docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md`
- Modify: `tests/test_lcc_dynamic_acceptance.py`
- Modify: `tests/test_documentation_runtime.py`

- [ ] **Step 1: Add failing documentation assertions**

Add assertions for all four phrases in both READMEs:

```python
required = {
    "wp1b_smoke",
    "wp1c_dynamic",
    "engineering_verdict=PASS",
    "status=INCOMPLETE_ANALYSIS",
}
assert all(item in readme for item in required)
assert "WP1C accepted" not in readme
```

Also assert the roadmap names WP1C's full runner, WP1B-before-WP1C ordering, the companion baseline-gates plan, and WP6 as the only independent-golden/final-accepted owner.

- [ ] **Step 2: Run documentation tests and verify RED**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_acceptance.py tests/test_documentation_runtime.py -k "readme or roadmap or wp1c"
```

Expected: FAIL because the current README documents only the manual evaluator semantics.

- [ ] **Step 3: Update commands and evidence language**

Document the operator command using the four exact installed paths from Task 12, the three exit codes, and this exact successful pre-WP6 statement:

> fixed LCC WP1C current-commit dynamic engineering evidence completed; final status remains `INCOMPLETE_ANALYSIS` pending independent reviewed golden.

Keep the existing historical WP1B report identified as historical until Task 12 produces a same-commit report. Do not change the checked-in program baseline in this task.

- [ ] **Step 4: Run documentation tests and commit**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_acceptance.py tests/test_documentation_runtime.py
```

Expected: all tests PASS.

```powershell
git add README.md docs/zh-CN/README.md docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md tests/test_lcc_dynamic_acceptance.py tests/test_documentation_runtime.py
git commit -m "docs: define fixed LCC WP1C evidence boundary"
```

### Task 11: Run the complete offline verification gate

**Files:**

- No production files should change
- Record command output in the execution transcript; do not commit cache or generated output

- [ ] **Step 1: Clear every licensed opt-in from the current shell**

```powershell
Get-ChildItem Env: | Where-Object {
    $_.Name -like 'PSCAD_MCP_*ACCEPTANCE*'
} | ForEach-Object {
    Remove-Item -LiteralPath "Env:$($_.Name)"
}
```

Expected: a subsequent `Get-ChildItem Env:PSCAD_MCP_*ACCEPTANCE* -ErrorAction SilentlyContinue` returns nothing.

- [ ] **Step 2: Run the focused WP1B/WP1C regression set**

```powershell
& $wp1cPython -m pytest -q `
  tests/test_lcc_tools.py `
  tests/test_lcc_builder_service.py `
  tests/test_lcc_assets.py `
  tests/test_lcc_schema.py `
  tests/test_lcc_fault_event.py `
  tests/test_lcc_fault_shunt_assets.py `
  tests/test_lcc_planner.py `
  tests/test_lcc_executor.py `
  tests/test_lcc_smoke.py `
  tests/test_lcc_fixed_acceptance.py `
  tests/test_lcc_dynamic_evidence.py `
  tests/test_lcc_dynamic_acceptance.py `
  tests/test_lcc_dynamic_runner.py `
  tests/test_lcc_dynamic_acceptance_cli.py `
  tests/test_lcc_dynamic_acceptance_real.py -rs
```

Expected: zero failures; the real test is skipped because opt-in is absent. Record exact passed/skipped counts.

- [ ] **Step 3: Run fatal static, syntax, package, and whitespace gates**

```powershell
& $wp1cPython -m ruff check --select E9,F63,F7,F82 pscad_mcp tests
& $wp1cPython -m compileall -q pscad_mcp tests
& $wp1cPython -m pip check
& $wp1cPython -m pytest -q tests/test_packaging_metadata.py tests/test_install_smoke.py tests/test_repository_hygiene.py
git diff --check
```

Expected: each command exits zero, Ruff prints `All checks passed!`, `pip check` reports no broken requirements, and Git prints no whitespace errors.

- [ ] **Step 4: Run the full offline suite**

```powershell
& $wp1cPython -m pytest -q
```

Expected: zero failures; licensed tests remain skipped. Record the exact counts rather than reusing the investigation baseline `2401 passed, 47 skipped`.

- [ ] **Step 5: Prove the execution branch is clean**

```powershell
git status --short --branch
git log --oneline --decorate -12
```

Expected: no uncommitted files and a linear set of focused commits from Tasks 1-10. If any test changed a source, asset, existing report, or baseline file, stop and investigate before licensed execution.

### Task 12: Licensed same-commit WP1B then WP1C evidence

**Files:**

- Create outside repository: `D:/PSCAD-Workspace/lcc-wp1c-native-closure/`; each runner creates its own UTC timestamp plus UUID child directory below this root
- Do not modify: `docs/acceptance/lcc-mmc-program-baseline.json`

> **Authorization gate:** Stop here until the user explicitly authorizes launching licensed PSCAD. That authorization does not authorize baseline promotion, merge, or push.

- [ ] **Step 1: Reconfirm checkout and environment identity without mutation**

```powershell
git status --porcelain
git branch --show-current
git rev-parse HEAD
Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -like 'PSCAD*'
}
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Program Files (x86)\PSCAD46\master.pslx'
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Program Files (x86)\PSCAD46\fortran_compilers.xml'
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Program Files (x86)\GFortran\4.6\bin\gfortran.exe'
```

Expected: clean named branch, no PSCAD process, and hashes exactly `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939`, `bd6183220badfa7a32f5419e8563d9b5c598fc370d50970d9e0bfaba092f6ca1`, and `fd179ba3ddb0df54ddc59911042947d97a20f039297279eb6cbf9554b32c8665`. If any hash differs, stop with preflight exit semantics; do not update expected identities during the run.

- [ ] **Step 2: Run the current-commit WP1B no-fault gate first**

```powershell
$env:PSCAD_MCP_ACCEPTANCE = '1'
& .\scripts\run_fixed_lcc_smoke_acceptance.ps1 `
  -WorkspaceRoot 'D:\PSCAD-Workspace\lcc-wp1c-native-closure' `
  -MasterPath 'C:\Program Files (x86)\PSCAD46\master.pslx' `
  -CompilerConfiguration 'C:\Program Files (x86)\PSCAD46\fortran_compilers.xml' `
  -CompilerExecutable 'C:\Program Files (x86)\GFortran\4.6\bin\gfortran.exe' `
  -ProjectName 'WP1B_FIXED_LCC'
```

Expected: exit zero, a durable current-HEAD `simulated/PASS` report, final project reload/recompile PASS, output parts hashed, sources unchanged, and zero remaining PSCAD process. If WP1B fails, stop; do not run WP1C.

- [ ] **Step 3: Run the 1.5 s WP1C dynamic gate on the same HEAD**

```powershell
& .\scripts\run_fixed_lcc_dynamic_acceptance.ps1 `
  -WorkspaceRoot 'D:\PSCAD-Workspace\lcc-wp1c-native-closure' `
  -MasterPath 'C:\Program Files (x86)\PSCAD46\master.pslx' `
  -CompilerConfiguration 'C:\Program Files (x86)\PSCAD46\fortran_compilers.xml' `
  -CompilerExecutable 'C:\Program Files (x86)\GFortran\4.6\bin\gfortran.exe' `
  -ProjectName 'WP1C_FIXED_LCC'
```

Expected: exit zero and printed values `FIXED_LCC_DYNAMIC_ENGINEERING_VERDICT=PASS` and `FIXED_LCC_DYNAMIC_STATUS=INCOMPLETE_ANALYSIS`. If `breaker1.NAME` rejects the symbol, stop with `LCC_DYNAMIC_EVENT_UNAVAILABLE`, retain the quarantined candidate and compile messages, and open a separate Master-compatible component design; do not switch to wall-clock control.

- [ ] **Step 4: Independently validate both reports and all hashes**

For each printed report path, run strict loader/validator code and `Get-FileHash`. Confirm both reports own the same full commit and branch, each source before/after hash matches, WP1C covers through at least `1.4 s`, every check contains selectors/units/window/sample count/metrics, the normalized-samples hash matches, and `runtime.remaining_processes` is empty.

Expected: WP1B `status=PASS`; WP1C `engineering_verdict=PASS`, `golden_verdict=INCOMPLETE_ANALYSIS`, `status=INCOMPLETE_ANALYSIS`. Do not label the second result simply `PASS`.

- [ ] **Step 5: Clear the opt-in and leave repository state untouched**

```powershell
Remove-Item Env:PSCAD_MCP_ACCEPTANCE -ErrorAction SilentlyContinue
git status --short --branch
```

Expected: clean repository; only external run directories contain new artifacts.

### Task 13: Review, completion record, and baseline handoff

**Files:**

- Create after licensed success: `docs/superpowers/specs/2026-09-02-lcc-wp1c-native-closure-completion.md`
- Do not modify: `docs/acceptance/lcc-mmc-program-baseline.json`

- [ ] **Step 1: Run an independent code/evidence review**

Use `superpowers:requesting-code-review`. Provide the approved design, this plan, the complete branch diff, full offline outputs, both exact report paths/hashes, normalized samples, OUT/INF part hashes, and cleanup evidence. Require every Critical/Important finding to be resolved with a reproducing test and a fresh verification run.

- [ ] **Step 2: Write the completion record from verified values only**

Record full commit, branch, exact test counts, each report path/hash/run ID, project/companion/output/sample hashes, event timing, observed domain, each numerical check, source before/after hashes, cleanup result, and review conclusion. End with exactly:

> fixed LCC WP1C current-commit dynamic engineering evidence completed; final status remains `INCOMPLETE_ANALYSIS` pending independent reviewed golden.

Do not create the record when WP1B or WP1C engineering evidence failed.

- [ ] **Step 3: Re-run document and diff checks, then commit only the completion record**

```powershell
& $wp1cPython -m pytest -q tests/test_lcc_dynamic_acceptance.py tests/test_documentation_runtime.py
git diff --check
git add docs/superpowers/specs/2026-09-02-lcc-wp1c-native-closure-completion.md
git commit -m "docs: record fixed LCC WP1C engineering evidence"
```

Expected: tests PASS, no whitespace errors, and the commit contains no baseline or generated PSCAD artifacts.

- [ ] **Step 4: Hand the two validated reports to the companion baseline plan**

Continue with `docs/superpowers/plans/2026-09-02-lcc-program-baseline-gates.md` only after a separate baseline-promotion approval. If promotion is not approved, retain both external reports and report `baseline_scope_granularity_insufficient`; do not overwrite WP1B's scope record.

## Final stop conditions

Stop without fallback if any of these occurs: live inventory is absent or not 4.6.2; the control symbol does not survive save/reload/compile; scheduler mode is selected without native EMTDC capability readback; duration or output domain is short; OUT/INF selection is ambiguous; units mismatch; a source hash changes; checkout identity changes; external PSCAD already exists; an owned PSCAD process remains; or report validation fails. Preserve the journal, candidate/quarantine path, compile output, and a durable non-PASS report after any post-write failure.
