"""Native PSCAD 4.6 LCC template inspection and derived-copy helpers.

The fixed LCC blueprint is intentionally a logical contract.  A downloaded
PSCAD example, however, contains real ``Definition`` bodies that the
Automation Library can instantiate.  This module keeps that vendor-specific
path explicit: it audits one read-only source, extracts only its converter
definitions into a valid PSLX library, and writes a derived PSCX case with
pre-programmed fault timing.  The source file is never edited in place.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError
from ....core.definition_metadata import read_definition_metadata_matches
from ....core.master_bindings import AuditedMasterRegistry

_MAX_TEMPLATE_BYTES = 32 * 1024 * 1024
_REQUIRED_DEFINITIONS = {"station", "main", "rectifier", "inverter", "rectifier_ac", "inverter_ac"}
_FAULT_DEFINITION = "master:tfault"
_FAULT_CHANNEL_NAME = "LCC Fault Active"
_FAULT_CHANNEL_PATH = "Fault/LCC Fault Active"
_PROJECT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _local(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].casefold()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: str | Path, operation: str) -> Path:
    raw = Path(path).expanduser()
    try:
        if raw.is_symlink():
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "The LCC template must be an existing regular PSCX file.",
                operation,
                path=str(raw),
            )
        candidate = raw.resolve()
        if candidate.is_symlink() or not candidate.is_file():
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "The LCC template must be an existing regular PSCX file.",
                operation,
                path=str(candidate),
            )
        if candidate.stat().st_size > _MAX_TEMPLATE_BYTES:
            raise _error(
                "LCC_TEMPLATE_INCOMPATIBLE",
                "The LCC template exceeds the bounded size limit.",
                operation,
                path=str(candidate),
                max_bytes=_MAX_TEMPLATE_BYTES,
            )
    except BackendError:
        raise
    except OSError as error:
        raise _error(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "The LCC template could not be inspected.",
            operation,
            path=str(candidate),
            exception=type(error).__name__,
        ) from error
    return candidate


def _parse(path: Path, operation: str) -> tuple[ET.Element, bytes]:
    try:
        payload = path.read_bytes()
        root = ET.fromstring(payload)
    except (OSError, ET.ParseError) as error:
        raise _error(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "The LCC template is not readable PSCX XML.",
            operation,
            path=str(path),
            exception=type(error).__name__,
        ) from error
    if _local(root.tag) != "project":
        raise _error(
            "LCC_TEMPLATE_INCOMPATIBLE",
            "The LCC template root must be <project>.",
            operation,
            path=str(path),
        )
    return root, payload


def _definitions(root: ET.Element) -> list[ET.Element]:
    containers = [child for child in root if _local(child.tag) == "definitions"]
    if len(containers) != 1:
        return []
    return [child for child in containers[0] if _local(child.tag) == "definition"]


def _definition_name(definition: ET.Element) -> str:
    return (definition.get("name") or definition.get("id") or "").strip()


def _components(root: ET.Element) -> list[ET.Element]:
    return [
        element
        for element in root.iter()
        if _local(element.tag) in {"user", "component"}
        and (element.get("classid") or "").casefold() in {"usercmp", ""}
    ]


def _parameters(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in element.iter():
        if _local(child.tag) != "param":
            continue
        name = (child.get("name") or "").strip()
        if not name:
            continue
        value = child.get("value")
        result[name] = (value if value is not None else child.text or "").strip()
    return result


def _scoped_definition(element: ET.Element) -> str:
    return (
        element.get("definition")
        or element.get("defn")
        or element.get("type")
        or ""
    ).strip()


def _external_definition_names(root: ET.Element) -> set[str]:
    names: set[str] = set()
    for element in root.iter():
        for value in element.attrib.values():
            if ":" not in value:
                continue
            local = value.rsplit(":", 1)[-1].strip().casefold()
            if local:
                names.add(local)
    return names


def _replace_text_namespace(
    root: ET.Element,
    old: str,
    new: str,
    *,
    preserve_locals: set[str] | None = None,
) -> None:
    prefix = f"{old}:"
    preserved = {item.casefold() for item in (preserve_locals or set())}
    for element in root.iter():
        for key, value in list(element.attrib.items()):
            local = value.rsplit(":", 1)[-1].casefold() if value.startswith(prefix) else ""
            if local in preserved:
                continue
            if value == f"{old}:Station" or value == f"{old}:Main":
                element.set(key, value.replace(prefix, f"{new}:"))
            elif value.startswith(prefix):
                element.set(key, value.replace(prefix, f"{new}:", 1))
        if element.text and prefix in element.text:
            element.text = element.text.replace(prefix, f"{new}:")
        if element.tail and prefix in element.tail:
            element.tail = element.tail.replace(prefix, f"{new}:")


def _set_param(element: ET.Element, name: str, value: str, *, operation: str) -> None:
    matches = [
        child
        for child in element.iter()
        if _local(child.tag) == "param" and child.get("name") == name
    ]
    if len(matches) != 1:
        raise _error(
            "LCC_TEMPLATE_NATIVE_BINDING_MISSING",
            "A native LCC parameter was not uniquely found.",
            operation,
            parameter=name,
            matches=len(matches),
        )
    matches[0].set("value", value)


def _set_or_add_param(element: ET.Element, name: str, value: str) -> None:
    matches = [
        child
        for child in element.iter()
        if _local(child.tag) == "param" and child.get("name") == name
    ]
    if matches:
        matches[0].set("value", value)
        return
    paramlists = [child for child in element if _local(child.tag) == "paramlist"]
    parent = paramlists[0] if paramlists else element
    ET.SubElement(parent, "param", {"name": name, "value": value})


def _settings(root: ET.Element) -> ET.Element:
    for element in root.iter():
        if _local(element.tag) == "paramlist" and element.get("name") == "Settings":
            return element
    raise _error(
        "LCC_TEMPLATE_INCOMPATIBLE",
        "The LCC template has no Settings parameter list.",
        "audit_lcc_native_template",
    )


def _set_setting(root: ET.Element, name: str, value: str) -> None:
    settings = _settings(root)
    matches = [child for child in settings if _local(child.tag) == "param" and child.get("name") == name]
    if len(matches) == 1:
        matches[0].set("value", value)
    elif not matches:
        ET.SubElement(settings, "param", {"name": name, "value": value})
    else:
        raise _error(
            "LCC_TEMPLATE_NATIVE_BINDING_AMBIGUOUS",
            "The template Settings parameter is duplicated.",
            "materialize_lcc_native_template",
            parameter=name,
            matches=len(matches),
        )


def _fault_records(root: ET.Element) -> list[tuple[ET.Element, ET.Element]]:
    records: list[tuple[ET.Element, ET.Element]] = []
    for definition in _definitions(root):
        for component in _components(definition):
            if _scoped_definition(component).casefold() == _FAULT_DEFINITION:
                records.append((definition, component))
    return records


def _fault_network_records(definition: ET.Element) -> list[ET.Element]:
    return [
        component
        for component in _components(definition)
        if _scoped_definition(component).casefold() == "master:tpflt"
    ]


def _output(root: ET.Element) -> ET.Element | None:
    return next((child for child in root if _local(child.tag) == "output"), None)


def _output_channels(root: ET.Element) -> list[dict[str, Any]]:
    output = _output(root)
    if output is None:
        return []
    analog = next((child for child in output if _local(child.tag) == "analog"), None)
    if analog is None:
        return []
    result: list[dict[str, Any]] = []
    for channel in analog:
        if _local(channel.tag) != "channel":
            continue
        name = (channel.get("name") or "").strip()
        if not name:
            continue
        label = (channel.get("label") or "").strip()
        result.append(
            {
                "index": channel.get("index"),
                "id": channel.get("id"),
                "name": name,
                "label": label,
                "units": channel.get("unit", ""),
                "path": f"{label}/{name}" if label else name,
                "dimension": channel.get("dim"),
            }
        )
    return result


@dataclass(frozen=True)
class NativeLccTemplateAudit:
    compatible: bool
    source: str
    source_sha256: str
    pscad_version: str | None
    root_name: str
    definitions: tuple[str, ...]
    output_channels: tuple[dict[str, Any], ...]
    fault_timer: dict[str, Any] = field(default_factory=dict)
    master_sha256: str | None = None
    master_binding_registry_sha256: str | None = None
    master_references: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_native_lcc_template(
    source: str | Path,
    *,
    master_registry: AuditedMasterRegistry | None = None,
) -> NativeLccTemplateAudit:
    path = _regular(source, "audit_lcc_native_template")
    root, payload = _parse(path, "audit_lcc_native_template")
    version = (root.get("version") or root.get("pscad_version") or "").strip() or None
    names = tuple(sorted(_definition_name(item) for item in _definitions(root) if _definition_name(item)))
    lower_names = {name.casefold() for name in names}
    errors: list[str] = []
    warnings: list[str] = []
    if (root.get("Target") or root.get("target") or "").casefold() not in {"emtdc", "case"}:
        errors.append("target_not_case")
    if version is None or not version.startswith("4.6"):
        errors.append("pscad_version_not_4_6")
    external_names = _external_definition_names(root)
    for required in sorted(_REQUIRED_DEFINITIONS - lower_names):
        if required not in external_names:
            errors.append(f"definition_missing:{required}")
    channels = _output_channels(root)
    if not channels:
        errors.append("output_channels_missing")
    faults = _fault_records(root)
    if len(faults) != 1:
        errors.append("fault_timer_not_unique")
    fault_timer: dict[str, Any] = {}
    if len(faults) == 1:
        definition, component = faults[0]
        values = _parameters(component)
        if "TF" not in values or "DF" not in values:
            errors.append("fault_timer_parameters_missing")
        fault_timer = {
            "owner": component.get("id", ""),
            "definition": _scoped_definition(component),
            "container": _definition_name(definition),
            "parameters": {key: values[key] for key in ("TF", "DF") if key in values},
        }
    master_references: list[dict[str, Any]] = []
    if master_registry is not None:
        live_hash = _sha256(Path(master_registry.master_path))
        if live_hash != master_registry.master_sha256:
            errors.append("master_source_changed")
        references = sorted(
            {
                _scoped_definition(component)
                for component in _components(root)
                if _scoped_definition(component).casefold().startswith("master:")
            },
            key=str.casefold,
        )
        for reference in references:
            if reference in master_registry.registry.by_logical_name:
                evidence = master_registry.definitions.get(reference)
                state = (
                    evidence.get("verification_state")
                    if isinstance(evidence, Mapping)
                    else None
                )
                if state != "verified":
                    errors.append(f"master_reference_unverified:{reference}")
                master_references.append(
                    {
                        "reference": reference,
                        "physical_definition": (
                            evidence.get("physical_definition")
                            if isinstance(evidence, Mapping)
                            else None
                        ),
                        "verification_state": state or "missing",
                        "source": "binding_registry",
                    }
                )
                continue
            physical_definition = reference.split(":", 1)[1]
            matches = read_definition_metadata_matches(
                master_registry.master_path,
                physical_definition,
            )
            if len(matches) != 1:
                error_kind = "missing" if not matches else "ambiguous"
                errors.append(
                    f"master_reference_{error_kind}:{physical_definition}"
                )
            master_references.append(
                {
                    "reference": reference,
                    "physical_definition": physical_definition,
                    "verification_state": (
                        "verified" if len(matches) == 1 else "missing"
                    ),
                    "source": "live_master",
                }
            )
    # Absolute paths are not necessarily invalid PSCAD values, but they make a
    # portable derived case non-reproducible and therefore remain explicit.
    for element in root.iter():
        for value in element.attrib.values():
            if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", value.strip()):
                warnings.append("absolute_path_present")
                break
    return NativeLccTemplateAudit(
        compatible=not errors,
        source=str(path),
        source_sha256=hashlib.sha256(payload).hexdigest(),
        pscad_version=version,
        root_name=(root.get("name") or "").strip(),
        definitions=names,
        output_channels=tuple(channels),
        fault_timer=fault_timer,
        master_sha256=(
            master_registry.master_sha256
            if master_registry is not None
            else None
        ),
        master_binding_registry_sha256=(
            master_registry.registry.sha256
            if master_registry is not None
            else None
        ),
        master_references=tuple(master_references),
        errors=tuple(sorted(set(errors))),
        warnings=tuple(sorted(set(warnings))),
    )


def _write_tree(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise _error(
            "LCC_TEMPLATE_NATIVE_WRITE_FAILED",
            "The derived native LCC XML could not be written.",
            "materialize_lcc_native_template",
            path=str(path),
            exception=type(error).__name__,
        ) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _port_offset(orientation: int) -> tuple[int, int]:
    # master:tfault's output Y is at (-36, 0); this is the same orientation
    # transform used by the legacy backend for static component ports.
    transforms = {
        0: (-36, 0),
        1: (0, -36),
        2: (36, 0),
        3: (0, 36),
        4: (36, 0),
        5: (0, 36),
        6: (-36, 0),
        7: (0, -36),
    }
    return transforms.get(orientation, (-36, 0))


def _inject_fault_channel(
    root: ET.Element,
    definition: ET.Element,
    fault: ET.Element,
    *,
    add_output: bool = True,
) -> dict[str, Any]:
    existing = [
        channel
        for channel in _output_channels(root)
        if channel["path"].casefold() == _FAULT_CHANNEL_PATH.casefold()
    ]
    if existing:
        return {"path": _FAULT_CHANNEL_PATH, "id": existing[0].get("id"), "created": False}
    schematic = next((child for child in definition if _local(child.tag) == "schematic"), None)
    if schematic is None:
        raise _error(
            "LCC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The native fault timer container has no schematic.",
            "materialize_lcc_native_template",
        )
    prototype = next(
        (
            item
            for item in schematic
            if _local(item.tag) == "user" and _scoped_definition(item).casefold() == "master:pgb"
        ),
        None,
    )
    if prototype is None:
        raise _error(
            "LCC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The native LCC template has no PGB component to expose fault evidence.",
            "materialize_lcc_native_template",
        )
    clone = copy.deepcopy(prototype)
    ids = []
    for item in root.iter():
        try:
            ids.append(int(item.get("id", "")))
        except (TypeError, ValueError):
            continue
    owner = str(max(ids, default=1) + 1)
    clone.set("id", owner)
    clone.set("name", "")
    clone.set("defn", "master:pgb")
    clone.set("x", str(int(fault.get("x", "0")) + _port_offset(int(fault.get("orient", "0")))[0]))
    clone.set("y", str(int(fault.get("y", "0")) + _port_offset(int(fault.get("orient", "0")))[1]))
    clone.set("w", "84")
    clone.set("h", "38")
    _set_or_add_param(clone, "Name", _FAULT_CHANNEL_NAME)
    _set_or_add_param(clone, "Group", "Fault")
    _set_or_add_param(clone, "Scale", "1.0")
    _set_or_add_param(clone, "Units", "state")
    _set_or_add_param(clone, "mrun", "1")
    _set_or_add_param(clone, "Min", "-0.1")
    _set_or_add_param(clone, "Max", "1.1")
    schematic.append(clone)
    if not add_output:
        return {"path": _FAULT_CHANNEL_PATH, "id": f"{owner}:0", "created": True, "owner": owner}
    output = _output(root)
    if output is None:
        output = ET.Element("output", {"name": root.get("name", ""), "device": "EMTDC", "version": "2010"})
        root.insert(1, output)
    analog = next((child for child in output if _local(child.tag) == "analog"), None)
    if analog is None:
        analog = ET.SubElement(output, "analog")
    indices = []
    for channel in analog:
        try:
            indices.append(int(channel.get("index", "-1")))
        except (TypeError, ValueError):
            continue
    ET.SubElement(
        analog,
        "channel",
        {
            "index": str(max(indices, default=-1) + 1),
            "id": f"{owner}:0",
            "name": _FAULT_CHANNEL_NAME,
            "label": "Fault",
            "dim": "1",
            "unit": "state",
            "min": "-0.1",
            "max": "1.1",
        },
    )
    return {"path": _FAULT_CHANNEL_PATH, "id": f"{owner}:0", "created": True, "owner": owner}


def materialize_native_lcc_bundle(
    source: str | Path,
    project_destination: str | Path,
    library_destination: str | Path,
    *,
    project_name: str,
    fault_time_s: float,
    fault_duration_s: float,
    namespace: str = "cigre_lcc_v1",
    time_duration_s: float = 1.0,
    time_step_us: int = 50,
    sample_step_us: int = 250,
    fault_resistance_ohm: float = 1e-6,
    fault_phase_mask: tuple[int, int, int] = (1, 1, 1),
    master_registry: AuditedMasterRegistry | None = None,
) -> dict[str, Any]:
    """Create a derived case and valid companion library from a PSCX source."""

    if not isinstance(project_name, str) or _PROJECT_NAME.fullmatch(project_name) is None:
        raise _error("LCC_LAYOUT_INVALID", "project_name is not workspace-safe.", "materialize_lcc_native_template", project_name=project_name)
    if isinstance(fault_time_s, bool) or not isinstance(fault_time_s, (int, float)) or not math.isfinite(float(fault_time_s)) or fault_time_s < 0:
        raise _error("LCC_TEMPLATE_NATIVE_BINDING_INVALID", "fault_time_s must be finite and non-negative.", "materialize_lcc_native_template")
    if isinstance(fault_duration_s, bool) or not isinstance(fault_duration_s, (int, float)) or not math.isfinite(float(fault_duration_s)) or fault_duration_s <= 0:
        raise _error("LCC_TEMPLATE_NATIVE_BINDING_INVALID", "fault_duration_s must be finite and positive.", "materialize_lcc_native_template")
    if isinstance(fault_resistance_ohm, bool) or not isinstance(fault_resistance_ohm, (int, float)) or not math.isfinite(float(fault_resistance_ohm)) or fault_resistance_ohm <= 0:
        raise _error("LCC_TEMPLATE_NATIVE_BINDING_INVALID", "fault_resistance_ohm must be finite and positive.", "materialize_lcc_native_template")
    if len(fault_phase_mask) != 3 or any(value not in {0, 1} for value in fault_phase_mask):
        raise _error("LCC_TEMPLATE_NATIVE_BINDING_INVALID", "fault_phase_mask must contain three binary values.", "materialize_lcc_native_template")
    source_path = _regular(source, "materialize_lcc_native_template")
    project_path = Path(project_destination).expanduser().resolve()
    library_path = Path(library_destination).expanduser().resolve()
    if project_path == source_path or library_path == source_path or project_path == library_path:
        raise _error("LCC_BUILD_CONFLICT", "Derived native outputs must be distinct from the source and each other.", "materialize_lcc_native_template")
    if project_path.exists() or project_path.is_symlink() or library_path.exists() or library_path.is_symlink():
        raise _error("LCC_BUILD_CONFLICT", "A derived native output already exists.", "materialize_lcc_native_template", project=str(project_path), library=str(library_path))
    audit = audit_native_lcc_template(
        source_path,
        master_registry=master_registry,
    )
    if not audit.compatible:
        raise _error("LCC_TEMPLATE_INCOMPATIBLE", "The native LCC template failed its audit.", "materialize_lcc_native_template", errors=list(audit.errors))
    root, payload = _parse(source_path, "materialize_lcc_native_template")
    old_namespace = (root.get("name") or "").strip()
    definitions = _definitions(root)
    custom_definitions = [definition for definition in definitions if _definition_name(definition).casefold() not in {"station", "main"}]

    # Build the external library from the converter definitions only.  Keeping
    # Station/Main local is important: their output IDs are part of the case
    # contract and must not be re-instantiated as nested library pages.
    library_root = copy.deepcopy(root)
    for child in list(library_root):
        if _local(child.tag) in {"output", "hierarchy", "definitions"}:
            library_root.remove(child)
    library_root.set("name", namespace)
    library_root.set("Target", "Library")
    library_definitions = ET.SubElement(library_root, "definitions")
    for definition in custom_definitions:
        clone = copy.deepcopy(definition)
        _replace_text_namespace(clone, old_namespace, namespace)
        library_definitions.append(clone)

    # Strip custom bodies from the derived case and bind their references to
    # the stable companion namespace.
    case_root = copy.deepcopy(root)
    case_definitions = next(child for child in case_root if _local(child.tag) == "definitions")
    for definition in list(case_definitions):
        if _definition_name(definition).casefold() not in {"station", "main"}:
            case_definitions.remove(definition)
    _replace_text_namespace(
        case_root,
        old_namespace,
        namespace,
        preserve_locals={"Station", "Main"},
    )
    case_root.set("name", project_name)
    output = _output(case_root)
    if output is not None:
        output.set("name", project_name)
    main = next((definition for definition in case_definitions if _definition_name(definition).casefold() == "main"), None)
    if main is None:
        raise _error("LCC_TEMPLATE_INCOMPATIBLE", "The native LCC template has no Main definition.", "materialize_lcc_native_template")
    references = next((child for child in main if _local(child.tag) == "references"), None)
    if references is None:
        references = ET.SubElement(main, "references")
    if not any((child.get("namespace") or "").casefold() == namespace.casefold() for child in references if _local(child.tag) == "using"):
        ET.SubElement(references, "using", {"namespace": namespace})
    # Rewrite local Station/Main hierarchy names after the external namespace
    # replacement above.
    for element in case_root.iter():
        for key, value in list(element.attrib.items()):
            if value == f"{old_namespace}:Station" or value == f"{old_namespace}:Main":
                element.set(key, value.replace(f"{old_namespace}:", f"{project_name}:"))
    _set_setting(case_root, "time_duration", format(float(time_duration_s), ".15g"))
    _set_setting(case_root, "time_step", str(int(time_step_us)))
    _set_setting(case_root, "sample_step", str(int(sample_step_us)))
    _set_setting(case_root, "PlotType", "1")
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", project_name)
    _set_setting(case_root, "output_filename", f"{normalized}.out")
    source_faults = _fault_records(root)
    if len(source_faults) != 1:
        raise _error(
            "LCC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The native LCC source does not have one unique fault timer.",
            "materialize_lcc_native_template",
            matches=len(source_faults),
        )
    source_fault_definition, _source_fault = source_faults[0]
    fault_definition_name = _definition_name(source_fault_definition).casefold()
    if fault_definition_name in {"station", "main"}:
        fault_targets = _fault_records(case_root)
        target_root = case_root
        add_output = True
    else:
        fault_targets = [
            (definition, component)
            for definition in _definitions(library_root)
            if _definition_name(definition).casefold() == fault_definition_name
            for component in _components(definition)
            if _scoped_definition(component).casefold() == _FAULT_DEFINITION
        ]
        target_root = library_root
        add_output = False
    if len(fault_targets) != 1:
        raise _error(
            "LCC_TEMPLATE_NATIVE_BINDING_MISSING",
            "The derived native LCC bundle lost its unique fault timer.",
            "materialize_lcc_native_template",
            matches=len(fault_targets),
        )
    fault_definition, fault = fault_targets[0]
    _set_param(
        fault,
        "TF",
        f"{float(fault_time_s):.15g} [s]",
        operation="materialize_lcc_native_template",
    )
    _set_param(
        fault,
        "DF",
        f"{float(fault_duration_s):.15g} [s]",
        operation="materialize_lcc_native_template",
    )
    fault_networks = _fault_network_records(fault_definition)
    for network in fault_networks:
        values = _parameters(network)
        if "RON" in values:
            _set_param(
                network,
                "RON",
                f"{float(fault_resistance_ohm):.15g} [ohm]",
                operation="materialize_lcc_native_template",
            )
        for parameter, value in zip(("A", "B", "C"), fault_phase_mask, strict=True):
            if parameter in values:
                _set_param(
                    network,
                    parameter,
                    str(int(value)),
                    operation="materialize_lcc_native_template",
                )
        if "G" in values:
            _set_param(
                network,
                "G",
                "1",
                operation="materialize_lcc_native_template",
            )
    fault_channel = _inject_fault_channel(
        target_root,
        fault_definition,
        fault,
        add_output=add_output,
    )
    if not add_output:
        # The PGB lives in the external definition; the case output selector
        # still needs a root-level channel entry for PSCAD's OUT writer.
        output = _output(case_root)
        if output is None:
            output = ET.Element(
                "output",
                {"name": project_name, "device": "EMTDC", "version": "2010"},
            )
            case_root.insert(1, output)
        analog = next((child for child in output if _local(child.tag) == "analog"), None)
        if analog is None:
            analog = ET.SubElement(output, "analog")
        indices = []
        for channel in analog:
            try:
                indices.append(int(channel.get("index", "-1")))
            except (TypeError, ValueError):
                continue
        ET.SubElement(
            analog,
            "channel",
            {
                "index": str(max(indices, default=-1) + 1),
                "id": str(fault_channel["id"]),
                "name": _FAULT_CHANNEL_NAME,
                "label": "Fault",
                "dim": "1",
                "unit": "state",
                "min": "-0.1",
                "max": "1.1",
            },
        )

    try:
        _write_tree(project_path, case_root)
        _write_tree(library_path, library_root)
    except BaseException:
        project_path.unlink(missing_ok=True)
        library_path.unlink(missing_ok=True)
        raise
    try:
        project_audit = audit_native_lcc_template(
            project_path,
            master_registry=master_registry,
        )
        allowed_external_fault = {
            "fault_timer_not_unique",
            "fault_timer_parameters_missing",
        }
        if not project_audit.compatible and not set(project_audit.errors) <= allowed_external_fault:
            raise _error("LCC_TEMPLATE_NATIVE_WRITE_FAILED", "The derived native LCC case failed its post-write audit.", "materialize_lcc_native_template", errors=list(project_audit.errors))
        if (ET.parse(library_path).getroot().get("Target") or "").casefold() != "library":
            raise _error("LCC_TEMPLATE_NATIVE_WRITE_FAILED", "The derived companion is not a PSCAD Library project.", "materialize_lcc_native_template")
        library_definitions_observed = {
            _definition_name(item) for item in _definitions(ET.parse(library_path).getroot())
        }
        if not add_output and not any(
            _scoped_definition(component).casefold() == _FAULT_DEFINITION
            for component in _components(ET.parse(library_path).getroot())
        ):
            raise _error(
                "LCC_TEMPLATE_NATIVE_WRITE_FAILED",
                "The derived companion does not retain the native fault timer.",
                "materialize_lcc_native_template",
            )
    except (OSError, ET.ParseError):
        project_path.unlink(missing_ok=True)
        library_path.unlink(missing_ok=True)
        raise _error("LCC_TEMPLATE_NATIVE_WRITE_FAILED", "The derived native XML could not be verified.", "materialize_lcc_native_template")
    return {
        "source": str(source_path),
        "project": str(project_path),
        "library": str(library_path),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "project_sha256": _sha256(project_path),
        "library_sha256": _sha256(library_path),
        "namespace": namespace,
        "library_definitions": sorted(library_definitions_observed),
        "fault_channel": fault_channel,
        "timing_basis": "template_embedded_emt",
        "fault_time_s": float(fault_time_s),
        "fault_duration_s": float(fault_duration_s),
        "fault_resistance_ohm": float(fault_resistance_ohm),
        "fault_phase_mask": list(fault_phase_mask),
    }


def _channel_records(samples: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = samples.get("channels") if isinstance(samples, Mapping) else None
    if isinstance(raw, Mapping):
        records: list[Mapping[str, Any]] = []
        for name, value in raw.items():
            if isinstance(value, Mapping):
                records.append({"path": name, **value})
        return records
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)) else []


def _sample(channel: Mapping[str, Any]) -> tuple[list[float], list[float]] | None:
    time_values = channel.get("domain", channel.get("time"))
    values = channel.get("values", channel.get("samples"))
    if not isinstance(time_values, Sequence) or isinstance(time_values, (str, bytes, bytearray)) or not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)) or len(time_values) != len(values) or not time_values:
        return None
    try:
        times = [float(item) for item in time_values]
        numbers = [float(item) for item in values]
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(item) for item in times + numbers) or any(
        right <= left for left, right in itertools.pairwise(times)
    ):
        return None
    return times, numbers


def _find_channel(records: Sequence[Mapping[str, Any]], tokens: Sequence[str]) -> tuple[Mapping[str, Any], list[float], list[float]] | None:
    lowered = tuple(token.casefold() for token in tokens)
    for record in records:
        text = " ".join(str(record.get(key, "")) for key in ("path", "name", "description", "label")).casefold()
        if not all(token in text for token in lowered):
            continue
        values = _sample(record)
        if values is not None:
            return record, values[0], values[1]
    return None


def evaluate_native_lcc_commutation(
    samples: Mapping[str, Any],
    *,
    fault_time_s: float,
    fault_duration_s: float,
    current_limit_pu: float,
    recovery_delay_s: float = 0.5,
) -> dict[str, Any]:
    """Evaluate explicit waveform evidence from the native LCC fault event."""

    records = _channel_records(samples)
    fault = _find_channel(records, ("fault", "active"))
    current = _find_channel(records, ("dc", "current"))
    gamma = _find_channel(records, ("gamma",))
    dc_voltage = _find_channel(records, ("dc", "volt"))
    ac_rms = _find_channel(records, ("ac", "rms"))
    missing: list[str] = []
    for name, value in (("fault_applied", fault), ("dc_current", current)):
        if value is None:
            missing.append(name)
    if gamma is None and dc_voltage is None:
        missing.append("failure_indication")
    if gamma is None:
        missing.append("recovery")
    checks = {
        "disturbance": False,
        "failure_indication": False,
        "bounded_dc_response": False,
        "recovered": False,
    }
    evidence: dict[str, Any] = {
        "fault_time_s": fault_time_s,
        "fault_duration_s": fault_duration_s,
        "current_limit_pu": current_limit_pu,
        "recovery_window_s": float(recovery_delay_s),
    }
    indicator_record: Mapping[str, Any] | None = None
    channels: dict[str, dict[str, Any]] = {}

    def channel_identity(
        channel: tuple[Mapping[str, Any], list[float], list[float]],
    ) -> dict[str, Any]:
        record, times, _values = channel
        return {
            "path": str(record.get("path") or record.get("name") or ""),
            "units": str(record.get("units", record.get("unit", ""))),
            "samples": len(times),
            "domain_start_s": float(times[0]),
            "domain_end_s": float(times[-1]),
        }

    if fault is not None:
        channels["fault_active"] = channel_identity(fault)
    if current is not None:
        channels["dc_current"] = channel_identity(current)
    fault_indices: list[int] = []
    if fault is not None:
        times, values = fault[1], fault[2]
        fault_indices = [index for index, value in enumerate(values) if fault_time_s - 1e-9 <= times[index] <= fault_time_s + fault_duration_s + 1e-9 and value > 0.5]
        checks["disturbance"] = bool(fault_indices)
        evidence["fault_samples"] = len(fault_indices)
    if current is not None:
        times, values = current[1], current[2]
        peak = max((abs(value) for time, value in zip(times, values) if fault_time_s - 1e-9 <= time <= fault_time_s + fault_duration_s + 1e-9), default=float("nan"))
        evidence["dc_current_peak_pu"] = peak
        checks["bounded_dc_response"] = math.isfinite(peak) and math.isfinite(float(current_limit_pu)) and float(current_limit_pu) >= 0 and peak <= float(current_limit_pu)
    if fault_indices:
        if gamma is not None:
            times, values = gamma[1], gamma[2]
            pre = [value for time, value in zip(times, values) if time < fault_time_s]
            during = [value for time, value in zip(times, values) if fault_time_s <= time <= fault_time_s + fault_duration_s]
            after = [
                value
                for time, value in zip(times, values)
                if time > fault_time_s + fault_duration_s + recovery_delay_s
            ]
            if not after:
                after = [
                    value
                    for time, value in zip(times, values)
                    if time > fault_time_s + fault_duration_s
                ]
            baseline = sum(pre[-min(len(pre), 20) :]) / max(1, min(len(pre), 20)) if pre else float("nan")
            checks["failure_indication"] = bool(during) and math.isfinite(baseline) and min(during) <= baseline - 1.0
            if checks["failure_indication"]:
                indicator_record = gamma[0]
            if after and math.isfinite(baseline):
                tail = sum(after[-min(len(after), 20) :]) / max(1, min(len(after), 20))
                checks["recovered"] = abs(tail - baseline) <= max(2.0, abs(baseline) * 0.2)
        if not checks["failure_indication"] and dc_voltage is not None:
            times, values = dc_voltage[1], dc_voltage[2]
            during = [value for time, value in zip(times, values) if fault_time_s <= time <= fault_time_s + fault_duration_s]
            checks["failure_indication"] = bool(during) and min(during) < -0.02
            if checks["failure_indication"]:
                indicator_record = dc_voltage[0]
        if not checks["failure_indication"] and ac_rms is not None:
            times, values = ac_rms[1], ac_rms[2]
            pre = [value for time, value in zip(times, values) if time < fault_time_s]
            during = [value for time, value in zip(times, values) if fault_time_s <= time <= fault_time_s + fault_duration_s]
            baseline = sum(pre[-min(len(pre), 20) :]) / max(1, min(len(pre), 20)) if pre else float("nan")
            checks["failure_indication"] = bool(during) and math.isfinite(baseline) and min(during) <= baseline * 0.8
            if checks["failure_indication"]:
                indicator_record = ac_rms[0]
    if indicator_record is not None:
        indicator_sample = _sample(indicator_record)
        if indicator_sample is not None:
            channels["failure_indicator"] = {
                "path": str(
                    indicator_record.get("path")
                    or indicator_record.get("name")
                    or ""
                ),
                "units": str(
                    indicator_record.get(
                        "units",
                        indicator_record.get("unit", ""),
                    )
                ),
                "samples": len(indicator_sample[0]),
                "domain_start_s": float(indicator_sample[0][0]),
                "domain_end_s": float(indicator_sample[0][-1]),
            }
    evidence["channels"] = channels
    if missing:
        verdict = "INCOMPLETE_ANALYSIS"
    else:
        verdict = "PASS" if all(checks.values()) else "FAIL"
    return {
        "verdict": verdict,
        "checks": checks,
        "missing_evidence": sorted(set(missing)),
        "evidence": evidence,
        "source": "template_native_waveforms",
    }


__all__ = [
    "NativeLccTemplateAudit",
    "audit_native_lcc_template",
    "evaluate_native_lcc_commutation",
    "materialize_native_lcc_bundle",
]
