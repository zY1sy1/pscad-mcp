from __future__ import annotations

import json

import pytest

from pscad_mcp.builders.blueprint.journal import BuildJournal, next_state, write_json_atomic
from pscad_mcp.builders.blueprint.models import BlueprintBuildState
from pscad_mcp.core.backend.base import BackendError


def test_next_state_accepts_only_declared_success_order_and_terminal_failures():
    assert next_state(BlueprintBuildState.PLANNED, BlueprintBuildState.STAGING_CREATED) is BlueprintBuildState.STAGING_CREATED
    assert next_state(BlueprintBuildState.COMPILED, BlueprintBuildState.SIMULATED) is BlueprintBuildState.SIMULATED
    assert next_state(BlueprintBuildState.SAVED, BlueprintBuildState.QUARANTINED) is BlueprintBuildState.QUARANTINED
    assert next_state(BlueprintBuildState.FAILED, BlueprintBuildState.QUARANTINED) is BlueprintBuildState.QUARANTINED

    for current, proposed in [
        (BlueprintBuildState.PLANNED, BlueprintBuildState.SAVED),
        (BlueprintBuildState.FAILED, BlueprintBuildState.ACCEPTANCE_PASSED),
        (BlueprintBuildState.PUBLISHED, BlueprintBuildState.FAILED),
        (BlueprintBuildState.QUARANTINED, BlueprintBuildState.PUBLISHED),
    ]:
        with pytest.raises(BackendError) as raised:
            next_state(current, proposed)
        assert raised.value.code == "BLUEPRINT_STATE_INVALID"


def test_journal_appends_json_safe_events_and_preserves_prior_lines(tmp_path):
    journal = BuildJournal(tmp_path, "build-001")

    journal.append("state", {"state": "planned", "plan_hash": "a" * 64})
    journal.append("operation", {"operation_id": "op-001", "requested": {"x": 1}, "observed": {"x": 1}})

    lines = journal.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    events = [json.loads(line) for line in lines]
    assert [event["event"] for event in events] == ["state", "operation"]
    assert all(event["build_id"] == "build-001" for event in events)
    assert all(event["timestamp_utc"].endswith("Z") for event in events)


def test_journal_rejects_unsafe_build_ids_and_non_finite_payloads(tmp_path):
    with pytest.raises(BackendError):
        BuildJournal(tmp_path, "../escape")

    journal = BuildJournal(tmp_path, "build-safe")
    with pytest.raises(BackendError) as raised:
        journal.append("operation", {"observed": float("nan")})
    assert raised.value.code == "BLUEPRINT_JOURNAL_INVALID"
    assert not journal.path.exists()


def test_atomic_json_write_replaces_complete_document(tmp_path):
    path = tmp_path / "evidence" / "manifest.json"
    write_json_atomic(path, {"state": "planned"})
    write_json_atomic(path, {"state": "published", "accepted": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"accepted": True, "state": "published"}
    assert list(path.parent.glob("*.pending")) == []
