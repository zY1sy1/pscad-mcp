"""Index only caller-declared acceptance reports as regular files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..core.backend.base import BackendError
from .baseline import (
    CAPABILITY_STATES,
    LICENSED_STATUSES,
    PROGRAM_SCOPES,
    SCOPE_BUILDER_PATHS,
    is_utc_timestamp,
)

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MAX_REPORT_BYTES = 16 * 1024 * 1024


def _error(reason: str, message: str, **details: Any) -> BackendError:
    return BackendError(
        "PROGRAM_EVIDENCE_INVALID",
        message,
        "acceptance",
        "index_program_evidence",
        {"reason": reason, **details},
    )


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _is_reparse_point(value: os.stat_result) -> bool:
    attributes = int(getattr(value, "st_file_attributes", 0))
    marker = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(value.st_mode) or bool(attributes & marker)


def _read_regular_report(path: Path) -> tuple[Path, bytes, tuple[int, int, int, int]]:
    absolute = Path(os.path.abspath(path))
    for component in [*reversed(absolute.parents), absolute]:
        try:
            component_stat = os.lstat(component)
        except OSError as error:
            raise _error(
                "not_regular_file",
                "Evidence path must be a regular file.",
                path=str(absolute),
            ) from error
        if _is_reparse_point(component_stat):
            raise _error(
                "reparse_path_component",
                "Evidence path cannot contain symlink or reparse components.",
                path=str(absolute),
                component=str(component),
            )
    try:
        with absolute.open("rb") as stream:
            opened_stat = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened_stat.st_mode):
                raise _error(
                    "not_regular_file",
                    "Evidence path must be a regular file.",
                    path=str(absolute),
                )
            raw = stream.read(_MAX_REPORT_BYTES + 1)
    except BackendError:
        raise
    except OSError as error:
        raise _error(
            "not_regular_file",
            "Evidence path must be a readable regular file.",
            path=str(absolute),
        ) from error
    if len(raw) > _MAX_REPORT_BYTES:
        raise _error(
            "report_too_large",
            "Evidence report exceeds the bounded size limit.",
            path=str(absolute),
            max_bytes=_MAX_REPORT_BYTES,
        )
    return absolute.resolve(strict=True), raw, _identity(opened_stat)


def _require_unchanged(
    path: Path,
    identity: tuple[int, int, int, int],
    expected: bytes,
) -> None:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise _error(
            "evidence_changed",
            "Evidence path changed while it was being indexed.",
            path=str(path),
        ) from error
    if _is_reparse_point(current) or _identity(current) != identity:
        raise _error(
            "evidence_changed",
            "Evidence path changed while it was being indexed.",
            path=str(path),
        )
    try:
        with path.open("rb") as stream:
            observed = stream.read(_MAX_REPORT_BYTES + 1)
    except OSError as error:
        raise _error(
            "evidence_changed",
            "Evidence path changed while it was being indexed.",
            path=str(path),
        ) from error
    if observed != expected:
        raise _error(
            "evidence_changed",
            "Evidence path changed while it was being indexed.",
            path=str(path),
        )


def _kind_matches_state(kind: str, state: str) -> bool:
    required_kind = {
        "compiled": "licensed_compile",
        "simulated": "licensed_simulation",
        "accepted": "licensed_acceptance",
    }.get(state)
    return required_kind is None or kind == required_kind


def _owned_text(payload: Mapping[str, Any], field: str, path: Path) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _error(
            "missing_report_metadata",
            f"Evidence report must own non-empty {field}.",
            field=field,
            path=str(path),
        )
    return value.strip()


def build_run_metadata(
    *,
    run_id: str,
    scope: str,
    kind: str,
    capability_state: str,
    commit: str,
    generated_at_utc: str,
) -> dict[str, Any]:
    if not isinstance(scope, str) or scope not in PROGRAM_SCOPES:
        raise _error("unknown_scope", "Run metadata scope is unknown.", scope=scope)
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (run_id, kind, capability_state, generated_at_utc)
    ):
        raise _error(
            "missing_report_metadata",
            "Run metadata text is required.",
        )
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise _error(
            "invalid_durable_commit",
            "Run metadata requires a full commit.",
        )
    if not is_utc_timestamp(generated_at_utc):
        raise _error(
            "invalid_timestamp",
            "Run metadata requires a UTC RFC3339 timestamp.",
        )
    if capability_state not in CAPABILITY_STATES:
        raise _error(
            "unknown_state",
            "Run metadata capability state is invalid.",
        )
    if not _kind_matches_state(kind.strip(), capability_state):
        raise _error(
            "kind_state_mismatch",
            "Run metadata kind and state differ.",
        )
    return {
        "schema_version": 1,
        "run_id": run_id.strip(),
        "scope": scope,
        "builder_path": SCOPE_BUILDER_PATHS[scope],
        "kind": kind.strip(),
        "capability_state": capability_state,
        "commit": commit,
        "generated_at_utc": generated_at_utc.strip(),
    }


def index_explicit_reports(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(
        values, (str, bytes, bytearray)
    ):
        raise _error("not_array", "Evidence descriptors must be an array.")
    result = []
    run_ids = set()
    for index, descriptor in enumerate(values):
        if not isinstance(descriptor, Mapping):
            raise _error(
                "not_object",
                "Evidence descriptor must be an object.",
                index=index,
            )
        if set(descriptor) != {"path"}:
            raise _error(
                "field_set",
                "Evidence descriptor fields are invalid.",
                index=index,
            )
        path = Path(str(descriptor["path"])).expanduser()
        resolved, raw, opened_identity = _read_regular_report(path)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _error(
                "invalid_json",
                "Evidence report must be UTF-8 JSON.",
                path=str(resolved),
            ) from error
        _require_unchanged(resolved, opened_identity, raw)
        if not isinstance(payload, Mapping):
            raise _error(
                "not_object",
                "Evidence report root must be an object.",
                path=str(resolved),
            )
        if payload.get("schema_version") != 1 or isinstance(
            payload.get("schema_version"), bool
        ):
            raise _error(
                "unsupported_schema",
                "Evidence report schema_version must be 1.",
                path=str(resolved),
            )
        run_id = _owned_text(payload, "run_id", resolved)
        if run_id in run_ids:
            raise _error(
                "duplicate_run_id",
                "run_id must be unique.",
                run_id=run_id,
            )
        run_ids.add(run_id)
        scope = _owned_text(payload, "scope", resolved)
        if scope not in PROGRAM_SCOPES:
            raise _error(
                "unknown_scope",
                "Evidence scope is unknown.",
                scope=scope,
            )
        builder_path = _owned_text(payload, "builder_path", resolved)
        if builder_path != SCOPE_BUILDER_PATHS[scope]:
            raise _error(
                "builder_path_mismatch",
                "Evidence builder_path does not own its scope.",
                scope=scope,
                builder_path=builder_path,
            )
        kind = _owned_text(payload, "kind", resolved)
        capability_state = _owned_text(payload, "capability_state", resolved)
        if capability_state not in CAPABILITY_STATES:
            raise _error(
                "unknown_state",
                "Evidence report capability state is invalid.",
                path=str(resolved),
            )
        if not _kind_matches_state(kind, capability_state):
            raise _error(
                "kind_state_mismatch",
                "Evidence report kind and capability state differ.",
                path=str(resolved),
            )
        generated_at_utc = _owned_text(payload, "generated_at_utc", resolved)
        if not is_utc_timestamp(generated_at_utc):
            raise _error(
                "invalid_timestamp",
                "Evidence report timestamp must be UTC RFC3339.",
                path=str(resolved),
            )
        status = payload.get("status")
        if status not in LICENSED_STATUSES:
            raise _error(
                "unknown_status",
                "Evidence report status is invalid.",
                path=str(resolved),
            )
        report_commit = payload.get("commit")
        if report_commit is None:
            raise _error(
                "missing_durable_commit",
                "Evidence without a report-owned commit is historical only.",
                path=str(resolved),
            )
        if (
            not isinstance(report_commit, str)
            or _COMMIT.fullmatch(report_commit) is None
        ):
            raise _error(
                "invalid_durable_commit",
                "Evidence report commit must be a full lowercase git identity.",
                path=str(resolved),
            )
        result.append(
            {
                "run_id": run_id,
                "scope": scope,
                "builder_path": builder_path,
                "kind": kind,
                "capability_state": capability_state,
                "status": str(status),
                "commit": report_commit,
                "generated_at_utc": generated_at_utc,
                "path": resolved.as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "availability": "verified_local",
            }
        )
    return result
