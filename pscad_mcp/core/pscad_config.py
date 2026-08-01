from dataclasses import dataclass
import os
import re
from typing import Literal, Mapping, Optional, Sequence


@dataclass(frozen=True)
class PscadLaunchConfig:
    """User-selectable PSCAD launch settings."""

    version: Optional[str] = None
    x64: Optional[bool] = None
    timeout: int = 30
    backend: Literal["auto", "legacy", "modern"] = "auto"
    legacy_wheel: Optional[str] = None

    @classmethod
    def from_environ(
        cls,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "PscadLaunchConfig":
        values = os.environ if environ is None else environ
        backend = values.get("PSCAD_MCP_BACKEND", "auto").strip().lower()
        if backend not in {"auto", "legacy", "modern"}:
            raise ValueError(
                "PSCAD_MCP_BACKEND must be auto, legacy, or modern."
            )
        version = values.get("PSCAD_MCP_VERSION", "").strip() or None
        raw_x64 = values.get("PSCAD_MCP_X64")
        if raw_x64 is None:
            x64 = None
        elif raw_x64.strip().lower() in {"1", "true", "yes", "on"}:
            x64 = True
        elif raw_x64.strip().lower() in {"0", "false", "no", "off"}:
            x64 = False
        else:
            raise ValueError("PSCAD_MCP_X64 must be true or false.")

        raw_timeout = values.get("PSCAD_MCP_LAUNCH_TIMEOUT", "30")
        try:
            timeout = int(raw_timeout)
        except ValueError as exc:
            raise ValueError(
                "PSCAD_MCP_LAUNCH_TIMEOUT must be a positive integer."
            ) from exc
        if timeout < 1:
            raise ValueError(
                "PSCAD_MCP_LAUNCH_TIMEOUT must be a positive integer."
            )
        legacy_wheel = (
            values.get("PSCAD_MCP_LEGACY_WHEEL", "").strip() or None
        )
        return cls(
            version=version,
            x64=x64,
            timeout=timeout,
            backend=backend,
            legacy_wheel=legacy_wheel,
        )


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(r"\d+", version))


def select_installation(
    installations: Sequence[tuple[str, bool]],
    config: PscadLaunchConfig,
) -> tuple[str, bool]:
    """Choose an installed PSCAD version that satisfies the configuration."""
    candidates = list(installations)
    if config.version is not None:
        candidates = [item for item in candidates if item[0] == config.version]
    if config.x64 is not None:
        candidates = [item for item in candidates if item[1] is config.x64]

    if not candidates:
        available = ", ".join(
            f"{version} ({'x64' if x64 else 'x86'})"
            for version, x64 in installations
        )
        raise ValueError(
            "Requested PSCAD installation is unavailable. "
            f"Installed: {available or 'none'}"
        )

    return max(
        candidates,
        key=lambda item: (_version_key(item[0]), item[1]),
    )
