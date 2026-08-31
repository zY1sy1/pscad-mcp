"""Strict durable evidence and scoped promotion for fixed LCC smoke runs."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ....acceptance.baseline import validate_program_baseline
from ....acceptance.evidence import build_run_metadata, index_explicit_reports
from ....acceptance.promotion import promote_program_report
from ....core.backend.base import BackendError
from ....core.master_bindings import parse_master_binding_registry
from .companion import audit_companion_library
from .companion_gate import FIXTURES

FIXED_SCOPE = "lcc.fixed_autonomous"
FIXED_BUILDER_PATH = "lcc.fixed_autonomous"
FIXED_KIND = "licensed_simulation"
FIXED_CAPABILITY = "simulated"
FIXED_OWNER = "WP1"
FIXED_EXCLUSIONS = (
    "disturbance_acceptance",
    "commutation_failure_acceptance",
    "independent_golden",
    "final_accepted",
)
SUCCESS_HISTORY = (
    "validated",
    "staging_created",
    "components_placed",
    "parameters_verified",
    "connections_verified",
    "structure_verified",
    "staging_saved",
    "compiled",
    "simulated",
    "smoke_passed",
    "published",
)
REPORT_KEYS = {
    "schema_version",
    "run_id",
    "scope",
    "builder_path",
    "kind",
    "capability_state",
    "commit",
    "generated_at_utc",
    "status",
    "repository",
    "preflight",
    "sources",
    "component_gate",
    "build",
    "artifacts",
    "smoke",
    "runtime",
    "explicit_exclusions",
    "failure",
}
SOURCE_KEYS = {
    "master",
    "registry",
    "asset_manifest",
    "catalog",
    "blueprint",
    "library",
    "smoke_contract",
    "provenance",
}
BUILD_KEYS = {
    "project_name",
    "workspace",
    "build_id",
    "plan_hash",
    "verification_profile",
    "journal_path",
    "journal_sha256",
    "history",
    "terminal_state",
}
ARTIFACT_KEYS = {
    "project",
    "library",
    "selected_output",
    "output_parts",
    "output_metadata",
}

_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_REPORT_BYTES = 16 * 1024 * 1024
_SMOKE_DURATION_S = 0.1
_SMOKE_OUTPUT_STEP_S = 0.00005
_SMOKE_CHECKS = (
    "time_domain",
    "finite_outputs",
    "controls_enabled",
    "ao_within_limits",
)
_SMOKE_CHANNELS = (
    "Main/IDC",
    "Main/VDC_RECT",
    "Main/VDC_INV",
    "Main/AO_RECT_Y",
    "Main/AO_RECT_D",
    "Main/AO_INV_Y",
    "Main/AO_INV_D",
    "Main/GAMMA_INV",
    "Main/ENABLE_RECT",
    "Main/ENABLE_INV",
)
_ENABLE_CHANNELS = ("Main/ENABLE_RECT", "Main/ENABLE_INV")
_AO_LIMITS = {
    "Main/AO_RECT_Y": (0.08726646259971647, 0.5235987755982988),
    "Main/AO_RECT_D": (0.08726646259971647, 0.5235987755982988),
    "Main/AO_INV_Y": (0.52, 1.92),
    "Main/AO_INV_D": (0.52, 1.92),
}
_ELECTRICAL_BRIDGE_PORTS = {
    "ACY_A",
    "ACY_B",
    "ACY_C",
    "ACD_A",
    "ACD_B",
    "ACD_C",
    "DC_POS",
    "DC_NEG",
}
_MANIFEST_SOURCES = {
    "registry": "master-bindings-pscad-4.6.2.json",
    "catalog": "catalog-pscad-4.6.2.json",
    "blueprint": "blueprint.json",
    "library": "library/cigre_lcc_v1.pslx",
    "smoke_contract": "smoke.json",
    "provenance": "PROVENANCE.md",
}


def _error(field: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        "LCC_FIXED_REPORT_INVALID",
        message,
        "hvdc",
        "validate_fixed_lcc_acceptance_report",
        {"field": field, **details},
    )


def _exact_record(value: Any, field: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _error(field, f"{field} fields are not exact.")
    return dict(value)


def _sequence(value: Any, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise _error(field, f"{field} must be an array.")
    return list(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(field, f"{field} must be non-empty text.")
    return value.strip()


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if _HASH.fullmatch(text) is None:
        raise _error(field, f"{field} must be lowercase SHA-256.")
    return text


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(field, f"{field} must be a finite number.")
    number = float(value)
    if not math.isfinite(number):
        raise _error(field, f"{field} must be a finite number.")
    return number


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error(field, f"{field} must be a positive integer.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_path(value: str | Path, field: str) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    marker = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    for component in [*reversed(path.parents), path]:
        try:
            observed = os.lstat(component)
        except OSError as error:
            raise _error(field, f"{field} is not a regular file.") from error
        attributes = int(getattr(observed, "st_file_attributes", 0))
        if stat.S_ISLNK(observed.st_mode) or attributes & marker:
            raise _error(field, f"{field} contains a symlink/reparse component.")
    if not path.is_file():
        raise _error(field, f"{field} is not a regular file.")
    return path


def _regular_directory(value: str | Path, field: str) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    marker = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    for component in [*reversed(path.parents), path]:
        try:
            observed = os.lstat(component)
        except OSError as error:
            raise _error(field, f"{field} is not a regular directory.") from error
        attributes = int(getattr(observed, "st_file_attributes", 0))
        if stat.S_ISLNK(observed.st_mode) or attributes & marker:
            raise _error(field, f"{field} contains a symlink/reparse component.")
    if not path.is_dir():
        raise _error(field, f"{field} is not a regular directory.")
    return path


def _path_hash(value: Any, field: str) -> dict[str, str]:
    item = _exact_record(value, field, {"path", "sha256"})
    return {
        "path": _text(item["path"], f"{field}.path"),
        "sha256": _hash(item["sha256"], f"{field}.sha256"),
    }


def _validate_repository(
    value: Any,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    item = _exact_record(value, "repository", {"branch", "commit", "clean"})
    normalized = {
        "branch": _text(item["branch"], "repository.branch"),
        "commit": metadata["commit"],
        "clean": True,
    }
    if item != normalized:
        raise _error(
            "repository",
            "Repository evidence must name the clean report commit.",
        )
    return normalized


def _validate_preflight(value: Any, *, require_pass: bool) -> dict[str, Any]:
    item = _exact_record(value, "preflight", {"status", "sha256", "snapshot"})
    status = _text(item["status"], "preflight.status")
    if status not in {"PASS", "FAIL"} or require_pass and status != "PASS":
        raise _error("preflight.status", "PASS report requires PASS preflight.")
    if not isinstance(item["snapshot"], Mapping):
        raise _error("preflight.snapshot", "Preflight snapshot must be an object.")
    snapshot = copy.deepcopy(dict(item["snapshot"]))
    try:
        encoded = json.dumps(
            snapshot,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise _error(
            "preflight.snapshot",
            "Preflight snapshot must be canonical JSON.",
        ) from error
    observed = _hash(item["sha256"], "preflight.sha256")
    if observed != hashlib.sha256(encoded).hexdigest():
        raise _error("preflight.sha256", "Preflight snapshot hash is invalid.")
    if require_pass:
        for path_field, hash_field in (
            ("compiler_configuration", "compiler_configuration_sha256"),
            ("compiler_executable", "compiler_executable_sha256"),
            ("master_path", "master_sha256"),
        ):
            _text(snapshot.get(path_field), f"preflight.{path_field}")
            _hash(snapshot.get(hash_field), f"preflight.{hash_field}")
    return {"status": status, "sha256": observed, "snapshot": snapshot}


def _validate_immutable_source(
    value: Any,
    field: str,
    *,
    require_immutable: bool,
) -> dict[str, str | None]:
    item = _exact_record(value, field, {"path", "before", "after"})
    before = _hash(item["before"], f"{field}.before")
    after = (
        None
        if item["after"] is None and not require_immutable
        else _hash(item["after"], f"{field}.after")
    )
    if require_immutable and before != after:
        raise _error(field, f"{field} changed during fixed acceptance.")
    return {
        "path": _text(item["path"], f"{field}.path"),
        "before": before,
        "after": after,
    }


def _validate_sources(value: Any, *, require_immutable: bool) -> dict[str, Any]:
    item = _exact_record(value, "sources", SOURCE_KEYS)
    result = {
        name: _validate_immutable_source(
            item[name],
            f"sources.{name}",
            require_immutable=require_immutable,
        )
        for name in SOURCE_KEYS - {"registry"}
    }
    registry = _exact_record(
        item["registry"],
        "sources.registry",
        {"path", "before", "after", "registry_sha256"},
    )
    before = _hash(registry["before"], "sources.registry.before")
    after = (
        None
        if registry["after"] is None and not require_immutable
        else _hash(registry["after"], "sources.registry.after")
    )
    if require_immutable and before != after:
        raise _error(
            "sources.registry",
            "The registry changed during fixed acceptance.",
        )
    result["registry"] = {
        "path": _text(registry["path"], "sources.registry.path"),
        "before": before,
        "after": after,
        "registry_sha256": _hash(
            registry["registry_sha256"],
            "sources.registry.registry_sha256",
        ),
    }
    return result


def _same_value(left: Any, right: Any) -> bool:
    if left == right or str(left).strip() == str(right).strip():
        return True
    try:
        return float(str(left).split("[", 1)[0]) == float(
            str(right).split("[", 1)[0]
        )
    except (TypeError, ValueError):
        return False


def _validate_snapshot(
    value: Any,
    field: str,
    fixture: Any,
) -> dict[str, Any]:
    item = _exact_record(value, field, {"definition", "parameters", "ports"})
    if item["definition"] != fixture.definition:
        raise _error(field, "Fixture Definition evidence is not exact.")
    if not isinstance(item["parameters"], Mapping):
        raise _error(f"{field}.parameters", "Fixture parameters must be an object.")
    parameters = {
        _text(name, f"{field}.parameters.name"): _text(
            observed,
            f"{field}.parameters.{name}",
        )
        for name, observed in item["parameters"].items()
    }
    for name, expected in fixture.parameters.items():
        if name not in parameters or not _same_value(parameters[name], expected):
            raise _error(
                f"{field}.parameters.{name}",
                "Fixture parameter evidence is not exact.",
            )
    if not isinstance(item["ports"], Mapping) or set(item["ports"]) != set(
        fixture.expected_ports
    ):
        raise _error(f"{field}.ports", "Fixture port evidence is not exact.")
    ports = {}
    bridge = fixture.definition.endswith(":LCC12PulseBridge")
    for name in fixture.expected_ports:
        port = _exact_record(
            item["ports"][name],
            f"{field}.ports.{name}",
            {"kind", "dimension"},
        )
        expected_kind = (
            "electrical"
            if bridge and name in _ELECTRICAL_BRIDGE_PORTS
            else "data"
        )
        if port["kind"] != expected_kind or port["dimension"] != 1:
            raise _error(
                f"{field}.ports.{name}",
                "Fixture port contract evidence is not exact.",
            )
        ports[name] = {"kind": expected_kind, "dimension": 1}
    return {
        "definition": fixture.definition,
        "parameters": parameters,
        "ports": ports,
    }


def _validate_fixture(value: Any, index: int) -> dict[str, Any]:
    field = f"component_gate.fixtures[{index}]"
    fixture = FIXTURES[index]
    item = _exact_record(
        value,
        field,
        {
            "fixture",
            "definition",
            "project",
            "component_id",
            "before_reload",
            "after_reload",
            "compile",
        },
    )
    if item["fixture"] != fixture.name or item["definition"] != fixture.definition:
        raise _error(field, "Component fixture order or identity is not exact.")
    project = _exact_record(
        item["project"],
        f"{field}.project",
        {"name", "path", "sha256_before_compile", "sha256"},
    )
    normalized_project = {
        "name": _text(project["name"], f"{field}.project.name"),
        "path": _text(project["path"], f"{field}.project.path"),
        "sha256_before_compile": _hash(
            project["sha256_before_compile"],
            f"{field}.project.sha256_before_compile",
        ),
        "sha256": _hash(project["sha256"], f"{field}.project.sha256"),
    }
    before = _validate_snapshot(item["before_reload"], f"{field}.before_reload", fixture)
    after = _validate_snapshot(item["after_reload"], f"{field}.after_reload", fixture)
    if before != after:
        raise _error(field, "Fixture identity changed after reload.")
    compile_result = _exact_record(
        item["compile"],
        f"{field}.compile",
        {"success", "result_type"},
    )
    if compile_result["success"] is not True:
        raise _error(f"{field}.compile", "Fixture compile did not succeed.")
    return {
        "fixture": fixture.name,
        "definition": fixture.definition,
        "project": normalized_project,
        "component_id": _positive_integer(
            item["component_id"],
            f"{field}.component_id",
        ),
        "before_reload": before,
        "after_reload": after,
        "compile": {
            "success": True,
            "result_type": _text(
                compile_result["result_type"],
                f"{field}.compile.result_type",
            ),
        },
    }


def _validate_gate_failure(value: Any) -> dict[str, str]:
    item = _exact_record(
        value,
        "component_gate.failure",
        {"fixture", "operation", "code", "message"},
    )
    return {
        name: _text(item[name], f"component_gate.failure.{name}")
        for name in ("fixture", "operation", "code", "message")
    }


def _validate_component_gate(
    value: Any,
    *,
    require_pass: bool,
) -> dict[str, Any] | None:
    if value is None and not require_pass:
        return None
    item = _exact_record(
        value,
        "component_gate",
        {
            "schema_version",
            "status",
            "workspace",
            "master_sha256",
            "registry_sha256",
            "library",
            "fixtures",
            "failure",
        },
    )
    if item["schema_version"] != 1 or isinstance(item["schema_version"], bool):
        raise _error("component_gate.schema_version", "Gate schema must be 1.")
    status = _text(item["status"], "component_gate.status")
    if status not in {"PASS", "FAIL"} or require_pass and status != "PASS":
        raise _error("component_gate.status", "PASS report requires PASS gate.")
    raw_fixtures = _sequence(item["fixtures"], "component_gate.fixtures")
    if len(raw_fixtures) > len(FIXTURES):
        raise _error("component_gate.fixtures", "The fixture list is too long.")
    fixtures = [
        _validate_fixture(raw_fixture, index)
        for index, raw_fixture in enumerate(raw_fixtures)
    ]
    if status == "PASS" and len(fixtures) != len(FIXTURES):
        raise _error(
            "component_gate.fixtures",
            "PASS gate requires all six fixtures in exact order.",
        )
    library = (
        None
        if item["library"] is None and status == "FAIL"
        else _path_hash(item["library"], "component_gate.library")
    )
    failure = (
        None
        if item["failure"] is None
        else _validate_gate_failure(item["failure"])
    )
    if status == "PASS" and failure is not None:
        raise _error("component_gate.failure", "PASS gate contains failure evidence.")
    if status == "FAIL" and failure is None:
        raise _error("component_gate.failure", "FAIL gate requires failure evidence.")
    return {
        "schema_version": 1,
        "status": status,
        "workspace": _text(item["workspace"], "component_gate.workspace"),
        "master_sha256": _hash(
            item["master_sha256"],
            "component_gate.master_sha256",
        ),
        "registry_sha256": _hash(
            item["registry_sha256"],
            "component_gate.registry_sha256",
        ),
        "library": library,
        "fixtures": fixtures,
        "failure": failure,
    }


def _validate_build(value: Any, *, require_published: bool) -> dict[str, Any]:
    item = _exact_record(value, "build", BUILD_KEYS)
    history = [
        _text(entry, "build.history")
        for entry in _sequence(item["history"], "build.history")
    ]
    result = {
        "project_name": _text(item["project_name"], "build.project_name"),
        "workspace": _text(item["workspace"], "build.workspace"),
        "build_id": (
            None
            if item["build_id"] is None
            else _text(item["build_id"], "build.build_id")
        ),
        "plan_hash": (
            None
            if item["plan_hash"] is None
            else _hash(item["plan_hash"], "build.plan_hash")
        ),
        "verification_profile": (
            None
            if item["verification_profile"] is None
            else _text(
                item["verification_profile"],
                "build.verification_profile",
            )
        ),
        "journal_path": (
            None
            if item["journal_path"] is None
            else _text(item["journal_path"], "build.journal_path")
        ),
        "journal_sha256": (
            None
            if item["journal_sha256"] is None
            else _hash(item["journal_sha256"], "build.journal_sha256")
        ),
        "history": history,
        "terminal_state": _text(item["terminal_state"], "build.terminal_state"),
    }
    if require_published and (
        any(
            result[name] is None
            for name in (
                "build_id",
                "plan_hash",
                "verification_profile",
                "journal_path",
                "journal_sha256",
            )
        )
        or result["verification_profile"] != "wp1b_smoke"
        or tuple(history) != SUCCESS_HISTORY
        or result["terminal_state"] != "published"
    ):
        raise _error("build", "PASS requires exact published WP1B build evidence.")
    return result


def _validate_pass_artifacts(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "artifacts", ARTIFACT_KEYS)
    parts = _sequence(item["output_parts"], "artifacts.output_parts")
    metadata = _sequence(item["output_metadata"], "artifacts.output_metadata")
    if not parts:
        raise _error("artifacts.output_parts", "PASS requires output parts.")
    return {
        "project": _path_hash(item["project"], "artifacts.project"),
        "library": _path_hash(item["library"], "artifacts.library"),
        "selected_output": _path_hash(
            item["selected_output"],
            "artifacts.selected_output",
        ),
        "output_parts": [
            _path_hash(entry, f"artifacts.output_parts[{index}]")
            for index, entry in enumerate(parts)
        ],
        "output_metadata": [
            _path_hash(entry, f"artifacts.output_metadata[{index}]")
            for index, entry in enumerate(metadata)
        ],
    }


def _validate_fail_artifacts(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "artifacts", ARTIFACT_KEYS)
    return {
        **{
            name: (
                None
                if item[name] is None
                else _path_hash(item[name], f"artifacts.{name}")
            )
            for name in ("project", "library", "selected_output")
        },
        "output_parts": [
            _path_hash(entry, f"artifacts.output_parts[{index}]")
            for index, entry in enumerate(
                _sequence(item["output_parts"], "artifacts.output_parts")
            )
        ],
        "output_metadata": [
            _path_hash(entry, f"artifacts.output_metadata[{index}]")
            for index, entry in enumerate(
                _sequence(item["output_metadata"], "artifacts.output_metadata")
            )
        ],
    }


def _validate_smoke(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "smoke", {"verdict", "checks", "evidence"})
    checks = _exact_record(item["checks"], "smoke.checks", set(_SMOKE_CHECKS))
    if item["verdict"] != "PASS" or any(
        checks[name] is not True for name in _SMOKE_CHECKS
    ):
        raise _error("smoke", "All fixed smoke checks must pass.")
    evidence = _exact_record(
        item["evidence"],
        "smoke.evidence",
        {
            "duration_s",
            "output_step_s",
            "domain_start_s",
            "domain_end_s",
            "samples",
            "channels",
        },
    )
    duration = _finite(evidence["duration_s"], "smoke.evidence.duration_s")
    output_step = _finite(
        evidence["output_step_s"],
        "smoke.evidence.output_step_s",
    )
    start = _finite(
        evidence["domain_start_s"],
        "smoke.evidence.domain_start_s",
    )
    end = _finite(evidence["domain_end_s"], "smoke.evidence.domain_end_s")
    samples = _positive_integer(evidence["samples"], "smoke.evidence.samples")
    if (
        not math.isclose(duration, _SMOKE_DURATION_S, abs_tol=1e-12)
        or not math.isclose(output_step, _SMOKE_OUTPUT_STEP_S, abs_tol=1e-12)
        or start < 0
        or end <= start
        or abs(end - duration) > output_step
    ):
        raise _error("smoke.evidence", "Smoke time-domain evidence is invalid.")
    raw_channels = evidence["channels"]
    if not isinstance(raw_channels, Mapping) or set(raw_channels) != set(
        _SMOKE_CHANNELS
    ):
        raise _error("smoke.evidence.channels", "Smoke channels are not exact.")
    channels = {}
    for name in _SMOKE_CHANNELS:
        field = f"smoke.evidence.channels.{name}"
        channel = _exact_record(
            raw_channels[name],
            field,
            {"units", "samples", "minimum", "maximum"},
        )
        if not isinstance(channel["units"], str):
            raise _error(f"{field}.units", "Smoke channel units must be text.")
        channel_samples = _positive_integer(channel["samples"], f"{field}.samples")
        minimum = _finite(channel["minimum"], f"{field}.minimum")
        maximum = _finite(channel["maximum"], f"{field}.maximum")
        if channel_samples != samples or minimum > maximum:
            raise _error(field, "Smoke channel summary is invalid.")
        units = channel["units"].strip()
        if name in _AO_LIMITS:
            lower, upper = _AO_LIMITS[name]
            if units.casefold() != "rad" or minimum < lower or maximum > upper:
                raise _error(field, "AO smoke evidence is outside its contract.")
        if name in _ENABLE_CHANNELS and (minimum != 1.0 or maximum != 1.0):
            raise _error(field, "Enable smoke evidence is not continuously on.")
        channels[name] = {
            "units": units,
            "samples": channel_samples,
            "minimum": minimum,
            "maximum": maximum,
        }
    return {
        "verdict": "PASS",
        "checks": {name: True for name in _SMOKE_CHECKS},
        "evidence": {
            "duration_s": duration,
            "output_step_s": output_step,
            "domain_start_s": start,
            "domain_end_s": end,
            "samples": samples,
            "channels": channels,
        },
    }


def _validate_runtime(value: Any, *, require_licensed: bool) -> dict[str, Any]:
    item = _exact_record(
        value,
        "runtime",
        {
            "backend",
            "version",
            "x64",
            "licensed",
            "managed_pid",
            "quit_error",
            "remaining_processes",
        },
    )
    if not isinstance(item["backend"], str) or not isinstance(item["version"], str):
        raise _error("runtime", "Runtime backend and version must be text.")
    backend = item["backend"].strip()
    version = item["version"].strip()
    if not isinstance(item["x64"], bool) or not isinstance(item["licensed"], bool):
        raise _error("runtime", "Runtime x64 and licensed must be boolean.")
    if require_licensed and (
        backend != "legacy"
        or version != "4.6.2"
        or item["x64"] is not True
        or item["licensed"] is not True
    ):
        raise _error("runtime", "PASS requires licensed Legacy PSCAD 4.6.2 x64.")
    managed_pid = item["managed_pid"]
    if managed_pid is not None and (
        isinstance(managed_pid, bool) or not isinstance(managed_pid, int)
    ):
        raise _error("runtime.managed_pid", "managed_pid must be integer or null.")
    if item["quit_error"] is not None and not isinstance(item["quit_error"], str):
        raise _error("runtime.quit_error", "quit_error must be text or null.")
    processes = _sequence(
        item["remaining_processes"],
        "runtime.remaining_processes",
    )
    if any(not isinstance(process, Mapping) for process in processes):
        raise _error(
            "runtime.remaining_processes",
            "Remaining process entries must be objects.",
        )
    return {
        "backend": backend,
        "version": version,
        "x64": item["x64"],
        "licensed": item["licensed"],
        "managed_pid": managed_pid,
        "quit_error": item["quit_error"],
        "remaining_processes": copy.deepcopy(processes),
    }


def _validate_failure(value: Any) -> dict[str, str]:
    item = _exact_record(value, "failure", {"stage", "code", "message"})
    return {
        name: _text(item[name], f"failure.{name}")
        for name in ("stage", "code", "message")
    }


def validate_fixed_lcc_acceptance_report(value: Any) -> dict[str, Any]:
    report = _exact_record(value, "report", REPORT_KEYS)
    if report["schema_version"] != 1 or isinstance(report["schema_version"], bool):
        raise _error("schema_version", "schema_version must be 1.")
    try:
        metadata = build_run_metadata(
            run_id=_text(report["run_id"], "run_id"),
            scope=_text(report["scope"], "scope"),
            kind=_text(report["kind"], "kind"),
            capability_state=_text(
                report["capability_state"],
                "capability_state",
            ),
            commit=_text(report["commit"], "commit"),
            generated_at_utc=_text(
                report["generated_at_utc"],
                "generated_at_utc",
            ),
        )
    except BackendError as error:
        raise _error("metadata", "Fixed report metadata is invalid.") from error
    if (
        metadata["scope"] != FIXED_SCOPE
        or metadata["builder_path"] != FIXED_BUILDER_PATH
        or _text(report["builder_path"], "builder_path") != FIXED_BUILDER_PATH
        or metadata["kind"] != FIXED_KIND
    ):
        raise _error("scope", "The report is not owned by fixed LCC.")
    exclusions = _sequence(report["explicit_exclusions"], "explicit_exclusions")
    if tuple(exclusions) != FIXED_EXCLUSIONS:
        raise _error("explicit_exclusions", "Fixed exclusions are not exact.")
    status = _text(report["status"], "status")
    if status not in {"PASS", "FAIL"}:
        raise _error("status", "Fixed status must be PASS or FAIL.")
    require_pass = status == "PASS"
    repository = _validate_repository(report["repository"], metadata)
    preflight = _validate_preflight(report["preflight"], require_pass=require_pass)
    sources = _validate_sources(
        report["sources"],
        require_immutable=require_pass,
    )
    component_gate = _validate_component_gate(
        report["component_gate"],
        require_pass=require_pass,
    )
    build = _validate_build(report["build"], require_published=require_pass)
    runtime = _validate_runtime(report["runtime"], require_licensed=require_pass)
    if require_pass:
        if metadata["capability_state"] != FIXED_CAPABILITY:
            raise _error("capability_state", "PASS must remain simulated.")
        if tuple(build["history"]) != SUCCESS_HISTORY:
            raise _error("build.history", "PASS history is not exact.")
        smoke = _validate_smoke(report["smoke"])
        artifacts = _validate_pass_artifacts(report["artifacts"])
        if (
            report["failure"] is not None
            or runtime["quit_error"] is not None
            or runtime["remaining_processes"]
        ):
            raise _error("failure", "PASS contains failure or cleanup evidence.")
        if component_gate is None:
            raise _error("component_gate", "PASS requires component gate evidence.")
        if (
            component_gate["master_sha256"] != sources["master"]["after"]
            or component_gate["registry_sha256"]
            != sources["registry"]["registry_sha256"]
            or component_gate["library"] is None
            or component_gate["library"]["sha256"] != sources["library"]["after"]
            or artifacts["library"]["sha256"] != sources["library"]["after"]
        ):
            raise _error(
                "sources",
                "PASS source identities do not bind gate and build artifacts.",
            )
        snapshot = preflight["snapshot"]
        if (
            _identity_path(snapshot["master_path"])
            != _identity_path(sources["master"]["path"])
            or snapshot["master_sha256"] != sources["master"]["after"]
        ):
            raise _error(
                "preflight.master",
                "Preflight does not bind the report Master source.",
            )
        failure = None
    else:
        if metadata["capability_state"] != "failed":
            raise _error("capability_state", "FAIL must use failed.")
        if report["smoke"] is not None:
            raise _error("smoke", "FAIL cannot contain PASS smoke.")
        smoke = None
        artifacts = _validate_fail_artifacts(report["artifacts"])
        failure = _validate_failure(report["failure"])
    return copy.deepcopy(
        {
            **metadata,
            "status": status,
            "repository": repository,
            "preflight": preflight,
            "sources": sources,
            "component_gate": component_gate,
            "build": build,
            "artifacts": artifacts,
            "smoke": smoke,
            "runtime": runtime,
            "explicit_exclusions": list(FIXED_EXCLUSIONS),
            "failure": failure,
        }
    )


def _verify_file(path_value: str, expected_sha256: str, field: str) -> Path:
    path = _regular_path(path_value, field)
    if _sha256(path) != expected_sha256:
        raise _error(field, f"{field} file/hash evidence does not match disk.")
    return path


def _require_owned(path: Path, root: Path, field: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise _error(field, f"{field} escaped its owned workspace.") from error


def _verify_audited_library(path: Path, expected_sha256: str, field: str) -> None:
    try:
        audit = audit_companion_library(path)
    except BackendError as error:
        raise _error(field, f"{field} failed physical companion audit.") from error
    if audit.get("sha256") != expected_sha256:
        raise _error(field, f"{field} physical audit hash is inconsistent.")


def _verify_manifest_sources(report: Mapping[str, Any]) -> None:
    sources = report["sources"]
    manifest_path = _verify_file(
        sources["asset_manifest"]["path"],
        sources["asset_manifest"]["after"],
        "sources.asset_manifest",
    )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error("sources.asset_manifest", "Asset manifest is invalid.") from error
    hashes = manifest.get("hashes") if isinstance(manifest, Mapping) else None
    if (
        not isinstance(hashes, Mapping)
        or manifest.get("schema_version") != 1
        or manifest.get("name") != "cigre_lcc_monopole_v1"
        or manifest.get("pscad_version") != "4.6.2"
        or manifest.get("companion_library") != _MANIFEST_SOURCES["library"]
    ):
        raise _error("sources.asset_manifest", "Asset manifest identity is invalid.")
    root = manifest_path.parent
    for source_name, relative in _MANIFEST_SOURCES.items():
        source = sources[source_name]
        expected_path = Path(os.path.abspath(root / Path(relative)))
        if (
            _identity_path(source["path"]) != _identity_path(expected_path)
            or hashes.get(relative) != source["after"]
        ):
            raise _error(
                f"sources.{source_name}",
                "Source is not bound by the fixed asset manifest.",
            )


def _verify_preflight_files(preflight: Mapping[str, Any]) -> None:
    snapshot = preflight["snapshot"]
    for path_field, hash_field in (
        ("compiler_configuration", "compiler_configuration_sha256"),
        ("compiler_executable", "compiler_executable_sha256"),
        ("master_path", "master_sha256"),
    ):
        _verify_file(
            snapshot[path_field],
            snapshot[hash_field],
            f"preflight.{path_field}",
        )


def _verify_fixed_report_files(report: Mapping[str, Any]) -> None:
    _verify_preflight_files(report["preflight"])
    sources = report["sources"]
    _verify_file(
        sources["master"]["path"],
        sources["master"]["after"],
        "sources.master",
    )
    registry_path = _verify_file(
        sources["registry"]["path"],
        sources["registry"]["after"],
        "sources.registry",
    )
    try:
        registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
        registry = parse_master_binding_registry(registry_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, BackendError) as error:
        raise _error("sources.registry", "Registry evidence is invalid.") from error
    if registry.sha256 != sources["registry"]["registry_sha256"]:
        raise _error(
            "sources.registry.registry_sha256",
            "Registry semantic hash does not match disk.",
        )
    _verify_manifest_sources(report)
    for name in SOURCE_KEYS - {"master", "registry", "asset_manifest"}:
        _verify_file(
            sources[name]["path"],
            sources[name]["after"],
            f"sources.{name}",
        )
    source_library = _regular_path(sources["library"]["path"], "sources.library")
    _verify_audited_library(
        source_library,
        sources["library"]["after"],
        "sources.library",
    )

    gate = report["component_gate"]
    gate_root = _regular_directory(gate["workspace"], "component_gate.workspace")
    gate_library = _verify_file(
        gate["library"]["path"],
        gate["library"]["sha256"],
        "component_gate.library",
    )
    _require_owned(gate_library, gate_root, "component_gate.library")
    _verify_audited_library(
        gate_library,
        gate["library"]["sha256"],
        "component_gate.library",
    )
    for index, fixture in enumerate(gate["fixtures"]):
        project = _verify_file(
            fixture["project"]["path"],
            fixture["project"]["sha256"],
            f"component_gate.fixtures[{index}].project",
        )
        _require_owned(
            project,
            gate_root,
            f"component_gate.fixtures[{index}].project",
        )

    build = report["build"]
    build_root = _regular_directory(build["workspace"], "build.workspace")
    journal = _verify_file(
        build["journal_path"],
        build["journal_sha256"],
        "build.journal",
    )
    _require_owned(journal, build_root, "build.journal")
    artifacts = report["artifacts"]
    verified_artifacts = {}
    for name in ("project", "library", "selected_output"):
        path = _verify_file(
            artifacts[name]["path"],
            artifacts[name]["sha256"],
            f"artifacts.{name}",
        )
        _require_owned(path, build_root, f"artifacts.{name}")
        verified_artifacts[name] = path
    _verify_audited_library(
        verified_artifacts["library"],
        artifacts["library"]["sha256"],
        "artifacts.library",
    )
    for group in ("output_parts", "output_metadata"):
        for index, item in enumerate(artifacts[group]):
            path = _verify_file(
                item["path"],
                item["sha256"],
                f"artifacts.{group}[{index}]",
            )
            _require_owned(path, build_root, f"artifacts.{group}[{index}]")


def load_fixed_lcc_acceptance_report(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report_path = _regular_path(path, "report")
    try:
        with report_path.open("rb") as stream:
            raw = stream.read(_MAX_REPORT_BYTES + 1)
    except OSError as error:
        raise _error("report", "Fixed report could not be read.") from error
    if len(raw) > _MAX_REPORT_BYTES:
        raise _error("report", "Fixed report exceeds 16 MiB.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error("report", "Fixed report is not UTF-8 JSON.") from error
    normalized = validate_fixed_lcc_acceptance_report(payload)
    if normalized["status"] == "PASS":
        _verify_fixed_report_files(normalized)
    indexed = index_explicit_reports([{"path": str(report_path)}])[0]
    if indexed["sha256"] != hashlib.sha256(raw).hexdigest():
        raise _error("report", "Fixed report changed during validation.")
    return normalized, indexed


def _identity_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(Path(value).expanduser()))


def _validate_fixed_baseline_identities(
    baseline_path: Path,
    report: Mapping[str, Any],
) -> None:
    try:
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline = validate_program_baseline(baseline_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, BackendError) as error:
        raise _error("baseline", "Program baseline is invalid.") from error
    environment = baseline["environment"]
    master = report["sources"]["master"]
    if (
        _identity_path(environment["master_path"]) != _identity_path(master["path"])
        or environment["master_sha256"] != master["after"]
    ):
        raise _error(
            "sources.master",
            "Fixed report does not use the baseline Master source.",
        )
    snapshot = report["preflight"]["snapshot"]
    compiler = environment["compiler"]
    for path_field, hash_field, baseline_path_field, baseline_hash_field in (
        (
            "compiler_configuration",
            "compiler_configuration_sha256",
            "configuration_path",
            "configuration_sha256",
        ),
        (
            "compiler_executable",
            "compiler_executable_sha256",
            "executable_path",
            "executable_sha256",
        ),
    ):
        if (
            _identity_path(snapshot[path_field])
            != _identity_path(compiler[baseline_path_field])
            or snapshot[hash_field] != compiler[baseline_hash_field]
        ):
            raise _error(
                f"preflight.{path_field}",
                "Fixed report does not use the baseline compiler input.",
            )
    manifests = [
        item
        for item in baseline["assets"]
        if item["asset_id"] == "asset.lcc.fixed.manifest"
    ]
    manifest = report["sources"]["asset_manifest"]
    repository_root = baseline_path.parents[2].resolve()
    if (
        len(manifests) != 1
        or _identity_path(repository_root / manifests[0]["path"])
        != _identity_path(manifest["path"])
        or manifests[0]["sha256"] != manifest["after"]
    ):
        raise _error(
            "sources.asset_manifest",
            "Fixed report does not use the baseline LCC asset manifest.",
        )
    scopes = [
        item for item in baseline["scopes"] if item["scope"] == FIXED_SCOPE
    ]
    if (
        len(scopes) != 1
        or scopes[0]["builder_path"] != FIXED_BUILDER_PATH
        or scopes[0]["owner_work_package"] != FIXED_OWNER
    ):
        raise _error("baseline.scopes", "Program baseline fixed scope is invalid.")


def write_fixed_lcc_acceptance_report(
    path: str | Path,
    value: Any,
) -> Path:
    destination = Path(path)
    normalized = validate_fixed_lcc_acceptance_report(value)
    raw = (
        json.dumps(
            normalized,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("ascii")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def promote_fixed_lcc_report(
    baseline_path: Path,
    report_path: Path,
    *,
    promotion_action: Callable[..., dict[str, Any]] = promote_program_report,
) -> dict[str, Any]:
    report, indexed = load_fixed_lcc_acceptance_report(report_path)
    if (
        report["status"] != "PASS"
        or indexed["scope"] != FIXED_SCOPE
        or indexed["builder_path"] != FIXED_BUILDER_PATH
        or indexed["kind"] != FIXED_KIND
        or indexed["capability_state"] != FIXED_CAPABILITY
    ):
        raise _error("status", "Only fixed simulated/PASS evidence may be promoted.")
    _validate_fixed_baseline_identities(baseline_path, report)
    return promotion_action(
        baseline_path,
        report_path,
        expected_scope=FIXED_SCOPE,
        owner_work_package=FIXED_OWNER,
        explicit_exclusions=FIXED_EXCLUSIONS,
        expected_report_sha256=indexed["sha256"],
        expected_repository_branch=report["repository"]["branch"],
    )


__all__ = [
    "ARTIFACT_KEYS",
    "BUILD_KEYS",
    "FIXED_BUILDER_PATH",
    "FIXED_CAPABILITY",
    "FIXED_EXCLUSIONS",
    "FIXED_KIND",
    "FIXED_OWNER",
    "FIXED_SCOPE",
    "REPORT_KEYS",
    "SOURCE_KEYS",
    "SUCCESS_HISTORY",
    "load_fixed_lcc_acceptance_report",
    "promote_fixed_lcc_report",
    "validate_fixed_lcc_acceptance_report",
    "write_fixed_lcc_acceptance_report",
]
