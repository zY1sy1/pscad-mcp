"""Compose actual routed command and physical-switch probes with arm evidence."""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

from . import timed_control
from .fault_channels import (
    _ports,
    _script_hash,
    reachable_instances,
    verify_fault_instrumentation,
)
from .pwm_commands import _params


def routed_pwm_profile(prepared):
    """Expose only exact, unit-declared channels present in this derived circuit."""
    from ...profiles import load_profile

    profile = load_profile("mmc_detailed_pwm_v2")
    profile.pop("extends", None)
    profile.pop("project_binding", None)
    profile["command_bindings"] = prepared["routing"]["command_bindings"]
    profile["project_fingerprints"] = [{"pscad_version": "4.6.2"}]
    profile["mappings"], profile["result_channels"], profile["metric_roles"] = (
        [],
        [],
        {},
    )
    aliases = {
        ("p_active", "T2"): "station_p_active_power",
        ("p_active", "T1"): "station_vdc_active_power",
        ("q_reactive", "T2"): "station_p_reactive_power",
        ("q_reactive", "T1"): "station_vdc_reactive_power",
        ("v_dc", "T1"): "dc_voltage",
        ("i_dc_station", "T1"): "dc_current",
    }
    contract = prepared["channels"]
    for binding in contract["channels"] + contract["diagnostic_channels"]:
        role, scope, units = binding["role"], binding["model_scope"], binding["units"]
        canonical = aliases.get((role, scope), binding["channel_id"].lower())
        description = binding["selector"]["description"]
        family = {
            "kV": "voltage",
            "kA": "current",
            "MW": "power",
            "MVAr": "power",
            "MJ": "energy",
            "s": "time",
        }.get(units, "ratio")
        profile["mappings"].append(
            {
                "canonical": canonical,
                "aliases": [description],
                "source_kinds": ["measurement"],
                "unit_family": family,
                "direction": "measurement",
                "units": units,
            }
        )
        profile["result_channels"].append(
            {
                "canonical": canonical,
                "path": description,
                "units": units,
                "location": binding["definition_name"],
                "role": role,
                "model_scope": scope,
            }
        )
        profile["metric_roles"][canonical] = canonical
    profile["requires_frozen_channel_contract"] = True
    return profile


def compose_pwm_channel_contract(project, contract):
    root = ET.parse(project).getroot()
    result = deepcopy(contract)
    result["project_path"] = str(project)
    definitions = root.findall("./definitions/Definition")
    reachable = reachable_instances(root)
    for definition in definitions:
        name = definition.get("name")
        if name.startswith("McpPwm"):
            result["readback_scripts"][name] = _script_hash(definition)
            result["readback_ports"][name] = _ports(definition)
        instances = [i for i in reachable if i["definition_name"] == name]
        if len(instances) != 1:
            continue
        for component in definition.findall("./schematic/User"):
            parameters = _params(component)
            channel_id = parameters.get("Name", "")
            if component.get("defn") != "master:pgb":
                continue
            role, scope = None, None
            if channel_id.startswith("MCP_Q_T"):
                role, scope = "q_reactive", channel_id[-2:]
            elif channel_id.startswith("MCP_DC_PROTECTION_T"):
                role, scope = "dc_protection_trip", channel_id[-2:]
            elif channel_id.startswith("MCP_AC_CLOSED_"):
                role, scope = (
                    "ac_breaker_state",
                    channel_id.removeprefix("MCP_AC_CLOSED_"),
                )
            elif channel_id.startswith("MCP_DC_CLOSED_"):
                role, scope = (
                    "dc_breaker_state",
                    channel_id.removeprefix("MCP_DC_CLOSED_"),
                )
            elif channel_id.startswith("MCP_AC_FAULT_CLOSED"):
                role, scope = (
                    "ac_fault_branch_state",
                    channel_id.removeprefix("MCP_AC_FAULT_CLOSED").strip("_") or "any",
                )
            elif channel_id.startswith("MCP_AC_FAULT_CURRENT_"):
                role, scope = "ac_fault_current", channel_id[-1]
            elif channel_id.startswith("MCP_AC_GRID_CURRENT_"):
                role, scope = "ac_grid_current", channel_id[-1]
            elif channel_id == "MCP_DC_PG_FAULT_CLOSED":
                role, scope = "pg_fault_state", "DC_T2_PG"
            elif channel_id == "MCP_DC_PG_FAULT_CURRENT":
                role, scope = "pg_fault_current", "DC_T2_PG"
            if role is None:
                continue
            instance = instances[0]["instance_path"]
            binding = {
                "channel_id": channel_id,
                "role": role,
                "model_scope": scope,
                "definition_name": name,
                "owner_id": component.get("id"),
                "definition": "master:pgb",
                "signal_source": {
                    "kind": "routed_physical_probe",
                    "owner_id": component.get("id"),
                    "definition": "master:pgb",
                    "parameter": "Signl",
                    "instance_path": instance + "/pgb[" + component.get("id") + "]",
                },
                "selector": {
                    "description": parameters["Name"],
                    "group": parameters["Group"],
                    "port": "Signl",
                    "owner_id": component.get("id"),
                    "instance_path": instance,
                },
                "units": parameters["Units"],
                "dimension": 1,
                "instance_path": instance,
            }
            result["diagnostic_channels"].append(binding)
    # Freeze every routed component and its complete wiring before scenario timing.
    existing = {
        (c["definition_name"], c["owner_id"]) for c in result["readback_components"]
    }
    wire_ids = {(w["definition_name"], w["owner_id"]) for w in result["readback_wires"]}
    for definition in definitions:
        name = definition.get("name")
        if name != "Main" and not name.startswith("McpPwm"):
            continue
        for component in definition.findall("./schematic/User"):
            if (name, component.get("id")) in existing:
                continue
            result["readback_components"].append(
                {
                    "definition_name": name,
                    "owner_id": component.get("id"),
                    "definition": component.get("defn"),
                    "parameters": _params(component),
                    "position": {
                        key: component.get(key) for key in ("x", "y", "orient")
                    },
                }
            )
        for wire in definition.findall("./schematic/Wire"):
            if (name, wire.get("id")) not in wire_ids:
                result["readback_wires"].append(
                    {
                        "definition_name": name,
                        "owner_id": wire.get("id"),
                        "attributes": {
                            key: wire.get(key)
                            for key in ("classid", "x", "y", "orient")
                        },
                        "vertices": [dict(v.attrib) for v in wire.findall("vertex")],
                    }
                )
    result["ac_fault_network"] = audited_ac_fault_network(root)
    transformer_definition = root.find("./definitions/Definition[@name='MFE_VSC_T2']")
    for component in transformer_definition.findall("./schematic/User"):
        if component.get("id") not in {"247869978", "1805502023"}:
            continue
        if (transformer_definition.get("name"), component.get("id")) not in existing:
            result["readback_components"].append(
                {
                    "definition_name": transformer_definition.get("name"),
                    "owner_id": component.get("id"),
                    "definition": component.get("defn"),
                    "parameters": _params(component),
                    "position": {
                        key: component.get(key) for key in ("x", "y", "orient")
                    },
                }
            )
    result["readback"] = verify_fault_instrumentation(project, result)
    return result


def audited_ac_fault_network(root):
    """Use the connected grid and grounded Y/delta transformer's sequence path."""
    main = root.find("./definitions/Definition[@name='Main']/schematic")
    grid = main.find("User[@id='2102734538']")
    station = main.find("User[@id='800413106']")
    winding = root.find(
        "./definitions/Definition[@name='MFE_VSC_T2']/schematic/User[@id='247869978']"
    )
    ground = root.find(
        "./definitions/Definition[@name='MFE_VSC_T2']/schematic/User[@id='1805502023']"
    )
    if any(x is None for x in (grid, station, winding, ground)):
        raise RuntimeError("The AC sequence network has no audited connected owners")
    g, s, w = _params(grid), _params(station), _params(winding)
    if (
        grid.get("defn") != "master:source_3"
        or g["Type"] != "3"
        or g["Grnd"] != "1"
        or float(g["C"].split()[0]) != 0
        or w["YD1"] != "0"
        or w["YD2"] != "1"
        or w["Xl"] != "Xt"
        or w["Tmva"] != "Sbase"
        or w["V1"] != "Vtr_1"
        or ground.get("defn") != "master:ground"
        or (int(ground.get("x")), int(ground.get("y"))) != (270, 288)
        or (int(winding.get("x")), int(winding.get("y")), winding.get("orient"))
        != (288, 252, "0")
    ):
        raise RuntimeError("The grounded Y/delta zero-sequence network differs")
    voltage = float(s["Vtr_1"].split()[0])
    main_instances = root.findall(".//User[@id='152486038']")
    if len(main_instances) != 1:
        raise RuntimeError("The actual Main frequency instance is ambiguous")
    frequency = float(_params(main_instances[0])["Freq"])
    return {
        "voltage_kv": voltage,
        "grid_resistance_ohm": float(g["R_"].split()[0]),
        "grid_reactance_ohm": 2 * math.pi * frequency * float(g["L"].split()[0]),
        "transformer_zero_sequence_reactance_ohm": float(s["Xt"])
        * voltage**2
        / float(s["Sbase"].split()[0]),
        "topology": "grounded_Y_delta",
        "grid_owner": grid.get("id"),
        "station_owner": station.get("id"),
        "transformer_owner": winding.get("id"),
        "ground_owner": ground.get("id"),
        "sequence_equations": "Z1=Z2=Zgrid; Z0=Zgrid || j*Xt*Vac^2/Sbase; If=3*Vphase/(Z1+Z2+Z0)",
    }


def compose_pwm_scenario_contract(contract, scenario, namespace):
    """Apply only recorded initializer changes and the exact immutable renderer."""
    result = deepcopy(contract)
    baseline = ET.parse(contract["project_path"]).getroot()
    schedule = scenario.get("timed_control")
    source = schedule["scenario_source"]["path"] if schedule else scenario["project"]
    initialization = scenario["pwm_initialization"]
    if initialization["source_sha256"] != contract["instrumented_project_sha256"]:
        raise RuntimeError(
            "The scenario initializer does not bind the instrumented baseline"
        )
    main = baseline.find("./definitions/Definition[@name='Main']/schematic")
    for change in initialization["changes"]:
        component = main.find(f"User[@id='{change['owner']}']")
        parameter = component.find(f"./paramlist/param[@name='{change['parameter']}']")
        if parameter.get("value") != str(change["before"]):
            raise RuntimeError(
                "An initializer's recorded before-value disagrees with its baseline"
            )
        parameter.set("value", str(change["after"]))
    observed = ET.parse(source).getroot()
    if ET.tostring(baseline) != ET.tostring(observed):
        raise RuntimeError(
            "The scenario source differs from its exact recorded initializer"
        )
    if (
        hashlib.sha256(Path(source).read_bytes()).hexdigest()
        != initialization["scenario_source_sha256"]
    ):
        raise RuntimeError("The initialized scenario source hash changed")
    rendered = (
        timed_control._render(schedule, namespace)
        if schedule
        else ET.parse(source).getroot()
    )
    if not schedule:
        original_name = rendered.get("name")
        rendered.set("name", namespace)
        for component in rendered.iter():
            for key in ("defn", "name"):
                value = component.get(key, "")
                if value.startswith(original_name + ":"):
                    component.set(key, namespace + value[len(original_name) :])
    definitions = {
        d.get("name"): d for d in rendered.findall("./definitions/Definition")
    }
    for expected in result["readback_components"]:
        component = definitions[expected["definition_name"]].find(
            f"./schematic/User[@id='{expected['owner_id']}']"
        )
        expected["definition"] = component.get("defn")
        expected["parameters"] = _params(component)
    result["wire_layout_normalization"] = []
    for expected in result["readback_wires"]:
        wire = definitions[expected["definition_name"]].find(
            f"./schematic/Wire[@id='{expected['owner_id']}']"
        )
        # Vendor first-save recomputes drawing bounds; electrical connections
        # are identified by class, origin, orientation and every exact vertex.
        layout = {
            key: value
            for key, value in expected["attributes"].items()
            if key in ("w", "h")
        }
        if layout:
            result["wire_layout_normalization"].append(
                {"owner": expected["owner_id"], "original_bounds": layout}
            )
        expected["attributes"] = {
            key: wire.get(key)
            for key in expected["attributes"]
            if key not in ("w", "h")
        }
    original_namespace = observed.get("name")
    for binding in result["channels"] + result["diagnostic_channels"]:
        definition = binding["signal_source"]["definition"]
        if definition.startswith(original_namespace + ":"):
            binding["signal_source"]["definition"] = (
                namespace + definition[len(original_namespace) :]
            )
    result["reachable_instances"] = reachable_instances(rendered)
    result["scenario_composition"] = {
        "schedule_sha256": schedule["schedule_sha256"] if schedule else None,
        "initializer": initialization,
        "namespace": namespace,
    }
    result["vendor_finalized"] = False
    return result
