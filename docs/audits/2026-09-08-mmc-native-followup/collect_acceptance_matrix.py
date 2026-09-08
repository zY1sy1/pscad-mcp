"""Prepare the actual MMC test request/scenario matrix using offline functions."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OWNED = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from collect_signal_audit import digest, snapshot

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.assets import load_packaged_asset_set
from pscad_mcp.hvdc.builders.mmc.derivation import derive_mmc_parameters
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from pscad_mcp.hvdc.builders.mmc.parametric_planner import (
    STANDARD_SCENARIOS,
    create_parametric_plan,
)
from pscad_mcp.hvdc.builders.mmc.scenarios import recommend_scenarios
from pscad_mcp.hvdc.builders.mmc.template_audit import (
    build_template_audit,
    discover_official_mmc_template,
)

DEFAULT_PREPARED = Path("D:/PSCAD-Workspace/mmc-parametric-acceptance/mmc-parametric-acceptance-20260828T080837223737Z")
TEST = REPO / "tests/test_mmc_parametric_real_acceptance.py"
ROADMAP = REPO / "docs/superpowers/specs/2026-08-30-lcc-mmc-completion-roadmap-design.md"
ENGINES = ("detailed_pwm", "average_value")


def test_requests() -> tuple[tuple[dict, ...], tuple[tuple[str, dict], ...]]:
    spec = importlib.util.spec_from_file_location("mmc_real_acceptance_matrix_source", TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._feasible_requests(), module._infeasible_requests()


def attempt_plan(request: dict, name: str, audit: object, assets: object) -> dict:
    try:
        plan = create_parametric_plan(request, name, OWNED / "not-materialized", audit, assets)
    except BackendError as error:
        return {"status": "rejected", "error": error.to_dict()}
    return {
        "status": "planned", "plan_hash": plan.plan_hash, "equation_version": plan.equation_version,
        "workspace_created": False,
        "engines": [
            {"engine": engine.engine, "plan_hash": engine.plan_hash,
             "candidate_hashes": [candidate.parameter_hash for candidate in engine.candidates],
             "candidate_count": len(engine.candidates), "settings": dict(engine.settings),
             "source_hashes": dict(engine.source_hashes), "asset_hashes": dict(engine.asset_hashes),
             "scenarios": list(engine.scenarios), "capabilities": dict(engine.capabilities)}
            for engine in plan.engine_plans
        ],
    }


def collect(prepared_root: Path) -> dict:
    feasible, infeasible = test_requests()
    if len(feasible) != 3 or len(infeasible) != 6 or len(STANDARD_SCENARIOS) != 11:
        raise ValueError("The acceptance test matrix changed; review the collector")
    official_project, official_library = discover_official_mmc_template()
    prepared_pairs = [(prepared_root / f"feasible-{index + 1}/pwm-sources/H_MMC_Mono_DC.pscx",
                       prepared_root / f"feasible-{index + 1}/pwm-sources/intermediate.pslx") for index in range(3)]
    files = [TEST, ROADMAP, REPO / "docs/acceptance-criteria.md", Path(__file__).resolve(),
             OWNED / "collect_signal_audit.py", REPO / "pscad_mcp/hvdc/profiles.py",
             official_project, official_library]
    files += [REPO / f"pscad_mcp/hvdc/builders/mmc/{name}.py" for name in ("derivation", "parametric_models", "parametric_planner", "scenarios", "template_audit", "assets")]
    files += list((REPO / "pscad_mcp/assets/mmc/cigre_b4_p2p_avm_v1").rglob("*"))
    files += [path for pair in prepared_pairs for path in pair]
    for _, library in [(official_project, official_library), *prepared_pairs]:
        files += list((library.parent / "Obj_Files_2016_03_25").rglob("*"))
    for index in range(3):
        files += list((prepared_root / f"feasible-{index + 1}/public-line-constants").rglob("*"))
    files = [path for path in files if path.is_file()]
    before = snapshot(files)
    assets = load_packaged_asset_set()
    official_audit = build_template_audit(official_project, official_library)
    official_guard = attempt_plan(feasible[0], "OFFICIAL_MMC", official_audit, assets)
    prepared_audits = [build_template_audit(project, library) for project, library in prepared_pairs]
    feasible_results, scenario_rows = [], []
    for index, (request, audit) in enumerate(zip(feasible, prepared_audits), 1):
        design = derive_mmc_parameters(parse_parametric_request(request))
        plan = attempt_plan(request, f"MMC_CASE_{index}", audit, assets)
        if not design.feasible or plan["status"] != "planned":
            raise ValueError(f"Previously feasible case {index} no longer prepares: {plan}")
        engines = {item["engine"] for item in plan["engines"]}
        if engines != set(ENGINES) or any(set(item["scenarios"]) != set(STANDARD_SCENARIOS) for item in plan["engines"]):
            raise ValueError("Incomplete engine or scenario plan")
        case_id = f"feasible-{index}"
        feasible_results.append({
            "case_id": case_id, "request": request, "analytic_feasible": design.feasible,
            "derivation": {"equation_version": design.equation_version, "common": dict(design.common), "constraints": [item.to_dict() for item in design.constraints], "candidate_hashes": [item.parameter_hash for item in design.candidates]},
            "offline_plan": plan,
            "prepared_source_audit": {key: audit.to_dict()[key] for key in ("compatible", "sources", "source_hashes", "absolute_paths", "compiler_support", "submodule_topology")},
            "topology_caveat": "Request is half_bridge; the audited detailed PWM template declares full_bridge. A successful plan does not prove requested half-bridge materialization or either topology's dynamic capabilities.",
            "licensed_status": "NOT_RUN_ON_CURRENT_COMMIT",
        })
        for engine in ENGINES:
            engine_request = {**request, "model_fidelity": engine}
            engine_design = derive_mmc_parameters(parse_parametric_request(engine_request))
            recommendations = recommend_scenarios(engine_design, derived_project=f"MMC_CASE_{index}_{engine}")
            if tuple(item.name for item in recommendations) != STANDARD_SCENARIOS:
                raise ValueError("Recommendations differ from the real-test scenario matrix")
            for recommendation in recommendations:
                record = recommendation.to_dict()
                if record["capabilities"]["intrinsic_dc_fault_blocking"] is not False:
                    raise ValueError("Half-bridge recommendation claims intrinsic blocking")
                scenario_rows.append({
                    "case_id": case_id, "engine": engine, "converter_request": "half_bridge",
                    "scenario_name": recommendation.name,
                    "events": record["scenario"]["events"], "duration_s": record["duration_s"],
                    "time_step_s": record["time_step_s"], "output_step_s": record["scenario"]["output_step_s"],
                    "metrics": record["metrics"], "thresholds": record["thresholds"],
                    "preconditions": record["preconditions"], "capabilities": record["capabilities"],
                    "limitations": record["limitations"], "licensed_status": "NOT_RUN_ON_CURRENT_COMMIT",
                    "physical_verdict": None, "golden_verdict": None, "output_hashes": {},
                })
    guards = []
    for expected, request in infeasible:
        design = derive_mmc_parameters(parse_parametric_request(request))
        failures = [item.name for item in design.constraints if not item.passed]
        planned = attempt_plan(request, f"GUARD_{expected}", prepared_audits[0], assets)
        passed = not design.feasible and expected in failures and planned["status"] == "rejected" and planned["error"]["code"] == "MMC_REQUEST_INFEASIBLE"
        guards.append({"expected_constraint": expected, "request": request, "analytic_feasible": design.feasible, "failed_constraints": failures, "constraints": [item.to_dict() for item in design.constraints], "planner": planned, "offline_guard_passed": passed})
        if not passed:
            raise ValueError(f"Infeasible guard {expected} did not reject for its intended constraint")
    try:
        parse_parametric_request({**feasible[0], "converter": "full_bridge"})
    except BackendError as error:
        full_bridge_guard = {"rejected": True, "error": error.to_dict()}
    else:
        raise ValueError("Parametric full-bridge scope changed; review the acceptance matrix")
    after = snapshot(files)
    if before != after:
        raise ValueError("A planner, test fixture, asset or source changed during collection")
    if (OWNED / "not-materialized").exists():
        raise ValueError("Offline planner unexpectedly materialized its target")
    return {
        "schema_version": 1, "scope": "offline_parametric_acceptance_preparation", "status": "planned",
        "collection_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "licensed_run_performed": False, "runtime_process_started": False,
        "counts": {"feasible_requests": 3, "infeasible_guards": 6, "engines": 2, "scenarios_per_engine": 11, "scenario_rows": len(scenario_rows)},
        "source_manifest_before": before, "source_manifest_after": after, "sources_immutable": True,
        "test_source": TEST.as_posix(), "engines": list(ENGINES), "standard_scenarios": list(STANDARD_SCENARIOS),
        "feasible_cases": feasible_results, "infeasible_guards": guards, "scenario_matrix": scenario_rows,
        "raw_official_template_guard": {"plan": official_guard, "absolute_paths": list(official_audit.absolute_paths), "remedy": "Use verified independently hashed line-constant artifacts in isolated staging. The existing historical prepared copies used here already contain such bindings; no source files were modified."},
        "full_bridge_parametric_guard": full_bridge_guard,
        "wp4": {
            "reference": {"path": ROADMAP.as_posix(), "section": "12"},
            "required_channels": ["fault_active", "v_inserted", "blocking_state", "i_dc_fault", "v_dc", "i_arm", "v_cap", "recovery_enable", "time"],
            "required_channel_fields": ["path", "units", "dimension", "owner_id", "component_definition", "signal_source", "output_part", "inf_metadata", "sample_count", "time_bounds", "source_hash"],
            "required_physical_checks": ["fault active in planned window", "negative inserted voltage reaches existing contract threshold during fault", "blocking observed", "fault-current peak within existing bound", "blocking released after fault removal", "DC voltage/power/arm-current recovery within contract", "valid units and simulation-time domains"],
            "missing_evidence_action": "MMC_ACCEPTANCE_INCOMPLETE; add real probes in a derived copy, save/reload, rerun affected licensed acceptance. Never synthesize a missing channel.",
            "historical_signal_manifest": "signal-manifest.json",
        },
        "wp6": {
            "reference": {"path": ROADMAP.as_posix(), "section": "14"},
            "independent_reference_status": "MISSING_REVIEWED_REFERENCE",
            "acceptable_sources": ["licensed run of independent manual or official reference project", "independently reviewed external output", "reference assembly that does not share the builder implementation path"],
            "required_identity": ["reference_id", "source_project_hash", "source_library_hash", "PSCAD_version", "compiler_identity", "parameters", "output_file_hashes", "channel_selectors", "units", "review_id", "reviewer", "review_date", "review_scope"],
            "prohibited_sources": ["golden generated by the builder under test in the same run", "hand-copied constant arrays", "synthetic fixtures", "historical template evidence promoted to current autonomous acceptance"],
            "regeneration_rule": "Every regeneration creates a new reference identity and hashes.",
            "final_paths": [
                {"path": "blank_native_full_bridge", "steady": "required", "reversal": "required", "dc_fault": "required", "physical": "required", "golden": "required", "publication": "required"},
                {"path": "detailed_pwm_full_bridge", "steady": "required", "reversal": "required", "dc_fault": "required", "physical": "required", "golden": "required", "publication": "required"},
                {"path": "average_value_full_bridge", "steady": "required", "reversal": "required", "dc_fault": "required", "physical": "required", "golden": "required", "publication": "required"},
                {"path": "average_value_half_bridge", "steady": "required", "reversal": "required", "dc_fault": "limitation_check", "physical": "required", "golden": "required", "publication": "required", "intrinsic_dc_fault_blocking": False},
            ],
            "publication_gates": ["all required cases PASS", "physical checks PASS", "golden checks PASS", "final project compile smoke PASS", "immutable sources and preexisting workspace", "current-commit report", "report-schema validation PASS", "all owned runtime processes exited", "no unresolved critical/important review findings", "full test suite PASS"],
        },
        "licensed_prerequisites": {
            "required_environment": {"PSCAD_MCP_MMC_ACCEPTANCE": "1", "PSCAD_MCP_BACKEND": "legacy", "PSCAD_MCP_VERSION": "4.6.2", "PSCAD_MCP_WORKSPACE": "existing absolute isolated workspace", "PSCAD_MCP_MMC_TEMPLATE": "immutable H_MMC_Mono_DC.pscx", "PSCAD_MCP_MMC_LIBRARY": "immutable intermediate.pslx"},
            "ownership": "Independent instance/executor/workspace with vendor-confirmed ownership. Do not terminate foreign processes. Concurrent opt-in only when the actual runner supports it.",
            "command_template": "python -m pytest tests/test_mmc_parametric_real_acceptance.py -q -s",
        },
        "limitations": [
            "Planning and analytic rejection checks do not establish compiled, simulated or accepted capability.",
            "The six prepared engine plans and 66 recommendation rows require fresh licensed outputs at the delivered revision.",
            "The raw official template has missing C:/Temp/my_constants_file.tlo bindings; guard results must not be removed to force planning.",
            "Parametric converter parsing supports half_bridge only. The full-bridge roadmap paths require separate implementation and independent evidence.",
            "Reference review identity and reviewed waveforms remain missing. No accepted status was updated.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-root", type=Path, default=DEFAULT_PREPARED)
    args = parser.parse_args()
    result = collect(args.prepared_root.resolve())
    target = OWNED / "acceptance-matrix.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": target.as_posix(), "sha256": digest(target), "counts": result["counts"], "feasible_plans": sum(case["offline_plan"]["status"] == "planned" for case in result["feasible_cases"]), "infeasible_guards_passed": sum(case["offline_guard_passed"] for case in result["infeasible_guards"]), "full_bridge_rejected": result["full_bridge_parametric_guard"]["rejected"], "sources_immutable": result["sources_immutable"]}, indent=2))


if __name__ == "__main__":
    main()
