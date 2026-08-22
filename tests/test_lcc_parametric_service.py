import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.parametric_models import LccRatings, ParametricLccRequest
from pscad_mcp.hvdc.builders.lcc.parametric_service import ParametricLccBuilderService


def request():
    return ParametricLccRequest(
        topology="bipolar",
        ratings=LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 3.0),
        engineering_overrides={
            "smoothing_reactor_mh": 120.0,
            "filter_capacitance_uf": 60.0,
            "min_firing_angle_deg": 5.0,
            "max_firing_angle_deg": 170.0,
        },
        operation_modes=("bipolar_run",),
        return_path_assets=("neutral_bus",),
    )


def test_plan_is_deterministic():
    service = ParametricLccBuilderService()
    assert service.plan_parametric_model(request())["plan_hash"] == service.plan_parametric_model(request())["plan_hash"]


def test_build_rejects_stale_hash_before_write(tmp_path):
    root = tmp_path / "must-not-be-created"
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=root)
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.build_parametric_model(request(), expected_plan_hash="wrong", confirm=True))
    assert raised.value.code == "LCC_PLAN_STALE"
    assert service._statuses == {}
    assert not root.exists()


def test_build_requires_confirmation_before_configuration_checks():
    service = ParametricLccBuilderService()
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.build_parametric_model(request(), expected_plan_hash="wrong", confirm=False))
    assert raised.value.code == "CONFIRMATION_REQUIRED"
    assert service._statuses == {}


@pytest.mark.parametrize(
    ("pscad_service", "workspace_root", "missing"),
    [
        (None, ".", ["pscad_service"]),
        (object(), None, ["workspace_root"]),
        (None, None, ["pscad_service", "workspace_root"]),
    ],
)
def test_build_fails_closed_when_lifecycle_configuration_is_missing(
    tmp_path, pscad_service, workspace_root, missing
):
    root = tmp_path / "must-not-be-created" if workspace_root is not None else None
    service = ParametricLccBuilderService(pscad_service=pscad_service, workspace_root=root)
    plan = service.plan_parametric_model(request())

    with pytest.raises(BackendError) as raised:
        asyncio.run(
            service.build_parametric_model(
                request(), expected_plan_hash=plan["plan_hash"], confirm=True
            )
        )

    assert raised.value.code == "LCC_BUILD_UNAVAILABLE"
    assert raised.value.details["missing"] == missing
    assert service._statuses == {}
    if root is not None:
        assert not root.exists()


def test_build_fails_closed_when_real_executor_is_not_connected(tmp_path):
    root = tmp_path / "must-not-be-created"
    service = ParametricLccBuilderService(pscad_service=object(), workspace_root=root)
    plan = service.plan_parametric_model(request())

    with pytest.raises(BackendError) as raised:
        asyncio.run(
            service.build_parametric_model(
                request(), expected_plan_hash=plan["plan_hash"], confirm=True
            )
        )

    assert raised.value.code == "LCC_BUILD_UNAVAILABLE"
    assert raised.value.details["reason"] == "real_lifecycle_not_implemented"
    assert service._statuses == {}
    assert not root.exists()
