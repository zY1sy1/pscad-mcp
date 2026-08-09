"""Safety checks shared by PSCAD run-control backends."""

from __future__ import annotations

from collections.abc import Mapping

from .base import BackendError, RunState


ACTIVE_RUN_STATUSES = frozenset(
    {"starting", "building", "running", "paused"}
)
STOPPED_RUN_STATUSES = frozenset(
    {"idle", "stopped", "complete", "completed"}
)


def _status(state: RunState | None) -> str | None:
    return state.status.casefold() if state is not None else None


def require_active_target(
    project_name: str,
    states: Mapping[str, RunState],
    *,
    backend: str,
    operation: str,
) -> RunState:
    """Reject a run-control operation whose target is not active."""
    target = states.get(project_name)
    if _status(target) not in ACTIVE_RUN_STATUSES:
        raise BackendError(
            "RUN_NOT_ACTIVE",
            f"Project '{project_name}' is not active.",
            backend,
            operation,
            {
                "project_name": project_name,
                "state": _status(target),
            },
        )
    return target


def require_single_active_target(
    project_name: str,
    states: Mapping[str, RunState],
    *,
    backend: str,
    operation: str,
) -> RunState:
    """Allow an application-wide command only for one active case."""
    target = require_active_target(
        project_name,
        states,
        backend=backend,
        operation=operation,
    )
    active = {
        name: state.status.casefold()
        for name, state in states.items()
        if state.status.casefold() in ACTIVE_RUN_STATUSES
    }
    if set(active) != {project_name}:
        raise BackendError(
            "RUN_CONTROL_SCOPE_CONFLICT",
            "The PSCAD command would affect more than the requested project.",
            backend,
            operation,
            {
                "project_name": project_name,
                "active_projects": active,
                "scope": "all-running-projects",
            },
        )
    return target
