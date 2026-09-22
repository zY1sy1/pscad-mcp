import math

import pytest

from pscad_mcp.hvdc.builders.mmc.native_energy import diagnose_native_arm_energy


def _lossless_lc():
    times = [i / 10000 for i in range(20001)]
    trace = {"time": times}
    inductance, capacitance = 0.05, 0.001
    omega = 1 / math.sqrt(inductance * capacitance)
    for station in ("P", "V"):
        for phase in "ABC":
            for position in ("UPPER", "LOWER"):
                prefix = f"{station}_{phase}_{position}"
                trace[prefix + "_I"] = [math.sin(omega * t) for t in times]
                trace[prefix + "_W"] = [0.5 * inductance * math.cos(omega * t) ** 2 for t in times]
                trace[prefix + "_VT"] = [0.0] * len(times)
                trace[prefix + "_VCAP"] = [0.5 * math.sqrt(inductance / capacitance) * math.cos(omega * t) for t in times]
    return trace, dict(R_arm_ohm=0.0, L_arm_H=inductance, P_nonohmic_MW=0.0, V_loss_floor_kV=0.01)


def test_lossless_lc_exchange_does_not_create_terminal_energy():
    trace, parameters = _lossless_lc()
    for result in diagnose_native_arm_energy(trace, parameters):
        assert result["unaccounted_mean_power_mw"] == pytest.approx(0.0, abs=1e-12)


def test_energy_creation_is_visible_even_with_finite_bounded_channels():
    trace, parameters = _lossless_lc()
    for name in list(trace):
        if name.endswith("_VT"):
            trace[name] = [-10 * i for i in trace[name[:-3] + "_I"]]
    for result in diagnose_native_arm_energy(trace, parameters):
        assert result["unaccounted_mean_power_mw"] < -25


def test_missing_arm_cannot_be_silently_dropped():
    trace, parameters = _lossless_lc()
    del trace["V_C_LOWER_W"]
    with pytest.raises(ValueError, match="missing"):
        diagnose_native_arm_energy(trace, parameters)
