"""Physical checks on complete, identity-bound detailed PWM output traces."""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
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
    rated_ac_voltage_kv: float = 230.0,
    grid_short_circuit_ratio: float = 5.0,
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

    observed_ids = [c.get("channel_id") for c in samples.get("channels", [])]
    check(
        "complete_declared_channels",
        len(observed_ids) == len(set(observed_ids))
        and set(observed_ids) == set(bindings),
        {"observed": len(observed_ids), "expected": len(bindings)},
        "every declared channel exactly once",
    )
    common_domain = None
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
        if common_domain is None:
            common_domain = times
        valid = valid and times == common_domain
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
        "q_reactive": 2,
        "ac_breaker_state": 2,
        "dc_breaker_state": 4,
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

    def window(times, values, left, right):
        return values[bisect_left(times, left) : bisect_right(times, right)]

    def mean_window(times, values, left, right):
        selected = window(times, values, left, right)
        return fmean(selected) if selected else math.nan

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
    q_orders = [
        e["value"] for e in scenario["events"] if e["target"] == "reactive_power_order"
    ]
    expected_q = rated_power_mw * (q_orders[-1] if q_orders else 0.0)
    for binding, times, values in grouped["q_reactive"]:
        measured = fmean(tail(times, values))
        check(
            "reactive_power_" + binding["model_scope"],
            abs(measured - expected_q) / rated_power_mw <= 0.05,
            {"measured_mvar": measured, "expected_mvar": expected_q},
            "<=0.05 pu on rated MVA",
        )
    if name in {
        "active_power_step",
        "reactive_power_step",
        "power_reversal",
        "reverse_steady",
    }:
        for event in scenario["events"]:
            if (
                event["target"] not in {"active_power_order", "reactive_power_order"}
                or event["before_value"] == event["after_value"]
            ):
                continue
            role = (
                "p_active" if event["target"] == "active_power_order" else "q_reactive"
            )
            left = (
                min(event["end_time_s"], event["time_s"] + limits["recovery_time_s"])
                - 1.0 / 60.0
            )
            right = min(
                event["end_time_s"], event["time_s"] + limits["recovery_time_s"]
            )
            target = rated_power_mw * event["value"] * (-1 if role == "p_active" else 1)
            for binding, times, values in grouped[role]:
                if binding["model_scope"] != "T2" and role == "p_active":
                    continue
                measured = mean_window(times, values, left, right)
                check(
                    "step_response_" + event["event_id"] + "_" + binding["model_scope"],
                    abs(measured - target) / rated_power_mw <= 0.05,
                    {
                        "window_s": [left, right],
                        "measured": measured,
                        "expected": target,
                    },
                    "<=0.05 pu within 0.5 s",
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
    fault_events = [
        e
        for e in scenario["events"]
        if e["target"] in {"ac_fault_command", "dc_fault_command"} and e["value"] == 1
    ]
    for event in fault_events:
        onset, cleared = event["time_s"], event["end_time_s"]
        tolerance = scenario["time_step_s"] + scenario["output_step_s"]
        ac = event["target"] == "ac_fault_command"
        pg = name == "dc_pole_to_ground_fault"
        state_role = (
            "ac_fault_branch_state"
            if ac
            else "pg_fault_state"
            if pg
            else "fault_active"
        )
        current_role = (
            "ac_fault_current" if ac else "pg_fault_current" if pg else "i_dc_fault"
        )
        state_traces = grouped[state_role]
        expected_count = 7 if ac else 1
        check(
            "complete_fault_branch_states",
            len(state_traces) == expected_count,
            len(state_traces),
            expected_count,
        )
        for binding, times, values in state_traces:
            scope = binding["model_scope"]
            if ac and scope != "any":
                # The installed type selector requests grounded ABC or grounded A.
                active = scope in (
                    {"AG", "BG", "CG"} if name == "ac_three_phase_fault" else {"AG"}
                )
            else:
                active = True
            rises = [t for t, v in zip(times, values) if v >= 0.5]
            interior = window(times, values, onset + tolerance, cleared - tolerance)
            timing_ok = (
                bool(
                    rises
                    and interior
                    and abs(rises[0] - onset) <= tolerance
                    and all(v == 1 for v in interior)
                    and all(
                        v == 0
                        for t, v in zip(times, values)
                        if t < onset - tolerance or t >= cleared + tolerance
                    )
                )
                if active
                else all(v == 0 for v in values)
            )
            check(
                "physical_fault_state_" + scope,
                timing_ok,
                {
                    "first_closed_s": rises[0] if rises else None,
                    "expected_active": active,
                },
                {"onset_s": onset, "cleared_s": cleared, "tolerance_s": tolerance},
            )
        current_traces = grouped[current_role]
        # The 20 kA contract governs the DC fault switch. AC source crests
        # depend on requested short-circuit MVA and the worst DC offset.
        current_limit_ka = (
            2
            * math.sqrt(2)
            * grid_short_circuit_ratio
            * rated_power_mw
            / (math.sqrt(3) * rated_ac_voltage_kv)
            if ac
            else 20.0
        )
        check(
            "complete_fault_branch_currents",
            len(current_traces) == (3 if ac else 1),
            len(current_traces),
            3 if ac else 1,
        )
        for binding, times, values in current_traces:
            peak = max(abs(v) for v in window(times, values, onset, cleared))
            conducting = (
                not ac
                or name == "ac_three_phase_fault"
                or binding["model_scope"] == "A"
            )
            check(
                "physical_fault_current_" + binding["model_scope"],
                (peak > 0.01 if conducting else peak < 0.01)
                and peak <= current_limit_ka,
                peak,
                {
                    "maximum_ka": current_limit_ka,
                    "basis": "2*sqrt(2)*SCR*Prated/(sqrt(3)*Vac)"
                    if ac
                    else "original DC fault-switch contract",
                    "minimum_active_ka": 0.01,
                    "conducting": conducting,
                },
            )
        for binding, times, values in grouped["blocking_state"]:
            blocked = window(times, values, onset, cleared)
            check(
                "blocked_during_fault_" + binding["model_scope"],
                any(v == 1 for v in blocked),
                max(blocked),
                1,
            )
        for binding, times, values in grouped["i_arm"]:
            peak = max(
                abs(v)
                for v in window(
                    times, values, onset, cleared + limits["recovery_time_s"]
                )
            )
            check("fault_arm_peak_" + binding["model_scope"], peak <= 3.0, peak, 3.0)
        for binding, times, values in grouped["i_dc_station"]:
            peak = max(
                abs(v)
                for v in window(
                    times, values, onset, cleared + limits["recovery_time_s"]
                )
            ) / (rated_power_mw / rated_dc_voltage_kv)
            check(
                "fault_dc_peak_" + binding["model_scope"],
                peak <= limits["dc_current_peak_pu"],
                peak,
                limits["dc_current_peak_pu"],
            )
        if not ac:
            check(
                "complete_negative_insertion",
                len(grouped["v_inserted"]) == 12,
                len(grouped["v_inserted"]),
                12,
            )
            for binding, times, values in grouped["v_inserted"]:
                negative = min(window(times, values, onset, cleared))
                check(
                    "negative_voltage_during_fault_" + binding["model_scope"],
                    negative <= -1.0,
                    negative,
                    "<=-1 kV",
                )
        for role in ("ac_breaker_state" if ac else "dc_breaker_state",):
            command = "ac_breaker_command" if ac else "dc_breaker_command"
            for switch_event in [
                e for e in scenario["events"] if e["target"] == command
            ]:
                for binding, times, values in grouped[role]:
                    plateau = window(
                        times,
                        values,
                        switch_event["time_s"] + tolerance,
                        switch_event["end_time_s"] - tolerance,
                    )
                    check(
                        "physical_isolation_"
                        + switch_event["event_id"]
                        + "_"
                        + binding["model_scope"],
                        bool(plateau)
                        and all(v == switch_event["value"] for v in plateau),
                        {
                            "minimum": min(plateau) if plateau else None,
                            "maximum": max(plateau) if plateau else None,
                        },
                        switch_event["value"],
                    )
        deadline = cleared + limits["recovery_time_s"]
        for binding, times, values in grouped["v_cap"]:
            measured = mean_window(times, values, deadline - 1 / 60, deadline)
            error = abs(measured / rated_dc_voltage_kv - 1)
            check(
                "fault_capacitor_recovery_" + binding["model_scope"],
                error <= 0.05,
                {"error_pu": error, "deadline_s": deadline},
                "<=0.05 pu by 0.5 s after fault clearance",
            )
        for binding, times, values in grouped["modulation_request"]:
            margin = 2.0 - max(abs(v) for v in window(times, values, deadline, end))
            check(
                "fault_modulation_recovery_" + binding["model_scope"],
                margin >= limits["modulation_margin_min_pu"],
                margin,
                {
                    "deadline_s": deadline,
                    "minimum_margin_pu": limits["modulation_margin_min_pu"],
                },
            )
        for binding, times, values in grouped["v_dc"]:
            error = max(
                abs(v / rated_dc_voltage_kv - 1)
                for v in window(times, values, deadline, end)
            )
            check(
                "fault_voltage_recovery_" + binding["model_scope"],
                error <= limits["dc_voltage_deviation_pu"],
                error,
                {
                    "deadline_s": deadline,
                    "maximum_error_pu": limits["dc_voltage_deviation_pu"],
                },
            )
        for binding, times, values in grouped["p_active"]:
            if binding["model_scope"] == "T2":
                measured = mean_window(times, values, deadline - 1 / 60, deadline)
                check(
                    "fault_power_recovery",
                    abs(measured - expected) / rated_power_mw <= 0.05,
                    {
                        "measured_mw": measured,
                        "expected_mw": expected,
                        "deadline_s": deadline,
                    },
                    "<=0.05 pu by 0.5 s after fault clearance",
                )
        for binding, times, values in grouped["blocking_state"]:
            check(
                "fault_deblocking_recovery_" + binding["model_scope"],
                all(v == 0 for v in window(times, values, deadline, end)),
                max(window(times, values, deadline, end)),
                {"blocked": 0, "deadline_s": deadline},
            )
    return {
        "status": "PASS" if all(c["passed"] for c in checks) else "FAIL",
        "checks": checks,
        "model_accepted": False,
        "scope": "routed_pwm_scenario_physical_checks",
        "scenario": name,
        "steady_window_s": [start, end],
    }
