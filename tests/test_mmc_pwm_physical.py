"""Missing or flat physical data cannot establish PWM acceptance."""

from pscad_mcp.hvdc.builders.mmc.pwm_physical import evaluate_routed_pwm_samples


def test_missing_arm_data_remains_incomplete():
    result = evaluate_routed_pwm_samples(
        {"channels": []},
        {"channels": []},
        {
            "duration_s": 1.0,
            "output_step_s": 0.01,
            "analysis": {"thresholds": {}},
            "name": "forward_steady",
            "events": [],
        },
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert result["model_accepted"] is False
    assert any(
        c["name"] == "complete_i_arm" and not c["passed"] for c in result["checks"]
    )


def test_incorrect_units_are_rejected_before_any_electrical_verdict():
    binding = {"channel_id": "dc", "role": "v_dc", "units": "kV"}
    trace = {
        "channel_id": "dc",
        "units": "V",
        "domain": [0, 0.01, 0.02],
        "values": [640, 640, 640],
    }
    result = evaluate_routed_pwm_samples(
        {"channels": [trace]},
        {"channels": [binding]},
        {
            "duration_s": 0.02,
            "output_step_s": 0.01,
            "analysis": {"thresholds": {}},
            "name": "forward_steady",
            "events": [],
        },
    )
    assert result["status"] == "INCOMPLETE_ANALYSIS"
    assert (
        next(c for c in result["checks"] if c["name"] == "trace_dc")["passed"] is False
    )


def complete_samples():
    times = [i / 100 for i in range(121)]
    bindings, channels = [], []

    def add(role, scope, value, units):
        channel_id = role + "_" + scope
        bindings.append(
            {
                "channel_id": channel_id,
                "role": role,
                "model_scope": scope,
                "units": units,
            }
        )
        channels.append(
            {
                "channel_id": channel_id,
                "units": units,
                "domain": times,
                "values": [value] * len(times),
            }
        )

    for station in ("T1", "T2"):
        for role, value, units in (
            ("v_dc", 640, "kV"),
            ("p_active", 1030 if station == "T1" else -1000, "MW"),
            ("i_dc_station", 1.6, "kA"),
            ("q_reactive", 0, "MVAr"),
            ("ac_breaker_state", 1, "1"),
        ):
            add(role, station, value, units)
        for pole in ("P", "N"):
            add("dc_breaker_state", station + pole, 1, "1")
        for phase in "ABC":
            for arm in ("upper", "lower"):
                for role, value, units in (
                    ("v_cap", 640, "kV"),
                    ("i_arm", 1.6, "kA"),
                    ("blocking_state", 0, "1"),
                    ("modulation_request", 1.5, "pu"),
                ):
                    add(role, station + "/" + phase + "/" + arm, value, units)
    scenario = {
        "name": "forward_steady",
        "duration_s": 1.2,
        "time_step_s": 0.001,
        "output_step_s": 0.01,
        "events": [],
        "analysis": {
            "thresholds": {
                "dc_voltage_deviation_pu": 0.1,
                "dc_current_peak_pu": 1.25,
                "modulation_margin_min_pu": 0.02,
                "recovery_time_s": 0.5,
            }
        },
    }
    return {"channels": channels}, {"channels": bindings}, scenario


def test_flat_power_trace_cannot_pass_a_requested_step():
    samples, contract, scenario = complete_samples()
    scenario.update(
        name="active_power_step",
        events=[
            {
                "event_id": "lower",
                "target": "active_power_order",
                "time_s": 0.1,
                "end_time_s": 0.5,
                "value": 0.8,
                "before_value": 1,
                "after_value": 0.8,
            },
            {
                "event_id": "raise",
                "target": "active_power_order",
                "time_s": 0.5,
                "end_time_s": 1.2,
                "value": 1,
                "before_value": 0.8,
                "after_value": 1,
            },
        ],
    )
    result = evaluate_routed_pwm_samples(samples, contract, scenario)
    assert result["status"] == "FAIL"
    assert (
        next(c for c in result["checks"] if c["name"] == "step_response_lower_T2")[
            "passed"
        ]
        is False
    )


def test_good_final_power_cannot_replace_real_fault_and_recovery_evidence():
    samples, contract, scenario = complete_samples()
    scenario.update(
        name="dc_pole_to_pole_fault",
        events=[
            {
                "event_id": "fault",
                "target": "dc_fault_command",
                "time_s": 0.3,
                "end_time_s": 0.5,
                "value": 1,
                "before_value": 0,
                "after_value": 1,
            }
        ],
    )
    result = evaluate_routed_pwm_samples(samples, contract, scenario)
    assert result["status"] != "PASS"
    assert (
        next(
            c for c in result["checks"] if c["name"] == "complete_fault_branch_states"
        )["passed"]
        is False
    )


def test_a_trace_missing_from_the_declared_contract_is_incomplete():
    samples, contract, scenario = complete_samples()
    contract["channels"].append(
        {"channel_id": "fault_current", "role": "i_dc_fault", "units": "kA"}
    )
    result = evaluate_routed_pwm_samples(samples, contract, scenario)
    assert result["status"] == "INCOMPLETE_ANALYSIS"


def ac_fault_samples(*, single_phase=False, fault_current=32.0, grid_current=29.7):
    samples, contract, scenario = complete_samples()
    scenario.update(
        name="ac_single_line_ground_fault" if single_phase else "ac_three_phase_fault",
        events=[
            {
                "event_id": "fault",
                "target": "ac_fault_command",
                "time_s": 0.3,
                "end_time_s": 0.5,
                "value": 1,
                "before_value": 0,
                "after_value": 1,
            }
        ],
    )
    times = samples["channels"][0]["domain"]

    def add(role, scope, value):
        channel_id = role + "_" + scope
        units = "kA" if role in {"ac_fault_current", "ac_grid_current"} else "1"
        contract["channels"].append(
            {
                "channel_id": channel_id,
                "role": role,
                "model_scope": scope,
                "units": units,
            }
        )
        samples["channels"].append(
            {
                "channel_id": channel_id,
                "units": units,
                "domain": times,
                "values": [value if 0.3 <= t < 0.5 else 0 for t in times],
            }
        )

    for branch in ("any", "AG", "BG", "CG", "AB", "BC", "CA"):
        add(
            "ac_fault_branch_state",
            branch,
            1
            if branch in ({"any", "AG"} if single_phase else {"any", "AG", "BG", "CG"})
            else 0,
        )
    for phase in "ABC":
        add(
            "ac_fault_current",
            phase,
            fault_current if not single_phase or phase == "A" else 0,
        )
        add("ac_grid_current", phase, grid_current)
    for channel in samples["channels"]:
        if channel["channel_id"].startswith("blocking_state_"):
            channel["values"] = [1 if 0.3 <= t < 0.5 else 0 for t in times]
    contract["ac_fault_network"] = {
        "voltage_kv": 230.0,
        "grid_resistance_ohm": 1.0527493472421685,
        "grid_reactance_ohm": 10.527493472421686,
        "transformer_zero_sequence_reactance_ohm": 5.29,
        "topology": "grounded_Y_delta",
    }
    return samples, contract, scenario


def test_ac_fault_current_uses_the_grid_short_circuit_envelope():
    result = evaluate_routed_pwm_samples(*ac_fault_samples())
    current_checks = [
        c for c in result["checks"] if c["name"].startswith("physical_fault_current_")
    ]
    assert len(current_checks) == 3
    assert all(c["passed"] for c in current_checks)


def test_single_phase_fault_includes_the_passive_transformer_zero_sequence_path():
    # Independent sequence-network calculation: Z1=Z2=Zg, Z0=Zg || j*5.29.
    # 3*Vphase / |Z1+Z2+Z0| = 16.125 kA RMS, crest < 45.61 kA.
    result = evaluate_routed_pwm_samples(
        *ac_fault_samples(single_phase=True, fault_current=39.82)
    )
    check = next(c for c in result["checks"] if c["name"] == "physical_fault_current_A")
    assert check["passed"] is True
    assert 45.5 < check["limit"]["maximum_ka"] < 45.7
    too_large = evaluate_routed_pwm_samples(
        *ac_fault_samples(single_phase=True, fault_current=47.0)
    )
    assert not next(
        c for c in too_large["checks"] if c["name"] == "physical_fault_current_A"
    )["passed"]


def test_single_phase_fault_still_checks_the_original_grid_source_crest():
    result = evaluate_routed_pwm_samples(
        *ac_fault_samples(single_phase=True, fault_current=39.82, grid_current=36.0)
    )
    assert any(
        c["name"].startswith("physical_grid_current_") and not c["passed"]
        for c in result["checks"]
    )


def test_single_phase_fault_requires_an_audited_sequence_network():
    samples, contract, scenario = ac_fault_samples(
        single_phase=True, fault_current=39.82
    )
    del contract["ac_fault_network"]
    result = evaluate_routed_pwm_samples(samples, contract, scenario)
    assert result["status"] == "INCOMPLETE_ANALYSIS"
