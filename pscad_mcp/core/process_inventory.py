"""Bounded, read-only process discovery used by the PSCAD launcher."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import psutil


MAX_PROCESS_RECORDS = 16
MAX_PROCESS_NAME_CHARS = 128
MAX_PROCESS_PATH_CHARS = 512


def bounded_process_records(
    values: Iterable[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Return JSON-safe process records without leaking command-line data."""
    records: list[dict[str, object]] = []
    for value in values:
        if len(records) >= MAX_PROCESS_RECORDS:
            break
        try:
            pid = int(value.get("pid"))
        except (TypeError, ValueError, OverflowError):
            continue
        if pid < 1:
            continue
        records.append(
            {
                "pid": pid,
                "name": str(value.get("name") or "")[:MAX_PROCESS_NAME_CHARS],
                "exe": str(value.get("exe") or "")[:MAX_PROCESS_PATH_CHARS],
            }
        )
    return sorted(records, key=lambda item: int(item["pid"]))


def list_pscad_processes() -> list[dict[str, object]]:
    """List visible PSCAD executables without reading their command lines."""
    candidates: list[dict[str, object]] = []
    for process in psutil.process_iter(("pid", "name", "exe")):
        try:
            name = str(process.info.get("name") or "")
            exe = str(process.info.get("exe") or "")
            executable_name = Path(exe).name if exe else ""
            if (
                "pscad" not in name.casefold()
                and "pscad" not in executable_name.casefold()
            ):
                continue
            candidates.append(
                {"pid": process.info.get("pid"), "name": name, "exe": exe}
            )
        except (
            psutil.AccessDenied,
            psutil.NoSuchProcess,
            psutil.ZombieProcess,
            OSError,
        ):
            continue
    return bounded_process_records(candidates)
