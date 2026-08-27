"""Strict versioned parsing for generic PSCAD blueprints."""

from __future__ import annotations

import math
from pathlib import PurePosixPath
import re
from typing import Any, Mapping

from ...core.backend.base import BackendError
from .models import Blueprint, BlueprintIdentity, BlueprintOperation, PublicationSpec, freeze


_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_OPERATION_KINDS = {
    "clone_component",
    "create_component",
    "set_component_location",
    "rotate_component",
    "set_component_parameters",
    "create_wire",
    "connect_ports",
    "set_project_settings",
    "declare_output_channel",
}
_SOURCE_CLASSES = {"engineering_accepted", "model_observed", "provisional", "implementation_policy"}
_PUBLICATION_SCOPES = {"model_run_through_only", "physical_and_model", "evidence_only"}
_ROTATION_DIRECTIONS = {"right", "left", "180"}


def _error(message: str, *, code: str = "BLUEPRINT_SCHEMA_INVALID", path: str = "blueprint") -> BackendError:
    return BackendError(code, message, "blueprint", "parse_blueprint", {"path": path})


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _error(f"{path} must be an object.", path=path)
    return value


def _exact(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    record = _mapping(value, path)
    if set(record) != keys:
        raise _error(f"{path} must contain exactly: {', '.join(sorted(keys))}.", path=path)
    return record


def _allowed(value: Any, required: set[str], optional: set[str], path: str) -> Mapping[str, Any]:
    record = _mapping(value, path)
    keys = set(record)
    if not required <= keys or not keys <= required | optional:
        raise _error(f"{path} has missing or unknown fields.", path=path)
    return record


def _non_empty_string(value: Any, path: str, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(f"{path} must be a non-empty string.", path=path)
    if identifier and _IDENTIFIER.fullmatch(value) is None:
        raise _error(f"{path} must be a stable identifier.", path=path)
    return value


def _json_finite(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error(f"{path} contains a non-finite number.", path=path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _json_finite(item, f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error(f"{path} has a non-string key.", path=path)
            _json_finite(item, f"{path}.{key}")
        return
    raise _error(f"{path} contains a non-JSON value.", path=path)


def _location(value: Any, path: str) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        raise _error(f"{path} must contain two integers.", path=path)
    return value


def _operation_arguments(kind: str, value: Any, path: str) -> Mapping[str, Any]:
    if kind == "clone_component":
        arguments = _allowed(value, {"logical_id", "location"}, {"expected_definition", "canvas"}, path)
        _non_empty_string(arguments["logical_id"], f"{path}.logical_id", identifier=True)
        _location(arguments["location"], f"{path}.location")
        for name in ("expected_definition", "canvas"):
            if name in arguments:
                _non_empty_string(arguments[name], f"{path}.{name}")
    elif kind == "create_component":
        arguments = _allowed(
            value,
            {"logical_id", "definition", "location"},
            {"orientation", "canvas", "parameters", "units"},
            path,
        )
        _non_empty_string(arguments["logical_id"], f"{path}.logical_id", identifier=True)
        _non_empty_string(arguments["definition"], f"{path}.definition")
        _location(arguments["location"], f"{path}.location")
        orientation = arguments.get("orientation", 0)
        if not isinstance(orientation, int) or isinstance(orientation, bool) or not 0 <= orientation <= 7:
            raise _error(f"{path}.orientation must be an integer from 0 through 7.", path=f"{path}.orientation")
        if "canvas" in arguments:
            _non_empty_string(arguments["canvas"], f"{path}.canvas")
        parameters = _mapping(arguments.get("parameters", {}), f"{path}.parameters")
        units = _mapping(arguments.get("units", {}), f"{path}.units")
        if not set(units) <= set(parameters):
            raise _error(f"{path}.units may only name declared parameters.", path=f"{path}.units")
    elif kind == "set_component_location":
        arguments = _exact(value, {"location"}, path)
        _location(arguments["location"], f"{path}.location")
    elif kind == "rotate_component":
        arguments = _exact(value, {"direction", "expected_orientation"}, path)
        if arguments["direction"] not in _ROTATION_DIRECTIONS:
            raise _error(f"{path}.direction is not supported.", path=f"{path}.direction")
        orientation = arguments["expected_orientation"]
        if not isinstance(orientation, int) or isinstance(orientation, bool) or orientation not in {0, 90, 180, 270}:
            raise _error(f"{path}.expected_orientation is invalid.", path=f"{path}.expected_orientation")
    elif kind == "set_component_parameters":
        arguments = _allowed(value, {"parameters"}, {"units"}, path)
        parameters = _mapping(arguments["parameters"], f"{path}.parameters")
        if not parameters:
            raise _error(f"{path}.parameters cannot be empty.", path=f"{path}.parameters")
        units = _mapping(arguments.get("units", {}), f"{path}.units")
        if not set(units) <= set(parameters):
            raise _error(f"{path}.units may only name declared parameters.", path=f"{path}.units")
    elif kind == "create_wire":
        arguments = _allowed(value, {"vertices"}, {"canvas"}, path)
        vertices = arguments["vertices"]
        if not isinstance(vertices, list) or len(vertices) < 2:
            raise _error(f"{path}.vertices must contain at least two points.", path=f"{path}.vertices")
        parsed = [_location(point, f"{path}.vertices[{index}]") for index, point in enumerate(vertices)]
        if any(left == right or (left[0] != right[0] and left[1] != right[1]) for left, right in zip(parsed, parsed[1:])):
            raise _error(f"{path}.vertices must form non-zero orthogonal segments.", path=f"{path}.vertices")
        if "canvas" in arguments:
            _non_empty_string(arguments["canvas"], f"{path}.canvas")
    elif kind == "connect_ports":
        arguments = _allowed(value, {"from", "to"}, {"canvas"}, path)
        for endpoint_name in ("from", "to"):
            endpoint_path = f"{path}.{endpoint_name}"
            endpoint = _exact(arguments[endpoint_name], {"logical_id", "port"}, endpoint_path)
            _non_empty_string(endpoint["logical_id"], f"{endpoint_path}.logical_id", identifier=True)
            _non_empty_string(endpoint["port"], f"{endpoint_path}.port")
        if arguments["from"] == arguments["to"]:
            raise _error(f"{path} cannot connect a port to itself.", path=path)
        if "canvas" in arguments:
            _non_empty_string(arguments["canvas"], f"{path}.canvas")
    elif kind == "set_project_settings":
        arguments = _exact(value, {"settings"}, path)
        if not _mapping(arguments["settings"], f"{path}.settings"):
            raise _error(f"{path}.settings cannot be empty.", path=f"{path}.settings")
    else:
        arguments = _allowed(value, {"path", "units"}, {"call_id"}, path)
        _non_empty_string(arguments["path"], f"{path}.path")
        _non_empty_string(arguments["units"], f"{path}.units")
        call_id = arguments.get("call_id")
        if call_id is not None and (not isinstance(call_id, int) or isinstance(call_id, bool) or call_id < 1):
            raise _error(f"{path}.call_id must be a positive integer.", path=f"{path}.call_id")
    _json_finite(arguments, path)
    return arguments


def _identity(value: Any) -> BlueprintIdentity:
    record = _allowed(
        value,
        {"schema_version", "name", "supported_pscad_versions"},
        {"inspection_profile"},
        "blueprint.identity",
    )
    version = record["schema_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _error("schema_version must be the integer 1.", path="blueprint.identity.schema_version")
    if version != 1:
        raise _error(
            f"Blueprint schema version {version} is not supported.",
            code="BLUEPRINT_SCHEMA_UNSUPPORTED",
            path="blueprint.identity.schema_version",
        )
    name = _non_empty_string(record["name"], "blueprint.identity.name", identifier=True)
    versions = record["supported_pscad_versions"]
    if not isinstance(versions, list) or not versions:
        raise _error("supported_pscad_versions must be a non-empty array.", path="blueprint.identity.supported_pscad_versions")
    parsed_versions = tuple(_non_empty_string(item, "blueprint.identity.supported_pscad_versions[]") for item in versions)
    if len(set(parsed_versions)) != len(parsed_versions):
        raise _error("supported_pscad_versions must be unique.", path="blueprint.identity.supported_pscad_versions")
    profile = record.get("inspection_profile")
    if profile is not None:
        profile = _non_empty_string(profile, "blueprint.identity.inspection_profile", identifier=True)
    return BlueprintIdentity(version, name, parsed_versions, profile)


def _source_package(value: Any) -> Mapping[str, Any]:
    record = _exact(value, {"entry_point", "required", "handling_policy"}, "blueprint.source_package")
    _non_empty_string(record["entry_point"], "blueprint.source_package.entry_point")
    if record["handling_policy"] != "read_only":
        raise _error("source_package.handling_policy must be read_only.", path="blueprint.source_package.handling_policy")
    required = record["required"]
    if not isinstance(required, list) or not required:
        raise _error("source_package.required must be a non-empty array.", path="blueprint.source_package.required")
    paths: list[str] = []
    for index, item in enumerate(required):
        path = f"blueprint.source_package.required[{index}]"
        requirement = _allowed(item, {"path", "kind"}, {"sha256"}, path)
        paths.append(_non_empty_string(requirement["path"], f"{path}.path"))
        if requirement["kind"] not in {"file", "directory"}:
            raise _error(f"{path}.kind must be file or directory.", path=f"{path}.kind")
        digest = requirement.get("sha256")
        if digest is not None and (not isinstance(digest, str) or _SHA256.fullmatch(digest) is None):
            raise _error(f"{path}.sha256 must be a lowercase SHA-256 digest.", path=f"{path}.sha256")
    if len(set(paths)) != len(paths):
        raise _error("source_package.required paths must be unique.", path="blueprint.source_package.required")
    return record


def _operations(value: Any) -> tuple[BlueprintOperation, ...]:
    if not isinstance(value, list):
        raise _error("operations must be an array.", path="blueprint.operations")
    operations: list[BlueprintOperation] = []
    for index, item in enumerate(value):
        path = f"blueprint.operations[{index}]"
        record = _exact(item, {"sequence", "kind", "target", "arguments", "operation_id"}, path)
        sequence = record["sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise _error(f"{path}.sequence must be a positive integer.", path=f"{path}.sequence")
        kind = record["kind"]
        if kind not in _OPERATION_KINDS:
            raise _error(f"{path}.kind is not supported.", path=f"{path}.kind")
        target = _non_empty_string(record["target"], f"{path}.target", identifier=True)
        operation_id = _non_empty_string(record["operation_id"], f"{path}.operation_id", identifier=True)
        arguments = _operation_arguments(kind, record["arguments"], f"{path}.arguments")
        operations.append(BlueprintOperation(sequence, kind, target, freeze(arguments), operation_id))
    sequences = [operation.sequence for operation in operations]
    identifiers = [operation.operation_id for operation in operations]
    if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
        raise _error("operations must have unique ascending sequence values.", path="blueprint.operations")
    if len(set(identifiers)) != len(identifiers):
        raise _error("operations must have unique operation_id values.", path="blueprint.operations")
    return tuple(operations)


def _acceptance(value: Any) -> Mapping[str, Any]:
    record = _exact(
        value,
        {"required_structure", "required_parameters", "blocking_messages", "outputs", "rules"},
        "blueprint.acceptance",
    )
    for field in ("required_structure", "required_parameters", "blocking_messages", "outputs", "rules"):
        if not isinstance(record[field], list):
            raise _error(f"acceptance.{field} must be an array.", path=f"blueprint.acceptance.{field}")
    channels: list[str] = []
    for index, output in enumerate(record["outputs"]):
        path = f"blueprint.acceptance.outputs[{index}]"
        parsed = _exact(output, {"channel", "units", "required"}, path)
        channels.append(_non_empty_string(parsed["channel"], f"{path}.channel"))
        _non_empty_string(parsed["units"], f"{path}.units")
        if not isinstance(parsed["required"], bool):
            raise _error(f"{path}.required must be boolean.", path=f"{path}.required")
    if len(set(channels)) != len(channels):
        raise _error("acceptance output channels must be unique.", path="blueprint.acceptance.outputs")
    rule_ids: list[str] = []
    for index, rule in enumerate(record["rules"]):
        path = f"blueprint.acceptance.rules[{index}]"
        parsed = _exact(rule, {"rule_id", "kind", "channel", "required", "source_class", "physical", "arguments"}, path)
        rule_ids.append(_non_empty_string(parsed["rule_id"], f"{path}.rule_id", identifier=True))
        _non_empty_string(parsed["kind"], f"{path}.kind", identifier=True)
        _non_empty_string(parsed["channel"], f"{path}.channel")
        if not isinstance(parsed["required"], bool) or not isinstance(parsed["physical"], bool):
            raise _error(f"{path} required and physical flags must be boolean.", path=path)
        if parsed["source_class"] not in _SOURCE_CLASSES:
            raise _error(f"{path}.source_class is not recognized.", path=f"{path}.source_class")
        _mapping(parsed["arguments"], f"{path}.arguments")
    if len(set(rule_ids)) != len(rule_ids):
        raise _error("acceptance rule IDs must be unique.", path="blueprint.acceptance.rules")
    _json_finite(record, "blueprint.acceptance")
    return record


def _publication(value: Any) -> PublicationSpec:
    record = _exact(value, {"delivery_package", "evidence_files", "scope"}, "blueprint.publication")
    if not isinstance(record["delivery_package"], bool):
        raise _error("publication.delivery_package must be boolean.", path="blueprint.publication.delivery_package")
    evidence = record["evidence_files"]
    if not isinstance(evidence, list) or any(not isinstance(item, str) or not item for item in evidence):
        raise _error("publication.evidence_files must contain non-empty paths.", path="blueprint.publication.evidence_files")
    if len(set(evidence)) != len(evidence):
        raise _error("publication.evidence_files must be unique.", path="blueprint.publication.evidence_files")
    for item in evidence:
        candidate = PurePosixPath(item.replace("\\", "/"))
        if candidate.is_absolute() or ".." in candidate.parts or len(candidate.parts) != 1:
            raise _error(
                "publication.evidence_files must use simple evidence filenames.",
                path="blueprint.publication.evidence_files",
            )
    if record["scope"] not in _PUBLICATION_SCOPES:
        raise _error("publication.scope is not supported.", path="blueprint.publication.scope")
    return PublicationSpec(record["delivery_package"], tuple(evidence), record["scope"])


def parse_blueprint(value: Any) -> Blueprint:
    """Parse a schema-version-1 blueprint and reject all ambiguous fields."""

    record = _exact(value, {"identity", "source_package", "operations", "acceptance", "publication"}, "blueprint")
    parsed = Blueprint(
        identity=_identity(record["identity"]),
        source_package=freeze(_source_package(record["source_package"])),
        operations=_operations(record["operations"]),
        acceptance=freeze(_acceptance(record["acceptance"])),
        publication=_publication(record["publication"]),
    )
    _json_finite(parsed.to_dict(), "blueprint")
    return parsed
