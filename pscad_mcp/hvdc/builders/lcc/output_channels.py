"""Map native output selectors to the identities declared by an LCC blueprint."""

from collections.abc import Mapping, Sequence
from typing import Any

from ....core.backend.base import BackendError


def logical_output_payload(value: Any, blueprint: Mapping[str, Any]) -> Any:
    if not isinstance(value, Mapping):
        return value
    raw_channels = value.get("channels")
    if not isinstance(raw_channels, Sequence) or isinstance(raw_channels, (str, bytes, bytearray)):
        return value
    components = {
        component["logical_id"]: component
        for component in blueprint.get("components", ())
    }
    measurements = {
        measurement.get("logical_id"): measurement
        for measurement in blueprint.get("measurements", ())
        if isinstance(measurement, Mapping)
        and isinstance(measurement.get("logical_id"), str)
    }
    physical_to_logical = {}
    for output in blueprint.get("outputs", ()):
        measurement = measurements.get(output.get("measurement"))
        component_id = measurement.get("component") if isinstance(measurement, Mapping) else None
        component = components.get(component_id)
        if component is None:
            continue
        logical_path = output["path"]
        physical_path = component["definition"].rsplit(":", 1)[-1] + "/" + logical_path.rsplit("/", 1)[-1]
        previous = physical_to_logical.setdefault(physical_path, logical_path)
        if previous != logical_path:
            raise BackendError(
                "LCC_OUTPUT_INCOMPLETE",
                "Physical output selectors are ambiguous.",
                "hvdc", "read_lcc_output", {"physical_path": physical_path},
            )
    normalized_channels = []
    observed_paths = set()
    for raw_channel in raw_channels:
        if not isinstance(raw_channel, Mapping):
            normalized_channels.append(raw_channel)
            continue
        channel = dict(raw_channel)
        raw_path = channel.get("path")
        if isinstance(raw_path, str) and raw_path in physical_to_logical:
            channel["path"] = physical_to_logical[raw_path]
        normalized_path = channel.get("path")
        if isinstance(normalized_path, str) and normalized_path in observed_paths:
            raise BackendError(
                "LCC_OUTPUT_INCOMPLETE",
                "Logical output selectors are duplicated.",
                "hvdc", "read_lcc_output", {"path": normalized_path},
            )
        if isinstance(normalized_path, str):
            observed_paths.add(normalized_path)
        normalized_channels.append(channel)
    return {**value, "channels": normalized_channels}
