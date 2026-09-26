"""Licensed, isolated MMC Master binding readback/compile fixture; no model verdict."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from pscad_mcp.acceptance.process_scope import (
    concurrent_acceptance_enabled,
    managed_acceptance_pid,
)
from pscad_mcp.acceptance.project_finalization import (
    POLICY,
    compare_project_finalization,
    snapshot_project_semantics,
)
from pscad_mcp.core.backend import legacy_support
from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.backend.legacy import LegacyBackend
from pscad_mcp.core.master_bindings import AuditedMasterRegistry
from pscad_mcp.core.process_inventory import list_pscad_processes
from pscad_mcp.hvdc.builders.mmc.master_bindings import (
    audit_mmc_master_bindings,
    load_mmc_master_registry,
    normalize_mmc_master_parameters,
)
from pscad_mcp.topology.providers.pscx import PscxSnapshotProvider
from scripts.run_mmc_native_probe_acceptance import (
    _category,
    _error,
    _json_safe,
    _service,
    _sha256,
    _stamp,
    _write_report,
    cleanup_owned_session,
    require_runtime,
)
from scripts.run_mmc_native_probe_acceptance import (
    _code_snapshot as _runtime_code_snapshot,
)

SCOPE = "mmc_direct_master_binding_readback_compile"
REGISTRY_PATH = REPOSITORY / "pscad_mcp/assets/mmc/master_bindings/pscad-4.6.2.json"
REMAINING_SCOPE = [
    "This fixture establishes direct Master binding readback and compile only.",
    "MMC full-model simulation, physical acceptance, line assemblies and arm models remain unverified.",
]
FIXTURE_PARAMETERS = {
    "master:dc_bus": {"Name": "MMC_DC_POS"},
    "master:source3": {
        "Name": "MMC_SOURCE",
        "Amplitude": 400.0,
        "Frequency": 50.0,
        "GridR": 3.0,
        "GridX": 4.0,
    },
    "master:transformer": {
        "Name": "MMC_TRANSFORMER",
        "RatedPower_MVA": 1100.0,
        "Primary_kV": 230.0,
        "Secondary_kV": 230.0,
        "Frequency": 60.0,
        "Leakage_pu": 0.1,
    },
    "master:pi_controller": {
        "Kp": 1.0,
        "Ti_s": 0.01,
        "Lower": -10.0,
        "Upper": 10.0,
        "Initial": 0.0,
    },
    "master:phase_breakout": {},
    "master:ground": {},
}


def _require_optins() -> None:
    for name in ("PSCAD_MCP_ACCEPTANCE", "PSCAD_MCP_MASTER_BINDING_ACCEPTANCE"):
        if os.environ.get(name) != "1":
            raise PermissionError(f"{name}=1 is required before an attempt")


def _check(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _values_match(expected: Mapping[str, Any], observed: Any) -> bool:
    return _contains(expected, observed) and set(expected) == set(observed)


def _contains(expected: Mapping[str, Any], observed: Any) -> bool:
    return isinstance(observed, Mapping) and all(
        key in observed and LegacyBackend._settings_values_match(value, observed[key])
        for key, value in expected.items()
    )


def _sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _messages_have_errors(messages: Any) -> bool:
    _check(
        isinstance(messages, list)
        and all(
            isinstance(item, dict)
            and isinstance(item.get("severity"), str)
            and isinstance(item.get("text"), str)
            for item in messages
        ),
        "Structured compiler messages are required",
    )
    return any(
        "error" in item["severity"].casefold() or "fatal" in item["severity"].casefold()
        for item in messages
    )


def _code_snapshot() -> dict[str, Any]:
    result = _runtime_code_snapshot()
    result["source_code_hashes"].update(
        {
            str(path): _sha256(path)
            for path in (
                Path(__file__).resolve(),
                REPOSITORY / "tests/test_mmc_master_binding_acceptance.py",
                REPOSITORY / "tests/test_acceptance_project_finalization.py",
            )
        }
    )
    return result


def _catalog(context) -> dict[str, Any]:
    return {
        "definitions": {
            name: {
                "ports": [
                    {"name": port, "kind": data["kind"], "dimension": data["dimension"]}
                    for port, data in definition["selected_ports"].items()
                ]
            }
            for name, definition in context.audited.definitions.items()
        }
    }


def _validate_binding(item: Mapping[str, Any], audited: AuditedMasterRegistry) -> None:
    name = item.get("logical_name")
    _check(name in audited.registry.by_logical_name, "Unexpected logical binding")
    raw = FIXTURE_PARAMETERS[name]
    normalized = normalize_mmc_master_parameters(name, raw)
    resolved = audited.resolve_component(name, normalized)
    for contract in audited.registry.by_logical_name[name].ports:
        port = resolved.selected_ports.get(contract.logical, {})
        _check(
            all(
                port.get(key) == getattr(contract, key)
                for key in ("physical", "dimension", "kind", "occurrence")
            ),
            f"Selected port differs from the registry contract: {name}",
        )
    evidence = resolved.to_evidence()
    _check(
        item.get("requested_parameters") == raw
        and _values_match(normalized, item.get("logical_parameters")),
        f"Incomplete logical parameter readback: {name}",
    )
    _check(
        all(item.get(key) == value for key, value in evidence.items()),
        f"Resolved binding evidence differs: {name}",
    )
    component_id = item.get("component_id")
    members = item.get("observed_instances")
    _check(
        type(component_id) is int
        and component_id > 0
        and isinstance(members, list)
        and len(members) == 1,
        f"Missing direct physical observation: {name}",
    )
    member = members[0]
    _check(
        member.get("role") == "component"
        and member.get("component_id") == component_id
        and member.get("definition") == "master:" + resolved.physical_definition,
        f"Physical instance mismatch: {name}",
    )
    physical = member.get("parameters", {})
    _check(
        _contains(resolved.physical_parameters, physical),
        f"Physical parameter readback mismatch: {name}",
    )
    _check(
        _values_match(normalized, resolved.logical_parameters(physical)),
        f"Physical reverse mapping mismatch: {name}",
    )
    ports, location = item.get("ports", {}), item.get("location", {})
    _check(
        set(ports) == set(resolved.selected_ports)
        and all(type(location.get(axis)) is int for axis in ("x", "y")),
        f"Missing logical port readback: {name}",
    )
    for port_name, expected in resolved.selected_ports.items():
        port = ports[port_name]
        _check(
            port.get("name") == port_name
            and port.get("dim") == expected["dimension"]
            and port.get("type") == (expected.get("type") or expected["kind"])
            and [port.get("x"), port.get("y")]
            == [
                location[axis] + expected["offset"][index]
                for index, axis in enumerate(("x", "y"))
            ],
            f"Selected port dimension, type or position mismatch: {name}:{port_name}",
        )


def _resistor_ports(metadata) -> dict[str, Any]:
    resistance = metadata.get("parameters", {}).get("R", {})
    ports = metadata.get("ports", [])
    _check(
        metadata.get("name") == "resistor"
        and _contains({"type": "Real", "unit": "ohm", "readonly": False}, resistance)
        and (resistance.get("minimum") is None or resistance["minimum"] <= 10.0)
        and (resistance.get("maximum") is None or resistance["maximum"] >= 10.0)
        and len(ports) == 2
        and {port.get("name") for port in ports} == {"A", "B"}
        and all(
            port.get("model") == "Natural"
            and port.get("type") == "Removable"
            and type(port.get("dim")) is int
            and port["dim"] in (0, 1)
            and port.get("condition") == "true"
            for port in ports
        ),
        "The DC shunt requires native resistor metadata for 10 ohm and scalar/adaptive electrical A/B ports",
    )
    return {port["name"]: port for port in ports}


def _validate_dc_shunt(shunt) -> None:
    metadata_ports = _resistor_ports(shunt.get("metadata", {}))
    component = shunt.get("component", {})
    _check(
        component.get("definition") == "master:resistor"
        and type(component.get("id")) is int
        and component["id"] > 0
        and _values_match({"R": 10.0}, shunt.get("parameters")),
        "The DC shunt must read back as a native 10-ohm resistor",
    )
    location, ports = shunt.get("location", {}), shunt.get("ports", {})
    _check(
        set(ports) == {"A", "B"}
        and all(type(location.get(axis)) is int for axis in ("x", "y")),
        "The DC shunt requires both physical port locations",
    )
    for name, metadata in metadata_ports.items():
        expected = {
            "name": name,
            "dim": metadata["dim"],
            "type": metadata["type"],
            "x": location["x"] + metadata["x"],
            "y": location["y"] + metadata["y"],
        }
        _check(
            _contains(expected, ports[name]),
            f"DC shunt port {name} differs from native metadata",
        )
    _check(
        (ports["A"]["x"], ports["A"]["y"]) != (ports["B"]["x"], ports["B"]["y"]),
        "The DC shunt terminals must remain distinct",
    )


def _validate_support(support, bindings) -> None:
    _check(
        isinstance(support, dict)
        and set(support)
        == {
            "pi_input",
            "transformer_neutral",
            "source_neutral",
            "dc_shunt",
            "dc_shunt_ground",
        },
        "Every fixture input and neutral connection is required",
    )
    by_name = {item["logical_name"]: item for item in bindings}
    pi = support["pi_input"]
    output = pi.get("port", {})
    _check(
        output.get("name") == "OUT"
        and output.get("dim") == 1
        and output.get("type") == "Real"
        and _values_match({"Name": "MMC_PI_INPUT", "Value": 0.0}, pi.get("parameters")),
        "The PI fixture requires a verified real scalar constant",
    )
    metadata = pi.get("metadata", {})
    _check(
        metadata.get("name") == "const"
        and any(
            port.get("name") == "OUT"
            and port.get("dim") == 1
            and port.get("type") == "Real"
            and port.get("mode") == "Output"
            and port.get("condition") == "true"
            for port in metadata.get("ports", [])
        ),
        "Native constant metadata evidence is required",
    )
    ground = by_name["master:ground"]["ports"]["GND"]
    shunt = support["dc_shunt"]
    _validate_dc_shunt(shunt)
    _check(
        ground["dim"] == 1
        and shunt["component"]["id"] not in {item["component_id"] for item in bindings},
        "The DC shunt must be a distinct component connected to scalar ground",
    )
    endpoints = {
        "pi_input": (output, by_name["master:pi_controller"]["ports"]["IN"]),
        "source_neutral": (by_name["master:source3"]["ports"]["NEUTRAL"], ground),
        "transformer_neutral": (
            by_name["master:transformer"]["ports"]["NEUTRAL"],
            ground,
        ),
        "dc_shunt": (by_name["master:dc_bus"]["ports"]["DC"], shunt["ports"]["A"]),
        "dc_shunt_ground": (shunt["ports"]["B"], ground),
    }
    wire_ids = []
    for name, (start, end) in endpoints.items():
        vertices, wire = (
            support[name].get("vertices", []),
            support[name].get("wire", {}),
        )
        expected = [[start["x"], start["y"]], [end["x"], end["y"]]]
        _check(
            len(vertices) >= 2
            and [vertices[0], vertices[-1]] == expected
            and wire.get("endpoints") == expected
            and type(wire.get("id")) is int
            and wire["id"] > 0,
            f"Fixture wire endpoints differ: {name}",
        )
        wire_ids.append(wire["id"])
    _check(
        len(set(wire_ids)) == len(wire_ids),
        "Fixture wires must have distinct physical IDs",
    )


def _validate_reloaded(item, expected) -> None:
    _check(
        _contains(
            {
                "component_id": expected["component_id"],
                "definition": "master:" + expected["physical_definition"],
                "location": expected["location"],
                "orientation": 0,
            },
            item,
        )
        and _contains(expected["physical_parameters"], item.get("parameters")),
        "Reload physical evidence differs from the compiled binding",
    )


def read_saved_fixture_wires(
    project_path: Path, support: Mapping[str, Any]
) -> dict[str, Any]:
    """Read conductor IDs and absolute vertices from the finalized PSCX bytes."""
    snapshot = PscxSnapshotProvider().read(project_path, "Main")
    _check(
        _sha256(project_path) == snapshot.source_fingerprint,
        "Saved PSCX changed during wire readback",
    )
    expected_ids = {str(item["wire"]["id"]) for item in support.values()}
    return {
        "source": "saved_pscx",
        "project_path": snapshot.project_path,
        "project_sha256": snapshot.source_fingerprint,
        "wires": [
            {
                "wire_id": int(wire.object_id),
                "canvas": wire.canvas_key,
                "kind": wire.kind,
                "vertices": [list(point) for point in wire.vertices],
                "evidence": [asdict(reference) for reference in wire.evidence],
            }
            for wire in snapshot.conductors
            if wire.canvas_key == "Main" and wire.object_id in expected_ids
        ],
    }


def _validate_saved_wires(readback, support, project_path, project_sha256) -> None:
    _check(
        isinstance(readback, Mapping)
        and _contains(
            {
                "source": "saved_pscx",
                "project_path": project_path,
                "project_sha256": project_sha256,
            },
            readback,
        ),
        "Saved wire readback must identify the compiled PSCX hash",
    )
    wires = readback.get("wires", [])
    for name, requested in support.items():
        wire_id = requested["wire"]["id"]
        matches = [wire for wire in wires if wire.get("wire_id") == wire_id]
        _check(
            len(matches) == 1, f"Saved wire {name} ID {wire_id} is missing or ambiguous"
        )
        wire, vertices = matches[0], requested["vertices"]
        _check(
            wire.get("canvas") == "Main"
            and wire.get("kind") == "wire"
            and wire.get("vertices") in (vertices, list(reversed(vertices))),
            f"Saved wire {name} ID {wire_id} geometry differs",
        )
        _check(
            any(
                _contains(
                    {
                        "source": "pscx",
                        "reference": f"Main:{wire_id}",
                        "fingerprint": project_sha256,
                        "status": "observed",
                    },
                    reference,
                )
                for reference in wire.get("evidence", [])
            ),
            f"Saved wire {name} has no PSCX evidence reference",
        )


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "mtime_ns": path.stat().st_mtime_ns,
    }


def _executables(run_dir: Path, project_path: Path) -> list[Path]:
    return sorted(run_dir.rglob(project_path.stem + ".exe"))


def _validate_fresh_executables(compilation) -> None:
    artifacts = compilation.get("artifacts", [])
    started = compilation.get("started_after_ns")
    _check(
        compilation.get("executables_before_build") == []
        and type(started) is int
        and started > 0
        and isinstance(artifacts, list)
        and artifacts
        and all(
            _sha(item.get("sha256"))
            and item.get("bytes", 0) > 0
            and type(item.get("mtime_ns")) is int
            and item["mtime_ns"] >= started
            and str(item.get("path", "")).casefold().endswith(".exe")
            for item in artifacts
        ),
        "A fresh compiled executable is required",
    )


def _validate_finalization(finalization, project) -> None:
    _check(isinstance(finalization, dict), "Project finalization evidence is required")
    comparison = finalization.get("semantic_comparison", {})
    _check(
        comparison.get("policy") == POLICY,
        "The direct Master report requires the default finalization policy",
    )
    expected = compare_project_finalization(
        comparison.get("authored"), comparison.get("finalized")
    )
    initial = finalization.get("compile", {})
    authored = finalization.get("authored_project_artifact", {})
    clean = finalization.get("clean", {})
    _check(
        comparison == expected
        and comparison["finalized"]["path"] == project["path"]
        and comparison["finalized"]["sha256"]
        == project["sha256"]
        == finalization.get("sha256_after_clean")
        and authored.get("sha256") == comparison["authored"]["sha256"]
        and authored.get("bytes", 0) > 0
        and initial.get("success") is True
        and not _messages_have_errors(initial.get("messages"))
        and clean.get("mode") == "vendor_project_clean"
        and clean.get("project") == project["name"]
        and str(clean.get("result", {}).get("success", "")).casefold() == "true"
        and clean.get("executables_after_clean") == [],
        "Project finalization or owned clean evidence differs",
    )
    _validate_fresh_executables(initial)
    initial_artifacts = {item["path"]: item for item in initial["artifacts"]}
    preserved = finalization.get("artifacts", [])
    _check(
        len(preserved) == len(initial_artifacts)
        and {item.get("original_path") for item in preserved} == set(initial_artifacts)
        and set(clean.get("executables_before_clean", [])) == set(initial_artifacts)
        and all(
            item.get("path") != item["original_path"]
            and all(
                item.get(key) == initial_artifacts[item["original_path"]][key]
                for key in ("sha256", "bytes")
            )
            for item in preserved
        ),
        "The canonicalization build artifacts must be preserved separately",
    )


def _delivered_artifact_hashes(report) -> dict[str, str]:
    finalization = report.get("finalization", {})
    artifacts = {
        item["path"]: item["sha256"]
        for item in (
            *report["compile"].get("artifacts", []),
            *finalization.get("artifacts", []),
        )
    }
    authored = finalization.get("authored_project_artifact", {})
    if authored.get("sha256"):
        artifacts[authored["path"]] = authored["sha256"]
    project = report.get("project", {})
    if project.get("sha256"):
        artifacts[project["path"]] = project["sha256"]
    return artifacts


def validate_mmc_master_binding_report(payload: object) -> dict[str, Any]:
    """Validate finalized evidence without inspecting live PSCAD processes."""
    _check(isinstance(payload, dict), "MMC binding report must be an object")
    _check(
        payload.get("schema_version") == 1
        and payload.get("scope") == SCOPE
        and payload.get("model_accepted") is False,
        "The report must retain its limited MMC binding scope",
    )
    _check(payload.get("status") in {"PASS", "FAIL"}, "Invalid attempt verdict")
    if payload["status"] != "PASS":
        return payload
    registry = load_mmc_master_registry()
    record = payload.get("registry", {})
    _check(
        record.get("sha256") == registry.sha256 and _sha(record.get("file_sha256")),
        "Missing exact MMC registry identity",
    )
    before, after = (
        payload.get("source_hashes_before", {}),
        payload.get("source_hashes_after", {}),
    )
    _check(
        before == after
        and payload.get("source_inputs_immutable") is True
        and all(_sha(value) for value in before.values())
        and {payload.get("master_path"), record.get("path")} <= set(before)
        and before[record["path"]] == record["file_sha256"],
        "Immutable Master and registry source hashes are required",
    )
    code_before, code_after = (
        payload.get("code_before", {}),
        payload.get("code_after", {}),
    )
    _check(
        payload.get("source_code_immutable") is True
        and bool(code_before.get("source_code_hashes"))
        and code_before.get("source_code_hashes")
        == code_after.get("source_code_hashes")
        and re.fullmatch(r"[0-9a-f]{40,64}", str(code_before.get("commit", "")))
        is not None
        and code_before.get("commit") == code_after.get("commit"),
        "Runtime code changed or has no revision evidence",
    )
    code_root = Path(code_before.get("repository", ""))
    required_code = {
        str(code_root / path)
        for path in (
            "scripts/run_mmc_master_binding_acceptance.py",
            "scripts/run_mmc_native_probe_acceptance.py",
            "pscad_mcp/core/backend/legacy.py",
            "pscad_mcp/hvdc/builders/mmc/master_bindings.py",
            "pscad_mcp/acceptance/process_scope.py",
            "pscad_mcp/acceptance/project_finalization.py",
        )
    }
    _check(
        required_code <= set(code_before["source_code_hashes"])
        and all(_sha(value) for value in code_before["source_code_hashes"].values()),
        "The acceptance runtime code must be source-hashed",
    )
    inventory = payload.get("inventory", {})
    names = set(registry.by_logical_name)
    _check(
        inventory.get("master_sha256") == before[payload["master_path"]]
        and inventory.get("master_binding_registry_sha256") == registry.sha256
        and set(inventory.get("definitions", {})) == names,
        "Live inventory coverage or source identity differs",
    )
    audited = AuditedMasterRegistry(
        registry,
        payload["master_path"],
        inventory["master_sha256"],
        inventory["definitions"],
    )
    bindings = payload.get("bindings", [])
    _check(
        isinstance(bindings, list)
        and len(bindings) == len(names)
        and {item.get("logical_name") for item in bindings} == names
        and len({item.get("component_id") for item in bindings}) == len(names),
        "Every registry binding requires a unique physical instance",
    )
    for item in bindings:
        _validate_binding(item, audited)
    _validate_support(payload.get("support"), bindings)
    compilation = payload.get("compile", {})
    _check(
        compilation.get("success") is True
        and not _messages_have_errors(compilation.get("messages")),
        "Successful compilation without error messages is required",
    )
    gate = compilation.get("binding_gate", {})
    _check(
        gate.get("master_sha256") == audited.master_sha256
        and gate.get("registry_sha256") == registry.sha256
        and set(gate.get("components", {})) == names,
        "Full binding hash gate evidence is required",
    )
    for item in bindings:
        observed = gate["components"][item["logical_name"]]
        _check(
            all(
                observed.get(key) == item[key]
                for key in (
                    "logical_parameters",
                    "observed_instances",
                    "selected_ports",
                    "physical_parameters",
                    "verification_state",
                )
            ),
            "Compile binding gate differs from readback",
        )
    _validate_fresh_executables(compilation)
    project = payload.get("project", {})
    _check(
        _sha(project.get("sha256"))
        and project.get("sha256_before_compile")
        == project.get("sha256_after_compile")
        == project["sha256"],
        "The finalized compiled project hash must be stable",
    )
    _validate_finalization(payload.get("finalization"), project)
    _validate_saved_wires(
        payload.get("wire_readback"),
        payload["support"],
        project["path"],
        project["sha256"],
    )
    artifact_hashes = _delivered_artifact_hashes(payload)
    _check(
        payload.get("artifacts_immutable") is True
        and payload.get("artifact_hashes_after_cleanup") == artifact_hashes,
        "Delivered project and executable hashes must survive owned cleanup",
    )
    persistence = payload.get("persistence", {})
    _check(
        persistence.get("readback_verified") is True
        and persistence.get("mode") in {"save_live_readback", "save_reload_readback"}
        and persistence.get("sha256_before")
        == persistence.get("sha256_after")
        == project["sha256"],
        "Saved project readback evidence is incomplete",
    )
    if persistence["mode"] == "save_live_readback":
        _check(
            persistence.get("reload_error", {}).get("code")
            == "BLUEPRINT_RELOAD_UNAVAILABLE",
            "Unavailable reload must be recorded explicitly",
        )
    else:
        readback = persistence.get("physical_readback", [])
        _check(
            len(readback) == len(names)
            and {item.get("logical_name") for item in readback} == names,
            "Reload requires every physical binding readback",
        )
        expected_bindings = {item["logical_name"]: item for item in bindings}
        for item in readback:
            _validate_reloaded(item, expected_bindings[item["logical_name"]])
    runtime, cleanup = payload.get("runtime", {}), payload.get("cleanup", {})
    require_runtime(runtime)
    _check(
        cleanup.get("managed_pid") == managed_acceptance_pid(runtime)
        and cleanup.get("owned_process_cleaned") is True
        and cleanup.get("remaining_owned_processes") == []
        and not cleanup.get("errors")
        and not cleanup.get("error"),
        "Owned PSCAD cleanup must complete without errors",
    )
    return payload


async def _read_bindings(service, project_name, components, context, bounded):
    result = []
    for name, component_id in components.items():
        observed = await bounded(
            service.backend.get_master_binding_evidence(project_name, component_id)
        )
        item = {
            **observed,
            "component_id": component_id,
            "requested_parameters": FIXTURE_PARAMETERS[name],
            "logical_parameters": await bounded(
                service.get_component_parameters(project_name, component_id)
            ),
            "ports": await bounded(
                service.get_component_ports(project_name, component_id)
            ),
            "location": await bounded(
                service.get_component_location(project_name, component_id)
            ),
        }
        _validate_binding(item, context.audited)
        result.append(item)
    return result


async def _support_fixture(service, project, bindings, context, bounded):
    by_name = {item["logical_name"]: item for item in bindings}
    definitions = context.metadata.get("const", ())
    _check(len(definitions) == 1, "Exactly one native const definition is required")
    definition = definitions[0]
    outputs = [
        port
        for port in definition.ports
        if port.name == "OUT"
        and port.dim == 1
        and port.type == "Real"
        and port.mode == "Output"
        and port.condition == "true"
    ]
    _check(
        len(outputs) == 1
        and definition.parameters["Name"].type == "Text"
        and definition.parameters["Value"].type == "Real",
        "The native PI input constant contract is unavailable",
    )
    target = by_name["master:pi_controller"]["ports"]["IN"]
    output = outputs[0]
    location = (target["x"] - 108 - output.x, target["y"] - output.y)
    parameters = {"Name": "MMC_PI_INPUT", "Value": 0.0}
    created = await bounded(
        service.add_canvas_component(
            project, "master", "const", *location, 0, parameters
        )
    )
    observed = await bounded(
        service.get_component_parameters(project, int(created["id"]))
    )
    _check(
        _contains(parameters, observed),
        "PI input constant parameter readback differs",
    )
    ports = await bounded(service.get_component_ports(project, int(created["id"])))
    port = ports.get("OUT", {})
    _check(
        port.get("dim") == 1
        and port.get("type") == "Real"
        and (port.get("x"), port.get("y"))
        == (location[0] + output.x, location[1] + output.y),
        "PI input constant must expose the metadata-verified scalar output",
    )
    pi_vertices = [[port["x"], port["y"]], [target["x"], target["y"]]]
    neutral, ground = (
        by_name["master:transformer"]["ports"]["NEUTRAL"],
        by_name["master:ground"]["ports"]["GND"],
    )
    neutral_vertices = [
        [neutral["x"], neutral["y"]],
        [neutral["x"], neutral["y"] + 108],
        [ground["x"], neutral["y"] + 108],
        [ground["x"], ground["y"]],
    ]
    source = by_name["master:source3"]["ports"]["NEUTRAL"]
    source_vertices = [
        [source["x"], source["y"]],
        [source["x"] - 72, source["y"]],
        [source["x"] - 72, ground["y"]],
        [ground["x"], ground["y"]],
    ]
    definitions = context.metadata.get("resistor", ())
    _check(len(definitions) == 1, "Exactly one native resistor definition is required")
    resistor_metadata = asdict(definitions[0])
    resistor_ports = _resistor_ports(resistor_metadata)
    dc = by_name["master:dc_bus"]["ports"]["DC"]
    resistor_location = (
        dc["x"] + 108 - resistor_ports["A"]["x"],
        dc["y"] - resistor_ports["A"]["y"],
    )
    resistor = await bounded(
        service.add_canvas_component(
            project, "master", "resistor", *resistor_location, 0, {"R": 10.0}
        )
    )
    resistor_id = int(resistor["id"])
    shunt = {
        "component": resistor,
        "metadata": resistor_metadata,
        "parameters": await bounded(
            service.get_component_parameters(project, resistor_id)
        ),
        "location": await bounded(service.get_component_location(project, resistor_id)),
        "ports": await bounded(service.get_component_ports(project, resistor_id)),
    }
    _validate_dc_shunt(shunt)
    a, b = shunt["ports"]["A"], shunt["ports"]["B"]
    dc_vertices = [[dc["x"], dc["y"]], [a["x"], a["y"]]]
    ground_vertices = [
        [b["x"], b["y"]],
        [b["x"], ground["y"] + 72],
        [ground["x"], ground["y"] + 72],
        [ground["x"], ground["y"]],
    ]
    return {
        "pi_input": {
            "component": created,
            "parameters": observed,
            "metadata": asdict(definition),
            "port": port,
            "vertices": pi_vertices,
            "wire": await bounded(service.create_wire(project, pi_vertices)),
        },
        "transformer_neutral": {
            "vertices": neutral_vertices,
            "wire": await bounded(service.create_wire(project, neutral_vertices)),
        },
        "source_neutral": {
            "vertices": source_vertices,
            "wire": await bounded(service.create_wire(project, source_vertices)),
        },
        "dc_shunt": {
            **shunt,
            "vertices": dc_vertices,
            "wire": await bounded(service.create_wire(project, dc_vertices)),
        },
        "dc_shunt_ground": {
            "vertices": ground_vertices,
            "wire": await bounded(service.create_wire(project, ground_vertices)),
        },
    }


async def _persistence(service, project, bindings, context, bounded):
    result = {
        "sha256_before": _sha256(Path(project["path"])),
        "readback_verified": False,
    }
    try:
        await bounded(service.reload_project(project["name"], project["path"]))
    except BackendError as error:
        if error.code != "BLUEPRINT_RELOAD_UNAVAILABLE":
            raise
        result.update(mode="save_live_readback", reload_error=_error(error))
        await _read_bindings(
            service,
            project["name"],
            {item["logical_name"]: item["component_id"] for item in bindings},
            context,
            bounded,
        )
    else:
        result.update(mode="save_reload_readback", physical_readback=[])
        components = {
            item["id"]: item
            for item in await bounded(service.list_canvas_components(project["name"]))
        }
        # Reload clears the legacy binding cache. Check native identity and full
        # parameters directly; selected-port evidence belongs to the compile gate.
        for item in bindings:
            name, component_id = item["logical_name"], item["component_id"]
            native = components.get(component_id, {})
            parameters = await bounded(
                service.get_component_parameters(project["name"], component_id)
            )
            location = await bounded(
                service.get_component_location(project["name"], component_id)
            )
            observed = {
                "logical_name": name,
                "component_id": component_id,
                "definition": native.get("definition"),
                "parameters": parameters,
                "location": location,
                "orientation": native.get("orientation"),
            }
            _validate_reloaded(observed, item)
            result["physical_readback"].append(observed)
    result["sha256_after"] = _sha256(Path(project["path"]))
    _check(
        result["sha256_before"] == result["sha256_after"],
        "Persistence changed the finalized project",
    )
    result["readback_verified"] = True
    return result


async def _compile_fixture(
    service, project_path, run_dir, component_ids, context, record, bounded, timeout
):
    project_name = project_path.stem
    record["success"] = False
    record["binding_gate"] = await bounded(
        service.backend.verify_master_binding_state(
            project_name,
            component_ids,
            context.audited.master_sha256,
            context.audited.registry.sha256,
        )
    )
    record["executables_before_build"] = [
        str(path) for path in _executables(run_dir, project_path)
    ]
    _check(
        not record["executables_before_build"],
        "A fresh fixture must not contain a pre-existing project executable",
    )
    record["started_at"] = _stamp()
    # Windows' precise wall clock can run ahead of newly created file mtimes.
    # Use the same filesystem as the compiler, keeping the empty-before-build
    # requirement above and the unchanged nanosecond freshness gate below.
    with tempfile.NamedTemporaryFile(dir=run_dir, prefix=".compile-", suffix=".stamp", delete=False) as stream:
        marker = Path(stream.name)
        stream.write(b"compile boundary\n")
    try:
        record["started_after_ns"] = marker.stat().st_mtime_ns
    finally:
        marker.unlink()
    record["started_after"] = record["started_after_ns"] / 1_000_000_000
    record["clock_basis"] = "filesystem"
    record["result"] = await bounded(service.build_project(project_name), timeout)
    record["messages"] = await bounded(
        service.get_project_output(project_name, structured=True)
    )
    _check(
        not _messages_have_errors(record["messages"]), "PSCAD reported compiler errors"
    )
    executables = _executables(run_dir, project_path)
    _check(
        executables
        and all(
            path.is_file()
            and not path.is_symlink()
            and path.resolve().is_relative_to(run_dir.resolve())
            for path in executables
        ),
        "The build produced no fresh project executable",
    )
    record["artifacts"] = [_artifact(path) for path in executables]
    _validate_fresh_executables(record)
    record["success"] = True


async def _finalize_project(
    service, project_path, run_dir, component_ids, context, record, bounded, timeout
):
    project_name = project_path.stem
    evidence_dir = run_dir / "canonicalization"
    evidence_dir.mkdir()
    authored = snapshot_project_semantics(project_path)
    authored_copy = evidence_dir / "authored.pscx"
    shutil.copy2(project_path, authored_copy)
    record["authored_project_artifact"] = _artifact(authored_copy)
    _check(
        record["authored_project_artifact"]["sha256"] == authored["sha256"],
        "The authored project changed while preserving finalization evidence",
    )
    record["semantic_comparison"] = {"authored": authored}
    record["compile"] = {}
    await _compile_fixture(
        service,
        project_path,
        run_dir,
        component_ids,
        context,
        record["compile"],
        bounded,
        timeout,
    )
    record["save_result"] = await bounded(
        service.save_project(project_name, confirm=True)
    )
    finalized = snapshot_project_semantics(project_path)
    record["semantic_comparison"]["finalized"] = finalized
    record["semantic_comparison"] = compare_project_finalization(authored, finalized)
    record["artifacts"] = []
    for index, item in enumerate(record["compile"]["artifacts"]):
        source = Path(item["path"])
        copy = evidence_dir / f"initial-{index}-{source.name}"
        shutil.copy2(source, copy)
        preserved = {**_artifact(copy), "original_path": str(source)}
        _check(
            preserved["sha256"] == item["sha256"],
            "The canonicalization executable changed while preserving evidence",
        )
        record["artifacts"].append(preserved)
    clean = record["clean"] = {
        "mode": "vendor_project_clean",
        "project": project_name,
        "executables_before_clean": [
            str(path) for path in _executables(run_dir, project_path)
        ],
    }
    native_project = await bounded(service.backend._project(project_name))
    operation = getattr(native_project, "clean", None)
    _check(callable(operation), "The owned vendor project has no clean capability")
    response = await bounded(
        service.backend.executor.run_safe(operation, timeout=timeout), timeout
    )
    clean["result"] = legacy_support.response_payload(response)
    legacy_support.require_success(response, "clean_project", {"project": project_name})
    clean["executables_after_clean"] = [
        str(path) for path in _executables(run_dir, project_path)
    ]
    _check(
        not clean["executables_after_clean"],
        "The owned project clean left a canonicalization executable behind",
    )
    record["sha256_after_clean"] = _sha256(project_path)
    _check(
        record["sha256_after_clean"] == finalized["sha256"],
        "The finalized project changed during owned clean",
    )
    return finalized["sha256"]


async def run_attempt(
    args: argparse.Namespace, run_dir: Path, *, service_factory=_service
) -> dict[str, Any]:
    _require_optins()
    report_path = run_dir / "report.json"
    report = {
        "schema_version": 1,
        "scope": SCOPE,
        "status": "FAIL",
        "model_accepted": False,
        "started_at": _stamp(),
        "run_directory": str(run_dir),
        "master_path": str(args.master),
        "remaining_scope": REMAINING_SCOPE,
        "concurrent": concurrent_acceptance_enabled(),
        "stages": [],
        "bindings": [],
        "compile": {"success": False},
    }
    stage, service, runtime, project_name = "inputs", None, {}, None
    attach_attempted, input_hashes, code_before = False, {}, {}

    def begin(name):
        nonlocal stage
        if report["stages"]:
            report["stages"][-1].update(status="PASS", finished_at=_stamp())
        stage = name
        report["stages"].append(
            {"name": name, "status": "RUNNING", "started_at": _stamp()}
        )
        _write_report(report_path, report)
        print(f"MMC_MASTER_BINDING_STAGE={name}", flush=True)

    async def bounded(awaitable, timeout=None):
        return await asyncio.wait_for(
            awaitable, args.operation_timeout if timeout is None else timeout
        )

    try:
        begin("inputs")
        for source in (args.master, REGISTRY_PATH):
            if source.is_symlink() or not source.is_file():
                raise FileNotFoundError(
                    f"Required immutable source is not a regular file: {source}"
                )
        input_hashes = {
            str(path): _sha256(path) for path in (args.master, REGISTRY_PATH)
        }
        report["source_hashes_before"] = input_hashes
        code_before = report["code_before"] = _code_snapshot()
        context = audit_mmc_master_bindings(args.master)
        registry = context.audited.registry
        _check(
            set(registry.by_logical_name) == set(FIXTURE_PARAMETERS),
            "Fixture parameters must cover the complete MMC direct registry",
        )
        report["registry"] = {
            "path": str(REGISTRY_PATH),
            "file_sha256": input_hashes[str(REGISTRY_PATH)],
            "sha256": registry.sha256,
        }
        report["processes_before"] = list_pscad_processes()
        begin("attach")
        service = service_factory(run_dir)
        report["runtime_before"] = await bounded(service.status())
        attach_attempted = True
        report["attach_result"] = await bounded(service.attach_local())
        begin("runtime")
        runtime = report["runtime"] = await bounded(service.status())
        require_runtime(runtime)
        service.backend.definition_paths["master"] = args.master
        begin("inventory")
        inventory = report["inventory"] = await bounded(
            service.get_lcc_inventory(_catalog(context), registry.to_dict())
        )
        _check(
            inventory["master_sha256"] == context.audited.master_sha256
            and inventory["master_binding_registry_sha256"] == registry.sha256,
            "Live inventory hashes differ from the audited MMC inputs",
        )
        begin("place_bindings")
        project = await bounded(
            service.create_project(
                "case",
                "MMC_MASTER_" + uuid.uuid4().hex[:10] + ".pscx",
                str(run_dir),
                confirm=True,
            )
        )
        project_name = project["name"]
        project_path = Path(project["filename"])
        _check(
            project_path.resolve().parent == run_dir.resolve(),
            "The created project must stay in this attempt workspace",
        )
        report["project"] = {"name": project_name, "path": str(project_path)}
        component_ids = {}
        for index, binding in enumerate(registry.bindings):
            name = binding.logical_name
            raw = FIXTURE_PARAMETERS[name]
            resolved = context.resolve_component(name, raw)
            created = await bounded(
                service.add_canvas_component(
                    project_name,
                    "master",
                    name.split(":", 1)[1],
                    180 + 360 * (index % 3),
                    180 + 360 * (index // 3),
                    0,
                    normalize_mmc_master_parameters(name, raw),
                    binding_evidence=resolved.to_evidence(),
                )
            )
            component_ids[name] = int(created["id"])
        report["bindings"] = await _read_bindings(
            service, project_name, component_ids, context, bounded
        )
        begin("fixture_connections")
        report["support"] = await _support_fixture(
            service, project_name, report["bindings"], context, bounded
        )
        begin("save_readback")
        report["save_result"] = await bounded(
            service.save_project(project_name, confirm=True)
        )
        report["bindings"] = await _read_bindings(
            service, project_name, component_ids, context, bounded
        )
        authored_sha256 = _sha256(project_path)
        report["wire_readback"] = await bounded(
            asyncio.to_thread(read_saved_fixture_wires, project_path, report["support"])
        )
        _validate_saved_wires(
            report["wire_readback"],
            report["support"],
            str(project_path),
            authored_sha256,
        )
        report["authored_wire_readback"] = report["wire_readback"]
        begin("finalize_project")
        report["finalization"] = {}
        report["project"]["sha256"] = await _finalize_project(
            service,
            project_path,
            run_dir,
            component_ids,
            context,
            report["finalization"],
            bounded,
            args.build_timeout,
        )
        report["bindings"] = await _read_bindings(
            service, project_name, component_ids, context, bounded
        )
        report["wire_readback"] = await bounded(
            asyncio.to_thread(read_saved_fixture_wires, project_path, report["support"])
        )
        _validate_saved_wires(
            report["wire_readback"],
            report["support"],
            str(project_path),
            report["project"]["sha256"],
        )
        begin("compile")
        report["project"]["sha256_before_compile"] = _sha256(project_path)
        _check(
            report["project"]["sha256_before_compile"] == report["project"]["sha256"],
            "The finalized project changed before the fresh compile",
        )
        await _compile_fixture(
            service,
            project_path,
            run_dir,
            component_ids,
            context,
            report["compile"],
            bounded,
            args.build_timeout,
        )
        report["project"]["sha256_after_compile"] = _sha256(project_path)
        _check(
            report["project"]["sha256_after_compile"] == report["project"]["sha256"],
            "The finalized project changed during compilation",
        )
        report["compile"]["success"] = True
        begin("persistence")
        report["persistence"] = await _persistence(
            service, report["project"], report["bindings"], context, bounded
        )
        report["status"] = "PASS"
        report["stages"][-1].update(status="PASS", finished_at=_stamp())
    except BaseException as error:  # noqa: BLE001 - interrupted attempts need durable evidence
        report.update(
            status="FAIL",
            failure_category=_category(stage, error),
            failed_stage=stage,
            error=_error(error),
        )
        if report["stages"]:
            report["stages"][-1].update(
                status="FAIL", finished_at=_stamp(), error=_error(error)
            )
        if service is not None and project_name and managed_acceptance_pid(runtime):
            try:
                report["failure_messages"] = await bounded(
                    service.get_project_output(project_name, structured=True)
                )
            except BaseException as error:  # noqa: BLE001 - diagnostics must not prevent cleanup
                report["failure_messages_error"] = _error(error)
    finally:
        try:
            _write_report(report_path, report)
        except OSError as error:
            report.update(status="FAIL", pre_cleanup_report_error=_error(error))
        try:
            if service is not None and attach_attempted:
                if not runtime:
                    runtime = report["runtime_after_error"] = await bounded(
                        service.status()
                    )
                report["cleanup"] = await cleanup_owned_session(
                    service,
                    runtime,
                    project_name=project_name,
                    run_pending=False,
                    process_reader=list_pscad_processes,
                    timeout=args.cleanup_timeout,
                )
            else:
                report["cleanup"] = {
                    "owned_process_cleaned": True,
                    "runtime_started": False,
                    "remaining_owned_processes": [],
                }
            if not report["cleanup"]["owned_process_cleaned"] or report["cleanup"].get(
                "errors"
            ):
                report["status"] = "FAIL"
                report.setdefault("failure_category", "process_cleanup")
        except BaseException as error:  # noqa: BLE001 - retain cleanup failures through final verification
            report.update(
                status="FAIL",
                cleanup={"owned_process_cleaned": False, "error": _error(error)},
            )
            report.setdefault("failure_category", "process_cleanup")
        try:
            report["source_hashes_after"] = {
                path: _sha256(Path(path)) for path in input_hashes
            }
            report["source_inputs_immutable"] = (
                bool(input_hashes) and input_hashes == report["source_hashes_after"]
            )
            if code_before:
                report["code_after"] = _code_snapshot()
                report["source_code_immutable"] = (
                    code_before["source_code_hashes"]
                    == report["code_after"]["source_code_hashes"]
                    and code_before["commit"] == report["code_after"]["commit"]
                )
            if not report["source_inputs_immutable"] or not report.get(
                "source_code_immutable"
            ):
                report["status"] = "FAIL"
                report.setdefault("failure_category", "implementation_defect")
            artifacts = _delivered_artifact_hashes(report)
            report["artifact_hashes_after_cleanup"] = {
                path: _sha256(Path(path)) for path in artifacts
            }
            report["artifacts_immutable"] = (
                bool(artifacts) and artifacts == report["artifact_hashes_after_cleanup"]
            )
            validate_mmc_master_binding_report(report)
        except BaseException as error:  # noqa: BLE001 - final verification must preserve the report
            report.update(status="FAIL", validation_error=_error(error))
            report.setdefault("failure_category", "implementation_defect")
        report["finished_at"] = _stamp()
        report = _json_safe(report)
        _write_report(report_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument(
        "--master",
        type=Path,
        default=Path(
            os.getenv(
                "PSCAD_MCP_MASTER_LIBRARY",
                r"C:\Program Files (x86)\PSCAD46\master.pslx",
            )
        ),
    )
    parser.add_argument("--operation-timeout", type=float, default=120.0)
    parser.add_argument("--build-timeout", type=float, default=360.0)
    parser.add_argument("--cleanup-timeout", type=float, default=30.0)
    return parser


def main(argv: Sequence[str] | None = None, *, service_factory=_service) -> int:
    args = _parser().parse_args(argv)
    try:
        _require_optins()
    except PermissionError as error:
        print(str(error), file=sys.stderr)
        return 2
    if any(
        not math.isfinite(getattr(args, key)) or getattr(args, key) <= 0
        for key in ("operation_timeout", "build_timeout", "cleanup_timeout")
    ):
        raise SystemExit("Timeouts must be finite and positive")
    if not args.workspace_root.expanduser().is_absolute():
        raise SystemExit("--workspace-root must be absolute")
    for key in ("workspace_root", "master"):
        path = getattr(args, key).expanduser()
        if path.is_symlink():
            raise SystemExit("Symbolic-link sources and workspaces are unsupported")
        setattr(args, key, path.resolve())
    for source in (args.master, REGISTRY_PATH):
        if args.workspace_root.is_relative_to(source.parent) or source.is_relative_to(
            args.workspace_root
        ):
            raise SystemExit(
                "The workspace must be disjoint from immutable source directories"
            )
    run_dir = args.workspace_root / (
        "mmc-master-binding-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    report = asyncio.run(run_attempt(args, run_dir, service_factory=service_factory))
    print(f"MMC_MASTER_BINDING_STATUS={report['status']}")
    print(f"MMC_MASTER_BINDING_REPORT={run_dir / 'report.json'}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
