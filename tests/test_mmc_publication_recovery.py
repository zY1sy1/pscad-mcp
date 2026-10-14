"""Publication retries cannot promote partial or live electrical evidence."""

import json

import pytest

from pscad_mcp.hvdc.builders.mmc.publication_recovery import read_recoverable_matrix
from pscad_mcp.hvdc.builders.mmc.pwm_validation import SCENARIOS


def report():
    return {
        "stage": "finished",
        "sources_immutable": True,
        "remaining_owned_processes": [],
        "parent_status": {
            "engines": [
                {
                    "candidate_result": {
                        "model_accepted": True,
                        "routed_physical_acceptance": True,
                        "scenario_results": [{"name": n} for n in SCENARIOS],
                        "independent_reload_accepted": True,
                    }
                }
            ]
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        {"stage": "running"},
        {"sources_immutable": False},
        {"remaining_owned_processes": [1234]},
    ],
)
def test_live_changed_or_uncleaned_evidence_is_rejected(tmp_path, change):
    payload = report()
    payload.update(change)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="finished, immutable, cleaned-up"):
        read_recoverable_matrix(path)


def test_all_eleven_scenes_and_reload_are_required(tmp_path):
    payload = report()
    candidate = payload["parent_status"]["engines"][0]["candidate_result"]
    candidate["scenario_results"].pop()
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="complete accepted eleven-scenario"):
        read_recoverable_matrix(path)
