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
    _remove_matching_lock as _common_remove_matching_lock,
)


_JOURNAL_OPERATION = "write_lcc_journal"
_LEASE_OPERATION = "acquire_lcc_build_lease"
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
    """Preserve LCC journals and errors while sharing the builder lock."""

    journal_class = AtomicJournal
    lock_filename = "builder-build.lock"
    guard_filename = "builder-build.guard"
    lock_description = "LCC/MMC builder lock"
    owner_description = "LCC or MMC builder"

    @classmethod
    def _build_conflict(cls, message: str, **details: Any) -> BackendError:
        return _build_conflict(message, **details)

    @classmethod
    def _remove_matching_lock(cls, lock_path: Path, expected_token: str) -> bool:
        # Keep the historical module-level monkeypatch seam used by LCC tests.
        return _remove_matching_lock(lock_path, expected_token)


__all__ = ["AtomicJournal", "WorkspaceBuildLease"]
