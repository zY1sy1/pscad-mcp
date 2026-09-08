"""Process-local opt-in and instance ownership for independent acceptance runs."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import psutil

from ..core.process_inventory import list_pscad_processes


def concurrent_acceptance_enabled() -> bool:
    return os.environ.get("PSCAD_MCP_ACCEPTANCE_CONCURRENT") == "1"


def acceptance_launch_policy() -> str:
    return "allow" if concurrent_acceptance_enabled() else "reject"


def managed_acceptance_pid(runtime: Mapping[str, Any]) -> int | None:
    session = runtime.get("session", runtime)
    pid = session.get("managed_pid") if isinstance(session, Mapping) else None
    return pid if type(pid) is int and pid > 0 else None


def require_acceptance_ownership(runtime: Mapping[str, Any]) -> None:
    if concurrent_acceptance_enabled() and managed_acceptance_pid(runtime) is None:
        raise RuntimeError("Concurrent acceptance requires a verified managed PSCAD PID.")


def remaining_acceptance_processes(
    runtime: Mapping[str, Any],
    process_reader: Callable[[], Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    if not concurrent_acceptance_enabled():
        return [dict(value) for value in process_reader()]
    require_acceptance_ownership(runtime)
    owned_pid = managed_acceptance_pid(runtime)
    # Discovery is bounded and may omit inaccessible processes. Real cleanup
    # must probe the owned PID directly; injected inventories serve test backends.
    if process_reader is list_pscad_processes:
        return [{"pid": owned_pid}] if psutil.pid_exists(owned_pid) else []
    records = [dict(value) for value in process_reader()]
    return [value for value in records if value.get("pid") == owned_pid]
