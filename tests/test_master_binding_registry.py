from __future__ import annotations

import hashlib
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


def _packaged_registry(module):
    payload = json.loads(
        (ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(
            encoding="utf-8"
        )
    )
    return module.parse_master_binding_registry(payload)


def _master_fixture_xml(
    *,
    duplicate_source: bool = False,
    source_a_model: str = "Natural",
    inductor_type: str = "Real",
) -> str:
    duplicate = (
        "<Definition name='source3'><svg><port model='Natural' name='A' "
        "x='0' y='0' dim='1' type='NonRemovable'/></svg></Definition>"
        if duplicate_source
        else ""
    )
    return f"""<?xml version='1.0'?>
<pslx>
  <Definition name='source3'>
    <form><category>
      <parameter name='Vm' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
      <parameter name='F' type='Real' unit='Hz' intent='Input'><value>50</value></parameter>
      <parameter name='Ph' type='Real' unit='deg' intent='Input'><value>0</value></parameter>
      <parameter name='View' type='Choice'><value>1</value><choice>0 = 3 phase</choice><choice>1 = single</choice></parameter>
    </category></form>
    <svg>
      <port model='{source_a_model}' name='A' x='36' y='-36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='B' x='36' y='0' dim='1' type='NonRemovable'/>
      <port model='Natural' name='C' x='36' y='36' dim='1' type='NonRemovable'/>
    </svg>
  </Definition>
  {duplicate}
  <Definition name='xfmr-3p2w'>
    <form><category>
      <parameter name='V1' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
      <parameter name='V2' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
      <parameter name='f' type='Real' unit='Hz' intent='Input'><value>50</value></parameter>
      <parameter name='YD1' type='Choice'><value>0</value><choice>0 = Y</choice><choice>1 = Delta</choice></parameter>
      <parameter name='YD2' type='Choice'><value>1</value><choice>0 = Y</choice><choice>1 = Delta</choice></parameter>
      <parameter name='Lead' type='Choice'><value>1</value><choice>1 = Lags</choice><choice>2 = Leads</choice></parameter>
      <parameter name='View' type='Choice'><value>1</value><choice>0 = phase</choice><choice>1 = single</choice><choice>2 = winding</choice></parameter>
    </category></form>
    <svg>
      <port model='Natural' name='A1' x='-72' y='-36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='B1' x='-72' y='0' dim='1' type='NonRemovable'/>
      <port model='Natural' name='C1' x='-72' y='36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='A2' x='72' y='-36' dim='1' type='NonRemovable'/>
      <port model='Natural' name='B2' x='72' y='0' dim='1' type='NonRemovable'/>
      <port model='Natural' name='C2' x='72' y='36' dim='1' type='NonRemovable'/>
    </svg>
  </Definition>
  <Definition name='cfilter'>
    <form><category>
      <parameter name='Q' type='Real' unit='MVA' intent='Input'><value>49</value></parameter>
      <parameter name='h' type='Real' unit='' intent='Input'><value>3</value></parameter>
      <parameter name='dentry' type='Choice'><value>1</value><choice>0 = RLC</choice><choice>1 = rated</choice></parameter>
      <parameter name='f0' type='Real' unit='Hz' intent='Input'><value>50</value></parameter>
      <parameter name='V' type='Real' unit='kV' intent='Input'><value>315</value></parameter>
    </category></form>
    <svg>
      <port model='Natural' name='A' x='0' y='-54' dim='0' type='NonRemovable'/>
      <port model='Natural' name='B' x='0' y='54' dim='0' type='NonRemovable'/>
      <port model='Natural' name='N' x='0' y='-36' dim='0' type='NonRemovable'/>
    </svg>
  </Definition>
  <Definition name='inductor'>
    <form><category><parameter name='L' type='{inductor_type}' unit='H' intent='Input'><value>0.1</value></parameter></category></form>
    <svg>
      <port model='Natural' name='A' x='0' y='0' dim='0' type='Removable'/>
      <port model='Natural' name='B' x='36' y='0' dim='0' type='Removable'/>
    </svg>
  </Definition>
  <Definition name='resistor'>
    <form><category><parameter name='R' type='Real' unit='ohm' intent='Input'><value>1</value></parameter></category></form>
    <svg>
      <port model='Natural' name='A' x='0' y='0' dim='0' type='Removable'/>
      <port model='Natural' name='B' x='36' y='0' dim='0' type='Removable'/>
    </svg>
  </Definition>
  <Definition name='multimeter'>
    <form><category>
      <parameter name='MeasV' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='MeasI' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='MeasP' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='MeasQ' type='Choice'><value>0</value><choice>0 = No</choice><choice>1 = Yes</choice></parameter>
      <parameter name='Freq' type='Real' unit='Hz' intent='Input'><value>50</value></parameter>
      <parameter name='BaseV' type='Real' unit='kV' intent='Input'><value>230</value></parameter>
    </category></form>
    <svg>
      <port model='Natural' name='A' x='-18' y='0' dim='0' type='Removable'>MeasV+MeasP+MeasQ==0</port>
      <port model='Natural' name='A' x='-18' y='0' dim='0' type='NonRemovable'>MeasV+MeasP+MeasQ!=0</port>
      <port model='Natural' name='B' x='18' y='0' dim='0' type='NonRemovable'>MeasP+MeasQ+MeasI==0</port>
      <port model='Natural' name='B' x='18' y='0' dim='0' type='Removable'>MeasP+MeasQ+MeasI!=0</port>
    </svg>
  </Definition>
  <Definition name='ground'>
    <svg><port model='Natural' name='A' x='0' y='0' dim='1' type='Ground'/></svg>
  </Definition>
</pslx>
"""


def _write_master_fixture(tmp_path: Path, **options) -> Path:
    path = tmp_path / "master.pslx"
    path.write_text(_master_fixture_xml(**options), encoding="utf-8")
    return path


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
    "cases",
    [
        [
            {"logical": ["A"], "physical": [0]},
            {"logical": ["A"], "physical": [1]},
        ],
        [
            {"logical": ["A"], "physical": [0]},
            {"logical": ["B"], "physical": [0]},
        ],
        [
            {"logical": [1], "physical": [0]},
            {"logical": ["1"], "physical": [1]},
        ],
        [
            {"logical": ["A"], "physical": [1]},
            {"logical": ["B"], "physical": ["1"]},
        ],
    ],
)
def test_registry_rejects_ambiguous_lookup_bundles(cases):
    module = _subject()
    binding = _minimal_binding()
    binding["parameters"][0]["transform"] = {
        "kind": "lookup_bundle",
        "cases": cases,
    }

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(_registry_payload(binding))

    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"
    assert failure.value.details["field"] == "transform.cases"


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


def test_registry_rejects_non_finite_transform_constants():
    module = _subject()
    binding = _minimal_binding()
    binding["parameters"][0]["transform"] = {
        "kind": "scale",
        "factor": float("nan"),
    }

    with pytest.raises(BackendError) as failure:
        module.parse_master_binding_registry(_registry_payload(binding))

    assert failure.value.code == "MASTER_BINDING_MISSING"
    assert failure.value.details["field"] == "transform.factor"


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


def test_filter_expansion_offsets_are_pscad_grid_aligned():
    module = _subject()
    registry = _packaged_registry(module)
    shape = registry.by_logical_name["master:ac_filter_branch"].shape

    assert all(
        coordinate % 18 == 0
        for instance in shape["instances"]
        for coordinate in instance["offset"]
    )
    assert all(
        coordinate % 18 == 0
        for coordinate in shape["neutral"]["ground_offset"]
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


def test_audit_resolves_all_eight_bindings_and_preserves_source_hash(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    master = _write_master_fixture(tmp_path)

    audited = module.audit_master_bindings(master, registry)

    assert audited.master_sha256 == hashlib.sha256(master.read_bytes()).hexdigest()
    assert set(audited.definitions) == set(registry.by_logical_name)
    assert audited.definitions["master:dc_line_section"]["physical_definition"] == "resistor"
    selected = audited.definitions["master:ac_meter"]["selected_ports"]
    assert selected["A"]["occurrence"] == 1
    assert selected["A"]["raw_dimension"] == 0
    assert selected["A"]["dimension"] == 1
    assert selected["A"]["kind"] == "electrical"


def test_audit_rejects_duplicate_physical_definitions(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    master = _write_master_fixture(tmp_path, duplicate_source=True)

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(master, registry)

    assert failure.value.code == "MASTER_BINDING_AMBIGUOUS"
    assert failure.value.details["physical_definition"] == "source3"


def test_audit_rejects_wrong_port_kind_before_resolution(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    master = _write_master_fixture(tmp_path, source_a_model="Transfer")

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(master, registry)

    assert failure.value.code == "MASTER_PORT_MISMATCH"
    assert failure.value.details["logical_port"] == "A"
    assert failure.value.details["observed_kind"] == "data"


def test_audit_rejects_wrong_parameter_type(tmp_path):
    module = _subject()
    registry = _packaged_registry(module)
    master = _write_master_fixture(tmp_path, inductor_type="Text")

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(master, registry)

    assert failure.value.code == "MASTER_PARAMETER_MISMATCH"
    assert failure.value.details["physical_parameter"] == "L"
    assert failure.value.details["expected_type"] == "Real"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("ground_definition", "missing_ground", "MASTER_BINDING_MISSING"),
        ("ground_port", "MISSING", "MASTER_BINDING_MISSING"),
        ("ground_occurrence", 99, "MASTER_BINDING_AMBIGUOUS"),
    ],
)
def test_audit_rejects_invalid_filter_ground_contract(
    tmp_path,
    field,
    value,
    code,
):
    module = _subject()
    payload = json.loads(
        (ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(
            encoding="utf-8"
        )
    )
    filter_binding = next(
        item
        for item in payload["bindings"]
        if item["logical_name"] == "master:ac_filter_branch"
    )
    filter_binding["shape"]["neutral"][field] = value
    registry = module.parse_master_binding_registry(payload)

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(
            _write_master_fixture(tmp_path),
            registry,
        )

    assert failure.value.code == code
    assert failure.value.details["ground_definition"] == filter_binding["shape"][
        "neutral"
    ]["ground_definition"]


@pytest.mark.parametrize(
    ("logical_name", "physical_parameter", "invalid_value"),
    [
        ("master:three_phase_source", "View", 999),
        ("master:converter_transformer", "YD2", 999),
    ],
)
def test_audit_rejects_fixed_or_lookup_values_outside_live_contract(
    tmp_path,
    logical_name,
    physical_parameter,
    invalid_value,
):
    module = _subject()
    payload = json.loads(
        (ASSET_ROOT / "master-bindings-pscad-4.6.2.json").read_text(
            encoding="utf-8"
        )
    )
    binding = next(
        item for item in payload["bindings"] if item["logical_name"] == logical_name
    )
    fixed = next(
        (
            item
            for item in binding["fixed_parameters"]
            if item["physical"] == physical_parameter
        ),
        None,
    )
    if fixed is not None:
        fixed["value"] = invalid_value
    else:
        parameter = next(
            item
            for item in binding["parameters"]
            if physical_parameter in item["physical"]
        )
        index = parameter["physical"].index(physical_parameter)
        parameter["transform"]["cases"][0]["physical"][index] = invalid_value
    registry = module.parse_master_binding_registry(payload)

    with pytest.raises(BackendError) as failure:
        module.audit_master_bindings(
            _write_master_fixture(tmp_path),
            registry,
        )

    assert failure.value.code == "MASTER_PARAMETER_MISMATCH"
    assert failure.value.details["physical_parameter"] == physical_parameter


def test_resolver_round_trips_reactor_transform(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    resolved = audited.resolve_component(
        "master:smoothing_reactor", {"Inductance_mH": 100.0}
    )

    assert resolved.physical_definition == "inductor"
    assert resolved.physical_parameters == {"L": pytest.approx(0.1)}
    assert resolved.logical_parameters({"L": 0.1}) == {
        "Inductance_mH": pytest.approx(100.0)
    }


def test_resolver_maps_transformer_lookup_and_fixed_voltage_base(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    resolved = audited.resolve_component(
        "master:converter_transformer",
        {"Ratio": 1.0, "Connection": "Y-delta", "PhaseShift_deg": 30.0},
    )

    assert resolved.physical_parameters == {
        "V1": 230.0,
        "V2": 230.0,
        "f": 50.0,
        "View": 0,
        "YD1": 0,
        "YD2": 1,
        "Lead": 1,
    }
    assert resolved.logical_parameters(
        {"V2": 230.0, "YD1": 0, "YD2": 1, "Lead": 1}
    ) == {
        "Ratio": 1.0,
        "Connection": "Y-delta",
        "PhaseShift_deg": 30.0,
    }


def test_resolver_rejects_unreviewed_transformer_tuple(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    with pytest.raises(BackendError) as failure:
        audited.resolve_component(
            "master:converter_transformer",
            {"Ratio": 1.0, "Connection": "Y-delta", "PhaseShift_deg": -30.0},
        )

    assert failure.value.code == "MASTER_TRANSFORM_UNSUPPORTED"


def test_filter_resolution_is_per_phase_and_uses_harmonic_order(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    resolved = audited.resolve_component(
        "master:ac_filter_branch",
        {"Branch_MVAR": 50.0, "Tuning_Hz": 300.0},
    )

    assert resolved.instances == ("A", "B", "C")
    assert resolved.physical_parameters["Q"] == pytest.approx(50.0 / 3.0)
    assert resolved.physical_parameters["f0"] == 50.0
    assert resolved.physical_parameters["h"] == 6.0
    assert resolved.logical_parameters({"Q": 50.0 / 3.0, "h": 6.0}) == {
        "Branch_MVAR": pytest.approx(50.0),
        "Tuning_Hz": pytest.approx(300.0),
    }


def test_line_length_is_explicit_evidence_not_a_physical_parameter(tmp_path):
    module = _subject()
    audited = module.audit_master_bindings(
        _write_master_fixture(tmp_path), _packaged_registry(module)
    )

    resolved = audited.resolve_component(
        "master:dc_line_section",
        {"Length_km": 300.0, "Resistance_ohm": 10.0},
    )

    assert resolved.physical_definition == "resistor"
    assert resolved.physical_parameters == {"R": 10.0}
    assert resolved.evidence_parameters == {"Length_km": 300.0}
    assert resolved.logical_parameters({"R": 10.0}) == {
        "Resistance_ohm": 10.0,
        "Length_km": 300.0,
    }
