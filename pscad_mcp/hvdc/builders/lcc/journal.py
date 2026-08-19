"""LCC compatibility surface backed by the shared journal and lease."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import psutil

from ....core.backend.base import BackendError
from ..common.journal import (
    AtomicJournal as _CommonAtomicJournal,
    WorkspaceBuildLease as _CommonWorkspaceBuildLease,
    _atomic_write_json,
    _remove_matching_lock as _common_remove_matching_lock,
    _restore_without_overwrite,
    _utc_now,
    _workspace_guard,
)


_JOURNAL_OPERATION = "write_lcc_journal"
_LEASE_OPERATION = "acquire_lcc_build_lease"
_GUARD_FILENAME = "lcc-build.guard"
_SHARED_GUARD_FILENAME = "builder-build.guard"
_FOREIGN_LOCK_FILENAME = "mmc-build.lock"


def _journal_invalid(message: str, **details: Any) -> BackendError:
    return BackendError("LCC_JOURNAL_INVALID", message, "hvdc", _JOURNAL_OPERATION, details)


def _build_conflict(message: str, **details: Any) -> BackendError:
    return BackendError("LCC_BUILD_CONFLICT", message, "hvdc", _LEASE_OPERATION, details)


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
        raise _journal_invalid(
            f"{path} is not JSON-safe: {type(value).__name__}",
            field=path,
            type=type(value).__name__,
        )
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _journal_invalid(
                    f"{path} contains a non-string mapping key.",
                    field=path,
                    key_type=type(key).__name__,
                )
            result[key] = _json_safe(item, f"{path}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise _journal_invalid(
        f"{path} is not JSON-safe: {type(value).__name__}",
        field=path,
        type=type(value).__name__,
    )


def _remove_matching_lock(lock_path: Path, expected_token: str) -> bool:
    return _common_remove_matching_lock(lock_path, expected_token)


def _check_foreign_lock(root: Path) -> None:
    lock_path = root / ".pscad-mcp" / _FOREIGN_LOCK_FILENAME
    if not lock_path.exists():
        return
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _build_conflict("The existing MMC build lock is unreadable or corrupt.", lock_path=str(lock_path)) from error
    if not isinstance(raw, Mapping) or not isinstance(raw.get("pid"), int) or isinstance(raw.get("pid"), bool) or not isinstance(raw.get("token"), str) or not raw["token"]:
        raise _build_conflict("The existing MMC build lock has invalid metadata.", lock_path=str(lock_path))
    if psutil.pid_exists(raw["pid"]):
        raise _build_conflict("Another MMC build owns the workspace lock.", build_id=raw.get("build_id"), pid=raw["pid"], journal_path=raw.get("journal_path"))
    try:
        lock_path.unlink()
    except OSError as error:
        raise _build_conflict("The stale MMC build lock could not be recovered.", lock_path=str(lock_path)) from error


class AtomicJournal(_CommonAtomicJournal):
    """Preserve the LCC journal location and serialization error contract."""

    journal_directory = "lcc-builds"
    build_id_label = "LCC"

    @classmethod
    def _journal_invalid(cls, message: str, **details: Any) -> BackendError:
        return _journal_invalid(message, **details)

    @staticmethod
    def _json_safe(value: Any) -> Any:
        return _json_safe(value)


class WorkspaceBuildLease(_CommonWorkspaceBuildLease):
    """Preserve the LCC lock filename and conflict payloads."""

    journal_class = AtomicJournal
    lock_filename = "lcc-build.lock"
    guard_filename = _GUARD_FILENAME
    lock_description = "LCC build lock"
    owner_description = "LCC build"

    @classmethod
    def _build_conflict(cls, message: str, **details: Any) -> BackendError:
        return _build_conflict(message, **details)

    @classmethod
    def acquire(cls, workspace_root: str | Path, build_id: str) -> "WorkspaceBuildLease":
        root = Path(workspace_root).expanduser().resolve()
        with _workspace_guard(root / ".pscad-mcp" / _SHARED_GUARD_FILENAME):
            _check_foreign_lock(root)
            return super().acquire(root, build_id)

    def release(self, token: str | None = None) -> bool:
        with _workspace_guard(self.workspace_root / ".pscad-mcp" / _SHARED_GUARD_FILENAME):
            return super().release(token)

    @classmethod
    def _remove_matching_lock(cls, lock_path: Path, expected_token: str) -> bool:
        # Keep the historical module-level monkeypatch seam used by LCC tests.
        return _remove_matching_lock(lock_path, expected_token)


__all__ = ["AtomicJournal", "WorkspaceBuildLease"]
