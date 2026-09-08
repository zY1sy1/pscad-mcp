import asyncio

import pytest

from tests.test_backend_components import StatefulComponent
from tests.test_master_definition_bindings import _runtime_backend


@pytest.mark.parametrize("orientation", range(8))
def test_created_orientation_uses_native_horizontal_mirror(tmp_path, orientation):
    async def exercise():
        backend, project, _ = await _runtime_backend(tmp_path)
        created = await backend.add_component("case", "Main", "master", "ac_meter", (36, 36), orientation,
            {"ActivePowerSignal": "P_ORIENTATION", "ReactivePowerSignal": "Q_ORIENTATION"})
        return project.main.components[-1], backend._component_orientations[("case", created.id)]

    component, cached = asyncio.run(exercise())
    assert component.mirrored is (orientation >= 4)
    assert component.flipped is False
    assert component.orientation == (orientation % 4) * 90
    assert cached == orientation


@pytest.mark.parametrize("axis, code", [("horizontal", 4), ("vertical", 6)])
def test_mirror_cache_matches_native_saved_orientation(tmp_path, axis, code):
    async def exercise():
        backend, project, _ = await _runtime_backend(tmp_path)
        created = await backend.add_component("case", "Main", "master", "ac_meter", (36, 36), 0,
            {"ActivePowerSignal": "P_ORIENTATION", "ReactivePowerSignal": "Q_ORIENTATION"})
        await backend.mirror_component("case", created.id, axis)
        return project.main.components[-1], backend._component_orientations[("case", created.id)]

    component, cached = asyncio.run(exercise())
    assert component.mirrored is (axis == "horizontal")
    assert component.flipped is (axis == "vertical")
    assert cached == code


def test_expanded_filter_uses_the_same_native_mirror(tmp_path):
    async def exercise():
        backend, project, _ = await _runtime_backend(tmp_path)
        await backend.add_component("case", "Main", "master", "ac_filter_branch", (360, 180), 4,
            {"Branch_MVAR": 50.0, "Tuning_Hz": 300.0})
        return [component for component in project.main.components if isinstance(component, StatefulComponent) and component.defn_name == "master:cfilter"]

    filters = asyncio.run(exercise())
    assert len(filters) == 3
    assert all(component.mirrored and not component.flipped for component in filters)
