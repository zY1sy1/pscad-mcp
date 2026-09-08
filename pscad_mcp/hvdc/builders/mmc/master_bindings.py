"""MMC normalization and checked use of the shared physical Master registry."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from ....core.backend.base import BackendError
from ....core.definition_metadata import (
    DefinitionMetadata,
    read_definition_metadata_document,
)
from ....core.master_bindings import (
    AuditedMasterRegistry,
    MasterBindingRegistry,
    ResolvedMasterComponent,
    _validate_bound_physical_value,
    audit_master_bindings,
    parse_master_binding_registry,
)
from ..common.serialization import content_hash, json_safe
from .catalog import MmcCatalog

_FIELDS = {
    "master:dc_bus": {"Name"},
    "master:source3": {"Name", "Amplitude", "Frequency", "GridR", "GridX"},
    "master:transformer": {
        "Name",
        "RatedPower_MVA",
        "Primary_kV",
        "Secondary_kV",
        "Frequency",
        "Leakage_pu",
    },
    "master:pi_controller": {"Kp", "Ti_s", "Lower", "Upper", "Initial"},
    "master:ground": set(),
}


def _error(message: str, **details: Any) -> BackendError:
    return BackendError(
        "MMC_PARAMETER_MISMATCH", message, "hvdc", "normalize_mmc_master", details
    )


def load_mmc_master_registry() -> MasterBindingRegistry:
    data = (
        resources.files("pscad_mcp")
        .joinpath("assets/mmc/master_bindings/pscad-4.6.2.json")
        .read_bytes()
    )
    return parse_master_binding_registry(json.loads(data))


def native_inventory_catalog(catalog: Mapping[str, Any] | MmcCatalog) -> dict[str, Any]:
    """Request the whole audited registry alongside the declared companion types."""
    payload = json_safe(asdict(catalog) if isinstance(catalog, MmcCatalog) else catalog)
    definitions = payload.setdefault("definitions", {})
    for binding in load_mmc_master_registry().bindings:
        definitions[binding.logical_name] = {
            "ports": [
                {"name": port.logical, "kind": port.kind, "dimension": port.dimension}
                for port in binding.ports
            ]
        }
    return payload


def normalize_mmc_master_parameters(
    logical_name: str, parameters: Mapping[str, Any]
) -> dict[str, Any]:
    expected = _FIELDS.get(logical_name)
    if expected is None:
        raise BackendError(
            "MASTER_BINDING_MISSING",
            "No direct MMC Master binding is defined for this component.",
            "hvdc",
            "normalize_mmc_master",
            {"logical_name": logical_name},
        )
    if not isinstance(parameters, Mapping) or set(parameters) != expected:
        raise _error(
            "The MMC Master request must match its explicit parameter contract.",
            logical_name=logical_name,
            required=sorted(expected),
        )
    result = dict(parameters)
    for key, value in result.items():
        if key == "Name":
            if not isinstance(value, str) or not value.strip():
                raise _error(
                    "A Master component name must be a nonempty string.", parameter=key
                )
            if (
                logical_name == "master:dc_bus"
                and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value) is None
            ):
                raise _error(
                    "A DC node requires an explicit valid electrical identifier.",
                    parameter=key,
                )
        else:
            try:
                valid = (
                    not isinstance(value, bool)
                    and isinstance(value, (int, float))
                    and math.isfinite(float(value))
                )
            except (ValueError, TypeError, OverflowError):
                valid = False
            if not valid:
                raise _error(
                    "Numeric Master parameters must be finite real values.",
                    parameter=key,
                )
    positive = expected - {"Name", "Kp", "Lower", "Upper", "Initial"}
    if any(result[name] <= 0 for name in positive):
        raise _error(
            "Physical ratings, frequency, impedance and time constants must be positive.",
            logical_name=logical_name,
        )
    if logical_name == "master:source3":
        magnitude = math.hypot(result["GridR"], result["GridX"])
        angle = math.degrees(math.atan2(result["GridX"], result["GridR"]))
        if not math.isfinite(magnitude) or not 0.1 <= angle <= 89.9:
            raise _error(
                "The requested R/X is outside the installed impedance-angle profile.",
                angle_deg=angle,
            )
        result.update(
            GridMagnitude=magnitude,
            GridAngle=angle,
            OperatingVoltage_kV=result["Amplitude"],
            OperatingFrequency_Hz=result["Frequency"],
        )
    if (
        logical_name == "master:pi_controller"
        and not result["Lower"] <= result["Initial"] <= result["Upper"]
    ):
        raise _error("PI initial state must be inside its declared limits.")
    return result


@dataclass(frozen=True)
class MmcMasterContext:
    audited: AuditedMasterRegistry
    metadata: Mapping[str, tuple[DefinitionMetadata, ...]]

    def resolve_component(
        self, logical_name: str, parameters: Mapping[str, Any]
    ) -> ResolvedMasterComponent:
        source = Path(self.audited.master_path)
        if (
            hashlib.sha256(source.read_bytes()).hexdigest()
            != self.audited.master_sha256
        ):
            raise BackendError(
                "MASTER_SOURCE_CHANGED",
                "Master changed after the MMC binding audit.",
                "hvdc",
                "resolve_mmc_master",
                {},
            )
        normalized = normalize_mmc_master_parameters(logical_name, parameters)
        resolved = self.audited.resolve_component(logical_name, normalized)
        definition = self.metadata[resolved.physical_definition][0]
        binding = self.audited.registry.by_logical_name[logical_name]
        for name, value in resolved.physical_parameters.items():
            _validate_bound_physical_value(
                binding, name, value, definition.parameters[name]
            )
        return resolved


def audit_mmc_master_bindings(master_path: str | Path) -> MmcMasterContext:
    path = Path(master_path)
    if path.is_symlink() or not path.is_file():
        raise BackendError(
            "MASTER_SOURCE_CHANGED",
            "The MMC Master source must be a regular file.",
            "hvdc",
            "audit_mmc_master",
            {},
        )
    payload = path.read_bytes()
    audited = audit_master_bindings(path, load_mmc_master_registry())
    if hashlib.sha256(payload).hexdigest() != audited.master_sha256:
        raise BackendError(
            "MASTER_SOURCE_CHANGED",
            "Master changed during the MMC binding audit.",
            "hvdc",
            "audit_mmc_master",
            {},
        )
    return MmcMasterContext(audited, read_definition_metadata_document(payload))


def context_from_inventory(inventory: Any) -> MmcMasterContext | None:
    """Recheck native evidence; bare injected inventories retain their test contract."""
    identity = {"master_path", "master_sha256", "master_binding_registry_sha256"}
    if not isinstance(inventory, Mapping) or not identity.intersection(inventory):
        return None
    if not identity <= inventory.keys() or not isinstance(
        inventory["master_path"], str
    ):
        raise BackendError(
            "MASTER_BINDING_MISSING",
            "MMC inventory has incomplete native Master identity.",
            "hvdc",
            "create_mmc_plan",
            {},
        )
    context = audit_mmc_master_bindings(inventory["master_path"])
    audited = context.audited
    if (
        inventory["master_sha256"] != audited.master_sha256
        or inventory["master_binding_registry_sha256"] != audited.registry.sha256
    ):
        raise BackendError(
            "MASTER_SOURCE_CHANGED",
            "MMC inventory no longer matches the installed Master and registry.",
            "hvdc",
            "create_mmc_plan",
            {},
        )
    observed = inventory.get("definitions", {})
    for name, expected in audited.definitions.items():
        record = observed.get(name) if isinstance(observed, Mapping) else None
        keys = (
            "logical_name",
            "physical_definition",
            "selected_ports",
            "verification_state",
        )
        if not isinstance(record, Mapping) or content_hash(
            {key: record.get(key) for key in keys}
        ) != content_hash({key: expected.get(key) for key in keys}):
            raise BackendError(
                "MASTER_SOURCE_CHANGED",
                "MMC inventory contains altered or incomplete physical definition evidence.",
                "hvdc",
                "create_mmc_plan",
                {"logical_name": name},
            )
    return context
