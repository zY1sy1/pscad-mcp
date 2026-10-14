"""Reproducible preparation of the audited installed full-bridge PWM circuit."""

from __future__ import annotations

import hashlib
import json
import math
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from .fault_channels import _new_target, _regular, _write_new_xml
from .pwm_commands import _params, _set


def materialize_pwm_power_response(source, destination, *, integral_time_s=0.02):
    """Remove the observed 0.2 s outer-power integrator lag; retain current bounds."""
    original = _regular(source)
    target = _new_target(destination, (original,))
    if (
        isinstance(integral_time_s, bool)
        or not math.isfinite(integral_time_s)
        or not 0.005 <= integral_time_s <= 0.2
    ):
        raise ValueError("The outer-power integral time must be between 5 and 200 ms")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    root = ET.parse(original).getroot()
    controllers = root.findall("./definitions/Definition[@name='Main']/schematic/User")
    controllers = [
        u for u in controllers if u.get("defn", "").endswith(":VSCConverter")
    ]
    if len(controllers) != 2 or {_params(u).get("dmode") for u in controllers} != {
        "0",
        "1",
    }:
        raise BackendError(
            "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED",
            "The audited controllers are unavailable.",
            "hvdc",
            "prepare_pwm_response",
        )
    changes = []
    for controller in controllers:
        for parameter in ("Ti_P", "Ti_Q"):
            if _params(controller).get(parameter) != "0.2":
                raise BackendError(
                    "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED",
                    "The audited outer-power integral time differs.",
                    "hvdc",
                    "prepare_pwm_response",
                )
            _set(controller, parameter, integral_time_s)
            changes.append(
                {
                    "owner": controller.get("id"),
                    "parameter": parameter,
                    "before_s": 0.2,
                    "after_s": integral_time_s,
                }
            )
    _write_new_xml(root, target)
    if hashlib.sha256(original.read_bytes()).hexdigest() != digest:
        raise RuntimeError("The original PWM source changed")
    return {
        "source": str(original),
        "source_sha256": digest,
        "destination": str(target),
        "destination_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "changes": changes,
        "current_bounds_unchanged": True,
        "physical_acceptance_required": True,
    }


def prepare_routed_pwm_case(source, library, master, workspace):
    """Prepare the explicit 640 kV/1000 MW/60 Hz/200 km full-bridge reference."""
    from pathlib import Path

    from . import fault_channels as physical
    from .pwm_channels import compose_pwm_channel_contract
    from .pwm_commands import materialize_pwm_command_interface

    directory = Path(workspace).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    current = Path(source).resolve()
    lineage = []
    stages = (
        ("charging", physical.materialize_terminal_two_charging, {}),
        (
            "headroom",
            physical.materialize_voltage_control_headroom,
            {"current_limit_pu": 1.1},
        ),
        ("feedback", physical.materialize_dc_feedback_filter, {"master": master}),
        ("carrier", physical.materialize_terminal_two_carrier, {}),
        (
            "virtual_resistance",
            physical.materialize_arm_virtual_resistance,
            {"master": master},
        ),
        ("sorting", physical.materialize_complete_arm_sorting, {"library": library}),
        ("dc_integral", physical.materialize_voltage_control_integral_time, {}),
        ("power_integral", materialize_pwm_power_response, {}),
    )
    for name, producer, kwargs in stages:
        target = directory / (name + ".pscx")
        lineage.append(producer(current, target, **kwargs))
        current = target
    command_source = directory / "command_source.pscx"
    routing = materialize_pwm_command_interface(
        current,
        command_source,
        master=master,
        library=library,
        rated_power_mw=1000.0,
        power_reversal_time_s=0.5,
        dc_link_length_km=200.0,
    )
    target = directory / "H_MMC_Mono_DC.pscx"
    contract = physical.instrument_fault_channels(
        command_source,
        target,
        library=library,
        master=master,
        fault_switch_name="McpDcPnFault",
        recovery_signals={"T1": "McpEnableT1", "T2": "McpEnableT2"},
    )
    contract = compose_pwm_channel_contract(target, contract)
    for name, document in (
        ("routing.json", routing),
        ("channels.json", contract),
        ("lineage.json", lineage),
    ):
        (directory / name).write_text(json.dumps(document, indent=2), encoding="utf-8")
    return {
        "project": str(target),
        "routing": routing,
        "channels": contract,
        "lineage": lineage,
        "model_accepted": False,
    }
