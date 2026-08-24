from __future__ import annotations

import copy
import json
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
