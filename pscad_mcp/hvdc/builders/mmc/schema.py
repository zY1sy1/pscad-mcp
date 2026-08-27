"""Closed, side-effect-free schema validation for the Stage A MMC blueprint."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError
from .models import (
    MmcAcceptanceCheck,
    MmcArmSpec,
    MmcBlueprint,
    MmcComponentSpec,
    MmcControlContract,
    MmcNetSpec,
    MmcOutputSpec,
    MmcSequencePhase,
    MmcStationSpec,
)


SUPPORTED_BLUEPRINT = "cigre_b4_p2p_avm_v1"
_ARM_CURRENT_EQUATION = "i_upper = I_dc / 3 + i_phase / 2 + i_circulating"
_ARM_CURRENT_LOWER_EQUATION = "i_lower = I_dc / 3 - i_phase / 2 + i_circulating"
_ENERGY_EQUATION = "W_arm = 0.5 * C_eq * V_cap_eq^2"
_ENERGY_DERIVATIVE_EQUATION = "dW_arm/dt = v_inserted * i_arm - p_loss_arm"
_SEQUENCE_NAMES = (
    "blocked_precharge",
    "ready_to_deblock",
    "forward_ramp",
    "forward_steady",
    "power_reversal",
    "reverse_steady",
)
_ACCEPTANCE_NAMES = ("precharge_ready", "forward_steady", "power_reversal", "reverse_steady")
_OUTPUT_UNITS = {
    "dc_voltage_pole_to_pole": "kV",
    "dc_voltage_pole_to_ground": "kV",
    "dc_conductor_current": "kA",
    "station_ac_active_power": "MW",
    "station_ac_reactive_power": "MVAr",
    "station_dc_power": "MW",
    "ac_voltage": "kV",
    "ac_current": "kA",
    "arm_current": "kA",
    "arm_energy": "MJ",
    "equivalent_capacitor_voltage": "kV",
    "circulating_current": "kA",
    "arm_energy_difference": "MJ",
    "pll_frequency": "Hz",
    "pll_lock": "1",
    "active_power_command": "MW",
    "reactive_power_command": "MVAr",
    "dc_voltage_command": "kV",
    "modulation_index_unclipped": "1",
    "modulation_index_clipped": "1",
    "modulation_margin": "1",
    "controller_saturation": "1",
    "controller_saturation_duration": "s",
    "sequence_state": "1",
}

_TOP_LEVEL_KEYS = {
    "schema_version", "name", "profile", "model", "topology", "equation_version",
    "nominal_vdc_kv", "nominal_power_mw", "settings", "stations", "components", "nets",
    "outputs", "control_contract", "sequence", "acceptance_checks", "provenance",
}
_SETTINGS_KEYS = {
    "time_step_s", "output_step_s", "simulation_duration_s", "compiler_target", "compiler",
    "output_enabled", "pscad_version", "x64", "frequency_hz", "project_type", "simulation_set",
}
_STATION_KEYS = {
    "logical_id", "role", "ac_component", "arms", "control_contract", "dc_positive_bus",
    "dc_negative_bus", "transformer_component", "ac_impedance_component", "energy_control_component",
    "circulating_control_component", "parameters",
}
_ARM_KEYS = {
    "logical_id", "station_role", "phase", "arm", "definition", "location", "parameters", "ports",
    "orientation", "canvas", "role", "equations",
}
_COMPONENT_KEYS = {
    "logical_id", "definition", "location", "parameters", "ports", "orientation", "canvas",
    "bounding_box", "role",
}
_NET_KEYS = {"logical_id", "kind", "endpoints", "route", "label"}
_OUTPUT_KEYS = {"logical_id", "path", "units", "role", "call_id", "location", "measurement"}
_CONTROL_KEYS = {"version", "role", "active_power_command", "reactive_power_command", "dc_voltage_command", "equations", "modulation_bounds", "signals"}
_EQUATION_KEYS = {"arm_current_upper", "arm_current_lower", "energy", "energy_derivative", "arm_current"}
_SEQUENCE_KEYS = {"name", "order", "entry_condition", "exit_condition", "duration_s", "outputs", "commands"}
_ACCEPTANCE_KEYS = {"name", "kind", "required", "expected", "units", "comparison_window", "severity", "rationale"}


def _invalid(message: str, **details: Any) -> BackendError:
    return BackendError("MMC_BLUEPRINT_INVALID", message, "hvdc", "parse_mmc_blueprint", details)


def _object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{context} must be an object.", context=context)
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    non_string = [key for key in value if not isinstance(key, str)]
    if non_string:
        raise _invalid(f"{context} keys must be strings.", context=context, keys=[repr(key) for key in non_string])
    unknown = sorted(key for key in value if key not in allowed)
    if unknown:
        raise _invalid(f"{context} contains unknown field(s): {', '.join(unknown)}.", context=context, unknown=unknown)


def _sequence(value: Any, context: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise _invalid(f"{context} must be an array.", context=context)
    return value


def _text(value: Any, context: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{context} must be a string.", context=context)
    result = value.strip()
    if required and not result:
        raise _invalid(f"{context} must not be empty.", context=context)
    return result


def _integer(value: Any, context: str, *, positive: bool = False, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{context} must be an integer.", context=context)
    if positive and value <= 0:
        raise _invalid(f"{context} must be positive.", context=context)
    if nonnegative and value < 0:
        raise _invalid(f"{context} must be non-negative.", context=context)
    return value


def _number(value: Any, context: str, *, positive: bool = False, nonnegative: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{context} must be a number.", context=context)
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite = False
    if not finite:
        raise _invalid(f"{context} must be finite.", context=context)
    if positive and value <= 0:
        raise _invalid(f"{context} must be positive.", context=context)
    if nonnegative and value < 0:
        raise _invalid(f"{context} must be non-negative.", context=context)
    return value


def _json_value(value: Any, context: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid(f"{context} contains a non-finite number.", context=context)
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid(f"{context} keys must be strings.", context=context)
            result[key] = _json_value(item, f"{context}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item, f"{context}[{index}]") for index, item in enumerate(value)]
    raise _invalid(f"{context} contains a non-JSON value.", context=context)


def _required(value: Mapping[str, Any], names: set[str], context: str) -> None:
    missing = sorted(names - set(value))
    if missing:
        raise _invalid(f"{context} requires {', '.join(missing)}.", context=context)


def _location(value: Any, context: str) -> tuple[int, int]:
    point = _object(value, context)
    _keys(point, {"x", "y"}, context)
    _required(point, {"x", "y"}, context)
    return (_integer(point["x"], f"{context}.x"), _integer(point["y"], f"{context}.y"))


def _ports(value: Any, context: str) -> tuple[str, ...]:
    values = _sequence(value, context)
    result = tuple(_text(item, f"{context}[{index}]") for index, item in enumerate(values))
    if len(set(result)) != len(result):
        raise _invalid(f"{context} must not contain duplicate ports.", context=context)
    return result


def _parameters(value: Any, context: str) -> dict[str, Any]:
    mapping = _object(value, context)
    parsed: dict[str, Any] = {}
    for key, item in mapping.items():
        if not isinstance(key, str):
            raise _invalid(f"{context} keys must be strings.", context=context)
        parsed[key] = _json_value(item, f"{context}.{key}")
    return parsed


def _parse_control(value: Any, context: str, *, role: str | None = None, require_equations: bool = False) -> MmcControlContract:
    control = _object(value, context)
    _keys(control, _CONTROL_KEYS, context)
    _required(control, {"active_power_command", "reactive_power_command"}, context)
    control_role = _text(control.get("role", role or "link"), f"{context}.role")
    if role is not None and control_role != role:
        raise _invalid(f"{context}.role must match station role.", context=context)
    dc = control.get("dc_voltage_command")
    if role == "VDC" and dc is None:
        raise _invalid("VDC control requires dc_voltage_command.", context=context)
    if role == "P" and dc is not None:
        raise _invalid("P control must not define dc_voltage_command.", context=context)
    equations_value = control.get("equations", {})
    equations = _object(equations_value, f"{context}.equations")
    _keys(equations, _EQUATION_KEYS, f"{context}.equations")
    equations_json = {key: _text(item, f"{context}.equations.{key}") for key, item in equations.items()}
    if require_equations:
        required_equations = {"energy", "energy_derivative"}
        _required(equations, required_equations, f"{context}.equations")
        upper_equation = equations.get("arm_current_upper", equations.get("arm_current"))
        lower_equation = equations.get("arm_current_lower")
        if upper_equation is None or lower_equation is None:
            raise _invalid(f"{context}.equations requires upper and lower arm-current equations.", context=context)
        if upper_equation != _ARM_CURRENT_EQUATION or lower_equation != _ARM_CURRENT_LOWER_EQUATION or equations["energy"] != _ENERGY_EQUATION or equations["energy_derivative"] != _ENERGY_DERIVATIVE_EQUATION:
            raise _invalid(f"{context}.equations do not match the declared MMC equations.", context=context)
    bounds_value = _sequence(control.get("modulation_bounds", (0.0, 1.0)), f"{context}.modulation_bounds")
    if len(bounds_value) != 2:
        raise _invalid(f"{context}.modulation_bounds requires two numbers.", context=context)
    bounds = (_number(bounds_value[0], f"{context}.modulation_bounds[0]", nonnegative=True), _number(bounds_value[1], f"{context}.modulation_bounds[1]", nonnegative=True))
    if tuple(bounds) != (0.0, 1.0):
        raise _invalid(f"{context}.modulation_bounds must be [0, 1].", context=context)
    signals = tuple(_text(item, f"{context}.signals[{index}]") for index, item in enumerate(_sequence(control.get("signals", ()), f"{context}.signals")))
    return MmcControlContract(
        role=control_role,
        active_power_command=_text(control["active_power_command"], f"{context}.active_power_command"),
        reactive_power_command=_text(control["reactive_power_command"], f"{context}.reactive_power_command"),
        dc_voltage_command=None if dc is None else _text(dc, f"{context}.dc_voltage_command"),
        version=None if control.get("version") is None else _text(control["version"], f"{context}.version"),
        equations=equations_json,
        modulation_bounds=(float(bounds[0]), float(bounds[1])),
        signals=signals,
    )


def _parse_arm(value: Any, index: int, station_role: str) -> MmcArmSpec:
    context = f"stations[{station_role}].arms[{index}]"
    arm = _object(value, context)
    _keys(arm, _ARM_KEYS, context)
    _required(arm, {"logical_id", "station_role", "phase", "arm", "definition", "location", "parameters", "ports"}, context)
    arm_role = _text(arm["station_role"], f"{context}.station_role")
    if arm_role != station_role:
        raise _invalid(f"{context}.station_role does not match station role.", context=context)
    phase = _text(arm["phase"], f"{context}.phase")
    arm_kind = _text(arm["arm"], f"{context}.arm")
    if phase not in {"A", "B", "C"} or arm_kind not in {"upper", "lower"}:
        raise _invalid(f"{context} must identify phase A/B/C and upper/lower arm.", context=context)
    equations_value = _object(arm.get("equations", {}), f"{context}.equations")
    _keys(equations_value, _EQUATION_KEYS, f"{context}.equations")
    equations = {key: _text(item, f"{context}.equations.{key}") for key, item in equations_value.items()}
    return MmcArmSpec(
        logical_id=_text(arm["logical_id"], f"{context}.logical_id"),
        station_role=arm_role,
        phase=phase,
        arm=arm_kind,
        definition=_text(arm["definition"], f"{context}.definition"),
        location=_location(arm["location"], f"{context}.location"),
        parameters=_parameters(arm["parameters"], f"{context}.parameters"),
        ports=_ports(arm["ports"], f"{context}.ports"),
        orientation=_integer(arm.get("orientation", 0), f"{context}.orientation", nonnegative=True),
        canvas=_text(arm.get("canvas", "Main"), f"{context}.canvas"),
        role=None if arm.get("role") is None else _text(arm["role"], f"{context}.role"),
        equations=equations,
    )


def _parse_station(value: Any, index: int) -> MmcStationSpec:
    context = f"stations[{index}]"
    station = _object(value, context)
    _keys(station, _STATION_KEYS, context)
    _required(station, {"logical_id", "role", "ac_component", "arms", "control_contract"}, context)
    logical_id = _text(station["logical_id"], f"{context}.logical_id")
    role = _text(station["role"], f"{context}.role")
    if role not in {"P", "VDC"}:
        raise _invalid(f"{context}.role must be P or VDC.", context=context)
    arms_value = _sequence(station["arms"], f"{context}.arms")
    if len(arms_value) != 6:
        raise _invalid(f"{context}.arms must contain exactly six arms.", context=context)
    arms = tuple(_parse_arm(item, arm_index, role) for arm_index, item in enumerate(arms_value))
    arm_ids = [item.logical_id for item in arms]
    if len(set(arm_ids)) != len(arm_ids):
        raise _invalid(f"{context}.arms logical IDs must be unique.", context=context)
    if {(item.phase, item.arm) for item in arms} != {(phase, arm) for phase in ("A", "B", "C") for arm in ("upper", "lower")}:
        raise _invalid(f"{context}.arms must contain one upper and lower arm for each phase.", context=context)
    return MmcStationSpec(
        logical_id=logical_id,
        role=role,
        arms=arms,
        ac_component=_text(station["ac_component"], f"{context}.ac_component"),
        control_contract=_parse_control(station["control_contract"], f"{context}.control_contract", role=role),
        dc_positive_bus=None if station.get("dc_positive_bus") is None else _text(station["dc_positive_bus"], f"{context}.dc_positive_bus"),
        dc_negative_bus=None if station.get("dc_negative_bus") is None else _text(station["dc_negative_bus"], f"{context}.dc_negative_bus"),
        transformer_component=None if station.get("transformer_component") is None else _text(station["transformer_component"], f"{context}.transformer_component"),
        ac_impedance_component=None if station.get("ac_impedance_component") is None else _text(station["ac_impedance_component"], f"{context}.ac_impedance_component"),
        energy_control_component=None if station.get("energy_control_component") is None else _text(station["energy_control_component"], f"{context}.energy_control_component"),
        circulating_control_component=None if station.get("circulating_control_component") is None else _text(station["circulating_control_component"], f"{context}.circulating_control_component"),
        parameters=_parameters(station.get("parameters", {}), f"{context}.parameters"),
    )


def _parse_component(value: Any, index: int) -> MmcComponentSpec:
    context = f"components[{index}]"
    component = _object(value, context)
    _keys(component, _COMPONENT_KEYS, context)
    _required(component, {"logical_id", "definition", "location", "parameters", "ports"}, context)
    bounding = component.get("bounding_box")
    if bounding is not None:
        values = _sequence(bounding, f"{context}.bounding_box")
        if len(values) != 4:
            raise _invalid(f"{context}.bounding_box requires four integers.", context=context)
        bounding = tuple(_integer(item, f"{context}.bounding_box[{index}]") for index, item in enumerate(values))
    return MmcComponentSpec(
        logical_id=_text(component["logical_id"], f"{context}.logical_id"),
        definition=_text(component["definition"], f"{context}.definition"),
        location=_location(component["location"], f"{context}.location"),
        parameters=_parameters(component["parameters"], f"{context}.parameters"),
        ports=_ports(component["ports"], f"{context}.ports"),
        orientation=_integer(component.get("orientation", 0), f"{context}.orientation", nonnegative=True),
        canvas=_text(component.get("canvas", "Main"), f"{context}.canvas"),
        bounding_box=bounding,
        role=None if component.get("role") is None else _text(component["role"], f"{context}.role"),
    )


def _endpoint(value: Any, context: str) -> str:
    if isinstance(value, str):
        return _text(value, context)
    endpoint = _object(value, context)
    _keys(endpoint, {"component", "port"}, context)
    _required(endpoint, {"component", "port"}, context)
    return f"{_text(endpoint['component'], f'{context}.component')}:{_text(endpoint['port'], f'{context}.port')}"


def _parse_net(value: Any, index: int) -> MmcNetSpec:
    context = f"nets[{index}]"
    net = _object(value, context)
    _keys(net, _NET_KEYS, context)
    _required(net, {"logical_id", "kind", "endpoints"}, context)
    endpoints = tuple(_endpoint(item, f"{context}.endpoints[{endpoint_index}]") for endpoint_index, item in enumerate(_sequence(net["endpoints"], f"{context}.endpoints")))
    if len(endpoints) < 2:
        raise _invalid(f"{context}.endpoints requires at least two endpoints.", context=context)
    route = net.get("route", ())
    route_points: tuple[tuple[int, int], ...]
    if isinstance(route, Mapping):
        _keys(route, {"vertices"}, f"{context}.route")
        route = route.get("vertices", ())
    route_points = tuple(_location({"x": point[0], "y": point[1]}, f"{context}.route[{route_index}]") for route_index, point in enumerate(_sequence(route, f"{context}.route")) if isinstance(point, Sequence) and not isinstance(point, (str, bytes, bytearray)) and len(point) == 2)
    if route and len(route_points) != len(route):
        raise _invalid(f"{context}.route points must have two integer coordinates.", context=context)
    return MmcNetSpec(
        logical_id=_text(net["logical_id"], f"{context}.logical_id"),
        kind=_text(net["kind"], f"{context}.kind"),
        endpoints=endpoints,
        route=route_points,
        label=None if net.get("label") is None else _text(net["label"], f"{context}.label"),
    )


def _parse_output(value: Any, index: int) -> MmcOutputSpec:
    context = f"outputs[{index}]"
    output = _object(value, context)
    _keys(output, _OUTPUT_KEYS, context)
    _required(output, {"logical_id", "path", "units", "role"}, context)
    role = _text(output["role"], f"{context}.role")
    expected_units = _OUTPUT_UNITS.get(role)
    units = _text(output["units"], f"{context}.units")
    if expected_units is None:
        raise _invalid(f"{context}.role is not a declared fixed-profile output selector.", context=context)
    if units != expected_units:
        raise _invalid(f"{context}.units must be {expected_units} for role {role}.", context=context)
    call_id = output.get("call_id")
    return MmcOutputSpec(
        logical_id=_text(output["logical_id"], f"{context}.logical_id"),
        path=_text(output["path"], f"{context}.path"),
        units=units,
        role=role,
        call_id=None if call_id is None else _integer(call_id, f"{context}.call_id", positive=True),
        location=None if output.get("location") is None else _text(output["location"], f"{context}.location"),
        measurement=None if output.get("measurement") is None else _text(output["measurement"], f"{context}.measurement"),
    )


def _parse_sequence(value: Any, outputs: set[str]) -> tuple[MmcSequencePhase, ...]:
    records = _sequence(value, "sequence")
    if len(records) != len(_SEQUENCE_NAMES):
        raise _invalid("sequence must contain the six declared operating phases.", context="sequence")
    parsed: list[MmcSequencePhase] = []
    for index, item in enumerate(records):
        context = f"sequence[{index}]"
        phase = _object(item, context)
        _keys(phase, _SEQUENCE_KEYS, context)
        _required(phase, {"name", "order", "entry_condition", "exit_condition", "duration_s", "outputs"}, context)
        name = _text(phase["name"], f"{context}.name")
        if name != _SEQUENCE_NAMES[index] or _integer(phase["order"], f"{context}.order") != index + 1:
            raise _invalid("sequence phase names and order must match the fixed operating sequence.", context=context)
        phase_outputs = tuple(_text(output, f"{context}.outputs[{output_index}]") for output_index, output in enumerate(_sequence(phase["outputs"], f"{context}.outputs")))
        missing = sorted(set(phase_outputs) - outputs)
        if missing:
            raise _invalid("sequence references unknown output selectors.", context=context, outputs=missing)
        parsed.append(MmcSequencePhase(name=name, order=index + 1, entry_condition=_text(phase["entry_condition"], f"{context}.entry_condition"), exit_condition=_text(phase["exit_condition"], f"{context}.exit_condition"), duration_s=float(_number(phase["duration_s"], f"{context}.duration_s", positive=True)), outputs=phase_outputs, commands=_json_value(phase.get("commands", {}), f"{context}.commands")))
    return tuple(parsed)


def _parse_acceptance(value: Any, output_units: Mapping[str, str]) -> tuple[MmcAcceptanceCheck, ...]:
    records = _sequence(value, "acceptance_checks")
    if len(records) != len(_ACCEPTANCE_NAMES):
        raise _invalid("acceptance_checks must contain exactly four required windows.", context="acceptance_checks")
    parsed: list[MmcAcceptanceCheck] = []
    for index, item in enumerate(records):
        context = f"acceptance_checks[{index}]"
        check = _object(item, context)
        _keys(check, _ACCEPTANCE_KEYS, context)
        _required(check, {"name", "kind", "required", "expected", "units", "comparison_window"}, context)
        name = _text(check["name"], f"{context}.name")
        if name != _ACCEPTANCE_NAMES[index]:
            raise _invalid("acceptance windows must be precharge_ready, forward_steady, power_reversal, reverse_steady.", context=context)
        if check["required"] is not True:
            raise _invalid(f"{context}.required must be true for the fixed acceptance contract.", context=context)
        expected = _object(check["expected"], f"{context}.expected")
        if "channels" not in expected:
            raise _invalid(f"{context}.expected requires channels.", context=context)
        channels = tuple(
            _text(channel, f"{context}.expected.channels[{channel_index}]")
            for channel_index, channel in enumerate(
                _sequence(expected["channels"], f"{context}.expected.channels")
            )
        )
        if not channels:
            raise _invalid(f"{context}.expected.channels must not be empty.", context=context)
        if len(set(channels)) != len(channels):
            raise _invalid(f"{context}.expected.channels must be unique.", context=context)
        units = _text(check["units"], f"{context}.units")
        for channel in channels:
            declared_units = output_units.get(channel)
            if declared_units is None:
                raise _invalid(f"{context}.expected.channels references an unknown output selector.", context=context, channel=channel)
            if declared_units != units:
                raise _invalid(
                    f"{context}.expected.channels units must match {units}.",
                    context=context,
                    channel=channel,
                    expected_units=units,
                    observed_units=declared_units,
                )
        window = _sequence(check["comparison_window"], f"{context}.comparison_window")
        if len(window) != 2:
            raise _invalid(f"{context}.comparison_window requires two numbers.", context=context)
        start = float(_number(window[0], f"{context}.comparison_window[0]", nonnegative=True))
        end = float(_number(window[1], f"{context}.comparison_window[1]", positive=True))
        if end <= start:
            raise _invalid(f"{context}.comparison_window must be increasing.", context=context)
        parsed.append(MmcAcceptanceCheck(name=name, kind=_text(check["kind"], f"{context}.kind"), required=True, expected=_json_value(expected, f"{context}.expected"), units=units, comparison_window=(start, end), severity=None if check.get("severity") is None else _text(check["severity"], f"{context}.severity"), rationale=None if check.get("rationale") is None else _text(check["rationale"], f"{context}.rationale")))
    return tuple(parsed)


def parse_blueprint(data: Mapping[str, Any]) -> MmcBlueprint:
    """Parse the fixed Stage A blueprint without side effects."""
    blueprint = _object(data, "blueprint")
    _keys(blueprint, _TOP_LEVEL_KEYS, "blueprint")
    _required(blueprint, {"schema_version", "name", "profile", "nominal_vdc_kv", "nominal_power_mw", "settings", "stations", "components", "nets", "outputs", "control_contract", "sequence", "acceptance_checks"}, "blueprint")
    if _integer(blueprint["schema_version"], "schema_version", positive=True) != 1:
        raise _invalid("schema_version must be 1.", context="schema_version")
    profile = _text(blueprint["profile"], "profile")
    if profile != SUPPORTED_BLUEPRINT:
        raise _invalid(f"profile must be {SUPPORTED_BLUEPRINT}.", context="profile")
    name = _text(blueprint["name"], "name")
    if name != SUPPORTED_BLUEPRINT:
        raise _invalid(f"name must be {SUPPORTED_BLUEPRINT}.", context="name")
    nominal_vdc = float(_number(blueprint["nominal_vdc_kv"], "nominal_vdc_kv", positive=True))
    nominal_power = float(_number(blueprint["nominal_power_mw"], "nominal_power_mw", positive=True))
    settings_value = _object(blueprint["settings"], "settings")
    _keys(settings_value, _SETTINGS_KEYS, "settings")
    _required(settings_value, {"time_step_s", "output_step_s", "simulation_duration_s"}, "settings")
    settings = {key: _json_value(item, f"settings.{key}") for key, item in settings_value.items()}
    for key in ("time_step_s", "output_step_s", "simulation_duration_s"):
        _number(settings[key], f"settings.{key}", positive=True)
    for key in {"compiler_target", "compiler", "pscad_version", "project_type", "simulation_set"} & set(settings):
        _text(settings[key], f"settings.{key}")
    for key in {"output_enabled", "x64"} & set(settings):
        if not isinstance(settings[key], bool):
            raise _invalid(f"settings.{key} must be a boolean.", context=f"settings.{key}")

    station_values = _sequence(blueprint["stations"], "stations")
    if len(station_values) != 2:
        raise _invalid("stations must contain exactly two stations.", context="stations")
    stations = tuple(_parse_station(item, index) for index, item in enumerate(station_values))
    if {station.role for station in stations} != {"P", "VDC"}:
        raise _invalid("stations must contain exactly roles P and VDC.", context="stations")
    station_ids = [station.logical_id for station in stations]
    if len(set(station_ids)) != len(station_ids):
        raise _invalid("station logical IDs must be unique.", context="stations")
    arm_ids = [arm.logical_id for station in stations for arm in station.arms]
    if len(set(arm_ids)) != len(arm_ids):
        raise _invalid("arm logical IDs must be unique across both stations.", context="stations")

    component_values = _sequence(blueprint["components"], "components")
    components = tuple(_parse_component(item, index) for index, item in enumerate(component_values))
    component_ids = [component.logical_id for component in components]
    if len(set(component_ids)) != len(component_ids):
        raise _invalid("component logical IDs must be unique.", context="components")
    nets = tuple(_parse_net(item, index) for index, item in enumerate(_sequence(blueprint["nets"], "nets")))
    net_ids = [net.logical_id for net in nets]
    if len(set(net_ids)) != len(net_ids):
        raise _invalid("net logical IDs must be unique.", context="nets")
    outputs = tuple(_parse_output(item, index) for index, item in enumerate(_sequence(blueprint["outputs"], "outputs")))
    output_ids = [output.logical_id for output in outputs]
    if len(set(output_ids)) != len(output_ids):
        raise _invalid("output logical IDs must be unique.", context="outputs")
    output_ids_set = set(output_ids)

    control = _parse_control(blueprint["control_contract"], "control_contract", require_equations=True)
    if control.role not in {"link", "system"}:
        raise _invalid("control_contract.role must be link or system.", context="control_contract")
    sequence = _parse_sequence(blueprint["sequence"], output_ids_set)
    acceptance = _parse_acceptance(
        blueprint["acceptance_checks"],
        {output.logical_id: output.units for output in outputs},
    )
    provenance = _json_value(blueprint.get("provenance", {}), "provenance")
    topology = None if blueprint.get("topology") is None else _text(blueprint["topology"], "topology")
    model = None if blueprint.get("model") is None else _text(blueprint["model"], "model")
    equation_version = None if blueprint.get("equation_version") is None else _text(blueprint["equation_version"], "equation_version")
    return MmcBlueprint(schema_version=1, name=name, profile=profile, nominal_vdc_kv=nominal_vdc, nominal_power_mw=nominal_power, settings=settings, stations=stations, components=components, nets=nets, outputs=outputs, control_contract=control, sequence=sequence, acceptance_checks=acceptance, model=model, topology=topology, equation_version=equation_version, provenance=provenance)


parse_mmc_blueprint = parse_blueprint


__all__ = ["SUPPORTED_BLUEPRINT", "parse_blueprint", "parse_mmc_blueprint"]
