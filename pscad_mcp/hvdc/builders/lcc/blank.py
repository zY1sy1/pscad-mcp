"""Request and plan records for blank-project LCC builds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..common.blank import BlankProjectFactory
from ..common.serialization import content_hash


@dataclass(frozen=True)
class BlankLccRequest:
    project_name: str
    folder: str | None = None
    topology: str = "single_pole_12_pulse"
    ratings: Mapping[str, Any] = None  # type: ignore[assignment]
    operation_modes: tuple[str, ...] = ()
    parameterization: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ratings",
            dict(self.ratings or {"dc_voltage_kv": 500.0, "power_mw": 1000.0}),
        )
        object.__setattr__(self, "parameterization", dict(self.parameterization or {}))
        object.__setattr__(
            self,
            "operation_modes",
            tuple(self.operation_modes or ("rectifier", "inverter")),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> BlankLccRequest:
        return cls(
            project_name=str(value.get("project_name", "")),
            folder=value.get("folder"),
            topology=str(value.get("topology", "single_pole_12_pulse")),
            ratings=value.get("ratings"),
            operation_modes=tuple(value.get("operation_modes", ())),
            parameterization=value.get("parameterization"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "folder": self.folder,
            "topology": self.topology,
            "ratings": dict(self.ratings),
            "operation_modes": list(self.operation_modes),
            "parameterization": dict(self.parameterization),
        }


def plan_blank_lcc(
    request: BlankLccRequest, *, workspace_root: str, inventory: Any = None
) -> dict[str, Any]:
    destination = BlankProjectFactory(workspace_root).plan(
        request.project_name, folder=request.folder
    )
    payload = {
        "request": request.to_dict(),
        **destination,
        "pscad_version": "4.6.2",
        "required_components": [
            "sending_ac_system",
            "receiving_ac_system",
            "converter_transformer",
            "two_six_pulse_bridges",
            "smoothing_reactor",
            "dc_line",
            "ac_filters",
            "reactive_compensation",
            "rectifier_control",
            "inverter_control",
        ],
        "output_channels": [
            {"role": "dc_voltage", "units": "kV"},
            {"role": "dc_current", "units": "kA"},
            {"role": "dc_power", "units": "MW"},
            {"role": "firing_angle", "units": "deg"},
            {"role": "extinction_angle", "units": "deg"},
        ],
        "fault_events": [
            {
                "name": "inverter_ac_disturbance",
                "kind": "inverter_ac_disturbance",
                "time_s": 0.5,
                "duration_s": 0.1,
                "magnitude_pu": 0.8,
            }
        ],
        "capabilities": {
            "commutation_failure_detection": True,
            "commutation_failure_recovery": True,
        },
        "inventory_version": inventory.get("version")
        if isinstance(inventory, Mapping)
        else None,
    }
    payload["plan_hash"] = content_hash(payload)
    return payload


__all__ = ["BlankLccRequest", "plan_blank_lcc"]
