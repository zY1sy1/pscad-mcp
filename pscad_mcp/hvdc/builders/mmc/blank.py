"""Request and plan records for blank-project MMC builds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ....core.backend.base import BackendError
from ..common.blank import BlankProjectFactory
from ..common.serialization import content_hash
from .models import SubmoduleTopology


@dataclass(frozen=True)
class BlankMmcRequest:
    project_name: str
    folder: str | None = None
    submodule_topology: SubmoduleTopology = SubmoduleTopology.FULL_BRIDGE
    ratings: Mapping[str, Any] = None  # type: ignore[assignment]
    control_profile: str = "active_reactive_dc_voltage"
    fault_profile: str = "dc_pole_to_pole_and_recovery"
    parameterization: Mapping[str, Any] = None  # type: ignore[assignment]
    template_path: str | None = None
    library_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "submodule_topology", SubmoduleTopology(self.submodule_topology)
        )
        object.__setattr__(
            self,
            "ratings",
            dict(self.ratings or {"dc_voltage_kv": 320.0, "power_mw": 1000.0}),
        )
        object.__setattr__(self, "parameterization", dict(self.parameterization or {}))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BlankMmcRequest:
        return cls(
            project_name=str(value.get("project_name", "")),
            folder=value.get("folder"),
            submodule_topology=value.get(
                "submodule_topology", SubmoduleTopology.FULL_BRIDGE
            ),
            ratings=value.get("ratings"),
            control_profile=str(
                value.get("control_profile", "active_reactive_dc_voltage")
            ),
            fault_profile=str(
                value.get("fault_profile", "dc_pole_to_pole_and_recovery")
            ),
            parameterization=value.get("parameterization"),
            template_path=value.get("template_path"),
            library_path=value.get("library_path"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "folder": self.folder,
            "submodule_topology": self.submodule_topology.value,
            "ratings": dict(self.ratings),
            "control_profile": self.control_profile,
            "fault_profile": self.fault_profile,
            "parameterization": dict(self.parameterization),
            "template_path": self.template_path,
            "library_path": self.library_path,
        }


def plan_blank_mmc(request: BlankMmcRequest, *, workspace_root: str) -> dict[str, Any]:
    destination = BlankProjectFactory(workspace_root).plan(
        request.project_name, folder=request.folder
    )
    topology = request.submodule_topology
    payload = {
        "request": request.to_dict(),
        **destination,
        "pscad_version": "4.6.2",
        "component_contract": {
            "arms": 6,
            "submodules_per_arm": int(
                request.parameterization.get("submodules_per_arm", 4)
            ),
            "serial_submodules": True,
            "submodule_definition": "companion:FullBridgeSubmodule",
            "ports": [
                "DC_POS",
                "DC_NEG",
                "AC",
                "CAPACITOR_STATE",
                "SWITCH_STATE",
                "GATES",
                "V_INSERTED",
                "I_ARM",
            ],
        },
        "required_components": [
            "two_ac_systems",
            "converter_transformers",
            "six_mmc_arms",
            "arm_inductors",
            "dc_line",
            "active_reactive_control",
            "circulating_current_suppression",
            "capacitor_voltage_sorting",
        ],
        "output_channels": [
            {"role": "submodule_capacitor_voltage", "units": "kV"},
            {"role": "arm_current", "units": "kA"},
            {"role": "circulating_current", "units": "kA"},
            {"role": "dc_voltage", "units": "kV"},
            {"role": "dc_current", "units": "kA"},
            {"role": "gate_state", "units": "1"},
        ],
        "fault_events": [
            {
                "name": "dc_fault",
                "kind": "dc_pole_to_pole",
                "time_s": 0.3,
                "removal_time_s": 0.5,
            }
        ],
        "capabilities": topology.capabilities(topology),
    }
    if request.template_path or request.library_path:
        if not request.template_path or not request.library_path:
            raise ValueError("template_path and library_path must be supplied together")
        from .template_audit import audit_mmc_template

        audit = audit_mmc_template(request.template_path, request.library_path)
        observed = audit.get("submodule_topology", {})
        declared = observed.get("declared") if isinstance(observed, Mapping) else "unknown"
        if declared not in {topology.value, "unknown"}:
            raise BackendError(
                "MMC_TEMPLATE_TOPOLOGY_MISMATCH",
                "The official MMC template topology differs from the request.",
                "hvdc",
                "plan_blank_mmc_model",
                {"requested": topology.value, "observed": declared},
            )
        payload["native_template"] = audit
        payload["capabilities"] = {
            **payload["capabilities"],
            "template_submodule_topology": declared,
            "template_native_timing": bool(
                isinstance(audit.get("template_native_controls"), Mapping)
                and audit["template_native_controls"].get("available") is True
            ),
            "native_schedule": False,
        }
    payload["plan_hash"] = content_hash(payload)
    return payload


__all__ = ["BlankMmcRequest", "plan_blank_mmc"]
