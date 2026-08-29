from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from pscad_mcp.core.backend.base import BackendError, ComponentInfo
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.definition_metadata import master_definition_binding
from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set
from tests.backend_fakes import FakeLegacyAutomation, ImmediateExecutor
from tests.test_backend_components import ComponentApp, LegacyComponentProject
from tests.test_master_binding_registry import _master_fixture_xml


def test_master_binding_uses_installed_pscad_names_and_explicit_port_mapping():
    binding = master_definition_binding("master:three_phase_source")
    assert binding.definition == "source3"
    assert binding.port_map == {"A": "A", "B": "B", "C": "C"}
    assert binding.parameter_map["Amplitude_kV"] == "Vm"


def test_master_binding_marks_three_phase_filter_as_expansion():
    binding = master_definition_binding("master:ac_filter_branch")
    assert binding.definition == "cfilter"
    assert binding.instances == 3
    assert binding.port_map == {"IN": "A", "OUT": "B"}


async def _runtime_backend(tmp_path):
    master = tmp_path / "master.pslx"
    master.write_text(_master_fixture_xml(), encoding="utf-8")
    project = LegacyComponentProject()
    project.main.wires = []

    def add_wire(*vertices):
        wire = SimpleNamespace(
            id=10_000 + len(project.main.wires),
            vertices=tuple(vertices),
        )
        project.main.wires.append(wire)
        return wire

    project.main.add_wire = add_wire
    backend = LegacyBackend(
        ImmediateExecutor(),
        version="4.6.2",
        x64=True,
        automation_module=FakeLegacyAutomation(ComponentApp(project)),
        definition_paths={"master": master},
    )
    await backend.attach()
    assets = load_packaged_asset_set()
    assert assets.master_bindings is not None
    await backend.lcc_definition_inventory(
        assets.catalog,
        assets.master_bindings.to_dict(),
    )
    return backend, project, master


@pytest.mark.parametrize(
    ("logical", "parameters", "physical", "expected_physical"),
    [
        (
            "three_phase_source",
            {"Amplitude_kV": 230.0, "Frequency_Hz": 50.0, "Phase_deg": 0.0},
            "source3",
            {"Vm": 230.0, "F": 50.0, "Ph": 0.0, "View": 0},
        ),
        (
            "converter_transformer",
            {"Ratio": 1.0, "Connection": "Y-delta", "PhaseShift_deg": 30.0},
            "xfmr-3p2w",
            {
                "V1": 230.0,
                "V2": 230.0,
                "f": 50.0,
                "View": 0,
                "YD1": 0,
                "YD2": 1,
                "Lead": 1,
            },
        ),
        (
            "smoothing_reactor",
            {"Inductance_mH": 100.0},
            "inductor",
            {"L": 0.1},
        ),
        (
            "dc_line_section",
            {"Length_km": 300.0, "Resistance_ohm": 10.0},
            "resistor",
            {"R": 10.0},
        ),
        (
            "ac_meter",
            {},
            "multimeter",
            {"MeasP": 1, "MeasQ": 1, "Freq": 50.0, "BaseV": 230.0},
        ),
        (
            "dc_meter",
            {},
            "multimeter",
            {"MeasV": 1, "MeasI": 1},
        ),
        ("ground", {}, "ground", {}),
    ],
)
def test_legacy_instantiates_direct_physical_binding_and_round_trips(
    tmp_path,
    logical,
    parameters,
    physical,
    expected_physical,
):
    async def exercise():
        backend, project, _master = await _runtime_backend(tmp_path)
        created = await backend.add_component(
            "case",
            "Main",
            "master",
            logical,
            (36, 36),
            0,
            parameters,
        )
        component = project.main.components[-1]
        observed = await backend.get_component_parameters("case", created.id)
        return created, component, observed

    created, component, observed = asyncio.run(exercise())

    assert component.defn_name == f"master:{physical}"
    assert created.definition == f"master:{logical}"
    assert component.values | expected_physical == component.values
    assert all(observed[name] == pytest.approx(value) if isinstance(value, float) else observed[name] == value for name, value in parameters.items())


def test_legacy_rejects_changed_master_source_before_component_creation(tmp_path):
    async def exercise():
        backend, project, master = await _runtime_backend(tmp_path)
        before = len(project.main.components)
        master.write_text(_master_fixture_xml() + "\n", encoding="utf-8")
        with pytest.raises(BackendError) as failure:
            await backend.add_component(
                "case",
                "Main",
                "master",
                "smoothing_reactor",
                (36, 36),
                0,
                {"Inductance_mH": 100.0},
            )
        return failure.value, before, len(project.main.components)

    error, before, after = asyncio.run(exercise())

    assert error.code == "MASTER_SOURCE_CHANGED"
    assert before == after


def test_legacy_expands_filter_and_grounds_each_neutral(tmp_path):
    async def exercise():
        backend, project, _master = await _runtime_backend(tmp_path)
        created = await backend.add_component(
            "case",
            "Main",
            "master",
            "ac_filter_branch",
            (360, 180),
            0,
            {"Branch_MVAR": 50.0, "Tuning_Hz": 300.0},
        )
        physical = project.main.components[1:]
        parameters = await backend.get_component_parameters("case", created.id)
        ports = await backend.get_component_ports("case", created.id)
        return created, physical, project.main.wires, parameters, ports

    created, physical, wires, parameters, ports = asyncio.run(exercise())

    assert created.definition == "master:ac_filter_branch"
    assert [item.defn_name for item in physical] == [
        "master:cfilter",
        "master:ground",
        "master:cfilter",
        "master:ground",
        "master:cfilter",
        "master:ground",
    ]
    filters = physical[::2]
    for item in filters:
        assert item.values["Q"] == pytest.approx(50.0 / 3.0)
        assert item.values["h"] == pytest.approx(6.0)
        assert item.values["f0"] == pytest.approx(50.0)
        assert item.values["dentry"] == 1
        assert item.values["V"] == pytest.approx(132.79056191361394)
    assert [wire.vertices for wire in wires] == [
        ((360, 144), (414, 144)),
        ((360, 264), (414, 264)),
        ((360, 384), (414, 384)),
    ]
    assert parameters == {
        "Branch_MVAR": pytest.approx(50.0),
        "Tuning_Hz": pytest.approx(300.0),
    }
    assert {port.name for port in ports} == {
        "IN_A",
        "OUT_A",
        "IN_B",
        "OUT_B",
        "IN_C",
        "OUT_C",
    }


def test_service_preserves_legacy_add_component_signature_without_binding(tmp_path):
    class ExistingBackend:
        async def add_component(
            self,
            project_name,
            canvas_name,
            library,
            definition,
            location,
            orientation,
            parameters,
        ):
            return ComponentInfo(
                1,
                "R1",
                f"{library}:{definition}",
                {"x": location[0], "y": location[1]},
            )

    backend = ExistingBackend()
    service = PscadService(
        lambda: backend,
        path_policy=PathPolicy(str(tmp_path)),
    )
    service._backend = backend

    created = asyncio.run(
        service.add_canvas_component(
            "case",
            "master",
            "resistor",
            36,
            36,
            0,
            {"R": 10.0},
        )
    )

    assert created["definition"] == "master:resistor"
