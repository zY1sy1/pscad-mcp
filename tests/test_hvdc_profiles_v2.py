import json

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.profiles import load_profile


def _write_profile(tmp_path, payload, name="profile"):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _v2_profile(**overrides):
    profile = {
        "profile_version": 2,
        "required_assets": [],
        "mappings": [],
        "project_fingerprints": [],
        "command_bindings": [],
        "result_channels": [],
        "metric_roles": {},
        "sequences": [],
    }
    profile.update(overrides)
    return profile


def test_profile_v2_accepts_explicit_commands_results_and_metric_roles(tmp_path):
    path = _write_profile(tmp_path, _v2_profile(
        required_assets=["breaker"],
        project_fingerprints=[{"project_stem": "case", "definitions": ["loadbreaker_3"]}],
        command_bindings=[{
            "canonical": "breaker_command",
            "component": {
                "canvas": "BreakerBlock",
                "definition": "master:const",
                "component_id": "17",
            },
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
            "read_back": True,
        }],
        result_channels=[{
            "canonical": "dc_voltage_breaker",
            "path": "loadbreaker_3/UMC",
            "call_id": 90,
            "units": "kV",
            "location": "breaker",
        }],
        metric_roles={"dc_voltage": "dc_voltage_breaker"},
    ))

    loaded = load_profile("case_profile", str(path))

    assert loaded["profile_version"] == 2
    assert loaded["command_bindings"][0]["parameter_name"] == "Value"
    assert loaded["result_channels"][0]["call_id"] == 90
    assert loaded["metric_roles"] == {"dc_voltage": "dc_voltage_breaker"}


@pytest.mark.parametrize("field", ["command_bindings", "result_channels"])
def test_profile_v2_rejects_duplicate_canonicals(tmp_path, field):
    item = (
        {
            "canonical": "x",
            "component": {"definition": "master:const"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
        }
        if field == "command_bindings"
        else {"canonical": "x", "path": "Main/X", "units": "kV"}
    )
    payload = _v2_profile(**{field: [item, dict(item)]})
    path = _write_profile(tmp_path, payload)

    with pytest.raises(BackendError, match="duplicated"):
        load_profile("case_profile", str(path))


@pytest.mark.parametrize("version", [True, False, 0, 3, "2"])
def test_profile_rejects_non_integer_or_unsupported_versions(tmp_path, version):
    path = _write_profile(tmp_path, _v2_profile(profile_version=version))

    with pytest.raises(BackendError, match="profile_version"):
        load_profile("case_profile", str(path))


def test_profile_v2_rejects_invalid_explicit_binding_sections(tmp_path):
    path = _write_profile(tmp_path, _v2_profile(
        project_fingerprints=["not-an-object"],
        command_bindings=[{
            "canonical": "breaker_command",
            "component": {},
            "parameter_name": "",
            "allowed_values": [],
            "semantics": "unknown",
        }],
        result_channels=[{
            "canonical": "dc_voltage_breaker",
            "path": "",
            "call_id": True,
        }],
        metric_roles={"dc_voltage": 1},
        sequences=["not-an-object"],
    ))

    with pytest.raises(BackendError, match="project_fingerprints"):
        load_profile("case_profile", str(path))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"project_fingerprints": [{"project_stem": 7}]}, "project_stem"),
        ({"command_bindings": [{
            "canonical": "breaker_command",
            "component": {"component_id": 17},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
        }]}, "component_id"),
        ({"command_bindings": [{
            "canonical": "breaker_command",
            "component": {"component_id": "17"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
            "read_back": "yes",
        }]}, "read_back"),
        ({"result_channels": [{
            "canonical": "dc_voltage_breaker",
            "path": "loadbreaker_3/UMC",
            "units": 7,
        }]}, "units"),
        ({"result_channels": [{
            "canonical": "dc_voltage_breaker",
            "path": "loadbreaker_3/UMC",
            "location": 7,
        }]}, "location"),
        ({"sequences": [{}]}, r"sequences\[0\]"),
    ],
)
def test_profile_v2_rejects_invalid_nested_binding_fields(tmp_path, overrides, message):
    path = _write_profile(tmp_path, _v2_profile(**overrides))

    with pytest.raises(BackendError, match=message):
        load_profile("case_profile", str(path))


def test_profile_v2_inheritance_merges_canonical_lists_and_metric_roles(tmp_path):
    workspace = tmp_path / "workspace"
    profile_directory = workspace / ".pscad-mcp" / "hvdc-profiles"
    profile_directory.mkdir(parents=True)
    _write_profile(profile_directory, _v2_profile(
        command_bindings=[
            {
                "canonical": "breaker_command",
                "component": {"component_id": "17"},
                "parameter_name": "Value",
                "allowed_values": [0],
                "semantics": "active_low",
            },
            {
                "canonical": "fault_command",
                "component": {"component_id": "18"},
                "parameter_name": "Value",
                "allowed_values": [0, 1],
                "semantics": "active_high",
            },
        ],
        result_channels=[
            {"canonical": "dc_voltage", "path": "Main/Old", "units": "kV"},
            {"canonical": "dc_current", "path": "Main/Current", "units": "kA"},
        ],
        metric_roles={"dc_voltage": "dc_voltage", "dc_current": "dc_current"},
    ), "parent")
    child = _write_profile(tmp_path, _v2_profile(
        extends="parent",
        command_bindings=[{
            "canonical": "breaker_command",
            "component": {"component_id": "17"},
            "parameter_name": "Value",
            "allowed_values": [1],
            "semantics": "active_high",
        }],
        result_channels=[{"canonical": "dc_voltage", "path": "Main/New", "units": "kV"}],
        metric_roles={"dc_voltage": "dc_voltage_override"},
    ), "child")

    loaded = load_profile("child", str(child), workspace_root=workspace)

    assert {item["canonical"] for item in loaded["command_bindings"]} == {
        "breaker_command", "fault_command",
    }
    assert next(item for item in loaded["command_bindings"] if item["canonical"] == "breaker_command")["allowed_values"] == [1]
    assert {item["canonical"] for item in loaded["result_channels"]} == {"dc_voltage", "dc_current"}
    assert next(item for item in loaded["result_channels"] if item["canonical"] == "dc_voltage")["path"] == "Main/New"
    assert loaded["metric_roles"] == {
        "dc_voltage": "dc_voltage_override",
        "dc_current": "dc_current",
    }


def test_v1_child_cannot_override_a_v2_parent_with_unvalidated_bindings(tmp_path):
    workspace = tmp_path / "workspace"
    profile_directory = workspace / ".pscad-mcp" / "hvdc-profiles"
    profile_directory.mkdir(parents=True)
    _write_profile(profile_directory, _v2_profile(), "parent_v2")
    child = _write_profile(tmp_path, {
        "extends": "parent_v2",
        "required_assets": [],
        "mappings": [],
        "command_bindings": [{"canonical": "unvalidated"}],
    }, "child_v1")

    with pytest.raises(BackendError, match="version"):
        load_profile("child_v1", str(child), workspace_root=workspace)


def test_v2_child_revalidates_v1_parent_fields_after_inheritance(tmp_path):
    workspace = tmp_path / "workspace"
    profile_directory = workspace / ".pscad-mcp" / "hvdc-profiles"
    profile_directory.mkdir(parents=True)
    _write_profile(profile_directory, {
        "required_assets": [],
        "mappings": [],
        "result_channels": [{"canonical": "missing_path"}],
    }, "parent_v1")
    child = _write_profile(tmp_path, _v2_profile(extends="parent_v1"), "child_v2")

    with pytest.raises(BackendError, match="requires path"):
        load_profile("child_v2", str(child), workspace_root=workspace)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("command_bindings", ["not-an-object"], r"command_bindings\[0\] must be an object"),
        ("result_channels", [{"path": "Main/X"}], "requires a non-empty canonical"),
        ("metric_roles", [], "metric_roles"),
    ],
)
def test_v2_child_reports_invalid_v1_parent_fields_as_backend_errors(
    tmp_path,
    field,
    value,
    message,
):
    workspace = tmp_path / "workspace"
    profile_directory = workspace / ".pscad-mcp" / "hvdc-profiles"
    profile_directory.mkdir(parents=True)
    parent = {"required_assets": [], "mappings": [], field: value}
    _write_profile(profile_directory, parent, "parent_v1")
    child = _write_profile(tmp_path, _v2_profile(extends="parent_v1"), "child_v2")

    with pytest.raises(BackendError, match=message):
        load_profile("child_v2", str(child), workspace_root=workspace)


@pytest.mark.parametrize("field", ["command_bindings", "result_channels"])
def test_v2_child_rejects_duplicate_canonicals_in_a_v1_parent(tmp_path, field):
    workspace = tmp_path / "workspace"
    profile_directory = workspace / ".pscad-mcp" / "hvdc-profiles"
    profile_directory.mkdir(parents=True)
    item = (
        {
            "canonical": "breaker_command",
            "component": {"component_id": "17"},
            "parameter_name": "Value",
            "allowed_values": [0, 1],
            "semantics": "active_high",
        }
        if field == "command_bindings"
        else {"canonical": "dc_voltage_breaker", "path": "Main/UMC", "units": "kV"}
    )
    _write_profile(
        profile_directory,
        {"required_assets": [], "mappings": [], field: [item, dict(item)]},
        "parent_v1",
    )
    child = _write_profile(tmp_path, _v2_profile(extends="parent_v1"), "child_v2")

    with pytest.raises(BackendError, match="duplicated"):
        load_profile("child_v2", str(child), workspace_root=workspace)


def test_returned_profile_nested_values_do_not_mutate_the_builtin_source():
    first = load_profile("hvdc_breaker_difforder")
    first["result_channels"][0]["path"] = "mutated"
    first["mappings"][0]["aliases"].append("mutated")

    second = load_profile("hvdc_breaker_difforder")

    assert second["result_channels"][0]["path"] != "mutated"
    assert "mutated" not in second["mappings"][0]["aliases"]


def test_breaker_profile_v2_defines_exact_result_selectors():
    profile = load_profile("hvdc_breaker_difforder")

    assert {
        item["canonical"]: {
            key: item.get(key)
            for key in ("path", "call_id", "units", "location")
        }
        for item in profile["result_channels"]
    } == {
        "dc_voltage_breaker": {
            "path": "loadbreaker_3/UMC",
            "call_id": 90,
            "units": "kV",
            "location": "breaker",
        },
        "dc_current_breaker": {
            "path": "loadbreaker_3/IMC",
            "call_id": 83,
            "units": "kA",
            "location": "breaker",
        },
        "breaker_command_observed": {
            "path": "loadbreaker_3/BrkOrd1",
            "call_id": 78,
            "units": None,
            "location": "breaker",
        },
        "dc_voltage_rectifier_pole1": {
            "path": "Main/VDCRp1",
            "call_id": 1,
            "units": "pu",
            "location": "rectifier_pole1",
        },
        "dc_voltage_inverter_pole1": {
            "path": "Main/VDCIp1",
            "call_id": 3,
            "units": "pu",
            "location": "inverter_pole1",
        },
        "dc_voltage_rectifier_pole2": {
            "path": "Main/VDCRp2",
            "call_id": 6,
            "units": "pu",
            "location": "rectifier_pole2",
        },
        "dc_voltage_inverter_pole2": {
            "path": "Main/VDCIp2",
            "call_id": 9,
            "units": "pu",
            "location": "inverter_pole2",
        },
    }
    assert profile["sequences"] == []
