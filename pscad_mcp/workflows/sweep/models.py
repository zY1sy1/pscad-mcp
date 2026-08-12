"""Validation and normalized records for parameter-sweep manifests."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ...core.path_policy import PathPolicy


JsonScalar = None | bool | int | float | str

_ENTRY_SUFFIXES = {".pscx", ".pslx", ".pswx"}
_OUTPUT_SUFFIXES = {".out", ".psout"}
_TOP_LEVEL_FIELDS = {
    "source_root",
    "entry_file",
    "project_name",
    "scenarios",
    "outputs",
    "baseline_scenario",
    "run_timeout_seconds",
    "max_samples",
    "poll_interval_seconds",
    "output_stability_seconds",
    "filesystem_timestamp_tolerance_seconds",
}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object.")
    return value


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted((key for key in raw if key not in allowed), key=str)
    if unknown:
        names = ", ".join(repr(name) for name in unknown)
        raise ValueError(f"{label} contains unknown field(s): {names}.")


def _require_fields(raw: Mapping[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required.difference(raw))
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"{label} is missing required field(s): {names}.")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


def _number_in_range(
    value: Any,
    label: str,
    minimum: float,
    maximum: float,
) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number from {minimum} through {maximum}.")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be a number from {minimum} through {maximum}.")
    return value


def _integer_in_range(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer from {minimum} through {maximum}.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} through {maximum}.")
    return value


def _relative_path(
    value: Any,
    label: str,
    base_dir: Path,
    path_policy: PathPolicy,
    suffixes: set[str],
    *,
    must_exist: bool,
) -> tuple[str, Path]:
    raw_path = _nonempty_string(value, label)
    candidate = Path(raw_path)
    if candidate.is_absolute() or candidate.anchor:
        raise ValueError(f"{label} must be a relative path.")
    try:
        resolved = path_policy.resolve_child(
            str(base_dir),
            raw_path,
            suffixes=suffixes,
            must_exist=must_exist,
        )
        relative = resolved.relative_to(base_dir)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise ValueError(f"Invalid {label}: {error}") from error
    return relative.as_posix(), resolved


def _directory_key(name: str) -> str:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
    return f"scenario-{digest}"


def _json_scalar(value: Any, label: str) -> JsonScalar:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"{label} must be a JSON scalar (null, boolean, number, or string).")


@dataclass(frozen=True)
class ParameterUpdate:
    component_id: int
    parameters: Mapping[str, JsonScalar]

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class SweepScenario:
    name: str
    directory_key: str
    updates: tuple[ParameterUpdate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "directory_key": self.directory_key,
            "updates": [update.to_dict() for update in self.updates],
        }


@dataclass(frozen=True)
class SweepOutput:
    path: str
    channels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "channels": list(self.channels)}


@dataclass(frozen=True)
class SweepSpec:
    source_root: Path
    entry_file: str
    project_name: str
    scenarios: tuple[SweepScenario, ...]
    outputs: tuple[SweepOutput, ...]
    baseline_scenario: str | None = None
    run_timeout_seconds: int | float = 3600
    max_samples: int = 10_000
    poll_interval_seconds: int | float = 1.0
    output_stability_seconds: int | float = 0.5
    filesystem_timestamp_tolerance_seconds: int | float = 2.0

    @classmethod
    def parse(cls, raw: Any, path_policy: PathPolicy) -> "SweepSpec":
        manifest = _mapping(raw, "Sweep specification")
        _reject_unknown(manifest, _TOP_LEVEL_FIELDS, "Sweep specification")
        _require_fields(
            manifest,
            {"source_root", "entry_file", "project_name", "scenarios", "outputs"},
            "Sweep specification",
        )

        if not isinstance(path_policy, PathPolicy):
            raise ValueError("path_policy must be a PathPolicy instance.")
        if path_policy.workspace_root is None:
            raise ValueError("A configured PSCAD workspace is required for parameter sweeps.")

        source_value = _nonempty_string(manifest["source_root"], "source_root")
        try:
            source_root = path_policy.resolve(source_value, must_exist=True)
        except (FileNotFoundError, OSError, ValueError) as error:
            raise ValueError(f"Invalid source_root: {error}") from error
        if not source_root.is_dir():
            raise ValueError("source_root must be an existing directory.")

        managed_sweeps = (path_policy.workspace_root / ".pscad-mcp" / "sweeps").resolve()
        if source_root == managed_sweeps or managed_sweeps in source_root.parents:
            raise ValueError("source_root cannot be inside .pscad-mcp/sweeps.")

        entry_file, entry_path = _relative_path(
            manifest["entry_file"],
            "entry_file",
            source_root,
            path_policy,
            _ENTRY_SUFFIXES,
            must_exist=True,
        )
        if not entry_path.is_file():
            raise ValueError("entry_file must identify an existing file.")

        project_name = _nonempty_string(manifest["project_name"], "project_name")
        scenarios = cls._parse_scenarios(manifest["scenarios"])
        outputs = cls._parse_outputs(manifest["outputs"], source_root, path_policy)

        baseline = manifest.get("baseline_scenario")
        if baseline is not None:
            baseline = _nonempty_string(baseline, "baseline_scenario")
            if baseline not in {scenario.name for scenario in scenarios}:
                raise ValueError("baseline_scenario must exactly match a scenario name.")

        return cls(
            source_root=source_root,
            entry_file=entry_file,
            project_name=project_name,
            scenarios=scenarios,
            outputs=outputs,
            baseline_scenario=baseline,
            run_timeout_seconds=_number_in_range(
                manifest.get("run_timeout_seconds", 3600),
                "run_timeout_seconds",
                60,
                604_800,
            ),
            max_samples=_integer_in_range(
                manifest.get("max_samples", 10_000),
                "max_samples",
                1,
                1_000_000,
            ),
            poll_interval_seconds=_number_in_range(
                manifest.get("poll_interval_seconds", 1.0),
                "poll_interval_seconds",
                0.1,
                60,
            ),
            output_stability_seconds=_number_in_range(
                manifest.get("output_stability_seconds", 0.5),
                "output_stability_seconds",
                0.1,
                60,
            ),
            filesystem_timestamp_tolerance_seconds=_number_in_range(
                manifest.get("filesystem_timestamp_tolerance_seconds", 2.0),
                "filesystem_timestamp_tolerance_seconds",
                0,
                60,
            ),
        )

    @staticmethod
    def _parse_scenarios(value: Any) -> tuple[SweepScenario, ...]:
        if not isinstance(value, list) or not value:
            raise ValueError("scenarios must be a non-empty ordered list.")

        scenarios: list[SweepScenario] = []
        names: set[str] = set()
        directory_keys: set[str] = set()
        for index, scenario_value in enumerate(value):
            label = f"scenarios[{index}]"
            scenario = _mapping(scenario_value, label)
            _reject_unknown(scenario, {"name", "updates"}, label)
            _require_fields(scenario, {"name", "updates"}, label)
            name = _nonempty_string(scenario["name"], f"{label}.name")
            folded_name = name.casefold()
            if folded_name in names:
                raise ValueError("Scenario names must be unique case-insensitively.")
            names.add(folded_name)

            updates_value = scenario["updates"]
            if not isinstance(updates_value, list) or not updates_value:
                raise ValueError(f"{label}.updates must be a non-empty list.")
            updates: list[ParameterUpdate] = []
            targets: set[tuple[int, str]] = set()
            for update_index, update_value in enumerate(updates_value):
                update_label = f"{label}.updates[{update_index}]"
                update = _mapping(update_value, update_label)
                _reject_unknown(update, {"component_id", "parameters"}, update_label)
                _require_fields(update, {"component_id", "parameters"}, update_label)

                component_id = update["component_id"]
                if isinstance(component_id, bool) or not isinstance(component_id, int) or component_id <= 0:
                    raise ValueError(f"{update_label}.component_id must be a positive integer.")
                parameters_value = update["parameters"]
                if not isinstance(parameters_value, Mapping) or not parameters_value:
                    raise ValueError(f"{update_label}.parameters must be a non-empty object.")

                parameters: dict[str, JsonScalar] = {}
                for parameter_name, parameter_value in parameters_value.items():
                    name_label = f"{update_label}.parameters parameter name"
                    parameter_name = _nonempty_string(parameter_name, name_label)
                    target = (component_id, parameter_name)
                    if target in targets:
                        raise ValueError(
                            f"Scenario {name!r} has a duplicate update for component "
                            f"{component_id} parameter {parameter_name!r}."
                        )
                    targets.add(target)
                    parameters[parameter_name] = _json_scalar(
                        parameter_value,
                        f"{update_label}.parameters[{parameter_name!r}]",
                    )
                updates.append(
                    ParameterUpdate(component_id, MappingProxyType(parameters))
                )

            directory_key = _directory_key(name)
            folded_key = directory_key.casefold()
            if folded_key in directory_keys:
                raise ValueError("Scenario directory keys have a case-insensitive collision.")
            directory_keys.add(folded_key)
            scenarios.append(SweepScenario(name, directory_key, tuple(updates)))
        return tuple(scenarios)

    @staticmethod
    def _parse_outputs(
        value: Any,
        source_root: Path,
        path_policy: PathPolicy,
    ) -> tuple[SweepOutput, ...]:
        if not isinstance(value, list) or not value:
            raise ValueError("outputs must be a non-empty list.")

        outputs: list[SweepOutput] = []
        for index, output_value in enumerate(value):
            label = f"outputs[{index}]"
            output = _mapping(output_value, label)
            _reject_unknown(output, {"path", "channels"}, label)
            _require_fields(output, {"path", "channels"}, label)
            path, _ = _relative_path(
                output["path"],
                f"{label}.path",
                source_root,
                path_policy,
                _OUTPUT_SUFFIXES,
                must_exist=False,
            )

            channels_value = output["channels"]
            if not isinstance(channels_value, list) or not channels_value:
                raise ValueError(f"{label}.channels must be a non-empty list.")
            channels: list[str] = []
            for channel_index, channel_value in enumerate(channels_value):
                channel = _nonempty_string(
                    channel_value,
                    f"{label}.channels[{channel_index}]",
                )
                if any(character in channel for character in "*?[]"):
                    raise ValueError(
                        f"{label}.channels must contain exact selectors without wildcards."
                    )
                channels.append(channel)
            outputs.append(SweepOutput(path, tuple(channels)))
        return tuple(outputs)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-safe normalized manifest dictionary."""
        return {
            "source_root": str(self.source_root),
            "entry_file": self.entry_file,
            "project_name": self.project_name,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "outputs": [output.to_dict() for output in self.outputs],
            "baseline_scenario": self.baseline_scenario,
            "run_timeout_seconds": self.run_timeout_seconds,
            "max_samples": self.max_samples,
            "poll_interval_seconds": self.poll_interval_seconds,
            "output_stability_seconds": self.output_stability_seconds,
            "filesystem_timestamp_tolerance_seconds": (
                self.filesystem_timestamp_tolerance_seconds
            ),
        }
