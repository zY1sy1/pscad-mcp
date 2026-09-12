import asyncio
import importlib
from types import SimpleNamespace

import pytest

from scripts.run_mmc_average_arm_acceptance import _probe_owners


def test_cable_runner_requires_both_optins_before_materialization(
    tmp_path, monkeypatch
):
    runner = importlib.import_module("scripts.run_mmc_cable_acceptance")
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    monkeypatch.delenv("PSCAD_MCP_CABLE_ACCEPTANCE", raising=False)
    with pytest.raises(PermissionError, match="PSCAD_MCP_CABLE_ACCEPTANCE"):
        asyncio.run(runner.run_attempt(SimpleNamespace(), tmp_path / "unused"))
    assert not (tmp_path / "unused").exists()


def test_probe_owner_reader_checks_explicit_cable_units(tmp_path):
    path = tmp_path / "loop.pscx"
    path.write_text(
        """<project><definitions><Definition name="Main"><schematic>
<User id="17" defn="master:pgb"><paramlist><param name="Name" value="I_SEND"/>
<param name="Units" value="kA"/></paramlist></User>
</schematic></Definition></definitions></project>""",
        encoding="ascii",
    )
    assert _probe_owners(path, channel_units={"I_SEND": "kA"}) == {"I_SEND": "17"}
    with pytest.raises(ValueError, match="units"):
        _probe_owners(path, channel_units={"I_SEND": "A"})
    with pytest.raises(ValueError, match="missing"):
        _probe_owners(path, channel_units={"I_SEND": "kA", "V_SEND": "kV"})


def test_runtime_binding_rejects_changed_or_unbound_constants(tmp_path):
    import hashlib

    runner = importlib.import_module("scripts.run_mmc_cable_acceptance")
    constants = tmp_path / "line.clo"
    constants.write_bytes(b"verified coefficients")
    data = tmp_path / "Main.dta"
    data.write_text("TLINE-OUTPUT-DATA line.clo\n", encoding="ascii")
    fixture = {"constants_path": "constants/line.clo", "constants_sha256": hashlib.sha256(constants.read_bytes()).hexdigest()}
    executable = {"path": str(tmp_path / "model.exe")}
    assert str(constants) in runner.runtime_constants_receipt(executable, fixture)
    constants.write_bytes(b"different coefficients")
    with pytest.raises(ValueError, match="differ"):
        runner.runtime_constants_receipt(executable, fixture)
    data.write_text("TLINE-OUTPUT-DATA other.clo\n", encoding="ascii")
    with pytest.raises(ValueError, match="unexpected"):
        runner.runtime_constants_receipt(executable, fixture)
