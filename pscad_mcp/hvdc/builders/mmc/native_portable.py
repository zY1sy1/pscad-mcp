"""Copy a verified native project and its exact portable dependencies."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_native_bundle(project: Path, library: Path, expected: dict[str, str], destination: Path) -> dict:
    if any(Path(p).is_symlink() for p in (project, library, destination, *expected)):
        raise ValueError("Portable bundle paths must not be symbolic links")
    project, library, destination = map(lambda p: Path(p).resolve(), (project, library, destination))
    source_root = project.parent
    if destination.exists() or destination.is_relative_to(source_root) or source_root.is_relative_to(destination):
        raise ValueError("A portable verification bundle needs a new disjoint directory")
    if library.parent != source_root or not expected:
        raise ValueError("The native project/library must share one verified model directory")
    selected = {str(project), str(library)}
    resolved = {str(Path(name).resolve()): digest for name, digest in expected.items()}
    if len(resolved) != len(expected):
        raise ValueError("Portable dependencies must have unique canonical paths")
    if not selected <= resolved.keys():
        raise ValueError("The frozen manifest must include both model files")
    files = []
    for name, digest in resolved.items():
        source = Path(name)
        if source.is_symlink() or not source.is_file() or not source.is_relative_to(source_root):
            raise ValueError("A portable dependency is missing or escapes the model directory")
        relative = source.relative_to(source_root)
        if relative.parts[0] != "constants" and str(source) not in selected:
            raise ValueError("Only exact model files and declared constants may enter the portable bundle")
        if _digest(source) != digest:
            raise ValueError("A frozen native source changed before independent reload")
        files.append((source, relative, digest))
    destination.mkdir(parents=True)
    copied = {}
    for source, relative, digest in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if _digest(target) != digest or _digest(source) != digest:
            raise ValueError("Native portable copy differs from its frozen source")
        copied[str(target)] = digest
    return {"project_path": str(destination / project.name), "library_path": str(destination / library.name),
            "source_hashes": resolved, "copied_hashes": copied, "source_immutable": True,
            "compiled_artifacts_copied": False, "model_accepted": False}
