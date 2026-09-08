"""Isolated licensed compile fixtures for fixed LCC companion definitions."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....core.master_bindings import parse_master_binding_registry
from .assets import LccAssetSet, materialize_library, sha256_file
from .catalog import parse_catalog, require_definition, require_port
from .companion import audit_companion_library
from .routing import absolute_port


@dataclass(frozen=True)
class CompanionFixture:
    name: str
    definition: str
    parameters: Mapping[str, Any]
    expected_ports: tuple[str, ...]


FIXTURES = (
    CompanionFixture(
        "bridge_rectifier",
        "cigre_lcc_v1:LCC12PulseBridge",
        {"UP": 1},
        (
            "ACY_A",
            "ACY_B",
            "ACY_C",
            "ACD_A",
            "ACD_B",
            "ACD_C",
            "DC_POS",
            "DC_NEG",
            "AO_Y",
            "AO_D",
            "ENABLE",
            "AM_Y",
            "AM_D",
            "GM_Y",
            "GM_D",
            "REF_A",
            "REF_B",
            "REF_C",
        ),
    ),
    CompanionFixture(
        "bridge_inverter",
        "cigre_lcc_v1:LCC12PulseBridge",
        {"UP": 0},
        (
            "ACY_A",
            "ACY_B",
            "ACY_C",
            "ACD_A",
            "ACD_B",
            "ACD_C",
            "DC_POS",
            "DC_NEG",
            "AO_Y",
            "AO_D",
            "ENABLE",
            "AM_Y",
            "AM_D",
            "GM_Y",
            "GM_D",
            "REF_A",
            "REF_B",
            "REF_C",
        ),
    ),
    CompanionFixture(
        "rectifier_control",
        "cigre_lcc_v1:RectifierControl",
        {},
        (
            "VDC_MEAS",
            "IDC_MEAS",
            "IORDER",
            "ENABLE",
            "AO_Y",
            "AO_D",
            "ALPHA",
        ),
    ),
    CompanionFixture(
        "inverter_control",
        "cigre_lcc_v1:InverterControl",
        {},
        (
            "VDC_MEAS",
            "IDC_MEAS",
            "GM_Y",
            "GM_D",
            "GAMMA_ORDER",
            "ENABLE",
            "AO_Y",
            "AO_D",
            "GAMMA",
        ),
    ),
    CompanionFixture(
        "initialization",
        "cigre_lcc_v1:Initialization",
        {},
        ("IORDER", "GAMMA_ORDER", "ENABLE_RECT", "ENABLE_INV"),
    ),
    CompanionFixture(
        "signal_interface",
        "cigre_lcc_v1:SignalInterface",
        {},
        (
            "VDC_RECT_RAW",
            "VDC_INV_RAW",
            "IDC_RAW",
            "VDC_RECT",
            "VDC_INV",
            "IDC",
            "AM_Y", "AM_D", "GM_Y", "GM_D",
            "P_RECT_A", "P_RECT_B", "P_RECT_C", "P_INV_A", "P_INV_B", "P_INV_C",
            "ALPHA_RECT", "MU_RECT", "P_RECT", "P_INV",
        ),
    ),
)

_FIXTURE_INPUTS = {
    "cigre_lcc_v1:LCC12PulseBridge": ("AO_Y", "AO_D", "ENABLE"),
    "cigre_lcc_v1:RectifierControl": (
        "VDC_MEAS",
        "IDC_MEAS",
        "IORDER",
        "ENABLE",
    ),
    "cigre_lcc_v1:InverterControl": (
        "VDC_MEAS",
        "IDC_MEAS",
        "GM_Y",
        "GM_D",
        "GAMMA_ORDER",
        "ENABLE",
    ),
    "cigre_lcc_v1:Initialization": (),
    "cigre_lcc_v1:SignalInterface": (
        "VDC_RECT_RAW",
        "VDC_INV_RAW",
        "IDC_RAW",
        "AM_Y", "AM_D", "GM_Y", "GM_D",
        "P_RECT_A", "P_RECT_B", "P_RECT_C", "P_INV_A", "P_INV_B", "P_INV_C",
    ),
}
_BRIDGE_ELECTRICAL_PORTS = (
    "ACY_A",
    "ACY_B",
    "ACY_C",
    "ACD_A",
    "ACD_B",
    "ACD_C",
    "DC_POS",
    "DC_NEG",
    "REF_A",
    "REF_B",
    "REF_C",
)
# Input harnesses must approach the module from the left of its output ports.
_FIXTURE_POSITION = (1440, 180)


def _error(code: str, message: str, operation: str, **details: Any) -> BackendError:
    return BackendError(code, message, "hvdc", operation, details)


def _semantic_registry_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise _error(
            "MASTER_BINDING_MISSING",
            "The companion registry is not a regular file.",
            "verify_sources",
            path=str(path),
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return parse_master_binding_registry(payload).sha256
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, BackendError) as error:
        raise _error(
            "MASTER_BINDING_MISSING",
            "The companion registry cannot be parsed.",
            "verify_sources",
            path=str(path),
        ) from error


def _verify_sources(
    master_path: Path,
    registry_path: Path,
    expected_master_sha256: str,
    expected_registry_sha256: str,
) -> dict[str, str]:
    observed_master = sha256_file(master_path)
    observed_registry = _semantic_registry_hash(registry_path)
    if observed_master != expected_master_sha256:
        raise _error(
            "MASTER_SOURCE_CHANGED",
            "The Master source changed during the component gate.",
            "verify_sources",
            expected=expected_master_sha256,
            observed=observed_master,
        )
    if observed_registry != expected_registry_sha256:
        raise _error(
            "MASTER_SOURCE_CHANGED",
            "The companion registry changed during the component gate.",
            "verify_sources",
            expected=expected_registry_sha256,
            observed=observed_registry,
        )
    return {
        "master_sha256": observed_master,
        "registry_sha256": observed_registry,
    }


def _same_value(left: Any, right: Any) -> bool:
    if left == right or str(left).strip() == str(right).strip():
        return True
    try:
        return float(str(left).split("[", 1)[0]) == float(
            str(right).split("[", 1)[0]
        )
    except (TypeError, ValueError):
        return False


def _port_records(value: Any) -> dict[str, dict[str, Any]]:
    if isinstance(value, Mapping):
        records = []
        for name, item in value.items():
            if isinstance(item, Mapping):
                records.append({"name": str(name), **dict(item)})
            else:
                records.append({"name": str(name)})
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        records = [dict(item) for item in value if isinstance(item, Mapping)]
    else:
        raise _error(
            "LCC_COMPANION_READBACK_FAILED",
            "Component ports are not structured evidence.",
            "validate_readback",
        )
    result: dict[str, dict[str, Any]] = {}
    for item in records:
        name = item.get("name")
        if not isinstance(name, str) or not name or name in result:
            raise _error(
                "LCC_COMPANION_READBACK_FAILED",
                "Component ports are missing or duplicated.",
                "validate_readback",
                port=name,
            )
        kind = str(item.get("kind", item.get("type", ""))).casefold()
        if kind in {
            "natural",
            "power",
            "node",
            "nonremovable",
            "removable",
            "switched",
        }:
            kind = "electrical"
        elif kind in {"transfer", "signal", "analog", "real", "integer"}:
            kind = "data"
        dimension = item.get("dimension", item.get("dim"))
        if isinstance(dimension, str) and dimension.isdigit():
            dimension = int(dimension)
        result[name] = {"kind": kind, "dimension": dimension}
    return result


async def _service_call(operation: str, call: Awaitable[Any]) -> Any:
    try:
        return await call
    except BackendError:
        raise
    except Exception as error:
        raise _error(
            "LCC_COMPANION_COMPILE_FAILED",
            f"Companion component operation '{operation}' failed.",
            operation,
            exception=type(error).__name__,
        ) from error


async def _snapshot(
    service: Any,
    project_name: str,
    component_id: int,
    fixture: CompanionFixture,
    catalog: Any,
) -> dict[str, Any]:
    snapshot_reader = getattr(service, "get_component_snapshot", None)
    if callable(snapshot_reader):
        snapshot = await _service_call(
            "get_component_snapshot",
            snapshot_reader(project_name, component_id),
        )
        observed_definition = (
            snapshot.get("definition") if isinstance(snapshot, Mapping) else None
        )
        if observed_definition != fixture.definition:
            raise _error(
                "LCC_COMPANION_READBACK_FAILED",
                "The component Definition changed on read-back.",
                "validate_readback",
                expected=fixture.definition,
                observed=observed_definition,
            )
    parameters = await _service_call(
        "get_component_parameters",
        service.get_component_parameters(project_name, component_id),
    )
    if not isinstance(parameters, Mapping):
        raise _error(
            "LCC_COMPANION_READBACK_FAILED",
            "Component parameters are not structured evidence.",
            "validate_readback",
        )
    for name, expected in fixture.parameters.items():
        if name not in parameters or not _same_value(parameters[name], expected):
            raise _error(
                "LCC_COMPANION_READBACK_FAILED",
                "A component parameter changed on read-back.",
                "validate_readback",
                parameter=name,
                expected=expected,
                observed=parameters.get(name),
            )
    ports = _port_records(
        await _service_call(
            "get_component_ports",
            service.get_component_ports(project_name, component_id),
        )
    )
    if set(ports) != set(fixture.expected_ports):
        raise _error(
            "LCC_COMPANION_READBACK_FAILED",
            "The companion external port set changed on read-back.",
            "validate_readback",
            expected=sorted(fixture.expected_ports),
            observed=sorted(ports),
        )
    definition = require_definition(catalog, fixture.definition)
    for name in fixture.expected_ports:
        contract = require_port(definition, name)
        observed = ports[name]
        if (
            observed["kind"] != contract.kind
            or observed["dimension"] != contract.dimension
        ):
            raise _error(
                "LCC_COMPANION_READBACK_FAILED",
                "A companion port contract changed on read-back.",
                "validate_readback",
                port=name,
                expected={"kind": contract.kind, "dimension": contract.dimension},
                observed=observed,
            )
    return {
        "definition": fixture.definition,
        "parameters": {
            str(name): str(value)
            for name, value in sorted(parameters.items(), key=lambda item: str(item[0]))
        },
        "ports": {name: ports[name] for name in sorted(ports)},
    }


async def _reload_fixture(
    service: Any,
    project_name: str,
    project_file: Path,
    component_id: int,
    fixture: CompanionFixture,
) -> tuple[str, Path, int]:
    try:
        await service.reload_project(project_name, str(project_file))
        return project_name, project_file, component_id
    except BackendError as error:
        if error.code != "BLUEPRINT_RELOAD_UNAVAILABLE":
            raise

    save_as = getattr(service, "save_project_as", None)
    finder = getattr(service, "find_components", None)
    if not callable(save_as) or not callable(finder):
        raise _error(
            "LCC_COMPANION_READBACK_FAILED",
            "The legacy reload fallback is unavailable.",
            "reload_project",
        )
    reloaded_file = project_file.with_name(f"{fixture.name}_reloaded.pscx")
    await _service_call(
        "save_project_as",
        save_as(
            project_name,
            reloaded_file.name,
            str(reloaded_file.parent),
            confirm=True,
        ),
    )
    if reloaded_file.is_symlink() or not reloaded_file.is_file():
        raise _error(
            "LCC_COMPANION_READBACK_FAILED",
            "The legacy reload fallback did not save a regular project file.",
            "save_project_as",
            path=str(reloaded_file),
        )
    reloaded_name = reloaded_file.stem
    matches = await _service_call(
        "find_components",
        finder(
            reloaded_name,
            definition=fixture.definition,
            canvas_name="Main",
        ),
    )
    if (
        not isinstance(matches, Sequence)
        or isinstance(matches, (str, bytes))
        or len(matches) != 1
        or not isinstance(matches[0], Mapping)
        or isinstance(matches[0].get("id"), bool)
        or not isinstance(matches[0].get("id"), int)
        or matches[0].get("definition") not in {None, fixture.definition}
    ):
        raise _error(
            "LCC_COMPANION_READBACK_FAILED",
            "The reloaded fixture component is missing or ambiguous.",
            "find_components",
            definition=fixture.definition,
        )
    return reloaded_name, reloaded_file, int(matches[0]["id"])


def _orthogonal_vertices(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    bend_x: int | None = None,
) -> list[list[int]]:
    bend = end[0] if bend_x is None else bend_x
    points = [start, (bend, start[1]), (bend, end[1]), end]
    return [
        [point[0], point[1]]
        for index, point in enumerate(points)
        if index == 0 or point != points[index - 1]
    ]


async def _add_fixture_harness(
    service: Any,
    project_name: str,
    fixture: CompanionFixture,
    catalog: Any,
) -> None:
    writer = getattr(service, "create_wire", None)
    if not callable(writer):
        raise _error(
            "LCC_COMPANION_COMPILE_FAILED",
            "The fixture service cannot create harness wires.",
            "create_fixture_harness",
        )
    definition = require_definition(catalog, fixture.definition)
    input_ports = _FIXTURE_INPUTS[fixture.definition]
    for source_index, port_name in enumerate(input_ports):
        contract = require_port(definition, port_name)
        target = absolute_port(_FIXTURE_POSITION, contract.offset, 0)
        integer = False
        if port_name in {"AO_Y", "AO_D"}:
            value = "0.2617993877991494" if fixture.parameters.get("UP") == 1 else "1.57"
        elif port_name == "GAMMA_ORDER":
            value = "0.3141592653589793"
        else:
            value = "1" if integer else "1.0"
        source_y = 720 + source_index * 54
        source_x = 540
        bend_x = 324 + (len(input_ports) - source_index) * 54
        await _service_call(
            "create_fixture_harness",
            service.add_canvas_component(
                project_name,
                "master",
                "consti" if integer else "const",
                source_x,
                source_y,
                0,
                {
                    "Name": f"FIXTURE_{fixture.name}_{port_name}",
                    "Value": value,
                },
                canvas_name="Main",
            ),
        )
        await _service_call(
            "create_fixture_harness",
            writer(
                project_name,
                _orthogonal_vertices(
                    (source_x + 36, source_y),
                    target,
                    bend_x=bend_x,
                ),
                canvas_name="Main",
            ),
        )

    if fixture.definition.endswith(":LCC12PulseBridge"):
        for index, port_name in enumerate(_BRIDGE_ELECTRICAL_PORTS):
            contract = require_port(definition, port_name)
            target = absolute_port(_FIXTURE_POSITION, contract.offset, 0)
            ground = (1080 + index * 72, 1080)
            await _service_call(
                "create_fixture_harness",
                service.add_canvas_component(
                    project_name,
                    "master",
                    "ground",
                    ground[0],
                    ground[1],
                    0,
                    {},
                    canvas_name="Main",
                ),
            )
            await _service_call(
                "create_fixture_harness",
                writer(
                    project_name,
                    _orthogonal_vertices(
                        ground,
                        target,
                        bend_x=594 + index * 54,
                    ),
                    canvas_name="Main",
                ),
            )

async def _verify_compile_messages(service: Any, project_name: str) -> None:
    reader = getattr(service, "get_project_output", None)
    if not callable(reader):
        raise _error(
            "LCC_COMPANION_COMPILE_FAILED",
            "The component gate cannot read structured build messages.",
            "verify_compile_messages",
        )
    messages = await _service_call(
        "verify_compile_messages",
        reader(project_name, structured=True),
    )
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes)):
        raise _error(
            "LCC_COMPANION_COMPILE_FAILED",
            "Structured build messages are not an array.",
            "verify_compile_messages",
        )
    errors = [
        dict(message)
        for message in messages
        if isinstance(message, Mapping)
        and str(message.get("severity", message.get("status", ""))).casefold()
        == "error"
    ]
    if errors:
        summary = " | ".join(
            str(error.get("text", error.get("message", "compile error")))[:256]
            for error in errors[:3]
        )
        raise _error(
            "LCC_COMPANION_COMPILE_FAILED",
            f"PSCAD reported component fixture compile errors: {summary}",
            "verify_compile_messages",
            errors=errors[:20],
        )


def _failure(
    fixture: str,
    operation: str,
    error: BaseException,
) -> dict[str, str]:
    if isinstance(error, BackendError):
        code = error.code
        message = str(error)
        operation = error.operation
    else:
        code = "LCC_COMPANION_COMPILE_FAILED"
        message = str(error)
    return {
        "fixture": fixture,
        "operation": operation,
        "code": code,
        "message": message or type(error).__name__,
    }


async def run_companion_component_gate(
    service: Any,
    assets: LccAssetSet,
    workspace: str | Path,
    *,
    master_path: str | Path,
    registry_path: str | Path,
    expected_master_sha256: str,
    expected_registry_sha256: str,
) -> dict[str, Any]:
    workspace_path = Path(workspace).expanduser().resolve()
    master = Path(master_path).expanduser().resolve()
    registry = Path(registry_path).expanduser().resolve()
    result: dict[str, Any] = {
        "schema_version": 1,
        "status": "FAIL",
        "workspace": str(workspace_path),
        "master_sha256": expected_master_sha256,
        "registry_sha256": expected_registry_sha256,
        "library": None,
        "fixtures": [],
        "failure": None,
    }
    fixture_name = "setup"
    operation = "create_workspace"
    try:
        workspace_path.mkdir(parents=True, exist_ok=False)
        operation = "verify_sources"
        _verify_sources(
            master,
            registry,
            expected_master_sha256,
            expected_registry_sha256,
        )
        operation = "materialize_library"
        library_path = materialize_library(assets, workspace_path)
        physical = audit_companion_library(library_path)
        result["library"] = {
            "path": str(library_path),
            "sha256": physical["sha256"],
        }
        operation = "load_projects"
        await service.load_projects([str(library_path)])
        catalog = parse_catalog(assets.catalog)

        for fixture in FIXTURES:
            fixture_name = fixture.name
            fixture_root = workspace_path / fixture.name
            fixture_root.mkdir(parents=True, exist_ok=False)
            project_file = fixture_root / f"{fixture.name}.pscx"
            operation = "create_project"
            created_project = await service.create_project(
                "case",
                project_file.name,
                str(fixture_root),
                confirm=True,
            )
            project_name = (
                str(created_project.get("name"))
                if isinstance(created_project, Mapping)
                and created_project.get("name")
                else project_file.stem
            )
            observed_file = (
                created_project.get("filename")
                if isinstance(created_project, Mapping)
                else None
            )
            if observed_file:
                project_file = Path(str(observed_file)).expanduser().resolve()
            try:
                project_file.relative_to(fixture_root)
            except ValueError as error:
                raise _error(
                    "LCC_COMPANION_COMPILE_FAILED",
                    "The fixture project escaped its owned directory.",
                    "create_project",
                    path=str(project_file),
                ) from error

            library, definition_name = fixture.definition.split(":", 1)
            operation = "add_canvas_component"
            component = await service.add_canvas_component(
                project_name,
                library,
                definition_name,
                *_FIXTURE_POSITION,
                0,
                dict(fixture.parameters),
                canvas_name="Main",
            )
            if not isinstance(component, Mapping) or isinstance(
                component.get("id"), bool
            ):
                raise _error(
                    "LCC_COMPANION_READBACK_FAILED",
                    "Component creation returned no stable ID.",
                    "validate_readback",
                )
            component_id = int(component["id"])
            if component.get("definition") not in {None, fixture.definition}:
                raise _error(
                    "LCC_COMPANION_READBACK_FAILED",
                    "Component creation returned the wrong Definition.",
                    "validate_readback",
                    expected=fixture.definition,
                    observed=component.get("definition"),
                )
            operation = "create_fixture_harness"
            await _add_fixture_harness(
                service,
                project_name,
                fixture,
                catalog,
            )
            operation = "validate_readback"
            before_reload = await _snapshot(
                service,
                project_name,
                component_id,
                fixture,
                catalog,
            )
            operation = "save_project"
            await service.save_project(project_name, confirm=True)
            if project_file.is_symlink() or not project_file.is_file():
                raise _error(
                    "LCC_COMPANION_COMPILE_FAILED",
                    "The fixture project was not saved as a regular file.",
                    "save_project",
                    path=str(project_file),
                )
            operation = "reload_project"
            project_name, project_file, component_id = await _reload_fixture(
                service,
                project_name,
                project_file,
                component_id,
                fixture,
            )
            before_compile_sha256 = sha256_file(project_file)
            operation = "validate_readback"
            after_reload = await _snapshot(
                service,
                project_name,
                component_id,
                fixture,
                catalog,
            )
            if before_reload != after_reload:
                raise _error(
                    "LCC_COMPANION_READBACK_FAILED",
                    "Component identity changed after save/reload.",
                    "validate_readback",
                    before=before_reload,
                    after=after_reload,
                )
            operation = "verify_sources"
            _verify_sources(
                master,
                registry,
                expected_master_sha256,
                expected_registry_sha256,
            )
            operation = "build_project"
            compile_result = await service.build_project(project_name)
            operation = "verify_compile_messages"
            await _verify_compile_messages(service, project_name)
            operation = "verify_sources"
            _verify_sources(
                master,
                registry,
                expected_master_sha256,
                expected_registry_sha256,
            )
            operation = "save_project"
            await service.save_project(project_name, confirm=True)
            result["fixtures"].append(
                {
                    "fixture": fixture.name,
                    "definition": fixture.definition,
                    "project": {
                        "name": project_name,
                        "path": str(project_file),
                        "sha256_before_compile": before_compile_sha256,
                        "sha256": sha256_file(project_file),
                    },
                    "component_id": component_id,
                    "before_reload": before_reload,
                    "after_reload": after_reload,
                    "compile": {
                        "success": True,
                        "result_type": type(compile_result).__name__,
                    },
                }
            )

        fixture_name = "final"
        operation = "verify_sources"
        _verify_sources(
            master,
            registry,
            expected_master_sha256,
            expected_registry_sha256,
        )
        result["status"] = "PASS"
        return result
    except Exception as error:  # noqa: BLE001 - persist fixture failure evidence
        result["failure"] = _failure(fixture_name, operation, error)
        return result


__all__ = ["FIXTURES", "CompanionFixture", "run_companion_component_gate"]
