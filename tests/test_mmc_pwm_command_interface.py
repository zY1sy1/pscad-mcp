"""Independent schematic fixtures for physical PWM command routing."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError


def test_pwm_command_interface_refuses_unrouted_source_without_writing(tmp_path: Path):
    from pscad_mcp.hvdc.builders.mmc.pwm_commands import (
        materialize_pwm_command_interface,
    )

    source = tmp_path / "source.pscx"
    master = tmp_path / "master.pslx"
    library = tmp_path / "intermediate.pslx"
    source.write_text('<project name="source" version="4.6.2"><definitions/></project>')
    master.write_text("<library><definitions/></library>")
    library.write_text('<library name="intermediate"><definitions/></library>')
    destination = tmp_path / "prepared.pscx"
    before = source.read_bytes(), master.read_bytes(), library.read_bytes()
    with pytest.raises(BackendError) as raised:
        materialize_pwm_command_interface(
            source, destination, master=master, library=library, rated_power_mw=1000.0
        )
    assert raised.value.code == "MMC_PWM_CONTROL_TOPOLOGY_UNSUPPORTED"
    assert not destination.exists()
    assert before == (source.read_bytes(), master.read_bytes(), library.read_bytes())


def test_pwm_reset_combines_existing_reset_and_explicit_command():
    from pscad_mcp.hvdc.builders.mmc.pwm_commands import append_reset_combiner

    root = ET.fromstring('<project name="fixture"><definitions/></project>')
    definition = append_reset_combiner(root)
    ports = {
        item.get("name"): (item.get("type"), item.get("mode"))
        for item in definition.findall("./svg/port")
    }
    assert ports == {
        "ORIGINAL": ("Integer", "Input"),
        "COMMAND": ("Real", "Input"),
        "RESET": ("Integer", "Output"),
    }
    code = definition.find("./script/segment[@name='Dsdyn']").text
    assert "$ORIGINAL" in code and "$COMMAND" in code and "$RESET" in code
