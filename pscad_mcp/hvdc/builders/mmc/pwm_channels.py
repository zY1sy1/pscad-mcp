"""Compose actual routed command and physical-switch probes with arm evidence."""

from __future__ import annotations

import hashlib
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
    """Expose every actual probe without aliasing whole arm sets to one value."""
    from ...profiles import load_profile

    profile = load_profile("mmc_detailed_pwm_v2")
    bindings = prepared["channels"]["channels"] + prepared["channels"]["diagnostic_channels"]
    families = {"1": "boolean", "pu": "ratio", "kV": "voltage", "kA": "current",
                "MW": "power", "MVAr": "power", "MJ": "energy", "s": "time"}
    profile["mappings"] = [{
        "canonical": binding["channel_id"].lower(),
        "aliases": [binding["selector"]["description"]],
        "source_kinds": ["measurement"], "direction": "measurement",
        "units": binding["units"], "unit_family": families[binding["units"]],
    } for binding in bindings]
    profile["result_channels"] = [{
        "canonical": binding["channel_id"].lower(),
        "path": "H_MMC_Mono_DC/" + binding["channel_id"],
        "units": binding["units"], "location": binding["model_scope"],
        "quantity": binding["role"], "dimension": binding["dimension"],
        "selector": deepcopy(binding["selector"]),
        "signal_source": deepcopy(binding["signal_source"]),
    } for binding in bindings]
    profile["metric_roles"] = {binding["channel_id"].lower(): binding["role"] for binding in bindings}
    profile["command_bindings"] = deepcopy(prepared["routing"]["command_bindings"])
    profile["project_fingerprints"] = [{"project_stem": "H_MMC_Mono_DC", "pscad_version": "4.6.2"}]
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
            elif channel_id == "MCP_AC_PROTECTION":
                role, scope = "ac_protection_trip", "both"
            elif channel_id == "MCP_AC_PROTECTION_CURRENT":
                role, scope = "ac_protection_current", "both"
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
    result["readback"] = verify_fault_instrumentation(project, result)
    return result


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
