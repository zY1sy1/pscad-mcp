# HVDC Simulation-Time Scheduling and Explicit Bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HVDC timed events use strict EMTDC simulation time, authorize mutations only through explicit project-qualified bindings, resolve the real Breaker output channels without ambiguity, and fail safely when timing, output, or physical semantics are unconfirmed.

**Architecture:** Keep generic MCP tools stable and add focused HVDC modules for binding resolution, timing selection, preflight, and audit evidence. Extend the internal backend contract with conservative timed-control capability methods; real backends report unsupported until a verified vendor capability exists, while the HVDC scheduler supports native scheduling and simulation-clock polling through the same contract. Profile version 2 separates read-only aliases, writable commands, explicit result selectors, metric roles, and binary sequence semantics.

**Tech Stack:** Python 3.12, `asyncio`, dataclasses and typed mappings, `pytest`, PSCAD 4.6.2 legacy `mhrc.automation`, PSCAD 5.x `mhi.pscad`, legacy `.inf` plus segmented `.out`, SHA-256 audit evidence.

---

## Execution prerequisites

Before Task 1, use `superpowers:using-git-worktrees` to create an isolated branch such as `codex/hvdc-simulation-time-bindings`. Run this clean baseline from the isolated worktree:

```powershell
$tests = Get-ChildItem tests -Filter 'test_hvdc*.py' | ForEach-Object { $_.FullName }
& .\.venv\Scripts\python.exe -m pytest @tests tests\test_psout_reader.py -q
```

Expected: the current baseline reports `122 passed, 1 skipped` before feature changes.

## File responsibility map

- `pscad_mcp/hvdc/profiles.py`: profile-v2 schema, inheritance, and built-in Breaker selectors.
- `pscad_mcp/hvdc/bindings.py`: project fingerprint matching and unique command binding resolution.
- `pscad_mcp/hvdc/timing.py`: capability selection, native scheduling, and simulation-clock polling.
- `pscad_mcp/hvdc/preflight.py`: side-effect ordering, output readiness, and required-selector checks.
- `pscad_mcp/hvdc/audit.py`: deterministic profile/file hashes and JSON-safe evidence.
- `pscad_mcp/hvdc/scenarios.py`: scenario lifecycle integration, verified writes, rollback, and strict timed dispatch.
- `pscad_mcp/hvdc/results.py`: explicit selector-based result normalization.
- `pscad_mcp/hvdc/metrics.py`: unit-aware derived metrics and profile-defined binary edges/sequences.
- `pscad_mcp/core/backend/base.py`: timed-control backend protocol.
- `pscad_mcp/core/backend/legacy.py`: explicit conservative PSCAD 4.6 capability result.
- `pscad_mcp/core/backend/modern.py`: explicit conservative PSCAD 5 capability result.
- `pscad_mcp/core/service.py`: stable service proxies for the internal timing contract.
- `pscad_mcp/core/pscad_adapter.py`: retained legacy INF channel metadata.
- `tests/test_hvdc_profiles_v2.py`: profile-v2 validation and built-in selector tests.
- `tests/test_hvdc_bindings.py`: fingerprint and command-binding tests.
- `tests/test_hvdc_timing.py`: strict simulation-time scheduler tests.
- `tests/test_hvdc_preflight.py`: output readiness and side-effect-order tests.
- `tests/test_hvdc_scenarios.py`: end-to-end scenario orchestration behavior.
- `tests/test_hvdc_scenario_containment.py`: timeout, settlement, and lease regression behavior.
- `tests/test_psout_reader.py`: legacy INF metadata parsing.
- `tests/test_hvdc_metrics.py`: selector, unit, edge, and sequence metrics.
- `tests/test_hvdc_real_acceptance.py`: opt-in PSCAD 4.6 Breaker acceptance.
- `README.md` and `docs/zh-CN/README.md`: new guarantees and explicit limitations.

### Task 1: Add the profile-v2 contract and split Breaker result channels

**Files:**
- Create: `tests/test_hvdc_profiles_v2.py`
- Modify: `pscad_mcp/hvdc/profiles.py:12-122`
- Modify: `tests/test_hvdc_breaker_fixture.py:12-43`

- [ ] **Step 1: Write failing profile-v2 schema tests**

Create `tests/test_hvdc_profiles_v2.py` with tests that load JSON through the public `load_profile()` path:

```python
import json

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.profiles import load_profile


def _write_profile(tmp_path, payload):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_profile_v2_accepts_explicit_commands_results_and_metric_roles(tmp_path):
    path = _write_profile(tmp_path, {
        "profile_version": 2,
        "required_assets": ["breaker"],
        "mappings": [],
        "project_fingerprints": [{"project_stem": "case", "definitions": ["loadbreaker_3"]}],
        "command_bindings": [{
            "canonical": "breaker_command",
            "component": {"canvas": "BreakerBlock", "definition": "master:const", "component_id": "17"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
            "read_back": True,
        }],
        "result_channels": [{
            "canonical": "dc_voltage_breaker",
            "path": "loadbreaker_3/UMC",
            "call_id": 90,
            "units": "kV",
            "location": "breaker",
        }],
        "metric_roles": {"dc_voltage": "dc_voltage_breaker"},
        "sequences": [],
    })

    loaded = load_profile("case_profile", str(path))

    assert loaded["profile_version"] == 2
    assert loaded["command_bindings"][0]["parameter_name"] == "Value"
    assert loaded["result_channels"][0]["call_id"] == 90
    assert loaded["metric_roles"] == {"dc_voltage": "dc_voltage_breaker"}


@pytest.mark.parametrize("field", ["command_bindings", "result_channels"])
def test_profile_v2_rejects_duplicate_canonicals(tmp_path, field):
    item = (
        {"canonical": "x", "component": {"definition": "master:const"}, "parameter_name": "Value", "allowed_values": [0, 1], "semantics": "active_high"}
        if field == "command_bindings"
        else {"canonical": "x", "path": "Main/X", "units": "kV"}
    )
    payload = {
        "profile_version": 2,
        "required_assets": [],
        "mappings": [],
        "project_fingerprints": [],
        "command_bindings": [item, dict(item)],
        "result_channels": [],
        "metric_roles": {},
        "sequences": [],
    }
    if field == "result_channels":
        payload["command_bindings"] = []
        payload["result_channels"] = [item, dict(item)]
    path = _write_profile(tmp_path, payload)

    with pytest.raises(BackendError, match="duplicated"):
        load_profile("case_profile", str(path))
```

Extend `tests/test_hvdc_breaker_fixture.py` to assert that `hvdc_breaker_difforder` has `profile_version == 2`, no built-in writable command binding, and these exact result canonicals:

```python
assert {item["canonical"] for item in profile["result_channels"]} == {
    "dc_voltage_breaker",
    "dc_current_breaker",
    "breaker_command_observed",
    "dc_voltage_rectifier_pole1",
    "dc_voltage_inverter_pole1",
    "dc_voltage_rectifier_pole2",
    "dc_voltage_inverter_pole2",
}
assert profile["command_bindings"] == []
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_profiles_v2.py tests\test_hvdc_breaker_fixture.py -q
```

Expected: failures because profile-v2 fields are neither validated nor present in the built-in Breaker profile.

- [ ] **Step 3: Implement strict profile-v2 validation and inheritance**

In `profiles.py`, keep version 1 profiles backward compatible. For version 2, validate all sections and copy nested values before returning them. Add helpers with these signatures:

```python
def _validate_unique_canonicals(items: Any, field: str, name: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise _invalid(f"'{field}' must be a list.", name)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise _invalid(f"{field}[{index}] must be an object.", name)
        item = dict(raw)
        canonical = item.get("canonical")
        if not isinstance(canonical, str) or not canonical.strip():
            raise _invalid(f"{field}[{index}] requires a non-empty canonical.", name)
        if canonical in seen:
            raise _invalid(f"Canonical '{canonical}' is duplicated in '{field}'.", name)
        seen.add(canonical)
        result.append(item)
    return result


def _validate_profile_v2(profile: dict[str, Any], name: str) -> None:
    fingerprints = profile.get("project_fingerprints", [])
    if not isinstance(fingerprints, list) or any(not isinstance(item, dict) for item in fingerprints):
        raise _invalid("'project_fingerprints' must be a list of objects.", name)
    commands = _validate_unique_canonicals(profile.get("command_bindings", []), "command_bindings", name)
    results = _validate_unique_canonicals(profile.get("result_channels", []), "result_channels", name)
    for item in commands:
        if not isinstance(item.get("component"), dict):
            raise _invalid(f"Command '{item['canonical']}' requires a component selector.", name)
        if not isinstance(item.get("parameter_name"), str) or not item["parameter_name"].strip():
            raise _invalid(f"Command '{item['canonical']}' requires parameter_name.", name)
        if not isinstance(item.get("allowed_values"), list) or not item["allowed_values"]:
            raise _invalid(f"Command '{item['canonical']}' requires allowed_values.", name)
        if item.get("semantics") not in {"active_high", "active_low", "open", "close", "enable", "disable"}:
            raise _invalid(f"Command '{item['canonical']}' has invalid semantics.", name)
    for item in results:
        if not isinstance(item.get("path"), str) or not item["path"].strip():
            raise _invalid(f"Result '{item['canonical']}' requires path.", name)
        if item.get("call_id") is not None and (isinstance(item["call_id"], bool) or not isinstance(item["call_id"], int) or item["call_id"] < 1):
            raise _invalid(f"Result '{item['canonical']}' has invalid call_id.", name)
    roles = profile.get("metric_roles", {})
    if not isinstance(roles, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in roles.items()):
        raise _invalid("'metric_roles' must map strings to strings.", name)
    sequences = profile.get("sequences", [])
    if not isinstance(sequences, list) or any(not isinstance(item, dict) for item in sequences):
        raise _invalid("'sequences' must be a list of objects.", name)
```

Call `_validate_profile_v2()` when `profile_version == 2`; reject booleans and values other than integer `1` or `2`. Extend `_merge_profile()` so child version-2 lists override items with the same canonical while retaining unrelated parent items, and dictionaries such as `metric_roles` merge parent-first.

Upgrade only `hvdc_breaker_difforder` to version 2. Add the seven exact selectors from the approved design, with call IDs `90`, `83`, `78`, `1`, `3`, `6`, and `9`. Keep `command_bindings` and `sequences` empty because the real writable parameter and active levels are not confirmed.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/profiles.py tests/test_hvdc_profiles_v2.py tests/test_hvdc_breaker_fixture.py
git commit -m "feat: define explicit HVDC profile bindings"
```

### Task 2: Resolve project fingerprints and command bindings without alias inference

**Files:**
- Create: `pscad_mcp/hvdc/bindings.py`
- Create: `tests/test_hvdc_bindings.py`
- Modify: `pscad_mcp/hvdc/scenarios.py:136-231`

- [ ] **Step 1: Write failing binding-resolution tests**

Create a small PSCX fixture in each test and call the public resolver:

```python
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.bindings import resolve_command_binding
from pscad_mcp.hvdc.scanner import scan_project


def _evidence(tmp_path: Path):
    path = tmp_path / "case.pscx"
    path.write_text("""<project name='case' version='4.6.2'>
      <definition name='Main'><canvas name='Main'>
        <component id='17' name='Trip command' definition='master:const'>
          <parameter name='Value' value='0'/><parameter name='Name' value='BrkOrd1'/>
        </component>
      </canvas></definition><definition name='loadbreaker_3'/>
    </project>""", encoding="utf-8")
    return scan_project(path)


def test_binding_requires_matching_fingerprint_and_unique_component(tmp_path):
    evidence = _evidence(tmp_path)
    profile = {
        "profile_version": 2,
        "project_fingerprints": [{"project_stem": "case", "pscad_version": "4.6.2", "definitions": ["loadbreaker_3"]}],
        "command_bindings": [{
            "canonical": "breaker_command",
            "component": {"canvas": "Main", "definition": "master:const", "component_id": "17"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
            "read_back": True,
        }],
    }

    binding = resolve_command_binding(evidence, profile, "breaker_command", 1)

    assert binding["component_id"] == "17"
    assert binding["parameter_name"] == "Value"
    assert binding["read_back"] is True


def test_binding_rejects_unlisted_value(tmp_path):
    evidence = _evidence(tmp_path)
    profile = {"profile_version": 2, "project_fingerprints": [], "command_bindings": [{
        "canonical": "breaker_command",
        "component": {"component_id": "17", "definition": "master:const"},
        "parameter_name": "Value",
        "allowed_values": [0, 1],
        "semantics": "active_high",
    }]}

    with pytest.raises(BackendError, match="allowed"):
        resolve_command_binding(evidence, profile, "breaker_command", 2)


def test_display_parameter_remains_forbidden_even_when_profile_names_it(tmp_path):
    evidence = _evidence(tmp_path)
    profile = {"profile_version": 2, "project_fingerprints": [], "command_bindings": [{
        "canonical": "breaker_command",
        "component": {"component_id": "17"},
        "parameter_name": "Name",
        "allowed_values": ["BrkOrd1"],
        "semantics": "active_high",
    }]}

    with pytest.raises(BackendError) as raised:
        resolve_command_binding(evidence, profile, "breaker_command", "BrkOrd1")
    assert raised.value.details["reason"] == "unsafe_command_parameter"
```

Add cases for zero matches, two matches, a mismatched project stem, and a missing parameter in the selected component.

- [ ] **Step 2: Run tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_bindings.py -q
```

Expected: import failure because `bindings.py` does not exist.

- [ ] **Step 3: Implement binding resolution**

Create `bindings.py` with three public functions: `matching_fingerprints(evidence,
profile)`, `resolve_command_binding(evidence, profile, canonical, value)`, and
`resolve_requested_commands(evidence, profile, requests)`. The first returns a
list of matched fingerprint dictionaries, the second returns one JSON-safe
resolved binding dictionary, and the third preserves request order while
returning one resolved binding per request.

Implement the bodies without aliases:

- fingerprint fields are conjunctive; omitted fields are unconstrained;
- `definitions` is a required subset of `evidence.definitions`;
- component selector fields `component_id`, `canvas`, and `definition` are conjunctive;
- exactly one component must match;
- the exact `parameter_name` must exist in `component.parameters`;
- normalized parameter names in the existing unsafe set are rejected;
- the requested value must equal an entry in `allowed_values` using type-sensitive equality so `True` does not equal `1`;
- the returned binding contains canonical, component ID, parameter name, old scanned value, semantics, read-back flag, and matched fingerprint.

Move `_UNSAFE_COMMAND_PARAMETERS` to this module and import it from `scenarios.py`. Delete the alias-based `_bind_approved_commands()` authorization path after Task 5 integrates the new resolver; until then, leave its callers unchanged so this task remains independently green.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Step 2 command. Expected: all binding tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/bindings.py pscad_mcp/hvdc/scenarios.py tests/test_hvdc_bindings.py
git commit -m "feat: resolve explicit HVDC commands"
```

### Task 3: Add a conservative timed-control backend contract

**Files:**
- Modify: `pscad_mcp/core/backend/base.py:118-219`
- Modify: `pscad_mcp/core/backend/legacy.py`
- Modify: `pscad_mcp/core/backend/modern.py`
- Modify: `pscad_mcp/core/service.py:432-447`
- Create: `tests/test_hvdc_timing.py`
- Modify: `tests/test_tool_backend_matrix.py`

- [ ] **Step 1: Write failing contract and scheduler-selection tests**

In `tests/test_hvdc_timing.py`, define fake services for native, polling, and unsupported modes:

```python
import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.timing import dispatch_timed_events, select_timing_mode


class NativeTimingBackend:
    async def get_timed_control_capabilities(self, project_name):
        return {"native_schedule": True, "simulation_clock": True}

    async def schedule_timed_controls(self, project_name, events):
        return [{"index": 0, "requested_time_s": 1.0, "observed_time_s": 1.0, "status": "registered"}]


class PollingTimingBackend:
    def __init__(self):
        self.times = iter([0.0, 0.4, 1.05])
        self.writes = []

    async def get_timed_control_capabilities(self, project_name):
        return {"native_schedule": False, "simulation_clock": True}

    async def get_simulation_time(self, project_name):
        return next(self.times)

    async def set_component_parameters(self, project_name, component_id, values):
        self.writes.append((project_name, component_id, values))


def test_native_timing_is_preferred():
    assert asyncio.run(select_timing_mode(NativeTimingBackend(), "case")) == "native"


def test_polling_dispatch_uses_reported_simulation_time(monkeypatch):
    backend = PollingTimingBackend()

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_delay)
    result = asyncio.run(dispatch_timed_events(backend, "case", [{
        "time_s": 1.0,
        "component_id": "17",
        "parameter_name": "Value",
        "value": 1,
    }], mode="simulation_clock_polling"))

    assert backend.writes == [("case", 17, {"Value": 1})]
    assert result[0]["requested_time_s"] == 1.0
    assert result[0]["observed_time_s"] == 1.05
    assert result[0]["timing_error_s"] == pytest.approx(0.05)


def test_missing_strict_timing_capability_is_rejected():
    class Unsupported:
        async def get_timed_control_capabilities(self, project_name):
            return {"native_schedule": False, "simulation_clock": False}

    with pytest.raises(BackendError) as raised:
        asyncio.run(select_timing_mode(Unsupported(), "case"))
    assert raised.value.code == "HVDC_TIMED_CONTROL_UNAVAILABLE"
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_timing.py tests\test_tool_backend_matrix.py -q
```

Expected: import and contract failures because timed-control APIs are absent.

- [ ] **Step 3: Extend the backend and service contracts conservatively**

Add these exact asynchronous methods to `ProjectBackend`:
`get_timed_control_capabilities(project_name: str) -> JsonDict`,
`schedule_timed_controls(project_name: str, events:
Sequence[Mapping[str, Any]]) -> list[JsonDict]`, and
`get_simulation_time(project_name: str) -> float`.

Add matching proxies to `PscadService`. Both `LegacyBackend` and `ModernBackend` must return:

```python
{"native_schedule": False, "simulation_clock": False, "time_basis": "EMTDC"}
```

Their `schedule_timed_controls()` and `get_simulation_time()` implementations must raise `BackendError(code="CAPABILITY_UNAVAILABLE")` with project name and backend version evidence. Do not probe undocumented vendor attributes and do not infer simulation time from wall-clock progress.

- [ ] **Step 4: Implement the timing module**

Create `pscad_mcp/hvdc/timing.py`. `select_timing_mode()` must prefer native scheduling, then simulation clock, then raise `HVDC_TIMED_CONTROL_UNAVAILABLE`. `dispatch_timed_events()` must:

- call `schedule_timed_controls()` once in native mode and validate one acknowledgement per event;
- poll only `get_simulation_time()` in polling mode;
- require finite, monotonically non-decreasing reported times;
- write each event once when simulation time reaches its threshold;
- return requested time, observed time, error, and mode;
- use wall-clock only for a bounded liveness deadline passed separately by the caller.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass and the registered MCP tool count remains unchanged.

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/core/backend/base.py pscad_mcp/core/backend/legacy.py pscad_mcp/core/backend/modern.py pscad_mcp/core/service.py pscad_mcp/hvdc/timing.py tests/test_hvdc_timing.py tests/test_tool_backend_matrix.py
git commit -m "feat: add strict HVDC timing capabilities"
```

### Task 4: Add side-effect-free preflight and derived-project output readiness

**Files:**
- Create: `pscad_mcp/hvdc/preflight.py`
- Create: `tests/test_hvdc_preflight.py`
- Modify: `pscad_mcp/hvdc/scenarios.py:838-938`

- [ ] **Step 1: Write failing output-preflight tests**

Use a fake backend that records all operations:

```python
import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.preflight import ensure_output_ready


class OutputBackend:
    def __init__(self, plot_type):
        self.settings = {"PlotType": plot_type}
        self.calls = []

    async def get_project_settings(self, project_name):
        self.calls.append(("get", project_name))
        return dict(self.settings)

    async def set_project_settings(self, project_name, settings):
        self.calls.append(("set", project_name, dict(settings)))
        self.settings.update(settings)


def test_disabled_output_is_not_changed_on_source_project():
    backend = OutputBackend("NONE")
    with pytest.raises(BackendError) as raised:
        asyncio.run(ensure_output_ready(backend, "source", source_project="source", confirm=True))
    assert raised.value.code == "HVDC_CAPABILITY_UNAVAILABLE"
    assert backend.calls == [("get", "source")]


def test_confirmed_derived_project_enables_legacy_out_and_reads_back():
    backend = OutputBackend(0)
    result = asyncio.run(ensure_output_ready(backend, "derived", source_project="source", confirm=True))
    assert result == {"changed": True, "previous": 0, "current": "OUT"}
    assert backend.calls == [
        ("get", "derived"),
        ("set", "derived", {"PlotType": "OUT"}),
        ("get", "derived"),
    ]
```

Add cases for enabled aliases (`OUT`, `LEGACY`, `1`, `True`), disabled aliases (`NONE`, `NO`, `0`, `False`), unconfirmed correction, missing `PlotType`, and failed read-back.

- [ ] **Step 2: Run tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_preflight.py -q
```

Expected: import failure because `preflight.py` does not exist.

- [ ] **Step 3: Implement output readiness and required-selector checks**

Create `preflight.py` with the exact public functions
`ensure_output_ready(backend, target_project, *, source_project, confirm)`,
`required_result_selectors(profile, requested_metrics)`, and
`preflight_scenario(service, source_project, target_project, normalized, *,
confirm)`. Return JSON-safe dictionaries and lists using the field names
asserted by the tests in this task.

`preflight_scenario()` must resolve all requested commands from the target project's inspected evidence, choose strict timing only when events exist, validate that profile-v2 metrics point to defined result canonicals, and call `ensure_output_ready()`. It returns resolved commands, timing mode, output-change evidence, matched fingerprint, and required result selectors. It does not write component parameters or start a run.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Step 2 command. Expected: all preflight tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/preflight.py pscad_mcp/hvdc/scenarios.py tests/test_hvdc_preflight.py
git commit -m "feat: preflight HVDC output readiness"
```

### Task 5: Integrate explicit bindings, verified writes, rollback, and strict scheduling

**Files:**
- Modify: `pscad_mcp/hvdc/scenarios.py:136-231,580-938`
- Modify: `tests/test_hvdc_scenarios.py`
- Modify: `tests/test_hvdc_scenario_containment.py`

- [ ] **Step 1: Replace alias-authorization tests with explicit-binding tests**

Update the scenario fake profile to version 2 and add a confirmed `Value` binding. Add these behavioral tests:

```python
import json


def _strict_service(tmp_path, backend):
    source = tmp_path / "source.pscx"
    derived = tmp_path / "derived.pscx"
    xml = """<project name='case' version='4.6.2'>
      <definition name='Main'><canvas name='Main'>
        <component id='17' name='Trip command' definition='master:const'>
          <parameter name='Value' value='0'/>
        </component>
      </canvas></definition><definition name='loadbreaker_3'/>
    </project>"""
    source.write_text(xml, encoding="utf-8")
    derived.write_text(xml, encoding="utf-8")
    profile_directory = tmp_path / ".pscad-mcp" / "hvdc-profiles"
    profile_directory.mkdir(parents=True)
    (profile_directory / "strict_breaker.json").write_text(json.dumps({
        "profile_version": 2,
        "required_assets": [],
        "mappings": [],
        "project_fingerprints": [{"definitions": ["loadbreaker_3"]}],
        "command_bindings": [{
            "canonical": "breaker_command",
            "component": {"canvas": "Main", "definition": "master:const", "component_id": "17"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
            "read_back": True,
        }],
        "result_channels": [],
        "metric_roles": {},
        "sequences": [],
    }), encoding="utf-8")
    service = HvdcDomainService(
        backend,
        path_policy=PathPolicy(workspace_root=str(tmp_path)),
    )
    return service, source, derived


def _strict_event_scenario(derived):
    return {
        "name": "trip",
        "profile": "strict_breaker",
        "project": "source",
        "derived_project": str(derived),
        "parameter_changes": [],
        "events": [{"time_s": 1.0, "target": "breaker_command", "value": 1}],
        "analysis": {},
    }


def test_timed_scenario_without_strict_time_fails_before_write_or_run(tmp_path):
    backend = ScenarioBackend(projects=("derived",))
    backend.timing_capabilities = {"native_schedule": False, "simulation_clock": False}
    service, source, derived = _strict_service(tmp_path, backend)
    scenario = _strict_event_scenario(derived)

    with pytest.raises(BackendError) as raised:
        asyncio.run(service.run_scenario(str(source), scenario, confirm=True))

    assert raised.value.code == "HVDC_TIMED_CONTROL_UNAVAILABLE"
    assert backend.calls == []


def test_initial_write_is_read_back_and_restored_on_mismatch(tmp_path):
    backend = ScenarioBackend(projects=("derived",))
    backend.parameters = {17: {"Value": 0}}
    backend.forced_readback = {17: {"Value": 0}}
    service, source, derived = _strict_service(tmp_path, backend)
    scenario = _strict_event_scenario(derived)
    scenario["events"] = []
    scenario["parameter_changes"] = [{"target": "breaker_command", "value": 1}]

    async def exercise():
        started = await service.run_scenario(str(source), scenario, confirm=True)
        return await _wait_for_terminal(service, started["scenario_id"])

    terminal = asyncio.run(exercise())

    assert terminal["status"] == "failed"
    assert backend.parameters[17]["Value"] == 0
    assert terminal["partial_completion"]["applied_parameter_changes"] == []


def test_polling_event_records_requested_and_observed_simulation_time(tmp_path):
    backend = ScenarioBackend(projects=("derived",))
    backend.timing_capabilities = {"native_schedule": False, "simulation_clock": True}
    backend.simulation_times = [0.0, 0.5, 1.02]
    service, source, derived = _strict_service(tmp_path, backend)

    async def exercise():
        started = await service.run_scenario(
            str(source), _strict_event_scenario(derived), confirm=True
        )
        return await _wait_for_terminal(service, started["scenario_id"])

    terminal = asyncio.run(exercise())

    applied = terminal["partial_completion"]["applied_events"][0]
    assert applied["requested_time_s"] == 1.0
    assert applied["observed_time_s"] == pytest.approx(1.02)
    assert applied["timing_error_s"] == pytest.approx(0.02)
```

Change the previous wall-clock timed-event tests so they assert no code path treats `asyncio.get_running_loop().time()` as event time. Retain wall-clock timeout and containment tests.

- [ ] **Step 2: Run scenario tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_scenarios.py tests\test_hvdc_scenario_containment.py -q
```

Expected: failures because scenario startup still authorizes aliases, schedules from elapsed wall time, and does not read back or restore parameters.

- [ ] **Step 3: Reorder scenario startup around preflight**

In `run_scenario()`:

1. validate and require confirmation;
2. reserve the application scenario lease;
3. resolve the derived target before inspecting commands;
4. call `preflight_scenario()`;
5. create the record with a JSON-safe copy of preflight evidence;
6. start the worker.

Delete `_bind_approved_commands()`. Copy the resolved `component_id` and `parameter_name` into normalized parameter changes and events only from preflight results.

- [ ] **Step 4: Add verified writes and rollback**

Add asynchronous helpers named `_apply_verified_change(service, record,
target_project, change, operation)` and `_restore_parameter(service, record,
target_project, change, old_value, operation)`.

`_apply_verified_change()` must read the complete parameter mapping, require the named parameter, write one value, read it again when `read_back` is true, compare type-sensitively, and append to `applied_parameter_changes` only after success. On mismatch, restore the old value, verify restoration, and raise `HVDC_SCENARIO_EXECUTION_FAILED` with both requested and observed values.

- [ ] **Step 5: Replace wall-clock event scheduling**

For native mode, register all events before `run_project()` and record backend acknowledgements. For polling mode, start the run, wait for confirmed running status, then call `dispatch_timed_events()` while the run task is active. Remove `running_started`, elapsed-loop-time subtraction, and `asyncio.sleep(max(0.0, event_time - elapsed))` from `scenarios.py`.

Preserve the existing worker timeout, stop containment, vendor settlement tracking, output discovery, and lease release rules.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all scenario and containment tests pass.

- [ ] **Step 7: Commit**

```powershell
git add pscad_mcp/hvdc/scenarios.py tests/test_hvdc_scenarios.py tests/test_hvdc_scenario_containment.py
git commit -m "feat: enforce simulation-time HVDC events"
```

### Task 6: Retain legacy INF metadata and resolve explicit result selectors

**Files:**
- Modify: `pscad_mcp/core/pscad_adapter.py:235-355`
- Modify: `pscad_mcp/hvdc/results.py`
- Modify: `pscad_mcp/hvdc/service.py:505-550`
- Modify: `tests/test_psout_reader.py`
- Modify: `tests/test_hvdc_metrics.py`

- [ ] **Step 1: Write failing metadata and selector tests**

Extend the legacy fixture to include real metadata:

```python
basename.with_suffix(".inf").write_text(
    '\n'.join([
        'PGB(1) Output Desc="VDCRp1" Group="Main" Max=1.2 Min=-0.2 Units="pu"',
        'PGB(2) Output Desc="IMC" Group="loadbreaker_3" Max=2.0 Min=-2.0 Units="kA"',
        'PGB(3) Output Desc="UMC" Group="loadbreaker_3" Max=2.0 Min=-2.0 Units="kV"',
    ]),
    encoding="utf-8",
)
```

Assert returned channel records retain `description`, `group`, `units`, `max`, `min`, and `call_id`.

Add a result-resolution test:

```python
def test_profile_v2_resolves_exact_path_call_id_and_units():
    samples = {"channels": [
        {"path": "Main/VDCRp1", "call_id": 1, "units": "pu", "values": [1.0], "domain": [0.0]},
        {"path": "loadbreaker_3/UMC", "call_id": 90, "units": "kV", "values": [500.0], "domain": [0.0]},
    ]}
    profile = {"profile_version": 2, "result_channels": [
        {"canonical": "dc_voltage_breaker", "path": "loadbreaker_3/UMC", "call_id": 90, "units": "kV"},
        {"canonical": "dc_voltage_rectifier_pole1", "path": "Main/VDCRp1", "call_id": 1, "units": "pu"},
    ]}

    result = resolve_result_channels(samples, profile)

    assert [item["name"] for item in result["samples"]["channels"]] == [
        "dc_voltage_breaker",
        "dc_voltage_rectifier_pole1",
    ]
    assert result["samples"]["channels"][0]["units"] == "kV"
```

Add mismatch cases for path, call ID, and units; each mismatch must remain unresolved and produce a structured warning.

- [ ] **Step 2: Run tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_psout_reader.py tests\test_hvdc_metrics.py -q
```

Expected: metadata keys are absent and profile-v2 resolution still uses aliases.

- [ ] **Step 3: Parse complete INF metadata**

Replace the narrow metadata regex with parsing that captures quoted `Desc`, quoted `Group`, numeric `Max`, numeric `Min`, and quoted `Units`. Convert max/min to finite floats and reject malformed non-finite values. Include all metadata fields in each returned channel record in both summary and sample modes.

- [ ] **Step 4: Implement profile-version-aware result resolution**

In `results.py`, retain the current alias resolver for version 1 profiles. For version 2:

- index channels by exact normalized path;
- require exact `call_id` when the selector defines it;
- require exact case-insensitive units when the selector defines units;
- reject zero or multiple candidates;
- copy selector metadata such as location, polarity, transition, active level, and metric role into the normalized channel record;
- return structured warnings with canonical and candidate evidence.

Update `HvdcDomainService.analyze_results()` to pass the full profile into metrics and store the resolved metadata.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add pscad_mcp/core/pscad_adapter.py pscad_mcp/hvdc/results.py pscad_mcp/hvdc/service.py tests/test_psout_reader.py tests/test_hvdc_metrics.py
git commit -m "feat: resolve explicit HVDC result channels"
```

### Task 7: Make metrics unit-aware and profile-driven for binary edges and sequences

**Files:**
- Modify: `pscad_mcp/hvdc/metrics.py`
- Modify: `pscad_mcp/hvdc/service.py:505-550`
- Modify: `tests/test_hvdc_metrics.py`

- [ ] **Step 1: Write failing metric-semantics tests**

Add tests for falling edges, configured order, and unit refusal:

```python
def test_trip_delay_supports_profile_configured_falling_status_edge():
    samples = {"channels": [
        {"name": "breaker_command_observed", "units": "", "values": [0, 1, 1], "domain": [0.0, 1.0, 1.1]},
        {"name": "breaker_open", "units": "", "values": [1, 1, 0], "domain": [0.0, 1.0, 1.1]},
    ]}
    profile = {
        "metric_roles": {"breaker_command": "breaker_command_observed", "breaker_status": "breaker_open"},
        "result_channels": [
            {"canonical": "breaker_command_observed", "path": "x", "transition": "rising", "threshold": 0.5},
            {"canonical": "breaker_open", "path": "y", "transition": "falling", "threshold": 0.5},
        ],
        "sequences": [],
    }

    result = calculate_metrics(samples, ["trip_delay_s"], profile=profile)

    assert result["metrics"][0]["value"] == pytest.approx(0.1)


def test_dc_power_requires_confirmed_kv_and_ka_roles():
    samples = {"channels": [
        {"name": "v", "units": "pu", "values": [1.0], "domain": [0.0]},
        {"name": "i", "units": "kA", "values": [2.0], "domain": [0.0]},
    ]}
    profile = {"metric_roles": {"dc_voltage": "v", "dc_current": "i"}, "result_channels": [], "sequences": []}

    result = calculate_metrics(samples, ["dc_power"], profile=profile)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["metrics"][0]["status"] == "invalid"
```

Add a sequence test whose configured order is `protection_trip`, `breaker_command_observed`, `breaker_open`; assert the previous hard-coded command/status/protection order is not used.

- [ ] **Step 2: Run tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_metrics.py -q
```

Expected: `calculate_metrics()` does not accept `profile`, falling edges are unavailable, and per-unit power is incorrectly treated as MW.

- [ ] **Step 3: Implement metadata-aware normalization and transitions**

Change the signature to:

```python
def calculate_metrics(samples: dict[str, Any], metrics: list[str] | None = None, *, profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
```

Return channel metadata from `_normalize()`. Replace `_first_crossing()` with:

```python
def _transition_index(values: list[float], transition: str, threshold: float) -> int | None:
    for index in range(1, len(values)):
        previous, current = values[index - 1], values[index]
        if transition == "rising" and previous < threshold <= current:
            return index
        if transition == "falling" and previous >= threshold > current:
            return index
    return None
```

Resolve logical sources through `profile["metric_roles"]`. Calculate `dc_power` only for `kV` and `kA`; support explicit per-unit conversion only when both selectors provide finite `base_value` metadata. Resolve sequence order and per-channel transition settings from `profile["sequences"]` and `result_channels`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all metric tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/metrics.py pscad_mcp/hvdc/service.py tests/test_hvdc_metrics.py
git commit -m "feat: apply HVDC metric semantics"
```

### Task 8: Add reproducible scenario audit evidence

**Files:**
- Create: `pscad_mcp/hvdc/audit.py`
- Create: `tests/test_hvdc_audit.py`
- Modify: `pscad_mcp/hvdc/scenarios.py`
- Modify: `pscad_mcp/hvdc/service.py`

- [ ] **Step 1: Write failing audit tests**

```python
import hashlib

from pscad_mcp.hvdc.audit import file_evidence, profile_evidence


def test_file_evidence_is_streamed_and_json_safe(tmp_path):
    path = tmp_path / "result.out"
    path.write_bytes(b"abc")

    evidence = file_evidence(path)

    assert evidence["path"] == str(path.resolve())
    assert evidence["size"] == 3
    assert evidence["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert isinstance(evidence["modified_ns"], int)


def test_profile_hash_is_stable_across_mapping_order():
    left = {"profile_version": 2, "metric_roles": {"b": "2", "a": "1"}}
    right = {"metric_roles": {"a": "1", "b": "2"}, "profile_version": 2}
    assert profile_evidence("case", left)["sha256"] == profile_evidence("case", right)["sha256"]
```

Add a scenario test asserting source/derived evidence, profile hash, timing mode, output setting changes, resolved bindings, and output hashes appear in the status payload.

- [ ] **Step 2: Run tests and verify RED**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_audit.py tests\test_hvdc_scenarios.py -q
```

Expected: import failure and absent audit fields.

- [ ] **Step 3: Implement bounded deterministic evidence**

Create `audit.py` with 1 MiB streaming SHA-256 reads, canonical JSON profile hashing using `sort_keys=True` and compact separators, and helpers that omit unavailable optional fields instead of inventing values.

Integrate audit capture as follows:

- source and derived project evidence before the worker starts;
- profile evidence and matched fingerprint during preflight;
- backend/PSCAD/compiler versions when exposed by health or settings;
- output file evidence after path-policy validation and discovery;
- requested/observed event times from the scheduler;
- containment and pending-operation state from the existing scenario record.

Hash failures add a structured warning and make audit completeness false; they do not hide an otherwise valid simulation result.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add pscad_mcp/hvdc/audit.py pscad_mcp/hvdc/scenarios.py pscad_mcp/hvdc/service.py tests/test_hvdc_audit.py tests/test_hvdc_scenarios.py
git commit -m "feat: audit HVDC scenario evidence"
```

### Task 9: Add opt-in real PSCAD 4.6 Breaker acceptance and documentation

**Files:**
- Create: `tests/test_hvdc_real_acceptance.py`
- Modify: `README.md:75-122`
- Modify: `docs/zh-CN/README.md`

- [ ] **Step 1: Write the opt-in acceptance test**

Gate the test on all of these environment variables:

```text
PSCAD_MCP_ACCEPTANCE=1
PSCAD_MCP_HVDC_SOURCE=<absolute difforder_new.pscx>
PSCAD_MCP_HVDC_LIBRARY=<absolute BreakerArc.pslx>
PSCAD_MCP_WORKSPACE=<absolute acceptance workspace>
```

The test must:

1. skip when the gate is absent;
2. reject a workspace that equals or contains the source directory;
3. hash source and library files;
4. create a timestamped acceptance directory under `PSCAD_MCP_WORKSPACE`;
5. copy the case, library, and required `lib` directory without modifying the source;
6. connect through the legacy backend and load the derived project and library;
7. run a baseline after output preflight;
8. resolve the seven explicit result selectors;
9. attempt an external event only when a user-provided workspace profile contains a unique command binding and the backend reports strict timing capability;
10. otherwise assert `HVDC_TIMED_CONTROL_UNAVAILABLE` or `HVDC_MAPPING_MISSING` occurred before parameter mutation;
11. quit the owned PSCAD process in `finally`;
12. re-hash source files and assert equality.

Do not delete acceptance evidence automatically. Print its directory and process-cleanup status.

- [ ] **Step 2: Run the acceptance test without the gate**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_real_acceptance.py -q
```

Expected: one clean skip with the missing environment gate explained.

- [ ] **Step 3: Update English and Chinese documentation**

Document:

- `events[].time_s` always means EMTDC time;
- no wall-clock fallback exists;
- built-in Breaker profile result selectors and their units;
- built-in profile intentionally contains no writable breaker/fault binding;
- user profiles must provide confirmed command bindings;
- derived-only `PlotType="OUT"` correction behavior;
- safe rejection is the expected result when real timing or binding capability is unavailable;
- the exact opt-in acceptance command and environment variables.

- [ ] **Step 4: Run documentation and tool-inventory regressions**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_real_acceptance.py tests\test_hvdc_tools.py tests\test_tool_inventory.py -q
```

Expected: tests pass with the real acceptance skipped unless explicitly enabled; the tool inventory remains 70 total tools with 10 HVDC tools.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_hvdc_real_acceptance.py README.md docs/zh-CN/README.md
git commit -m "test: accept strict HVDC workflows"
```

### Task 10: Run complete verification and real acceptance when available

**Files:**
- Verify: all changed files
- Update only if verification finds a defect: the owning production file and its regression test

- [ ] **Step 1: Run every HVDC and output-reader test**

```powershell
$tests = Get-ChildItem tests -Filter 'test_hvdc*.py' | ForEach-Object { $_.FullName }
& .\.venv\Scripts\python.exe -m pytest @tests tests\test_psout_reader.py -q
```

Expected: all tests pass; only explicitly gated real acceptance may skip.

- [ ] **Step 2: Run the full repository test suite**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures. Record the exact passed, skipped, and subtest counts from fresh output.

- [ ] **Step 3: Run compile, whitespace, and package verification**

```powershell
& .\.venv\Scripts\python.exe -m compileall -q pscad_mcp tests
git diff --check
powershell -ExecutionPolicy Bypass -File scripts\verify_package.ps1
```

Expected: all commands exit zero; the isolated install reports version `0.2.0` and the unchanged 70-tool inventory.

- [ ] **Step 4: Run licensed PSCAD 4.6 acceptance when configured**

```powershell
$env:PSCAD_MCP_ACCEPTANCE='1'
& .\.venv\Scripts\python.exe -m pytest tests\test_hvdc_real_acceptance.py -q -s
```

Run this only when the four documented environment variables point to valid, user-approved locations. Expected outcomes are either:

- baseline plus a strict-time external event completes with requested/observed EMTDC timestamps; or
- baseline completes and external mutation is safely rejected before writing because a binding or strict timing capability is unavailable.

Neither outcome permits source hash changes or leftover owned PSCAD/simulation processes.

- [ ] **Step 5: Review requirements and repository state**

```powershell
git status --short
git log --oneline --decorate -12
git diff main HEAD --stat
git diff main HEAD --check
```

Check every completion criterion in `docs/superpowers/specs/2026-08-17-hvdc-simulation-time-and-bindings-design.md` against code, tests, and acceptance evidence. Do not mark external injection accepted when the result is a safety rejection.

- [ ] **Step 6: Request code review before integration**

Use `superpowers:requesting-code-review` on the complete branch. Address only verified findings, re-run the relevant focused test after each correction, then repeat Steps 1-5 before claiming completion.
