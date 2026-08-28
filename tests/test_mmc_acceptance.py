from __future__ import annotations

import math

import pytest

from pscad_mcp.hvdc.builders.mmc.acceptance import (
    AVM_LIMITATIONS,
    AcceptanceState,
    CheckResult,
    ac_power_tracking_check,
    arm_current_check,
    capacitance_consistency_check,
    circulating_current_check,
    compare_golden,
    dc_link_check,
    dc_power_check,
    energy_consistency_check,
    energy_profile_check,
    evaluate_acceptance,
    modulation_check,
    normalize_samples,
    phase_kcl_check,
    pll_check,
    power_balance_check,
    precharge_check,
    reverse_steady_check,
    reversal_check,
    station_energy_check,
)
from pscad_mcp.hvdc.builders.mmc.models import MmcAcceptanceCheck


CHECKS = tuple(
    MmcAcceptanceCheck(
        name=name,
        kind="window",
        required=True,
        expected={"channels": ["vdc"]},
        units="kV",
        comparison_window=(0.0, 1.0),
    )
    for name in ("precharge_ready", "forward_steady", "power_reversal", "reverse_steady")
)


def _series(values=(1.0, 2.0, 3.0)):
    return {"vdc": {"units": "kV", "time": [0.0, 0.5, 1.0], "values": list(values)}}


def test_samples_require_finite_nonempty_strictly_increasing_aligned_data():
    normalized = normalize_samples(_series())
    assert normalized["vdc"].state == AcceptanceState.OBSERVED.value
    assert normalize_samples({"vdc": {"units": "kV", "time": [0.0, 0.0], "values": [1.0, 1.0]}})["vdc"].state == AcceptanceState.INVALID.value
    assert normalize_samples({"vdc": {"units": "V", "time": [0.0, 1.0], "values": [1.0, 1.0]}})["vdc"].state == AcceptanceState.INVALID.value
    assert normalize_samples({"vdc": {"units": "kV", "time": [], "values": []}})["vdc"].state == AcceptanceState.MISSING.value


def test_golden_comparison_requires_aligned_units_and_uses_scale_floor():
    result = compare_golden(_series((1.0, 2.0, 3.0)), _series((1.0, 2.0, 3.0)), scale_floor=1.0)
    assert result.passed is True
    assert result.state == AcceptanceState.DERIVED.value
    bad = compare_golden(_series((1.0, 2.0, 3.0)), _series((1.0, 2.0, 4.0)), scale_floor=1.0, nrmse_max=0.1, max_error_max=0.1)
    assert bad.passed is False
    assert bad.state == AcceptanceState.DERIVED.value


def test_empty_or_unreviewed_golden_cannot_create_a_passing_result():
    empty = compare_golden(_series(), {"source": {"builder_generated": False}, "channels": {}})
    assert empty.passed is False
    assert empty.state == AcceptanceState.MISSING.value

    unreviewed = evaluate_acceptance(
        _series(),
        CHECKS,
        golden={
            "source": {"status": "independently_reviewed_reference_required", "builder_generated": False},
            "channels": {},
        },
    )
    assert unreviewed.verdict == "INCOMPLETE_ANALYSIS"
    assert any(result.name == "golden" and not result.passed for result in unreviewed.checks)

    reviewed = {
        "source": {"status": "independently_reviewed", "builder_generated": False},
        "channels": {
            "vdc": {
                **_series()["vdc"],
                "scale_floor": 1.0,
                "nrmse_max": 0.01,
                "max_error_max": 0.02,
            }
        },
    }
    assert compare_golden(_series(), reviewed).passed is True


def test_physical_checks_cover_arm_equation_energy_and_modulation():
    assert arm_current_check(9.0, 3.0, 0.2, 4.7, 1.7).passed is True
    assert arm_current_check(9.0, 3.0, 0.2, 4.7, 2.3).passed is False
    assert energy_consistency_check(2_000_000.0, 10_000.0, 20.0).passed is True
    assert energy_consistency_check(-1.0, 10_000.0, 20.0).passed is False
    assert modulation_check(1.2, 1.0, 0.0, 0.5).passed is True
    assert modulation_check(1.2, 1.2, 0.0, 0.5).passed is False
    assert power_balance_check(100.0, 98.0, 2.0).passed is True
    assert phase_kcl_check(3.0, 4.7, 1.7, 9.0, 0.2).passed is True
    assert circulating_current_check(0.1, 0.05, 0.2, 0.1).passed is True
    assert pll_check(True, 50.0, 50.0, 0.5, 0.1, 1.0).passed is True
    assert precharge_check(0.5, 1.0, True).passed is True
    assert reversal_check([1.0, 0.0, -1.0], [1.0, 0.2, -1.0], zero_cross_index=1, max_overshoot=0.3).passed is True


def test_physical_checks_cover_polarity_tracking_energy_limits_and_reverse_steady():
    assert dc_link_check(320.0, -320.0, 640.0).passed is True
    assert dc_link_check(320.0, 320.0, 640.0).passed is False
    assert dc_power_check(640.0, 1.5625, 1000.0).passed is True
    assert dc_power_check(640.0, -1.5625, 1000.0).passed is False
    assert ac_power_tracking_check(1000.0, 0.0, 1000.0, 0.0).passed is True
    assert ac_power_tracking_check(900.0, 0.0, 1000.0, 0.0).passed is False
    assert station_energy_check([1_000.0, 1_100.0], 2_100.0, 0.0).passed is True
    assert station_energy_check([1_000.0, -1.0], 999.0, 0.0).passed is False
    assert energy_profile_check([100.0, 101.0, 99.0], ripple_fraction_limit=0.05).passed is True
    assert energy_profile_check([100.0, 150.0], ripple_fraction_limit=0.05).passed is False
    assert capacitance_consistency_check(2_000_000.0, 10_000.0, 20.0).passed is True
    assert precharge_check(0.5, 1.0, True, energy_converged=True, deblocked=False, protection_active=False).passed is True
    assert precharge_check(0.5, 1.0, True, energy_converged=False, deblocked=False, protection_active=False).passed is False
    assert reverse_steady_check([-1000.0, -999.0], [-1.5, -1.49], power_limit=1100.0, current_limit=2.0).passed is True
    assert reverse_steady_check([1000.0, -999.0], [-1.5, -1.49], power_limit=1100.0, current_limit=2.0).passed is False


def test_acceptance_reports_missing_without_zero_fill_and_avm_limitations():
    report = evaluate_acceptance({"vdc": {"units": "kV", "time": [0.0, 0.5], "values": [1.0, 2.0]}}, CHECKS)
    assert report.verdict == "INCOMPLETE_ANALYSIS"
    assert any(result.state == AcceptanceState.MISSING.value for result in report.checks)
    assert all(item["state"] == "not_modeled" for item in report.limitations)
    assert all(item["passed"] is False for item in report.limitations)


def test_acceptance_passes_only_when_every_required_window_is_observed():
    samples = {"vdc": {"units": "kV", "time": [0.0, 0.5, 1.0], "values": [1.0, 2.0, 3.0]}}
    report = evaluate_acceptance(
        samples,
        CHECKS,
        golden={
            "source": {"status": "independently_reviewed", "builder_generated": False},
            "channels": {"vdc": samples["vdc"]},
        },
        physical_checks=(arm_current_check(9.0, 3.0, 0.2, 4.7, 1.7),),
    )
    assert report.verdict == "PASS"
    assert all(result.passed for result in report.checks)


def test_reviewed_golden_without_independent_physical_evidence_cannot_pass():
    samples = _series()
    report = evaluate_acceptance(
        samples,
        CHECKS,
        golden={
            "source": {"status": "independently_reviewed", "builder_generated": False},
            "channels": {"vdc": samples["vdc"]},
        },
    )

    assert report.verdict == "INCOMPLETE_ANALYSIS"
    physical = next(result for result in report.checks if result.name == "physical_contract")
    assert physical.state == AcceptanceState.MISSING.value
    assert physical.passed is False


def test_physical_evidence_must_be_unique_check_results():
    physical = arm_current_check(9.0, 3.0, 0.2, 4.7, 2.3)
    report = evaluate_acceptance(
        _series(),
        CHECKS,
        golden={
            "source": {"status": "independently_reviewed", "builder_generated": False},
            "channels": {"vdc": _series()["vdc"]},
        },
        physical_checks=(physical, physical),
    )

    assert report.verdict == "INCOMPLETE_ANALYSIS"
    contract = next(result for result in report.checks if result.name == "physical_contract")
    assert contract.state == AcceptanceState.INVALID.value
    assert contract.passed is False


def test_physical_evidence_with_missing_state_cannot_pass():
    report = evaluate_acceptance(
        _series(),
        CHECKS,
        golden={
            "source": {"status": "independently_reviewed", "builder_generated": False},
            "channels": {"vdc": _series()["vdc"]},
        },
        physical_checks=(CheckResult("arm_current", AcceptanceState.MISSING.value, True),),
    )

    assert report.verdict == "INCOMPLETE_ANALYSIS"
    contract = next(result for result in report.checks if result.name == "physical_contract")
    assert contract.passed is False
    assert contract.state == AcceptanceState.MISSING.value


def test_acceptance_requires_a_reviewed_golden_reference_before_pass():
    report = evaluate_acceptance(_series(), CHECKS)
    assert report.verdict == "INCOMPLETE_ANALYSIS"
    assert any(result.name == "golden" and result.state == AcceptanceState.MISSING.value for result in report.checks)


def test_acceptance_rejects_nonfinite_values_and_no_extrapolation():
    invalid = {"vdc": {"units": "kV", "time": [0.0, 0.5, 1.0], "values": [1.0, math.inf, 3.0]}}
    report = evaluate_acceptance(invalid, CHECKS)
    assert report.verdict == "INCOMPLETE_ANALYSIS"
    outside = tuple(
        MmcAcceptanceCheck(name=check.name, kind=check.kind, required=True, expected={"channels": ["vdc"]}, units="kV", comparison_window=(0.0, 2.0))
        for check in CHECKS
    )
    report = evaluate_acceptance(_series(), outside)
    assert report.verdict == "INCOMPLETE_ANALYSIS"


def test_acceptance_rejects_duplicate_or_reordered_required_windows():
    duplicate = CHECKS[:-1] + (CHECKS[0],)
    report = evaluate_acceptance(_series(), duplicate)
    assert report.verdict == "INCOMPLETE_ANALYSIS"
    assert any(result.name == "acceptance_contract" and result.state == AcceptanceState.INVALID.value for result in report.checks)
