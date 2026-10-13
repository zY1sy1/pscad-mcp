"""Physical metrics from explicit windows of retained, bounded waveform samples."""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from copy import deepcopy
from itertools import pairwise
from pathlib import PurePosixPath
from typing import Any

from .store import sweep_error

_KINDS = {"energy", "i2t", "threshold_crossing", "peak_abs"}
_UNIT_SCALES = {"voltage": {"V": 1, "kV": 1000}, "current": {"A": 1, "kA": 1000}}


def _invalid(message):
    return sweep_error("SWEEP_INVALID_ANALYSIS", message)


def _unavailable(message):
    return sweep_error("SWEEP_METRIC_UNAVAILABLE", message)


def _finite(value):
    try:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    except OverflowError:
        return False


def validate_metric_specs(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 32:
        raise _invalid("metrics must be a list of at most 32 definitions.")
    definitions = []
    names = set()
    for item in raw:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("kind"), str)
            or item["kind"] not in _KINDS
        ):
            raise _invalid("Each metric needs a supported kind.")
        kind = item["kind"]
        required = {"name", "kind", "output_path", "window"}
        optional = set()
        if kind == "energy":
            required |= {"voltage_channel", "current_channel"}
            optional |= {"voltage_units", "current_units", "mode", "polarity"}
        elif kind == "i2t":
            required.add("current_channel")
            optional.add("current_units")
        else:
            required.add("channel")
            optional.add("channel_units")
            if kind == "threshold_crossing":
                required |= {"threshold", "operator"}
        if not required <= item.keys() or not item.keys() <= required | optional:
            raise _invalid("A metric has missing or unknown fields.")
        name = item["name"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name)
            or name in names
        ):
            raise _invalid("Metric names must be unique, bounded identifiers.")
        names.add(name)
        path = item["output_path"]
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or ":" in path
            or path.startswith("/")
            or any(p in {"", ".", ".."} for p in path.split("/"))
            or PurePosixPath(path).suffix.lower() not in {".out", ".psout"}
        ):
            raise _invalid(
                "Metric output_path must be a contained relative OUT or PSOUT path."
            )
        window = item["window"]
        if (
            not isinstance(window, list)
            or len(window) != 2
            or not all(_finite(v) for v in window)
            or window[0] < 0
            or window[1] <= window[0]
        ):
            raise _invalid(
                "Metric window needs finite nonnegative start < end in seconds."
            )
        for key in required:
            if key.endswith("channel"):
                value = item[key]
                if (
                    not isinstance(value, str)
                    or not value
                    or any(p.strip() != p or not p for p in value.split("/"))
                    or any(c in value for c in "\\*?[]")
                ):
                    raise _invalid("Metric channels must be exact retained selectors.")
        for key in optional & item.keys():
            if key.endswith("units") and (
                not isinstance(item[key], str) or not item[key] or len(item[key]) > 32
            ):
                raise _invalid("Unit declarations must be bounded, nonempty strings.")
        definition = deepcopy(item)
        if kind == "energy":
            mode, polarity = item.get("mode", "signed"), item.get("polarity", 1)
            if (
                not isinstance(mode, str)
                or mode not in {"signed", "positive", "absolute"}
                or not _finite(polarity)
                or polarity not in {-1, 1}
            ):
                raise _invalid(
                    "Energy mode is signed, positive or absolute; polarity is +1 or -1."
                )
            definition.update(mode=mode, polarity=polarity)
        if kind == "threshold_crossing" and (
            not _finite(item["threshold"])
            or not isinstance(item["operator"], str)
            or item["operator"] not in {">=", "<="}
        ):
            raise _invalid("Threshold crossing needs a finite threshold and >= or <=.")
        definitions.append(definition)
    return definitions


def _signal(payload, selector, declared_units, quantity=None):
    channels = [c for c in payload.get("channels", []) if c.get("path") == selector]
    if len(channels) != 1:
        raise _unavailable("A metric channel must have exactly one retained match.")
    channel = channels[0]
    time, values = channel.get("domain"), channel.get("values")
    if (
        not isinstance(time, list)
        or not isinstance(values, list)
        or not 2 <= len(time) == len(values) <= 1_000_000
        or not all(_finite(v) for v in [*time, *values])
        or any(b <= a for a, b in pairwise(time))
    ):
        raise _unavailable(
            "A metric needs at least two finite samples on an increasing time domain."
        )
    observed = channel.get("units") or None
    if declared_units and observed and declared_units != observed:
        raise _unavailable("A requested unit conflicts with retained metadata.")
    units = observed or declared_units
    if quantity and (not isinstance(units, str) or units not in _UNIT_SCALES[quantity]):
        raise _unavailable(
            "Physical metric units must be V/kV or A/kA, from metadata or an explicit declaration."
        )
    return channel, {
        "channel": selector,
        "units": units,
        "units_source": "metadata"
        if observed
        else "request"
        if declared_units
        else "unknown",
    }


def _interpolate(time, values, point):
    index = min(bisect_right(time, point) - 1, len(time) - 2)
    fraction = (point - time[index]) / (time[index + 1] - time[index])
    return values[index] * (1 - fraction) + values[index + 1] * fraction


def _clip(time, values, start, end):
    if start < time[0] or end > time[-1]:
        raise _unavailable(
            "The requested window is not fully covered; extrapolation is forbidden."
        )
    points = [start, *[t for t in time if start < t < end], end]
    return points, [_interpolate(time, values, t) for t in points]


def _energy(time, voltage, current, mode, polarity):
    terms = []
    for index, (start, end) in enumerate(pairwise(time)):
        ua, ub = voltage[index : index + 2]
        ia, ib = current[index : index + 2]
        cuts = [0.0, 1.0]
        for a, b in ((ua, ub), (ia, ib)):
            if (a < 0 < b) or (b < 0 < a):
                cuts.append(-a / (b - a))
        for left, right in pairwise(sorted(set(cuts))):
            u0, u1 = (ua * (1 - x) + ub * x for x in (left, right))
            i0, i1 = (ia * (1 - x) + ib * x for x in (left, right))
            integral = (
                polarity
                * (end - start)
                * (right - left)
                * (2 * u0 * i0 + u0 * i1 + u1 * i0 + 2 * u1 * i1)
                / 6
            )
            if mode == "absolute":
                integral = abs(integral)
            elif mode == "positive":
                integral = max(integral, 0)
            terms.append(integral)
    return math.fsum(terms)


def _evaluate_metrics(
    payload: dict[str, Any], definitions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    for definition in definitions:
        kind, window = definition["kind"], definition["window"]
        inputs = {}
        if kind == "energy":
            voltage, inputs["voltage"] = _signal(
                payload,
                definition["voltage_channel"],
                definition.get("voltage_units"),
                "voltage",
            )
            current, inputs["current"] = _signal(
                payload,
                definition["current_channel"],
                definition.get("current_units"),
                "current",
            )
            if voltage["domain"] != current["domain"]:
                raise _unavailable(
                    "Energy channels must share the exact retained time domain."
                )
            time, v = _clip(voltage["domain"], voltage["values"], *window)
            _, i = _clip(current["domain"], current["values"], *window)
            source = voltage
            factor = (
                _UNIT_SCALES["voltage"][inputs["voltage"]["units"]]
                * _UNIT_SCALES["current"][inputs["current"]["units"]]
            )
            value = (
                _energy(time, v, i, definition["mode"], definition["polarity"]) * factor
            )
            units, method = "J", "exact_product_of_piecewise_linear_signals"
        else:
            role = "current" if kind == "i2t" else "signal"
            source, inputs[role] = _signal(
                payload,
                definition["current_channel"]
                if kind == "i2t"
                else definition["channel"],
                definition.get("current_units")
                if kind == "i2t"
                else definition.get("channel_units"),
                "current" if kind == "i2t" else None,
            )
            time, values = _clip(source["domain"], source["values"], *window)
            if kind == "i2t":
                value = (
                    math.fsum(
                        (b - a) * (x * x + x * y + y * y) / 3
                        for (a, b), (x, y) in zip(pairwise(time), pairwise(values))
                    )
                    * _UNIT_SCALES["current"][inputs[role]["units"]] ** 2
                )
                units, method = "A^2 s", "exact_square_of_piecewise_linear_current"
            elif kind == "peak_abs":
                value = max(map(abs, values))
                units, method = (
                    inputs[role]["units"],
                    "bounded_sample_with_interpolated_window_edges",
                )
            else:
                threshold, operator = definition["threshold"], definition["operator"]
                satisfies = lambda v, threshold=threshold, operator=operator: (
                    v >= threshold if operator == ">=" else v <= threshold
                )
                value = time[0] if satisfies(values[0]) else None
                if value is None:
                    for index, (left, right) in enumerate(pairwise(values)):
                        if satisfies(right):
                            value = time[index] + (threshold - left) / (
                                right - left
                            ) * (time[index + 1] - time[index])
                            break
                units, method = "s", "first_satisfied_time_with_linear_interpolation"
        if value is not None and not _finite(value):
            raise _unavailable("Metric arithmetic produced a nonfinite result.")
        result = {
            **deepcopy(definition),
            "value": value,
            "units": units,
            "status": "available" if value is not None else "not_observed",
            "method": method,
            "statistics_scope": "bounded_sample_piecewise_linear",
            "time_units": "s",
            "inputs": inputs,
            "sample_count": len(source["domain"]),
            "total_samples": source.get("total_samples"),
            "window_points": len(time),
            "input_time_bounds": [source["domain"][0], source["domain"][-1]],
            "max_sample_interval_s": max(b - a for a, b in pairwise(time)),
        }
        if value is None:
            result["reason"] = "threshold_not_reached"
        results.append(result)
    return results


def evaluate_metrics(
    payload: dict[str, Any], definitions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    try:
        return _evaluate_metrics(payload, definitions)
    except (OverflowError, ValueError) as error:
        raise _unavailable(
            "Metric arithmetic exceeded finite numeric limits."
        ) from error
