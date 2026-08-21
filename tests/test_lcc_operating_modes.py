import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.modes import derive_mode_copies, validate_lcc_schedule


def test_mode_copies_are_independent_records():
    copies = derive_mode_copies({"plan_hash": "x"}, ("bipolar_run", "metallic_return"))
    assert [item.mode for item in copies] == ["bipolar_run", "metallic_return"]


def test_schedule_is_strictly_monotonic():
    schedule = validate_lcc_schedule([{"event_id": "e1", "time_s": 1.0, "target": "metallic_return", "value": 1}])
    assert schedule[0].event_id == "e1"


@pytest.mark.parametrize("events", [
    [{"event_id": "e1", "time_s": 1.0, "target": "metallic_return", "value": 1}, {"event_id": "e1", "time_s": 2.0, "target": "metallic_return", "value": 0}],
    [{"event_id": "e1", "time_s": 2.0, "target": "metallic_return", "value": 1}, {"event_id": "e2", "time_s": 1.0, "target": "metallic_return", "value": 0}],
])
def test_schedule_rejects_duplicate_or_non_increasing_events(events):
    with pytest.raises(BackendError) as raised:
        validate_lcc_schedule(events)
    assert raised.value.code == "LCC_OPERATING_MODE_INVALID"
