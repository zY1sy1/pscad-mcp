"""Strict XML evidence for the one authorized compiler-normalization stage.

Only project Settings/revisor's value, Definition date/crc, automatic-sequence
User/Wire z, and schematic Wire w/h are compiler metadata. Parameter values,
IDs, ports, coordinates, orientation, vertices, code and child order remain
semantic. Outside this stage, callers must compare exact file hashes.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from pscad_mcp.topology.hashing import canonical_sha256

POLICY = "pscad_compiler_metadata_v1"


def snapshot_project_semantics(path: str | Path) -> dict[str, Any]:
    """Capture exact bytes and structured semantics without changing the file."""
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"A regular PSCAD project file is required: {source}")
    raw = source.read_bytes()
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    root = ET.fromstring(raw, parser=parser)
    if root.tag != "project":
        raise ValueError("PSCAD project XML must have a project root")
    metadata: dict[str, str] = {}

    def walk(element, ancestors, address, *, in_schematic=False, automatic=False):
        tag = element.tag
        if tag is ET.Comment:
            tag = "#comment"
        elif tag is ET.ProcessingInstruction:
            tag = "#processing-instruction"
        parents = tuple(parent.tag for parent in ancestors)
        if (
            tag == "schematic"
            and len(ancestors) >= 3
            and parents[:3] == ("project", "definitions", "Definition")
        ):
            in_schematic = True
            sequence = element.findall("./paramlist/param[@name='auto_sequence']")
            automatic = len(sequence) == 1 and sequence[0].get("value") == "1"
        excluded = set()
        if (
            tag == "param"
            and parents == ("project", "paramlist")
            and ancestors[-1].get("name") == "Settings"
            and element.get("name") == "revisor"
        ):
            excluded.add("value")
        if tag == "Definition" and parents == ("project", "definitions"):
            excluded.update(("date", "crc"))
        if in_schematic and tag in {"User", "Wire"} and automatic:
            excluded.add("z")
        if in_schematic and tag == "Wire":
            excluded.update(("w", "h"))
        attributes = {}
        for name, value in element.attrib.items():
            if name in excluded:
                metadata[f"{address}/@{name}"] = value
            else:
                attributes[name] = value
        children = list(element)
        content = element.text
        if children and content is not None and not content.strip():
            content = None
        tail = element.tail
        if tail is not None and not tail.strip() and ("\n" in tail or "\r" in tail):
            tail = None
        return {
            "tag": tag,
            "attributes": attributes,
            "text": content,
            "tail": tail,
            "children": [
                walk(
                    child,
                    (*ancestors, element),
                    f"{address}/{child.tag if isinstance(child.tag, str) else 'content'}[{index}]",
                    in_schematic=in_schematic,
                    automatic=automatic,
                )
                for index, child in enumerate(children)
            ],
        }

    semantics = walk(root, (), "/project")
    digest = hashlib.sha256(raw).hexdigest()
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError("PSCAD project changed during semantic snapshot")
    return {
        "policy": POLICY,
        "path": str(source),
        "sha256": digest,
        "semantics_sha256": canonical_sha256(semantics),
        "semantics": semantics,
        "compiler_metadata": metadata,
    }


def compare_project_finalization(
    authored: dict[str, Any], finalized: dict[str, Any]
) -> dict[str, Any]:
    """Reject semantic changes and return durable before/after metadata evidence."""
    for snapshot in (authored, finalized):
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("policy") != POLICY
            or not isinstance(snapshot.get("semantics"), dict)
            or not isinstance(snapshot.get("compiler_metadata"), dict)
            or not isinstance(snapshot.get("path"), str)
            or re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("sha256", ""))) is None
            or snapshot.get("semantics_sha256")
            != canonical_sha256(snapshot["semantics"])
        ):
            raise ValueError("Invalid project semantic snapshot or hash")
    if authored["semantics"] != finalized["semantics"]:
        raise ValueError("Compiler finalization changed authored project semantics")
    before, after = authored["compiler_metadata"], finalized["compiler_metadata"]
    return {
        "policy": POLICY,
        "semantic_structure_unchanged": True,
        "authored": authored,
        "finalized": finalized,
        "metadata_changes": [
            {"field": key, "before": before.get(key), "after": after.get(key)}
            for key in sorted(set(before) | set(after))
            if before.get(key) != after.get(key)
        ],
    }
