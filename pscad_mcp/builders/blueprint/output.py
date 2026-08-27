"""Strict PSCAD INF metadata and segmented legacy OUT parsing."""

from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any

from ...core.backend.base import BackendError


_PGB = re.compile(r"^\s*PGB\((\d+)\)\s+Output\s+(.*)$", re.IGNORECASE)
_ATTRIBUTE = re.compile(r'([A-Za-z][A-Za-z0-9_]*)=(?:"([^"]*)"|(\S+))')


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "blueprint", "read_blueprint_output", details)


def _finite_float(value: str, *, path: Path, line: int, column: int) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise _error("BLUEPRINT_OUTPUT_INVALID", "Output data contains a non-numeric value.", path=str(path), line=line, column=column) from error
    if not math.isfinite(parsed):
        raise _error("BLUEPRINT_OUTPUT_INVALID", "Output data contains a non-finite value.", path=str(path), line=line, column=column)
    return parsed


def parse_inf(path: str | Path) -> tuple[dict[str, Any], ...]:
    metadata_path = Path(path).expanduser().resolve()
    if not metadata_path.is_file() or metadata_path.is_symlink() or metadata_path.suffix.casefold() != ".inf":
        raise _error("BLUEPRINT_OUTPUT_INVALID", "Output metadata must be a regular INF file.", path=str(metadata_path))
    channels: list[dict[str, Any]] = []
    try:
        lines = metadata_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise _error("BLUEPRINT_OUTPUT_INVALID", "Output metadata could not be read.", path=str(metadata_path)) from error
    for line_number, line in enumerate(lines, start=1):
        matched = _PGB.match(line)
        if matched is None:
            continue
        call_id = int(matched.group(1))
        attributes = {
            name.casefold(): quoted if quoted != "" else bare
            for name, quoted, bare in _ATTRIBUTE.findall(matched.group(2))
        }
        if not {"desc", "group", "units", "min", "max"} <= set(attributes):
            raise _error("BLUEPRINT_OUTPUT_INVALID", "An INF channel is missing required metadata.", line=line_number)
        group = attributes["group"].strip("/")
        description = attributes["desc"].strip("/")
        if not group or not description or not attributes["units"]:
            raise _error("BLUEPRINT_OUTPUT_INVALID", "An INF channel has an empty path or unit.", line=line_number)
        channels.append(
            {
                "call_id": call_id,
                "path": f"{group}/{description}",
                "units": attributes["units"],
                "minimum": _finite_float(attributes["min"], path=metadata_path, line=line_number, column=0),
                "maximum": _finite_float(attributes["max"], path=metadata_path, line=line_number, column=0),
            }
        )
    if not channels:
        raise _error("BLUEPRINT_OUTPUT_INVALID", "INF metadata declares no output channels.", path=str(metadata_path))
    call_ids = [channel["call_id"] for channel in channels]
    paths = [channel["path"] for channel in channels]
    if len(set(call_ids)) != len(call_ids) or len(set(paths)) != len(paths) or call_ids != list(range(1, len(call_ids) + 1)):
        raise _error("BLUEPRINT_OUTPUT_INVALID", "INF channel IDs and paths must be unique and contiguous.", path=str(metadata_path))
    return tuple(channels)


def _read_segment(path: Path, expected_columns: int) -> tuple[list[float], list[list[float]]]:
    if not path.is_file() or path.is_symlink():
        raise _error("BLUEPRINT_OUTPUT_INVALID", "A required OUT segment is missing or not a regular file.", path=str(path))
    domain: list[float] = []
    columns: list[list[float]] = [[] for _ in range(expected_columns)]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise _error("BLUEPRINT_OUTPUT_INVALID", "An OUT segment could not be read.", path=str(path)) from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != expected_columns + 1:
            raise _error(
                "BLUEPRINT_OUTPUT_INVALID",
                "An OUT row has the wrong number of columns.",
                path=str(path),
                line=line_number,
                expected=expected_columns + 1,
                observed=len(fields),
            )
        values = [_finite_float(field, path=path, line=line_number, column=index) for index, field in enumerate(fields)]
        domain.append(values[0])
        for index, value in enumerate(values[1:]):
            columns[index].append(value)
    if not domain or any(right <= left for left, right in zip(domain, domain[1:])):
        raise _error("BLUEPRINT_OUTPUT_INVALID", "OUT time values must be non-empty and strictly increasing.", path=str(path))
    return domain, columns


def read_output_dataset(path: str | Path) -> dict[str, Any]:
    metadata_path = Path(path).expanduser().resolve()
    metadata = parse_inf(metadata_path)
    base = metadata_path.with_suffix("")
    expected_segments = (len(metadata) + 9) // 10
    observed_files = sorted(metadata_path.parent.glob(f"{base.name}_*.out"), key=lambda item: item.name.casefold())
    expected_files = [Path(f"{base}_{index:02d}.out") for index in range(1, expected_segments + 1)]
    if [path.resolve() for path in observed_files] != [path.resolve() for path in expected_files]:
        raise _error(
            "BLUEPRINT_OUTPUT_INVALID",
            "OUT segment set is incomplete or contains unexpected files.",
            expected=[path.name for path in expected_files],
            observed=[path.name for path in observed_files],
        )
    shared_domain: list[float] | None = None
    channel_columns: list[list[float]] = []
    for index, segment in enumerate(expected_files):
        remaining = len(metadata) - index * 10
        domain, columns = _read_segment(segment, min(10, remaining))
        if shared_domain is None:
            shared_domain = domain
        elif domain != shared_domain:
            raise _error("BLUEPRINT_OUTPUT_INVALID", "OUT segments do not share the same time domain.", path=str(segment))
        channel_columns.extend(columns)
    channels: dict[str, dict[str, Any]] = {}
    for channel, values in zip(metadata, channel_columns):
        channels[channel["path"]] = {
            **channel,
            "domain": list(shared_domain or []),
            "values": values,
        }
    return {
        "metadata_file": str(metadata_path),
        "segments": [path.name for path in expected_files],
        "channels": channels,
    }


def discover_output_dataset(staging_root: str | Path) -> dict[str, Any]:
    root = Path(staging_root).expanduser().resolve()
    if not root.is_dir():
        raise _error("BLUEPRINT_OUTPUT_INVALID", "Output staging path must be a directory.", path=str(root))
    candidates: list[Path] = []
    for path in sorted(root.rglob("*.inf"), key=lambda item: item.as_posix()):
        if path.is_symlink() or root not in path.resolve().parents:
            raise _error("BLUEPRINT_OUTPUT_INVALID", "Output metadata escapes the staging package.", path=str(path))
        if list(path.parent.glob(f"{path.stem}_*.out")):
            candidates.append(path)
    if not candidates:
        raise _error("BLUEPRINT_OUTPUT_INVALID", "No complete PSCAD output dataset was found.", path=str(root))
    if len(candidates) != 1:
        raise _error("BLUEPRINT_OUTPUT_AMBIGUOUS", "More than one PSCAD output dataset was found.", candidates=[str(path) for path in candidates])
    return read_output_dataset(candidates[0])
