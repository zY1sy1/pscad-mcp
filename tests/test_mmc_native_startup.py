from pscad_mcp.hvdc.builders.mmc.native_startup import PrechargeState, STARTUP_INPUTS, advance_precharge, analyze_precharge_trace


def observation(capacitor=240.0, current=0.01):
    return {name: capacitor if name.endswith("_VCAP") else current if name.endswith("_I") else 480.0 for name in STARTUP_INPUTS}


def test_precharge_waits_for_charge_convergence_and_a_continuous_ready_hold():
    state = PrechargeState()
    for i in range(1, 5001):
        t = i * 0.0001
        sample = observation(100.0 if t < 0.2 else 240.0, 0.4 if 0.25 < t < 0.3 else 0.01)
        state, result = advance_precharge(state, sample, t, 0.0001, {})
        if t < 0.33:
            assert not result["ready"]
    assert result["ready"] and not result["failed"]
    assert 0.33 <= state.start_time_s < 0.5
    later, result = advance_precharge(state, observation(200.0, 1.0), 0.6, 0.0001, {})
    assert later.start_time_s == state.start_time_s  # readiness is latched, not rearmed during operation


def test_time_alone_cannot_deblock_a_low_capacitor_or_a_high_current():
    for sample in (observation(100.0), observation(current=1.0)):
        state = PrechargeState()
        for i in range(1, 11001):
            state, result = advance_precharge(state, sample, i * 0.0001, 0.0001, {})
        assert not result["ready"]
        assert result["failed"]


def test_independent_precharge_audit_checks_waveforms_before_using_state_anchors():
    time = [i / 1000 for i in range(4001)]
    trace = {"time": time, "PRECHARGE_READY": [float(t >= 0.25) for t in time],
             "PRECHARGE_FAILED": [0.0] * len(time), "DEBLOCK_TIME": [-1.0 if t < 0.25 else 0.25 for t in time]}
    for name, value in observation().items():
        trace[name] = [value] * len(time)
        if name.endswith("_VCAP"):
            trace[name.removesuffix("_VCAP") + "_W"] = [1.875] * len(time)
    for station in ("P", "V"):
        trace[station + "_BLOCK"] = [float(t < 0.25) for t in time]
    parameters = {"output_step_s": 0.001, "frequency_hz": 60.0, "vdc_order_kv": 640.0,
                  "deblock_time_s": 0.1, "maximum_precharge_time_s": 1.0,
                  "precharge_current_limit_ka": 2.0, "reversal_time_s": 1.0, "reversal_duration_s": 1.0}
    result = analyze_precharge_trace(trace, parameters)
    assert result["status"] == "PASS" and result["model_accepted"] is False
    assert result["operating_windows"]["forward"] == [0.75, 1.05]
    trace["P_A_UPPER_W"][230] = 5.0
    result = analyze_precharge_trace(trace, parameters)
    assert result["status"] == "FAIL"
    assert "P:precharge_energy_convergence" in result["failed_checks"]
    trace["P_A_UPPER_I"][230] = float("nan")
    assert analyze_precharge_trace(trace, parameters)["status"] == "FAIL"
