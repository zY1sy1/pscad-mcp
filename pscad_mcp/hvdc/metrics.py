"""Bounded, deterministic metrics over normalized sampled channels."""

from __future__ import annotations

import math
from typing import Any, Iterable


def _normalize(samples: dict[str, Any]) -> tuple[list[float], dict[str, list[float]]]:
    if not isinstance(samples, dict):
        return [], {}
    raw_channels = samples.get("channels", {})
    if isinstance(raw_channels, dict):
        time = _numeric_values(samples.get("time", []))
        channels = {str(name): _numeric_values(values)[:1_000_000] for name, values in raw_channels.items() if isinstance(values, (list, tuple))}
    elif isinstance(raw_channels, list):
        channels = {}
        time = []
        for channel in raw_channels:
            if not isinstance(channel, dict):
                continue
            name = channel.get("path") or channel.get("name")
            values = channel.get("values")
            domain = channel.get("domain")
            if name and isinstance(values, (list, tuple)):
                channels[str(name)] = _numeric_values(values)[:1_000_000]
                if not time and isinstance(domain, (list, tuple)):
                    time = _numeric_values(domain)[:1_000_000]
    else:
        return [], {}
    if not time:
        longest = max((len(values) for values in channels.values()), default=0)
        time = [float(index) for index in range(longest)]
    return time[:1_000_000], channels


def _numeric_values(values: Any) -> list[float]:
    if not isinstance(values, (list, tuple)):
        return []
    numeric: list[float] = []
    for value in values:
        try:
            converted = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(converted):
            numeric.append(converted)
    return numeric


def _window(time: list[float]) -> tuple[float, float] | None:
    return (time[0], time[-1]) if time else None


def _missing(name: str, channels: Iterable[str], time: list[float]) -> dict[str, Any]:
    return {"name": name, "value": None, "units": None, "time_window": _window(time), "source_channels": tuple(channels), "method": "required channel unavailable", "status": "missing", "warning": "Required channel is not mapped or contains no samples."}


def _metric(name: str, value: float, units: str | None, channels: Iterable[str], time: list[float], method: str, status: str = "observed") -> dict[str, Any]:
    return {"name": name, "value": float(value), "units": units, "time_window": _window(time), "source_channels": tuple(channels), "method": method, "status": status, "warning": None}


def _first_crossing(values: list[float], threshold: float = 0.5) -> int | None:
    for index, value in enumerate(values):
        if value >= threshold:
            return index
    return None


def calculate_metrics(samples: dict[str, Any], metrics: list[str] | None = None) -> dict[str, Any]:
    time, channels = _normalize(samples)
    requested = metrics or ["dc_voltage_peak", "dc_current_peak", "dc_power"]
    result: list[dict[str, Any]] = []
    for name in requested:
        if name in {"voltage_imbalance", "current_imbalance", "pole_imbalance"}:
            prefix = "dc_voltage" if name == "voltage_imbalance" else "dc_current"
            positive, negative = channels.get(f"{prefix}_positive", []), channels.get(f"{prefix}_negative", [])
            count = min(len(positive), len(negative))
            units = "kV" if prefix == "dc_voltage" else "kA"
            result.append(_metric(name, max((abs(abs(positive[index]) - abs(negative[index])) for index in range(count)), default=0.0), units, (f"{prefix}_positive", f"{prefix}_negative"), time, "maximum absolute pole-magnitude difference", "derived") if count else _missing(name, (f"{prefix}_positive", f"{prefix}_negative"), time))
            continue
        if name in {"breaker_sequence", "breaker_protection_sequence"}:
            names = ("breaker_command", "breaker_status", "protection_trip")
            indices = [_first_crossing(channels.get(channel, [])) for channel in names]
            if any(index is None for index in indices) or not time:
                result.append(_missing(name, names, time))
            else:
                ordered = indices == sorted(indices)
                result.append(_metric(name, 1.0 if ordered else 0.0, "boolean", names, time, "ordered command/status/protection threshold crossings", "observed"))
            continue
        response_suffix = next((suffix for suffix in ("_overshoot", "_undershoot", "_settling_time_s", "_recovery_time_s") if name.endswith(suffix)), None)
        if response_suffix:
            channel = name[: -len(response_suffix)]
            values = channels.get(channel, [])
            if not values or not time:
                result.append(_missing(name, (channel,), time))
                continue
            final = sum(values[max(0, len(values) - max(1, len(values) // 10)):]) / max(1, len(values) // 10)
            peak_index = max(range(len(values)), key=values.__getitem__)
            post_peak = values[peak_index:]
            if response_suffix == "_overshoot":
                result.append(_metric(name, max(0.0, max(values) - final), "kA" if "current" in channel else "kV" if "voltage" in channel else None, (channel,), time, "peak minus final steady-state mean", "derived"))
            elif response_suffix == "_undershoot":
                result.append(_metric(name, max(0.0, final - min(post_peak)), "kA" if "current" in channel else "kV" if "voltage" in channel else None, (channel,), time, "final steady-state mean minus post-peak minimum", "derived"))
            else:
                tolerance = max(abs(final) * 0.01, 1e-12)
                settling_index = None
                for index in range(len(values)):
                    if all(abs(value - final) <= tolerance for value in values[index:]):
                        settling_index = index
                        break
                value = time[settling_index] if settling_index is not None else None
                status = "derived" if value is not None else "missing"
                result.append(_metric(name, value, "s", (channel,), time, "first sustained 1% settling band" , status) if value is not None else _missing(name, (channel,), time))
        elif name.endswith("_peak"):
            channel = name.removesuffix("_peak")
            values = channels.get(channel, [])
            result.append(_metric(name, max(values), "kV" if "voltage" in channel else "kA" if "current" in channel else None, (channel,), time, "maximum sampled value") if values else _missing(name, (channel,), time))
        elif name.endswith("_min"):
            channel = name.removesuffix("_min")
            values = channels.get(channel, [])
            result.append(_metric(name, min(values), "kV" if "voltage" in channel else "kA" if "current" in channel else None, (channel,), time, "minimum sampled value") if values else _missing(name, (channel,), time))
        elif name.endswith("_steady_state_mean") or name.endswith("_steady_state_rms"):
            suffix = "_steady_state_mean" if name.endswith("_steady_state_mean") else "_steady_state_rms"
            channel = name[: -len(suffix)]
            values = channels.get(channel, [])
            tail = values[max(0, len(values) - max(1, len(values) // 10)):]
            if not tail:
                result.append(_missing(name, (channel,), time))
            elif suffix.endswith("rms"):
                result.append(_metric(name, math.sqrt(sum(value * value for value in tail) / len(tail)), None, (channel,), time, "last 10% RMS", "derived"))
            else:
                result.append(_metric(name, sum(tail) / len(tail), None, (channel,), time, "last 10% arithmetic mean", "derived"))
        elif name.endswith("_mean"):
            channel = name.removesuffix("_mean")
            values = channels.get(channel, [])
            result.append(_metric(name, sum(values) / len(values), None, (channel,), time, "arithmetic mean") if values else _missing(name, (channel,), time))
        elif name.endswith("_rms"):
            channel = name.removesuffix("_rms")
            values = channels.get(channel, [])
            result.append(_metric(name, math.sqrt(sum(value * value for value in values) / len(values)), "kA" if "current" in channel else "kV" if "voltage" in channel else None, (channel,), time, "root mean square") if values else _missing(name, (channel,), time))
        elif name == "dc_power":
            voltage, current = channels.get("dc_voltage", []), channels.get("dc_current", [])
            count = min(len(voltage), len(current))
            result.append(_metric(name, max((voltage[index] * current[index] for index in range(count)), default=0.0), "MW", ("dc_voltage", "dc_current"), time, "pointwise Vdc * Idc peak", "derived") if count else _missing(name, ("dc_voltage", "dc_current"), time))
        elif name == "trip_delay_s":
            command, status = channels.get("breaker_command", []), channels.get("breaker_status", [])
            command_index, status_index = _first_crossing(command), _first_crossing(status)
            if command_index is None or status_index is None or not time:
                result.append(_missing(name, ("breaker_command", "breaker_status"), time))
            else:
                result.append(_metric(name, round(max(0.0, time[status_index] - time[command_index]), 12), "s", ("breaker_command", "breaker_status"), time, "ordered threshold crossing", "observed"))
        else:
            result.append(_missing(name, (name,), time))
    verdict = "INCOMPLETE_ANALYSIS" if any(item["status"] == "missing" for item in result) else "PASS"
    return {"metrics": result, "verdict": verdict, "warnings": [item["warning"] for item in result if item["warning"]]}
