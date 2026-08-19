"""MMC journal and workspace lease compatibility backed by common primitives."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import psutil

from ....core.backend.base import BackendError
from ..common.journal import (
    AtomicJournal as _CommonAtomicJournal,
    WorkspaceBuildLease as _CommonWorkspaceBuildLease,
    _workspace_guard,
)


_JOURNAL_OPERATION = "write_mmc_journal"
_LEASE_OPERATION = "acquire_mmc_build_lease"
_SHARED_GUARD_FILENAME = "builder-build.guard"
_FOREIGN_LOCK_FILENAME = "lcc-build.lock"


def _journal_invalid(message: str, **details: object) -> BackendError:
    return BackendError("MMC_JOURNAL_INVALID", message, "hvdc", _JOURNAL_OPERATION, details)


def _build_conflict(message: str, **details: object) -> BackendError:
    return BackendError("MMC_BUILD_CONFLICT", message, "hvdc", _LEASE_OPERATION, details)


class AtomicJournal(_CommonAtomicJournal):
    """Write MMC records below the MMC-specific journal directory."""

    journal_directory = "mmc-builds"
    build_id_label = "MMC"

    @classmethod
    def _journal_invalid(cls, message: str, **details: object) -> BackendError:
        return _journal_invalid(message, **details)


def _check_foreign_lock(root: Path) -> None:
    lock_path = root / ".pscad-mcp" / _FOREIGN_LOCK_FILENAME
    if not lock_path.exists():
        return
    try:
        raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _build_conflict("The existing LCC build lock is unreadable or corrupt.", lock_path=str(lock_path)) from error
    if not isinstance(raw, Mapping) or not isinstance(raw.get("pid"), int) or isinstance(raw.get("pid"), bool) or not isinstance(raw.get("token"), str) or not raw["token"]:
        raise _build_conflict("The existing LCC build lock has invalid metadata.", lock_path=str(lock_path))
    if psutil.pid_exists(raw["pid"]):
        raise _build_conflict("Another LCC build owns the workspace lock.", build_id=raw.get("build_id"), pid=raw["pid"], journal_path=raw.get("journal_path"))
    try:
        lock_path.unlink()
    except OSError as error:
        raise _build_conflict("The stale LCC build lock could not be recovered.", lock_path=str(lock_path)) from error


class WorkspaceBuildLease(_CommonWorkspaceBuildLease):
    """Use a family-specific lock while coordinating with the LCC lock."""

    journal_class = AtomicJournal
    lock_filename = "mmc-build.lock"
    guard_filename = "mmc-build.guard"
    lock_description = "MMC build lock"
    owner_description = "MMC build"

    @classmethod
    def _build_conflict(cls, message: str, **details: object) -> BackendError:
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


__all__ = ["AtomicJournal", "WorkspaceBuildLease"]
