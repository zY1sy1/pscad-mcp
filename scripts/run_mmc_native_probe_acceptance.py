"""Isolated licensed timing/probe diagnostics; never overall MMC acceptance."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.preflight_cli import _service
from pscad_mcp.acceptance.process_scope import (
    concurrent_acceptance_enabled,
    managed_acceptance_pid,
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy_support import (
    rewrite_template_identity,
)
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.core.pscad_adapter import (
    _legacy_first_numeric_row,
    _legacy_next_nonblank,
    _legacy_numeric_row,
)
from pscad_mcp.core.service import discover_output_candidates
from pscad_mcp.hvdc.builders.mmc.line_constants import (
    generate_public_line_constants,
    rebind_template_line_constants,
)
from pscad_mcp.hvdc.builders.mmc.native_probes import (
    materialize_native_fault_probes,
)
from pscad_mcp.hvdc.builders.mmc.template_native import (
    materialize_template_native_scenario,
)

PROBE_UNITS = {
    "MMC_DC_FAULT_ACTIVE": "1",
    "MMC_DC_FAULT_CURRENT": "kA",
    "MMC_VDC_T1": "kV",
    "MMC_VDC_T2": "kV",
    "MMC_V_INSERTED_TOP": "kV",
    "MMC_V_INSERTED_BTM": "kV",
    "MMC_BLOCKED_TOP": "1",
    "MMC_BLOCKED_BTM": "1",
    "MMC_VCAP_TOP": "kV",
    "MMC_VCAP_BTM": "kV",
}
REMAINING_SCOPE = [
    "Overall MMC electrical acceptance and approved golden baseline are not established.",
    "Steady operating point, capacitor balancing/ripple limits, recovery, power transfer, and the full scenario matrix remain unverified.",
    "Negative arm terminal voltage and actual firing-block inputs are diagnostic observations, not proof of all full-bridge fault-blocking criteria.",
]
CURRENT_LIMIT_KA = 20.0
MAX_SAMPLES = 100_000


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": str(value)}
    return value


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(_json_safe(report), stream, allow_nan=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _error(error: BaseException) -> dict[str, Any]:
    payload = (
        error.to_dict()
        if isinstance(error, BackendError)
        else {
            "code": type(error).__name__,
            "message": str(error),
        }
    )
    return {**payload, "traceback": "".join(traceback.format_exception(error))}


def _category(stage: str, error: BaseException) -> str:
    code = getattr(error, "code", "")
    if code in {
        "LEGACY_EXISTING_PROCESS",
        "PSCAD_ALREADY_RUNNING",
        "LEGACY_EXISTING_PROCESS_CONFLICT",
    }:
        return "environment_contention"
    if isinstance(error, FileNotFoundError) or code in {
        "NOT_LICENSED",
        "UNSUPPORTED_OPERATION",
    }:
        return "external_prerequisite"
    if stage in {"attach", "runtime", "run", "poll", "cleanup"}:
        return "process_or_runtime"
    return "implementation_defect"


def _family(description: str) -> str | None:
    name = (
        description.rsplit(":", 1)[0]
        if re.search(r":\d+$", description)
        else description
    )
    if name in PROBE_UNITS:
        return name
    instance = re.fullmatch(r"(.+)_([1-9]\d*)", name)
    if instance is not None and instance.group(1) in PROBE_UNITS:
        return instance.group(1)
    return None


def read_infx(path: Path) -> dict[int, dict[str, Any]]:
    """Expand zero-based INFX Analog indexes to one-based INF/OUT call IDs."""
    root = ET.parse(path).getroot()
    domain = root.find("./Domain")
    if domain is None or domain.get("name") != "Time" or domain.get("unit") != "s":
        raise ValueError("INFX must declare a Time domain in seconds")
    result = {}
    for analog in root.findall("./List/Analog"):
        start, dimension = int(analog.attrib["index"]), int(analog.attrib["dim"])
        if start < 0 or not 1 <= dimension <= 4096 or start + dimension > 20_000:
            raise ValueError(
                "INFX channel range is invalid or exceeds the diagnostic bound"
            )
        name, owner = analog.attrib["name"], analog.attrib["id"]
        for component in range(dimension):
            call_id = start + component + 1
            if call_id in result:
                raise ValueError("INFX contains overlapping channel indexes")
            result[call_id] = {
                **analog.attrib,
                "name": name,
                "id": owner,
                "owner": owner.split(":", 1)[0],
                "instance": name.rsplit(":", 1)[0],
                "dimension": dimension,
                "component": component,
                "source": str(path),
            }
    if not result:
        raise ValueError("INFX has no Analog channel mapping")
    return result


def discover_run_outputs(
    project: Path, started_after: float, *, metadata_started_after: float | None = None
) -> dict[str, Any]:
    root = project.parent.resolve()

    def contained(path: Path) -> Path:
        if path.is_symlink():
            raise ValueError("An output cannot be a symbolic link")
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        return resolved

    candidates = [
        Path(value)
        for value in discover_output_candidates(
            project,
            started_after=started_after,
            max_files=2048,
            resolve_candidate=contained,
        )
    ]
    if len(candidates) >= 2048:
        raise ValueError("Output discovery reached its 2048-file bound")
    pattern = re.compile(re.escape(project.stem) + r"_(\d{2,})\.out", re.IGNORECASE)
    numbered = [(path, pattern.fullmatch(path.name)) for path in candidates]
    numbered = [(path, int(match.group(1))) for path, match in numbered if match]
    primaries = [path for path, index in numbered if index == 1]
    if len(primaries) != 1:
        raise ValueError(
            "The actual run must have exactly one fresh numbered OUT family"
        )
    primary = primaries[0]
    parts = sorted(
        (item for item in numbered if item[0].parent == primary.parent),
        key=lambda item: item[1],
    )
    if [index for _, index in parts] != list(range(1, len(parts) + 1)):
        raise ValueError("The actual run has missing or duplicate numbered OUT parts")
    metadata = {}
    metadata_start = (
        started_after if metadata_started_after is None else metadata_started_after
    )
    for suffix in ("inf", "infx"):
        path = primary.with_name(project.stem + "." + suffix)
        if not path.is_file() or path.stat().st_mtime < metadata_start:
            raise ValueError(
                f"The actual run has no fresh {suffix.upper()} metadata: {path}"
            )
        metadata[suffix] = contained(path)
    return {"primary": primary, "parts": [path for path, _ in parts], **metadata}


async def read_run_probes(
    service: Any, files: Mapping[str, Any], receipt: Mapping[str, Any], progress=None
) -> list[dict[str, Any]]:
    infx = read_infx(files["infx"])
    owners = {item["name"]: str(item["pgb_owner"]) for item in receipt["probes"]}
    metadata = {}
    pattern = re.compile(
        r'^PGB\((\d+)\).*?Desc="([^"]+)"\s+Group="([^"]*)".*?\bUnits="([^"]*)"'
    )
    for line in files["inf"].read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            if line.lstrip().startswith("PGB("):
                raise ValueError("INF contains an unparseable output channel")
            continue
        call_id = int(match.group(1))
        if call_id in metadata:
            raise ValueError("INF contains a duplicate call ID")
        metadata[call_id] = {
            "description": match.group(2),
            "group": match.group(3),
            "units": match.group(4),
        }
    if sorted(metadata) != list(range(1, len(metadata) + 1)) or set(metadata) != set(
        infx
    ):
        raise ValueError("INF and INFX channel coverage differs or is nonsequential")
    if (len(metadata) + 9) // 10 != len(files["parts"]):
        raise ValueError(
            "The OUT part count does not match full INF/INFX channel coverage"
        )
    families_by_owner = {owner: family for family, owner in owners.items()}
    if set(owners) != set(PROBE_UNITS) or len(families_by_owner) != len(PROBE_UNITS):
        raise ValueError(
            "The probe receipt does not contain the ten required physical prototypes"
        )
    selected = {
        key: item
        for key, item in metadata.items()
        if infx[key]["owner"] in families_by_owner
    }
    domain, records = [], {}
    for call_id, meta in selected.items():
        identity = infx[call_id]
        family = families_by_owner[identity["owner"]]
        native_name = identity["name"].rsplit(":", 1)[-1]
        expected_description = native_name + (
            f":{identity['component'] + 1}" if identity["dimension"] > 1 else ""
        )
        if (
            re.fullmatch(re.escape(family) + r"(?:_[1-9]\d*)?", native_name) is None
            or meta["description"] != expected_description
        ):
            raise ValueError(
                f"INF/INFX owner, instance, or vector component does not match the physical probe receipt at call ID {call_id}"
            )
        if identity["unit"] != meta["units"]:
            raise ValueError(f"INF/INFX unit mismatch at call ID {call_id}")
        records[call_id] = {
            **meta,
            "call_id": call_id,
            "family": family,
            "path": f"{meta['group']}/{meta['description']}"
            if meta["group"]
            else meta["description"],
            "infx": identity,
            "domain": domain,
            "values": [],
            "source_part": str(files["parts"][(call_id - 1) // 10]),
            "source_column": (call_id - 1) % 10 + 1,
            "source_inf": str(files["inf"]),
        }

    def read_part(path: Path, part_index: int) -> None:
        first_call = part_index * 10 + 1
        width = min(10, len(metadata) - part_index * 10)
        retained = {
            key: records[key]["values"]
            for key in range(first_call, first_call + width)
            if key in records
        }
        row_index = 0
        with path.open(encoding="utf-8") as stream:
            line = _legacy_first_numeric_row(stream)
            while line:
                parsed = _legacy_numeric_row(line)
                if parsed is None or len(parsed) != width + 1:
                    raise ValueError(
                        f"OUT column count differs from INF at {path}, row {row_index + 1}"
                    )
                if row_index >= MAX_SAMPLES:
                    raise ValueError(
                        "Fresh output exceeds the 100000 full-sample diagnostic bound"
                    )
                if part_index == 0:
                    if domain and parsed[0] <= domain[-1]:
                        raise ValueError(
                            "The OUT time domain is not strictly increasing"
                        )
                    domain.append(parsed[0])
                elif row_index >= len(domain) or parsed[0] != domain[row_index]:
                    raise ValueError(
                        f"OUT time domains differ at {path}, row {row_index + 1}"
                    )
                for call_id, values in retained.items():
                    values.append(parsed[call_id - first_call + 1])
                row_index += 1
                line = _legacy_next_nonblank(stream)
        if not row_index or row_index != len(domain):
            raise ValueError(
                f"OUT part lengths differ or contain no numeric data: {path}"
            )

    # The shared legacy numeric parser validates every column, including
    # unselected channels; each finalized part is opened only once.
    for part_index, path in enumerate(files["parts"]):
        await asyncio.to_thread(read_part, path, part_index)
        if progress is not None:
            progress(part_index + 1, len(files["parts"]))
    return [records[key] for key in sorted(records)]


def analyze_probes(
    channels: Sequence[Mapping[str, Any]],
    *,
    fault_time: float,
    fault_duration: float,
    duration: float,
    sample_step: float,
) -> dict[str, Any]:
    """Strict schedule/probe checks plus bounded physical diagnostics."""
    issues, summaries = [], []
    groups = defaultdict(list)
    valid = {}
    reference = None

    def issue(code: str, **details: Any) -> None:
        issues.append({"code": code, **details})

    for trace in channels:
        family = _family(str(trace.get("description", "")))
        if family is None:
            continue
        groups[family].append(trace)
        call_id, identity = trace.get("call_id"), trace.get("infx", {})
        raw_time, raw_values = trace.get("domain", []), trace.get("values", [])
        try:
            domain, values = (
                [float(value) for value in raw_time],
                [float(value) for value in raw_values],
            )
        except (TypeError, ValueError):
            domain, values = [], []
        finite = bool(values) and all(math.isfinite(value) for value in values + domain)
        if not finite:
            issue("nonfinite_probe", call_id=call_id, family=family)
        good_values = [value for value in values if math.isfinite(value)]
        summary = {
            key: trace.get(key)
            for key in (
                "call_id",
                "description",
                "path",
                "units",
                "source_part",
                "source_column",
                "source_inf",
                "infx",
            )
        }
        summary.update(
            {
                "family": family,
                "sample_count": len(values),
                "finite": finite,
                "min": min(good_values) if good_values else None,
                "max": max(good_values) if good_values else None,
                "end": values[-1] if values and math.isfinite(values[-1]) else None,
                "start_s": domain[0] if domain and math.isfinite(domain[0]) else None,
                "end_s": domain[-1] if domain and math.isfinite(domain[-1]) else None,
            }
        )
        summaries.append(summary)
        if (
            trace.get("units") != PROBE_UNITS[family]
            or identity.get("unit") != PROBE_UNITS[family]
        ):
            issue(
                "probe_units",
                call_id=call_id,
                family=family,
                expected=PROBE_UNITS[family],
                observed=trace.get("units"),
                infx=identity.get("unit"),
            )
        if not identity.get("owner") or not identity.get("instance"):
            issue("probe_identity", call_id=call_id, family=family)
        aligned = finite and len(domain) == len(values) and len(domain) >= 3
        aligned = aligned and all(
            abs(right - left - sample_step) <= 1e-9
            for left, right in itertools.pairwise(domain)
        )
        aligned = (
            aligned
            and abs(domain[0]) <= 2 * sample_step
            and abs(domain[-1] - duration) <= 2 * sample_step
        )
        if reference is None and aligned:
            reference = domain
        aligned = aligned and (
            reference is None
            or len(domain) == len(reference)
            and all(abs(a - b) < 1e-10 for a, b in zip(domain, reference))
        )
        if not aligned:
            issue("trace_time_alignment", call_id=call_id, family=family)
        if finite and aligned:
            if call_id in valid:
                issue("duplicate_call_id", call_id=call_id)
            valid[call_id] = (domain, values)
        if PROBE_UNITS[family] == "1" and any(
            min(abs(value), abs(value - 1)) > 1e-6 for value in good_values
        ):
            issue("nonbinary_control", call_id=call_id, family=family)

    families = {}
    pole_instances = {
        trace.get("infx", {}).get("instance") for trace in groups["MMC_V_INSERTED_TOP"]
    }
    for family, units in PROBE_UNITS.items():
        members = groups[family]
        instances = defaultdict(list)
        for trace in members:
            instances[trace.get("infx", {}).get("instance")].append(trace)
        expected = 1 if family.startswith(("MMC_DC_", "MMC_VDC_")) else 6
        if expected == 6 and set(instances) != pole_instances:
            issue(
                "probe_instance_alignment",
                family=family,
                expected=sorted(pole_instances, key=str),
                observed=sorted(instances, key=str),
            )
        if not members:
            issue("missing_probe_family", family=family)
        elif len(instances) != expected:
            issue(
                "probe_instance_count",
                family=family,
                expected=expected,
                observed=len(instances),
            )
        for instance, traces in instances.items():
            if "VCAP" in family:
                dimensions = {
                    trace.get("infx", {}).get("dimension") for trace in traces
                }
                components = [
                    trace.get("infx", {}).get("component") for trace in traces
                ]
                dimension = next(iter(dimensions)) if len(dimensions) == 1 else None
                if (
                    type(dimension) is not int
                    or dimension < 2
                    or sorted(components, key=str) != sorted(range(dimension), key=str)
                ):
                    issue(
                        "capacitor_dimension",
                        family=family,
                        instance=instance,
                        dimensions=list(dimensions),
                        observed_components=components,
                    )
            elif len(traces) != 1:
                issue(
                    "probe_instance_count",
                    family=family,
                    instance=instance,
                    expected=1,
                    observed=len(traces),
                )
        family_summaries = [item for item in summaries if item["family"] == family]
        families[family] = {
            "count": len(members),
            "instance_count": len(instances),
            "units": units,
            "finite": bool(members)
            and all(item["finite"] for item in family_summaries),
            "min": min(
                (item["min"] for item in family_summaries if item["min"] is not None),
                default=None,
            ),
            "max": max(
                (item["max"] for item in family_summaries if item["max"] is not None),
                default=None,
            ),
        }

    schedule = {
        "requested_on_s": fault_time,
        "requested_off_s": fault_time + fault_duration,
        "requested_duration_s": fault_duration,
        "tolerance_s": 2 * sample_step,
        "status": "FAIL",
    }
    active = groups["MMC_DC_FAULT_ACTIVE"]
    if len(active) == 1 and active[0].get("call_id") in valid:
        domain, values = valid[active[0]["call_id"]]
        states = [value > 0.5 for value in values]
        rising = [
            index
            for index in range(1, len(states))
            if states[index] and not states[index - 1]
        ]
        falling = [
            index
            for index in range(1, len(states))
            if not states[index] and states[index - 1]
        ]
        schedule.update(
            {
                "rising_edges_s": [domain[index] for index in rising],
                "falling_edges_s": [domain[index] for index in falling],
            }
        )
        if len(rising) == len(falling) == 1 and not states[0] and not states[-1]:
            onset, release = domain[rising[0]], domain[falling[0]]
            schedule.update(
                {
                    "measured_on_s": onset,
                    "measured_off_s": release,
                    "measured_duration_s": release - onset,
                }
            )
            if all(
                abs(observed - requested) <= 2 * sample_step + 1e-10
                for observed, requested in (
                    (onset, fault_time),
                    (release, fault_time + fault_duration),
                    (release - onset, fault_duration),
                )
            ):
                schedule["status"] = "PASS"
    if schedule["status"] != "PASS":
        issue("fault_schedule", measurement=schedule)

    current_bound = {"limit_ka": CURRENT_LIMIT_KA, "status": "FAIL"}
    currents = groups["MMC_DC_FAULT_CURRENT"]
    if (
        len(currents) == 1
        and currents[0].get("call_id") in valid
        and currents[0].get("units") == "kA"
    ):
        _, values = valid[currents[0]["call_id"]]
        maximum = max(abs(value) for value in values)
        current_bound.update(
            {
                "peak_absolute_ka": maximum,
                "status": "PASS" if maximum <= CURRENT_LIMIT_KA else "FAIL",
            }
        )
        if maximum > CURRENT_LIMIT_KA:
            issue(
                "fault_current_bound",
                category="model_physical",
                measured_ka=maximum,
                limit_ka=CURRENT_LIMIT_KA,
            )

    arms = []
    for side in ("TOP", "BTM"):
        gates = {
            trace.get("infx", {}).get("instance"): trace
            for trace in groups[f"MMC_BLOCKED_{side}"]
        }
        for voltage in groups[f"MMC_V_INSERTED_{side}"]:
            instance = voltage.get("infx", {}).get("instance")
            gate = gates.get(instance, {})
            arm = {
                "side": side,
                "instance": instance,
                "voltage_call_id": voltage.get("call_id"),
                "gate_call_id": gate.get("call_id"),
                "negative_voltage_during_fault": None,
                "blocked_during_fault": None,
                "released_after_fault": None,
            }
            if voltage.get("call_id") in valid and gate.get("call_id") in valid:
                domain, volts = valid[voltage["call_id"]]
                _, blocked = valid[gate["call_id"]]
                during = [
                    index
                    for index, value in enumerate(domain)
                    if fault_time <= value < fault_time + fault_duration
                ]
                after = [
                    index
                    for index, value in enumerate(domain)
                    if value > fault_time + fault_duration + 2 * sample_step
                ]
                if during and after:
                    arm.update(
                        {
                            "fault_min_kv": min(volts[index] for index in during),
                            "negative_voltage_during_fault": any(
                                volts[index] < -1e-9 for index in during
                            ),
                            "blocked_during_fault": any(
                                blocked[index] > 0.5 for index in during
                            ),
                            "released_after_fault": any(
                                blocked[index] <= 0.5 for index in after
                            )
                            and blocked[-1] <= 0.5,
                            "first_fault_block_s": next(
                                (
                                    domain[index]
                                    for index in during
                                    if blocked[index] > 0.5
                                ),
                                None,
                            ),
                            "first_postfault_release_s": next(
                                (
                                    domain[index]
                                    for index in after
                                    if blocked[index] <= 0.5
                                ),
                                None,
                            ),
                        }
                    )
                    for key in (
                        "negative_voltage_during_fault",
                        "blocked_during_fault",
                        "released_after_fault",
                    ):
                        if not arm[key]:
                            issue(
                                key,
                                category="model_physical",
                                side=side,
                                instance=instance,
                            )
            arms.append(arm)
    physical_codes = {
        "fault_current_bound",
        "negative_voltage_during_fault",
        "blocked_during_fault",
        "released_after_fault",
    }
    return {
        "status": "FAIL" if issues else "PASS",
        "model_accepted": False,
        "measurement_complete": not any(
            item["code"] not in physical_codes for item in issues
        ),
        "schedule": schedule,
        "current_bound": current_bound,
        "families": families,
        "arms": arms,
        "channels": summaries,
        "issues": issues,
        "remaining_scope": REMAINING_SCOPE,
    }


def require_runtime(runtime: Mapping[str, Any]) -> None:
    require_acceptance_ownership(runtime)
    if (
        managed_acceptance_pid(runtime) is None
        or runtime.get("owns_process") is not True
    ):
        raise RuntimeError(
            "A vendor-reported managed PSCAD PID and ownership are required"
        )
    expected = {
        "connected": True,
        "licensed": True,
        "backend": "legacy",
        "version": "4.6.2",
        "x64": True,
    }
    if any(runtime.get(key) != value for key, value in expected.items()):
        if runtime.get("licensed") is False:
            raise BackendError(
                "NOT_LICENSED",
                "The owned PSCAD runtime is not licensed",
                "legacy",
                "native_probe_acceptance",
                dict(runtime),
            )
        raise RuntimeError(
            "The diagnostic requires connected, licensed legacy PSCAD 4.6.2 x64"
        )


async def cleanup_owned_session(
    service: Any,
    runtime: Mapping[str, Any],
    *,
    project_name: str | None,
    run_pending: bool,
    process_reader=list_pscad_processes,
    timeout: float = 30.0,
) -> dict[str, Any]:
    result = {
        "managed_pid": managed_acceptance_pid(runtime),
        "owned_process_cleaned": False,
        "remaining_owned_processes": [],
        "errors": [],
    }
    if (
        managed_acceptance_pid(runtime) is None
        or runtime.get("owns_process") is not True
    ):
        result["error"] = {
            "code": "OWNERSHIP_UNVERIFIED",
            "message": "No stop or quit was issued without a verified vendor PID.",
        }
        return result
    require_acceptance_ownership(runtime)
    if run_pending and project_name:
        try:
            await asyncio.wait_for(service.stop_simulation(project_name), timeout)
        except BaseException as error:  # noqa: BLE001 - preserve cleanup evidence even on cancellation
            result["errors"].append({"operation": "stop", **_error(error)})
    try:
        await asyncio.wait_for(service.quit_pscad(confirm=True), timeout)
    except BaseException as error:  # noqa: BLE001 - quitting must still be followed by PID verification
        result["errors"].append({"operation": "quit", **_error(error)})
        try:
            await asyncio.wait_for(service.disconnect(), timeout)
        except BaseException as disconnect_error:  # noqa: BLE001 - retain the complete cleanup attempt
            result["errors"].append(
                {"operation": "disconnect", **_error(disconnect_error)}
            )
    deadline = time.monotonic() + timeout
    while True:
        remaining = remaining_acceptance_processes(runtime, process_reader)
        result["remaining_owned_processes"] = remaining
        if not remaining or time.monotonic() >= deadline:
            break
        await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
    result["owned_process_cleaned"] = not remaining
    return result


def _code_snapshot() -> dict[str, Any]:
    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()

    paths = list((REPOSITORY / "pscad_mcp").rglob("*.py"))
    paths += [
        Path(__file__).resolve(),
        REPOSITORY / "tests/test_mmc_native_probe_acceptance.py",
        REPOSITORY / "pyproject.toml",
    ]
    return {
        "repository": str(REPOSITORY),
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "working_tree_status": git("status", "--porcelain"),
        "source_code_hashes": {
            str(path): _sha256(path) for path in sorted(set(paths)) if path.is_file()
        },
    }


def _inputs(args: argparse.Namespace) -> list[Path]:
    paths = [
        args.template,
        args.library,
        args.master,
        args.compiler_configuration,
        args.compiler_executable,
        args.tline,
    ]
    for parent in {args.template.parent, args.library.parent}:
        for name in ("Obj_Files_2016_03_25", "lib"):
            folder = parent / name
            if folder.is_dir():
                paths += [path for path in folder.rglob("*") if path.is_file()]
        paths += list(parent.glob("*.lib"))
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(
                f"Required immutable input is not a regular file: {path}"
            )
    return sorted(set(paths))


def _copy_support(args: argparse.Namespace, run_dir: Path) -> list[str]:
    copied = []
    for parent in sorted({args.template.parent, args.library.parent}):
        sources = [
            parent / name
            for name in ("Obj_Files_2016_03_25", "lib")
            if (parent / name).is_dir()
        ]
        sources += list(parent.glob("*.lib"))
        for source in sources:
            for path in sorted(source.rglob("*") if source.is_dir() else [source]):
                if not path.is_file():
                    continue
                target = run_dir / path.relative_to(parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if _sha256(target) != _sha256(path):
                        raise ValueError(
                            f"The supplied source pair has conflicting support dependencies: {path}"
                        )
                else:
                    shutil.copy2(path, target)
                copied.append(str(target))
    return sorted(set(copied))


async def run_attempt(
    args: argparse.Namespace, run_dir: Path, *, service_factory=_service
) -> dict[str, Any]:
    if os.environ.get("PSCAD_MCP_ACCEPTANCE") != "1":
        raise PermissionError("PSCAD_MCP_ACCEPTANCE=1 is required before an attempt")
    report_path = run_dir / "report.json"
    report = {
        "schema_version": 1,
        "scope": "native_mmc_fault_schedule_and_physical_probes",
        "status": "FAIL",
        "model_accepted": False,
        "started_at": _stamp(),
        "run_directory": str(run_dir),
        "remaining_scope": REMAINING_SCOPE,
        "concurrent": concurrent_acceptance_enabled(),
        "stages": [],
        "requested": {
            "fault_time_s": args.fault_time,
            "fault_duration_s": args.fault_duration,
            "simulation_duration_s": args.duration,
            "time_step_s": args.time_step * 1e-6,
            "sample_step_s": args.sample_step * 1e-6,
            "current_limit_ka": CURRENT_LIMIT_KA,
        },
        "paths": {
            key: str(getattr(args, key))
            for key in (
                "template",
                "library",
                "master",
                "compiler_configuration",
                "compiler_executable",
                "tline",
            )
        },
    }
    stage = "inputs"
    service, runtime, project_name = None, {}, None
    input_hashes, code_before = {}, {}
    run_pending = attach_attempted = False

    def begin(name: str) -> None:
        nonlocal stage
        if report["stages"] and report["stages"][-1].get("status") == "RUNNING":
            report["stages"][-1].update(status="PASS", finished_at=_stamp())
        stage = name
        report["stages"].append(
            {"name": name, "started_at": _stamp(), "status": "RUNNING"}
        )
        _write_report(report_path, report)
        print(f"MMC_NATIVE_PROBE_STAGE={name}", flush=True)

    async def bounded(awaitable, timeout=None):
        return await asyncio.wait_for(
            awaitable, args.operation_timeout if timeout is None else timeout
        )

    try:
        begin("inputs")
        input_hashes = {str(path): _sha256(path) for path in _inputs(args)}
        report["source_hashes_before"] = input_hashes
        code_before = _code_snapshot()
        report["code_before"] = code_before
        report["processes_before"] = list_pscad_processes()
        begin("line_constants")
        artifacts = generate_public_line_constants(
            args.template,
            run_dir / "line-constants",
            executable=args.tline,
            timeout_s=args.operation_timeout,
        )
        if not artifacts:
            raise ValueError(
                "No public line constants were generated for the source template"
            )
        report["line_constants"] = [item.to_dict() for item in artifacts]
        begin("stage_source_pair")
        staged_library = run_dir / args.library.name
        shutil.copy2(args.library, staged_library)
        report["copied_support"] = _copy_support(args, run_dir)
        rebound = rebind_template_line_constants(
            args.template, artifacts, run_dir / "line_rebound.pscx"
        )
        token = uuid.uuid4().hex[:10]
        base = run_dir / f"MMC_BASE_{token}.pscx"
        rewrite_template_identity(rebound, base, base.stem)
        report["staged_base"] = str(base)
        report["staged_library"] = str(staged_library)
        begin("attach")
        service = service_factory(run_dir)
        report["runtime_before"] = await bounded(service.status())
        attach_attempted = True
        report["attach_result"] = await bounded(service.attach_local())
        begin("runtime")
        runtime = await bounded(service.status())
        report["runtime"] = runtime
        require_runtime(runtime)
        begin("normalize_owned_sources")
        await bounded(service.load_projects([str(staged_library), str(base)]))
        library_name = ET.parse(staged_library).getroot().attrib["name"]
        await bounded(service.save_project(library_name, confirm=True))
        await bounded(service.save_project(base.stem, confirm=True))
        report["normalized_source_hashes"] = {
            str(path): _sha256(path) for path in (base, staged_library)
        }
        begin("materialize_probes")
        probe_project = run_dir / "physical_probes.pscx"
        receipt = materialize_native_fault_probes(
            base, probe_project, master_path=args.master, library_path=staged_library
        )
        report["probes_receipt"] = receipt
        begin("materialize_scenario")
        scenario = run_dir / "native_scenario.pscx"
        report["scenario_receipt"] = materialize_template_native_scenario(
            probe_project,
            scenario,
            dc_fault_time_s=args.fault_time,
            fault_duration_s=args.fault_duration,
        )
        final = run_dir / f"MMC_PROBE_{token}.pscx"
        rewrite_template_identity(scenario, final, final.stem)
        project_name = final.stem
        report["project"] = str(final)
        begin("settings")
        await bounded(service.load_projects([str(final)]))
        before = await bounded(service.get_project_settings(project_name))
        requested = {
            "time_duration": format(args.duration, ".15g"),
            "time_step": format(args.time_step, ".15g"),
            "sample_step": format(args.sample_step, ".15g"),
            "PlotType": "1",
            "output_filename": final.stem + ".out",
        }
        if any(key not in before for key in requested):
            raise ValueError(
                f"Required native simulation settings are missing: {set(requested) - set(before)}"
            )
        await bounded(service.set_project_settings(project_name, requested))
        readback = await bounded(service.get_project_settings(project_name))
        report["settings"] = {
            "before": before,
            "requested": requested,
            "readback": readback,
        }
        for key, expected in requested.items():
            if key == "output_filename":
                matches = readback.get(key) == expected
            else:
                matches = float(readback[key]) == float(expected)
            if not matches:
                raise ValueError(
                    f"Native simulation setting {key} did not read back exactly"
                )
        await bounded(service.save_project(project_name, confirm=True))
        report["finalized_project_sha256_before_run"] = _sha256(final)
        begin("compile")
        report["compile_started_after"] = time.time()
        report["compile_result"] = await bounded(
            service.build_project(project_name), args.build_timeout
        )
        report["compile_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        begin("run")
        report["run_started_after"] = time.time()
        run_pending = True
        report["run_result"] = await bounded(service.run_project(project_name))
        begin("poll")
        deadline = time.monotonic() + args.run_timeout
        report["run_status_history"] = []
        while True:
            state = await bounded(service.get_run_status(project_name))
            report["run_status_history"].append({"observed_at": _stamp(), **state})
            _write_report(report_path, report)
            status = str(state.get("status", "")).casefold()
            if status in {"completed", "complete", "idle"}:
                run_pending = False
                break
            if status in {"failed", "stopped", "interrupted"}:
                raise RuntimeError(
                    f"The native simulation terminated with status {status}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Native simulation exceeded {args.run_timeout} seconds"
                )
            await asyncio.sleep(args.poll_interval)
        report["run_messages"] = await bounded(
            service.get_project_output(project_name, structured=True)
        )
        begin("read_outputs")
        files = discover_run_outputs(
            final,
            report["run_started_after"],
            metadata_started_after=report["compile_started_after"],
        )
        report["outputs"] = files
        finalized_outputs = [*files["parts"], files["inf"], files["infx"]]
        report["output_hashes_before_read"] = {
            str(path): _sha256(path) for path in finalized_outputs
        }

        def progress(completed, total):
            report["read_progress"] = {
                "completed_parts": completed,
                "total_parts": total,
            }
            if completed % 8 == 0 or completed == total:
                _write_report(report_path, report)
                print(f"MMC_NATIVE_PROBE_READ={completed}/{total}", flush=True)

        traces = await bounded(
            read_run_probes(service, files, receipt, progress), args.read_timeout
        )
        report["output_hashes_after_read"] = {
            str(path): _sha256(path) for path in finalized_outputs
        }
        if report["output_hashes_before_read"] != report["output_hashes_after_read"]:
            raise RuntimeError("Output artifacts changed while being read")
        begin("analyze")
        report["analysis"] = analyze_probes(
            traces,
            fault_time=args.fault_time,
            fault_duration=args.fault_duration,
            duration=args.duration,
            sample_step=args.sample_step * 1e-6,
        )
        report["status"] = report["analysis"]["status"]
        report["finalized_project_sha256_after_run"] = _sha256(final)
        if (
            report["finalized_project_sha256_after_run"]
            != report["finalized_project_sha256_before_run"]
        ):
            raise RuntimeError("The finalized project changed during the run")
        if report["status"] == "FAIL":
            report["failure_category"] = (
                "model_physical"
                if report["analysis"]["measurement_complete"]
                else "implementation_or_measurement"
            )
        report["stages"][-1].update(status=report["status"], finished_at=_stamp())
    except BaseException as error:  # noqa: BLE001 - every interrupted attempt needs a durable failure report
        report.update(
            status="FAIL",
            failure_category=_category(stage, error),
            error=_error(error),
            failed_stage=stage,
        )
        if report["stages"]:
            report["stages"][-1].update(
                status="FAIL", finished_at=_stamp(), error=_error(error)
            )
        if service is not None and project_name and managed_acceptance_pid(runtime):
            try:
                report["failure_messages"] = await bounded(
                    service.get_project_output(project_name, structured=True)
                )
            except BaseException as message_error:  # noqa: BLE001 - failed diagnostics must not prevent cleanup
                report["failure_messages_error"] = _error(message_error)
    finally:
        try:
            _write_report(report_path, report)
        except OSError as write_error:
            report["pre_cleanup_report_error"] = _error(write_error)
            report["status"] = "FAIL"
        try:
            if service is not None and attach_attempted:
                if not runtime:
                    runtime = await bounded(service.status())
                    report["runtime_after_error"] = runtime
                report["cleanup"] = await cleanup_owned_session(
                    service,
                    runtime,
                    project_name=project_name,
                    run_pending=run_pending,
                    timeout=args.cleanup_timeout,
                )
            else:
                report["cleanup"] = {
                    "owned_process_cleaned": True,
                    "runtime_started": False,
                    "remaining_owned_processes": [],
                }
            if not report["cleanup"]["owned_process_cleaned"] or report["cleanup"].get(
                "errors"
            ):
                report["status"] = "FAIL"
                report.setdefault("failure_category", "process_cleanup")
        except BaseException as error:  # noqa: BLE001 - retain cleanup failure and finish source verification
            report["cleanup"] = {"owned_process_cleaned": False, "error": _error(error)}
            report["status"] = "FAIL"
            report.setdefault("failure_category", "process_cleanup")
        try:
            after = {path: _sha256(Path(path)) for path in input_hashes}
            report["source_hashes_after"] = after
            report["source_inputs_immutable"] = (
                bool(input_hashes) and after == input_hashes
            )
            if code_before:
                report["code_after"] = _code_snapshot()
                report["source_code_immutable"] = (
                    report["code_after"]["source_code_hashes"]
                    == code_before["source_code_hashes"]
                    and report["code_after"]["commit"] == code_before["commit"]
                )
            if not report["source_inputs_immutable"] or not report.get(
                "source_code_immutable", False
            ):
                report["status"] = "FAIL"
                report.setdefault("failure_category", "implementation_defect")
            report["artifacts"] = {
                str(path): {"sha256": _sha256(path), "bytes": path.stat().st_size}
                for path in sorted(run_dir.rglob("*"))
                if path.is_file()
                and path != report_path
                and path != report_path.with_suffix(".json.tmp")
            }
        except BaseException as error:  # noqa: BLE001 - retain failed evidence finalization
            report["finalization_error"] = _error(error)
            report["status"] = "FAIL"
            report.setdefault("failure_category", "implementation_defect")
        report["finished_at"] = _stamp()
        _write_report(report_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("C:/Program Files (x86)/PSCAD46/master.pslx"),
    )
    parser.add_argument(
        "--compiler-configuration",
        type=Path,
        default=Path("C:/Program Files (x86)/PSCAD46/fortran_compilers.xml"),
    )
    parser.add_argument(
        "--compiler-executable",
        type=Path,
        default=Path("C:/Program Files (x86)/GFortran/4.6/bin/gfortran.exe"),
    )
    parser.add_argument(
        "--tline",
        type=Path,
        default=Path(
            os.environ.get(
                "PSCAD_MCP_TLINE", "C:/Program Files (x86)/PSCAD46/bin/win/tline.exe"
            )
        ),
    )
    parser.add_argument("--fault-time", type=float, default=0.8)
    parser.add_argument("--fault-duration", type=float, default=0.2)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument(
        "--time-step", type=float, default=50.0, help="EMTDC step in microseconds"
    )
    parser.add_argument(
        "--sample-step", type=float, default=250.0, help="Output step in microseconds"
    )
    for name, default in (
        ("operation-timeout", 300),
        ("build-timeout", 600),
        ("run-timeout", 900),
        ("read-timeout", 1800),
        ("cleanup-timeout", 30),
        ("poll-interval", 0.5),
    ):
        parser.add_argument("--" + name, type=float, default=default)
    return parser


def main(argv: Sequence[str] | None = None, *, service_factory=_service) -> int:
    args = _parser().parse_args(argv)
    if os.environ.get("PSCAD_MCP_ACCEPTANCE") != "1":
        print(
            "PSCAD_MCP_ACCEPTANCE=1 is required; no runtime or workspace was created.",
            file=sys.stderr,
        )
        return 2
    numeric = (
        "fault_time",
        "fault_duration",
        "duration",
        "time_step",
        "sample_step",
        "operation_timeout",
        "build_timeout",
        "run_timeout",
        "read_timeout",
        "cleanup_timeout",
        "poll_interval",
    )
    if any(
        not math.isfinite(getattr(args, key)) or getattr(args, key) <= 0
        for key in numeric
    ):
        raise SystemExit("Timing and timeout values must be finite and positive")
    if (
        args.fault_time + args.fault_duration + 2 * args.sample_step * 1e-6
        >= args.duration
    ):
        raise SystemExit(
            "The run must include samples before and after the full requested fault"
        )
    if args.sample_step < args.time_step or not math.isclose(
        args.sample_step / args.time_step,
        round(args.sample_step / args.time_step),
        abs_tol=1e-9,
    ):
        raise SystemExit(
            "The sample step must be an integer multiple of the EMTDC time step"
        )
    if args.duration / (args.sample_step * 1e-6) + 1 > MAX_SAMPLES:
        raise SystemExit(
            "The requested run exceeds the 100000 full-sample diagnostic bound"
        )
    if not args.workspace_root.expanduser().is_absolute():
        raise SystemExit("--workspace-root must be absolute")
    for key in (
        "workspace_root",
        "template",
        "library",
        "master",
        "compiler_configuration",
        "compiler_executable",
        "tline",
    ):
        raw = getattr(args, key).expanduser()
        if raw.is_symlink():
            raise SystemExit(f"Symbolic-link input/workspace is not supported: {raw}")
        setattr(args, key, raw.resolve())
    for source in (
        args.template,
        args.library,
        args.master,
        args.compiler_configuration,
        args.compiler_executable,
        args.tline,
    ):
        if args.workspace_root.is_relative_to(source.parent) or source.is_relative_to(
            args.workspace_root
        ):
            raise SystemExit(
                "The workspace must be disjoint from immutable source/compiler directories"
            )
    run_dir = args.workspace_root / (
        "mmc-native-probe-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    report = asyncio.run(run_attempt(args, run_dir, service_factory=service_factory))
    print(f"MMC_NATIVE_PROBE_STATUS={report['status']}")
    print(f"MMC_NATIVE_PROBE_REPORT={run_dir / 'report.json'}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
