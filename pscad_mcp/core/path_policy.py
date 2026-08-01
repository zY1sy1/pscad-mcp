import os
from pathlib import Path
from typing import Iterable, Optional


class PathPolicy:
    """Resolve user-supplied paths and optionally keep them inside a workspace."""

    def __init__(self, workspace_root: Optional[str] = None):
        configured_root = workspace_root or os.getenv("PSCAD_MCP_WORKSPACE")
        self.workspace_root = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else None
        )

    def resolve(
        self,
        candidate: str,
        *,
        suffixes: Optional[Iterable[str]] = None,
        must_exist: bool = False,
    ) -> Path:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = (self.workspace_root or Path.cwd()) / path
        resolved = path.resolve()

        if self.workspace_root and not self._is_within(resolved, self.workspace_root):
            raise ValueError(
                f"Path '{candidate}' is outside the configured PSCAD workspace."
            )

        if suffixes:
            allowed = {suffix.lower() for suffix in suffixes}
            if resolved.suffix.lower() not in allowed:
                raise ValueError(
                    f"Path '{candidate}' must use one of: {', '.join(sorted(allowed))}."
                )

        if must_exist and not resolved.exists():
            raise FileNotFoundError(str(resolved))

        return resolved

    def resolve_child(
        self,
        base_dir: str,
        candidate: str,
        *,
        suffixes: Optional[Iterable[str]] = None,
        must_exist: bool = False,
    ) -> Path:
        base = Path(base_dir).expanduser().resolve()
        path = (base / candidate).resolve()
        if not self._is_within(path, base):
            raise ValueError(f"Path '{candidate}' escapes the allowed directory.")
        if suffixes:
            allowed = {suffix.lower() for suffix in suffixes}
            if path.suffix.lower() not in allowed:
                raise ValueError(
                    f"Path '{candidate}' must use one of: {', '.join(sorted(allowed))}."
                )
        if must_exist and not path.exists():
            raise FileNotFoundError(str(path))
        return path

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        return path == root or root in path.parents
