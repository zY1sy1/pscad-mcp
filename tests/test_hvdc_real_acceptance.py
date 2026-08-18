"""Opt-in licensed PSCAD 4.6 acceptance for the Breaker profile."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil

import pytest

from pscad_mcp.core.backend.base import BackendError


_REQUIRED_ENV = (
    "PSCAD_MCP_HVDC_SOURCE",
    "PSCAD_MCP_HVDC_LIBRARY",
    "PSCAD_MCP_WORKSPACE",
)


def _sha256_tree(path: Path) -> dict[str, str]:
    files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
    evidence: dict[str, str] = {}
    base = path.parent if path.is_file() else path
    for item in files:
        digest = hashlib.sha256()
        with item.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        evidence[str(item.relative_to(base))] = digest.hexdigest()
    return evidence


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _workspace_profile(workspace: Path) -> tuple[str, dict] | None:
    profile_dir = workspace / ".pscad-mcp" / "hvdc-profiles"
    if not profile_dir.is_dir():
        return None
    candidates: list[tuple[str, dict]] = []
    for path in sorted(profile_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        bindings = payload.get("command_bindings") if isinstance(payload, dict) else None
        if payload.get("profile_version") == 2 and isinstance(bindings, list) and len(bindings) == 1:
            candidates.append((path.stem, payload))
    return candidates[0] if len(candidates) == 1 else None


async def _wait_for_terminal(service, scenario_id: str):
    for _ in range(600):
        terminal = await service.scenario_status(scenario_id)
        if terminal["status"] in {"completed", "failed", "timed_out"}:
            return terminal
        await asyncio.sleep(0.05)
    raise AssertionError("scenario did not reach a terminal state")


async def _run_external_event(service, source_project: str, scenario: dict, capabilities: dict) -> dict:
    strict = capabilities.get("native_schedule") is True or capabilities.get("simulation_clock") is True
    if not strict:
        try:
            await service.run_scenario(source_project, scenario, confirm=True)
        except BackendError as error:
            if error.code not in {"HVDC_TIMED_CONTROL_UNAVAILABLE", "HVDC_MAPPING_MISSING"}:
                raise
            return {"outcome": "safe_rejection", "code": error.code}
        raise AssertionError("external event was accepted without strict timing or an explicit binding")

    started = await service.run_scenario(source_project, scenario, confirm=True)
    terminal = await _wait_for_terminal(service, started["scenario_id"])
    assert terminal["status"] == "completed", terminal
    applied_events = terminal.get("partial_completion", {}).get("applied_events", [])
    assert any(float(item.get("requested_time_s")) == float(scenario["events"][0]["time_s"]) for item in applied_events)
    return {"outcome": "completed", "scenario": terminal}


def test_external_acceptance_helper_requires_safe_rejection_without_capability():
    class Service:
        async def run_scenario(self, project_name, scenario, confirm=False):
            raise BackendError("HVDC_TIMED_CONTROL_UNAVAILABLE", "unsupported", "test", "run")

    result = asyncio.run(_run_external_event(Service(), "source", {"events": [{"time_s": 1.0}]}, {}))
    assert result == {"outcome": "safe_rejection", "code": "HVDC_TIMED_CONTROL_UNAVAILABLE"}


def test_external_acceptance_helper_waits_for_completed_event():
    class Service:
        async def run_scenario(self, project_name, scenario, confirm=False):
            return {"scenario_id": "hvdc-1"}

        async def scenario_status(self, scenario_id):
            return {
                "status": "completed",
                "partial_completion": {"applied_events": [{"requested_time_s": 1.0}]},
            }

    result = asyncio.run(_run_external_event(Service(), "source", {"events": [{"time_s": 1.0}]}, {"simulation_clock": True}))
    assert result["outcome"] == "completed"


@pytest.mark.skipif(
    os.getenv("PSCAD_MCP_ACCEPTANCE") != "1"
    or not all(os.getenv(name) for name in _REQUIRED_ENV),
    reason="Set PSCAD_MCP_ACCEPTANCE=1 and the three HVDC acceptance paths to enable licensed PSCAD acceptance.",
)
def test_real_hvdc_acceptance_preserves_sources_and_fails_closed_without_capability():
    source = Path(os.environ["PSCAD_MCP_HVDC_SOURCE"]).expanduser().resolve()
    library = Path(os.environ["PSCAD_MCP_HVDC_LIBRARY"]).expanduser().resolve()
    workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"]).expanduser().resolve()
    assert source.is_file(), source
    assert library.is_file(), library
    assert workspace.is_dir(), workspace

    source_root = source.parent
    library_root = library.parent
    assert not (_within(workspace, source_root) or _within(source_root, workspace)), "acceptance workspace must be disjoint from the source directory"
    assert not (_within(workspace, library_root) or _within(library_root, workspace)), "acceptance workspace must be disjoint from the library directory"

    source_hash = _sha256_tree(source)
    library_hash = _sha256_tree(library)
    source_lib = source_root / "lib"
    assert source_lib.is_dir(), f"required source lib directory is missing: {source_lib}"
    lib_hash = _sha256_tree(source_lib)
    user_profile = _workspace_profile(workspace)

    acceptance = workspace / f"hvdc-acceptance-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    acceptance.mkdir(parents=True)
    copied_source = acceptance / source.name
    copied_library = acceptance / library.name
    copied_lib = acceptance / "lib"
    shutil.copy2(source, copied_source)
    shutil.copy2(library, copied_library)
    shutil.copytree(source_lib, copied_lib)
    if user_profile is not None:
        profile_name, _ = user_profile
        profile_source = workspace / ".pscad-mcp" / "hvdc-profiles" / f"{profile_name}.json"
        profile_destination = acceptance / ".pscad-mcp" / "hvdc-profiles"
        profile_destination.mkdir(parents=True)
        shutil.copy2(profile_source, profile_destination / profile_source.name)
    derived = acceptance / f"{source.stem}_derived.pscx"
    shutil.copy2(copied_source, derived)
    print(f"HVDC_ACCEPTANCE_DIRECTORY={acceptance}")

    backend = None
    owned_process = False
    failure: BaseException | None = None
    try:
        from pscad_mcp.core.backend.legacy import LegacyBackend
        from pscad_mcp.core.executor import robust_executor
        from pscad_mcp.core.path_policy import PathPolicy
        from pscad_mcp.hvdc.preflight import ensure_output_ready
        from pscad_mcp.hvdc.service import HvdcDomainService

        backend = LegacyBackend(robust_executor, version="4.6.2", x64=True)
        asyncio.run(backend.attach())
        owned_process = bool(getattr(backend, "owns_process", False))
        asyncio.run(backend.load_projects([str(copied_source), str(derived), str(copied_library)]))
        service = HvdcDomainService(backend, path_policy=PathPolicy(workspace_root=str(acceptance)))
        asyncio.run(ensure_output_ready(backend, str(derived), source_project=str(copied_source), confirm=True))

        baseline = {
            "name": "baseline",
            "profile": "hvdc_breaker_difforder",
            "project": str(derived),
            "parameter_changes": [],
            "events": [],
            "analysis": {},
        }
        started = asyncio.run(service.run_scenario(str(derived), baseline, confirm=True))

        terminal = asyncio.run(_wait_for_terminal(service, started["scenario_id"]))
        assert terminal["status"] == "completed", terminal

        from pscad_mcp.hvdc.profiles import load_profile
        from pscad_mcp.hvdc.results import resolve_result_channels

        profile = load_profile("hvdc_breaker_difforder")
        samples = asyncio.run(backend.read_output_file(str(derived), max_samples=10000, summary_only=False))
        resolved = resolve_result_channels(samples, profile)
        expected_selectors = {
            "dc_voltage_breaker", "dc_current_breaker", "breaker_command_observed",
            "dc_voltage_rectifier_pole1", "dc_voltage_inverter_pole1",
            "dc_voltage_rectifier_pole2", "dc_voltage_inverter_pole2",
        }
        assert {item["canonical"] for item in profile["result_channels"]} == expected_selectors
        assert {item["canonical"] for item in resolved["resolved_channels"]} == expected_selectors
        assert not [warning for warning in resolved["warnings"] if warning.get("code") == "HVDC_RESULT_SELECTOR_UNRESOLVED"]

        candidate = _workspace_profile(acceptance)
        if candidate is not None:
            profile_name, profile_payload = candidate
            capabilities = asyncio.run(backend.get_timed_control_capabilities(str(derived)))
            event = {
                "name": "external-trip",
                "profile": profile_name,
                "project": str(copied_source),
                "derived_project": str(derived),
                "parameter_changes": [],
                "events": [{"time_s": 1.0, "target": profile_payload["command_bindings"][0]["canonical"], "value": profile_payload["command_bindings"][0]["allowed_values"][-1]}],
            }
            result = asyncio.run(_run_external_event(service, str(copied_source), event, capabilities))
            if result["outcome"] == "safe_rejection":
                print(f"HVDC_ACCEPTANCE_SAFE_REJECTION={result['code']}")
            else:
                event_record = result["scenario"]["partial_completion"]["applied_events"][-1]
                print(
                    "HVDC_ACCEPTANCE_EVENT="
                    f"requested={event_record['requested_time_s']};"
                    f"observed={event_record.get('observed_time_s')};"
                    f"error={event_record.get('timing_error_s')}"
                )
        else:
            print("HVDC_ACCEPTANCE_SAFE_REJECTION=HVDC_MAPPING_MISSING")
    except BaseException as error:
        failure = error
    finally:
        if backend is not None:
            try:
                if owned_process:
                    asyncio.run(backend.quit())
                else:
                    asyncio.run(backend.disconnect())
            finally:
                print(f"HVDC_ACCEPTANCE_OWNED_PROCESS_CLEANED={not bool(getattr(backend, 'owns_process', False))}")

    assert _sha256_tree(source) == source_hash
    assert _sha256_tree(library) == library_hash
    assert _sha256_tree(source_lib) == lib_hash
    if failure is not None:
        raise failure
