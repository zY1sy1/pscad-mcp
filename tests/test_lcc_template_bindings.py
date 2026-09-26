from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.assets import load_parametric_catalog
from pscad_mcp.hvdc.builders.lcc.template_audit import audit_lcc_parameter_bindings


FIXTURE = Path(__file__).parent / "fixtures" / "lcc_parametric" / "real_binding_template.pscx"


def test_real_template_bindings_are_reviewed_and_exact():
    report = audit_lcc_parameter_bindings(FIXTURE)
    assert report["compatible"] is True
    assert report["bindings"]
    for binding in report["bindings"]:
        assert set(("logical_parameter", "role", "selector", "attribute", "units", "binding_status")) <= set(binding)
        assert binding["binding_status"] == "reviewed"
        assert binding["selector"].startswith("/project/definitions/")


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda catalog: catalog["template_bindings"][0].pop("selector"), "binding_invalid"),
        (lambda catalog: catalog["template_bindings"].append(copy.deepcopy(catalog["template_bindings"][0])), "duplicate_selector"),
        (lambda catalog: catalog["template_bindings"][0].update(units="kV"), "unit_mismatch"),
        (lambda catalog: catalog["template_bindings"][0].update(selector="/project/definitions/Definition/schematic/User"), "binding_not_unique"),
    ],
)
def test_invalid_or_ambiguous_binding_fails_closed(tmp_path, mutate, reason):
    catalog = copy.deepcopy(load_parametric_catalog())
    mutate(catalog)
    with pytest.raises(BackendError) as raised:
        audit_lcc_parameter_bindings(FIXTURE, catalog=catalog)
    assert raised.value.code == "LCC_PARAMETER_BINDING_UNAVAILABLE"
    assert raised.value.details["reason"] == reason


def test_binding_catalog_is_json_serializable_and_deterministic():
    catalog = load_parametric_catalog()
    assert json.dumps(catalog["template_bindings"], sort_keys=True)
    selectors = [item["selector"] for item in catalog["template_bindings"]]
    assert len(selectors) == len(set(selectors))


def _substituted_frequency_template(tmp_path):
    tree = ET.parse(FIXTURE)
    root = tree.getroot()
    declaration = root.find("./definitions/Definition[@name='Main']/form/category[@name='Global Substitutions']/parameter[@name='Freq']")
    declaration.set("unit", "Hz")
    declaration.find("value").text = "50.0 Hz"
    for binding in load_parametric_catalog()["template_bindings"]:
        if binding["logical_parameter"] == "frequency_hz" and binding["attribute"] == "value":
            root.find("." + binding["selector"][len("/project"):]).set("value", "$(Freq)")
    path = tmp_path / "symbolic-frequency.pscx"
    tree.write(path, encoding="utf-8")
    return path


def test_frequency_substitution_uses_unique_declared_global_units(tmp_path):
    path = _substituted_frequency_template(tmp_path)
    report = audit_lcc_parameter_bindings(path)
    assert report["compatible"] is True
    assert all(b["observed_units"] == "Hz" for b in report["bindings"] if b["logical_parameter"] == "frequency_hz")


@pytest.mark.parametrize("change", ["missing", "duplicate", "conflicting_units", "expression"])
def test_ambiguous_or_untyped_frequency_substitution_is_not_inferred(tmp_path, change):
    path = _substituted_frequency_template(tmp_path)
    tree = ET.parse(path)
    category = tree.getroot().find("./definitions/Definition[@name='Main']/form/category[@name='Global Substitutions']")
    declaration = category.find("parameter[@name='Freq']")
    if change == "missing":
        declaration.set("name", "Other")
    elif change == "duplicate":
        category.append(copy.deepcopy(declaration))
    elif change == "conflicting_units":
        declaration.set("unit", "kV")
    else:
        for element in tree.getroot().iter("param"):
            if element.get("value") == "$(Freq)":
                element.set("value", "2 * $(Freq)")
    tree.write(path, encoding="utf-8")
    with pytest.raises(BackendError):
        audit_lcc_parameter_bindings(path)
