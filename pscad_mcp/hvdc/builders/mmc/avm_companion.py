"""Repository-authored native PSCAD averaged half-bridge arm and isolated fixture.

The public equivalent voltage is half the physical stack voltage. Consequently
Cphysical = C_eq_F / 4 and W[MJ] = C_eq_F * V_CAP_EQ[kV]**2 / 2.
Only arithmetic coupling is authored here; EMTDC solves the capacitor, arm R/L,
current-source branch, voltage-source branches, breaker, and diode branches.
This generator does not establish licensed or complete-converter acceptance.
"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from ....core.definition_metadata import read_definition_metadata_document

LIBRARY_SCOPE = "mmc_average_arm"
OUTPUT_UNITS = {
    "V_INSERTED": "kV",
    "I_ARM": "kA",
    "ENERGY": "MJ",
    "V_CAP_EQ": "kV",
    "V_CAP_TOTAL": "kV",
    "I_NORMAL": "kA",
    "I_CLAMP": "kA",
    "I_BYPASS": "kA",
    "I_CAP": "kA",
    "V_ARM": "kV",
    "P_NONOHMIC": "MW",
    "P_SWITCH": "MW",
}
OPERATING_WINDOWS = {
    "charge": (0.025, 0.055),
    "discharge": (0.075, 0.085),
    "blocked_charge": (0.11, 0.13),
    "blocked_bypass": (0.16, 0.18),
}
MIN_SWITCH_ON_RESISTANCE_OHM = 1e-3
CAPACITOR_FEEDBACK_ADVANCE_STEPS = 2.0
VOLTAGE_CONVENTION = {
    "equivalent_voltage_target": "rated_dc_voltage_kv / 2",
    "full_stack_voltage": "2 * V_CAP_EQ",
    "physical_capacitance_F": "C_eq_F / 4",
    "energy_MJ": "0.5 * C_eq_F * V_CAP_EQ_kV**2",
    "positive_arm_current": "IN to OUT",
    "inserted_voltage": "stack node after arm R/L minus OUT",
    "bypass_current": "OUT to stack node, opposite positive arm current",
}


@dataclass(frozen=True)
class AverageArmParameters:
    C_eq_F: float = 0.004
    L_arm_H: float = 0.02
    R_arm_ohm: float = 0.1
    P_nonohmic_MW: float = 0.0
    V_loss_floor_kV: float = 0.01
    R_on_ohm: float = MIN_SWITCH_ON_RESISTANCE_OHM
    R_off_ohm: float = 1e8
    V_diode_kV: float = 0.0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be finite and real")
            if value < 0 or (
                name not in {"R_arm_ohm", "P_nonohmic_MW", "V_diode_kV"} and value == 0
            ):
                raise ValueError(f"{name} is outside its physical range")
        if (
            not 1e-9 <= self.L_arm_H <= 1e6
            or self.R_on_ohm < MIN_SWITCH_ON_RESISTANCE_OHM
            or self.R_off_ohm < 1
            or self.R_off_ohm <= self.R_on_ohm
        ):
            raise ValueError(
                "Native inductance and switch resistances are outside their audited ranges"
            )
        if self.V_diode_kV > 10:
            raise ValueError("Native diode forward drop exceeds the Master range")


def average_arm_reference(
    *,
    v_cap_total_kv: float,
    i_arm_ka: float,
    insertion: float,
    blocked: bool,
    parameters: AverageArmParameters,
) -> dict[str, float]:
    """Ideal continuous-time reference, never a substitute for native evidence."""
    if any(not math.isfinite(value) for value in (v_cap_total_kv, i_arm_ka, insertion)):
        raise ValueError("Physical reference inputs must be finite")
    if v_cap_total_kv < 0 or not 0 <= insertion <= 1 or not isinstance(blocked, bool):
        raise ValueError("Physical reference inputs are outside their operating domain")
    ratio = (1.0 if i_arm_ka > 0 else 0.0) if blocked else insertion
    loss_current = (
        parameters.P_nonohmic_MW / max(v_cap_total_kv, parameters.V_loss_floor_kV)
        if v_cap_total_kv > 0
        else 0.0
    )
    current = ratio * i_arm_ka - loss_current
    return {
        "i_cap_ka": current,
        "p_cap_mw": v_cap_total_kv * current,
        "v_inserted_ideal_kv": ratio * v_cap_total_kv,
        "v_cap_eq_kv": v_cap_total_kv / 2,
        "energy_mj": parameters.C_eq_F * v_cap_total_kv**2 / 8,
        "arm_ohmic_loss_mw": parameters.R_arm_ohm * i_arm_ka**2,
        "nonohmic_loss_mw": loss_current * v_cap_total_kv,
    }


def limited_nonohmic_current(voltage_kv: float, parameters: AverageArmParameters, step_s: float) -> float:
    """Dissipate available capacitor energy without empty-state current demand.

    The explicit current/voltage interface spans two solver steps. A maximum
    discharge rate of 1/8 per step keeps this delayed sink passive near zero;
    normal charged operation retains the declared constant-power loss.
    """
    if not math.isfinite(voltage_kv) or not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("Loss current requires finite voltage and a positive timestep")
    if voltage_kv <= 0:
        return 0.0
    return min(parameters.P_nonohmic_MW / max(voltage_kv, parameters.V_loss_floor_kV),
               0.25 * parameters.C_eq_F * voltage_kv / (8.0 * step_s))


def predict_coupled_capacitor_voltage(
    voltage_kv: float, storage_current_ka: float, capacitance_f: float, step_s: float
) -> float:
    """Compensate the current-source and voltage-source interface delays.

    Each EMTDC Dsdyn reads the preceding Dsout measurement. The isolated
    capacitor is driven by the preceding arm current, and its voltage is then
    applied on the next network solution. Advance that measured voltage by
    both interface steps. This introduces no capacitor-energy state override.
    """
    if not all(math.isfinite(value) for value in (
        voltage_kv, storage_current_ka, capacitance_f, step_s
    )) or capacitance_f <= 0 or step_s <= 0:
        raise ValueError("Capacitor prediction requires finite physical values")
    return max(0.0, voltage_kv + CAPACITOR_FEEDBACK_ADVANCE_STEPS
               * step_s * storage_current_ka / capacitance_f)


# Exact port occurrences matter: source_1 has a distinct grounded NB occurrence.
_MASTER_PORTS = {
    "source_1": {
        "NA": (-36, 0, "Natural", 0),
        "NB": (36, 0, "Natural", 1),
        "Mag": (0, 36, "Transfer", 0),
    },
    "src_ccin_1": {
        "A": (0, 0, "Natural", 0),
        "B": (36, 0, "Natural", 0),
        "Mag": (0, 36, "Transfer", 0),
    },
    "varrlc": {"A": (0, 0, "Natural", 0), "B": (36, 0, "Natural", 0)},
    # Retained for the cable-loop fixture and existing LCC companion users;
    # the average arm itself uses the audited variable R/L/C primitive.
    "resistor": {"A": (0, 0, "Natural", 0), "B": (36, 0, "Natural", 0)},
    "gain": {"IN:Dim": (-36, 0, "Transfer", 0), "OUT:Dim": (36, 0, "Transfer", 0)},
    "pi_ctlr": {"IN": (-36, 0, "Transfer", 0), "OUT": (36, 0, "Transfer", 0)},
    "realpole": {
        "I:Dim": (-36, 0, "Transfer", 0),
        "O:Dim": (36, 0, "Transfer", 0),
    },
    "breakout": {
        "N": (0, 0, "Natural", 0),
        "N1": (36, -36, "Natural", 0),
        "N2": (36, 0, "Natural", 0),
        "N3": (36, 36, "Natural", 0),
    },
    "ammeter": {"N1": (0, 0, "Natural", 0), "N2": (36, 0, "Natural", 0)},
    "voltmeter": {"N1": (0, 0, "Natural", 0), "N2": (0, 36, "Natural", 0)},
    "breaker1": {"A": (36, 0, "Natural", 0), "B": (-36, 0, "Natural", 0)},
    "peswitch": {"DP": (0, 0, "Natural", 0), "DN": (0, -36, "Natural", 0)},
    "ground": {"A": (0, 0, "Natural", 0)},
    "xnode": {"N": (0, 0, "Natural", 0)},
    "nodelabel": {"A": (0, 0, "Natural", 0)},
    "datalabel": {"A": (0, 0, "Transfer", 0)},
    "import": {"N": (36, 0, "Transfer", 0)},
    "export": {"N": (36, 0, "Transfer", 0)},
    "pgb": {"Signl": (0, 0, "Transfer", 0)},
    "arrester": {"NF": (0, -36, "Natural", 0), "NT": (0, 0, "Natural", 0)},
    "const": {"OUT": (36, 0, "Transfer", 0)},
}
_MASTER_WRITER_PORTS = {
    **_MASTER_PORTS,
    "source3": {
        "N3": (36, 0, "Natural", 0),
        "N": (-36, 0, "Natural", 1),
    },
    "xfmr-3p2w": {
        "N1": (-54, 0, "Natural", 0),
        "N2": (36, 0, "Natural", 0),
        "G1": (-18, 36, "Natural", 0),
    },
}
_SOURCE_PARAMETERS = {
    "Name": "",
    "Type": "6",
    "Grnd": "0",
    "Spec": "0",
    "Cntrl": "1",
    "AC": "0",
    "Tc": "0.0 [s]",
    "CUR": "",
}
_DIODE_PARAMETERS = {
    "L": "",
    "Type": "0",
    "SNUB": "0",
    "INTR": "0",
    "RON": "R_on_ohm",
    "ROFF": "R_off_ohm",
    "EFVD": "V_diode_kV",
    "EBO": "1.0e5 [kV]",
    "Erw": "1.0e5 [kV]",
    "TEXT": "0.0 [us]",
    "PFB": "1",
    "I": "",
    "It": "",
    "V": "",
}
_PARAMETER_UNITS = {
    "C_eq_F": "F",
    "L_arm_H": "H",
    "R_arm_ohm": "ohm",
    "P_nonohmic_MW": "MW",
    "V_loss_floor_kV": "kV",
    "R_on_ohm": "ohm",
    "R_off_ohm": "ohm",
    "V_diode_kV": "kV",
    "Frequency_Hz": "Hz",
    "Modulation_Index": "1",
    "Phase_Offset_Deg": "deg",
    "Deblock_Time_s": "s",
    "Reversal_Time_s": "s",
    "Reversal_Duration_s": "s",
    "Ramp_Time_s": "s",
    "P_Order_MW": "MW",
    "Q_Order_MVAr": "MVAr",
    "Vdc_Order_kV": "kV",
    "Control_Mode": "1",
    "Kp_Active": "1",
    "Ti_Active_s": "s",
    "Kp_Reactive": "1",
    "Ti_Reactive_s": "s",
    "Base_Modulation": "1",
    "Circulating_Gain_ohm": "ohm",
    "Circulating_Integral_Time_s": "s",
    "Energy_Gain_per_s": "1",
    "Kp_Vdc_MW_per_kV": "1",
    "Ti_Vdc_s": "s",
    "Feedback_Filter_s": "s",
    "Energy_Difference_Filter_s": "s",
    "Maximum_Precharge_s": "s",
    "Precharge_Voltage_Fraction": "1",
    "Precharge_Current_Limit_kA": "kA",
    "Precharge_Rate_Per_Cycle": "1",
    "Precharge_Hold_Cycles": "1",
    "PLL_Required": "1",
    "Controlled_Charge": "1",
    "Startup_Charge_Time_s": "s",
    "Recovery_Charge_Time_s": "s",
    "DC_Link_Capacitance_F": "F",
    "Maximum_Conditioning_s": "s",
    "Power_Correction_Limit_MW": "MW",
    "Cable_Loss_MW": "MW",
    "Converter_Loss_MW": "MW",
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _audit_master(path: Path) -> tuple[dict, str, dict]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Master must be an immutable regular library file")
    payload = path.read_bytes()
    root = ET.fromstring(payload)
    if (
        root.tag != "project"
        or root.get("version") != "4.6.2"
        or root.get("Target") != "Library"
    ):
        raise ValueError("Master must use native PSCAD 4.6.2 library XML")
    metadata = read_definition_metadata_document(payload)
    for name, ports in _MASTER_PORTS.items():
        if len(metadata.get(name, ())) != 1:
            raise ValueError(f"Master definition is missing or ambiguous: {name}")
        for port_name, contract in ports.items():
            records = [
                port
                for port in metadata[name][0].ports
                if port.name == port_name and port.occurrence == contract[3]
            ]
            if (
                len(records) != 1
                or (records[0].x, records[0].y, records[0].model, records[0].occurrence)
                != contract
            ):
                raise ValueError(f"Master port contract changed: {name}:{port_name}")
            expected_dimension = {
                ("breakout", "N"): 3,
                ("breakout", "N1"): 1,
                ("breakout", "N2"): 1,
                ("breakout", "N3"): 1,
            }.get(
                (name, port_name),
                1
                if name
                in {
                    "source_1",
                    "src_ccin_1",
                    "breaker1",
                    "peswitch",
                    "ground",
                    "pi_ctlr",
                    "const",
                }
                else 0,
            )
            if records[0].dim != expected_dimension:
                raise ValueError(f"Master scalar dimension changed: {name}:{port_name}")
            expected_condition = {
                ("source_1", "NB"): "Grnd==0",
                ("source_1", "Mag"): "(Cntrl==1)&&(Spec==0)",
                ("src_ccin_1", "Mag"): "(Cntrl)",
                ("breakout", "N1"): "Com==0",
                ("breakout", "N3"): "Com==0",
                ("pi_ctlr", "IN"): "Mthd==0||INTR==0",
            }.get((name, port_name), "true")
            if re.sub(r"\s+", "", records[0].condition or "") != expected_condition:
                raise ValueError(
                    f"Master selected-terminal condition changed: {name}:{port_name}"
                )
            if contract[2] == "Transfer" and records[0].type != "Real":
                raise ValueError(f"Master scalar type changed: {name}:{port_name}")
    for name, parameter, unit in (
        ("varrlc", "C", "uF"),
        ("varrlc", "R", "ohm"),
        ("varrlc", "L", "H"),
        ("source_1", "Tc", "s"),
        ("peswitch", "EFVD", "kV"),
        ("peswitch", "RON", "ohm"),
        ("peswitch", "ROFF", "ohm"),
        ("arrester", "VSCAL", "kV"),
    ):
        if (
            parameter not in metadata[name][0].parameters
            or metadata[name][0].parameters[parameter].unit != unit
        ):
            raise ValueError(f"Master parameter unit changed: {name}:{parameter}")
    for name, segment, token in (
        ("source_1", "Branch", "BA = $NB $NA SOURCE"),
        ("source_1", "Dsdyn", "RVD1_1 = $Mag"),
        ("src_ccin_1", "Branch", "BR = $B $A BREAKER"),
        ("src_ccin_1", "Dsdyn", "CCBR($BR,$SS) = $Mag"),
        ("varrlc", "Branch", "BR = $A $B BREAKER"),
        ("varrlc", "Dsdyn", "CALL E_VARRLC1_EXE"),
        ("varrlc", "Dsout", "#OUTPUT REAL I 0 {$CBR:BR}"),
        ("gain", "Fortran", "$OUT = $G * $IN"),
        ("ammeter", "Branch", "BN = $N1 $N2 AMMETER"),
        ("ammeter", "Dsout", "$CBR:BN"),
        ("voltmeter", "Dsout", "$VDC:N1:N2"),
        ("breaker1", "Dsdyn", "NINT(1.0-$NAME)"),
        ("peswitch", "Branch", "NBR = $DP $DN BREAKER $ROFF"),
        ("arrester", "Dsdyn", "CALL ARRESTERZNO_EXE"),
    ):
        element = root.find(
            f"./definitions/Definition[@name='{name}']/script/segment[@name='{segment}']"
        )
        if element is None or token not in re.sub(r"\s+", " ", element.text or ""):
            raise ValueError(f"Master electrical directive changed: {name}:{segment}")
    for parameter, unit_label in (("Energy", "[kJoules]"), ("Curr", "[kA]")):
        element = root.find(f"./definitions/Definition[@name='arrester']/form//parameter[@name='{parameter}']")
        if element is None or unit_label not in element.get("desc", ""):
            raise ValueError("Master arrester output units changed")
    if _sha(path.read_bytes()) != _sha(payload):
        raise ValueError("Master changed during native arm audit")
    defaults = {
        name: {
            parameter.get("name"): (parameter.findtext("value") or "").strip()
            for parameter in root.findall(
                f"./definitions/Definition[@name='{name}']/form//parameter"
            )
        }
        for name in _MASTER_WRITER_PORTS
    }
    return metadata, _sha(payload), defaults


def _project(name: str, *, library: bool) -> ET.Element:
    template = "empty_library.pslx" if library else "empty_case.pscx"
    payload = (
        resources.files("pscad_mcp").joinpath("assets/templates", template).read_bytes()
    )
    root = ET.fromstring(payload)
    previous = root.get("name")
    root.set("name", name)
    root.set("Target", "Library" if library else "EMTDC")
    for size in root.findall(
        "./definitions/Definition/schematic[@classid='UserCanvas']/paramlist/param[@name='size']"
    ):
        size.set("value", "4")
    for element in root.iter():
        for key, value in tuple(element.attrib.items()):
            if value.startswith(previous + ":"):
                element.set(key, name + value[len(previous) :])
    return root


def _paramlist(parent: ET.Element, values: dict[str, Any], **attributes: str) -> None:
    element = ET.SubElement(parent, "paramlist", attributes)
    for name, value in values.items():
        ET.SubElement(element, "param", {"name": name, "value": str(value)})


def _form(parent: ET.Element, parameters: dict[str, float], *, signed_parameters: tuple[str, ...] = ()) -> None:
    form = ET.SubElement(
        parent,
        "form",
        {
            "name": "Native averaged half-bridge arm",
            "w": "480",
            "h": "480",
            "splitter": "65",
        },
    )
    category = ET.SubElement(form, "category", {"name": "Physical parameters"})
    for name, value in parameters.items():
        parameter = ET.SubElement(
            category,
            "parameter",
            {
                "type": "Real",
                "name": name,
                "desc": name,
                "content_type": "Constant",
                "intent": "Input",
                "dim": "1",
                "unit": _PARAMETER_UNITS[name],
                "min": "" if name in signed_parameters else "0",
            },
        )
        ET.SubElement(parameter, "value").text = str(value)


def _definition(
    root: ET.Element, name: str, ports: dict[str, tuple], parameters: dict[str, float],
    *, signed_parameters: tuple[str, ...] = (),
) -> ET.Element:
    element = ET.SubElement(
        root.find("definitions"),
        "Definition",
        {
            "classid": "UserCmpDefn",
            "name": name,
            "id": str(1_700_000_000 + len(root.find("definitions"))),
            "crc": "0",
            "view": "false",
            "date": "0",
            "group": "HVDC FACTS PE",
        },
    )
    _paramlist(
        element, {"Description": "Repository-authored native averaged half-bridge arm"}
    )
    _form(element, parameters, signed_parameters=signed_parameters)
    top = min([-36, *(port[1] - 18 for port in ports.values())])
    bottom = max([36, *(port[1] + 18 for port in ports.values())])
    svg = ET.SubElement(element, "svg", {"viewBox": f"-240 {top - 36} 240 {bottom + 36}"})
    ET.SubElement(
        svg,
        "rect",
        {
            "x": "-54",
            "y": str(top),
            "width": "108",
            "height": str(bottom - top),
            "stroke": "Black",
            "stroke-width": "0.2",
            "fill-style": "Hollow",
        },
    )
    for port_name, (x, y, model, mode) in ports.items():
        ET.SubElement(
            svg,
            "port",
            {
                "name": port_name,
                "x": str(x),
                "y": str(y),
                "model": model,
                "mode": mode,
                "dim": "1",
                "type": "NonRemovable" if model == "Natural" else "Real",
            },
        ).text = "true"
    return element


def _script(definition: ET.Element, segment: str, text: str) -> None:
    script = definition.find("script")
    if script is None:
        script = ET.SubElement(definition, "script")
    ET.SubElement(script, "segment", {"name": segment}).text = text


def _manual_sequence(definition: ET.Element, groups: tuple[tuple[str, ...], ...]) -> None:
    """Freeze Dsdyn feedback boundaries independently of schematic position."""
    canvas = definition.find("schematic")
    canvas.find("./paramlist/param[@name='auto_sequence']").set("value", "0")
    priority = {name: index + 1 for index, names in enumerate(groups) for name in names}
    components = sorted(canvas.findall("User"), key=lambda c: (
        priority.get(c.get("defn", "").split(":")[-1], 0), int(c.get("id"))))
    for index, component in enumerate(components, 1):
        component.set("z", str(index * 10))


class _Writer:
    def __init__(
        self,
        root: ET.Element,
        master: dict,
        master_defaults: dict,
        additional: dict | None = None,
    ):
        self.root, self.master = root, master
        self.master_defaults = master_defaults
        self.local = read_definition_metadata_document(ET.tostring(root))
        self.additional = additional or {}
        self.sequence = 1_800_000_000
        self.routes: list[dict] = []
        self.nets: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.ports: dict[str, list[tuple[tuple[int, int], str, str]]] = defaultdict(
            list
        )
        self.counts: dict[str, int] = defaultdict(int)
        self.blocks: dict[str, list[tuple]] = defaultdict(list)
        self.layout_complete = False

    def identifier(self) -> str:
        self.sequence += 1
        return str(self.sequence)

    def metadata(self, scoped: str):
        scope, name = scoped.split(":", 1)
        return (
            self.master
            if scope == "master"
            else self.local
            if scope == self.root.get("name")
            else self.additional[scope]
        )[name][0]

    def component(
        self,
        definition: ET.Element,
        role: str,
        scoped: str,
        parameters: dict,
        point: tuple[int, int],
    ) -> ET.Element:
        metadata = self.metadata(scoped)
        unknown = set(parameters) - set(metadata.parameters)
        if unknown:
            raise ValueError(
                f"Unknown native component parameters for {scoped}: {sorted(unknown)}"
            )
        canvas = definition.find("schematic")
        if canvas is None:
            canvas = ET.SubElement(definition, "schematic", {"classid": "UserCanvas"})
            _paramlist(
                canvas,
                {
                    "show_grid": 0,
                    "size": 4,
                    "orient": 1,
                    "show_border": 0,
                    "monitor_bus_voltage": 0,
                    "show_signal": 0,
                    "show_virtual": 0,
                    "show_sequence": 0,
                    "auto_sequence": 1,
                },
            )
        element = ET.SubElement(
            canvas,
            "User",
            {
                "classid": "UserCmp",
                "name": role,
                "defn": scoped,
                "id": self.identifier(),
                "x": str(point[0]),
                "y": str(point[1]),
                "w": "120",
                "h": "72",
                "z": "0",
                "orient": "0",
                "link": "-1",
                "q": "4",
            },
        )
        values = dict(parameters)
        if scoped.startswith("master:"):
            for name, value in self.master_defaults[scoped.split(":", 1)[1]].items():
                values.setdefault(name, value)
        _paramlist(element, values, name="", link="-1")
        return element

    def add(
        self,
        definition: ET.Element,
        role: str,
        scoped: str,
        parameters: dict,
        bindings: dict[str, str],
    ) -> ET.Element:
        name = definition.get("name")
        index = self.counts[name]
        self.counts[name] += 1
        native = self.metadata(scoped)
        point = (180 + (index % 6) * 432, 270 + (index // 6) * 432)
        component = self.component(definition, role, scoped, parameters, point)
        members = [component]
        for port_name, signal in bindings.items():
            occurrence = (
                _MASTER_WRITER_PORTS[scoped.split(":", 1)[1]][port_name][3]
                if scoped.startswith("master:")
                else 0
            )
            port = next(
                port
                for port in native.ports
                if port.name == port_name and port.occurrence == occurrence
            )
            kind = "electrical" if port.model == "Natural" else "data"
            start = (point[0] + port.x, point[1] + port.y)
            dx, dy = (
                ((-18, 0) if port.x <= 0 else (18, 0))
                if port.x != 0 or port.y == 0
                else (0, 18 if port.y > 0 else -18)
            )
            finish = (start[0] + dx, start[1] + dy)
            label_role = f"{role}_{port_name}_label"
            label = self.component(
                definition,
                label_role,
                "master:nodelabel" if kind == "electrical" else "master:datalabel",
                {"Name": signal},
                finish,
            )
            wire = ET.SubElement(
                definition.find("schematic"),
                "Wire",
                {
                    "classid": "WireOrthogonal",
                    "name": "",
                    "id": self.identifier(),
                    "x": str(start[0]),
                    "y": str(start[1]),
                    "w": str(abs(dx)),
                    "h": str(abs(dy)),
                    "orient": "0",
                },
            )
            ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
            ET.SubElement(wire, "vertex", {"x": str(dx), "y": str(dy)})
            members.extend((label, wire))
            self.routes.append(
                {
                    "definition": name,
                    "wire_id": wire.get("id"),
                    "kind": kind,
                    "signal": signal,
                    "vertices": [list(start), list(finish)],
                    "endpoints": [
                        {
                            "component_id": component.get("id"),
                            "port": port.name,
                            "occurrence": occurrence,
                        },
                        {"component_id": label.get("id"), "port": "A", "occurrence": 0},
                    ],
                }
            )
            self.ports[name].extend(
                [(start, component.get("id"), kind), (finish, label.get("id"), kind)]
            )
            if kind == "electrical":
                self.nets[name][signal].append(f"{role}:{port_name}")
        top = min([-36, *(port.y - 36 for port in native.ports)])
        bottom = max([36, *(port.y + 36 for port in native.ports)])
        self.blocks[name].append((top, bottom, point, members))
        return component

    def verify(self) -> None:
        if not self.layout_complete:
            # PSCAD 4.6 supports 34x44 inch landscape (6336x4896 XML units).
            # Pack complete local wire/label groups into twelve columns. Tall
            # controllers go first; probes fill the remaining column heights.
            offsets = {}
            for name, blocks in self.blocks.items():
                heights = [108] * 12
                for top, bottom, old, members in sorted(blocks, key=lambda b: b[0] - b[1]):
                    column = min(range(12), key=heights.__getitem__)
                    point = (216 + 504 * column, heights[column] - top)
                    heights[column] = point[1] + bottom + 18
                    if heights[column] > 4788:
                        raise ValueError("Native schematic exceeds the PSCAD 4.6 page")
                    dx, dy = point[0] - old[0], point[1] - old[1]
                    for member in members:
                        member.set("x", str(int(member.get("x")) + dx))
                        member.set("y", str(int(member.get("y")) + dy))
                        offsets[member.get("id")] = (dx, dy)
                self.ports[name] = [((point[0] + offsets[owner][0], point[1] + offsets[owner][1]), owner, kind)
                                    for point, owner, kind in self.ports[name]]
            for route in self.routes:
                dx, dy = offsets[route["endpoints"][0]["component_id"]]
                route["vertices"] = [[x + dx, y + dy] for x, y in route["vertices"]]
            self.layout_complete = True
        for route in self.routes:
            (x1, y1), (x2, y2) = route["vertices"]
            owners = {endpoint["component_id"] for endpoint in route["endpoints"]}
            for (x, y), owner, kind in self.ports[route["definition"]]:
                if (
                    min(x1, x2) <= x <= max(x1, x2)
                    and min(y1, y2) <= y <= max(y1, y2)
                    and (owner not in owners or kind != route["kind"])
                ):
                    raise ValueError(
                        "Native arm route touches an unintended or differently typed terminal"
                    )


def _make_library(
    master: dict, master_defaults: dict, *, scope: str = LIBRARY_SCOPE
) -> tuple[ET.Element, _Writer]:
    root = _project(scope, library=True)
    defaults = asdict(AverageArmParameters())
    arm_ports = {
        "IN": (-90, 0, "Natural", "Electrical"),
        "OUT": (90, 0, "Natural", "Electrical"),
        "M": (-90, 90, "Transfer", "Input"),
        "BLOCK": (-90, 126, "Transfer", "Input"),
    }
    arm_ports.update(
        {
            name: (144, -180 + index * 36, "Transfer", "Output")
            for index, name in enumerate(OUTPUT_UNITS)
        }
    )
    arm = _definition(root, "MMCAverageArm", arm_ports, defaults)
    _script(
        arm,
        "Checks",
        "ERROR Equivalent capacitance must be positive : C_eq_F > 0\nERROR Arm inductance must be positive : L_arm_H >= 1e-9\nERROR Non-ohmic loss must be nonnegative : P_nonohmic_MW >= 0\nERROR Loss voltage floor must be positive : V_loss_floor_kV > 0\nERROR Switch on resistance must avoid short-circuit classification : R_on_ohm >= 0.001\nERROR Switch resistances must be ordered : R_off_ohm > R_on_ohm\n",
    )
    coupling_ports = {
        name: (-72, -72 + index * 36, "Transfer", "Input")
        for index, name in enumerate(("M", "BLOCK", "VCAP", "INORMAL", "ICLAMP", "VSTACK", "IBYPASS", "ICAP"))
    }
    coupling_ports.update(
        {
            name: (72, -72 + index * 36, "Transfer", "Output")
            for index, name in enumerate(
                ("VNORMAL", "ISTORE", "W", "VEQ", "OPEN", "PLOSS", "VCLAMP", "PSWITCH")
            )
        }
    )
    coupling = _definition(
        root,
        "MMCAverageCoupling",
        coupling_ports,
        {key: defaults[key] for key in ("C_eq_F", "P_nonohmic_MW", "V_loss_floor_kV")},
    )
    _script(
        coupling,
        "Fortran",
        f"""#STORAGE REAL:5
#LOCAL REAL NINSERT
#LOCAL REAL ILOSS
#LOCAL REAL VPREDICT
      NINSERT = MIN(1.0, MAX(0.0, $M))
      IF (TIMEZERO) THEN
        STORF(NSTORF) = NINSERT
        STORF(NSTORF+1) = 0.0
        STORF(NSTORF+2) = 0.0
        STORF(NSTORF+3) = 0.0
        STORF(NSTORF+4) = 0.0
      ENDIF
! Native branch drops and currents come from the same preceding solution.
! Include the disconnect, positive diode, bypass diode and capacitor clamp.
      $PSWITCH = ($VSTACK - STORF(NSTORF+1)) * $INORMAL
      $PSWITCH = $PSWITCH + ($VSTACK - STORF(NSTORF+2)) * $ICLAMP - $VSTACK * $IBYPASS
      $PSWITCH = $PSWITCH + $VCAP * (STORF(NSTORF+3) - $ICAP)
      $PLOSS = STORF(NSTORF+4) * $VCAP
      ILOSS = 0.0
      IF ($VCAP .GT. 0.0) THEN
        ILOSS = $P_nonohmic_MW / MAX($VCAP, $V_loss_floor_kV)
        ILOSS = MIN(ILOSS, 0.25 * $C_eq_F * $VCAP / (8.0 * DELT))
      ENDIF
! The measured branch current belongs to the preceding network solution.
! Pair it with the ratio that produced that solution, not the new command.
! Otherwise a varying insertion ratio creates first-order artificial power.
      $ISTORE = STORF(NSTORF) * $INORMAL + $ICLAMP - ILOSS
      VPREDICT = MAX(0.0, $VCAP + {CAPACITOR_FEEDBACK_ADVANCE_STEPS} * DELT * $ISTORE / (0.25 * $C_eq_F))
      $VNORMAL = NINSERT * VPREDICT
      $VCLAMP = VPREDICT
      $W = 0.125 * $C_eq_F * $VCAP * $VCAP
      $VEQ = 0.5 * $VCAP
      $OPEN = 0.0
      IF ($BLOCK .GE. 0.5) $OPEN = 1.0
      STORF(NSTORF) = NINSERT
      STORF(NSTORF+1) = $VNORMAL
      STORF(NSTORF+2) = $VCLAMP
      STORF(NSTORF+3) = $ISTORE
      STORF(NSTORF+4) = ILOSS
      NSTORF = NSTORF + 5
""",
    )
    writer = _Writer(root, master, master_defaults)
    add = lambda role, name, parameters, bindings: writer.add(
        arm, role, "master:" + name, parameters, bindings
    )
    add("arm_in", "xnode", {"Name": "IN"}, {"N": "IN"})
    add("arm_out", "xnode", {"Name": "OUT"}, {"N": "OUT"})
    add(
        "arm_resistance",
        "varrlc",
        {"RLC": "0", "R": "R_arm_ohm", "E": "0.0 [kV]", "dLdC": "0", "I": "ARM_I"},
        {"A": "IN", "B": "ARM_L_IN"},
    )
    add(
        "arm_inductance",
        "varrlc",
        {"RLC": "1", "L": "L_arm_H", "E": "0.0 [kV]", "dLdC": "0", "I": ""},
        {"A": "ARM_L_IN", "B": "STACK_IN"},
    )
    add(
        "normal_current_meter",
        "ammeter",
        {"Name": "NORMAL_I"},
        {"N1": "STACK_IN", "N2": "NORMAL_POS"},
    )
    add(
        "normal_voltage",
        "source_1",
        _SOURCE_PARAMETERS,
        {"NA": "NORMAL_POS", "NB": "NORMAL_NEG", "Mag": "NORMAL_V"},
    )
    add(
        "normal_disconnect",
        "breaker1",
        {
            "NAME": "ARM_OPEN",
            "OPCUR": "1",
            "ENAB": "0",
            "ViewB": "0",
            "RON": "R_on_ohm",
            "ROFF": "R_off_ohm",
            "CLVL": "0.0 [kA]",
            "IBR": "",
            "SBR": "",
            "VBR": "",
        },
        {"B": "NORMAL_NEG", "A": "OUT"},
    )
    add(
        "clamp_current_meter",
        "ammeter",
        {"Name": "CLAMP_I"},
        {"N1": "STACK_IN", "N2": "CLAMP_IN"},
    )
    add(
        "positive_clamp",
        "peswitch",
        _DIODE_PARAMETERS,
        {"DP": "CLAMP_IN", "DN": "CLAMP_POS"},
    )
    add(
        "clamp_voltage",
        "source_1",
        _SOURCE_PARAMETERS,
        {"NA": "CLAMP_POS", "NB": "OUT", "Mag": "CLAMP_V"},
    )
    add(
        "negative_bypass",
        "peswitch",
        {**_DIODE_PARAMETERS, "I": "BYPASS_I"},
        {"DP": "OUT", "DN": "STACK_IN"},
    )
    add(
        "storage_current",
        "src_ccin_1",
        {"Name": "", "Cntrl": "1"},
        {"A": "CAP_POS", "B": "GND", "Mag": "STORE_I"},
    )
    add(
        "capacitor_current_meter",
        "ammeter",
        {"Name": "CAP_I"},
        {"N1": "CAP_POS", "N2": "CAP_MEASURE"},
    )
    add(
        "storage_capacitor",
        "varrlc",
        {"RLC": "2", "C": "CAP_C_UF", "E": "0.0 [kV]", "dLdC": "0", "I": ""},
        {"A": "CAP_MEASURE", "B": "GND"},
    )
    add(
        "capacitor_reverse_clamp",
        "peswitch",
        {**_DIODE_PARAMETERS, "EFVD": "0.0 [kV]"},
        {"DP": "GND", "DN": "CAP_POS"},
    )
    add("storage_ground", "ground", {}, {"A": "GND"})
    add(
        "capacitor_voltage_meter",
        "voltmeter",
        {"Name": "CAP_V"},
        {"N1": "CAP_MEASURE", "N2": "GND"},
    )
    add(
        "inserted_voltage_meter",
        "voltmeter",
        {"Name": "INSERTED_V"},
        {"N1": "STACK_IN", "N2": "OUT"},
    )
    add(
        "terminal_voltage_meter",
        "voltmeter",
        {"Name": "ARM_V"},
        {"N1": "IN", "N2": "OUT"},
    )
    for name in ("M", "BLOCK", *defaults):
        add("input_" + name, "import", {"Name": name}, {"N": name})
    add(
        "capacitance_conversion",
        "gain",
        {"G": "250000.0", "Dim": "1", "COM": "Cphysical_uF = Ceq_F / 4 * 1e6"},
        {"IN:Dim": "C_eq_F", "OUT:Dim": "CAP_C_UF"},
    )
    writer.add(
        arm,
        "signed_power_coupling",
        scope + ":MMCAverageCoupling",
        {name: name for name in ("C_eq_F", "P_nonohmic_MW", "V_loss_floor_kV")},
        {
            "M": "M",
            "BLOCK": "BLOCK",
            "VCAP": "CAP_V",
            "INORMAL": "NORMAL_I",
            "ICLAMP": "CLAMP_I",
            "VSTACK": "INSERTED_V",
            "IBYPASS": "BYPASS_I",
            "ICAP": "CAP_I",
            "VNORMAL": "NORMAL_V",
            "ISTORE": "STORE_I",
            "W": "CAP_W",
            "VEQ": "CAP_EQ_V",
            "OPEN": "ARM_OPEN",
            "PLOSS": "NONOHMIC_P",
            "VCLAMP": "CLAMP_V",
            "PSWITCH": "SWITCH_P",
        },
    )
    signals = {
        "V_INSERTED": "INSERTED_V",
        "I_ARM": "ARM_I",
        "ENERGY": "CAP_W",
        "V_CAP_EQ": "CAP_EQ_V",
        "V_CAP_TOTAL": "CAP_V",
        "I_NORMAL": "NORMAL_I",
        "I_CLAMP": "CLAMP_I",
        "I_BYPASS": "BYPASS_I",
        "I_CAP": "CAP_I",
        "V_ARM": "ARM_V",
        "P_NONOHMIC": "NONOHMIC_P",
        "P_SWITCH": "SWITCH_P",
    }
    for name, signal in signals.items():
        add("output_" + name, "export", {"Name": name}, {"N": signal})
    _manual_sequence(arm, (("MMCAverageCoupling",), ("varrlc", "src_ccin_1", "source_1", "breaker1", "peswitch"), ("export",)))
    writer.verify()
    return root, writer


def _write_new(path: Path, root: ET.Element) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with path.open("xb") as stream:
        stream.write(payload)
    if path.read_bytes() != payload:
        raise ValueError("Native artifact readback differs from authored bytes")
    return _sha(payload)


def materialize_average_arm_library(
    destination: str | Path, *, master_path: str | Path
) -> dict[str, Any]:
    """Write a new native library after checking immutable installed metadata."""
    target, source = Path(destination), Path(master_path)
    if target.exists() or target.is_symlink() or target.resolve() == source.resolve():
        raise FileExistsError("Native arm output must be new and distinct from Master")
    master, before, defaults = _audit_master(source)
    root, writer = _make_library(master, defaults)
    after = _sha(source.read_bytes())
    if before != after:
        raise ValueError("Master changed while authoring the native arm")
    output_hash = _write_new(target, root)
    return {
        "library_path": str(target.resolve()),
        "library_sha256": output_hash,
        "master_path": str(source.resolve()),
        "master_sha256_before": before,
        "master_sha256_after": after,
        "voltage_convention": VOLTAGE_CONVENTION,
        "initialization": "physical_charge_from_zero_or_pscad_snapshot",
        "blocked_state_path": "half_bridge_diode_equivalent",
        "intrinsic_dc_fault_blocking": False,
        "nonohmic_loss": "P_nonohmic_MW excludes physical R_arm_ohm and native semiconductor losses; reduced below V_loss_floor_kV",
        "electrical_nets": {name: dict(nets) for name, nets in writer.nets.items()},
        "routes": writer.routes,
        "route_contacts_verified": True,
        "licensed_acceptance": "NOT_RUN",
    }


def materialize_average_arm_fixture(
    destination: str | Path,
    *,
    master_path: str | Path,
    parameters: AverageArmParameters | None = None,
) -> dict[str, Any]:
    """Create a source-driven one-arm case with measured charge/discharge/block phases."""
    folder, source = Path(destination), Path(master_path)
    if folder.exists() or folder.is_symlink():
        raise FileExistsError("Native arm fixture directory must be new")
    parameters = parameters or AverageArmParameters()
    master, before, defaults = _audit_master(source)
    library, library_writer = _make_library(master, defaults)
    library_metadata = read_definition_metadata_document(ET.tostring(library))
    project_name = "average_arm_fixture"
    root = _project(project_name, library=False)
    settings = root.find("./paramlist[@name='Settings']")
    values = {
        "time_duration": "0.19",
        "time_step": "2",
        "sample_step": "20",
        "PlotType": "1",
        "StartType": "0",
        "output_filename": project_name + ".out",
    }
    for name, value in values.items():
        item = settings.find(f"param[@name='{name}']")
        if item is None:
            item = ET.SubElement(settings, "param", {"name": name})
        item.set("value", value)
    drive = _definition(
        root,
        "ArmFixtureDrive",
        {
            name: (72, index * 36, "Transfer", "Output")
            for index, name in enumerate(("I", "M", "BLOCK"))
        },
        {},
    )
    _script(
        drive,
        "Fortran",
        """      $M = 0.5
      $BLOCK = 0.0
      IF (TIME .GE. 0.095) $BLOCK = 1.0
      IF (TIME .LT. 0.01) THEN
        $I = 20.0 * TIME
      ELSEIF (TIME .LT. 0.06) THEN
        $I = 0.2
      ELSEIF (TIME .LT. 0.07) THEN
        $I = 0.2 - 40.0 * (TIME - 0.06)
      ELSEIF (TIME .LT. 0.09) THEN
        $I = -0.2
      ELSEIF (TIME .LT. 0.10) THEN
        $I = -0.2 + 40.0 * (TIME - 0.09)
      ELSEIF (TIME .LT. 0.14) THEN
        $I = 0.2
      ELSEIF (TIME .LT. 0.15) THEN
        $I = 0.2 - 40.0 * (TIME - 0.14)
      ELSE
        $I = -0.2
      ENDIF
""",
    )
    writer = _Writer(root, master, defaults, {LIBRARY_SCOPE: library_metadata})
    main = root.find("./definitions/Definition[@name='Main']")
    writer.add(
        main,
        "arm_under_test",
        LIBRARY_SCOPE + ":MMCAverageArm",
        asdict(parameters),
        {
            "IN": "TEST_IN",
            "OUT": "GND",
            "M": "M",
            "BLOCK": "BLOCK",
            **{name: name for name in OUTPUT_UNITS},
        },
    )
    instance = main.find("./schematic/User[@name='arm_under_test']")
    ET.SubElement(
        root.find("./hierarchy/call/call"),
        "call",
        {
            "link": instance.get("id"),
            "name": instance.get("defn"),
            # PSCAD assigns nested hierarchy calls an explicit display order;
            # author the value so finalization remains a semantic check.
            "z": "60",
            "view": "false",
            "instance": "0",
        },
    )
    writer.add(
        main,
        "drive",
        project_name + ":ArmFixtureDrive",
        {},
        {"I": "CURRENT_COMMAND", "M": "M", "BLOCK": "BLOCK"},
    )
    writer.add(
        main,
        "test_current",
        "master:src_ccin_1",
        {"Name": "", "Cntrl": "1"},
        {"A": "TEST_IN", "B": "GND", "Mag": "CURRENT_COMMAND"},
    )
    writer.add(main, "test_ground", "master:ground", {}, {"A": "GND"})
    channels = {**OUTPUT_UNITS, "M": "1", "BLOCK": "1", "CURRENT_COMMAND": "kA"}
    for name, unit in channels.items():
        writer.add(
            main,
            "probe_" + name,
            "master:pgb",
            {
                "Name": name,
                "Units": unit,
                "Group": "",
                "UseSignalName": "0",
                "enab": "1",
                "Display": "1",
                "Scale": "1.0",
                "mrun": "0",
                "Pol": "0",
                "Max": "20.0",
                "Min": "-20.0",
            },
            {"Signl": name},
        )
    writer.verify()
    if _sha(source.read_bytes()) != before:
        raise ValueError("Master changed during native fixture generation")
    folder.mkdir(parents=True)
    library_path, project_path = (
        folder / (LIBRARY_SCOPE + ".pslx"),
        folder / (project_name + ".pscx"),
    )
    library_hash = _write_new(library_path, library)
    project_hash = _write_new(project_path, root)
    return {
        "project_path": str(project_path.resolve()),
        "project_sha256": project_hash,
        "project_name": project_name,
        "library_path": str(library_path.resolve()),
        "library_sha256": library_hash,
        "master_path": str(source.resolve()),
        "master_sha256_before": before,
        "master_sha256_after": _sha(source.read_bytes()),
        "parameters": asdict(parameters),
        "voltage_convention": VOLTAGE_CONVENTION,
        "operating_windows": OPERATING_WINDOWS,
        "channels": channels,
        "routes": writer.routes,
        "library_routes": library_writer.routes,
        "route_contacts_verified": True,
        "licensed_acceptance": "NOT_RUN",
    }
