"""Literal, instance-backed sizing of the installed switched full-bridge arms."""

from __future__ import annotations

import math
import re
from xml.etree import ElementTree as ET

from .pwm_commands import _params


def audit_pwm_physical_reference(root: ET.Element) -> dict:
    calls = [u for u in root.findall(".//User") if u.get("defn", "").endswith(":Main")]
    if len(calls) != 1 or "NoCells1" not in _params(calls[0]):
        return {
            "available": False,
            "reason": "The instantiated PWM dimension is unavailable",
        }
    try:
        count = int(_params(calls[0])["NoCells1"])
        frequency = float(_params(calls[0])["Freq"])
    except (ValueError, KeyError):
        return {
            "available": False,
            "reason": "The instantiated dimension or frequency is not literal",
        }
    arms = [
        u
        for u in root.findall("./definitions/Definition[@name='Main']/schematic/User")
        if u.get("defn", "").endswith(":MMC_Hb_PWM")
    ]
    if len(arms) != 2 or count <= 0 or frequency <= 0:
        return {
            "available": False,
            "reason": "Both physical PWM stations must be uniquely instantiated",
        }

    def scalar(value, unit=None):
        match = re.fullmatch(
            r"\s*([+-]?[0-9.]+(?:[Ee][+-]?[0-9]+)?)\s*(?:\[([^]]+)\])?\s*", value
        )
        if match is None or (match.group(2) is not None and match.group(2) != unit):
            raise ValueError("A physical rating must have literal compatible units")
        number = float(match.group(1))
        if not math.isfinite(number) or number <= 0:
            raise ValueError("A physical rating must be positive and finite")
        return number

    ratings = []
    for arm in arms:
        p = _params(arm)
        ratings.append(
            {
                "owner": arm.get("id"),
                "cell_capacitance_f": scalar(p["Cdc"], "uF") * 1e-6,
                "arm_inductance_h": scalar(p["Lsmth"], "mH") * 1e-3,
                "switch_on_resistance_ohm": scalar(p["RSOn"], "ohm"),
                "rated_dc_voltage_kv": scalar(p["VdcBase"], "kV"),
                "transformer_rating_mva": scalar(p["Sbase"], "MVA"),
                "carrier_ratio": scalar(p["Cfreq"]),
            }
        )
    shared = (
        "cell_capacitance_f",
        "arm_inductance_h",
        "switch_on_resistance_ohm",
        "rated_dc_voltage_kv",
        "transformer_rating_mva",
    )
    if any(ratings[0][key] != ratings[1][key] for key in shared):
        return {
            "available": False,
            "reason": "The station arm ratings disagree",
            "stations": ratings,
        }
    arm = ratings[0]
    capacitance = arm["cell_capacitance_f"] / count
    voltage = arm["rated_dc_voltage_kv"] * 1000
    return {
        "available": True,
        "reference_cells_per_arm": count,
        "dimension_owner": calls[0].get("id"),
        "dimension_parameter": "NoCells1",
        "form_default_used": False,
        "stations": ratings,
        "arm_inductance_h": arm["arm_inductance_h"],
        "arm_resistance_ohm": 2 * count * arm["switch_on_resistance_ohm"],
        "stored_energy_mj": 12 * 0.5 * capacitance * voltage**2 / 1e6,
        "equivalent_arm_capacitance_f": capacitance,
        "transformer_rating_mva": arm["transformer_rating_mva"],
        "equivalent_capacitor_voltage_target_kv": arm["rated_dc_voltage_kv"],
        "switching_frequency_hz": max(s["carrier_ratio"] * frequency for s in ratings),
        "source_time_step_s": float(
            root.find("./paramlist/param[@name='time_step']").get("value")
        )
        * 1e-6,
        "source_output_step_s": float(
            root.find("./paramlist/param[@name='sample_step']").get("value")
        )
        * 1e-6,
        "control_sample_time_s": 50e-6,
        "control_bandwidth_hz": 100.0,
        "time_step_s": 1e-5,
        "output_step_s": 5e-5,
        "energy_equation": "12 * 0.5 * (Ccell / Ncells) * Vdc^2",
        "on_state_resistance_equation": "2 * Ncells * Ron; conducting state only",
    }
