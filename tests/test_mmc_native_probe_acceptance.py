"""Offline checks for the isolated native MMC diagnostic runner."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "run_mmc_native_probe_acceptance.py"


def runner():
    assert SCRIPT.is_file(), (
        "The native probe diagnostic runner has not been implemented"
    )
    spec = importlib.util.spec_from_file_location("mmc_native_probe_runner", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_optin_refuses_startup_and_workspace_writes(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.delenv("PSCAD_MCP_ACCEPTANCE", raising=False)
    workspace = tmp_path / "not-created"
    startup = []
    code = module.main(
        [
            "--workspace-root",
            str(workspace),
            "--template",
            "absent.pscx",
            "--library",
            "absent.pslx",
        ],
        service_factory=lambda path: startup.append(path),
    )
    assert code == 2
    assert startup == []
    assert not workspace.exists()


def test_direct_attempt_requires_optin_before_writes(tmp_path, monkeypatch):
    module = runner()
    monkeypatch.delenv("PSCAD_MCP_ACCEPTANCE", raising=False)
    with pytest.raises(PermissionError, match="PSCAD_MCP_ACCEPTANCE"):
        asyncio.run(module.run_attempt(SimpleNamespace(), tmp_path))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "native_suffixes,infx_suffixes", [(False, False), (True, True), (True, False)]
)
def test_reader_retains_large_vectors_and_actual_owner_mapping(
    tmp_path, monkeypatch, native_suffixes, infx_suffixes
):
    from xml.etree import ElementTree as ET

    from pscad_mcp.core.pscad_adapter import PscadAdapter

    module = runner()
    project = tmp_path / "many.pscx"
    project.write_text("<project/>", encoding="utf-8")
    generated = tmp_path / "many.gf42"
    generated.mkdir()
    document = ET.Element("Output")
    ET.SubElement(document, "Domain", {"name": "Time", "unit": "s"})
    analogs = ET.SubElement(document, "List", {"classid": "Analog"})
    metadata, expected, receipt = [], [], {"probes": []}
    for owner, (family, unit) in enumerate(module.PROBE_UNITS.items(), 1800000000):
        receipt["probes"].append({"name": family, "pgb_owner": str(owner)})
        for pole in range(1 if family.startswith(("MMC_DC_", "MMC_VDC_")) else 6):
            dimension = 90 if "VCAP" in family else 1
            native_name = family + (f"_{pole}" if native_suffixes and pole else "")
            infx_name = family + (f"_{pole}" if infx_suffixes and pole else "")
            ET.SubElement(
                analogs,
                "Analog",
                {
                    "name": f"Main(0)\\Pole({pole}):{infx_name}",
                    "index": str(len(expected)),
                    "dim": str(dimension),
                    "id": f"{owner}:{pole}",
                    "unit": unit,
                },
            )
            for component in range(dimension):
                call_id = len(expected) + 1
                name = native_name + (f":{component + 1}" if dimension > 1 else "")
                metadata.append(
                    f'PGB({call_id}) Output Desc="{name}" Group="Main" Max=1000 Min=-1000 Units="{unit}"'
                )
                expected.append(call_id)
    (generated / "many.inf").write_text("\n".join(metadata) + "\n", encoding="utf-8")
    ET.ElementTree(document).write(generated / "many.infx", encoding="utf-8")
    for part in range((len(expected) + 9) // 10):
        values = expected[part * 10 : part * 10 + 10]
        (generated / f"many_{part + 1:02d}.out").write_text(
            "".join(
                f"{t} " + " ".join(map(str, values)) + "\n" for t in (0.0, 0.01, 0.02)
            ),
            encoding="utf-8",
        )
    adapter = PscadAdapter(
        None, pscad_module=object(), psout_module=object(), environ={}
    )

    async def read(path, **kwargs):
        assert kwargs["max_samples"] == 100000
        return await adapter.read_psout(path, **kwargs)

    files = module.discover_run_outputs(project, project.stat().st_mtime - 1)
    original_open = Path.open
    opens = []

    def counted_open(path, *args, **kwargs):
        if path.suffix == ".out" and path.parent == generated:
            opens.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)
    traces = asyncio.run(
        module.read_run_probes(SimpleNamespace(read_output_file=read), files, receipt)
    )
    assert len(opens) == len(files["parts"])
    assert set(opens) == set(files["parts"])
    monkeypatch.setattr(Path, "open", original_open)
    assert len(files["parts"]) > 100
    assert [item["call_id"] for item in traces] == expected
    assert traces[-1]["values"] == [float(expected[-1])] * 3
    assert traces[-1]["source_part"].endswith(
        f"many_{(expected[-1] + 9) // 10:02d}.out"
    )
    assert traces[-1]["infx"]["instance"] == "Main(0)\\Pole(5)"
    assert (
        len(
            [
                item
                for item in traces
                if module._family(item["description"]) == "MMC_V_INSERTED_TOP"
            ]
        )
        == 6
    )
    if native_suffixes:
        assert traces[-1]["description"] == "MMC_VCAP_BTM_5:90"
        assert traces[-1]["path"] == "Main/MMC_VCAP_BTM_5:90"
        assert traces[-1]["infx"]["name"] == "Main(0)\\Pole(5):MMC_VCAP_BTM" + (
            "_5" if infx_suffixes else ""
        )
    for description in (traces[0]["description"], traces[-1]["description"]):
        existing = asyncio.run(
            adapter.read_psout(
                str(files["primary"]), channel=description, max_samples=100000
            )
        )
        observed = [item for item in traces if item["description"] == description]
        assert [
            (item["call_id"], item["domain"], item["values"]) for item in observed
        ] == [
            (item["call_id"], item["domain"], item["values"])
            for item in existing["channels"]
        ]
    corrupt = files["parts"][-1]
    corrupt.write_text(
        corrupt.read_text(encoding="utf-8").replace("\n", " 999\n"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="column"):
        asyncio.run(
            module.read_run_probes(
                SimpleNamespace(read_output_file=read), files, receipt
            )
        )


def channels():
    domain = [index * 0.01 for index in range(201)]
    traces = []

    def add(name, unit, values, instance="Main(0)", component=0, dim=1):
        traces.append(
            {
                "description": name,
                "path": name,
                "units": unit,
                "call_id": len(traces) + 1,
                "domain": list(domain),
                "values": values,
                "infx": {
                    "name": instance + ":" + name.split(":")[0],
                    "instance": instance,
                    "owner": name.split(":")[0],
                    "id": name.split(":")[0] + ":0",
                    "dimension": dim,
                    "component": component,
                    "unit": unit,
                },
                "source_part": "fresh_01.out",
            }
        )

    add("MMC_DC_FAULT_ACTIVE", "1", [float(0.8 <= t < 1) for t in domain])
    add("MMC_DC_FAULT_CURRENT", "kA", [5.0 if 0.8 <= t < 1 else 0.0 for t in domain])
    for terminal in (1, 2):
        add(f"MMC_VDC_T{terminal}", "kV", [640.0] * len(domain))
    for pole in range(6):
        instance = f"Main(0)\\MMC_Hb_PWM({pole // 3})\\MMC_Hb_Pole_PWM({pole % 3})"
        for arm in ("TOP", "BTM"):
            add(
                f"MMC_V_INSERTED_{arm}",
                "kV",
                [-10.0 if 0.8 <= t < 1 else 300.0 for t in domain],
                instance,
            )
            add(
                f"MMC_BLOCKED_{arm}",
                "1",
                [float(0.8 <= t < 1) for t in domain],
                instance,
            )
            for cell in range(2):
                add(
                    f"MMC_VCAP_{arm}:{cell + 1}",
                    "kV",
                    [4.0] * len(domain),
                    instance,
                    cell,
                    2,
                )
    return traces


def analyze(module, traces):
    return module.analyze_probes(
        traces, fault_time=0.8, fault_duration=0.2, duration=2.0, sample_step=0.01
    )


def test_measured_schedule_and_physical_diagnostics_never_accept_whole_model():
    result = analyze(runner(), channels())
    assert result["status"] == "PASS"
    assert result["model_accepted"] is False
    assert result["schedule"]["measured_on_s"] == pytest.approx(0.8)
    assert result["schedule"]["measured_off_s"] == pytest.approx(1.0)
    assert result["families"]["MMC_VCAP_TOP"]["count"] == 12
    assert len(result["arms"]) == 12
    assert all(arm["negative_voltage_during_fault"] for arm in result["arms"])
    assert all(
        arm["blocked_during_fault"] and arm["released_after_fault"]
        for arm in result["arms"]
    )
    assert result["current_bound"]["limit_ka"] == 20.0
    assert result["remaining_scope"]


def test_analysis_retains_all_native_suffixed_instances():
    traces = channels()
    instances = sorted(
        {
            trace["infx"]["instance"]
            for trace in traces
            if "Pole_PWM" in trace["infx"]["instance"]
        }
    )
    for trace in traces:
        instance = trace["infx"]["instance"]
        if instance not in instances:
            continue
        index = instances.index(instance)
        family, separator, component = trace["description"].partition(":")
        native_name = family + (f"_{index}" if index else "")
        trace["description"] = native_name + (
            separator + component if separator else ""
        )
        trace["path"] = "Main/" + trace["description"]
        trace["infx"]["name"] = instance + ":" + native_name
    result = analyze(runner(), traces)
    assert result["status"] == "PASS"
    assert len(result["arms"]) == 12
    assert result["families"]["MMC_VCAP_TOP"]["count"] == 12
    assert result["families"]["MMC_BLOCKED_TOP"]["instance_count"] == 6
    assert result["channels"][-1]["description"] == "MMC_VCAP_BTM_5:2"


@pytest.mark.parametrize("wrong_owned_name", [False, True])
def test_probe_selection_uses_receipt_owner_before_channel_name(
    tmp_path, wrong_owned_name
):
    from xml.etree import ElementTree as ET

    module = runner()
    document = ET.Element("Output")
    ET.SubElement(document, "Domain", {"name": "Time", "unit": "s"})
    analogs = ET.SubElement(document, "List", {"classid": "Analog"})
    metadata, receipt = [], {"probes": []}
    for index, (family, unit) in enumerate(module.PROBE_UNITS.items()):
        owner = str(1800000000 + index)
        receipt["probes"].append({"name": family, "pgb_owner": owner})
        name = "unrecognized_owned_probe" if wrong_owned_name and index == 0 else family
        ET.SubElement(
            analogs,
            "Analog",
            {
                "name": "Main(0):" + name,
                "index": str(index),
                "dim": "1",
                "id": owner + ":0",
                "unit": unit,
            },
        )
        metadata.append(
            f'PGB({index + 1}) Output Desc="{name}" Group="Main" Max=1 Min=0 Units="{unit}"'
        )
    foreign_name = "unrelated" if wrong_owned_name else "MMC_DC_FAULT_ACTIVE"
    ET.SubElement(
        analogs,
        "Analog",
        {
            "name": "Main(0):" + foreign_name,
            "index": "10",
            "dim": "1",
            "id": "unowned:0",
            "unit": "1",
        },
    )
    metadata.append(
        f'PGB(11) Output Desc="{foreign_name}" Group="Main" Max=1 Min=0 Units="1"'
    )
    inf, infx = tmp_path / "owned.inf", tmp_path / "owned.infx"
    inf.write_text("\n".join(metadata) + "\n", encoding="utf-8")
    ET.ElementTree(document).write(infx, encoding="utf-8")
    parts = [tmp_path / "owned_01.out", tmp_path / "owned_02.out"]
    parts[0].write_text("0 " + " ".join(["1"] * 10) + "\n", encoding="utf-8")
    parts[1].write_text("0 1\n", encoding="utf-8")
    files = {"inf": inf, "infx": infx, "parts": parts, "primary": parts[0]}
    if wrong_owned_name:
        with pytest.raises(ValueError, match="receipt"):
            asyncio.run(module.read_run_probes(None, files, receipt))
    else:
        traces = asyncio.run(module.read_run_probes(None, files, receipt))
        assert [trace["call_id"] for trace in traces] == list(range(1, 11))


@pytest.mark.parametrize(
    "minimum,expected", [(-0.5e-9, False), (-1e-9, False), (-1.5e-9, True)]
)
def test_negative_voltage_preserves_existing_epsilon(minimum, expected):
    traces = channels()
    for trace in traces:
        if trace["description"].startswith("MMC_V_INSERTED_"):
            trace["values"] = [
                minimum if 0.8 <= moment < 1 else 300.0 for moment in trace["domain"]
            ]
    result = analyze(runner(), traces)
    assert all(
        arm["negative_voltage_during_fault"] is expected for arm in result["arms"]
    )
    assert result["status"] == ("PASS" if expected else "FAIL")


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("missing", "missing_probe_family"),
        ("units", "probe_units"),
        ("time", "trace_time_alignment"),
        ("pulse", "fault_schedule"),
        ("nan", "nonfinite_probe"),
        ("overcurrent", "fault_current_bound"),
        ("missing_arm", "probe_instance_count"),
        ("missing_cell", "capacitor_dimension"),
        ("wrong_instance", "probe_instance_alignment"),
    ],
)
def test_incomplete_or_invalid_measurements_cannot_pass(mutation, expected):
    traces = channels()
    if mutation == "missing":
        traces = [
            trace for trace in traces if trace["description"] != "MMC_DC_FAULT_ACTIVE"
        ]
    elif mutation == "units":
        traces[1]["units"] = "A"
    elif mutation == "time":
        traces[1]["domain"][81] += 0.001
    elif mutation == "pulse":
        traces[0]["values"] = [float(0.8 <= t < 0.81) for t in traces[0]["domain"]]
    elif mutation == "nan":
        traces[1]["values"][85] = float("nan")
    elif mutation == "overcurrent":
        traces[1]["values"][85] = 20.01
    elif mutation == "missing_arm":
        traces.pop(4)
    elif mutation == "wrong_instance":
        traces[5]["infx"]["instance"] = "Main(0)\\WrongPole(0)"
    else:
        traces.pop(6)
    result = analyze(runner(), traces)
    assert result["status"] == "FAIL"
    assert expected in {issue["code"] for issue in result["issues"]}
    assert result["model_accepted"] is False


def test_infx_maps_vector_components_and_owner_instances(tmp_path):
    module = runner()
    path = tmp_path / "case.infx"
    path.write_text(
        '<Output><Domain name="Time" unit="s"><Sample rate="4000" end="8000"/></Domain>'
        '<List classid="Analog"><Analog name="Main(0)\\Pole(4):MMC_VCAP_TOP" '
        'index="9" id="1800000010:4" dim="2" unit="kV"/></List></Output>',
        encoding="utf-8",
    )
    result = module.read_infx(path)
    assert result[10]["owner"] == "1800000010"
    assert result[10]["instance"] == "Main(0)\\Pole(4)"
    assert result[11]["component"] == 1
    assert result[11]["dimension"] == 2
    assert result[11]["unit"] == "kV"


def test_discovery_preserves_more_than_100_parts_and_rejects_stale_metadata(tmp_path):
    module = runner()
    project = tmp_path / "unique.pscx"
    project.write_text("<project/>", encoding="utf-8")
    generated = tmp_path / "unique.gf42"
    generated.mkdir()
    for index in range(1, 124):
        (generated / f"unique_{index:02d}.out").write_text("0 1\n", encoding="utf-8")
    for suffix in (".inf", ".infx"):
        (generated / ("unique" + suffix)).write_text("metadata", encoding="utf-8")
    started = project.stat().st_mtime - 1.0
    result = module.discover_run_outputs(project, started)
    assert len(result["parts"]) == 123
    assert result["primary"].name == "unique_01.out"
    assert result["parts"][-1].name == "unique_123.out"
    import os

    os.utime(result["infx"], (started - 10, started - 10))
    with pytest.raises(ValueError, match="fresh"):
        module.discover_run_outputs(project, started)


def test_fresh_compiled_metadata_is_bound_to_the_same_unique_run(tmp_path):
    import os
    import time

    module = runner()
    project = tmp_path / "new.pscx"
    project.write_text("<project/>", encoding="utf-8")
    generated = tmp_path / "new.gf42"
    generated.mkdir()
    (generated / "new_01.out").write_text("0 1\n", encoding="utf-8")
    compile_start, run_start = time.time() - 20, time.time() - 10
    for suffix in (".inf", ".infx"):
        metadata = generated / ("new" + suffix)
        metadata.write_text("from this compile", encoding="utf-8")
        os.utime(metadata, (compile_start + 1, compile_start + 1))
    result = module.discover_run_outputs(
        project, run_start, metadata_started_after=compile_start
    )
    assert result["infx"].name == "new.infx"
    with pytest.raises(ValueError, match="fresh"):
        module.discover_run_outputs(project, run_start)


class Session:
    def __init__(self):
        self.calls = []

    async def stop_simulation(self, project):
        self.calls.append(("stop", project))

    async def quit_pscad(self, *, confirm):
        self.calls.append(("quit", confirm))

    async def disconnect(self):
        self.calls.append(("disconnect",))


def test_cleanup_filters_foreign_processes_using_verified_pid(monkeypatch):
    module = runner()
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    service = Session()
    runtime = {"owns_process": True, "session": {"managed_pid": 123}}
    observed = []
    original = module.remaining_acceptance_processes

    def remaining(current, reader):
        observed.append(current)
        return original(current, reader)

    monkeypatch.setattr(module, "remaining_acceptance_processes", remaining)
    result = asyncio.run(
        module.cleanup_owned_session(
            service,
            runtime,
            project_name="ours",
            run_pending=True,
            process_reader=lambda: [{"pid": 999}],
            timeout=0.1,
        )
    )
    assert result["owned_process_cleaned"] is True
    assert result["remaining_owned_processes"] == []
    assert observed == [runtime]
    assert service.calls == [("stop", "ours"), ("quit", True)]


def test_unknown_ownership_cannot_stop_or_quit_any_instance(monkeypatch):
    module = runner()
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    service = Session()
    result = asyncio.run(
        module.cleanup_owned_session(
            service,
            {"owns_process": True},
            project_name="unknown",
            run_pending=True,
            process_reader=lambda: [{"pid": 999}],
            timeout=0.1,
        )
    )
    assert result["owned_process_cleaned"] is False
    assert result["error"]["code"] == "OWNERSHIP_UNVERIFIED"
    assert not any(call[0] in {"stop", "quit"} for call in service.calls)


def test_runtime_requires_license_legacy_462_x64_and_vendor_pid():
    module = runner()
    valid = {
        "connected": True,
        "licensed": True,
        "backend": "legacy",
        "version": "4.6.2",
        "x64": True,
        "owns_process": True,
        "session": {"managed_pid": 123},
    }
    module.require_runtime(valid)
    for key, value in (
        ("licensed", False),
        ("backend", "modern"),
        ("version", "5.0"),
        ("x64", False),
        ("connected", False),
        ("session", {}),
    ):
        with pytest.raises(RuntimeError):
            module.require_runtime({**valid, key: value})


def test_failed_setup_writes_a_durable_report_and_classifies_missing_source(
    tmp_path, monkeypatch
):
    module = runner()
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    workspace = tmp_path / "attempts"
    startup = []
    code = module.main(
        [
            "--workspace-root",
            str(workspace),
            "--template",
            str(tmp_path / "sources/missing.pscx"),
            "--library",
            str(tmp_path / "sources/missing.pslx"),
        ],
        service_factory=lambda path: startup.append(path),
    )
    reports = list(workspace.glob("*/report.json"))
    assert code == 1
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["failure_category"] == "external_prerequisite"
    assert report["error"]["traceback"]
    assert report["model_accepted"] is False
    assert startup == []


def test_failed_compile_preserves_attempt_and_quits_only_its_session(
    tmp_path, monkeypatch
):
    module = runner()
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE_CONCURRENT", "1")
    inputs = tmp_path / "sources"
    inputs.mkdir()
    template, library = inputs / "template.pscx", inputs / "intermediate.pslx"
    template.write_text(
        '<project name="old_identity"><definitions/></project>', encoding="utf-8"
    )
    library.write_text(
        '<project name="VSC_MMC_Lib"><definitions/></project>', encoding="utf-8"
    )
    support = inputs / "lib"
    support.mkdir()
    (support / "support.lib").write_bytes(b"immutable dependency")
    args = module._parser().parse_args(
        [
            "--workspace-root",
            str(tmp_path / "runs"),
            "--template",
            str(template),
            "--library",
            str(library),
            "--master",
            str(library),
            "--compiler-configuration",
            str(library),
            "--compiler-executable",
            str(library),
            "--tline",
            str(library),
            "--cleanup-timeout",
            "0.01",
        ]
    )
    instance = Session()
    runtime = {
        "connected": True,
        "licensed": True,
        "backend": "legacy",
        "version": "4.6.2",
        "x64": True,
        "owns_process": True,
        "session": {"managed_pid": 123},
    }
    state = {
        "attached": False,
        "settings": {
            "time_duration": "1",
            "time_step": "50",
            "sample_step": "250",
            "PlotType": "0",
            "output_filename": "noname.out",
        },
    }

    async def status():
        return runtime if state["attached"] else {"connected": False}

    async def attach():
        state["attached"] = True
        instance.calls.append(("attach",))

    async def load(paths):
        instance.calls.append(("load", paths))

    async def save(project, *, confirm):
        instance.calls.append(("save", project))

    async def get_settings(project):
        return dict(state["settings"])

    async def set_settings(project, values):
        state["settings"].update(values)

    async def build(project):
        raise module.BackendError(
            "PSCAD_BUILD_FAILED",
            "specific compiler defect",
            "legacy",
            "build_project",
            {"project": project},
        )

    async def messages(project, *, structured):
        return [{"text": "specific compiler defect", "severity": "error"}]

    instance.status, instance.attach_local = status, attach
    instance.load_projects, instance.save_project = load, save
    instance.get_project_settings, instance.set_project_settings = (
        get_settings,
        set_settings,
    )
    instance.build_project, instance.get_project_output = build, messages
    monkeypatch.setattr(module, "list_pscad_processes", lambda: [{"pid": 999}])
    monkeypatch.setattr(
        module, "remaining_acceptance_processes", lambda runtime, reader: []
    )
    monkeypatch.setattr(
        module,
        "generate_public_line_constants",
        lambda *args, **kwargs: (
            SimpleNamespace(to_dict=lambda: {"test": "external utility stub"}),
        ),
    )
    monkeypatch.setattr(
        module,
        "rebind_template_line_constants",
        lambda source, artifacts, target: Path(shutil.copy2(source, target)),
    )

    def materialize(source, destination, **kwargs):
        shutil.copy2(source, destination)
        return {"probes": []}

    monkeypatch.setattr(module, "materialize_native_fault_probes", materialize)
    monkeypatch.setattr(module, "materialize_template_native_scenario", materialize)
    before = (template.read_bytes(), library.read_bytes())
    run_dir = tmp_path / "runs/attempt"
    run_dir.mkdir(parents=True)
    result = asyncio.run(
        module.run_attempt(args, run_dir, service_factory=lambda root: instance)
    )
    durable = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert result["status"] == durable["status"] == "FAIL"
    assert durable["failed_stage"] == "compile"
    assert durable["error"]["code"] == "PSCAD_BUILD_FAILED"
    assert durable["error"]["traceback"]
    assert durable["failure_category"] == "implementation_defect"
    assert durable["cleanup"]["owned_process_cleaned"] is True
    assert ("quit", True) in instance.calls
    assert ("save", "VSC_MMC_Lib") in instance.calls
    assert not any(call[0] == "stop" for call in instance.calls)
    assert before == (template.read_bytes(), library.read_bytes())
    assert durable["source_inputs_immutable"] is True
    assert durable["source_code_immutable"] is True
    assert (run_dir / "lib/support.lib").read_bytes() == b"immutable dependency"
    assert durable["artifacts"]
