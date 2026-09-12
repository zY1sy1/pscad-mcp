"""Native XML and signed physical contracts for the averaged half-bridge arm."""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pscad_mcp.core.definition_metadata import read_definition_metadata_document


@pytest.fixture(scope="module")
def companion():
    module = "pscad_mcp.hvdc.builders.mmc.avm_companion"
    assert importlib.util.find_spec(module) is not None, (
        "Native arm generator is missing"
    )
    return importlib.import_module(module)


@pytest.fixture(scope="module")
def master():
    path = Path(
        os.environ.get(
            "PSCAD_MASTER_LIBRARY", r"C:\Program Files (x86)\PSCAD46\master.pslx"
        )
    )
    if not path.is_file():
        pytest.skip(
            "Installed PSCAD 4.6.2 Master metadata is required, no license is used"
        )
    return path


def _parameters(element):
    return {
        item.get("name"): item.get("value")
        for item in element.findall("./paramlist/param")
    }


@pytest.fixture
def library(companion, master, tmp_path):
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    target = tmp_path / "mmc_average_arm.pslx"
    report = companion.materialize_average_arm_library(target, master_path=master)
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before
    assert report["master_sha256_before"] == report["master_sha256_after"] == before
    assert report["licensed_acceptance"] == "NOT_RUN"
    return ET.parse(target).getroot(), report


def test_library_is_native_repository_authored_assembly(library):
    root, report = library
    assert root.tag == "project"
    assert root.get("Target") == "Library"
    assert root.get("version") == "4.6.2"
    definitions = {
        item.get("name"): item for item in root.findall("./definitions/Definition")
    }
    assert set(definitions) == {
        "Station",
        "Main",
        "MMCAverageArm",
        "MMCAverageCoupling",
    }
    arm = definitions["MMCAverageArm"]
    assert arm.get("classid") == "UserCmpDefn"
    ports = {port.get("name"): port for port in arm.findall("./svg/port")}
    assert {name for name, port in ports.items() if port.get("model") == "Natural"} == {
        "IN",
        "OUT",
    }
    for name in ("M", "BLOCK"):
        assert ports[name].get("model") == "Transfer"
        assert ports[name].get("mode") == "Input"
        assert ports[name].get("type") == "Real"
    for name in ("V_INSERTED", "I_ARM", "ENERGY", "V_CAP_EQ", "V_CAP_TOTAL"):
        assert ports[name].get("mode") == "Output"
        assert ports[name].get("dim") == "1"
    assert report["voltage_convention"]["full_stack_voltage"] == "2 * V_CAP_EQ"
    assert report["voltage_convention"]["physical_capacitance_F"] == "C_eq_F / 4"
    assert report["initialization"] == "physical_charge_from_zero_or_pscad_snapshot"


def test_native_branches_preserve_signed_storage_and_blocked_diode_paths(library):
    root, report = library
    arm = root.find("./definitions/Definition[@name='MMCAverageArm']")
    components = {item.get("name"): item for item in arm.findall("./schematic/User")}
    expected_types = {
        "arm_resistance": "master:varrlc",
        "arm_inductance": "master:varrlc",
        "normal_voltage": "master:source_1",
        "normal_disconnect": "master:breaker1",
        "positive_clamp": "master:peswitch",
        "clamp_voltage": "master:source_1",
        "negative_bypass": "master:peswitch",
        "storage_current": "master:src_ccin_1",
        "storage_capacitor": "master:varrlc",
        "capacitance_conversion": "master:gain",
        "arm_current_meter": "master:ammeter",
        "normal_current_meter": "master:ammeter",
        "clamp_current_meter": "master:ammeter",
        "capacitor_current_meter": "master:ammeter",
    }
    for role, definition in expected_types.items():
        assert components[role].get("defn") == definition
    for role in ("normal_voltage", "clamp_voltage"):
        values = _parameters(components[role])
        assert {
            key: values[key] for key in ("Type", "Grnd", "Spec", "Cntrl", "AC", "Tc")
        } == {
            "Type": "6",
            "Grnd": "0",
            "Spec": "0",
            "Cntrl": "1",
            "AC": "0",
            "Tc": "0.0 [s]",
        }
    assert _parameters(components["storage_capacitor"])["C"] == "CAP_C_UF"
    assert _parameters(components["arm_resistance"])["R"] == "R_arm_ohm"
    assert _parameters(components["arm_inductance"])["L"] == "L_arm_H"
    assert _parameters(components["capacitance_conversion"])["G"] == "250000.0"
    for role, kind in (
        ("arm_resistance", "0"),
        ("arm_inductance", "1"),
        ("storage_capacitor", "2"),
    ):
        assert _parameters(components[role])["RLC"] == kind
        assert _parameters(components[role])["dLdC"] == "0"
    imports = {
        _parameters(item).get("Name")
        for item in components.values()
        if item.get("defn") == "master:import"
    }
    assert {p.get("name") for p in arm.findall("./form/category/parameter")} <= imports
    assert _parameters(components["normal_disconnect"])["NAME"] == "ARM_OPEN"
    for role in ("positive_clamp", "negative_bypass"):
        assert _parameters(components[role])["Type"] == "0"
        assert _parameters(components[role])["SNUB"] == "0"
    nets = report["electrical_nets"]["MMCAverageArm"]
    assert {"normal_voltage:NA", "normal_current_meter:N2"} <= set(nets["NORMAL_POS"])
    assert {"normal_voltage:NB", "normal_disconnect:B"} <= set(nets["NORMAL_NEG"])
    assert {"positive_clamp:DP", "clamp_current_meter:N2"} <= set(nets["CLAMP_IN"])
    assert {"positive_clamp:DN", "clamp_voltage:NA"} <= set(nets["CLAMP_POS"])
    assert {"negative_bypass:DP", "clamp_voltage:NB"} <= set(nets["OUT"])
    assert {"negative_bypass:DN", "arm_inductance:B"} <= set(nets["STACK_IN"])
    assert "storage_current:A" in nets["CAP_POS"]
    assert "storage_current:B" in nets["GND"]
    assert report["blocked_state_path"] == "half_bridge_diode_equivalent"
    assert report["intrinsic_dc_fault_blocking"] is False


def test_every_authored_wire_uses_checked_physical_endpoints(library, master):
    root, report = library
    native = read_definition_metadata_document(master.read_bytes())
    local = read_definition_metadata_document(ET.tostring(root))
    for route in report["routes"]:
        definition = root.find(
            f"./definitions/Definition[@name='{route['definition']}']"
        )
        wire = definition.find(f"./schematic/Wire[@id='{route['wire_id']}']")
        points = [
            (int(wire.get("x")) + int(v.get("x")), int(wire.get("y")) + int(v.get("y")))
            for v in wire.findall("vertex")
        ]
        assert [list(point) for point in points] == route["vertices"]
        assert points[0] != points[-1]
        for endpoint, point in zip(route["endpoints"], (points[0], points[-1])):
            component = definition.find(
                f"./schematic/User[@id='{endpoint['component_id']}']"
            )
            scope, name = component.get("defn").split(":", 1)
            metadata = (native if scope == "master" else local)[name][0]
            port = next(
                p
                for p in metadata.ports
                if p.name == endpoint["port"] and p.occurrence == endpoint["occurrence"]
            )
            assert (
                int(component.get("x")) + port.x,
                int(component.get("y")) + port.y,
            ) == point
            assert ("electrical" if port.model == "Natural" else "data") == route[
                "kind"
            ]
    assert report["route_contacts_verified"] is True


def test_all_master_defaults_are_authored_before_native_normalization(library, master):
    root, _ = library
    metadata = read_definition_metadata_document(master.read_bytes())
    for component in root.findall("./definitions/Definition/schematic/User"):
        scope, name = component.get("defn").split(":", 1)
        if scope == "master":
            assert set(_parameters(component)) == set(metadata[name][0].parameters)


def test_generator_rejects_changed_master_contract_and_existing_outputs(
    companion, master, tmp_path
):
    target = tmp_path / "must_not_overwrite.pslx"
    target.write_text("owned input", encoding="ascii")
    with pytest.raises((ValueError, FileExistsError)):
        companion.materialize_average_arm_library(target, master_path=master)
    assert target.read_text(encoding="ascii") == "owned input"
    changed = ET.fromstring(master.read_bytes())
    changed.find(
        "./definitions/Definition[@name='src_ccin_1']/svg/port[@name='A']"
    ).set("x", "18")
    invalid = tmp_path / "changed_master.pslx"
    invalid.write_bytes(ET.tostring(changed))
    with pytest.raises(ValueError, match="Master"):
        companion.materialize_average_arm_library(
            tmp_path / "invalid.pslx", master_path=invalid
        )
    assert not (tmp_path / "invalid.pslx").exists()


@pytest.mark.parametrize(
    "mutation", ["inactive_terminal", "vector_terminal", "changed_capacitor_unit"]
)
def test_master_active_scalar_and_unit_contract_is_fail_closed(
    companion, master, tmp_path, mutation
):
    root = ET.fromstring(master.read_bytes())
    if mutation == "inactive_terminal":
        ports = root.findall(
            "./definitions/Definition[@name='source_1']/svg/port[@name='NB']"
        )
        ports[1].text = "false"
    elif mutation == "vector_terminal":
        root.find(
            "./definitions/Definition[@name='src_ccin_1']/svg/port[@name='A']"
        ).set("dim", "3")
    else:
        root.find(
            "./definitions/Definition[@name='varrlc']/form/category/parameter[@name='C']"
        ).set("unit", "F")
    modified = tmp_path / "modified_master.pslx"
    modified.write_bytes(ET.tostring(root))
    with pytest.raises(ValueError, match="Master"):
        companion.materialize_average_arm_library(
            tmp_path / "should_not_exist.pslx", master_path=modified
        )
    assert not (tmp_path / "should_not_exist.pslx").exists()


def test_fixture_has_actual_arm_and_all_four_operating_windows(
    companion, master, tmp_path
):
    report = companion.materialize_average_arm_fixture(
        tmp_path / "fixture", master_path=master
    )
    root = ET.parse(report["project_path"]).getroot()
    assert root.get("Target") == "EMTDC"
    arm = root.find(
        "./definitions/Definition[@name='Main']/schematic/User[@name='arm_under_test']"
    )
    assert arm is not None and arm.get("defn").endswith(":MMCAverageArm")
    module_call = root.find("./hierarchy/call/call/call")
    assert module_call is not None
    assert module_call.attrib == {
        "link": arm.get("id"),
        "name": arm.get("defn"),
        "z": "60",
        "view": "false",
        "instance": "0",
    }
    assert set(report["operating_windows"]) == {
        "charge",
        "discharge",
        "blocked_charge",
        "blocked_bypass",
    }
    assert {
        "M",
        "BLOCK",
        "I_ARM",
        "V_ARM",
        "I_CAP",
        "I_NORMAL",
        "I_CLAMP",
        "I_BYPASS",
        "ENERGY",
        "V_CAP_TOTAL",
        "V_CAP_EQ",
        "V_INSERTED",
    } <= set(report["channels"])
    assert report["licensed_acceptance"] == "NOT_RUN"


@pytest.mark.parametrize(
    "current,blocked,expected_ratio",
    [(0.2, False, 0.5), (-0.2, False, 0.5), (0.2, True, 1.0), (-0.2, True, 0.0)],
)
def test_signed_physical_energy_contract(companion, current, blocked, expected_ratio):
    parameters = companion.AverageArmParameters()
    vfull = 10.0
    result = companion.average_arm_reference(
        v_cap_total_kv=vfull,
        i_arm_ka=current,
        insertion=0.5,
        blocked=blocked,
        parameters=parameters,
    )
    assert result["i_cap_ka"] == pytest.approx(current * expected_ratio)
    assert result["p_cap_mw"] == pytest.approx(vfull * current * expected_ratio)
    assert result["v_cap_eq_kv"] == 5.0
    assert result["energy_mj"] == pytest.approx(0.5 * parameters.C_eq_F * 5.0**2)
    assert (
        math.copysign(1, result["p_cap_mw"]) == math.copysign(1, current)
        if expected_ratio
        else result["p_cap_mw"] == 0
    )
    assert result["arm_ohmic_loss_mw"] == pytest.approx(
        parameters.R_arm_ohm * current**2
    )


def test_nonohmic_loss_is_distinct_from_physical_arm_resistance(companion):
    parameters = companion.AverageArmParameters(P_nonohmic_MW=0.02)
    result = companion.average_arm_reference(
        v_cap_total_kv=10,
        i_arm_ka=-0.2,
        insertion=0.5,
        blocked=False,
        parameters=parameters,
    )
    assert result["p_cap_mw"] == pytest.approx(-1.02)
    assert result["i_cap_ka"] == pytest.approx(-0.102)
    assert result["arm_ohmic_loss_mw"] == pytest.approx(0.004)
