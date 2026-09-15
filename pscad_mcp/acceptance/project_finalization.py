"""Strict XML evidence for the one authorized compiler-normalization stage.

Only project Settings/revisor's value, Definition date/crc, automatic-sequence
User/Wire z, and schematic Wire w/h are compiler metadata. Parameter values,
IDs, ports, coordinates, orientation, vertices, code and child order remain
semantic. Outside this stage, callers must compare exact file hashes.

The generated-module opt-in also permits User display bounds, direct instance
parameter-list crc, and the top Station hierarchy call's vendor-assigned link.
It permits compiler-assigned ``instance`` and automatic execution-order ``z``
only on direct children of the Main hierarchy call; component links, names and
nested child calls remain semantic. Schematic User/Wire ``z`` already follows
the same automatic-sequence rule.
These were observed in the authored/model pair from average-arm acceptance
attempt-20260908-174633-918404c6. Nested hierarchy calls and all parameter children
remain semantic; the generator must author defaults and child calls explicitly.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from pscad_mcp.topology.hashing import canonical_sha256

POLICY = "pscad_compiler_metadata_v1"
GENERATED_MODULE_POLICY = "pscad_generated_module_metadata_v1"
_POLICIES = {POLICY, GENERATED_MODULE_POLICY}


def snapshot_project_semantics(
    path: str | Path, *, policy: str = POLICY
) -> dict[str, Any]:
    """Capture exact bytes and structured semantics without changing the file."""
    if not isinstance(policy, str) or policy not in _POLICIES:
        raise ValueError(f"Unknown project finalization policy: {policy}")
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
        if policy == GENERATED_MODULE_POLICY:
            if in_schematic and tag == "User" and element.get("classid") == "UserCmp":
                excluded.update(("w", "h"))
            if (
                in_schematic
                and tag == "paramlist"
                and ancestors[-1].tag == "User"
                and ancestors[-1].get("classid") == "UserCmp"
                and element.get("name") == ""
                and element.get("link") == "-1"
            ):
                excluded.add("crc")
            if (
                tag == "call"
                and parents == ("project", "hierarchy")
                and root.get("name")
                and element.get("name") == f"{root.get('name')}:Station"
            ):
                excluded.add("link")
            if tag == "call" and parents == (
                "project",
                "hierarchy",
                "call",
                "call",
            ):
                excluded.update(("instance", "z"))
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
        "policy": policy,
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
            or not isinstance(snapshot.get("policy"), str)
            or snapshot["policy"] not in _POLICIES
        ):
            raise ValueError("Invalid project finalization policy")
        if (
            not isinstance(snapshot.get("semantics"), dict)
            or not isinstance(snapshot.get("compiler_metadata"), dict)
            or not isinstance(snapshot.get("path"), str)
            or re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("sha256", ""))) is None
            or snapshot.get("semantics_sha256")
            != canonical_sha256(snapshot["semantics"])
        ):
            raise ValueError("Invalid project semantic snapshot or hash")
    if authored["policy"] != finalized["policy"]:
        raise ValueError("Project finalization policies must match")
    if authored["semantics"] != finalized["semantics"]:
        raise ValueError("Compiler finalization changed authored project semantics")
    before, after = authored["compiler_metadata"], finalized["compiler_metadata"]
    return {
        "policy": authored["policy"],
        "semantic_structure_unchanged": True,
        "authored": authored,
        "finalized": finalized,
        "metadata_changes": [
            {"field": key, "before": before.get(key), "after": after.get(key)}
            for key in sorted(set(before) | set(after))
            if before.get(key) != after.get(key)
        ],
    }
