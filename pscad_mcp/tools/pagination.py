"""Shared, compatibility-preserving bounds for large MCP tool results."""

from __future__ import annotations

from typing import TypeVar

from pydantic import SkipValidation

from ..core.backend.base import BackendError

T = TypeVar("T")

PaginationOffset = SkipValidation[int]
PaginationLimit = SkipValidation[int | None]


def slice_items(
    values: list[T],
    offset: int,
    limit: int | None,
    operation: str,
) -> list[T]:
    """Return a bounded list slice after strict, non-coercing validation."""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise BackendError(
            "INVALID_ARGUMENT",
            "offset must be a non-negative integer.",
            "service",
            operation,
        )
    if limit is not None and (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 1000
    ):
        raise BackendError(
            "INVALID_ARGUMENT",
            "limit must be between 1 and 1000.",
            "service",
            operation,
        )
    return values[offset:] if limit is None else values[offset : offset + limit]


def slice_text(
    value: str,
    offset: int,
    max_chars: int | None,
    operation: str,
) -> str:
    """Return a bounded text slice after strict, non-coercing validation."""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise BackendError(
            "INVALID_ARGUMENT",
            "offset must be a non-negative integer.",
            "service",
            operation,
        )
    if max_chars is not None and (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or not 1 <= max_chars <= 100000
    ):
        raise BackendError(
            "INVALID_ARGUMENT",
            "max_chars must be between 1 and 100000.",
            "service",
            operation,
        )
    return (
        value[offset:]
        if max_chars is None
        else value[offset : offset + max_chars]
    )
