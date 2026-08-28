"""Opt-in licensed PSCAD 4.6.2 acceptance for parametric MMC models."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.mmc.derivation import derive_mmc_parameters
from pscad_mcp.hvdc.builders.mmc.line_constants import (
    generate_public_line_constants,
    rebind_template_line_constants,
)
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from pscad_mcp.hvdc.builders.mmc.parametric_planner import STANDARD_SCENARIOS


_ENABLED = os.getenv("PSCAD_MCP_MMC_ACCEPTANCE") == "1"
_REQUIRED_ENV = (
    "PSCAD_MCP_BACKEND",
    "PSCAD_MCP_VERSION",
    "PSCAD_MCP_WORKSPACE",
    "PSCAD_MCP_MMC_TEMPLATE",
    "PSCAD_MCP_MMC_LIBRARY",
)
_TERMINAL_BUILD_STATES = {"published", "failed", "interrupted"}
_TERMINAL_SCENARIO_STATES = {"completed", "failed", "timed_out"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot(root: Path, *, excluded: Path | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if excluded is not None and (path == excluded or excluded in path.parents):
            continue
        result[path.relative_to(root).as_posix()] = _sha256(path)
    return result


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _config() -> dict[str, Any]:
    missing = [name for name in _REQUIRED_ENV if not os.getenv(name)]
    if missing:
        raise ValueError(f"MMC acceptance is missing environment variables: {missing}")
    if os.environ["PSCAD_MCP_BACKEND"] != "legacy":
        raise ValueError("MMC acceptance requires PSCAD_MCP_BACKEND=legacy")
    if os.environ["PSCAD_MCP_VERSION"] != "4.6.2":
        raise ValueError("MMC acceptance requires PSCAD_MCP_VERSION=4.6.2")
    workspace = Path(os.environ["PSCAD_MCP_WORKSPACE"]).expanduser().resolve()
    template = Path(os.environ["PSCAD_MCP_MMC_TEMPLATE"]).expanduser().resolve()
    library = Path(os.environ["PSCAD_MCP_MMC_LIBRARY"]).expanduser().resolve()
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("PSCAD_MCP_WORKSPACE must be an existing absolute directory")
    if not template.is_file() or template.name.casefold() != "h_mmc_mono_dc.pscx":
        raise ValueError("PSCAD_MCP_MMC_TEMPLATE must name H_MMC_Mono_DC.pscx")
    if not library.is_file() or library.name.casefold() != "intermediate.pslx":
        raise ValueError("PSCAD_MCP_MMC_LIBRARY must name intermediate.pslx")
    for source in (template, library):
        if _within(workspace, source.parent) or _within(source.parent, workspace):
            raise ValueError("The MMC acceptance workspace must be disjoint from official sources")
    return {
        "backend": "legacy",
        "version": "4.6.2",
        "workspace": workspace,
        "template": template,
        "library": library,
    }


def _request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "model_fidelity": "both",
        "topology": "two_terminal_symmetrical_monopole",
        "converter": "half_bridge",
        "dc_voltage_kv": 640.0,
        "active_power_mw": 1000.0,
        "reactive_power_mvar": 0.0,
        "frequency_hz": 60.0,
        "station_p": {
            "ac_voltage_kv": 230.0,
            "short_circuit_ratio": 5.0,
            "x_over_r": 10.0,
        },
        "station_vdc": {
            "ac_voltage_kv": 230.0,
            "short_circuit_ratio": 5.0,
            "x_over_r": 10.0,
        },
        "dc_link": {"kind": "overhead_line", "length_km": 200.0},
        "power_reversal_time_s": 0.5,
        "engineering_overrides": {},
    }
    payload.update(overrides)
    return payload


def _feasible_requests() -> tuple[dict[str, Any], ...]:
    return (
        _request(),
        _request(
            dc_voltage_kv=500.0,
            active_power_mw=750.0,
            reactive_power_mvar=100.0,
            station_p={"ac_voltage_kv": 180.0, "short_circuit_ratio": 4.0, "x_over_r": 8.0},
            station_vdc={"ac_voltage_kv": 180.0, "short_circuit_ratio": 4.0, "x_over_r": 8.0},
            dc_link={"kind": "cable", "length_km": 100.0},
        ),
        _request(
            dc_voltage_kv=800.0,
            active_power_mw=1200.0,
            reactive_power_mvar=-120.0,
            frequency_hz=50.0,
            station_p={"ac_voltage_kv": 287.0, "short_circuit_ratio": 6.0, "x_over_r": 12.0},
            station_vdc={"ac_voltage_kv": 287.0, "short_circuit_ratio": 6.0, "x_over_r": 12.0},
            dc_link={"kind": "overhead_line", "length_km": 300.0},
            power_reversal_time_s=0.8,
        ),
    )


def _infeasible_requests() -> tuple[tuple[str, dict[str, Any]], ...]:
    weak_grid = {"ac_voltage_kv": 230.0, "short_circuit_ratio": 1.5, "x_over_r": 10.0}
    return (
        ("modulation_margin", _request(dc_voltage_kv=200.0)),
        ("dc_current", _request(active_power_mw=4000.0)),
        ("line_drop", _request(dc_link={"kind": "overhead_line", "length_km": 20_000.0})),
        ("grid_strength", _request(station_p=weak_grid)),
        ("control_bandwidth", _request(power_reversal_time_s=0.01)),
        ("resource_limit", _request(dc_voltage_kv=3000.0, station_p={"ac_voltage_kv": 400.0, "short_circuit_ratio": 5.0, "x_over_r": 10.0}, station_vdc={"ac_voltage_kv": 400.0, "short_circuit_ratio": 5.0, "x_over_r": 10.0})),
    )


def _error_payload(error: BaseException) -> dict[str, Any]:
    if isinstance(error, BackendError):
        return error.to_dict()
    return {
        "code": "MMC_ACCEPTANCE_EXCEPTION",
        "message": str(error),
        "exception": type(error).__name__,
    }


async def _wait_for_build(builder: Any, build_id: str) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + 1800.0
    while True:
        status = builder.get_status(build_id)
        if status.get("state") in _TERMINAL_BUILD_STATES:
            return status
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"MMC build {build_id} timed out")
        await asyncio.sleep(0.5)


async def _wait_for_scenario(domain: Any, scenario_id: str) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + 1800.0
    while True:
        status = await domain.scenario_status(scenario_id)
        if status.get("status") in _TERMINAL_SCENARIO_STATES:
            return status
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"MMC scenario {scenario_id} timed out")
        await asyncio.sleep(0.5)


def _output_hashes(record: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in record.get("output_files", ()):
        path = Path(str(raw)).expanduser().resolve()
        if path.is_file() and not path.is_symlink():
            result[str(path)] = _sha256(path)
    return result


async def _run_standard_scenarios(
    service: Any,
    builder: Any,
    request: dict[str, Any],
    case_root: Path,
    build: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from pscad_mcp.core.path_policy import PathPolicy
    from pscad_mcp.hvdc.service import HvdcDomainService

    domain = HvdcDomainService(
        service,
        path_policy=PathPolicy(workspace_root=str(case_root)),
    )
    engine_paths = {
        str(item["engine"]): Path(str(item["final_path"])).resolve()
        for item in build["engines"]
    }
    results: list[dict[str, Any]] = []
    for engine in ("detailed_pwm", "average_value"):
        final_project = engine_paths[engine]
        source_copy = case_root / f"{final_project.stem}_scenario_source.pscx"
        if not source_copy.is_file():
            raise AssertionError(f"The {engine} scenario source was not published")
        source_hash = _sha256(source_copy)
        selected = builder.recommend_simulation(str(final_project))["recommendations"]
        if {item["name"] for item in selected} != set(STANDARD_SCENARIOS):
            raise AssertionError(f"The {engine} recommendation set is incomplete")
        for recommendation in selected:
            scenario = dict(recommendation["scenario"])
            if Path(str(scenario["project"])).resolve() != source_copy:
                raise AssertionError("The MMC recommendation source binding is not executable")
            if Path(str(scenario["derived_project"])).resolve() != final_project:
                raise AssertionError("The MMC recommendation derived binding is not executable")
            started = await domain.run_scenario(
                str(scenario["project"]), scenario, confirm=True
            )
            terminal = await _wait_for_scenario(domain, str(started["scenario_id"]))
            analysis = (
                await domain.analyze_results(str(started["scenario_id"]))
                if terminal.get("status") == "completed"
                else {}
            )
            results.append(
                {
                    "engine": engine,
                    "name": recommendation["name"],
                    "status": terminal.get("status"),
                    "capabilities": recommendation["capabilities"],
                    "output_hashes": _output_hashes(terminal),
                    "analysis": analysis,
                    "error": terminal.get("error"),
                }
            )
        if _sha256(source_copy) != source_hash:
            raise AssertionError(f"Scenario execution mutated its {engine} source copy")
    return results


async def _run_case(
    config: Mapping[str, Any],
    acceptance_root: Path,
    index: int,
    request: dict[str, Any],
) -> dict[str, Any]:
    from pscad_mcp.core.backend.legacy import LegacyBackend
    from pscad_mcp.core.executor import robust_executor
    from pscad_mcp.core.path_policy import PathPolicy
    from pscad_mcp.core.service import PscadService
    from pscad_mcp.hvdc.builders.mmc.parametric_service import ParametricMmcBuilderService

    case_root = acceptance_root / f"feasible-{index + 1}"
    case_root.mkdir()
    line_root = case_root / "public-line-constants"
    artifacts = generate_public_line_constants(config["template"], line_root)
    source_root = case_root / "pwm-sources"
    source_root.mkdir()
    staged_library = source_root / "intermediate.pslx"
    shutil.copy2(config["library"], staged_library)
    staged_template = rebind_template_line_constants(
        config["template"], artifacts, source_root / "H_MMC_Mono_DC.pscx"
    )
    service = PscadService(
        lambda: LegacyBackend(robust_executor, version="4.6.2", x64=True),
        path_policy=PathPolicy(workspace_root=str(case_root)),
    )
    builder = ParametricMmcBuilderService(service, workspace_root=case_root)
    record: dict[str, Any] = {
        "request": request,
        "plan_hash": None,
        "child_hashes": {},
        "source_hashes": {},
        "asset_hashes": {},
        "line_constants": [item.to_dict() for item in artifacts],
        "build": {},
        "project_hashes": {},
        "library_hashes": {},
        "output_hashes": {},
        "scenarios": [],
        "runtime": {},
        "compiler": {},
        "owned_process_cleaned": False,
        "status": "INCOMPLETE_ANALYSIS",
        "error": None,
    }
    try:
        await service.attach_local()
        record["runtime"] = await service.status()
        plan = builder.plan_model(
            request,
            project_name="MMC_CASE",
            folder=str(case_root),
            template_path=str(staged_template),
            library_path=str(staged_library),
        )
        record["plan_hash"] = plan["plan_hash"]
        record["child_hashes"] = {
            item["engine"]: item["plan_hash"] for item in plan["engine_plans"]
        }
        record["source_hashes"] = {
            item["engine"]: item["source_hashes"] for item in plan["engine_plans"]
        }
        record["asset_hashes"] = {
            item["engine"]: item["asset_hashes"] for item in plan["engine_plans"]
        }
        started = await builder.build_model(
            request,
            plan["plan_hash"],
            "MMC_CASE",
            str(case_root),
            template_path=str(staged_template),
            library_path=str(staged_library),
            confirm=True,
        )
        build = await _wait_for_build(builder, str(started["build_id"]))
        record["build"] = build
        if build.get("state") != "published":
            record["error"] = build.get("error")
            return record
        for engine in build["engines"]:
            project = Path(str(engine["final_path"])).resolve()
            engine_name = str(engine["engine"])
            record["project_hashes"][engine_name] = _sha256(project)
            if engine_name == "detailed_pwm":
                final_library = Path(str(engine["final_library_path"])).resolve()
                final_library_hash = _sha256(final_library)
                planned_library_hash = record["source_hashes"][engine_name]["library"]
                if final_library_hash != planned_library_hash:
                    raise AssertionError(
                        "The published PWM library differs from the immutable plan"
                    )
                record["library_hashes"][engine_name] = final_library_hash
            settings = await service.get_project_settings(project.stem)
            record["compiler"][engine_name] = {
                key: value
                for key, value in settings.items()
                if "compiler" in str(key).casefold()
            }
        scenarios = await _run_standard_scenarios(
            service, builder, request, case_root, build
        )
        record["scenarios"] = scenarios
        record["output_hashes"] = {
            f"{item['engine']}:{item['name']}": item["output_hashes"]
            for item in scenarios
        }
        record["status"] = (
            "PASS"
            if all(
                item["status"] == "completed"
                and item["output_hashes"]
                and item["analysis"].get("verdict") == "PASS"
                and item["capabilities"].get("intrinsic_dc_fault_blocking") is False
                for item in scenarios
            )
            else "INCOMPLETE_ANALYSIS"
        )
        return record
    except BaseException as error:
        record["error"] = _error_payload(error)
        return record
    finally:
        try:
            await service.quit_pscad(confirm=True)
            record["owned_process_cleaned"] = True
        except BaseException as cleanup_error:
            record["status"] = "INCOMPLETE_ANALYSIS"
            record["cleanup_error"] = _error_payload(cleanup_error)
            try:
                await service.disconnect()
            except BaseException:
                pass


async def _run_cases(
    config: Mapping[str, Any], acceptance_root: Path
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for index, request in enumerate(_feasible_requests()):
        results.append(await _run_case(config, acceptance_root, index, request))
    return results


def _commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[1],
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


@pytest.mark.skipif(
    not _ENABLED,
    reason="Set PSCAD_MCP_MMC_ACCEPTANCE=1 to run licensed PSCAD 4.6.2 MMC acceptance.",
)
def test_real_parametric_mmc_matrix() -> None:
    config = _config()
    workspace = config["workspace"]
    assert isinstance(workspace, Path)
    before_workspace = _snapshot(workspace)
    source_before = {
        "template": _sha256(config["template"]),
        "library": _sha256(config["library"]),
    }
    asset_before = dict(load_packaged_asset_set().hashes)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    acceptance_root = workspace / f"mmc-parametric-acceptance-{stamp}"
    acceptance_root.mkdir(exist_ok=False)
    infeasible: list[dict[str, Any]] = []
    for expected_constraint, request in _infeasible_requests():
        design = derive_mmc_parameters(parse_parametric_request(request))
        failed = [item.name for item in design.constraints if not item.passed]
        infeasible.append(
            {
                "expected_constraint": expected_constraint,
                "failed_constraints": failed,
                "rejected": not design.feasible and expected_constraint in failed,
            }
        )
    cases = asyncio.run(_run_cases(config, acceptance_root))
    source_after = {
        "template": _sha256(config["template"]),
        "library": _sha256(config["library"]),
    }
    asset_after = dict(load_packaged_asset_set().hashes)
    after_workspace = _snapshot(workspace, excluded=acceptance_root)
    preexisting_immutable = all(
        after_workspace.get(path) == digest for path, digest in before_workspace.items()
    )
    report = {
        "schema_version": 1,
        "status": (
            "PASS"
            if all(case["status"] == "PASS" for case in cases)
            and all(item["rejected"] for item in infeasible)
            and source_before == source_after
            and asset_before == asset_after
            and preexisting_immutable
            else "INCOMPLETE_ANALYSIS"
        ),
        "commit": _commit(),
        "config": {
            "backend": config["backend"],
            "version": config["version"],
            "workspace": str(workspace),
            "template": str(config["template"]),
            "library": str(config["library"]),
        },
        "source_hashes_before": source_before,
        "source_hashes_after": source_after,
        "asset_hashes_before": asset_before,
        "asset_hashes_after": asset_after,
        "preexisting_workspace_before": before_workspace,
        "preexisting_workspace_after": after_workspace,
        "preexisting_workspace_immutable": preexisting_immutable,
        "feasible_cases": cases,
        "infeasible_cases": infeasible,
        "capability_levels": {
            f"case-{index + 1}": {
                item.get("engine"): item.get("capability_level")
                for item in case.get("build", {}).get("engines", [])
            }
            for index, case in enumerate(cases)
        },
    }
    report_path = acceptance_root / "mmc-parametric-acceptance-report.json"
    report_path.write_text(
        json.dumps(report, allow_nan=False, ensure_ascii=True, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(f"MMC_ACCEPTANCE_REPORT={report_path}")
    assert source_before == source_after
    assert asset_before == asset_after
    assert preexisting_immutable
    assert report["status"] == "PASS", report
