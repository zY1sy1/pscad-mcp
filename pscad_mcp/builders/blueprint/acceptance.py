"""Generic, source-class-aware acceptance rule evaluation."""

from __future__ import annotations

import math
from statistics import fmean
from typing import Any, Iterable, Mapping

from ...core.backend.base import BackendError


_RULE_KINDS = {
    "all_finite",
    "exact_value",
    "exact_set",
    "minimum",
    "maximum",
    "inclusive_range",
    "allowed_states",
    "transition_count",
    "transition_time",
    "window_summary",
    "monotonic",
}


def _error(message: str, **details: Any) -> BackendError:
    return BackendError("BLUEPRINT_ACCEPTANCE_INVALID", message, "blueprint", "evaluate_blueprint_acceptance", details)


def _values(values: Iterable[Any]) -> list[Any]:
    if isinstance(values, (str, bytes, Mapping)):
        raise _error("Acceptance samples must be an array.")
    result = list(values)
    if not result:
        raise _error("Acceptance samples cannot be empty.")
    for value in result:
        if isinstance(value, float) and not math.isfinite(value):
            raise _error("Acceptance samples must be finite.")
        if not isinstance(value, (str, int, float, bool)):
            raise _error("Acceptance samples must be scalar JSON values.")
    return result


def _number(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise _error(f"Rule argument {name} must be a finite number.")
    return float(value)


def _numeric(values: list[Any]) -> list[float]:
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
        raise _error("This rule requires numeric samples.")
    return [float(value) for value in values]


def _observed(values: list[Any]) -> dict[str, Any]:
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        numeric = [float(value) for value in values]
        return {"count": len(values), "minimum": min(numeric), "maximum": max(numeric)}
    return {"count": len(values), "states": sorted(set(values), key=lambda item: str(item))}


def evaluate_rule(rule: Mapping[str, Any], values: Iterable[Any], *, domain: Iterable[Any] | None = None) -> dict[str, Any]:
    if not isinstance(rule, Mapping) or not isinstance(rule.get("kind"), str) or not isinstance(rule.get("arguments"), Mapping):
        raise _error("Acceptance rule requires kind and arguments.")
    kind = rule["kind"]
    arguments = rule["arguments"]
    if kind not in _RULE_KINDS:
        raise _error("Acceptance rule kind is not supported.", kind=kind)
    samples = _values(values)
    observed = _observed(samples)
    passed = False
    if kind == "all_finite":
        passed = True
    elif kind == "exact_value":
        if "value" not in arguments:
            raise _error("exact_value requires value.")
        passed = all(value == arguments["value"] for value in samples)
    elif kind in {"exact_set", "allowed_states"}:
        allowed = arguments.get("values")
        if not isinstance(allowed, list) or not allowed:
            raise _error(f"{kind} requires a non-empty values array.")
        passed = set(samples) == set(allowed) if kind == "exact_set" else set(samples) <= set(allowed)
    elif kind == "minimum":
        passed = min(_numeric(samples)) >= _number(arguments.get("minimum"), "minimum")
    elif kind == "maximum":
        passed = max(_numeric(samples)) <= _number(arguments.get("maximum"), "maximum")
    elif kind == "inclusive_range":
        minimum = _number(arguments.get("minimum"), "minimum")
        maximum = _number(arguments.get("maximum"), "maximum")
        if minimum > maximum:
            raise _error("inclusive_range minimum cannot exceed maximum.")
        passed = all(minimum <= value <= maximum for value in _numeric(samples))
    elif kind == "transition_count":
        count = arguments.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise _error("transition_count requires a non-negative integer count.")
        observed_count = sum(left != right for left, right in zip(samples, samples[1:]))
        observed["transition_count"] = observed_count
        passed = observed_count == count
    elif kind == "transition_time":
        if domain is None:
            raise _error("transition_time requires a time domain.")
        times = _numeric(_values(domain))
        if len(times) != len(samples):
            raise _error("transition_time domain length must match samples.")
        target = arguments.get("to")
        minimum = _number(arguments.get("minimum"), "minimum")
        maximum = _number(arguments.get("maximum"), "maximum")
        transition = next((times[index] for index in range(1, len(samples)) if samples[index] == target and samples[index - 1] != target), None)
        observed["transition_time"] = transition
        passed = transition is not None and minimum <= transition <= maximum
    elif kind == "window_summary":
        if domain is None:
            raise _error("window_summary requires a time domain.")
        times = _numeric(_values(domain))
        numeric = _numeric(samples)
        if len(times) != len(numeric):
            raise _error("window_summary domain length must match samples.")
        window = arguments.get("window")
        if not isinstance(window, list) or len(window) != 2:
            raise _error("window_summary requires a relative two-value window.")
        start = _number(window[0], "window[0]")
        end = _number(window[1], "window[1]")
        if not 0 <= start <= end <= 1:
            raise _error("window_summary relative window must satisfy 0 <= start <= end <= 1.")
        lower = times[0] + (times[-1] - times[0]) * start
        upper = times[0] + (times[-1] - times[0]) * end
        selected = [value for time, value in zip(times, numeric) if lower <= time <= upper]
        if not selected:
            raise _error("window_summary selected no samples.")
        metric = arguments.get("metric")
        metrics = {"minimum": min(selected), "maximum": max(selected), "mean": fmean(selected), "first": selected[0], "last": selected[-1]}
        if metric not in metrics:
            raise _error("window_summary metric is not supported.")
        summary = metrics[metric]
        observed.update({"window": [lower, upper], "metric": metric, "summary": summary})
        minimum = arguments.get("minimum")
        maximum = arguments.get("maximum")
        expected = arguments.get("value")
        passed = True
        if minimum is not None:
            passed = passed and summary >= _number(minimum, "minimum")
        if maximum is not None:
            passed = passed and summary <= _number(maximum, "maximum")
        if expected is not None:
            passed = passed and summary == _number(expected, "value")
        if minimum is None and maximum is None and expected is None:
            raise _error("window_summary requires minimum, maximum, or value.")
    else:
        numeric = _numeric(samples)
        direction = arguments.get("direction")
        strict = arguments.get("strict", False)
        if direction not in {"increasing", "decreasing"} or not isinstance(strict, bool):
            raise _error("monotonic requires direction and a boolean strict flag.")
        pairs = zip(numeric, numeric[1:])
        if direction == "increasing":
            passed = all(left < right if strict else left <= right for left, right in pairs)
        else:
            passed = all(left > right if strict else left >= right for left, right in pairs)
    return {"kind": kind, "passed": passed, "observed": observed}


def evaluate_acceptance(
    contract: Mapping[str, Any],
    dataset: Mapping[str, Any],
    *,
    structure_acceptance: bool = True,
    parameters_acceptance: bool = True,
    messages_acceptance: bool = True,
    trusted_source_classes: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(contract, Mapping) or not isinstance(dataset, Mapping):
        raise _error("Acceptance contract and output dataset must be objects.")
    channels = dataset.get("channels")
    outputs = contract.get("outputs")
    rules = contract.get("rules")
    if not isinstance(channels, Mapping) or not isinstance(outputs, (list, tuple)) or not isinstance(rules, (list, tuple)):
        raise _error("Acceptance contract or output dataset has an invalid shape.")
    output_results: list[dict[str, Any]] = []
    for output in outputs:
        channel_name = output["channel"]
        observed = channels.get(channel_name)
        present = isinstance(observed, Mapping)
        units_match = present and observed.get("units") == output["units"]
        finite = False
        if present and isinstance(observed.get("values"), (list, tuple)):
            values = observed["values"]
            finite = bool(values) and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in values
            )
        output_results.append(
            {
                "channel": channel_name,
                "required": output["required"],
                "present": present,
                "units_match": units_match,
                "finite": finite,
                "passed": present and units_match and finite,
            }
        )
    rule_results: list[dict[str, Any]] = []
    for rule in rules:
        observed = channels.get(rule["channel"])
        if not isinstance(observed, Mapping) or not isinstance(observed.get("values"), (list, tuple)):
            result = {"kind": rule["kind"], "passed": False, "observed": {"missing_channel": rule["channel"]}}
        else:
            try:
                result = evaluate_rule(rule, observed["values"], domain=observed.get("domain"))
            except BackendError as error:
                result = {"kind": rule["kind"], "passed": False, "observed": {"error": error.to_dict()}}
        rule_results.append(
            {
                "rule_id": rule["rule_id"],
                "channel": rule["channel"],
                "required": rule["required"],
                "source_class": rule["source_class"],
                "physical": rule["physical"],
                **result,
            }
        )
    outputs_passed = all(result["passed"] for result in output_results if result["required"])
    rules_passed = all(result["passed"] for result in rule_results if result["required"])
    run_through = bool(structure_acceptance and parameters_acceptance and messages_acceptance and outputs_passed and rules_passed)
    trusted = set(trusted_source_classes or {"engineering_accepted"})
    physical_rules = [result for result in rule_results if result["physical"]]
    physical = bool(
        run_through
        and physical_rules
        and all(result["passed"] and result["source_class"] in trusted for result in physical_rules)
    )
    return {
        "structure_acceptance": bool(structure_acceptance),
        "parameters_acceptance": bool(parameters_acceptance),
        "messages_acceptance": bool(messages_acceptance),
        "output_acceptance": outputs_passed,
        "run_through_acceptance": run_through,
        "physical_acceptance": physical,
        "outputs": output_results,
        "rules": rule_results,
    }
