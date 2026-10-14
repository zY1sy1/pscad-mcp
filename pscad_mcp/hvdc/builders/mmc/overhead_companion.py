"""Four-terminal native overhead module with explicit conductor ordering."""

import copy
from pathlib import Path
from xml.etree import ElementTree as ET

from ....core.definition_metadata import read_definition_metadata_document
from .avm_companion import _paramlist
from .cable_companion import (
    _geometry_sha,
    _module_definition,
    _parameters,
    _set_parameter,
    _xml_sha,
)
from .overhead_constants import verify_overhead_constants_receipt


def append_native_overhead_link(root, *, constants_evidence, source_project, master_path, local_constants):
    model, constants, files, hashes = verify_overhead_constants_receipt(constants_evidence, source_project, master_path)
    source_root = ET.parse(source_project).getroot()
    row = source_root.find("./definitions/Definition[@name='DCTL']")
    configuration = source_root.find(".//Wire[@classid='TLine']")
    if root.find("./definitions/Definition[@name='DCTL']") is not None:
        raise ValueError("Destination already contains an overhead definition")
    master_bytes = Path(master_path).read_bytes()
    metadata = read_definition_metadata_document(master_bytes)
    interfaces = metadata.get("tline_interface", ())
    if len(interfaces) != 1:
        raise ValueError("Native overhead Master interface is missing or ambiguous")
    for name, y in (("A", -18), ("C", 18)):
        ports = [p for p in interfaces[0].ports if p.name == name]
        if len(ports) != 1 or (ports[0].x, ports[0].y) != (-18, y):
            raise ValueError("Native overhead conductor interface geometry changed")
    interface_definition = ET.fromstring(master_bytes).find("./definitions/Definition[@name='tline_interface']")
    defaults = {p.get("name"): (p.findtext("value") or "").strip() for p in interface_definition.findall("./form//parameter")}
    prototypes = []
    for end in range(2):
        interface = ET.Element("User", {"classid": "UserCmp", "defn": "master:tline_interface", "id": str(end), "q": "4", "link": "-1"})
        _paramlist(interface, {**defaults, "Name": constants["segment"], "NC": "2", "View": "0",
                              "send_recv": str(end + 1), "dim_s": "0", "dim_r": "0", "alien": "2"}, name="", link="-1", crc="0")
        prototypes.append(interface)
    original_hash = _xml_sha(row)
    row = copy.deepcopy(row)
    root.find("definitions").append(row)
    module, interfaces, wires = _module_definition(root, source_root, constants["segment"],
                                                  interface_prototypes=prototypes, overhead=True)
    line = copy.deepcopy(configuration)
    scope = root.get("name")
    line.attrib.update(name=scope + ":DCTL", defn=scope + ":DCTL", x="342", y="108", send="-1", recv="-1")
    wrapper = line.find("User")
    wrapper.attrib.update(name=scope + ":DCTL", defn=scope + ":DCTL")
    for name, value in {"Name": constants["segment"], "Length": f"{constants['length_km']:.15g} [km]",
                        "const_path": str(Path(local_constants).resolve()), "gen_cnst": "0"}.items():
        _set_parameter(wrapper, name, value)
    module.find("schematic").append(line)
    return {"model": model, "constants": constants, "files": files, "input_hashes": hashes,
            "module": module, "configuration": line, "module_wires": wires,
            "source_definition_receipts": {"DCTL": original_hash, "configuration": _xml_sha(configuration),
                                           "interfaces": interfaces, "master_interface": _xml_sha(interface_definition)},
            "geometry_semantics_sha256": _geometry_sha(row)}


def audit_native_overhead_link(library, receipt):
    root = ET.parse(library).getroot()
    module = root.find("./definitions/Definition[@name='MMCOverheadLink']")
    geometry = root.find("./definitions/Definition[@name='DCTL']")
    if module is None or geometry is None or _geometry_sha(geometry) != receipt["link_topology"]["geometry_semantics_sha256"]:
        raise ValueError("Native overhead geometry or module changed")
    ports = {p.get("name") for p in module.findall("./svg/port")}
    if ports != {"SEND_POS", "SEND_NEG", "RECV_POS", "RECV_NEG"}:
        raise ValueError("Native overhead terminals are incomplete")
    canvas = module.find("schematic")
    interfaces = canvas.findall("./User[@defn='master:tline_interface']")
    configurations = canvas.findall("./Wire[@classid='TLine']")
    if len(interfaces) != 2 or len(configurations) != 1 or len(canvas.findall("./Wire[@classid='WireOrthogonal']")) != 4:
        raise ValueError("Native overhead module has a missing connection or bypass")
    for index, interface in enumerate(interfaces):
        values = _parameters(interface)
        expected = {"Name": receipt["link_name"], "NC": "2", "View": "0", "alien": "2",
                    "send_recv": str(index + 1), "dim_s": "0", "dim_r": "0"}
        if any(values.get(k) != v for k, v in expected.items()):
            raise ValueError("Native overhead conductor order or endpoint changed")
    for route in receipt["link_topology"]["module_wires"]:
        wire = canvas.find(f"./Wire[@id='{route['wire_id']}']")
        interface = canvas.find(f"./User[@id='{route['interface_id']}']")
        node = canvas.find(f"./User[@id='{route['node_id']}']")
        if wire is None or interface is None or node is None or _parameters(node).get("Name") != route["port"]:
            raise ValueError("Native overhead pole connection is incomplete")
        vertices = [[int(wire.get("x")) + int(v.get("x")), int(wire.get("y")) + int(v.get("y"))] for v in wire.findall("vertex")]
        terminal_y = int(interface.get("y")) + (-18 if route["native_port"] == "A" else 18)
        if vertices != route["vertices"] or vertices[-1] != [int(interface.get("x")) - 18, terminal_y]:
            raise ValueError("Native overhead pole connection or conductor ordering changed")
    values = _parameters(configurations[0].find("User"))
    if (configurations[0].get("defn") != root.get("name") + ":DCTL"
            or values.get("Name") != receipt["link_name"] or values.get("Dim") != "2"
            or values.get("gen_cnst") != "0" or Path(values.get("const_path", "")).resolve() != Path(receipt["constants_path"]).resolve()):
        raise ValueError("Native overhead configuration differs from its frozen constants")
    return {"coupled_overhead_count": 1, "conductor_order_verified": True}
