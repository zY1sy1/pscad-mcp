import asyncio
import hashlib
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.parametric_executor import execute_parametric_template


TEMPLATE = '<project name="Fixture"><definitions><Definition name="Main"><form><parameter name="Freq" value="50.0 Hz" /></form></Definition></definitions></project>'


def _plan(tmp_path: Path, *, lifecycle=None, binding=True):
    source = tmp_path / "source.pscx"
    source.write_text(TEMPLATE, encoding="utf-8")
    staging = tmp_path / "workspace" / "stage.pscx"
    bindings = []
    if binding:
        bindings = [{
            "logical_parameter": "frequency_hz",
            "selector": "/project/definitions/Definition/form/parameter[@name='Freq']",
            "attribute": "value",
            "value": "60.0 Hz",
            "units": "Hz",
        }]
    plan = {
        "template": {"path": str(source), "fingerprint": hashlib.sha256(source.read_bytes()).hexdigest()},
        "project": {"name": "StageProject", "staging_path": str(staging), "target_path": str(tmp_path / "final.pscx")},
        "bindings": bindings,
    }
    if lifecycle is not None:
        plan["lifecycle"] = lifecycle
    return plan, staging


class FakePscadService:
    def __init__(self, *, run_response="started", write_output=True, fail_on=None):
        self.calls = []
        self.run_response = run_response
        self.write_output = write_output
        self.fail_on = fail_on

    def _call(self, name, *args, **kwargs):
        self.calls.append(name)
        if self.fail_on == name:
            raise RuntimeError(name)

    async def load_projects(self, filenames):
        self._call("load_projects", filenames)

    async def set_project_settings(self, project_name, settings):
        self._call("set_project_settings", project_name, settings)

    async def save_project_as(self, project_name, filename, folder, *, confirm=False):
        self._call("save_project_as", project_name, filename, folder, confirm=confirm)

    async def run_project(self, project_name):
        self._call("run_project", project_name)
        if self.write_output:
            # The output is created by PSCAD beside the staging project.
            Path(self._staging).with_suffix(".out").write_bytes(b"waveform")
        return self.run_response

    async def read_output_file(self, file_path, max_samples=10_000, channel=None, summary_only=False):
        self._call("read_output_file", file_path, max_samples, channel, summary_only)
        return {"file": file_path, "samples": 1}


def _run(plan, staging, fake):
    fake._staging = str(staging)
    return asyncio.run(execute_parametric_template(plan, fake, staging.parent, build_id="lifecycle"))


def test_lifecycle_calls_public_service_in_order_and_reads_output(tmp_path):
    plan, staging = _plan(tmp_path, lifecycle={"settings": {"time_duration": 1.0}})
    service = FakePscadService()
    result = _run(plan, staging, service)
    assert service.calls == ["load_projects", "set_project_settings", "save_project_as", "run_project", "read_output_file"]
    assert result["state"] == "validated"
    assert Path(result["result"]["output_file"]).is_file()
    assert not Path(plan["project"]["target_path"]).exists()


def test_binding_error_occurs_before_first_pscad_call(tmp_path):
    plan, staging = _plan(tmp_path, binding=False)
    service = FakePscadService()
    with pytest.raises(BackendError) as raised:
        _run(plan, staging, service)
    assert raised.value.code == "LCC_PARAMETER_BINDING_UNAVAILABLE"
    assert service.calls == []
    assert not staging.exists()


def test_compile_failure_is_stable_and_keeps_staging(tmp_path):
    plan, staging = _plan(tmp_path)
    service = FakePscadService(fail_on="run_project")
    with pytest.raises(BackendError) as raised:
        _run(plan, staging, service)
    assert raised.value.code == "LCC_COMPILE_FAILED"
    assert staging.is_file()
    assert not Path(plan["project"]["target_path"]).exists()


def test_run_timeout_is_stable_when_pscad_does_not_emit_output(tmp_path):
    plan, staging = _plan(tmp_path, lifecycle={"run_timeout_s": 0.01, "poll_interval_s": 0.001})
    service = FakePscadService(write_output=False)
    with pytest.raises(BackendError) as raised:
        _run(plan, staging, service)
    assert raised.value.code == "LCC_RUN_TIMED_OUT"
    assert staging.is_file()


def test_output_reader_failure_is_reported_as_missing_output(tmp_path):
    plan, staging = _plan(tmp_path)
    service = FakePscadService()

    async def fail_reader(*args, **kwargs):
        raise FileNotFoundError("missing")

    service.read_output_file = fail_reader
    with pytest.raises(BackendError) as raised:
        _run(plan, staging, service)
    assert raised.value.code == "LCC_OUTPUT_MISSING"
    assert staging.is_file()
