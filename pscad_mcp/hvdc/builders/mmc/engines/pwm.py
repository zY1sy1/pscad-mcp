"""Read-only-source staging engine for audited detailed PWM templates."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .....core.backend.base import BackendError
from ....scanner import scan_project
from ..parametric_models import MmcCandidate, MmcEnginePlan


_SOURCE_NAMES = ("project", "library")
_PARAMETER_BINDINGS = {
    "rated_dc_voltage_kv": "requested_dc_voltage_kv",
    "active_power_mw": "requested_active_power_mw",
}
_TERMINAL_SCENARIO_STATES = {"completed", "failed", "timed_out"}


def _error(code: str, message: str, **details: object) -> BackendError:
    return BackendError(code, message, "hvdc", "execute_pwm_candidate", details)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_scenario_source(
    source_project: Path,
    expected_sha256: str,
    scenario_name: str,
) -> None:
    try:
        observed = _sha256(source_project)
    except OSError:
        observed = None
    if not isinstance(observed, str) or not hmac.compare_digest(
        observed, expected_sha256
    ):
        raise _error(
            "MMC_POSTCONDITION_FAILED",
            "PWM scenario execution changed its read-only source project.",
            scenario=scenario_name,
            source_project=str(source_project),
            expected_sha256=expected_sha256,
            observed_sha256=observed,
        )


def _require_method(service: object, name: str):
    method = getattr(service, name, None)
    if not callable(method):
        raise _error(
            "MMC_ENGINE_SERVICE_INVALID",
            f"The PWM engine requires PscadService.{name}().",
            method=name,
        )
    return method


def _require_scenario_method(service: object, name: str):
    method = getattr(service, name, None)
    if not callable(method):
        raise _error(
            "MMC_ENGINE_SERVICE_INVALID",
            f"The PWM engine requires HvdcDomainService.{name}().",
            method=name,
        )
    return method


def _source_files(plan: MmcEnginePlan) -> dict[str, Path]:
    if plan.engine != "detailed_pwm":
        raise _error("MMC_PLAN_INVALID", "The PWM engine requires a detailed_pwm child plan.")
    if set(plan.source_paths) != set(_SOURCE_NAMES) or set(plan.source_hashes) != set(_SOURCE_NAMES):
        raise _error(
            "MMC_PLAN_INVALID",
            "The PWM plan must bind exactly one project and one sibling library.",
        )
    result = {
        name: Path(plan.source_paths[name]).expanduser().resolve()
        for name in _SOURCE_NAMES
    }
    if result["project"].suffix.casefold() != ".pscx" or result["library"].suffix.casefold() != ".pslx":
        raise _error("MMC_PLAN_INVALID", "The PWM source pair must be PSCX and PSLX files.")
    return result


def _verify_sources(plan: MmcEnginePlan, sources: Mapping[str, Path]) -> None:
    for name, source in sources.items():
        if not source.is_file() or source.is_symlink():
            raise _error(
                "MMC_TEMPLATE_SOURCE_CHANGED",
                "An audited PWM source is missing or is no longer a regular file.",
                source=name,
                path=str(source),
            )
        observed = _sha256(source)
        expected = plan.source_hashes[name]
        if not hmac.compare_digest(observed, expected):
            raise _error(
                "MMC_TEMPLATE_SOURCE_CHANGED",
                "An audited PWM source changed after planning.",
                source=name,
                path=str(source),
                expected_sha256=expected,
                observed_sha256=observed,
            )


def _preflight_dependencies(plan: MmcEnginePlan) -> None:
    blocking = [
        dict(item)
        for item in plan.dependencies
        if item.get("repair_policy") == "requires_verified_rebind"
    ]
    if blocking:
        raise _error(
            "MMC_ABSOLUTE_PATH_UNRESOLVED",
            "The PWM plan contains a line dependency without a verified rebind.",
            dependencies=blocking,
        )
    for dependency in plan.dependencies:
        if dependency.get("repair_policy") != "verified_rebind":
            continue
        resolved_value = dependency.get("resolved_value")
        expected_hash = dependency.get("expected_sha256")
        resolved = Path(str(resolved_value)).expanduser().resolve() if resolved_value else None
        if (
            resolved is None
            or not resolved.is_file()
            or not isinstance(expected_hash, str)
            or not hmac.compare_digest(_sha256(resolved), expected_hash)
        ):
            raise _error(
                "MMC_ABSOLUTE_PATH_UNRESOLVED",
                "A declared PWM dependency rebind lacks matching file identity.",
                dependency=dict(dependency),
            )


def _candidate(plan: MmcEnginePlan, candidate_id: str | None) -> MmcCandidate:
    if not plan.candidates:
        raise _error("MMC_PLAN_INVALID", "The PWM child plan has no candidates.")
    if candidate_id is None:
        return plan.candidates[0]
    for item in plan.candidates:
        if item.candidate_id == candidate_id:
            return item
    raise _error(
        "MMC_PLAN_INVALID",
        "The requested PWM candidate is not in the immutable child plan.",
        candidate_id=candidate_id,
    )


def _staging_paths(plan: MmcEnginePlan, candidate: MmcCandidate) -> tuple[Path, Path, Path]:
    workspace = Path(plan.workspace).expanduser().resolve()
    stage = (workspace / ".mmc-candidates" / plan.plan_hash / candidate.candidate_id).resolve()
    try:
        stage.relative_to(workspace)
    except ValueError as error:
        raise _error("MMC_LAYOUT_INVALID", "The PWM staging path escapes the workspace.") from error
    if stage.exists() or stage.is_symlink():
        raise _error(
            "MMC_BUILD_CONFLICT",
            "The PWM candidate staging directory already exists.",
            staging_path=str(stage),
        )
    project = stage / f"{plan.target_name}__{candidate.candidate_id}.pscx"
    library = stage / "intermediate.pslx"
    return stage, project, library


def _planned_parameter_writes(
    plan: MmcEnginePlan, candidate: MmcCandidate
) -> tuple[tuple[str, str, Any], ...]:
    writes: list[tuple[str, str, Any]] = []
    for binding in plan.source_bindings:
        owner = binding.get("owner")
        parameter = binding.get("parameter")
        if not isinstance(owner, str) or not isinstance(parameter, str):
            continue
        logical = _PARAMETER_BINDINGS.get(parameter, parameter)
        if logical in candidate.parameters:
            writes.append((owner, parameter, candidate.parameters[logical]))
    if not writes:
        raise _error(
            "MMC_BINDING_MISSING",
            "No audited PWM parameter binding matches the selected candidate.",
            candidate_id=candidate.candidate_id,
        )
    return tuple(writes)


async def _apply_and_read_back(
    service: object,
    project_name: str,
    owner: str,
    parameter: str,
    value: Any,
) -> None:
    await _require_method(service, "set_component_parameters")(
        project_name, owner, {parameter: value}
    )
    observed = await _require_method(service, "get_component_parameters")(
        project_name, owner
    )
    if not isinstance(observed, Mapping) or observed.get(parameter) != value:
        raise _error(
            "MMC_POSTCONDITION_FAILED",
            "A PWM parameter read-back differed from the immutable plan.",
            owner=owner,
            parameter=parameter,
            expected=value,
            observed=dict(observed) if isinstance(observed, Mapping) else observed,
        )


def _bound_scenarios(
    plan: MmcEnginePlan,
    scenarios: Sequence[Mapping[str, Any]] | None,
    source_project: Path,
    derived_project: Path,
) -> tuple[dict[str, Any], ...]:
    supplied = (
        [dict(item) for item in scenarios]
        if scenarios is not None
        else [
            {
                "name": name,
                "profile": "mmc_detailed_pwm_v2",
                "parameter_changes": [],
                "events": [],
                "analysis": {"metrics": ["dc_voltage"]},
            }
            for name in plan.scenarios
        ]
    )
    by_name: dict[str, dict[str, Any]] = {}
    for scenario in supplied:
        name = scenario.get("name")
        if not isinstance(name, str) or name in by_name:
            raise _error(
                "MMC_PLAN_INVALID",
                "PWM scenario evidence must bind each planned name exactly once.",
                scenario=name,
            )
        by_name[name] = scenario
    if set(by_name) != set(plan.scenarios):
        raise _error(
            "MMC_PLAN_INVALID",
            "PWM scenario payloads differ from the immutable child plan.",
            expected=list(plan.scenarios),
            observed=sorted(by_name),
        )
    result = []
    for name in plan.scenarios:
        scenario = dict(by_name[name])
        scenario["project"] = str(source_project)
        scenario["derived_project"] = str(derived_project)
        result.append(scenario)
    return tuple(result)


async def _await_scenario_terminal(
    scenario_service: object,
    scenario_id: str,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_s + 5.0
    status_method = _require_scenario_method(scenario_service, "scenario_status")
    while True:
        status = await status_method(scenario_id)
        if not isinstance(status, Mapping):
            raise _error(
                "MMC_ACCEPTANCE_FAILED",
                "The HVDC domain returned an invalid PWM scenario status.",
                scenario_id=scenario_id,
            )
        record = dict(status)
        if record.get("status") in _TERMINAL_SCENARIO_STATES:
            return record
        if asyncio.get_running_loop().time() >= deadline:
            raise _error(
                "MMC_BUILD_TIMED_OUT",
                "A PWM acceptance scenario did not reach a terminal state.",
                scenario_id=scenario_id,
            )
        await asyncio.sleep(0.1)


async def _execute_scenarios(
    plan: MmcEnginePlan,
    scenario_service: object,
    source_project: Path,
    derived_project: Path,
    scenarios: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    source_hash = _sha256(source_project)
    results: list[dict[str, Any]] = []
    run_method = _require_scenario_method(scenario_service, "run_scenario")
    analyze_method = _require_scenario_method(scenario_service, "analyze_results")
    for scenario in _bound_scenarios(
        plan, scenarios, source_project, derived_project
    ):
        try:
            started = await run_method(
                str(source_project), scenario, confirm=True
            )
            scenario_id = (
                started.get("scenario_id") if isinstance(started, Mapping) else None
            )
            if not isinstance(scenario_id, str) or not scenario_id:
                raise _error(
                    "MMC_ACCEPTANCE_FAILED",
                    "The HVDC domain did not return a PWM scenario identifier.",
                    scenario=scenario["name"],
                )
            timeout_s = float((scenario.get("run") or {}).get("timeout_s", 300.0))
            terminal = await _await_scenario_terminal(
                scenario_service, scenario_id, timeout_s
            )
            if terminal.get("status") != "completed":
                raise _error(
                    "MMC_ACCEPTANCE_FAILED",
                    "A required PWM scenario did not complete successfully.",
                    scenario=scenario["name"],
                    scenario_id=scenario_id,
                    status=terminal.get("status"),
                    error=terminal.get("error"),
                )
            output_files = terminal.get("output_files")
            if not isinstance(output_files, (list, tuple)) or not output_files:
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "A completed PWM scenario produced no result files.",
                    scenario=scenario["name"],
                    scenario_id=scenario_id,
                )
            analysis = await analyze_method(scenario_id)
            if not isinstance(analysis, Mapping) or str(
                analysis.get("verdict", "")
            ).upper() != "PASS":
                raise _error(
                    "MMC_ACCEPTANCE_FAILED",
                    "A completed PWM scenario lacked passing analysis evidence.",
                    scenario=scenario["name"],
                    scenario_id=scenario_id,
                    verdict=(
                        analysis.get("verdict")
                        if isinstance(analysis, Mapping)
                        else None
                    ),
                )
            metrics = analysis.get("metrics")
            channels = analysis.get("resolved_channels")
            if not isinstance(metrics, list) or not metrics or not isinstance(
                channels, list
            ) or not channels:
                raise _error(
                    "MMC_OUTPUT_INCOMPLETE",
                    "Passing PWM analysis lacked metric or channel evidence.",
                    scenario=scenario["name"],
                    scenario_id=scenario_id,
                )
            results.append(
                {
                    "name": scenario["name"],
                    "scenario_id": scenario_id,
                    "status": "completed",
                    "output_files": list(output_files),
                    "analysis": dict(analysis),
                }
            )
        finally:
            _verify_scenario_source(
                source_project, source_hash, str(scenario["name"])
            )
    return results


class PwmTemplateEngine:
    name = "detailed_pwm"

    async def execute_candidate(
        self,
        plan: MmcEnginePlan,
        service: object,
        *,
        candidate_id: str | None = None,
        scenario_service: object | None = None,
        scenarios: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, object]:
        sources = _source_files(plan)
        _preflight_dependencies(plan)
        _verify_sources(plan, sources)
        candidate = _candidate(plan, candidate_id)
        stage, staged_project, staged_library = _staging_paths(plan, candidate)
        stage.mkdir(parents=True)
        shutil.copy2(sources["project"], staged_project)
        shutil.copy2(sources["library"], staged_library)
        if not hmac.compare_digest(_sha256(staged_project), plan.source_hashes["project"]):
            raise _error("MMC_POSTCONDITION_FAILED", "The staged PWM project copy hash differs.")
        if not hmac.compare_digest(_sha256(staged_library), plan.source_hashes["library"]):
            raise _error("MMC_POSTCONDITION_FAILED", "The staged PWM library copy hash differs.")

        project_name = staged_project.stem
        try:
            await _require_method(service, "load_projects")(
                [str(staged_library), str(staged_project)]
            )
            for dependency in plan.dependencies:
                policy = dependency.get("repair_policy")
                if policy == "remove_if_missing" and not dependency.get("exists", False):
                    await _apply_and_read_back(
                        service,
                        project_name,
                        str(dependency["owner"]),
                        str(dependency["parameter"]),
                        "",
                    )
                elif policy == "verified_rebind":
                    await _apply_and_read_back(
                        service,
                        project_name,
                        str(dependency["owner"]),
                        str(dependency["parameter"]),
                        str(dependency["resolved_value"]),
                    )
            for owner, parameter, value in _planned_parameter_writes(plan, candidate):
                await _apply_and_read_back(
                    service, project_name, owner, parameter, value
                )
            settings = dict(candidate.settings)
            await _require_method(service, "set_project_settings")(project_name, settings)
            observed_settings = await _require_method(service, "get_project_settings")(
                project_name
            )
            if not isinstance(observed_settings, Mapping) or any(
                observed_settings.get(key) != value for key, value in settings.items()
            ):
                raise _error(
                    "MMC_POSTCONDITION_FAILED",
                    "PWM project settings read-back differed from the plan.",
                    expected=settings,
                    observed=(
                        dict(observed_settings)
                        if isinstance(observed_settings, Mapping)
                        else observed_settings
                    ),
                )
            await _require_method(service, "save_project")(project_name, confirm=True)
            scan_project(staged_project)
            await _require_method(service, "build_project")(project_name)
            scenario_source = stage / f"{staged_project.stem}_scenario_source.pscx"
            shutil.copy2(staged_project, scenario_source)
            scenario_results = await _execute_scenarios(
                plan,
                service if scenario_service is None else scenario_service,
                scenario_source,
                staged_project,
                scenarios,
            )
            validation = self.validate(
                plan,
                staged_project,
                {"scenarios": scenario_results},
            )
            _verify_sources(plan, sources)
            return {
                "state": "accepted",
                "engine": self.name,
                "candidate_id": candidate.candidate_id,
                "candidate_path": str(stage),
                "project_path": str(staged_project),
                "library_path": str(staged_library),
                "written_paths": (
                    str(staged_project),
                    str(staged_library),
                    str(scenario_source),
                ),
                "source_hashes": dict(plan.source_hashes),
                "project_sha256": _sha256(staged_project),
                "scenario_results": scenario_results,
                "validation": validation,
                "capability_level": "accepted",
            }
        except BaseException as error:
            try:
                _verify_sources(plan, sources)
            except BackendError as drift:
                raise drift from error
            raise

    def validate(
        self,
        plan: MmcEnginePlan,
        project_path: Path,
        outputs: dict[str, object],
    ) -> dict[str, object]:
        if not project_path.is_file() or project_path.suffix.casefold() != ".pscx":
            raise _error(
                "MMC_STRUCTURE_INVALID",
                "The staged PWM project is missing after execution.",
                project_path=str(project_path),
            )
        scenarios = outputs.get("scenarios")
        if not isinstance(scenarios, list) or len(scenarios) != len(plan.scenarios):
            raise _error(
                "MMC_ACCEPTANCE_FAILED",
                "The detailed PWM candidate lacks complete scenario evidence.",
            )
        observed = [
            item.get("name") for item in scenarios if isinstance(item, Mapping)
        ]
        if observed != list(plan.scenarios) or any(
            not isinstance(item, Mapping)
            or item.get("status") != "completed"
            or not isinstance(item.get("analysis"), Mapping)
            or str(item["analysis"].get("verdict", "")).upper() != "PASS"
            for item in scenarios
        ):
            raise _error(
                "MMC_ACCEPTANCE_FAILED",
                "The detailed PWM scenario evidence did not pass acceptance.",
                observed=observed,
            )
        return {
            "verdict": "PASS",
            "model_fidelity": self.name,
            "intrinsic_dc_fault_blocking": False,
            "plan_hash": plan.plan_hash,
            "scenario_count": len(scenarios),
        }


async def execute_pwm_candidate(
    plan: MmcEnginePlan,
    service: object,
    *,
    candidate_id: str | None = None,
    scenario_service: object | None = None,
    scenarios: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, object]:
    return await PwmTemplateEngine().execute_candidate(
        plan,
        service,
        candidate_id=candidate_id,
        scenario_service=scenario_service,
        scenarios=scenarios,
    )


__all__ = ["PwmTemplateEngine", "execute_pwm_candidate"]
