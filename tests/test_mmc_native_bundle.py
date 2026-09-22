from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc import cable_constants
from pscad_mcp.hvdc.builders.mmc.avm_companion import AverageArmParameters
from pscad_mcp.hvdc.builders.mmc.native_bundle import (
    CLOSED_LOOP_CONTROL_NAME,
    CONTROL_NAME,
    FIXTURE_CHANNELS,
    MEASUREMENT_NAME,
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
        CLOSED_LOOP_CONTROL_NAME,
        MEASUREMENT_NAME,
        "MMCControlErrors",
        "MMCModulationSynthesis",
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
    measurements = definitions[MEASUREMENT_NAME]
    measurement_ports = {
        item.get("name"): (item.get("mode"), item.get("type"))
        for item in measurements.findall("./svg/port")
    }
    assert set(measurement_ports) == {
        "VA",
        "VB",
        "VC",
        "IA",
        "IB",
        "IC",
        "VDC",
        "IDC",
        "P",
        "Q",
    }
    assert all(measurement_ports[name] == ("Input", "Real") for name in ("VA", "VB", "VC", "IA", "IB", "IC", "VDC", "IDC"))
    assert all(measurement_ports[name] == ("Output", "Real") for name in ("P", "Q"))
    controller = definitions[CLOSED_LOOP_CONTROL_NAME]
    assert len(controller.findall("./schematic/User[@defn='master:pi_ctlr']")) == 3
    assert len(controller.findall("./schematic/User[@defn='master:realpole']")) == 12
    controller_components = {
        component.get("name"): component
        for component in controller.findall("./schematic/User")
    }
    lower_limit = controller_components["voltage_power_lower_limit"]
    reference_filter = controller_components["voltage_reference_ramp"]
    assert reference_filter.find("./paramlist/param[@name='Reset']").get("value") == "2"
    assert reference_filter.find("./paramlist/param[@name='YO']").get("value") == "0.0"
    assert lower_limit.find("./paramlist/param[@name='G']").get("value") == "-1.0"
    assert controller_components["voltage_pi"].find(
        "./paramlist/param[@name='YLO']"
    ).get("value") == "POWER_CORRECTION_MIN"
    for prefix, kp, ti, error in (
        ("active", 0.003, 0.5, 1000.0),
        ("reactive", 0.00005, 0.5, 1000.0),
    ):
        gain = {
            p.get("name"): p.get("value")
            for p in controller_components[prefix + "_error_gain"].findall("./paramlist/param")
        }
        native_pi = {
            p.get("name"): p.get("value")
            for p in controller_components[prefix + "_pi"].findall("./paramlist/param")
        }
        assert gain["G"] == ("Kp_Active" if prefix == "active" else "Kp_Reactive")
        assert float(native_pi["GP"]) == 1.0
        # A native parallel PI must reproduce the specified series gain,
        # including its integral slope rather than only proportional gain.
        step_response = float(native_pi["GP"]) * kp * error + kp * error * 0.01 / ti
        assert step_response == pytest.approx(kp * error * (1 + 0.01 / ti))
    assert (
        controller.find(
            f"./schematic/User[@defn='{NATIVE_SCOPE}:MMCControlErrors']"
        )
        is not None
    )
    error_script = definitions["MMCControlErrors"].find(
        "./script/segment[@name='Fortran']"
    ).text
    assert "$P_MEAS - PREF" in error_script
    assert "$VDC_REFERENCE - $VDC_MEAS" in error_script
    assert "$P_MEAS + PREF - $POWER_CORRECTION" in error_script
    assert "$Q_MEAS - SCALE * $Q_Order_MVAr" in error_script
    assert (
        controller.find(
            f"./schematic/User[@defn='{NATIVE_SCOPE}:MMCModulationSynthesis']"
        )
        is not None
    )
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
    assert len([item for item in users if item.get("defn") == "master:ammeter"]) == 8
    assert len([item for item in users if item.get("defn") == "master:voltmeter"]) == 8
    assert (
        len(
            [
                item
                for item in users
                if item.get("defn") == f"{NATIVE_SCOPE}:{MEASUREMENT_NAME}"
            ]
        )
        == 2
    )
    assert len([item for item in users if item.get("defn") == "master:ground"]) == 1
    arms = [
        item
        for item in users
        if item.get("defn") == f"{NATIVE_SCOPE}:MMCAverageArm"
    ]
    assert all(
        float(
            next(
                parameter.get("value")
                for parameter in arm.findall("./paramlist/param")
                if parameter.get("name") == "R_on_ohm"
            )
        )
        >= 0.001
        for arm in arms
    )
    transformers = [item for item in users if item.get("defn") == "master:xfmr-3p2w"]
    for transformer in transformers:
        values = {
            parameter.get("name"): parameter.get("value")
            for parameter in transformer.findall("./paramlist/param")
        }
        assert values["CuL"] == "0.0 [pu]"
        assert values["NLL"] == "0.0 [pu]"
        assert values["Ideal"] == "1"
        assert values["YD1"] == "0"
        assert values["YD2"] == "1"
    sources = [item for item in users if item.get("defn") == "master:source3"]
    assert all(
        next(
            parameter.get("value")
            for parameter in source.findall("./paramlist/param")
            if parameter.get("name") == "Type"
        )
        == "3"
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
        "P_transformer:G1",
        "V_source:N",
        "V_transformer:G1",
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
                f"{prefix}_grid_current_{phase}:N1",
            } <= set(report["electrical_nets"]["Main"][prefix + "_GRID_R_" + phase])
            assert {
                f"{prefix}_grid_current_{phase}:N2",
                f"{prefix}_grid_merger:N{phase_index}",
                f"{prefix}_phase_voltage_{phase}:N1",
            } <= set(report["electrical_nets"]["Main"][prefix + "_GRID_" + phase])
        assert {
            f"{prefix}_dc_current:N2",
            f"DC_CABLE:{'SEND_POS' if prefix == 'P' else 'RECV_POS'}",
        } <= set(report["electrical_nets"]["Main"][prefix + "_CABLE_POS"])
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


def test_full_fixture_materializes_parametric_electrical_and_runtime_values(
    constants_evidence, installed_sources, tmp_path
):
    donor, master = installed_sources
    arms = AverageArmParameters(
        C_eq_F=8e-5,
        L_arm_H=0.04,
        R_arm_ohm=0.12,
        P_nonohmic_MW=0.5,
    )
    report = materialize_native_avm_fixture(
        tmp_path / "parametric-fixture",
        constants_evidence=constants_evidence,
        source_project=donor,
        master_path=master,
        project_name="MMC_PARAM_AVM",
        frequency_hz=50.0,
        station_p_ac_voltage_kv=180.0,
        station_vdc_ac_voltage_kv=190.0,
        station_p_grid_r_ohm=0.5,
        station_p_grid_x_ohm=5.0,
        station_vdc_grid_r_ohm=0.75,
        station_vdc_grid_x_ohm=6.0,
        transformer_rating_mva=825.0,
        station_p_valve_voltage_kv=250.0,
        station_vdc_valve_voltage_kv=260.0,
        modulation_index=0.8,
        control_kind="closed_loop",
        active_power_order_mw=750.0,
        reactive_power_order_mvar=25.0,
        vdc_order_kv=500.0,
        deblock_time_s=0.2,
        reversal_time_s=0.7,
        simulation_duration_s=1.0,
        time_step_s=50e-6,
        output_step_s=100e-6,
        arm_parameters=arms,
    )

    root = ET.parse(report["project_path"]).getroot()
    assert root.get("name") == "MMC_PARAM_AVM"
    assert Path(report["project_path"]).name == "MMC_PARAM_AVM.pscx"
    settings = {
        item.get("name"): item.get("value")
        for item in root.findall("./paramlist[@name='Settings']/param")
    }
    assert settings["time_duration"] == "1"
    assert settings["time_step"] == "50"
    assert settings["sample_step"] == "100"
    assert settings["output_filename"] == "MMC_PARAM_AVM.out"

    users = {
        item.get("name"): item
        for item in root.findall("./definitions/Definition[@name='Main']/schematic/User")
    }
    p_source = {
        item.get("name"): item.get("value")
        for item in users["P_source"].findall("./paramlist/param")
    }
    v_source = {
        item.get("name"): item.get("value")
        for item in users["V_source"].findall("./paramlist/param")
    }
    assert p_source["Vm"] == p_source["Es"] == "180 [kV]"
    assert v_source["Vm"] == v_source["Es"] == "190 [kV]"
    assert float(p_source["Z1"].split()[0]) == pytest.approx((0.5**2 + 5.0**2) ** 0.5)
    assert float(v_source["Z1"].split()[0]) == pytest.approx((0.75**2 + 6.0**2) ** 0.5)

    for prefix, primary, secondary in (("P", 180.0, 250.0), ("V", 190.0, 260.0)):
        transformer = {
            item.get("name"): item.get("value")
            for item in users[prefix + "_transformer"].findall("./paramlist/param")
        }
        assert transformer["Tmva"] == "825 [MVA]"
        assert transformer["V1"] == f"{primary:g} [kV]"
        assert transformer["V2"] == f"{secondary:g} [kV]"
        control = {
            item.get("name"): item.get("value")
            for item in users[prefix + "_controller"].findall("./paramlist/param")
        }
        assert float(control["Frequency_Hz"]) == 50.0
        assert float(control["Base_Modulation"]) == 0.8
        assert float(control["Deblock_Time_s"]) == 0.2
        assert float(control["Reversal_Time_s"]) == 0.7
        assert float(control["P_Order_MW"]) == 750.0
        assert float(control["Q_Order_MVAr"]) == 25.0
        assert float(control["Vdc_Order_kV"]) == 500.0
        assert float(control["Control_Mode"]) == (0.0 if prefix == "P" else 1.0)

    for name, component in users.items():
        if not name.endswith(("_UPPER", "_LOWER")):
            continue
        values = {
            item.get("name"): item.get("value")
            for item in component.findall("./paramlist/param")
        }
        assert float(values["C_eq_F"]) == arms.C_eq_F
        assert float(values["L_arm_H"]) == arms.L_arm_H
        assert float(values["R_arm_ohm"]) == arms.R_arm_ohm
        assert float(values["P_nonohmic_MW"]) == arms.P_nonohmic_MW
    assert report["parameters"]["transformer_rating_mva"] == 825.0
    assert report["parameters"]["cable_length_km"] == 300.0
    assert report["topology"]["control_kind"] == "closed_loop"
    assert report["topology"]["physical_power_control_closed"] is True


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
