import math

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.electrical import (
    SaturationDuration,
    accumulate_saturation_duration,
    arm_currents,
    arm_energy,
    arm_energy_step,
    arm_losses,
    clip_modulation,
    conduction_loss,
    equivalent_capacitor_voltage,
    equivalent_switching_loss,
)


def test_declared_arm_equations_and_modulation_clipping():
    # The design equation gives 3 - 1.5 + 0.2 = 1.7 for the lower arm.
    assert arm_currents(9.0, 3.0, 0.2) == (4.7, 1.7)
    assert equivalent_capacitor_voltage(2_000_000.0, 10_000.0) == pytest.approx(20.0)
    assert arm_energy(10_000.0, 20.0) == pytest.approx(2_000_000.0)
    assert clip_modulation(1.2) == (1.2, 1.0, 0.0, True)


@pytest.mark.parametrize("values", [(math.nan, 1.0, 1.0), (1.0, math.inf, 1.0), (1.0, 1.0, math.nan)])
def test_arm_currents_reject_non_finite_inputs(values):
    with pytest.raises(BackendError) as raised:
        arm_currents(*values)
    assert raised.value.code == "MMC_MODEL_UNSUPPORTED"


@pytest.mark.parametrize("energy, capacitance", [(-1.0, 10.0), (math.nan, 10.0), (1.0, 0.0), (1.0, math.inf)])
def test_energy_conversion_rejects_invalid_states(energy, capacitance):
    with pytest.raises(BackendError) as raised:
        equivalent_capacitor_voltage(energy, capacitance)
    assert raised.value.code == "MMC_ENERGY_INFEASIBLE"


def test_losses_are_explicit_and_energy_step_rejects_loss_above_inserted_power():
    assert conduction_loss(10.0, 2.0) == pytest.approx(200.0)
    assert equivalent_switching_loss(-10.0, 3.0) == pytest.approx(30.0)
    losses = arm_losses(10.0, 2.0, 3.0)
    assert losses.conduction_w == pytest.approx(200.0)
    assert losses.switching_w == pytest.approx(30.0)
    assert losses.total_w == pytest.approx(230.0)

    with pytest.raises(BackendError) as raised:
        arm_energy_step(100.0, 5.0, 10.0, 60.0, 0.1)
    assert raised.value.code == "MMC_ENERGY_INFEASIBLE"


def test_saturation_duration_accumulates_only_monotonic_saturated_intervals():
    state = SaturationDuration()
    state = accumulate_saturation_duration(state, 1.0, False)
    state = accumulate_saturation_duration(state, 1.2, True)
    state = accumulate_saturation_duration(state, 1.5, True)
    state = accumulate_saturation_duration(state, 1.8, False)
    assert state.duration_s == pytest.approx(0.5)
    assert state.last_time_s == pytest.approx(1.8)

    with pytest.raises(BackendError) as raised:
        accumulate_saturation_duration(state, 1.7, True)
    assert raised.value.code == "MMC_MODULATION_INFEASIBLE"
