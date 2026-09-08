"""Audit finalized native MMC outputs without starting PSCAD or a compiler."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import subprocess
import sys
from itertools import pairwise
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parents[3]
OWNED = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from pscad_mcp.core.executor import robust_executor
from pscad_mcp.core.pscad_adapter import PscadAdapter

DEFAULT_RUN = Path("D:/PSCAD-Workspace/blank-mmc-native-acceptance-20260829")
DEFAULT_MASTER = Path("C:/Program Files (x86)/PSCAD46/master.pslx")
DEFAULT_OFFICIAL = Path("C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress")
STAGING = ".pscad-mcp/blank-mmc-builds/BLANK_MMC-1b75c2453b74.staging"
PREFIX = "BLANK_MMC_scenario_source"
JOURNAL = ".pscad-mcp/mmc-builds/b260eaf5c5004b5dab39c9368ed1023c/journal.json"
REQUIRED = (
    "fault_active", "v_inserted", "blocking_state", "i_dc_fault", "v_dc",
    "i_arm", "v_cap", "recovery_enable", "time",
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot(paths: list[Path]) -> dict[str, dict]:
    return {
        path.resolve().as_posix(): {"sha256": digest(path), "bytes": path.stat().st_size}
        for path in sorted(set(paths))
    }


def params(element: ET.Element) -> dict[str, str]:
    return {item.attrib["name"]: item.get("value", "") for item in element.findall("./paramlist/param")}


def component_record(element: ET.Element, parent: str, project: Path) -> dict:
    return {
        "owner_id": element.get("id"), "parent_definition": parent,
        "component_definition": element.get("defn") or element.get("name"),
        "x": int(element.get("x", "0")), "y": int(element.get("y", "0")),
        "orientation": int(element.get("orient", "0")),
        "compilation_order": element.get("z"), "parameters": params(element),
        "source_path": project.as_posix(),
        "xpath": f"./definitions/Definition[@name='{parent}']//User[@id='{element.get('id')}']",
    }


def components(root: ET.Element, project: Path) -> dict[str, dict]:
    result = {}
    for definition in root.findall("./definitions/Definition"):
        for element in definition.findall(".//User"):
            if element.get("id"):
                record = component_record(element, definition.attrib["name"], project)
                if record["owner_id"] in result:
                    raise ValueError(f"Duplicate source component owner: {record['owner_id']}")
                result[record["owner_id"]] = record
    return result


def segment_reference(root: ET.Element, definition: str, segment: str, path: Path) -> dict:
    node = root.find(f"./definitions/Definition[@name='{definition}']/script/segment[@name='{segment}']")
    if node is None or not node.text:
        raise ValueError(f"Missing {definition}/{segment}")
    return {
        "source_path": path.as_posix(), "source_sha256": digest(path),
        "xpath": f"./definitions/Definition[@name='{definition}']/script/segment[@name='{segment}']",
        "segment_sha256": hashlib.sha256(node.text.encode("utf-8")).hexdigest(),
    }


def line_reference(path: Path, needles: tuple[str, ...]) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    result = {needle: [index for index, line in enumerate(lines, 1) if needle in line] for needle in needles}
    if any(not found for found in result.values()):
        raise ValueError(f"Missing finalized source evidence in {path}: {result}")
    return {"source_path": path.as_posix(), "source_sha256": digest(path), "line_matches": result}


def source_expression(component: dict, compiled: Path) -> dict | None:
    path = compiled / f"{component['parent_definition']}.f"
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = re.compile(rf"!\s+{component['compilation_order']}:\[pgb\]")
    candidates = []
    for index, line in enumerate(lines):
        if not marker.match(line):
            continue
        for offset in range(index + 1, min(index + 14, len(lines))):
            if re.match(r"!\s+\d+:\[", lines[offset]):
                break
            if re.match(r"\s*PGB\(.*?\)\s*=", lines[offset]):
                candidates.append({"line": offset + 1, "expression": lines[offset].split("=", 1)[1].strip()})
    return {"source_path": path.as_posix(), "source_sha256": digest(path), "assignments": candidates}


def stats(values: list[float], times: list[float]) -> dict:
    if not values or len(values) != len(times) or not all(math.isfinite(v) for v in values + times):
        raise ValueError("Invalid trace samples")
    result = {
        "sample_count": len(values), "time_start_s": times[0], "time_end_s": times[-1],
        "minimum": min(values), "maximum": max(values), "first": values[0], "last": values[-1],
        "absolute_peak": max(abs(value) for value in values),
        "absolute_peak_time_s": times[max(range(len(values)), key=lambda index: abs(values[index]))],
    }
    unique = sorted(set(values))
    if len(unique) <= 4:
        result["discrete_values"] = unique
        result["transitions"] = [
            {"time_s": times[index], "from": values[index - 1], "to": values[index]}
            for index in range(1, len(values)) if values[index] != values[index - 1]
        ]
    return result


def role_table(channels: list[dict]) -> list[dict]:
    by_call = {channel["call_id"]: channel for channel in channels}
    arm = [c["call_id"] for c in channels if re.match(r"Ia (Top|Btm)(_|$)", c["description"])]
    cap = [c["call_id"] for c in channels if c["description"].startswith("Sum Vc ")]
    records = [
        ("fault_active", "missing_direct_output", [71, 143], "1", "Fault mode is the protection FltPulse, not the fault-switch command or persistent FltMode. Neither FltActive nor DC_flt_Mid is exported."),
        ("v_inserted", "missing", [], "kV", "No measured FullCellR_n Ntop-minus-Nbtm output exists. Capacitor sums, Vref and cell orders are not inserted terminal voltage."),
        ("blocking_state", "available_deblocking_proxy_units_missing", [29, 30], "1", "Dblk1P/Dblk2P feed the actual control hierarchy. Zero means blocking requested. Actual FiringHBridge Block additionally ORs inverted DBlk with Fltm; Block_Finder_H flag is not exported."),
        ("i_dc_fault", "available_units_missing", [33], "kA", "Selected physical fault branch current through RT_12 and CMultiplexer; Flt_Select=5 selects IFlt_Mid. Native fault_sw defines current in kA; INF/INFX units are blank."),
        ("v_dc", "available_units_missing", [9, 13, 25, 26, 27, 28], "kV", "Edc1/Edc2 are differential DC voltmeters; two 2-vector ground-referenced outputs also exist. INF/INFX units are blank. Keep station and pole identity."),
        ("i_arm", "available_units_missing", arm, "kA", "Twelve scalar arm currents from physical master:varrlc current outputs. Current field contract declares kA; INF/INFX units are blank."),
        ("v_cap", "aggregate_only_units_missing", cap, "kV", "Twelve scalar sums of 76-cell capacitor-voltage arrays exist. Individual cell voltages are not exported. VSCConverter:Vc is not a capacitor-voltage selector."),
        ("recovery_enable", "available_deblocking_proxy_units_missing", [29, 30, 31, 32], "1", "T1 Dblk1P re-enables at 0.561 s with Discon1 reset. This is enable-state evidence only; voltage, power and current recovery checks remain required."),
        ("time", "available", [], "s", "All 18 OUT time columns are checked by the existing parser; INFX declares a 4000 Hz Time domain."),
    ]
    return [
        {"role": role, "availability": availability, "required_units": unit,
         "call_ids": calls, "selectors": [by_call[call]["path"] for call in calls],
         "evidence_ready": role == "time", "reason": reason}
        for role, availability, calls, unit, reason in records
    ]


def probes(index: dict[str, dict], library_root: ET.Element, master_root: ET.Element,
           project: Path, library: Path, master: Path, compiled: Path) -> dict:
    cell = library_root.find("./definitions/Definition[@name='FullCellR_n']")
    ports = {p.attrib["name"]: dict(p.attrib) for p in cell.findall("./svg/port") if p.get("name") in {"Ntop", "Nbtm"}}
    voltage_sites = []
    for owner, arm in (("2087957400", "top"), ("1092787740", "bottom")):
        component = index[owner]
        if component["orientation"] != 0:
            raise ValueError("Probe calculation only supports the audited unrotated cell instances")
        terminal = {name: [component["x"] + int(port["x"]), component["y"] + int(port["y"])] for name, port in ports.items()}
        voltage_sites.append({"arm": arm, "component": component, "ports": ports, "terminals": terminal,
                              "measurement": "V(Ntop) - V(Nbtm)", "expected_units": "kV",
                              "required_runtime_instances": 6})
    return {
        "status": "inspected",
        "inserted_voltage": {
            "sites": voltage_sites,
            "probe_definition": "master:voltmeter", "positive_port": "N1", "negative_port": "N2",
            "probe_local_ports": {"N1": [0, 0], "N2": [0, 36]},
            "polarity_evidence": segment_reference(master_root, "voltmeter", "Dsout", master),
            "scope": "External aggregate arm-cell terminal voltage, measured separately for each of six station/phase instances and both arms. Sign convention must be reviewed against the fault-current direction; do not change polarity after seeing results to obtain PASS.",
            "excluded_substitutes": ["SUM(VcT)", "SUM(VcB)", "Vref", "NoCells ORD", "internal a-minus-b Vbr", "EBRD=-Vth"],
        },
        "fault_switch": {
            "timer": index["1067520513"], "timer_output_xy": [1206, 594],
            "fault_time_control": index["208155720"],
            "timer_output_label": index["1174284206"],
            "selector": index["1311596185"], "decoder": index["53975847"],
            "selected_command_tap": index["1506967676"], "selected_command_label": index["308537607"],
            "selected_switch": index["349503808"], "switch_terminals": {"A": [1530, 900], "B": [1494, 900]},
            "command_variable": "DC_flt_Mid", "command_active_value": 1,
            "command_binding": "master:fault_sw Name is the named control variable, not an explicit signal port.",
            "true_closed_state": "1 - E_BtoI(OPENBR(NBR, SS)); currently only PSCAD AG1 indication, no sampled output",
            "timer_logic": segment_reference(master_root, "tfaultn", "Dsdyn", master),
            "switch_logic": segment_reference(master_root, "fault_sw", "Dsdyn", master),
            "source_chain": line_reference(compiled / "Main.f", ("IT_3(Flt_Select) = FltActive", "DC_flt_Mid = IT_3(5)", "),0,DC_flt_Mid )")),
        },
        "fault_current": {
            "output": index["798055218"], "merge": index["2069640825"], "selector": index["482646581"],
            "merge_inputs": {"1": "zero", "2": "zero", "3": "IFlt_2PN", "4": "IFlt_2P", "5": "IFlt_Mid", "6": "IFlt_1P", "7": "IFlt_1PN", "8": "zero"},
            "selected_input": 5, "unit_evidence": "master:fault_sw form Iflt description: Name for Fault Current (kA)",
            "positive_direction": "Selected fault_sw branch A to B; do not infer station direction from the PGB title.",
            "source_chain": line_reference(compiled / "Main.f", ("RT_12(5) = IFlt_Mid", "RT_8 = RT_12(MIN(Flt_Select,8))", "PGB(IPGB+33) = RT_8", "IFlt_Mid = ( CBR((IBRCH+73), SS))")),
        },
        "blocking": {
            "deblock_outputs": [index["1738732526"], index["233224815"]],
            "polarity": "Dblk1P/Dblk2P: 1=enabled; PolePWM Blk=logical NOT DBlk; FiringHBridge Block=Blk OR Fltm (1=block requested)",
            "gate_input_sites": [
                {"component": index["1522304910"], "port": "Block", "xy": [2196, 1440], "arm": "top"},
                {"component": index["1370947611"], "port": "Block", "xy": [2196, 1890], "arm": "bottom"},
            ],
            "source_chain": line_reference(compiled / "MMC_Hb_Pole_PWM.f", ("IF (DBlk .NE. 0) THEN", "IF ( (Blk .NE. 0) .OR. (Fltm .NE. 0) ) THEN", "CALL HBridge_Ctrl(IT_9,IT_3,76,IaBtm,IT_16", "CALL HBridge_Ctrl(IT_10,IT_1,76,IaTop,IT_15", "CALL Block_Finder_H(76,T1_u")),
            "internal_flag": "FullCellR_n Block_Finder_H(76,FP1,FP2,FP3,FP4,BlkFlag) is the internal switching-state determination; BlkFlag==1 is documented by its If blocked branch. No sampled BlkFlag exists.",
            "library_evidence": segment_reference(library_root, "FullCellR_n", "Dsdyn", library),
            "fault_mode_label_caveat": "PGB Fault mode is REAL(FltPulse), a 1 ms monostable. Persistent FltMode is a different signal, passed to Fltm in PolePWM.",
            "fault_mode_source": line_reference(compiled / "MMC_Hb_PWM.f", ("PGB(IPGB+2) = REAL(FltPulse)", "FltMode = NINT(RVD2_2(1))", "RVD2_1(1) = FLOAT(DCflt_Flag)")),
        },
        "arm_current": {"top": index["1514910955"], "bottom": index["1386643874"], "units_evidence": "master:varrlc form parameter I describes Name for Branch Current [kA]"},
        "capacitor_voltage": {
            "top_sum": index["1736788950"], "bottom_sum": index["722366065"],
            "internal_array_dimension": 76, "exported_dimension": 1,
            "array_probe_port": {"name": "Vc:DimC", "model": "Transfer", "offset": [54, -18], "dim": 0, "type": "Real", "mode": "Output", "dimension_binding": "DimC=$(NoCells1); compiled as 76", "top_xy": [900, 378], "bottom_xy": [900, 666], "unit_attribute": None},
            "limitation": "Only summed capacitor voltage is exported; per-cell balance is unobservable. The raw Vc array can be probed in a new derived copy, retaining its 76-element dimension. The port itself has no unit attribute; the SumVc0 parameter specifies kV.",
        },
    }


def source_profile(project: Path, library: Path) -> dict:
    project_root, library_root = (ET.parse(path).getroot() for path in (project, library))
    pole = project_root.find("./definitions/Definition[@name='MMC_Hb_Pole_PWM']")
    definition_contracts = {}
    for name in ("FullCellR_n", "FiringHBridge"):
        node = library_root.find(f"./definitions/Definition[@name='{name}']")
        definition_contracts[name] = {
            "ports": [dict(port.attrib) for port in node.findall("./svg/port") if port.get("name") in {"Ntop", "Nbtm", "Vc:DimC", "Block"}],
            "form": [{**parameter.attrib, "default": parameter.findtext("value")} for parameter in node.findall("./form/category/parameter") if parameter.get("name") in {"DimC", "DimFb", "SumVc0", "C", "DTBP", "BPS_L", "FrChange"}],
            "segments": [{**segment_reference(library_root, name, segment.attrib["name"], library),
                          "called_routines": sorted(set(re.findall(r"\bCALL\s+([A-Za-z_0-9]+)\s*\(", segment.text or "", re.IGNORECASE)))} for segment in node.findall("./script/segment") if segment.text],
        }
    wires = []
    for wire in pole.findall("./schematic/Wire"):
        if wire.get("orient", "0") != "0":
            continue
        vertices = [[int(wire.get("x", "0")) + int(vertex.attrib["x"]), int(wire.get("y", "0")) + int(vertex.attrib["y"])] for vertex in wire.findall("vertex")]
        if vertices:
            wires.append({"owner_id": wire.get("id"), "vertices": vertices, "endpoints": [vertices[0], vertices[-1]]})
    sites = []
    for component in pole.findall("./schematic/User"):
        name = (component.get("defn") or component.get("name", "")).rsplit(":", 1)[-1]
        if name not in definition_contracts:
            continue
        if component.get("orient") != "0":
            raise ValueError("Unreviewed profile component orientation")
        for port in definition_contracts[name]["ports"]:
            xy = [int(component.attrib["x"]) + int(port["x"]), int(component.attrib["y"]) + int(port["y"])]
            matching = [wire for wire in wires if xy in wire["endpoints"]]
            if not matching:
                raise ValueError(f"Profile {project} has no matching wire endpoint at {name}/{port['name']} {xy}")
            sites.append({"component": component_record(component, "MMC_Hb_Pole_PWM", project), "port": port, "xy": xy, "matching_wires": matching})
    return {"source_project": project.as_posix(), "source_project_sha256": digest(project),
            "source_library": library.as_posix(), "source_library_sha256": digest(library),
            "library_namespace": library_root.get("name"), "definition_contracts": definition_contracts,
            "sites": sites, "all_sites_have_matching_wire_endpoints": True}


def collect(run: Path, master: Path, official_root: Path) -> dict:
    staging = run / STAGING
    project, library = staging / f"{PREFIX}.pscx", staging / "intermediate.pslx"
    compiled = staging / f"{PREFIX}.gf42"
    output = run / "BLANK_MMC.outputs"
    inf, infx = output / f"{PREFIX}.inf", output / f"{PREFIX}.infx"
    parts = sorted(output.glob(f"{PREFIX}_[0-9][0-9].out"))
    journal = run / JOURNAL
    journal_data = json.loads(journal.read_text(encoding="utf-8"))
    archived_sources = {name: Path(path) for name, path in journal_data["result"]["template_native"]["source_paths"].items()}
    official_project, official_library = official_root / "H_MMC_Mono_DC.pscx", official_root / "intermediate.pslx"
    code = [Path(__file__).resolve(), REPO / "pscad_mcp/core/pscad_adapter.py", REPO / "pscad_mcp/core/executor.py"]
    sources = [project, library, master, journal, inf, infx, staging / "BLANK_MMC.pscx", *parts, *compiled.glob("*.f"), official_project, official_library, *archived_sources.values()]
    before = snapshot(sources)
    code_before = snapshot(code)
    root, library_root, master_root = (ET.parse(path).getroot() for path in (project, library, master))
    index = components(root, project)
    parsed = asyncio.run(PscadAdapter(robust_executor).read_psout(str(parts[0]), max_samples=100000, summary_only=False))
    if len(parts) != 18 or len(parsed["channels"]) != 177 or parsed["warnings"] or parsed["skipped_channels"]:
        raise ValueError("Historical output shape changed or parser diagnostics are present")
    metadata = ET.parse(infx).getroot()
    scalar_map = {}
    for analog in metadata.findall("./List/Analog"):
        for position in range(int(analog.attrib["dim"])):
            call = int(analog.attrib["index"]) + position + 1
            if call in scalar_map:
                raise ValueError("Overlapping INFX channel indices")
            scalar_map[call] = {**analog.attrib, "vector_position_one_based": position + 1}
    channels = []
    inf_lines = inf.read_text(encoding="utf-8").splitlines()
    times = parsed["channels"][0]["domain"]
    for trace in parsed["channels"]:
        call = trace["call_id"]
        analog = scalar_map[call]
        owner, occurrence = analog["id"].split(":")
        component = index[owner]
        if analog["unit"] != trace["units"] or trace["domain"] != times:
            raise ValueError("INF/INFX units or trace domains differ")
        part = output / f"{PREFIX}_{(call - 1) // 10 + 1:02d}.out"
        source = dict(component)
        source["source_sha256"] = before[project.as_posix()]["sha256"]
        path = analog["name"].rsplit(":", 1)[0]
        station = "T2" if "MMC_Hb_PWM(0)" in path else "T1" if "MMC_Hb_PWM(1)" in path else None
        pole = re.search(r"MMC_Hb_Pole_PWM\((\d+)\)", path)
        channels.append({
            **{key: value for key, value in trace.items() if key not in {"values", "domain", "min", "max"}},
            "scalar_dimension": 1, "source_dimension": int(analog["dim"]),
            "vector_position_one_based": analog["vector_position_one_based"],
            "owner_id": owner, "full_owner_id": analog["id"], "runtime_occurrence": int(occurrence),
            "instance_path": path, "infx_name": analog["name"],
            "station_from_compilation_order": station,
            "phase_from_compilation_order": ("C", "B", "A")[int(pole.group(1)) % 3] if pole else None,
            "component": source, "signal_source": source_expression(component, compiled),
            "output_part": part.as_posix(), "output_part_sha256": before[part.as_posix()]["sha256"],
            "column_one_based_including_time": (call - 1) % 10 + 2,
            "inf": {"path": inf.as_posix(), "sha256": before[inf.as_posix()]["sha256"], "line": call, "record": inf_lines[call - 1]},
            "infx": {"path": infx.as_posix(), "sha256": before[infx.as_posix()]["sha256"], "record": analog},
            "samples": stats(trace["values"], times),
        })
    identifiers = [(channel["full_owner_id"], channel["vector_position_one_based"]) for channel in channels]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Ambiguous owner/position identity")
    if any(not channel["signal_source"] or not channel["signal_source"]["assignments"] for channel in channels):
        raise ValueError("A sampled channel lacks a compiled PGB source assignment")
    delta = [right - left for left, right in pairwise(times)]
    if len(times) != 5201 or times[0] != 0 or times[-1] != 1.3 or any(abs(value - 0.00025) > 1e-12 for value in delta):
        raise ValueError("Historical output sampling domain changed")
    probe_records = probes(index, library_root, master_root, project, library, master, compiled)
    profiles = {"historical_native": source_profile(project, library), "installed_official": source_profile(official_project, official_library)}
    for name, source in archived_sources.items():
        if digest(source) != journal_data["result"]["template_native"]["source_hashes"][name]:
            raise ValueError(f"Archived source {name} no longer matches historical journal")
    if digest(library) != digest(archived_sources["library"]):
        raise ValueError("Staged historical library no longer matches its archived source")
    after, code_after = snapshot(sources), snapshot(code)
    if after != before or code_after != code_before:
        raise ValueError("A sampled source or parser changed during collection")
    return {
        "schema_version": 1, "scope": "historical_native_signal_audit",
        "status": "inspected", "acceptance_verdict": "INCOMPLETE_ANALYSIS", "licensed_run_performed": False,
        "collection_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "historical_code_commit": None, "historical_code_commit_reason": "Journal has no commit; the collection commit must not be attributed to the historical run.",
        "source_manifest_before": before, "source_manifest_after": after, "sources_immutable": True,
        "collector_code_before": code_before, "collector_code_after": code_after,
        "journal": {"path": journal.as_posix(), "sha256": digest(journal), "build_id": journal_data["build_id"], "plan_hash": journal_data["plan_hash"], "historical_acceptance": journal_data["result"]["acceptance"]},
        "time": {"units": "s", "sample_count": len(times), "start_s": times[0], "end_s": times[-1], "step_s": 0.00025, "infx_domain": metadata.find("Domain").attrib, "infx_sample": metadata.find("Domain/Sample").attrib, "all_parts_synchronized": True},
        "channel_count": len(channels), "output_part_count": len(parts),
        "owner_identity_rule": "INF call_id is a scalar channel number. INFX full owner id plus vector position is unique. Base component owner alone repeats across runtime module instances.",
        "required_channels": role_table(channels), "channels": channels, "probe_preparation": probe_records,
        "source_profiles": profiles,
        "profile_provenance": {
            "historical_archived_sources": {name: {"path": path.as_posix(), "sha256": digest(path)} for name, path in archived_sources.items()},
            "archive_hashes_match_journal": True, "historical_staged_library_matches_archive": True,
            "history_limit": "The two library profiles differ before this audit. The available journal establishes the archived inputs, not who changed them or when. No claim that either library was modified by this audit is supported.",
            "incompatibilities": ["Nbtm y offset: historical36 versus installed54", "FiringHBridge Block x offset: historical18 versus installed0", "Firing routine: HBridge_Ctrl versus HBridge_Ctrl1", "Cell routine: MMC_FullB versus FULLCELL1_CFG/FULLCELL1_EXE at installed DTBP0", "Firing FrChange instance: historical1 versus installed0"],
            "rule": "Do not combine a project's component coordinates, IDs or wire endpoints with the other library profile. Every fresh derived model needs its own paired source-hash and port-contract audit.",
        },
        "topology": {"historical_native": "full_bridge", "evidence": "FullCellR_n with four gate arrays and FiringHBridge in the reachable pole definition", "nominal_internal_cells_per_arm": 76, "intrinsic_blocking_proven": False},
        "limitations": [
            "No PSCAD connection, compiler or simulation started; this audit cannot establish acceptance at the collection commit.",
            "Required direct fault_active and v_inserted outputs are absent; blank units and gate-state provenance prevent complete WP4 evidence.",
            "No waveform threshold was changed, no missing channel was synthesized, and no historical report was promoted to PASS.",
            "Probe proposals require derived-copy save/reload, compilation, a fresh licensed run and independent review of polarity and station binding.",
        ],
    }


def channel_table(result: dict) -> str:
    by_call = {channel["call_id"]: channel for channel in result["channels"]}
    lines = [
        "# Required Native MMC Channels", "",
        "Generated from finalized historical OUT, INF, INFX, PSCX and compiled-source evidence.",
        "All listed traces have 5201 samples over 0..1.3 s at 0.00025 s. Empty exported units remain empty.",
        "The full source hashes, component definitions, source assignments and metadata records are in signal-manifest.json.", "",
        "| Role | INF call / selector | Full owner ID | Scalar / source dimension | Exported units | OUT part | Source assignment |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for role in result["required_channels"]:
        if not role["call_ids"]:
            state = "available: time column, units s" if role["role"] == "time" else role["availability"]
            lines.append(f"| {role['role']} | {state} | - | - | - | all / absent | - |")
        for call in role["call_ids"]:
            channel = by_call[call]
            expressions = ", ".join(item["expression"] for item in channel["signal_source"]["assignments"])
            lines.append(f"| {role['role']} | {call}: {channel['path']} | {channel['full_owner_id']} | 1 / {channel['source_dimension']} | {channel['units'] or '(empty)'} | {(call - 1) // 10 + 1:02d} | {expressions} |")
    lines += ["", "## Availability and Interpretation", ""]
    lines += [f"- `{role['role']}`: **{role['availability']}**. {role['reason']}" for role in result["required_channels"]]
    lines += ["", "`Fault mode` rows are rejected candidate aliases for fault_active, not valid direct evidence.",
              "T2 is MMC_Hb_PWM(0), T1 is MMC_Hb_PWM(1). Pole occurrences 0..2 are T2 C/B/A; 3..5 are T1 C/B/A.",
              "A base owner ID can repeat across runtime instances. Select full INFX owner identity plus vector position.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--official-root", type=Path, default=DEFAULT_OFFICIAL)
    args = parser.parse_args()
    result = collect(args.run_root.resolve(), args.master.resolve(), args.official_root.resolve())
    target = OWNED / "signal-manifest.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    (OWNED / "required-channel-table.md").write_text(channel_table(result), encoding="utf-8")
    print(json.dumps({"artifact": target.as_posix(), "sha256": digest(target), "channels": result["channel_count"], "parts": result["output_part_count"], "samples": result["time"]["sample_count"], "sources_immutable": result["sources_immutable"], "acceptance_verdict": result["acceptance_verdict"]}, indent=2))


if __name__ == "__main__":
    main()
