"""Shared bounded identifier rules for MCP tool metadata."""

from __future__ import annotations

import re
from typing import Any


BACKEND_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
PSCAD_VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,31}\Z")


def bounded_identifier(value: Any, pattern: re.Pattern[str]) -> str | None:
    """Return only strings accepted by a fixed identifier pattern."""
    if isinstance(value, str) and pattern.fullmatch(value) is not None:
        return value
    return None
