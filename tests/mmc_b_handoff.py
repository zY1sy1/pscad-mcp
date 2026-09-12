"""Verify native B evidence before an independently owned integration run."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import re
import stat
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath

from pscad_mcp.acceptance.evidence import _is_reparse_point
from pscad_mcp.core.pscad_adapter import PscadAdapter
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    default_fault_checks,
    read_fault_output_dataset,
    verify_fault_instrumentation,
    verify_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.template_native import (
    evaluate_template_native_dc_fault,
)
from tests.test_mmc_fault_evidence_real import _steady

_DIGEST = re.compile(r"[0-9a-f]{64}")
_STAGES = (
    "native_binding", "charging_delay_repair", "operating_point_repair",
    "feedback_filter", "carrier_diagnostic", "arm_virtual_resistance",
    "complete_sorting", "dc_integral_repair",
)


def _file_identity(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Evidence paths must be absolute")
    for item in (path, *path.parents):
        if _is_reparse_point(item.lstat()):
            raise ValueError("Evidence paths must not traverse reparse points")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Evidence must be a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in fields):
        raise ValueError("Evidence changed while hashing")
    return {"path": str(path.resolve()), "sha256": digest.hexdigest()}


def _check_ref(ref, expected=None, *, within=None):
    if not isinstance(ref, Mapping) or not _DIGEST.fullmatch(str(ref.get("sha256", ""))):
        raise ValueError("Evidence has no valid SHA-256 reference")
    identity = _file_identity(ref["path"])
    if identity["sha256"] != ref["sha256"]:
        raise ValueError("Evidence identity changed: " + identity["path"])
    if expected is not None and Path(identity["path"]) != Path(expected).resolve():
        raise ValueError("Evidence refers to a different case artifact")
    if within is not None and not Path(identity["path"]).is_relative_to(Path(within).resolve()):
        raise ValueError("Case evidence is outside its recorded run")
    return identity


def _load_ref(ref, expected=None, *, within=None):
    identity = _check_ref(ref, expected, within=within)
    raw = Path(identity["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != identity["sha256"]:
        raise ValueError("Evidence changed before parsing")
    return json.loads(raw), identity


def require_recipe_match(b_recipe, public_recipe):
    if (
        b_recipe.get("id") != public_recipe.get("name")
        or b_recipe.get("parameters") != public_recipe.get("parameters")
        or b_recipe.get("steps") != public_recipe.get("steps")
    ):
        raise ValueError("B and public execution use different model recipes")
    return True


def _verify_owned_runtime(report):
    identities = []
    for key in ("launch_ownership", "runtime"):
        record = report.get(key, {})
        session = record.get("session", {})
        pid = session.get("managed_pid")
        executable = Path(str(session.get("managed_executable", "")))
        if (
            record.get("owns_process") is not True
            or type(pid) is not int or pid <= 0
            or session.get("mode") != "managed-launch"
            or not executable.is_absolute() or executable.name.casefold() != "pscad.exe"
        ):
            raise ValueError("B has no consistent owned PSCAD launch and runtime")
        identities.append((pid, executable.resolve()))
    if identities[0] != identities[1]:
        raise ValueError("B owned PSCAD launch and runtime identities disagree")


def _verify_producers(recipe, report):
    refs = recipe.get("producer_code_hashes", {})
    required = {"fault_channels", "template_native"}
    if not isinstance(refs, Mapping) or not required <= set(refs):
        raise ValueError("The B physics producers are not frozen")
    raw = report.get("code_hashes", {})
    recorded = {PureWindowsPath(key).as_posix(): digest for key, digest in raw.items()}
    if len(recorded) != len(raw):
        raise ValueError("B producer paths are ambiguous after normalization")
    for name, ref in refs.items():
        identity = _check_ref(ref)
        if name in required:
            key = f"pscad_mcp/hvdc/builders/mmc/{name}.py"
            if identity["sha256"] != recorded.get(key):
                raise ValueError("B producer differs from the actual native run: " + name)
        elif not any(
            Path(key).name == Path(identity["path"]).name and digest == identity["sha256"]
            for key, digest in recorded.items()
        ):
            raise ValueError("An additional B producer was not recorded by its run")


def _verify_support(report, root):
    before = report["compiler_support_before"]["files"]
    if report.get("compiler_support_immutable") is not True or before != report["compiler_support_after"]["files"]:
        raise ValueError("B compiler support was not immutable")
    copies = report["compiler_support_copies"]
    by_name = {item["relative_path"]: item for item in copies}
    if not before or len(by_name) != len(copies) or set(by_name) != {item["relative_path"] for item in before}:
        raise ValueError("B compiler support copies are incomplete")
    for item in before:
        _check_ref(item)
        copied = by_name[item["relative_path"]]
        if copied["sha256"] != item["sha256"] or copied["copied_sha256"] != item["sha256"]:
            raise ValueError("A compiler support copy has the wrong identity")
        _check_ref({"path": copied["copied_path"], "sha256": copied["copied_sha256"]}, root / item["relative_path"], within=root)
    lines = report.get("line_constants", [])
    if len(lines) != 2 or {line["segment"] for line in lines} != {"TL12a", "TL12b"}:
        raise ValueError("The two native line-constant segments are not frozen")
    for line in lines:
        if line.get("returncode") != 0:
            raise ValueError("Line-constant generation did not succeed")
        for key in ("input", "constants", "log", "output"):
            _check_ref({"path": line[key + "_path"], "sha256": line[key + "_sha256"]}, within=root)


def _verify_lineage(case, contract, root):
    previous = None
    for key in _STAGES:
        stage = case.get(key)
        if stage is None:
            if key == "dc_integral_repair":
                continue
            raise ValueError("The native recipe lineage is incomplete: " + key)
        source = _check_ref({"path": stage["source"], "sha256": stage["source_sha256"]}, within=root)
        target = _check_ref({"path": stage["destination"], "sha256": stage["destination_sha256"]}, within=root)
        if previous is not None and source != previous:
            raise ValueError("Native recipe stages do not form one model lineage")
        previous = target
    if previous != _check_ref(contract["source_hashes"]["project"], within=root):
        raise ValueError("Instrumentation used a different recipe output")


def _verify_pi(samples, recipe, checks):
    expected = (
        ("T1", "controller_dc_proportional_gain", 12.0),
        ("T1", "controller_dc_integral_time", recipe["parameters"].get("t1_dc_integral_time_s", 0.08)),
        ("T2", "controller_dc_proportional_gain", 0.2),
        ("T2", "controller_dc_integral_time", 0.2),
    )
    for terminal, role, nominal in expected:
        matches = [item for item in samples["channels"] if item["channel_id"] == f"MFE_{terminal}_{role}"]
        if len(matches) != 1:
            raise ValueError("An actual DC PI parameter channel is missing or ambiguous")
        values = [value for instant, value in zip(matches[0]["domain"], matches[0]["values"])
                  if checks["prefault_window_s"][0] <= instant <= checks["recovery_window_s"][1]]
        if not values or not all(math.isclose(value, nominal, abs_tol=1e-12, rel_tol=0) for value in values):
            raise ValueError("Actual DC PI parameters differ from the accepted recipe")


def _verify_channel_handoff(rows, contract, samples):
    bindings = {item["channel_id"]: item for item in contract["channels"] + contract.get("diagnostic_channels", [])}
    traces = {item["channel_id"]: item for item in samples["channels"]}
    ids = [item["channel_id"] for item in rows]
    if len(ids) != len(set(ids)) or not {item["channel_id"] for item in contract["channels"]} <= set(ids) <= set(bindings):
        raise ValueError("The handoff channel matrix is incomplete or ambiguous")
    static = ("role", "model_scope", "instance_path", "owner_id", "definition", "definition_name", "signal_source", "selector", "units", "dimension", "polarity", "nominal", "nominal_role")
    observed = ("output_part", "metadata_file", "sample_count", "time_bounds_s", "hash", "metadata_sha256",
                "compiler_metadata_file", "compiler_metadata_sha256", "call_id", "compiled_identity")
    for row in rows:
        binding, trace = bindings[row["channel_id"]], traces[row["channel_id"]]
        if any(row.get(key) != binding.get(key) for key in static):
            raise ValueError("A handoff channel changed its physical binding")
        if any(row.get(key) != trace.get(key) for key in observed):
            raise ValueError("A handoff channel changed its observed output identity")


async def validate_b_handoff(path, reader=None):
    """Re-read frozen output and physical checks without connecting to PSCAD."""
    validators = {name: _file_identity(file) for name, file in (
        ("handoff", __file__), ("fault_channels", read_fault_output_dataset.__code__.co_filename),
        ("template_native", evaluate_template_native_dc_fault.__code__.co_filename),
        ("steady_gate", _steady.__code__.co_filename), ("output_reader", PscadAdapter.read_psout.__code__.co_filename),
    )}
    file = _file_identity(path)
    handoff, _ = _load_ref(file)
    if handoff.get("schema_version") != 1 or handoff.get("scope") != "template_native_dc_fault":
        raise ValueError("The B handoff has an unsupported scope or schema")
    report, report_ref = _load_ref(handoff["evidence"]["acceptance_report"])
    if report.get("status") != "PASS" or report.get("scope") != "steady_and_dc_fault_recovery" or report.get("owned_process_cleaned") is not True:
        raise ValueError("B has not completed native steady and fault acceptance")
    if report.get("error") or not re.fullmatch(r"[0-9a-f]{40}", str(report.get("commit", ""))) or handoff.get("producer_revision") != report["commit"]:
        raise ValueError("B has no consistent completed producer revision")
    _verify_owned_runtime(report)
    if report["runtime"].get("licensed") is not True:
        raise ValueError("B has no licensed runtime evidence")
    root = Path(report_ref["path"]).parent
    if Path(report["root"]).resolve() != root:
        raise ValueError("The native report belongs to another run directory")
    checks = default_fault_checks()
    if handoff.get("required_checks") != checks or report.get("checks_contract") != checks:
        raise ValueError("B acceptance does not use the fixed physical checks")
    sources = handoff["source_hashes"]
    if set(sources) != {"project", "library", "master"} or sources != report["source_hashes"] or sources != report["source_hashes_after"]:
        raise ValueError("The original B sources changed")
    for ref in sources.values():
        _check_ref(ref)
    recipe = handoff["recipe"]
    _verify_producers(recipe, report)
    _verify_support(report, root)
    cases = {item["case"]: item for item in report["cases"]}
    if set(cases) != {"steady", "fault"} or len(report["cases"]) != 2:
        raise ValueError("Both native cases must be unique and complete")
    if reader is None:
        reader = PscadAdapter(None).read_psout
    summaries = {}
    for name, case in cases.items():
        if case.get("status") != "PASS" or case.get("recipe_id") != recipe["id"]:
            raise ValueError("A native case did not pass with the declared recipe")
        evidence = handoff["evidence"]["steady" if name == "steady" else "dc_fault"]
        saved_case, _ = _load_ref(evidence["case_report"], Path(case["project"]).parent / "report.json", within=root)
        if saved_case != case:
            raise ValueError("The inner and outer native case reports differ")
        contract, _ = _load_ref(evidence["channel_contract"], case["channel_contract_path"], within=root)
        index, _ = _load_ref(evidence["output_index"], case["output_index_path"], within=root)
        archived, _ = _load_ref(evidence["samples"], case["samples_path"], within=root)
        for field in ("channel_contract", "output_index", "samples"):
            if evidence[field]["sha256"] != case[field + "_sha256"]:
                raise ValueError("A handoff reference differs from its recorded case")
        project = _check_ref(evidence["project"], case["project"], within=root)
        if project["sha256"] != contract["instrumented_project_sha256"] or project["sha256"] != case["readback"]["project_sha256"]:
            raise ValueError("The finalized native model identity differs")
        if contract.get("required_checks") != checks or archived.get("identity") != index:
            raise ValueError("Native samples and frozen checks are inconsistent")
        if contract["source_hashes"]["master"] != sources["master"]:
            raise ValueError("Native instrumentation used another Master")
        library = _check_ref(contract["source_hashes"]["library"], within=root)
        if library["sha256"] != sources["library"]["sha256"]:
            raise ValueError("Native instrumentation used another library")
        _verify_lineage(case, contract, root)
        verify_fault_instrumentation(project["path"], contract)
        verify_output_dataset(index)
        case_root = Path(project["path"]).parent
        if Path(index["primary"]).name != Path(project["path"]).stem + "_01.out" or index["started_after"] != case["started_after"]:
            raise ValueError("The frozen output does not belong to this native case run")
        for ref in index["files"].values():
            _check_ref(ref, within=case_root)
        settings = case["settings"]
        for key, expected in (("time_duration", checks["simulation_duration_s"]), ("time_step", 1e6 * checks["time_step_s"]), ("sample_step", 1e6 * checks["output_step_s"])):
            if float(settings[key]) != expected:
                raise ValueError("Native simulation settings differ from the checks")
        if str(settings.get("StartType")) != "0" or settings.get("startup_filename") != "" or str(settings.get("PlotType")) != "1" or settings.get("output_filename") != Path(project["path"]).stem + ".out":
            raise ValueError("Native acceptance must use the recorded cold start and output")
        fresh = await read_fault_output_dataset(reader, index["primary"], contract, started_after=index["started_after"])
        if fresh != archived:
            raise ValueError("Archived samples differ from the actual complete output")
        _verify_pi(fresh, recipe, checks)
        result = _steady(fresh, contract, checks) if name == "steady" else evaluate_template_native_dc_fault(fresh, channel_contract=contract, checks_contract=checks, fault_current_limit_ka=checks["fault_current_limit_ka"])
        if result.get("verdict") != "PASS":
            raise ValueError("Re-evaluation of the native " + name + " evidence did not pass")
        if name == "fault":
            if handoff["instrumented_project_sha256"] != project["sha256"]:
                raise ValueError("Handoff does not identify the final fault project")
            _verify_channel_handoff(handoff["channels"], contract, fresh)
        verify_output_dataset(index)
        for ref in evidence.values():
            _check_ref(ref, within=root)
        summaries[name] = {"verdict": result["verdict"], "channel_count": len(fresh["channels"]), "project": project, "output_index": evidence["output_index"]}
    _check_ref(file)
    _check_ref(report_ref)
    for ref in sources.values():
        _check_ref(ref)
    _verify_producers(recipe, report)
    _verify_support(report, root)
    for ref in validators.values():
        _check_ref(ref)
    return {"file": file, "recipe": copy.deepcopy(recipe), "source_hashes": copy.deepcopy(sources), "handoff": handoff,
            "producer_revision": report["commit"], "acceptance_report": report_ref, "cases": summaries,
            "verification_code_hashes": validators}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(str(args.output))
    result = {"status": "FAIL", "scope": "static_b_handoff_validation"}
    try:
        result.update(asyncio.run(validate_b_handoff(args.handoff)))
        result["status"] = "PASS"
    except Exception as error:  # noqa: BLE001 - retain failed static verification as evidence
        result["error"] = {"type": type(error).__name__, "message": str(error)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "report": str(args.output.resolve()), "error": result.get("error")}))
    raise SystemExit(0 if result["status"] == "PASS" else 1)
