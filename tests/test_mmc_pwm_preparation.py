"""PWM response repair preserves physical bounds and source identity."""

from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.pwm_channels import compose_pwm_scenario_contract
from pscad_mcp.hvdc.builders.mmc.pwm_preparation import materialize_pwm_power_response


def source(tmp_path, *, time="0.2"):
    path = tmp_path / "source.pscx"
    root = ET.fromstring(
        '<project name="source"><definitions><Definition name="Main"><schematic/></Definition></definitions></project>'
    )
    for mode in ("0", "1"):
        user = ET.SubElement(
            root.find(".//schematic"), "User", id=mode, defn="source:VSCConverter"
        )
        group = ET.SubElement(user, "paramlist")
        for key, value in {
            "dmode": mode,
            "Ti_P": time,
            "Ti_Q": time,
            "Imax": "1.1",
            "Ti_dc": "0.04",
        }.items():
            ET.SubElement(group, "param", name=key, value=value)
    ET.ElementTree(root).write(path, encoding="utf-8")
    return path


def test_response_repair_leaves_current_and_voltage_loops_unchanged(tmp_path):
    original = source(tmp_path)
    before = original.read_bytes()
    destination = tmp_path / "copy.pscx"
    report = materialize_pwm_power_response(original, destination)
    assert original.read_bytes() == before
    assert report["physical_acceptance_required"] is True
    for user in ET.parse(destination).findall(".//User"):
        parameters = {
            p.get("name"): p.get("value") for p in user.findall("./paramlist/param")
        }
        assert parameters["Imax"] == "1.1"
        assert parameters["Ti_dc"] == "0.04"


def test_response_repair_refuses_an_unverified_source_controller(tmp_path):
    original = source(tmp_path, time="0.1")
    destination = tmp_path / "copy.pscx"
    with pytest.raises(BackendError):
        materialize_pwm_power_response(original, destination)
    assert not destination.exists()


def test_scenario_contract_refuses_a_forged_initializer_identity(tmp_path):
    original = source(tmp_path)
    with pytest.raises(RuntimeError, match="instrumented baseline"):
        compose_pwm_scenario_contract(
            {"project_path": str(original), "instrumented_project_sha256": "a" * 64},
            {
                "timed_control": {"scenario_source": {"path": str(original)}},
                "pwm_initialization": {"source_sha256": "b" * 64},
            },
            "PWM",
        )
