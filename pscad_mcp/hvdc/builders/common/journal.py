"""Atomic journals and workspace-scoped cross-process leases."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import psutil

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from ....core.backend.base import BackendError
from .serialization import SerializationError, json_safe


_BUILD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_JOURNAL_DIRECTORIES = frozenset({"builds", "lcc-builds", "mmc-builds"})


def _common_journal_invalid(message: str, **details: Any) -> BackendError:
    return BackendError("BUILDER_JOURNAL_INVALID", message, "hvdc", "write_builder_journal", details)


def _common_build_conflict(message: str, **details: Any) -> BackendError:
    return BackendError("BUILDER_BUILD_CONFLICT", message, "hvdc", "acquire_builder_build_lease", details)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, payload: Mapping[str, Any], *, safe_copy, invalid_error) -> Path:
    temp_path: Path | None = None
    try:
        safe_payload = safe_copy(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
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
    except (SerializationError, TypeError, ValueError) as error:
        raise invalid_error(f"Journal payload could not be serialized: {error}") from error
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


class AtomicJournal:
    """Write JSON journals using same-directory atomic replacement."""

    journal_directory: ClassVar[str] = "builds"
    journal_filename: ClassVar[str] = "journal.json"
    build_id_label: ClassVar[str] = "builder"

    @classmethod
    def _journal_invalid(cls, message: str, **details: Any) -> BackendError:
        return _common_journal_invalid(message, **details)

    @classmethod
    def _validate_build_id(cls, build_id: Any) -> str:
        if not isinstance(build_id, str) or _BUILD_ID_RE.fullmatch(build_id) is None:
            raise cls._journal_invalid(
                f"The {cls.build_id_label} build_id must be a simple workspace-safe identifier.",
                build_id=build_id,
            )
        return build_id

    @staticmethod
    def _json_safe(value: Any) -> Any:
        return json_safe(value)

    def __init__(self, workspace_root: str | Path, build_id: str) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.build_id = type(self)._validate_build_id(build_id)
        self.path = self.workspace_root / ".pscad-mcp" / type(self).journal_directory / self.build_id / type(self).journal_filename

    def write(self, payload: Mapping[str, Any]) -> Path:
        return _atomic_write_json(
            self.path,
            payload,
            safe_copy=type(self)._json_safe,
            invalid_error=type(self)._journal_invalid,
        )


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


def _restore_without_overwrite(tombstone: Path, lock_path: Path) -> bool:
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


def _read_lock_metadata(lock_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _common_build_conflict("The existing builder lock is unreadable or corrupt.", lock_path=str(lock_path)) from error
    if not isinstance(raw, Mapping) or not isinstance(raw.get("token"), str) or not raw["token"]:
        raise _common_build_conflict("The existing builder lock has invalid metadata.", lock_path=str(lock_path))
    return dict(raw)


def _remove_matching_lock(lock_path: Path, expected_token: str) -> bool:
    """Remove only the lock whose token was verified by the caller."""

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


class WorkspaceBuildLease:
    """Cross-process build lease backed by an exclusive lock file."""

    journal_class: ClassVar[type[AtomicJournal]] = AtomicJournal
    lock_filename: ClassVar[str] = "builder-build.lock"
    guard_filename: ClassVar[str] = "builder-build.guard"
    lock_description: ClassVar[str] = "builder build lock"
    owner_description: ClassVar[str] = "builder"

    @classmethod
    def _build_conflict(cls, message: str, **details: Any) -> BackendError:
        return _common_build_conflict(message, **details)

    @classmethod
    def _remove_matching_lock(cls, lock_path: Path, expected_token: str) -> bool:
        return _remove_matching_lock(lock_path, expected_token)

    def __init__(self, workspace_root: str | Path, build_id: str, token: str, journal_path: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.build_id = type(self).journal_class._validate_build_id(build_id)
        self.token = token
        self.journal_path = Path(journal_path)
        self.lock_path = self.workspace_root / ".pscad-mcp" / type(self).lock_filename
        self.guard_path = self.lock_path.with_name(type(self).guard_filename)

    @classmethod
    def acquire(cls, workspace_root: str | Path, build_id: str) -> "WorkspaceBuildLease":
        root = Path(workspace_root).expanduser().resolve()
        lock_path = root / ".pscad-mcp" / cls.lock_filename
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path = cls.journal_class(root, build_id).path
        token = uuid.uuid4().hex
        metadata = {
            "build_id": build_id,
            "pid": os.getpid(),
            "token": token,
            "created_at_utc": _utc_now(),
            "journal_path": str(journal_path),
        }

        with _workspace_guard(lock_path.parent / cls.guard_filename):
            while True:
                try:
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    existing = cls._read_lock_metadata(lock_path)
                    cls._validate_lock_journal_path(root, existing)
                    if cls._pid_is_live(existing["pid"]):
                        raise cls._build_conflict(
                            f"Another {cls.owner_description} owns the workspace lock.",
                            build_id=existing["build_id"],
                            pid=existing["pid"],
                            journal_path=existing["journal_path"],
                        )
                    cls._mark_interrupted(root, existing)
                    cls._remove_matching_lock(lock_path, existing["token"])
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
                metadata = type(self)._read_lock_metadata(self.lock_path)
            except (OSError, json.JSONDecodeError, BackendError):
                return False

            type(self)._validate_lock_journal_path(self.workspace_root, metadata)
            if metadata["token"] != expected_token:
                return False
            return type(self)._remove_matching_lock(self.lock_path, expected_token)

    @classmethod
    def _read_lock_metadata(cls, lock_path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise cls._build_conflict(f"The existing {cls.lock_description} is unreadable or corrupt.", lock_path=str(lock_path)) from error
        return cls._validate_lock_metadata(raw, lock_path)

    @classmethod
    def _validate_lock_metadata(cls, raw: Any, lock_path: Path) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise cls._build_conflict(f"The existing {cls.lock_description} has invalid metadata.", lock_path=str(lock_path))
        required = ("build_id", "pid", "token", "created_at_utc", "journal_path")
        missing = [key for key in required if key not in raw]
        if missing:
            raise cls._build_conflict(f"The existing {cls.lock_description} is missing metadata.", lock_path=str(lock_path), missing=missing)
        if not isinstance(raw["build_id"], str) or not raw["build_id"]:
            raise cls._build_conflict(f"The existing {cls.lock_description} has an invalid build_id.", lock_path=str(lock_path))
        if not isinstance(raw["pid"], int) or isinstance(raw["pid"], bool):
            raise cls._build_conflict(f"The existing {cls.lock_description} has an invalid pid.", lock_path=str(lock_path))
        if not isinstance(raw["token"], str) or not raw["token"]:
            raise cls._build_conflict(f"The existing {cls.lock_description} has an invalid token.", lock_path=str(lock_path))
        if not isinstance(raw["created_at_utc"], str) or not raw["created_at_utc"]:
            raise cls._build_conflict(f"The existing {cls.lock_description} has an invalid created_at_utc.", lock_path=str(lock_path))
        if not isinstance(raw["journal_path"], str) or not raw["journal_path"]:
            raise cls._build_conflict(f"The existing {cls.lock_description} has an invalid journal_path.", lock_path=str(lock_path))
        return {key: raw[key] for key in required}

    @classmethod
    def _pid_is_live(cls, pid: int) -> bool:
        try:
            return psutil.pid_exists(pid)
        except Exception as error:
            raise cls._build_conflict(f"The existing {cls.lock_description} owner could not be validated.", pid=pid) from error

    @classmethod
    def _validate_lock_journal_path(cls, workspace_root: Path, lock_metadata: Mapping[str, Any]) -> Path:
        candidate = Path(str(lock_metadata["journal_path"])).expanduser()
        try:
            resolved = candidate.resolve()
            relative = resolved.relative_to((workspace_root / ".pscad-mcp").resolve())
        except OSError as error:
            raise cls._build_conflict(f"The existing {cls.lock_description} has an invalid journal path.", journal_path=str(candidate)) from error
        except ValueError as error:
            raise cls._build_conflict(
                f"The existing {cls.lock_description} journal is outside the workspace or does not match its build ID.",
                journal_path=str(candidate),
            ) from error
        expected_parts = (str(lock_metadata["build_id"]), "journal.json")
        if (
            not candidate.is_absolute()
            or len(relative.parts) != 3
            or relative.parts[0] not in _JOURNAL_DIRECTORIES
            or relative.parts[1:] != expected_parts
        ):
            raise cls._build_conflict(
                f"The existing {cls.lock_description} journal is outside the workspace or does not match its build ID.",
                journal_path=str(candidate),
            )
        return resolved

    @classmethod
    def _mark_interrupted(cls, workspace_root: Path, lock_metadata: Mapping[str, Any]) -> None:
        journal_path = cls._validate_lock_journal_path(workspace_root, lock_metadata)
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
        _atomic_write_json(
            journal_path,
            record,
            safe_copy=cls.journal_class._json_safe,
            invalid_error=cls.journal_class._journal_invalid,
        )


__all__ = ["AtomicJournal", "WorkspaceBuildLease"]
