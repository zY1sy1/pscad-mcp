"""Terminal energy accounting for measured native averaged arms.

This is a diagnostic, not the complete-converter acceptance contract. The
unaccounted power includes native switch losses and sampling error. A large
negative value indicates that the arm delivers energy not supplied at its
terminals or released from its capacitor/inductor state.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def diagnose_native_arm_energy(
    trace: Mapping[str, Sequence[float]],
    parameters: Mapping[str, float],
    windows: Sequence[tuple[float, float]] = ((0.4, 0.9), (1.5, 1.9)),
) -> list[dict]:
    times = trace["time"]
    resistance = parameters["R_arm_ohm"]
    inductance = parameters["L_arm_H"]
    loss = parameters["P_nonohmic_MW"]
    floor = parameters["V_loss_floor_kV"]
    if len(times) < 2 or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Energy accounting requires increasing native timestamps")
    results = []
    for start, end in windows:
        indexes = [i for i, time in enumerate(times) if start <= time <= end]
        if len(indexes) < 2:
            raise ValueError("Energy accounting window has fewer than two samples")
        first, last = indexes[0], indexes[-1]
        duration = times[last] - times[first]
        for station in ("P", "V"):
            arms = []
            for phase in "ABC":
                for position in ("UPPER", "LOWER"):
                    prefix = f"{station}_{phase}_{position}"
                    required = [prefix + suffix for suffix in ("_I", "_W", "_VT", "_VCAP")]
                    measured_loss = trace.get(prefix + "_PLOSS")
                    if measured_loss is not None:
                        required.append(prefix + "_PLOSS")
                    if any(
                        name not in trace
                        or len(trace[name]) != len(times)
                        or any(not math.isfinite(value) for value in trace[name])
                        for name in required
                    ):
                        raise ValueError("Energy accounting is missing finite arm measurements")
                    current, voltage, energy, capacitor = (
                        trace[prefix + suffix] for suffix in ("_I", "_VT", "_W", "_VCAP")
                    )
                    terminal = [voltage[i] * current[i] for i in indexes]
                    passive_loss = [
                        resistance * current[i] ** 2
                        + (measured_loss[i] if measured_loss is not None else loss * max(0.0, min(1.0, 2 * capacitor[i] / floor)))
                        for i in indexes
                    ]

                    def integrate(values):
                        return sum(
                            (values[k] + values[k + 1]) * 0.5
                            * (times[right] - times[left])
                            for k, (left, right) in enumerate(zip(indexes, indexes[1:]))
                        )

                    change = energy[last] - energy[first] + 0.5 * inductance * (
                        current[last] ** 2 - current[first] ** 2
                    )
                    supplied = integrate(terminal)
                    dissipated = integrate(passive_loss)
                    arms.append({
                        "arm": prefix,
                        "terminal_energy_mj": supplied,
                        "capacitor_and_inductor_change_mj": change,
                        "resistor_and_nonohmic_loss_mj": dissipated,
                        "unaccounted_mean_power_mw": (supplied - change - dissipated) / duration,
                    })
            results.append({
                "station": station,
                "window_s": [times[first], times[last]],
                "arms": arms,
                "terminal_mean_power_mw": sum(a["terminal_energy_mj"] for a in arms) / duration,
                "storage_mean_power_mw": sum(a["capacitor_and_inductor_change_mj"] for a in arms) / duration,
                "loss_mean_power_mw": sum(a["resistor_and_nonohmic_loss_mj"] for a in arms) / duration,
                "unaccounted_mean_power_mw": sum(a["unaccounted_mean_power_mw"] for a in arms),
            })
    return results
