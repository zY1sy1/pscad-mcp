"""Deterministic PSCAD automation backend selection."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterable, Mapping, Sequence

from ..pscad_config import PscadLaunchConfig, _version_key


Installation = tuple[str, bool]
VersionDiscovery = Callable[[], Iterable[Installation | str]]


@dataclass(frozen=True)
class BackendChoice:
    backend: str
    version: str
    x64: bool


class BackendSelectionError(ValueError):
    """Raised when the requested backend/version cannot be honored."""


def normalize_legacy_versions(values: Iterable[Installation | str]) -> list[Installation]:
    """Convert legacy display names to the common ``(version, x64)`` shape."""
    normalized: list[Installation] = []
    for value in values:
        if isinstance(value, tuple):
            normalized.append((str(value[0]), bool(value[1])))
            continue
        match = re.search(
            r"PSCAD\s+([0-9]+(?:\.[0-9]+)+)\s+\((x64|x86)\)",
            str(value),
            flags=re.IGNORECASE,
        )
        if match:
            normalized.append(
                (match.group(1), match.group(2).lower() == "x64")
            )
    return normalized


def _normalize_modern_versions(values: Iterable[Installation | str]) -> list[Installation]:
    normalized: list[Installation] = []
    for value in values:
        if isinstance(value, tuple):
            candidate = (str(value[0]), bool(value[1]))
        else:
            match = re.search(
                r"([0-9]+(?:\.[0-9]+)+).*?(x64|x86)",
                str(value),
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            candidate = (match.group(1), match.group(2).lower() == "x64")
        if _major(candidate[0]) >= 5:
            normalized.append(candidate)
    return normalized


def _major(version: str) -> int:
    key = _version_key(version)
    return key[0] if key else 0


def _format_available(
    legacy: Sequence[Installation], modern: Sequence[Installation]
) -> str:
    entries = [
        *(f"legacy {version} ({'x64' if x64 else 'x86'})" for version, x64 in legacy),
        *(f"modern {version} ({'x64' if x64 else 'x86'})" for version, x64 in modern),
    ]
    return ", ".join(entries) or "none"


def _choose(
    candidates: Sequence[Installation],
    config: PscadLaunchConfig,
) -> Installation | None:
    filtered = list(candidates)
    if config.version is not None:
        filtered = [item for item in filtered if item[0] == config.version]
    if config.x64 is not None:
        filtered = [item for item in filtered if item[1] is config.x64]
    if not filtered:
        return None
    return max(filtered, key=lambda item: (_version_key(item[0]), item[1]))


def select_backend(
    environ: Mapping[str, str],
    *,
    legacy_versions: VersionDiscovery,
    modern_versions: VersionDiscovery,
) -> BackendChoice:
    """Select an installed backend without silently changing user intent."""
    config = PscadLaunchConfig.from_environ(environ)
    legacy = [
        item
        for item in normalize_legacy_versions(legacy_versions())
        if _major(item[0]) < 5
    ]
    modern = _normalize_modern_versions(modern_versions())

    requested_backend = config.backend
    if config.version is not None:
        implied_backend = "legacy" if _major(config.version) < 5 else "modern"
        if requested_backend != "auto" and requested_backend != implied_backend:
            raise BackendSelectionError(
                f"Backend {requested_backend} cannot run PSCAD {config.version}. "
                f"Detected: {_format_available(legacy, modern)}"
            )
        requested_backend = implied_backend

    if requested_backend == "legacy":
        selected = _choose(legacy, config)
        if selected:
            return BackendChoice("legacy", *selected)
    elif requested_backend == "modern":
        selected = _choose(modern, config)
        if selected:
            return BackendChoice("modern", *selected)
    else:
        choices: list[BackendChoice] = []
        legacy_choice = _choose(legacy, config)
        modern_choice = _choose(modern, config)
        if legacy_choice:
            choices.append(BackendChoice("legacy", *legacy_choice))
        if modern_choice:
            choices.append(BackendChoice("modern", *modern_choice))
        if choices:
            return max(
                choices,
                key=lambda item: (_version_key(item.version), item.x64),
            )

    raise BackendSelectionError(
        f"Requested PSCAD {requested_backend} backend/version is unavailable. "
        f"Detected: {_format_available(legacy, modern)}"
    )
