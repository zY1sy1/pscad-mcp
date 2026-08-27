"""Append-only build events and atomic evidence documents."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Mapping
import uuid

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from ...core.backend.base import BackendError
from .models import BlueprintBuildState, json_safe


_BUILD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_GUARD_FILENAME = "blueprint-build.guard"
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


def _workspace_control_root(workspace_root: Path) -> Path:
    control_root = workspace_root / ".pscad-mcp"
    if control_root.is_symlink():
        raise _error("BLUEPRINT_BUILD_CONFLICT", "The blueprint control root cannot be a symbolic link.")
    if control_root.exists():
        if not control_root.is_dir() or control_root.resolve() != control_root:
            raise _error("BLUEPRINT_BUILD_CONFLICT", "The blueprint control root is not a contained directory.")
        return control_root
    try:
        control_root.mkdir()
    except FileExistsError:
        pass
    if control_root.is_symlink() or not control_root.is_dir() or control_root.resolve() != control_root:
        raise _error("BLUEPRINT_BUILD_CONFLICT", "The blueprint control root is not a contained directory.")
    return control_root


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


@contextmanager
def _workspace_guard(path: Path):
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
    descriptor = os.open(str(path), flags, 0o600)
    try:
        if os.name == "nt":
            os.ftruncate(descriptor, max(1, os.fstat(descriptor).st_size))
            while True:
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


class BuildJournal:
    def __init__(self, workspace_root: str | Path, build_id: str) -> None:
        if not isinstance(build_id, str) or _BUILD_ID.fullmatch(build_id) is None:
            raise _error("BLUEPRINT_JOURNAL_INVALID", "Build ID is not a safe identifier.", build_id=build_id)
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.build_id = build_id
        self.build_root = _workspace_control_root(self.workspace_root) / "blueprint-builds" / build_id
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


class WorkspaceBuildLease:
    """Exclusive cross-process lease for mutation in one PSCAD workspace."""

    def __init__(self, workspace_root: Path, build_id: str, token: str) -> None:
        self.workspace_root = workspace_root
        self.build_id = build_id
        self.token = token
        self.lock_path = workspace_root / ".pscad-mcp" / "blueprint-build.lock"
        self.guard_path = self.lock_path.with_name(_GUARD_FILENAME)

    @classmethod
    def acquire(cls, workspace_root: str | Path, build_id: str) -> "WorkspaceBuildLease":
        if not isinstance(build_id, str) or _BUILD_ID.fullmatch(build_id) is None:
            raise _error("BLUEPRINT_BUILD_CONFLICT", "Build lease ID is invalid.", build_id=build_id)
        root = Path(workspace_root).expanduser().resolve()
        lock_path = _workspace_control_root(root) / "blueprint-build.lock"
        token = uuid.uuid4().hex
        metadata = {
            "build_id": build_id,
            "pid": os.getpid(),
            "token": token,
            "created_at_utc": _utc_now(),
        }
        guard_path = lock_path.with_name(_GUARD_FILENAME)
        with _workspace_guard(guard_path):
            try:
                descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as error:
                try:
                    existing = json.loads(lock_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = {"build_id": "unknown"}
                raise _error(
                    "BLUEPRINT_BUILD_CONFLICT",
                    "Another blueprint build owns the workspace lease.",
                    owner_build_id=existing.get("build_id"),
                ) from error
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(_serialized(metadata) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                raise
        return cls(root, build_id, token)

    def release(self, token: str | None = None) -> bool:
        expected = self.token if token is None else token
        with _workspace_guard(self.guard_path):
            try:
                metadata = json.loads(self.lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            if metadata.get("token") != expected or metadata.get("build_id") != self.build_id:
                return False
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                return False
            return True
