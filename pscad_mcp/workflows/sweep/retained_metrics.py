"""Read-only physical analysis of finalized, hash-verified campaign artifacts."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from pathlib import Path

from ...core.pscad_adapter import PscadAdapter
from .analysis import legacy_dataset_paths, read_legacy
from .metrics import evaluate_metrics, validate_metric_specs
from .store import contained, digest, file_hash, sweep_error


def enrich_metrics(report, raw_definitions, manifest, campaign_root):
    definitions = validate_metric_specs(raw_definitions)
    collected = {
        output["path"]: set(output["channels"])
        for output in manifest["spec"]["outputs"]
    }
    for definition in definitions:
        selectors = {
            value for key, value in definition.items() if key.endswith("channel")
        }
        if (
            definition["output_path"] not in collected
            or not selectors <= collected[definition["output_path"]]
        ):
            raise sweep_error(
                "SWEEP_INVALID_ANALYSIS",
                "Metrics may only use outputs and exact channels selected by this campaign.",
            )
    report = deepcopy(report)
    for scenario in report["scenarios"]:
        scenario["metrics"] = []
        if scenario["state"] != "succeeded":
            continue
        for output_path in sorted({d["output_path"] for d in definitions}):
            subset = [d for d in definitions if d["output_path"] == output_path]
            selectors = tuple(
                sorted(
                    {
                        value
                        for d in subset
                        for key, value in d.items()
                        if key.endswith("channel")
                    }
                )
            )
            matches = [
                a
                for a in scenario["artifacts"]
                if a["relative_path"].endswith("/outputs/" + output_path)
            ]
            if len(matches) != 1:
                raise sweep_error(
                    "SWEEP_EVIDENCE_CHANGED",
                    "A metric output must have exactly one retained artifact.",
                )
            primary = contained(
                campaign_root, matches[0]["relative_path"], must_exist=True
            )
            output_root = primary.parents[len(Path(output_path).parts) - 1]
            if primary.suffix.casefold() == ".out":
                metadata, parts = legacy_dataset_paths(output_root, output_path)
                files = [metadata, *parts]
                payload = read_legacy(
                    output_root, output_path, selectors, manifest["spec"]["max_samples"]
                )
            else:
                files = [primary]
                # This file reader does not invoke the executor or connect to PSCAD.
                adapter = PscadAdapter(None, pscad_module=False, environ={})
                payload = adapter._read_psout_sync(
                    primary, 0, manifest["spec"]["max_samples"], None, False
                )
            artifacts = {a["path"]: a for a in scenario["artifacts"]}
            evidence = []
            for path in files:
                item = artifacts.get(str(path))
                if item is None or file_hash(path) != item["sha256"]:
                    raise sweep_error(
                        "SWEEP_EVIDENCE_CHANGED",
                        "A metric input changed during analysis.",
                    )
                evidence.append(deepcopy(item))
            for metric in evaluate_metrics(payload, subset):
                metric["evidence"] = deepcopy(evidence)
                metric["definition_sha256"] = digest(
                    next(d for d in subset if d["name"] == metric["name"])
                )
                scenario["metrics"].append(metric)
    baseline = next(
        (
            s
            for s in report["scenarios"]
            if s["name"] == report.get("baseline_scenario")
            and s["state"] == "succeeded"
        ),
        {},
    )
    reference = {m["name"]: m for m in baseline.get("metrics", [])}
    for scenario in report["scenarios"]:
        for metric in scenario["metrics"]:
            original = reference.get(metric["name"], {}).get("value")
            value = metric["value"]
            metric["comparison"] = {}
            metric["comparison_warnings"] = []
            if value is not None and original is not None:
                delta = value - original
                relative = delta / abs(original) if original else None
                metric["comparison"] = {
                    "absolute_delta": delta if isfinite(delta) else None,
                    "relative_delta": relative
                    if relative is not None and isfinite(relative)
                    else None,
                }
                if original == 0:
                    metric["comparison_warnings"].append("zero_baseline")
            elif report.get("baseline_scenario") is not None:
                metric["comparison_warnings"].append("baseline_metric_unavailable")
    return report, definitions
