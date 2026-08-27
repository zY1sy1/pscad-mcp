import asyncio
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.core.service import ConfirmationRequired
from pscad_mcp.hvdc.builders.lcc.journal import WorkspaceBuildLease as LccLease
from tests.mmc_parametric_fakes import (
    make_parametric_service,
    valid_request,
    wait_for_terminal,
)


def _build(service, tmp_path: Path, request: dict):
    plan = service.plan_model(
        request, project_name="MMC_CASE", folder=str(tmp_path)
    )
    started = asyncio.run(
        service.build_model(
            request,
            plan["plan_hash"],
            "MMC_CASE",
            str(tmp_path),
            confirm=True,
        )
    )
    return plan, wait_for_terminal(service, started["build_id"])


def test_both_engines_publish_only_after_independent_acceptance(tmp_path: Path) -> None:
    service = make_parametric_service(
        tmp_path, pwm_verdict="PASS", avm_verdict="PASS"
    )
    request = valid_request(model_fidelity="both")

    plan, terminal = _build(service, tmp_path, request)

    assert terminal["state"] == "published"
    assert terminal["plan_hash"] == plan["plan_hash"]
    assert [
        item["capability_level"] for item in terminal["engines"]
    ] == ["accepted", "accepted"]
    assert (tmp_path / "MMC_CASE_pwm.pscx").is_file()
    assert (tmp_path / "MMC_CASE_avm.pscx").is_file()
    assert service.recorded_engine_calls == [
        ("detailed_pwm", "pwm-0"),
        ("average_value", "avm-0"),
    ]


def test_one_engine_failure_keeps_parent_unpublished_but_runs_other_child(
    tmp_path: Path,
) -> None:
    service = make_parametric_service(tmp_path, pwm_verdict="FAIL", avm_verdict="PASS")

    _, terminal = _build(service, tmp_path, valid_request(model_fidelity="both"))

    assert terminal["state"] == "failed"
    assert [item["state"] for item in terminal["engines"]] == ["failed", "accepted"]
    assert service.recorded_engine_calls == [
        ("detailed_pwm", "pwm-0"),
        ("average_value", "avm-0"),
    ]
    assert not (tmp_path / "MMC_CASE_pwm.pscx").exists()
    assert not (tmp_path / "MMC_CASE_avm.pscx").exists()


def test_retry_walks_only_preplanned_matching_candidate(tmp_path: Path) -> None:
    service = make_parametric_service(
        tmp_path, pwm_verdict="NUMERICAL_ONCE", avm_verdict="PASS"
    )

    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="detailed_pwm")
    )

    assert terminal["state"] == "published"
    assert service.recorded_engine_calls == [
        ("detailed_pwm", "pwm-0"),
        ("detailed_pwm", "pwm-1"),
    ]
    attempts = terminal["engines"][0]["attempts"]
    assert [item["candidate_id"] for item in attempts] == ["pwm-0", "pwm-1"]
    assert attempts[0]["adjustment"]["category"] == "numerical_stability"


def test_build_requires_confirmation_and_exact_recomposed_hash(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path)
    request = valid_request(model_fidelity="average_value")
    plan = service.plan_model(request, project_name="MMC_CASE", folder=str(tmp_path))

    with pytest.raises(ConfirmationRequired):
        asyncio.run(
            service.build_model(
                request,
                plan["plan_hash"],
                "MMC_CASE",
                str(tmp_path),
                confirm=False,
            )
        )
    with pytest.raises(BackendError) as raised:
        asyncio.run(
            service.build_model(
                request,
                "0" * 64,
                "MMC_CASE",
                str(tmp_path),
                confirm=True,
            )
        )
    assert raised.value.code == "MMC_PLAN_STALE"


def test_mmc_parent_uses_shared_lcc_workspace_lease(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path)
    request = valid_request(model_fidelity="average_value")
    plan = service.plan_model(request, project_name="MMC_CASE", folder=str(tmp_path))
    lease = LccLease.acquire(tmp_path, "lcc-active")
    try:
        with pytest.raises(BackendError) as raised:
            asyncio.run(
                service.build_model(
                    request,
                    plan["plan_hash"],
                    "MMC_CASE",
                    str(tmp_path),
                    confirm=True,
                )
            )
        assert raised.value.code in {"MMC_BUILD_CONFLICT", "LCC_BUILD_CONFLICT"}
    finally:
        assert lease.release(lease.token) is True


def test_validation_without_outputs_cannot_claim_acceptance(tmp_path: Path) -> None:
    service = make_parametric_service(tmp_path)
    _, terminal = _build(
        service, tmp_path, valid_request(model_fidelity="average_value")
    )

    validation = service.validate_model(
        terminal["engines"][0]["final_path"],
        "average_value",
        output_files=None,
    )

    assert validation["capability_level"] == "built"
    assert validation["accepted"] is False
    assert validation["acceptance"]["status"] == "not_evaluated"
