from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError

ASSET_ROOT = (
    Path(__file__).parents[1]
    / "pscad_mcp"
    / "assets"
    / "lcc"
    / "cigre_lcc_monopole_v1"
)


def _subject():
    return importlib.import_module("pscad_mcp.core.master_bindings")


def _minimal_binding(logical_name: str = "master:test") -> dict[str, object]:
    return {
        "logical_name": logical_name,
        "physical_definition": "resistor",
        "shape": {"kind": "direct"},
        "ports": [
            {
                "logical": "IN",
                "physical": "A",
                "kind": "electrical",
                "dimension": 1,
                "occurrence": 0,
            }
        ],
        "parameters": [
            {
                "logical": ["Resistance_ohm"],
                "physical": ["R"],
                "transform": {"kind": "identity"},
                "physical_contracts": {
                    "R": {"type": "Real", "unit": "ohm"}
                },
            }
        ],
        "fixed_parameters": [],
        "evidence_parameters": [],
    }


def _registry_payload(*bindings: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "test_master_bindings_v1",
        "pscad_version": "4.6.2",
        "bindings": list(bindings or (_minimal_binding(),)),
    }


def test_registry_rejects_unknown_top_level_fields():
    module = _subject()
    payload = _registry_payload()
    payload["unexpected"] = True

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(payload)

    assert failure.value.code == "MASTER_BINDING_MISSING"
    assert failure.value.details["unknown_fields"] == ["unexpected"]


def test_registry_rejects_duplicate_logical_names():
    module = _subject()
    payload = _registry_payload(_minimal_binding(), _minimal_binding())

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(payload)

    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"
    assert failure.value.details["logical_name"] == "master:test"


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        (lambda binding: binding["ports"][0].update(dimension=0), "dimension"),
        (lambda binding: binding["ports"][0].update(occurrence=-1), "occurrence"),
        (lambda binding: binding["shape"].update(kind="unknown"), "shape.kind"),
        (
            lambda binding: binding["parameters"][0]["transform"].update(
                kind="unknown"
            ),
            "transform.kind",
        ),
    ],
)
def test_registry_rejects_invalid_port_and_transform_contracts(mutation, field):
    module = _subject()
    binding = _minimal_binding()
    mutation(binding)

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(_registry_payload(binding))

    assert failure.value.code == "MASTER_BINDING_MISSING"
    assert failure.value.details["field"] == field


def test_packaged_registry_contains_exact_fixed_catalog_bindings():
    module = _subject()
    payload = json.loads(
        (ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(
            encoding="utf-8"
        )
    )

    registry = module.parse_master_binding_registry(payload)

    assert set(registry.by_logical_name) == {
        "master:three_phase_source",
        "master:converter_transformer",
        "master:ac_filter_branch",
        "master:smoothing_reactor",
        "master:dc_line_section",
        "master:ac_meter",
        "master:dc_meter",
        "master:ground",
    }
    assert (
        registry.by_logical_name["master:converter_transformer"].physical_definition
        == "xfmr-3p2w"
    )
    assert (
        registry.by_logical_name["master:dc_line_section"].physical_definition
        == "resistor"
    )
    assert (
        registry.by_logical_name["master:dc_meter"].physical_definition
        == "multimeter"
    )


def test_registry_hash_is_stable_for_key_order():
    module = _subject()
    payload = _registry_payload()
    reordered = {
        "bindings": payload["bindings"],
        "pscad_version": payload["pscad_version"],
        "name": payload["name"],
        "schema_version": payload["schema_version"],
    }

    first = module.parse_master_binding_registry(payload)
    second = module.parse_master_binding_registry(reordered)

    assert first.sha256 == second.sha256
