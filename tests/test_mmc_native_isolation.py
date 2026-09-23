from xml.etree import ElementTree as ET

from pscad_mcp.hvdc.builders.mmc.native_bundle import materialize_native_avm_library
from pscad_mcp.hvdc.builders.mmc.native_isolation import PREINSERT_LOGIC
from tests.test_mmc_native_bundle import constants_evidence, installed_sources  # noqa: F401
from tests.test_mmc_native_dq import _run_native_equations


def test_preinsertion_never_leaves_an_auxiliary_path_connected_after_trip(constants_evidence, installed_sources, tmp_path):
    donor, master = installed_sources
    receipt = materialize_native_avm_library(tmp_path / "isolation.pslx", constants_evidence=constants_evidence,
                                             source_project=donor, master_path=master)
    root = ET.parse(receipt["library_path"])
    definition = root.find(f"./definitions/Definition[@name='{PREINSERT_LOGIC}']")
    rows = _run_native_equations(tmp_path, PREINSERT_LOGIC, definition=definition,
        declarations="", initialize="", loop="""SIG_OPEN = 0.0
if (TIME >= 0.1 .and. TIME < 0.12) SIG_OPEN = 1.0""",
        observations="if (sample == 1000 .or. sample == 2010 .or. sample == 2300 .or. sample == 2405 .or. sample == 3000) print *, SIG_MAIN_OPEN, SIG_AUX_OPEN", steps=3000)
    assert rows == [[0.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0]]
    pole = root.find("./definitions/Definition[@name='MMCDCIsolationPole']/schematic")
    for name in ("contact", "preinsert_contact"):
        contact = pole.find(f"User[@name='{name}']")
        assert contact.get("defn") == "master:breaker1"
        assert contact.find("./paramlist/param[@name='ENAB']").get("value") == "0"
