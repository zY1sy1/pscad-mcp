"""Explicit command routing in derived copies of the installed PWM circuit.

Vendor definitions are read at runtime. No vendor definition bodies are
distributed in the repository. A manifest records the original and derived
identities; routing evidence alone never establishes physical acceptance.
"""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from itertools import pairwise
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from ....topology.geometry import absolute_port
from .avm_companion import _definition, _script
from .fault_channels import _new_target, _regular, _write_new_xml

COMMANDS = {
    "active_power_order": ("P_ORDER", 0.0, "pu", [-1.0, -0.8, 0.0, 0.8, 1.0]),
    "reactive_power_order": ("Q_ORDER", 0.0, "pu", [-0.1, 0.0, 0.1]),
    "reset_command": ("RESET_CMD", 0.0, "1", [0, 1, 0.0, 1.0]),
    "block_command": ("BLOCK_CMD", 0.0, "1", [0, 1, 0.0, 1.0]),
    "ac_breaker_command": ("AC_CLOSE", 1.0, "1", [0, 1, 0.0, 1.0]),
    "dc_breaker_command": ("DC_CLOSE", 1.0, "1", [0, 1, 0.0, 1.0]),
    "ac_fault_command": ("AC_FAULT", 0.0, "1", [0, 1, 0.0, 1.0]),
    "dc_fault_command": ("DC_FAULT", 0.0, "1", [0, 1, 0.0, 1.0]),
}


def _error(message: str, **details: Any) -> BackendError:
    return BackendError(
        "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED",
        message,
        "hvdc",
        "prepare_pwm_commands",
        details,
    )


def _params(element: ET.Element) -> dict[str, str]:
    return {
        p.get("name"): p.get("value", "") for p in element.findall("./paramlist/param")
    }


def _set(element: ET.Element, key: str, value: Any) -> None:
    group = element.find("paramlist")
    if group is None:
        group = ET.SubElement(element, "paramlist", {"name": "", "link": "-1"})
    items = group.findall(f"param[@name='{key}']")
    if len(items) > 1:
        raise _error(
            "A routed parameter is ambiguous.", owner=element.get("id"), parameter=key
        )
    item = items[0] if items else ET.SubElement(group, "param", {"name": key})
    item.set("value", str(value))


def append_reset_combiner(root: ET.Element) -> ET.Element:
    definition = _definition(
        root,
        "McpPwmResetOr",
        {
            "ORIGINAL": (-72, -36, "Transfer", "Input"),
            "COMMAND": (-72, 36, "Transfer", "Input"),
            "RESET": (72, 0, "Transfer", "Output"),
        },
        {},
    )
    for port in definition.findall("./svg/port"):
        if port.get("name") != "COMMAND":
            port.set("type", "Integer")
    _script(
        definition,
        "Dsdyn",
        "      $RESET = 0\n      IF ($ORIGINAL .NE. 0 .OR. $COMMAND .GE. 0.5) $RESET = 1\n",
    )
    _set(
        definition,
        "Description",
        "Original PI reset combined with explicit PWM reset command",
    )
    return definition


class _Editor:
    def __init__(self, root: ET.Element, master: ET.Element):
        self.root, self.master = root, master
        self.used = {e.get("id") for e in root.iter()}
        self.sequence = 2023000000
        self.namespace = root.get("name")
        self.routes: list[dict[str, Any]] = []
        self.probes: list[dict[str, Any]] = []

    def probe(
        self,
        canvas: ET.Element,
        signal: str,
        name: str,
        units: str,
        *,
        source: dict[str, Any],
    ) -> None:
        index = len(self.probes)
        x, y = 8820, 180 + index * 72
        self.label(canvas, signal, (x - 72, y))
        output = self.user(
            canvas,
            "master:pgb",
            x,
            y,
            {
                "Name": name,
                "Group": "MCP_PWM_INTERFACE",
                "Units": units,
                "Scale": "1.0",
                "Display": "1",
                "enab": "1",
                "UseSignalName": "0",
            },
        )
        self.wire(canvas, (x - 72, y), (x, y))
        self.probes.append(
            {
                "description": name,
                "signal": signal,
                "units": units,
                "owner": output.get("id"),
                "source": source,
            }
        )

    def identifier(self) -> str:
        self.sequence += 1
        while str(self.sequence) in self.used:
            self.sequence += 1
        value = str(self.sequence)
        self.used.add(value)
        return value

    def user(
        self,
        canvas: ET.Element,
        definition: str,
        x: int,
        y: int,
        parameters: dict[str, Any],
    ) -> ET.Element:
        item = ET.SubElement(
            canvas,
            "User",
            {
                "classid": "UserCmp",
                "name": definition,
                "defn": definition,
                "id": self.identifier(),
                "x": str(x),
                "y": str(y),
                "orient": "0",
                "w": "144",
                "h": "108",
                "z": str(self.sequence),
                "link": "-1",
                "q": "4",
            },
        )
        if definition.startswith("master:"):
            original = self.master.find(
                f"./definitions/Definition[@name='{definition.split(':')[1]}']"
            )
            if original is None:
                raise _error(
                    "A required Master definition is absent.", definition=definition
                )
            for parameter in original.findall("./form//parameter"):
                value = parameter.find("value")
                if value is not None and value.text is not None:
                    _set(item, parameter.get("name"), value.text)
        for key, value in parameters.items():
            _set(item, key, value)
        return item

    def label(
        self,
        canvas: ET.Element,
        signal: str,
        point: tuple[int, int],
        *,
        electrical: bool = False,
    ) -> ET.Element:
        return self.user(
            canvas,
            "master:nodelabel" if electrical else "master:datalabel",
            *point,
            {"Name": signal},
        )

    def wire(
        self, canvas: ET.Element, start: tuple[int, int], end: tuple[int, int]
    ) -> ET.Element:
        item = ET.SubElement(
            canvas,
            "Wire",
            {
                "classid": "WireOrthogonal",
                "id": self.identifier(),
                "name": "",
                "x": str(start[0]),
                "y": str(start[1]),
                "orient": "0",
                "w": str(abs(end[0] - start[0]) + 10),
                "h": str(abs(end[1] - start[1]) + 10),
            },
        )
        points = [(0, 0)]
        if start[0] != end[0] and start[1] != end[1]:
            points.append((end[0] - start[0], 0))
        points.append((end[0] - start[0], end[1] - start[1]))
        for x, y in points:
            ET.SubElement(item, "vertex", {"x": str(x), "y": str(y)})
        return item

    def clone_observed_switch(
        self, name: str, original: str, expression: str
    ) -> ET.Element:
        source = self.master.find(f"./definitions/Definition[@name='{original}']")
        if source is None or not source.findall("./script/segment"):
            raise _error(
                "The installed switch implementation is unavailable.",
                definition=original,
            )
        result = deepcopy(source)
        result.set("name", name)
        result.set("id", self.identifier())
        result.set("instances", "0")
        category = result.find("./form/category")
        parameter = ET.SubElement(
            category,
            "parameter",
            {
                "name": "McpClosed",
                "type": "Text",
                "desc": "Actual switch closure measured with OPENBR",
                "content_type": "Literal",
            },
        )
        ET.SubElement(parameter, "value").text = ""
        script = result.find("script")
        segment = script.find("segment[@name='Dsout']")
        if segment is None:
            segment = ET.SubElement(
                script,
                "segment",
                {"name": "Dsout", "classid": "CoreSegment", "id": self.identifier()},
            )
        segment.text = (
            segment.text or ""
        ).rstrip() + f"\n#OUTPUT REAL McpClosed {{{expression}}}\n"
        self.root.find("definitions").append(result)
        return result

    def reset_ports(
        self, definitions: dict[str, ET.Element], library: ET.Element
    ) -> None:
        pi = library.find("./definitions/Definition[@name='PIwithFreeze']")
        ports = [] if pi is None else pi.findall(".//port[@name='Rst']")
        if len(ports) != 1 or (
            ports[0].get("type"),
            ports[0].get("mode"),
            ports[0].get("x"),
            ports[0].get("y"),
        ) != ("Integer", "Input", "0", "-36"):
            raise _error("The real PI reset port differs from the audited contract.")
        append_reset_combiner(self.root)
        for name in ("VSCConverter", "VSCControl2"):
            definition = definitions[name]
            svg = definition.find("svg")
            if svg is None:
                raise _error(
                    "A control module has no typed port diagram.", definition=name
                )
            ET.SubElement(
                svg,
                "port",
                {
                    "name": "McpReset",
                    "model": "Transfer",
                    "type": "Real",
                    "mode": "Input",
                    "dim": "1",
                    "x": "-90",
                    "y": "-72",
                    "internal": "false",
                },
            ).text = "true"
            canvas = definition.find("schematic")
            self.user(canvas, "master:import", 7200, 216, {"Name": "McpReset"})
            self.label(canvas, "McpReset", (7236, 216))
        converter = definitions["VSCConverter"].find("schematic")
        children = [
            u
            for u in converter.findall("User")
            if u.get("defn", "").endswith(":VSCControl2")
        ]
        if len(children) != 1:
            raise _error("The converter's physical control instance is ambiguous.")
        child = children[0]
        point = absolute_port(
            (int(child.get("x")), int(child.get("y"))),
            (-90, -72),
            child.get("orient", "0"),
        )
        self.label(converter, "McpReset", point)
        self.routes.append(
            {
                "role": "reset_command",
                "module": "VSCConverter",
                "owner": child.get("id"),
                "port": "McpReset",
            }
        )
        canvas = definitions["VSCControl2"].find("schematic")
        controls = [
            u
            for u in canvas.findall("User")
            if u.get("defn") == "intermediate:PIwithFreeze"
        ]
        if len(controls) != 8:
            raise _error(
                "The audited control circuit must expose all eight PI resets.",
                observed=len(controls),
            )
        for index, control in enumerate(controls):
            point = absolute_port(
                (int(control.get("x")), int(control.get("y"))),
                (0, -36),
                control.get("orient", "0"),
            )
            wires = []
            for wire in canvas.findall("Wire"):
                vertices = wire.findall("vertex")
                coordinates = [
                    (
                        int(wire.get("x", "0")) + int(v.get("x")),
                        int(wire.get("y", "0")) + int(v.get("y")),
                    )
                    for v in vertices
                ]
                if any(
                    min(a[0], b[0]) <= point[0] <= max(a[0], b[0])
                    and min(a[1], b[1]) <= point[1] <= max(a[1], b[1])
                    and (a[0] == b[0] or a[1] == b[1])
                    for a, b in pairwise(coordinates)
                ):
                    wires.append(wire)
            if len(wires) > 1:
                raise _error(
                    "A PI reset has no unique original signal route.",
                    owner=control.get("id"),
                    wires=len(wires),
                )
            original_signal = "McpOriginalReset" + control.get("id")
            combined_signal = "McpCombinedReset" + control.get("id")
            if wires:
                wire = wires[0]
                vertices = wire.findall("vertex")
                coordinates = [
                    (
                        int(wire.get("x", "0")) + int(v.get("x")),
                        int(wire.get("y", "0")) + int(v.get("y")),
                    )
                    for v in vertices
                ]
                if point in (coordinates[0], coordinates[-1]):
                    kept = (
                        coordinates[1:] if point == coordinates[0] else coordinates[:-1]
                    )
                    moved = kept[0] if point == coordinates[0] else kept[-1]
                else:
                    kept = [coordinates[0]]
                    for a, b in pairwise(coordinates):
                        if min(a[0], b[0]) <= point[0] <= max(a[0], b[0]) and min(
                            a[1], b[1]
                        ) <= point[1] <= max(a[1], b[1]):
                            if a[1] == b[1]:
                                direction = 1 if b[0] > a[0] else -1
                                kept.extend(
                                    [
                                        (point[0] - 18 * direction, point[1]),
                                        (point[0] - 18 * direction, point[1] - 18),
                                        (point[0] + 18 * direction, point[1] - 18),
                                        (point[0] + 18 * direction, point[1]),
                                    ]
                                )
                            else:
                                direction = 1 if b[1] > a[1] else -1
                                kept.extend(
                                    [
                                        (point[0], point[1] - 18 * direction),
                                        (point[0] - 18, point[1] - 18 * direction),
                                        (point[0] - 18, point[1] + 18 * direction),
                                        (point[0], point[1] + 18 * direction),
                                    ]
                                )
                        kept.append(b)
                    moved = coordinates[0]
                for vertex in vertices:
                    wire.remove(vertex)
                if len(kept) > 1:
                    wire.set("x", str(kept[0][0]))
                    wire.set("y", str(kept[0][1]))
                    for x, y in kept:
                        ET.SubElement(
                            wire,
                            "vertex",
                            {"x": str(x - kept[0][0]), "y": str(y - kept[0][1])},
                        )
                else:
                    canvas.remove(wire)
                self.label(canvas, original_signal, moved)
            else:
                # The limiter PI has an originally unconnected reset input.
                # Give that original inactive input an explicit zero source;
                # the new reset command still drives the real Rst port.
                x, y = 7344, 432 + index * 180
                self.user(
                    canvas,
                    "master:consti",
                    x,
                    y,
                    {"Name": "McpInactiveReset", "Value": "0"},
                )
                self.label(canvas, original_signal, (x + 36, y))
            x, y = 7560, 432 + index * 180
            self.user(canvas, self.namespace + ":McpPwmResetOr", x, y, {})
            self.label(canvas, original_signal, (x - 72, y - 36))
            self.label(canvas, "McpReset", (x - 72, y + 36))
            self.label(canvas, combined_signal, (x + 72, y))
            self.label(canvas, combined_signal, point)
            self.probe(
                canvas,
                combined_signal,
                "MCP_PI_RESET_" + control.get("id"),
                "1",
                source={
                    "kind": "routed_reset_port",
                    "pi_owner": control.get("id"),
                    "port": "Rst",
                },
            )
            self.routes.append(
                {
                    "role": "reset_command",
                    "module": "VSCControl2",
                    "owner": control.get("id"),
                    "port": "Rst",
                    "original_reset_retained": original_signal,
                    "combined_signal": combined_signal,
                }
            )

    def dc_isolation(
        self, main: ET.Element, arms: list[ET.Element], arm_definition: ET.Element
    ) -> None:
        self.clone_observed_switch(
            "McpPwmDcBreaker", "breaker1", "1-E_BtoI(OPENBR($NBR,$SS))"
        )
        for station, arm in enumerate(arms):
            for pole, port_name in enumerate(("OUT_P", "OUT_N")):
                port = arm_definition.find(f"./svg/port[@name='{port_name}']")
                if port is None or port.get("model") != "Natural":
                    raise _error(
                        "A physical converter DC port is unavailable.", port=port_name
                    )
                point = absolute_port(
                    (int(arm.get("x")), int(arm.get("y"))),
                    (int(port.get("x")), int(port.get("y"))),
                    arm.get("orient", "0"),
                )
                matches = []
                for wire in main.findall("Wire"):
                    vertices = [
                        (
                            int(wire.get("x", "0")) + int(v.get("x")),
                            int(wire.get("y", "0")) + int(v.get("y")),
                        )
                        for v in wire.findall("vertex")
                    ]
                    if vertices and point in (vertices[0], vertices[-1]):
                        matches.append((wire, vertices))
                if len(matches) != 1:
                    raise _error(
                        "DC isolation needs one exact wire at the physical port.",
                        owner=arm.get("id"),
                        port=port_name,
                        matches=len(matches),
                    )
                wire, vertices = matches[0]
                line_point = vertices[-1] if vertices[0] == point else vertices[0]
                # PSCAD requires one consistent name for an electrical bus.
                original_node_names = []
                for label in main.findall("User"):
                    if label.get("defn") != "master:nodelabel":
                        continue
                    xy = (int(label.get("x", "0")), int(label.get("y", "0")))
                    if any(
                        min(a[0], b[0]) <= xy[0] <= max(a[0], b[0])
                        and min(a[1], b[1]) <= xy[1] <= max(a[1], b[1])
                        and (a[0] == b[0] or a[1] == b[1])
                        for a, b in pairwise(vertices)
                    ):
                        label.set("x", str(line_point[0]))
                        label.set("y", str(line_point[1]))
                        original_node_names.append(_params(label)["Name"])
                main.remove(wire)
                if len(set(original_node_names)) > 1:
                    raise _error("The original DC wire has ambiguous node names.")
                arm_net = f"McpDcArm{station}_{pole}"
                line_net = (
                    original_node_names[0]
                    if original_node_names
                    else f"McpDcLine{station}_{pole}"
                )
                self.label(main, arm_net, point, electrical=True)
                if not original_node_names:
                    self.label(main, line_net, line_point, electrical=True)
                x, y = 8100, 432 + (station * 2 + pole) * 216
                state = f"McpDcClosed{station}_{pole}"
                switch = self.user(
                    main,
                    self.namespace + ":McpPwmDcBreaker",
                    x,
                    y,
                    {
                        "NAME": "McpDcOpen",
                        "ENAB": "0",
                        "OPCUR": "1",
                        "RON": "0.005 [ohm]",
                        "ROFF": "1e8 [ohm]",
                        "McpClosed": state,
                        "IBR": f"McpDcI{station}_{pole}",
                    },
                )
                self.label(main, arm_net, (x - 36, y), electrical=True)
                self.label(main, line_net, (x + 36, y), electrical=True)
                self.routes.append(
                    {
                        "role": "dc_breaker_command",
                        "owner": switch.get("id"),
                        "parameter": "NAME",
                        "arm_owner": arm.get("id"),
                        "arm_port": port_name,
                        "line_net": line_net,
                        "arm_net": arm_net,
                        "state_signal": state,
                        "state_expression": "1-OPENBR",
                        "removed_wire": wire.get("id"),
                    }
                )
                self.probe(
                    main,
                    state,
                    f"MCP_DC_CLOSED_{station}_{pole}",
                    "1",
                    source={
                        "kind": "physical_switch_state",
                        "switch_owner": switch.get("id"),
                        "expression": "1-OPENBR",
                    },
                )


def materialize_pwm_command_interface(
    source: str | Path,
    destination: str | Path,
    *,
    master: str | Path,
    library: str | Path,
    rated_power_mw: float,
    reactive_power_mvar: float = 0.0,
    power_reversal_time_s: float = 0.5,
    dc_link_length_km: float | None = None,
) -> dict[str, Any]:
    original, master_path, library_path = (
        _regular(source),
        _regular(master),
        _regular(library),
    )
    target = _new_target(destination, (original, master_path, library_path))
    identities = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (original, master_path, library_path)
    }
    root, masters, companion = (
        ET.parse(original).getroot(),
        ET.parse(master_path).getroot(),
        ET.parse(library_path).getroot(),
    )
    definitions = {d.get("name"): d for d in root.findall("./definitions/Definition")}
    required = ("Main", "VSCConverter", "VSCControl2", "MMC_Hb_PWM")
    if root.get("version") != "4.6.2" or not all(
        name in definitions for name in required
    ):
        raise _error(
            "The source does not contain the audited physical PWM control circuit."
        )
    if any(name.startswith("McpPwm") for name in definitions):
        raise _error(
            "The source already contains a command interface; use its immutable original instead."
        )
    if (
        isinstance(rated_power_mw, bool)
        or not math.isfinite(rated_power_mw)
        or rated_power_mw <= 0
        or not math.isfinite(reactive_power_mvar)
    ):
        raise _error(
            "PWM command scaling requires finite power values with positive rated MW."
        )
    if (
        isinstance(power_reversal_time_s, bool)
        or not math.isfinite(power_reversal_time_s)
        or power_reversal_time_s <= 0
    ):
        raise _error("The requested reversal duration must be finite and positive.")
    if dc_link_length_km is not None:
        if (
            isinstance(dc_link_length_km, bool)
            or not math.isfinite(dc_link_length_km)
            or dc_link_length_km <= 0
        ):
            raise _error("The DC route length must be finite and positive.")
        segments = root.findall(".//Wire[@classid='TLine']")
        if len(segments) != 2:
            raise _error(
                "The audited two-terminal route must have two physical line segments."
            )
        for segment in segments:
            fields = {
                p.get("name"): p for p in segment.findall("./User/paramlist/param")
            }
            if "Length" not in fields:
                raise _error("A physical line length is not declared.")
            fields["Length"].set("value", str(dc_link_length_km / 2.0))
    main = definitions["Main"].find("schematic")
    if main is None:
        raise _error("The source has no physical Main schematic.")
    editor = _Editor(root, masters)
    converters = [
        u for u in main.findall("User") if u.get("defn", "").endswith(":VSCConverter")
    ]
    arms = [
        u for u in main.findall("User") if u.get("defn", "").endswith(":MMC_Hb_PWM")
    ]
    if (
        len(converters) != 2
        or len(arms) != 2
        or {_params(u).get("dmode") for u in converters} != {"0", "1"}
    ):
        raise _error(
            "Both physical controller modes and both switched converters must be present."
        )
    editor.reset_ports(definitions, companion)
    editor.dc_isolation(main, arms, definitions["MMC_Hb_PWM"])
    inputs = [item[0] for item in COMMANDS.values()] + [
        "ENABLE_T1",
        "ENABLE_T2",
        "DC_GROUND",
    ]
    outputs = {
        "P_REF": "McpPRef",
        "Q_REF": "McpQRef",
        "RESET_OUT": "McpResetCommand",
        "E_T1": "McpEnableT1",
        "E_T2": "McpEnableT2",
        "AC_OPEN": "McpAcOpen",
        "DC_OPEN": "McpDcOpen",
        "AC_FAULT_OUT": "McpAcFault",
        "DC_PN_FAULT": "McpDcPnFault",
        "DC_PG_FAULT": "McpDcPgFault",
    }
    ports = {
        name: (-72, -180 + index * 36, "Transfer", "Input")
        for index, name in enumerate(inputs)
    }
    ports.update(
        {
            name: (72, -180 + index * 36, "Transfer", "Output")
            for index, name in enumerate(outputs)
        }
    )
    definition = _definition(root, "McpPwmCommands", ports, {})
    integer_names = {
        "ENABLE_T1",
        "ENABLE_T2",
        "E_T1",
        "E_T2",
        "AC_FAULT_OUT",
        "DC_PN_FAULT",
        "DC_PG_FAULT",
    }
    for port in definition.findall("./svg/port"):
        if port.get("name") in integer_names:
            port.set("type", "Integer")
    _set(
        definition,
        "Description",
        "Routed PWM power, reset, block, physical isolation and imposed faults",
    )
    _script(
        definition,
        "Dsdyn",
        f"""      $P_REF = -{rated_power_mw:.15g} * $P_ORDER
      $Q_REF = {reactive_power_mvar:.15g} + {rated_power_mw:.15g} * $Q_ORDER
      $RESET_OUT = $RESET_CMD
      $AC_OPEN = 1.0 - $AC_CLOSE
      $DC_OPEN = 1.0 - $DC_CLOSE
      $E_T1 = $ENABLE_T1
      $E_T2 = $ENABLE_T2
      IF ($RESET_CMD .GE. 0.5 .OR. $BLOCK_CMD .GE. 0.5 .OR. $AC_CLOSE .LT. 0.5 .OR. $DC_CLOSE .LT. 0.5) THEN
        $E_T1 = 0
        $E_T2 = 0
      ENDIF
      $AC_FAULT_OUT = NINT($AC_FAULT)
      $DC_PN_FAULT = NINT($DC_FAULT * (1.0-$DC_GROUND))
      $DC_PG_FAULT = NINT($DC_FAULT * $DC_GROUND)
""",
    )
    adapter = editor.user(main, editor.namespace + ":McpPwmCommands", 7200, 360, {})
    bindings = []
    for index, (canonical, (port, initial, units, allowed)) in enumerate(
        COMMANDS.items()
    ):
        signal = "McpInput" + port
        source = editor.user(
            main,
            "master:const",
            6624,
            180 + index * 36,
            {"Name": "McpCommand" + port, "Value": initial},
        )
        editor.label(main, signal, (6660, 180 + index * 36))
        editor.label(main, signal, (7128, 180 + index * 36))
        bindings.append(
            {
                "canonical": canonical,
                "component": {"component_id": source.get("id")},
                "parameter_name": "Value",
                "allowed_values": allowed,
                "semantics": "active_high",
                "read_back": True,
                "units": units,
            }
        )
        editor.probe(
            main,
            signal,
            "MCP_COMMAND_" + canonical,
            units,
            source={"kind": "control_command", "source_owner": source.get("id")},
        )
    for port, signal in (("ENABLE_T1", "Dblk1P"), ("ENABLE_T2", "Dblk2P")):
        editor.label(main, signal, (7128, 180 + inputs.index(port) * 36))
    selector = editor.user(
        main,
        "master:const",
        6624,
        180 + 10 * 36,
        {"Name": "McpDcGroundCase", "Value": 0},
    )
    editor.label(main, "McpDcGroundCase", (6660, 540))
    editor.label(main, "McpDcGroundCase", (7128, 540))
    for name, signal in outputs.items():
        editor.label(main, signal, (7272, 180 + list(outputs).index(name) * 36))
    for converter in converters:
        mode = _params(converter)["dmode"]
        station = "T1" if mode == "0" else "T2"
        _set(converter, "Dblk", "McpEnable" + station)
        _set(converter, "qmode", "1")
        _set(converter, "Qref", "McpQRef")
        if mode == "1":
            _set(converter, "Pref", "McpPRef")
            _set(
                converter,
                "PrefRate",
                format(2.0 * rated_power_mw / power_reversal_time_s, ".15g"),
            )
        point = absolute_port(
            (int(converter.get("x")), int(converter.get("y"))),
            (-90, -72),
            converter.get("orient", "0"),
        )
        editor.label(main, "McpResetCommand", point)
        editor.routes.append(
            {
                "role": "block_command",
                "owner": converter.get("id"),
                "parameter": "Dblk",
                "signal": "McpEnable" + station,
                "polarity": "command_high_disables_firing",
                "original_enable_retained": "Dblk" + station[-1] + "P",
            }
        )
    editor.clone_observed_switch(
        "McpPwmAcBreaker",
        "breaker3",
        "MIN(1-E_BtoI(OPENBR($BrA,$SS)),1-E_BtoI(OPENBR($BrB,$SS)),1-E_BtoI(OPENBR($BrC,$SS)))",
    )
    for breaker in [
        u for u in main.findall("User") if u.get("defn") == "master:breaker3"
    ]:
        breaker.set("defn", editor.namespace + ":McpPwmAcBreaker")
        _set(breaker, "NAME", "McpAcOpen")
        _set(breaker, "OPCUR", "1")
        state = "McpAcClosed" + breaker.get("id")
        _set(breaker, "McpClosed", state)
        editor.routes.append(
            {
                "role": "ac_breaker_command",
                "owner": breaker.get("id"),
                "parameter": "NAME",
                "state_signal": state,
                "state_expression": "three_phase_1-OPENBR",
            }
        )
        editor.probe(
            main,
            state,
            "MCP_AC_CLOSED_" + breaker.get("id"),
            "1",
            source={
                "kind": "physical_switch_state",
                "switch_owner": breaker.get("id"),
                "expression": "three_phase_1-OPENBR",
            },
        )
    for component in main.findall("User"):
        values = _params(component)
        if values.get("Name") == "Fault Time":
            _set(component, "Value", "100")
        if (
            component.get("defn") == "master:fault_sw"
            and values.get("Name") == "DC_flt_2_PN"
        ):
            _set(component, "Name", "McpDcPnFault")
            _set(component, "OpCur", "1")
        if (
            component.get("defn") == "master:fault_sw"
            and values.get("Name") == "DC_flt_2_P"
        ):
            _set(component, "Name", "McpDcPgFault")
            _set(component, "OpCur", "1")
    ac_fault = main.find("User[@id='75317492']")
    ac_label = main.find("User[@id='597346103']")
    if (
        ac_fault is None
        or ac_fault.get("defn") != "master:tpflt"
        or ac_label is None
        or _params(ac_label).get("Name") != "AC_flt_2"
    ):
        raise _error("The audited terminal-2 AC fault branch is unavailable.")
    input_point = absolute_port(
        (int(ac_fault.get("x")), int(ac_fault.get("y"))),
        (36, 36),
        ac_fault.get("orient", "0"),
    )
    label_point = (int(ac_label.get("x")), int(ac_label.get("y")))
    ac_wires = [
        w
        for w in main.findall("Wire")
        if {input_point, label_point}
        <= {
            (
                int(w.get("x", "0")) + int(v.get("x")),
                int(w.get("y", "0")) + int(v.get("y")),
            )
            for v in w.findall("vertex")
        }
    ]
    if len(ac_wires) != 1:
        raise _error("The AC command label does not route to the physical IS input.")
    _set(ac_label, "Name", "McpAcFault")
    _set(ac_fault, "OpCur", "1")
    editor.routes.append(
        {
            "role": "ac_fault_command",
            "owner": ac_fault.get("id"),
            "definition": "master:tpflt",
            "port": "IS",
            "label_owner": ac_label.get("id"),
            "wire_owner": ac_wires[0].get("id"),
        }
    )
    observed_ac = editor.clone_observed_switch(
        "McpPwmAcFault",
        "tpflt",
        "MAX("
        + ",".join(
            f"1-E_BtoI(OPENBR($Br{branch},$SS))"
            for branch in ("AB", "BC", "CA", "AG", "BG", "CG")
        )
        + ")",
    )
    ac_fault.set("defn", editor.namespace + ":McpPwmAcFault")
    _set(ac_fault, "McpClosed", "McpAcFaultClosed")
    editor.probe(
        main,
        "McpAcFaultClosed",
        "MCP_AC_FAULT_CLOSED",
        "1",
        source={
            "kind": "physical_switch_state",
            "switch_owner": ac_fault.get("id"),
            "expression": "MAX(1-OPENBR)",
            "quantity": "fault_branch_closed",
        },
    )
    segment = observed_ac.find("./script/segment[@name='Dsout']")
    category = observed_ac.find("./form/category")
    for branch in ("AB", "BC", "CA", "AG", "BG", "CG"):
        parameter = ET.SubElement(
            category,
            "parameter",
            {
                "name": "McpClosed" + branch,
                "type": "Text",
                "desc": "Measured fault branch",
                "content_type": "Literal",
            },
        )
        ET.SubElement(parameter, "value").text = ""
        segment.text += (
            f"\n#OUTPUT REAL McpClosed{branch} {{1-E_BtoI(OPENBR($Br{branch},$SS))}}\n"
        )
        signal = "McpAcFaultClosed" + branch
        _set(ac_fault, "McpClosed" + branch, signal)
        editor.probe(
            main,
            signal,
            "MCP_AC_FAULT_CLOSED_" + branch,
            "1",
            source={
                "kind": "physical_switch_state",
                "switch_owner": ac_fault.get("id"),
                "expression": f"1-OPENBR(Br{branch})",
                "quantity": "fault_branch_closed",
            },
        )
    for phase, parameter in (("A", "Ifla"), ("B", "Iflb"), ("C", "Iflc")):
        signal = "McpAcFaultCurrent" + phase
        _set(ac_fault, parameter, signal)
        editor.probe(
            main,
            signal,
            "MCP_AC_FAULT_CURRENT_" + phase,
            "kA",
            source={
                "kind": "physical_measurement",
                "owner": ac_fault.get("id"),
                "parameter": parameter,
                "quantity": "physical_fault_branch_current",
            },
        )
    editor.clone_observed_switch(
        "McpPwmPgFault", "fault_sw", "1-E_BtoI(OPENBR($NBR,$SS))"
    )
    pg_switches = [
        u
        for u in main.findall("User")
        if u.get("defn") == "master:fault_sw"
        and _params(u).get("Name") == "McpDcPgFault"
    ]
    if len(pg_switches) != 1:
        raise _error("The physical pole-to-ground fault branch is not unique.")
    pg = pg_switches[0]
    pg.set("defn", editor.namespace + ":McpPwmPgFault")
    _set(pg, "McpClosed", "McpDcPgFaultClosed")
    editor.probe(
        main,
        "McpDcPgFaultClosed",
        "MCP_DC_PG_FAULT_CLOSED",
        "1",
        source={
            "kind": "physical_switch_state",
            "switch_owner": pg.get("id"),
            "expression": "1-OPENBR",
            "quantity": "fault_branch_closed",
        },
    )
    editor.probe(
        main,
        _params(pg)["Iflt"],
        "MCP_DC_PG_FAULT_CURRENT",
        "kA",
        source={
            "kind": "physical_measurement",
            "owner": pg.get("id"),
            "parameter": "Iflt",
            "quantity": "physical_fault_branch_current",
        },
    )
    for number in ("1", "2"):
        for field, signal, units in (
            ("P", "P" + number, "MW"),
            ("Q", "Q" + number, "MVAr"),
        ):
            meters = [
                u
                for u in main.findall("User")
                if u.get("defn") == "master:multimeter"
                and _params(u).get(field) == signal
            ]
            if len(meters) != 1 or _params(meters[0]).get("S") not in (
                "1",
                "1.0",
                "1 [MVA]",
                "1.0 [MVA]",
            ):
                raise _error(
                    "The raw three-phase power measurement base is not verified.",
                    signal=signal,
                )
            editor.probe(
                main,
                signal,
                "MCP_" + field + "_T" + number,
                units,
                source={
                    "kind": "physical_measurement",
                    "owner": meters[0].get("id"),
                    "parameter": field,
                    "base_mva": 1.0,
                },
            )
        for definition, signal, units, quantity in (
            ("master:voltmeter", "Edc" + number, "kV", "VDC"),
            ("master:ammeter", "Idc" + number, "kA", "IDC"),
        ):
            meters = [
                u
                for u in main.findall("User")
                if u.get("defn") == definition and _params(u).get("Name") == signal
            ]
            if len(meters) != 1:
                raise _error("The raw DC measurement is not unique.", signal=signal)
            editor.probe(
                main,
                signal,
                "MCP_" + quantity + "_T" + number,
                units,
                source={
                    "kind": "physical_measurement",
                    "owner": meters[0].get("id"),
                    "parameter": "Name",
                },
            )
    for path, digest in identities.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise _error(
                "A command-interface source changed during preparation.", path=path
            )
    _write_new_xml(root, target)
    return {
        "schema_version": 1,
        "source_identities": identities,
        "destination": str(target),
        "destination_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "model_accepted": False,
        "adapter_owner": adapter.get("id"),
        "command_bindings": bindings,
        "routes": editor.routes,
        "probes": editor.probes,
        "dc_fault_type_owner": selector.get("id"),
        "rated_power_mw": rated_power_mw,
        "reactive_power_mvar": reactive_power_mvar,
        "power_reversal_time_s": power_reversal_time_s,
        "dc_link_length_km": dc_link_length_km,
        "requires_physical_acceptance": True,
    }
