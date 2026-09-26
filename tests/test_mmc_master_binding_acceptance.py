"""Offline contracts for the licensed MMC direct-binding fixture runner."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError, BackendInfo
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.hvdc.builders.mmc.master_bindings import (
    audit_mmc_master_bindings,
    load_mmc_master_registry,
)

SCRIPT = Path(__file__).parents[1] / "scripts/run_mmc_master_binding_acceptance.py"


def runner():
    assert SCRIPT.is_file(), "The MMC Master binding acceptance runner is missing"
    spec = importlib.util.spec_from_file_location("mmc_master_binding_runner", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "missing", ["PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_MASTER_BINDING_ACCEPTANCE"]
)
def test_each_optin_is_required_before_startup_or_workspace_writes(
    tmp_path, monkeypatch, missing
):
    module = runner()
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_MASTER_BINDING_ACCEPTANCE"):
        monkeypatch.setenv(name, "1")
    monkeypatch.delenv(missing)
    started = []
    workspace = tmp_path / "not-created"
    assert (
        module.main(
            ["--workspace-root", str(workspace)], service_factory=started.append
        )
        == 2
    )
    assert started == []
    assert not workspace.exists()
    with pytest.raises(PermissionError, match=missing):
        asyncio.run(
            module.run_attempt(
                SimpleNamespace(), tmp_path, service_factory=started.append
            )
        )
    assert list(tmp_path.iterdir()) == []


def test_real_service_backend_is_configured_only_after_owned_attach(
    tmp_path, monkeypatch
):
    module = runner()
    for name in (
        "PSCAD_MCP_ACCEPTANCE",
        "PSCAD_MCP_MASTER_BINDING_ACCEPTANCE",
        "PSCAD_MCP_ACCEPTANCE_CONCURRENT",
    ):
        monkeypatch.setenv(name, "1")
    master = synthetic_master(tmp_path / "sources/master.pslx")
    calls = []

    class LifecycleBackend:
        name, version, x64, owns_process = "legacy", "4.6.2", True, True

        def __init__(self):
            self.definition_paths = {}
            self.session_details = {"managed_pid": 123}

        async def attach(self):
            calls.append("attach")
            return BackendInfo("legacy", "4.6.2", True, True, False, True, True)

        async def heartbeat(self):
            calls.append("heartbeat")
            return BackendInfo("legacy", "4.6.2", True, True, False, True, True)

        async def lcc_definition_inventory(self, catalog, registry):
            assert self.definition_paths["master"] == master
            calls.append("inventory")
            raise BackendError(
                "OFFLINE_BOUNDARY_REACHED",
                "No vendor operation is permitted in this regression",
                "legacy",
                "get_lcc_inventory",
                {},
            )

        async def quit(self):
            calls.append("quit")

    backend = LifecycleBackend()
    service = PscadService(
        lambda: backend,
        executor=SimpleNamespace(snapshot=dict),
        path_policy=PathPolicy(workspace_root=str(tmp_path)),
    )
    with pytest.raises(RuntimeError, match="not connected"):
        _ = service.backend
    monkeypatch.setattr(module, "list_pscad_processes", lambda: [{"pid": 999}])
    args = module._parser().parse_args(
        [
            "--workspace-root",
            str(tmp_path / "runs"),
            "--master",
            str(master),
            "--cleanup-timeout",
            "0.01",
        ]
    )
    run_dir = tmp_path / "runs/attempt"
    run_dir.mkdir(parents=True)
    report = asyncio.run(
        module.run_attempt(args, run_dir, service_factory=lambda root: service)
    )
    assert report["failed_stage"] == "inventory", report.get("error")
    assert report["error"]["code"] == "OFFLINE_BOUNDARY_REACHED"
    assert calls == ["attach", "heartbeat", "inventory", "quit"]
    assert report["cleanup"]["owned_process_cleaned"] is True


def synthetic_master(path):
    """Build a portable XML source with the registry's checked contracts."""
    root = ET.Element("project", name="master")
    definitions = ET.SubElement(root, "definitions")
    registry = load_mmc_master_registry()
    for binding in registry.bindings:
        definition = ET.SubElement(
            definitions, "Definition", name=binding.physical_definition
        )
        svg = ET.SubElement(definition, "svg")
        for index, port in enumerate(binding.ports):
            for _ in range(port.occurrence + 1):
                ET.SubElement(
                    svg,
                    "port",
                    name=port.physical,
                    x=str(36 * index),
                    y="0",
                    dim=str(port.dimension),
                    model="Transfer" if port.kind == "data" else "Natural",
                    type="Real" if port.kind == "data" else "NonRemovable",
                ).text = "true"
        form = ET.SubElement(definition, "form")
        contracts = {item.physical: item.contract for item in binding.fixed_parameters}
        for item in binding.parameters:
            contracts.update(item.physical_contracts)
        for name, contract in contracts.items():
            attrs = {"name": name, "type": contract["type"]}
            if contract.get("unit"):
                attrs["unit"] = contract["unit"]
            parameter = ET.SubElement(form, "parameter", attrs)
            for choice in contract.get("choices", ()):
                ET.SubElement(parameter, "choice").text = str(choice)
    definition = ET.SubElement(definitions, "Definition", name="const")
    svg = ET.SubElement(definition, "svg")
    ET.SubElement(
        svg,
        "port",
        name="OUT",
        x="36",
        y="0",
        dim="1",
        model="Transfer",
        type="Real",
        mode="Output",
    ).text = "true"
    form = ET.SubElement(definition, "form")
    ET.SubElement(form, "parameter", name="Name", type="Text")
    ET.SubElement(form, "parameter", name="Value", type="Real")
    definition = ET.SubElement(definitions, "Definition", name="resistor")
    svg = ET.SubElement(definition, "svg")
    for name, x in (("A", 0), ("B", 36)):
        ET.SubElement(
            svg,
            "port",
            name=name,
            x=str(x),
            y="0",
            dim="0",
            model="Natural",
            type="Removable",
        ).text = "true"
    form = ET.SubElement(definition, "form")
    ET.SubElement(form, "parameter", name="R", type="Real", unit="ohm", min="0")
    path.parent.mkdir(parents=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


class Session:
    def __init__(
        self,
        master,
        *,
        compiler_error=False,
        attach_error=False,
        reload_available=False,
        unknown_ownership=False,
        cleanup_error=False,
        no_executable=False,
        mutate_project_on_quit=False,
        wire_mutation=None,
        wire_index=0,
        normalize_metadata=False,
        finalization_mutation=None,
        finalized_drift=None,
        skip_second_executable=False,
        clean_leaves_executable=False,
        clean_changes_project=False,
        clean_error=False,
    ):
        self.context = audit_mmc_master_bindings(master)
        self.backend = self
        self.definition_paths = {}
        self.calls = []
        self.components = {}
        self.wires = {}
        self.attached = False
        self.compiler_error = compiler_error
        self.attach_error = attach_error
        self.reload_available = reload_available
        self.cleanup_error = cleanup_error
        self.no_executable = no_executable
        self.mutate_project_on_quit = mutate_project_on_quit
        self.wire_mutation, self.wire_index = wire_mutation, wire_index
        self.normalize_metadata = normalize_metadata
        self.finalization_mutation = finalization_mutation
        self.finalized_drift = finalized_drift
        self.skip_second_executable = skip_second_executable
        self.clean_leaves_executable = clean_leaves_executable
        self.clean_changes_project = clean_changes_project
        self.clean_error = clean_error
        self.build_count = 0
        self.executor = SimpleNamespace(run_safe=self.run_safe)
        self.reloaded = False
        self.runtime = {
            "connected": True,
            "licensed": True,
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "owns_process": True,
            "session": {"managed_pid": 123},
        }
        if unknown_ownership:
            self.runtime["session"] = {}

    async def status(self):
        return self.runtime if self.attached else {"connected": False}

    async def attach_local(self):
        self.attached = True
        self.calls.append(("attach",))
        if self.attach_error:
            raise TimeoutError("owned startup timed out")

    async def get_lcc_inventory(self, catalog, registry):
        assert registry == self.context.audited.registry.to_dict()
        assert set(catalog["definitions"]) == set(
            self.context.audited.registry.by_logical_name
        )
        self.calls.append(("inventory", catalog))
        audited = self.context.audited
        return {
            "pscad_version": "4.6.2",
            "master_path": audited.master_path,
            "master_sha256": audited.master_sha256,
            "master_binding_registry_sha256": audited.registry.sha256,
            "definitions": json.loads(
                json.dumps(dict(audited.definitions), default=dict)
            ),
        }

    async def create_project(self, kind, filename, folder, *, confirm):
        self.path = Path(folder) / filename
        self.path.write_text(
            '<project name="' + self.path.stem + '"/>', encoding="utf-8"
        )
        return {"name": self.path.stem, "filename": str(self.path)}

    async def add_canvas_component(
        self,
        project,
        library,
        name,
        x,
        y,
        orientation,
        parameters,
        *,
        binding_evidence=None,
    ):
        component_id = len(self.components) + 1
        logical = f"{library}:{name}"
        resolved = None
        if logical in self.context.audited.registry.by_logical_name:
            resolved = self.context.audited.resolve_component(logical, parameters)
            assert resolved.to_evidence() == binding_evidence
        self.components[component_id] = {
            "id": component_id,
            "definition": f"master:{resolved.physical_definition}"
            if resolved
            else logical,
            "location": {"x": x, "y": y},
            "orientation": orientation,
            "parameters": dict(resolved.physical_parameters)
            if resolved
            else dict(parameters),
            "resolved": resolved,
        }
        self.calls.append(("add", logical, dict(parameters)))
        return {
            "id": component_id,
            "definition": self.components[component_id]["definition"],
        }

    async def get_master_binding_evidence(self, project, component_id):
        assert not self.reloaded, "Reload clears vendor binding state"
        item = self.components[component_id]
        resolved = item["resolved"]
        return {
            **resolved.to_evidence(),
            "logical_parameters": resolved.logical_parameters(item["parameters"]),
            "observed_instances": [
                {
                    "role": "component",
                    "instance": "default",
                    "component_id": component_id,
                    "definition": item["definition"],
                    "parameters": dict(item["parameters"]),
                }
            ],
        }

    async def get_component_parameters(self, project, component_id):
        item = self.components[component_id]
        if item["resolved"] and not self.reloaded:
            return item["resolved"].logical_parameters(item["parameters"])
        return dict(item["parameters"])

    async def get_component_ports(self, project, component_id):
        item = self.components[component_id]
        if item["resolved"] and not self.reloaded:
            ports = {
                name: {
                    "name": name,
                    "x": item["location"]["x"] + port["offset"][0],
                    "y": item["location"]["y"] + port["offset"][1],
                    "dim": port["dimension"],
                    "type": port["type"],
                }
                for name, port in item["resolved"].selected_ports.items()
            }
        else:
            definition = self.context.metadata[item["definition"].split(":")[1]][0]
            ports = {
                port.name: {
                    "name": port.name,
                    "x": item["location"]["x"] + port.x,
                    "y": item["location"]["y"] + port.y,
                    "dim": port.dim,
                    "type": port.type,
                }
                for port in definition.ports
            }
        return ports

    async def get_component_location(self, project, component_id):
        return dict(self.components[component_id]["location"])

    async def list_canvas_components(self, project):
        return [
            {key: value for key, value in item.items() if key != "resolved"}
            for item in self.components.values()
        ]

    async def verify_master_binding_state(
        self, project, ids, master_sha256, registry_sha256, *, refresh_components=True
    ):
        assert master_sha256 == self.context.audited.master_sha256
        assert registry_sha256 == self.context.audited.registry.sha256
        self.calls.append(("binding_gate", refresh_components))
        return {
            "master_sha256": master_sha256,
            "registry_sha256": registry_sha256,
            "components": {
                name: await self.get_master_binding_evidence(project, component_id)
                for name, component_id in ids.items()
            }
            if refresh_components
            else {},
        }

    async def create_wire(self, project, vertices):
        self.calls.append(("wire", vertices))
        wire_id = 100 + len(self.calls)
        self.wires[wire_id] = copy.deepcopy(vertices)
        return {"id": wire_id, "endpoints": [vertices[0], vertices[-1]]}

    async def save_project(self, project, *, confirm):
        self.calls.append(("save", project))
        root = ET.Element("project", name=project, version="4.6.2")
        normalized = self.normalize_metadata and self.build_count > 0
        settings = ET.SubElement(root, "paramlist", name="Settings")
        ET.SubElement(
            settings,
            "param",
            name="revisor",
            value="user, 1" if normalized else "user, 0",
        )
        definitions = ET.SubElement(root, "definitions")
        schematic = ET.SubElement(
            ET.SubElement(
                definitions,
                "Definition",
                name="Main",
                date="1" if normalized else "0",
                crc="456" if normalized else "123",
            ),
            "schematic",
            classid="UserCanvas",
        )
        sequence = ET.SubElement(schematic, "paramlist")
        ET.SubElement(sequence, "param", name="auto_sequence", value="1")
        for item in self.components.values():
            user = ET.SubElement(
                schematic,
                "User",
                id=str(item["id"]),
                defn=item["definition"],
                x=str(item["location"]["x"]),
                y=str(item["location"]["y"]),
                orient=str(item["orientation"]),
                z="1" if normalized else "-1",
            )
            parameters = ET.SubElement(user, "paramlist")
            for name, value in item["parameters"].items():
                ET.SubElement(parameters, "param", name=name, value=str(value))
        for index, (wire_id, requested) in enumerate(self.wires.items()):
            mutation = self.wire_mutation if index == self.wire_index else None
            if mutation == "missing":
                continue
            vertices = copy.deepcopy(requested)
            if mutation == "drift":
                vertices[-1][0] += 18
            if mutation == "bend":
                vertices[1][0] += 18
            if mutation == "wrong_id":
                wire_id += 1000
            parent = schematic
            if mutation == "wrong_canvas":
                parent = ET.SubElement(
                    ET.SubElement(definitions, "Definition", name="Other"), "schematic"
                )
            origin = vertices[0]
            wire = ET.SubElement(
                parent,
                "Wire",
                classid="WireOrthogonal",
                id=str(wire_id),
                x=str(origin[0]),
                y=str(origin[1]),
                orient="0",
                w="118" if normalized else "82",
                h="28" if normalized else "10",
            )
            for x, y in vertices:
                ET.SubElement(
                    wire, "vertex", x=str(x - origin[0]), y=str(y - origin[1])
                )
            if mutation == "duplicate":
                parent.append(copy.deepcopy(wire))
        if self.build_count == 1:
            if self.finalization_mutation == "parameter":
                root.find(".//User/paramlist/param[@name='R']").set("value", "11")
            elif self.finalization_mutation == "wire":
                root.find(".//Wire/vertex").set("x", "18")
        ET.ElementTree(root).write(self.path, encoding="utf-8", xml_declaration=True)

    async def reload_project(self, project, filename):
        self.calls.append(("reload", project))
        if not self.reload_available:
            raise BackendError(
                "BLUEPRINT_RELOAD_UNAVAILABLE",
                "vendor has no unload",
                "legacy",
                "reload_project",
                {},
            )
        self.reloaded = True

    async def build_project(self, project):
        self.calls.append(("build", project))
        self.build_count += 1
        if not self.no_executable and not (
            self.skip_second_executable and self.build_count == 2
        ):
            self.path.with_suffix(".exe").write_bytes(
                f"offline compiler test artifact {self.build_count}".encode("ascii")
            )
        if self.finalized_drift and self.build_count == 2:
            tree = ET.parse(self.path)
            if self.finalized_drift == "metadata":
                tree.find("./paramlist/param[@name='revisor']").set("value", "user, 2")
            else:
                tree.find(".//User/paramlist/param[@name='R']").set("value", "11")
            tree.write(self.path, encoding="utf-8", xml_declaration=True)
        return "Project built successfully"

    async def _project(self, name):
        assert name == self.path.stem
        return self

    async def run_safe(self, function, *args, timeout=None):
        return function(*args)

    def clean(self):
        self.calls.append(("clean", self.path.stem))
        if not self.clean_leaves_executable:
            self.path.with_suffix(".exe").unlink()
        if self.clean_changes_project:
            tree = ET.parse(self.path)
            tree.find("./paramlist/param[@name='revisor']").set("value", "user, 2")
            tree.write(self.path, encoding="utf-8", xml_declaration=True)
        return ET.Element("result", success="false" if self.clean_error else "true")

    async def get_project_output(self, project, *, structured):
        assert structured
        return (
            [{"severity": "error", "text": "unconnected PI input"}]
            if self.compiler_error
            else [{"severity": "normal", "text": "Build complete"}]
        )

    async def quit_pscad(self, *, confirm):
        self.calls.append(("quit", confirm))
        if self.mutate_project_on_quit:
            self.path.write_text("changed during vendor shutdown", encoding="utf-8")
        if self.cleanup_error:
            raise TimeoutError("owned quit timed out")

    async def disconnect(self):
        self.calls.append(("disconnect",))


def attempt(tmp_path, monkeypatch, *, source_code_drift=False, **session_options):
    module = runner()
    baseline_code = module._code_snapshot()
    snapshot_calls = 0

    def code_snapshot():
        nonlocal snapshot_calls
        snapshot_calls += 1
        result = copy.deepcopy(baseline_code)
        if source_code_drift and snapshot_calls > 1:
            result["source_code_hashes"][str(SCRIPT.resolve())] = "b" * 64
        return result

    monkeypatch.setattr(module, "_code_snapshot", code_snapshot)
    for name in (
        "PSCAD_MCP_ACCEPTANCE",
        "PSCAD_MCP_MASTER_BINDING_ACCEPTANCE",
        "PSCAD_MCP_ACCEPTANCE_CONCURRENT",
    ):
        monkeypatch.setenv(name, "1")
    master = synthetic_master(tmp_path / "sources/master.pslx")
    session = Session(master, **session_options)
    monkeypatch.setattr(module, "list_pscad_processes", lambda: [{"pid": 999}])
    args = module._parser().parse_args(
        [
            "--workspace-root",
            str(tmp_path / "runs"),
            "--master",
            str(master),
            "--cleanup-timeout",
            "0.01",
        ]
    )
    run_dir = tmp_path / "runs/attempt"
    run_dir.mkdir(parents=True)
    result = asyncio.run(
        module.run_attempt(args, run_dir, service_factory=lambda root: session)
    )
    durable = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert result == durable
    return module, result, session


def test_compile_freshness_uses_filesystem_time_instead_of_precise_wall_clock(tmp_path, monkeypatch):
    import time

    module = runner()
    monkeypatch.setattr(module, "time", SimpleNamespace(
        time=lambda: time.time() + 60.0,
        time_ns=lambda: time.time_ns() + 60_000_000_000,
    ), raising=False)
    monkeypatch.setitem(globals(), "runner", lambda: module)
    _, report, _ = attempt(tmp_path, monkeypatch)
    assert report["status"] == "PASS", report.get("error")


def test_registry_complete_fixture_preserves_normalized_rx_and_scoped_evidence(
    tmp_path, monkeypatch
):
    module, report, session = attempt(tmp_path, monkeypatch)
    assert report["status"] == "PASS", report.get("error")
    assert module.validate_mmc_master_binding_report(report) is report
    assert report["model_accepted"] is False
    assert {item["logical_name"] for item in report["bindings"]} == set(
        load_mmc_master_registry().by_logical_name
    )
    source_call = next(
        call for call in session.calls if call[:2] == ("add", "master:source3")
    )
    assert source_call[2]["GridMagnitude"] == 5.0
    assert source_call[2]["GridAngle"] == pytest.approx(53.13010235415598)
    assert (source_call[2]["GridR"], source_call[2]["GridX"]) == (3.0, 4.0)
    source = next(
        item for item in report["bindings"] if item["logical_name"] == "master:source3"
    )
    physical = source["observed_instances"][0]["parameters"]
    assert physical["Es"] == physical["Vm"] == 400.0
    assert physical["F0"] == physical["F"] == 50.0
    assert any(call[:2] == ("add", "master:const") for call in session.calls)
    assert len([call for call in session.calls if call[0] == "wire"]) == 5
    assert "source_neutral" in report["support"]
    assert report["persistence"]["mode"] == "save_live_readback"
    assert (
        report["persistence"]["reload_error"]["code"] == "BLUEPRINT_RELOAD_UNAVAILABLE"
    )
    assert report["cleanup"]["managed_pid"] == 123
    assert report["cleanup"]["remaining_owned_processes"] == []
    assert session.calls[-1] == ("quit", True)
    assert report["source_hashes_before"] == report["source_hashes_after"]
    assert str(SCRIPT.resolve()) in report["code_before"]["source_code_hashes"]


def test_native_metadata_is_finalized_before_a_clean_fresh_compile(
    tmp_path, monkeypatch
):
    module, report, session = attempt(tmp_path, monkeypatch, normalize_metadata=True)
    assert report["status"] == "PASS", report.get("error")
    finalization = report["finalization"]
    semantic = finalization["semantic_comparison"]
    assert semantic["semantic_structure_unchanged"] is True
    assert semantic["metadata_changes"]
    assert semantic["authored"]["sha256"] != semantic["finalized"]["sha256"]
    assert semantic["finalized"]["sha256"] == report["project"]["sha256"]
    assert finalization["clean"]["executables_after_clean"] == []
    assert finalization["sha256_after_clean"] == report["project"]["sha256"]
    assert report["wire_readback"]["project_sha256"] == report["project"]["sha256"]
    assert report["compile"]["executables_before_build"] == []
    assert (
        report["compile"]["artifacts"][0]["sha256"]
        != finalization["artifacts"][0]["sha256"]
    )
    assert all(Path(item["path"]).is_file() for item in finalization["artifacts"])
    assert Path(finalization["authored_project_artifact"]["path"]).is_file()
    build_calls = [i for i, call in enumerate(session.calls) if call[0] == "build"]
    clean_call = next(i for i, call in enumerate(session.calls) if call[0] == "clean")
    assert len(build_calls) == 2 and build_calls[0] < clean_call < build_calls[1]
    assert not any(call[0] == "save" for call in session.calls[build_calls[1] :])
    assert module.validate_mmc_master_binding_report(report) is report


@pytest.mark.parametrize("mutation", ["parameter", "wire"])
def test_compiler_finalization_rejects_authored_semantic_drift(
    tmp_path, monkeypatch, mutation
):
    _, report, session = attempt(
        tmp_path, monkeypatch, normalize_metadata=True, finalization_mutation=mutation
    )
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == "finalize_project"
    assert "semantic" in report["error"]["message"]
    assert session.build_count == 1
    assert report["cleanup"]["owned_process_cleaned"] is True


@pytest.mark.parametrize("mutation", ["parameter", "metadata"])
def test_finalized_project_rejects_any_hash_drift_during_fresh_compile(
    tmp_path, monkeypatch, mutation
):
    _, report, session = attempt(
        tmp_path, monkeypatch, normalize_metadata=True, finalized_drift=mutation
    )
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == "compile"
    assert (
        report["project"]["sha256_before_compile"]
        != report["project"]["sha256_after_compile"]
    )
    assert report["cleanup"]["owned_process_cleaned"] is True
    assert session.build_count == 2


@pytest.mark.parametrize(
    "failure", ["clean_leaves_executable", "skip_second_executable"]
)
def test_canonicalization_executable_cannot_satisfy_fresh_build(
    tmp_path, monkeypatch, failure
):
    _, report, session = attempt(tmp_path, monkeypatch, **{failure: True})
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == (
        "finalize_project" if failure == "clean_leaves_executable" else "compile"
    )
    assert session.build_count == (1 if failure == "clean_leaves_executable" else 2)
    assert report["cleanup"]["owned_process_cleaned"] is True


@pytest.mark.parametrize(
    "mutation", ["missing", "project_hash", "semantics", "clean", "preserved_artifact"]
)
def test_pass_report_requires_finalization_evidence(tmp_path, monkeypatch, mutation):
    module, report, _ = attempt(tmp_path, monkeypatch)
    assert report["status"] == "PASS", report.get("error")
    assert "finalization" in report
    if mutation == "missing":
        del report["finalization"]
    elif mutation == "project_hash":
        report["finalization"]["semantic_comparison"]["finalized"]["sha256"] = "b" * 64
    elif mutation == "semantics":
        report["finalization"]["semantic_comparison"]["authored"]["semantics"][
            "attributes"
        ]["name"] = "Other"
    elif mutation == "clean":
        report["finalization"]["clean"]["executables_after_clean"] = ["stale.exe"]
    else:
        report["finalization"]["artifacts"][0]["sha256"] = "b" * 64
    with pytest.raises(ValueError):
        module.validate_mmc_master_binding_report(report)


def test_master_report_cannot_substitute_generated_module_policy(tmp_path, monkeypatch):
    from pscad_mcp.acceptance.project_finalization import GENERATED_MODULE_POLICY

    module, report, _ = attempt(tmp_path, monkeypatch)
    assert report["status"] == "PASS", report.get("error")
    comparison = report["finalization"]["semantic_comparison"]
    comparison["policy"] = GENERATED_MODULE_POLICY
    comparison["authored"]["policy"] = GENERATED_MODULE_POLICY
    comparison["finalized"]["policy"] = GENERATED_MODULE_POLICY
    with pytest.raises(ValueError, match="policy"):
        module.validate_mmc_master_binding_report(report)


@pytest.mark.parametrize("failure", ["clean_changes_project", "clean_error"])
def test_owned_clean_must_succeed_without_changing_finalized_input(
    tmp_path, monkeypatch, failure
):
    _, report, session = attempt(tmp_path, monkeypatch, **{failure: True})
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == "finalize_project"
    assert session.build_count == 1
    assert report["cleanup"]["owned_process_cleaned"] is True


def test_runtime_source_hash_drift_cannot_pass(tmp_path, monkeypatch):
    _, report, session = attempt(tmp_path, monkeypatch, source_code_drift=True)
    assert session.build_count == 2
    assert report["status"] == "FAIL"
    assert report["source_code_immutable"] is False
    assert report["source_inputs_immutable"] is True
    assert report["cleanup"]["owned_process_cleaned"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "binding_missing",
        "duplicate_binding",
        "wrong_names",
        "port_dimension",
        "logical_rx",
        "physical_value",
        "missing_observation",
        "missing_gate",
        "compiler_error",
        "source_drift",
        "registry_file_drift",
        "code_drift",
        "owned_process_alive",
        "cleanup_error",
        "model_claim",
        "support_missing",
        "support_endpoint",
        "preexisting_executable",
        "unhashed_runtime_code",
        "forged_selected_port",
    ],
)
def test_pass_report_rejects_missing_or_contradictory_evidence(
    tmp_path, monkeypatch, mutation
):
    module, original, _ = attempt(tmp_path, monkeypatch)
    assert original["status"] == "PASS", original.get("error")
    report = copy.deepcopy(original)
    if mutation == "binding_missing":
        report["bindings"].pop()
    elif mutation == "duplicate_binding":
        report["bindings"][-1] = copy.deepcopy(report["bindings"][0])
    elif mutation == "wrong_names":
        report["bindings"][0]["logical_name"] = "master:three_phase_source"
    elif mutation == "port_dimension":
        next(
            item
            for item in report["bindings"]
            if item["logical_name"] == "master:source3"
        )["ports"]["AC"]["dim"] = 1
    elif mutation == "logical_rx":
        next(
            item
            for item in report["bindings"]
            if item["logical_name"] == "master:source3"
        )["logical_parameters"]["GridR"] = 5.0
    elif mutation == "physical_value":
        next(
            item
            for item in report["bindings"]
            if item["logical_name"] == "master:source3"
        )["observed_instances"][0]["parameters"]["Z1"] = 3.0
    elif mutation == "missing_observation":
        report["bindings"][0]["observed_instances"] = []
    elif mutation == "missing_gate":
        report["compile"]["binding_gate"]["components"] = {}
    elif mutation == "compiler_error":
        report["compile"]["messages"].append(
            {"severity": "error", "text": "compile failed"}
        )
    elif mutation in {"source_drift", "registry_file_drift"}:
        key = (
            report["master_path"]
            if mutation == "source_drift"
            else report["registry"]["path"]
        )
        report["source_hashes_after"][key] = "b" * 64
    elif mutation == "code_drift":
        report["code_after"]["commit"] = "b" * 40
    elif mutation == "owned_process_alive":
        report["cleanup"]["remaining_owned_processes"] = [{"pid": 123}]
    elif mutation == "cleanup_error":
        report["cleanup"]["errors"] = [{"operation": "quit", "code": "TIMEOUT"}]
    elif mutation == "model_claim":
        report["model_accepted"] = True
    elif mutation == "support_missing":
        del report["support"]["source_neutral"]
    elif mutation == "support_endpoint":
        report["support"]["transformer_neutral"]["vertices"][0][0] += 36
    elif mutation == "preexisting_executable":
        report["compile"]["executables_before_build"] = [
            report["compile"]["artifacts"][0]["path"]
        ]
    elif mutation == "unhashed_runtime_code":
        for key in ("code_before", "code_after"):
            report[key]["source_code_hashes"] = {"unrelated.py": "a" * 64}
    elif mutation == "forged_selected_port":
        source = next(
            item
            for item in report["bindings"]
            if item["logical_name"] == "master:source3"
        )
        source["ports"]["AC"]["dim"] = 1
        source["selected_ports"]["AC"]["dimension"] = 1
        report["inventory"]["definitions"]["master:source3"]["selected_ports"]["AC"][
            "dimension"
        ] = 1
        report["compile"]["binding_gate"]["components"]["master:source3"][
            "selected_ports"
        ]["AC"]["dimension"] = 1
    with pytest.raises((ValueError, TypeError)):
        module.validate_mmc_master_binding_report(report)


def test_compiler_messages_override_success_string_and_preserve_failure(
    tmp_path, monkeypatch
):
    _, report, session = attempt(tmp_path, monkeypatch, compiler_error=True)
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == "finalize_project"
    assert report["finalization"]["compile"]["success"] is False
    assert report["finalization"]["compile"]["messages"][0]["severity"] == "error"
    assert report["cleanup"]["owned_process_cleaned"] is True
    assert session.calls[-1] == ("quit", True)
    assert report["source_inputs_immutable"] is True


def test_attach_timeout_recovers_owned_status_for_cleanup(tmp_path, monkeypatch):
    _, report, session = attempt(tmp_path, monkeypatch, attach_error=True)
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == "attach"
    assert report["runtime_after_error"]["session"]["managed_pid"] == 123
    assert report["cleanup"]["owned_process_cleaned"] is True
    assert session.calls == [("attach",), ("quit", True)]


def test_reload_uses_fresh_physical_readback_after_binding_cache_is_cleared(
    tmp_path, monkeypatch
):
    module, report, session = attempt(tmp_path, monkeypatch, reload_available=True)
    assert report["status"] == "PASS", report.get("error")
    assert session.reloaded
    assert report["persistence"]["mode"] == "save_reload_readback"
    assert len(report["persistence"]["physical_readback"]) == len(
        load_mmc_master_registry().bindings
    )
    source = next(
        item
        for item in report["persistence"]["physical_readback"]
        if item["logical_name"] == "master:source3"
    )
    source["parameters"]["Es"] = 230.0
    with pytest.raises(ValueError, match="Reload"):
        module.validate_mmc_master_binding_report(report)


def test_unknown_ownership_never_quits_any_instance(tmp_path, monkeypatch):
    _, report, session = attempt(tmp_path, monkeypatch, unknown_ownership=True)
    assert report["status"] == "FAIL"
    assert report["cleanup"]["error"]["code"] == "OWNERSHIP_UNVERIFIED"
    assert session.calls == [("attach",)]


def test_cleanup_timeout_cannot_produce_pass_even_after_owned_pid_exits(
    tmp_path, monkeypatch
):
    _, report, session = attempt(tmp_path, monkeypatch, cleanup_error=True)
    assert report["status"] == "FAIL"
    assert report["cleanup"]["owned_process_cleaned"] is True
    assert report["cleanup"]["errors"][0]["operation"] == "quit"
    assert session.calls[-2:] == [("quit", True), ("disconnect",)]


def test_build_success_without_an_executable_is_not_acceptance(tmp_path, monkeypatch):
    _, report, _ = attempt(tmp_path, monkeypatch, no_executable=True)
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == "finalize_project"
    assert report["cleanup"]["owned_process_cleaned"] is True


@pytest.mark.parametrize(
    "wire_index",
    [0, 1, 2, 3, 4],
    ids=[
        "pi_input",
        "transformer_neutral",
        "source_neutral",
        "dc_shunt",
        "dc_shunt_ground",
    ],
)
@pytest.mark.parametrize(
    "mutation", ["missing", "drift", "wrong_id", "duplicate", "wrong_canvas"]
)
def test_saved_wire_must_match_returned_id_and_geometry_despite_success_ack(
    tmp_path, monkeypatch, wire_index, mutation
):
    _, report, session = attempt(
        tmp_path, monkeypatch, wire_mutation=mutation, wire_index=wire_index
    )
    assert len(report["support"]) > wire_index, "The fixture is missing a required wire"
    support = list(report["support"].values())[wire_index]
    assert support["wire"]["endpoints"] == [
        support["vertices"][0],
        support["vertices"][-1],
    ]
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == "save_readback"
    assert report["wire_readback"]["project_sha256"]
    assert report["cleanup"]["owned_process_cleaned"] is True
    assert not any(call[0] == "build" for call in session.calls)


def test_saved_wire_bends_are_verified_as_well_as_endpoints(tmp_path, monkeypatch):
    _, report, _ = attempt(tmp_path, monkeypatch, wire_mutation="bend", wire_index=1)
    assert report["status"] == "FAIL"
    assert report["failed_stage"] == "save_readback"


@pytest.mark.parametrize("mutation", ["missing", "geometry", "project_hash"])
def test_report_validator_requires_saved_wire_readback(tmp_path, monkeypatch, mutation):
    module, report, _ = attempt(tmp_path, monkeypatch)
    assert report["status"] == "PASS", report.get("error")
    assert "wire_readback" in report, "The report has only create_wire request echoes"
    saved = report["wire_readback"]
    if mutation == "missing":
        saved["wires"].pop()
    elif mutation == "geometry":
        saved["wires"][0]["vertices"][-1][0] += 18
    else:
        saved["project_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="[Ww]ire|[Ss]aved"):
        module.validate_mmc_master_binding_report(report)


def test_dc_node_has_a_verified_ten_ohm_shunt_with_two_saved_leads(
    tmp_path, monkeypatch
):
    _, report, session = attempt(tmp_path, monkeypatch)
    assert report["status"] == "PASS", report.get("error")
    assert "dc_shunt" in report["support"], "The adaptive DC node has no scalar circuit"
    shunt = report["support"]["dc_shunt"]
    assert shunt["component"]["definition"] == "master:resistor"
    assert shunt["parameters"] == {"R": 10.0}
    assert shunt["metadata"]["parameters"]["R"]["unit"] == "ohm"
    assert {
        port["name"]: (port["dim"], port["model"])
        for port in shunt["metadata"]["ports"]
    } == {"A": (0, "Natural"), "B": (0, "Natural")}
    bindings = {item["logical_name"]: item for item in report["bindings"]}
    dc = bindings["master:dc_bus"]["ports"]["DC"]
    ground = bindings["master:ground"]["ports"]["GND"]
    assert ground["dim"] == 1

    def endpoints(port):
        return [port["x"], port["y"]]

    assert shunt["wire"]["endpoints"] == [endpoints(dc), endpoints(shunt["ports"]["A"])]
    assert report["support"]["dc_shunt_ground"]["wire"]["endpoints"] == [
        endpoints(shunt["ports"]["B"]),
        endpoints(ground),
    ]
    assert len(report["wire_readback"]["wires"]) == 5
    assert report["wire_readback"]["project_sha256"] == report["project"]["sha256"]
    assert any(
        call[:2] == ("add", "master:resistor") and call[2] == {"R": 10.0}
        for call in session.calls
    )
    assert not any(
        set(map(tuple, item["wire"]["endpoints"]))
        == {tuple(endpoints(dc)), tuple(endpoints(ground))}
        for item in report["support"].values()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_resistor",
        "shorted_resistor",
        "resistance_drift",
        "wrong_definition",
        "wrong_unit",
        "vector_port",
        "data_port",
        "missing_ground_lead",
        "direct_short",
    ],
)
def test_dc_shunt_evidence_cannot_be_missing_or_substituted(
    tmp_path, monkeypatch, mutation
):
    module, report, _ = attempt(tmp_path, monkeypatch)
    assert report["status"] == "PASS", report.get("error")
    assert "dc_shunt" in report["support"], "The adaptive DC node has no scalar circuit"
    support = report["support"]
    shunt = support["dc_shunt"]
    if mutation == "missing_resistor":
        del support["dc_shunt"]
    elif mutation in {"shorted_resistor", "resistance_drift"}:
        shunt["parameters"]["R"] = 0 if mutation == "shorted_resistor" else 11
    elif mutation == "wrong_definition":
        shunt["component"]["definition"] = "master:inductor"
    elif mutation == "wrong_unit":
        shunt["metadata"]["parameters"]["R"]["unit"] = "H"
    elif mutation == "vector_port":
        shunt["ports"]["A"]["dim"] = 3
    elif mutation == "data_port":
        shunt["metadata"]["ports"][0]["model"] = "Transfer"
    elif mutation == "missing_ground_lead":
        del support["dc_shunt_ground"]
    else:
        dc = next(
            item
            for item in report["bindings"]
            if item["logical_name"] == "master:dc_bus"
        )["ports"]["DC"]
        support["dc_shunt_ground"]["vertices"][0] = [dc["x"], dc["y"]]
        support["dc_shunt_ground"]["wire"]["endpoints"][0] = [dc["x"], dc["y"]]
    with pytest.raises(ValueError):
        module.validate_mmc_master_binding_report(report)


def test_shutdown_cannot_change_the_delivered_project_after_it_was_verified(
    tmp_path, monkeypatch
):
    _, report, _ = attempt(tmp_path, monkeypatch, mutate_project_on_quit=True)
    assert report["status"] == "FAIL"
    assert report["cleanup"]["owned_process_cleaned"] is True
    assert report["artifacts_immutable"] is False


def test_missing_master_is_a_durable_external_prerequisite(tmp_path, monkeypatch):
    module = runner()
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_MASTER_BINDING_ACCEPTANCE"):
        monkeypatch.setenv(name, "1")
    started = []
    workspace = tmp_path / "runs"
    assert (
        module.main(
            [
                "--workspace-root",
                str(workspace),
                "--master",
                str(tmp_path / "sources/missing.pslx"),
            ],
            service_factory=started.append,
        )
        == 1
    )
    reports = list(workspace.glob("*/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["failure_category"] == "external_prerequisite"
    assert report["model_accepted"] is False
    assert report["cleanup"]["runtime_started"] is False
    assert report["error"]["traceback"]
    assert started == []
