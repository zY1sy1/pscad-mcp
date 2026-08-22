"""Bounded, deterministic metrics over normalized sampled channels."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Iterable


def _numeric_series(values: Any, label: str) -> tuple[list[float] | None, str | None]:
    if not isinstance(values, (list, tuple)):
        return None, f"{label} must be a list of numeric samples."
    numeric: list[float] = []
    for index, value in enumerate(values[:1_000_000]):
        try:
            converted = float(value)
        except (TypeError, ValueError):
            return None, f"{label}[{index}] is not numeric."
        if not math.isfinite(converted):
            return None, f"{label}[{index}] is not finite."
        numeric.append(converted)
    return numeric, None


def _normalize(
    samples: dict[str, Any],
) -> tuple[list[float], dict[str, list[float]], set[str], list[str], dict[str, float]]:
    if not isinstance(samples, dict):
        return [], {}, {"__time__"}, ["Samples must be an object."], {}
    raw_channels = samples.get("channels", {})
    channels: dict[str, list[float]] = {}
    invalid: set[str] = set()
    warnings: list[str] = []
    if isinstance(raw_channels, dict):
        parsed_time, error = _numeric_series(samples.get("time"), "time")
        time = parsed_time or []
        if error or not time or any(time[index] <= time[index - 1] for index in range(1, len(time))):
            invalid.add("__time__")
            warnings.append(error or "time must be non-empty and strictly increasing.")
        for raw_name, raw_values in raw_channels.items():
            name = str(raw_name)
            values, value_error = _numeric_series(raw_values, f"channels.{name}")
            if value_error or values is None or not values or len(values) != len(time):
                invalid.add(name)
                warnings.append(
                    value_error
                    or f"Channel '{name}' must contain exactly {len(time)} non-empty samples."
                )
                continue
            channels[name] = values
    elif isinstance(raw_channels, list):
        time = []
        for index, channel in enumerate(raw_channels[:10_000]):
            if not isinstance(channel, Mapping):
                warnings.append(f"channels[{index}] must be an object.")
                continue
            name = channel.get("path") or channel.get("name")
            if not isinstance(name, str) or not name:
                warnings.append(f"channels[{index}] has no path or name.")
                continue
            values, value_error = _numeric_series(channel.get("values"), f"channels.{name}.values")
            domain, domain_error = _numeric_series(channel.get("domain"), f"channels.{name}.domain")
            if (
                value_error
                or domain_error
                or values is None
                or domain is None
                or not values
                or len(values) != len(domain)
                or any(domain[item] <= domain[item - 1] for item in range(1, len(domain)))
            ):
                invalid.add(name)
                warnings.append(
                    value_error
                    or domain_error
                    or f"Channel '{name}' values/domain must be non-empty, aligned, and strictly increasing."
                )
                continue
            if time and domain != time:
                invalid.add(name)
                warnings.append(f"Channel '{name}' uses a different time domain.")
                continue
            if name in channels:
                channels.pop(name, None)
                invalid.add(name)
                warnings.append(f"Channel '{name}' is duplicated.")
                continue
            if not time:
                time = domain
            channels[name] = values
        if not time:
            invalid.add("__time__")
    else:
        return [], {}, {"__time__"}, ["channels must be an object or list."], {}
    if "__time__" in invalid:
        invalid.update(channels)
        channels = {}
    baselines: dict[str, float] = {}
    raw_baselines = samples.get("recovery_baselines", {})
    if isinstance(raw_baselines, Mapping):
        for name, value in raw_baselines.items():
            if isinstance(value, bool):
                continue
            try:
                converted = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(converted):
                baselines[str(name)] = converted
    return time[:1_000_000], channels, invalid, warnings, baselines


def _invalid(name: str, channels: Iterable[str], time: list[float], warning: str) -> dict[str, Any]:
    return {
        "name": name,
        "value": None,
        "units": None,
        "time_window": _window(time),
        "source_channels": tuple(channels),
        "method": "invalid or unaligned sampled data",
        "status": "invalid",
        "warning": warning,
    }


def _window(time: list[float]) -> tuple[float, float] | None:
    return (time[0], time[-1]) if time else None


def _missing(name: str, channels: Iterable[str], time: list[float]) -> dict[str, Any]:
    return {"name": name, "value": None, "units": None, "time_window": _window(time), "source_channels": tuple(channels), "method": "required channel unavailable", "status": "missing", "warning": "Required channel is not mapped or contains no samples."}


def _metric(name: str, value: float, units: str | None, channels: Iterable[str], time: list[float], method: str, status: str = "observed") -> dict[str, Any]:
    return {"name": name, "value": float(value), "units": units, "time_window": _window(time), "source_channels": tuple(channels), "method": method, "status": status, "warning": None}


def _first_crossing(values: list[float], threshold: float = 0.5) -> int | None:
    for index in range(1, len(values)):
        if values[index - 1] < threshold <= values[index]:
            return index
    return None


def _transition_index(values: list[float], transition: str, threshold: float) -> int | None:
    for index in range(1, len(values)):
        previous, current = values[index - 1], values[index]
        if transition == "rising" and previous < threshold <= current:
            return index
        if transition == "falling" and previous >= threshold > current:
            return index
    return None


def calculate_metrics(samples: dict[str, Any], metrics: list[str] | None = None, *, profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    time, channels, invalid_channels, validation_warnings, recovery_baselines = _normalize(samples)
    profile_provided = profile is not None and profile.get("profile_version", 1) == 2
    profile = profile or {}
    roles = profile.get("metric_roles", {}) if isinstance(profile, Mapping) else {}
    selectors = {item.get("canonical"): item for item in profile.get("result_channels", []) if isinstance(item, Mapping)} if isinstance(profile, Mapping) else {}
    channel_unit_map = {name: selectors.get(name, {}).get("units") for name in channels}
    if isinstance(samples.get("channels"), list):
        channel_unit_map.update({str(item.get("path") or item.get("name")): item.get("units", "") for item in samples["channels"] if isinstance(item, Mapping)})
    def source(role: str, fallback: str) -> str:
        value = roles.get(role) if isinstance(roles, Mapping) else None
        return str(value) if isinstance(value, str) else fallback

    def channel_units(channel: str, fallback: str | None = None) -> str | None:
        configured = channel_unit_map.get(channel)
        if configured not in (None, ""):
            return str(configured)
        lowered = channel.casefold()
        if "frequency" in lowered or lowered.endswith("_freq"):
            return "Hz"
        if "voltage" in lowered:
            return "kV"
        if "current" in lowered:
            return "kA"
        if "active_power" in lowered or lowered in {"power", "p"}:
            return "MW"
        if "reactive_power" in lowered or lowered in {"q", "qreactive"}:
            return "MVAr"
        return fallback
    requested = metrics or ["dc_voltage_peak", "dc_current_peak", "dc_power"]
    result: list[dict[str, Any]] = []
    legacy_named_channels = isinstance(samples.get("channels"), dict)

    def unavailable(metric_name: str, source_channels: Iterable[str]) -> dict[str, Any]:
        sources = tuple(source_channels)
        if "__time__" in invalid_channels or any(source in invalid_channels for source in sources):
            return _invalid(
                metric_name,
                sources,
                time,
                "Required samples are invalid, non-numeric, unaligned, or use a non-monotonic time domain.",
            )
        return _missing(metric_name, sources, time)

    def lcc_units_valid(expected: Mapping[str, str]) -> bool:
        return all(
            (
                isinstance(channel_unit_map.get(channel), str)
                and str(channel_unit_map[channel]).strip().casefold() == unit.casefold()
            )
            or (
                legacy_named_channels
                and channel_units(channel) is not None
                and str(channel_units(channel)).casefold() == unit.casefold()
            )
            for channel, unit in expected.items()
        )

    def invalid_lcc_units(metric_name: str, expected: Mapping[str, str]) -> dict[str, Any]:
        return _invalid(
            metric_name,
            tuple(expected),
            time,
            "LCC operating-mode metrics require explicit units on every source channel.",
        )

    for name in requested:
        if name == "pole_current_imbalance":
            positive = channels.get("positive_pole_current", [])
            negative = channels.get("negative_pole_current", [])
            count = min(len(positive), len(negative))
            if count and not lcc_units_valid({"positive_pole_current": "kA", "negative_pole_current": "kA"}):
                result.append(invalid_lcc_units(name, {"positive_pole_current": "kA", "negative_pole_current": "kA"}))
            else:
                result.append(
                _metric(name, max(abs(abs(positive[i]) - abs(negative[i])) for i in range(count)), "kA",
                        ("positive_pole_current", "negative_pole_current"), time,
                        "maximum absolute pole-magnitude difference", "derived")
                if count else unavailable(name, ("positive_pole_current", "negative_pole_current"))
                )
            continue
        if name == "pole_voltage_imbalance":
            positive = channels.get("positive_pole_voltage", [])
            negative = channels.get("negative_pole_voltage", [])
            count = min(len(positive), len(negative))
            if count and not lcc_units_valid({"positive_pole_voltage": "kV", "negative_pole_voltage": "kV"}):
                result.append(invalid_lcc_units(name, {"positive_pole_voltage": "kV", "negative_pole_voltage": "kV"}))
            else:
                result.append(
                _metric(name, max(abs(abs(positive[i]) - abs(negative[i])) for i in range(count)), "kV",
                        ("positive_pole_voltage", "negative_pole_voltage"), time,
                        "maximum absolute pole-magnitude difference", "derived")
                if count else unavailable(name, ("positive_pole_voltage", "negative_pole_voltage"))
                )
            continue
        if name == "return_current_closure_error":
            positive = channels.get("positive_pole_current", [])
            negative = channels.get("negative_pole_current", [])
            earth = channels.get("earth_return_current", [])
            metallic = channels.get("metallic_return_current", [])
            if not earth and not metallic:
                result.append(unavailable(name, ("positive_pole_current", "negative_pole_current", "earth_return_current", "metallic_return_current")))
            else:
                count = min(len(positive), len(negative), len(earth) or len(metallic))
                ret = earth if earth else metallic
                return_name = "earth_return_current" if earth else "metallic_return_current"
                expected_units = {
                    "positive_pole_current": "kA",
                    "negative_pole_current": "kA",
                    return_name: "kA",
                }
                if count and not lcc_units_valid(expected_units):
                    result.append(invalid_lcc_units(name, expected_units))
                else:
                    result.append(_metric(name, max(abs(positive[i] - negative[i] - ret[i]) for i in range(count)), "kA",
                                          tuple(expected_units), time,
                                          "maximum algebraic return-current closure error", "derived") if count else unavailable(name, tuple(expected_units)))
            continue
        if name == "mode_transition_recovery_time_s":
            command = channels.get("mode_command", [])
            response = channels.get("dc_voltage", [])
            expected_units = {"mode_command": "state", "dc_voltage": "kV"}
            count = min(len(command), len(response), len(time))
            if not count:
                result.append(unavailable(name, tuple(expected_units)))
            elif not lcc_units_valid(expected_units):
                result.append(invalid_lcc_units(name, expected_units))
            elif "dc_voltage" not in recovery_baselines:
                result.append(_invalid(name, tuple(expected_units), time, "Mode transition recovery requires an explicit dc_voltage recovery baseline."))
            else:
                transition_index = _first_crossing(command)
                baseline = recovery_baselines["dc_voltage"]
                tolerance = max(abs(baseline) * 0.01, 1e-12)
                recovery_index = None if transition_index is None else next(
                    (
                        index
                        for index in range(transition_index, count)
                        if all(abs(value - baseline) <= tolerance for value in response[index:count])
                    ),
                    None,
                )
                if transition_index is None or recovery_index is None:
                    result.append(_invalid(name, tuple(expected_units), time, "A command transition and sustained 1% response recovery are both required."))
                else:
                    result.append(_metric(
                        name,
                        time[recovery_index] - time[transition_index],
                        "s",
                        tuple(expected_units),
                        time,
                        "EMTDC time from mode-command transition to sustained 1% dc-voltage recovery",
                        "derived",
                    ))
            continue
        if name == "mode_mismatch":
            command = channels.get("mode_command", [])
            status = channels.get("mode_status", [])
            expected_units = {"mode_command": "state", "mode_status": "state"}
            count = min(len(command), len(status))
            if not count:
                result.append(unavailable(name, tuple(expected_units)))
            elif not lcc_units_valid(expected_units):
                result.append(invalid_lcc_units(name, expected_units))
            else:
                mismatch = sum(1 for index in range(count) if command[index] != status[index]) / count
                result.append(_metric(
                    name,
                    mismatch,
                    "ratio",
                    tuple(expected_units),
                    time,
                    "fraction of aligned samples whose observed mode differs from the command",
                    "derived",
                ))
            continue
        if name in {"voltage_imbalance", "current_imbalance", "pole_imbalance"}:
            prefix = "dc_voltage" if name == "voltage_imbalance" else "dc_current"
            positive, negative = channels.get(f"{prefix}_positive", []), channels.get(f"{prefix}_negative", [])
            count = min(len(positive), len(negative))
            units = "kV" if prefix == "dc_voltage" else "kA"
            result.append(_metric(name, max(abs(abs(positive[index]) - abs(negative[index])) for index in range(count)), units, (f"{prefix}_positive", f"{prefix}_negative"), time, "maximum absolute pole-magnitude difference", "derived") if count else unavailable(name, (f"{prefix}_positive", f"{prefix}_negative")))
            continue
        if name in {"breaker_sequence", "breaker_protection_sequence"}:
            configured = next((item for item in profile.get("sequences", []) if isinstance(item, Mapping) and item.get("canonical") == name), {})
            names = tuple(configured.get("order", (source("breaker_command", "breaker_command"), source("breaker_status", "breaker_status"), source("protection_trip", "protection_trip"))))
            indices = [_transition_index(channels.get(channel, []), selectors.get(channel, {}).get("transition", "rising"), float(selectors.get(channel, {}).get("threshold", 0.5))) for channel in names]
            if any(index is None for index in indices) or not time:
                result.append(unavailable(name, names))
            else:
                ordered = indices == sorted(indices)
                result.append(_metric(name, 1.0 if ordered else 0.0, "boolean", names, time, "ordered command/status/protection threshold crossings", "observed"))
            continue
        response_suffix = next((suffix for suffix in ("_overshoot", "_undershoot", "_settling_time_s", "_recovery_time_s") if name.endswith(suffix)), None)
        if response_suffix:
            channel = name[: -len(response_suffix)]
            values = channels.get(channel, [])
            if not values or not time:
                result.append(unavailable(name, (channel,)))
                continue
            final = sum(values[max(0, len(values) - max(1, len(values) // 10)):]) / max(1, len(values) // 10)
            peak_index = max(range(len(values)), key=values.__getitem__)
            post_peak = values[peak_index:]
            if response_suffix == "_overshoot":
                result.append(_metric(name, max(0.0, max(values) - final), "kA" if "current" in channel else "kV" if "voltage" in channel else None, (channel,), time, "peak minus final steady-state mean", "derived"))
            elif response_suffix == "_undershoot":
                result.append(_metric(name, max(0.0, final - min(post_peak)), "kA" if "current" in channel else "kV" if "voltage" in channel else None, (channel,), time, "final steady-state mean minus post-peak minimum", "derived"))
            elif response_suffix == "_settling_time_s":
                tolerance = max(abs(final) * 0.01, 1e-12)
                settling_index = None
                for index in range(len(values)):
                    if all(abs(value - final) <= tolerance for value in values[index:]):
                        settling_index = index
                        break
                value = time[settling_index] if settling_index is not None else None
                status = "derived" if value is not None else "missing"
                result.append(_metric(name, value, "s", (channel,), time, "first sustained 1% settling band" , status) if value is not None else unavailable(name, (channel,)))
            else:
                baseline = recovery_baselines.get(channel)
                if baseline is None:
                    result.append(
                        _invalid(
                            name,
                            (channel,),
                            time,
                            "Recovery time requires an explicit recovery_baselines entry for the source channel.",
                        )
                    )
                    continue
                deviation_index = max(
                    range(len(values)),
                    key=lambda index: abs(values[index] - baseline),
                )
                tolerance = max(abs(baseline) * 0.01, 1e-12)
                recovery_index = next(
                    (
                        index
                        for index in range(deviation_index, len(values))
                        if all(abs(value - baseline) <= tolerance for value in values[index:])
                    ),
                    None,
                )
                if recovery_index is None:
                    result.append(unavailable(name, (channel,)))
                else:
                    result.append(
                        _metric(
                            name,
                            time[recovery_index] - time[deviation_index],
                            "s",
                            (channel,),
                            time,
                            "elapsed time from maximum baseline deviation to sustained 1% baseline recovery",
                            "derived",
                        )
                    )
        elif name.endswith("_peak"):
            channel = name.removesuffix("_peak")
            values = channels.get(channel, [])
            result.append(_metric(name, max(values), channel_units(channel), (channel,), time, "maximum sampled value") if values else unavailable(name, (channel,)))
        elif name.endswith("_min"):
            channel = name.removesuffix("_min")
            values = channels.get(channel, [])
            result.append(_metric(name, min(values), channel_units(channel), (channel,), time, "minimum sampled value") if values else unavailable(name, (channel,)))
        elif name.endswith("_steady_state_mean") or name.endswith("_steady_state_rms"):
            suffix = "_steady_state_mean" if name.endswith("_steady_state_mean") else "_steady_state_rms"
            channel = name[: -len(suffix)]
            values = channels.get(channel, [])
            tail = values[max(0, len(values) - max(1, len(values) // 10)):]
            if not tail:
                result.append(unavailable(name, (channel,)))
            elif suffix.endswith("rms"):
                result.append(_metric(name, math.sqrt(sum(value * value for value in tail) / len(tail)), channel_units(channel), (channel,), time, "last 10% RMS", "derived"))
            else:
                result.append(_metric(name, sum(tail) / len(tail), channel_units(channel), (channel,), time, "last 10% arithmetic mean", "derived"))
        elif name.endswith("_mean"):
            channel = name.removesuffix("_mean")
            values = channels.get(channel, [])
            result.append(_metric(name, sum(values) / len(values), channel_units(channel), (channel,), time, "arithmetic mean") if values else unavailable(name, (channel,)))
        elif name.endswith("_rms"):
            channel = name.removesuffix("_rms")
            values = channels.get(channel, [])
            result.append(_metric(name, math.sqrt(sum(value * value for value in values) / len(values)), channel_units(channel), (channel,), time, "root mean square") if values else unavailable(name, (channel,)))
        elif name == "dc_power":
            voltage_name, current_name = source("dc_voltage", "dc_voltage"), source("dc_current", "dc_current")
            voltage, current = channels.get(voltage_name, []), channels.get(current_name, [])
            count = min(len(voltage), len(current))
            valid_units = {str(channel_unit_map.get(voltage_name, "")).casefold(), str(channel_unit_map.get(current_name, "")).casefold()} >= {"kv", "ka"}
            if count and (valid_units or not profile_provided):
                result.append(_metric(name, max(voltage[index] * current[index] for index in range(count)), "MW", (voltage_name, current_name), time, "pointwise Vdc * Idc peak", "derived"))
            elif count and profile_provided:
                result.append(_invalid(name, (voltage_name, current_name), time, "dc_power requires confirmed kV and kA channels."))
            else:
                result.append(unavailable(name, (voltage_name, current_name)))
        elif name == "trip_delay_s":
            command_name, status_name = source("breaker_command", "breaker_command"), source("breaker_status", "breaker_status")
            command, status = channels.get(command_name, []), channels.get(status_name, [])
            command_index = _transition_index(command, selectors.get(command_name, {}).get("transition", "rising"), float(selectors.get(command_name, {}).get("threshold", 0.5)))
            status_index = _transition_index(status, selectors.get(status_name, {}).get("transition", "rising"), float(selectors.get(status_name, {}).get("threshold", 0.5)))
            if not command or not status or not time:
                result.append(unavailable(name, ("breaker_command", "breaker_status")))
            elif command_index is None or status_index is None:
                result.append(
                    _invalid(
                        name,
                        ("breaker_command", "breaker_status"),
                        time,
                        "Trip delay requires observed low-to-high command and status edges.",
                    )
                )
            elif status_index < command_index:
                result.append(
                    _invalid(
                        name,
                        ("breaker_command", "breaker_status"),
                        time,
                        "Breaker status crossed before the breaker command; trip delay is invalid.",
                    )
                )
            else:
                result.append(_metric(name, round(time[status_index] - time[command_index], 12), "s", ("breaker_command", "breaker_status"), time, "ordered threshold crossing", "observed"))
        else:
            result.append(unavailable(name, (name,)))
    verdict = "INCOMPLETE_ANALYSIS" if any(item["status"] in {"missing", "invalid"} for item in result) else "PASS"
    metric_warnings = [item["warning"] for item in result if item["warning"]]
    return {"metrics": result, "verdict": verdict, "warnings": [*validation_warnings, *metric_warnings]}
