"""Shared contracts for builders that start from a blank PSCAD project."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....core.path_policy import PathPolicy


@dataclass(frozen=True)
class DefinitionResolution:
    """Immutable evidence describing where a component definition came from."""

    identity: str
    source: str
    ports: tuple[str, ...] = ()
    parameters: Mapping[str, Any] | None = None
    source_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "source": self.source,
            "ports": list(self.ports),
            "parameters": dict(self.parameters or {}),
            "source_hash": self.source_hash,
        }


class ComponentLibraryResolver:
    """Resolve definitions with live Master Library precedence."""

    def __init__(
        self,
        *,
        master: Mapping[str, Any] | None = None,
        companion: Mapping[str, Any] | None = None,
    ) -> None:
        self.master = dict(master or {})
        self.companion = dict(companion or {})

    @staticmethod
    def _record(identity: str, source: str, value: Any) -> DefinitionResolution:
        value = value if isinstance(value, Mapping) else {}
        ports = value.get("ports", ())
        if isinstance(ports, Mapping):
            ports = tuple(str(port) for port in ports)
        elif isinstance(ports, (list, tuple)):
            ports = tuple(
                str(item if isinstance(item, str) else item.get("name"))
                for item in ports
                if isinstance(item, str)
                or isinstance(item, Mapping)
                and item.get("name") is not None
            )
        else:
            ports = ()
        source_hash = value.get("sha256")
        payload = value.get("bytes")
        if source_hash is None and isinstance(payload, (bytes, bytearray)):
            source_hash = hashlib.sha256(payload).hexdigest()
        return DefinitionResolution(
            identity, source, ports, value.get("parameters"), source_hash
        )

    def resolve(self, identity: str) -> DefinitionResolution:
        if not isinstance(identity, str) or not identity.strip():
            raise BackendError(
                "BLANK_DEFINITION_MISSING",
                "A component definition identity is required.",
                "hvdc",
                "resolve_definition",
            )
        identity = identity.strip()
        if identity in self.master:
            return self._record(identity, "master", self.master[identity])
        if identity in self.companion:
            return self._record(identity, "companion", self.companion[identity])
        raise BackendError(
            "BLANK_DEFINITION_MISSING",
            f"Definition '{identity}' is unavailable in Master or companion libraries.",
            "hvdc",
            "resolve_definition",
            {"definition": identity},
        )


class BlankProjectFactory:
    """Plan a new contained PSCX destination without mutating the workspace."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.path_policy = PathPolicy(workspace_root=str(self.workspace_root))

    def plan(self, project_name: str, *, folder: str | None = None) -> dict[str, str]:
        if not isinstance(project_name, str) or not project_name.strip():
            raise BackendError(
                "BLANK_LAYOUT_INVALID",
                "project_name must be a non-empty string.",
                "hvdc",
                "plan_blank_project",
            )
        filename = project_name.strip()
        if not filename.casefold().endswith(".pscx"):
            filename += ".pscx"
        try:
            parent = (
                self.workspace_root
                if folder is None
                else self.path_policy.resolve(folder)
            )
            target = self.path_policy.resolve_child(
                str(parent), filename, suffixes={".pscx"}
            )
        except (ValueError, OSError) as error:
            raise BackendError(
                "BLANK_LAYOUT_INVALID", str(error), "hvdc", "plan_blank_project"
            ) from error
        if target.exists() or target.is_symlink():
            raise BackendError(
                "BLANK_BUILD_CONFLICT",
                "The blank-project destination already exists.",
                "hvdc",
                "plan_blank_project",
                {"target_path": str(target)},
            )
        staging = (
            self.workspace_root
            / ".pscad-mcp"
            / "blank-builds"
            / f"{Path(filename).stem}.staging"
        )
        return {
            "project_name": Path(filename).stem,
            "target_path": str(target),
            "staging_path": str(staging),
        }


__all__ = ["BlankProjectFactory", "ComponentLibraryResolver", "DefinitionResolution"]
