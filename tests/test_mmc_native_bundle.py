from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc import cable_constants
from pscad_mcp.hvdc.builders.mmc.native_bundle import (
    CONTROL_NAME,
    FIXTURE_CHANNELS,
    NATIVE_SCOPE,
    audit_native_avm_fixture,
    materialize_native_avm_fixture,
    materialize_native_avm_library,
)
from tests.test_mmc_cable_constants import _fake_native_run


@pytest.fixture(scope="module")
def installed_sources():
    master = Path(r"C:\Program Files (x86)\PSCAD46\master.pslx")
    donor = Path(r"C:\Users\Public\Documents\PSCAD\4.6\Examples\hvdc_vsc\VSCTrans.pscx")
    if not master.is_file() or not donor.is_file():
        pytest.skip("Installed PSCAD 4.6.2 XML sources are required")
    return donor, master


@pytest.fixture
def constants_evidence(installed_sources, tmp_path, monkeypatch):
    donor, master = installed_sources
    executable = tmp_path / "tline.exe"
    executable.write_bytes(b"fixture")
    monkeypatch.setattr(cable_constants.subprocess, "run", _fake_native_run)
    result = cable_constants.generate_public_cable_constants(
        donor,
        tmp_path / "constants-source",
        master_path=master,
        executable=executable,
        lengths_km=(300.0,),
    )[0]
    return Path(result.evidence_path)


def test_native_bundle_contains_physical_arm_control_and_coupled_cable(
    constants_evidence, installed_sources, tmp_path
):
    donor, master = installed_sources
    report = materialize_native_avm_library(
        tmp_path / "bundle" / f"{NATIVE_SCOPE}.pslx",
        constants_evidence=constants_evidence,
        source_project=donor,
        master_path=master,
    )
    root = ET.parse(report["library_path"]).getroot()
    definitions = {
        item.get("name"): item for item in root.findall("./definitions/Definition")
    }
    assert root.get("Target") == "Library"
    assert root.get("name") == NATIVE_SCOPE
    assert {
        "MMCAverageArm",
        "MMCAverageCoupling",
        CONTROL_NAME,
        "MMCCableLink",
        "Cable2",
    } <= set(definitions)
    arm_ports = definitions["MMCAverageArm"].findall("./svg/port")
    assert {
        item.get("name") for item in arm_ports if item.get("model") == "Natural"
    } == {
        "IN",
        "OUT",
    }
    control = definitions[CONTROL_NAME]
    assert control.find("./script/segment[@name='Fortran']") is not None
    cable = definitions["MMCCableLink"]
    assert len(cable.findall("./schematic/User[@defn='master:cable_interface']")) == 2
    assert len(cable.findall("./schematic/Wire[@classid='Cable']")) == 1
    assert Path(report["constants_path"]).is_file()
    assert (
        hashlib.sha256(Path(report["constants_path"]).read_bytes()).hexdigest()
        == report["constants_sha256"]
    )
    assert report["model_accepted"] is False


def test_full_fixture_wires_twelve_two_terminal_arms_to_two_three_phase_stations(
    constants_evidence, installed_sources, tmp_path
):
    donor, master = installed_sources
    report = materialize_native_avm_fixture(
        tmp_path / "fixture",
        constants_evidence=constants_evidence,
        source_project=donor,
        master_path=master,
    )
    root = ET.parse(report["project_path"]).getroot()
    main = root.find("./definitions/Definition[@name='Main']")
    users = main.findall("./schematic/User")
    assert (
        len(
            [
                item
                for item in users
                if item.get("defn") == f"{NATIVE_SCOPE}:MMCAverageArm"
            ]
        )
        == 12
    )
    assert len([item for item in users if item.get("defn") == "master:breakout"]) == 6
    assert len([item for item in users if item.get("defn") == "master:resistor"]) == 6
    assert len([item for item in users if item.get("defn") == "master:ground"]) == 1
    transformers = [item for item in users if item.get("defn") == "master:xfmr-3p2w"]
    for transformer in transformers:
        values = {
            parameter.get("name"): parameter.get("value")
            for parameter in transformer.findall("./paramlist/param")
        }
        assert values["CuL"] == "0.005 [pu]"
        assert values["NLL"] == "0.005 [pu]"
        assert values["Ideal"] == "1"
        assert values["YD1"] == "1"
        assert values["YD2"] == "0"
    sources = [item for item in users if item.get("defn") == "master:source3"]
    assert all(
        next(
            parameter.get("value")
            for parameter in source.findall("./paramlist/param")
            if parameter.get("name") == "Type"
        )
        == "4"
        for source in sources
    )
    assert (
        len(
            [
                item
                for item in users
                if item.get("defn") == f"{NATIVE_SCOPE}:MMCCableLink"
            ]
        )
        == 1
    )
    assert (
        len(
            [
                item
                for item in users
                if item.get("defn") == f"{NATIVE_SCOPE}:{CONTROL_NAME}"
            ]
        )
        == 2
    )
    assert report["topology"] == {
        "two_stations": True,
        "arm_count": 12,
        "phase_breakout_count": 2,
        "coupled_cable_count": 1,
        "control_kind": "scheduled_open_loop",
        "physical_power_control_closed": False,
    }
    assert report["channels"] == FIXTURE_CHANNELS
    assert report["model_accepted"] is False
    assert report["licensed_acceptance"] == "NOT_RUN"
    assert {
        "P_source:N",
        "P_transformer:G2",
        "V_source:N",
        "V_transformer:G2",
        "neutral_ground:A",
    } <= set(report["electrical_nets"]["Main"]["GND"])
    for prefix in ("P", "V"):
        assert {
            f"{prefix}_source:N3",
            f"{prefix}_source_breakout:N",
        } <= set(report["electrical_nets"]["Main"][prefix + "_SOURCE_VECTOR"])
        assert {
            f"{prefix}_grid_merger:N",
            f"{prefix}_transformer:N1",
        } <= set(report["electrical_nets"]["Main"][prefix + "_GRID"])
        for phase_index, phase in enumerate("ABC", start=1):
            assert {
                f"{prefix}_source_breakout:N{phase_index}",
                f"{prefix}_grid_resistor_{phase}:A",
            } <= set(report["electrical_nets"]["Main"][prefix + "_SOURCE_" + phase])
            assert {
                f"{prefix}_grid_resistor_{phase}:B",
                f"{prefix}_grid_merger:N{phase_index}",
            } <= set(report["electrical_nets"]["Main"][prefix + "_GRID_" + phase])
    hierarchy = root.findall("./hierarchy/call/call/call")
    assert len(hierarchy) == 13
    assert not any(item.get("name", "").endswith(CONTROL_NAME) for item in hierarchy)
    assert [int(item.get("z")) for item in hierarchy] == [
        30,
        40,
        50,
        60,
        70,
        80,
        110,
        120,
        130,
        140,
        150,
        160,
        170,
    ]
    assert [int(item.get("instance")) for item in hierarchy[:-1]] == [
        0,
        1,
        2,
        3,
        11,
        5,
        4,
        10,
        6,
        7,
        8,
        9,
    ]


@pytest.mark.parametrize("mutation", ["arm", "cable", "source_hash"])
def test_native_fixture_audit_rejects_missing_components_and_changed_inputs(
    constants_evidence, installed_sources, tmp_path, mutation
):
    donor, master = installed_sources
    report = materialize_native_avm_fixture(
        tmp_path / "fixture",
        constants_evidence=constants_evidence,
        source_project=donor,
        master_path=master,
    )
    if mutation == "source_hash":
        report["library"]["library_sha256"] = "0" * 64
    else:
        tree = ET.parse(report["project_path"])
        main = tree.find("./definitions/Definition[@name='Main']/schematic")
        suffix = "MMCAverageArm" if mutation == "arm" else "MMCCableLink"
        main.remove(
            next(
                item
                for item in main.findall("User")
                if item.get("defn", "").endswith(suffix)
            )
        )
        tree.write(report["project_path"], encoding="utf-8")
    with pytest.raises(ValueError):
        audit_native_avm_fixture(report["project_path"], report)


def test_runtime_audit_requires_an_explicit_finalized_library_hash(
    constants_evidence, installed_sources, tmp_path
):
    donor, master = installed_sources
    report = materialize_native_avm_fixture(
        tmp_path / "fixture",
        constants_evidence=constants_evidence,
        source_project=donor,
        master_path=master,
    )
    library = Path(report["library"]["library_path"])
    library.write_bytes(library.read_bytes() + b"\n")
    finalized = hashlib.sha256(library.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="library changed"):
        audit_native_avm_fixture(report["project_path"], report)
    assert audit_native_avm_fixture(
        report["project_path"],
        report,
        finalized_library_sha256=finalized,
    )["arm_count"] == 12


def test_native_modulator_stays_bounded_and_reverses_only_phase_offset():
    import math

    modulation = 0.82
    for time in (0.0, 0.099, 0.1, 0.299, 0.3, 0.499):
        offset = math.radians(5.0 if time < 0.3 else -5.0)
        phase = 2 * math.pi * 60 * time + offset
        commands = []
        for angle in (phase, phase - 2 * math.pi / 3, phase + 2 * math.pi / 3):
            value = modulation * math.sin(angle)
            commands.extend((0.5 * (1 - value), 0.5 * (1 + value)))
        assert min(commands) >= 0.09
        assert max(commands) <= 0.91
        assert all(
            a + b == pytest.approx(1.0) for a, b in zip(commands[::2], commands[1::2])
        )
