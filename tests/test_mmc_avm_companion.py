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
        "normal_current_meter": "master:ammeter",
        "clamp_current_meter": "master:ammeter",
        "capacitor_current_meter": "master:ammeter",
    }
    for role, definition in expected_types.items():
        assert components[role].get("defn") == definition
    assert components["arm_resistance"].find("./paramlist/param[@name='I']").get("value") == "ARM_I"
    assert {"arm_in:N", "arm_resistance:A"} <= set(report["electrical_nets"]["MMCAverageArm"]["IN"])
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


def test_switch_on_resistance_stays_above_pscad_short_circuit_threshold(
    companion, library
):
    root, _ = library
    parameters = companion.AverageArmParameters()
    assert parameters.R_on_ohm == 0.001
    with pytest.raises(ValueError, match="audited ranges"):
        companion.AverageArmParameters(R_on_ohm=0.0005)

    arm = root.find("./definitions/Definition[@name='MMCAverageArm']")
    components = {item.get("name"): item for item in arm.findall("./schematic/User")}
    for role in (
        "normal_disconnect",
        "positive_clamp",
        "negative_bypass",
        "capacitor_reverse_clamp",
    ):
        assert _parameters(components[role])["RON"] == "R_on_ohm"
    assert "R_on_ohm >= 0.001" in arm.find(
        "./script/segment[@name='Checks']"
    ).text


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


def test_delayed_loss_sink_cannot_drive_an_empty_capacitor_negative(companion):
    parameters = companion.AverageArmParameters(C_eq_F=6.510416666666667e-5, P_nonohmic_MW=1.1)
    step = 50e-6
    voltage = previous_voltage = 1.0
    energy = 0.125 * parameters.C_eq_F * voltage**2
    for _ in range(500):
        current = companion.limited_nonohmic_current(previous_voltage, parameters, step)
        next_voltage = voltage - step * current / (0.25 * parameters.C_eq_F)
        next_energy = 0.125 * parameters.C_eq_F * next_voltage**2
        assert 0 <= next_voltage <= voltage
        assert 0 <= next_energy <= energy
        previous_voltage, voltage, energy = voltage, next_voltage, next_energy
    assert voltage < 1e-20
    # At the rated capacitor voltage, the specified loss power is preserved.
    assert companion.limited_nonohmic_current(640.0, parameters, step) * 640.0 == pytest.approx(1.1)


def test_native_coupling_tracks_passive_rlc_and_converges_with_timestep(companion):
    # A constant-insertion arm driven by n*640 kV has the analytic damped
    # RLC response below. This exposes energy injection hidden by a fixture
    # that imposes arm current independently of inserted voltage.
    resistance, inductance, capacitance, insertion = 0.15, 0.05, 6.510416666666668e-5 / 4, 0.5
    decay = resistance / (2 * inductance)
    omega = math.sqrt(insertion**2 / (inductance * capacitance) - decay**2)

    def integrate(step):
        current, previous_current = 0.0, 0.0
        capacitor, previous_capacitor = 630.0, 630.0
        maximum_error = 0.0
        for index in range(1, round(0.2 / step) + 1):
            source = insertion * companion.predict_coupled_capacitor_voltage(
                capacitor, insertion * current, capacitance, step
            )
            previous_source = insertion * companion.predict_coupled_capacitor_voltage(
                previous_capacitor, insertion * previous_current, capacitance, step
            )
            next_current = (
                (2 * inductance / step - resistance) * current
                + 2 * insertion * 640 - source - previous_source
            ) / (2 * inductance / step + resistance)
            next_capacitor = capacitor + step * insertion * (
                current + previous_current
            ) / (2 * capacitance)
            instant = index * step
            reference = 640 - 10 * math.exp(-decay * instant) * (
                math.cos(omega * instant) + decay / omega * math.sin(omega * instant)
            )
            maximum_error = max(maximum_error, abs(next_capacitor - reference))
            previous_current, current = current, next_current
            previous_capacitor, capacitor = capacitor, next_capacitor
        return maximum_error

    coarse, fine = integrate(50e-6), integrate(25e-6)
    assert coarse < 0.3
    assert fine < coarse * 0.51


@pytest.mark.parametrize("current_sign", (1.0, -1.0))
def test_native_variable_insertion_preserves_port_energy(library, tmp_path, current_sign):
    from tests.test_mmc_native_dq import _run_native_equations

    # Drive the actual generated equations with periodic arm current and a
    # varying insertion ratio. The network solves a trapezoidal capacitor;
    # the coupling sees the previous network current, just as EMTDC Dsdyn does.
    # Constant-insertion RLC tests cannot reveal a ratio/current time mismatch.
    definition = library[0].find("./definitions/Definition[@name='MMCAverageCoupling']")
    residuals = []
    for step in (50e-6, 25e-6):
        rows = _run_native_equations(
            tmp_path, "MMCAverageCoupling", definition=definition,
            declarations="""real(8) :: capacitor, previous_storage, current_now, source_power
real(8) :: previous_power, supplied, initial_energy, physical_capacitance""",
            initialize=f"""DELT = {step}
PAR_C_eq_F = 0.0001041666666666667
PAR_P_nonohmic_MW = 0.0
physical_capacitance = PAR_C_eq_F / 4.0
capacitor = 640.0
previous_storage = 0.0
previous_power = 0.0
supplied = 0.0
initial_energy = 0.0""",
            loop=f"""SIG_M = 0.5 + 0.35 * SIN(6.283185307179586 * 60.0 * TIME)
SIG_VCAP = capacitor
SIG_INORMAL = {current_sign} * (-0.35 * 1.25 * COS(0.35) + 1.25 * SIN(6.283185307179586 * 60.0 * (TIME - DELT) + 0.35))
current_now = {current_sign} * (-0.35 * 1.25 * COS(0.35) + 1.25 * SIN(6.283185307179586 * 60.0 * TIME + 0.35))""",
            observations="""capacitor = capacitor + DELT * (SIG_ISTORE + previous_storage) / (2.0 * physical_capacitance)
source_power = SIG_VNORMAL * current_now
if (sample == NINT(0.1 / DELT)) initial_energy = 0.5 * physical_capacitance * capacitor**2
if (sample > NINT(0.1 / DELT)) supplied = supplied + 0.5 * DELT * (source_power + previous_power)
previous_storage = SIG_ISTORE
previous_power = source_power
if (sample == NINT(0.5 / DELT)) print *, (supplied - (0.5 * physical_capacitance * capacitor**2 - initial_energy)) / 0.4""",
            steps=round(0.5 / step),
        )
        residuals.append(abs(rows[0][0]))
    assert residuals[0] < 0.001  # < 1 kW; old coupling injects about 1 MW/arm
    assert residuals[1] < residuals[0] * 0.3


def test_empty_native_capacitor_cannot_supply_reverse_clamp_current(library, tmp_path):
    from tests.test_mmc_native_dq import _run_native_equations

    definition = library[0].find("./definitions/Definition[@name='MMCAverageCoupling']")
    rows = _run_native_equations(
        tmp_path, "MMCAverageCoupling", definition=definition,
        declarations="", initialize="PAR_C_eq_F = 0.00019\nPAR_P_nonohmic_MW = 0.0\nDELT = 0.00001",
        loop="""SIG_BLOCK = 1.0
SIG_M = 0.0
SIG_INORMAL = 0.0
SIG_VCAP = 0.0
SIG_ICLAMP = -0.005
if (sample == 2) SIG_ICLAMP = 0.005
if (sample == 3) SIG_VCAP = 500.0
""",
        observations="print *, SIG_ISTORE, SIG_VEQ, SIG_W", steps=3,
    )
    # A reverse/leakage current from the delayed diode solve cannot draw
    # charge from an empty stack. Charging and charged-stack discharge remain
    # physical currents; the reported capacitor voltage is never clipped.
    assert rows[0][0] == 0.0
    assert rows[1][0] == pytest.approx(0.005)
    assert rows[2][0] == pytest.approx(-0.005)
    assert rows[2][1] == pytest.approx(250.0)
