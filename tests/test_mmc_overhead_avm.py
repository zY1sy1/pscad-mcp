"""The public native AVM must honor an audited overhead-line request."""

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.hvdc.builders.mmc.engines.avm import AvmBlueprintEngine
from pscad_mcp.hvdc.builders.mmc.parametric_models import parse_parametric_request
from pscad_mcp.hvdc.builders.mmc.parametric_planner import create_parametric_plan
from tests.mmc_parametric_fakes import avm_assets, valid_request


def _authored_overhead_sources(tmp_path):
    """Small independently authored geometry; no vendor XML is distributed."""
    root = ET.Element("project", name="Authored", version="4.6.2")
    definitions = ET.SubElement(root, "definitions")
    dctl = ET.SubElement(definitions, "Definition", name="DCTL")
    types = ET.SubElement(dctl, "paramlist")
    ET.SubElement(types, "param", name="type", value="TLine")
    canvas = ET.SubElement(dctl, "schematic")
    records = {
        "Line_Tower_2_Flat": {
            "CDataType": 1, "GDataType": 1, "Hollow": 0, "SHSag": 0, "SHBund": 1,
            "BundSym": 0, "Transp": 1, "NG": 1, "ElimGW": 1, "GWSame": 1, "NC1": 1, "NC2": 2,
            "RadiusC": "0.02 [m]", "DCResC": "0.06 [ohm/km]", "Y": "30 [m]", "XC": "10 [m]",
            "BSP": "0.4 [m]", "RadiusG": "0.004 [m]", "DCResG": "0.25 [ohm/km]",
            "YG": "36 [m]", "NCondB": 3, "SAGC": "10 [m]", "SAGG": "8 [m]",
            "XG": "0 [m]", "ShuntG": "1e-11 [mho/m]",
        },
        "Line_Ground": {"GRRES": "100 [ohm*m]", "GPERM": 1},
        "Line_FrePhase_Options": {"YMaxP": 20, "AMaxP": 20, "YMaxE": 0.2, "AMaxE": 0.2},
    }
    for name, values in records.items():
        user = ET.SubElement(canvas, "User", defn="master:" + name)
        params = ET.SubElement(user, "paramlist")
        for key, value in values.items():
            ET.SubElement(params, "param", name=key, value=str(value))
    wire = ET.SubElement(canvas, "Wire", classid="TLine", defn="Authored:DCTL")
    user = ET.SubElement(wire, "User")
    params = ET.SubElement(user, "paramlist")
    for key, value in {"Name": "AuthoredLine", "Dim": 2, "Freq": "0 [Hz]", "Length": "200 [km]",
                       "Mode": 1, "ManEnab": 0, "CoupleEnab": 0}.items():
        ET.SubElement(params, "param", name=key, value=str(value))
    donor, master, tline = (tmp_path / name for name in ("donor.pscx", "master.pslx", "tline.exe"))
    ET.ElementTree(root).write(donor)
    master.write_text('<project version="4.6.2"/>')
    tline.write_bytes(b"not executable; planning only")
    return {"master": str(master), "overhead_donor": str(donor), "tline": str(tline)}


def test_authored_overhead_profile_is_bound_to_the_public_plan_without_native_launch(tmp_path):
    sources = _authored_overhead_sources(tmp_path)
    engine = AvmBlueprintEngine(native_sources=sources, native_required=True)
    request = parse_parametric_request(valid_request(model_fidelity="average_value", converter="full_bridge",
        dc_link={"kind": "overhead_line", "length_km": 150.0}))
    inputs = engine.planning_inputs(request)
    plan = create_parametric_plan(request, "AUTHORED", tmp_path, None, avm_assets(), avm_native_inputs=inputs)
    assert plan.engine_plans[0].candidates[0].parameters["line_resistance_ohm"] == pytest.approx(6.0)
    parameters = plan.engine_plans[0].candidates[0].parameters
    resistance = parameters["station_dc_filter_resistance_ohm"]
    capacitance = parameters["station_dc_filter_capacitance_f"]
    # The existing reclose/reset interval is 0.13 s. Reserve twenty RC time
    # constants for passive recharging; the deadline itself is unchanged.
    assert 20 * resistance * capacitance <= 0.13
    assert request.dc_voltage_kv / (2 * resistance) == pytest.approx(request.active_power_mw / request.dc_voltage_kv)
    assert 1 / (2 * 3.141592653589793 * resistance * capacitance) == pytest.approx(request.frequency_hz / 2)
    assert not (tmp_path / ".mmc-candidates").exists()


@pytest.mark.parametrize("quantity,invalid", [("RadiusC", "NaN [m]"), ("NCondB", "2.5"),
                                               ("DCResC", "0.06 [ohm/m]"), ("NC2", "1")])
def test_overhead_geometry_rejects_invalid_units_bundle_and_conductor_order(tmp_path, quantity, invalid):
    from pscad_mcp.hvdc.builders.mmc.overhead_constants import (
        extract_overhead_configuration,
    )
    sources = _authored_overhead_sources(tmp_path)
    tree = ET.parse(sources["overhead_donor"])
    tree.find(f".//param[@name='{quantity}']").set("value", invalid)
    tree.write(sources["overhead_donor"])
    with pytest.raises(ValueError):
        extract_overhead_configuration(sources["overhead_donor"], master_path=sources["master"])


def test_native_overhead_artifacts_and_module_are_verified_before_any_simulation(tmp_path, installed_overhead_sources):
    from pscad_mcp.hvdc.builders.mmc.native_bundle import audit_native_avm_fixture
    from pscad_mcp.hvdc.builders.mmc.overhead_constants import (
        verify_overhead_constants_receipt,
    )
    sources = installed_overhead_sources
    engine = AvmBlueprintEngine(native_sources=sources, native_required=True)
    request = parse_parametric_request(valid_request(model_fidelity="average_value", converter="full_bridge",
        dc_link={"kind": "overhead_line", "length_km": 200.0}))
    inputs = engine.planning_inputs(request)
    plan = create_parametric_plan(request, "NATIVE_OHL", tmp_path, None, avm_assets(), avm_native_inputs=inputs).engine_plans[0]

    async def no_op(*args, **kwargs):
        return {"messages": []}

    service = SimpleNamespace(load_projects=no_op, save_project=no_op, build_project=no_op, get_project_output=no_op)
    result = asyncio.run(engine.execute_candidate(plan, service))
    fixture = result["fixture"]
    case_root = ET.parse(result["project_path"])
    filters = case_root.findall("./definitions/Definition[@name='Main']/schematic/User[@defn='master:capacitor']")
    assert len(filters) == 4
    assert case_root.find("./paramlist/param[@name='StartType']").get("value") == "0"
    assert all(c.find("./paramlist/param[@name='Vinit']") is None for c in filters)
    library_root = ET.parse(fixture["library"]["library_path"])
    configuration = library_root.find("./definitions/Definition[@name='MMCOverheadLink']/schematic/Wire[@classid='TLine']/User")
    assert configuration.find("./paramlist/param[@name='Mode']").get("value") == "0"
    for interface in library_root.findall("./definitions/Definition[@name='MMCOverheadLink']/schematic/User[@defn='master:tline_interface']"):
        assert interface.get("q") == "4"
        assert interface.find("paramlist").get("name") == ""
        assert interface.find("paramlist").get("link") == "-1"
    assert result["model_accepted"] is False
    assert fixture["topology"]["coupled_overhead_count"] == 1
    assert fixture["topology"]["coupled_cable_count"] == 0
    receipt = fixture["library"]["constants_receipt"]
    _, record, _, _ = verify_overhead_constants_receipt(receipt, sources["overhead_donor"], sources["master"])
    assert record["coefficient_structure"]["delay_groups"] == 2
    assert fixture["parameters"]["dc_link_capacitance_f"] == pytest.approx(
        200 * record["differential_capacitance_f_per_km"] + fixture["parameters"]["station_dc_filter_capacitance_f"]
    )
    # A changed endpoint must be rejected even when the mutated library hash is supplied.
    library = Path(fixture["library"]["library_path"])
    tree = ET.parse(library)
    parameter = tree.find("./definitions/Definition[@name='MMCOverheadLink']/schematic/User[@defn='master:tline_interface']/paramlist/param[@name='NC']")
    parameter.set("value", "3")
    tree.write(library)
    with pytest.raises(ValueError, match="conductor order"):
        audit_native_avm_fixture(result["project_path"], fixture,
                                finalized_library_sha256=hashlib.sha256(library.read_bytes()).hexdigest())


def test_overhead_receipt_rejects_a_changed_physical_value_with_unchanged_artifacts(tmp_path, installed_overhead_sources):
    from pscad_mcp.hvdc.builders.mmc.overhead_constants import (
        generate_public_overhead_constants,
        verify_overhead_constants_receipt,
    )
    sources = installed_overhead_sources
    artifact = generate_public_overhead_constants(sources["overhead_donor"], tmp_path / "constants",
        master_path=sources["master"], executable=sources["tline"])[0]
    path = Path(artifact.evidence_path)
    report = json.loads(path.read_text())
    report["differential_capacitance_f_per_km"] *= 2
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="physical or coefficient evidence"):
        verify_overhead_constants_receipt(path, sources["overhead_donor"], sources["master"])


@pytest.fixture
def installed_overhead_sources():
    master = Path(r"C:\Program Files (x86)\PSCAD46\master.pslx")
    donor = Path(r"C:\Users\Public\Documents\PSCAD\4.6\Examples\ModelsInProgress\H_MMC_Mono_DC.pscx")
    tline = master.parent / "bin/win/tline.exe"
    if not all(path.is_file() for path in (master, donor, tline)):
        pytest.skip("Installed PSCAD XML and native line-constants utility are required")
    return {"master": str(master), "overhead_donor": str(donor), "tline": str(tline)}


@pytest.mark.parametrize("voltage,power", [(640.0, 1000.0), (500.0, 750.0)])
def test_overhead_plan_uses_physical_bundle_resistance_without_rating_scaling(
    tmp_path, installed_overhead_sources, voltage, power
):
    engine = AvmBlueprintEngine(native_sources=installed_overhead_sources, native_required=True)
    request = parse_parametric_request(valid_request(
        model_fidelity="average_value", converter="full_bridge",
        dc_voltage_kv=voltage, active_power_mw=power,
        dc_link={"kind": "overhead_line", "length_km": 200.0},
    ))
    inputs = engine.planning_inputs(request)
    assert inputs["capabilities"]["native_overhead_constants"] is True
    assert inputs["capabilities"].get("native_cable_constants", False) is False
    assert inputs["source_hashes"]["overhead_donor"] == hashlib.sha256(
        Path(installed_overhead_sources["overhead_donor"]).read_bytes()
    ).hexdigest()
    plan = create_parametric_plan(request, "OVERHEAD", tmp_path, None, avm_assets(),
                                  avm_native_inputs=inputs).engine_plans[0]
    assert plan.candidates[0].parameters["line_resistance_ohm"] == pytest.approx(
        2 * 0.03182 / 3 * 200
    )
    assert plan.candidates[0].parameters["dc_link_kind"] == "overhead_line"
    assert not list(tmp_path.iterdir())
