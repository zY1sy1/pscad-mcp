"""Offline preparation and same-dataset gate for the joint MMC case.

This harness intentionally has no licensed-run entry point. The fault model
must first have fresh physical acceptance before joint simulation is enabled.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from pscad_mcp.hvdc.builders.mmc import (
    blank_service,
    fault_channels,
    line_constants,
    template_native,
    timed_control,
)
from pscad_mcp.hvdc.builders.mmc.blank_service import (
    BlankMmcBuilderService,
    _copy_frozen,
    _identity,
    _materialize_native_mmc_case,
    _stage_dependencies,
    _verify_copies,
    _verify_plan_inputs,
    _write_evidence,
    json_bytes,
)
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    default_fault_checks,
    finalize_fault_instrumentation,
    reachable_instances,
    read_fault_output_dataset,
    verify_fault_instrumentation,
    verify_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.native_fault_replay import _verify_replay_saved_model
from pscad_mcp.hvdc.builders.mmc.template_audit import (
    audit_mmc_template,
    discover_official_mmc_template,
)
from pscad_mcp.hvdc.builders.mmc.template_native import (
    evaluate_template_native_dc_fault,
)


def _digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def read_a_handoff(path, public_plan):
    identity = _identity(Path(path))
    handoff = json.loads(Path(identity["path"]).read_text(encoding="utf-8"))
    canonical = timed_control.schedule_sha256(handoff)
    if canonical != handoff.get("schedule_sha256"):
        raise ValueError(
            "The formal A handoff has an inconsistent canonical schedule hash"
        )
    expected_sources = copy.deepcopy(public_plan["source_identities"])
    expected_sources.update(
        {
            "compiler_support:" + item["relative_path"]: {
                "path": item["path"],
                "sha256": item["sha256"],
            }
            for item in public_plan["compiler_support"]["files"]
        }
    )
    for name, expected in expected_sources.items():
        claimed = handoff["source_hashes"].get(name)
        if (
            not claimed
            or claimed["sha256"] != expected["sha256"]
            or Path(claimed["path"]).resolve() != Path(expected["path"]).resolve()
            or _identity(Path(claimed["path"])) != expected
        ):
            raise ValueError("The A handoff original source identity differs: " + name)
    if (
        handoff.get("supported_scope", {}).get("role") != "control_command"
        or len(handoff["events"]) != 1
        or len(handoff["event_channels"]) != 1
        or handoff["event_channels"][0]["role"] != "control_command"
    ):
        raise ValueError(
            "The formal A handoff does not identify the supported control-command scope"
        )
    if _identity(Path(identity["path"])) != identity:
        raise ValueError("The formal A handoff changed while reading")
    return {
        "file": identity,
        "canonical_schedule_sha256": canonical,
        "producer_revision": handoff["producer_revision"],
        "original_source_identities": expected_sources,
        "timing": {
            key: handoff[key]
            for key in (
                "time_step_s",
                "output_step_s",
                "duration_s",
                "max_timing_error_s",
            )
        },
        "event": copy.deepcopy(handoff["events"][0]),
        "role": "control_command",
    }


def _rebind_fault_contract(contract, schedule, project):
    expected = timed_control._render(schedule, project.stem)
    if ET.canonicalize(
        ET.tostring(expected, encoding="unicode"), strip_text=True
    ) != ET.canonicalize(project.read_text(encoding="utf-8"), strip_text=True):
        raise ValueError("Joint model differs from the deterministic scheduled source")
    old_namespace = ET.parse(schedule["scenario_source"]["path"]).getroot().get("name")

    def rebind(value):
        if isinstance(value, dict):
            return {key: rebind(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebind(item) for item in value]
        if isinstance(value, str) and value.startswith(old_namespace + ":"):
            return project.stem + value[len(old_namespace) :]
        return value

    result = rebind(copy.deepcopy(contract))
    result.update(
        {
            "project_path": str(project),
            "vendor_finalized": False,
            "instrumented_project_sha256": _identity(project)["sha256"],
            "reachable_instances": reachable_instances(expected),
            "joint_parent_contract_sha256": _digest(contract),
            "joint_schedule_sha256": schedule["schedule_sha256"],
            "required_checks": default_fault_checks(),
        }
    )
    result["readback"] = verify_fault_instrumentation(project, result)
    return result


async def prepare_joint_case(
    workspace, *, source=None, library=None, master=None, a_handoff=None, model_recipe="raw"
):
    root = Path(workspace).resolve()
    if root.exists():
        raise FileExistsError(str(root))
    if source is None or library is None:
        if source is not None or library is not None:
            raise ValueError("Source project and library must be supplied together")
        source, library = discover_official_mmc_template()
    master = Path(master or "C:/Program Files (x86)/PSCAD46/master.pslx").resolve()
    service = BlankMmcBuilderService(None, workspace_root=root)
    public_plan = service.plan_model(
        {
            "project_name": "JointFaultCase",
            "template_path": str(source),
            "library_path": str(library),
            "parameterization": {"master_path": str(master), "model_recipe": model_recipe},
        }
    )
    a_handoff = (
        a_handoff
        or Path(__file__).resolve().parents[1]
        / "docs"
        / "acceptance"
        / "emt-timed-control"
        / "schedule-handoff.json"
    )
    parent_a = read_a_handoff(a_handoff, public_plan)
    root.mkdir(parents=True)
    bundle = root / "JointFaultCase.bundle"
    bundle.mkdir()
    preparation = {
        "schema_version": 1,
        "scope": "offline_joint_contract",
        "status": "FAIL",
        "physical_acceptance_verified": False,
        "public_plan": public_plan,
        "checks": default_fault_checks(),
        "lineage": [],
        "joint_parents": {
            "A": parent_a,
            "B": {
                "accepted": False,
                "handoff_status": "pending",
                "required_handoff": "accepted channels-handoff.json with exact model recipe and source/output hashes",
                "current_offline_recipe": public_plan["model_recipe"],
                "model_corrections": public_plan["model_corrections"],
            },
        },
    }
    try:
        staged, staged_library = await _stage_dependencies(
            public_plan, root, bundle, preparation
        )
        instrumented = root / "FaultInstrumented.pscx"
        parent = _materialize_native_mmc_case(public_plan, staged, staged_library, root, instrumented, preparation)
        recipe_source = Path(parent["source_hashes"]["project"]["path"])
        preparation["lineage"].append(
            {
                "stage": "fault_instrumentation",
                "source": str(recipe_source),
                "source_sha256": _identity(recipe_source)["sha256"],
                "destination": str(instrumented),
                "destination_sha256": _identity(instrumented)["sha256"],
                "channel_contract_sha256": _digest(parent),
            }
        )
        event = {
            **{
                key: copy.deepcopy(value)
                for key, value in parent_a["event"].items()
                if key != "event_selector"
            },
            "event_id": "t2_active_power_command",
            "time_s": 1.0,
            "end_time_s": 1.2,
        }
        sources = {
            **public_plan["source_identities"],
            "fault_instrumented": _identity(instrumented),
            "fault_recipe_source": _identity(recipe_source),
            "a_schedule_handoff": parent_a["file"],
        }
        schedule = timed_control.plan_embedded_control(
            instrumented,
            [event],
            master_path=master,
            time_step_s=25e-6,
            output_step_s=250e-6,
            duration_s=5.0,
            max_timing_error_s=500e-6,
            source_hashes=sources,
        )
        project = root / "JointFaultCase.pscx"
        embedded = timed_control.materialize_embedded_control(schedule, project)
        contract = _rebind_fault_contract(parent, schedule, project)
        snapshot = root / "prepared-bytes" / project.name
        _copy_frozen(project, snapshot, _identity(project)["sha256"])
        preparation["dependency_copies"].append(
            _copy_frozen(
                Path(parent_a["file"]["path"]),
                bundle / "evidence" / "a-schedule-handoff.json",
                parent_a["file"]["sha256"],
            )
        )
        preparation["lineage"].append(
            {
                "stage": "embedded_control",
                "source": str(instrumented),
                "source_sha256": _identity(instrumented)["sha256"],
                "destination": str(project),
                "destination_sha256": _identity(project)["sha256"],
                "schedule_sha256": schedule["schedule_sha256"],
            }
        )
        preparation.update(
            {
                "project": _identity(project),
                "prepared_snapshot": _identity(snapshot),
                "parent_fault_contract": parent,
                "fault_contract": contract,
                "schedule": schedule,
                "schedule_derivation": {
                    "parent_schedule_sha256": parent_a["canonical_schedule_sha256"],
                    "parent_handoff_sha256": parent_a["file"]["sha256"],
                    "preserved_fields": [
                        "target",
                        "before_value",
                        "value",
                        "after_value",
                        "units",
                    ],
                    "joint_event_window_s": [1.0, 1.2],
                    "joint_timing": {
                        key: schedule[key]
                        for key in (
                            "time_step_s",
                            "output_step_s",
                            "duration_s",
                            "max_timing_error_s",
                        )
                    },
                    "inherited_physical_acceptance": False,
                },
                "timing_readback": embedded["readback"],
                "checks_sha256": _digest(preparation["checks"]),
                "status": "PASS",
                "code_identities": [
                    _identity(Path(module.__file__))
                    for module in (
                        blank_service,
                        fault_channels,
                        line_constants,
                        template_native,
                        timed_control,
                    )
                ]
                + [_identity(Path(__file__))],
            }
        )
        preparation["preparation_sha256"] = _digest(preparation)
        verify_joint_preparation(preparation)
        _write_evidence(bundle / "evidence" / "joint-fault-channels.json", contract)
        _write_evidence(bundle / "evidence" / "schedule.json", schedule)
        _write_evidence(root / "preparation.json", preparation)
        return preparation
    except BaseException as error:
        preparation.update(
            {
                "status": "FAIL",
                "error": {"type": type(error).__name__, "message": str(error)},
            }
        )
        _write_evidence(root / "preparation.json", preparation)
        raise


def verify_joint_preparation(preparation, *, saved_fault_contract=None):
    if _digest(
        {
            key: value
            for key, value in preparation.items()
            if key != "preparation_sha256"
        }
    ) != preparation.get("preparation_sha256"):
        raise ValueError("The immutable joint preparation changed")
    if preparation["checks"] != default_fault_checks() or preparation[
        "checks_sha256"
    ] != _digest(preparation["checks"]):
        raise ValueError("Joint physical checks differ from the production contract")
    _verify_plan_inputs(preparation["public_plan"], audit_mmc_template)
    parent_a = read_a_handoff(
        preparation["joint_parents"]["A"]["file"]["path"], preparation["public_plan"]
    )
    if (
        parent_a != preparation["joint_parents"]["A"]
        or preparation["schedule"]["source_hashes"]["a_schedule_handoff"]
        != parent_a["file"]
    ):
        raise ValueError(
            "Joint planning no longer identifies the formal A parent handoff"
        )
    _verify_copies(preparation["dependency_copies"])
    for item in [preparation["prepared_snapshot"], *preparation["code_identities"]]:
        if _identity(Path(item["path"])) != item:
            raise ValueError("A frozen joint code or model input changed")
    project = Path(preparation["project"]["path"])
    contract = saved_fault_contract or preparation["fault_contract"]
    if saved_fault_contract is None and _identity(project) != preparation["project"]:
        raise ValueError("The prepared joint model changed")
    if saved_fault_contract is not None:
        if (
            contract.get("vendor_finalized") is not True
            or contract.get("joint_schedule_sha256")
            != preparation["schedule"]["schedule_sha256"]
        ):
            raise ValueError("Joint run has no finalized saved model contract")
        _verify_replay_saved_model(
            Path(preparation["prepared_snapshot"]["path"]), project, contract
        )
        if (
            finalize_fault_instrumentation(project, preparation["fault_contract"])
            != contract
        ):
            raise ValueError(
                "The saved joint channel contract differs from its prepared parent"
            )
    for stage in preparation["lineage"]:
        for label in ("source", "destination"):
            if (
                saved_fault_contract is not None
                and label == "destination"
                and stage["stage"] == "embedded_control"
            ):
                continue
            if _identity(Path(stage[label]))["sha256"] != stage[label + "_sha256"]:
                raise ValueError("An intermediate joint model changed")
    timed_control.verify_embedded_control(preparation["schedule"], project)
    verify_fault_instrumentation(project, contract)
    if contract["joint_parent_contract_sha256"] != _digest(
        preparation["parent_fault_contract"]
    ):
        raise ValueError(
            "Joint instrumentation does not identify its original fault contract"
        )
    return True


def require_same_dataset(manifest, event_evidence):
    entries = [
        item
        for item in event_evidence["output_evidence"]["files"]
        if item["kind"] != "project"
    ]
    observed = {
        Path(item["path"]).name: {
            "path": item["path"],
            "sha256": item["sha256"],
            "size": item["size_bytes"],
            "mtime_ns": item["mtime_ns"],
        }
        for item in entries
    }
    if len(entries) != len(manifest["files"]) or observed != manifest["files"]:
        raise ValueError(
            "Timing and fault evidence do not share the identical complete dataset"
        )
    return True


async def evaluate_joint_dataset(
    preparation, reader, saved_fault_contract, output_identity
):
    """Evaluate one frozen run; owned execution/reload remain separate gates."""
    project = Path(preparation["project"]["path"])
    report = {
        "schema_version": 1,
        "scope": "joint_dataset_evaluation",
        "verdict": "INCOMPLETE_ANALYSIS",
        "physical_acceptance_verified": False,
        "preparation_sha256": preparation["preparation_sha256"],
        "schedule_sha256": preparation["schedule"]["schedule_sha256"],
        "checks_sha256": preparation["checks_sha256"],
        "saved_fault_contract_sha256": _digest(saved_fault_contract),
        "output_identity": output_identity,
        "remaining_acceptance": [
            "fresh_accepted_fault_model",
            "owned_joint_execution",
            "independent_joint_replay",
            "owned_process_cleanup",
        ],
    }
    try:
        verify_joint_preparation(preparation, saved_fault_contract=saved_fault_contract)
        verify_output_dataset(output_identity)
        started = output_identity["started_after"]
        samples = await read_fault_output_dataset(
            reader,
            output_identity["primary"],
            saved_fault_contract,
            started_after=started,
        )
        if samples["identity"] != output_identity:
            raise ValueError("Fault reading changed the frozen joint dataset")
        report["timing"] = timed_control.read_event_evidence(
            preparation["schedule"],
            project,
            [
                item["path"]
                for name, item in output_identity["files"].items()
                if name.casefold().endswith(".out")
            ],
            started_after=started,
        )
        require_same_dataset(output_identity, report["timing"])
        report["fault"] = evaluate_template_native_dc_fault(
            samples,
            channel_contract=saved_fault_contract,
            checks_contract=preparation["checks"],
            fault_current_limit_ka=preparation["checks"]["fault_current_limit_ka"],
        )
        verify_output_dataset(output_identity)
        verify_joint_preparation(preparation, saved_fault_contract=saved_fault_contract)
        report["verdict"] = report["fault"]["verdict"]
    except BaseException as error:  # noqa: BLE001 - preserve interrupted analysis without claiming acceptance
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    report["report_path"] = str(
        project.parent / "joint-analysis" / (uuid4().hex + ".json")
    )
    report["report_sha256"] = _write_evidence(Path(report["report_path"]), report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--model-recipe", choices=tuple(blank_service._MODEL_RECIPES), default="raw")
    args = parser.parse_args()
    result = asyncio.run(prepare_joint_case(args.workspace, model_recipe=args.model_recipe))
    print(
        json.dumps(
            {
                "scope": result["scope"],
                "status": result["status"],
                "physical_acceptance_verified": False,
                "preparation": str(args.workspace.resolve() / "preparation.json"),
                "preparation_sha256": result["preparation_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
