"""Native four-terminal cable assembly from immutable, verified coax inputs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from importlib import resources
from itertools import pairwise
from pathlib import Path
from statistics import fmean
from xml.etree import ElementTree as ET

from ....core.definition_metadata import read_definition_metadata_document
from .avm_companion import _paramlist, _project, _write_new, _Writer
from .cable_constants import (
    _coefficient_structure,
    _fit_errors,
    extract_cable_configuration,
    parse_cable_phase_output,
    render_cable_cli,
)

DEFAULT_DONOR = Path(r"C:\Users\Public\Documents\PSCAD\4.6\Examples\hvdc_vsc\VSCTrans.pscx")
DEFAULT_MASTER = Path(r"C:\Program Files (x86)\PSCAD46\master.pslx")
CHANNEL_UNITS = {"I_SEND": "kA", "I_RETURN": "kA", "V_SEND": "kV", "V_RECV": "kV"}
PORT_OFFSETS = {"SEND_POS": (-72, -36), "SEND_NEG": (-72, 36), "RECV_POS": (72, -36), "RECV_NEG": (72, 36)}
PORT_BINDINGS = {
    "SEND_POS": {"end": "sending", "native_port": "C1"},
    "SEND_NEG": {"end": "sending", "native_port": "C2"},
    "RECV_POS": {"end": "receiving", "native_port": "C1"},
    "RECV_NEG": {"end": "receiving", "native_port": "C2"},
}
TOLERANCES = {"dc_current": 0.01, "source_voltage": 0.001, "kcl": 0.001,
              "load_ohm": 0.001, "dc_loss": 0.01, "steady_ripple": 0.001}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _xml_sha(element: ET.Element) -> str:
    return hashlib.sha256(ET.tostring(element)).hexdigest()


def _geometry_sha(element: ET.Element) -> str:
    value = copy.deepcopy(element)
    for key in ("date", "crc"):
        value.attrib.pop(key, None)
    canonical = ET.canonicalize(ET.tostring(value, encoding="unicode"), strip_text=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _parameters(element):
    values = {}
    for parameter in element.findall("./paramlist/param"):
        name = parameter.get("name")
        if name in values:
            raise ValueError(f"Duplicate native parameter: {name}")
        values[name] = parameter.get("value", "")
    return values


def _set_parameter(element, name, value):
    matches = element.findall(f"./paramlist/param[@name='{name}']")
    if len(matches) != 1:
        raise ValueError(f"Expected one native parameter {name}")
    matches[0].set("value", str(value))


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return float(value)


def _verified_constants(evidence: Path, source: Path, master: Path):
    for path in (evidence, source, master):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"An immutable regular source is required: {path}")
    report_bytes = evidence.read_bytes()
    report = json.loads(report_bytes)
    if report.get("status") != "PASS" or report.get("returncode") != 0 or report.get("scope") != "native_cable_line_constants_only":
        raise ValueError("A passing native cable-constants receipt is required")
    model = extract_cable_configuration(source, master_path=master)
    if _canonical(report.get("configuration")) != _canonical(model.to_dict()):
        raise ValueError("Cable receipt does not describe the supplied immutable source geometry")
    source_hashes = report.get("source_hashes_before", {})
    if (not source_hashes or source_hashes != report.get("source_hashes_after")
            or source_hashes.get(str(source)) != model.project_sha256
            or source_hashes.get(str(master)) != model.master_sha256):
        raise ValueError("Cable receipt lacks immutable source hashes")
    for path, expected in source_hashes.items():
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file() or _sha(candidate) != expected:
            raise ValueError(f"Cable receipt source changed: {candidate}")
    files = {}
    for key, suffix in (("input", ".cli"), ("constants", ".clo"), ("log", ".log"), ("output", ".out")):
        path = Path(report.get(key + "_path", "")).resolve()
        if path.parent != evidence.parent or path.suffix != suffix or path.is_symlink() or not path.is_file():
            raise ValueError(f"Cable receipt has an invalid {key} artifact path")
        if _sha(path) != report.get(key + "_sha256"):
            raise ValueError(f"Cable {key} artifact differs from its receipt")
        files[key] = path
    produced = report.get("produced_files", {})
    if not produced or not {path.name for path in files.values()} <= set(produced):
        raise ValueError("Cable receipt has incomplete produced-file hashes")
    for filename, expected in produced.items():
        path = evidence.parent / filename
        if Path(filename).name != filename or path.is_symlink() or not path.is_file() or _sha(path) != expected:
            raise ValueError(f"Cable produced artifact changed: {filename}")
    length = _positive(report.get("length_km"), "length_km")
    frequency = _positive(report.get("reference_frequency_hz"), "reference_frequency_hz")
    name = report.get("segment", "")
    expected_input = render_cable_cli(model, length_km=length, reference_frequency_hz=frequency, name=name).encode("ascii")
    if files["input"].read_bytes() != expected_input:
        raise ValueError("Native cable input does not match the source geometry, length, or frequency")
    coefficients = _coefficient_structure(files["constants"].read_text(encoding="ascii"), conductors=2, options=model.options)
    fit = _fit_errors(files["log"].read_text(encoding="utf-8"))
    phase = parse_cable_phase_output(files["output"].read_text(encoding="ascii"), conductors=2, reference_frequency_hz=frequency)
    for key, observed in (("coefficient_structure", coefficients), ("fit_record", fit), ("phase_data", phase.to_dict())):
        if _canonical(report.get(key)) != _canonical(observed):
            raise ValueError(f"Native cable receipt has changed or incomplete {key}")
    if (fit["admittance_max_error_percent"] > model.options["YMaxE"]
            or fit["propagation_max_error_percent"] > model.options["AMaxE"]
            or fit["max_residue_pole_ratio"] > model.options["MaxRPtol"]):
        raise ValueError("Native cable fit exceeds immutable source tolerances")
    for key, source_key in (("admittance_requested_error_percent", "YMaxE"), ("propagation_requested_error_percent", "AMaxE"),
                            ("admittance_pole_limit", "YMaxP"), ("propagation_pole_limit", "AMaxP")):
        if fit[key] != model.options[source_key]:
            raise ValueError("Cable fit limits differ from source data")
    if (fit["admittance_poles"] != max(coefficients["admittance_pole_counts"])
            or tuple(group["poles"] for group in fit["delay_groups"]) != coefficients["propagation_pole_counts"]):
        raise ValueError("Cable coefficient and fit dimensions differ")
    resistance = sum(cable.core_dc_resistance_ohm_per_km for cable in model.cables) * length
    if not math.isclose(resistance, report.get("loop_dc_resistance_ohm", math.nan), rel_tol=1e-12):
        raise ValueError("Cable receipt DC resistance is inconsistent with conductor geometry")
    hashes = {**source_hashes, str(evidence): hashlib.sha256(report_bytes).hexdigest(),
              **{str(evidence.parent / filename): digest for filename, digest in produced.items()}}
    return model, report, files, hashes


def _native_metadata(master: Path):
    payload = master.read_bytes()
    metadata = read_definition_metadata_document(payload)
    root = ET.fromstring(payload)
    required = {
        "cable_interface": {"C1": (-18, 0, 1, "Natural", "true"), "C2": (-18, 54, 1, "Natural", "NCAB>=2")},
        "xnode": {"N": (0, 0, 0, "Natural", "true")},
        "nodelabel": {"A": (0, 0, 0, "Natural", "true")},
    }
    for name, ports in required.items():
        definitions = metadata.get(name, ())
        if len(definitions) != 1:
            raise ValueError(f"Native Master definition is missing or ambiguous: {name}")
        for key, expected in ports.items():
            found = [port for port in definitions[0].ports if port.name == key and port.occurrence == 0]
            if (len(found) != 1 or (found[0].x, found[0].y, found[0].dim, found[0].model,
                                   re.sub(r"\s+", "", found[0].condition or "")) != expected):
                raise ValueError(f"Native cable terminal contract changed: {name}:{key}")
    defaults = {
        name: {parameter.get("name"): (parameter.findtext("value") or "").strip()
               for parameter in root.findall(f"./definitions/Definition[@name='{name}']/form//parameter")}
        for name in (*required, "source_1", "ammeter", "resistor", "voltmeter", "ground", "pgb", "datalabel")
    }
    return metadata, defaults


def _module_definition(root, source_root, cable_name):
    definitions = root.find("definitions")
    module = ET.SubElement(definitions, "Definition", {
        "classid": "UserCmpDefn", "name": "MMCCableLink", "id": "1750000000",
        "crc": "0", "view": "false", "date": "0", "group": "HVDC FACTS PE",
    })
    _paramlist(module, {"Description": "Native coupled two-conductor cable"})
    ET.SubElement(module, "form", {"name": "Native coupled cable", "w": "320", "h": "240", "splitter": "60"})
    svg = ET.SubElement(module, "svg", {"viewBox": "-108 -72 108 72"})
    ET.SubElement(svg, "rect", {"x": "-54", "y": "-54", "width": "108", "height": "108",
                              "stroke": "Black", "stroke-width": "0.2", "fill-style": "Hollow"})
    ET.SubElement(svg, "text", {"x": "0", "y": "0", "font-size": "Small", "fill": "Black"}).text = "Cable"
    for name, point in PORT_OFFSETS.items():
        ET.SubElement(svg, "port", {"model": "Natural", "name": name, "x": str(point[0]), "y": str(point[1]),
                                    "dim": "1", "mode": "Electrical", "type": "NonRemovable"}).text = "true"
    canvas = ET.SubElement(module, "schematic", {"classid": "UserCanvas"})
    _paramlist(canvas, {"show_grid": "0", "size": "0", "orient": "1", "show_border": "0",
                       "monitor_bus_voltage": "0", "show_signal": "0", "show_virtual": "0",
                       "show_sequence": "0", "auto_sequence": "1"})
    prototypes = [item for item in source_root.findall(".//User[@defn='master:cable_interface']")
                  if _parameters(item).get("Name") == "Cable2"]
    if len(prototypes) != 2:
        raise ValueError("The donor requires exactly two cable interfaces")
    source_receipts = {}
    expected_wires = []
    for end_index, (end, x) in enumerate((("sending", 216), ("receiving", 576))):
        prototype = prototypes[end_index]
        parameters = _parameters(prototype)
        if any(parameters.get(key) != value for key, value in {"NCAB": "2", "C1T": "1", "C2T": "1", "dim_s": "0", "dim_r": "0", "pipe": "0"}.items()):
            raise ValueError("Donor cable interface conductor ordering is unsupported")
        source_receipts[end] = {"component_id": prototype.get("id"), "sha256": _xml_sha(prototype)}
        interface = copy.deepcopy(prototype)
        interface.attrib.update(id=str(1750000010 + end_index), name=end, x=str(x), y="216", orient="0", z="0")
        _set_parameter(interface, "Name", cable_name)
        _set_parameter(interface, "send_recv", end_index + 1)
        canvas.append(interface)
        for pole_index, pole in enumerate(("POS", "NEG")):
            port_name = ("SEND" if end_index == 0 else "RECV") + "_" + pole
            y = 216 + 54 * pole_index
            node = ET.SubElement(canvas, "User", {
                "classid": "UserCmp", "name": port_name, "defn": "master:xnode", "id": str(1750000020 + end_index * 2 + pole_index),
                "x": str(x - 72), "y": str(y), "w": "18", "h": "31", "z": "0", "orient": "0", "link": "-1", "q": "4",
            })
            _paramlist(node, {"Name": port_name}, name="", link="-1")
            wire = ET.SubElement(canvas, "Wire", {
                "classid": "WireOrthogonal", "id": str(1750000030 + end_index * 2 + pole_index),
                "name": "", "x": str(x - 72), "y": str(y), "w": "54", "h": "0", "orient": "0",
            })
            ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
            ET.SubElement(wire, "vertex", {"x": "54", "y": "0"})
            expected_wires.append({"port": port_name, "wire_id": wire.get("id"), "vertices": [[x - 72, y], [x - 18, y]],
                                   "node_id": node.get("id"), "interface_id": interface.get("id"), "native_port": "C" + str(pole_index + 1)})
    return module, source_receipts, expected_wires


def _materialize(destination, *, constants_evidence, source_project, master_path, project_name, fixture):
    folder, evidence = Path(destination).resolve(), Path(constants_evidence).resolve()
    source, master = Path(source_project).resolve(), Path(master_path).resolve()
    if folder.exists() or folder.is_symlink():
        raise FileExistsError("Cable assembly output directory must be new")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", project_name) is None:
        raise ValueError("Cable project name must be a portable PSCAD identifier")
    model, constants, files, input_hashes = _verified_constants(evidence, source, master)
    if any(Path(path).is_relative_to(folder) or folder.is_relative_to(Path(path).parent) for path in input_hashes):
        raise ValueError("Cable assembly workspace must be disjoint from immutable input directories")
    metadata, defaults = _native_metadata(master)
    source_root = ET.parse(source).getroot()
    row = source_root.find("./definitions/Definition[@name='Cable2']")
    configuration = source_root.find(f".//Wire[@classid='Cable'][@defn='{source_root.get('name')}:Cable2']")
    if row is None or configuration is None or row.findall(".//script"):
        raise ValueError("The donor lacks the supported native cable geometry/configuration")
    root = _project(project_name, library=False)
    root.find("definitions").append(copy.deepcopy(row))
    module, interface_receipts, module_wires = _module_definition(root, source_root, constants["segment"])
    writer = _Writer(root, metadata, defaults)
    main = root.find("./definitions/Definition[@name='Main']")
    local_constants = folder / "constants" / files["constants"].name
    line = copy.deepcopy(configuration)
    line.attrib.update(name=project_name + ":Cable2", defn=project_name + ":Cable2", x="342", y="108")
    wrapper = line.find("User")
    wrapper.attrib.update(name=project_name + ":Cable2", defn=project_name + ":Cable2")
    for name, value in {"Name": constants["segment"], "Length": f"{constants['length_km']:.15g} [km]", "const_path": str(local_constants)}.items():
        _set_parameter(wrapper, name, value)
    if _parameters(wrapper).get("gen_cnst") != "1":
        raise ValueError("Donor cable must use its external constants-file selection")
    main.find("schematic").append(line)
    sending_negative = "GND" if fixture else "SEND_NEG"
    writer.add(main, "cable_link", project_name + ":MMCCableLink", {}, {
        name: sending_negative if name == "SEND_NEG" else name for name in PORT_OFFSETS
    })
    link = main.find(f"./schematic/User[@defn='{project_name}:MMCCableLink']")
    terminals = {name: {"component_id": link.get("id"), "port": name,
                        "x": int(link.get("x")) + offset[0], "y": int(link.get("y")) + offset[1]}
                 for name, offset in PORT_OFFSETS.items()}
    reference = None
    if fixture:
        if constants["phase_data"]["recommended_step_s"] < 20e-6:
            raise ValueError("The fixture time step exceeds the native cable recommendation")
        source_values = {"Name": "CABLE_DC_SOURCE", "Type": "6", "Grnd": "0", "Spec": "0", "Cntrl": "0",
                         "AC": "0", "Vm": "10.0 [kV]", "Tc": "0.005 [s]", "CUR": ""}
        writer.add(main, "dc_source", "master:source_1", source_values, {"NA": "SOURCE_POS", "NB": sending_negative})
        writer.add(main, "sending_current", "master:ammeter", {"Name": "I_SEND"}, {"N1": "SOURCE_POS", "N2": "SEND_POS"})
        writer.add(main, "load", "master:resistor", {"R": "100.0 [ohm]"}, {"A": "RECV_POS", "B": "LOAD_RETURN"})
        writer.add(main, "receiving_current", "master:ammeter", {"Name": "I_RETURN"}, {"N1": "LOAD_RETURN", "N2": "RECV_NEG"})
        writer.add(main, "sending_voltage", "master:voltmeter", {"Name": "V_SEND"}, {"N1": "SEND_POS", "N2": sending_negative})
        writer.add(main, "receiving_voltage", "master:voltmeter", {"Name": "V_RECV"}, {"N1": "RECV_POS", "N2": "RECV_NEG"})
        writer.add(main, "test_ground", "master:ground", {}, {"A": sending_negative})
        for name, unit in CHANNEL_UNITS.items():
            writer.add(main, "probe_" + name, "master:pgb", {
                "Name": name, "Units": unit, "Group": "CABLE", "UseSignalName": "0", "enab": "1",
                "Display": "1", "Scale": "1.0", "mrun": "0", "Pol": "0", "Max": "20.0", "Min": "-20.0",
            }, {"Signl": name})
        settings = root.find("./paramlist[@name='Settings']")
        for name, value in {"time_duration": "5", "time_step": "20", "sample_step": "100",
                            "PlotType": "1", "StartType": "0", "output_filename": project_name + ".out"}.items():
            settings.find(f"param[@name='{name}']").set("value", value)
        reference = {"source_voltage_kv": 10.0, "load_resistance_ohm": 100.0,
                     "loop_dc_resistance_ohm": constants["loop_dc_resistance_ohm"],
                     "dc_current_ka": 10.0 / (100.0 + constants["loop_dc_resistance_ohm"]),
                     "duration_s": 5.0, "output_step_s": 100e-6, "time_step_s": 20e-6,
                     "steady_window_s": [4.0, 5.0], "tolerances": TOLERANCES}
    writer.verify()
    hierarchy = root.find("./hierarchy/call/call")
    for component, definition in ((line, "Cable2"), (link, "MMCCableLink")):
        ET.SubElement(hierarchy, "call", {"link": component.get("id"), "name": project_name + ":" + definition,
                                          "z": "10" if fixture and definition == "MMCCableLink" else "-1", "view": "false", "instance": "0"})
    receipt = {
        "schema_version": 1, "scope": "native_two_conductor_cable_assembly", "project_name": project_name,
        "project_path": str(folder / (project_name + ".pscx")), "cable_name": constants["segment"],
        "length_km": constants["length_km"], "constants_path": str(local_constants),
        "constants_sha256": constants["constants_sha256"], "constants_receipt_path": str(evidence),
        "constants_receipt_sha256": _sha(evidence), "loop_dc_resistance_ohm": constants["loop_dc_resistance_ohm"],
        "source_hashes_before": input_hashes, "terminals": terminals, "module_wires": module_wires,
        "source_definition_receipts": {"Cable2": _xml_sha(row), "configuration": _xml_sha(configuration), "interfaces": interface_receipts},
        "geometry_semantics_sha256": _geometry_sha(row),
        "shell_sha256": hashlib.sha256(resources.files("pscad_mcp").joinpath("assets/templates/empty_case.pscx").read_bytes()).hexdigest(),
        "electrical_nets": {name: dict(nets) for name, nets in writer.nets.items()}, "routes": writer.routes,
        "channels": dict(CHANNEL_UNITS) if fixture else {}, "physical_reference": reference,
        "fixture": fixture, "licensed_acceptance": "NOT_RUN", "topology": {},
    }
    folder.mkdir(parents=True)
    constants_dir = folder / "constants"
    constants_dir.mkdir()
    for filename in constants["produced_files"]:
        source_file = evidence.parent / filename
        (constants_dir / filename).write_bytes(source_file.read_bytes())
    (constants_dir / "evidence.json").write_bytes(evidence.read_bytes())
    receipt["project_sha256"] = _write_new(Path(receipt["project_path"]), root)
    receipt["topology"] = audit_cable_assembly(receipt["project_path"], receipt)
    receipt["source_hashes_after"] = {path: _sha(Path(path)) for path in input_hashes}
    if receipt["source_hashes_after"] != input_hashes:
        raise ValueError("Cable source inputs changed during materialization")
    receipt["delivered_hashes"] = {str(path): _sha(path) for path in sorted(folder.rglob("*")) if path.is_file()}
    (folder / "assembly-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def materialize_cable_assembly(destination, *, constants_evidence, source_project=DEFAULT_DONOR,
                               master_path=DEFAULT_MASTER, project_name="mmc_cable_link"):
    """Create one native coupled link with four connectable Main-canvas terminals."""
    return _materialize(destination, constants_evidence=constants_evidence, source_project=source_project,
                        master_path=master_path, project_name=project_name, fixture=False)


def materialize_cable_loop_fixture(destination, *, constants_evidence, source_project=DEFAULT_DONOR,
                                  master_path=DEFAULT_MASTER, project_name="mmc_cable_loop"):
    """Create the same link in a measured, source-driven DC load loop."""
    return _materialize(destination, constants_evidence=constants_evidence, source_project=source_project,
                        master_path=master_path, project_name=project_name, fixture=True)


def audit_cable_assembly(project_path, receipt: Mapping) -> dict:
    """Reject extra active definitions, endpoint changes, or electrical bypasses."""
    root = ET.parse(project_path).getroot()
    definitions = {item.get("name"): item for item in root.findall("./definitions/Definition")}
    if (len(root.findall("./definitions/Definition")) != 4 or set(definitions) != {"Station", "Main", "Cable2", "MMCCableLink"}
            or root.findall(".//script") or root.get("name") != receipt["project_name"]):
        raise ValueError("Cable assembly contains unexpected active definitions or scripts")
    if _geometry_sha(definitions["Cable2"]) != receipt["geometry_semantics_sha256"]:
        raise ValueError("Copied native cable geometry changed")
    module, main = definitions["MMCCableLink"], definitions["Main"]
    ports = module.findall("./svg/port")
    if len(ports) != 4 or {port.get("name") for port in ports} != set(PORT_OFFSETS):
        raise ValueError("Cable module must expose exactly four distinct terminals")
    for port in ports:
        if ((int(port.get("x")), int(port.get("y"))) != PORT_OFFSETS[port.get("name")]
                or any(port.get(key) != value for key, value in {"model": "Natural", "dim": "1", "mode": "Electrical", "type": "NonRemovable"}.items())):
            raise ValueError("Cable external terminal semantics changed")
    components = module.findall("./schematic/User")
    if Counter(item.get("defn") for item in components) != {"master:cable_interface": 2, "master:xnode": 4}:
        raise ValueError("Cable module contains unexpected native components")
    by_id = {item.get("id"): item for item in components}
    wires = module.findall("./schematic/Wire")
    if len(wires) != 4 or {item.get("id") for item in wires} != {item["wire_id"] for item in receipt["module_wires"]}:
        raise ValueError("Cable module has a missing wire or an electrical bypass")
    for expected in receipt["module_wires"]:
        wire = next(item for item in wires if item.get("id") == expected["wire_id"])
        vertices = [[int(wire.get("x")) + int(vertex.get("x")), int(wire.get("y")) + int(vertex.get("y"))] for vertex in wire.findall("vertex")]
        node, interface = by_id[expected["node_id"]], by_id[expected["interface_id"]]
        values = _parameters(interface)
        end = PORT_BINDINGS[expected["port"]]["end"]
        end_value = "1" if end == "sending" else "2"
        if (wire.get("classid") != "WireOrthogonal" or vertices != expected["vertices"]
                or _parameters(node).get("Name") != expected["port"] or node.get("orient") != "0"
                or [int(node.get("x")), int(node.get("y"))] != vertices[0]
                or interface.get("orient") != "0"
                or [int(interface.get("x")) - 18, int(interface.get("y")) + (54 if expected["native_port"] == "C2" else 0)] != vertices[1]
                or any(values.get(key) != value for key, value in {"Name": receipt["cable_name"], "NCAB": "2", "C1T": "1", "C2T": "1", "send_recv": end_value, "dim_s": "0", "dim_r": "0", "pipe": "0"}.items())):
            raise ValueError("Cable end, phase ordering, or endpoint connection changed")
    configurations = main.findall("./schematic/Wire[@classid='Cable']")
    if len(configurations) != 1 or configurations[0].get("defn") != receipt["project_name"] + ":Cable2":
        raise ValueError("Exactly one native cable configuration is required")
    values = _parameters(configurations[0].find("User"))
    if (any(values.get(key) != value for key, value in {"Name": receipt["cable_name"], "Dim": "2", "gen_cnst": "1", "const_path": receipt["constants_path"]}.items())
            or float(values["Length"].split()[0]) != receipt["length_km"] or _sha(Path(values["const_path"])) != receipt["constants_sha256"]):
        raise ValueError("Native cable configuration or constants binding changed")
    users = main.findall("./schematic/User")
    expected_counts = Counter({receipt["project_name"] + ":MMCCableLink": 1, "master:nodelabel": 4})
    if receipt["fixture"]:
        expected_counts.update({"master:source_1": 1, "master:ammeter": 2, "master:resistor": 1,
                                "master:voltmeter": 2, "master:ground": 1, "master:pgb": 4,
                                "master:nodelabel": 13, "master:datalabel": 4})
    if Counter(item.get("defn") for item in users) != expected_counts:
        raise ValueError("Main canvas contains unexpected active components")
    user_ids = {item.get("id"): item for item in users}
    routes = [route for route in receipt["routes"] if route["definition"] == "Main"]
    main_wires = main.findall("./schematic/Wire[@classid='WireOrthogonal']")
    if {wire.get("id") for wire in main_wires} != {route["wire_id"] for route in routes} or len(main_wires) != len(routes):
        raise ValueError("Main canvas has a missing route or electrical bypass")
    for route in routes:
        wire = next(item for item in main_wires if item.get("id") == route["wire_id"])
        vertices = [[int(wire.get("x")) + int(vertex.get("x")), int(wire.get("y")) + int(vertex.get("y"))] for vertex in wire.findall("vertex")]
        label = user_ids[route["endpoints"][1]["component_id"]]
        if vertices != route["vertices"] or _parameters(label).get("Name") != route["signal"]:
            raise ValueError("Main cable route or net label changed")
    return {"terminals_separate": True, "native_cable_count": 1, "native_interface_count": 2,
            "port_bindings": PORT_BINDINGS, "phase_order": ["positive", "negative"],
            "coupling": "one native two-conductor frequency-dependent phase model"}


def analyze_cable_loop(trace: Mapping, reference: Mapping) -> dict:
    """Apply fixed DC-loop tolerances to measured scalar electrical quantities."""
    result = {"status": "FAIL", "measurement_complete": False, "failed_checks": [], "checks": {}, "tolerances": TOLERANCES}
    try:
        if set(trace) != {"time", *CHANNEL_UNITS}:
            raise ValueError("The cable trace must contain exactly the four measured channels")
        times = trace["time"]
        if (len(times) < 10 or any(len(trace[key]) != len(times) for key in CHANNEL_UNITS)
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for values in trace.values() for value in values)
                or any(right <= left for left, right in pairwise(times))):
            raise ValueError("Cable samples must be complete, finite, and strictly increasing")
        step = _positive(reference["output_step_s"], "output_step_s")
        duration = _positive(reference["duration_s"], "duration_s")
        if times[0] > step * 1.1 or times[-1] < duration - step * 1.1 or any(right - left > step * 1.1 for left, right in pairwise(times)):
            raise ValueError("Cable trace does not cover the complete native run")
        start, end = reference["steady_window_s"]
        indexes = [index for index, time in enumerate(times) if start <= time <= end]
        if len(indexes) < 10 or times[indexes[0]] > start + step * 1.1 or times[indexes[-1]] < end - step * 1.1:
            raise ValueError("Cable steady-state window is incomplete")
        voltage = _positive(reference["source_voltage_kv"], "source_voltage_kv")
        load = _positive(reference["load_resistance_ohm"], "load_resistance_ohm")
        resistance = _positive(reference["loop_dc_resistance_ohm"], "loop_dc_resistance_ohm")
        expected_current = voltage / (load + resistance)
        samples = {name: [trace[name][index] for index in indexes] for name in CHANNEL_UNITS}
        means = {name: fmean(values) for name, values in samples.items()}
        relative = {
            "dc_current": max(abs(value - expected_current) for value in samples["I_SEND"]) / expected_current,
            "source_voltage": max(abs(value - voltage) for value in samples["V_SEND"]) / voltage,
            "kcl": max(abs(left - right) for left, right in zip(samples["I_SEND"], samples["I_RETURN"])) / expected_current,
            "load_ohm": max(abs(v - load * i) for v, i in zip(samples["V_RECV"], samples["I_RETURN"])) / voltage,
            "dc_loss": max(abs(vs * ins - vr * ir - ins**2 * resistance) for vs, ins, vr, ir in
                           zip(samples["V_SEND"], samples["I_SEND"], samples["V_RECV"], samples["I_RETURN"])) / (voltage * expected_current),
            "steady_ripple": (max(samples["I_SEND"]) - min(samples["I_SEND"])) / expected_current,
        }
        result["checks"] = {name: {"passed": value <= TOLERANCES[name], "observed_relative": value, "limit": TOLERANCES[name]} for name, value in relative.items()}
        result["failed_checks"] = [name for name, value in result["checks"].items() if not value["passed"]]
        result.update(measurement_complete=True, means=means, expected_dc_current_ka=expected_current,
                      observed_loop_resistance_ohm=(means["V_SEND"] - means["V_RECV"]) / means["I_SEND"] if means["I_SEND"] != 0 else None)
        result["status"] = "FAIL" if result["failed_checks"] else "PASS"
    except (KeyError, TypeError, ValueError) as error:
        result["failed_checks"] = ["measurement_contract"]
        result["error"] = str(error)
    return result


__all__ = ["CHANNEL_UNITS", "DEFAULT_DONOR", "DEFAULT_MASTER", "PORT_BINDINGS", "PORT_OFFSETS", "TOLERANCES",
           "analyze_cable_loop", "audit_cable_assembly", "materialize_cable_assembly", "materialize_cable_loop_fixture"]
