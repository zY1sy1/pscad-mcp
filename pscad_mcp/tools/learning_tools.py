from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from ..core.backend.base import BackendError
from ..learning.models import GoalFailureKind
from ..learning.service import learning_runtime
from .registration import register_tool


FailureKindValue = Literal[
    "unsupported_operation",
    "incorrect_result",
    "incomplete_result",
    "environment_blocked",
    "recovery_failed",
    "unknown",
]


async def record_goal_failure(
    failure_kind: str,
    primary_tool: str | None = None,
) -> dict[str, Any]:
    try:
        kind = GoalFailureKind(failure_kind)
    except (TypeError, ValueError) as error:
        raise BackendError(
            "INVALID_ARGUMENT",
            "failure_kind must be one of the documented enum values.",
            "learning",
            "record_goal_failure",
        ) from error
    return learning_runtime.record_goal_failure(
        kind,
        primary_tool,
    )


async def review_improvement_backlog(
    limit: int = 10,
    min_evidence: int = 3,
    mark_notified: bool = False,
) -> dict[str, Any]:
    return learning_runtime.review(
        limit=limit,
        min_evidence=min_evidence,
        mark_notified=mark_notified,
    )


async def clear_learning_history(
    confirm: bool = False,
) -> dict[str, Any]:
    return learning_runtime.clear(confirm=confirm)


def register_learning_tools(mcp: FastMCP) -> None:
    for function in (
        record_goal_failure,
        review_improvement_backlog,
        clear_learning_history,
    ):
        register_tool(mcp, function, record_learning=False)
