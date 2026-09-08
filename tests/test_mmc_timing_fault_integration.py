"""Offline joint-contract checks; these do not establish electrical acceptance."""

import asyncio
import copy
import importlib
import json
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.fault_channels import (
    default_fault_checks,
    finalize_fault_instrumentation,
    snapshot_output_dataset,
)
from pscad_mcp.hvdc.builders.mmc.template_audit import discover_official_mmc_template


def _harness():
    spec = importlib.util.find_spec("tests.mmc_timing_fault_case")
    assert spec is not None, "Joint timing/fault harness is missing"
    return importlib.import_module(spec.name)


@pytest.fixture(scope="module")
def joint_case(tmp_path_factory):
    master = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
    if not master.is_file():
        pytest.skip("Installed Master metadata is unavailable")
    try:
        source, library = discover_official_mmc_template()
    except BackendError:
        pytest.skip("Installed official MMC metadata is unavailable")
    root = tmp_path_factory.mktemp("joint_contract") / "case"
    return asyncio.run(
        _harness().prepare_joint_case(
            root, source=source, library=library, master=master
        )
    )


def test_joint_preparation_preserves_originals_and_separates_command_from_fault(
    joint_case,
):
    harness = _harness()
    harness.verify_joint_preparation(joint_case)
    assert joint_case["scope"] == "offline_joint_contract"
    assert joint_case["physical_acceptance_verified"] is False
    assert joint_case["checks"] == default_fault_checks()
    schedule = joint_case["schedule"]
    assert (
        schedule["time_step_s"],
        schedule["output_step_s"],
        schedule["max_timing_error_s"],
    ) == (25e-6, 250e-6, 500e-6)
    assert schedule["event_channels"][0]["role"] == "control_command"
    assert schedule["events"][0]["time_s"] == 1.0
    assert schedule["events"][0]["end_time_s"] == 1.2
    fault = joint_case["fault_contract"]
    assert any(channel["role"] == "fault_active" for channel in fault["channels"])
    assert not any(
        channel["role"] == "control_command" for channel in fault["channels"]
    )
    assert fault["joint_schedule_sha256"] == schedule["schedule_sha256"]
    assert joint_case["lineage"][-1]["stage"] == "embedded_control"
    assert joint_case["lineage"][-2]["stage"] == "fault_instrumentation"


def test_joint_preparation_does_not_authorize_schedule_drift(joint_case):
    changed = copy.deepcopy(joint_case)
    changed["schedule"]["events"][0]["time_s"] = 2.5
    with pytest.raises((BackendError, ValueError)):
        _harness().verify_joint_preparation(changed)


def test_joint_contract_pins_formal_a_handoff_and_new_sampling_derivation(joint_case):
    parent = joint_case["joint_parents"]["A"]
    assert (
        parent["canonical_schedule_sha256"]
        == "5f799315640b6760c86f345b3ce791d77301ab2b6cc832a96ca25ad036f5e917"
    )
    assert parent["file"]["sha256"]
    assert (
        joint_case["schedule"]["source_hashes"]["a_schedule_handoff"] == parent["file"]
    )
    assert (
        joint_case["schedule_derivation"]["parent_schedule_sha256"]
        == parent["canonical_schedule_sha256"]
    )
    assert parent["timing"]["max_timing_error_s"] == 20e-6
    assert joint_case["schedule"]["max_timing_error_s"] == 500e-6
    assert joint_case["joint_parents"]["B"]["accepted"] is False


@pytest.mark.parametrize("changed", ["canonical", "master", "project", "library"])
def test_joint_formal_handoff_rejects_inconsistent_original_identity(
    tmp_path, joint_case, changed
):
    path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "acceptance"
        / "emt-timed-control"
        / "schedule-handoff.json"
    )
    value = json.loads(path.read_text())
    if changed == "canonical":
        value["schedule_sha256"] = "0" * 64
    else:
        value["source_hashes"][changed]["sha256"] = "0" * 64
        value["schedule_sha256"] = _harness().timed_control.schedule_sha256(value)
    altered = tmp_path / "altered-handoff.json"
    altered.write_text(json.dumps(value))
    assert callable(getattr(_harness(), "read_a_handoff", None))
    with pytest.raises((BackendError, ValueError)):
        _harness().read_a_handoff(altered, joint_case["public_plan"])


def test_joint_finalized_contract_cannot_relabel_a_fault_channel_as_a_command(
    joint_case,
):
    saved = finalize_fault_instrumentation(
        joint_case["project"]["path"], joint_case["fault_contract"]
    )
    saved["channels"][0]["role"] = "control_command"
    with pytest.raises((BackendError, ValueError)):
        _harness().verify_joint_preparation(joint_case, saved_fault_contract=saved)


def test_joint_readback_rejects_a_changed_physical_probe(tmp_path, joint_case):
    target = tmp_path / "changed.pscx"
    target.write_bytes(Path(joint_case["project"]["path"]).read_bytes())
    contract = copy.deepcopy(joint_case["fault_contract"])
    probe = contract["readback_components"][0]
    tree = ET.parse(target)
    owner = tree.find(
        f"./definitions/Definition[@name='{probe['definition_name']}']/schematic/User[@id='{probe['owner_id']}']"
    )
    owner.set("x", str(int(owner.get("x", "0")) + 18))
    tree.write(target)
    with pytest.raises(BackendError):
        _harness().verify_fault_instrumentation(target, contract)


@pytest.mark.parametrize("changed", [None, "path", "sha256", "extra"])
def test_joint_gate_requires_the_identical_complete_dataset(changed):
    manifest = {
        "primary": "C:/run/Joint_01.out",
        "files": {
            "Joint_01.out": {
                "path": "C:/run/Joint_01.out",
                "sha256": "a" * 64,
                "size": 40,
                "mtime_ns": 123,
            },
            "Joint.inf": {
                "path": "C:/run/Joint.inf",
                "sha256": "b" * 64,
                "size": 50,
                "mtime_ns": 124,
            },
            "Joint.infx": {
                "path": "C:/run/Joint.infx",
                "sha256": "c" * 64,
                "size": 60,
                "mtime_ns": 125,
            },
        },
    }
    event_evidence = {
        "output_evidence": {
            "files": [
                {
                    "kind": Path(name).suffix[1:].upper(),
                    "path": value["path"],
                    "sha256": value["sha256"],
                    "size_bytes": value["size"],
                    "mtime_ns": value["mtime_ns"],
                }
                for name, value in manifest["files"].items()
            ]
        }
    }
    if changed == "extra":
        event_evidence["output_evidence"]["files"].append(
            {
                "kind": "OUT",
                "path": "C:/other/Joint_02.out",
                "sha256": "d" * 64,
                "size_bytes": 1,
                "mtime_ns": 1,
            }
        )
    elif changed:
        event_evidence["output_evidence"]["files"][0][changed] = "changed"
    if changed:
        with pytest.raises(ValueError, match="dataset"):
            _harness().require_same_dataset(manifest, event_evidence)
    else:
        assert _harness().require_same_dataset(manifest, event_evidence) is True


@pytest.mark.parametrize(
    ("fault_verdict", "changed_dataset"),
    [("PASS", False), ("FAIL", False), ("PASS", True)],
)
def test_joint_dataset_gate_preserves_physical_failures_and_identity_mismatches(
    tmp_path, monkeypatch, joint_case, fault_verdict, changed_dataset
):
    harness = _harness()
    saved = finalize_fault_instrumentation(
        joint_case["project"]["path"], joint_case["fault_contract"]
    )
    started = time.time() - 1
    output = tmp_path / "JointFaultCase_01.out"
    output.write_text("0 0\n5 0\n")
    (tmp_path / "JointFaultCase.inf").write_text("metadata")
    (tmp_path / "JointFaultCase.infx").write_text("compiler metadata")
    identity = snapshot_output_dataset(output, started_after=started)
    timing = {
        "measured_events": [{"event_id": "t2_active_power_command"}],
        "output_evidence": {
            "files": [
                {
                    "kind": Path(name).suffix[1:].upper(),
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "size_bytes": item["size"],
                    "mtime_ns": item["mtime_ns"],
                }
                for name, item in identity["files"].items()
            ]
        },
    }
    if changed_dataset:
        timing["output_evidence"]["files"][0]["sha256"] = "0" * 64

    async def read(*args, **kwargs):
        return {
            "identity": identity,
            "channels": [],
            "checks_contract": {"fault_current_limit_ka": 99999},
        }

    def evaluate(samples, *, channel_contract, checks_contract, fault_current_limit_ka):
        assert channel_contract == saved
        assert checks_contract == default_fault_checks()
        assert fault_current_limit_ka == 20.0
        return {"verdict": fault_verdict}

    monkeypatch.setattr(harness, "read_fault_output_dataset", read)
    monkeypatch.setattr(
        harness.timed_control, "read_event_evidence", lambda *args, **kwargs: timing
    )
    monkeypatch.setattr(harness, "evaluate_template_native_dc_fault", evaluate)
    result = asyncio.run(
        harness.evaluate_joint_dataset(joint_case, None, saved, identity)
    )
    assert result["verdict"] == (
        "INCOMPLETE_ANALYSIS" if changed_dataset else fault_verdict
    )
    assert result["physical_acceptance_verified"] is False
    assert Path(result["report_path"]).is_file()
    assert (
        json.loads(Path(result["report_path"]).read_text())["verdict"]
        == result["verdict"]
    )
