"""Inventory a saved, loaded Legacy input without dirtying its native canvas."""

from collections import Counter
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from ...core.backend.base import BackendError
from ...core.definition_metadata import parse_definition_metadata_source
from ...topology.geometry import absolute_port


def inventory_from_saved_sources(project: Path, definition_paths: dict[str, Path], version: str) -> dict:
    snapshots = {path: path.read_bytes() for path in {project, *definition_paths.values()} if path.is_file()}
    source = snapshots[project]
    root = ET.fromstring(source)
    directories = {scope: parse_definition_metadata_source(snapshots[path]).definitions
                   for scope, path in definition_paths.items() if path in snapshots}
    directories[root.get("name")] = parse_definition_metadata_source(source).definitions
    mains = root.findall("./definitions/Definition[@name='Main']")
    if len(mains) != 1:
        raise BackendError("BLUEPRINT_PROJECT_INVALID", "Saved input must have one Main definition.",
                           "legacy", "get_blueprint_inventory")
    definitions = {}
    components = []
    for node in mains[0].findall("./schematic/User"):
        if node.get("classid") != "UserCmp":
            continue
        component_id = int(node.attrib["id"])
        scoped = node.get("defn", "")
        namespace, _, local = scoped.partition(":")
        matches = directories.get(namespace, {}).get(local, ())
        resolved = len(matches) == 1
        metadata = matches[0] if resolved else None
        parameters = {item.attrib["name"]: item.get("value", "")
                      for item in node.findall("./paramlist/param") if item.get("name")}
        contracts = {name: {"resolved": not item.readonly, "units": item.unit}
                     for name, item in metadata.parameters.items()} if metadata else {}
        # Conditional or duplicate ports remain unavailable to the planner.
        # Resolving a parameter never grants an unverified wiring capability.
        candidates = [port for port in metadata.ports if not port.condition] if metadata else []
        counts = Counter(port.name for port in candidates)
        selected = [port for port in candidates if counts[port.name] == 1]
        location = [int(node.attrib["x"]), int(node.attrib["y"])]
        orientation = int(node.get("orient", "0"))
        port_contracts = {port.name: {"kind": "electrical" if port.model == "Natural" else "signal",
                                      "dimension": port.dim or 1} for port in selected}
        ports = {}
        for port in selected:
            x, y = absolute_port(location, [port.x, port.y], orientation)
            ports[port.name] = {"name": port.name, "x": x, "y": y, **port_contracts[port.name]}
        definitions[scoped] = {"parameters": contracts, "ports": port_contracts}
        name = parameters.get("Name") or node.get("name") or str(component_id)
        components.append({
            "id": component_id, "logical_id": name, "name": name,
            "definition": scoped or "unresolved", "canvas": "Main",
            "location": location, "orientation": orientation, "parameters": parameters,
            "parameter_metadata": {key: contracts.get(key, {"resolved": False, "units": None})
                                   for key in parameters},
            "ports": ports, "resolved": resolved,
        })
    if any(hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(content).digest()
           for path, content in snapshots.items()):
        raise BackendError("BLUEPRINT_SOURCE_HASH_MISMATCH", "An inventory source changed during reading.",
                           "legacy", "get_blueprint_inventory")
    return {"pscad_version": version, "definitions": definitions, "components": components}
