"""Copy a verified native project and its exact portable dependencies."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from xml.etree import ElementTree as ET


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
    copied_library = destination / library.name
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    tree = ET.parse(copied_library, parser=parser)
    relocations = []
    for parameter in tree.findall(".//param[@name='const_path']"):
        value = parameter.get("value", "")
        old = Path(value)
        old = (old if old.is_absolute() else source_root / old).resolve()
        if str(old) not in resolved or old.relative_to(source_root).parts[0] != "constants":
            raise ValueError("A cable dependency has no frozen portable file")
        target = destination / old.relative_to(source_root)
        parameter.set("value", str(target))
        relocations.append({"parameter": "const_path", "before": value, "after": str(target), "sha256": resolved[str(old)]})
    if relocations:
        tree.write(copied_library, encoding="utf-8", xml_declaration=True)
        copied[str(copied_library)] = _digest(copied_library)
    if any(_digest(Path(path)) != digest for path, digest in resolved.items()):
        raise ValueError("A frozen source changed during portable dependency relocation")
    return {"project_path": str(destination / project.name), "library_path": str(destination / library.name),
            "source_hashes": resolved, "copied_hashes": copied, "source_immutable": True,
            "dependency_relocations": relocations,
            "compiled_artifacts_copied": False, "model_accepted": False}
