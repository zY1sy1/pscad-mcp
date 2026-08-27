from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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
            f"C{index:04d}",
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
        conductor_id = f"W{index:04d}"
        conductors.append(ConductorRecipe(conductor_id, vertices))
        nets.append(
            _net(
                f"Main:C{index:04d}:OUT",
                f"Main:C{next_index:04d}:IN",
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
    cases: tuple[CaseRecipe, ...], sources: dict[str, Path]
) -> dict[str, object]:
    expected_names = {case.name for case in cases}
    if set(sources) != expected_names:
        raise ValueError("source projects do not match recipe names")
    projected_cases = []
    for case in cases:
        source = sources[case.name].resolve()
        if not source.is_file():
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
