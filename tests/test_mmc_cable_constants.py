import importlib
import json
import math
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

_GEOMETRY = {
    "CABNUM": (1, ""), "X": (0, "m"), "Y": (1, "m"),
    "OHC": (0, ""), "LL": (3, ""), "LC": (1, ""),
    "RorT": (0, ""), "SemiCL": (0, ""), "CROSSBOND": (0, ""),
    "R1": (0, "m"), "R2": (0.0104, "m"), "RHOC": (2.82e-8, "ohm*m"),
    "PERMC": (1, ""), "R3": (0.016, "m"), "EPS1": (4.1, ""),
    "PERM1": (1, ""), "R4": (0.0205, "m"), "RHOS": (1.86e-8, "ohm*m"),
    "PERMS": (1, ""), "R5": (0.0215, "m"), "EPS2": (2.3, ""), "PERM2": (1, ""),
}
_GROUND = {
    "GrRho": (0, ""), "GRRES": (100, "ohm*m"), "GPERM": (1, ""),
    "EarthForm": (0, ""), "EarthForm2": (0, ""), "EarthForm3": (2, ""),
}
_OPTIONS = {
    "Interp1": (1, ""), "Output": (1, ""), "Inflen": (0, ""),
    "FS": (0.001, "Hz"), "FE": (1e5, "Hz"), "Numf": (100, ""),
    "YMaxP": (20, ""), "YMaxE": (2, "%"), "AMaxP": (20, ""), "AMaxE": (2, "%"),
    "MaxRPtol": (100, ""), "W1": (1, ""), "W2": (1, ""), "W3": (1, ""),
    "CPASS": (0, ""), "DCenab": (0, ""),
}
_DISPLAY = {
    "DataF": (60, "Hz"), "Zero_Tol": (1e-19, ""), "Vbase": (230, "kV"),
    "MVAbase": (100, "MVA"), "picomp": (0, ""),
}
_NATIVE_OUTPUT = """PSCAD LINE CONSTANTS PROGRAM OUTPUT FILE (*.out)
 PHASE DOMAIN DATA @ 50.000 Hz:
 SERIES IMPEDANCE MATRIX (Z) [ohms/m]:
 0.119897949E-03,0.521306976E-04 0.169176640E-06,-.278941410E-05
 0.169176640E-06,-.278941410E-05 0.119897949E-03,0.521306976E-04

 SHUNT ADMITTANCE MATRIX (Y) [mhos/m]:
 0.000000000E+00,0.166342742E-06 0.000000000E+00,0.000000000E+00
 0.000000000E+00,0.000000000E+00 0.000000000E+00,0.166342742E-06

 Minimum Time Delay for the Line [ms]: 0.688414378
 Recommended Time Step for the Line [ms]: 0.068841438
"""
_NATIVE_CONSTANTS = """Fre-Phase 2 0 1 1 /
Fitting parameters for the char. admittance:
N.o. conductors:
2
Residues and poles:
1
-1
0
1
0
0.1
0
1
-1
0
0.1
0
1
0
0.02
0
0
0.02
Fitting parameters for the propagation function:
N.o. delay groups:
1
Time delays:
0.000688414378001545
Poles:
1
-2
0
Residues:
1
0
0.1
0
0.1
0
1
0
"""
_NATIVE_LOG = """Fitting Characteristic Admittance Yc:
 Maximum Fitting Error Requested: 2.0000 %
 Maximum Number of Poles: 20
 Yc: Maximum Number
 Fitting Error of Poles
 -------------- --------
 1.4721 % 1
 Fitting Propagation Function H:
 Maximum Fitting Error Requested: 2.0000 %
 Maximum Number of Poles (per delay group): 20
 Attempt # 1 Target error: 12.5000 %
 Hmode: Delay Maximum Number Time
 Group # Fitting Error of Poles Delay
 ------- ------------- -------- -----
 1 5.23834 % 1 0.692477 ms
 Hphase: Maximum Maximum Maximum
 Fitting Error RMS Error Residue/Pole Ratio
 -------------- ---------- ------------------
 5.2383 % 2.8188 % 0.75
 Attempt # 2 Target error: 1.5625 %
 Hmode: Delay Maximum Number Time
 Group # Fitting Error of Poles Delay
 ------- ------------- -------- -----
 1 0.23690 % 1 0.688414 ms
 Hphase: Maximum Maximum Maximum
 Fitting Error RMS Error Residue/Pole Ratio
 -------------- ---------- ------------------
 0.2369 % 0.0929 % 0.49
 Line Constants Ending!
 Tline Ending....
0
"""


def _module():
    return importlib.import_module("pscad_mcp.hvdc.builders.mmc.cable_constants")


def _component(parent, definition, parameters):
    component = ET.SubElement(parent, "User", {"defn": f"master:{definition}"})
    values = ET.SubElement(component, "paramlist")
    for name, (value, unit) in parameters.items():
        ET.SubElement(values, "param", {
            "name": name, "value": f"{value} [{unit}]" if unit else str(value),
        })
    return component


@pytest.fixture
def cable_sources(tmp_path):
    master = ET.Element("project", {"name": "master", "version": "4.6.2"})
    definitions = ET.SubElement(master, "definitions")
    for name, parameters in {
        "Cable_Coax": _GEOMETRY, "Line_Ground": _GROUND,
        "Line_FrePhase_Options": _OPTIONS, "Line_Out_Disp": _DISPLAY,
    }.items():
        definition = ET.SubElement(definitions, "Definition", {"name": name})
        form = ET.SubElement(definition, "form")
        for parameter, (value, unit) in parameters.items():
            field = ET.SubElement(form, "parameter", {
                "name": parameter, "type": "Real", "unit": unit,
            })
            ET.SubElement(field, "value").text = str(value)
    master_path = tmp_path / "master.pslx"
    ET.ElementTree(master).write(master_path, encoding="utf-8")

    project = ET.Element("project", {"name": "Example", "version": "4.6.2"})
    definitions = ET.SubElement(project, "definitions")
    main = ET.SubElement(ET.SubElement(definitions, "Definition", {"name": "Main"}), "schematic")
    wire = ET.SubElement(main, "Wire", {"classid": "Cable", "defn": "Example:Cable2"})
    wrapper = ET.SubElement(ET.SubElement(wire, "User"), "paramlist")
    for name, value in {
        "Name": "Cable2", "Length": "100 [km]", "Freq": "0 [Hz]",
        "Dim": "2", "Mode": "0", "CoupleEnab": "0",
    }.items():
        ET.SubElement(wrapper, "param", {"name": name, "value": value})
    definition = ET.SubElement(definitions, "Definition", {"name": "Cable2", "classid": "RowDefn"})
    parameters = ET.SubElement(definition, "paramlist")
    ET.SubElement(parameters, "param", {"name": "type", "value": "Cable"})
    schematic = ET.SubElement(definition, "schematic")
    _component(schematic, "Cable_Coax", _GEOMETRY)
    _component(schematic, "Cable_Coax", {**_GEOMETRY, "CABNUM": (2, ""), "X": (0.4, "m")})
    _component(schematic, "Line_Ground", _GROUND)
    _component(schematic, "Line_FrePhase_Options", _OPTIONS)
    project_path = tmp_path / "source.pscx"
    ET.ElementTree(project).write(project_path, encoding="utf-8")
    return project_path, master_path


def test_extracts_source_geometry_and_physical_core_dc_resistance(cable_sources):
    project, master = cable_sources
    model = _module().extract_cable_configuration(project, master_path=master)

    assert model.name == "Cable2"
    assert model.length_km == 100.0
    assert model.steady_state_frequency_hz == 0.0
    assert model.conductors == 2
    assert [cable.number for cable in model.cables] == [1, 2]
    assert model.cables[1].parameters["X"] == 0.4
    assert model.cables[0].core_dc_resistance_ohm_per_km == pytest.approx(
        2.82e-8 * 1000.0 / (math.pi * 0.0104**2)
    )
    with pytest.raises(TypeError):
        model.cables[0].parameters["R2"] = 0.02
    assert len(model.project_sha256) == len(model.master_sha256) == 64


def test_renders_native_cable_format_and_explicit_calculation_frequency(cable_sources):
    project, master = cable_sources
    model = _module().extract_cable_configuration(project, master_path=master)
    text = _module().render_cable_cli(model, length_km=300.0, reference_frequency_hz=50.0)

    assert "Cable Summary:" in text
    assert "Cable Length = 300" in text
    assert "Steady State Frequency = 0" in text
    assert text.count("Coax Cable:") == 2
    assert "Conductor Resistivity = 2.82e-08" in text
    assert "Frequency for Calculation = 50" in text
    assert "Maximum Fitting Error (%) for Surge Admittance = 2" in text
    assert "Line Constants Tower" not in text


@pytest.mark.parametrize(
    "name, value, message",
    [("LL", "5", "unsupported"), ("RorT", "1", "unsupported"),
     ("R2", "0 [m]", "radius"), ("Y", "1 [km]", "unit")],
)
def test_rejects_unverified_geometry_or_units(cable_sources, name, value, message):
    project, master = cable_sources
    document = ET.parse(project)
    document.find(f".//User[@defn='master:Cable_Coax']/paramlist/param[@name='{name}']").set("value", value)
    document.write(project, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        _module().extract_cable_configuration(project, master_path=master)


def test_rejects_additional_native_model_data(cable_sources):
    project, master = cable_sources
    document = ET.parse(project)
    schematic = document.find("./definitions/Definition[@name='Cable2']/schematic")
    ET.SubElement(schematic, "User", {"defn": "master:Line_ManualYZ"})
    document.write(project, encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        _module().extract_cable_configuration(project, master_path=master)


def test_parses_native_phase_matrices_without_conflating_ac_and_dc_resistance():
    phase = _module().parse_cable_phase_output(_NATIVE_OUTPUT, conductors=2, reference_frequency_hz=50.0)
    assert phase.impedance_ohm_per_m[0][0] == complex(0.119897949e-3, 0.521306976e-4)
    assert phase.impedance_ohm_per_m[0][1].imag < 0
    assert phase.minimum_delay_s == pytest.approx(0.688414378e-3)
    values = phase.to_dict()
    assert values["resistance_ohm_per_km"][0][0] == pytest.approx(0.119897949)
    assert values["inductance_h_per_km"][0][0] == pytest.approx(0.521306976e-4 * 1000 / (2 * math.pi * 50))
    assert values["capacitance_f_per_km"][0][0] == pytest.approx(0.166342742e-6 * 1000 / (2 * math.pi * 50))
    json.dumps(values, allow_nan=False)


@pytest.mark.parametrize("output", [
    _NATIVE_OUTPUT.replace("50.000", "60.000"),
    _NATIVE_OUTPUT.replace("0.119897949E-03,0.521306976E-04", "", 1),
    _NATIVE_OUTPUT.replace("0.119897949E-03", "1e999", 1),
])
def test_rejects_wrong_frequency_ragged_or_nonfinite_native_output(output):
    with pytest.raises(ValueError):
        _module().parse_cable_phase_output(output, conductors=2, reference_frequency_hz=50.0)


def _fake_native_run(command, *, cwd, stdout, constants=_NATIVE_CONSTANTS, log=_NATIVE_LOG, **kwargs):
    stem = Path(command[1]).stem
    assert Path(command[1]).suffix == ".cli"
    (Path(cwd) / f"{stem}.clo").write_text(constants, encoding="ascii")
    (Path(cwd) / f"{stem}.out").write_text(_NATIVE_OUTPUT, encoding="ascii")
    stdout.write(log)
    return SimpleNamespace(returncode=0)


def test_generation_records_fresh_native_artifacts_and_source_hashes(cable_sources, tmp_path, monkeypatch):
    module = _module()
    project, master = cable_sources
    executable = tmp_path / "tline.exe"
    executable.write_bytes(b"test executable")
    monkeypatch.setattr(module.subprocess, "run", _fake_native_run)
    before = project.read_bytes(), master.read_bytes()
    artifacts = module.generate_public_cable_constants(
        project, tmp_path / "evidence", master_path=master, executable=executable,
        lengths_km=(100.0, 300.0), reference_frequency_hz=50.0,
    )

    assert [artifact.length_km for artifact in artifacts] == [100.0, 300.0]
    assert artifacts[1].loop_dc_resistance_ohm == pytest.approx(3 * artifacts[0].loop_dc_resistance_ohm)
    for artifact in artifacts:
        assert artifact.constants_path.endswith(".clo")
        report = json.loads(Path(artifact.evidence_path).read_text(encoding="utf-8"))
        assert report["status"] == "PASS"
        assert report["source_hashes_before"] == report["source_hashes_after"]
        assert artifact.input_sha256 and artifact.constants_sha256 and artifact.output_sha256
        assert report["coefficient_structure"]["admittance_pole_counts"] == [1, 1]
        assert report["coefficient_structure"]["propagation_pole_counts"] == [1]
        assert report["fit_record"]["propagation_rms_error_percent"] == 0.0929
        assert report["fit_record"]["max_residue_pole_ratio"] == 0.49
    assert before == (project.read_bytes(), master.read_bytes())
    with pytest.raises(FileExistsError):
        module.generate_public_cable_constants(
            project, tmp_path / "evidence", master_path=master, executable=executable,
            lengths_km=(100.0,), reference_frequency_hz=50.0,
        )


@pytest.mark.parametrize("failure", ["fit", "source", "missing_source"])
def test_generation_preserves_failed_attempt_evidence(cable_sources, tmp_path, monkeypatch, failure):
    module = _module()
    project, master = cable_sources
    executable = tmp_path / "tline.exe"
    executable.write_bytes(b"test executable")

    def run(command, *, cwd, stdout, **kwargs):
        result = _fake_native_run(command, cwd=cwd, stdout=stdout, **kwargs)
        if failure == "source":
            project.write_bytes(project.read_bytes() + b"\n")
        elif failure == "missing_source":
            project.unlink()
        else:
            stdout.write("Hphase:\n 2.5 % 0.1 % 0.5\n")
        return result

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="fit|source"):
        module.generate_public_cable_constants(
            project, tmp_path / "evidence", master_path=master, executable=executable,
            lengths_km=(100.0,), reference_frequency_hz=50.0,
        )
    reports = list((tmp_path / "evidence").rglob("evidence.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["status"] == "FAIL"


@pytest.mark.parametrize("constants", [
    "Fre-Phase 2 0 1 1 /\n",
    _NATIVE_CONSTANTS.rsplit("0\n", 1)[0],
    _NATIVE_CONSTANTS + "0\n",
    _NATIVE_CONSTANTS.replace("N.o. conductors:\n2", "N.o. conductors:\n3"),
    _NATIVE_CONSTANTS.replace("Poles:\n1", "Poles:\n2"),
    _NATIVE_CONSTANTS.replace("Residues and poles:\n1", "Residues and poles:\n999"),
    _NATIVE_CONSTANTS.replace("0.02", "1e999", 1),
    _NATIVE_CONSTANTS.replace("0.02", "nan", 1),
    _NATIVE_CONSTANTS.replace("0.000688414378001545", "-0.000688414378001545"),
], ids=["header-only", "truncated", "trailing", "dimension", "pole-count", "excess-poles", "nonfinite", "nan", "negative-delay"])
def test_generation_rejects_incomplete_or_invalid_coefficient_bodies(cable_sources, tmp_path, monkeypatch, constants):
    module = _module()
    project, master = cable_sources
    executable = tmp_path / "tline.exe"
    executable.write_bytes(b"test executable")
    monkeypatch.setattr(module.subprocess, "run", partial(_fake_native_run, constants=constants))

    with pytest.raises(RuntimeError, match="coefficient|constants"):
        module.generate_public_cable_constants(
            project, tmp_path / "evidence", master_path=master, executable=executable,
            lengths_km=(100.0,), reference_frequency_hz=50.0,
        )
    report = json.loads(next((tmp_path / "evidence").rglob("evidence.json")).read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["source_hashes_before"] == report["source_hashes_after"]
    assert any(name.endswith(".clo") for name in report["produced_files"])


@pytest.mark.parametrize("log", [
    _NATIVE_LOG.replace("0.0929 % 0.49", "0.0929 % 101"),
    _NATIVE_LOG.replace("0.0929 % 0.49", "1e999 % 0.49"),
    _NATIVE_LOG.replace("0.0929 % 0.49", "0.0929 % 1e999"),
    _NATIVE_LOG.replace("0.0929 % 0.49", "NaN % 0.49"),
    _NATIVE_LOG.replace("0.0929 % 0.49", "0.0929 % NaN"),
    _NATIVE_LOG.replace("Line Constants Ending!", "Hphase:\nLine Constants Ending!"),
    _NATIVE_LOG.replace("Line Constants Ending!", "Attempt # 3 Target error: 1.0000 %\nLine Constants Ending!"),
    _NATIVE_LOG.replace("Line Constants Ending!", ""),
    _NATIVE_LOG.replace("Tline Ending....", ""),
    _NATIVE_LOG.replace("1 5.23834 % 1", "1 NaN % 1"),
    _NATIVE_LOG + "unexpected trailing data\n",
], ids=["residue-limit", "infinite-rms", "infinite-ratio", "nan-rms", "nan-ratio", "unfinished-hphase", "unfinished-attempt", "missing-line-end", "missing-tool-end", "nonfinite-mode", "trailing-data"])
def test_generation_rejects_incomplete_or_invalid_final_fit_records(cable_sources, tmp_path, monkeypatch, log):
    module = _module()
    project, master = cable_sources
    executable = tmp_path / "tline.exe"
    executable.write_bytes(b"test executable")
    monkeypatch.setattr(module.subprocess, "run", partial(_fake_native_run, log=log))

    with pytest.raises(RuntimeError, match="fit"):
        module.generate_public_cable_constants(
            project, tmp_path / "evidence", master_path=master, executable=executable,
            lengths_km=(100.0,), reference_frequency_hz=50.0,
        )
    report = json.loads(next((tmp_path / "evidence").rglob("evidence.json")).read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["source_hashes_before"] == report["source_hashes_after"]
    assert any(name.endswith(".log") for name in report["produced_files"])
