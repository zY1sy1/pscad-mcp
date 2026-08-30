"""Strict durable evidence contract for blank/native LCC acceptance."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ....acceptance.evidence import build_run_metadata, index_explicit_reports
from ....acceptance.promotion import promote_program_report
from ....core.backend.base import BackendError
from ....core.master_bindings import parse_master_binding_registry

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
        after = _hash(source["after"], f"sources.{name}.after")
        if require_immutable and before != after:
            raise _error(f"sources.{name}", f"{name} changed during acceptance.")
        result[name] = {
            "path": _text(source["path"], f"sources.{name}.path"),
            "before": before,
            "after": after,
        }
    return result


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
            "units": _text(
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
    if (
        item["backend"] != "legacy"
        or item["version"] != "4.6.2"
        or item["x64"] is not True
    ):
        raise _error("runtime", "Runtime identity is not Legacy 4.6.2 x64.")
    if not isinstance(item["licensed"], bool):
        raise _error("runtime.licensed", "licensed must be boolean.")
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
    return promotion_action(
        baseline_path,
        report_path,
        expected_scope=NATIVE_SCOPE,
        owner_work_package=NATIVE_OWNER,
        explicit_exclusions=NATIVE_EXCLUSIONS,
        expected_report_sha256=indexed["sha256"],
    )


__all__ = [
    "NATIVE_BUILDER_PATH",
    "NATIVE_CAPABILITY",
    "NATIVE_EXCLUSIONS",
    "NATIVE_KIND",
    "NATIVE_OWNER",
    "NATIVE_SCOPE",
    "REQUIRED_CHECKS",
    "SUCCESS_HISTORY",
    "load_native_lcc_acceptance_report",
    "promote_native_lcc_report",
    "validate_native_lcc_acceptance_report",
]
