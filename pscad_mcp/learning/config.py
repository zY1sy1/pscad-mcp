from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_RETENTION_MIN = 1
_RETENTION_MAX = 3650
_EVENT_LIMIT_MIN = 100
_EVENT_LIMIT_MAX = 1_000_000


def _state_directory(values: Mapping[str, str], home: Path) -> Path:
    local = values.get("LOCALAPPDATA", "").strip()
    if local and Path(local).is_absolute():
        return Path(local) / "pscad-mcp"
    xdg = values.get("XDG_STATE_HOME", "").strip()
    if xdg and Path(xdg).is_absolute():
        return Path(xdg) / "pscad-mcp"
    return home / ".pscad-mcp"


def _absolute_override(
    values: Mapping[str, str],
    variable: str,
    default: Path,
) -> tuple[Path, str | None]:
    raw = values.get(variable, "").strip()
    if not raw:
        return default, None
    candidate = Path(raw)
    if not candidate.is_absolute():
        return default, variable
    return candidate, None


def _normalized_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _bounded_integer(
    values: Mapping[str, str],
    variable: str,
    default: int,
    minimum: int,
    maximum: int,
) -> tuple[int, str | None]:
    if variable not in values:
        return default, None
    try:
        value = int(values[variable].strip())
    except (AttributeError, TypeError, ValueError):
        return default, variable
    if not minimum <= value <= maximum:
        return default, variable
    return value, None


@dataclass(frozen=True)
class LearningConfig:
    enabled: bool
    database_path: Path
    backlog_path: Path
    retention_days: int
    max_events: int
    issue: str | None

    @property
    def available(self) -> bool:
        return self.enabled and self.issue is None

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        home: Path | None = None,
    ) -> "LearningConfig":
        values = os.environ if environ is None else environ
        home_path = Path.home() if home is None else Path(home)
        state_directory = _state_directory(values, home_path)
        default_database = state_directory / "learning.sqlite3"
        default_backlog = state_directory / "improvement-backlog.md"

        raw_enabled = values.get("PSCAD_MCP_LEARNING_ENABLED")
        if raw_enabled is None:
            enabled = True
        else:
            normalized_enabled = raw_enabled.strip().lower()
            if normalized_enabled in _FALSE_VALUES:
                return cls(
                    enabled=False,
                    database_path=default_database,
                    backlog_path=default_backlog,
                    retention_days=90,
                    max_events=20_000,
                    issue=None,
                )
            if normalized_enabled in _TRUE_VALUES:
                enabled = True
            else:
                return cls(
                    enabled=True,
                    database_path=default_database,
                    backlog_path=default_backlog,
                    retention_days=90,
                    max_events=20_000,
                    issue="PSCAD_MCP_LEARNING_ENABLED",
                )

        database_path, issue = _absolute_override(
            values, "PSCAD_MCP_LEARNING_DB", default_database
        )
        backlog_path, backlog_issue = _absolute_override(
            values, "PSCAD_MCP_LEARNING_BACKLOG", default_backlog
        )
        if issue is None:
            issue = backlog_issue

        retention_days, retention_issue = _bounded_integer(
            values,
            "PSCAD_MCP_LEARNING_RETENTION_DAYS",
            90,
            _RETENTION_MIN,
            _RETENTION_MAX,
        )
        if issue is None:
            issue = retention_issue

        max_events, max_events_issue = _bounded_integer(
            values,
            "PSCAD_MCP_LEARNING_MAX_EVENTS",
            20_000,
            _EVENT_LIMIT_MIN,
            _EVENT_LIMIT_MAX,
        )
        if issue is None:
            issue = max_events_issue

        try:
            normalized_database = _normalized_path(database_path)
        except (OSError, RuntimeError):
            issue = "PSCAD_MCP_LEARNING_DB"
        else:
            try:
                normalized_backlog = _normalized_path(backlog_path)
            except (OSError, RuntimeError):
                issue = "PSCAD_MCP_LEARNING_BACKLOG"
            else:
                if normalized_database == normalized_backlog and issue is None:
                    issue = "PSCAD_MCP_LEARNING_BACKLOG"

        return cls(
            enabled=enabled,
            database_path=database_path,
            backlog_path=backlog_path,
            retention_days=retention_days,
            max_events=max_events,
            issue=issue,
        )
