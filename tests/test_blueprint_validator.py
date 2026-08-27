from __future__ import annotations

import json
from pathlib import Path

from pscad_mcp.builders.blueprint.validator import inspect_project_file, validate_staging, write_validation_report
from test_blueprint_planner import plan


def write_staging_project(root: Path, *, definition="master:breaker", parameter="BRK_COPY") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    project = root / "BuiltCase.pscx"
    project.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<project name="BuiltCase" version="4.6.2">
  <definition name="Main">
    <component id="1" logical_id="breaker_copy" definition="{definition}" x="20" y="30" orientation="0">
      <parameters><param name="Name" value="{parameter}" /></parameters>
      <port name="A" x="19" y="30" kind="electrical" dimension="1" />
      <port name="B" x="21" y="30" kind="electrical" dimension="1" />
    </component>
  </definition>
</project>
""",
        encoding="utf-8",
    )
    return project


def validation_dataset() -> dict:
    return {
        "channels": {
            "Main/BRK_STATE": {
                "path": "Main/BRK_STATE",
                "units": "state",
                "domain": [0.0, 0.1],
                "values": [0.0, 1.0],
            }
        }
    }


def test_inspect_project_file_reads_persisted_components_parameters_and_ports(tmp_path):
    project = write_staging_project(tmp_path)

    graph = inspect_project_file(project)

    assert graph["project_name"] == "BuiltCase"
    assert graph["pscad_version"] == "4.6.2"
    assert graph["components"][0]["logical_id"] == "breaker_copy"
    assert graph["components"][0]["parameters"] == {"Name": "BRK_COPY"}
    assert [port["name"] for port in graph["components"][0]["ports"]] == ["A", "B"]


def test_validator_independently_accepts_matching_saved_evidence(tmp_path):
    build_plan = plan(tmp_path)
    staging = tmp_path / "staging"
    write_staging_project(staging)

    report = validate_staging(build_plan, staging, dataset=validation_dataset(), messages=[])

    assert report["source_integrity"] is True
    assert report["structure_acceptance"] is True
    assert report["parameters_acceptance"] is True
    assert report["messages_acceptance"] is True
    assert report["run_through_acceptance"] is True
    assert report["valid"] is True


def test_validator_does_not_trust_executor_success_when_saved_graph_drifted(tmp_path):
    build_plan = plan(tmp_path)
    staging = tmp_path / "staging"
    write_staging_project(staging, definition="master:source")

    report = validate_staging(
        build_plan,
        staging,
        dataset=validation_dataset(),
        messages=[],
        executor_result={"state": "acceptance_passed", "run_through_acceptance": True},
    )

    assert report["structure_acceptance"] is False
    assert report["run_through_acceptance"] is False
    assert report["valid"] is False
    assert report["structure_checks"][0]["observed_definition"] == "master:source"


def test_validator_detects_parameter_message_and_source_drift(tmp_path):
    build_plan = plan(tmp_path)
    staging = tmp_path / "staging"
    write_staging_project(staging, parameter="WRONG")
    (Path(build_plan.source_path) / "support" / "notes.txt").write_text("tampered", encoding="utf-8")

    report = validate_staging(
        build_plan,
        staging,
        dataset=validation_dataset(),
        messages=[{"severity": "error", "text": "Fatal compiler issue"}],
    )

    assert report["source_integrity"] is False
    assert report["parameters_acceptance"] is False
    assert report["messages_acceptance"] is False
    assert report["run_through_acceptance"] is False
    assert report["blocking_messages"][0]["text"] == "Fatal compiler issue"


def test_validation_report_is_written_inside_staging_with_relative_evidence_paths(tmp_path):
    build_plan = plan(tmp_path)
    staging = tmp_path / "staging"
    write_staging_project(staging)
    report = validate_staging(build_plan, staging, dataset=validation_dataset(), messages=[])

    path = write_validation_report(staging, report)

    assert path == staging / "evidence" / "validation-report.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["evidence"]["project"] == "BuiltCase.pscx"
    assert str(staging) not in json.dumps(value)
