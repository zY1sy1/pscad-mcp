from dataclasses import replace
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from pscad_mcp.hvdc.builders.mmc.parametric_planner import create_parametric_plan
from tests.mmc_parametric_fakes import avm_assets, pwm_audit, valid_request


def test_parent_plan_is_deterministic_and_contains_two_independent_children(tmp_path: Path) -> None:
    request = parse_parametric_request(valid_request(model_fidelity="both"))
    before = list(tmp_path.iterdir())
    first = create_parametric_plan(request, "MMC_CASE", tmp_path, pwm_audit(), avm_assets())
    second = create_parametric_plan(request, "MMC_CASE", tmp_path, pwm_audit(), avm_assets())
    assert first.to_dict() == second.to_dict()
    assert first.plan_hash == second.plan_hash
    assert [plan.engine for plan in first.engine_plans] == ["detailed_pwm", "average_value"]
    assert [plan.target_name for plan in first.engine_plans] == ["MMC_CASE_pwm", "MMC_CASE_avm"]
    assert before == list(tmp_path.iterdir())


def test_planner_rejects_unresolved_pwm_path_dependency(tmp_path: Path) -> None:
    audit = pwm_audit()
    paths = tuple(
        {**item, "repair_policy": "requires_verified_rebind"}
        if item["kind"] == "line_constants"
        else item
        for item in audit.absolute_paths
    )
    with pytest.raises(BackendError) as raised:
        create_parametric_plan(
            parse_parametric_request(valid_request(model_fidelity="detailed_pwm")),
            "MMC_CASE",
            tmp_path,
            replace(audit, absolute_paths=paths),
            avm_assets(),
        )
    assert raised.value.code == "MMC_ABSOLUTE_PATH_UNRESOLVED"


def test_planner_rejects_existing_final_target(tmp_path: Path) -> None:
    (tmp_path / "MMC_CASE_avm.pscx").write_text("existing", encoding="utf-8")
    with pytest.raises(BackendError) as raised:
        create_parametric_plan(
            parse_parametric_request(valid_request(model_fidelity="average_value")),
            "MMC_CASE",
            tmp_path,
            pwm_audit(),
            avm_assets(),
        )
    assert raised.value.code == "MMC_BUILD_CONFLICT"
