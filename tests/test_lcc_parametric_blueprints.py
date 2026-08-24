import copy
import hashlib
from pathlib import Path

import pytest
import xml.etree.ElementTree as ET

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import (
    canonical_json,
    load_parametric_blueprint,
    load_parametric_catalog,
    load_parametric_provenance,
    validate_parametric_blueprint_asset,
    validate_parametric_catalog_asset,
    validate_parametric_provenance_asset,
)
from pscad_mcp.hvdc.builders.lcc.parametric_models import (
    DerivedParameter,
    DerivedParameterReport,
    LccRatings,
    ParametricLccRequest,
)
from pscad_mcp.hvdc.builders.lcc.derivation import derive_lcc_parameters
from pscad_mcp.hvdc.builders.lcc.planner import create_parametric_topology_plan
from pscad_mcp.hvdc.builders.lcc.template_audit import audit_lcc_template
from pscad_mcp.hvdc.builders.lcc.validator import validate_parametric_topology_contract


FIXTURES = Path(__file__).parent / "fixtures" / "lcc_parametric"


def test_parametric_blueprints_have_distinct_topology_contracts():
    mono = load_parametric_blueprint("lcc_monopole_parametric_v1")
    bipole = load_parametric_blueprint("lcc_bipole_parametric_v1")
    assert mono["topology"] == "lcc" and mono["poles"] == 1
    assert bipole["topology"] == "lcc" and bipole["poles"] == 2
    assert {"positive_pole", "negative_pole", "neutral_bus"} <= set(bipole["required_assets"])
    assert mono["contract_kind"] == bipole["contract_kind"] == "template_role_topology"
    assert mono["components"] and mono["nets"] and mono["outputs"]
    assert bipole["components"] and bipole["nets"] and bipole["outputs"]


def test_bipole_declares_exact_real_template_roles_returns_and_baseline_outputs():
    bipole = load_parametric_blueprint("lcc_bipole_parametric_v1")

    assert set(bipole["template_roles"]) == {
        "rectifier_positive_pole",
        "rectifier_negative_pole",
        "inverter_positive_pole",
        "inverter_negative_pole",
        "earth_electrode",
    }
    assert {item["logical_id"] for item in bipole["components"]} == {
        *bipole["template_roles"],
        "neutral_bus",
        "metallic_return_terminal",
    }
    nets = {item["logical_id"]: item for item in bipole["nets"]}
    assert {"dc_positive", "dc_negative", "neutral_bus", "earth_return", "metallic_return"} == set(nets)
    assert nets["dc_positive"]["endpoints"] == [
        {"role": "rectifier_positive_pole", "port": "DCP1"},
        {"role": "inverter_positive_pole", "port": "DCP1"},
    ]
    assert nets["earth_return"]["endpoints"] == [
        {"role": "neutral_bus", "port": "earth"},
        {"role": "earth_electrode", "port": "A"},
    ]
    assert nets["metallic_return"]["endpoints"] == [
        {"role": "neutral_bus", "port": "metallic"},
        {"role": "metallic_return_terminal", "port": "remote"},
    ]
    assert {item["name"] for item in bipole["outputs"]} == {
        "VDCRp1", "VDCRp2", "VDCIp1", "VDCIp2",
        "CMRp1", "CMRp2", "CMIp1", "CMIp2",
        "Ielectrode", "PR", "PI",
        "AORp1", "AORp2", "AOIp1", "AOIp2",
        "VacR", "Vac (rms)", "VacI", "VacI (rms)", "QR", "QI",
    }
    assert len(bipole["outputs"]) == 21
    current_units = {
        item["name"]: item["units"]
        for item in bipole["outputs"]
        if item["name"].startswith(("CMR", "CMI"))
    }
    assert current_units == {
        "CMRp1": "pu", "CMRp2": "pu", "CMIp1": "pu", "CMIp2": "pu"
    }


def test_monopole_has_its_own_roles_nets_and_outputs():
    mono = load_parametric_blueprint("lcc_monopole_parametric_v1")

    assert set(mono["template_roles"]) == {
        "rectifier_valve_group", "inverter_valve_group", "earth_electrode"
    }
    assert {item["logical_id"] for item in mono["nets"]} == {
        "dc_pole", "earth_return", "metallic_return"
    }
    assert {item["name"] for item in mono["outputs"]} == {
        "VDCRp1", "VDCIp1", "CMRp1", "CMIp1", "Ielectrode",
        "PR", "PI", "AORp1", "AOIp1",
    }


def test_parametric_catalog_is_versioned():
    catalog = load_parametric_catalog()
    assert catalog["identity"] == "lcc_parametric_catalog_v1"
    assert catalog["pscad_version"] == "4.6.2"
    for name in ("lcc_monopole_parametric_v1", "lcc_bipole_parametric_v1"):
        blueprint = load_parametric_blueprint(name)
        assert hashlib.sha256(canonical_json(blueprint)).hexdigest() == catalog["blueprint_hashes"][name]


def test_parametric_blueprint_loader_rejects_schema_drift_and_missing_structure():
    catalog = load_parametric_catalog()
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")

    for mutate in (
        lambda value: value.update({"unexpected": True}),
        lambda value: value.update({"outputs": []}),
        lambda value: value["components"].pop(),
        lambda value: value["nets"].pop(),
    ):
        candidate = copy.deepcopy(blueprint)
        mutate(candidate)
        with pytest.raises(BackendError) as raised:
            validate_parametric_blueprint_asset(candidate, "lcc_bipole_parametric_v1", catalog)
        assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_parametric_blueprint_rejects_rehashed_pole_and_return_endpoint_drift():
    catalog = load_parametric_catalog()
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    nets = {item["logical_id"]: item for item in blueprint["nets"]}
    nets["dc_positive"]["endpoints"][0] = {
        "role": "rectifier_negative_pole",
        "port": "DCP1",
    }
    nets["earth_return"]["endpoints"][0] = {
        "role": "neutral_bus",
        "port": "metallic",
    }
    catalog["blueprint_hashes"]["lcc_bipole_parametric_v1"] = hashlib.sha256(
        canonical_json(blueprint)
    ).hexdigest()

    with pytest.raises(BackendError) as raised:
        validate_parametric_blueprint_asset(
            blueprint, "lcc_bipole_parametric_v1", catalog
        )
    assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_parametric_catalog_loader_rejects_undeclared_roles_and_contract_fields():
    catalog = load_parametric_catalog()
    bad_role = copy.deepcopy(catalog)
    bad_role["logical_parameter_bindings"]["rated_power_mw"]["roles_by_topology"]["bipolar"] = ["ghost_pole"]
    with pytest.raises(BackendError) as raised:
        validate_parametric_catalog_asset(bad_role)
    assert raised.value.code == "LCC_ASSET_MISMATCH"

    extra_field = copy.deepcopy(catalog)
    extra_field["topology_contracts"]["bipolar"]["unexpected"] = True
    with pytest.raises(BackendError) as raised:
        validate_parametric_catalog_asset(extra_field)
    assert raised.value.code == "LCC_ASSET_MISMATCH"

    unknown_top_level = copy.deepcopy(catalog)
    unknown_top_level["unexpected"] = True
    with pytest.raises(BackendError) as raised:
        validate_parametric_catalog_asset(unknown_top_level)
    assert raised.value.code == "LCC_ASSET_MISMATCH"

    swapped = copy.deepcopy(catalog)
    swapped["topology_contracts"]["monopolar"]["blueprint"] = "lcc_bipole_parametric_v1"
    with pytest.raises(BackendError) as raised:
        validate_parametric_catalog_asset(swapped)
    assert raised.value.code == "LCC_ASSET_MISMATCH"


def test_parametric_provenance_loader_rejects_schema_hash_and_machine_binding_drift():
    catalog = load_parametric_catalog()
    provenance = load_parametric_provenance()

    unknown = copy.deepcopy(provenance)
    unknown["unexpected"] = True
    with pytest.raises(BackendError) as raised:
        validate_parametric_provenance_asset(unknown, catalog)
    assert raised.value.code == "LCC_ASSET_MISMATCH"

    changed_machine = copy.deepcopy(provenance)
    changed_machine["entries"]["bipole_return_contract"]["machine_contract"]["required"] = []
    changed_catalog = copy.deepcopy(catalog)
    changed_catalog["provenance_sha256"] = hashlib.sha256(
        canonical_json(changed_machine)
    ).hexdigest()
    with pytest.raises(BackendError) as raised:
        validate_parametric_provenance_asset(changed_machine, changed_catalog)
    assert raised.value.code == "LCC_ASSET_MISMATCH"


@pytest.mark.parametrize("entry,mutate", [
    ("positive_finite", lambda machine: machine.update({"value": -1.0})),
    ("dimensional_identity", lambda machine: machine.update({"formula": "rated_power_mw"})),
    ("unit_conversions", lambda machine: machine["parameters"]["smoothing_reactor_mh"]["multipliers"].update({"H": 1.0})),
])
def test_parametric_provenance_rejects_rehashed_core_machine_contract_drift(entry, mutate):
    catalog = load_parametric_catalog()
    provenance = load_parametric_provenance()
    mutate(provenance["entries"][entry]["machine_contract"])
    catalog["provenance_sha256"] = hashlib.sha256(canonical_json(provenance)).hexdigest()

    with pytest.raises(BackendError) as raised:
        validate_parametric_provenance_asset(provenance, catalog)
    assert raised.value.code == "LCC_ASSET_MISMATCH"


def test_parametric_provenance_distinguishes_invariants_from_legacy_defaults():
    catalog = load_parametric_catalog()
    provenance = load_parametric_provenance()
    entries = provenance["entries"]

    assert catalog["provenance_identity"] == provenance["identity"]
    assert entries["positive_finite"]["classification"] == "physical_invariant"
    assert entries["angle_domain_deg"]["classification"] == "basic_domain"
    assert entries["legacy_catalog_defaults"]["classification"] == "legacy_catalog_default"
    assert entries["floating_point_comparison"]["classification"] == "implementation_policy"
    assert "do not establish allowable ranges" in entries["legacy_catalog_defaults"]["limitation"]


def test_return_asset_allowlist_matches_packaged_bipole_contract():
    catalog = load_parametric_catalog()
    provenance = load_parametric_provenance()
    bipole = load_parametric_blueprint("lcc_bipole_parametric_v1")
    allowed = catalog["return_asset_requirements"]["bipolar"]["allowed"]

    assert allowed == provenance["entries"]["bipole_return_contract"]["machine_contract"]["allowed"]
    assert set(allowed) <= set(bipole["required_assets"])


def _derived(value=1000.0):
    return DerivedParameterReport(
        parameters=(
            DerivedParameter(
                name="rated_power_mw", value=value, source="user",
                formula="request.ratings.rated_power_mw", units="MW",
                asset="lcc_parametric_provenance_v1:positive_finite",
            ),
            DerivedParameter(
                name="min_firing_angle_deg", value=15.0, source="user",
                formula="user value in catalog units (deg)", units="deg",
                asset="lcc_parametric_provenance_v1:angle_domain_deg",
            ),
        )
    )


def test_parametric_topology_planner_is_deterministic_explicit_and_fail_closed():
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    first = create_parametric_topology_plan(blueprint, _derived())
    second = create_parametric_topology_plan(blueprint, _derived())

    assert first == second
    assert first["executable"] is False
    assert first["unresolved_bindings"]
    assert {item["parameter"] for item in first["unresolved_bindings"]} == {
        "rated_power_mw", "min_firing_angle_deg"
    }
    assert all(item["reason"] == "template_parameter_binding_unreviewed" for item in first["unresolved_bindings"])
    assert first["role_parameters"]["rectifier_positive_pole"]["rated_power_mw"] == {
        "value": 1000.0,
        "units": "MW",
        "logical_parameter": "rated_power_mw",
        "template_parameter": None,
    }
    assert first["plan_hash"] != create_parametric_topology_plan(blueprint, _derived(1200.0))["plan_hash"]


def test_parametric_topology_planner_maps_the_complete_derived_report_without_authorizing_writes():
    request = ParametricLccRequest(
        topology="bipolar",
        ratings=LccRatings(1200.0, 500.0, 2.4, 500.0, 50.0, 3.0, 2.5),
        engineering_overrides={
            "smoothing_reactor_mh": 120.0,
            "filter_capacitance_uf": 60.0,
            "min_firing_angle_deg": 5.0,
            "max_firing_angle_deg": 45.0,
        },
        return_path_assets=("neutral_bus",),
    )
    report = derive_lcc_parameters(request)
    plan = create_parametric_topology_plan(
        load_parametric_blueprint("lcc_bipole_parametric_v1"), report
    )

    assert plan["executable"] is False
    unresolved = {item["parameter"] for item in plan["unresolved_bindings"]}
    assert unresolved < {item.name for item in report.parameters}
    assert "frequency_hz" not in unresolved


def test_reviewed_catalog_bindings_are_executable_and_hash_bound():
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    catalog = copy.deepcopy(load_parametric_catalog())
    catalog["template_bindings"] = [
        {
            "logical_parameter": "rated_power_mw",
            "role": "rectifier_positive_pole",
            "selector": "/project/definitions/Definition[@name='RectPole']/power",
            "attribute": "value",
            "units": "MW",
            "binding_status": "reviewed",
        },
        {
            "logical_parameter": "min_firing_angle_deg",
            "role": "inverter_positive_pole",
            "selector": "/project/definitions/Definition[@name='InverterPole']/angle",
            "attribute": "value",
            "units": "deg",
            "binding_status": "reviewed",
        },
    ]
    first = create_parametric_topology_plan(blueprint, _derived(), catalog)
    assert first["executable"] is True
    assert {item["derived_value"] for item in first["bindings"]} == {1000.0, 15.0}
    assert all(item["expected_match_count"] == 1 for item in first["bindings"])

    changed_selector = copy.deepcopy(catalog)
    changed_selector["template_bindings"][0]["selector"] += "/@x"
    assert first["plan_hash"] != create_parametric_topology_plan(blueprint, _derived(), changed_selector)["plan_hash"]
    assert first["plan_hash"] != create_parametric_topology_plan(blueprint, _derived(1100.0), catalog)["plan_hash"]


def _audit_roles(blueprint):
    components = {
        item.get("template_role"): item
        for item in blueprint["components"]
        if item["kind"] == "template_role"
    }
    return {
        role: {
            "definition": (
                "master:ground"
                if role == "earth_electrode"
                else "Fixture:" + ("RectPole" if role.startswith("rectifier") else "InverterPole")
            ),
            **(
                {"discriminator": components[role]["discriminator"]}
                if components[role]["discriminator"] is not None
                else {}
            ),
            "validated_contract": (
                "lcc_parametric_catalog_v1:earth_electrode"
                if role == "earth_electrode"
                else "lcc_parametric_catalog_v1:" + ("RectPole" if role.startswith("rectifier") else "InverterPole")
            ),
        }
        for role in blueprint["template_roles"]
    }


def _template_with_evidence(tmp_path, blueprint, fixture="bipole_template.pscx", *, wires=True, outputs=True):
    tree = ET.parse(FIXTURES / fixture)
    main = next(
        item for item in tree.getroot().iter()
        if item.tag.rsplit("}", 1)[-1].casefold() == "definition"
        and item.attrib.get("name") == "Main"
    )
    schematic = next(
        item for item in main.iter()
        if item.tag.rsplit("}", 1)[-1].casefold() == "schematic"
    )
    if wires:
        for index, net in enumerate(blueprint["nets"]):
            wire = ET.SubElement(
                schematic, "Wire",
                {"classid": "WireOrthogonal", "name": net["logical_id"], "id": str(8000 + index), "x": str(index * 20), "y": "500"},
            )
            ET.SubElement(wire, "vertex", {"x": "0", "y": "0"})
            ET.SubElement(wire, "vertex", {"x": "10", "y": "0"})
    if outputs:
        for index, output in enumerate(blueprint["outputs"]):
            pgb = ET.SubElement(
                schematic, "User",
                {"classid": "UserCmp", "defn": "master:pgb", "id": str(9000 + index), "x": str(index * 20), "y": "600"},
            )
            params = ET.SubElement(pgb, "paramlist")
            ET.SubElement(params, "param", {"name": "Name", "value": output["name"]})
            ET.SubElement(params, "param", {"name": "Units", "value": output["units"]})
    path = tmp_path / f"{fixture}-{int(wires)}-{int(outputs)}.pscx"
    tree.write(path, encoding="utf-8")
    return path


def _connected_bipole_template(tmp_path, blueprint):
    source = _template_with_evidence(tmp_path, blueprint, wires=False, outputs=True)
    tree = ET.parse(source)
    root = tree.getroot()
    definitions = {
        item.attrib.get("name"): item
        for item in root.iter()
        if item.tag.rsplit("}", 1)[-1].casefold() == "definition"
    }
    for name in ("RectPole", "InverterPole"):
        for port in definitions[name].iter("port"):
            if port.attrib.get("name") == "DCP1":
                port.attrib.update({"x": "0", "y": "-90"})
            elif port.attrib.get("name") == "DCP2":
                port.attrib.update({"x": "0", "y": "90"})
    schematic = next(item for item in definitions["Main"].iter() if item.tag == "schematic")
    neutral = ET.SubElement(schematic, "User", {"logical_id": "neutral_bus", "x": "400", "y": "300", "orient": "0"})
    for name, x, y in (("rp1", -10, -110), ("ip1", 10, -110), ("rp2", -10, 90), ("ip2", 10, 90), ("earth", 0, 0), ("metallic", 0, 20)):
        ET.SubElement(neutral, "port", {"name": name, "x": str(x), "y": str(y)})
    terminal = ET.SubElement(schematic, "User", {"logical_id": "metallic_return_terminal", "x": "500", "y": "320", "orient": "0"})
    ET.SubElement(terminal, "port", {"name": "remote", "x": "0", "y": "0"})

    def add_wire(name, points):
        wire = ET.SubElement(schematic, "Wire", {"classid": "WireOrthogonal", "name": name, "x": "0", "y": "0"})
        for x, y in points:
            ET.SubElement(wire, "vertex", {"x": str(x), "y": str(y)})

    add_wire("dc_positive", [(100, 10), (700, 10)])
    add_wire("dc_negative", [(100, 210), (700, 210)])
    add_wire("neutral_bus", [(100, 190), (700, 190)])
    add_wire("neutral_bus", [(50, 190), (100, 190)])
    add_wire("neutral_bus", [(50, 190), (50, 390)])
    add_wire("neutral_bus", [(50, 390), (100, 390)])
    add_wire("neutral_bus", [(100, 390), (700, 390)])
    add_wire("earth_return", [(400, 300), (750, 300), (750, 200), (400, 200)])
    add_wire("metallic_return", [(400, 320), (500, 320)])
    tree.write(source, encoding="utf-8")
    return source


def test_parametric_validator_rejects_decorative_disconnected_named_wires(tmp_path):
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    source = _template_with_evidence(tmp_path, blueprint)
    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(
            blueprint, audit_lcc_template(source), source
        )
    assert raised.value.code == "LCC_PROJECT_INVALID"


def test_parametric_validator_accepts_connected_endpoint_graph_and_output_channels(tmp_path):
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    source = _connected_bipole_template(tmp_path, blueprint)
    result = validate_parametric_topology_contract(blueprint, audit_lcc_template(source), source)
    assert result == {
        "valid": True,
        "template_audit_compatible": True,
        "topology_execution_valid": True,
        "blueprint": "lcc_bipole_parametric_v1",
        "template_roles": sorted(blueprint["template_roles"]),
        "structural_nets": sorted(item["logical_id"] for item in blueprint["nets"]),
        "audited_output_channels": sorted(item["name"] for item in blueprint["outputs"]),
    }


def test_parametric_validator_rejects_disconnected_decorative_segment_on_real_net(tmp_path):
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    source = _connected_bipole_template(tmp_path, blueprint)
    tree = ET.parse(source)
    schematic = next(
        item for item in tree.getroot().iter()
        if item.tag == "schematic" and any(child.attrib.get("logical_id") == "neutral_bus" for child in item)
    )
    decorative = ET.SubElement(schematic, "Wire", {"name": "dc_positive", "x": "0", "y": "0"})
    ET.SubElement(decorative, "vertex", {"x": "900", "y": "900"})
    ET.SubElement(decorative, "vertex", {"x": "910", "y": "900"})
    tree.write(source, encoding="utf-8")

    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(blueprint, audit_lcc_template(source), source)
    assert raised.value.code == "LCC_PROJECT_INVALID"


@pytest.mark.parametrize("wires,outputs", [(False, True), (True, False)])
def test_parametric_validator_rejects_wire_zero_or_pgb_zero(tmp_path, wires, outputs):
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    source = _template_with_evidence(tmp_path, blueprint, wires=wires, outputs=outputs)
    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(
            blueprint, audit_lcc_template(source), source
        )
    assert raised.value.code == "LCC_PROJECT_INVALID"


@pytest.mark.parametrize("extra_kind", ["wire", "pgb"])
def test_parametric_validator_rejects_extra_observed_net_or_output(tmp_path, extra_kind):
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    source = _template_with_evidence(tmp_path, blueprint)
    tree = ET.parse(source)
    schematic = next(
        item for item in tree.getroot().iter()
        if item.tag.rsplit("}", 1)[-1].casefold() == "schematic"
        and any(child.attrib.get("defn", "").endswith(":RectPole") for child in item)
    )
    if extra_kind == "wire":
        extra = ET.SubElement(schematic, "Wire", {"name": "extra_net"})
        ET.SubElement(extra, "vertex", {"x": "0", "y": "0"})
        ET.SubElement(extra, "vertex", {"x": "10", "y": "0"})
    else:
        extra = ET.SubElement(schematic, "User", {"defn": "master:pgb"})
        params = ET.SubElement(extra, "paramlist")
        ET.SubElement(params, "param", {"name": "Name", "value": "extra_output"})
        ET.SubElement(params, "param", {"name": "Units", "value": "pu"})
    tree.write(source, encoding="utf-8")

    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(
            blueprint, audit_lcc_template(source), source
        )
    assert raised.value.code == "LCC_PROJECT_INVALID"


def test_parametric_validator_binds_graph_evidence_to_the_audited_snapshot(tmp_path):
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    source = _template_with_evidence(tmp_path, blueprint)
    audit = audit_lcc_template(source)
    source.write_bytes(source.read_bytes() + b"\n")

    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(blueprint, audit, source)
    assert raised.value.code == "LCC_PROJECT_INVALID"


@pytest.mark.parametrize("field,item", [
    ("components", "neutral_bus"),
    ("nets", "earth_return"),
    ("nets", "metallic_return"),
    ("outputs", "VDCRp2"),
])
def test_parametric_validator_rejects_missing_bipole_evidence(field, item):
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    candidate = copy.deepcopy(blueprint)
    key = "name" if field == "outputs" else "logical_id"
    candidate[field] = [record for record in candidate[field] if record[key] != item]

    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(candidate, _audit_roles(blueprint), FIXTURES / "bipole_template.pscx")
    assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_parametric_validator_rejects_extra_template_role_or_net():
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    roles = _audit_roles(blueprint)
    roles["extra_pole"] = {"definition": "Fixture:RectPole"}
    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(blueprint, roles, FIXTURES / "bipole_template.pscx")
    assert raised.value.code == "LCC_PROJECT_INVALID"

    candidate = copy.deepcopy(blueprint)
    candidate["nets"].append(copy.deepcopy(candidate["nets"][0]) | {"logical_id": "extra_dc"})
    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(candidate, _audit_roles(blueprint), FIXTURES / "bipole_template.pscx")
    assert raised.value.code == "LCC_BLUEPRINT_INVALID"


def test_parametric_validator_requires_exact_audited_definition_not_just_claimed_contract():
    blueprint = load_parametric_blueprint("lcc_bipole_parametric_v1")
    roles = _audit_roles(blueprint)
    roles["rectifier_positive_pole"]["definition"] = "Fixture:WrongPole"

    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(blueprint, roles, FIXTURES / "bipole_template.pscx")
    assert raised.value.code == "LCC_PROJECT_INVALID"


@pytest.mark.parametrize("name,fixture", [
    ("lcc_monopole_parametric_v1", "monopole_template.pscx"),
    ("lcc_bipole_parametric_v1", "bipole_template.pscx"),
])
def test_parametric_validator_rejects_role_only_fixture_without_graph_evidence(name, fixture):
    blueprint = load_parametric_blueprint(name)
    audit = audit_lcc_template(FIXTURES / fixture)

    with pytest.raises(BackendError) as raised:
        validate_parametric_topology_contract(blueprint, audit, FIXTURES / fixture)
    assert raised.value.code == "LCC_PROJECT_INVALID"
    assert raised.value.details["template_audit_compatible"] is True
    assert raised.value.details["topology_execution_valid"] is False
