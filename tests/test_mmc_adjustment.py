from dataclasses import replace

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.adjustment import choose_next_candidate
from tests.mmc_parametric_fakes import (
    error_with_code,
    numerical_failure,
    parent_plan_with_four_candidates,
    repeated_failure,
)


def test_adjustment_uses_only_next_preplanned_candidate() -> None:
    plan = parent_plan_with_four_candidates()
    decision = choose_next_candidate(
        plan,
        "detailed_pwm",
        attempted=("pwm-0",),
        failure=numerical_failure(),
    )
    assert decision.candidate_id == "pwm-1"
    assert decision.adjustment.category == "numerical_stability"
    assert decision.candidate.parameter_hash in {
        item.parameter_hash for item in plan.engine_plans[0].candidates
    }


def test_same_signature_and_candidate_state_stops_loop() -> None:
    with pytest.raises(BackendError) as raised:
        choose_next_candidate(
            parent_plan_with_four_candidates(),
            "detailed_pwm",
            attempted=("pwm-0", "pwm-1"),
            failure=repeated_failure(),
        )
    assert raised.value.code == "MMC_CANDIDATES_EXHAUSTED"


def test_environment_failure_cannot_advance_candidate() -> None:
    with pytest.raises(BackendError) as raised:
        choose_next_candidate(
            parent_plan_with_four_candidates(),
            "detailed_pwm",
            attempted=("pwm-0",),
            failure=error_with_code("LICENSE_UNAVAILABLE"),
        )
    assert raised.value.code == "MMC_ADJUSTMENT_NOT_ALLOWED"


def test_duplicate_parameter_hashes_are_rejected() -> None:
    parent = parent_plan_with_four_candidates()
    child = parent.engine_plans[0]
    duplicate = replace(
        child.candidates[1], parameter_hash=child.candidates[0].parameter_hash
    )
    invalid_child = replace(
        child, candidates=(child.candidates[0], duplicate, *child.candidates[2:])
    )
    invalid_parent = replace(
        parent, engine_plans=(invalid_child, *parent.engine_plans[1:])
    )

    with pytest.raises(BackendError) as raised:
        choose_next_candidate(
            invalid_parent,
            "detailed_pwm",
            attempted=("pwm-0",),
            failure=numerical_failure(),
        )

    assert raised.value.code == "MMC_CANDIDATE_INVALID"
