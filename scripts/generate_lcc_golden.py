"""Generate golden.json from confirmed, independently reviewed reference output."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_SAMPLES = 1_000_000


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path} must be a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_with_hash(path: Path, label: str) -> tuple[Any, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    try:
        with path.open("rb") as stream:
            payload = stream.read()
    except OSError as error:
        raise ValueError(f"unable to read {label}: {path}") from error
    digest = hashlib.sha256(payload).hexdigest()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must contain valid UTF-8 JSON: {path}") from error
    return value, digest


def _channels(reference: Any) -> dict[str, Any]:
    if isinstance(reference, dict) and isinstance(reference.get("channels"), dict):
        return dict(reference["channels"])
    raise ValueError("reference output must contain a channels object")


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _window(value: Any, field: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{field} must contain [start, end]")
    start = _finite(value[0], f"{field}[0]")
    end = _finite(value[1], f"{field}[1]")
    if end <= start:
        raise ValueError(f"{field} must be strictly increasing")
    return start, end


def _acceptance_contract(blueprint: Path, value: Any | None = None) -> dict[str, Any]:
    contract_path = blueprint.parent / "acceptance.json"
    if value is None and (contract_path.is_symlink() or not contract_path.is_file()):
        raise ValueError("blueprint directory must contain acceptance.json with a golden comparison window")
    contract = _read_json(contract_path) if value is None else value
    if not isinstance(contract, dict) or not isinstance(contract.get("golden"), dict):
        raise ValueError("acceptance.json must contain a golden object")
    return contract


def _comparison_window(contract: dict[str, Any]) -> tuple[float, float]:
    return _window(contract["golden"].get("comparison_window"), "golden.comparison_window")


def _alignment_channel(contract: dict[str, Any]) -> str:
    golden = contract["golden"]
    alignment = golden.get("alignment")
    if not isinstance(alignment, dict) or not isinstance(alignment.get("channel"), str) or not alignment["channel"].strip():
        raise ValueError("golden.alignment.channel must be declared")
    return alignment["channel"].strip()


def _time_step(settings: Any, field: str) -> float:
    if not isinstance(settings, dict):
        raise ValueError("blueprint.settings must declare time_step_s and output_step_s")
    value = _finite(settings.get(field), f"blueprint.settings.{field}")
    if value <= 0:
        raise ValueError(f"blueprint.settings.{field} must be positive")
    return value


def _declared_selectors(blueprint_value: dict[str, Any]) -> dict[str, str]:
    outputs = blueprint_value.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("blueprint.outputs must be a non-empty array")
    selectors: dict[str, str] = {}
    for index, output in enumerate(outputs):
        if not isinstance(output, dict):
            raise ValueError(f"blueprint.outputs[{index}] must be an object")
        path = output.get("path")
        units = output.get("units")
        if not isinstance(path, str) or not path.strip() or not isinstance(units, str) or not units.strip():
            raise ValueError(f"blueprint.outputs[{index}] requires path and units")
        if path in selectors:
            raise ValueError(f"blueprint contains duplicate output selector: {path}")
        selectors[path] = units
    return selectors


def _windowed_channel(name: str, channel: Any, units: str, window: tuple[float, float]) -> dict[str, Any]:
    if not isinstance(channel, dict):
        raise ValueError(f"reference channel '{name}' must be an object")
    if channel.get("units") != units:
        raise ValueError(f"reference channel '{name}' units do not match blueprint: expected {units!r}, observed {channel.get('units')!r}")
    times = channel.get("time")
    values = channel.get("values")
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values) or not times:
        raise ValueError(f"reference channel '{name}' must contain equal non-empty time and values arrays")
    if len(times) > MAX_SAMPLES:
        raise ValueError(f"reference channel '{name}' exceeds the {MAX_SAMPLES} sample limit")
    normalized_times = [_finite(value, f"{name}.time") for value in times]
    normalized_values = [_finite(value, f"{name}.values") for value in values]
    if any(right <= left for left, right in zip(normalized_times, normalized_times[1:])):
        raise ValueError(f"reference channel '{name}' time must be strictly increasing")
    start, end = window
    if normalized_times[0] > start or normalized_times[-1] < end:
        raise ValueError(f"reference channel '{name}' does not cover the declared comparison window")
    selected = [index for index, time in enumerate(normalized_times) if start <= time <= end]
    if len(selected) < 2:
        raise ValueError(f"reference channel '{name}' has fewer than two samples in the comparison window")
    return {
        "units": units,
        "time": [normalized_times[index] for index in selected],
        "values": [normalized_values[index] for index in selected],
    }


def _review_evidence(
    review_record: Path | None,
    *,
    reference_output: Path,
    reference_hash: str,
    blueprint_hash: str,
    acceptance_hash: str,
    compiler: Path,
    compiler_hash: str,
    emtdc_time_step: float,
    output_step: float,
) -> tuple[dict[str, Any], str, dict[Path, str]]:
    if review_record is None:
        raise ValueError("an independent review record is required before golden generation")
    review, review_hash = _read_json_with_hash(review_record, "independent review record")
    required = {
        "schema_version", "review_status", "review_id", "reviewer", "reviewed_at_utc",
        "scope", "reference_kind", "independence_statement", "target_blueprint_sha256",
        "acceptance_sha256", "normalized_output", "source_project", "source_libraries",
        "raw_outputs", "output_metadata", "compiler", "emtdc_time_step_s", "output_step_s",
    }
    if not isinstance(review, dict) or set(review) != required:
        raise ValueError("independent review record has an invalid field set")
    if type(review["schema_version"]) is not int or review["schema_version"] != 1:
        raise ValueError("independent review schema_version must be 1")
    if review["review_status"] != "approved" or review["scope"] != "lcc.fixed_autonomous":
        raise ValueError("independent review must approve the lcc.fixed_autonomous scope")
    if not isinstance(review["reference_kind"], str) or review["reference_kind"] not in {
        "official_reference", "independent_manual_assembly", "external_reviewed_output",
    }:
        raise ValueError("independent review requires an independent reference_kind")
    for field in ("review_id", "reviewer", "independence_statement"):
        if not isinstance(review[field], str) or not review[field].strip():
            raise ValueError(f"independent review requires {field}")
    timestamp = review["reviewed_at_utc"]
    if not isinstance(timestamp, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", timestamp
    ) is None:
        raise ValueError("reviewed_at_utc must be a UTC RFC3339 timestamp")
    reviewed_at = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    if reviewed_at > datetime.now(timezone.utc):
        raise ValueError("reviewed_at_utc cannot be in the future")
    if review["target_blueprint_sha256"] != blueprint_hash or review["acceptance_sha256"] != acceptance_hash:
        raise ValueError("independent review blueprint/acceptance hash mismatch")
    if (
        _finite(review["emtdc_time_step_s"], "review.emtdc_time_step_s") != emtdc_time_step
        or _finite(review["output_step_s"], "review.output_step_s") != output_step
    ):
        raise ValueError("independent review timestep differs from target blueprint")

    snapshots = {review_record: review_hash}

    def verify(item: Any, field: str, suffixes: set[str]) -> Path:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError(f"review.{field} requires path and sha256")
        if not isinstance(item["path"], str) or not item["path"]:
            raise ValueError(f"review.{field}.path must be an absolute file path")
        path = Path(item["path"])
        if not path.is_absolute() or path.suffix.casefold() not in suffixes:
            raise ValueError(f"review.{field} has an invalid absolute path or file type")
        if any(parent.is_symlink() or getattr(parent, "is_junction", lambda: False)()
               for parent in [path, *path.parents]):
            raise ValueError(f"review.{field} cannot contain linked path components")
        expected = item["sha256"]
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError(f"review.{field} requires a SHA-256 hash")
        if _sha256(path) != expected:
            raise ValueError(f"review.{field} source hash mismatch")
        snapshots[path] = expected
        return path

    normalized = verify(review["normalized_output"], "normalized_output", {".json"})
    if normalized.resolve() != reference_output.resolve() or review["normalized_output"]["sha256"] != reference_hash:
        raise ValueError("independent review does not bind this reference output")
    reviewed_compiler = verify(review["compiler"], "compiler", {".exe"})
    if reviewed_compiler.resolve() != compiler.resolve() or review["compiler"]["sha256"] != compiler_hash:
        raise ValueError("independent review does not bind this compiler")
    verify(review["source_project"], "source_project", {".pscx"})
    for field, suffixes in (
        ("source_libraries", {".pslx"}),
        ("raw_outputs", {".out", ".psout"}),
        ("output_metadata", {".inf", ".infx"}),
    ):
        items = review[field]
        if not isinstance(items, list) or not items:
            raise ValueError(f"independent review requires nonempty {field}")
        seen: set[Path] = set()
        for index, item in enumerate(items):
            path = verify(item, f"{field}[{index}]", suffixes).resolve()
            if path in seen:
                raise ValueError(f"independent review contains duplicate {field}")
            seen.add(path)
    return review, review_hash, snapshots


def generate(
    reference_output: Path, blueprint: Path, library: Path, compiler: Path,
    *, review_record: Path | None = None,
) -> Path:
    for path, label in ((reference_output, "reference output"), (blueprint, "blueprint"), (library, "library"), (compiler, "compiler")):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{label} must be a regular file: {path}")
    blueprint_value, blueprint_hash = _read_json_with_hash(blueprint, "blueprint")
    reference_value, reference_hash = _read_json_with_hash(reference_output, "reference output")
    if not isinstance(blueprint_value, dict) or not isinstance(reference_value, dict):
        raise ValueError("blueprint and reference output must contain structured JSON")
    channels = _channels(reference_value)
    selectors = _declared_selectors(blueprint_value)
    missing = [selector for selector in selectors if selector not in channels]
    if missing:
        raise ValueError(f"reference output is missing declared selectors: {missing}")
    unexpected = sorted(set(channels) - set(selectors))
    if unexpected:
        raise ValueError(f"reference output contains undeclared selectors: {unexpected}")
    acceptance_path = blueprint.parent / "acceptance.json"
    acceptance, acceptance_hash = _read_json_with_hash(acceptance_path, "acceptance contract")
    acceptance = _acceptance_contract(blueprint, acceptance)
    library_hash = _sha256(library)
    compiler_hash = _sha256(compiler)
    comparison_window = _comparison_window(acceptance)
    alignment_channel = _alignment_channel(acceptance)
    if alignment_channel not in selectors:
        raise ValueError(f"golden alignment channel is not a declared output selector: {alignment_channel}")
    settings = blueprint_value.get("settings")
    emtdc_time_step = _time_step(settings, "time_step_s")
    output_step = _time_step(settings, "output_step_s")
    review, review_hash, review_snapshots = _review_evidence(
        review_record,
        reference_output=reference_output,
        reference_hash=reference_hash,
        blueprint_hash=blueprint_hash,
        acceptance_hash=acceptance_hash,
        compiler=compiler,
        compiler_hash=compiler_hash,
        emtdc_time_step=emtdc_time_step,
        output_step=output_step,
    )
    selected_channels = {
        name: _windowed_channel(name, channels[name], units, comparison_window)
        for name, units in selectors.items()
    }
    payload = {
        "schema_version": 1,
        "source": {
            "review_record_sha256": review_hash,
            "review": review,
            "reference_output_sha256": reference_hash,
            "blueprint_sha256": blueprint_hash,
            "acceptance_sha256": acceptance_hash,
            "library_sha256": library_hash,
            "compiler": compiler.name,
            "compiler_sha256": compiler_hash,
            "emtdc_time_step_s": emtdc_time_step,
            "output_step_s": output_step,
            "alignment_channel": alignment_channel,
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "comparison_window": list(comparison_window),
        "channels": {name: selected_channels[name] for name in sorted(selected_channels)},
    }
    snapshots = {
        **review_snapshots,
        reference_output: reference_hash,
        blueprint: blueprint_hash,
        acceptance_path: acceptance_hash,
        library: library_hash,
        compiler: compiler_hash,
    }
    for path, expected_hash in snapshots.items():
        observed_hash = _sha256(path)
        if observed_hash != expected_hash:
            raise ValueError(f"input changed during golden generation: {path}")
    destination = blueprint.parent / "golden.json"
    if destination.resolve() in {path.resolve() for path in snapshots}:
        raise ValueError("golden destination cannot overwrite a reviewed source input")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, prefix=".golden-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=True, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    statistics = {
        name: {
            "samples": len(channel["values"]),
            "time_domain": [channel["time"][0], channel["time"][-1]],
            "minimum": min(channel["values"]),
            "maximum": max(channel["values"]),
        }
        for name, channel in selected_channels.items()
    }
    print(json.dumps({"golden": str(destination), "channels": len(selected_channels), "comparison_window": list(comparison_window), "statistics": statistics, "source": payload["source"]}, ensure_ascii=True, sort_keys=True))
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-output", required=True, type=Path)
    parser.add_argument("--blueprint", required=True, type=Path)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--review-record", required=True, type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("writing golden.json requires literal --confirm")
    try:
        generate(
            args.reference_output.absolute(), args.blueprint.absolute(),
            args.library.absolute(), args.compiler.absolute(),
            review_record=args.review_record.absolute(),
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"generate_lcc_golden: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
