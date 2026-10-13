"""Strict bounded channel statistics, baseline comparison and constrained ranking."""

from __future__ import annotations

import hashlib
import math
import re
from copy import deepcopy
from itertools import chain, pairwise
from pathlib import Path
from typing import Any

from ...core.pscad_adapter import _legacy_first_numeric_row
from .store import contained, sweep_error

STATISTICS = frozenset({"min", "max", "mean", "first", "last", "rms", "peak_abs"})


def _metadata(path: Path) -> list[dict[str, Any]]:
    channels = []
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            match = re.match(r"\s*PGB\((\d+)\)\s+Output\s+(.*)", line, re.IGNORECASE)
            if not match:
                continue
            fields = {
                key.casefold(): quoted or bare
                for key, quoted, bare in re.findall(
                    r'([A-Za-z][A-Za-z0-9_]*)=(?:"([^"]*)"|(\S+))', match[2]
                )
            }
            description = fields.get("desc", "").strip("/")
            group = fields.get("group", "").strip("/")
            if not description:
                raise sweep_error(
                    "SWEEP_OUTPUT_INVALID", "An INF channel has no description."
                )
            channels.append(
                {
                    "call_id": int(match[1]),
                    "path": f"{group}/{description}" if group else description,
                    "units": fields.get("units") or None,
                }
            )
            if len(channels) > 10000:
                raise sweep_error(
                    "SWEEP_OUTPUT_INVALID", "INF is limited to 10000 channels."
                )
    if not channels or [item["call_id"] for item in channels] != list(
        range(1, len(channels) + 1)
    ):
        raise sweep_error(
            "SWEEP_OUTPUT_INVALID",
            "INF channel IDs must be non-empty, contiguous and ordered.",
        )
    if len({item["path"] for item in channels}) != len(channels):
        raise sweep_error("SWEEP_OUTPUT_INVALID", "INF channel paths are ambiguous.")
    return channels


def legacy_dataset_paths(work: Path, relative: str) -> tuple[Path, list[Path]]:
    output = contained(work, relative)
    base = re.sub(r"_\d{2}$", "", output.stem)
    metadata = contained(
        work, str(output.parent.relative_to(work) / (base + ".inf")), must_exist=True
    )
    channels = _metadata(metadata)
    parts = [
        contained(
            work,
            str(output.parent.relative_to(work) / f"{base}_{index:02d}.out"),
            must_exist=True,
        )
        for index in range(1, (len(channels) + 9) // 10 + 1)
    ]
    observed = sorted(output.parent.glob(f"{base}_*.out"))
    if observed != sorted(parts):
        raise sweep_error(
            "SWEEP_OUTPUT_INVALID",
            "The numbered OUT dataset is incomplete or ambiguous.",
        )
    return metadata, parts


def _rows(path: Path, width: int):
    with path.open("r", encoding="utf-8") as stream:
        previous = None
        try:
            first = _legacy_first_numeric_row(stream)
        except ValueError as error:
            raise sweep_error(
                "SWEEP_OUTPUT_INVALID", "OUT contains invalid numeric data."
            ) from error
        for line in chain([first], stream):
            if not line.strip():
                continue
            try:
                row = [float(value) for value in line.split()]
            except ValueError as error:
                raise sweep_error(
                    "SWEEP_OUTPUT_INVALID", "OUT contains non-numeric data."
                ) from error
            if len(row) != width + 1 or not all(math.isfinite(value) for value in row):
                raise sweep_error(
                    "SWEEP_OUTPUT_INVALID",
                    "OUT contains invalid columns or non-finite data.",
                )
            if previous is not None and row[0] <= previous:
                raise sweep_error(
                    "SWEEP_OUTPUT_INVALID", "OUT time must be strictly increasing."
                )
            previous = row[0]
            yield row


def read_legacy(
    work: Path, relative: str, selectors: tuple[str, ...], max_samples: int
) -> dict[str, Any]:
    metadata, parts = legacy_dataset_paths(work, relative)
    definitions = _metadata(metadata)
    available = {item["path"] for item in definitions}
    if not set(selectors) <= available:
        raise sweep_error("SWEEP_CHANNEL_MISSING", "A required OUT channel is absent.")
    channels = []
    expected_count = None
    expected_domain = None
    for number, path in enumerate(parts):
        subset = definitions[number * 10 : number * 10 + 10]
        count = 0
        domain_hash = hashlib.sha256()
        for row in _rows(path, len(subset)):
            count += 1
            domain_hash.update(row[0].hex().encode("ascii") + b"\n")
        if not count or (
            expected_count is not None
            and (count != expected_count or domain_hash.hexdigest() != expected_domain)
        ):
            raise sweep_error(
                "SWEEP_OUTPUT_INVALID",
                "OUT parts have empty or different time domains.",
            )
        expected_count, expected_domain = count, domain_hash.hexdigest()
        sample_count = min(count, max_samples)
        indices = (
            {0}
            if sample_count == 1
            else {i * (count - 1) // (sample_count - 1) for i in range(sample_count)}
        )
        selected = [
            (index + 1, definition, [])
            for index, definition in enumerate(subset)
            if definition["path"] in selectors
        ]
        domain = []
        for index, row in enumerate(_rows(path, len(subset))):
            if index in indices:
                domain.append(row[0])
                for column, _definition, values in selected:
                    values.append(row[column])
        for _column, definition, values in selected:
            channels.append(
                {
                    "path": definition["path"],
                    "units": definition["units"],
                    "values": values,
                    "domain": domain,
                    "total_samples": count,
                }
            )
    return {"channels": channels, "warnings": []}


def summarize(
    payload: dict[str, Any], selectors: tuple[str, ...], max_samples: int
) -> list[dict[str, Any]]:
    selected = []
    for selector in selectors:
        matches = [
            channel
            for channel in payload.get("channels", [])
            if channel.get("path") == selector
        ]
        if len(matches) != 1:
            raise sweep_error(
                "SWEEP_CHANNEL_MISSING",
                "A channel selector must have exactly one match.",
                channel=selector,
            )
        channel = matches[0]
        values = channel.get("values", [])
        if (
            not isinstance(values, list)
            or not values
            or len(values) > max_samples
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in values
            )
        ):
            raise sweep_error(
                "SWEEP_OUTPUT_INVALID",
                "Channel samples must be bounded, non-empty and finite.",
                channel=selector,
            )
        domain = channel.get("domain", [])
        if (
            not isinstance(domain, list)
            or len(domain) != len(values)
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in domain
            )
            or any(b <= a for a, b in pairwise(domain))
        ):
            raise sweep_error(
                "SWEEP_OUTPUT_INVALID",
                "A selected channel needs a matching, increasing time domain.",
                channel=selector,
            )
        # Scaling before summation avoids overflow for finite, large samples.
        scale = max(abs(value) for value in values)
        mean = math.fsum(value / len(values) for value in values)
        rms = (
            scale
            * math.sqrt(
                math.fsum((value / scale) ** 2 for value in values) / len(values)
            )
            if scale
            else 0.0
        )
        statistics = {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": mean,
            "first": values[0],
            "last": values[-1],
            "rms": rms,
            "peak_abs": scale,
        }
        selected.append(
            {
                "path": selector,
                "units": channel.get("units"),
                "statistics_scope": "bounded_sample",
                "max_samples": max_samples,
                "total_samples": channel.get("total_samples"),
                "time_bounds": [domain[0], domain[-1]],
                "statistics": statistics,
            }
        )
    return selected


def compare(report: dict[str, Any], baseline_name: str | None) -> dict[str, Any]:
    report = deepcopy(report)
    baseline = next(
        (
            item
            for item in report["scenarios"]
            if item["name"] == baseline_name and item["state"] == "succeeded"
        ),
        None,
    )
    reference = {
        (output["path"], channel["path"]): channel
        for output in (baseline or {}).get("outputs", [])
        for channel in output["channels"]
    }
    report["baseline_scenario"] = baseline_name
    report["baseline_available"] = baseline is not None
    for scenario in report["scenarios"]:
        for output in scenario.get("outputs", []):
            for channel in output["channels"]:
                base = reference.get((output["path"], channel["path"]))
                channel["comparison"] = {}
                warnings = []
                if baseline_name is not None and base is None:
                    warnings.append("baseline_unavailable")
                for metric in sorted(STATISTICS):
                    if base is None:
                        continue
                    value, original = (
                        channel["statistics"][metric],
                        base["statistics"][metric],
                    )
                    delta = value - original
                    relative = delta / abs(original) if original else None
                    channel["comparison"][metric] = {
                        "absolute_delta": delta if math.isfinite(delta) else None,
                        "relative_delta": relative
                        if relative is not None and math.isfinite(relative)
                        else None,
                    }
                    if original == 0:
                        warnings.append(f"zero_baseline:{metric}")
                channel["comparison_warnings"] = warnings
    return report


def _metric(raw: Any, extra: set[str]) -> dict[str, Any]:
    required = {"output_path", "channel", "statistic"} | extra
    if (
        not isinstance(raw, dict)
        or set(raw) != required
        or not isinstance(raw.get("statistic"), str)
        or raw["statistic"] not in STATISTICS
    ):
        raise sweep_error(
            "SWEEP_INVALID_ANALYSIS",
            "An analysis metric needs an exact output path, channel and supported statistic.",
        )
    if not all(
        isinstance(raw.get(key), str) and raw[key] for key in ("output_path", "channel")
    ):
        raise sweep_error(
            "SWEEP_INVALID_ANALYSIS", "Metric paths must be non-empty strings."
        )
    return dict(raw)


def rank(
    report: dict[str, Any],
    objective: dict[str, Any] | None = None,
    constraints: list[dict[str, Any]] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise sweep_error("SWEEP_INVALID_ANALYSIS", "limit must be between 1 and 100.")
    if objective is not None:
        objective = _metric(objective, {"direction"})
        if not isinstance(objective["direction"], str) or objective[
            "direction"
        ] not in {"minimize", "maximize"}:
            raise sweep_error(
                "SWEEP_INVALID_ANALYSIS", "direction must be minimize or maximize."
            )
    constraints = [] if constraints is None else constraints
    if not isinstance(constraints, list) or len(constraints) > 32:
        raise sweep_error(
            "SWEEP_INVALID_ANALYSIS", "At most 32 constraints are supported."
        )
    normalized = []
    for item in constraints:
        item = _metric(item, {"operator", "value"})
        if (
            not isinstance(item["operator"], str)
            or item["operator"] not in {"<=", ">=", "=="}
            or isinstance(item["value"], bool)
            or not isinstance(item["value"], (int, float))
            or not math.isfinite(item["value"])
        ):
            raise sweep_error(
                "SWEEP_INVALID_ANALYSIS",
                "A constraint needs <=, >= or == and a finite numeric value.",
            )
        normalized.append(item)
    ranking = []
    excluded = []
    for scenario in report["scenarios"]:
        if scenario["state"] != "succeeded":
            excluded.append({"name": scenario["name"], "reason": scenario["state"]})
            continue
        metrics = {
            (output["path"], channel["path"], name): value
            for output in scenario.get("outputs", [])
            for channel in output["channels"]
            for name, value in channel["statistics"].items()
        }

        def lookup(metric, metrics=metrics):
            key = (metric["output_path"], metric["channel"], metric["statistic"])
            if key not in metrics:
                raise sweep_error(
                    "SWEEP_CHANNEL_MISSING",
                    "An analysis metric is not in the retained results.",
                )
            return metrics[key]

        violations = []
        for item in normalized:
            observed = lookup(item)
            valid = {
                "<=": observed <= item["value"],
                ">=": observed >= item["value"],
                "==": observed == item["value"],
            }[item["operator"]]
            if not valid:
                violations.append({**item, "observed": observed})
        ranking.append(
            {
                "name": scenario["name"],
                "feasible": not violations,
                "objective_value": lookup(objective) if objective else None,
                "violations": violations,
            }
        )
    if objective:
        sign = -1 if objective["direction"] == "maximize" else 1
        ranking.sort(
            key=lambda item: (not item["feasible"], sign * item["objective_value"])
        )
    else:
        ranking.sort(key=lambda item: not item["feasible"])
    feasible = [item for item in ranking if item["feasible"]]
    return {
        "optimization_scope": "evaluated_scenarios",
        "statistics_scope": "bounded_sample",
        "objective": objective,
        "constraints": normalized,
        "best": feasible[0] if feasible and objective else None,
        "ranking": ranking[:limit],
        "evaluated_count": len(ranking),
        "feasible_count": len(feasible),
        "infeasible_count": len(ranking) - len(feasible),
        "excluded": excluded,
        "report": report,
    }
