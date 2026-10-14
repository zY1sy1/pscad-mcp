"""Physical checks on complete, identity-bound detailed PWM output traces."""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import pairwise
from statistics import fmean
from typing import Any


def evaluate_routed_pwm_samples(
    samples: dict[str, Any],
    contract: dict[str, Any],
    scenario: dict[str, Any],
    *,
    rated_power_mw: float = 1000.0,
    rated_dc_voltage_kv: float = 640.0,
) -> dict[str, Any]:
    """Keep the original voltage/current/margin/recovery requirements explicit.

    Cold-start transients are checked separately from the final steady window.
    A command waveform does not prove a physical switch or electrical recovery.
    """
    bindings = {
        b["channel_id"]: b
        for b in contract["channels"] + contract.get("diagnostic_channels", [])
    }
    grouped = defaultdict(list)
    checks = []

    def check(name, passed, observed, limit):
        checks.append(
            {"name": name, "passed": bool(passed), "observed": observed, "limit": limit}
        )

    for channel in samples.get("channels", []):
        binding = bindings.get(channel.get("channel_id"))
        if binding is None:
            continue
        times = channel.get("domain", [])
        values = channel.get("values", [])
        valid = (
            bool(times)
            and len(times) == len(values)
            and all(math.isfinite(x) for x in times + values)
        )
        valid = (
            valid
            and channel.get("units") == binding["units"]
            and times[0] <= scenario["output_step_s"]
            and times[-1] >= scenario["duration_s"] - scenario["output_step_s"]
        )
        valid = valid and all(
            0 < b - a <= scenario["output_step_s"] * 1.001 + 1e-12
            for a, b in pairwise(times)
        )
        check(
            "trace_" + binding["channel_id"],
            valid,
            {"samples": len(values), "units": channel.get("units")},
            "finite, aligned, full EMTDC domain, exact declared units",
        )
        if valid:
            grouped[binding["role"]].append((binding, times, values))
    required = {
        "v_dc": 2,
        "p_active": 2,
        "v_cap": 12,
        "i_arm": 12,
        "blocking_state": 12,
        "modulation_request": 12,
        "i_dc_station": 2,
    }
    for role, count in required.items():
        check(
            "complete_" + role, len(grouped[role]) == count, len(grouped[role]), count
        )
    if any(not c["passed"] for c in checks):
        return {
            "status": "INCOMPLETE_ANALYSIS",
            "checks": checks,
            "model_accepted": False,
        }
    end = scenario["duration_s"]
    start = end - 0.2
    limits = scenario["analysis"]["thresholds"]
    name = scenario["name"]

    def tail(times, values):
        return [v for t, v in zip(times, values) if start <= t <= end]

    orders = [
        e["value"] for e in scenario["events"] if e["target"] == "active_power_order"
    ]
    order = orders[-1] if orders else 1.0
    expected = -rated_power_mw * order
    powers = {b["model_scope"]: fmean(tail(t, v)) for b, t, v in grouped["p_active"]}
    error = abs(powers["T2"] - expected) / rated_power_mw
    check(
        "rated_active_power",
        error <= 0.05,
        {"measured_mw": powers["T2"], "expected_mw": expected, "error_pu": error},
        0.05,
    )
    loss = powers["T1"] + powers["T2"]
    check(
        "active_power_balance",
        0 <= loss <= 0.1 * abs(expected),
        loss,
        {"minimum_mw": 0, "maximum_mw": 0.1 * abs(expected)},
    )
    for binding, times, values in grouped["v_dc"]:
        deviation = max(abs(v / rated_dc_voltage_kv - 1) for v in tail(times, values))
        check(
            "dc_voltage_" + binding["model_scope"],
            deviation <= limits["dc_voltage_deviation_pu"],
            deviation,
            limits["dc_voltage_deviation_pu"],
        )
    for binding, times, values in grouped["i_dc_station"]:
        peak = max(abs(v) for v in tail(times, values)) / (
            rated_power_mw / rated_dc_voltage_kv
        )
        check(
            "dc_current_" + binding["model_scope"],
            peak <= limits["dc_current_peak_pu"],
            peak,
            limits["dc_current_peak_pu"],
        )
    for binding, times, values in grouped["i_arm"]:
        peak = max(abs(v) for v in tail(times, values))
        check("arm_current_" + binding["model_scope"], peak <= 3.0, peak, 3.0)
    for binding, times, values in grouped["v_cap"]:
        mean = fmean(tail(times, values))
        error = abs(mean / rated_dc_voltage_kv - 1)
        check("capacitor_voltage_" + binding["model_scope"], error <= 0.05, error, 0.05)
    for binding, times, values in grouped["modulation_request"]:
        # The audited FullCell/FiringHBridge input and carrier span [-2,2].
        margin = 2.0 - max(abs(v) for v in tail(times, values))
        check(
            "modulation_margin_" + binding["model_scope"],
            margin >= limits["modulation_margin_min_pu"],
            margin,
            limits["modulation_margin_min_pu"],
        )
    for binding, times, values in grouped["blocking_state"]:
        check(
            "deblocked_" + binding["model_scope"],
            all(v == 0 for v in tail(times, values)),
            max(tail(times, values)),
            0,
        )
    if name.startswith(("ac_", "dc_")) or name == "post_fault_recovery":
        check(
            "fault_physical_evidence",
            False,
            "fault-specific branch and recovery checks are still required",
            "verified physical branch closure and <=0.5 s electrical recovery",
        )
    return {
        "status": "PASS" if all(c["passed"] for c in checks) else "FAIL",
        "checks": checks,
        "model_accepted": False,
        "scope": "routed_pwm_normal_physical_checks",
        "scenario": name,
        "steady_window_s": [start, end],
    }
