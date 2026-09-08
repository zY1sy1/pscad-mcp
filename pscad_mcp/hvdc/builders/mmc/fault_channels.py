"""Derived-only MMC measurements and immutable output-dataset identities.

Vendor definitions are read from the local installation at runtime. No vendor
definition body is shipped as an asset by this module.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shlex
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from .template_audit import _components, _parameters, _sha256

REQUIRED_ROLES = (
    "fault_active", "v_inserted", "blocking_state", "i_dc_fault", "v_dc",
    "i_arm", "v_cap", "recovery_enable", "p_active",
)
OUTPUT_GROUP = "MMC_FAULT_EVIDENCE"


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "mmc_fault_channels", details)


def _regular(path: str | Path) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Evidence must be a regular file.", path=str(raw))
    return raw.resolve()


def snapshot_output_dataset(primary: str | Path, *, started_after: float | None = None) -> dict[str, Any]:
    """Freeze every numbered part and INF/INFX companion before reading."""

    path = _regular(primary)
    base = re.sub(r"_\d{2,}$", "", path.stem)
    pattern = re.compile(re.escape(base) + r"(?:_\d{2,})?\.(?:out|inf|infx)$", re.IGNORECASE)
    files: dict[str, dict[str, Any]] = {}
    for item in sorted(path.parent.iterdir(), key=lambda value: value.name.casefold()):
        if pattern.fullmatch(item.name):
            observed = _regular(item)
            stat = observed.stat()
            if item.suffix.casefold() == ".out" and started_after is not None and stat.st_mtime + 1e-6 < started_after:
                raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "A dataset contains stale evidence.", path=str(observed), started_after=started_after, mtime=stat.st_mtime)
            files[item.name] = {"path": str(observed), "sha256": _sha256(observed), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if not any(name.casefold().endswith(".inf") for name in files):
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "An output dataset requires its INF metadata.", primary=str(path))
    return {"primary": str(path), "base": base, "started_after": started_after, "files": files}


def verify_output_dataset(manifest: Mapping[str, Any]) -> None:
    try:
        observed = snapshot_output_dataset(str(manifest["primary"]), started_after=manifest.get("started_after"))
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The output dataset is no longer available.") from error
    if observed["files"] != manifest.get("files"):
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The complete output or metadata identity changed during reading.", expected=manifest.get("files"), observed=observed["files"])


def _metadata(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        tokens = shlex.split(line)
        if not tokens or not (match := re.fullmatch(r"PGB\((\d+)\)", tokens[0])):
            continue
        fields = dict(token.split("=", 1) for token in tokens[1:] if "=" in token)
        records.append({"call_id": int(match.group(1)), "description": fields.get("Desc", ""), "group": fields.get("Group", ""), "units": fields.get("Units", "")})
    return records


async def read_fault_output_dataset(reader: Any, primary: str | Path, channel_contract: Mapping[str, Any], *, started_after: float | None = None) -> dict[str, Any]:
    """Use the existing output reader per exact selector, retaining file identity."""

    project_readback = verify_fault_instrumentation(channel_contract["project_path"], channel_contract)
    if project_readback["project_sha256"] != channel_contract["readback"]["project_sha256"]:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The frozen measured project changed after its last readback.")
    manifest = snapshot_output_dataset(primary, started_after=started_after)
    inf = next(Path(value["path"]) for key, value in manifest["files"].items() if key.casefold().endswith(".inf"))
    metadata = _metadata(inf)
    infx_paths = [Path(value["path"]) for name, value in manifest["files"].items() if name.casefold().endswith(".infx")]
    if len(infx_paths) != 1:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Runtime owner identity requires one compiled INFX companion.")
    infx = ET.parse(infx_paths[0]).getroot()
    if infx.get("device") != "EMTDC" or not any(item.get("name") == "Time" and item.get("unit") == "s" for item in infx.findall("Domain")):
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The compiled output has no EMTDC time domain in seconds.")
    ids = sorted(item["call_id"] for item in metadata)
    if ids != list(range(1, len(ids) + 1)) or not ids:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Output channel numbers must be complete and unique.")
    expected_parts = {f"{manifest['base']}_{index:02d}.out".casefold() for index in range(1, math.ceil(len(ids) / 10) + 1)}
    observed_parts = {name.casefold() for name in manifest["files"] if name.casefold().endswith(".out")}
    if expected_parts != observed_parts:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The numbered output set disagrees with INF metadata.", expected=sorted(expected_parts), observed=sorted(observed_parts))
    bulk = await reader(str(primary), max_samples=1_000_000, summary_only=False)
    bulk_channels = bulk.get("channels", []) if isinstance(bulk, Mapping) else []
    channels = []
    missing = []
    for binding in [*channel_contract.get("channels", []), *channel_contract.get("diagnostic_channels", [])]:
        selector = binding["selector"]
        candidates = [item for item in metadata if item["description"] == selector["description"] and item["group"] == selector.get("group", "")]
        if len(candidates) != 1:
            missing.append({"channel_id": binding["channel_id"], "matches": len(candidates)})
            continue
        selected = candidates[0]
        compiled = [item for item in infx.iter("Analog") if item.get("name", "").endswith(":" + selected["description"]) and item.get("label") == selected["group"]]
        expected_instance = binding["definition_name"] + "(0):" + selected["description"]
        if len(compiled) != 1 or compiled[0].get("name") != expected_instance or compiled[0].get("id") != binding["owner_id"] + ":0" or compiled[0].get("index") != str(selected["call_id"] - 1) or compiled[0].get("dim") != str(binding["dimension"]) or compiled[0].get("unit") != selected["units"]:
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Compiled channel owner, scope, index or units disagree with the measured project.", channel_id=binding["channel_id"], observed=[dict(item.attrib) for item in compiled])
        traces = [item for item in bulk_channels if item.get("description") == selected["description"] and item.get("group") == selected["group"]]
        if not traces:
            result = await reader(str(primary), channel=f"{selected['group']}/{selected['description']}" if selected["group"] else selected["description"], max_samples=1_000_000, summary_only=False)
            traces = result.get("channels", []) if isinstance(result, Mapping) else []
        if len(traces) != 1:
            missing.append({"channel_id": binding["channel_id"], "matches": len(traces)})
            continue
        trace = traces[0]
        if trace.get("description") != selected["description"] or trace.get("units") != selected["units"]:
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The reader and frozen INF metadata disagree.", channel_id=binding["channel_id"])
        part_name = f"{manifest['base']}_{(selected['call_id'] - 1) // 10 + 1:02d}.out"
        part = next(value for name, value in manifest["files"].items() if name.casefold() == part_name.casefold())
        times = trace.get("domain", trace.get("time", []))
        channels.append({**trace, **selector, "channel_id": binding["channel_id"], "dimension": binding["dimension"], "call_id": selected["call_id"], "output_part": part["path"], "metadata_file": str(inf), "hash": part["sha256"], "metadata_sha256": _sha256(inf), "compiler_metadata_file": str(infx_paths[0]), "compiler_metadata_sha256": _sha256(infx_paths[0]), "compiled_identity": dict(compiled[0].attrib), "sample_count": len(times), "time_bounds_s": [times[0], times[-1]] if times else None})
    verify_output_dataset(manifest)
    if verify_fault_instrumentation(channel_contract["project_path"], channel_contract) != project_readback:
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The measured project changed during output reading.")
    return {"channels": channels, "identity": manifest, "missing_selectors": missing, "evidence_kind": "pscad_output", "project_readback": project_readback}


def instrument_fault_channels(source: str | Path, destination: str | Path, *, library: str | Path, master: str | Path, expected_source_hashes: Mapping[str, Any] | None = None) -> dict[str, Any]:
    paths = {"project": _regular(source), "library": _regular(library), "master": _regular(master)}
    hashes = {name: _sha256(path) for name, path in paths.items()}
    for name, expected in (expected_source_hashes or {}).items():
        digest = expected.get("sha256") if isinstance(expected, Mapping) else expected
        if hashes.get(name) != digest:
            raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "The instrumentation source differs from its frozen identity.", source=name, expected=digest, observed=hashes.get(name))
    target = Path(destination).expanduser().resolve()
    if target in paths.values() or target.exists() or target.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "Instrumentation requires a new derived project.", destination=str(target))
    root, library_root, master_root = (ET.parse(paths[name]).getroot() for name in ("project", "library", "master"))
    definitions = {item.get("name"): item for item in root.findall("./definitions/Definition")}
    vendor = {item.get("name"): item for item in library_root.findall("./definitions/Definition")}
    masters = {item.get("name"): item for item in master_root.findall("./definitions/Definition")}
    required = ("Main", "MMC_Hb_PWM", "MMC_Hb_Pole_PWM")
    if any(name not in definitions for name in required) or "FullCellR_n" not in vendor or "fault_sw" not in masters:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The audited full-bridge source chain is absent.")
    cell = vendor["FullCellR_n"]
    ports = {item.get("name"): item for item in cell.findall("./svg/port")}
    if any(name not in ports or ports[name].get("internal") != "false" or (ports[name].text or "").strip() != "true" for name in ("Ntop", "Nbtm")):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "Full-cell electrical probe ports are not unconditional external ports.")
    pgb_ports = {item.get("name") for item in masters["pgb"].findall("./svg/port")}
    if "Signl" not in pgb_ports:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "Installed PGB metadata has no Signl input.")
    old_namespace, namespace = root.get("name", ""), target.stem
    root.set("name", namespace)
    for element in root.iter():
        for key in ("name", "defn", "definition"):
            value = element.get(key, "")
            if value.startswith(old_namespace + ":"):
                element.set(key, namespace + value[len(old_namespace):])
    used_ids = {item.get("id") for item in root.iter()}

    def allocate(label: str) -> str:
        value = 1000000000 + int(hashlib.sha256(label.encode("ascii")).hexdigest()[:8], 16) % 1000000000
        while str(value) in used_ids:
            value += 1
        used_ids.add(str(value))
        return str(value)

    def set_param(component: ET.Element, name: str, value: str) -> None:
        existing = [item for item in component.findall("./paramlist/param") if item.get("name") == name]
        if len(existing) > 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A source parameter is duplicated.", owner=component.get("id"), parameter=name)
        if existing:
            existing[0].set("value", value)
        else:
            params = component.find("paramlist")
            if params is None:
                params = ET.SubElement(component, "paramlist", {"name": "", "link": "-1"})
            ET.SubElement(params, "param", {"name": name, "value": value})

    def clone_definition(original: ET.Element, name: str) -> ET.Element:
        result = copy.deepcopy(original)
        result.set("name", name)
        result.set("id", allocate("definition:" + name))
        result.set("instances", "0")
        root.find("definitions").append(result)
        definitions[name] = result
        return result

    def expose(definition: ET.Element, parameter: str, segment_name: str, expression: str, kind: str) -> None:
        category = definition.find("./form/category")
        parameter_node = ET.SubElement(category, "parameter", {"type": "Text", "name": parameter, "desc": "Measurement output signal", "content_type": "Literal"})
        ET.SubElement(parameter_node, "value").text = ""
        script = definition.find("script")
        segment = next((item for item in script.findall("segment") if item.get("name") == segment_name), None)
        if segment is None:
            segment = ET.SubElement(script, "segment", {"name": segment_name, "classid": "CoreSegment", "id": allocate(definition.get("name") + segment_name)})
        segment.text = (segment.text or "").rstrip() + f"\n#OUTPUT {kind} {parameter} {{{expression}}}\n"

    observed_cell = clone_definition(cell, "MmcObservedFullCell")
    dynamic = next(item for item in observed_cell.findall("./script/segment") if item.get("name") == "Dsdyn")
    if "CALL Block_Finder_H" not in (dynamic.text or "") or "IVD1_1" not in (dynamic.text or ""):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The installed cell has no audited physical blocking state.")
    expose(observed_cell, "MmcInserted", "Dsout", "$VDC:Ntop:Nbtm", "REAL")
    expose(observed_cell, "MmcCapSum", "Dsout", "SUM($Vc)", "REAL")
    expose(observed_cell, "MmcBlocked", "Dsdyn", "IVD1_1", "INTEGER")
    observed_fault = clone_definition(masters["fault_sw"], "MmcObservedFaultSwitch")
    expose(observed_fault, "MmcClosed", "Dsout", "1-E_BtoI(OPENBR($NBR,$SS))", "INTEGER")
    channels: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    wires: list[dict[str, Any]] = []

    def component_record(definition: ET.Element, component: ET.Element) -> dict[str, Any]:
        return {"definition_name": definition.get("name"), "owner_id": component.get("id"), "definition": component.get("defn"), "parameters": dict(_parameters(component)), "position": {key: component.get(key) for key in ("x", "y", "orient")}}

    def add_probe(definition: ET.Element, role: str, scope: str, signal: str, source_component: ET.Element, *, kind: str = "physical_measurement", source_parameter: str | None = None, polarity: dict[str, int] | None = None, nominal: float | None = None, extra: dict[str, Any] | None = None, units_override: str | None = None) -> None:
        channel_id = f"MFE_{scope.replace('/', '_')}_{role}"
        slot = len(channels)
        x, y = 3600, 3600 + 54 * slot
        canvas = definition.find("schematic")
        if canvas is None:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A measurement scope has no schematic.")
        label = ET.SubElement(canvas, "User", {"classid": "UserCmp", "defn": "master:datalabel", "id": allocate(channel_id + ":label"), "x": str(x - 72), "y": str(y), "orient": "0", "w": "72", "h": "22", "z": str(20000 + slot), "link": "-1", "q": "4"})
        set_param(label, "Name", signal)
        pgb = ET.SubElement(canvas, "User", {"classid": "UserCmp", "defn": "master:pgb", "id": allocate(channel_id), "x": str(x), "y": str(y), "orient": "0", "w": "84", "h": "38", "z": str(22000 + slot), "link": "-1", "q": "4"})
        units = "kV" if role in ("v_inserted", "v_dc", "v_cap") else "kA" if role in ("i_arm", "i_dc_fault") else "MW" if role == "p_active" else "1"
        units = units_override or units
        for name, value in {"Name": channel_id, "Group": OUTPUT_GROUP, "Display": "1", "Scale": "1.0", "Units": units, "mrun": "0", "Pol": "0", "Max": "1000.0", "Min": "-1000.0", "UseSignalName": "0", "enab": "1"}.items():
            set_param(pgb, name, value)
        wire = ET.SubElement(canvas, "Wire", {"classid": "WireOrthogonal", "id": allocate(channel_id + ":wire"), "name": "", "x": str(x - 72), "y": str(y), "w": "82", "h": "10", "orient": "0"})
        ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
        ET.SubElement(wire, "vertex", {"x": "72", "y": "0"})
        wires.append({"definition_name": definition.get("name"), "owner_id": wire.get("id"), "attributes": {key: wire.get(key) for key in ("classid", "x", "y", "orient")}, "vertices": [dict(item.attrib) for item in wire.findall("vertex")]})
        source_record = {"kind": kind, "owner_id": source_component.get("id"), "definition": source_component.get("defn"), "parameter": source_parameter, "signal_name": signal, **(extra or {})}
        channels.append({"channel_id": channel_id, "role": role, "model_scope": scope, "definition_name": definition.get("name"), "owner_id": pgb.get("id"), "definition": "master:pgb", "signal_source": source_record, "selector": {"description": channel_id, "group": OUTPUT_GROUP, "port": "Signl"}, "units": units, "dimension": 1, "polarity": polarity, "nominal": nominal, "output_part": None, "metadata_file": None, "sample_count": None, "time_bounds_s": None, "hash": None})
        probes.extend(component_record(definition, component) for component in (label, pgb, source_component))

    main = definitions["Main"]
    switches = [item for item in _components(main) if item.get("defn") == "master:fault_sw" and dict(_parameters(item)).get("Name") == "DC_flt_2_PN"]
    if len(switches) != 1:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The terminal-2 pole-to-pole fault branch is not unique.")
    switch = switches[0]
    switch.set("defn", namespace + ":MmcObservedFaultSwitch")
    set_param(switch, "MmcClosed", "MmcFaultClosed")
    add_probe(main, "fault_active", "DC_T2_PN", "MmcFaultClosed", switch, kind="physical_state", source_parameter="MmcClosed", polarity={"inactive": 0, "active": 1}, extra={"expression": "1-OPENBR", "quantity": "fault_branch_closed"})
    add_probe(main, "i_dc_fault", "DC_T2_PN", dict(_parameters(switch))["Iflt"], switch, source_parameter="Iflt", extra={"quantity": "branch_current", "direction": "fault_switch_A_to_B"})
    for terminal in ("T1", "T2"):
        number = terminal[-1]
        converters = [item for item in _components(main) if item.get("defn", "").endswith(":MMC_Hb_PWM") and dict(_parameters(item)).get("IvlvTop") == f"ITop{terminal}"]
        if len(converters) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A station's physical converter is not uniquely identified.", terminal=terminal)
        converter = converters[0]
        pwm_name = f"MFE_PWM_{terminal}"
        pwm = clone_definition(definitions["MMC_Hb_PWM"], pwm_name)
        converter.set("defn", namespace + ":" + pwm_name)
        poles = [item for item in _components(pwm) if item.get("defn", "").endswith(":MMC_Hb_Pole_PWM")]
        if len(poles) != 3:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The converter must expose three phase poles.", terminal=terminal)
        for phase, pole in zip(("A", "B", "C"), sorted(poles, key=lambda item: int(item.get("x", "0")))):
            pole_name = f"MFE_Pole_{terminal}_{phase}"
            pole_definition = clone_definition(definitions["MMC_Hb_Pole_PWM"], pole_name)
            pole.set("defn", namespace + ":" + pole_name)
            cells = [item for item in _components(pole_definition) if item.get("defn") == "intermediate:FullCellR_n"]
            if len(cells) != 2 or any(dict(_parameters(item)).get("DTBP") != "0" for item in cells):
                raise _error("MMC_ACCEPTANCE_INCOMPLETE", "Every pole must contain two unconditional full-bridge cell groups.")
            for arm, instance in zip(("upper", "lower"), sorted(cells, key=lambda item: int(item.get("y", "0")))):
                instance.set("defn", namespace + ":MmcObservedFullCell")
                arm_suffix = "Top" if arm == "upper" else "Btm"
                scope = f"{terminal}/{phase}/{arm}"
                for parameter, signal in (("MmcInserted", f"MmcV{arm_suffix}"), ("MmcCapSum", f"MmcVc{arm_suffix}"), ("MmcBlocked", f"MmcBlock{arm_suffix}")):
                    set_param(instance, parameter, signal)
                add_probe(pole_definition, "v_inserted", scope, f"MmcV{arm_suffix}", instance, source_parameter="MmcInserted", extra={"quantity": "cell_group_terminal_voltage", "positive_port": "Ntop", "negative_port": "Nbtm", "condition": {"DTBP": "0"}})
                add_probe(pole_definition, "v_cap", scope, f"MmcVc{arm_suffix}", instance, source_parameter="MmcCapSum", nominal=640.0, extra={"quantity": "sum_of_submodule_capacitor_voltages", "expression": "SUM(Vc)", "cell_count_expression": dict(_parameters(instance))["DimC"]})
                add_probe(pole_definition, "blocking_state", scope, f"MmcBlock{arm_suffix}", instance, kind="physical_state", source_parameter="MmcBlocked", polarity={"inactive": 0, "active": 1}, extra={"quantity": "firing_based_cell_group_blocked", "expression": "Block_Finder_H result"})
                current_signal = "IaTop" if arm == "upper" else "IaBtm"
                current_sources = [item for item in _components(pole_definition) if item.get("defn") == "master:varrlc" and dict(_parameters(item)).get("I") == current_signal]
                if len(current_sources) != 1:
                    raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The measured arm inductance branch is missing.", scope=scope)
                add_probe(pole_definition, "i_arm", scope, current_signal, current_sources[0], source_parameter="I", extra={"quantity": "arm_inductor_current", "direction": "original_varrlc_A_to_B"})
        meters = [item for item in _components(main) if item.get("defn") == "master:multimeter" and dict(_parameters(item)).get("P") == "P" + number]
        if len(meters) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The terminal power meter is missing.", terminal=terminal)
        add_probe(main, "p_active", terminal, "P" + number, meters[0], source_parameter="P", nominal=900.0 if terminal == "T1" else -900.0, extra={"quantity": "three_phase_active_power", "direction": "meter_arrow", "base_mva": dict(_parameters(meters[0]))["S"]})
        voltage_sources = [item for item in _components(main) if item.get("defn") == "master:voltmeter" and dict(_parameters(item)).get("Name") == "Edc" + number]
        if len(voltage_sources) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The pole-to-pole terminal voltage meter is missing.", terminal=terminal)
        add_probe(main, "v_dc", terminal, "Edc" + number, voltage_sources[0], source_parameter="Name", nominal=640.0, extra={"quantity": "dc_pole_to_pole_voltage", "direction": "positive_pole_minus_negative_pole"})
        controls = [item for item in _components(main) if item.get("defn", "").endswith(":VSCConverter") and dict(_parameters(item)).get("Dblk") == f"Dblk{number}P"]
        if len(controls) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The terminal recovery enable is missing.", terminal=terminal)
        vsc_name = "MFE_VSC_" + terminal
        vsc = clone_definition(definitions["VSCConverter"], vsc_name)
        controls[0].set("defn", namespace + ":" + vsc_name)
        control_name = "MFE_Control_" + terminal
        control_definition = clone_definition(definitions["VSCControl2"], control_name)
        control_calls = [item for item in _components(vsc) if item.get("defn", "").endswith(":VSCControl2")]
        if len(control_calls) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The actual station controller is not unique.")
        control_calls[0].set("defn", namespace + ":" + control_name)
        freeze_source = next(item for item in _components(control_definition) if item.get("id") == "1356454688")
        magnitude_source = next(item for item in _components(control_definition) if item.get("id") == "1359229547")
        add_probe(control_definition, "controller_freeze", terminal, "FrzI", freeze_source, kind="physical_state", polarity={"inactive": 0, "active": 1}, extra={"quantity": "actual_current_limit_antiwindup_freeze"})
        add_probe(control_definition, "controller_current_magnitude", terminal, "Imag", magnitude_source, units_override="pu", extra={"quantity": "dq_current_reference_magnitude", "base": "sqrt(2)*Sbase/(sqrt(3)*Vtr_2)"})
        add_probe(main, "recovery_enable", terminal, f"Dblk{number}P", controls[0], kind="recovery_control", source_parameter="Dblk", polarity={"inactive": 0, "active": 1}, extra={"quantity": "deblocking_enable", "electrical_recovery_required": True})

    # Update hierarchy calls from the actual specialized component graph.
    hierarchy = root.find("hierarchy")
    if hierarchy is not None:
        def rebind_calls(parent: ET.Element, scope: ET.Element | None = None) -> None:
            components = {item.get("id"): item for item in _components(scope)} if scope is not None else {}
            for call in parent.findall("call"):
                actual = components.get(call.get("link"))
                if actual is not None:
                    call.set("name", actual.get("defn"))
                local = call.get("name", "").rsplit(":", 1)[-1]
                rebind_calls(call, definitions.get(local))
        rebind_calls(hierarchy)
    reachable = reachable_instances(root)
    for channel in channels:
        scopes = [item for item in reachable if item["definition_name"] == channel["definition_name"]]
        if len(scopes) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A specialized measurement scope is not a unique running instance.", channel_id=channel["channel_id"], scopes=scopes)
        channel["instance_path"] = scopes[0]["instance_path"]
        channel["selector"].update({"owner_id": channel["owner_id"], "instance_path": channel["instance_path"]})
        channel["signal_source"]["instance_path"] = channel["instance_path"] + "/" + channel["signal_source"]["definition"].rsplit(":", 1)[-1] + "[" + channel["signal_source"]["owner_id"] + "]"
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=False)
    contract = {"schema_version": 1, "source_hashes": {name: {"path": str(paths[name]), "sha256": hashes[name]} for name in paths}, "project_path": str(target), "channels": channels, "readback_components": probes, "readback_wires": wires, "readback_ports": {name: _ports(definition) for name, definition in definitions.items() if name.startswith(("MFE_", "MmcObserved"))}, "readback_scripts": {item.get("name"): _script_hash(item) for item in (observed_cell, observed_fault)}, "instrumented_project_sha256": _sha256(target), "reachable_instances": reachable}
    contract["diagnostic_channels"] = [item for item in channels if item["role"] not in REQUIRED_ROLES]
    contract["channels"] = [item for item in channels if item["role"] in REQUIRED_ROLES]
    contract["readback"] = verify_fault_instrumentation(target, contract)
    for name, path in paths.items():
        if _sha256(path) != hashes[name]:
            raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "An original source changed while instrumentation was written.", source=name)
    return contract


def reachable_instances(root: ET.Element) -> list[dict[str, Any]]:
    """Expand runtime scope paths; repeated definition owners remain distinct."""

    definitions = {item.get("name"): item for item in root.findall("./definitions/Definition")}
    result: list[dict[str, Any]] = []
    hierarchy = root.find("hierarchy")
    def visit(name: str, path: str, seen: tuple[str, ...]) -> None:
        if name in seen:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The template instance graph is recursive.", definition=name)
        definition = definitions.get(name)
        if definition is None:
            return
        result.append({"definition_name": name, "definition_id": definition.get("id"), "instance_path": path})
        for component in _components(definition):
            local = component.get("defn", "").rsplit(":", 1)[-1]
            if local in definitions:
                visit(local, path + "/" + local + "[" + component.get("id", "") + "]", (*seen, name))
    if hierarchy is not None and hierarchy.find("call") is not None:
        call = hierarchy.find("call")
        name = call.get("name", "").rsplit(":", 1)[-1]
        visit(name, name + "[" + call.get("link", "") + "]", ())
    else:
        visit("Main", "Main", ())
    return result


def _script_hash(definition: ET.Element) -> str:
    scripts = {item.get("name"): (item.text or "").strip() for item in definition.findall("./script/segment")}
    return hashlib.sha256(json.dumps(scripts, sort_keys=True, ensure_ascii=True).encode("ascii")).hexdigest()


def _ports(definition: ET.Element) -> list[dict[str, Any]]:
    return [{"attributes": dict(item.attrib), "condition": (item.text or "").strip()} for item in definition.findall("./svg/port")]


def verify_fault_instrumentation(project: str | Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    path = _regular(project)
    if contract.get("vendor_finalized") and _sha256(path) != contract.get("instrumented_project_sha256"):
        raise _error("MMC_POSTCONDITION_FAILED", "The frozen instrumented project hash changed.")
    root = ET.parse(path).getroot()
    definitions = {item.get("name"): item for item in root.findall("./definitions/Definition")}
    for expected in contract.get("readback_components", []):
        scope = definitions.get(expected["definition_name"])
        matches = [item for item in _components(scope) if item.get("id") == expected["owner_id"]] if scope is not None else []
        if len(matches) != 1 or matches[0].get("defn") != expected["definition"] or any(dict(_parameters(matches[0])).get(key) != value for key, value in expected["parameters"].items()) or any(matches[0].get(key) != value for key, value in expected["position"].items()):
            raise _error("MMC_POSTCONDITION_FAILED", "A measured source, label or output changed after saving.", expected=expected)
    for name, digest in contract.get("readback_scripts", {}).items():
        if name not in definitions or _script_hash(definitions[name]) != digest:
            raise _error("MMC_POSTCONDITION_FAILED", "A physical measurement implementation changed after saving.", definition=name)
    for name, ports in contract.get("readback_ports", {}).items():
        if name not in definitions or _ports(definitions[name]) != ports:
            raise _error("MMC_POSTCONDITION_FAILED", "A measurement port or its activation condition changed.", definition=name)
    for wire in contract.get("readback_wires", []):
        scope = definitions.get(wire["definition_name"])
        matches = [item for item in scope.findall("./schematic/Wire") if item.get("id") == wire["owner_id"]] if scope is not None else []
        if len(matches) != 1 or any(matches[0].get(key) != value for key, value in wire["attributes"].items()) or [dict(item.attrib) for item in matches[0].findall("vertex")] != wire["vertices"]:
            raise _error("MMC_POSTCONDITION_FAILED", "A physical measurement connection changed.", wire=wire)
    if reachable_instances(root) != contract.get("reachable_instances"):
        raise _error("MMC_POSTCONDITION_FAILED", "The running instance hierarchy changed after saving.")
    return {"matched": True, "project_path": str(path), "project_sha256": _sha256(path)}


def finalize_fault_instrumentation(project: str | Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the vendor's first-save document root before any simulation."""

    result = copy.deepcopy(dict(contract))
    if result.get("vendor_finalized"):
        result["readback"] = verify_fault_instrumentation(project, result)
        return result
    observed = reachable_instances(ET.parse(project).getroot())
    expected = result["reachable_instances"]
    if not expected or not observed:
        raise _error("MMC_POSTCONDITION_FAILED", "The vendor save removed the running hierarchy.")
    before, after = expected[0]["instance_path"], observed[0]["instance_path"]
    if before != after:
        normalized = [{**item, "instance_path": before + item["instance_path"][len(after):]} for item in observed]
        if normalized != expected or expected[0]["definition_name"] != "Station" or observed[0]["definition_name"] != "Station":
            raise _error("MMC_POSTCONDITION_FAILED", "Vendor save changed actual running instances, not only the document root.")
        result["virtual_root_rebinding"] = {"before": before, "after": after, "source": "first_vendor_save", "project_sha256": _sha256(Path(project))}
        for channel in [*result["channels"], *result.get("diagnostic_channels", [])]:
            for record, key in ((channel, "instance_path"), (channel["selector"], "instance_path"), (channel["signal_source"], "instance_path")):
                if not record[key].startswith(before + "/"):
                    raise _error("MMC_POSTCONDITION_FAILED", "A channel is outside the expected document root.")
                record[key] = after + record[key][len(before):]
        result["reachable_instances"] = observed
    result["readback"] = verify_fault_instrumentation(project, result)
    result["instrumented_project_sha256"] = result["readback"]["project_sha256"]
    result["vendor_finalized"] = True
    return result


def materialize_voltage_control_headroom(source: str | Path, destination: str | Path, *, current_limit_pu: float = 1.05) -> dict[str, Any]:
    """Repair the voltage-controller current and antiwindup reference together.

    This bounded adjustment retains the installed 3 kA arm protection. It is
    specific to the audited 1000 MVA, 370 kV converter with a 900 MW setpoint.
    """

    original = _regular(source)
    target = Path(destination).expanduser().resolve()
    if target == original or target.exists() or target.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "A control repair requires a new derived copy.")
    if isinstance(current_limit_pu, bool) or not isinstance(current_limit_pu, (int, float)) or not 1.0 < current_limit_pu <= 1.1:
        raise _error("MMC_TEMPLATE_NATIVE_BINDING_INVALID", "The audited current headroom range is above 1.0 and at most 1.1 pu.")
    before_hash = _sha256(original)
    root = ET.parse(original).getroot()
    definitions = {item.get("name"): item for item in root.findall("./definitions/Definition")}
    main = definitions.get("Main")
    controller = definitions.get("VSCControl2")
    if main is None or controller is None:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The audited converter control graph is absent.")
    voltage_converters = [item for item in _components(main) if item.get("defn", "").endswith(":VSCConverter") and dict(_parameters(item)).get("dmode") == "0"]
    if len(voltage_converters) != 1:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "There must be exactly one DC-voltage controller.")
    voltage_converter = voltage_converters[0]
    values = dict(_parameters(voltage_converter))
    scalar = lambda value: float(re.match(r"[+-]?[\d.]+", value.strip()).group())
    if scalar(values.get("Sbase", "0")) != 1000 or scalar(values.get("Vtr_2", "0")) != 370 or scalar(values.get("Imax", "0")) != 1:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The headroom repair requires the audited original current base and limit.")
    for instance in _components(main):
        if instance.get("defn", "").endswith(":MMC_Hb_PWM") and scalar(dict(_parameters(instance)).get("IvlMax", "0")) != 3:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The original 3 kA arm protection must remain present.")
    limit = next(item for item in voltage_converter.findall("./paramlist/param") if item.get("name") == "Imax")
    limit.set("value", format(current_limit_pu, ".15g"))
    threshold = next((item for item in _components(controller) if item.get("id") == "278203269"), None)
    if threshold is None or threshold.get("defn") != "master:const" or dict(_parameters(threshold)).get("Value") != "0.99999" or threshold.get("orient") != "0":
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The audited antiwindup constant is absent or differs.")
    threshold.set("defn", "master:gain")
    threshold.set("name", "master:gain")
    params = threshold.find("paramlist")
    for item in list(params):
        params.remove(item)
    for key, value in (("G", "0.99999"), ("Dim", "1")):
        ET.SubElement(params, "param", {"name": key, "value": value})
    used = {item.get("id") for item in root.iter()}
    def next_id():
        value = 2050000001
        while str(value) in used:
            value += 1
        used.add(str(value))
        return str(value)
    x, y = int(threshold.get("x")), int(threshold.get("y"))
    canvas = controller.find("schematic")
    imported = ET.SubElement(canvas, "User", {"classid": "UserCmp", "defn": "master:import", "id": next_id(), "x": str(x - 108), "y": str(y), "orient": "0", "w": "80", "h": "22", "z": "715", "link": "-1", "q": "4"})
    params = ET.SubElement(imported, "paramlist", {"name": "", "link": "-1"})
    ET.SubElement(params, "param", {"name": "Name", "value": "Imax"})
    wire = ET.SubElement(canvas, "Wire", {"classid": "WireOrthogonal", "id": next_id(), "name": "", "x": str(x - 72), "y": str(y), "orient": "0", "w": "46", "h": "10"})
    ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
    ET.SubElement(wire, "vertex", {"x": "36", "y": "0"})
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=False)
    if _sha256(original) != before_hash:
        raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "The control repair source changed while reading.")
    base = 1000 / (math.sqrt(3) * 370)
    return {"source": str(original), "source_sha256": before_hash, "destination": str(target), "destination_sha256": _sha256(target), "voltage_controller_owner": voltage_converter.get("id"), "parameter": "Imax", "before_pu": 1.0, "after_pu": current_limit_pu, "freeze_reference": "0.99999 * Imax", "freeze_reference_owner": threshold.get("id"), "phase_current_base_rms_ka": base, "phase_current_rms_ka": base * current_limit_pu, "phase_current_peak_ka": base * math.sqrt(2) * current_limit_pu, "arm_protection_limit_ka": 3.0}


__all__ = ["REQUIRED_ROLES", "instrument_fault_channels", "reachable_instances", "read_fault_output_dataset", "snapshot_output_dataset", "verify_fault_instrumentation", "verify_output_dataset"]
