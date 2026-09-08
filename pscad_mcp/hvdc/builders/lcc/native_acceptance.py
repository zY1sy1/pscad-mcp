"""Strict durable evidence contract for blank/native LCC acceptance."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import os
import re
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....acceptance.baseline import validate_program_baseline
from ....acceptance.evidence import build_run_metadata, index_explicit_reports
from ....acceptance.preflight import write_preflight_report
from ....acceptance.promotion import promote_program_report
from ....core.backend.base import BackendError
from ....core.master_bindings import parse_master_binding_registry
from ....core.process_inventory import list_pscad_processes
from ....acceptance.process_scope import (
    remaining_acceptance_processes,
    require_acceptance_ownership,
)
from .journal import AtomicJournal

NATIVE_SCOPE = "lcc.blank_native"
NATIVE_BUILDER_PATH = "lcc.blank_native"
NATIVE_KIND = "licensed_simulation"
NATIVE_CAPABILITY = "simulated"
NATIVE_OWNER = "WP1"
NATIVE_EXCLUSIONS = (
    "fixed_autonomous",
    "parametric_lcc",
    "independent_golden",
    "final_accepted",
)
SUCCESS_HISTORY = (
    "validated",
    "staging_created",
    "compiled",
    "simulated",
    "acceptance_passed",
    "published",
)
REQUIRED_CHECKS = (
    "disturbance",
    "failure_indication",
    "bounded_dc_response",
    "recovered",
)

_HASH = re.compile(r"^[0-9a-f]{64}$")
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
    "build",
    "artifacts",
    "acceptance",
    "runtime",
    "explicit_exclusions",
    "failure",
}
BUILD_KEYS = {
    "project_name",
    "workspace",
    "build_id",
    "plan_hash",
    "journal_path",
    "journal_sha256",
    "history",
    "terminal_state",
}
ARTIFACT_KEYS = {
    "project",
    "library",
    "scenario",
    "selected_output",
    "output_parts",
    "output_metadata",
}


def _error(field: str, message: str) -> BackendError:
    return BackendError(
        "LCC_NATIVE_REPORT_INVALID",
        message,
        "hvdc",
        "validate_native_lcc_acceptance_report",
        {"field": field},
    )


def _exact_record(value: Any, field: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _error(field, f"{field} fields are not exact.")
    return dict(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(field, f"{field} must be non-empty text.")
    return value.strip()


def _observed_units(value: Any, field: str) -> str:
    # PSCAD 4.6 emits blank Units for some valid official-template PGB channels.
    if not isinstance(value, str):
        raise _error(field, f"{field} must be text.")
    return value.strip()


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if _HASH.fullmatch(text) is None:
        raise _error(field, f"{field} must be lowercase SHA-256.")
    return text


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


def _path_hash(value: Any, field: str) -> dict[str, str]:
    item = _exact_record(value, field, {"path", "sha256"})
    return {
        "path": _text(item["path"], f"{field}.path"),
        "sha256": _hash(item["sha256"], f"{field}.sha256"),
    }


def _validate_preflight(value: Any, *, require_pass: bool) -> dict[str, Any]:
    item = _exact_record(value, "preflight", {"status", "sha256", "snapshot"})
    if item["status"] not in {"PASS", "FAIL"}:
        raise _error("preflight.status", "Preflight status must be PASS or FAIL.")
    if require_pass and item["status"] != "PASS":
        raise _error("preflight.status", "Preflight must pass.")
    if not isinstance(item["snapshot"], Mapping):
        raise _error("preflight.snapshot", "Preflight snapshot must be an object.")
    try:
        encoded = json.dumps(
            item["snapshot"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise _error(
            "preflight.snapshot",
            "Preflight snapshot must be canonical JSON.",
        ) from error
    expected = hashlib.sha256(encoded).hexdigest()
    observed = _hash(item["sha256"], "preflight.sha256")
    if observed != expected:
        raise _error("preflight.sha256", "Preflight snapshot hash is invalid.")
    return {
        "status": str(item["status"]),
        "sha256": observed,
        "snapshot": copy.deepcopy(item["snapshot"]),
    }


def _validate_sources(value: Any, *, require_immutable: bool) -> dict[str, Any]:
    item = _exact_record(
        value,
        "sources",
        {"template", "master", "registry", "asset_manifest"},
    )
    registry = _exact_record(
        item["registry"],
        "sources.registry",
        {"path", "file_sha256", "registry_sha256"},
    )
    result: dict[str, Any] = {
        "registry": {
            "path": _text(registry["path"], "sources.registry.path"),
            "file_sha256": _hash(
                registry["file_sha256"],
                "sources.registry.file_sha256",
            ),
            "registry_sha256": _hash(
                registry["registry_sha256"],
                "sources.registry.registry_sha256",
            ),
        },
        "asset_manifest": _path_hash(
            item["asset_manifest"],
            "sources.asset_manifest",
        ),
    }
    for name in ("template", "master"):
        source = _exact_record(
            item[name],
            f"sources.{name}",
            {"path", "before", "after"},
        )
        before = _hash(source["before"], f"sources.{name}.before")
        if source["after"] is None and not require_immutable:
            after = None
        else:
            after = _hash(source["after"], f"sources.{name}.after")
        if require_immutable and before != after:
            raise _error(f"sources.{name}", f"{name} changed during acceptance.")
        result[name] = {
            "path": _text(source["path"], f"sources.{name}.path"),
            "before": before,
            "after": after,
        }
    return result


def _cleanup_hash(path: Path) -> tuple[str | None, BaseException | None]:
    try:
        return _sha256(path), None
    except BaseException as error:  # noqa: BLE001 - report unreadable inputs
        return None, error


def _validate_build(value: Any, *, require_published: bool) -> dict[str, Any]:
    item = _exact_record(value, "build", BUILD_KEYS)
    history = item["history"]
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise _error("build.history", "Build history must be an array.")
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
        "history": [_text(entry, "build.history") for entry in history],
        "terminal_state": _text(item["terminal_state"], "build.terminal_state"),
    }
    if require_published and (
        any(
            result[name] is None
            for name in ("build_id", "plan_hash", "journal_path", "journal_sha256")
        )
        or tuple(result["history"]) != SUCCESS_HISTORY
        or result["terminal_state"] != "published"
    ):
        raise _error("build", "PASS requires complete published build evidence.")
    return result


def _validate_pass_artifacts(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "artifacts", ARTIFACT_KEYS)
    output_parts = item["output_parts"]
    metadata = item["output_metadata"]
    if (
        not isinstance(output_parts, Sequence)
        or isinstance(output_parts, (str, bytes))
        or not output_parts
    ):
        raise _error("artifacts.output_parts", "PASS requires output parts.")
    if not isinstance(metadata, Sequence) or isinstance(metadata, (str, bytes)):
        raise _error(
            "artifacts.output_metadata",
            "Output metadata must be an array.",
        )
    return {
        "project": _path_hash(item["project"], "artifacts.project"),
        "library": _path_hash(item["library"], "artifacts.library"),
        "scenario": _path_hash(item["scenario"], "artifacts.scenario"),
        "selected_output": _path_hash(
            item["selected_output"],
            "artifacts.selected_output",
        ),
        "output_parts": [
            _path_hash(entry, f"artifacts.output_parts[{index}]")
            for index, entry in enumerate(output_parts)
        ],
        "output_metadata": [
            _path_hash(entry, f"artifacts.output_metadata[{index}]")
            for index, entry in enumerate(metadata)
        ],
    }


def _validate_fail_artifacts(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "artifacts", ARTIFACT_KEYS)
    if not isinstance(item["output_parts"], Sequence) or isinstance(
        item["output_parts"],
        (str, bytes),
    ):
        raise _error("artifacts.output_parts", "FAIL output parts must be an array.")
    if not isinstance(item["output_metadata"], Sequence) or isinstance(
        item["output_metadata"],
        (str, bytes),
    ):
        raise _error("artifacts.output_metadata", "FAIL metadata must be an array.")
    return {
        **{
            name: (
                None
                if item[name] is None
                else _path_hash(item[name], f"artifacts.{name}")
            )
            for name in ("project", "library", "scenario", "selected_output")
        },
        "output_parts": [
            _path_hash(entry, f"artifacts.output_parts[{index}]")
            for index, entry in enumerate(item["output_parts"])
        ],
        "output_metadata": [
            _path_hash(entry, f"artifacts.output_metadata[{index}]")
            for index, entry in enumerate(item["output_metadata"])
        ],
    }


def _validate_acceptance(value: Any) -> dict[str, Any]:
    item = _exact_record(value, "acceptance", {"verdict", "checks", "evidence"})
    checks = _exact_record(
        item["checks"],
        "acceptance.checks",
        set(REQUIRED_CHECKS),
    )
    if item["verdict"] != "PASS" or any(
        checks[name] is not True for name in REQUIRED_CHECKS
    ):
        raise _error("acceptance", "All four native checks must pass.")
    evidence = _exact_record(
        item["evidence"],
        "acceptance.evidence",
        {
            "fault_time_s",
            "fault_duration_s",
            "current_limit_pu",
            "dc_current_peak_pu",
            "recovery_window_s",
            "channels",
        },
    )
    for field in (
        "fault_time_s",
        "fault_duration_s",
        "current_limit_pu",
        "dc_current_peak_pu",
        "recovery_window_s",
    ):
        number = evidence[field]
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
        ):
            raise _error(
                f"acceptance.evidence.{field}",
                "Numeric evidence must be finite.",
            )
    channels = _exact_record(
        evidence["channels"],
        "acceptance.evidence.channels",
        {"fault_active", "dc_current", "failure_indicator"},
    )
    normalized_channels = {}
    for name, channel_value in channels.items():
        channel = _exact_record(
            channel_value,
            f"acceptance.evidence.channels.{name}",
            {"path", "units", "samples", "domain_start_s", "domain_end_s"},
        )
        samples = channel["samples"]
        start = channel["domain_start_s"]
        end = channel["domain_end_s"]
        if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
            raise _error(
                f"acceptance.evidence.channels.{name}.samples",
                "Channel samples must be positive integer.",
            )
        if any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            for item in (start, end)
        ) or float(end) <= float(start):
            raise _error(
                f"acceptance.evidence.channels.{name}.domain",
                "Channel domain must be finite and increasing.",
            )
        normalized_channels[name] = {
            "path": _text(
                channel["path"],
                f"acceptance.evidence.channels.{name}.path",
            ),
            "units": _observed_units(
                channel["units"],
                f"acceptance.evidence.channels.{name}.units",
            ),
            "samples": samples,
            "domain_start_s": float(start),
            "domain_end_s": float(end),
        }
    normalized_evidence = dict(evidence)
    normalized_evidence["channels"] = normalized_channels
    return {
        "verdict": "PASS",
        "checks": dict(checks),
        "evidence": normalized_evidence,
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
    for name in ("backend", "version"):
        if not isinstance(item[name], str):
            raise _error(f"runtime.{name}", f"{name} must be text.")
        item[name] = item[name].strip()
    if not isinstance(item["x64"], bool):
        raise _error("runtime.x64", "x64 must be boolean.")
    if not isinstance(item["licensed"], bool):
        raise _error("runtime.licensed", "licensed must be boolean.")
    if require_licensed and (
        item["backend"] != "legacy"
        or item["version"] != "4.6.2"
        or item["x64"] is not True
    ):
        raise _error("runtime", "Runtime identity is not Legacy 4.6.2 x64.")
    if require_licensed and item["licensed"] is not True:
        raise _error("runtime.licensed", "PASS requires a licensed runtime.")
    if item["managed_pid"] is not None and (
        isinstance(item["managed_pid"], bool)
        or not isinstance(item["managed_pid"], int)
    ):
        raise _error("runtime.managed_pid", "managed_pid must be integer or null.")
    if item["quit_error"] is not None and not isinstance(
        item["quit_error"],
        str,
    ):
        raise _error("runtime.quit_error", "quit_error must be text or null.")
    if not isinstance(item["remaining_processes"], Sequence) or isinstance(
        item["remaining_processes"],
        (str, bytes),
    ):
        raise _error(
            "runtime.remaining_processes",
            "Remaining processes must be an array.",
        )
    if any(
        not isinstance(process, Mapping)
        for process in item["remaining_processes"]
    ):
        raise _error(
            "runtime.remaining_processes",
            "Process entries must be objects.",
        )
    return copy.deepcopy(item)


def _validate_failure(value: Any) -> dict[str, str]:
    item = _exact_record(value, "failure", {"stage", "code", "message"})
    return {
        name: _text(item[name], f"failure.{name}")
        for name in ("stage", "code", "message")
    }


def validate_native_lcc_acceptance_report(value: Any) -> dict[str, Any]:
    report = _exact_record(value, "report", REPORT_KEYS)
    if report["schema_version"] != 1 or isinstance(
        report["schema_version"],
        bool,
    ):
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
        raise _error("metadata", "Native report metadata is invalid.") from error
    if (
        metadata["scope"] != NATIVE_SCOPE
        or metadata["builder_path"] != NATIVE_BUILDER_PATH
        or _text(report["builder_path"], "builder_path")
        != metadata["builder_path"]
    ):
        raise _error("scope", "The report is not owned by blank/native LCC.")
    repository = _exact_record(
        report["repository"],
        "repository",
        {"branch", "commit", "clean"},
    )
    normalized_repository = {
        "branch": _text(repository["branch"], "repository.branch"),
        "commit": metadata["commit"],
        "clean": True,
    }
    if repository != normalized_repository:
        raise _error("repository", "Repository evidence is not exact and clean.")
    exclusions = report["explicit_exclusions"]
    if (
        not isinstance(exclusions, Sequence)
        or isinstance(exclusions, (str, bytes))
        or tuple(exclusions) != NATIVE_EXCLUSIONS
    ):
        raise _error("explicit_exclusions", "Native exclusions are not exact.")

    status = _text(report["status"], "status")
    if status not in {"PASS", "FAIL"}:
        raise _error("status", "Native acceptance status must be PASS or FAIL.")
    build = _validate_build(
        report["build"],
        require_published=status == "PASS",
    )
    runtime = _validate_runtime(
        report["runtime"],
        require_licensed=status == "PASS",
    )
    sources = _validate_sources(
        report["sources"],
        require_immutable=status == "PASS",
    )
    if status == "PASS":
        if metadata["capability_state"] != NATIVE_CAPABILITY:
            raise _error("capability_state", "PASS must remain simulated.")
        if (
            tuple(build["history"]) != SUCCESS_HISTORY
            or build["terminal_state"] != "published"
        ):
            raise _error("build.history", "PASS requires the exact published history.")
        artifacts = _validate_pass_artifacts(report["artifacts"])
        acceptance = _validate_acceptance(report["acceptance"])
        if (
            report["failure"] is not None
            or runtime["quit_error"] is not None
            or runtime["remaining_processes"]
        ):
            raise _error(
                "failure",
                "PASS cannot contain failure, quit error, or remaining processes.",
            )
        failure = None
    else:
        if metadata["capability_state"] != "failed":
            raise _error("capability_state", "FAIL must use failed capability state.")
        if report["acceptance"] is not None:
            raise _error("acceptance", "FAIL cannot contain PASS acceptance evidence.")
        artifacts = _validate_fail_artifacts(report["artifacts"])
        acceptance = None
        failure = _validate_failure(report["failure"])
    normalized = {
        **metadata,
        "status": status,
        "repository": normalized_repository,
        "preflight": _validate_preflight(
            report["preflight"],
            require_pass=status == "PASS",
        ),
        "sources": sources,
        "build": build,
        "artifacts": artifacts,
        "acceptance": acceptance,
        "runtime": runtime,
        "explicit_exclusions": list(NATIVE_EXCLUSIONS),
        "failure": failure,
    }
    return copy.deepcopy(normalized)


def _verify_file(path_value: str, expected_sha256: str, field: str) -> None:
    path = _regular_path(path_value, field)
    if _sha256(path) != expected_sha256:
        raise _error(field, f"{field} file/hash evidence does not match disk.")


def _verify_native_report_files(report: Mapping[str, Any]) -> None:
    sources = report["sources"]
    _verify_file(
        sources["template"]["path"],
        sources["template"]["after"],
        "sources.template",
    )
    _verify_file(
        sources["master"]["path"],
        sources["master"]["after"],
        "sources.master",
    )
    _verify_file(
        sources["registry"]["path"],
        sources["registry"]["file_sha256"],
        "sources.registry",
    )
    registry_path = _regular_path(
        sources["registry"]["path"],
        "sources.registry",
    )
    try:
        registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
        registry = parse_master_binding_registry(registry_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, BackendError) as error:
        raise _error(
            "sources.registry",
            "Registry evidence is invalid.",
        ) from error
    if registry.sha256 != sources["registry"]["registry_sha256"]:
        raise _error(
            "sources.registry.registry_sha256",
            "Registry semantic hash does not match disk.",
        )
    _verify_file(
        sources["asset_manifest"]["path"],
        sources["asset_manifest"]["sha256"],
        "sources.asset_manifest",
    )
    build = report["build"]
    _verify_file(build["journal_path"], build["journal_sha256"], "build.journal")
    artifacts = report["artifacts"]
    for name in ("project", "library", "scenario", "selected_output"):
        _verify_file(
            artifacts[name]["path"],
            artifacts[name]["sha256"],
            f"artifacts.{name}",
        )
    for group in ("output_parts", "output_metadata"):
        for index, item in enumerate(artifacts[group]):
            _verify_file(
                item["path"],
                item["sha256"],
                f"artifacts.{group}[{index}]",
            )


def load_native_lcc_acceptance_report(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    report_path = _regular_path(path, "report")
    try:
        with report_path.open("rb") as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
    except OSError as error:
        raise _error("report", "Native report could not be read.") from error
    if len(raw) > 16 * 1024 * 1024:
        raise _error("report", "Native report exceeds 16 MiB.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error("report", "Native report is not UTF-8 JSON.") from error
    normalized = validate_native_lcc_acceptance_report(payload)
    if normalized["status"] == "PASS":
        _verify_native_report_files(normalized)
    indexed = index_explicit_reports([{"path": str(report_path)}])[0]
    if indexed["sha256"] != hashlib.sha256(raw).hexdigest():
        raise _error("report", "Native report changed during validation.")
    return normalized, indexed


def _identity_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(Path(value).expanduser()))


def _validate_native_baseline_identities(
    baseline_path: Path,
    report: Mapping[str, Any],
) -> None:
    try:
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline = validate_program_baseline(baseline_payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, BackendError) as error:
        raise _error("baseline", "Program baseline is invalid.") from error
    official_sources = [
        item
        for item in baseline["sources"]
        if item["source_id"] == "official.lcc.cigre_bidirectional.project"
    ]
    if len(official_sources) != 1:
        raise _error(
            "sources.template",
            "Program baseline must name one official LCC source.",
        )
    official = official_sources[0]
    template = report["sources"]["template"]
    if (
        _identity_path(official["path"]) != _identity_path(template["path"])
        or official["sha256"] != template["after"]
    ):
        raise _error(
            "sources.template",
            "Native report does not use the baseline official LCC source.",
        )
    master = report["sources"]["master"]
    environment = baseline["environment"]
    if (
        _identity_path(environment["master_path"])
        != _identity_path(master["path"])
        or environment["master_sha256"] != master["after"]
    ):
        raise _error(
            "sources.master",
            "Native report does not use the baseline Master source.",
        )
    manifests = [
        item
        for item in baseline["assets"]
        if item["asset_id"] == "asset.lcc.fixed.manifest"
    ]
    if (
        len(manifests) != 1
        or manifests[0]["sha256"]
        != report["sources"]["asset_manifest"]["sha256"]
    ):
        raise _error(
            "sources.asset_manifest",
            "Native report does not use the baseline LCC asset manifest.",
        )
    snapshot = report["preflight"]["snapshot"]
    compiler = environment["compiler"]
    if not isinstance(snapshot, Mapping):
        raise _error("preflight", "Native preflight snapshot is invalid.")
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
            not isinstance(snapshot.get(path_field), str)
            or _identity_path(snapshot[path_field])
            != _identity_path(compiler[baseline_path_field])
            or snapshot.get(hash_field) != compiler[baseline_hash_field]
        ):
            raise _error(
                f"preflight.{path_field}",
                "Native report does not use the baseline compiler input.",
            )
    if (
        not isinstance(snapshot.get("master_path"), str)
        or _identity_path(snapshot["master_path"])
        != _identity_path(master["path"])
        or snapshot.get("master_sha256") != master["after"]
    ):
        raise _error(
            "preflight.master",
            "Native preflight does not describe the report Master source.",
        )
    read_only_sources = snapshot.get("read_only_source_hashes")
    if not isinstance(read_only_sources, Mapping) or len(read_only_sources) != 1:
        raise _error(
            "preflight.read_only_sources",
            "Native preflight must describe one official LCC source.",
        )
    source_path, source_hash = next(iter(read_only_sources.items()))
    if (
        not isinstance(source_path, str)
        or _identity_path(source_path) != _identity_path(template["path"])
        or source_hash != template["after"]
    ):
        raise _error(
            "preflight.read_only_sources",
            "Native preflight does not describe the report LCC source.",
        )


def promote_native_lcc_report(
    baseline_path: Path,
    report_path: Path,
    *,
    promotion_action: Callable[..., dict[str, Any]] = promote_program_report,
) -> dict[str, Any]:
    report, indexed = load_native_lcc_acceptance_report(report_path)
    if (
        report["status"] != "PASS"
        or indexed["capability_state"] != NATIVE_CAPABILITY
    ):
        raise _error(
            "status",
            "Only native simulated/PASS evidence can be promoted.",
        )
    _validate_native_baseline_identities(baseline_path, report)
    return promotion_action(
        baseline_path,
        report_path,
        expected_scope=NATIVE_SCOPE,
        owner_work_package=NATIVE_OWNER,
        explicit_exclusions=NATIVE_EXCLUSIONS,
        expected_report_sha256=indexed["sha256"],
        expected_repository_branch=report["repository"]["branch"],
    )


@dataclass(frozen=True)
class NativeLccAcceptanceRequest:
    repository_root: Path
    workspace_root: Path
    template_path: Path
    master_path: Path
    report_path: Path
    project_name: str
    commit: str
    branch: str
    registry_sha256: str
    registry_file_sha256: str
    asset_manifest_sha256: str
    preflight: Mapping[str, Any]
    simulation_duration_s: float = 2.5


def _artifact(path: Path) -> dict[str, str]:
    resolved = _regular_path(path, "artifact")
    return {"path": resolved.as_posix(), "sha256": _sha256(resolved)}


def _history(record: Mapping[str, Any]) -> list[str]:
    values = record.get("history")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise BackendError(
            "LCC_NATIVE_HISTORY_INVALID",
            "Native build history is not an array.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    result = []
    for item in values:
        if not isinstance(item, Mapping) or not isinstance(item.get("state"), str):
            raise BackendError(
                "LCC_NATIVE_HISTORY_INVALID",
                "Native build history entry has no state.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
        result.append(str(item["state"]))
    return result


def _journal_path(workspace: Path, build_id: str) -> Path:
    return AtomicJournal(workspace, build_id).path


def _metadata(
    request: NativeLccAcceptanceRequest,
    run_id: str,
    capability_state: str,
) -> dict[str, Any]:
    return build_run_metadata(
        run_id=run_id,
        scope=NATIVE_SCOPE,
        kind=NATIVE_KIND,
        capability_state=capability_state,
        commit=request.commit,
        generated_at_utc=(
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        ),
    )


def _source_evidence(
    request: NativeLccAcceptanceRequest,
    template_before: str,
    master_before: str,
) -> dict[str, Any]:
    asset_root = (
        request.repository_root
        / "pscad_mcp"
        / "assets"
        / "lcc"
        / "cigre_lcc_monopole_v1"
    )
    return {
        "template": {
            "path": request.template_path.resolve().as_posix(),
            "before": template_before,
            "after": template_before,
        },
        "master": {
            "path": request.master_path.resolve().as_posix(),
            "before": master_before,
            "after": master_before,
        },
        "registry": {
            "path": (
                asset_root / "master-bindings-pscad-4.6.2.json"
            ).resolve().as_posix(),
            "file_sha256": request.registry_file_sha256,
            "registry_sha256": request.registry_sha256,
        },
        "asset_manifest": {
            "path": (asset_root / "manifest.json").resolve().as_posix(),
            "sha256": request.asset_manifest_sha256,
        },
    }


def _compiler_inputs(
    request: NativeLccAcceptanceRequest,
) -> tuple[tuple[Path, str], ...]:
    snapshot = request.preflight.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise BackendError(
            "LCC_NATIVE_PREFLIGHT_FAILED",
            "Native preflight snapshot is unavailable.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    result = []
    for path_field, hash_field in (
        ("compiler_configuration", "compiler_configuration_sha256"),
        ("compiler_executable", "compiler_executable_sha256"),
    ):
        path = _regular_path(snapshot.get(path_field), f"preflight.{path_field}")
        expected = _hash(snapshot.get(hash_field), f"preflight.{hash_field}")
        if _sha256(path) != expected:
            raise BackendError(
                "LCC_NATIVE_PREFLIGHT_FAILED",
                "A compiler input changed after preflight.",
                "hvdc",
                "run_native_lcc_acceptance",
                {"field": path_field},
            )
        result.append((path, expected))
    return tuple(result)


def _initial_fail_report(
    request: NativeLccAcceptanceRequest,
    run_id: str,
    template_before: str,
    master_before: str,
) -> dict[str, Any]:
    return {
        **_metadata(request, run_id, "failed"),
        "status": "FAIL",
        "repository": {
            "branch": request.branch,
            "commit": request.commit,
            "clean": True,
        },
        "preflight": {
            "status": str(request.preflight["status"]),
            "sha256": str(request.preflight["sha256"]),
            "snapshot": copy.deepcopy(request.preflight["snapshot"]),
        },
        "sources": _source_evidence(
            request,
            template_before,
            master_before,
        ),
        "build": {
            "project_name": request.project_name,
            "workspace": request.workspace_root.resolve().as_posix(),
            "build_id": None,
            "plan_hash": None,
            "journal_path": None,
            "journal_sha256": None,
            "history": [],
            "terminal_state": "not_started",
        },
        "artifacts": {
            "project": None,
            "library": None,
            "scenario": None,
            "selected_output": None,
            "output_parts": [],
            "output_metadata": [],
        },
        "acceptance": None,
        "runtime": {
            "backend": "legacy",
            "version": "4.6.2",
            "x64": True,
            "licensed": False,
            "managed_pid": None,
            "quit_error": None,
            "remaining_processes": [],
        },
        "explicit_exclusions": list(NATIVE_EXCLUSIONS),
        "failure": {
            "stage": "not_started",
            "code": "NOT_STARTED",
            "message": "Acceptance has not completed.",
        },
    }


def _fail_report(
    request: NativeLccAcceptanceRequest,
    current: Mapping[str, Any],
    stage: str,
    error: BaseException,
) -> dict[str, Any]:
    report = copy.deepcopy(dict(current))
    report.update(_metadata(request, str(report["run_id"]), "failed"))
    report["status"] = "FAIL"
    report["acceptance"] = None
    report["failure"] = {
        "stage": stage,
        "code": error.code if isinstance(error, BackendError) else type(error).__name__,
        "message": str(error)[:1024] or type(error).__name__,
    }
    if report["build"]["terminal_state"] == "published":
        report["build"]["terminal_state"] = "failed"
    return report


def write_native_lcc_setup_failure_report(
    request: NativeLccAcceptanceRequest,
    error: BaseException,
    *,
    process_reader: Callable[[], Sequence[Mapping[str, Any]]] = (
        list_pscad_processes
    ),
) -> dict[str, Any]:
    template_before = _sha256(
        _regular_path(request.template_path, "sources.template")
    )
    master_before = _sha256(_regular_path(request.master_path, "sources.master"))
    report = _initial_fail_report(
        request,
        request.report_path.parent.name,
        template_before,
        master_before,
    )
    report = _fail_report(request, report, "setup", error)
    report["runtime"]["remaining_processes"] = [
        dict(value) for value in process_reader()
    ]
    normalized = validate_native_lcc_acceptance_report(report)
    write_preflight_report(request.report_path, normalized)
    index_explicit_reports([{"path": str(request.report_path)}])
    return normalized


def _build_evidence_from_record(
    request: NativeLccAcceptanceRequest,
    plan: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    build_id = str(record["build_id"])
    journal = _journal_path(request.workspace_root, build_id)
    return {
        "project_name": request.project_name,
        "workspace": request.workspace_root.resolve().as_posix(),
        "build_id": build_id,
        "plan_hash": str(plan["plan_hash"]),
        "journal_path": journal.resolve().as_posix() if journal.is_file() else None,
        "journal_sha256": _sha256(journal) if journal.is_file() else None,
        "history": _history(record),
        "terminal_state": str(record.get("state") or "unknown"),
    }


async def _pass_report_from_record(
    request: NativeLccAcceptanceRequest,
    plan: Mapping[str, Any],
    record: Mapping[str, Any],
    service: Any,
    template_before: str,
    master_before: str,
) -> dict[str, Any]:
    if (
        record.get("state") != "published"
        or tuple(_history(record)) != SUCCESS_HISTORY
    ):
        raise BackendError(
            "LCC_NATIVE_HISTORY_INVALID",
            "Native build did not reach the exact published history.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    result = record.get("result")
    if not isinstance(result, Mapping) or not isinstance(
        result.get("acceptance"),
        Mapping,
    ):
        raise BackendError(
            "LCC_NATIVE_RESULT_INVALID",
            "Native result is incomplete.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    acceptance = result["acceptance"]
    checks = acceptance.get("checks")
    evidence = acceptance.get("evidence")
    if (
        acceptance.get("verdict") != "PASS"
        or not isinstance(checks, Mapping)
        or not isinstance(evidence, Mapping)
    ):
        raise BackendError(
            "LCC_ACCEPTANCE_FAILED",
            "Native physical checks did not pass.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    if any(checks.get(name) is not True for name in REQUIRED_CHECKS):
        raise BackendError(
            "LCC_ACCEPTANCE_FAILED",
            "A required native check is false.",
            "hvdc",
            "run_native_lcc_acceptance",
        )

    build = _build_evidence_from_record(request, plan, record)
    selected_output = Path(str(result["output_file"]))
    raw_output_parts = result.get("output_parts")
    if not isinstance(raw_output_parts, Sequence) or isinstance(
        raw_output_parts,
        (str, bytes),
    ):
        raise BackendError(
            "LCC_NATIVE_RESULT_INVALID",
            "Native output parts are incomplete.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    output_parts = [Path(str(value)) for value in raw_output_parts]
    output_base = re.sub(r"_\d{2}$", "", selected_output.stem)
    output_metadata = [
        selected_output.with_name(output_base + suffix)
        for suffix in (".inf", ".infx")
        if selected_output.with_name(output_base + suffix).is_file()
    ]
    runtime = await service.status()
    if not isinstance(runtime, Mapping):
        raise BackendError(
            "LCC_NATIVE_RUNTIME_INVALID",
            "Native runtime status is not an object.",
            "hvdc",
            "run_native_lcc_acceptance",
        )
    session = runtime.get("session")
    managed_pid = session.get("managed_pid") if isinstance(session, Mapping) else None
    acceptance_evidence = {
        "fault_time_s": float(evidence["fault_time_s"]),
        "fault_duration_s": float(evidence["fault_duration_s"]),
        "current_limit_pu": float(evidence["current_limit_pu"]),
        "dc_current_peak_pu": float(evidence["dc_current_peak_pu"]),
        "recovery_window_s": float(evidence["recovery_window_s"]),
        "channels": copy.deepcopy(evidence["channels"]),
    }
    return {
        **_metadata(request, request.report_path.parent.name, NATIVE_CAPABILITY),
        "status": "PASS",
        "repository": {
            "branch": request.branch,
            "commit": request.commit,
            "clean": True,
        },
        "preflight": {
            "status": str(request.preflight["status"]),
            "sha256": str(request.preflight["sha256"]),
            "snapshot": copy.deepcopy(request.preflight["snapshot"]),
        },
        "sources": {
            **_source_evidence(request, template_before, master_before),
            "template": {
                "path": request.template_path.resolve().as_posix(),
                "before": template_before,
                "after": _sha256(request.template_path),
            },
            "master": {
                "path": request.master_path.resolve().as_posix(),
                "before": master_before,
                "after": _sha256(request.master_path),
            },
        },
        "build": build,
        "artifacts": {
            "project": _artifact(Path(str(record["target_path"]))),
            "library": _artifact(Path(str(result["final_library_path"]))),
            "scenario": _artifact(Path(str(result["scenario_source"]))),
            "selected_output": _artifact(selected_output),
            "output_parts": [_artifact(path) for path in output_parts],
            "output_metadata": [_artifact(path) for path in output_metadata],
        },
        "acceptance": {
            "verdict": "PASS",
            "checks": {name: True for name in REQUIRED_CHECKS},
            "evidence": acceptance_evidence,
        },
        "runtime": {
            "backend": str(runtime.get("backend")),
            "version": str(runtime.get("version")),
            "x64": runtime.get("x64") is True,
            "licensed": runtime.get("licensed") is True,
            "managed_pid": managed_pid,
            "quit_error": None,
            "remaining_processes": [],
        },
        "explicit_exclusions": list(NATIVE_EXCLUSIONS),
        "failure": None,
    }


async def run_native_lcc_acceptance(
    request: NativeLccAcceptanceRequest,
    *,
    service: Any,
    builder: Any,
    process_reader: Callable[[], Sequence[Mapping[str, Any]]] = (
        list_pscad_processes
    ),
    poll_interval_s: float = 0.25,
    timeout_s: float = 1200.0,
) -> dict[str, Any]:
    template_path = _regular_path(request.template_path, "sources.template")
    master_path = _regular_path(request.master_path, "sources.master")
    template_before = _sha256(template_path)
    master_before = _sha256(master_path)
    run_id = request.report_path.parent.name
    report = _initial_fail_report(
        request,
        run_id,
        template_before,
        master_before,
    )
    failure: BaseException | None = None
    failure_stage = "preflight"
    compiler_inputs: tuple[tuple[Path, str], ...] = ()
    try:
        if request.preflight.get("status") != "PASS":
            raise BackendError(
                "LCC_NATIVE_PREFLIGHT_FAILED",
                "Native acceptance preflight failed.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
        compiler_inputs = _compiler_inputs(request)
        failure_stage = "attach"
        await service.attach_local()
        runtime_status = await service.status()
        if not isinstance(runtime_status, Mapping):
            raise BackendError(
                "LCC_NATIVE_RUNTIME_INVALID",
                "Native runtime status is not an object.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
        runtime_session = runtime_status.get("session")
        require_acceptance_ownership(runtime_status)
        report["runtime"].update(
            {
                "backend": str(runtime_status.get("backend")),
                "version": str(runtime_status.get("version")),
                "x64": runtime_status.get("x64") is True,
                "licensed": runtime_status.get("licensed") is True,
                "managed_pid": (
                    runtime_session.get("managed_pid")
                    if isinstance(runtime_session, Mapping)
                    else None
                ),
            }
        )
        if (
            report["runtime"]["backend"] != "legacy"
            or report["runtime"]["version"] != "4.6.2"
            or report["runtime"]["x64"] is not True
        ):
            raise BackendError(
                "LCC_NATIVE_RUNTIME_INVALID",
                "Native acceptance requires Legacy PSCAD 4.6.2 x64.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
        if report["runtime"]["licensed"] is not True:
            raise BackendError(
                "NOT_LICENSED",
                "Native acceptance requires a licensed PSCAD runtime.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
        failure_stage = "plan"
        plan = builder.plan_model(
            request.project_name,
            folder=str(request.workspace_root),
            simulation_duration_s=request.simulation_duration_s,
            template_path=str(request.template_path),
        )
        failure_stage = "build"
        started = await builder.build_model(
            request.project_name,
            str(plan["plan_hash"]),
            folder=str(request.workspace_root),
            simulation_duration_s=request.simulation_duration_s,
            confirm=True,
            template_path=str(request.template_path),
        )
        build_id = str(started["build_id"])
        deadline = time.monotonic() + timeout_s
        while True:
            record = builder.get_build_status(build_id)
            if record.get("state") in {"published", "failed", "interrupted"}:
                break
            if time.monotonic() >= deadline:
                raise BackendError(
                    "LCC_BUILD_TIMED_OUT",
                    "Native acceptance timed out.",
                    "hvdc",
                    "run_native_lcc_acceptance",
                )
            await asyncio.sleep(poll_interval_s)
        report["build"] = _build_evidence_from_record(request, plan, record)
        if record.get("state") != "published":
            error = (
                record.get("error")
                if isinstance(record.get("error"), Mapping)
                else {}
            )
            raise BackendError(
                str(error.get("code") or "LCC_BUILD_FAILED"),
                str(error.get("message") or "Native LCC build failed."),
                "hvdc",
                "run_native_lcc_acceptance",
                dict(error.get("details") or {}),
            )
        failure_stage = "validate"
        report = await _pass_report_from_record(
            request,
            plan,
            record,
            service,
            template_before,
            master_before,
        )
    except BaseException as error:  # noqa: BLE001 - persist lifecycle failures
        failure = error
        report = _fail_report(request, report, failure_stage, error)
    finally:
        cleanup_error: BaseException | None = None
        try:
            await builder.shutdown(timeout_s=5.0)
        except BaseException as error:  # noqa: BLE001 - cleanup controls verdict
            cleanup_error = error
        try:
            await service.quit_pscad(confirm=True)
        except BaseException as error:  # noqa: BLE001 - cleanup controls verdict
            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            report["runtime"]["quit_error"] = str(cleanup_error)[:1024]
            if failure is None:
                failure = cleanup_error
                report = _fail_report(request, report, "cleanup", cleanup_error)
        template_after, template_error = _cleanup_hash(template_path)
        master_after, master_error = _cleanup_hash(master_path)
        report["sources"]["template"]["after"] = template_after
        report["sources"]["master"]["after"] = master_after
        try:
            report["runtime"]["remaining_processes"] = remaining_acceptance_processes(
                report["runtime"], process_reader,
            )
        except Exception as error:  # noqa: BLE001 - missing process evidence fails
            report["runtime"]["quit_error"] = str(error)[:1024]
            report = _fail_report(request, report, "cleanup", error)
        compiler_error: BaseException | None = None
        compiler_changed = False
        for path, expected in compiler_inputs:
            observed, read_error = _cleanup_hash(path)
            compiler_error = compiler_error or read_error
            compiler_changed = compiler_changed or observed != expected
        if (
            report["sources"]["template"]["before"]
            != report["sources"]["template"]["after"]
            or report["sources"]["master"]["before"]
            != report["sources"]["master"]["after"]
            or compiler_changed
            or report["runtime"]["remaining_processes"]
        ):
            report = _fail_report(
                request,
                report,
                "cleanup",
                template_error
                or master_error
                or compiler_error
                or RuntimeError("source, compiler, or process cleanup mismatch"),
            )
        try:
            normalized = validate_native_lcc_acceptance_report(report)
        except BaseException as error:  # noqa: BLE001 - persist contract failures
            report = _fail_report(request, report, "report", error)
            normalized = validate_native_lcc_acceptance_report(report)
        write_preflight_report(request.report_path, normalized)
        indexed = index_explicit_reports([{"path": str(request.report_path)}])[0]
        if (
            indexed["status"] != normalized["status"]
            or indexed["commit"] != request.commit
        ):
            raise BackendError(
                "LCC_NATIVE_REPORT_INVALID",
                "Written report did not re-index.",
                "hvdc",
                "run_native_lcc_acceptance",
            )
    return normalized


__all__ = [
    "NATIVE_BUILDER_PATH",
    "NATIVE_CAPABILITY",
    "NATIVE_EXCLUSIONS",
    "NATIVE_KIND",
    "NATIVE_OWNER",
    "NATIVE_SCOPE",
    "REQUIRED_CHECKS",
    "SUCCESS_HISTORY",
    "NativeLccAcceptanceRequest",
    "load_native_lcc_acceptance_report",
    "promote_native_lcc_report",
    "run_native_lcc_acceptance",
    "validate_native_lcc_acceptance_report",
    "write_native_lcc_setup_failure_report",
]
