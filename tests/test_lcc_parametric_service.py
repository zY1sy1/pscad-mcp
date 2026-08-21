import asyncio

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.parametric_models import LccRatings, ParametricLccRequest
from pscad_mcp.hvdc.builders.lcc.parametric_service import ParametricLccBuilderService


def request():
    return ParametricLccRequest("bipolar", LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 3.0), {"smoothing_reactor_mh": 120.0}, ("bipolar_run",))


def test_plan_is_deterministic():
    service = ParametricLccBuilderService()
    assert service.plan_parametric_model(request())["plan_hash"] == service.plan_parametric_model(request())["plan_hash"]


def test_build_rejects_stale_hash_before_write():
    service = ParametricLccBuilderService()
    with pytest.raises(BackendError) as raised:
        asyncio.run(service.build_parametric_model(request(), expected_plan_hash="wrong", confirm=True))
    assert raised.value.code == "LCC_PLAN_STALE"
