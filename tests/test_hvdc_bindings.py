from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.bindings import (
    matching_fingerprints,
    resolve_command_binding,
    resolve_requested_commands,
)
from pscad_mcp.hvdc.scanner import scan_project


def _evidence(tmp_path: Path, *, stem: str = "case", components: str | None = None):
    component_xml = components or """
      <component id='17' name='Trip command' definition='master:const'>
        <parameter name='Value' value='0'/><parameter name='Name' value='BrkOrd1'/>
      </component>"""
    path = tmp_path / f"{stem}.pscx"
    path.write_text(
        f"""<project name='{stem}' version='4.6.2'>
      <definition name='Main'><canvas name='Main'>{component_xml}</canvas></definition>
      <definition name='loadbreaker_3'/>
    </project>""",
        encoding="utf-8",
    )
    return scan_project(path)


def _profile(**overrides):
    profile = {
        "profile_version": 2,
        "project_fingerprints": [{
            "project_stem": "case",
            "pscad_version": "4.6.2",
            "definitions": ["loadbreaker_3"],
        }],
        "command_bindings": [{
            "canonical": "breaker_command",
            "component": {
                "canvas": "Main",
                "definition": "master:const",
                "component_id": "17",
            },
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
            "read_back": True,
        }],
    }
    profile.update(overrides)
    return profile


def test_binding_requires_matching_fingerprint_and_unique_component(tmp_path):
    evidence = _evidence(tmp_path)
    profile = _profile()

    assert matching_fingerprints(evidence, profile) == profile["project_fingerprints"]

    binding = resolve_command_binding(evidence, profile, "breaker_command", 1)

    assert binding == {
        "canonical": "breaker_command",
        "component_id": "17",
        "parameter_name": "Value",
        "old_value": "0",
        "semantics": "active_high",
        "read_back": True,
        "matched_fingerprint": profile["project_fingerprints"][0],
    }


def test_binding_rejects_unlisted_value_with_type_sensitive_equality(tmp_path):
    evidence = _evidence(tmp_path)
    profile = _profile(project_fingerprints=[])

    with pytest.raises(BackendError, match="allowed"):
        resolve_command_binding(evidence, profile, "breaker_command", 2)
    with pytest.raises(BackendError, match="allowed"):
        resolve_command_binding(evidence, profile, "breaker_command", True)


def test_display_parameter_remains_forbidden_even_when_profile_names_it(tmp_path):
    evidence = _evidence(tmp_path)
    profile = _profile(command_bindings=[{
        "canonical": "breaker_command",
        "component": {"component_id": "17"},
        "parameter_name": "Name",
        "allowed_values": ["BrkOrd1"],
        "semantics": "active_high",
    }])

    with pytest.raises(BackendError) as raised:
        resolve_command_binding(evidence, profile, "breaker_command", "BrkOrd1")

    assert raised.value.details["reason"] == "unsafe_command_parameter"


@pytest.mark.parametrize(
    ("components", "selector", "message", "reason"),
    [
        ("""
          <component id='18' name='Other' definition='master:const'>
            <parameter name='Value' value='0'/>
          </component>""", {"component_id": "17"}, "exactly one", "component_selector_unresolved"),
        ("""
          <component id='17' name='Trip command 1' definition='master:const'>
            <parameter name='Value' value='0'/>
          </component>
          <component id='18' name='Trip command 2' definition='master:const'>
            <parameter name='Value' value='0'/>
          </component>""", {}, "exactly one", "component_selector_ambiguous"),
    ],
)
def test_binding_requires_exactly_one_component_match(tmp_path, components, selector, message, reason):
    evidence = _evidence(tmp_path, components=components)
    profile = _profile(command_bindings=[{
        "canonical": "breaker_command",
        "component": {"canvas": "Main", "definition": "master:const", **selector},
        "parameter_name": "Value",
        "allowed_values": [0, 1],
        "semantics": "active_high",
    }])

    with pytest.raises(BackendError, match=message) as raised:
        resolve_command_binding(evidence, profile, "breaker_command", 1)

    assert raised.value.details["reason"] == reason


def test_binding_rejects_mismatched_project_stem(tmp_path):
    evidence = _evidence(tmp_path, stem="other_case")

    with pytest.raises(BackendError, match="fingerprint") as raised:
        resolve_command_binding(evidence, _profile(), "breaker_command", 1)

    assert raised.value.details["reason"] == "project_fingerprint_mismatch"


def test_binding_rejects_selected_component_without_exact_parameter(tmp_path):
    evidence = _evidence(tmp_path, components="""
      <component id='17' name='Trip command' definition='master:const'>
        <parameter name='value' value='0'/>
      </component>""")

    with pytest.raises(BackendError, match="parameter") as raised:
        resolve_command_binding(evidence, _profile(), "breaker_command", 1)

    assert raised.value.details["reason"] == "command_parameter_missing"


def test_requested_commands_preserve_request_order(tmp_path):
    evidence = _evidence(tmp_path, components="""
      <component id='17' name='Trip command' definition='master:const'>
        <parameter name='Value' value='0'/>
      </component>
      <component id='18' name='Fault command' definition='master:const'>
        <parameter name='Value' value='1'/>
      </component>""")
    profile = _profile(command_bindings=[
        {
            "canonical": "breaker_command",
            "component": {"component_id": "17"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
        },
        {
            "canonical": "fault_command",
            "component": {"component_id": "18"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_low",
        },
    ])

    bindings = resolve_requested_commands(evidence, profile, [
        {"canonical": "fault_command", "value": 0},
        {"canonical": "breaker_command", "value": 1},
    ])

    assert [binding["canonical"] for binding in bindings] == [
        "fault_command",
        "breaker_command",
    ]
