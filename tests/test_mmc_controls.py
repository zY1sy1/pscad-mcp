import math

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.controls import (
    MmcBandwidthConfig,
    MmcSequenceObservation,
    MmcSequencePhaseName,
    MmcTransitionResult,
    fixed_control_set,
    reduce_sequence,
)


def test_fixed_controls_assign_station_roles_and_separate_bandwidths():
    controls = fixed_control_set()
    assert {station.station_id for station in controls.stations} == {"STATION_P", "STATION_VDC"}
    p = next(station for station in controls.stations if station.station_id == "STATION_P")
    vdc = next(station for station in controls.stations if station.station_id == "STATION_VDC")
    assert (p.active_control, p.reactive_control, p.dc_voltage_control) == ("P", "Q", None)
    assert (vdc.active_control, vdc.reactive_control, vdc.dc_voltage_control) == (None, "Q", "Vdc")
    values = controls.bandwidths.as_tuple()
    assert values == tuple(sorted(values))
    assert len(set(values)) == len(values)
    assert all(math.isfinite(limit) and limit > 0 for station in controls.stations for limit in station.anti_windup_limits.values())
    assert [phase.value for phase in controls.sequence] == [
        "blocked_precharge", "ready_to_deblock", "forward_ramp", "forward_steady", "power_reversal", "reverse_steady"
    ]


def test_bandwidth_config_rejects_non_separated_or_non_finite_values():
    with pytest.raises(BackendError):
        MmcBandwidthConfig(pll_hz=10, outer_hz=10, energy_hz=20, circulating_hz=30, inner_hz=40)
    with pytest.raises(BackendError):
        MmcBandwidthConfig(pll_hz=10, outer_hz=20, energy_hz=math.inf, circulating_hz=30, inner_hz=40)


def test_sequence_reducer_allows_only_declared_forward_and_reverse_edges():
    ready = MmcSequenceObservation(ready=True, pll_locked=True, energy_ok=True, current_ok=True, modulation_ok=True)
    result = reduce_sequence("blocked_precharge", ready)
    assert isinstance(result, MmcTransitionResult)
    assert result.accepted is True
    assert result.phase == MmcSequencePhaseName.READY_TO_DEBLOCK.value

    early = reduce_sequence("blocked_precharge", MmcSequenceObservation(deblock=True, ready=False))
    assert early.accepted is False
    assert early.phase == MmcSequencePhaseName.FAILED.value
    assert early.failure_code == "MMC_CONTROL_INFEASIBLE"

    invalid_reverse = reduce_sequence("forward_steady", MmcSequenceObservation(reverse_steady=True))
    assert invalid_reverse.accepted is False
    assert invalid_reverse.phase == MmcSequencePhaseName.FAILED.value


def test_sequence_reducer_stops_on_protection_and_tracks_observed_conditions():
    result = reduce_sequence("forward_ramp", MmcSequenceObservation(protection_active=True))
    assert result.phase == MmcSequencePhaseName.FAILED.value
    assert result.observed["protection_active"] is True
    assert result.failure_code == "MMC_CONTROL_INFEASIBLE"


def test_sequence_reducer_requires_reversal_before_reverse_steady():
    forward = reduce_sequence("forward_ramp", {"ramp_complete": True})
    assert forward.phase == "forward_steady"
    reversal = reduce_sequence("forward_steady", {"power_reversal": True})
    assert reversal.phase == "power_reversal"
    reverse = reduce_sequence("power_reversal", {"reverse_settled": True})
    assert reverse.phase == "reverse_steady"
