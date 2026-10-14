"""Cold-started, independently staged scenarios for routed PWM circuits."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from .fault_channels import _new_target, _regular, _write_new_xml
from .pwm_commands import COMMANDS, _params, _set


def prepare_routed_scenario_source(
    source: str | Path,
    destination: str | Path,
    scenario: dict[str, Any],
    *,
    warmup_s: float = 2.0,
) -> dict[str, Any]:
    """Bind initialization and fault type before the immutable timing plan.

    Each run starts from zero energy. Normal/fault events follow the measured
    precharge/settling allowance; their physical thresholds are unchanged.
    """
    original = _regular(source)
    target = _new_target(destination, (original,))
    source_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    root = ET.parse(original).getroot()
    main = root.find("./definitions/Definition[@name='Main']/schematic")
    if main is None:
        raise BackendError(
            "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED",
            "The PWM source has no Main schematic.",
            "hvdc",
            "prepare_pwm_scenario",
        )
    result = deepcopy(scenario)
    name = result["name"]
    changes = []
    initial = {
        "active_power_order": 1.0,
        "reactive_power_order": 0.0,
        "reset_command": 0.0,
        "block_command": 1.0 if name == "startup" else 0.0,
        "ac_breaker_command": 0.0 if name == "startup" else 1.0,
        "dc_breaker_command": 0.0 if name == "startup" else 1.0,
        "ac_fault_command": 0.0,
        "dc_fault_command": 0.0,
    }
    for canonical, (port, _default, _units, _allowed) in COMMANDS.items():
        matches = [
            u
            for u in main.findall("User")
            if u.get("defn") == "master:const"
            and _params(u).get("Name") == "McpCommand" + port
        ]
        if len(matches) != 1:
            raise BackendError(
                "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED",
                "A routed command source is missing or ambiguous.",
                "hvdc",
                "prepare_pwm_scenario",
                {"canonical": canonical},
            )
        before = _params(matches[0])["Value"]
        _set(matches[0], "Value", initial[canonical])
        changes.append(
            {
                "owner": matches[0].get("id"),
                "parameter": "Value",
                "before": before,
                "after": initial[canonical],
            }
        )
    if name.startswith("ac_"):
        control = main.find("User[@id='326579344']")
        if control is None or _params(control).get("Name") != "AC Fault type":
            raise BackendError(
                "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED",
                "The audited AC fault-type selector is missing.",
                "hvdc",
                "prepare_pwm_scenario",
            )
        _set(control, "Value", 1 if name == "ac_single_line_ground_fault" else 0)
    ground = [
        u
        for u in main.findall("User")
        if u.get("defn") == "master:const"
        and _params(u).get("Name") == "McpDcGroundCase"
    ]
    if len(ground) != 1:
        raise BackendError(
            "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED",
            "The physical DC fault selector is missing.",
            "hvdc",
            "prepare_pwm_scenario",
        )
    _set(ground[0], "Value", 1 if name == "dc_pole_to_ground_fault" else 0)
    if name != "startup":
        for event in result["events"]:
            event["time_s"] += warmup_s
    result["duration_s"] += warmup_s
    if name == "post_fault_recovery":
        # Recovery must follow an actual imposed fault in this same fresh run.
        sequence = [
            (0.30, "dc_fault_command", 1),
            (0.34, "block_command", 1),
            (0.38, "dc_breaker_command", 0),
            (0.50, "dc_fault_command", 0),
            (0.55, "reset_command", 1),
            (0.60, "reset_command", 0),
            (0.65, "ac_breaker_command", 1),
            (0.70, "dc_breaker_command", 1),
            (0.75, "block_command", 0),
            (0.80, "active_power_order", 0.8),
        ]
        result["events"] = [
            {"time_s": warmup_s + t, "target": role, "value": value}
            for t, role, value in sequence
        ]
        result["duration_s"] = warmup_s + 1.6
    result["pwm_initialization"] = {
        "source_sha256": source_hash,
        "zero_energy_start": True,
        "warmup_s": warmup_s,
        "initial_commands": initial,
        "changes": changes,
        "thresholds_unchanged": True,
    }
    result["project"] = str(target)
    _write_new_xml(root, target)
    if hashlib.sha256(original.read_bytes()).hexdigest() != source_hash:
        raise BackendError(
            "MMC_SOURCE_HASH_MISMATCH",
            "The PWM scenario source changed.",
            "hvdc",
            "prepare_pwm_scenario",
        )
    result["pwm_initialization"]["scenario_source_sha256"] = hashlib.sha256(
        target.read_bytes()
    ).hexdigest()
    return result
