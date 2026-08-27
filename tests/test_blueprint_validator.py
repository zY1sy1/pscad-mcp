from __future__ import annotations

import json
from pathlib import Path

from pscad_mcp.builders.blueprint.validator import inspect_project_file, validate_staging, write_validation_report
from test_blueprint_planner import plan
from test_blueprint_schema import valid_blueprint


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


def test_inspect_project_file_reads_real_pscx_user_components():
    fixture = Path(__file__).parent / "fixtures" / "lcc" / "graph_case.pscx"

    graph = inspect_project_file(fixture)

    assert [component["logical_id"] for component in graph["components"]] == [
        "source",
        "bridge",
        "load",
    ]
    assert graph["components"][1]["definition"] == "cigre_lcc_v1:LCC12PulseBridge"
    assert graph["components"][1]["orientation"] == 4
    assert graph["components"][1]["parameters"]["ValveDrop"] == "1.2"
    assert graph["wires"][0]["vertices"] == [[10, 0], [50, 0], [50, 20], [90, 20]]


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


def test_validator_checks_planned_operation_location_effect(tmp_path):
    build_plan = plan(tmp_path)
    staging = tmp_path / "staging"
    project = write_staging_project(staging)
    project.write_text(project.read_text(encoding="utf-8").replace('x="20" y="30"', 'x="99" y="30"'), encoding="utf-8")

    report = validate_staging(build_plan, staging, dataset=validation_dataset(), messages=[])

    assert report["operation_acceptance"] is False
    assert report["run_through_acceptance"] is False
    assert report["operation_checks"][0]["operation_id"] == "op-001"


def test_validator_uses_planned_renamed_entry_when_package_has_other_pscx_files(tmp_path):
    build_plan = plan(tmp_path)
    staging = tmp_path / "staging"
    write_staging_project(staging)
    nested = staging / "support"
    nested.mkdir()
    (nested / "legacy.pscx").write_text("<project name='legacy'/>", encoding="utf-8")

    report = validate_staging(build_plan, staging, dataset=validation_dataset(), messages=[])

    assert report["valid"] is True
    assert report["evidence"]["project"] == "BuiltCase.pscx"


def test_validator_resolves_runtime_logical_bindings_from_persisted_component_ids(tmp_path):
    build_plan = plan(tmp_path)
    staging = tmp_path / "staging"
    project = write_staging_project(staging)
    project.write_text(project.read_text(encoding="utf-8").replace('logical_id="breaker_copy"', 'logical_id="vendor-name"'), encoding="utf-8")
    evidence = staging / "evidence"
    evidence.mkdir()
    (evidence / "runtime-bindings.json").write_text(
        json.dumps({"component_bindings": {"breaker_copy": 1}}),
        encoding="utf-8",
    )

    report = validate_staging(build_plan, staging, dataset=validation_dataset(), messages=[])

    assert report["operation_acceptance"] is True
    assert report["structure_acceptance"] is True
    assert report["valid"] is True


def test_validator_confirms_connect_ports_as_persisted_real_pscx_wire(tmp_path):
    blueprint = valid_blueprint()
    blueprint["operations"].extend(
        [
            {
                "sequence": 3,
                "kind": "create_component",
                "target": "aux",
                "arguments": {
                    "logical_id": "aux",
                    "definition": "master:breaker",
                    "location": [40, 30],
                    "orientation": 0,
                    "canvas": "Main",
                    "parameters": {"Name": "AUX"},
                },
                "operation_id": "op-003",
            },
            {
                "sequence": 4,
                "kind": "connect_ports",
                "target": "connection-1",
                "arguments": {
                    "canvas": "Main",
                    "from": {"logical_id": "breaker_copy", "port": "B"},
                    "to": {"logical_id": "aux", "port": "A"},
                },
                "operation_id": "op-004",
            },
        ]
    )
    build_plan = plan(tmp_path, blueprint=blueprint)
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "BuiltCase.pscx").write_text(
        """<project name="BuiltCase" version="4.6.2">
  <definitions><Definition name="Main"><schematic>
    <User classid="UserCmp" id="17" logical_id="source_breaker" defn="master:breaker" x="10" y="30" orient="0">
      <paramlist><param name="Name" value="BRK_SOURCE" /></paramlist>
    </User>
    <User classid="UserCmp" id="18" logical_id="breaker_copy" defn="master:breaker" x="20" y="30" orient="0">
      <paramlist><param name="Name" value="BRK_COPY" /></paramlist>
      <Port name="B" x="21" y="30" />
    </User>
    <User classid="UserCmp" id="19" logical_id="aux" defn="master:breaker" x="40" y="30" orient="0">
      <paramlist><param name="LogicalId" value="aux" /><param name="Name" value="AUX" /></paramlist>
      <Port name="A" x="39" y="30" />
    </User>
    <Wire classid="WireOrthogonal" id="20" x="21" y="30" orient="0">
      <vertex x="0" y="0" /><vertex x="18" y="0" />
    </Wire>
  </schematic></Definition></definitions>
</project>
""",
        encoding="utf-8",
    )
    evidence = staging / "evidence"
    evidence.mkdir()
    (evidence / "runtime-bindings.json").write_text(
        json.dumps(
            {
                "component_bindings": {"source_breaker": 17, "breaker_copy": 18, "aux": 19},
                "operation_readbacks": {
                    "op-004": {
                        "wire_id": 20,
                        "from": {"component_id": 18, "port": "B", "x": 21, "y": 30},
                        "to": {"component_id": 19, "port": "A", "x": 39, "y": 30},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report = validate_staging(build_plan, staging, dataset=validation_dataset(), messages=[])

    connection = next(check for check in report["operation_checks"] if check["operation_id"] == "op-004")
    assert connection["passed"] is True
    assert connection["observed"]["vertices"] == [[21, 30], [39, 30]]
    assert report["operation_acceptance"] is True

    project = staging / "BuiltCase.pscx"
    project.write_text(
        project.read_text(encoding="utf-8")
        .replace('x="21" y="30" orient="0">\n      <vertex x="0" y="0" /><vertex x="18" y="0" />', 'x="100" y="100" orient="0">\n      <vertex x="0" y="0" /><vertex x="20" y="0" />'),
        encoding="utf-8",
    )
    runtime = json.loads((evidence / "runtime-bindings.json").read_text(encoding="utf-8"))
    runtime["operation_readbacks"]["op-004"]["from"].update(x=100, y=100)
    runtime["operation_readbacks"]["op-004"]["to"].update(x=120, y=100)
    (evidence / "runtime-bindings.json").write_text(json.dumps(runtime), encoding="utf-8")

    drifted = validate_staging(build_plan, staging, dataset=validation_dataset(), messages=[])

    connection = next(check for check in drifted["operation_checks"] if check["operation_id"] == "op-004")
    assert connection["passed"] is False
    assert drifted["valid"] is False


def test_validator_rejects_mismatched_persisted_project_identity(tmp_path):
    build_plan = plan(tmp_path)
    staging = tmp_path / "staging"
    project = write_staging_project(staging)
    project.write_text(project.read_text(encoding="utf-8").replace('name="BuiltCase"', 'name="WrongProject"'), encoding="utf-8")

    report = validate_staging(build_plan, staging, dataset=validation_dataset(), messages=[])

    assert report["project_identity_acceptance"] is False
    assert report["valid"] is False


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
