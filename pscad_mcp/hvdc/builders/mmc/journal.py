"""MMC journal and workspace lease compatibility backed by common primitives."""

from __future__ import annotations

from ....core.backend.base import BackendError
from ..common.journal import (
    AtomicJournal as _CommonAtomicJournal,
    WorkspaceBuildLease as _CommonWorkspaceBuildLease,
)


_JOURNAL_OPERATION = "write_mmc_journal"
_LEASE_OPERATION = "acquire_mmc_build_lease"
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


class WorkspaceBuildLease(_CommonWorkspaceBuildLease):
    """Preserve MMC journals and errors while sharing the builder lock."""

    journal_class = AtomicJournal
    lock_filename = "builder-build.lock"
    guard_filename = "builder-build.guard"
    lock_description = "LCC/MMC builder lock"
    owner_description = "LCC or MMC builder"

    @classmethod
    def _build_conflict(cls, message: str, **details: object) -> BackendError:
        return _build_conflict(message, **details)


__all__ = ["AtomicJournal", "WorkspaceBuildLease"]
