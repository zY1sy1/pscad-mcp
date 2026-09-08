"""Source-backed coax cable constants through PSCAD's public .cli interface.

The supported geometry is the installed VSCTrans Cable2 profile: two buried
coaxial cables, radial dimensions, and eliminated outer sheaths. Native
frequency-dependent phase constants remain distinct from core DC resistance.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType
from xml.etree import ElementTree as ET

from ....core.definition_metadata import read_definition_metadata_document
from .line_constants import LineConstantsArtifact

_DEFAULT_MASTER = Path(r"C:\Program Files (x86)\PSCAD46\master.pslx")
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_QUANTITY = re.compile(rf"\s*({_NUMBER})\s*(?:\[([^\]]+)\])?\s*")
_PAIR = re.compile(rf"({_NUMBER})\s*,\s*({_NUMBER})")
_GEOMETRY_FIELDS = (
    "CABNUM", "X", "Y", "OHC", "LL", "LC", "RorT", "SemiCL", "CROSSBOND",
    "R1", "R2", "RHOC", "PERMC", "R3", "EPS1", "PERM1", "R4", "RHOS",
    "PERMS", "R5", "EPS2", "PERM2",
)
_GROUND_FIELDS = ("GrRho", "GRRES", "GPERM", "EarthForm", "EarthForm2", "EarthForm3")
_OPTION_FIELDS = (
    "Interp1", "Output", "Inflen", "FS", "FE", "Numf", "YMaxP", "YMaxE",
    "AMaxP", "AMaxE", "MaxRPtol", "W1", "W2", "W3", "CPASS", "DCenab",
)
_DISPLAY_FIELDS = ("DataF", "Zero_Tol", "Vbase", "MVAbase", "picomp")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes(paths) -> dict[str, str | None]:
    result = {}
    for path in paths:
        try:
            result[path] = _sha256(Path(path))
        except OSError:
            result[path] = None
    return result


def _one(values, context: str):
    items = tuple(values)
    if len(items) != 1:
        raise ValueError(f"Expected one {context}; found {len(items)}")
    return items[0]


def _number(value: object, context: str, unit: str = "") -> float:
    match = _QUANTITY.fullmatch(str(value))
    if match is None:
        raise ValueError(f"Invalid numeric cable parameter {context}: {value!r}")
    observed_unit = match.group(2)
    if observed_unit is not None and observed_unit.strip() != unit:
        raise ValueError(f"Unexpected unit for {context}: {observed_unit!r}; expected {unit!r}")
    number = float(match.group(1).replace("D", "E").replace("d", "e"))
    if not math.isfinite(number):
        raise ValueError(f"Cable parameter {context} must be finite")
    return number


def _positive(value: object, context: str) -> float:
    number = _number(value, context)
    if number <= 0:
        raise ValueError(f"Cable parameter {context} must be positive")
    return number


def _parameters(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for parameter in element.findall("./paramlist/param"):
        name = parameter.get("name", "")
        if name in result:
            raise ValueError(f"Duplicate cable parameter {name!r}")
        result[name] = parameter.get("value", "")
    return result


def _component_parameters(element, definition_name, fields, metadata):
    definition = _one(metadata.get(definition_name, ()), f"Master definition {definition_name}")
    supplied = _parameters(element) if element is not None else {}
    values = {}
    for name in fields:
        contract = definition.parameters.get(name)
        if contract is None:
            raise ValueError(f"Master {definition_name} parameter {name!r} is missing")
        values[name] = _number(
            supplied.get(name, contract.default), f"{definition_name}.{name}", contract.unit or ""
        )
    return MappingProxyType(values)


@dataclass(frozen=True)
class CoaxCableGeometry:
    number: int
    parameters: Mapping[str, float]

    @property
    def core_area_m2(self) -> float:
        return math.pi * (self.parameters["R2"] ** 2 - self.parameters["R1"] ** 2)

    @property
    def core_dc_resistance_ohm_per_km(self) -> float:
        return self.parameters["RHOC"] * 1000.0 / self.core_area_m2

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "parameters_in_master_units": dict(self.parameters),
            "core_area_m2": self.core_area_m2,
            "core_dc_resistance_ohm_per_km": self.core_dc_resistance_ohm_per_km,
            "resistance_equation": "rho * 1000 / (pi * (outer_radius^2 - inner_radius^2))",
        }


@dataclass(frozen=True)
class CableConfiguration:
    name: str
    definition_name: str
    length_km: float
    steady_state_frequency_hz: float
    conductors: int
    cables: tuple[CoaxCableGeometry, ...]
    ground: Mapping[str, float]
    options: Mapping[str, float]
    display: Mapping[str, float]
    project_path: str
    project_sha256: str
    master_path: str
    master_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "definition_name": self.definition_name,
            "source_length_km": self.length_km,
            "steady_state_frequency_hz": self.steady_state_frequency_hz,
            "conductors": self.conductors,
            "cables": [cable.to_dict() for cable in self.cables],
            "ground": dict(self.ground), "options": dict(self.options),
            "display": dict(self.display), "project_path": self.project_path,
            "project_sha256": self.project_sha256, "master_path": self.master_path,
            "master_sha256": self.master_sha256,
        }


def extract_cable_configuration(
    project_path: str | Path,
    *,
    master_path: str | Path = _DEFAULT_MASTER,
    definition_name: str = "Cable2",
) -> CableConfiguration:
    """Extract one native cable and resolve omitted fields from immutable Master metadata."""

    project, master = Path(project_path).resolve(), Path(master_path).resolve()
    project_bytes, master_bytes = project.read_bytes(), master.read_bytes()
    root, master_root = ET.fromstring(project_bytes), ET.fromstring(master_bytes)
    if root.get("version") != "4.6.2" or master_root.get("version") != "4.6.2":
        raise ValueError("Only PSCAD 4.6.2 cable input metadata is supported")
    metadata = read_definition_metadata_document(master_bytes)
    definition = _one(
        (item for item in root.findall("./definitions/Definition") if item.get("name") == definition_name),
        f"cable definition {definition_name}",
    )
    if _parameters(definition).get("type") != "Cable":
        raise ValueError("The selected definition is not a native Cable")
    scoped_name = f"{root.get('name')}:{definition_name}"
    wire = _one(
        (item for item in root.findall(".//Wire")
         if item.get("classid") == "Cable" and item.get("defn") == scoped_name),
        f"native Cable instance {scoped_name}",
    )
    wrapper = _parameters(_one(wire.findall("./User"), "Cable configuration wrapper"))
    name = wrapper.get("Name", "")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", name) is None:
        raise ValueError("Cable name must be a portable PSCAD identifier")
    if _number(wrapper.get("Mode"), "Mode") != 0 or _number(wrapper.get("CoupleEnab"), "CoupleEnab") != 0:
        raise ValueError("Manual or externally coupled cable configurations are unsupported")
    conductors = _number(wrapper.get("Dim"), "Dim")
    if conductors != 2:
        raise ValueError("Only the two-conductor cable profile is supported")
    length = _number(wrapper.get("Length"), "Length", "km")
    frequency = _number(wrapper.get("Freq"), "Freq", "Hz")
    if length <= 0 or frequency < 0:
        raise ValueError("Cable length must be positive and steady-state frequency non-negative")
    components = definition.findall("./schematic/User")
    allowed = {"master:Cable_Coax", "master:Line_Ground", "master:Line_FrePhase_Options", "master:Line_Out_Disp"}
    unsupported = sorted({item.get("defn", "") for item in components} - allowed)
    if unsupported:
        raise ValueError(f"Cable model data definitions are unsupported: {unsupported}")

    def component(name):
        return _one((item for item in components if item.get("defn") == f"master:{name}"), name)

    cables = []
    for element in components:
        if element.get("defn") != "master:Cable_Coax":
            continue
        values = _component_parameters(element, "Cable_Coax", _GEOMETRY_FIELDS, metadata)
        for selector, expected in {"OHC": 0, "LL": 3, "LC": 1, "RorT": 0, "SemiCL": 0, "CROSSBOND": 0}.items():
            if values[selector] != expected:
                raise ValueError(f"Cable_Coax.{selector}={values[selector]} is unsupported")
        radii = [values[name] for name in ("R1", "R2", "R3", "R4", "R5")]
        if radii[0] < 0 or any(left >= right for left, right in pairwise(radii)):
            raise ValueError("Each cable radius must be greater than the preceding radius")
        for field in ("Y", "RHOC", "RHOS", "PERMC", "PERMS", "EPS1", "EPS2", "PERM1", "PERM2"):
            _positive(values[field], f"Cable_Coax.{field}")
        number = values["CABNUM"]
        if number not in (1, 2):
            raise ValueError("Cable numbers must be 1 and 2")
        cables.append(CoaxCableGeometry(int(number), values))
    cables.sort(key=lambda cable: cable.number)
    if [cable.number for cable in cables] != [1, 2]:
        raise ValueError("The native profile requires exactly two uniquely numbered coax cables")
    separation = math.hypot(cables[0].parameters["X"] - cables[1].parameters["X"],
                            cables[0].parameters["Y"] - cables[1].parameters["Y"])
    if separation <= sum(cable.parameters["R5"] for cable in cables):
        raise ValueError("Cable outer insulation layers overlap")
    ground = _component_parameters(component("Line_Ground"), "Line_Ground", _GROUND_FIELDS, metadata)
    options = _component_parameters(component("Line_FrePhase_Options"), "Line_FrePhase_Options", _OPTION_FIELDS, metadata)
    displays = [item for item in components if item.get("defn") == "master:Line_Out_Disp"]
    display = _component_parameters(_one(displays, "display options") if displays else None,
                                    "Line_Out_Disp", _DISPLAY_FIELDS, metadata)
    if ground["GrRho"] != 0 or options["CPASS"] != 0 or options["DCenab"] != 0 or options["Inflen"] != 0:
        raise ValueError("Frequency-dependent ground, extra DC correction, passivity sweeps, or infinite length are unsupported")
    if display["picomp"] != 0:
        raise ValueError("Automatic native pi-section creation is unsupported")
    for values, fields in ((ground, ("GRRES", "GPERM")), (options, ("FS", "FE", "YMaxE", "AMaxE", "YMaxP", "AMaxP", "Numf"))):
        for field in fields:
            _positive(values[field], field)
    if options["FS"] >= options["FE"]:
        raise ValueError("Cable fitting frequencies must increase")
    return CableConfiguration(
        name, definition_name, length, frequency, 2, tuple(cables), ground, options, display,
        str(project), hashlib.sha256(project_bytes).hexdigest(),
        str(master), hashlib.sha256(master_bytes).hexdigest(),
    )


def _section(name: str, values: Sequence[tuple[str, object]]) -> list[str]:
    return [f"{name}:", "   {", *(f"   {key} = {value}" for key, value in values), "   }"]


def _format(value: float) -> str:
    return f"{value:.15g}"


def render_cable_cli(
    configuration: CableConfiguration,
    *,
    length_km: float | None = None,
    reference_frequency_hz: float = 50.0,
    name: str | None = None,
) -> str:
    """Render the verified PSCAD cable syntax; the file must use a .cli suffix."""

    length = _positive(configuration.length_km if length_km is None else length_km, "length_km")
    frequency = _positive(reference_frequency_hz, "reference_frequency_hz")
    cable_name = configuration.name if name is None else name
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", cable_name) is None:
        raise ValueError("Cable input name must be a portable PSCAD identifier")
    lines = _section("Cable Summary", [
        ("Cable Name", cable_name), ("Cable Length", _format(length)),
        ("Steady State Frequency", _format(configuration.steady_state_frequency_hz)),
        ("Number of Conductors", configuration.conductors),
    ])
    geometry_labels = (
        ("Layers", "LL"), ("Ground Last Layer", "LC"),
        ("Conductor Inner Radius", "R1"), ("Conductor Outer Radius", "R2"),
        ("Conductor Resistivity", "RHOC"), ("Conductor Permeability", "PERMC"),
        ("Insulator 1 Outer Radius", "R3"), ("Insulator 1 Relative Permittivity", "EPS1"),
        ("Insulator 1 Relative Permeability", "PERM1"), ("Sheath Outer Radius", "R4"),
        ("Sheath Resistivity", "RHOS"), ("Sheath Permeability", "PERMS"),
        ("Insulator 2 Outer Radius", "R5"), ("Insulator 2 Relative Permittivity", "EPS2"),
        ("Insulator 2 Relative Permeability", "PERM2"),
    )
    for cable in configuration.cables:
        values = cable.parameters
        lines.extend(_section("Coax Cable", [
            ("Cable Number", cable.number), ("P1", f"{_format(values['X'])} {_format(values['Y'])}"),
            *((label, _format(values[key])) for label, key in geometry_labels),
        ]))
    option_labels = (
        ("Interpolate Travel Times", "Interp1"), ("Infinite Line Length", "Inflen"),
        ("Curve Fitting Start Frequency", "FS"), ("Curve Fitting End Frequency", "FE"),
        ("Total Number of Frequency Increments", "Numf"),
        ("Maximum # of Poles for Surge Admittance Fit", "YMaxP"),
        ("Maximum # of Poles for Attenuation Constant Fit", "AMaxP"),
        ("Maximum Fitting Error (%) for Surge Admittance", "YMaxE"),
        ("Maximum Fitting Error (%) for Attenuation Constant", "AMaxE"),
        ("Maximum Residue/Pole Ratio Tolerance", "MaxRPtol"),
        ("Weighting Factor 1", "W1"), ("Weighting Factor 2", "W2"),
        ("Weighting Factor 3", "W3"), ("Write Detailed Output Files", "Output"),
    )
    lines.extend(_section("Frequency Dep. (Phase) Model Options", [
        (label, _format(configuration.options[key])) for label, key in option_labels
    ]))
    ground_labels = (
        ("Ground Resistivity Type", "GrRho"), ("GroundResistivity", "GRRES"),
        ("GroundPermeability", "GPERM"), ("EarthImpedanceFormula", "EarthForm2"),
        ("EarthUImpedanceFormula", "EarthForm"), ("EarthMImpedanceFormula", "EarthForm3"),
    )
    lines.extend(_section("Line Constants Ground Data", [
        (label, _format(configuration.ground[key])) for label, key in ground_labels
    ]))
    lines.extend(_section("Output File Display Options", [
        ("Frequency for Calculation", _format(frequency)),
        ("Zero Tolerance for Display", _format(configuration.display["Zero_Tol"])),
        ("Base Voltage for Display", _format(configuration.display["Vbase"])),
        ("Base MVA for Display", _format(configuration.display["MVAbase"])),
        ("Create PI-Section", 0),
    ]))
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class CablePhaseData:
    reference_frequency_hz: float
    impedance_ohm_per_m: tuple[tuple[complex, ...], ...]
    admittance_s_per_m: tuple[tuple[complex, ...], ...]
    minimum_delay_s: float
    recommended_step_s: float

    def to_dict(self) -> dict[str, object]:
        omega = 2.0 * math.pi * self.reference_frequency_hz
        z, y = self.impedance_ohm_per_m, self.admittance_s_per_m
        return {
            "reference_frequency_hz": self.reference_frequency_hz,
            "impedance_ohm_per_m": [[{"real": item.real, "imag": item.imag} for item in row] for row in z],
            "admittance_s_per_m": [[{"real": item.real, "imag": item.imag} for item in row] for row in y],
            "resistance_ohm_per_km": [[item.real * 1000.0 for item in row] for row in z],
            "inductance_h_per_km": [[item.imag * 1000.0 / omega for item in row] for row in z],
            "conductance_s_per_km": [[item.real * 1000.0 for item in row] for row in y],
            "capacitance_f_per_km": [[item.imag * 1000.0 / omega for item in row] for row in y],
            "minimum_delay_s": self.minimum_delay_s, "recommended_step_s": self.recommended_step_s,
        }


def parse_cable_phase_output(
    output: str, *, conductors: int, reference_frequency_hz: float
) -> CablePhaseData:
    """Read uncorrected per-metre phase Z/Y, retaining their declared frequency."""

    frequency = _positive(reference_frequency_hz, "reference_frequency_hz")
    observed = _one(re.findall(rf"PHASE DOMAIN DATA\s*@\s*({_NUMBER})\s*Hz:", output), "phase frequency")
    if not math.isclose(_number(observed, "phase frequency"), frequency, rel_tol=0.0, abs_tol=0.0005):
        raise ValueError("Native phase output has the wrong reference frequency")

    def matrix(label):
        parts = output.split(label)
        if len(parts) != 2:
            raise ValueError(f"Expected one native {label}")
        rows = []
        for line in parts[1].strip().splitlines():
            if not line.strip():
                break
            matches = list(_PAIR.finditer(line))
            if len(matches) != conductors or _PAIR.sub("", line).strip():
                raise ValueError(f"Invalid or ragged native {label}")
            rows.append(tuple(complex(_number(match[1], label), _number(match[2], label)) for match in matches))
        if len(rows) != conductors:
            raise ValueError(f"Native {label} has the wrong dimension")
        return tuple(rows)

    def timing(label):
        value = _one(re.findall(rf"{label}\s*\[ms\]:\s*({_NUMBER})", output), label)
        return _positive(value, label) * 0.001

    return CablePhaseData(
        frequency, matrix("SERIES IMPEDANCE MATRIX (Z) [ohms/m]:"),
        matrix("SHUNT ADMITTANCE MATRIX (Y) [mhos/m]:"),
        timing("Minimum Time Delay for the Line"), timing("Recommended Time Step for the Line"),
    )


def _coefficient_structure(constants: str, *, conductors: int, options: Mapping[str, float]) -> dict[str, object]:
    """Validate the complete coefficient layout observed in native two-core outputs."""

    lines = [line.strip() for line in constants.splitlines() if line.strip() and not line.lstrip().startswith("!")]
    position = 0
    scalar_count = 0

    def take(context):
        nonlocal position
        if position >= len(lines):
            raise RuntimeError(f"Native cable coefficients are incomplete at {context}")
        value = lines[position]
        position += 1
        return value

    def label(expected):
        if take(expected) != expected:
            raise RuntimeError(f"Native cable coefficients require {expected!r}")

    def count(context, maximum):
        value = take(context)
        if re.fullmatch(r"\d+", value) is None or not 1 <= int(value) <= maximum:
            raise RuntimeError(f"Native cable coefficients have an invalid {context}")
        return int(value)

    def scalar(context):
        nonlocal scalar_count
        try:
            value = _number(take(context), context)
        except ValueError as error:
            raise RuntimeError(f"Native cable coefficients have an invalid {context}") from error
        scalar_count += 1
        return value

    header = re.fullmatch(r"Fre-Phase\s+(\d+)\s+0\s+1\s+1\s*/", take("header"))
    if header is None or int(header[1]) != conductors or conductors != 2:
        raise RuntimeError("Native cable coefficients have an unsupported model header")
    label("Fitting parameters for the char. admittance:")
    label("N.o. conductors:")
    if count("admittance conductor count", conductors) != conductors:
        raise RuntimeError("Native cable coefficients have inconsistent conductor dimensions")
    label("Residues and poles:")
    admittance_counts = []
    for row in range(conductors):
        poles = count("admittance pole count", options["YMaxP"])
        admittance_counts.append(poles)
        # Each pole has a complex pole and one complex residue per conductor.
        for _ in range(poles * 2 * (conductors + 1)):
            scalar(f"admittance row {row + 1}")
    for _ in range(conductors**2):
        scalar("admittance direct matrix")
    label("Fitting parameters for the propagation function:")
    label("N.o. delay groups:")
    delay_groups = count("delay-group count", conductors)
    if delay_groups != 1:
        raise RuntimeError("Native cable coefficients with multiple delay groups require an independently verified layout")
    label("Time delays:")
    delay = scalar("propagation time delay")
    if delay <= 0:
        raise RuntimeError("Native cable coefficients have a non-positive time delay")
    label("Poles:")
    propagation_poles = count("propagation pole count", options["AMaxP"])
    for _ in range(2 * propagation_poles):
        scalar("propagation pole")
    label("Residues:")
    for _ in range(conductors**2 * 2 * propagation_poles):
        scalar("propagation residue matrix")
    if position != len(lines):
        raise RuntimeError("Native cable coefficients contain trailing data after the residue matrices")
    return {
        "conductors": conductors, "admittance_pole_counts": tuple(admittance_counts),
        "propagation_pole_counts": (propagation_poles,), "time_delays_s": (delay,),
        "delay_groups": delay_groups, "coefficient_scalar_count": scalar_count - delay_groups,
    }


def _fit_errors(log: str) -> dict[str, object]:
    """Parse complete native fit attempts and require ordered completion records."""

    def fail(message):
        raise RuntimeError(f"Native cable fit log {message}")

    def number(value, context, *, positive=False):
        try:
            result = _number(value, context)
        except ValueError:
            fail(f"has a non-finite or invalid {context}")
        if result < 0 or (positive and result == 0):
            fail(f"has an invalid {context}")
        return result

    def match(pattern, line, context):
        result = re.fullmatch(pattern, line)
        if result is None:
            fail(f"has an incomplete or invalid {context}")
        return result

    lines = [" ".join(line.split()) for line in log.splitlines() if line.strip() and set(line.strip()) - {"-", "=", " "}]
    if lines.count("Line Constants Ending!") != 1 or lines.count("Tline Ending....") != 1:
        fail("is missing unique completion markers")
    end = lines.index("Line Constants Ending!")
    if lines[end:] != ["Line Constants Ending!", "Tline Ending....", "0"]:
        fail("has incomplete or unexpected trailing completion records")
    lines = lines[:end]
    yc_title, h_title = "Fitting Characteristic Admittance Yc:", "Fitting Propagation Function H:"
    if lines.count(yc_title) != 1 or lines.count(h_title) != 1:
        fail("is missing unique fitting sections")
    yc_start, h_start = lines.index(yc_title), lines.index(h_title)
    yc = lines[yc_start + 1:h_start]
    if len(yc) != 5 or yc[2:4] != ["Yc: Maximum Number", "Fitting Error of Poles"]:
        fail("has an incomplete admittance record")
    yc_limit = number(match(rf"Maximum Fitting Error Requested: ({_NUMBER}) %", yc[0], "admittance limit")[1], "admittance limit", positive=True)
    yc_pole_limit = int(match(r"Maximum Number of Poles: (\d+)", yc[1], "admittance pole limit")[1])
    yc_row = match(rf"({_NUMBER}) % (\d+)", yc[4], "admittance fit row")
    yc_error, yc_poles = number(yc_row[1], "admittance error"), int(yc_row[2])
    h = lines[h_start + 1:]
    if len(h) < 3:
        fail("has no complete propagation attempt")
    h_limit = number(match(rf"Maximum Fitting Error Requested: ({_NUMBER}) %", h[0], "propagation limit")[1], "propagation limit", positive=True)
    h_pole_limit = int(match(r"Maximum Number of Poles \(per delay group\): (\d+)", h[1], "propagation pole limit")[1])
    if yc_poles <= 0 or yc_poles > yc_pole_limit or h_pole_limit <= 0:
        fail("has invalid pole counts or limits")
    starts = [index for index, line in enumerate(h) if line.startswith("Attempt #")]
    if not starts or starts[0] != 2:
        fail("has an incomplete propagation attempt header")
    attempts = []
    for index, start in enumerate(starts):
        header = match(rf"Attempt # (\d+) Target error: ({_NUMBER}) %", h[start], "attempt header")
        if int(header[1]) != index + 1:
            fail("has non-sequential attempts")
        target = number(header[2], "attempt target", positive=True)
        stop = starts[index + 1] if index + 1 < len(starts) else len(h)
        body = h[start + 1:stop]
        phase_header = "Hphase: Maximum Maximum Maximum"
        if (body[:2] != ["Hmode: Delay Maximum Number Time", "Group # Fitting Error of Poles Delay"]
                or body.count(phase_header) != 1):
            fail("has an incomplete propagation table")
        phase_index = body.index(phase_header)
        modes = []
        for mode_line in body[2:phase_index]:
            mode = match(rf"(\d+) ({_NUMBER}) % (\d+) ({_NUMBER}) ms", mode_line, "delay-group row")
            group, error, poles, delay = int(mode[1]), number(mode[2], "mode error"), int(mode[3]), number(mode[4], "mode delay", positive=True) * 0.001
            if group != len(modes) + 1 or not 1 <= poles <= h_pole_limit:
                fail("has invalid delay-group dimensions or pole counts")
            modes.append({"group": group, "max_error_percent": error, "poles": poles, "time_delay_s": delay})
        phase = body[phase_index:]
        if not modes or len(phase) != 3 or phase[1] != "Fitting Error RMS Error Residue/Pole Ratio":
            fail("has an incomplete final phase record")
        values = match(rf"({_NUMBER}) % ({_NUMBER}) % ({_NUMBER})", phase[2], "phase fit row")
        maximum, rms, ratio = (number(values[column], context) for column, context in
                               ((1, "phase maximum error"), (2, "phase RMS error"), (3, "residue/pole ratio")))
        attempts.append({
            "attempt": index + 1, "target_error_percent": target, "delay_groups": modes,
            "propagation_max_error_percent": maximum, "propagation_rms_error_percent": rms,
            "max_residue_pole_ratio": ratio,
        })
    return {
        "admittance_max_error_percent": yc_error, "admittance_poles": yc_poles,
        "admittance_requested_error_percent": yc_limit, "admittance_pole_limit": yc_pole_limit,
        "propagation_requested_error_percent": h_limit, "propagation_pole_limit": h_pole_limit,
        **attempts[-1], "attempt_count": len(attempts), "attempts": attempts,
    }


@dataclass(frozen=True)
class CableConstantsArtifact(LineConstantsArtifact):
    length_km: float
    core_dc_resistance_ohm_per_km: tuple[float, ...]
    phase_data: CablePhaseData
    fit_errors_percent: tuple[float, float]
    coefficient_structure: Mapping[str, object]
    fit_record: Mapping[str, object]
    evidence_path: str

    @property
    def loop_dc_resistance_ohm(self) -> float:
        return sum(self.core_dc_resistance_ohm_per_km) * self.length_km

    def to_dict(self) -> dict[str, object]:
        return {
            **super().to_dict(), "length_km": self.length_km,
            "core_dc_resistance_ohm_per_km": list(self.core_dc_resistance_ohm_per_km),
            "loop_dc_resistance_ohm": self.loop_dc_resistance_ohm,
            "phase_data": self.phase_data.to_dict(),
            "fit_errors_percent": dict(zip(("admittance", "propagation"), self.fit_errors_percent)),
            "coefficient_structure": dict(self.coefficient_structure),
            "fit_record": dict(self.fit_record),
            "evidence_path": self.evidence_path,
        }


def generate_public_cable_constants(
    project_path: str | Path,
    output_dir: str | Path,
    *,
    master_path: str | Path = _DEFAULT_MASTER,
    definition_name: str = "Cable2",
    executable: str | Path | None = None,
    lengths_km: Sequence[float] = (100.0,),
    reference_frequency_hz: float = 50.0,
    timeout_s: float = 300.0,
) -> tuple[CableConstantsArtifact, ...]:
    """Run fresh, isolated .cli/.clo cases and preserve success or failure evidence."""

    model = extract_cable_configuration(project_path, master_path=master_path, definition_name=definition_name)
    lengths = tuple(_positive(length, "length_km") for length in lengths_km)
    if not lengths or len(set(lengths)) != len(lengths):
        raise ValueError("Cable target lengths must be non-empty and unique")
    frequency = _positive(reference_frequency_hz, "reference_frequency_hz")
    timeout = _positive(timeout_s, "timeout_s")
    configured = executable or os.environ.get("PSCAD_MCP_TLINE") or Path(model.master_path).parent / "bin/win/tline.exe"
    tline = Path(configured).resolve()
    if not tline.is_file():
        raise FileNotFoundError(f"PSCAD tline.exe was not found: {tline}")
    source_hashes = {
        model.project_path: model.project_sha256, model.master_path: model.master_sha256,
        str(tline): _sha256(tline),
    }
    destination = Path(output_dir).resolve()
    if any(Path(path).is_relative_to(destination) for path in source_hashes):
        raise ValueError("Cable evidence directory must not contain source files")
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for length in lengths:
        suffix = _format(length).replace(".", "p").replace("+", "").replace("-", "m")
        name = f"{model.name}_{suffix}km"
        case = destination / name
        case.mkdir(exist_ok=False)
        input_path, constants_path = case / f"{name}.cli", case / f"{name}.clo"
        log_path, output_path, evidence_path = case / f"{name}.log", case / f"{name}.out", case / "evidence.json"
        command = (str(tline), input_path.name)
        report: dict[str, object] = {
            "status": "FAIL", "scope": "native_cable_line_constants_only",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "implementation_sha256": _sha256(Path(__file__)),
            "configuration": model.to_dict(), "length_km": length,
            "reference_frequency_hz": frequency, "command": list(command),
            "source_hashes_before": source_hashes,
        }
        try:
            if _source_hashes(source_hashes) != source_hashes:
                raise RuntimeError("Cable source changed before native generation")
            input_path.write_text(render_cable_cli(model, length_km=length, reference_frequency_hz=frequency, name=name),
                                  encoding="ascii", newline="\n")
            with log_path.open("w", encoding="utf-8", newline="") as log:
                result = subprocess.run(list(command), cwd=case, stdout=log, stderr=subprocess.STDOUT,
                                        check=False, timeout=timeout)
            report["returncode"] = result.returncode
            if result.returncode != 0 or not constants_path.is_file() or not output_path.is_file():
                raise RuntimeError(f"Native cable constants failed: returncode={result.returncode}; log={log_path}")
            constants = constants_path.read_text(encoding="ascii")
            coefficients = _coefficient_structure(constants, conductors=model.conductors, options=model.options)
            log_text = log_path.read_text(encoding="utf-8")
            if "Unknown Data Line Ignored" in log_text:
                raise RuntimeError("Native cable input contains ignored data")
            fit = _fit_errors(log_text)
            for field, source in (("admittance_requested_error_percent", "YMaxE"),
                                  ("propagation_requested_error_percent", "AMaxE"),
                                  ("admittance_pole_limit", "YMaxP"), ("propagation_pole_limit", "AMaxP")):
                if not math.isclose(fit[field], model.options[source], rel_tol=1e-9, abs_tol=0.0):
                    raise RuntimeError(f"Native cable fit log disagrees with source {source}")
            errors = fit["admittance_max_error_percent"], fit["propagation_max_error_percent"]
            if (errors[0] > model.options["YMaxE"] or errors[1] > model.options["AMaxE"]
                    or fit["max_residue_pole_ratio"] > model.options["MaxRPtol"]):
                raise RuntimeError(f"Native cable fit exceeds source tolerance: {errors}, residue/pole={fit['max_residue_pole_ratio']}")
            if (fit["admittance_poles"] != max(coefficients["admittance_pole_counts"])
                    or tuple(group["poles"] for group in fit["delay_groups"]) != coefficients["propagation_pole_counts"]):
                raise RuntimeError("Native cable fit pole counts disagree with coefficient dimensions")
            if any(not math.isclose(group["time_delay_s"], delay, rel_tol=0.0, abs_tol=5e-10)
                   for group, delay in zip(fit["delay_groups"], coefficients["time_delays_s"])):
                raise RuntimeError("Native cable fit delays disagree with coefficients")
            phase = parse_cable_phase_output(output_path.read_text(encoding="ascii"),
                                            conductors=model.conductors, reference_frequency_hz=frequency)
            if _source_hashes(source_hashes) != source_hashes:
                raise RuntimeError("Cable source changed during native generation")
            artifact = CableConstantsArtifact(
                segment=name, input_path=str(input_path), constants_path=str(constants_path),
                log_path=str(log_path), output_path=str(output_path), input_sha256=_sha256(input_path),
                constants_sha256=_sha256(constants_path), log_sha256=_sha256(log_path),
                output_sha256=_sha256(output_path), command=command, returncode=result.returncode,
                length_km=length, core_dc_resistance_ohm_per_km=tuple(cable.core_dc_resistance_ohm_per_km for cable in model.cables),
                phase_data=phase, fit_errors_percent=errors, evidence_path=str(evidence_path),
                coefficient_structure=MappingProxyType(coefficients), fit_record=MappingProxyType(fit),
            )
            report.update(artifact.to_dict())
            report["status"] = "PASS"
            artifacts.append(artifact)
        except Exception as error:
            report["error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            after = _source_hashes(source_hashes)
            changed_after_validation = after != source_hashes and report["status"] == "PASS"
            if changed_after_validation:
                report["status"] = "FAIL"
                report["error"] = {"type": "RuntimeError", "message": "Cable source changed before evidence finalization"}
            report["source_hashes_after"] = after
            report["produced_files"] = {
                path.name: _sha256(path) for path in sorted(case.iterdir()) if path.is_file() and path != evidence_path
            }
            evidence_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            if changed_after_validation:
                raise RuntimeError("Cable source changed before evidence finalization")
    return tuple(artifacts)


__all__ = [
    "CableConfiguration", "CableConstantsArtifact", "CablePhaseData", "CoaxCableGeometry",
    "extract_cable_configuration", "generate_public_cable_constants",
    "parse_cable_phase_output", "render_cable_cli",
]
