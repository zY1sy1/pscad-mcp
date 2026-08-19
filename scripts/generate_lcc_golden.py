"""Generate a golden.json only from an explicitly confirmed reference output."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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


def generate(reference_output: Path, blueprint: Path, library: Path, compiler: Path) -> Path:
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
    selected_channels = {
        name: _windowed_channel(name, channels[name], units, comparison_window)
        for name, units in selectors.items()
    }
    payload = {
        "schema_version": 1,
        "source": {
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
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("writing golden.json requires literal --confirm")
    try:
        generate(args.reference_output.resolve(), args.blueprint.resolve(), args.library.resolve(), args.compiler.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"generate_lcc_golden: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
