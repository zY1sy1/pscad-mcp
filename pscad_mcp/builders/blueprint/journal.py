"""Append-only build events and atomic evidence documents."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
import uuid

from ...core.backend.base import BackendError
from .models import BlueprintBuildState, json_safe


_BUILD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SUCCESS_ORDER = (
    BlueprintBuildState.PLANNED,
    BlueprintBuildState.STAGING_CREATED,
    BlueprintBuildState.MUTATIONS_APPLIED,
    BlueprintBuildState.STRUCTURE_VERIFIED,
    BlueprintBuildState.SAVED,
    BlueprintBuildState.RELOADED,
    BlueprintBuildState.PARAMETERS_VERIFIED,
    BlueprintBuildState.COMPILED,
    BlueprintBuildState.SIMULATED,
    BlueprintBuildState.ACCEPTANCE_PASSED,
    BlueprintBuildState.PUBLISHED,
)
_EXCEPTION_STATES = {
    BlueprintBuildState.REJECTED,
    BlueprintBuildState.FAILED,
    BlueprintBuildState.TIMED_OUT,
    BlueprintBuildState.INTERRUPTED,
    BlueprintBuildState.QUARANTINED,
}


def _error(code: str, message: str, **details: Any) -> BackendError:
    return BackendError(code, message, "blueprint", "blueprint_journal", details)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _serialized(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(json_safe(value), ensure_ascii=True, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise _error("BLUEPRINT_JOURNAL_INVALID", "Journal evidence must contain finite JSON values.") from error


def next_state(current: BlueprintBuildState, proposed: BlueprintBuildState) -> BlueprintBuildState:
    if not isinstance(current, BlueprintBuildState) or not isinstance(proposed, BlueprintBuildState):
        raise _error("BLUEPRINT_STATE_INVALID", "Build states must use BlueprintBuildState values.")
    allowed = False
    if current in _SUCCESS_ORDER:
        index = _SUCCESS_ORDER.index(current)
        allowed = index + 1 < len(_SUCCESS_ORDER) and (
            _SUCCESS_ORDER[index + 1] is proposed or proposed in _EXCEPTION_STATES
        )
    elif current in {BlueprintBuildState.FAILED, BlueprintBuildState.TIMED_OUT, BlueprintBuildState.INTERRUPTED}:
        allowed = proposed is BlueprintBuildState.QUARANTINED
    if not allowed:
        raise _error(
            "BLUEPRINT_STATE_INVALID",
            "The requested blueprint build transition is not permitted.",
            current=current.value,
            proposed=proposed.value,
        )
    return proposed


def write_json_atomic(path: str | Path, value: Mapping[str, Any]) -> Path:
    destination = Path(path)
    payload = _serialized(value) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.pending")
    try:
        with pending.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, destination)
    finally:
        try:
            pending.unlink()
        except FileNotFoundError:
            pass
    return destination


class BuildJournal:
    def __init__(self, workspace_root: str | Path, build_id: str) -> None:
        if not isinstance(build_id, str) or _BUILD_ID.fullmatch(build_id) is None:
            raise _error("BLUEPRINT_JOURNAL_INVALID", "Build ID is not a safe identifier.", build_id=build_id)
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.build_id = build_id
        self.build_root = self.workspace_root / ".pscad-mcp" / "blueprint-builds" / build_id
        self.path = self.build_root / "journal.jsonl"

    def append(self, event: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(event, str) or not event or not isinstance(payload, Mapping):
            raise _error("BLUEPRINT_JOURNAL_INVALID", "Journal events require a name and object payload.")
        record = {
            "timestamp_utc": _utc_now(),
            "build_id": self.build_id,
            "event": event,
            **dict(payload),
        }
        line = _serialized(record) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        return json.loads(line)
