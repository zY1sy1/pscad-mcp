"""Strict no-fault smoke evaluation for the fixed LCC builder."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

from ....core.backend.base import BackendError

CONTRACT_KEYS = {
    "schema_version",
    "identity",
    "duration_s",
    "output_step_s",
    "required_channels",
    "enable_channels",
    "ao_limits_rad",
}
CHECK_NAMES = (
    "time_domain",
    "finite_outputs",
    "controls_enabled",
    "ao_within_limits",
)


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        code,
        message,
        "hvdc",
        "evaluate_fixed_lcc_smoke",
        details,
    )


def _invalid(reason: str, message: str, **details: Any) -> BackendError:
    return _error(
        "LCC_FIXED_SMOKE_INVALID",
        message,
        reason=reason,
        **details,
    )


def _failed(reason: str, message: str, **details: Any) -> BackendError:
    return _error(
        "LCC_FIXED_SMOKE_FAILED",
        message,
        reason=reason,
        **details,
    )


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise _invalid("invalid_contract", f"{field} must be an array.", field=field)
    return value


def _finite_contract_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(
            "invalid_contract",
            f"{field} must be a finite number.",
            field=field,
        )
    number = float(value)
    if not math.isfinite(number):
        raise _invalid(
            "invalid_contract",
            f"{field} must be a finite number.",
            field=field,
        )
    return number


def _channel_names(value: Any, field: str) -> tuple[str, ...]:
    names = tuple(_sequence(value, field))
    if (
        not names
        or any(not isinstance(name, str) or not name.strip() for name in names)
        or len(names) != len(set(names))
    ):
        raise _invalid(
            "invalid_contract",
            f"{field} must contain unique non-empty channel names.",
            field=field,
        )
    return tuple(name.strip() for name in names)


def _parse_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != CONTRACT_KEYS:
        raise _invalid(
            "invalid_contract",
            "The smoke contract fields are not exact.",
            expected=sorted(CONTRACT_KEYS),
            observed=sorted(value) if isinstance(value, Mapping) else None,
        )
    if isinstance(value["schema_version"], bool) or value["schema_version"] != 1:
        raise _invalid(
            "invalid_contract",
            "The smoke contract schema version must be 1.",
            field="schema_version",
        )
    identity = value["identity"]
    if not isinstance(identity, str) or not identity.strip():
        raise _invalid(
            "invalid_contract",
            "The smoke contract identity must be non-empty text.",
            field="identity",
        )
    duration = _finite_contract_number(value["duration_s"], "duration_s")
    output_step = _finite_contract_number(
        value["output_step_s"], "output_step_s"
    )
    if duration <= 0 or output_step <= 0 or output_step > duration:
        raise _invalid(
            "invalid_contract",
            "Smoke duration and output step are not positive and ordered.",
        )
    required = _channel_names(value["required_channels"], "required_channels")
    enabled = _channel_names(value["enable_channels"], "enable_channels")
    if not set(enabled).issubset(required):
        raise _invalid(
            "invalid_contract",
            "Enable channels must be required channels.",
            unknown=sorted(set(enabled) - set(required)),
        )
    raw_limits = value["ao_limits_rad"]
    if not isinstance(raw_limits, Mapping) or not raw_limits:
        raise _invalid(
            "invalid_contract",
            "AO limits must be a non-empty object.",
            field="ao_limits_rad",
        )
    if not set(raw_limits).issubset(required):
        raise _invalid(
            "invalid_contract",
            "AO limit channels must be required channels.",
            unknown=sorted(set(raw_limits) - set(required)),
        )
    limits: dict[str, tuple[float, float]] = {}
    for channel, raw_bounds in raw_limits.items():
        if not isinstance(channel, str) or not channel.strip():
            raise _invalid(
                "invalid_contract",
                "AO limit channel names must be non-empty text.",
            )
        bounds = _sequence(raw_bounds, f"ao_limits_rad.{channel}")
        if len(bounds) != 2:
            raise _invalid(
                "invalid_contract",
                "AO limits require lower and upper values.",
                channel=channel,
            )
        lower = _finite_contract_number(
            bounds[0], f"ao_limits_rad.{channel}[0]"
        )
        upper = _finite_contract_number(
            bounds[1], f"ao_limits_rad.{channel}[1]"
        )
        if lower > upper:
            raise _invalid(
                "invalid_contract",
                "AO limits are inverted.",
                channel=channel,
                lower=lower,
                upper=upper,
            )
        limits[channel.strip()] = (lower, upper)
    return {
        "schema_version": 1,
        "identity": identity.strip(),
        "duration_s": duration,
        "output_step_s": output_step,
        "required_channels": required,
        "enable_channels": enabled,
        "ao_limits_rad": limits,
    }


def _finite_samples(values: Any, channel: str) -> list[float]:
    if not isinstance(values, Sequence) or isinstance(
        values, (str, bytes, bytearray)
    ):
        raise _failed(
            "nonfinite_output",
            "A required output has no numeric sample array.",
            channel=channel,
        )
    raw_values = values
    numbers: list[float] = []
    for index, value in enumerate(raw_values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _failed(
                "nonfinite_output",
                "A required output contains a non-numeric sample.",
                channel=channel,
                index=index,
            )
        number = float(value)
        if not math.isfinite(number):
            raise _failed(
                "nonfinite_output",
                "A required output contains a non-finite sample.",
                channel=channel,
                index=index,
            )
        numbers.append(number)
    if not numbers:
        raise _failed(
            "nonfinite_output",
            "A required output has no samples.",
            channel=channel,
        )
    return numbers


def _time_samples(values: Any, channel: str) -> list[float]:
    if not isinstance(values, Sequence) or isinstance(
        values, (str, bytes, bytearray)
    ):
        raise _failed(
            "invalid_time_domain",
            "A required channel has no numeric time array.",
            channel=channel,
        )
    raw_values = values
    numbers: list[float] = []
    for index, value in enumerate(raw_values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _failed(
                "invalid_time_domain",
                "A required channel has a non-numeric time sample.",
                channel=channel,
                index=index,
            )
        number = float(value)
        if not math.isfinite(number):
            raise _failed(
                "invalid_time_domain",
                "A required channel has a non-finite time sample.",
                channel=channel,
                index=index,
            )
        numbers.append(number)
    if len(numbers) < 2 or any(right <= left for left, right in pairwise(numbers)):
        raise _failed(
            "invalid_time_domain",
            "A required channel time domain is not strictly increasing.",
            channel=channel,
        )
    return numbers


def _parse_channels(samples: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(samples, Mapping):
        raise _failed(
            "invalid_output",
            "Smoke output must be an object.",
        )
    raw_channels = samples.get("channels")
    if not isinstance(raw_channels, Mapping):
        raise _failed(
            "invalid_output",
            "Smoke output channels must be an object.",
        )
    global_time = samples.get("time")
    channels: dict[str, dict[str, Any]] = {}
    for raw_name, raw_channel in raw_channels.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise _failed(
                "invalid_output",
                "Output channel names must be non-empty text.",
            )
        if not isinstance(raw_channel, Mapping):
            raise _failed(
                "invalid_output",
                "Output channel evidence must be an object.",
                channel=raw_name,
            )
        units = raw_channel.get("units")
        if not isinstance(units, str):
            raise _failed(
                "invalid_output",
                "Output channel units must be text.",
                channel=raw_name,
            )
        time = raw_channel.get("time", global_time)
        if time is None:
            raise _failed(
                "invalid_time_domain",
                "A required channel has no time domain.",
                channel=raw_name,
            )
        times = _time_samples(time, raw_name)
        values = _finite_samples(raw_channel.get("values"), raw_name)
        if len(times) != len(values):
            raise _failed(
                "invalid_time_domain",
                "A channel time/value length does not match.",
                channel=raw_name,
                time_samples=len(times),
                value_samples=len(values),
            )
        channels[raw_name.strip()] = {
            "time": times,
            "values": values,
            "units": units.strip(),
        }
    return channels


def _require_common_time(
    channels: Mapping[str, Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> list[float]:
    required = contract["required_channels"]
    reference = list(channels[required[0]]["time"])
    for channel in required[1:]:
        observed = channels[channel]["time"]
        if len(observed) != len(reference) or any(
            left != right for left, right in zip(reference, observed)
        ):
            raise _failed(
                "inconsistent_time_domain",
                "Required smoke channels do not share one time domain.",
                channel=channel,
            )
    duration = float(contract["duration_s"])
    tolerance = float(contract["output_step_s"])
    if reference[0] < 0 or abs(reference[-1] - duration) > tolerance:
        raise _failed(
            "invalid_time_domain",
            "The smoke time domain does not reach the configured duration.",
            domain_start_s=reference[0],
            domain_end_s=reference[-1],
            duration_s=duration,
            tolerance_s=tolerance,
        )
    return reference


def _require_enabled(
    channels: Mapping[str, Mapping[str, Any]],
    enabled: Sequence[str],
) -> None:
    for channel in enabled:
        for index, value in enumerate(channels[channel]["values"]):
            if value != 1.0:
                raise _failed(
                    "control_not_enabled",
                    "A fixed LCC control is not enabled for the smoke run.",
                    channel=channel,
                    index=index,
                    observed=value,
                )


def _require_ao_limits(
    channels: Mapping[str, Mapping[str, Any]],
    limits: Mapping[str, tuple[float, float]],
) -> None:
    for channel, (lower, upper) in limits.items():
        if channels[channel]["units"].casefold() != "rad":
            raise _failed(
                "ao_unit_mismatch",
                "A fixed LCC angle order is not expressed in radians.",
                channel=channel,
                observed_units=channels[channel]["units"],
            )
        for index, value in enumerate(channels[channel]["values"]):
            if not lower <= value <= upper:
                raise _failed(
                    "ao_out_of_bounds",
                    "A fixed LCC angle order is outside its hard limits.",
                    channel=channel,
                    index=index,
                    lower=lower,
                    upper=upper,
                    observed=value,
                )


def evaluate_fixed_smoke(
    samples: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _parse_contract(contract)
    channels = _parse_channels(samples)
    missing = [
        name for name in normalized["required_channels"] if name not in channels
    ]
    if missing:
        raise _failed(
            "missing_channel",
            "Required smoke channels are missing.",
            channels=missing,
        )
    selected = {
        name: channels[name] for name in normalized["required_channels"]
    }
    common_time = _require_common_time(selected, normalized)
    _require_enabled(selected, normalized["enable_channels"])
    _require_ao_limits(selected, normalized["ao_limits_rad"])
    return {
        "verdict": "PASS",
        "checks": {name: True for name in CHECK_NAMES},
        "evidence": {
            "duration_s": normalized["duration_s"],
            "output_step_s": normalized["output_step_s"],
            "domain_start_s": common_time[0],
            "domain_end_s": common_time[-1],
            "samples": len(common_time),
            "channels": {
                name: {
                    "units": selected[name]["units"],
                    "samples": len(selected[name]["values"]),
                    "minimum": min(selected[name]["values"]),
                    "maximum": max(selected[name]["values"]),
                }
                for name in sorted(selected)
            },
        },
    }


__all__ = ["evaluate_fixed_smoke"]
