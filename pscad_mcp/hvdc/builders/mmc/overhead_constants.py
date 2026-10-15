"""Audited two-conductor overhead geometry and fresh native phase constants."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from xml.etree import ElementTree as ET

from .cable_constants import (
    _coefficient_structure,
    _fit_errors,
    parse_cable_phase_output,
)
from .line_constants import (
    LineConstantsArtifact,
    TlineSegment,
    extract_tline_segments,
    render_tli,
)

DEFAULT_OVERHEAD_DONOR = Path(
    r"C:\Users\Public\Documents\PSCAD\4.6\Examples\ModelsInProgress\H_MMC_Mono_DC.pscx"
)
SCOPE = "native_overhead_line_constants_only"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def _quantity(values, name, unit=None):
    raw = values.get(name, "")
    match = re.fullmatch(r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s*(?:\[([^]]+)\])?\s*", raw)
    if match is None or (match[2] is not None and match[2] != unit):
        raise ValueError(f"Unsupported overhead quantity or units: {name}")
    number = float(match[1])
    if not math.isfinite(number):
        raise ValueError(f"Overhead quantity must be finite: {name}")
    return number


@dataclass(frozen=True)
class OverheadConfiguration:
    project_path: str
    project_sha256: str
    master_path: str
    master_sha256: str
    segment: TlineSegment

    def to_dict(self):
        return asdict(self)

    def dc_profile(self):
        tower = self.segment.tower
        resistance = _quantity(tower, "DCResC", "ohm/km") / _quantity(tower, "NCondB")
        return {
            "schema_version": 1, "dc_link_kind": "overhead_line", "conductors": 2,
            "conductor_dc_resistance_ohm_per_km": [resistance, resistance],
            "geometry_sha256": hashlib.sha256(_canonical(asdict(self.segment)).encode()).hexdigest(),
        }


def extract_overhead_configuration(project_path, *, master_path):
    source, master = Path(project_path).resolve(), Path(master_path).resolve()
    if any(path.is_symlink() or not path.is_file() for path in (source, master)):
        raise ValueError("Overhead sources must be immutable regular files")
    source_hash, master_hash = _sha(source), _sha(master)
    root = ET.parse(source).getroot()
    if root.get("version") != "4.6.2":
        raise ValueError("Native overhead geometry requires a PSCAD 4.6.2 source")
    definitions = root.findall("./definitions/Definition[@name='DCTL']")
    if len(definitions) != 1 or definitions[0].findall(".//script"):
        raise ValueError("One native DCTL geometry without scripts is required")
    types = definitions[0].findall("./paramlist/param[@name='type']")
    if len(types) != 1 or types[0].get("value") != "TLine":
        raise ValueError("DCTL must declare a native overhead TLine")
    allowed = {"master:Line_FrePhase_Options", "master:Line_Ground", "master:Line_Tower_2_Flat"}
    users = definitions[0].findall("./schematic/User")
    if len(users) != 3 or {item.get("defn") for item in users} != allowed:
        raise ValueError("Only the audited flat two-conductor overhead tower is supported")
    segments = extract_tline_segments(source)
    segment = segments[0]
    if any(s.conductors != 2 or s.frequency_hz != 0 or s.tower != segment.tower
           or s.options != segment.options or s.ground != segment.ground for s in segments):
        raise ValueError("Overhead segments must use the same two-conductor DC geometry")
    for wire in root.findall(".//Wire[@classid='TLine']"):
        values = {p.get("name"): p.get("value", "") for p in wire.findall("./User/paramlist/param")}
        if wire.get("defn") != root.get("name") + ":DCTL" or any(
            values.get(key) != value for key, value in {"Mode": "1", "ManEnab": "0", "CoupleEnab": "0"}.items()
        ):
            raise ValueError("Manual, mutually coupled or non-phase overhead segments are unsupported")
    tower = segment.tower
    for key, value in {"CDataType": 1, "GDataType": 1, "Hollow": 0, "SHSag": 0,
                       "SHBund": 1, "BundSym": 0, "Transp": 1, "NG": 1,
                       "ElimGW": 1, "GWSame": 1, "NC1": 1, "NC2": 2}.items():
        if _quantity(tower, key) != value:
            raise ValueError(f"Unsupported overhead geometry setting: {key}")
    for key, unit in {"RadiusC": "m", "DCResC": "ohm/km", "Y": "m", "XC": "m",
                      "BSP": "m", "RadiusG": "m", "DCResG": "ohm/km", "YG": "m"}.items():
        _positive(_quantity(tower, key, unit), key)
    bundle = _quantity(tower, "NCondB")
    if bundle != int(bundle) or not 1 <= bundle <= 10:
        raise ValueError("Overhead bundle count must be a supported positive integer")
    for key, unit in {"SAGC": "m", "SAGG": "m", "XG": "m", "ShuntG": "mho/m"}.items():
        if _quantity(tower, key, unit) < 0:
            raise ValueError(f"Overhead quantity must be nonnegative: {key}")
    if _quantity(tower, "SAGC", "m") >= _quantity(tower, "Y", "m"):
        raise ValueError("Overhead conductor sag intersects ground")
    for values in (segment.ground, segment.options):
        for raw in values.values():
            if raw and re.match(r"^[-+\d.]", raw) and not math.isfinite(float(re.match(r"[-+\d.eE]+", raw)[0])):
                raise ValueError("Overhead options must be finite")
    if _sha(source) != source_hash or _sha(master) != master_hash:
        raise ValueError("Overhead source changed during geometry audit")
    return OverheadConfiguration(str(source), source_hash, str(master), master_hash, segment)


def render_overhead_tli(configuration, *, length_km, reference_frequency_hz, name):
    length = _positive(length_km, "length_km")
    frequency = _positive(reference_frequency_hz, "reference_frequency_hz")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", name) is None:
        raise ValueError("Overhead segment name must be a portable native identifier")
    text = render_tli(replace(configuration.segment, name=name, length_km=length))
    # DCenab/DCCOR/ECLS/shntcab are cable-only conditional options in Master.
    # The native overhead model uses its own metallic/ground delay groups.
    return text + ("\nOutput File Display Options:\n   {\n"
                   f"   Frequency for Calculation = {frequency:.15g}\n"
                   "   Zero Tolerance for Display = 1e-19\n"
                   "   Base Voltage for Display = 230\n   Base MVA for Display = 100\n"
                   "   Create PI-Section = 0\n   }\n")


def _validated_output(configuration, constants, log, output, frequency):
    options = {key: float(value) for key, value in configuration.segment.options.items()
               if key in {"YMaxP", "AMaxP", "YMaxE", "AMaxE", "MaxRPtol"}}
    options.setdefault("MaxRPtol", 100.0)
    coefficients = _coefficient_structure(constants, conductors=2, options=options, allow_multiple_delay_groups=True)
    if "Unknown Data Line Ignored" in log:
        raise ValueError("Native overhead input contains ignored data")
    fit = _fit_errors(log)
    if fit.get("dc_correction_applied"):
        raise ValueError("Cable DC correction cannot certify an overhead model")
    for field, key in (("admittance_requested_error_percent", "YMaxE"), ("propagation_requested_error_percent", "AMaxE"),
                       ("admittance_pole_limit", "YMaxP"), ("propagation_pole_limit", "AMaxP")):
        if not math.isclose(fit[field], options[key], rel_tol=1e-9):
            raise ValueError("Overhead fitting limits differ from the immutable geometry")
    if (fit["admittance_max_error_percent"] > options["YMaxE"]
            or fit["propagation_max_error_percent"] > options["AMaxE"]
            or fit["max_residue_pole_ratio"] > options["MaxRPtol"]):
        raise ValueError("Overhead fit exceeds its source tolerance")
    if (max(coefficients["admittance_pole_counts"]) != fit["admittance_poles"]
            or coefficients["propagation_pole_counts"] != tuple(g["poles"] for g in fit["delay_groups"])
            or len(coefficients["time_delays_s"]) != len(fit["delay_groups"])
            or any(not math.isclose(delay, group["time_delay_s"], abs_tol=5e-10, rel_tol=0)
                   for delay, group in zip(coefficients["time_delays_s"], fit["delay_groups"]))):
        raise ValueError("Overhead coefficient layout differs from its native fitting log")
    phase = parse_cable_phase_output(output, conductors=2, reference_frequency_hz=frequency)
    c = phase.to_dict()["capacitance_f_per_km"]
    capacitance = (c[0][0] + c[1][1] - c[0][1] - c[1][0]) / 4
    _positive(capacitance, "differential_capacitance_f_per_km")
    if not math.isclose(c[0][1], c[1][0], rel_tol=1e-9, abs_tol=1e-18):
        raise ValueError("Overhead phase capacitance is not reciprocal")
    return coefficients, fit, phase, capacitance


@dataclass(frozen=True)
class OverheadConstantsArtifact(LineConstantsArtifact):
    length_km: float
    conductor_dc_resistance_ohm_per_km: tuple[float, float]
    differential_capacitance_f_per_km: float
    phase_data: object
    coefficient_structure: dict
    fit_record: dict
    evidence_path: str

    @property
    def loop_dc_resistance_ohm(self):
        return math.fsum(self.conductor_dc_resistance_ohm_per_km) * self.length_km

    def to_dict(self):
        return {**super().to_dict(), "length_km": self.length_km, "dc_link_kind": "overhead_line",
                "conductor_dc_resistance_ohm_per_km": list(self.conductor_dc_resistance_ohm_per_km),
                "loop_dc_resistance_ohm": self.loop_dc_resistance_ohm,
                "differential_capacitance_f_per_km": self.differential_capacitance_f_per_km,
                "phase_data": self.phase_data.to_dict(), "coefficient_structure": self.coefficient_structure,
                "fit_record": self.fit_record, "evidence_path": self.evidence_path}


def generate_public_overhead_constants(project_path, output_dir, *, master_path, executable=None,
                                       lengths_km=(200.0,), reference_frequency_hz=60.0,
                                       timeout_s=300.0):
    model = extract_overhead_configuration(project_path, master_path=master_path)
    lengths = tuple(_positive(v, "length_km") for v in lengths_km)
    if not lengths or len(set(lengths)) != len(lengths):
        raise ValueError("Overhead lengths must be nonempty and unique")
    frequency, timeout = _positive(reference_frequency_hz, "frequency"), _positive(timeout_s, "timeout")
    tline = Path(executable or Path(master_path).parent / "bin/win/tline.exe").resolve()
    if tline.is_symlink() or not tline.is_file():
        raise FileNotFoundError("Native overhead tline executable is unavailable")
    sources = {str(Path(p).resolve()): _sha(p) for p in (project_path, master_path, tline)}
    destination = Path(output_dir).resolve()
    if any(destination.is_relative_to(Path(p).resolve().parent) for p in sources):
        raise ValueError("Overhead outputs must be disjoint from immutable source directories")
    destination.mkdir(parents=True, exist_ok=False)
    artifacts = []
    for index, length in enumerate(lengths):
        case = destination / f"length-{index}"
        case.mkdir()
        name = f"OHL{index}"
        input_path, constants_path, output_path, log_path = (case / (name + suffix) for suffix in (".tli", ".tlo", ".out", ".log"))
        evidence = case / "evidence.json"
        command = (str(tline), input_path.name)
        report = {"scope": SCOPE, "status": "FAIL", "configuration": model.to_dict(), "length_km": length,
                  "reference_frequency_hz": frequency, "source_hashes_before": sources,
                  "command": list(command), "implementation_sha256": _sha(__file__)}
        try:
            if {p: _sha(p) for p in sources} != sources:
                raise ValueError("Overhead source changed before generation")
            input_path.write_text(render_overhead_tli(model, length_km=length, reference_frequency_hz=frequency, name=name), encoding="ascii")
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(command, cwd=case, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
            report["returncode"] = completed.returncode
            if completed.returncode or not constants_path.is_file() or not output_path.is_file():
                raise RuntimeError("Native overhead constants generation failed; see the preserved log")
            coefficients, fit, phase, capacitance = _validated_output(
                model, constants_path.read_text(), log_path.read_text(), output_path.read_text(), frequency)
            artifact = OverheadConstantsArtifact(name, str(input_path), str(constants_path), str(log_path), str(output_path),
                _sha(input_path), _sha(constants_path), _sha(log_path), _sha(output_path), command, completed.returncode,
                length, tuple(model.dc_profile()["conductor_dc_resistance_ohm_per_km"]), capacitance,
                phase, coefficients, fit, str(evidence))
            report.update(artifact.to_dict())
            report["status"] = "PASS"
            artifacts.append(artifact)
        except Exception as error:
            report["error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            report["source_hashes_after"] = {p: _sha(p) for p in sources}
            changed = report["source_hashes_after"] != sources
            if changed:
                report.update(status="FAIL", error={"type": "ValueError", "message": "Immutable overhead inputs changed"})
            report["produced_files"] = {p.name: _sha(p) for p in sorted(case.iterdir()) if p.is_file() and p != evidence}
            evidence.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            if changed:
                raise ValueError("Immutable overhead inputs changed during generation")
    return tuple(artifacts)


def verify_overhead_constants_receipt(evidence, source, master):
    evidence, source, master = (Path(p).resolve() for p in (evidence, source, master))
    report = json.loads(evidence.read_text())
    model = extract_overhead_configuration(source, master_path=master)
    if report.get("scope") != SCOPE or report.get("status") != "PASS" or report.get("returncode") != 0:
        raise ValueError("A passing native overhead receipt is required")
    if _canonical(report.get("configuration")) != _canonical(model.to_dict()):
        raise ValueError("Overhead receipt geometry differs from the immutable source")
    before = report.get("source_hashes_before", {})
    if (len(before) != 3 or report.get("source_hashes_after") != before
            or before.get(str(source)) != _sha(source) or before.get(str(master)) != _sha(master)
            or any(Path(p).is_symlink() or not Path(p).is_file() or _sha(p) != h for p, h in before.items())):
        raise ValueError("Overhead receipt source hashes changed or are incomplete")
    files = report.get("produced_files", {})
    if not files:
        raise ValueError("Overhead receipt lacks produced-file hashes")
    for filename, digest in files.items():
        path = evidence.parent / filename
        if Path(filename).name != filename or path.is_symlink() or not path.is_file() or _sha(path) != digest:
            raise ValueError("Overhead produced artifact changed or escaped its receipt")
    paths = {}
    for key in ("input", "constants", "log", "output"):
        path = Path(report[key + "_path"])
        if path.parent != evidence.parent or files.get(path.name) != report[key + "_sha256"]:
            raise ValueError("Overhead receipt paths or hashes disagree")
        paths[key] = path
    expected_input = render_overhead_tli(model, length_km=report["length_km"], reference_frequency_hz=report["reference_frequency_hz"], name=report["segment"])
    if paths["input"].read_text() != expected_input:
        raise ValueError("Overhead native input does not describe its frozen geometry")
    coefficients, fit, phase, capacitance = _validated_output(model, paths["constants"].read_text(), paths["log"].read_text(),
                                                             paths["output"].read_text(), report["reference_frequency_hz"])
    resistance = math.fsum(model.dc_profile()["conductor_dc_resistance_ohm_per_km"]) * report["length_km"]
    if (not math.isclose(report["loop_dc_resistance_ohm"], resistance, rel_tol=1e-12)
            or not math.isclose(report["differential_capacitance_f_per_km"], capacitance, rel_tol=1e-12)
            or _canonical(report["coefficient_structure"]) != _canonical(coefficients)
            or _canonical(report["fit_record"]) != _canonical(fit)
            or _canonical(report["phase_data"]) != _canonical(phase.to_dict())):
        raise ValueError("Overhead physical or coefficient evidence differs from its native artifacts")
    return model, report, paths, before
