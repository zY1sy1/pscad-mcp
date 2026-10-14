"""Reproducible preparation of the audited installed full-bridge PWM circuit."""

from __future__ import annotations

import hashlib
import json
import math
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from .fault_channels import _new_target, _regular, _write_new_xml
from .pwm_commands import _params, _set


def materialize_pwm_power_response(source, destination, *, integral_time_s=0.002):
    """Remove the observed 0.2 s outer-power integrator lag; retain current bounds."""
    original = _regular(source)
    target = _new_target(destination, (original,))
    if (
        isinstance(integral_time_s, bool)
        or not math.isfinite(integral_time_s)
        or not 0.001 <= integral_time_s <= 0.2
    ):
        raise ValueError("The active-power integral time must be between 1 and 200 ms")
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
        if _params(controller).get("Kp_P") != "0.25":
            raise RuntimeError("The audited active-power proportional gain differs")
        _set(controller, "Kp_P", 2.0)
        changes.append(
            {
                "owner": controller.get("id"),
                "parameter": "Kp_P",
                "before": 0.25,
                "after": 2.0,
            }
        )
        for parameter in ("Ti_P", "Ti_Q"):
            if _params(controller).get(parameter) != "0.2":
                raise BackendError(
                    "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED",
                    "The audited outer-power integral time differs.",
                    "hvdc",
                    "prepare_pwm_response",
                )
            selected_time = integral_time_s if parameter == "Ti_P" else 0.02
            _set(controller, parameter, selected_time)
            changes.append(
                {
                    "owner": controller.get("id"),
                    "parameter": parameter,
                    "before_s": 0.2,
                    "after_s": selected_time,
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
        ("ratings", materialize_pwm_reference_ratings, {"master": master}),
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
        ("dynamic_headroom", materialize_pwm_dynamic_headroom, {}),
        ("fault_protection", materialize_pwm_fault_protection, {}),
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


def materialize_pwm_reference_ratings(source, destination, *, master):
    """Bind both 230 kV grids to SCR=5, X/R=10 through real series R/L branches."""
    original, master_path = _regular(source), _regular(master)
    target = _new_target(destination, (original, master_path))
    root, masters = ET.parse(original).getroot(), ET.parse(master_path).getroot()
    implementation = masters.find(
        "./definitions/Definition[@name='source_3']/script/segment[@name='Dsdyn']"
    )
    if (
        implementation is None
        or "E_BRANCH_CFG($BA,$SS,1,IVD1_1,IVD1_2,$R_,$L,$C)" not in implementation.text
        or "IF ($C .LE. 1.0E-38) IVD1_2 = 0" not in implementation.text
    ):
        raise RuntimeError(
            "The installed series R/L grid-source implementation is not audited"
        )
    main = root.find("./definitions/Definition[@name='Main']/schematic")
    grids = [u for u in main.findall("User") if u.get("defn") == "master:source_3"]
    if {u.get("id") for u in grids} != {"2102734538", "1387181349"}:
        raise RuntimeError("The audited physical grids are unavailable")
    impedance = 230.0**2 / (1000.0 * 5.0)
    resistance = impedance / math.sqrt(1 + 10.0**2)
    inductance = 10.0 * resistance / (2 * math.pi * 60.0)
    changes = []
    for grid in grids:
        for key, value in {
            "Type": 3,
            "Vm": 230.0,
            "Vbase": "230 [kV]",
            "f": "$(Freq)",
            "R_": f"{resistance:.17g} [ohm]",
            "L": f"{inductance:.17g} [H]",
            "C": "0.0 [uF]",
        }.items():
            changes.append(
                {
                    "owner": grid.get("id"),
                    "parameter": key,
                    "before": _params(grid)[key],
                    "after": str(value),
                }
            )
            _set(grid, key, value)
    _write_new_xml(root, target)
    return {
        "source": str(original),
        "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "master_sha256": hashlib.sha256(master_path.read_bytes()).hexdigest(),
        "destination": str(target),
        "destination_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "changes": changes,
        "station_grid": {
            "voltage_kv": 230.0,
            "scr": 5.0,
            "x_over_r": 10.0,
            "rated_power_mw": 1000.0,
            "resistance_ohm": resistance,
            "inductance_h": inductance,
        },
    }


def materialize_pwm_dynamic_headroom(source, destination):
    """Avoid observed reverse-power current clipping and DC-energy lag."""
    original = _regular(source)
    target = _new_target(destination, (original,))
    root = ET.parse(original).getroot()
    main = root.find("./definitions/Definition[@name='Main']/schematic")
    power = main.find("User[@id='800413106']")
    voltage = main.find("User[@id='976600655']")
    integral = main.find("User[@id='1520814881']")
    if (
        power is None
        or _params(power).get("dmode") != "1"
        or _params(power).get("Imax") != "1"
        or integral is None
        or _params(integral).get("Name") != "TiDCRec"
        or _params(integral).get("Value") != "0.04"
    ):
        raise RuntimeError(
            "The audited current headroom or active DC integral setting differs"
        )
    _set(power, "Imax", 1.1)
    if voltage is None or _params(voltage).get("Imax") != "1.1":
        raise RuntimeError("The active voltage-control current headroom differs")
    _set(voltage, "Imax", 1.18)
    _set(integral, "Value", 0.02)
    _write_new_xml(root, target)
    return {
        "source": str(original),
        "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "destination": str(target),
        "destination_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "changes": [
            {
                "owner": power.get("id"),
                "parameter": "Imax",
                "before": "1",
                "after": "1.1",
            },
            {
                "owner": voltage.get("id"),
                "parameter": "Imax",
                "before": "1.1",
                "after": "1.18",
            },
            {
                "owner": integral.get("id"),
                "parameter": "Value",
                "before": "0.04",
                "after": "0.02",
            },
        ],
        "arm_acceptance_peak_ka": 3.0,
        "acceptance_bounds_unchanged": True,
    }


def materialize_pwm_fault_protection(source, destination):
    """Detect physical current/voltage faults before the observed millisecond peaks."""
    original = _regular(source)
    target = _new_target(destination, (original,))
    root = ET.parse(original).getroot()
    arms = [
        u
        for u in root.findall("./definitions/Definition[@name='Main']/schematic/User")
        if u.get("defn", "").endswith(":MMC_Hb_PWM")
    ]
    if len(arms) != 2:
        raise RuntimeError("The physical PWM protection instances are unavailable")
    changes = []
    for arm in arms:
        parameters = _params(arm)
        if (
            parameters.get("IvlMax") != "3.0 [kA]"
            or parameters.get("VdcDrop") != "0.4 [pu]"
            or parameters.get("FltPkT") != "100 [us]"
        ):
            raise RuntimeError("The audited physical protection settings differ")
        for key, value in {
            "IvlMax": "2.2 [kA]",
            "VdcDrop": "0.9 [pu]",
            "FltPkT": "20 [us]",
        }.items():
            changes.append(
                {
                    "owner": arm.get("id"),
                    "parameter": key,
                    "before": parameters[key],
                    "after": value,
                }
            )
            _set(arm, key, value)
    _write_new_xml(root, target)
    return {
        "source": str(original),
        "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "destination": str(target),
        "destination_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "changes": changes,
        "acceptance_arm_peak_ka": 3.0,
        "acceptance_dc_peak_pu": 2.0,
        "physical_fault_sensors_retained": True,
    }
