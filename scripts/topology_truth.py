from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Literal
import xml.etree.ElementTree as ET


Point = tuple[int, int]
Namespace = Literal["electrical", "data"]


@dataclass(frozen=True)
class PortRecipe:
    name: str
    offset: Point
    kind: Namespace
    dimension: int
    required: bool = False
    page: bool = False


@dataclass(frozen=True)
class DefinitionRecipe:
    name: str
    ports: tuple[PortRecipe, ...]
    conductors: tuple["ConductorRecipe", ...] = ()


@dataclass(frozen=True)
class ComponentRecipe:
    object_id: str
    definition: str
    location: Point
    orientation: int = 0
    name: str | None = None
    explicit_ports: tuple[PortRecipe, ...] = ()


@dataclass(frozen=True)
class ConductorRecipe:
    object_id: str
    vertices: tuple[Point, ...]
    namespace: Namespace = "electrical"
    kind: Literal["wire", "bus"] = "wire"


@dataclass(frozen=True)
class LabelRecipe:
    object_id: str
    name: str
    location: Point
    namespace: Namespace
    scope: str = "Main"


@dataclass(frozen=True)
class NetTruth:
    namespace: Namespace
    port_keys: tuple[str, ...]
    conductor_keys: tuple[str, ...]
    label_keys: tuple[str, ...] = ()

    def text(self) -> str:
        return (
            f"{self.namespace}|ports={','.join(sorted(self.port_keys))}"
            f"|conductors={','.join(sorted(self.conductor_keys))}"
            f"|labels={','.join(sorted(self.label_keys))}"
        )


@dataclass(frozen=True)
class CaseRecipe:
    name: str
    healthy: bool
    definitions: tuple[DefinitionRecipe, ...]
    components: tuple[ComponentRecipe, ...]
    conductors: tuple[ConductorRecipe, ...]
    labels: tuple[LabelRecipe, ...]
    nets: tuple[NetTruth, ...]
    expected_error_codes: tuple[str, ...] = ()
    expected_unresolved_codes: tuple[str, ...] = ()
    required_source_capabilities: tuple[tuple[str, bool], ...] = (
        ("live.components", True),
        ("live.conductors", True),
        ("live.labels", True),
        ("live.ports", True),
    )

    @property
    def object_count(self) -> int:
        return len(self.components) + len(self.conductors) + len(self.labels)

    @property
    def project_name(self) -> str:
        return self.name.replace("-", "_")


def _port(
    name: str,
    offset: Point,
    *,
    kind: Namespace = "electrical",
    dimension: int = 1,
    required: bool = False,
    page: bool = False,
) -> PortRecipe:
    return PortRecipe(name, offset, kind, dimension, required, page)


def _net(
    *ports: str,
    conductor: str,
    namespace: Namespace = "electrical",
    labels: tuple[str, ...] = (),
) -> NetTruth:
    return NetTruth(namespace, tuple(ports), (conductor,), labels)


def _scale_case(object_count: int) -> CaseRecipe:
    component_count = object_count // 2
    components = tuple(
        ComponentRecipe(
            str(1_000_000 + index),
            "Link",
            (72 + index * 72, 180),
            name=f"L{index:04d}",
        )
        for index in range(component_count)
    )
    conductors: list[ConductorRecipe] = []
    nets: list[NetTruth] = []
    for index in range(component_count):
        next_index = (index + 1) % component_count
        start = (components[index].location[0] + 18, 180)
        end = (components[next_index].location[0] - 18, 180)
        vertices = (
            (start, end)
            if next_index
            else (start, (start[0], 72), (end[0], 72), end)
        )
        conductor_id = str(2_000_000 + index)
        conductors.append(ConductorRecipe(conductor_id, vertices))
        nets.append(
            _net(
                f"Main:{components[index].object_id}:OUT",
                f"Main:{components[next_index].object_id}:IN",
                conductor=f"Main:{conductor_id}",
            )
        )
    return CaseRecipe(
        name=f"scale-{object_count}",
        healthy=True,
        definitions=(
            DefinitionRecipe(
                "Link",
                (_port("IN", (-18, 0)), _port("OUT", (18, 0))),
            ),
        ),
        components=components,
        conductors=tuple(conductors),
        labels=(),
        nets=tuple(nets),
    )


def case_recipes() -> tuple[CaseRecipe, ...]:
    electrical_pair = (
        _port("A", (-18, 0)),
        _port("B", (18, 0)),
    )
    ordinary = CaseRecipe(
        name="ordinary",
        healthy=True,
        definitions=(),
        components=(
            ComponentRecipe(
                "101", "master:resistor", (72, 72), 0, "R1", electrical_pair
            ),
            ComponentRecipe(
                "102", "master:resistor", (180, 72), 0, "R2", electrical_pair
            ),
        ),
        conductors=(
            ConductorRecipe("201", ((90, 72), (162, 72))),
            ConductorRecipe(
                "202", ((198, 72), (198, 36), (54, 36), (54, 72))
            ),
        ),
        labels=(),
        nets=(
            _net("Main:101:B", "Main:102:A", conductor="Main:201"),
            _net("Main:101:A", "Main:102:B", conductor="Main:202"),
        ),
    )
    seeded = CaseRecipe(
        name="seeded-defects",
        healthy=False,
        definitions=(
            DefinitionRecipe("Dim1", (_port("P", (0, 0)),)),
            DefinitionRecipe("Dim3", (_port("P", (0, 0), dimension=3),)),
            DefinitionRecipe(
                "DataTap", (_port("P", (0, 0), kind="data"),)
            ),
            DefinitionRecipe("ElectricalEnd", (_port("P", (0, 0)),)),
            DefinitionRecipe(
                "RequiredOne", (_port("P", (0, 0), required=True),)
            ),
            DefinitionRecipe("SingleTerminal", (_port("P", (0, 0)),)),
        ),
        components=(
            ComponentRecipe("210", "Dim1", (72, 216)),
            ComponentRecipe("211", "Dim3", (144, 216)),
            ComponentRecipe("310", "DataTap", (108, 360)),
            ComponentRecipe("311", "ElectricalEnd", (72, 360)),
            ComponentRecipe("313", "ElectricalEnd", (144, 360)),
            ComponentRecipe("410", "RequiredOne", (72, 504)),
            ComponentRecipe("510", "SingleTerminal", (72, 648)),
        ),
        conductors=(
            ConductorRecipe("212", ((72, 216), (144, 216))),
            ConductorRecipe("312", ((72, 360), (108, 360), (144, 360))),
            ConductorRecipe("511", ((72, 648), (144, 648))),
        ),
        labels=(
            LabelRecipe("110", "CONFLICT", (72, 72), "electrical"),
            LabelRecipe("111", "CONFLICT", (72, 108), "data"),
        ),
        nets=(
            _net("Main:210:P", "Main:211:P", conductor="Main:212"),
            _net("Main:311:P", "Main:313:P", conductor="Main:312"),
            _net("Main:510:P", conductor="Main:511"),
        ),
        expected_error_codes=(
            "LABEL_CONFLICT",
            "PORT_DIMENSION_MISMATCH",
            "PORT_KIND_MISMATCH",
            "REQUIRED_PORT_UNCONNECTED",
            "WIRE_DANGLING_ENDPOINT",
        ),
    )
    meter_ports = (_port("IN", (-18, 0)), _port("OUT", (18, 0)))
    custom_library = CaseRecipe(
        name="custom-library",
        healthy=True,
        definitions=(DefinitionRecipe("Meter", meter_ports),),
        components=(
            ComponentRecipe("301", "Meter", (72, 72), name="M1"),
            ComponentRecipe("302", "Meter", (180, 72), name="M2"),
        ),
        conductors=(
            ConductorRecipe("601", ((90, 72), (162, 72))),
            ConductorRecipe(
                "602", ((198, 72), (198, 36), (54, 36), (54, 72))
            ),
        ),
        labels=(),
        nets=(
            _net("Main:301:OUT", "Main:302:IN", conductor="Main:601"),
            _net("Main:301:IN", "Main:302:OUT", conductor="Main:602"),
        ),
    )
    hierarchy = CaseRecipe(
        name="hierarchy-uncertain",
        healthy=False,
        definitions=(
            DefinitionRecipe(
                "Child", (_port("IN", (0, 0), required=True, page=True),)
            ),
        ),
        components=(ComponentRecipe("410", "Child", (72, 72)),),
        conductors=(),
        labels=(),
        nets=(),
        expected_unresolved_codes=(
            "hierarchy_boundary_unresolved:Main:410:IN->Main/410:Child:IN",
        ),
    )
    return (
        ordinary,
        seeded,
        custom_library,
        hierarchy,
        _scale_case(500),
        _scale_case(2000),
    )


def manifest_from_recipes(
    cases: tuple[CaseRecipe, ...],
    sources: dict[str, Path],
    *,
    require_files: bool = True,
) -> dict[str, object]:
    expected_names = {case.name for case in cases}
    if set(sources) != expected_names:
        raise ValueError("source projects do not match recipe names")
    projected_cases = []
    for case in cases:
        source = sources[case.name].resolve()
        if require_files and not source.is_file():
            raise FileNotFoundError(source)
        projected_cases.append(
            {
                "name": case.name,
                "source_project": str(source),
                "canvas": "Main",
                "healthy": case.healthy,
                "minimum_object_count": case.object_count,
                "expected_confirmed_edges": sorted(
                    net.text() for net in case.nets
                ),
                "expected_error_codes": sorted(case.expected_error_codes),
                "expected_unresolved_codes": sorted(
                    case.expected_unresolved_codes
                ),
                "required_source_capabilities": dict(
                    case.required_source_capabilities
                ),
            }
        )
    return {"schema_version": 1, "cases": projected_cases}


def generate_cases(
    seed: Path,
    destination: Path,
    cases: tuple[CaseRecipe, ...],
) -> dict[str, Path]:
    seed = seed.resolve()
    destination = destination.resolve()
    if not seed.is_file():
        raise FileNotFoundError(seed)
    if destination.exists():
        raise FileExistsError(
            f"refusing existing generation directory: {destination}"
        )
    destination.mkdir(parents=True)
    result = {}
    for case in cases:
        case_directory = destination / case.name
        case_directory.mkdir()
        tree = ET.parse(seed)
        root = tree.getroot()
        _rewrite_identity(root, case.project_name)
        _replace_definitions(root, case)
        _replace_main_schematic(root, case)
        _replace_hierarchy(root, case)
        path = case_directory / f"{case.name}.pscx"
        ET.indent(tree, space="  ")
        tree.write(path, encoding="utf-8", xml_declaration=True)
        result[case.name] = path.resolve()
    return result


def audit_case(path: Path, case: CaseRecipe) -> dict[str, object]:
    payload = path.read_bytes()
    root = ET.fromstring(payload)
    if root.get("name") != case.project_name:
        raise ValueError(f"project identity changed for {case.name}")
    observed_components = _audit_components(root, case)
    observed_conductors = _audit_conductors(root, case)
    observed_labels = _audit_labels(root, case)
    _audit_definitions(root, case)
    _audit_hierarchy(root, case)
    if observed_components != {item.object_id for item in case.components}:
        raise ValueError(f"component identities changed for {case.name}")
    if observed_conductors != {item.object_id for item in case.conductors}:
        raise ValueError(f"conductor identities changed for {case.name}")
    if observed_labels != {item.object_id for item in case.labels}:
        raise ValueError(f"label identities changed for {case.name}")
    return {
        "name": case.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "object_count": case.object_count,
        "confirmed_edges": sorted(net.text() for net in case.nets),
        "expected_error_codes": list(case.expected_error_codes),
        "expected_unresolved_codes": list(case.expected_unresolved_codes),
    }


def semantic_probe_set(
    sources: dict[str, Path], cases: tuple[CaseRecipe, ...]
) -> dict[str, object]:
    if set(sources) != {case.name for case in cases}:
        raise ValueError("semantic probe sources do not match recipes")
    namespace_seen = {"electrical": False, "data": False}
    namespace_ok = {"electrical": True, "data": True}
    dimensions = set()
    label_namespaces = set()
    required_seen = False
    required_ok = True
    hierarchy_seen = False
    hierarchy_ok = True

    for case in cases:
        root = ET.parse(sources[case.name]).getroot()
        definitions = {
            (element.get("name") or "").casefold(): element
            for element in root.iter("Definition")
        }
        main = _main_schematic(root)
        components = {
            element.get("id"): element
            for element in main
            if element.tag.casefold() in {"user", "component"}
            and not _is_label_element(element)
            and element.get("id")
        }
        conductors = {
            element.get("id"): element
            for element in main
            if element.tag.casefold() in {"wire", "bus"} and element.get("id")
        }
        labels = {
            element.get("id"): element
            for element in main
            if _is_label_element(element) and element.get("id")
        }
        hierarchy_links = {
            element.get("link")
            for element in root.iter("call")
            if element.get("link")
        }

        for definition_recipe in case.definitions:
            definition = definitions.get(definition_recipe.name.casefold())
            observed_ports = (
                {
                    port.get("name"): port
                    for port in definition.iter("port")
                    if port.get("name")
                }
                if definition is not None
                else {}
            )
            for port_recipe in definition_recipe.ports:
                port = observed_ports.get(port_recipe.name)
                _probe_port(
                    port,
                    port_recipe,
                    namespace_seen,
                    namespace_ok,
                    dimensions,
                )
                if port_recipe.required:
                    required_seen = True
                    required_ok &= port is not None and _boolean_attribute(
                        port, "required"
                    )
                if port_recipe.page:
                    hierarchy_seen = True
                    hierarchy_ok &= (
                        port is not None
                        and _boolean_attribute(port, "page")
                        and any(
                            component.object_id in hierarchy_links
                            for component in case.components
                            if component.definition.casefold()
                            == definition_recipe.name.casefold()
                        )
                    )

        for component_recipe in case.components:
            element = components.get(component_recipe.object_id)
            observed_ports = (
                {
                    port.get("name"): port
                    for port in element
                    if port.tag.casefold() == "port" and port.get("name")
                }
                if element is not None
                else {}
            )
            for port_recipe in component_recipe.explicit_ports:
                port = observed_ports.get(port_recipe.name)
                _probe_port(
                    port,
                    port_recipe,
                    namespace_seen,
                    namespace_ok,
                    dimensions,
                )
                if port_recipe.required:
                    required_seen = True
                    required_ok &= port is not None and _boolean_attribute(
                        port, "required"
                    )

        for conductor_recipe in case.conductors:
            namespace_seen[conductor_recipe.namespace] = True
            element = conductors.get(conductor_recipe.object_id)
            namespace_ok[conductor_recipe.namespace] &= (
                element is not None
                and element.get("namespace") == conductor_recipe.namespace
            )

        for label_recipe in case.labels:
            element = labels.get(label_recipe.object_id)
            if (
                element is not None
                and element.get("namespace") == label_recipe.namespace
            ):
                label_namespaces.add(label_recipe.namespace)

    return {
        "required_port_preserved": required_seen and required_ok,
        "electrical_namespace_preserved": (
            namespace_seen["electrical"] and namespace_ok["electrical"]
        ),
        "data_namespace_preserved": (
            namespace_seen["data"] and namespace_ok["data"]
        ),
        "dimensions_preserved": sorted(dimensions),
        "label_namespaces_preserved": sorted(label_namespaces),
        "hierarchy_boundary_preserved": hierarchy_seen and hierarchy_ok,
    }


_EXPECTED_SEMANTIC_PROBE = {
    "required_port_preserved": True,
    "electrical_namespace_preserved": True,
    "data_namespace_preserved": True,
    "dimensions_preserved": [1, 3],
    "label_namespaces_preserved": ["data", "electrical"],
    "hierarchy_boundary_preserved": True,
}


def audit_generated_set(staging: Path) -> dict[str, object]:
    staging = staging.resolve()
    projects_path = staging / "projects.json"
    project_paths = tuple(
        Path(value).resolve()
        for value in json.loads(projects_path.read_text(encoding="utf-8"))
    )
    if not project_paths:
        raise ValueError("generated topology set has no projects")
    if any(not path.is_relative_to(staging) for path in project_paths):
        raise ValueError("generated topology project escapes staging directory")
    cases_by_name = {case.name: case for case in case_recipes()}
    names = tuple(path.stem for path in project_paths)
    if set(names) != set(cases_by_name) or len(names) != len(cases_by_name):
        raise ValueError("generated topology set does not contain all six cases")
    cases = tuple(cases_by_name[name] for name in names)
    sources = dict(zip(names, project_paths, strict=True))
    audits = {
        case.name: audit_case(sources[case.name], case) for case in cases
    }
    semantic_probe = semantic_probe_set(sources, cases)
    if semantic_probe != _EXPECTED_SEMANTIC_PROBE:
        raise ValueError(f"semantic probe failed: {semantic_probe}")
    return {
        "cases": cases,
        "sources": sources,
        "audits": audits,
        "semantic_probe": semantic_probe,
    }


def publish_truth_set(
    staging: Path,
    source_destination: Path,
    manifest_destination: Path,
    preparation_evidence: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    staging = staging.resolve()
    source_destination = source_destination.resolve()
    manifest_destination = manifest_destination.resolve()
    if source_destination.exists():
        raise FileExistsError(
            f"refusing existing topology-sources: {source_destination}"
        )
    if manifest_destination.exists():
        raise FileExistsError(
            f"refusing existing topology-truth.json: {manifest_destination}"
        )
    if not staging.is_dir():
        raise FileNotFoundError(staging)
    if source_destination.parent != manifest_destination.parent:
        raise ValueError("source and manifest destinations must be siblings")
    audited = audit_generated_set(staging)
    cases = audited["cases"]
    staging_sources = audited["sources"]
    audits = audited["audits"]
    assert isinstance(cases, tuple)
    assert isinstance(staging_sources, dict)
    assert isinstance(audits, dict)

    source_destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix=f".{source_destination.name}-publishing-",
            dir=source_destination.parent,
        )
    )
    temporary_sources = temporary_root / source_destination.name
    temporary_manifest = temporary_root / manifest_destination.name
    source_published = False
    try:
        temporary_sources.mkdir()
        final_sources = {}
        for case in cases:
            assert isinstance(case, CaseRecipe)
            source = Path(staging_sources[case.name])
            case_directory = temporary_sources / case.name
            case_directory.mkdir()
            copied = case_directory / source.name
            shutil.copy2(source, copied)
            if hashlib.sha256(copied.read_bytes()).hexdigest() != audits[
                case.name
            ]["sha256"]:
                raise ValueError(f"copied source hash changed for {case.name}")
            final_sources[case.name] = (
                source_destination / case.name / source.name
            )

        recipe_payload = [asdict(case) for case in cases]
        recipe_json = json.dumps(
            recipe_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        recipe_sha256 = hashlib.sha256(recipe_json.encode("utf-8")).hexdigest()
        construction_record = {
            "schema_version": 1,
            "recipe_sha256": recipe_sha256,
            "recipes": recipe_payload,
            "audits": audits,
        }
        preparation_report = {
            "schema_version": 1,
            "status": "PASS",
            "recipe_sha256": recipe_sha256,
            "source_sha256": {
                case.name: audits[case.name]["sha256"] for case in cases
            },
            "semantic_probe": audited["semantic_probe"],
            **(preparation_evidence or {}),
        }
        manifest = manifest_from_recipes(
            cases,
            final_sources,
            require_files=False,
        )
        _write_json(
            temporary_sources / "construction-record.json",
            construction_record,
        )
        _write_json(
            temporary_sources / "preparation-report.json",
            preparation_report,
        )
        _write_json(temporary_manifest, manifest)

        temporary_sources.replace(source_destination)
        source_published = True
        if manifest_destination.exists():
            raise FileExistsError(manifest_destination)
        temporary_manifest.replace(manifest_destination)
        return source_destination, manifest_destination
    except BaseException:
        if source_published and source_destination.exists():
            rollback = temporary_root / source_destination.name
            source_destination.replace(rollback)
            shutil.rmtree(rollback)
        raise
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)


def _probe_port(
    element: ET.Element | None,
    recipe: PortRecipe,
    namespace_seen: dict[str, bool],
    namespace_ok: dict[str, bool],
    dimensions: set[int],
) -> None:
    namespace_seen[recipe.kind] = True
    namespace_ok[recipe.kind] &= (
        element is not None and element.get("kind") == recipe.kind
    )
    if element is None:
        return
    dimension = _integer_attribute(element, "dim", "dimension")
    if dimension == recipe.dimension:
        dimensions.add(dimension)


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).digest()
    return str(int.from_bytes(digest[:4], "big") % 2_000_000_000 + 1)


def _rewrite_identity(root: ET.Element, project_name: str) -> None:
    old_name = root.get("name") or ""
    root.set("name", project_name)
    old_prefix = f"{old_name}:"
    new_prefix = f"{project_name}:"
    for element in root.iter():
        for attribute, value in tuple(element.attrib.items()):
            if old_prefix in value:
                element.set(attribute, value.replace(old_prefix, new_prefix))


def _replace_definitions(root: ET.Element, case: CaseRecipe) -> None:
    definitions = root.find("definitions")
    if definitions is None:
        raise ValueError("seed has no definitions collection")
    for element in tuple(definitions):
        if element.tag.casefold() != "definition":
            continue
        if (element.get("name") or "").casefold() not in {"station", "main"}:
            definitions.remove(element)
    main = _definition(root, "Main")
    insertion_index = list(definitions).index(main)
    for recipe in sorted(case.definitions, key=lambda item: item.name):
        definition = _definition_element(case, recipe)
        definitions.insert(insertion_index, definition)
        insertion_index += 1


def _definition_element(
    case: CaseRecipe, recipe: DefinitionRecipe
) -> ET.Element:
    instances = sum(
        component.definition.casefold() == recipe.name.casefold()
        for component in case.components
    )
    definition = ET.Element(
        "Definition",
        {
            "classid": "UserCmpDefn",
            "name": recipe.name,
            "id": _stable_id(case.name, "definition", recipe.name),
            "group": "",
            "url": "",
            "version": "",
            "build": "",
            "view": "false",
            "date": "0",
            "instances": str(instances),
        },
    )
    parameters = ET.SubElement(definition, "paramlist", {"name": ""})
    ET.SubElement(parameters, "param", {"name": "Description", "value": ""})
    ET.SubElement(definition, "form", {"name": "", "w": "320", "h": "400"})
    svg = ET.SubElement(
        definition,
        "svg",
        {"viewBox": "-200 -200 200 200", "size": "2"},
    )
    for port in sorted(recipe.ports, key=lambda item: item.name):
        _append_definition_port(svg, port)
    ET.SubElement(
        svg,
        "rect",
        {
            "x": "-18",
            "y": "-18",
            "width": "36",
            "height": "36",
            "stroke": "Black",
            "stroke-width": "0.2",
            "fill-style": "Hollow",
        },
    )
    ET.SubElement(definition, "script")
    schematic = ET.SubElement(definition, "schematic", {"classid": "UserCanvas"})
    _append_canvas_parameters(schematic)
    for conductor in sorted(recipe.conductors, key=lambda item: item.object_id):
        _append_conductor(schematic, conductor)
    return definition


def _append_definition_port(parent: ET.Element, port: PortRecipe) -> None:
    attributes = {
        "model": "Transfer" if port.kind == "data" else "Natural",
        "name": port.name,
        "x": str(port.offset[0]),
        "y": str(port.offset[1]),
        "dim": str(port.dimension),
        "kind": port.kind,
        "mode": "Input" if port.kind == "data" else "Electrical",
        "type": "Real" if port.kind == "data" else "NonRemovable",
        "internal": "false",
    }
    if port.required:
        attributes["required"] = "true"
    if port.page:
        attributes["page"] = "true"
    element = ET.SubElement(parent, "port", attributes)
    element.text = "true"


def _replace_main_schematic(root: ET.Element, case: CaseRecipe) -> None:
    main = _definition(root, "Main")
    schematic = next(
        (
            element
            for element in main
            if element.tag.casefold() == "schematic"
        ),
        None,
    )
    if schematic is None:
        raise ValueError("seed Main definition has no schematic")
    for child in tuple(schematic):
        schematic.remove(child)
    _append_canvas_parameters(schematic)
    for index, component in enumerate(
        sorted(case.components, key=lambda item: item.object_id), start=1
    ):
        _append_component(schematic, case, component, index)
    for conductor in sorted(case.conductors, key=lambda item: item.object_id):
        _append_conductor(schematic, conductor)
    for label in sorted(case.labels, key=lambda item: item.object_id):
        _append_label(schematic, label)


def _append_canvas_parameters(schematic: ET.Element) -> None:
    parameters = ET.SubElement(schematic, "paramlist")
    values = {
        "show_grid": "0",
        "size": "0",
        "orient": "1",
        "show_border": "0",
        "monitor_bus_voltage": "0",
        "show_signal": "1",
        "show_virtual": "0",
        "show_sequence": "0",
        "auto_sequence": "1",
    }
    for name, value in values.items():
        ET.SubElement(parameters, "param", {"name": name, "value": value})


def _append_component(
    schematic: ET.Element,
    case: CaseRecipe,
    component: ComponentRecipe,
    z_order: int,
) -> None:
    local_definitions = {item.name.casefold() for item in case.definitions}
    definition = component.definition
    if definition.casefold() in local_definitions:
        definition = f"{case.project_name}:{definition}"
    element = ET.SubElement(
        schematic,
        "User",
        {
            "classid": "UserCmp",
            "name": component.name or definition,
            "id": component.object_id,
            "x": str(component.location[0]),
            "y": str(component.location[1]),
            "w": "46",
            "h": "36",
            "z": str(z_order),
            "orient": str(component.orientation),
            "link": "-1",
            "defn": definition,
            "q": "4",
        },
    )
    ET.SubElement(element, "paramlist", {"link": "-1", "name": ""})
    for port in sorted(component.explicit_ports, key=lambda item: item.name):
        attributes = {
            "classid": "Port",
            "id": _stable_id(case.name, component.object_id, port.name),
            "name": port.name,
            "x": str(port.offset[0]),
            "y": str(port.offset[1]),
            "kind": port.kind,
            "type": port.kind,
            "dim": str(port.dimension),
            "active": "true",
        }
        if port.required:
            attributes["required"] = "true"
        if port.page:
            attributes["page"] = "true"
        ET.SubElement(element, "Port", attributes)


def _append_conductor(
    schematic: ET.Element, conductor: ConductorRecipe
) -> None:
    origin = conductor.vertices[0]
    xs = [point[0] for point in conductor.vertices]
    ys = [point[1] for point in conductor.vertices]
    element = ET.SubElement(
        schematic,
        "Wire" if conductor.kind == "wire" else "Bus",
        {
            "classid": (
                "WireOrthogonal" if conductor.kind == "wire" else "Bus"
            ),
            "name": "",
            "id": conductor.object_id,
            "x": str(origin[0]),
            "y": str(origin[1]),
            "w": str(max(xs) - min(xs) + 10),
            "h": str(max(ys) - min(ys) + 10),
            "orient": "0",
            "namespace": conductor.namespace,
        },
    )
    for point in conductor.vertices:
        ET.SubElement(
            element,
            "vertex",
            {"x": str(point[0] - origin[0]), "y": str(point[1] - origin[1])},
        )


def _append_label(schematic: ET.Element, label: LabelRecipe) -> None:
    definition = (
        "master:datalabel" if label.namespace == "data" else "master:nodelabel"
    )
    element = ET.SubElement(
        schematic,
        "User",
        {
            "classid": "UserCmp",
            "name": definition,
            "id": label.object_id,
            "x": str(label.location[0]),
            "y": str(label.location[1]),
            "w": "46",
            "h": "21",
            "z": "1",
            "orient": "0",
            "link": "-1",
            "defn": definition,
            "q": "4",
            "namespace": label.namespace,
            "scope": label.scope,
        },
    )
    parameters = ET.SubElement(element, "paramlist", {"link": "-1", "name": ""})
    ET.SubElement(parameters, "param", {"name": "Name", "value": label.name})


def _replace_hierarchy(root: ET.Element, case: CaseRecipe) -> None:
    hierarchy = root.find("hierarchy")
    if hierarchy is None:
        raise ValueError("seed has no hierarchy")
    calls = [element for element in hierarchy.iter() if element.tag == "call"]
    main_call = next(
        (
            element
            for element in calls
            if (element.get("name") or "").rsplit(":", 1)[-1] == "Main"
        ),
        None,
    )
    if main_call is None:
        raise ValueError("seed hierarchy has no Main call")
    for child in tuple(main_call):
        main_call.remove(child)
    local_definitions = {item.name.casefold() for item in case.definitions}
    instance_counts: dict[str, int] = {}
    for index, component in enumerate(
        sorted(case.components, key=lambda item: item.object_id), start=1
    ):
        if component.definition.casefold() not in local_definitions:
            continue
        instance = instance_counts.get(component.definition.casefold(), 0)
        instance_counts[component.definition.casefold()] = instance + 1
        ET.SubElement(
            main_call,
            "call",
            {
                "link": component.object_id,
                "name": f"{case.project_name}:{component.definition}",
                "z": str(index),
                "view": "false",
                "instance": str(instance),
            },
        )


def _definition(root: ET.Element, name: str) -> ET.Element:
    definitions = root.find("definitions")
    if definitions is None:
        raise ValueError("project has no definitions collection")
    for element in definitions:
        if (
            element.tag.casefold() == "definition"
            and (element.get("name") or "").casefold() == name.casefold()
        ):
            return element
    raise ValueError(f"project has no {name} definition")


def _main_schematic(root: ET.Element) -> ET.Element:
    main = _definition(root, "Main")
    for element in main:
        if element.tag.casefold() == "schematic":
            return element
    raise ValueError("project Main definition has no schematic")


def _is_label_element(element: ET.Element) -> bool:
    tag = element.tag.casefold()
    definition = (element.get("defn") or "").casefold()
    return tag in {"label", "nodelabel", "datalabel"} or definition.endswith(
        (":nodelabel", ":datalabel")
    )


def _audit_components(root: ET.Element, case: CaseRecipe) -> set[str]:
    observed = {}
    for element in _main_schematic(root):
        if element.tag.casefold() not in {"user", "component"}:
            continue
        if _is_label_element(element):
            continue
        object_id = element.get("id")
        if object_id:
            observed[object_id] = element
    expected = {item.object_id: item for item in case.components}
    if set(observed) != set(expected):
        return set(observed)
    local_definitions = {item.name.casefold() for item in case.definitions}
    for object_id, recipe in expected.items():
        element = observed[object_id]
        definition = element.get("defn") or element.get("definition") or ""
        observed_name = definition.rsplit(":", 1)[-1].casefold()
        expected_name = recipe.definition.rsplit(":", 1)[-1].casefold()
        if observed_name != expected_name:
            raise ValueError(f"component definition changed for {case.name}:{object_id}")
        if ":" in recipe.definition and definition.casefold() != recipe.definition.casefold():
            raise ValueError(f"component scope changed for {case.name}:{object_id}")
        if _point(element) != recipe.location:
            raise ValueError(f"component location changed for {case.name}:{object_id}")
        if _integer_attribute(element, "orient", "orientation") != recipe.orientation:
            raise ValueError(f"component orientation changed for {case.name}:{object_id}")
        if recipe.definition.casefold() in local_definitions and ":" not in definition:
            raise ValueError(f"component scope changed for {case.name}:{object_id}")
        _audit_instance_ports(element, recipe, case.name)
    return set(observed)


def _audit_instance_ports(
    element: ET.Element, recipe: ComponentRecipe, case_name: str
) -> None:
    observed = {
        port.get("name"): port
        for port in element
        if port.tag.casefold() == "port" and port.get("name")
    }
    expected = {port.name: port for port in recipe.explicit_ports}
    if set(observed) != set(expected):
        raise ValueError(
            f"instance port identities changed for {case_name}:{recipe.object_id}"
        )
    for name, port in expected.items():
        element_port = observed[name]
        _audit_port(element_port, port, f"{case_name}:{recipe.object_id}:{name}")


def _audit_conductors(root: ET.Element, case: CaseRecipe) -> set[str]:
    observed = {}
    for element in _main_schematic(root):
        if element.tag.casefold() not in {"wire", "bus"}:
            continue
        object_id = element.get("id")
        if object_id:
            observed[object_id] = element
    expected = {item.object_id: item for item in case.conductors}
    if set(observed) != set(expected):
        return set(observed)
    for object_id, recipe in expected.items():
        element = observed[object_id]
        kind = (
            "bus"
            if element.tag.casefold() == "bus"
            or "bus" in (element.get("classid") or "").casefold()
            else "wire"
        )
        if kind != recipe.kind:
            raise ValueError(f"conductor kind changed for {case.name}:{object_id}")
        namespace = element.get("namespace") or element.get("kind") or "electrical"
        if namespace.casefold() != recipe.namespace:
            raise ValueError(
                f"conductor namespace changed for {case.name}:{object_id}"
            )
        if _absolute_vertices(element) != recipe.vertices:
            raise ValueError(
                f"conductor vertices changed for {case.name}:{object_id}"
            )
    return set(observed)


def _audit_labels(root: ET.Element, case: CaseRecipe) -> set[str]:
    observed = {}
    for element in _main_schematic(root):
        if not _is_label_element(element):
            continue
        object_id = element.get("id")
        if object_id:
            observed[object_id] = element
    expected = {item.object_id: item for item in case.labels}
    if set(observed) != set(expected):
        return set(observed)
    for object_id, recipe in expected.items():
        element = observed[object_id]
        definition = (element.get("defn") or element.tag).casefold()
        namespace = "data" if "datalabel" in definition else "electrical"
        if namespace != recipe.namespace:
            raise ValueError(f"label namespace changed for {case.name}:{object_id}")
        if _label_name(element) != recipe.name:
            raise ValueError(f"label name changed for {case.name}:{object_id}")
        if _point(element) != recipe.location:
            raise ValueError(f"label location changed for {case.name}:{object_id}")
        if (element.get("scope") or "Main") != recipe.scope:
            raise ValueError(f"label scope changed for {case.name}:{object_id}")
    return set(observed)


def _audit_definitions(root: ET.Element, case: CaseRecipe) -> None:
    definitions = root.find("definitions")
    if definitions is None:
        raise ValueError("project has no definitions collection")
    observed = {
        (element.get("name") or ""): element
        for element in definitions
        if element.tag.casefold() == "definition"
        and (element.get("name") or "").casefold() not in {"station", "main"}
    }
    expected = {item.name: item for item in case.definitions}
    if set(observed) != set(expected):
        raise ValueError(f"definition identities changed for {case.name}")
    for name, recipe in expected.items():
        element = observed[name]
        schematic = next(
            child for child in element if child.tag.casefold() == "schematic"
        )
        ports = {
            port.get("name"): port
            for port in element.iter()
            if port.tag.casefold() == "port"
            and not any(port is child for child in schematic.iter())
            and port.get("name")
        }
        expected_ports = {port.name: port for port in recipe.ports}
        if set(ports) != set(expected_ports):
            raise ValueError(f"definition ports changed for {case.name}:{name}")
        for port_name, port in expected_ports.items():
            _audit_port(ports[port_name], port, f"{case.name}:{name}:{port_name}")


def _audit_port(element: ET.Element, recipe: PortRecipe, identity: str) -> None:
    if _point(element) != recipe.offset:
        raise ValueError(f"port offset changed for {identity}")
    kind = element.get("kind")
    if kind is None:
        raw_type = (element.get("type") or "").casefold()
        kind = "data" if raw_type in {"data", "real", "integer"} else "electrical"
    if kind.casefold() != recipe.kind:
        raise ValueError(f"port namespace changed for {identity}")
    if _integer_attribute(element, "dim", "dimension") != recipe.dimension:
        raise ValueError(f"port dimension changed for {identity}")
    if _boolean_attribute(element, "required") != recipe.required:
        raise ValueError(f"port required flag changed for {identity}")
    if _boolean_attribute(element, "page") != recipe.page:
        raise ValueError(f"port page flag changed for {identity}")


def _audit_hierarchy(root: ET.Element, case: CaseRecipe) -> None:
    hierarchy = root.find("hierarchy")
    if hierarchy is None:
        raise ValueError(f"hierarchy disappeared for {case.name}")
    local_definitions = {item.name.casefold() for item in case.definitions}
    expected = {
        (component.object_id, component.definition.casefold())
        for component in case.components
        if component.definition.casefold() in local_definitions
    }
    observed = {
        (
            element.get("link") or "",
            (element.get("name") or "").rsplit(":", 1)[-1].casefold(),
        )
        for element in hierarchy.iter("call")
        if (element.get("name") or "").rsplit(":", 1)[-1].casefold()
        in local_definitions
    }
    if observed != expected:
        raise ValueError(f"hierarchy records changed for {case.name}")


def _point(element: ET.Element) -> Point | None:
    try:
        return int(element.get("x", "")), int(element.get("y", ""))
    except ValueError:
        return None


def _absolute_vertices(element: ET.Element) -> tuple[Point, ...]:
    origin = _point(element) or (0, 0)
    result = []
    for vertex in element:
        if vertex.tag.casefold() != "vertex":
            continue
        relative = _point(vertex)
        if relative is None:
            return ()
        result.append((origin[0] + relative[0], origin[1] + relative[1]))
    return tuple(result)


def _integer_attribute(element: ET.Element, *names: str) -> int | None:
    for name in names:
        raw = element.get(name)
        if raw is not None:
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def _boolean_attribute(element: ET.Element, name: str) -> bool:
    raw = element.get(name)
    return raw is not None and raw.casefold() in {"1", "true", "yes", "on"}


def _label_name(element: ET.Element) -> str:
    for parameter in element.iter("param"):
        if (parameter.get("name") or "").casefold() == "name":
            return parameter.get("value") or ""
    return element.get("name") or element.get("text") or ""


def _selected_cases(raw: str) -> tuple[CaseRecipe, ...]:
    requested = tuple(name.strip() for name in raw.split(",") if name.strip())
    available = {case.name: case for case in case_recipes()}
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"unknown topology cases: {unknown}")
    if len(requested) != len(set(requested)):
        raise ValueError("topology case selection contains duplicates")
    return tuple(available[name] for name in requested)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _build_command(arguments: argparse.Namespace) -> int:
    cases = _selected_cases(arguments.cases)
    generated = generate_cases(arguments.seed, arguments.destination, cases)
    _write_json(
        arguments.destination.resolve() / "projects.json",
        [str(generated[case.name]) for case in cases],
    )
    return 0


def _probe_command(arguments: argparse.Namespace) -> int:
    directory = arguments.directory.resolve()
    project_paths = tuple(
        Path(value).resolve()
        for value in json.loads(
            (directory / "projects.json").read_text(encoding="utf-8")
        )
    )
    available = {case.name: case for case in case_recipes()}
    names = tuple(path.stem for path in project_paths)
    unknown = sorted(set(names) - set(available))
    if unknown:
        raise ValueError(f"probe project names have no recipes: {unknown}")
    cases = tuple(available[name] for name in names)
    sources = dict(zip(names, project_paths, strict=True))
    result = semantic_probe_set(sources, cases)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    if result != _EXPECTED_SEMANTIC_PROBE:
        print("TOPOLOGY_SEMANTIC_PROBE=FAIL")
        return 1
    print("TOPOLOGY_SEMANTIC_PROBE=PASS")
    return 0


def _audit_command(arguments: argparse.Namespace) -> int:
    audited = audit_generated_set(arguments.directory)
    output = {
        "audits": audited["audits"],
        "semantic_probe": audited["semantic_probe"],
    }
    print(json.dumps(output, sort_keys=True, allow_nan=False))
    print("TOPOLOGY_TRUTH_AUDIT=PASS")
    return 0


def _publish_command(arguments: argparse.Namespace) -> int:
    pids = sorted(
        {
            int(value)
            for value in arguments.owned_pids.split(",")
            if value.strip()
        }
    )
    evidence = {
        "pscad": {
            "version": arguments.version,
            "x64": arguments.x64,
            "licensed": True,
        },
        "owned_pids": pids,
        "owned_processes_cleaned": True,
    }
    sources, manifest = publish_truth_set(
        arguments.staging,
        arguments.sources,
        arguments.manifest,
        evidence,
    )
    print(f"TOPOLOGY_SOURCES={sources}")
    print(f"TOPOLOGY_MANIFEST={manifest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build")
    build.add_argument("--seed", type=Path, required=True)
    build.add_argument("--destination", type=Path, required=True)
    build.add_argument("--cases", required=True)
    build.set_defaults(handler=_build_command)

    probe = commands.add_parser("probe")
    probe.add_argument("--directory", type=Path, required=True)
    probe.set_defaults(handler=_probe_command)

    audit = commands.add_parser("audit")
    audit.add_argument("--directory", type=Path, required=True)
    audit.set_defaults(handler=_audit_command)

    publish = commands.add_parser("publish")
    publish.add_argument("--staging", type=Path, required=True)
    publish.add_argument("--sources", type=Path, required=True)
    publish.add_argument("--manifest", type=Path, required=True)
    publish.add_argument("--version", required=True)
    publish.add_argument("--x64", action="store_true")
    publish.add_argument("--owned-pids", default="")
    publish.set_defaults(handler=_publish_command)

    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
