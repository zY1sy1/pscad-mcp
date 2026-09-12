from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc import blank_service
from pscad_mcp.hvdc.builders.mmc.blank import BlankMmcRequest
from pscad_mcp.hvdc.builders.mmc.blank_service import BlankMmcBuilderService
from pscad_mcp.hvdc.builders.mmc.fault_channels import default_fault_checks
from tests.test_mmc_template_native import _template as _native_template


def _audit(topology: str, template_path=None, library_path=None) -> dict[str, object]:
    return {
        "compatible": True,
        "pscad_version": "4.6.2",
        "source_hashes": {"project": hashlib.sha256(Path(template_path).read_bytes()).hexdigest() if template_path else "a" * 64,
                          "library": hashlib.sha256(Path(library_path).read_bytes()).hexdigest() if library_path else "b" * 64},
        "definitions": ["project:Main", "intermediate:FullCellR_n"],
        "absolute_paths": [],
        "compiler_support": {"required": False, "present": True, "hashes": {}},
        "template_native_controls": {"available": True, "time_basis": "EMTDC"},
        "submodule_topology": {"declared": topology, "full_cell_instances": 4, "firing_hbridge_instances": 3},
    }


@pytest.fixture(autouse=True)
def synthetic_master(tmp_path, monkeypatch):
    master = tmp_path / "master.pslx"
    master.write_text('<project name="master" Target="Library" synthetic="true"><definitions /></project>', encoding="ascii")
    monkeypatch.setattr(blank_service, "_default_master_path", lambda: master, raising=False)
    return master


def _plan_case(tmp_path, *, parameterization=None, audit_change=None):
    source = tmp_path / "source.pscx"
    library = tmp_path / "intermediate.pslx"
    source.write_text('<project name="source" Target="EMTDC" version="4.6.2"><definitions /></project>')
    library.write_text('<project name="intermediate" Target="Library"><definitions /></project>')

    def audit(*paths):
        result = _audit("full_bridge", *paths)
        if audit_change:
            audit_change(result)
        return result

    builder = BlankMmcBuilderService(None, workspace_root=tmp_path / "workspace", audit_loader=audit)
    request = BlankMmcRequest(project_name="MMC_CASE", template_path=str(source), library_path=str(library), parameterization=parameterization)
    return builder, request, source, library


def test_public_plan_uses_frozen_production_windows_and_raw_recipe(tmp_path, synthetic_master):
    service, request, *_ = _plan_case(tmp_path)
    plan = service.plan_model(request)
    assert plan["settings"] == {"simulation_duration_s": 5.0, "time_step_s": 25e-6, "output_step_s": 250e-6, "output_enabled": True}
    assert plan["fault"] == {"kind": "dc_pole_to_pole", "time_s": 2.5, "removal_time_s": 2.7}
    assert plan["checks_contract"] == default_fault_checks()
    assert plan["model_recipe"]["name"] == "raw"
    assert plan["model_recipe"]["physical_acceptance_verified"] is False
    assert plan["source_identities"]["master"]["sha256"] == hashlib.sha256(synthetic_master.read_bytes()).hexdigest()
    assert not (tmp_path / "workspace").exists()


@pytest.mark.parametrize("duration", [1.3, 4.99])
def test_public_plan_rejects_explicit_duration_that_misses_recovery(tmp_path, duration):
    service, request, *_ = _plan_case(tmp_path)
    with pytest.raises(BackendError, match="window"):
        service.plan_model(request, simulation_duration_s=duration)
    with pytest.raises(BackendError, match="window"):
        service.plan_model({**request.to_dict(), "simulation_duration_s": duration})
    assert not (tmp_path / "workspace").exists()


def test_public_plan_preserves_explicit_long_duration_without_changing_checks(tmp_path):
    service, request, *_ = _plan_case(tmp_path)
    plan = service.plan_model(request, simulation_duration_s=5.5)
    assert plan["settings"]["simulation_duration_s"] == 5.5
    assert plan["checks_contract"] == default_fault_checks()


@pytest.mark.parametrize("parameters", [{"model_recipe": "unknown"}, {"fault_current_limit_ka": 9999}, {"model_recipe": {"current_limit_pu": 3}}])
def test_public_plan_rejects_unrecognized_recipe_or_threshold_override(tmp_path, parameters):
    service, request, *_ = _plan_case(tmp_path, parameterization=parameters)
    with pytest.raises(BackendError):
        service.plan_model(request)


def test_public_plan_pins_compiler_support_before_any_copy(tmp_path):
    support = tmp_path / "lib" / "gf42" / "intermediate.lib"
    support.parent.mkdir(parents=True)
    support.write_bytes(b"synthetic compiler library")
    item = {"path": str(support.resolve()), "relative_path": "lib/gf42/intermediate.lib", "sha256": hashlib.sha256(support.read_bytes()).hexdigest()}
    service, request, *_ = _plan_case(tmp_path, audit_change=lambda audit: audit["compiler_support"].update(files=[item]))
    plan = service.plan_model(request)
    assert plan["compiler_support"]["files"] == [item]
    support.write_bytes(b"changed")
    with pytest.raises(BackendError):
        service.plan_model(request)


def test_public_plan_rejects_a_stale_audit_source_hash(tmp_path):
    service, request, *_ = _plan_case(tmp_path, audit_change=lambda audit: audit["source_hashes"].update(project="0" * 64))
    with pytest.raises(BackendError):
        service.plan_model(request)


@pytest.mark.parametrize("names", [["TL12A", "tl12a"], ["CON"], ["nul"], ["COM1"]])
def test_public_plan_rejects_windows_ambiguous_line_names(tmp_path, synthetic_master, monkeypatch, names):
    service, request, source, _library = _plan_case(tmp_path)
    source.write_text('<project name="source"><Wire classid="TLine" /></project>')
    executable = synthetic_master.parent / "bin" / "win" / "tline.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic executable; never executed")
    monkeypatch.setattr(blank_service, "extract_tline_segments", lambda _source: [SimpleNamespace(name=name) for name in names])
    monkeypatch.setattr(blank_service, "render_tli", lambda segment: "input " + segment.name)
    with pytest.raises(BackendError):
        service.plan_model(request)


@pytest.mark.parametrize("change", [
    {"ratings": {"dc_voltage_kv": 500.0, "power_mw": 2000.0}},
    {"control_profile": "custom_control"},
    {"fault_profile": "custom_fault"},
])
def test_public_plan_does_not_echo_unsupported_custom_requests_as_applied(tmp_path, change):
    service, request, *_ = _plan_case(tmp_path)
    with pytest.raises(BackendError):
        service.plan_model({**request.to_dict(), **change})


def test_public_plan_identifies_legacy_rating_metadata_separately_from_native_model(tmp_path):
    service, request, *_ = _plan_case(tmp_path)
    plan = service.plan_model(request)
    assert plan["request_implementation"]["ratings"]["binding"] == "descriptive_only"
    assert plan["request_implementation"]["supported_native_contract"]["dc_pole_to_pole_voltage_kv"] == 640.0
    assert plan["request_implementation"]["supported_native_contract"]["controlled_terminal_active_power_mw"] == -900.0
    assert plan["request_implementation"]["supported_native_contract"]["observed"] is False
    assert plan["request_implementation"]["template_ratings_observed"] is None


def test_raw_plan_declares_the_verified_t2_binding_correction_separately_from_tuning(tmp_path):
    service, request, *_ = _plan_case(tmp_path)
    plan = service.plan_model(request)
    assert plan["model_recipe"]["name"] == "raw"
    assert plan["model_recipe"]["parameters"] == {}
    assert plan["model_corrections"] == [{"name": "terminal_two_charging", "definition": "Main", "owner": "606940312", "parameter": "T", "before": "Tcharging1", "after": "Tcharging2", "classification": "verified_template_binding_defect"}]


def test_full_sort_recipe_is_explicit_ordered_and_still_requires_fault_acceptance(tmp_path):
    service, request, *_ = _plan_case(tmp_path)
    plan = service.plan_model({**request.to_dict(), "parameterization": {"model_recipe": "native_full_sort_v1"}})
    recipe = plan["model_recipe"]
    assert recipe["physical_acceptance_verified"] is False
    assert recipe["fault_recovery_status"] == "pending"
    assert [step["name"] for step in recipe["steps"]] == ["terminal_two_charging", "voltage_control_headroom", "dc_feedback_filter", "terminal_two_carrier", "arm_virtual_resistance", "complete_arm_sorting", "fault_instrumentation"]
    assert recipe["parameters"] == {"current_limit_pu": 1.1, "dc_feedback_time_constant_s": 0.005, "terminal_two_carrier_ratio": 23.0, "arm_virtual_resistance_ohm": 30.0, "sort_extent": "Dim", "sort_enable": "existing_Enab"}
    assert set(recipe["producer_code_hashes"]) == {"fault_channels", "template_native", "blank_service"}


def test_integral_candidate_has_a_new_recipe_identity_without_changing_full_sort_v1(tmp_path):
    service, request, *_ = _plan_case(tmp_path)
    old = service.plan_model({**request.to_dict(), "parameterization": {"model_recipe": "native_full_sort_v1"}})
    candidate = service.plan_model({**request.to_dict(), "parameterization": {"model_recipe": "native_full_sort_dc_integral_004_v1"}})
    assert "t1_dc_integral_time_s" not in old["model_recipe"]["parameters"]
    assert candidate["model_recipe"]["parameters"]["t1_dc_integral_time_s"] == 0.04
    assert candidate["model_recipe"]["steps"][-2] == {"name": "voltage_control_integral_time", "parameters": {"time_constant_s": 0.04}}
    assert candidate["model_recipe"]["physical_acceptance_verified"] is False
    assert candidate["checks_contract"] == old["checks_contract"] == default_fault_checks()
    assert candidate["plan_hash"] != old["plan_hash"]


@pytest.mark.parametrize("drift", ["changed_producer", "missing_producer"])
def test_recipe_execution_requires_the_frozen_materializer_producer(tmp_path, monkeypatch, drift):
    service, request, *_ = _plan_case(tmp_path)
    plan = service.plan_model(request)
    if drift == "changed_producer":
        original_identity = blank_service._identity

        def observed_identity(path):
            identity = original_identity(path)
            return {**identity, "sha256": "0" * 64} if Path(path).name == "blank_service.py" else identity

        monkeypatch.setattr(blank_service, "_identity", observed_identity)
    else:
        plan["model_recipe"]["producer_code_hashes"].pop("blank_service", None)
        plan["plan_hash"] = hashlib.sha256(blank_service.json_bytes({key: value for key, value in plan.items() if key not in {"plan_hash", "status"}})).hexdigest()
    with pytest.raises(BackendError) as raised:
        blank_service._verify_plan_inputs(plan, service.audit_loader)
    assert raised.value.code == "MMC_PLAN_STALE"


def _protocol_case(tmp_path, monkeypatch, *, verdict="FAIL", bad_master=False, read_error=False):
    """Synthetic protocol fixture; no licensed model acceptance is claimed."""
    service, request, source, library = _plan_case(tmp_path)
    master = blank_service._default_master_path()
    calls = []

    def materialize(origin, destination, **kwargs):
        calls.append("materialize_fault")
        root = ET.parse(origin).getroot()
        root.set("fault_time_s", str(kwargs["dc_fault_time_s"]))
        root.set("fault_duration_s", str(kwargs["fault_duration_s"]))
        ET.ElementTree(root).write(destination)
        return {"source": str(origin), "source_sha256": blank_service._sha256(Path(origin)), "destination": str(destination), "destination_sha256": blank_service._sha256(Path(destination)), "bindings": []}

    def instrument(origin, destination, **kwargs):
        calls.append("instrument")
        root = ET.parse(origin).getroot()
        root.set("name", Path(destination).stem)
        root.set("instrumented", "true")
        ET.ElementTree(root).write(destination)
        return {"schema_version": 1, "project_path": str(destination), "channels": [{"channel_id": "fault_active", "role": "fault_active"}], "diagnostic_channels": [], "readback": {"matched": True, "project_sha256": blank_service._sha256(Path(destination))}}

    def charging(origin, destination):
        calls.append("repair_t2_charging")
        Path(destination).write_bytes(Path(origin).read_bytes())
        return {"source": str(origin), "source_sha256": blank_service._sha256(Path(origin)), "destination": str(destination), "destination_sha256": blank_service._sha256(Path(destination)), "owner": "606940312", "before": "Tcharging1", "after": "Tcharging2"}

    def finalize(project, contract):
        calls.append("finalize")
        return {**contract, "project_path": str(project), "vendor_finalized": True, "instrumented_project_sha256": blank_service._sha256(Path(project)), "readback": {"matched": True, "project_path": str(project), "project_sha256": blank_service._sha256(Path(project))}}

    def verify(project, contract):
        observed = blank_service._sha256(Path(project))
        if observed != contract["readback"]["project_sha256"]:
            raise BackendError("MMC_POSTCONDITION_FAILED", "Fixture saved model drifted", "test", "verify")
        return {"matched": True, "project_path": str(project), "project_sha256": observed}

    async def read(reader, primary, contract, *, started_after):
        calls.append("read")
        indexes = list(Path(primary).parents[1].rglob("output-index.json"))
        assert indexes, "Output snapshot must be persisted before parsing"
        if read_error:
            raise BackendError("MMC_OUTPUT_IDENTITY_CHANGED", "wrong metadata or OUT parts", "test", "read")
        return {"channels": [], "identity": blank_service.snapshot_output_dataset(primary, started_after=started_after), "evidence_kind": "pscad_output", "checks_contract": {"fault_current_limit_ka": 99999}}

    def evaluate(samples, *, checks_contract, channel_contract, fault_current_limit_ka, topology):
        calls.append("evaluate")
        assert checks_contract == default_fault_checks()
        assert fault_current_limit_ka == 20.0
        assert channel_contract["vendor_finalized"] is True
        return {"verdict": verdict, "checks": {"fault_applied": verdict == "PASS"}, "check_results": [{"status": verdict, "expected": 20.0, "observed": 1.0, "source": "synthetic protocol", "window": [2.5, 2.7]}]}

    class Backend:
        def __init__(self):
            self.projects = {}
            self.settings = {}

        async def get_master_library_identity(self):
            calls.append("runtime_master")
            return {"master_path": str(master), "master_sha256": "0" * 64 if bad_master else blank_service._sha256(master), "pscad_version": "4.6.2"}

        async def list_projects(self):
            return [{"name": name, "type": "Case" if path.suffix == ".pscx" else "Library", "filename": str(path)} for name, path in self.projects.items()]

        async def load_projects(self, paths):
            calls.append("load")
            for path in paths:
                self.projects[Path(path).stem] = Path(path)

        async def set_project_settings(self, name, settings):
            assert name in self.projects
            self.settings[name] = dict(settings)

        async def get_project_settings(self, name):
            return self.settings[name]

        async def save_project(self, name, *, confirm):
            calls.append("save")

        async def build_project(self, name):
            calls.append("compile")

        async def get_project_output(self, name, structured=True):
            return []

        async def run_project(self, name):
            calls.append("run")
            project = self.projects[name]
            data = project.parent / (name + ".gf42")
            data.mkdir()
            (data / (name + "_01.out")).write_text("0 0\n5 0\n")
            (data / (name + ".inf")).write_text('PGB(1) Output Desc="fault_active" Group="TEST" Max=1 Min=0 Units="1"\n')
            (data / (name + ".infx")).write_text('<Output device="EMTDC"/>')

        async def get_run_status(self, name):
            return {"status": "completed"}

        async def discover_output_files(self, project, *, started_after, max_files):
            assert Path(project).is_file()
            return [str(path) for path in Path(project).parent.glob(Path(project).stem + ".*/*.out")]

        async def read_output_file(self, *args, **kwargs):
            raise AssertionError("The contract reader boundary must be used")

    async def replay(**kwargs):
        calls.append("replay")
        assert kwargs["checks_contract"] == default_fault_checks()
        assert ET.parse(kwargs["project"]).getroot().get("fault_time_s") == "2.5"
        report_path = Path(kwargs["workspace"]) / "worker" / "report.json"
        result = {"status": "PASS", "project_sha256": blank_service._sha256(Path(kwargs["project"])),
                  "checks_sha256": hashlib.sha256(blank_service.json_bytes(kwargs["checks_contract"])).hexdigest(),
                  "parent_channel_contract_sha256": hashlib.sha256(blank_service.json_bytes(kwargs["channel_contract"])).hexdigest(),
                  "owned_process_cleaned": True, "worker_exit_code": 0}
        blank_service._write_evidence(report_path, result)
        return {**result, "report_path": str(report_path), "report_sha256": blank_service._sha256(report_path),
                "artifacts": {"worker/report.json": {"path": str(report_path), "sha256": blank_service._sha256(report_path)}}}

    for name, callback in {"materialize_template_native_scenario": materialize, "instrument_fault_channels": instrument,
        "materialize_terminal_two_charging": charging,
        "finalize_fault_instrumentation": finalize, "verify_fault_instrumentation": verify,
        "read_fault_output_dataset": read, "evaluate_template_native_dc_fault": evaluate}.items():
        monkeypatch.setattr(blank_service, name, callback, raising=False)
    builder = BlankMmcBuilderService(Backend(), workspace_root=tmp_path / "workspace", audit_loader=service.audit_loader, replay_verifier=replay)
    return builder, request, calls, source, library


@pytest.mark.parametrize("read_error", [False, True])
def test_public_fault_failure_retains_history_frozen_evidence_and_never_publishes(tmp_path, monkeypatch, read_error):
    service, request, calls, source, library = _protocol_case(tmp_path, monkeypatch, read_error=read_error)
    hashes = [blank_service._sha256(path) for path in (source, library)]
    plan = service.plan_model(request)

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        return service.get_build_status(started["build_id"])

    record = asyncio.run(exercise())
    assert record["state"] == "failed"
    assert record["result"]["output_index_sha256"]
    assert record["result"]["channel_contract_sha256"]
    assert len(record["history"]) >= 5
    assert record["error"]["code"] == ("MMC_OUTPUT_IDENTITY_CHANGED" if read_error else "MMC_ACCEPTANCE_FAILED")
    assert not Path(plan["target_path"]).exists()
    assert "replay" not in calls
    assert [blank_service._sha256(path) for path in (source, library)] == hashes


def test_public_runtime_master_must_match_planned_identity_before_staging(tmp_path, monkeypatch):
    service, request, calls, *_ = _protocol_case(tmp_path, monkeypatch, bad_master=True)
    plan = service.plan_model(request)

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        return service.get_build_status(started["build_id"])

    record = asyncio.run(exercise())
    assert record["state"] == "failed"
    assert "load" not in calls and "materialize_fault" not in calls
    assert not Path(plan["staging_path"]).exists()


@pytest.mark.parametrize("recipe", ["native_full_sort_v1", "native_full_sort_dc_integral_004_v1"])
def test_public_full_sort_recipe_materializes_every_declared_step(tmp_path, monkeypatch, recipe):
    service, request, calls, *_ = _protocol_case(tmp_path, monkeypatch)

    def callback(name):
        def materialize(origin, destination, **kwargs):
            calls.append(name)
            Path(destination).write_bytes(Path(origin).read_bytes())
            return {"source": str(origin), "source_sha256": blank_service._sha256(Path(origin)), "destination": str(destination), "destination_sha256": blank_service._sha256(Path(destination)), "parameters": kwargs and {key: str(value) for key, value in kwargs.items()}}
        return materialize

    for name in ("materialize_voltage_control_headroom", "materialize_dc_feedback_filter", "materialize_terminal_two_carrier", "materialize_arm_virtual_resistance", "materialize_complete_arm_sorting", "materialize_voltage_control_integral_time"):
        monkeypatch.setattr(blank_service, name, callback(name), raising=False)
    request = {**request.to_dict(), "parameterization": {"model_recipe": recipe}}
    plan = service.plan_model(request)

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        return service.get_build_status(started["build_id"])

    record = asyncio.run(exercise())
    assert record["state"] == "failed"
    assert record["error"]["code"] == "MMC_ACCEPTANCE_FAILED"
    expected = ["native_fault", "terminal_two_charging", "headroom", "dc_feedback_filter", "terminal_two_carrier", "arm_virtual_resistance", "complete_arm_sorting"]
    if recipe == "native_full_sort_dc_integral_004_v1":
        expected.append("voltage_control_integral_time")
    assert [item["stage"] for item in record["lineage"]] == expected
    assert calls.index("materialize_complete_arm_sorting") < calls.index("instrument")


def test_public_publication_uses_tested_instrumented_fault_case(tmp_path, monkeypatch):
    service, request, calls, *_ = _protocol_case(tmp_path, monkeypatch, verdict="PASS")
    plan = service.plan_model(request)

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        return service.get_build_status(started["build_id"])

    record = asyncio.run(exercise())
    assert record["state"] == "published", record.get("error")
    target = Path(plan["target_path"])
    root = ET.parse(target).getroot()
    assert root.get("instrumented") == "true"
    assert root.get("fault_time_s") == "2.5"
    assert float(root.get("fault_duration_s")) == pytest.approx(0.2)
    assert calls.index("evaluate") < calls.index("replay")
    assert calls.index("materialize_fault") < calls.index("repair_t2_charging") < calls.index("instrument")
    assert record["lineage"][1]["stage"] == "terminal_two_charging"
    assert record["result"]["final_project_sha256"] == record["result"]["tested_project_sha256"]
    result = service.validate_model(str(target))
    assert result["accepted"] is True
    assert result["acceptance"]["verdict"] == "PASS"
    manifest = json.loads(Path(record["result"]["publication_manifest"]).read_text())
    assert manifest["output_index_sha256"]
    assert manifest["bundle_files"][Path(request.library_path).name]
    assert manifest["bundle_files"]["reload/worker/report.json"]


@pytest.mark.parametrize("changed", ["worker_exit_code", "parent_channel_contract_sha256", "report_sha256", "artifacts"])
def test_public_publication_requires_completed_replay_report_and_lineage(tmp_path, monkeypatch, changed):
    service, request, *_ = _protocol_case(tmp_path, monkeypatch, verdict="PASS")
    plan = service.plan_model(request)
    verifier = service._replay_verifier

    async def corrupt_replay(**kwargs):
        result = await verifier(**kwargs)
        result[changed] = {} if changed == "artifacts" else "changed"
        return result

    service._replay_verifier = corrupt_replay

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        return service.get_build_status(started["build_id"])

    record = asyncio.run(exercise())
    assert record["state"] == "failed"
    assert not Path(plan["target_path"]).exists()


@pytest.mark.parametrize("relative_path", ["evidence/checks.json", "evidence/published-channels.json", "outputs/ProtocolCase_01.out", "library.pslx"])
def test_public_validation_rejects_changed_published_bundle(tmp_path, monkeypatch, relative_path):
    service, request, *_ = _protocol_case(tmp_path, monkeypatch, verdict="PASS")
    plan = service.plan_model(request)

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        return service.get_build_status(started["build_id"])

    record = asyncio.run(exercise())
    assert record["state"] == "published", record.get("error")
    bundle = Path(record["result"]["bundle_path"])
    if relative_path.startswith("outputs/"):
        changed = Path(record["result"]["published_output_file"])
    elif relative_path == "library.pslx":
        changed = Path(record["result"]["final_library_path"])
    else:
        changed = bundle / relative_path
    changed.write_bytes(changed.read_bytes() + b" ")
    with pytest.raises(BackendError):
        service.validate_model(plan["target_path"])


def test_public_copy_failure_keeps_partial_publication_in_staging(tmp_path, monkeypatch):
    service, request, *_ = _protocol_case(tmp_path, monkeypatch, verdict="PASS")
    plan = service.plan_model(request)
    copytree = blank_service.shutil.copytree

    def interrupted_copy(source, destination, *args, **kwargs):
        copytree(source, destination, *args, **kwargs)
        raise OSError("Interrupted publication copy")

    monkeypatch.setattr(blank_service.shutil, "copytree", interrupted_copy)

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        return service.get_build_status(started["build_id"])

    record = asyncio.run(exercise())
    target = Path(plan["target_path"])
    assert record["state"] == "failed"
    assert not target.exists()
    assert not target.with_suffix(".bundle").exists()
    assert Path(record["result"]["output_index_path"]).is_file()


def test_failed_native_run_retains_lease_until_project_stop_is_confirmed(tmp_path, monkeypatch):
    service, request, *_ = _protocol_case(tmp_path, monkeypatch)
    plan = service.plan_model(request)

    async def interrupted(name):
        raise BackendError("MMC_BUILD_TIMED_OUT", "Vendor run did not settle", "test", "run")

    async def stopped(name):
        return {"status": "stopped"}

    service.pscad_service.run_project = interrupted

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        record = service.get_build_status(started["build_id"])
        assert record["containment"]["confirmed"] is False
        assert started["build_id"] in service._leases
        with pytest.raises(blank_service.PendingCleanupError):
            await service.shutdown(timeout_s=0.01)
        service.pscad_service.stop_simulation = stopped
        service.pscad_service.get_run_status = stopped
        await service.shutdown()
        assert not service._leases

    asyncio.run(exercise())


def test_pending_native_compile_retains_lease_until_its_vendor_token_settles(tmp_path, monkeypatch):
    from pscad_mcp.core.executor import ExecutorSettlementToken

    service, request, *_ = _protocol_case(tmp_path, monkeypatch)
    plan = service.plan_model(request)
    token = ExecutorSettlementToken(operation_id=1, generation=0, operation="build")
    owner = None

    class Executor:
        def pending_settlements_for(self, task):
            return (token,) if task is owner and not token.settled else ()

    async def interrupted(name):
        nonlocal owner
        owner = asyncio.current_task()
        raise BackendError("EXECUTOR_TIMEOUT", "Compile remains live", "test", "build")

    service.pscad_service.executor = Executor()
    service.pscad_service.build_project = interrupted

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        assert started["build_id"] in service._leases
        assert service.get_build_status(started["build_id"])["pending_vendor_calls"] == 1
        token.settle()
        await service.shutdown()
        assert not service._leases

    asyncio.run(exercise())


def test_raised_replay_failure_cannot_erase_pending_ownership_or_release_lease(tmp_path, monkeypatch):
    service, request, *_ = _protocol_case(tmp_path, monkeypatch, verdict="PASS")
    plan = service.plan_model(request)

    async def broken_replay(**kwargs):
        raise OSError("pipe read failure before cleanup report")

    service._replay_verifier = broken_replay

    async def exercise():
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await service._tasks[started["build_id"]]
        record = service.get_build_status(started["build_id"])
        assert record["state"] == "failed"
        assert record["result"]["reload"]["cleanup_pending"] is True
        assert started["build_id"] in service._leases
        assert record["containment"]["confirmed"] is False
        # This synthetic verifier created no process; clear only its fixture state.
        service._statuses[started["build_id"]]["result"]["reload"]["cleanup_pending"] = False
        await service.shutdown()

    asyncio.run(exercise())


def test_blank_mmc_plan_records_audited_topology_and_source_hashes(tmp_path: Path) -> None:
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text('<project name="template" version="4.6.2" Target="EMTDC"><definitions /></project>', encoding="ascii")
    library.write_text('<project name="library" Target="Library"><definitions /></project>', encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path / "workspace",
        audit_loader=lambda *_args: _audit("full_bridge", *_args),
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
            "submodule_topology": "full_bridge",
        }
    )

    plan = service.plan_model(request, folder=str(tmp_path / "workspace"))

    assert plan["status"] == "planned"
    assert plan["capabilities"]["intrinsic_dc_fault_blocking"] is True
    assert plan["template_native"]["source_hashes"]["project"] == hashlib.sha256(template.read_bytes()).hexdigest()
    assert plan["template_native"]["source_hashes"]["library"] == hashlib.sha256(library.read_bytes()).hexdigest()


def test_public_plan_freezes_installed_line_generation_inputs_without_writing(tmp_path):
    from pscad_mcp.hvdc.builders.mmc.template_audit import (
        discover_official_mmc_template,
    )

    master = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
    if not master.is_file():
        pytest.skip("Installed read-only Master is unavailable")
    project, library = discover_official_mmc_template()
    workspace = tmp_path / "workspace"
    service = BlankMmcBuilderService(None, workspace_root=workspace)
    request = BlankMmcRequest(project_name="CheckedLines", template_path=str(project), library_path=str(library), parameterization={"master_path": str(master)})
    plan = service.plan_model(request)
    lines = plan["line_constants"]
    assert lines["mode"] == "generate_public_from_source_dctl"
    assert lines["inputs"] and all(len(item["input_sha256"]) == 64 for item in lines["inputs"])
    assert lines["executable"]["sha256"] == hashlib.sha256(Path(lines["executable"]["path"]).read_bytes()).hexdigest()
    assert not workspace.exists()


def test_blank_mmc_plan_rejects_topology_mismatch(tmp_path: Path) -> None:
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text("template", encoding="ascii")
    library.write_text("library", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path / "workspace",
        audit_loader=lambda *_args: _audit("half_bridge"),
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
            "submodule_topology": "full_bridge",
        }
    )

    with pytest.raises(BackendError) as raised:
        service.plan_model(request, folder=str(tmp_path / "workspace"))

    assert raised.value.code == "MMC_TEMPLATE_TOPOLOGY_MISMATCH"


class _MmcNativeFake:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.project: Path | None = None
        self.settings: dict[str, object] = {}

    async def get_master_library_identity(self):
        master = blank_service._default_master_path()
        return {"master_path": str(master), "master_sha256": blank_service._sha256(master), "pscad_version": "4.6.2"}

    async def load_projects(self, paths: list[str]) -> None:
        self.calls.append("load_projects")
        self.project = Path(paths[-1])

    async def set_project_settings(self, project_name: str, settings: dict[str, object]) -> None:
        self.calls.append("set_project_settings")
        self.settings = dict(settings)

    async def get_project_settings(self, project_name: str) -> dict[str, object]:
        self.calls.append("get_project_settings")
        return dict(self.settings)

    async def save_project(self, project_name: str, *, confirm: bool = False) -> None:
        self.calls.append("save_project")

    async def build_project(self, project_name: str) -> None:
        self.calls.append("build_project")

    async def run_project(self, project_name: str) -> None:
        self.calls.append("run_project")

    async def get_run_status(self, project_name: str) -> dict[str, str]:
        self.calls.append("get_run_status")
        return {"status": "idle"}

    async def discover_output_files(self, project_name: str, *, started_after: float, max_files: int = 32) -> list[str]:
        self.calls.append("discover_output_files")
        assert self.project is not None
        output = self.project.parent / "native_01.out"
        output.write_text("waveform", encoding="ascii")
        return [str(output)]

    async def read_output_file(self, file_path: str, *, max_samples: int = 1_000_000, summary_only: bool = False) -> dict[str, object]:
        self.calls.append("read_output_file")
        return {
            "channels": [
                {"description": "Fault mode", "domain": [0.0, 0.3, 0.5], "values": [0.0, 1.0, 0.0]},
                {"description": "DC fault current", "domain": [0.0, 0.3, 0.5], "values": [0.0, 1.0, 0.0]},
                {"description": "De-blocking T1", "domain": [0.0, 0.3, 0.5], "values": [1.0, 0.0, 1.0]},
            ]
        }


def test_blank_mmc_native_build_keeps_staging_when_fault_evidence_is_incomplete(tmp_path: Path) -> None:
    template = _native_template(tmp_path / "template.pscx")
    library = tmp_path / "library.pslx"
    library.write_text("<project name='library' Target='Library'><definitions /></project>", encoding="ascii")
    workspace = tmp_path / "workspace"
    fake = _MmcNativeFake()
    def audit_for_build(template_path: str, library_path: str) -> dict[str, object]:
        report = _audit("full_bridge")
        report["source_hashes"] = {
            "project": hashlib.sha256(Path(template_path).read_bytes()).hexdigest(),
            "library": hashlib.sha256(Path(library_path).read_bytes()).hexdigest(),
        }
        return report

    service = BlankMmcBuilderService(
        fake,
        workspace_root=workspace,
        audit_loader=audit_for_build,
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
            "submodule_topology": "full_bridge",
        }
    )
    plan = service.plan_model(request, folder=str(workspace))

    async def run() -> dict[str, object]:
        started = await service.build_model(request, plan["plan_hash"], confirm=True)
        await asyncio.sleep(0)
        return service.get_build_status(str(started["build_id"]))

    status = asyncio.run(run())

    assert status["state"] == "failed"
    assert status["error"]["code"] == "MMC_ACCEPTANCE_INCOMPLETE"
    assert not Path(plan["target_path"]).exists()
    assert Path(plan["staging_path"]).is_dir()


def test_blank_mmc_validation_uses_audited_half_bridge_capability(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    library = tmp_path / "intermediate.pslx"
    output = tmp_path / "MMC_CASE.out"
    project.write_text("<project />", encoding="ascii")
    library.write_text("<project name='library' Target='Library' />", encoding="ascii")
    output.write_text("waveform", encoding="ascii")
    fake = _MmcNativeFake()
    service = BlankMmcBuilderService(
        fake,
        workspace_root=tmp_path,
        audit_loader=lambda *_args: _audit("half_bridge"),
    )

    async def call() -> dict[str, object]:
        return service.validate_model(
            str(project),
            output_file=str(output),
            template_path=str(project),
            library_path=str(library),
        )

    result = asyncio.run(call())

    assert result["acceptance"]["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["capabilities"]["intrinsic_dc_fault_blocking"] is False
    assert result["acceptance_scope"]["intrinsic_dc_fault_blocking"] == "NOT_APPLICABLE"
    assert result["valid"] is True and result["accepted"] is False


def test_blank_mmc_plan_rejects_non_finite_duration(tmp_path: Path) -> None:
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text("template", encoding="ascii")
    library.write_text("library", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path / "workspace",
        audit_loader=lambda *_args: _audit("full_bridge"),
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
        }
    )

    with pytest.raises(BackendError) as raised:
        service.plan_model(
            request,
            folder=str(tmp_path / "workspace"),
            simulation_duration_s=float("inf"),
        )

    assert raised.value.code == "MMC_BLUEPRINT_INVALID"


def test_blank_mmc_plan_rejects_a_dangling_destination_link(tmp_path: Path) -> None:
    template = tmp_path / "template.pscx"
    library = tmp_path / "library.pslx"
    template.write_text("template", encoding="ascii")
    library.write_text("library", encoding="ascii")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "MMC_CASE.pscx"
    try:
        target.symlink_to(workspace / "missing.pscx")
    except OSError as error:
        pytest.skip(f"file symlinks unavailable: {error}")
    service = BlankMmcBuilderService(
        None,
        workspace_root=workspace,
        audit_loader=lambda *_args: _audit("full_bridge"),
    )
    request = BlankMmcRequest.from_dict(
        {
            "project_name": "MMC_CASE",
            "template_path": str(template),
            "library_path": str(library),
        }
    )

    with pytest.raises(BackendError) as raised:
        service.plan_model(request, folder=str(workspace))

    assert raised.value.code == "MMC_BUILD_CONFLICT"


def test_blank_mmc_validation_requires_frozen_contract_before_reading(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    library = tmp_path / "intermediate.pslx"
    output = tmp_path / "MMC_CASE.out"
    project.write_text("<project />", encoding="ascii")
    library.write_text("<project name='library' Target='Library' />", encoding="ascii")
    output.write_text("waveform", encoding="ascii")

    class MinimalReader:
        async def read_output_file(self, file_path: str) -> dict[str, object]:
            raise AssertionError("Uncontracted samples must not be read")

    service = BlankMmcBuilderService(
        MinimalReader(),
        workspace_root=tmp_path,
        audit_loader=lambda *_args: _audit("half_bridge"),
    )

    result = service.validate_model(
        str(project),
        output_file=str(output),
        template_path=str(project),
        library_path=str(library),
    )

    assert result["acceptance"]["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["accepted"] is False


def test_blank_mmc_validation_rejects_partial_template_pair(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    project.write_text("<project />", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path,
        audit_loader=lambda *_args: _audit("full_bridge"),
    )

    with pytest.raises(BackendError) as raised:
        service.validate_model(
            str(project),
            template_path=str(project),
        )

    assert raised.value.code == "MMC_TEMPLATE_PAIR_INVALID"


def test_blank_mmc_validation_marks_an_incompatible_audit_invalid(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    library = tmp_path / "intermediate.pslx"
    project.write_text("<project />", encoding="ascii")
    library.write_text("<project />", encoding="ascii")
    service = BlankMmcBuilderService(
        None,
        workspace_root=tmp_path,
        audit_loader=lambda *_args: {"compatible": False, "submodule_topology": {}},
    )

    result = service.validate_model(
        str(project),
        template_path=str(project),
        library_path=str(library),
    )

    assert result["valid"] is False


def test_blank_mmc_validation_never_accepts_incompatible_audit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "MMC_CASE.pscx"
    library = tmp_path / "intermediate.pslx"
    output = tmp_path / "MMC_CASE.out"
    project.write_text("<project />", encoding="ascii")
    library.write_text("<project />", encoding="ascii")
    output.write_text("waveform", encoding="ascii")

    class PassingReader:
        async def read_output_file(self, file_path: str) -> dict[str, object]:
            domain = [0.0, 0.2, 0.4]
            return {
                "channels": [
                    {"description": "Fault mode", "domain": domain, "values": [0.0, 1.0, 0.0]},
                    {"description": "DC fault current", "domain": domain, "values": [0.0, 1.0, 0.0]},
                    {"description": "De-blocking", "domain": domain, "values": [1.0, 0.0, 1.0]},
                    {"description": "V_inserted", "domain": domain, "values": [0.0, -1.0, 0.0]},
                ]
            }

    service = BlankMmcBuilderService(
        PassingReader(),
        workspace_root=tmp_path,
        audit_loader=lambda *_args: {"compatible": False, "submodule_topology": {"declared": "full_bridge"}},
    )

    result = service.validate_model(
        str(project),
        output_file=str(output),
        template_path=str(project),
        library_path=str(library),
    )

    assert result["valid"] is False
    assert result["accepted"] is False
