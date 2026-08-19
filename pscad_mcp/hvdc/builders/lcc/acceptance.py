"""Golden waveform and physical acceptance for LCC build outputs."""

from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ....core.backend.base import BackendError


MAX_CHANNEL_SAMPLES = 1_000_000
PASS = "PASS"
FAIL = "FAIL"
INCOMPLETE = "INCOMPLETE_ANALYSIS"
_OPERATION = "evaluate_lcc_acceptance"


@dataclass(frozen=True)
class _Channel:
    name: str
    time: list[float]
    values: list[float]
    units: str | None


class _EvidenceError(Exception):
    def __init__(
        self,
        reason: str,
        *,
        status: str = "invalid",
        channel: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.channel = channel
        self.details = dict(details or {})


def _backend_error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", _OPERATION, details)


def _invalid(message: str, **details: Any) -> BackendError:
    return _backend_error("LCC_ACCEPTANCE_INVALID", message, **details)


def _incomplete(message: str, **details: Any) -> BackendError:
    return _backend_error("LCC_ACCEPTANCE_INCOMPLETE", message, **details)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{field} must be a finite number.", field=field)
    number = float(value)
    if not math.isfinite(number):
        raise _invalid(f"{field} must be a finite number.", field=field)
    return number


def _finite_evidence_float(value: Any, reason: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _EvidenceError(reason)
    number = float(value)
    if not math.isfinite(number):
        raise _EvidenceError(reason)
    return number


def _float_list(values: Any, *, reason: str) -> list[float]:
    if not _is_sequence(values):
        raise _EvidenceError(reason)
    return [_finite_evidence_float(value, reason) for value in values]


def _validate_time_values(time: Any, values: Any, *, direct: bool = False) -> tuple[list[float], list[float]]:
    try:
        times = _float_list(time, reason="duplicate or non-monotonic time")
        numbers = _float_list(values, reason="non-finite sample")
    except _EvidenceError as error:
        if direct:
            raise _incomplete(str(error), reason=error.reason) from error
        raise
    if not numbers:
        if direct:
            raise _incomplete("vectors must not be empty.", reason="empty samples")
        raise _EvidenceError("empty samples")
    if len(times) != len(numbers):
        if direct:
            raise _invalid("time and values must have equal lengths.", time=len(times), values=len(numbers))
        raise _EvidenceError("inconsistent domains", details={"time_samples": len(times), "value_samples": len(numbers)})
    if max(len(times), len(numbers)) > MAX_CHANNEL_SAMPLES:
        if direct:
            raise _incomplete("channel sample limit exceeded.", reason="too many samples", limit=MAX_CHANNEL_SAMPLES)
        raise _EvidenceError(
            "too many samples",
            details={"limit": MAX_CHANNEL_SAMPLES, "observed": max(len(times), len(numbers))},
        )
    if any(right <= left for left, right in zip(times, times[1:])):
        if direct:
            raise _incomplete("time values must be strictly increasing.", reason="duplicate or non-monotonic time")
        raise _EvidenceError("duplicate or non-monotonic time")
    return times, numbers


def _percentile95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise _invalid("vectors must not be empty.")
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * 0.95
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def normalized_errors(actual: list[float], golden: list[float], scale_floor: float) -> tuple[float, float]:
    """Return NRMSE and normalized maximum error using the contract formula."""

    floor = _finite_float(scale_floor, "scale_floor")
    if floor < 0:
        raise _invalid("scale_floor must be non-negative.", scale_floor=scale_floor)
    if len(actual) != len(golden) or not actual:
        raise _invalid("actual and golden vectors must be non-empty and equal length.", actual=len(actual), golden=len(golden))
    actual_values = [_finite_float(value, "actual") for value in actual]
    golden_values = [_finite_float(value, "golden") for value in golden]
    scale = max(_percentile95([abs(value) for value in golden_values]), floor)
    if scale <= 0:
        raise _invalid("normalization scale must be positive.", scale=scale)
    squared = [(left - right) ** 2 for left, right in zip(actual_values, golden_values)]
    nrmse = math.sqrt(sum(squared) / len(squared)) / scale
    maximum = max(abs(left - right) for left, right in zip(actual_values, golden_values)) / scale
    return nrmse, maximum


def _positive_zero_crossing(time: Sequence[float], values: Sequence[float]) -> float:
    if len(time) < 2:
        raise _incomplete("at least two samples are required for alignment.", reason="alignment failed")
    if values[0] == 0.0 and values[1] > values[0]:
        return float(time[0])
    for index in range(1, len(values)):
        left = values[index - 1]
        right = values[index]
        if left <= 0.0 <= right and right > left:
            if right == left:
                continue
            fraction = (0.0 - left) / (right - left)
            return float(time[index - 1] + fraction * (time[index] - time[index - 1]))
    raise _incomplete("positive-going zero crossing was not found.", reason="alignment failed")


def align_positive_zero_crossing(
    actual_time: Sequence[float],
    actual_values: Sequence[float],
    golden_time: Sequence[float],
    golden_values: Sequence[float],
    *,
    frequency_hz: float,
    max_cycles: float,
) -> dict[str, Any]:
    """Measure actual-minus-golden shift from the first positive-going zero crossing."""

    frequency = _finite_float(frequency_hz, "frequency_hz")
    cycles = _finite_float(max_cycles, "max_cycles")
    if frequency <= 0 or cycles <= 0:
        raise _invalid("frequency_hz and max_cycles must be positive.", frequency_hz=frequency_hz, max_cycles=max_cycles)
    actual_t, actual_v = _validate_time_values(actual_time, actual_values, direct=True)
    golden_t, golden_v = _validate_time_values(golden_time, golden_values, direct=True)
    actual_crossing = _positive_zero_crossing(actual_t, actual_v)
    golden_crossing = _positive_zero_crossing(golden_t, golden_v)
    max_shift = cycles / frequency
    shift = actual_crossing - golden_crossing
    if abs(shift) > max_shift:
        raise _incomplete(
            "alignment shift exceeds the contract bound.",
            reason="alignment failed",
            shift_seconds=shift,
            max_shift_seconds=max_shift,
        )
    return {
        "status": "observed",
        "rule": "positive_zero_crossing",
        "shift_seconds": shift,
        "actual_crossing_seconds": actual_crossing,
        "golden_crossing_seconds": golden_crossing,
        "max_shift_seconds": max_shift,
    }


def interpolate_to_grid(
    source_time: Sequence[float],
    source_values: Sequence[float],
    target_time: Sequence[float],
) -> list[float]:
    """Linearly interpolate source values at target times without extrapolation."""

    source_t, source_v = _validate_time_values(source_time, source_values, direct=True)
    targets = [_finite_float(value, "target_time") for value in target_time]
    if not targets:
        return []
    start = source_t[0]
    end = source_t[-1]
    if targets[0] < start or targets[-1] > end:
        raise _incomplete(
            "target grid would require extrapolation.",
            reason="inconsistent domains",
            source_domain=[start, end],
            target_domain=[targets[0], targets[-1]],
        )
    interpolated: list[float] = []
    for target in targets:
        if target == end:
            interpolated.append(source_v[-1])
            continue
        right = bisect.bisect_left(source_t, target)
        if right < len(source_t) and source_t[right] == target:
            interpolated.append(source_v[right])
            continue
        if right == 0 or right >= len(source_t):
            raise _incomplete("target grid would require extrapolation.", reason="inconsistent domains")
        left = right - 1
        width = source_t[right] - source_t[left]
        fraction = (target - source_t[left]) / width
        interpolated.append(source_v[left] * (1.0 - fraction) + source_v[right] * fraction)
    return interpolated


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field} must be a non-empty string.", field=field)
    return value.strip()


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _text(value, field)


def _required(value: Mapping[str, Any]) -> bool:
    required = value.get("required", True)
    if not isinstance(required, bool):
        raise _invalid("required must be a boolean.", required=required)
    return required


def _global_time(payload: Mapping[str, Any]) -> Any:
    return payload.get("time", payload.get("domain"))


def _canonical_channels(payload: Any, label: str) -> dict[str, _Channel]:
    if payload in (None, {}):
        return {}
    if not isinstance(payload, Mapping):
        raise _invalid(f"{label} must be a mapping.", payload=label)
    global_time = _global_time(payload)
    raw_channels = payload.get("channels")
    channels: dict[str, _Channel] = {}
    if raw_channels is None:
        raw_channels = {
            key: value
            for key, value in payload.items()
            if key not in {"time", "domain", "metadata"} and isinstance(value, (Mapping, Sequence))
        }
    if isinstance(raw_channels, Mapping):
        iterable = raw_channels.items()
    elif _is_sequence(raw_channels):
        prepared: list[tuple[str, Any]] = []
        for index, item in enumerate(raw_channels):
            if not isinstance(item, Mapping):
                raise _invalid(f"{label}.channels entries must be mappings.", index=index)
            name = item.get("name", item.get("path", item.get("channel")))
            prepared.append((_text(name, f"{label}.channels[{index}].name"), item))
        iterable = prepared
    else:
        raise _invalid(f"{label}.channels must be a mapping or list.", payload=label)
    for raw_name, raw_value in iterable:
        name = _text(raw_name, f"{label}.channels.name")
        if isinstance(raw_value, Mapping):
            values = raw_value.get("values", raw_value.get("samples"))
            time = raw_value.get("time", raw_value.get("domain", global_time))
            units = _optional_text(raw_value.get("units"), f"{label}.{name}.units")
        else:
            values = raw_value
            time = global_time
            units = None
        if time is None or not _is_sequence(time):
            raise _EvidenceError("inconsistent domains", channel=name)
        if not _is_sequence(values):
            raise _EvidenceError("empty samples", channel=name)
        times = list(time)
        numbers = list(values)
        try:
            times, numbers = _validate_time_values(times, numbers)
        except _EvidenceError as error:
            raise _EvidenceError(
                error.reason,
                status=error.status,
                channel=name,
                details=error.details,
            ) from error
        channels[name] = _Channel(name=name, time=times, values=numbers, units=units)
    return channels


def _channel(channels: Mapping[str, _Channel], name: str) -> _Channel:
    if name not in channels:
        raise _EvidenceError("missing channel", status="missing", channel=name)
    return channels[name]


def _require_exact_units(channel: _Channel, expected: str) -> None:
    if channel.units != expected:
        raise _EvidenceError(
            "unit mismatch",
            channel=channel.name,
            details={"expected_units": expected, "observed_units": channel.units},
        )


_UNIT_TO_SI = {
    "V": ("voltage", 1.0),
    "kV": ("voltage", 1_000.0),
    "A": ("current", 1.0),
    "kA": ("current", 1_000.0),
    "W": ("power", 1.0),
    "kW": ("power", 1_000.0),
    "MW": ("power", 1_000_000.0),
    "VAr": ("reactive_power", 1.0),
    "kVAr": ("reactive_power", 1_000.0),
    "MVAr": ("reactive_power", 1_000_000.0),
    "deg": ("angle", 1.0),
}


def _convert(values: Sequence[float], from_units: str | None, to_units: str, channel: str) -> list[float]:
    if from_units not in _UNIT_TO_SI or to_units not in _UNIT_TO_SI:
        raise _EvidenceError("unit mismatch", channel=channel, details={"expected_units": to_units, "observed_units": from_units})
    from_kind, from_scale = _UNIT_TO_SI[from_units]
    to_kind, to_scale = _UNIT_TO_SI[to_units]
    if from_kind != to_kind:
        raise _EvidenceError("unit mismatch", channel=channel, details={"expected_units": to_units, "observed_units": from_units})
    return [value * from_scale / to_scale for value in values]


def _validated_window(window: Any, *, field: str, channel: str | None = None) -> tuple[float, float]:
    details: dict[str, Any] = {"field": field}
    if channel is not None:
        details["channel"] = channel
    if not _is_sequence(window) or len(window) != 2:
        raise _invalid(f"{field} must contain two numbers.", **details)
    start = _finite_float(window[0], f"{field}[0]")
    end = _finite_float(window[1], f"{field}[1]")
    if end < start:
        raise _invalid(f"{field} end must be greater than or equal to start.", **details)
    return start, end


def _convert_power_from_watts(values: Sequence[float], to_units: str) -> list[float]:
    if to_units not in _UNIT_TO_SI or _UNIT_TO_SI[to_units][0] != "power":
        raise _EvidenceError("unit mismatch", details={"expected_units": to_units})
    scale = _UNIT_TO_SI[to_units][1]
    return [value / scale for value in values]


def _window(channel: _Channel, window: Sequence[Any] | None, units: str | None = None) -> tuple[list[float], list[float]]:
    channel_time, channel_values = _validate_time_values(channel.time, channel.values)
    if window is None:
        selected_time = list(channel_time)
        selected_values = list(channel_values)
    else:
        start, end = _validated_window(window, field="window", channel=channel.name)
        pairs = [(time, value) for time, value in zip(channel_time, channel_values) if start <= time <= end]
        if not pairs:
            raise _EvidenceError("inconsistent domains", channel=channel.name, details={"window": [start, end]})
        selected_time = [time for time, _ in pairs]
        selected_values = [value for _, value in pairs]
    if units is not None:
        selected_values = _convert(selected_values, channel.units, units, channel.name)
    return selected_time, selected_values


def _require_identical_domains(
    domains: Sequence[tuple[str, Sequence[float]]],
    *,
    check: str | None = None,
) -> None:
    """Require all referenced channels to describe the same usable time grid."""

    if not domains:
        raise _EvidenceError("inconsistent domains", details={"check": check} if check else {})
    reference_name, reference_time = domains[0]
    if any(not math.isfinite(time) for time in reference_time) or any(
        right <= left for left, right in zip(reference_time, reference_time[1:])
    ):
        raise _EvidenceError("inconsistent domains", details={"check": check} if check else {})
    for name, time in domains[1:]:
        if any(not math.isfinite(value) for value in time) or any(
            right <= left for left, right in zip(time, time[1:])
        ):
            raise _EvidenceError(
                "inconsistent domains",
                details={"check": check, "channels": [reference_name, name]} if check else {"channels": [reference_name, name]},
            )
        if len(time) != len(reference_time) or any(left != right for left, right in zip(reference_time, time)):
            details: dict[str, Any] = {"channels": [reference_name, name]}
            if check:
                details["check"] = check
            raise _EvidenceError("inconsistent domains", details=details)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _rms(values: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def _aggregate(values: Sequence[float], mode: str) -> float:
    if mode == "mean":
        return _mean(values)
    if mode == "min":
        return min(values)
    if mode == "max":
        return max(values)
    if mode == "rms":
        return _rms(values)
    raise _invalid("unsupported aggregation.", aggregation=mode)


def _ok_bounds(value: float, check: Mapping[str, Any]) -> bool:
    lower = check.get("min")
    upper = check.get("max")
    if lower is not None and value < _finite_float(lower, "min"):
        return False
    if upper is not None and value > _finite_float(upper, "max"):
        return False
    return True


def _check_base(check: Mapping[str, Any], index: int) -> dict[str, Any]:
    return {
        "name": _text(check.get("name", f"check_{index}"), f"physical_checks[{index}].name"),
        "kind": _text(check.get("kind"), f"physical_checks[{index}].kind"),
        "required": _required(check),
        "status": "missing",
        "outcome": INCOMPLETE,
    }


def _observed_stats(values: Sequence[float]) -> dict[str, float]:
    return {"mean": _mean(values), "min": min(values), "max": max(values)}


def _physical_dc(check: Mapping[str, Any], samples: Mapping[str, _Channel]) -> tuple[str, dict[str, Any]]:
    name = _text(check.get("channel"), "channel")
    units = _text(check.get("units"), "units")
    _, values = _window(_channel(samples, name), check.get("window"), units)
    polarity = check.get("polarity")
    if polarity not in {None, "positive", "negative"}:
        raise _invalid("polarity must be positive or negative.", polarity=polarity)
    if polarity == "positive" and any(value <= 0 for value in values):
        passed = False
    elif polarity == "negative" and any(value >= 0 for value in values):
        passed = False
    else:
        passed = True
    mode = _text(check.get("aggregation", "mean"), "aggregation")
    observed = _aggregate([abs(value) for value in values], mode)
    passed = passed and _ok_bounds(observed, check)
    return "observed", {"observed": {**_observed_stats(values), "aggregated": observed, "units": units}, "passed": passed}


def _physical_pdc(check: Mapping[str, Any], samples: Mapping[str, _Channel]) -> tuple[str, dict[str, Any]]:
    voltage_name = _text(check.get("voltage_channel"), "voltage_channel")
    current_name = _text(check.get("current_channel"), "current_channel")
    power_name = _text(check.get("power_channel"), "power_channel")
    power_units = _text(check.get("power_units"), "power_units")
    voltage_time, voltage = _window(
        _channel(samples, voltage_name),
        check.get("window"),
        _text(check.get("voltage_units"), "voltage_units"),
    )
    current_time, current = _window(
        _channel(samples, current_name),
        check.get("window"),
        _text(check.get("current_units"), "current_units"),
    )
    power_time, reported_power = _window(_channel(samples, power_name), check.get("window"), power_units)
    _require_identical_domains(
        [(voltage_name, voltage_time), (current_name, current_time), (power_name, power_time)],
        check=check.get("name"),
    )
    voltage_si = _convert(voltage, check.get("voltage_units"), "V", voltage_name)
    current_si = _convert(current, check.get("current_units"), "A", current_name)
    derived = _convert_power_from_watts([left * right for left, right in zip(voltage_si, current_si)], power_units)
    errors = [abs(left - right) for left, right in zip(derived, reported_power)]
    max_error = max(errors)
    passed = True
    if check.get("max_abs") is not None:
        passed = passed and max_error <= _finite_float(check["max_abs"], "max_abs")
    if check.get("max_percent") is not None:
        baseline = max(abs(_mean(reported_power)), 1e-12)
        passed = passed and (max_error / baseline * 100.0) <= _finite_float(check["max_percent"], "max_percent")
    return (
        "derived",
        {
            "observed": {
                "derived_power_mean": _mean(derived),
                "reported_power_mean": _mean(reported_power),
                "max_abs_error": max_error,
                "units": power_units,
            },
            "passed": passed,
        },
    )


def _physical_power_balance(check: Mapping[str, Any], samples: Mapping[str, _Channel]) -> tuple[str, dict[str, Any]]:
    units = _text(check.get("units"), "units")
    rectifier_name = _text(check.get("rectifier_power_channel"), "rectifier_power_channel")
    inverter_name = _text(check.get("inverter_power_channel"), "inverter_power_channel")
    rectifier_time, rectifier = _window(_channel(samples, rectifier_name), check.get("window"), units)
    inverter_time, inverter = _window(_channel(samples, inverter_name), check.get("window"), units)
    _require_identical_domains(
        [(rectifier_name, rectifier_time), (inverter_name, inverter_time)],
        check=check.get("name"),
    )
    imbalance_values = [abs(left + right) for left, right in zip(rectifier, inverter)]
    imbalance = max(imbalance_values)
    allowance = check.get("loss_allowance", check.get("max_abs"))
    if allowance is None:
        raise _invalid("terminal_power_balance requires loss_allowance or max_abs.")
    passed = imbalance <= _finite_float(allowance, "loss_allowance")
    return (
        "derived",
        {
            "observed": {
                "rectifier_power_mean": _mean(rectifier),
                "inverter_power_mean": _mean(inverter),
                "imbalance": imbalance,
                "units": units,
            },
            "passed": passed,
        },
    )


def _physical_angle(check: Mapping[str, Any], samples: Mapping[str, _Channel]) -> tuple[str, dict[str, Any]]:
    name = _text(check.get("channel"), "channel")
    units = _text(check.get("units"), "units")
    _, values = _window(_channel(samples, name), check.get("window"), units)
    stats = _observed_stats(values)
    passed = _ok_bounds(stats["min"], {"min": check.get("min")}) and _ok_bounds(stats["max"], {"max": check.get("max")})
    return "observed", {"observed": {**stats, "units": units}, "passed": passed}


def _physical_ripple(check: Mapping[str, Any], samples: Mapping[str, _Channel]) -> tuple[str, dict[str, Any]]:
    name = _text(check.get("channel"), "channel")
    units = _text(check.get("units"), "units")
    _, values = _window(_channel(samples, name), check.get("window"), units)
    peak_to_peak = max(values) - min(values)
    mean_abs = abs(_mean(values))
    if mean_abs == 0 and check.get("max_percent") is not None:
        raise _EvidenceError("inconsistent domains", channel=name, details={"reason": "zero mean ripple baseline"})
    percent = None if mean_abs == 0 else peak_to_peak / mean_abs * 100.0
    passed = True
    if check.get("max_abs") is not None:
        passed = passed and peak_to_peak <= _finite_float(check["max_abs"], "max_abs")
    if check.get("max_percent") is not None:
        passed = passed and percent is not None and percent <= _finite_float(check["max_percent"], "max_percent")
    return (
        "observed",
        {
            "observed": {"peak_to_peak": peak_to_peak, "percent": percent, "units": units},
            "passed": passed,
        },
    )


def _physical_control_error(check: Mapping[str, Any], samples: Mapping[str, _Channel]) -> tuple[str, dict[str, Any]]:
    actual_name = _text(check.get("actual_channel"), "actual_channel")
    units = _text(check.get("units"), "units")
    actual_time, actual = _window(_channel(samples, actual_name), check.get("window"), units)
    if check.get("target_channel") is not None:
        target_name = _text(check.get("target_channel"), "target_channel")
        target_time, target = _window(_channel(samples, target_name), check.get("window"), units)
        _require_identical_domains(
            [(actual_name, actual_time), (target_name, target_time)],
            check=check.get("name"),
        )
    elif check.get("target") is not None:
        target = [_finite_float(check["target"], "target") for _ in actual]
    else:
        raise _invalid("steady_state_control_error requires target or target_channel.")
    errors = [left - right for left, right in zip(actual, target)]
    max_abs = max(abs(value) for value in errors)
    passed = max_abs <= _finite_float(check.get("max_abs"), "max_abs")
    return (
        "derived",
        {
            "observed": {"mean_error": _mean(errors), "max_abs_error": max_abs, "units": units},
            "passed": passed,
        },
    )


_PHYSICAL_DISPATCH = {
    "dc_magnitude_polarity": _physical_dc,
    "pdc_product": _physical_pdc,
    "terminal_power_balance": _physical_power_balance,
    "angle_interval": _physical_angle,
    "ripple": _physical_ripple,
    "steady_state_control_error": _physical_control_error,
}


def _error_record(reason: str, *, channel: str | None = None, check: str | None = None, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"code": "LCC_ACCEPTANCE_INCOMPLETE", "reason": reason}
    if channel is not None:
        record["channel"] = channel
    if check is not None:
        record["check"] = check
    if details:
        record.update(details)
    return record


def _failure_record(reason: str, *, check: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"code": "LCC_ACCEPTANCE_FAILED", "reason": reason, "check": check}
    if details:
        record.update(details)
    return record


def _golden_declarations(contract: Mapping[str, Any], golden_channels: Mapping[str, _Channel]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    golden_contract = contract.get("golden", {})
    if golden_contract is None:
        golden_contract = {}
    if not isinstance(golden_contract, Mapping):
        raise _invalid("golden must be a mapping.")
    raw_channels = golden_contract.get("channels", contract.get("golden_channels"))
    if raw_channels is None:
        raw_channels = [{"name": name} for name in sorted(golden_channels)]
    declarations: list[dict[str, Any]] = []
    if isinstance(raw_channels, Mapping):
        iterable = []
        for name, value in raw_channels.items():
            item = dict(value) if isinstance(value, Mapping) else {}
            item["name"] = name
            iterable.append(item)
    elif _is_sequence(raw_channels):
        iterable = raw_channels
    else:
        raise _invalid("golden channels must be a mapping or list.")
    for index, item in enumerate(iterable):
        if isinstance(item, str):
            declarations.append({"name": item})
            continue
        if not isinstance(item, Mapping):
            raise _invalid("golden channel declarations must be mappings.", index=index)
        declarations.append(dict(item))
    return dict(golden_contract), declarations


def _target_grid(channel: _Channel, window: Sequence[Any] | None) -> tuple[list[float], list[float]]:
    channel_time, channel_values = _validate_time_values(channel.time, channel.values)
    if window is None:
        return list(channel_time), list(channel_values)
    start, end = _validated_window(window, field="comparison_window")
    pairs = [(time, value) for time, value in zip(channel_time, channel_values) if start <= time <= end]
    if not pairs:
        raise _EvidenceError("inconsistent domains", channel=channel.name, details={"window": [start, end]})
    return [time for time, _ in pairs], [value for _, value in pairs]


def _evaluate_golden(
    samples: Mapping[str, _Channel],
    golden: Mapping[str, _Channel],
    contract: Mapping[str, Any],
    result: dict[str, Any],
) -> None:
    golden_contract, declarations = _golden_declarations(contract, golden)
    result["canonical"]["golden_channels"] = [_text(item.get("name"), "golden channel name") for item in declarations]
    comparison_window = golden_contract.get("comparison_window")
    if comparison_window is not None:
        _validated_window(comparison_window, field="golden.comparison_window")
    for index, declaration in enumerate(declarations):
        declaration_window = declaration.get("comparison_window", comparison_window)
        if declaration_window is not None:
            _validated_window(declaration_window, field=f"golden.channels[{index}].comparison_window")
    if not declarations:
        return
    alignment_contract = golden_contract.get("alignment")
    shift = 0.0
    alignment_failed: _EvidenceError | None = None
    if alignment_contract is not None:
        if not isinstance(alignment_contract, Mapping):
            raise _invalid("alignment must be a mapping.")
        channel_name = _text(alignment_contract.get("channel"), "alignment.channel")
        rule = _text(alignment_contract.get("rule"), "alignment.rule")
        if rule != "positive_zero_crossing":
            raise _invalid("unsupported alignment rule.", rule=rule)
        try:
            actual_channel = _channel(samples, channel_name)
            golden_channel = _channel(golden, channel_name)
            if golden_channel.units is not None:
                _require_exact_units(actual_channel, golden_channel.units)
            result["alignment"] = align_positive_zero_crossing(
                actual_channel.time,
                actual_channel.values,
                golden_channel.time,
                golden_channel.values,
                frequency_hz=_finite_float(alignment_contract.get("frequency_hz"), "frequency_hz"),
                max_cycles=_finite_float(alignment_contract.get("max_cycles", 1.0), "max_cycles"),
            )
            shift = result["alignment"]["shift_seconds"]
        except BackendError as error:
            alignment_failed = _EvidenceError(
                error.details.get("reason", "alignment failed"),
                status="invalid",
                channel=channel_name,
                details={key: value for key, value in error.details.items() if key != "reason"},
            )
        except _EvidenceError as error:
            alignment_failed = error
    else:
        result["alignment"] = {"status": "missing", "rule": None, "shift_seconds": 0.0}

    if alignment_failed is not None:
        result["alignment"] = {
            "status": alignment_failed.status,
            "rule": "positive_zero_crossing",
            "shift_seconds": None,
            "channel": alignment_failed.channel,
        }
        result["errors"].append(_error_record(alignment_failed.reason, channel=alignment_failed.channel, details=alignment_failed.details))

    for index, declaration in enumerate(declarations):
        name = _text(declaration.get("name"), f"golden.channels[{index}].name")
        required = _required(declaration)
        check_result: dict[str, Any] = {
            "name": name,
            "kind": "golden",
            "required": required,
            "status": "missing",
            "outcome": INCOMPLETE,
        }
        if alignment_failed is not None:
            check_result["status"] = alignment_failed.status
            result["golden_checks"].append(check_result)
            continue
        try:
            actual_channel = _channel(samples, name)
            golden_channel = _channel(golden, name)
            expected_units = declaration.get("units", golden_channel.units)
            if expected_units is not None:
                expected_units = _text(expected_units, f"golden.channels[{index}].units")
                _require_exact_units(actual_channel, expected_units)
                _require_exact_units(golden_channel, expected_units)
            target_time, golden_values = _target_grid(golden_channel, declaration.get("comparison_window", comparison_window))
            shifted_actual_time = [time - shift for time in actual_channel.time]
            actual_values = interpolate_to_grid(shifted_actual_time, actual_channel.values, target_time)
            nrmse, maximum = normalized_errors(
                actual_values,
                golden_values,
                _finite_float(declaration.get("scale_floor", golden_contract.get("scale_floor", 0.0)), "scale_floor"),
            )
            metrics = {"nrmse": nrmse, "max_error": maximum, "samples": len(target_time)}
            check_result.update({"status": "observed", "metrics": metrics})
            nrmse_limit = _finite_float(declaration.get("nrmse_limit", golden_contract.get("nrmse_limit")), "nrmse_limit")
            max_limit = _finite_float(declaration.get("max_error_limit", golden_contract.get("max_error_limit")), "max_error_limit")
            passed = nrmse <= nrmse_limit and maximum <= max_limit
            check_result["outcome"] = PASS if passed else FAIL
            check_result["expected"] = {
                "units": expected_units,
                "nrmse_limit": nrmse_limit,
                "max_error_limit": max_limit,
            }
            if not passed:
                result["errors"].append(_failure_record("golden error limit exceeded", check=name, details=metrics))
        except BackendError as error:
            reason = error.details.get("reason", "inconsistent domains") if error.code == "LCC_ACCEPTANCE_INCOMPLETE" else "invalid golden comparison"
            check_result["status"] = "invalid"
            result["errors"].append(_error_record(reason, channel=name, check=name, details={key: value for key, value in error.details.items() if key != "reason"}))
        except _EvidenceError as error:
            check_result["status"] = error.status
            result["errors"].append(_error_record(error.reason, channel=error.channel or name, check=name, details=error.details))
        result["golden_checks"].append(check_result)


def _physical_declarations(contract: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = contract.get("physical_checks", ())
    if raw is None:
        return []
    if not _is_sequence(raw):
        raise _invalid("physical_checks must be a list.")
    declarations: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise _invalid("physical check declarations must be mappings.", index=index)
        declarations.append(item)
    return declarations


def _evaluate_physical(samples: Mapping[str, _Channel], contract: Mapping[str, Any], result: dict[str, Any]) -> None:
    for index, check in enumerate(_physical_declarations(contract)):
        record = _check_base(check, index)
        dispatch = _PHYSICAL_DISPATCH.get(record["kind"])
        if dispatch is None:
            raise _invalid("unsupported physical check kind.", kind=record["kind"])
        try:
            status, payload = dispatch(check, samples)
            record["status"] = status
            record["observed"] = payload["observed"]
            expected = {key: check[key] for key in ("min", "max", "target", "max_abs", "max_percent", "loss_allowance", "polarity") if key in check}
            if expected:
                record["expected"] = expected
            record["outcome"] = PASS if payload["passed"] else FAIL
            if not payload["passed"]:
                result["errors"].append(_failure_record("physical bound violated", check=record["name"], details={"kind": record["kind"]}))
        except _EvidenceError as error:
            record["status"] = error.status
            record["outcome"] = INCOMPLETE
            result["errors"].append(_error_record(error.reason, channel=error.channel, check=record["name"], details=error.details))
        result["physical_checks"].append(record)


def _require_manifest_check_evidence(contract: Mapping[str, Any], result: dict[str, Any]) -> None:
    """Prevent a required manifest check from disappearing from execution."""

    raw_checks = contract.get("checks")
    if raw_checks is None:
        return
    if not _is_sequence(raw_checks):
        raise _invalid("checks must be a list.")
    available = {
        "golden": bool(result["golden_checks"]),
        "physical": bool(result["physical_checks"]),
    }
    result.setdefault("manifest_checks", [])
    for index, item in enumerate(raw_checks):
        if not isinstance(item, Mapping):
            raise _invalid("checks entries must be mappings.", index=index)
        required = _required(item)
        if not required:
            continue
        kind = item.get("kind")
        name = _text(item.get("name", f"check_{index}"), f"checks[{index}].name")
        manifest_record = {
            "name": name,
            "kind": kind,
            "required": True,
            "status": "missing",
            "outcome": INCOMPLETE,
        }
        if not isinstance(kind, str) or kind not in available:
            result["manifest_checks"].append(manifest_record)
            result["errors"].append(
                _error_record(
                    "required acceptance check has no executable evaluator",
                    check=name,
                    details={"kind": kind},
                )
            )
            continue
        if not available[kind]:
            result[f"{kind}_checks"].append(
                {
                    "name": name,
                    "kind": kind,
                    "required": True,
                    "status": "missing",
                    "outcome": INCOMPLETE,
                }
            )
            result["errors"].append(
                _error_record(
                    "required acceptance check has no executable declaration",
                    check=name,
                    details={"kind": kind},
                )
            )
            result["manifest_checks"].append(manifest_record)
            continue
        observed_checks = result[f"{kind}_checks"]
        outcomes = [check.get("outcome") for check in observed_checks]
        if any(outcome == INCOMPLETE for outcome in outcomes):
            manifest_record["status"] = "incomplete"
        elif any(outcome == FAIL for outcome in outcomes):
            manifest_record["status"] = "failed"
            manifest_record["outcome"] = FAIL
        else:
            manifest_record["status"] = "observed"
            manifest_record["outcome"] = PASS
        manifest_record["evidence_count"] = len(observed_checks)
        result["manifest_checks"].append(manifest_record)


def _add_unusable_declared_checks(contract: Mapping[str, Any], result: dict[str, Any], error: _EvidenceError) -> None:
    if not result["golden_checks"]:
        _, declarations = _golden_declarations(contract, {})
        result["canonical"]["golden_channels"] = [_text(item.get("name"), "golden channel name") for item in declarations]
        for index, declaration in enumerate(declarations):
            result["golden_checks"].append(
                {
                    "name": _text(declaration.get("name"), f"golden.channels[{index}].name"),
                    "kind": "golden",
                    "required": _required(declaration),
                    "status": error.status,
                    "outcome": INCOMPLETE,
                }
            )
    if not result["physical_checks"]:
        for index, check in enumerate(_physical_declarations(contract)):
            record = _check_base(check, index)
            record["status"] = error.status
            result["physical_checks"].append(record)


def _final_verdict(result: Mapping[str, Any]) -> str:
    required_checks = [
        check
        for check in [*result["golden_checks"], *result["physical_checks"], *result.get("manifest_checks", [])]
        if check.get("required", True)
    ]
    if not required_checks:
        return PASS
    if any(check.get("outcome") == INCOMPLETE for check in required_checks):
        return INCOMPLETE
    if any(check.get("outcome") == FAIL for check in required_checks):
        return FAIL
    return PASS


def evaluate_acceptance(samples: Any, golden: Any, contract: Any) -> dict[str, Any]:
    """Evaluate contract-declared golden and physical evidence.

    Normal missing or unusable evidence is returned as INCOMPLETE_ANALYSIS.
    Malformed API arguments or malformed contract fields raise BackendError.
    """

    if not isinstance(contract, Mapping):
        raise _invalid("contract must be a mapping.")
    result: dict[str, Any] = {
        "verdict": INCOMPLETE,
        "alignment": {"status": "missing", "rule": None, "shift_seconds": None},
        "golden_checks": [],
        "physical_checks": [],
        "warnings": [],
        "errors": [],
        "metrics": {},
        "canonical": {"sample_channels": [], "golden_channels": []},
        "manifest_checks": [],
    }
    try:
        if isinstance(golden, Mapping):
            source = golden.get("source")
            if isinstance(source, str) and "placeholder" in source.casefold():
                raise _EvidenceError(
                    "unverified golden baseline",
                    details={"source": source},
                )
        sample_channels = _canonical_channels(samples, "samples")
        golden_channels = _canonical_channels(golden, "golden")
        result["canonical"]["sample_channels"] = sorted(sample_channels)
        _evaluate_golden(sample_channels, golden_channels, contract, result)
        _evaluate_physical(sample_channels, contract, result)
        _require_manifest_check_evidence(contract, result)
    except _EvidenceError as error:
        result["errors"].append(_error_record(error.reason, channel=error.channel, details=error.details))
        _add_unusable_declared_checks(contract, result, error)
    result["verdict"] = _final_verdict(result)
    result["metrics"] = {
        "golden_required": sum(1 for check in result["golden_checks"] if check.get("required", True)),
        "physical_required": sum(1 for check in result["physical_checks"] if check.get("required", True)),
        "errors": len(result["errors"]),
    }
    return result


__all__ = [
    "MAX_CHANNEL_SAMPLES",
    "align_positive_zero_crossing",
    "evaluate_acceptance",
    "interpolate_to_grid",
    "normalized_errors",
]
