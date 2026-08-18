"""Atomic journal persistence and workspace leases for LCC builds."""

from __future__ import annotations

import json
import math
import os
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import psutil

from ....core.backend.base import BackendError

_JOURNAL_OPERATION = "write_lcc_journal"
_LEASE_OPERATION = "acquire_lcc_build_lease"


def _journal_invalid(message: str, **details: Any) -> BackendError:
    return BackendError("LCC_JOURNAL_INVALID", message, "hvdc", _JOURNAL_OPERATION, details)


def _build_conflict(message: str, **details: Any) -> BackendError:
    return BackendError("LCC_BUILD_CONFLICT", message, "hvdc", _LEASE_OPERATION, details)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        self.workspace_root = Path(workspace_root)
        self.build_id = build_id
        self.path = self.workspace_root / ".pscad-mcp" / "lcc-builds" / build_id / "journal.json"

    def write(self, payload: Mapping[str, Any]) -> Path:
        return _atomic_write_json(self.path, payload)


class WorkspaceBuildLease:
    """Cross-process build lease backed by an exclusive lock file."""

    def __init__(self, workspace_root: str | Path, build_id: str, token: str, journal_path: str | Path) -> None:
        self.workspace_root = Path(workspace_root)
        self.build_id = build_id
        self.token = token
        self.journal_path = Path(journal_path)
        self.lock_path = self.workspace_root / ".pscad-mcp" / "lcc-build.lock"

    @classmethod
    def acquire(cls, workspace_root: str | Path, build_id: str) -> "WorkspaceBuildLease":
        root = Path(workspace_root)
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

        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                existing = _read_lock_metadata(lock_path)
                if _pid_is_live(existing["pid"]):
                    raise _build_conflict(
                        "Another LCC build owns the workspace lock.",
                        build_id=existing["build_id"],
                        pid=existing["pid"],
                        journal_path=existing["journal_path"],
                    )
                _mark_interrupted(existing)
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
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
        try:
            original_text = self.lock_path.read_text(encoding="utf-8")
            metadata = _validate_lock_metadata(json.loads(original_text), self.lock_path)
        except (OSError, json.JSONDecodeError, BackendError):
            return False

        if metadata["token"] != expected_token:
            return False
        try:
            if self.lock_path.read_text(encoding="utf-8") != original_text:
                return False
            self.lock_path.unlink()
        except FileNotFoundError:
            return False
        return True


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


def _mark_interrupted(lock_metadata: Mapping[str, Any]) -> None:
    journal_path = Path(str(lock_metadata["journal_path"]))
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
