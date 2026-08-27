"""Side-effect-free composition of immutable dual-engine MMC plans."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ..common.serialization import content_hash
from .derivation import EQUATION_VERSION, derive_mmc_parameters
from .parametric_models import (
    MmcCandidate,
    MmcEnginePlan,
    MmcParametricRequest,
    MmcParentPlan,
    parse_parametric_request,
)


STANDARD_SCENARIOS = (
    "startup", "forward_steady", "active_power_step", "reactive_power_step",
    "power_reversal", "reverse_steady", "ac_three_phase_fault",
    "ac_single_line_ground_fault", "dc_pole_to_pole_fault",
    "dc_pole_to_ground_fault", "post_fault_recovery",
)


def _error(code: str, message: str, **details: object) -> BackendError:
    return BackendError(code, message, "hvdc", "plan_parametric_mmc_model", details)


def _audit_dict(audit: object) -> dict[str, Any]:
    if hasattr(audit, "to_dict") and callable(getattr(audit, "to_dict")):
        value = audit.to_dict()
    elif isinstance(audit, Mapping):
        value = dict(audit)
    else:
        raise _error("MMC_TEMPLATE_INVALID", "PWM audit must be a structured audit record.")
    return value


def _hashes(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise _error("MMC_SOURCE_HASH_MISSING", f"{label} hashes are required.")
    result = dict(value)
    if any(not isinstance(key, str) or not isinstance(item, str) or re.fullmatch(r"[0-9a-f]{64}", item) is None for key, item in result.items()):
        raise _error("MMC_SOURCE_HASH_MISSING", f"{label} hashes must be SHA-256 values.")
    return result


def _target(workspace: Path, project_name: str, suffix: str) -> tuple[str, Path]:
    raw_name = project_name.strip()
    if not raw_name or any(separator in raw_name for separator in ("/", "\\")):
        raise _error("MMC_LAYOUT_INVALID", "project_name must be one workspace-safe identity.")
    identity = Path(raw_name).stem if raw_name.casefold().endswith(".pscx") else raw_name
    if identity in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identity):
        raise _error("MMC_LAYOUT_INVALID", "project_name is not workspace-safe.", project_name=project_name)
    target_name = f"{identity}_{suffix}"
    target_path = (workspace / f"{target_name}.pscx").resolve()
    try:
        target_path.relative_to(workspace)
    except ValueError as error:
        raise _error("MMC_LAYOUT_INVALID", "Planned target escapes the workspace.") from error
    if target_path.exists() or target_path.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "A planned MMC final target already exists.", target_path=str(target_path))
    return target_name, target_path


def _candidate_group(candidates: tuple[MmcCandidate, ...], engine: str) -> tuple[MmcCandidate, ...]:
    selected = tuple(item for item in candidates if item.engine == engine)
    if not 1 <= len(selected) <= 8:
        raise _error("MMC_CANDIDATE_INVALID", "Each MMC engine plan requires 1-8 candidates.", engine=engine, count=len(selected))
    hashes = [item.parameter_hash for item in selected]
    if any(not value for value in hashes) or len(set(hashes)) != len(hashes):
        raise _error("MMC_CANDIDATE_INVALID", "MMC candidate parameter hashes must be non-empty and unique.", engine=engine)
    return selected


def _pwm_reference(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "evidence": f"audited-template:{audit['source_hashes']['project']}",
        "reference_cells_per_arm": 400,
        "arm_inductance_h": 0.05,
        "arm_resistance_ohm": 0.15,
        "stored_energy_mj": 40.0,
        "switching_frequency_hz": 1350.0,
        "control_sample_time_s": 50e-6,
        "control_bandwidth_hz": 100.0,
    }


def _avm_reference(asset_set: object) -> dict[str, Any]:
    blueprint = getattr(asset_set, "blueprint", None)
    settings = getattr(blueprint, "settings", {})
    return {
        "evidence": f"repository-asset:{getattr(asset_set, 'name', 'unknown')}",
        "reference_cells_per_arm": 400,
        "arm_inductance_h": 0.05,
        "arm_resistance_ohm": 0.15,
        "stored_energy_mj": 40.0,
        "control_sample_time_s": float(settings.get("time_step_s", 100e-6)) * 2.0,
        "control_bandwidth_hz": 80.0,
    }


def _engine_plan(
    *,
    engine: str,
    target_name: str,
    target_path: Path,
    workspace: Path,
    candidates: tuple[MmcCandidate, ...],
    source_paths: dict[str, str],
    source_hashes: dict[str, str],
    asset_hashes: dict[str, str],
    source_bindings: tuple[dict[str, Any], ...],
    dependencies: tuple[dict[str, Any], ...],
) -> MmcEnginePlan:
    if engine == "detailed_pwm":
        operations = (
            {"kind": "verify_source_hashes"}, {"kind": "copy_template_pair"},
            {"kind": "apply_audited_bindings"}, {"kind": "read_back_parameters"},
            {"kind": "compile"}, {"kind": "run_scenarios"}, {"kind": "validate"},
        )
    else:
        operations = (
            {"kind": "verify_asset_hashes"}, {"kind": "materialize_parametric_blueprint"},
            {"kind": "execute_fixed_builder"}, {"kind": "compile"},
            {"kind": "run_scenarios"}, {"kind": "validate"},
        )
    payload = {
        "engine": engine,
        "target_name": target_name,
        "target_path": str(target_path),
        "workspace": str(workspace),
        "candidates": [item.to_dict() for item in candidates],
        "source_paths": source_paths,
        "source_hashes": source_hashes,
        "asset_hashes": asset_hashes,
        "source_bindings": source_bindings,
        "dependencies": dependencies,
        "operations": operations,
        "settings": candidates[0].settings,
        "scenarios": STANDARD_SCENARIOS,
        "capabilities": {"intrinsic_dc_fault_blocking": False},
    }
    return MmcEnginePlan(
        engine=engine,
        target_name=target_name,
        target_path=str(target_path),
        workspace=str(workspace),
        candidates=candidates,
        plan_hash=content_hash(payload),
        source_paths=source_paths,
        source_hashes=source_hashes,
        asset_hashes=asset_hashes,
        source_bindings=source_bindings,
        dependencies=dependencies,
        operations=operations,
        settings=dict(candidates[0].settings),
        scenarios=STANDARD_SCENARIOS,
        capabilities={"intrinsic_dc_fault_blocking": False},
    )


def create_parametric_plan(
    request: MmcParametricRequest | Mapping[str, Any],
    project_name: str,
    workspace: str | Path,
    pwm_audit: object,
    avm_assets: object,
) -> MmcParentPlan:
    parsed = parse_parametric_request(request)
    workspace_root = Path(workspace).expanduser().resolve()
    audit = _audit_dict(pwm_audit)
    source_hashes = _hashes(audit.get("source_hashes"), "PWM source")
    audit_sources = audit.get("sources", {})
    if not isinstance(audit_sources, Mapping):
        raise _error("MMC_TEMPLATE_INVALID", "PWM source paths must be a mapping.")
    source_paths = {str(key): str(value) for key, value in audit_sources.items()}
    asset_hashes = _hashes(getattr(avm_assets, "hashes", None), "AVM asset")
    requested_engines = (
        ("detailed_pwm", "average_value") if parsed.model_fidelity == "both" else (parsed.model_fidelity,)
    )
    if "detailed_pwm" in requested_engines:
        if audit.get("compatible") is not True:
            raise _error("MMC_TEMPLATE_INCOMPATIBLE", "The audited PWM template is not compatible.")
        unresolved = [
            item
            for item in audit.get("absolute_paths", ())
            if isinstance(item, Mapping) and item.get("repair_policy") == "requires_verified_rebind"
        ]
        if unresolved:
            raise _error(
                "MMC_ABSOLUTE_PATH_UNRESOLVED",
                "The audited PWM template contains unresolved line dependencies.",
                dependencies=[dict(item) for item in unresolved],
            )
    derived = derive_mmc_parameters(
        parsed,
        pwm_reference=_pwm_reference(audit),
        avm_reference=_avm_reference(avm_assets),
    )
    if not derived.feasible:
        raise _error("MMC_REQUEST_INFEASIBLE", "The MMC request failed analytic constraints.", diagnostics=list(derived.diagnostics))
    identity = Path(project_name).stem if project_name.casefold().endswith(".pscx") else project_name
    plans: list[MmcEnginePlan] = []
    for engine in requested_engines:
        suffix = "pwm" if engine == "detailed_pwm" else "avm"
        target_name, target_path = _target(workspace_root, identity, suffix)
        candidates = _candidate_group(derived.candidates, engine)
        if engine == "detailed_pwm":
            bindings = tuple(dict(item) for item in (*audit.get("role_bindings", ()), *audit.get("writable_parameter_bindings", ())))
            dependencies = tuple(dict(item) for item in audit.get("absolute_paths", ()))
            plan_source_paths, plan_source_hashes, plan_asset_hashes = source_paths, source_hashes, {}
        else:
            bindings = ()
            dependencies = ()
            plan_source_paths, plan_source_hashes, plan_asset_hashes = {}, {}, asset_hashes
        plans.append(
            _engine_plan(
                engine=engine,
                target_name=target_name,
                target_path=target_path,
                workspace=workspace_root,
                candidates=candidates,
                source_paths=plan_source_paths,
                source_hashes=plan_source_hashes,
                asset_hashes=plan_asset_hashes,
                source_bindings=bindings,
                dependencies=dependencies,
            )
        )
    parent_payload = {
        "request": parsed.to_dict(),
        "project_name": identity,
        "workspace": str(workspace_root),
        "equation_version": EQUATION_VERSION,
        "child_hashes": [item.plan_hash for item in plans],
    }
    return MmcParentPlan(
        request=parsed,
        project_name=identity,
        workspace=str(workspace_root),
        equation_version=EQUATION_VERSION,
        engine_plans=tuple(plans),
        plan_hash=content_hash(parent_payload),
    )


__all__ = ["STANDARD_SCENARIOS", "create_parametric_plan"]
