"""Hash-bound EMTDC controls in exclusive project copies.

The initial adapter supports scalar Main-page const/var Value signals only.
Changing a converter parameter, fault type, or shared module definition is not
equivalent to controlling that signal and is deliberately unsupported.
"""

from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import math
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from ....core.definition_metadata import read_definition_metadata_matches
from ...timing import normalize_timed_events

_CONTRACT_KEYS = (
    "schema_version",
    "source_hashes",
    "scenario_source",
    "time_basis",
    "schedule_source",
    "time_step_s",
    "output_step_s",
    "duration_s",
    "max_timing_error_s",
    "events",
    "event_channels",
)


def _error(message: str, **details: Any) -> BackendError:
    return BackendError(
        "HVDC_TIMED_CONTROL_UNAVAILABLE", message, "hvdc", "embedded_control", details
    )


def _identity(path: str | Path) -> dict[str, str]:
    raw = Path(path).expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise _error("A timed-control source must be a regular file.", path=str(raw))
    resolved = raw.resolve()
    return {
        "path": str(resolved),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def schedule_sha256(plan: Mapping[str, Any]) -> str:
    try:
        payload = {key: plan[key] for key in _CONTRACT_KEYS}
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        ).hexdigest()
    except (KeyError, ValueError, TypeError) as error:
        raise _error("The timed-control contract is not canonical JSON.") from error


def _verify_plan(plan: Mapping[str, Any]) -> None:
    expected = plan.get("schedule_sha256")
    if not isinstance(expected, str) or not hmac.compare_digest(
        schedule_sha256(plan), expected
    ):
        raise _error("The schedule hash changed after planning.")
    for item in [plan["scenario_source"], *plan["source_hashes"].values()]:
        observed = _identity(item["path"])
        if observed != item:
            raise _error(
                "An immutable timed-control input changed.",
                expected=item,
                observed=observed,
            )


def _main(root: ET.Element) -> ET.Element:
    definitions = root.findall("./definitions/Definition[@name='Main']")
    if len(definitions) != 1 or len(definitions[0].findall("schematic")) != 1:
        raise _error(
            "The embedded adapter requires exactly one Main definition and schematic."
        )
    return definitions[0].findall("schematic")[0]


def _owner(canvas: ET.Element, owner: str) -> ET.Element:
    matches = [item for item in canvas if item.get("id") == owner]
    if len(matches) != 1:
        raise _error(
            "The control owner is absent or ambiguous in its instance.",
            owner=owner,
            matches=len(matches),
        )
    return matches[0]


def _params(component: ET.Element) -> dict[str, str]:
    result = {}
    for item in component.findall("./paramlist/param"):
        name = item.get("name", "")
        if name in result:
            raise _error(
                "A component parameter is not unique.",
                owner=component.get("id"),
                parameter=name,
            )
        result[name] = item.get("value", "")
    return result


def _single_port(master: Path, definition: str, port: str, mode: str):
    matches = read_definition_metadata_matches(master, definition)
    if len(matches) != 1:
        raise _error("A Master definition is not unique.", definition=definition)
    ports = [item for item in matches[0].ports if item.name == port]
    if (
        len(ports) != 1
        or ports[0].mode != mode
        or ports[0].type != "Real"
        or ports[0].condition not in {None, "true"}
    ):
        raise _error(
            "The Master signal port is not uniquely unconditional.",
            definition=definition,
            port=port,
        )
    return ports[0]


def plan_embedded_control(
    source: str | Path,
    events: Sequence[Mapping[str, Any]],
    *,
    master_path: str | Path,
    time_step_s: float,
    output_step_s: float,
    duration_s: float,
    max_timing_error_s: float,
    source_hashes: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Bind and hash the complete event and output layout before mutation."""
    source_identity, master_identity = _identity(source), _identity(master_path)
    root = ET.parse(source_identity["path"]).getroot()
    if root.get("Target") != "EMTDC" or root.get("version") != "4.6.2":
        raise _error(
            "The embedded adapter is verified for PSCAD 4.6.2 EMTDC projects only."
        )
    values = {
        "time_step_s": time_step_s,
        "output_step_s": output_step_s,
        "duration_s": duration_s,
        "max_timing_error_s": max_timing_error_s,
    }
    for key, value in values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise _error("Timing settings must be finite positive seconds.", field=key)
    if max_timing_error_s < time_step_s + output_step_s - 1e-15:
        raise _error(
            "The requested bound is below integration plus output quantization."
        )
    canvas = _main(root)
    normalized = normalize_timed_events(events)
    if not normalized:
        raise _error("An embedded schedule must contain at least one event.")
    master = Path(master_identity["path"])
    replacement_port = _single_port(master, "const", "OUT", "Output")
    if replacement_port.dim != 1 or (replacement_port.x, replacement_port.y) != (36, 0):
        raise _error("The replacement const definition has no audited scalar OUT port.")
    pgb_port = _single_port(master, "pgb", "Signl", "Input")
    if (pgb_port.x, pgb_port.y) != (0, 0):
        raise _error("The Master output-channel attachment point changed.")
    used_ids = {item.get("id") for item in root.iter() if item.get("id")}
    next_id = 2_000_000_000
    channels: dict[str, dict[str, Any]] = {}
    previous = {}
    for event in normalized:
        target = event.get("target")
        if not isinstance(target, Mapping) or set(target) != {
            "instance_path",
            "owner",
            "definition",
            "parameter",
        }:
            raise _error(
                "Embedded events require an exact instance, owner, definition and parameter."
            )
        if (
            target["instance_path"] != "Main"
            or target["definition"] not in {"master:const", "master:var"}
            or target["parameter"] != "Value"
        ):
            raise _error(
                "This embedded signal target is not supported.",
                target=dict(target),
                supported=["Main/master:const/Value", "Main/master:var/Value"],
            )
        owner = str(target["owner"])
        if not owner.isdigit():
            raise _error("A native PSCAD component owner must be numeric.")
        target = {**target, "owner": owner}
        event["target"] = target
        component = _owner(canvas, owner)
        if (
            component.get("defn") != target["definition"]
            or component.get("orient", "0") != "0"
        ):
            raise _error(
                "The control definition or orientation differs from the supported binding.",
                target=target,
            )
        port = _single_port(master, target["definition"].split(":")[1], "OUT", "Output")
        if port.dim != 1 or (port.x, port.y) != (36, 0):
            raise _error("The control output is not the audited scalar OUT port.")
        for field in ("end_time_s", "before_value", "after_value"):
            if field not in event:
                raise _error(
                    "Embedded controls require bounded intervals and before/after values.",
                    field=field,
                )
        if event["end_time_s"] >= duration_s or event["time_s"] == 0:
            raise _error(
                "An event needs observable samples before its rise and after its fall."
            )
        if not isinstance(event.get("units"), str) or not event["units"].strip():
            raise _error("An event must declare its output units.")
        try:
            initial = float(_params(component)["Value"])
        except (KeyError, ValueError) as error:
            raise _error(
                "The original control Value is not a finite literal.", target=target
            ) from error
        expected_before = (
            previous[owner]["after_value"] if owner in previous else initial
        )
        if event["before_value"] != expected_before or not math.isfinite(initial):
            raise _error(
                "The scheduled before value differs from the source/preceding event.",
                target=target,
            )
        if event["value"] in {event["before_value"], event["after_value"]}:
            raise _error("Each bounded event must expose both observable edges.")
        if owner not in channels:
            while str(next_id) in used_ids:
                next_id += 1
            output_owner = str(next_id)
            used_ids.add(output_owner)
            next_id += 1
            while str(next_id) in used_ids:
                next_id += 1
            definition_id = str(next_id)
            used_ids.add(definition_id)
            next_id += 1
            channels[owner] = {
                "channel_id": f"EMT_EVENT_{owner}",
                "description": f"EMT_EVENT_{owner}",
                "role": "control_command",
                "instance_path": "Main",
                "owner": output_owner,
                "definition": "master:pgb",
                "port": "Signl",
                "units": event["units"],
                "polarity": {
                    "inactive": event["before_value"],
                    "active": event["value"],
                },
                "control_owner": owner,
                "control_definition": f"EMT_Control_{owner}",
                "definition_id": definition_id,
                "x": int(component.get("x", "0")) + port.x,
                "y": int(component.get("y", "0")) + port.y,
            }
        elif channels[owner]["units"] != event["units"]:
            raise _error("Events on one control cannot change output units.")
        event["event_selector"] = {
            key: channels[owner][key]
            for key in ("description", "instance_path", "owner", "definition", "port")
        }
        previous[owner] = event
    identities = deepcopy(dict(source_hashes or {"project": source_identity}))
    if "master" in identities and identities["master"] != master_identity:
        raise _error(
            "The requested Master identity changed before planning.",
            expected=identities["master"],
            observed=master_identity,
        )
    identities["master"] = master_identity
    plan = {
        "schema_version": 1,
        "source_hashes": identities,
        "scenario_source": source_identity,
        "time_basis": "EMTDC",
        "schedule_source": "embedded_control",
        **values,
        "events": normalized,
        "event_channels": list(channels.values()),
    }
    plan["schedule_sha256"] = schedule_sha256(plan)
    _verify_plan(plan)
    return plan


def _script(events: Sequence[Mapping[str, Any]]) -> str:
    def literal(value):
        value = repr(float(value))
        return value.replace("e", "D") + ("D0" if "e" not in value else "")

    lines = [f"      $OUT = {literal(events[0]['before_value'])}"]
    for event in events:
        lines += [
            f"      IF (TIME .GE. {literal(event['time_s'])}) THEN",
            f"        $OUT = {literal(event['value'])}",
            "      ENDIF",
            f"      IF (TIME .GE. {literal(event['end_time_s'])}) THEN",
            f"        $OUT = {literal(event['after_value'])}",
            "      ENDIF",
        ]
    return "\n".join(lines) + "\n"


def _render(plan: Mapping[str, Any], project_name: str) -> ET.Element:
    root = ET.parse(plan["scenario_source"]["path"]).getroot()
    old_name = root.get("name")
    root.set("name", project_name)
    for item in root.iter():
        for key in ("defn", "name"):
            value = item.get(key, "")
            if value.startswith(f"{old_name}:"):
                item.set(key, project_name + value[len(old_name) :])
    settings = root.find("./paramlist[@name='Settings']")
    if settings is None:
        raise _error("Project Settings are unavailable.")
    updates = {
        "time_step": plan["time_step_s"] * 1e6,
        "sample_step": plan["output_step_s"] * 1e6,
        "time_duration": plan["duration_s"],
        "PlotType": 1,
        "StartType": 0,
        "output_filename": f"{project_name}.out",
    }
    for key, value in updates.items():
        matches = settings.findall(f"param[@name='{key}']")
        if len(matches) > 1:
            raise _error("A project setting is ambiguous.", parameter=key)
        node = matches[0] if matches else ET.SubElement(settings, "param", name=key)
        node.set(
            "value", format(value, ".17g") if isinstance(value, (int, float)) else value
        )
    canvas = _main(root)
    master = ET.parse(plan["source_hashes"]["master"]["path"]).getroot()
    definitions = root.find("definitions")
    for channel in plan["event_channels"]:
        owner = channel["control_owner"]
        component = _owner(canvas, owner)
        original = master.findall("./definitions/Definition[@name='const']")
        if len(original) != 1:
            raise _error("The Master const definition is not unique.")
        definition = deepcopy(original[0])
        definition.set("name", channel["control_definition"])
        definition.set("id", channel["definition_id"])
        definition.set("instances", "1")
        definition.attrib.pop("crc", None)
        script = definition.find("script")
        if script is not None:
            definition.remove(script)
        text = _script(
            [event for event in plan["events"] if event["target"]["owner"] == owner]
        )
        ET.SubElement(
            ET.SubElement(definition, "script"), "segment", name="Fortran"
        ).text = text
        definitions.append(definition)
        component.set("defn", f"{project_name}:{channel['control_definition']}")
        component.set("name", component.get("defn"))
        output = ET.SubElement(
            canvas,
            "User",
            {
                "classid": "UserCmp",
                "defn": "master:pgb",
                "name": "master:pgb",
                "id": channel["owner"],
                "x": str(channel["x"]),
                "y": str(channel["y"]),
                "orient": "0",
                "w": "38",
                "h": "38",
            },
        )
        parameters = ET.SubElement(output, "paramlist", name="")
        for key, value in {
            "Name": channel["description"],
            "Units": channel["units"],
            "Group": "EMT events",
            "Scale": "1",
            "enab": "1",
            "Display": "1",
            "UseSignalName": "0",
            "mrun": "0",
            "Pol": "0",
            "Max": "2",
            "Min": "-2",
        }.items():
            ET.SubElement(parameters, "param", name=key, value=value)
    return root


def verify_embedded_control(
    plan: Mapping[str, Any], project: str | Path
) -> dict[str, Any]:
    """Reparse the saved executable script, actual ports and settings."""
    _verify_plan(plan)
    identity = _identity(project)
    observed = ET.parse(identity["path"]).getroot()
    expected = _render(plan, observed.get("name", ""))
    expected_canvas, observed_canvas = _main(expected), _main(observed)

    def wiring(canvas):
        records = []
        for item in canvas:
            if item.tag == "Wire" or item.get("defn") == "master:datalabel":
                records.append(
                    {
                        "geometry": {
                            key: item.get(key, "")
                            for key in (
                                "id",
                                "classid",
                                "defn",
                                "name",
                                "x",
                                "y",
                                "orient",
                            )
                        },
                        "vertices": [
                            dict(vertex.attrib) for vertex in item.findall("vertex")
                        ],
                        "parameters": _params(item),
                    }
                )
        return sorted(records, key=lambda item: item["geometry"]["id"])

    if wiring(expected_canvas) != wiring(observed_canvas):
        raise _error(
            "The saved Main-page signal wiring differs from the scheduled source."
        )
    bindings = []
    for channel in plan["event_channels"]:
        definition_name = channel["control_definition"]
        wanted = expected.findall(
            f"./definitions/Definition[@name='{definition_name}']"
        )
        actual = observed.findall(
            f"./definitions/Definition[@name='{definition_name}']"
        )
        if len(actual) != 1 or [
            (item.get("name"), item.text)
            for item in actual[0].findall("./script/segment")
        ] != [
            (item.get("name"), item.text)
            for item in wanted[0].findall("./script/segment")
        ]:
            raise _error("Saved EMTDC script drifted.", definition=definition_name)
        if [ET.tostring(item) for item in actual[0].findall("./svg/port")] != [
            ET.tostring(item) for item in wanted[0].findall("./svg/port")
        ]:
            raise _error(
                "Saved control output port drifted.", definition=definition_name
            )
        for owner in (channel["owner"], channel["control_owner"]):
            a, b = _owner(observed_canvas, owner), _owner(expected_canvas, owner)
            if any(
                a.get(key, "0") != b.get(key, "0")
                for key in ("defn", "x", "y", "orient")
            ) or any(_params(a).get(key) != value for key, value in _params(b).items()):
                raise _error(
                    "Saved control or event channel binding drifted.", owner=owner
                )
        bindings.append(deepcopy(channel))
    for setting in (
        "time_step",
        "sample_step",
        "time_duration",
        "PlotType",
        "StartType",
    ):
        actual = observed.findall(
            f"./paramlist[@name='Settings']/param[@name='{setting}']"
        )
        wanted = expected.find(
            f"./paramlist[@name='Settings']/param[@name='{setting}']"
        )
        if len(actual) != 1 or float(actual[0].get("value", "nan")) != float(
            wanted.get("value")
        ):
            raise _error("Saved simulation settings drifted.", setting=setting)
    return {
        "matched": True,
        "project_path": identity["path"],
        "project_sha256": identity["sha256"],
        "schedule_sha256": plan["schedule_sha256"],
        "bindings": bindings,
    }


def materialize_embedded_control(
    plan: Mapping[str, Any], destination: str | Path
) -> dict[str, Any]:
    _verify_plan(plan)
    path = Path(destination).expanduser()
    if (
        path.exists()
        or path.is_symlink()
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", path.stem)
    ):
        raise _error(
            "The derived path must be new and have a native PSCAD project identity.",
            destination=str(path),
        )
    root = _render(plan, path.stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        ET.ElementTree(root).write(stream, encoding="utf-8")
    return {**deepcopy(dict(plan)), "readback": verify_embedded_control(plan, path)}


def bind_embedded_request(plan, source, requests, profile):
    """Bind public canonical commands to the exact prehashed source targets."""
    from ...bindings import resolve_requested_commands
    from ...profiles import bind_profile_project
    from ...scanner import scan_project

    _verify_plan(plan)
    if (
        plan["schedule_source"] != "embedded_control"
        or _identity(source) != plan["scenario_source"]
    ):
        raise _error("The public scenario does not match the scheduled source.")
    normalized = normalize_timed_events(requests)
    if len(normalized) != len(plan["events"]):
        raise _error("The public scenario event count differs from its schedule.")
    source_profile = bind_profile_project(profile, str(source))
    evidence = scan_project(source)
    bindings = resolve_requested_commands(evidence, source_profile, normalized)
    for request, event, binding in zip(normalized, plan["events"], bindings):
        fields = (
            "event_id",
            "time_s",
            "end_time_s",
            "before_value",
            "value",
            "after_value",
            "units",
        )
        if any(request.get(field) != event[field] for field in fields):
            raise _error(
                "The public scenario event differs from its immutable schedule.",
                event_id=event["event_id"],
            )
        target = event["target"]
        if (
            binding["component_id"] != target["owner"]
            or binding["parameter_name"] != target["parameter"]
        ):
            raise _error(
                "The public canonical command resolved to a different target.",
                event_id=event["event_id"],
            )
        for field in ("before_value", "after_value"):
            resolve_requested_commands(
                evidence, source_profile, [{**request, "value": request[field]}]
            )
    return bindings


def measure_event_waveforms(
    plan: Mapping[str, Any], samples: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Require complete OUT samples and two correctly timed edges per interval."""
    _verify_plan(plan)
    channels = samples.get("channels", [])
    measurements = []
    for expected_channel in plan["event_channels"]:
        matches = [
            item
            for item in channels
            if item.get("description") == expected_channel["description"]
            and item.get("units") == expected_channel["units"]
        ]
        if len(matches) != 1:
            raise _error(
                "A scheduled event channel is missing or ambiguous.",
                selector=expected_channel,
                matches=len(matches),
            )
        channel = matches[0]
        try:
            times = [
                float(value)
                for value in channel.get(
                    "time", channel.get("domain", samples.get("domain", []))
                )
            ]
            values = [float(value) for value in channel["values"]]
        except (TypeError, ValueError, KeyError) as error:
            raise _error("Event waveform samples are invalid.") from error
        if (
            len(times) < 3
            or len(times) != len(values)
            or not all(math.isfinite(value) for value in times + values)
        ):
            raise _error("Event waveform samples must be finite and aligned.")
        output_step = plan["output_step_s"]
        if (
            times[0] < 0
            or times[0] > output_step + 1e-12
            or times[-1] < plan["duration_s"] - output_step - 1e-12
        ):
            raise _error("Event output does not cover the planned simulation interval.")
        if any(
            b <= a or b - a > output_step * 1.001 + 1e-12
            for a, b in itertools.pairwise(times)
        ):
            raise _error(
                "Event output was truncated, decimated or has a clock discontinuity."
            )
        events = [
            event
            for event in plan["events"]
            if event["target"]["owner"] == expected_channel["control_owner"]
        ]
        equal = lambda a, b: math.isclose(a, b, rel_tol=0, abs_tol=1e-9)
        edges = [
            index
            for index in range(1, len(times))
            if not equal(values[index], values[index - 1])
        ]
        if len(edges) != 2 * len(events) or not equal(
            values[0], events[0]["before_value"]
        ):
            raise _error(
                "The event waveform has missing or unexpected transitions.",
                observed_edges=len(edges),
                expected_edges=2 * len(events),
            )
        for index, event in enumerate(events):
            rise, fall = edges[2 * index : 2 * index + 2]
            if not equal(values[rise], event["value"]) or not equal(
                values[fall], event["after_value"]
            ):
                raise _error(
                    "The measured event values differ from the schedule.",
                    event_id=event["event_id"],
                )
            rise_error = times[rise] - event["time_s"]
            fall_error = times[fall] - event["end_time_s"]
            if (
                max(abs(rise_error), abs(fall_error))
                > plan["max_timing_error_s"] + 1e-12
            ):
                raise _error(
                    "The measured event timing error exceeds its fixed bound.",
                    event_id=event["event_id"],
                    rise_error_s=rise_error,
                    fall_error_s=fall_error,
                    max_timing_error_s=plan["max_timing_error_s"],
                )
            measurements.append(
                {
                    "event_id": event["event_id"],
                    "rise_time_s": times[rise],
                    "fall_time_s": times[fall],
                    "rise_error_s": rise_error,
                    "fall_error_s": fall_error,
                    "duration_s": times[fall] - times[rise],
                    "active_sample_count": fall - rise,
                    "sample_count": len(times),
                    "time_range_s": [times[0], times[-1]],
                    "units": event["units"],
                    "event_selector": deepcopy(event["event_selector"]),
                }
            )
    return sorted(measurements, key=lambda item: item["rise_time_s"])
