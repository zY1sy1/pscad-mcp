"""Periodic arm-energy sizing from the native valve circuit and SVM waveform.

This is a planning calculation, not simulated acceptance. It solves both power
directions, includes grid voltage drop and transformer/arm impedance, and
integrates each arm's instantaneous power over an AC cycle. A 5% mean-energy
reserve is kept inside the existing +/-10% capacitor-voltage envelope.
"""

from __future__ import annotations

import cmath
import math
from statistics import fmean


def periodic_native_envelope(parameters: dict, *, points: int = 1440) -> dict:
    if points < 360 or points % 6:
        raise ValueError("Native periodic sizing needs at least 360 points divisible by six")
    p = parameters
    voltage = float(p["rated_dc_voltage_kv"])
    rating = float(p["rated_power_mw"])
    frequency = float(p["frequency_hz"])
    energy = float(p["stored_energy_mj"])
    modulation = float(p["base_modulation_index"])
    resistance = float(p["arm_resistance_ohm"])
    inductance = float(p["arm_inductance_h"])
    cable_r = float(p["line_resistance_ohm"])
    reactive = float(p["reactive_power_mvar"])
    valve_rating = modulation * voltage * math.sqrt(3 / 8)
    omega = 2 * math.pi * frequency
    arm_base = energy / 12
    loss_station = 6 * float(p["loss_per_arm_mw"])
    result = {"method": "native_valve_svm_periodic_power_v1", "model_accepted": False,
              "mean_energy_reserve_pu": 0.05, "capacitor_voltage_limit_pu": 0.10,
              "required_stored_energy_mj": 0.0, "minimum_insertion_margin": 1.0,
              "maximum_converter_modulation": 0.0, "operating_points": []}
    for direction in (1.0, -1.0):
        transferred = direction * rating - loss_station
        discriminant = voltage**2 + 4 * cable_r * transferred
        if discriminant <= 0:
            raise ValueError("The native cable has no high-voltage DC operating solution")
        dc_current = 2 * transferred / (voltage + math.sqrt(discriminant))
        for station, active, dc_bus, circulating in (
            ("p", direction * rating, voltage + cable_r * dc_current, -dc_current / 3),
            ("vdc", -voltage * dc_current + loss_station, voltage, dc_current / 3),
        ):
            grid_voltage = float(p[f"station_{station}_ac_voltage_kv"])
            grid_r = float(p[f"station_{station}_grid_r_ohm"])
            grid_x = float(p[f"station_{station}_grid_x_ohm"])
            b = grid_voltage**2 - 2 * (grid_r * active + grid_x * reactive)
            disc = b*b - 4 * (grid_r**2 + grid_x**2) * (active**2 + reactive**2)
            if b <= 0 or disc <= 0:
                raise ValueError("The native AC grid has no high-voltage load-flow solution")
            primary = math.sqrt((b + math.sqrt(disc)) / 2)
            ratio = valve_rating / grid_voltage
            ac_current = complex(active, -reactive) / (math.sqrt(3) * primary * ratio)
            transformer_x = 0.15 * valve_rating**2 / float(p["transformer_rating_mva"])
            valve = primary * ratio / math.sqrt(3) - 1j * transformer_x * ac_current
            arm_current = ac_current
            if "neutral_inductance_h" in p:
                arm_current -= valve / (1j * omega * float(p["neutral_inductance_h"]))
            converter = valve - complex(resistance / 2, omega * inductance / 2) * arm_current
            converter_modulation = 2 * math.sqrt(2) * abs(converter) / voltage
            result["maximum_converter_modulation"] = max(result["maximum_converter_modulation"], converter_modulation)
            arm_voltages = [[] for _ in range(6)]
            arm_powers = [[] for _ in range(6)]
            for index in range(points + 1):
                rotations = [cmath.exp(1j * (2 * math.pi * index / points - phase * 2 * math.pi / 3)) for phase in range(3)]
                waves = [math.sqrt(2) * (converter * z).real for z in rotations]
                common_mode = -(max(waves) + min(waves)) / 2
                for phase, rotation in enumerate(rotations):
                    alternating = math.sqrt(2) * (arm_current * rotation).real
                    for position, sign in enumerate((-1.0, 1.0)):
                        arm = phase * 2 + position
                        inserted = dc_bus / 2 - resistance * circulating + sign * (waves[phase] + common_mode)
                        current = circulating + sign * alternating / 2
                        arm_voltages[arm].append(inserted)
                        arm_powers[arm].append(inserted * current)
            swings = []
            minimum_margin = 1.0
            required_energy = 0.0
            for voltages, powers in zip(arm_voltages, arm_powers):
                mean_power = fmean(powers[:-1])
                integrated = [0.0]
                for a, b in zip(powers, powers[1:]):
                    integrated.append(integrated[-1] + ((a + b) / 2 - mean_power) / (frequency * points))
                centre = fmean(integrated[:-1])
                ripple = [value - centre for value in integrated]
                rise, fall = max(ripple), -min(ripple)
                required_energy = max(required_energy, 12 * rise / (1.1**2 - 1 - 0.05),
                                      12 * fall / (1 - 0.9**2 - 0.05))
                swings.append({"rise_mj": rise, "fall_mj": fall})
                for inserted, change in zip(voltages, ripple):
                    for reserve in (-0.05, 0.05):
                        relative_energy = 1 + reserve + change / arm_base
                        if relative_energy <= 0:
                            minimum_margin = -1.0
                            continue
                        insertion = inserted / (voltage * math.sqrt(relative_energy))
                        minimum_margin = min(minimum_margin, insertion, 1 - insertion)
            result["required_stored_energy_mj"] = max(result["required_stored_energy_mj"], required_energy)
            result["minimum_insertion_margin"] = min(result["minimum_insertion_margin"], minimum_margin)
            result["operating_points"].append({"direction": int(direction), "station": station,
                "primary_voltage_kv": primary, "valve_voltage_kv": abs(valve) * math.sqrt(3),
                "valve_current_peak_ka": math.sqrt(2) * abs(ac_current), "dc_bus_voltage_kv": dc_bus,
                "converter_modulation": converter_modulation, "minimum_insertion_margin": minimum_margin,
                "required_stored_energy_mj": required_energy, "arm_energy_swings": swings})
    result["energy_feasible"] = energy >= result["required_stored_energy_mj"]
    result["modulation_feasible"] = result["minimum_insertion_margin"] >= 0.05 and result["maximum_converter_modulation"] <= 0.98
    return result
