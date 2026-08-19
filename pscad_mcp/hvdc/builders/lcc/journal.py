"""Atomic journal persistence and workspace leases for LCC builds."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import psutil

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from ....core.backend.base import BackendError

_JOURNAL_OPERATION = "write_lcc_journal"
_LEASE_OPERATION = "acquire_lcc_build_lease"
_GUARD_FILENAME = "lcc-build.guard"
_BUILD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _journal_invalid(message: str, **details: Any) -> BackendError:
    return BackendError("LCC_JOURNAL_INVALID", message, "hvdc", _JOURNAL_OPERATION, details)


def _build_conflict(message: str, **details: Any) -> BackendError:
    return BackendError("LCC_BUILD_CONFLICT", message, "hvdc", _LEASE_OPERATION, details)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_build_id(build_id: Any) -> str:
    if not isinstance(build_id, str) or _BUILD_ID_RE.fullmatch(build_id) is None:
        raise _journal_invalid(
            "The LCC build_id must be a simple workspace-safe identifier.",
            build_id=build_id,
        )
    return build_id


def _json_safe(value: Any, path: str = "payload") -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict(), path)
    if isinstance(value, Enum):
        return _json_safe(value.value, path)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _journal_invalid(f"{path} must be a finite number.", field=path)
        return value
    if isinstance(value, (Path, BaseException)):
        raise _journal_invalid(f"{path} is not JSON-safe: {type(value).__name__}", field=path, type=type(value).__name__)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _journal_invalid(f"{path} contains a non-string mapping key.", field=path, key_type=type(key).__name__)
            result[key] = _json_safe(item, f"{path}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise _journal_invalid(f"{path} is not JSON-safe: {type(value).__name__}", field=path, type=type(value).__name__)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    safe_payload = _json_safe(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent) as stream:
            temp_path = Path(stream.name)
            json.dump(safe_payload, stream, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        return path
    except BackendError:
        raise
    except (TypeError, ValueError) as error:
        raise _journal_invalid(f"Journal payload could not be serialized: {error}") from error
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


class AtomicJournal:
    """Write JSON journals using same-directory atomic replacement."""

    def __init__(self, workspace_root: str | Path, build_id: str) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.build_id = _validate_build_id(build_id)
        self.path = self.workspace_root / ".pscad-mcp" / "lcc-builds" / self.build_id / "journal.json"

    def write(self, payload: Mapping[str, Any]) -> Path:
        return _atomic_write_json(self.path, payload)


@contextmanager
def _workspace_guard(path: Path):
    """Serialize lease transitions with an OS-level advisory file lock."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
    fd = os.open(str(path), flags, 0o600)
    try:
        if os.name == "nt":
            os.ftruncate(fd, max(1, os.fstat(fd).st_size))
            while True:
                os.lseek(fd, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _remove_matching_lock(lock_path: Path, expected_token: str) -> bool:
    """Remove only the lock file whose token was verified by the caller.

    Renaming to a same-directory temporary name closes the path-based delete
    race: a replacement that is already visible at ``lock_path`` is moved to
    the tombstone and rejected by token, while a replacement created after the
    rename remains at the original path.
    """

    tombstone = lock_path.with_name(f".{lock_path.name}.{uuid.uuid4().hex}.pending")
    try:
        os.replace(lock_path, tombstone)
    except FileNotFoundError:
        return False
    except OSError:
        return False

    matched = False
    try:
        try:
            metadata = _read_lock_metadata(tombstone)
        except (OSError, BackendError, json.JSONDecodeError):
            return False
        matched = metadata["token"] == expected_token
        return matched
    finally:
        if matched:
            try:
                tombstone.unlink()
            except FileNotFoundError:
                pass
        else:
            _restore_without_overwrite(tombstone, lock_path)


def _restore_without_overwrite(tombstone: Path, lock_path: Path) -> bool:
    """Restore a rejected candidate without replacing a newer lock.

    ``os.replace`` overwrites an existing destination on Windows. A same-volume
    hard-link creation is the portable standard-library primitive that fails
    when the destination already exists; the source is removed only after the
    link succeeds. If hard links are unavailable, leave the tombstone in place
    rather than risking a new-owner overwrite.
    """

    try:
        os.link(tombstone, lock_path)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        tombstone.unlink()
    except FileNotFoundError:
        pass
    return True


class WorkspaceBuildLease:
    """Cross-process build lease backed by an exclusive lock file."""

    def __init__(self, workspace_root: str | Path, build_id: str, token: str, journal_path: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.build_id = _validate_build_id(build_id)
        self.token = token
        self.journal_path = Path(journal_path)
        self.lock_path = self.workspace_root / ".pscad-mcp" / "lcc-build.lock"
        self.guard_path = self.lock_path.with_name(_GUARD_FILENAME)

    @classmethod
    def acquire(cls, workspace_root: str | Path, build_id: str) -> "WorkspaceBuildLease":
        root = Path(workspace_root).expanduser().resolve()
        lock_path = root / ".pscad-mcp" / "lcc-build.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path = AtomicJournal(root, build_id).path
        token = uuid.uuid4().hex
        metadata = {
            "build_id": build_id,
            "pid": os.getpid(),
            "token": token,
            "created_at_utc": _utc_now(),
            "journal_path": str(journal_path),
        }

        with _workspace_guard(lock_path.parent / _GUARD_FILENAME):
            while True:
                try:
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    existing = _read_lock_metadata(lock_path)
                    _validate_lock_journal_path(root, existing)
                    if _pid_is_live(existing["pid"]):
                        raise _build_conflict(
                            "Another LCC build owns the workspace lock.",
                            build_id=existing["build_id"],
                            pid=existing["pid"],
                            journal_path=existing["journal_path"],
                        )
                    _mark_interrupted(root, existing)
                    _remove_matching_lock(lock_path, existing["token"])
                    continue

                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as stream:
                        json.dump(metadata, stream, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
                        stream.write("\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                except Exception:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    try:
                        lock_path.unlink()
                    except OSError:
                        pass
                    raise
                return cls(root, build_id, token, journal_path)

    def release(self, token: str | None = None) -> bool:
        expected_token = self.token if token is None else token
        with _workspace_guard(self.guard_path):
            try:
                metadata = _read_lock_metadata(self.lock_path)
            except (OSError, json.JSONDecodeError, BackendError):
                return False

            _validate_lock_journal_path(self.workspace_root, metadata)

            if metadata["token"] != expected_token:
                return False
            return _remove_matching_lock(self.lock_path, expected_token)


def _read_lock_metadata(lock_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _build_conflict("The existing LCC build lock is unreadable or corrupt.", lock_path=str(lock_path)) from error
    return _validate_lock_metadata(raw, lock_path)


def _validate_lock_metadata(raw: Any, lock_path: Path) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise _build_conflict("The existing LCC build lock has invalid metadata.", lock_path=str(lock_path))
    required = ("build_id", "pid", "token", "created_at_utc", "journal_path")
    missing = [key for key in required if key not in raw]
    if missing:
        raise _build_conflict("The existing LCC build lock is missing metadata.", lock_path=str(lock_path), missing=missing)
    if not isinstance(raw["build_id"], str) or not raw["build_id"]:
        raise _build_conflict("The existing LCC build lock has an invalid build_id.", lock_path=str(lock_path))
    if not isinstance(raw["pid"], int) or isinstance(raw["pid"], bool):
        raise _build_conflict("The existing LCC build lock has an invalid pid.", lock_path=str(lock_path))
    if not isinstance(raw["token"], str) or not raw["token"]:
        raise _build_conflict("The existing LCC build lock has an invalid token.", lock_path=str(lock_path))
    if not isinstance(raw["created_at_utc"], str) or not raw["created_at_utc"]:
        raise _build_conflict("The existing LCC build lock has an invalid created_at_utc.", lock_path=str(lock_path))
    if not isinstance(raw["journal_path"], str) or not raw["journal_path"]:
        raise _build_conflict("The existing LCC build lock has an invalid journal_path.", lock_path=str(lock_path))
    return {key: raw[key] for key in required}


def _pid_is_live(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except Exception as error:
        raise _build_conflict("The existing LCC build lock owner could not be validated.", pid=pid) from error


def _validate_lock_journal_path(workspace_root: Path, lock_metadata: Mapping[str, Any]) -> Path:
    expected = AtomicJournal(workspace_root, str(lock_metadata["build_id"])).path
    candidate = Path(str(lock_metadata["journal_path"])).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as error:
        raise _build_conflict(
            "The existing LCC build lock has an invalid journal path.",
            journal_path=str(candidate),
        ) from error
    if not candidate.is_absolute() or resolved != expected:
        raise _build_conflict(
            "The existing LCC build lock journal is outside the workspace or does not match its build ID.",
            journal_path=str(candidate),
            expected_journal_path=str(expected),
        )
    return expected


def _mark_interrupted(workspace_root: Path, lock_metadata: Mapping[str, Any]) -> None:
    journal_path = _validate_lock_journal_path(workspace_root, lock_metadata)
    try:
        raw = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    record = raw if isinstance(raw, dict) else {}
    history = record.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "state": "interrupted",
            "reason": "stale_lock_recovered",
            "pid": lock_metadata["pid"],
            "recovered_at_utc": _utc_now(),
        }
    )
    record["build_id"] = lock_metadata["build_id"]
    record["state"] = "interrupted"
    record["history"] = history
    _atomic_write_json(journal_path, record)
