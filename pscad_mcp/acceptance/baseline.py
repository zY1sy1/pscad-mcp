"""Strict current-truth baseline for LCC/MMC implementation scopes."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from ..core.backend.base import BackendError

PROGRAM_SCOPES = frozenset(
    {
        "lcc.master_bindings",
        "lcc.blank_native",
        "lcc.fixed_autonomous",
        "lcc.parametric",
        "mmc.blank_native_full_bridge",
        "mmc.detailed_pwm_full_bridge",
        "mmc.avm_full_bridge",
        "mmc.avm_half_bridge",
        "mmc.parametric",
    }
)
SCOPE_BUILDER_PATHS = {
    "lcc.master_bindings": "lcc.master_binding_registry",
    "lcc.blank_native": "lcc.blank_native",
    "lcc.fixed_autonomous": "lcc.fixed_autonomous",
    "lcc.parametric": "lcc.parametric",
    "mmc.blank_native_full_bridge": "mmc.blank_native_full_bridge",
    "mmc.detailed_pwm_full_bridge": "mmc.detailed_pwm_full_bridge",
    "mmc.avm_full_bridge": "mmc.avm_full_bridge",
    "mmc.avm_half_bridge": "mmc.avm_half_bridge",
    "mmc.parametric": "mmc.parametric_orchestrator",
}
CAPABILITY_STATES = frozenset(
    {
        "inspected",
        "planned",
        "built",
        "compiled",
        "simulated",
        "accepted",
        "INCOMPLETE_ANALYSIS",
        "failed",
    }
)
LICENSED_STATUSES = frozenset(
    {"PASS", "FAIL", "INCOMPLETE_ANALYSIS", "NOT_RUN_ON_CURRENT_COMMIT"}
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TOP = {
    "schema_version",
    "baseline_id",
    "generated_at_utc",
    "repository",
    "environment",
    "sources",
    "assets",
    "reports",
    "scopes",
}
_REPOSITORY = {"base_commit", "branch", "worktree_clean"}
_ENVIRONMENT = {
    "backend",
    "pscad_version",
    "x64",
    "automation_module",
    "master_path",
    "master_sha256",
    "compiler",
}
_COMPILER = {
    "identity",
    "configuration_path",
    "configuration_sha256",
    "executable_path",
    "executable_sha256",
}
_SOURCE = {"source_id", "kind", "path", "sha256", "availability"}
_ASSET = {"asset_id", "scope", "path", "sha256"}
_REPORT = {
    "run_id",
    "scope",
    "builder_path",
    "kind",
    "capability_state",
    "status",
    "commit",
    "generated_at_utc",
    "path",
    "sha256",
    "availability",
}
_SCOPE = {
    "scope",
    "builder_path",
    "owner_work_package",
    "capability_state",
    "licensed_status",
    "evidence_run_id",
    "explicit_exclusions",
}


def _error(field: str, reason: str, message: str) -> BackendError:
    return BackendError(
        "PROGRAM_BASELINE_INVALID",
        message,
        "acceptance",
        "validate_program_baseline",
        {"field": field, "reason": reason},
    )


def _record(value: Any, field: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(field, "not_object", f"{field} must be an object.")
    unknown = sorted(set(value) - keys)
    missing = sorted(keys - set(value))
    if unknown or missing:
        failure = _error(
            field,
            "field_set",
            f"{field} has an invalid field set.",
        )
        failure.details.update({"unknown": unknown, "missing": missing})
        raise failure
    return dict(value)


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise _error(field, "not_array", f"{field} must be an array.")
    return list(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(field, "not_text", f"{field} must be non-empty text.")
    return value.strip()


def _sha(value: Any, field: str) -> str:
    text = _text(value, field)
    if _SHA256.fullmatch(text) is None:
        raise _error(field, "not_sha256", f"{field} must be lowercase SHA-256.")
    return text


def _commit(value: Any, field: str) -> str:
    text = _text(value, field)
    if _COMMIT.fullmatch(text) is None:
        raise _error(field, "not_commit", f"{field} must be a full git commit.")
    return text


def _kind_matches_state(kind: str, state: str) -> bool:
    required_kind = {
        "compiled": "licensed_compile",
        "simulated": "licensed_simulation",
        "accepted": "licensed_acceptance",
    }.get(state)
    return required_kind is None or kind == required_kind


def _validate_repository(value: Any) -> dict[str, Any]:
    repository = _record(value, "repository", _REPOSITORY)
    repository["base_commit"] = _commit(
        repository["base_commit"], "repository.base_commit"
    )
    repository["branch"] = _text(repository["branch"], "repository.branch")
    if not isinstance(repository["worktree_clean"], bool):
        raise _error(
            "repository.worktree_clean",
            "not_boolean",
            "worktree_clean must be boolean.",
        )
    return repository


def _validate_environment(value: Any) -> dict[str, Any]:
    environment = _record(value, "environment", _ENVIRONMENT)
    environment["backend"] = _text(
        environment["backend"], "environment.backend"
    )
    environment["pscad_version"] = _text(
        environment["pscad_version"], "environment.pscad_version"
    )
    if (
        environment["backend"] != "legacy"
        or environment["pscad_version"] != "4.6.2"
    ):
        raise _error(
            "environment",
            "unsupported_runtime",
            "WP0 requires Legacy PSCAD 4.6.2.",
        )
    if not isinstance(environment["x64"], bool):
        raise _error(
            "environment.x64",
            "not_boolean",
            "x64 must be boolean.",
        )
    environment["automation_module"] = _text(
        environment["automation_module"], "environment.automation_module"
    )
    environment["master_path"] = _text(
        environment["master_path"], "environment.master_path"
    )
    environment["master_sha256"] = _sha(
        environment["master_sha256"], "environment.master_sha256"
    )
    compiler = _record(environment["compiler"], "environment.compiler", _COMPILER)
    compiler["identity"] = _text(
        compiler["identity"], "environment.compiler.identity"
    )
    compiler["configuration_path"] = _text(
        compiler["configuration_path"],
        "environment.compiler.configuration_path",
    )
    compiler["configuration_sha256"] = _sha(
        compiler["configuration_sha256"],
        "environment.compiler.configuration_sha256",
    )
    compiler["executable_path"] = _text(
        compiler["executable_path"], "environment.compiler.executable_path"
    )
    compiler["executable_sha256"] = _sha(
        compiler["executable_sha256"],
        "environment.compiler.executable_sha256",
    )
    environment["compiler"] = compiler
    return environment


def _validate_sources(value: Any) -> list[dict[str, Any]]:
    sources = []
    source_ids = set()
    for index, raw in enumerate(_array(value, "sources")):
        field = f"sources[{index}]"
        item = _record(raw, field, _SOURCE)
        item["source_id"] = _text(item["source_id"], f"{field}.source_id")
        if item["source_id"] in source_ids:
            raise _error(field, "duplicate_source_id", "source_id must be unique.")
        source_ids.add(item["source_id"])
        item["kind"] = _text(item["kind"], f"{field}.kind")
        item["path"] = _text(item["path"], f"{field}.path")
        item["sha256"] = _sha(item["sha256"], f"{field}.sha256")
        item["availability"] = _text(
            item["availability"], f"{field}.availability"
        )
        sources.append(item)
    return sources


def _validate_assets(value: Any) -> list[dict[str, Any]]:
    assets = []
    asset_ids = set()
    for index, raw in enumerate(_array(value, "assets")):
        field = f"assets[{index}]"
        item = _record(raw, field, _ASSET)
        item["asset_id"] = _text(item["asset_id"], f"{field}.asset_id")
        if item["asset_id"] in asset_ids:
            raise _error(field, "duplicate_asset_id", "asset_id must be unique.")
        asset_ids.add(item["asset_id"])
        item["scope"] = _text(item["scope"], f"{field}.scope")
        if item["scope"] not in PROGRAM_SCOPES:
            raise _error(f"{field}.scope", "unknown_scope", "Asset scope is unknown.")
        item["path"] = _text(item["path"], f"{field}.path")
        item["sha256"] = _sha(item["sha256"], f"{field}.sha256")
        assets.append(item)
    return assets


def _validate_reports(
    value: Any,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    reports = []
    reports_by_id = {}
    for index, raw in enumerate(_array(value, "reports")):
        field = f"reports[{index}]"
        item = _record(raw, field, _REPORT)
        item["run_id"] = _text(item["run_id"], f"{field}.run_id")
        if item["run_id"] in reports_by_id:
            raise _error(field, "duplicate_run_id", "run_id must be unique.")
        item["scope"] = _text(item["scope"], f"{field}.scope")
        if item["scope"] not in PROGRAM_SCOPES:
            raise _error(f"{field}.scope", "unknown_scope", "Report scope is unknown.")
        item["builder_path"] = _text(
            item["builder_path"], f"{field}.builder_path"
        )
        if item["builder_path"] != SCOPE_BUILDER_PATHS[item["scope"]]:
            raise _error(
                f"{field}.builder_path",
                "builder_path_mismatch",
                "Report builder_path does not own its scope.",
            )
        item["kind"] = _text(item["kind"], f"{field}.kind")
        item["capability_state"] = _text(
            item["capability_state"], f"{field}.capability_state"
        )
        if item["capability_state"] not in CAPABILITY_STATES:
            raise _error(
                f"{field}.capability_state",
                "unknown_state",
                "Report capability state is invalid.",
            )
        if not _kind_matches_state(item["kind"], item["capability_state"]):
            raise _error(
                field,
                "kind_state_mismatch",
                "Report kind and capability state are inconsistent.",
            )
        item["status"] = _text(item["status"], f"{field}.status")
        if item["status"] not in LICENSED_STATUSES:
            raise _error(
                f"{field}.status",
                "unknown_status",
                "Report status is invalid.",
            )
        item["commit"] = _commit(item["commit"], f"{field}.commit")
        item["generated_at_utc"] = _text(
            item["generated_at_utc"], f"{field}.generated_at_utc"
        )
        item["path"] = _text(item["path"], f"{field}.path")
        item["sha256"] = _sha(item["sha256"], f"{field}.sha256")
        item["availability"] = _text(
            item["availability"], f"{field}.availability"
        )
        reports_by_id[item["run_id"]] = item
        reports.append(item)
    return reports, reports_by_id


def _validate_scopes(
    value: Any,
    *,
    base_commit: str,
    reports_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    scopes = []
    scope_names = set()
    for index, raw in enumerate(_array(value, "scopes")):
        field = f"scopes[{index}]"
        item = _record(raw, field, _SCOPE)
        item["scope"] = _text(item["scope"], f"{field}.scope")
        if item["scope"] not in PROGRAM_SCOPES or item["scope"] in scope_names:
            reason = (
                "duplicate_scope" if item["scope"] in scope_names else "unknown_scope"
            )
            raise _error(
                f"{field}.scope",
                reason,
                "Scope must be known and unique.",
            )
        scope_names.add(item["scope"])
        item["builder_path"] = _text(
            item["builder_path"], f"{field}.builder_path"
        )
        if item["builder_path"] != SCOPE_BUILDER_PATHS[item["scope"]]:
            raise _error(
                f"{field}.builder_path",
                "builder_path_mismatch",
                "Scope builder_path is invalid.",
            )
        item["owner_work_package"] = _text(
            item["owner_work_package"], f"{field}.owner_work_package"
        )
        item["capability_state"] = _text(
            item["capability_state"], f"{field}.capability_state"
        )
        item["licensed_status"] = _text(
            item["licensed_status"], f"{field}.licensed_status"
        )
        if item["capability_state"] not in CAPABILITY_STATES:
            raise _error(
                f"{field}.capability_state",
                "unknown_state",
                "Capability state is invalid.",
            )
        if item["licensed_status"] not in LICENSED_STATUSES:
            raise _error(
                f"{field}.licensed_status",
                "unknown_status",
                "Licensed status is invalid.",
            )
        evidence_run_id = item["evidence_run_id"]
        if evidence_run_id is not None:
            evidence_run_id = _text(evidence_run_id, f"{field}.evidence_run_id")
        item["evidence_run_id"] = evidence_run_id
        item["explicit_exclusions"] = [
            _text(entry, f"{field}.explicit_exclusions")
            for entry in _array(
                item["explicit_exclusions"], f"{field}.explicit_exclusions"
            )
        ]
        if item["licensed_status"] == "PASS":
            report = reports_by_id.get(str(evidence_run_id))
            if (
                report is None
                or report["status"] != "PASS"
                or report["scope"] != item["scope"]
                or report["builder_path"] != item["builder_path"]
                or report["capability_state"] != item["capability_state"]
            ):
                raise _error(
                    field,
                    "pass_evidence_mismatch",
                    "PASS requires same-scope and same-builder PASS evidence.",
                )
            if report["commit"] != base_commit:
                raise _error(
                    field,
                    "pass_commit_mismatch",
                    "PASS evidence commit must match base_commit.",
                )
            if report["availability"] != "verified_local":
                raise _error(
                    field,
                    "pass_evidence_not_durable",
                    "PASS evidence must be a locally verified durable report.",
                )
        scopes.append(item)
    return scopes


def validate_program_baseline(value: Any) -> dict[str, Any]:
    top = _record(value, "baseline", _TOP)
    if top["schema_version"] != 1 or isinstance(top["schema_version"], bool):
        raise _error(
            "schema_version",
            "unsupported",
            "schema_version must be 1.",
        )
    repository = _validate_repository(top["repository"])
    environment = _validate_environment(top["environment"])
    sources = _validate_sources(top["sources"])
    assets = _validate_assets(top["assets"])
    reports, reports_by_id = _validate_reports(top["reports"])
    scopes = _validate_scopes(
        top["scopes"],
        base_commit=repository["base_commit"],
        reports_by_id=reports_by_id,
    )
    normalized = {
        "schema_version": 1,
        "baseline_id": _text(top["baseline_id"], "baseline_id"),
        "generated_at_utc": _text(top["generated_at_utc"], "generated_at_utc"),
        "repository": repository,
        "environment": environment,
        "sources": sources,
        "assets": assets,
        "reports": reports,
        "scopes": scopes,
    }
    return copy.deepcopy(normalized)


def canonical_program_baseline(value: Any) -> bytes:
    normalized = validate_program_baseline(value)
    return json.dumps(
        normalized,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def program_baseline_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_program_baseline(value)).hexdigest()


def apply_scope_report(
    baseline: Any,
    report: Mapping[str, Any],
    *,
    owner_work_package: str,
) -> dict[str, Any]:
    current = validate_program_baseline(baseline)
    candidate = _record(report, "report", _REPORT)
    scope_name = _text(candidate["scope"], "report.scope")
    builder_path = _text(candidate["builder_path"], "report.builder_path")
    if (
        scope_name not in SCOPE_BUILDER_PATHS
        or builder_path != SCOPE_BUILDER_PATHS[scope_name]
    ):
        raise BackendError(
            "PROGRAM_SCOPE_CONFLICT",
            "The report builder_path does not own the requested scope.",
            "acceptance",
            "apply_scope_report",
            {"reason": "builder_path_mismatch", "scope": scope_name},
        )
    commit = _commit(candidate["commit"], "report.commit")
    if commit != current["repository"]["base_commit"]:
        raise BackendError(
            "PROGRAM_SCOPE_CONFLICT",
            "Historical evidence cannot update current program truth.",
            "acceptance",
            "apply_scope_report",
            {"reason": "historical_commit", "scope": scope_name},
        )
    matching = [item for item in current["scopes"] if item["scope"] == scope_name]
    if (
        len(matching) != 1
        or matching[0]["owner_work_package"] != owner_work_package
    ):
        raise BackendError(
            "PROGRAM_SCOPE_CONFLICT",
            "The report does not belong to the requested work package scope.",
            "acceptance",
            "apply_scope_report",
            {"reason": "scope_owner_mismatch", "scope": scope_name},
        )
    status = _text(candidate["status"], "report.status")
    if status not in LICENSED_STATUSES:
        raise _error(
            "report.status",
            "unknown_status",
            "Report status is invalid.",
        )
    run_id = _text(candidate["run_id"], "report.run_id")
    previous = next(
        (item for item in current["reports"] if item["run_id"] == run_id),
        None,
    )
    if previous is not None and previous != candidate:
        raise BackendError(
            "PROGRAM_SCOPE_CONFLICT",
            "A run_id cannot be reused for different evidence.",
            "acceptance",
            "apply_scope_report",
            {"reason": "run_id_reuse", "run_id": run_id},
        )
    reports = [item for item in current["reports"] if item["run_id"] != run_id]
    reports.append(dict(candidate))
    scope = matching[0]
    scope["licensed_status"] = status
    scope["evidence_run_id"] = run_id
    scope["capability_state"] = _text(
        candidate["capability_state"],
        "report.capability_state",
    )
    updated = dict(current)
    updated["reports"] = reports
    updated["scopes"] = current["scopes"]
    return validate_program_baseline(updated)
