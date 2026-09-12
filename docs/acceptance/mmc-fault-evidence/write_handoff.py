"""Publish a traceable handoff only from a completed native acceptance run."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from pscad_mcp.acceptance.process_scope import require_acceptance_ownership
from pscad_mcp.hvdc.builders.mmc.blank_service import _recipe_contract
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    default_fault_checks,
    verify_fault_instrumentation,
    verify_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.template_native import (
    evaluate_template_native_dc_fault,
)
from tests.test_mmc_fault_evidence_real import _steady

PRODUCERS = {
    "fault_channels": "pscad_mcp/hvdc/builders/mmc/fault_channels.py",
    "template_native": "pscad_mcp/hvdc/builders/mmc/template_native.py",
    "steady_gate": "tests/test_mmc_fault_evidence_real.py",
    "acceptance": "pscad_mcp/hvdc/builders/mmc/acceptance.py",
    "template_audit": "pscad_mcp/hvdc/builders/mmc/template_audit.py",
    "line_constants": "pscad_mcp/hvdc/builders/mmc/line_constants.py",
}


def identity(path, expected=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Evidence is not a regular file: {path}")
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"Frozen evidence changed: {path}")
    return {"path": str(path.resolve()), "sha256": digest}


def read_frozen(path, digest):
    ref = identity(path, digest)
    return json.loads(Path(path).read_text(encoding="utf-8")), ref


def build_handoff(root: Path):
    report_path = root / "acceptance-report.json"
    report_ref = identity(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS" or report.get("scope") != "steady_and_dc_fault_recovery" or report.get("owned_process_cleaned") is not True:
        raise ValueError("Only completed owned steady/fault/recovery PASS evidence may be handed off")
    require_acceptance_ownership(report["launch_ownership"])
    if report["source_hashes"] != report["source_hashes_after"] or report.get("compiler_support_immutable") is not True:
        raise ValueError("The original inputs or compiler support changed")
    for source in report["source_hashes"].values():
        identity(source["path"], source["sha256"])
    for support in report["compiler_support_copies"]:
        identity(support["path"], support["sha256"])
        identity(support["copied_path"], support["copied_sha256"])
        if support["sha256"] != support["copied_sha256"]:
            raise ValueError("A copied compiler input differs from its frozen source")

    cases = {case["case"]: case for case in report["cases"]}
    if len(cases) != len(report["cases"]) or set(cases) != {"steady", "fault"}:
        raise ValueError("One steady and one fault case are required")
    names = {case["recipe_id"] for case in cases.values()}
    if len(names) != 1:
        raise ValueError("The accepted cases use different recipes")
    recipe_name = next(iter(names))
    if recipe_name != "native_full_sort_dc_integral_004_v1":
        raise ValueError("This publisher requires the verified T1 integral-time recipe")
    descriptor = _recipe_contract(recipe_name)
    parameters = {"current_limit_pu": 1.1, "dc_feedback_time_constant_s": 0.005, "terminal_two_carrier_ratio": 23.0, "arm_virtual_resistance_ohm": 30.0, "sort_extent": "Dim", "sort_enable": "existing_Enab", "t1_dc_integral_time_s": 0.04}
    if descriptor["parameters"] != parameters:
        raise ValueError("The public recipe descriptor differs from the verified native candidate")
    checks = default_fault_checks()
    if report["checks_contract"] != checks:
        raise ValueError("The accepted report does not use the production checks")

    repository = Path(__file__).resolve().parents[3]
    recorded_code = {name.replace("\\", "/"): digest for name, digest in report["code_hashes"].items()}
    producer_refs = {}
    destination = root / "producer-code"
    if destination.is_symlink():
        raise ValueError("The producer-code directory must not be a symlink")
    destination.mkdir(exist_ok=True)
    for role, relative in PRODUCERS.items():
        source = repository / relative
        identity(source, recorded_code[relative])
        frozen = destination / source.name
        if not frozen.exists():
            with frozen.open("xb") as stream:
                stream.write(source.read_bytes())
        producer_refs[role] = identity(frozen, recorded_code[relative])

    evidence = {"acceptance_report": report_ref}
    channels = []
    validations = {}
    for name, case in cases.items():
        case_path = root / name / "report.json"
        if json.loads(case_path.read_text(encoding="utf-8")) != case or case["status"] != "PASS":
            raise ValueError("A case report differs from the completed run record")
        contract, contract_ref = read_frozen(case["channel_contract_path"], case["channel_contract_sha256"])
        index, index_ref = read_frozen(case["output_index_path"], case["output_index_sha256"])
        samples, samples_ref = read_frozen(case["samples_path"], case["samples_sha256"])
        if samples["identity"] != index or contract["required_checks"] != checks:
            raise ValueError("Case samples or physical checks differ from their original freeze")
        if samples.get("missing_selectors") or len(samples["channels"]) != len(contract["channels"]) + len(contract.get("diagnostic_channels", [])):
            raise ValueError("The original bound channel set is incomplete")
        verify_output_dataset(index)
        verify_fault_instrumentation(case["project"], contract)
        final_hash = contract["instrumented_project_sha256"]
        if case["readback"]["project_sha256"] != final_hash:
            raise ValueError("Finalized project hashes disagree")
        project_ref = identity(case["project"], final_hash)
        result = _steady(samples, contract, checks) if name == "steady" else evaluate_template_native_dc_fault(samples, channel_contract=contract, checks_contract=checks, fault_current_limit_ka=checks["fault_current_limit_ka"])
        if result["verdict"] != "PASS":
            raise ValueError(f"Recomputed {name} acceptance does not pass")
        expected_steps = (("charging_delay_repair", "after", "Tcharging2"), ("operating_point_repair", "after_pu", 1.1), ("feedback_filter", "time_constant_s", 0.005), ("carrier_diagnostic", "after_ratio", 23.0), ("arm_virtual_resistance", "resistance_per_arm_ohm", 30.0), ("complete_sorting", "sort_extent", "Dim"), ("dc_integral_repair", "after_s", 0.04))
        previous = None
        for record_name, parameter, expected in expected_steps:
            step = case[record_name]
            if step[parameter] != expected:
                raise ValueError("The executed derivation differs from the handoff recipe")
            source_ref = identity(step["source"], step["source_sha256"])
            output_ref = identity(step["destination"], step["destination_sha256"])
            if previous is not None and source_ref != previous:
                raise ValueError("The model derivation chain is discontinuous")
            previous = output_ref
        if previous != contract["source_hashes"]["project"]:
            raise ValueError("Instrumentation did not consume the final recipe derivation")
        key = "steady" if name == "steady" else "dc_fault"
        evidence[key] = {"case_report": identity(case_path), "channel_contract": contract_ref, "output_index": index_ref, "samples": samples_ref, "project": project_ref}
        validations[key] = {"verdict": result["verdict"], "output_file_count": len(index["files"]), "sample_channel_count": len(samples["channels"]), "emtdc_elapsed_s": case["emtdc_elapsed_s"]}
        if name == "fault":
            traces = {trace["channel_id"]: trace for trace in samples["channels"]}
            if len(traces) != len(samples["channels"]):
                raise ValueError("A runtime channel identity is duplicated")
            fields = ("output_part", "metadata_file", "metadata_sha256", "compiler_metadata_file", "compiler_metadata_sha256", "hash", "call_id", "compiled_identity", "sample_count", "time_bounds_s")
            for binding in contract["channels"]:
                trace = traces[binding["channel_id"]]
                channels.append({**copy.deepcopy(binding), **{field: copy.deepcopy(trace[field]) for field in fields}})
        verify_output_dataset(index)
    identity(report_path, report_ref["sha256"])
    return {"schema_version": 1, "producer_revision": report["commit"], "scope": "template_native_dc_fault", "status": "PASS", "source_hashes": report["source_hashes"], "recipe": {"id": recipe_name, "parameters": descriptor["parameters"], "steps": descriptor["steps"], "producer_code_hashes": producer_refs}, "required_checks": checks, "channels": channels, "instrumented_project_sha256": evidence["dc_fault"]["project"]["sha256"], "evidence": evidence, "validation": validations}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = build_handoff(args.root.resolve())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    print(f"MMC_CHANNELS_HANDOFF={args.output.resolve()}")
    print(f"producer={payload['producer_revision']} channels={len(payload['channels'])} scope={payload['scope']}")
