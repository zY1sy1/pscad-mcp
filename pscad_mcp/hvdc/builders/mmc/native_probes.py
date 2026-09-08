"""Physical measurement probes for the audited PSCAD 4.6.2 full-cell template."""

from __future__ import annotations

import hashlib
from itertools import pairwise
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from ....core.definition_metadata import read_definition_metadata_document
from ....core.master_bindings import _normalized_kind
from ..common.routing import absolute_port
from .template_audit import _components, _parameters


def _error(message: str, **details: Any) -> BackendError:
    return BackendError(
        "MMC_PROBE_SOURCE_MISMATCH",
        message,
        "hvdc",
        "materialize_mmc_native_probes",
        details,
    )


def _definition(root: ET.Element, name: str) -> ET.Element:
    matches = [
        item
        for item in root.findall("./definitions/Definition")
        if item.get("name") == name
    ]
    if len(matches) != 1 or matches[0].find("schematic") is None:
        raise _error(
            "A probe canvas must have one native definition.",
            definition=name,
            matches=len(matches),
        )
    return matches[0]


def _position(
    component: ET.Element, offset: tuple[int, int] = (0, 0)
) -> tuple[int, int]:
    if offset != (0, 0) and component.get("orient", "0") != "0":
        raise _error(
            "This audited probe profile requires unrotated component ports.",
            owner=component.get("id"),
        )
    return int(component.attrib["x"]) + offset[0], int(component.attrib["y"]) + offset[
        1
    ]


def _require_port(
    document: dict, definition: str, name: str, offset: tuple[int, int], model: str
) -> None:
    matches = document.get(definition, ())
    ports = [port for match in matches for port in match.ports if port.name == name]
    if (
        len(matches) != 1
        or len(ports) != 1
        or (ports[0].x, ports[0].y) != offset
        or ports[0].model != model
        or ports[0].condition != "true"
    ):
        raise _error(
            "The physical probe port no longer matches its audited profile.",
            definition=definition,
            port=name,
        )


def _require_wire_anchor(definition: ET.Element, point: tuple[int, int]) -> None:
    for wire in definition.findall("./schematic/Wire"):
        x, y = int(wire.get("x", "0")), int(wire.get("y", "0"))
        if any(
            (x + int(vertex.get("x", "0")), y + int(vertex.get("y", "0"))) == point
            for vertex in wire.findall("vertex")
        ):
            return
    raise _error(
        "The project does not connect the selected library port at its declared position.",
        definition=definition.get("name"),
        point=list(point),
    )


def _contains(
    left: tuple[int, int], right: tuple[int, int], point: tuple[int, int]
) -> bool:
    return (
        _cross(left, right, point) == 0
        and min(left[0], right[0]) <= point[0] <= max(left[0], right[0])
        and min(left[1], right[1]) <= point[1] <= max(left[1], right[1])
    )


def _cross(a: tuple, b: tuple, c: tuple) -> int:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a: tuple, b: tuple, c: tuple, d: tuple) -> bool:
    if any(_contains(a, b, point) for point in (c, d)) or any(
        _contains(c, d, point) for point in (a, b)
    ):
        return True
    return (
        _cross(a, b, c) * _cross(a, b, d) < 0 and _cross(c, d, a) * _cross(c, d, b) < 0
    )


class _ProbeWriter:
    def __init__(self, root: ET.Element) -> None:
        self.used = {node.get("id") for node in root.iter() if node.get("id")}
        self.original_ids = set(self.used)
        self.canvas_names = {
            node.find("schematic"): node.get("name")
            for node in root.findall("./definitions/Definition")
        }
        self.next_id = 1_800_000_000
        self.probes: list[dict[str, Any]] = []
        self.routes: list[dict[str, Any]] = []

    def identifier(self) -> str:
        while str(self.next_id) in self.used:
            self.next_id += 1
        result = str(self.next_id)
        self.used.add(result)
        return result

    def component(
        self,
        canvas: ET.Element,
        definition: str,
        point: tuple[int, int],
        parameters: dict,
    ) -> str:
        identifier = self.identifier()
        component = ET.SubElement(
            canvas,
            "User",
            {
                "classid": "UserCmp",
                "id": identifier,
                "defn": definition,
                "name": definition,
                "x": str(point[0]),
                "y": str(point[1]),
                "w": "120",
                "h": "36",
                "orient": "0",
                "z": "0",
                "link": "-1",
                "q": "4",
            },
        )
        paramlist = ET.SubElement(component, "paramlist", {"name": "", "link": "-1"})
        for name, value in parameters.items():
            ET.SubElement(paramlist, "param", {"name": name, "value": str(value)})
        return identifier

    def wire(
        self, canvas: ET.Element, points: list[tuple[int, int]], *, kind: str = "data"
    ) -> str:
        points = [
            point
            for index, point in enumerate(points)
            if index == 0 or point != points[index - 1]
        ]
        if len(points) < 2 or any(
            left[0] != right[0] and left[1] != right[1]
            for left, right in pairwise(points)
        ):
            raise _error("Probe wires must have a nonempty orthogonal route.")
        x, y = min(point[0] for point in points), min(point[1] for point in points)
        identifier = self.identifier()
        wire = ET.SubElement(
            canvas,
            "Wire",
            {
                "classid": "Wire",
                "id": identifier,
                "name": "",
                "x": str(x),
                "y": str(y),
                "w": str(max(point[0] for point in points) - x),
                "h": str(max(point[1] for point in points) - y),
                "orient": "0",
            },
        )
        for px, py in points:
            ET.SubElement(wire, "vertex", {"x": str(px - x), "y": str(py - y)})
        self.routes.append(
            {
                "owner": identifier,
                "definition": self.canvas_names[canvas],
                "kind": kind,
                "points": points,
            }
        )
        return identifier

    def verify_routes(self, root: ET.Element, documents: dict) -> None:
        for name in {route["definition"] for route in self.routes}:
            routes = [route for route in self.routes if route["definition"] == name]
            for index, route in enumerate(routes):
                for other in routes[:index]:
                    if any(
                        _intersects(a, b, c, d)
                        for a, b in pairwise(route["points"])
                        for c, d in pairwise(other["points"])
                    ):
                        raise _error(
                            "New probe wires would contact each other.",
                            definition=name,
                            wire=route["owner"],
                            other_wire=other["owner"],
                        )
            definition = _definition(root, name)
            ports = []
            for component in _components(definition):
                reference = component.get("defn") or component.get("definition") or ""
                namespace, _, local_name = reference.partition(":")
                matches = documents.get(namespace, {}).get(local_name, ())
                if len(matches) != 1:
                    raise _error(
                        "Route validation requires exact component port metadata.",
                        reference=reference,
                    )
                for port in matches[0].ports:
                    point = absolute_port(
                        (int(component.get("x", "0")), int(component.get("y", "0"))),
                        (port.x, port.y),
                        int(component.get("orient", "0")),
                    )
                    ports.append((point, _normalized_kind(port), component.get("id")))
            old_wires = []
            for wire in definition.findall("./schematic/Wire"):
                if wire.get("id") in self.original_ids:
                    x, y = int(wire.get("x", "0")), int(wire.get("y", "0"))
                    vertices = [
                        (x + int(v.get("x", "0")), y + int(v.get("y", "0")))
                        for v in wire.findall("vertex")
                    ]
                    old_wires.append(
                        (wire.get("id"), list(pairwise(vertices)))
                    )
            for route in [item for item in self.routes if item["definition"] == name]:
                source = route["points"][0]
                segments = list(pairwise(route["points"]))
                for point, kind, owner in ports:
                    if any(_contains(a, b, point) for a, b in segments) and (
                        kind != route["kind"] or (owner in self.original_ids and point != source)
                    ):
                        raise _error(
                            "A probe wire would contact an unrelated component port.",
                            definition=name,
                            wire=route["owner"],
                            component=owner,
                            point=list(point),
                        )
                for owner, existing in old_wires:
                    if any(_contains(a, b, source) for a, b in existing):
                        continue
                    if any(
                        _intersects(a, b, c, d)
                        for a, b in segments
                        for c, d in existing
                    ):
                        raise _error(
                            "A probe wire would contact an unrelated existing wire.",
                            definition=name,
                            wire=route["owner"],
                            existing_wire=owner,
                        )

    def output(
        self,
        definition: ET.Element,
        name: str,
        units: str,
        point: tuple[int, int],
        **source: Any,
    ) -> None:
        canvas = definition.find("schematic")
        owner = self.component(
            canvas,
            "master:pgb",
            point,
            {
                "Name": name,
                "Group": "",
                "UseSignalName": 0,
                "enab": 1,
                "Display": 1,
                "Scale": 1,
                "Units": units,
                "mrun": 0,
                "Pol": 0,
                "Max": 1000 if units == "kV" else 20,
                "Min": -1000 if units == "kV" else -20,
            },
        )
        self.probes.append(
            {
                "name": name,
                "parent_definition": definition.get("name"),
                "pgb_owner": owner,
                "units": units,
                **source,
            }
        )

    def signal(
        self,
        definition: ET.Element,
        name: str,
        units: str,
        signal: str,
        point: tuple[int, int],
        **source: Any,
    ) -> None:
        canvas = definition.find("schematic")
        self.component(
            canvas, "master:datalabel", (point[0] - 36, point[1]), {"Name": signal}
        )
        self.wire(canvas, [(point[0] - 36, point[1]), point])
        self.output(definition, name, units, point, source_signal=signal, **source)

    def voltage(
        self,
        definition: ET.Element,
        name: str,
        terminals: tuple[tuple[int, int], tuple[int, int]],
        point: tuple[int, int],
        output_point: tuple[int, int],
        *,
        bottom_clearance: int = 0,
        **source: Any,
    ) -> None:
        canvas = definition.find("schematic")
        top, bottom = terminals
        x, y = point
        signal = name + "_MEASURED"
        meter_owner = self.component(
            canvas, "master:voltmeter", point, {"Name": signal}
        )
        self.wire(canvas, [top, (x, top[1]), point], kind="electrical")
        self.wire(
            canvas,
            [
                bottom,
                (bottom[0], bottom[1] + bottom_clearance),
                (x, bottom[1] + bottom_clearance),
                (x, y + 36),
            ],
            kind="electrical",
        )
        self.signal(
            definition,
            name,
            "kV",
            signal,
            output_point,
            meter_owner=meter_owner,
            meter_position=list(point),
            terminals=[list(top), list(bottom)],
            **source,
        )


def materialize_native_fault_probes(
    source: str | Path,
    destination: str | Path,
    *,
    master_path: str | Path,
    library_path: str | Path,
) -> dict[str, Any]:
    """Add measured cell voltages, gate inputs and selected midpoint-fault signals."""
    raw_sources = [Path(value) for value in (source, master_path, library_path)]
    raw_target = Path(destination)
    paths = [path.resolve() for path in raw_sources]
    target = raw_target.resolve()
    if any(path.is_symlink() or not path.is_file() for path in raw_sources):
        raise _error("Probe inputs must be regular immutable files.")
    if target in paths or raw_target.exists() or raw_target.is_symlink():
        raise BackendError(
            "MMC_BUILD_CONFLICT",
            "The probe destination must be new and distinct from its sources.",
            "hvdc",
            "materialize_mmc_native_probes",
            {},
        )
    payloads = [path.read_bytes() for path in paths]
    root = ET.fromstring(payloads[0])
    master = read_definition_metadata_document(payloads[1])
    library = read_definition_metadata_document(payloads[2])
    if any(
        ET.fromstring(payload).get("version") != "4.6.2" for payload in payloads[:2]
    ):
        raise _error("The physical probe project and Master must use PSCAD 4.6.2 XML.")
    library_version = ET.fromstring(payloads[2]).get("version")
    cell_records, gate_records = (
        library.get("FullCellR_n", ()),
        library.get("FiringHBridge", ()),
    )
    if len(cell_records) != 1 or len(gate_records) != 1:
        raise _error("The physical cell and firing definitions must be unique.")
    bottom = [port for port in cell_records[0].ports if port.name == "Nbtm"]
    block = [port for port in gate_records[0].ports if port.name == "Block"]
    if len(bottom) != 1 or len(block) != 1:
        raise _error("The physical terminal and gate input must be unique.")
    profile = (bottom[0].x, bottom[0].y, block[0].x, block[0].y)
    profiles = {
        (0, 54, 0, 72): "official_462",
        (0, 36, 18, 72): "historical_derived_462",
    }
    if profile not in profiles:
        raise _error(
            "The library has an unaudited physical port layout.", profile=list(profile)
        )
    if library_version != "4.6.2" and not (
        library_version == "4.6.1" and profiles[profile] == "historical_derived_462"
    ):
        raise _error(
            "The library version is outside the audited source profiles.",
            version=library_version,
        )
    bottom_offset, block_offset = profile[:2], profile[2:]
    for name, port, offset, model in (
        ("voltmeter", "N1", (0, 0), "Natural"),
        ("voltmeter", "N2", (0, 36), "Natural"),
        ("pgb", "Signl", (0, 0), "Transfer"),
        ("datalabel", "A", (0, 0), "Transfer"),
    ):
        _require_port(master, name, port, offset, model)
    for name, port, offset, model in (
        ("FullCellR_n", "Ntop", (0, -54), "Natural"),
        ("FullCellR_n", "Nbtm", bottom_offset, "Natural"),
        ("FullCellR_n", "Vc:DimC", (54, -18), "Transfer"),
        ("FiringHBridge", "Block", block_offset, "Transfer"),
    ):
        _require_port(library, name, port, offset, model)
    if (
        library["FullCellR_n"][0].parameters.get("SumVc0") is None
        or library["FullCellR_n"][0].parameters["SumVc0"].unit != "kV"
    ):
        raise _error("The cell capacitor-voltage scale must be declared in kV.")
    main = _definition(root, "Main")
    pole = _definition(root, "MMC_Hb_Pole_PWM")
    cells = sorted(
        [
            item
            for item in _components(pole)
            if (item.get("defn") or "").endswith(":FullCellR_n")
        ],
        key=lambda item: int(item.get("y", "0")),
    )
    gates = sorted(
        [
            item
            for item in _components(pole)
            if (item.get("defn") or "").endswith(":FiringHBridge")
        ],
        key=lambda item: int(item.get("y", "0")),
    )
    if len(cells) != 2 or len(gates) != 2:
        raise _error(
            "A full-bridge pole must have two cell stacks and two firing blocks."
        )
    for cell in cells:
        for offset in ((0, -54), bottom_offset, (54, -18)):
            _require_wire_anchor(pole, _position(cell, offset))
    for gate in gates:
        _require_wire_anchor(pole, _position(gate, block_offset))
    switches = [
        item
        for item in _components(main)
        if item.get("defn") == "master:fault_sw"
        and dict(_parameters(item)).get("Name") == "DC_flt_Mid"
    ]
    if len(switches) != 1 or dict(_parameters(switches[0])).get("Iflt") != "IFlt_Mid":
        raise _error("The midpoint fault command/current source is not unique.")
    writer = _ProbeWriter(root)
    main_x = max(int(item.get("x", "0")) for item in main.iter()) + 216
    writer.signal(
        main,
        "MMC_DC_FAULT_ACTIVE",
        "1",
        "DC_flt_Mid",
        (main_x, 90),
        switch_owner=switches[0].get("id"),
        active_value=1,
    )
    writer.signal(
        main,
        "MMC_DC_FAULT_CURRENT",
        "kA",
        "IFlt_Mid",
        (main_x, 180),
        switch_owner=switches[0].get("id"),
    )
    for station in (1, 2):
        nodes = []
        for polarity in ("P", "N"):
            found = [
                item
                for item in _components(main)
                if item.get("defn") == "master:nodelabel"
                and dict(_parameters(item)).get("Name") == f"T{station}{polarity}"
            ]
            if len(found) != 1:
                raise _error(
                    "The measured DC terminal node is not unique.",
                    station=station,
                    polarity=polarity,
                )
            nodes.append(_position(found[0]))
        if nodes[0][0] != nodes[1][0] or nodes[1][1] - nodes[0][1] != 90:
            raise _error(
                "The local DC meter slot no longer matches the audited station geometry.",
                station=station,
            )
        writer.voltage(
            main,
            f"MMC_VDC_T{station}",
            (nodes[0], nodes[1]),
            (nodes[0][0], nodes[0][1] + 36),
            (main_x, 180 + station * 90),
            polarity="positive_minus_negative",
        )
    pole_x = max(int(item.get("x", "0")) for item in pole.iter()) + 216
    for index, (label, cell, gate) in enumerate(zip(("TOP", "BTM"), cells, gates)):
        cx, cy = _position(cell)
        writer.voltage(
            pole,
            f"MMC_V_INSERTED_{label}",
            (_position(cell, (0, -54)), _position(cell, bottom_offset)),
            (cx - 126, cy - 54),
            (pole_x, 90 + index * 90),
            bottom_clearance=54 - bottom_offset[1],
            polarity="Ntop_minus_Nbtm",
            cell_owner=cell.get("id"),
        )
        block_point = _position(gate, block_offset)
        point = (pole_x, block_point[1])
        writer.wire(pole.find("schematic"), [block_point, point])
        writer.output(
            pole,
            f"MMC_BLOCKED_{label}",
            "1",
            point,
            source_point=list(block_point),
            gate_owner=gate.get("id"),
            active_value=1,
        )
        cap_point = _position(cell, (54, -18))
        point = (cap_point[0] + 18, cap_point[1] - 72)
        writer.wire(
            pole.find("schematic"), [cap_point, (cap_point[0], point[1]), point]
        )
        writer.output(
            pole,
            f"MMC_VCAP_{label}",
            "kV",
            point,
            source_point=list(cap_point),
            cell_owner=cell.get("id"),
            dimension="DimC",
        )
    writer.verify_routes(
        root,
        {
            "master": master,
            ET.fromstring(payloads[2]).get("name"): library,
            root.get("name"): read_definition_metadata_document(payloads[0]),
        },
    )
    hashes = [hashlib.sha256(payload).hexdigest() for payload in payloads]
    if any(
        hashlib.sha256(path.read_bytes()).hexdigest() != before
        for path, before in zip(paths, hashes)
    ):
        raise _error("A probe input changed during materialization.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=False)
    observed = ET.parse(target).getroot()
    for probe in writer.probes:
        matches = [
            item
            for item in _components(observed)
            if item.get("id") == probe["pgb_owner"]
        ]
        if (
            len(matches) != 1
            or dict(_parameters(matches[0])).get("Units") != probe["units"]
        ):
            raise _error(
                "A physical output probe failed XML read-back.",
                owner=probe["pgb_owner"],
            )
    return {
        "source": str(paths[0]),
        "destination": str(target),
        "source_sha256_before": hashes[0],
        "source_sha256_after": hashlib.sha256(paths[0].read_bytes()).hexdigest(),
        "master_sha256": hashes[1],
        "library_sha256": hashes[2],
        "library_port_profile": profiles[profile],
        "library_xml_version": library_version,
        "destination_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "probes": writer.probes,
        "routes": writer.routes,
        "route_contacts_verified": True,
        "status": "PROBES_MATERIALIZED",
        "licensed_acceptance": "NOT_RUN",
    }
