"""Read-only discovery and audit of the installed PSCAD 4.6 MMC example."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PureWindowsPath
from xml.etree import ElementTree as ET

from ....core.backend.base import BackendError


def _error(code: str, message: str, operation: str, **details: object) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _text(value: str | None) -> str:
    return (value or "").strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compiler_support(library: Path) -> dict[str, object]:
    support = library.parent / "Obj_Files_2016_03_25"
    try:
        text = library.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    required = "Obj_Files_2016_03_25" in text
    hashes: dict[str, str] = {}
    if support.is_dir():
        for path in sorted(item for item in support.rglob("*") if item.is_file()):
            hashes[path.relative_to(support).as_posix()] = _sha256(path)
    return {
        "required": required,
        "root": str(support),
        "present": support.is_dir(),
        "hashes": hashes,
    }


@dataclass(frozen=True)
class MmcTemplateAudit:
    compatible: bool
    pscad_version: str | None
    model_fidelity: str
    sources: dict[str, str]
    source_hashes: dict[str, str]
    definitions: tuple[str, ...]
    dependencies: tuple[dict[str, str], ...]
    role_bindings: tuple[dict[str, str], ...]
    writable_parameter_bindings: tuple[dict[str, str], ...]
    absolute_paths: tuple[dict[str, object], ...]
    warnings: tuple[str, ...]
    compiler_support: dict[str, object] = field(default_factory=dict)
    template_native_controls: dict[str, object] = field(default_factory=dict)
    submodule_topology: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def discover_official_mmc_template(
    public_root: str | Path | None = None,
) -> tuple[Path, Path]:
    root = (
        Path(public_root)
        if public_root is not None
        else Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    )
    directory = root / "Documents" / "PSCAD" / "4.6" / "Examples" / "ModelsInProgress"
    project = directory / "H_MMC_Mono_DC.pscx"
    library = directory / "intermediate.pslx"
    if not project.is_file() or not library.is_file():
        raise _error(
            "MMC_TEMPLATE_NOT_FOUND",
            "The installed PSCAD 4.6 MMC example was not found.",
            "audit_mmc_template",
            project=str(project),
            library=str(library),
        )
    return project.resolve(), library.resolve()


def resolve_template_pair(
    template_path: str | Path | None,
    library_path: str | Path | None,
) -> tuple[Path, Path]:
    if template_path is None and library_path is None:
        return discover_official_mmc_template()
    if template_path is None or library_path is None:
        raise _error(
            "MMC_TEMPLATE_PAIR_INVALID",
            "The MMC project and sibling library must be supplied together.",
            "audit_mmc_template",
        )
    raw_project = Path(template_path).expanduser()
    raw_library = Path(library_path).expanduser()
    if raw_project.is_symlink() or raw_library.is_symlink():
        raise _error(
            "MMC_TEMPLATE_NOT_FOUND",
            "The MMC project or sibling library must be a regular file, not a symlink.",
            "audit_mmc_template",
            project=str(raw_project),
            library=str(raw_library),
        )
    project = raw_project.resolve()
    library = raw_library.resolve()
    if project.is_symlink() or library.is_symlink() or not project.is_file() or not library.is_file():
        raise _error(
            "MMC_TEMPLATE_NOT_FOUND",
            "The MMC project or sibling library does not exist.",
            "audit_mmc_template",
            project=str(project),
            library=str(library),
        )
    if project.suffix.casefold() != ".pscx" or library.suffix.casefold() != ".pslx":
        raise _error(
            "MMC_TEMPLATE_PAIR_INVALID",
            "The MMC template pair must contain one PSCX project and one PSLX library.",
            "audit_mmc_template",
        )
    return project, library


def _parse(path: Path, label: str) -> ET.Element:
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise _error(
            "MMC_TEMPLATE_INVALID",
            f"The MMC {label} XML could not be parsed.",
            "audit_mmc_template",
            path=str(path),
        ) from error


def _definitions(root: ET.Element, namespace: str) -> tuple[str, ...]:
    names = {
        f"{namespace}:{value}"
        for element in root.iter()
        if _name(element.tag) == "definition"
        for value in [_text(element.attrib.get("name") or element.attrib.get("id"))]
        if value
    }
    return tuple(sorted(names))


def _components(root: ET.Element) -> tuple[ET.Element, ...]:
    return tuple(
        element
        for element in root.iter()
        if _name(element.tag) == "component"
        or (
            _name(element.tag) == "user"
            and _text(element.attrib.get("classid")).casefold() == "usercmp"
        )
    )


def _parameters(component: ET.Element) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for element in component.iter():
        if _name(element.tag) not in {"param", "parameter"}:
            continue
        name = _text(element.attrib.get("name"))
        if name:
            result.append((name, _text(element.attrib.get("value") or element.text)))
    return tuple(result)


def _hierarchy_call_names(root: ET.Element) -> tuple[str, ...]:
    return tuple(
        _text(element.attrib.get("name"))
        for element in root.iter()
        if _name(element.tag) == "call" and _text(element.attrib.get("name"))
    )


def _is_absolute(value: str) -> bool:
    return (
        Path(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
        or bool(re.match(r"^[A-Za-z]:[\\/]", value))
    )


def _path_kind(parameter: str, value: str) -> str | None:
    normalized = parameter.casefold().replace(" ", "_")
    suffix = PureWindowsPath(value).suffix.casefold()
    if (
        "startup" in normalized
        or "snapshot" in normalized
        or suffix in {".snp", ".snap"}
    ):
        return "startup_snapshot"
    if "database" in normalized or suffix in {".dbl", ".db"}:
        return "line_database"
    if "constant" in normalized or suffix == ".tlo":
        return "line_constants"
    return None


def _template_native_controls(root: ET.Element) -> dict[str, object]:
    """Describe controls evaluated by the template's own EMTDC logic.

    The presence of ``time-sig`` and ``tfaultn`` proves that a saved template
    can evaluate a pre-programmed event.  It does not expose a live simulation
    clock or an Automation Library scheduler, so the capability is recorded
    separately from the strict backend timing contract.
    """

    has_time_signal = False
    has_fault_timer = False
    components: dict[str, dict[str, str]] = {}
    known_names = {
        "fault time",
        "ac fault type",
        "dblk t1",
        "dblk t2",
        "ccsc enable",
    }
    for component in _components(root):
        definition = _text(
            component.attrib.get("definition")
            or component.attrib.get("defn")
            or component.attrib.get("type")
        )
        short_definition = definition.rsplit(":", 1)[-1].casefold()
        has_time_signal |= short_definition == "time-sig"
        has_fault_timer |= short_definition == "tfaultn"
        values = dict(_parameters(component))
        name = _text(values.get("Name"))
        if not name or name.casefold() not in known_names:
            continue
        if name in components:
            continue
        owner = _text(component.attrib.get("id"))
        if not owner:
            continue
        components[name] = {
            "owner": owner,
            "definition": definition,
            "parameter": "Value",
            "value": values.get("Value", ""),
        }
    available = has_time_signal and has_fault_timer and "Fault Time" in components
    return {
        "available": available,
        "time_basis": "EMTDC",
        "mechanism": "embedded_time_sig_fault_timer" if available else None,
        # Keep these false: they are not live Automation API capabilities.
        "native_schedule": False,
        "simulation_clock": False,
        "components": components,
    }


def _submodule_topology(project_root: ET.Element, _library_root: ET.Element) -> dict[str, object]:
    """Detect the electrical cell contract from project-owned instances.

    A PSLX library necessarily contains component prototypes inside its
    definitions.  Counting those prototypes as instantiated cells makes a
    half-bridge project look like a full-bridge project whenever the library
    happens to ship both families.  Only the PSCX component graph is evidence
    of the selected topology; the library argument is retained for API
    compatibility and future definition-availability checks.
    """

    full_cells: list[dict[str, str]] = []
    hbridge_count = 0
    half_cells: list[dict[str, str]] = []
    firing_block_count = 0
    for component in _components(project_root):
        definition = _text(
            component.attrib.get("definition")
            or component.attrib.get("defn")
            or component.attrib.get("type")
        )
        local = definition.rsplit(":", 1)[-1].casefold()
        values = dict(_parameters(component))
        owner = _text(component.attrib.get("id"))
        if local in {"fullcellr_n", "fullcellr_n_sdt"}:
            full_cells.append({"owner": owner, "definition": definition, "dtbp": values.get("DTBP", "")})
        elif local in {"firinghbridge"}:
            hbridge_count += 1
        elif local == "halfcell_sdt":
            half_cells.append({"owner": owner, "definition": definition})
        elif local == "firingblockvsc":
            firing_block_count += 1
    full_bridge_cells = [item for item in full_cells if item.get("dtbp", "0").strip() in {"", "0"}]
    if full_bridge_cells and hbridge_count:
        declared = "full_bridge"
    elif (half_cells or firing_block_count) and not full_bridge_cells:
        declared = "half_bridge"
    elif full_cells:
        declared = "full_bridge" if hbridge_count else "unknown"
    else:
        declared = "unknown"
    return {
        "declared": declared,
        "full_cell_instances": len(full_bridge_cells),
        "firing_hbridge_instances": hbridge_count,
        "half_cell_instances": len(half_cells),
        "firing_block_instances": firing_block_count,
        "evidence": full_bridge_cells[:32],
    }


def build_template_audit(project: Path, library: Path) -> MmcTemplateAudit:
    project_root = _parse(project, "project")
    library_root = _parse(library, "library")
    version = (
        _text(
            project_root.attrib.get("version")
            or project_root.attrib.get("pscad_version")
        )
        or None
    )
    library_namespace = (
        _text(library_root.attrib.get("namespace") or library_root.attrib.get("name"))
        or library.stem
    )
    definitions = tuple(
        sorted(
            (
                *_definitions(project_root, "project"),
                *_definitions(library_root, library_namespace),
            )
        )
    )

    dependencies: list[dict[str, str]] = []
    for element in project_root.iter():
        if _name(element.tag) not in {"dependency", "library", "resource"}:
            continue
        dependency = {
            key: value
            for key, value in {
                "name": _text(element.attrib.get("name")),
                "path": _text(element.attrib.get("path") or element.attrib.get("file")),
            }.items()
            if value
        }
        if dependency:
            dependencies.append(dependency)

    roles: list[dict[str, str]] = []
    bindings: list[dict[str, str]] = []
    absolute_paths: list[dict[str, object]] = []
    pwm_count = 0
    station_roles: set[str] = set()
    hierarchy_calls = _hierarchy_call_names(project_root)
    writable_links = {
        _text(element.attrib.get("link"))
        for element in project_root.iter()
        if _name(element.tag) == "call"
        and _text(element.attrib.get("link"))
        and _text(element.attrib.get("name")).rsplit(":", 1)[-1].casefold()
        in {"vscconverter", "dctl"}
    }
    has_station_hierarchy = (
        sum(name.rsplit(":", 1)[-1].casefold() == "station" for name in hierarchy_calls)
        == 1
    )
    converter_hierarchy_count = sum(
        name.rsplit(":", 1)[-1].casefold() == "vscconverter" for name in hierarchy_calls
    )
    for index, component in enumerate(_components(project_root)):
        owner = _text(component.attrib.get("id")) or f"component-{index}"
        component_name = _text(component.attrib.get("name"))
        definition = _text(
            component.attrib.get("definition")
            or component.attrib.get("defn")
            or component.attrib.get("type")
        )
        description = f"{component_name} {definition}".casefold()
        role = (
            "station_p"
            if "station_p" in description
            else "station_vdc"
            if "station_vdc" in description
            else ""
        )
        if not role and definition.rsplit(":", 1)[-1].casefold() == "vscconverter":
            parameter_values = dict(_parameters(component))
            mode = parameter_values.get("dmode", "").strip()
            if mode == "0":
                role = "station_vdc"
            elif mode == "1":
                role = "station_p"
        if role:
            station_roles.add(role)
            roles.append({"role": role, "owner": owner, "definition": definition})
        if "pwm" in description:
            pwm_count += 1
            roles.append(
                {
                    "role": f"pwm_converter_{pwm_count}",
                    "owner": owner,
                    "definition": definition,
                }
            )
        for parameter, value in _parameters(component):
            if not hierarchy_calls or owner in writable_links:
                bindings.append(
                    {"owner": owner, "parameter": parameter, "value": value}
                )
            kind = _path_kind(parameter, value)
            if not kind or not _is_absolute(value):
                continue
            path_record: dict[str, object] = {
                "kind": kind,
                "owner": owner,
                "parameter": parameter,
                "value": value,
                "exists": Path(value).is_file(),
                "repair_policy": (
                    "remove_if_missing"
                    if kind == "startup_snapshot"
                    else "verified_rebind"
                    if Path(value).is_file()
                    else "requires_verified_rebind"
                ),
            }
            if Path(value).is_file():
                path_record["resolved_value"] = str(Path(value).resolve())
                path_record["expected_sha256"] = _sha256(Path(value))
            absolute_paths.append(path_record)

    combined_text = " ".join(
        (*definitions, *(item.get("definition", "") for item in roles))
    ).casefold()
    model_fidelity = (
        "detailed_pwm" if pwm_count >= 2 or "pwm" in combined_text else "unknown"
    )
    compatible = (
        version == "4.6.2"
        and station_roles == {"station_p", "station_vdc"}
        and pwm_count >= 2
        and (
            not hierarchy_calls
            or (has_station_hierarchy and converter_hierarchy_count >= 2)
        )
        and any(library_namespace.casefold() in item.casefold() for item in definitions)
    )
    warnings: list[str] = []
    compiler_support = _compiler_support(library)
    template_native_controls = _template_native_controls(project_root)
    submodule_topology = _submodule_topology(project_root, library_root)
    if compiler_support["required"] and not compiler_support["present"]:
        warnings.append("The sibling compiler object tree is missing.")
        compatible = False
    if version != "4.6.2":
        warnings.append("The installed MMC template does not declare PSCAD 4.6.2.")
    if not compatible:
        warnings.append(
            "The installed MMC template roles or sibling library bindings are incomplete."
        )
    return MmcTemplateAudit(
        compatible=compatible,
        pscad_version=version,
        model_fidelity=model_fidelity,
        sources={"project": str(project), "library": str(library)},
        source_hashes={"project": _sha256(project), "library": _sha256(library)},
        definitions=definitions,
        dependencies=tuple(dependencies),
        role_bindings=tuple(roles),
        writable_parameter_bindings=tuple(bindings),
        absolute_paths=tuple(absolute_paths),
        warnings=tuple(warnings),
        compiler_support=compiler_support,
        template_native_controls=template_native_controls,
        submodule_topology=submodule_topology,
    )


def audit_mmc_template(
    template_path: str | Path | None = None,
    library_path: str | Path | None = None,
) -> dict[str, object]:
    project, library = resolve_template_pair(template_path, library_path)
    return build_template_audit(project, library).to_dict()


__all__ = [
    "MmcTemplateAudit",
    "audit_mmc_template",
    "build_template_audit",
    "discover_official_mmc_template",
    "resolve_template_pair",
]
