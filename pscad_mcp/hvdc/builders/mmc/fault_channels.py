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


def default_fault_checks() -> dict[str, Any]:
    """Return the frozen 640 kV/900 MW native full-bridge engineering contract."""

    return {
        "schema_version": 1, "time_basis": "EMTDC", "time_units": "s",
        "time_step_s": 25e-6, "simulation_duration_s": 5.0,
        "output_step_s": 250e-6, "max_timing_error_s": 500e-6,
        "frequency_hz": 60.0, "arm_rms_stability_relative_tolerance": 0.05,
        "nominal_target_relative_tolerance": 0.05, "arm_peak_limit_ka": 3.0,
        "maximum_power_loss_fraction": 0.1,
        "modulation_abs_limit": 2.0,
        "require_modulation_evidence": True,
        "fault_window_s": [2.5, 2.7], "prefault_window_s": [2.0, 2.4], "recovery_window_s": [4.6, 5.0],
        "negative_voltage_max_kv": -1.0, "fault_current_limit_ka": 20.0,
        "voltage_recovery_relative_tolerance": 0.05, "power_recovery_relative_tolerance": 0.05,
        "arm_rms_recovery_relative_tolerance": 0.1, "capacitor_recovery_relative_tolerance": 0.05,
        "steady_relative_rms_tolerance": 0.05, "minimum_operating_fraction": 0.9, "arm_rms_floor_ka": 0.05,
        "basis": "Native full-bridge engineering contract: 640 kV, T2 -900 MW, T1 supplies power plus measured losses; complete 60 Hz cycle windows; original 20 kA fault and 3 kA arm limits retained.",
    }


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", "mmc_fault_channels", details)


def _regular(path: str | Path) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "Evidence must be a regular file.", path=str(raw))
    return raw.resolve()


def _new_target(destination: str | Path, sources: tuple[Path, ...] = ()) -> Path:
    raw = Path(destination).expanduser()
    if raw.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "A derived destination must not be a symbolic link.", destination=str(raw))
    target = raw.resolve()
    if target in sources or target.exists() or target.is_symlink():
        raise _error("MMC_BUILD_CONFLICT", "A derived destination must be a new file.", destination=str(target))
    return target


def _write_new_xml(root: ET.Element, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=False)
    except FileExistsError as error:
        raise _error("MMC_BUILD_CONFLICT", "Another owner created the derived destination.", destination=str(target)) from error


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


def _compiled_scope_path(project_root: ET.Element, instance_path: str) -> str:
    definitions = {item.get("name"): item for item in project_root.findall("./definitions/Definition")}
    previous: ET.Element | None = None
    result = []
    for index, segment in enumerate(instance_path.split("/")):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", segment)
        if match is None:
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "A measured instance path is invalid.", instance_path=instance_path)
        name, owner = match.groups()
        instance_name = "0"
        if index == 0 and name == "Station":
            previous = definitions.get(name)
            continue
        if previous is not None:
            matches = [item for item in _components(previous) if item.get("id") == owner and item.get("defn", "").rsplit(":", 1)[-1] == name]
            if len(matches) != 1:
                raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The compiler path has no unique saved instance owner.", instance_path=instance_path, owner=owner)
            instance_name = dict(_parameters(matches[0])).get("Name") or "0"
        result.append(name + "(" + instance_name + ")")
        previous = definitions.get(name)
        if previous is None:
            raise _error("MMC_OUTPUT_IDENTITY_CHANGED", "The measured hierarchy refers to an unknown definition.", definition=name)
    return "\\".join(result)


async def read_fault_output_dataset(reader: Any, primary: str | Path, channel_contract: Mapping[str, Any], *, started_after: float | None = None) -> dict[str, Any]:
    """Use the existing output reader per exact selector, retaining file identity."""

    project_readback = verify_fault_instrumentation(channel_contract["project_path"], channel_contract)
    project_root = ET.parse(channel_contract["project_path"]).getroot()
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
        expected_instance = _compiled_scope_path(project_root, binding["instance_path"]) + ":" + selected["description"]
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
    target = _new_target(destination, tuple(paths.values()))
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
    expose(observed_cell, "MmcCapMin", "Dsout", "MINVAL($Vc)", "REAL")
    expose(observed_cell, "MmcCapMax", "Dsout", "MAXVAL($Vc)", "REAL")
    capacitance = [item for item in observed_cell.findall("./form/category/parameter") if item.get("name") == "C"]
    if len(capacitance) != 1 or capacitance[0].get("unit") != "uF":
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The actual cell capacitance unit must be audited before computing energy.")
    expose(observed_cell, "MmcCapEnergy", "Dsout", "0.5e-6*$C*SUM($Vc**2)", "REAL")
    expose(observed_cell, "MmcEquivalentSource", "Dsdyn", "RVD1_5", "REAL")
    expose(observed_cell, "MmcChargePower", "Dsdyn", "SUM($Vc*$Ic)", "REAL")
    expose(observed_cell, "MmcChargeCurrent", "Dsdyn", "SUM($Ic)", "REAL")
    expose(observed_cell, "MmcBalanceDrive", "Dsdyn", "SUM($Vc*$Ic)-SUM($Vc)*SUM($Ic)/REAL($DimC)", "REAL")
    expose(observed_cell, "MmcBlocked", "Dsdyn", "IVD1_1", "INTEGER")
    observed_fault = clone_definition(masters["fault_sw"], "MmcObservedFaultSwitch")
    expose(observed_fault, "MmcClosed", "Dsout", "1-E_BtoI(OPENBR($NBR,$SS))", "INTEGER")
    if "sorter" not in vendor:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The installed cell-index sorter is missing.")
    actual_sorters = [item for item in _components(definitions["MMC_Hb_Pole_PWM"]) if item.get("id") in {"607330449", "1348249230"}]
    actual_sort_definitions = {item.get("defn") for item in actual_sorters}
    if len(actual_sorters) != 2 or len(actual_sort_definitions) != 1:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The actual arm sorting recipe is missing, ambiguous or mixed.")
    actual_sort_definition = next(iter(actual_sort_definitions))
    if actual_sort_definition == "intermediate:sorter":
        sorter_source, sort_extent = vendor["sorter"], "NS"
    elif actual_sort_definition == namespace + ":MmcCompleteArmSorter" and "MmcCompleteArmSorter" in definitions:
        sorter_source, sort_extent = definitions["MmcCompleteArmSorter"], "Dim"
    else:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The actual arm sorter definition is not audited.", definition=actual_sort_definition)
    observed_sorter = clone_definition(sorter_source, "MmcObservedSorter")
    sorting = next(item for item in observed_sorter.findall("./script/segment") if item.get("name") == "Fortran")
    if f"CALL E_SORTER($Dim,${sort_extent},$Enab,$order2,$IN,$OUT)" not in (sorting.text or ""):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The installed sorter call contract differs.")
    sorting.text = (sorting.text or "").rstrip() + """
#LOCAL INTEGER MFEINV
#LOCAL INTEGER MFERANGE
#LOCAL INTEGER MFEI
#LOCAL INTEGER MFEJ
#LOCAL INTEGER MFEK
#LOCAL INTEGER MFEAPPLIC
#LOCAL REAL MFEPGAP
#LOCAL REAL MFESGAP
#LOCAL REAL MFESMIN
#LOCAL REAL MFEOMAX
#LOCAL REAL MFESMAX
#LOCAL REAL MFEOMIN
      MFEINV = 0
      MFERANGE = 0
      DO MFEI=1,$Dim
        MFEJ = $OUT(MFEI)
        IF ((MFEJ.LT.1).OR.(MFEJ.GT.$Dim)) THEN
          MFERANGE = MFERANGE + 1
        ELSEIF (MFEI.GT.1) THEN
          MFEJ = $OUT(MFEI-1)
          IF ((MFEJ.GE.1).AND.(MFEJ.LE.$Dim)) THEN
            IF ($IN($OUT(MFEI)).LT.$IN(MFEJ)) MFEINV=MFEINV+1
          ENDIF
        ENDIF
      ENDDO
      MFEPGAP = 0.0
      MFESGAP = 0.0
      MFEAPPLIC = 0
      MFEK = MIN($Dim,ABS($NS))
      IF ((MFERANGE.EQ.0).AND.(MFEK.GT.0).AND.(MFEK.LT.$Dim)) THEN
        MFEAPPLIC = 1
        MFESMAX = $IN($OUT(1))
        MFEOMIN = $IN($OUT(MFEK+1))
        MFESMIN = $IN($OUT($Dim-MFEK+1))
        MFEOMAX = $IN($OUT(1))
        DO MFEI=1,$Dim
          IF (MFEI.LE.MFEK) THEN
            MFESMAX = MAX(MFESMAX,$IN($OUT(MFEI)))
          ELSE
            MFEOMIN = MIN(MFEOMIN,$IN($OUT(MFEI)))
          ENDIF
          IF (MFEI.GT.($Dim-MFEK)) THEN
            MFESMIN = MIN(MFESMIN,$IN($OUT(MFEI)))
          ELSE
            MFEOMAX = MAX(MFEOMAX,$IN($OUT(MFEI)))
          ENDIF
        ENDDO
        MFEPGAP = MFESMAX - MFEOMIN
        MFESGAP = MFEOMAX - MFESMIN
      ENDIF
"""
    expose(observed_sorter, "MmcSortInvalid", "Fortran", "MFERANGE", "INTEGER")
    expose(observed_sorter, "MmcSortInversions", "Fortran", "MFEINV", "INTEGER")
    expose(observed_sorter, "MmcSortCount", "Fortran", "$NS", "INTEGER")
    expose(observed_sorter, "MmcSortExtent", "Fortran", "$" + sort_extent, "INTEGER")
    expose(observed_sorter, "MmcSortEnable", "Fortran", "$Enab", "INTEGER")
    expose(observed_sorter, "MmcSortPrefixGap", "Fortran", "MFEPGAP", "REAL")
    expose(observed_sorter, "MmcSortSuffixGap", "Fortran", "MFESGAP", "REAL")
    expose(observed_sorter, "MmcSortApplicable", "Fortran", "MFEAPPLIC", "INTEGER")
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

    def add_node_probe(definition: ET.Element, role: str, scope: str, signal: str, owner: str, x: int, y: int, units: str, quantity: str) -> None:
        sources = [item for item in _components(definition) if item.get("id") == owner]
        if len(sources) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A voltage-base diagnostic owner is not unique.", owner=owner)
        canvas = definition.find("schematic")
        matching_wires = [item for item in canvas.findall("Wire") if any(int(item.get("x", "0")) + int(vertex.get("x", "0")) == x and int(item.get("y", "0")) + int(vertex.get("y", "0")) == y for vertex in item.findall("vertex"))]
        if not matching_wires:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A voltage-base diagnostic node has no audited wire.", owner=owner, x=x, y=y)
        alias = ET.SubElement(canvas, "User", {"classid": "UserCmp", "defn": "master:datalabel", "id": allocate(scope + ":" + signal + ":node"), "x": str(x), "y": str(y), "orient": "0", "w": "72", "h": "22", "z": "1", "link": "-1", "q": "4"})
        set_param(alias, "Name", signal)
        probes.append(component_record(definition, alias))
        for wire in matching_wires:
            wires.append({"definition_name": definition.get("name"), "owner_id": wire.get("id"), "attributes": {key: wire.get(key) for key in ("classid", "x", "y", "orient")}, "vertices": [dict(item.attrib) for item in wire.findall("vertex")]})
        add_probe(definition, role, scope, signal, sources[0], kind="control_quantity", units_override=units, extra={"quantity": quantity, "node": {"x": x, "y": y}})

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
        local_dc = [item for item in _components(pwm) if item.get("id") == "2025177284" and item.get("defn") == "master:voltmeter" and dict(_parameters(item)).get("Name") == "Edc"]
        if len(local_dc) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The converter-side pole-to-pole voltmeter is missing.")
        add_probe(pwm, "v_dc_converter", terminal, "Edc", local_dc[0], source_parameter="Name", units_override="kV", extra={"quantity": "converter_side_dc_pole_to_pole_voltage", "not_an_acceptance_voltage": True})
        poles = [item for item in _components(pwm) if item.get("defn", "").endswith(":MMC_Hb_Pole_PWM")]
        if len(poles) != 3:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The converter must expose three phase poles.", terminal=terminal)
        for phase, pole in zip(("A", "B", "C"), sorted(poles, key=lambda item: int(item.get("x", "0")))):
            pole_name = f"MFE_Pole_{terminal}_{phase}"
            pole_definition = clone_definition(definitions["MMC_Hb_Pole_PWM"], pole_name)
            pole.set("defn", namespace + ":" + pole_name)
            for signal, owner, role, quantity in (("Vref", "1233804117", "phase_ac_reference", "phase_ac_voltage_reference_after_dc_normalization_and_clamp"), ("Vz", "1642798056", "phase_common_reference", "original_ccsc_common_voltage_reference")):
                sources = [item for item in _components(pole_definition) if item.get("id") == owner and dict(_parameters(item)).get("Name") == signal]
                if len(sources) != 1:
                    raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A phase-voltage diagnostic source is missing.", signal=signal)
                add_probe(pole_definition, role, f"{terminal}/{phase}", signal, sources[0], kind="control_quantity", units_override="pu", extra={"quantity": quantity})
            add_node_probe(pole_definition, "arm_deblocking_ramp", f"{terminal}/{phase}", "MmcDeblockingRamp", "263038724", 2304, 468, "pu", "deblocking_ramp_before_arm_voltage_sum")
            for arm, owner in (("upper", "607330449"), ("lower", "1348249230")):
                sorters = [item for item in _components(pole_definition) if item.get("id") == owner and item.get("defn") == actual_sort_definition]
                if len(sorters) != 1 or dict(_parameters(sorters[0])).get("order") != "0":
                    raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The audited ascending arm sorter differs.", owner=owner)
                sorter = sorters[0]
                sorter.set("defn", namespace + ":MmcObservedSorter")
                for parameter, role, quantity in (("MmcSortInvalid", "sort_index_invalid", "indices_outside_one_based_voltage_array_bounds"), ("MmcSortInversions", "sort_index_inversions", "adjacent_ascending_inversions_in_same_step_sort_input"), ("MmcSortCount", "sort_requested_count", "component_requested_count"), ("MmcSortExtent", "sort_extent", "actual_E_SORTER_NS_argument"), ("MmcSortEnable", "sort_enable", "actual_Enab_argument"), ("MmcSortPrefixGap", "sort_prefix_gap", "max_selected_prefix_minus_min_unselected"), ("MmcSortSuffixGap", "sort_suffix_gap", "max_unselected_minus_min_selected_suffix"), ("MmcSortApplicable", "sort_boundary_applicable", "valid_indices_and_nontrivial_requested_subset")):
                    signal = parameter + ("Top" if arm == "upper" else "Btm")
                    set_param(sorter, parameter, signal)
                    add_probe(pole_definition, role, f"{terminal}/{phase}/{arm}", signal, sorter, kind="control_quantity", source_parameter=parameter, units_override="kV" if role.endswith("_gap") else "1", extra={"quantity": quantity, "sort_extent": sort_extent, "index_base": 1, "timing": "immediately_after_E_SORTER_before_HBridge_Ctrl1", "voltage_array": "actual_one_step_delayed_VcT_or_VcB", "full_order_not_assumed": True, "gap_valid_when": "indices_in_1_to_Dim_and_0_lt_requested_count_lt_Dim", "positive_gap_means_wrong_extreme_set": role.endswith("_gap")})
            if any(dict(_parameters(item)).get("Name") == "MmcVzEffective" for item in _components(pole_definition)):
                for wire in pole_definition.findall("./schematic/Wire"):
                    wires.append({"definition_name": pole_name, "owner_id": wire.get("id"), "attributes": {key: wire.get(key) for key in ("classid", "x", "y", "orient")}, "vertices": [dict(item.attrib) for item in wire.findall("vertex")]})
                for signal, role, units, quantity in (
                    ("MmcIcircRaw", "circulating_current_raw", "kA", "half_sum_of_measured_arm_currents"),
                    ("MmcIcircHighpass", "circulating_current_highpass", "kA", "local_highpass_circulating_current"),
                    ("Vz", "circulating_voltage_raw", "pu", "original_ccsc_common_voltage_reference"),
                    ("MmcVzEffective", "circulating_voltage_effective", "pu", "common_voltage_reference_with_virtual_resistance"),
                ):
                    sources = [item for item in _components(pole_definition) if item.get("defn") in ("master:datalabel", "master:import") and dict(_parameters(item)).get("Name") == signal]
                    if not sources:
                        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A virtual-resistance diagnostic source is missing.", signal=signal)
                    add_probe(pole_definition, role, f"{terminal}/{phase}", signal, sources[0], units_override=units, extra={"quantity": quantity})
            for arm, signal in (("upper", "VrefT"), ("lower", "VrefB")):
                labels = [item for item in _components(pole_definition) if item.get("defn") == "master:datalabel" and dict(_parameters(item)).get("Name") == signal]
                if labels:
                    add_probe(pole_definition, "modulation_request", f"{terminal}/{phase}/{arm}", signal, labels[0], units_override="pu", extra={"quantity": "signed_arm_voltage_request", "requested_voltage_equation": "0.5*Vref*sum(Vc)", "carrier_range": [0.0, 2.0], "physical_cell_count_bounded": True})
                else:
                    raise _error("MMC_ACCEPTANCE_INCOMPLETE", "Every arm requires its actual signed modulation request.", scope=f"{terminal}/{phase}/{arm}", signal=signal)
            cells = [item for item in _components(pole_definition) if item.get("defn") == "intermediate:FullCellR_n"]
            if len(cells) != 2 or any(dict(_parameters(item)).get("DTBP") != "0" for item in cells):
                raise _error("MMC_ACCEPTANCE_INCOMPLETE", "Every pole must contain two unconditional full-bridge cell groups.")
            for arm, instance in zip(("upper", "lower"), sorted(cells, key=lambda item: int(item.get("y", "0")))):
                instance.set("defn", namespace + ":MmcObservedFullCell")
                arm_suffix = "Top" if arm == "upper" else "Btm"
                scope = f"{terminal}/{phase}/{arm}"
                for parameter, signal in (("MmcInserted", f"MmcV{arm_suffix}"), ("MmcCapSum", f"MmcVc{arm_suffix}"), ("MmcCapMin", f"MmcVcMin{arm_suffix}"), ("MmcCapMax", f"MmcVcMax{arm_suffix}"), ("MmcCapEnergy", f"MmcEnergy{arm_suffix}"), ("MmcEquivalentSource", f"MmcEquivalent{arm_suffix}"), ("MmcChargePower", f"MmcChargePower{arm_suffix}"), ("MmcChargeCurrent", f"MmcChargeCurrent{arm_suffix}"), ("MmcBalanceDrive", f"MmcBalanceDrive{arm_suffix}"), ("MmcBlocked", f"MmcBlock{arm_suffix}")):
                    set_param(instance, parameter, signal)
                add_probe(pole_definition, "v_inserted", scope, f"MmcV{arm_suffix}", instance, source_parameter="MmcInserted", extra={"quantity": "cell_group_terminal_voltage", "positive_port": "Ntop", "negative_port": "Nbtm", "condition": {"DTBP": "0"}})
                add_probe(pole_definition, "v_cap", scope, f"MmcVc{arm_suffix}", instance, source_parameter="MmcCapSum", nominal=640.0, extra={"quantity": "sum_of_submodule_capacitor_voltages", "expression": "SUM(Vc)", "cell_count_expression": dict(_parameters(instance))["DimC"]})
                add_probe(pole_definition, "v_cap_minimum", scope, f"MmcVcMin{arm_suffix}", instance, source_parameter="MmcCapMin", units_override="kV", extra={"quantity": "single_submodule_voltage_extremum", "expression": "MINVAL(Vc)", "cell_count_expression": dict(_parameters(instance))["DimC"]})
                add_probe(pole_definition, "v_cap_maximum", scope, f"MmcVcMax{arm_suffix}", instance, source_parameter="MmcCapMax", units_override="kV", extra={"quantity": "single_submodule_voltage_extremum", "expression": "MAXVAL(Vc)", "cell_count_expression": dict(_parameters(instance))["DimC"]})
                add_probe(pole_definition, "arm_capacitor_energy", scope, f"MmcEnergy{arm_suffix}", instance, source_parameter="MmcCapEnergy", units_override="MJ", extra={"quantity": "sum_of_actual_submodule_capacitor_energies", "expression": "0.5*C_uF*1e-6*SUM(Vc_kV**2)", "capacitance_expression": dict(_parameters(instance))["C"], "capacitance_unit": "uF", "unit_derivation": "F*kV**2=MJ"})
                add_probe(pole_definition, "cell_equivalent_source_voltage", scope, f"MmcEquivalent{arm_suffix}", instance, source_parameter="MmcEquivalentSource", units_override="kV", extra={"quantity": "vendor_cell_group_equivalent_source_voltage", "expression": "FULLCELL1_EXE RVD1_5", "branch_equation": "EBRD(BRx)=-RVD1_5", "not_a_direct_selected_cell_sum": True})
                add_probe(pole_definition, "capacitor_charge_power", scope, f"MmcChargePower{arm_suffix}", instance, source_parameter="MmcChargePower", units_override="MW", extra={"quantity": "sum_of_same_step_capacitor_voltage_current_products", "expression": "SUM(Vc*Ic)", "timing": "immediately_after_FULLCELL1_EXE", "unit_derivation": "kV*kA=MW"})
                add_probe(pole_definition, "capacitor_current_sum", scope, f"MmcChargeCurrent{arm_suffix}", instance, source_parameter="MmcChargeCurrent", units_override="kA", extra={"quantity": "sum_of_same_step_capacitor_currents", "expression": "SUM(Ic)", "timing": "immediately_after_FULLCELL1_EXE"})
                add_probe(pole_definition, "capacitor_balance_drive", scope, f"MmcBalanceDrive{arm_suffix}", instance, source_parameter="MmcBalanceDrive", units_override="MW", extra={"quantity": "same_step_capacitor_voltage_current_covariance_sum", "expression": "SUM(Vc*Ic)-SUM(Vc)*SUM(Ic)/DimC", "timing": "immediately_after_FULLCELL1_EXE", "positive_increases_within_arm_voltage_variance": True})
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
        channels[-1]["nominal_role"] = "power_balance_input" if terminal == "T1" else "controlled_active_power"
        dc_meters = [item for item in _components(main) if item.get("defn") == "master:ammeter" and dict(_parameters(item)).get("Name") == "Idc" + number]
        if len(dc_meters) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The physical station DC current meter is missing.")
        add_probe(main, "i_dc_station", terminal, "Idc" + number, dc_meters[0], source_parameter="Name", units_override="kA", extra={"quantity": "station_dc_current", "direction": "original_meter_arrow"})
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
        add_node_probe(control_definition, "controller_ac_magnitude_kv", terminal, "MmcAcMagnitudeKv", "736319288", 3204, 2034, "kV", "phase_voltage_command_magnitude_before_dc_normalization")
        add_node_probe(control_definition, "controller_ac_magnitude_preclamp", terminal, "MmcAcMagnitudePreclamp", "235800143", 3204, 1944, "pu", "phase_voltage_command_magnitude_before_1p5_clamp")
        probes.extend(component_record(control_definition, item) for item in _components(control_definition))
        for wire in control_definition.findall("./schematic/Wire"):
            wires.append({"definition_name": control_name, "owner_id": wire.get("id"), "attributes": {key: wire.get(key) for key in ("classid", "x", "y", "orient")}, "vertices": [dict(item.attrib) for item in wire.findall("vertex")]})
        freeze_source = next(item for item in _components(control_definition) if item.get("id") == "1356454688")
        magnitude_source = next(item for item in _components(control_definition) if item.get("id") == "1359229547")
        add_probe(control_definition, "controller_freeze", terminal, "FrzI", freeze_source, kind="physical_state", polarity={"inactive": 0, "active": 1}, extra={"quantity": "actual_current_limit_antiwindup_freeze"})
        add_probe(control_definition, "controller_current_magnitude", terminal, "Imag", magnitude_source, units_override="pu", extra={"quantity": "dq_current_reference_magnitude", "base": "sqrt(2)*Sbase/(sqrt(3)*Vtr_2)"})
        filters = [item for item in _components(control_definition) if item.get("defn") == "master:realpole" and dict(_parameters(item)).get("COM") == "MMC DC feedback only"]
        if filters:
            if len(filters) != 1:
                raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The DC feedback filter is not unique.")
            add_probe(control_definition, "controller_dc_voltage_filtered", terminal, "MmcFilteredVdcPu", filters[0], units_override="pu", extra={"quantity": "outer_loop_filtered_dc_voltage", "time_constant_s": 0.005, "not_an_acceptance_voltage": True})
        for signal, role, quantity in (
            ("MmcDcDamping", "controller_dc_damping", "highpass_d_axis_current_reference_correction"),
            ("MmcIdBeforeLimit", "controller_id_before_limit", "selected_d_axis_current_reference_before_total_limit"),
            ("idref", "controller_id_after_limit", "d_axis_current_reference_after_total_limit"),
        ):
            labels = [item for item in _components(control_definition) if item.get("defn") == "master:datalabel" and dict(_parameters(item)).get("Name") == signal]
            if labels:
                source_label = next((item for item in labels if item.get("id") == "1877948868"), labels[0])
                add_probe(control_definition, role, terminal, signal, source_label, kind="physical_state", units_override="pu", extra={"quantity": quantity})
        actual_id = [item for item in _components(control_definition) if item.get("defn") == "master:pgb" and dict(_parameters(item)).get("Name") == "id"]
        if len(actual_id) == 1:
            add_probe(control_definition, "controller_id_actual", terminal, "idpu", actual_id[0], units_override="pu", extra={"quantity": "measured_d_axis_current", "normalization": "Ibase2_pk"})
        add_probe(main, "recovery_enable", terminal, f"Dblk{number}P", controls[0], kind="recovery_control", source_parameter="Dblk", polarity={"inactive": 0, "active": 1}, extra={"quantity": "deblocking_enable", "electrical_recovery_required": True})

    for name, definition in definitions.items():
        if name.startswith("MFE_Pole_") and any(dict(_parameters(item)).get("Name") == "MmcVzEffective" for item in _components(definition)):
            probes.extend(component_record(definition, item) for item in _components(definition))

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
    _write_new_xml(root, target)
    contract = {"schema_version": 1, "source_hashes": {name: {"path": str(paths[name]), "sha256": hashes[name]} for name in paths}, "project_path": str(target), "channels": channels, "readback_components": probes, "readback_wires": wires, "readback_ports": {name: _ports(definition) for name, definition in definitions.items() if name.startswith(("MFE_", "MmcObserved"))}, "readback_scripts": {item.get("name"): _script_hash(item) for item in (observed_cell, observed_fault, observed_sorter)}, "instrumented_project_sha256": _sha256(target), "reachable_instances": reachable}
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
    scope_components = {}
    scope_wires = {}
    for name, definition in definitions.items():
        by_id: dict[str, list[ET.Element]] = {}
        for item in _components(definition):
            by_id.setdefault(item.get("id"), []).append(item)
        scope_components[name] = by_id
        by_wire_id: dict[str, list[ET.Element]] = {}
        for item in definition.findall("./schematic/Wire"):
            by_wire_id.setdefault(item.get("id"), []).append(item)
        scope_wires[name] = by_wire_id
    for expected in contract.get("readback_components", []):
        matches = scope_components.get(expected["definition_name"], {}).get(expected["owner_id"], [])
        if len(matches) != 1 or matches[0].get("defn") != expected["definition"] or any(dict(_parameters(matches[0])).get(key) != value for key, value in expected["parameters"].items()) or any(matches[0].get(key) != value for key, value in expected["position"].items()):
            raise _error("MMC_POSTCONDITION_FAILED", "A measured source, label or output changed after saving.", expected=expected)
    for name, digest in contract.get("readback_scripts", {}).items():
        if name not in definitions or _script_hash(definitions[name]) != digest:
            raise _error("MMC_POSTCONDITION_FAILED", "A physical measurement implementation changed after saving.", definition=name)
    for name, ports in contract.get("readback_ports", {}).items():
        if name not in definitions or _ports(definitions[name]) != ports:
            raise _error("MMC_POSTCONDITION_FAILED", "A measurement port or its activation condition changed.", definition=name)
    for wire in contract.get("readback_wires", []):
        matches = scope_wires.get(wire["definition_name"], {}).get(wire["owner_id"], [])
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
    target = _new_target(destination, (original,))
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
    def quantity(raw: str, definition_name: str, parameter: str, target_unit: str) -> float:
        form = definitions.get(definition_name)
        declarations = [item for item in form.findall("./form/category/parameter") if item.get("name") == parameter] if form is not None else []
        if len(declarations) != 1 or declarations[0].get("unit") != target_unit:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The current-base form unit differs from the audited contract.", definition=definition_name, parameter=parameter)
        match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*(?:\[([A-Za-z0-9]+)\])?\s*", raw)
        conversions = {"kV": {"kV": 1.0, "V": 0.001}, "MVA": {"MVA": 1.0, "kVA": 0.001, "VA": 1e-6}, "kA": {"kA": 1.0, "A": 0.001}, "pu": {"pu": 1.0, "1": 1.0}}
        if match is None or (unit := match.group(2) or target_unit) not in conversions[target_unit]:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The current-base value is not an unambiguous unit-qualified literal.", parameter=parameter, value=raw)
        result = float(match.group(1)) * conversions[target_unit][unit]
        if not math.isfinite(result):
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The current-base value must be finite.", parameter=parameter)
        return result
    if quantity(values.get("Sbase", ""), "VSCConverter", "Sbase", "MVA") != 1000 or quantity(values.get("Vtr_2", ""), "VSCConverter", "Vtr_2", "kV") != 370 or quantity(values.get("Imax", ""), "VSCConverter", "Imax", "pu") != 1:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The headroom repair requires the audited original current base and limit.")
    for instance in _components(main):
        if instance.get("defn", "").endswith(":MMC_Hb_PWM") and quantity(dict(_parameters(instance)).get("IvlMax", ""), "MMC_Hb_PWM", "IvlMax", "kA") != 3:
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
    _write_new_xml(root, target)
    if _sha256(original) != before_hash:
        raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "The control repair source changed while reading.")
    base = 1000 / (math.sqrt(3) * 370)
    return {"source": str(original), "source_sha256": before_hash, "destination": str(target), "destination_sha256": _sha256(target), "voltage_controller_owner": voltage_converter.get("id"), "parameter": "Imax", "before_pu": 1.0, "after_pu": current_limit_pu, "freeze_reference": "0.99999 * Imax", "freeze_reference_owner": threshold.get("id"), "phase_current_base_rms_ka": base, "phase_current_rms_ka": base * current_limit_pu, "phase_current_peak_ka": base * math.sqrt(2) * current_limit_pu, "arm_protection_limit_ka": 3.0}


def materialize_complete_arm_sorting(source: str | Path, destination: str | Path, *, library: str | Path) -> dict[str, Any]:
    """Order both selectable extremes when the existing sort event refreshes."""

    original, library_path = _regular(source), _regular(library)
    target = _new_target(destination, (original, library_path))
    source_hash, library_hash = _sha256(original), _sha256(library_path)
    root = ET.parse(original).getroot()
    vendor = ET.parse(library_path).getroot()
    pole = root.find("./definitions/Definition[@name='MMC_Hb_Pole_PWM']")
    sorter = vendor.find("./definitions/Definition[@name='sorter']")
    definitions = root.find("definitions")
    if pole is None or sorter is None or definitions is None or definitions.find("Definition[@name='MmcCompleteArmSorter']") is not None:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The original arm sorter scope is absent or already specialized.")
    calls = [item for item in _components(pole) if item.get("defn") == "intermediate:sorter"]
    if len(calls) != 2 or {item.get("id") for item in calls} != {"607330449", "1348249230"} or any(dict(_parameters(item)).get("order") != "0" for item in calls):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The audited ascending sorter instances differ.")
    clone = copy.deepcopy(sorter)
    clone.set("name", "MmcCompleteArmSorter")
    clone.set("instances", "0")
    used = {item.get("id") for item in root.iter()}
    owner = 2026000001
    while str(owner) in used:
        owner += 1
    clone.set("id", str(owner))
    segment = next(item for item in clone.findall("./script/segment") if item.get("name") == "Fortran")
    old_call = "CALL E_SORTER($Dim,$NS,$Enab,$order2,$IN,$OUT)"
    new_call = "CALL E_SORTER($Dim,$Dim,$Enab,$order2,$IN,$OUT)"
    if (segment.text or "").count(old_call) != 1:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The installed sorting routine call is not the audited source.")
    segment.text = segment.text.replace(old_call, new_call)
    definitions.append(clone)
    for instance in calls:
        instance.set("defn", root.get("name") + ":MmcCompleteArmSorter")
    _write_new_xml(root, target)
    if _sha256(original) != source_hash or _sha256(library_path) != library_hash:
        raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "A complete-sorting input changed.")
    return {"source": str(original), "source_sha256": source_hash, "library": str(library_path), "library_sha256": library_hash, "destination": str(target), "destination_sha256": _sha256(target), "definition": "MmcCompleteArmSorter", "sort_extent": "Dim", "requested_count_unchanged": True, "enable_unchanged": True, "current_and_firing_unchanged": True, "before_call": old_call, "after_call": new_call, "held_steps_not_resorted": True}


def materialize_terminal_two_charging(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Bind the T2 charging transition to its existing independent setting."""

    original = _regular(source)
    target = _new_target(destination, (original,))
    source_hash = _sha256(original)
    root = ET.parse(original).getroot()
    main = root.find("./definitions/Definition[@name='Main']")
    if main is None:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The original Main charging scope is missing.")
    owners = {item.get("id"): item for item in _components(main)}
    for owner, definition, parameter, value in (("584272924", "master:bin_delay", "T", "Tcharging1"), ("606940312", "master:bin_delay", "T", "Tcharging1"), ("2129272491", "master:datalabel", "Name", "Tcharging2")):
        component = owners.get(owner)
        if component is None or component.get("defn") != definition or dict(_parameters(component)).get(parameter) != value:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The audited charging-delay source differs.", owner=owner)
    delay = owners["606940312"]
    next(item for item in delay.findall("./paramlist/param") if item.get("name") == "T").set("value", "Tcharging2")
    _write_new_xml(root, target)
    if _sha256(original) != source_hash:
        raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "The charging-delay source changed.")
    return {"source": str(original), "source_sha256": source_hash, "destination": str(target), "destination_sha256": _sha256(target), "definition": "Main", "owner": "606940312", "parameter": "T", "before": "Tcharging1", "after": "Tcharging2", "terminal_one_unchanged": True}


def materialize_dc_feedback_filter(source: str | Path, destination: str | Path, *, master: str | Path, time_constant_s: float = 0.005) -> dict[str, Any]:
    """Filter only the DC outer-loop error input; raw voltage remains available."""

    original, master_path = _regular(source), _regular(master)
    target = _new_target(destination, (original, master_path))
    if isinstance(time_constant_s, bool) or time_constant_s != 0.005:
        raise _error("MMC_TEMPLATE_NATIVE_BINDING_INVALID", "The frozen DC feedback filter contract is 5 ms.")
    source_hash, master_hash = _sha256(original), _sha256(master_path)
    root = ET.parse(original).getroot()
    master_root = ET.parse(master_path).getroot()
    filter_definition = next((item for item in master_root.findall("./definitions/Definition") if item.get("name") == "realpole"), None)
    ports = {item.get("name"): item for item in filter_definition.findall("./svg/port")} if filter_definition is not None else {}
    if any(name not in ports or ports[name].get("x") != position or (ports[name].text or "").strip() != "true" for name, position in (("I:Dim", "-36"), ("O:Dim", "36"))):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The installed real-pole port contract differs.")
    definition = next((item for item in root.findall("./definitions/Definition") if item.get("name") == "VSCControl2"), None)
    if definition is None:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The DC outer controller is absent.")
    users = {item.get("id"): item for item in _components(definition)}
    feedback = users.get("177754199")
    summing = users.get("1475059159")
    if feedback is None or summing is None or feedback.get("defn") != "master:datalabel" or dict(_parameters(feedback)).get("Name") != "Edc_Pu" or dict(_parameters(summing)).get("B") != "-1":
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The exact raw DC-error feedback branch differs.")
    for owner in ("1379729478", "1453282758"):
        if owner not in users or dict(_parameters(users[owner])).get("Name") != "Edc_Pu":
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "A protected raw DC-voltage branch differs.")
    next(item for item in feedback.findall("./paramlist/param") if item.get("name") == "Name").set("value", "MmcFilteredVdcPu")
    used = {item.get("id") for item in root.iter()}
    def new_id():
        value = 2041000001
        while str(value) in used:
            value += 1
        used.add(str(value))
        return str(value)
    canvas = definition.find("schematic")
    def user(defn, x, params):
        item = ET.SubElement(canvas, "User", {"classid": "UserCmp", "defn": defn, "id": new_id(), "x": str(x), "y": "3402", "orient": "0", "w": "84", "h": "58", "z": "1375", "link": "-1", "q": "4"})
        group = ET.SubElement(item, "paramlist", {"name": "", "link": "-1"})
        for key, value in params.items():
            ET.SubElement(group, "param", {"name": key, "value": value})
        return item
    user("master:datalabel", 3528, {"Name": "Edc_Pu"})
    filtered = user("master:realpole", 3600, {"G": "1.0", "T": "0.005 [s]", "Dim": "1", "Limit": "0", "Reset": "2", "YO": "Edc_Pu", "Min": "-10.0", "Max": "10.0", "COM": "MMC DC feedback only"})
    user("master:datalabel", 3672, {"Name": "MmcFilteredVdcPu"})
    for x in (3528, 3636):
        wire = ET.SubElement(canvas, "Wire", {"classid": "WireOrthogonal", "id": new_id(), "name": "", "x": str(x), "y": "3402", "orient": "0", "w": "46", "h": "10"})
        ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
        ET.SubElement(wire, "vertex", {"x": "36", "y": "0"})
    _write_new_xml(root, target)
    if _sha256(original) != source_hash or _sha256(master_path) != master_hash:
        raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "A filter materialization source changed.")
    return {"source": str(original), "source_sha256": source_hash, "destination": str(target), "destination_sha256": _sha256(target), "master_sha256": master_hash, "filter_owner": filtered.get("id"), "time_constant_s": time_constant_s, "initialization": "reset_to_raw_feedback_at_timezero", "feedback_label_owner": feedback.get("id"), "raw_feedback_label_owners": ["1379729478", "1453282758"], "scope": "dc_outer_loop_feedback_only", "raw_voltage_acceptance": True}


def materialize_terminal_two_carrier(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Compare the installed 3/23 carrier asymmetry using only one ratio change."""

    original = _regular(source)
    target = _new_target(destination, (original,))
    digest = _sha256(original)
    root = ET.parse(original).getroot()
    main = next((item for item in root.findall("./definitions/Definition") if item.get("name") == "Main"), None)
    station = next((item for item in root.findall("./definitions/Definition") if item.get("name") == "Station"), None)
    matches = [item for item in _components(main) if item.get("id") == "1268416470" and item.get("defn", "").endswith(":MMC_Hb_PWM")] if main is not None else []
    if len(matches) != 1 or dict(_parameters(matches[0])).get("IvlvTop") != "ITopT2" or dict(_parameters(matches[0])).get("Cfreq") not in ("3", "3.0") or station is None or dict(_parameters(station)).get("Freq") not in ("60", "60.0"):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The installed terminal-2 carrier and 60 Hz source differ from this diagnostic contract.")
    next(item for item in matches[0].findall("./paramlist/param") if item.get("name") == "Cfreq").set("value", "23")
    _write_new_xml(root, target)
    if _sha256(original) != digest:
        raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "The carrier diagnostic source changed.")
    return {"source": str(original), "source_sha256": digest, "destination": str(target), "destination_sha256": _sha256(target), "owner_id": "1268416470", "parameter": "Cfreq", "before_ratio": 3.0, "after_ratio": 23.0, "fundamental_frequency_hz": 60.0, "cell_carrier_frequency_hz": 1380.0, "scope": "terminal_2_carrier_ratio_only", "arm_effective_switching_frequency_claimed": False}


def materialize_dc_port_damping(source: str | Path, destination: str | Path, *, master: str | Path) -> dict[str, Any]:
    """Add a zero-DC-gain damping term only to the power-mode current branch."""

    original, master_path = _regular(source), _regular(master)
    target = _new_target(destination, (original, master_path))
    digest, master_digest = _sha256(original), _sha256(master_path)
    root = ET.parse(original).getroot()
    definition = next((item for item in root.findall("./definitions/Definition") if item.get("name") == "VSCControl2"), None)
    if definition is None:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The original power controller is missing.")
    users = {item.get("id"): item for item in _components(definition)}
    selector = users.get("1610070623")
    limiter = users.get("1359229547")
    filters = [item for item in users.values() if item.get("defn") == "master:realpole" and dict(_parameters(item)).get("COM") == "MMC DC feedback only"]
    if selector is None or limiter is None or dict(_parameters(selector)).get("A") != "1" or dict(_parameters(selector)).get("DPath") != "1" or dict(_parameters(limiter)).get("UL") != "Imax" or len(filters) != 1:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "Power-mode selection, total limiter, or local DC feedback filter differs.")
    expected_filter = {"G": "1.0", "T": "0.005 [s]", "Dim": "1", "Limit": "0", "Reset": "2", "YO": "Edc_Pu", "Min": "-10.0", "Max": "10.0", "COM": "MMC DC feedback only"}
    if any(dict(_parameters(filters[0])).get(key) != value for key, value in expected_filter.items()) or any(filters[0].get(key) != value for key, value in {"x": "3600", "y": "3402", "orient": "0"}.items()):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The complete zero-DC-gain filter contract differs.")
    for signal, x in (("Edc_Pu", "3528"), ("MmcFilteredVdcPu", "3672")):
        labels = [item for item in users.values() if item.get("defn") == "master:datalabel" and dict(_parameters(item)).get("Name") == signal and item.get("x") == x and item.get("y") == "3402"]
        if len(labels) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The local DC filter signal binding differs.", signal=signal)
    for expected_points in ([(3528, 3402), (3564, 3402)], [(3636, 3402), (3672, 3402)]):
        connections = []
        for item in definition.findall("./schematic/Wire"):
            observed = [(int(item.get("x", "0")) + int(point.get("x", "0")), int(item.get("y", "0")) + int(point.get("y", "0"))) for point in item.findall("vertex")]
            if observed == expected_points or observed == list(reversed(expected_points)):
                connections.append(item)
        if len(connections) != 1:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The local DC filter connection is missing or ambiguous.")
    master_root = ET.parse(master_path).getroot()
    for name, required in {"gain": {"IN:Dim": (-36, 0), "OUT:Dim": (36, 0)}, "sumjct": {"IND": (-36, 0), "INB": (0, -36), "OUT": (36, 0)}, "select": {"InA:Dim": (-36, -36)}}.items():
        component_definition = next((item for item in master_root.findall("./definitions/Definition") if item.get("name") == name), None)
        ports = {item.get("name"): item for item in component_definition.findall("./svg/port") if item.get("type") == "Real"} if component_definition is not None else {}
        if any(port not in ports or (int(ports[port].get("x")), int(ports[port].get("y"))) != position for port, position in required.items()):
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The installed damping-network port metadata differs.", definition=name)
    canvas = definition.find("schematic")
    branch = next((item for item in canvas.findall("Wire") if item.get("id") == "2067107620"), None)
    points = [(int(branch.get("x")) + int(item.get("x")), int(branch.get("y")) + int(item.get("y"))) for item in branch.findall("vertex")] if branch is not None else []
    if points != [(2124, 1908), (2088, 1908), (2088, 1728), (1818, 1728)]:
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The power-mode PI-to-selector connection differs.")
    branch.set("x", "1818")
    branch.set("y", "1728")
    branch.set("w", "82")
    branch.set("h", "10")
    for item in branch.findall("vertex"):
        branch.remove(item)
    ET.SubElement(branch, "vertex", {"x": "0", "y": "0"})
    ET.SubElement(branch, "vertex", {"x": "72", "y": "0"})
    used = {item.get("id") for item in root.iter()}
    def next_id():
        value = 2031000001
        while str(value) in used:
            value += 1
        used.add(str(value))
        return str(value)
    def user(defn, x, y, params):
        item = ET.SubElement(canvas, "User", {"classid": "UserCmp", "defn": defn, "id": next_id(), "x": str(x), "y": str(y), "orient": "0", "w": "84", "h": "58", "z": "1555", "link": "-1", "q": "4"})
        group = ET.SubElement(item, "paramlist", {"name": "", "link": "-1"})
        for key, value in params.items():
            ET.SubElement(group, "param", {"name": key, "value": value})
        return item
    def label(name, x, y):
        return user("master:datalabel", x, y, {"Name": name})
    def wire(x, y, dx, dy):
        item = ET.SubElement(canvas, "Wire", {"classid": "WireOrthogonal", "id": next_id(), "name": "", "x": str(x), "y": str(y), "orient": "0", "w": str(abs(dx) + 10), "h": str(abs(dy) + 10)})
        ET.SubElement(item, "vertex", {"x": "0", "y": "0"})
        ET.SubElement(item, "vertex", {"x": str(dx), "y": str(dy)})
    subtract = {"DPath": "1", "A": "0", "B": "-1", "C": "0", "D": "1", "E": "0", "F": "0", "G": "0"}
    label("Edc_Pu", 3168, 3492)
    label("MmcFilteredVdcPu", 3240, 3420)
    user("master:sumjct", 3240, 3492, subtract)
    wire(3168, 3492, 36, 0)
    wire(3240, 3420, 0, 36)
    gain = user("master:gain", 3348, 3492, {"G": "1.5", "Dim": "1"})
    wire(3276, 3492, 36, 0)
    label("MmcDcDamping", 3420, 3492)
    wire(3384, 3492, 36, 0)
    label("Idref1", 3168, 3636)
    label("MmcDcDamping", 3240, 3564)
    user("master:sumjct", 3240, 3636, subtract)
    wire(3168, 3636, 36, 0)
    wire(3240, 3564, 0, 36)
    label("MmcDampedPIdref", 3312, 3636)
    wire(3276, 3636, 36, 0)
    label("MmcDampedPIdref", 2124, 1908)
    label("MmcIdBeforeLimit", 2232, 1944)
    _write_new_xml(root, target)
    if _sha256(original) != digest or _sha256(master_path) != master_digest:
        raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "A damping-network source changed.")
    return {"source": str(original), "source_sha256": digest, "destination": str(target), "destination_sha256": _sha256(target), "master_sha256": master_digest, "gain_owner": gain.get("id"), "equation": "power_mode_id = Idref1 - 1.5 * (Edc_Pu - MmcFilteredVdcPu)", "gain_pu": 1.5, "dc_gain": 0.0, "branch": "P_mode_InA_before_Imag_limiter", "selector_owner": "1610070623", "total_current_limiter_owner": "1359229547", "replaced_wire_owner": "2067107620", "steady_power_order_changed": False}


def materialize_arm_virtual_resistance(source: str | Path, destination: str | Path, *, master: str | Path) -> dict[str, Any]:
    """Add high-pass circulating-current feedback to the common arm voltage."""

    original, master_path = _regular(source), _regular(master)
    target = _new_target(destination, (original, master_path))
    digest, master_digest = _sha256(original), _sha256(master_path)
    root = ET.parse(original).getroot()
    definitions = {item.get("name"): item for item in root.findall("./definitions/Definition")}
    pole = definitions.get("MMC_Hb_Pole_PWM")
    main = definitions.get("Main")
    if pole is None or main is None or any(dict(_parameters(item)).get("Name") == "MmcDcDamping" for item in _components(root)):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "Use the native baseline without the rejected d-axis damping experiment.")
    for instance in _components(main):
        if instance.get("defn", "").endswith(":MMC_Hb_PWM") and dict(_parameters(instance)).get("VdcBase") not in ("640", "640.0", "640 [kV]", "640.0 [kV]"):
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "Virtual resistance requires the frozen 640 kV normalization.")
    users = {item.get("id"): item for item in _components(pole)}
    expected = {"166206085": ("master:datalabel", "Name", "Vz"), "1642798056": ("master:import", "Name", "Vz"), "1514910955": ("master:varrlc", "I", "IaTop"), "1386643874": ("master:varrlc", "I", "IaBtm")}
    for owner, (defn, parameter, value) in expected.items():
        if owner not in users or users[owner].get("defn") != defn or dict(_parameters(users[owner])).get(parameter) != value:
            raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The audited arm-current/common-voltage source differs.", owner=owner)
    if dict(_parameters(users["148785169"])).get("B") != "1" or dict(_parameters(users["935854485"])).get("B") != "-1":
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The original common/differential voltage equations differ.")
    master_root = ET.parse(master_path).getroot()
    realpole = next((item for item in master_root.findall("./definitions/Definition") if item.get("name") == "realpole"), None)
    if realpole is None or not any(item.get("name") == "T" and item.get("unit") == "s" for item in realpole.findall("./form/category/parameter")):
        raise _error("MMC_ACCEPTANCE_INCOMPLETE", "The verified real-pole time-constant contract is missing.")
    next(item for item in users["166206085"].findall("./paramlist/param") if item.get("name") == "Name").set("value", "MmcVzEffective")
    used = {item.get("id") for item in root.iter()}
    def next_id():
        value = 2021000001
        while str(value) in used:
            value += 1
        used.add(str(value))
        return str(value)
    canvas = pole.find("schematic")
    def user(defn, x, y, params):
        item = ET.SubElement(canvas, "User", {"classid": "UserCmp", "defn": defn, "id": next_id(), "x": str(x), "y": str(y), "orient": "0", "w": "84", "h": "58", "z": "165", "link": "-1", "q": "4"})
        group = ET.SubElement(item, "paramlist", {"name": "", "link": "-1"})
        for key, value in params.items():
            ET.SubElement(group, "param", {"name": key, "value": value})
        return item
    def label(name, x, y):
        return user("master:datalabel", x, y, {"Name": name})
    def wire(x, y, dx, dy):
        item = ET.SubElement(canvas, "Wire", {"classid": "WireOrthogonal", "id": next_id(), "name": "", "x": str(x), "y": str(y), "orient": "0", "w": str(abs(dx) + 10), "h": str(abs(dy) + 10)})
        ET.SubElement(item, "vertex", {"x": "0", "y": "0"})
        ET.SubElement(item, "vertex", {"x": str(dx), "y": str(dy)})
    add = {"DPath": "1", "A": "0", "B": "1", "C": "0", "D": "1", "E": "0", "F": "0", "G": "0"}
    subtract = {**add, "B": "-1"}
    label("IaTop", 3132, 2700)
    label("IaBtm", 3204, 2628)
    user("master:sumjct", 3204, 2700, add)
    wire(3132, 2700, 36, 0)
    wire(3204, 2628, 0, 36)
    user("master:gain", 3312, 2700, {"G": "0.5", "Dim": "1"})
    wire(3240, 2700, 36, 0)
    label("MmcIcircRaw", 3384, 2700)
    wire(3348, 2700, 36, 0)
    label("MmcIcircRaw", 3456, 2700)
    filtered = user("master:realpole", 3528, 2700, {"G": "1.0", "T": "0.005 [s]", "Dim": "1", "Limit": "0", "Reset": "2", "YO": "MmcIcircRaw", "Min": "-100.0", "Max": "100.0", "COM": "MMC highpass arm damping"})
    wire(3456, 2700, 36, 0)
    label("MmcIcircLowpass", 3600, 2700)
    wire(3564, 2700, 36, 0)
    label("MmcIcircRaw", 3132, 2880)
    label("MmcIcircLowpass", 3204, 2808)
    user("master:sumjct", 3204, 2880, subtract)
    wire(3132, 2880, 36, 0)
    wire(3204, 2808, 0, 36)
    label("MmcIcircHighpass", 3276, 2880)
    wire(3240, 2880, 36, 0)
    label("MmcIcircHighpass", 3348, 2880)
    user("master:gain", 3420, 2880, {"G": "0.09375", "Dim": "1"})
    wire(3348, 2880, 36, 0)
    label("MmcVzResistance", 3492, 2880)
    wire(3456, 2880, 36, 0)
    label("Vz", 3132, 3060)
    label("MmcVzResistance", 3204, 2988)
    user("master:sumjct", 3204, 3060, subtract)
    wire(3132, 3060, 36, 0)
    wire(3204, 2988, 0, 36)
    label("MmcVzEffective", 3276, 3060)
    wire(3240, 3060, 36, 0)
    _write_new_xml(root, target)
    if _sha256(original) != digest or _sha256(master_path) != master_digest:
        raise _error("MMC_TEMPLATE_SOURCE_CHANGED", "A virtual-resistance source changed.")
    return {"source": str(original), "source_sha256": digest, "destination": str(target), "destination_sha256": _sha256(target), "master_sha256": master_digest, "resistance_per_arm_ohm": 30.0, "equivalent_dc_resistance_ohm": 20.0, "normalization_voltage_kv": 640.0, "gain_pu_per_ka": 0.09375, "filter_owner": filtered.get("id"), "time_constant_s": 0.005, "dc_gain": 0.0, "command_difference_unchanged": True, "equation": "Vz_effective = Vz - (2*30/640)*HP_5ms((IaTop+IaBtm)/2)", "physical_resistor_loss_claimed": False, "existing_cell_count_saturation_retained": True}


__all__ = [
    "REQUIRED_ROLES",
    "default_fault_checks",
    "finalize_fault_instrumentation",
    "instrument_fault_channels",
    "materialize_arm_virtual_resistance",
    "materialize_complete_arm_sorting",
    "materialize_dc_feedback_filter",
    "materialize_dc_port_damping",
    "materialize_terminal_two_carrier",
    "materialize_terminal_two_charging",
    "materialize_voltage_control_headroom",
    "reachable_instances",
    "read_fault_output_dataset",
    "snapshot_output_dataset",
    "verify_fault_instrumentation",
    "verify_output_dataset",
]
