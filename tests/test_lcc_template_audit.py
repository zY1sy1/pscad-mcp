import copy
import hashlib
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import load_parametric_catalog
from pscad_mcp.hvdc.builders.lcc.template_audit import audit_lcc_template


FIXTURES = Path(__file__).parent / "fixtures" / "lcc_parametric"


def test_audit_default_catalog_validates_real_bipole_roles_without_mutation():
    source = FIXTURES / "bipole_template.pscx"
    before = source.read_bytes()
    report = audit_lcc_template(source)

    assert report.compatible is True
    assert set(report.roles) == {
        "rectifier_positive_pole", "rectifier_negative_pole",
        "inverter_positive_pole", "inverter_negative_pole", "earth_electrode",
    }
    assert report.roles["rectifier_positive_pole"] == {
        "definition": "FixtureBipole:RectPole", "instance_id": "2001",
        "location": [100, 100], "discriminator": {"name": "Des", "value": "RP1"},
        "validated_contract": "lcc_parametric_catalog_v1:RectPole",
    }
    assert report.roles["inverter_negative_pole"]["discriminator"]["value"] == "IP2"
    assert report.roles["earth_electrode"]["evidence"]["validated_contract"] == "lcc_parametric_catalog_v1:earth_electrode"
    assert report.fingerprint == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before


def test_audit_accepts_one_strictly_validated_monopole_pair():
    report = audit_lcc_template(FIXTURES / "monopole_template.pscx")
    assert report.compatible is True
    assert report.roles["rectifier_valve_group"]["definition"] == "FixtureMonopole:RectPole"
    assert report.roles["inverter_valve_group"]["definition"] == "FixtureMonopole:InverterPole"
    assert report.roles["rectifier_valve_group"]["validated_contract"].endswith(":RectPole")


def test_audit_rejects_duplicate_bipole_discriminator():
    with pytest.raises(BackendError) as raised:
        audit_lcc_template(FIXTURES / "ambiguous_template.pscx")
    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert raised.value.details["conflict_reasons"]["pole_instances"] == "duplicate_or_missing_bipole_discriminator"
    assert "RP1" not in str(raised.value.details)


def test_audit_does_not_authorize_bare_local_names_or_wrong_namespace():
    report = audit_lcc_template(FIXTURES / "incompatible_template.pscx")
    assert report.compatible is False
    assert "rectifier_pole_definition" in report.missing_contracts
    assert "inverter_pole_definition" in report.missing_contracts
    assert not any(name.startswith("rectifier_") for name in report.roles)


def test_audit_rejects_catalog_without_authoritative_contracts():
    catalog = copy.deepcopy(load_parametric_catalog())
    catalog.pop("template_role_contracts", None)
    with pytest.raises(BackendError) as raised:
        audit_lcc_template(FIXTURES / "bipole_template.pscx", catalog=catalog)
    assert raised.value.code == "LCC_ASSET_MISMATCH"
    assert raised.value.details == {"reason": "invalid_template_role_contracts"}


@pytest.mark.parametrize("mutate", [
    lambda c: c["template_role_contracts"].update(authoritative=False),
    lambda c: c["template_role_contracts"]["pole_definitions"]["rectifier"]["ports"]["AC"].update(dim=1),
    lambda c: c["template_role_contracts"]["earth_electrode"].update(anchor_parameter="Alias"),
])
def test_audit_strictly_rejects_modified_authoritative_contract(mutate):
    catalog = copy.deepcopy(load_parametric_catalog())
    mutate(catalog)
    with pytest.raises(BackendError) as raised:
        audit_lcc_template(FIXTURES / "bipole_template.pscx", catalog=catalog)
    assert raised.value.code == "LCC_ASSET_MISMATCH"
    assert raised.value.details == {"reason": "invalid_template_role_contracts"}


def test_audit_rejects_definition_with_wrong_port_or_internal_counts(tmp_path):
    payload = (FIXTURES / "monopole_template.pscx").read_text(encoding="utf-8")
    payload = payload.replace('name="AC" dim="3"', 'name="AC" dim="1"', 1)
    payload = payload.replace('<User defn="master:g6p200" />', '', 1)
    source = tmp_path / "invalid_contract.pscx"
    source.write_text(payload, encoding="utf-8")
    report = audit_lcc_template(source)
    assert report.compatible is False
    assert report.missing_contracts == ("rectifier_pole_definition",)


def test_audit_requires_exact_project_scoped_definition(tmp_path):
    payload = (FIXTURES / "monopole_template.pscx").read_text(encoding="utf-8")
    payload = payload.replace("FixtureMonopole:RectPole", "foreign:RectPole")
    source = tmp_path / "foreign_scope.pscx"
    source.write_text(payload, encoding="utf-8")
    report = audit_lcc_template(source)
    assert report.compatible is False
    assert "rectifier_valve_group" in report.missing_contracts


def test_audit_rejects_unknown_bipole_marker(tmp_path):
    payload = (FIXTURES / "bipole_template.pscx").read_text(encoding="utf-8")
    source = tmp_path / "unknown_marker.pscx"
    source.write_text(payload.replace('value="RP2"', 'value="RX"'), encoding="utf-8")
    report = audit_lcc_template(source)
    assert report.compatible is False
    assert report.missing_contracts == ("bipole_pole_discriminators",)


def test_electrode_exact_anchor_selects_nearest_exact_ground():
    report = audit_lcc_template(FIXTURES / "bipole_template.pscx")
    evidence = report.roles["earth_electrode"]["evidence"]
    assert evidence["anchor"] == {"definition": "master:ammeter", "instance_id": "3003", "location": [350, 200], "marker": {"name": "Name", "value": "Ielectrode"}}
    assert evidence["selected"] == {"definition": "master:ground", "instance_id": "3001", "location": [400, 200]}
    assert evidence["distance"] == 50.0


def test_audit_rejects_unsafe_xml_and_bounds_coordinate_evidence(tmp_path):
    unsafe = tmp_path / "unsafe.pscx"
    unsafe.write_text('<!DOCTYPE project><project name="x"/>', encoding="utf-8")
    with pytest.raises(BackendError) as raised:
        audit_lcc_template(unsafe)
    assert raised.value.details == {"reason": "forbidden_xml_declaration"}

    payload = (FIXTURES / "monopole_template.pscx").read_text(encoding="utf-8")
    huge = "bad-" + "x" * 10000
    source = tmp_path / "bad_coordinate.pscx"
    source.write_text(payload.replace('x="400"', f'x="{huge}"'), encoding="utf-8")
    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)
    assert raised.value.details["value_length"] == len(huge)
    assert len(raised.value.details["value_preview"]) <= 64


def test_audit_normalizes_open_errors(tmp_path, monkeypatch):
    source = tmp_path / "unreadable.pscx"
    source.write_text("<project/>", encoding="utf-8")
    catalog = load_parametric_catalog()
    def fail_open(*args, **kwargs):
        raise PermissionError("unbounded operating-system message")
    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source, catalog=catalog)
    assert raised.value.details == {"error_type": "PermissionError", "reason": "template_unreadable"}
