"""Request and plan records for blank-project MMC builds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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
    payload["plan_hash"] = content_hash(payload)
    return payload


__all__ = ["BlankMmcRequest", "plan_blank_mmc"]
