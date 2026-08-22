from pathlib import Path
from textwrap import dedent

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.lcc.template_audit import audit_lcc_template


def test_audit_reports_exact_roles_without_mutation(tmp_path):
    source = tmp_path / "template.pscx"
    original = '<project><component definition="cigre_lcc_v1:LCC12PulseBridge"/><component definition="master:ground" x="0" y="0"/></project>'
    source.write_text(original, encoding="utf-8")
    report = audit_lcc_template(source)
    assert report.compatible is True
    assert report.roles["rectifier_valve_group"]["definition"] == "cigre_lcc_v1:LCC12PulseBridge"
    assert source.read_text(encoding="utf-8") == original


def test_audit_accepts_real_template_roles_and_electrode_evidence(tmp_path):
    source = tmp_path / "real_template.pscx"
    source.write_text(
        dedent(
            """\
            <?xml version="1.0" encoding="utf-8"?>
            <pscx>
              <Definition name="Main">
                <Canvas name="Main">
                  <User classid="UserCmp" defn="HVDC_Bipolar_1000MW_500kV:RectPole" x="612" y="594" />
                  <User classid="UserCmp" defn="HVDC_Bipolar_1000MW_500kV:InverterPole" x="1152" y="594" />
                  <User classid="UserCmp" defn="master:ground" x="738" y="432" />
                  <User classid="UserCmp" defn="master:ground" x="1026" y="432" />
                  <User classid="UserCmp" defn="master:ammeter" x="666" y="432">
                    <paramlist>
                      <param name="Name" value="Ielectrode" />
                    </paramlist>
                  </User>
                </Canvas>
              </Definition>
            </pscx>
            """
        ),
        encoding="utf-8",
    )

    report = audit_lcc_template(source)

    assert report.compatible is True
    assert report.roles["rectifier_valve_group"]["definition"] == "HVDC_Bipolar_1000MW_500kV:RectPole"
    assert report.roles["inverter_valve_group"]["definition"] == "HVDC_Bipolar_1000MW_500kV:InverterPole"
    assert report.roles["earth_electrode"]["definition"] == "master:ground"
    assert report.roles["earth_electrode"]["evidence"]["anchor"]["marker"] == {
        "name": "Name",
        "value": "Ielectrode",
    }
    assert report.roles["earth_electrode"]["evidence"]["selected"]["location"] == [738, 432]


@pytest.mark.parametrize(
    "ambiguous_components, expected_role",
    [
        (
            '<component definition="model:RectPole"/><component definition="model:RectPole"/>',
            "rectifier_valve_group",
        ),
        (
            '<component definition="model:InverterPole"/><component definition="model:InverterPole"/>',
            "inverter_valve_group",
        ),
        (
            '<component definition="model:LCC12PulseBridge"/><component definition="model:LCC12PulseBridge"/>',
            "rectifier_valve_group",
        ),
    ],
)
def test_audit_rejects_duplicate_exact_role_instances(tmp_path, ambiguous_components, expected_role):
    source = tmp_path / "ambiguous_role.pscx"
    source.write_text(
        (
            "<project>"
            f"{ambiguous_components}"
            '<component definition="model:RectPole"/>'
            '<component definition="model:InverterPole"/>'
            '<component definition="master:ground" x="0" y="0"/>'
            "</project>"
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert raised.value.details["compatible"] is False
    assert expected_role in raised.value.details["conflicts"]


def test_audit_rejects_non_master_ammeter_as_electrode_anchor(tmp_path):
    source = tmp_path / "wrong_anchor.pscx"
    source.write_text(
        dedent(
            """\
            <project>
              <component definition="model:LCC12PulseBridge" />
              <component definition="master:ground" x="0" y="0" />
              <component definition="master:ground" x="100" y="0" />
              <component definition="custom:ammeter" x="0" y="0">
                <param name="Name" value="Ielectrode" />
              </component>
            </project>
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert "earth_electrode" in raised.value.details["conflicts"]


@pytest.mark.parametrize(
    "grounds, anchors",
    [
        (
            '<component definition="master:ground" x="0" y="0"/>'
            '<component definition="master:ground" x="100" y="0"/>',
            '<component definition="master:ammeter" x="0" y="0"><param name="Name" value="Ielectrode"/></component>'
            '<component definition="master:ammeter" x="100" y="0"><param name="Name" value="Ielectrode"/></component>',
        ),
        (
            '<component definition="master:ground" x="0" y="0"/>'
            '<component definition="master:ground" x="100" y="0"/>',
            "",
        ),
        (
            '<component definition="master:ground" x="0" y="0"/>'
            '<component definition="master:ground" x="100" y="0"/>',
            '<component definition="master:ammeter" x="50" y="0"><param name="Name" value="Ielectrode"/></component>',
        ),
    ],
)
def test_audit_rejects_ambiguous_electrode_evidence(tmp_path, grounds, anchors):
    source = tmp_path / "ambiguous_electrode.pscx"
    source.write_text(
        "<project>"
        '<component definition="model:LCC12PulseBridge"/>'
        f"{grounds}{anchors}"
        "</project>",
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert raised.value.details["compatible"] is False
    assert "earth_electrode" in raised.value.details["conflicts"]


def test_audit_accepts_single_ground_without_anchor_with_explicit_evidence(tmp_path):
    source = tmp_path / "single_ground.pscx"
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground" x="10" y="20"/></project>',
        encoding="utf-8",
    )

    report = audit_lcc_template(source)

    assert report.compatible is True
    evidence = report.roles["earth_electrode"]["evidence"]
    assert evidence["selection_reason"] == "single_exact_ground_without_anchor"
    assert evidence["selected"]["location"] == [10, 20]


def test_audit_rejects_template_larger_than_32_mib_before_parsing(tmp_path):
    source = tmp_path / "oversized.pscx"
    with source.open("wb") as stream:
        stream.truncate(32 * 1024 * 1024 + 1)

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details == {
        "actual_bytes": 32 * 1024 * 1024 + 1,
        "max_bytes": 32 * 1024 * 1024,
        "reason": "template_too_large",
    }


@pytest.mark.parametrize(
    "declaration",
    [
        '<!DOCTYPE project [<!ENTITY bridge "model:LCC12PulseBridge">]>',
        '<!ENTITY bridge "model:LCC12PulseBridge">',
    ],
)
def test_audit_rejects_dtd_and_entity_declarations_before_xml_parsing(tmp_path, declaration):
    source = tmp_path / "unsafe.pscx"
    source.write_text(
        declaration
        + '<project><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground"/></project>',
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details == {"reason": "forbidden_xml_declaration"}


def test_audit_wraps_invalid_coordinate_with_bounded_details(tmp_path):
    source = tmp_path / "invalid_coordinate.pscx"
    malicious_coordinate = "not-an-integer-" + ("x" * 10_000)
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        f'<component definition="master:ground" x="{malicious_coordinate}" y="0"/></project>',
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details["reason"] == "invalid_component_coordinate"
    assert raised.value.details["field"] == "x"
    assert raised.value.details["value_length"] == len(malicious_coordinate)
    assert len(raised.value.details["value_preview"]) <= 64
    assert malicious_coordinate not in str(raised.value.details)


def test_audit_rejects_malformed_combined_coordinate(tmp_path):
    source = tmp_path / "invalid_location.pscx"
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground" location="not-a-point"/></project>',
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details == {
        "field": "location",
        "reason": "invalid_component_coordinate",
        "value_length": len("not-a-point"),
        "value_preview": "not-a-point",
    }


def test_audit_emits_fixed_electrode_evidence_and_ignores_nested_parameters(tmp_path):
    source = tmp_path / "bounded_evidence.pscx"
    nested_parameters = "".join(
        f'<param name="untrusted_{index}" value="{index}"/>' for index in range(100)
    )
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground" x="0" y="0"/>'
        '<component definition="master:ammeter" x="0" y="0">'
        '<paramlist><param name="Name" value="Ielectrode"/></paramlist>'
        f'<metadata>{nested_parameters}</metadata>'
        '</component></project>',
        encoding="utf-8",
    )

    report = audit_lcc_template(source)

    assert report.roles["earth_electrode"]["evidence"]["anchor"] == {
        "definition": "master:ammeter",
        "location": [0, 0],
        "marker": {"name": "Name", "value": "Ielectrode"},
    }


def test_audit_does_not_use_nested_name_parameter_as_electrode_anchor(tmp_path):
    source = tmp_path / "nested_anchor.pscx"
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground" x="0" y="0"/>'
        '<component definition="master:ground" x="100" y="0"/>'
        '<component definition="master:ammeter" x="0" y="0">'
        '<metadata><param name="Name" value="Ielectrode"/></metadata>'
        '</component></project>',
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert raised.value.details["conflict_reasons"]["earth_electrode"] == (
        "multiple_exact_grounds_without_anchor"
    )


def test_audit_rejects_multiple_top_level_main_definitions(tmp_path):
    source = tmp_path / "duplicate_main.pscx"
    source.write_text(
        '<project><definitions>'
        '<Definition name="Main"><schematic><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground"/></schematic></Definition>'
        '<Definition name="Main"><canvas><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground"/></canvas></Definition>'
        '</definitions></project>',
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert raised.value.details == {
        "compatible": False,
        "conflict_reasons": {"main_scope": "multiple_main_definitions"},
        "conflicts": ["main_scope"],
        "roles": ["main_scope"],
    }


def test_audit_accepts_one_main_definition_with_named_canvas_and_schematic(tmp_path):
    source = tmp_path / "nested_main_scopes.pscx"
    source.write_text(
        '<project><definitions><Definition name="Main">'
        '<canvas name="Main"><schematic name="Main">'
        '<component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground" x="0" y="0"/>'
        '</schematic></canvas></Definition></definitions></project>',
        encoding="utf-8",
    )

    report = audit_lcc_template(source)

    assert report.compatible is True


def test_audit_does_not_scan_components_inside_nested_definition(tmp_path):
    source = tmp_path / "nested_definition.pscx"
    source.write_text(
        '<project><definitions><Definition name="Main"><schematic>'
        '<component definition="model:RectPole"/>'
        '<component definition="model:InverterPole"/>'
        '<component definition="master:ground" x="0" y="0"/>'
        '<Definition name="Nested"><schematic>'
        '<component definition="model:RectPole"/>'
        '<component definition="master:ground" x="100" y="100"/>'
        '</schematic></Definition>'
        '</schematic></Definition></definitions></project>',
        encoding="utf-8",
    )

    report = audit_lcc_template(source)

    assert report.compatible is True
    assert report.roles["rectifier_valve_group"]["definition"] == "model:RectPole"
    assert report.roles["earth_electrode"]["evidence"]["selected"]["location"] == [0, 0]


def test_audit_rejects_cross_definition_role_stitching_without_main(tmp_path):
    source = tmp_path / "cross_definition.pscx"
    source.write_text(
        '<project><definitions>'
        '<Definition name="Rectifier"><component definition="model:RectPole"/></Definition>'
        '<Definition name="Inverter"><component definition="model:InverterPole"/>'
        '<component definition="master:ground" x="0" y="0"/></Definition>'
        '</definitions></project>',
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_AMBIGUOUS"
    assert raised.value.details == {
        "compatible": False,
        "conflict_reasons": {"main_scope": "multiple_definitions_without_main"},
        "conflicts": ["main_scope"],
        "roles": ["main_scope"],
    }


@pytest.mark.parametrize(
    "ground, anchor, expected_role",
    [
        ('<component definition="master:ground"/>', "", "earth_electrode_ground"),
        (
            '<component definition="master:ground" x="0" y="0"/>',
            '<component definition="master:ammeter"><param name="Name" value="Ielectrode"/></component>',
            "earth_electrode_anchor",
        ),
    ],
)
def test_audit_rejects_missing_coordinates_needed_for_electrode_role(
    tmp_path, ground, anchor, expected_role
):
    source = tmp_path / "missing_role_coordinate.pscx"
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        f"{ground}{anchor}</project>",
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details == {
        "reason": "missing_component_coordinate",
        "role": expected_role,
    }


def test_audit_uses_one_open_and_does_not_pre_stat_path(tmp_path, monkeypatch):
    source = tmp_path / "single_open.pscx"
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground" x="0" y="0"/></project>',
        encoding="utf-8",
    )
    original_open = Path.open
    original_stat = Path.stat
    source_text = str(source.resolve())
    open_count = 0

    def counted_open(path, *args, **kwargs):
        nonlocal open_count
        if str(path) == source_text:
            open_count += 1
        return original_open(path, *args, **kwargs)

    def guarded_stat(path, *args, **kwargs):
        if str(path) == source_text:
            raise AssertionError("Path.stat must not be used before opening the template")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted_open)
    monkeypatch.setattr(Path, "stat", guarded_stat)

    report = audit_lcc_template(source)

    assert report.compatible is True
    assert open_count == 1


@pytest.mark.parametrize("error_type", [FileNotFoundError, PermissionError, OSError])
def test_audit_normalizes_template_open_errors(tmp_path, monkeypatch, error_type):
    source = tmp_path / "unreadable.pscx"
    source.write_text("<project/>", encoding="utf-8")

    def fail_open(*args, **kwargs):
        raise error_type("unbounded operating-system message")

    monkeypatch.setattr(Path, "open", fail_open)

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details == {
        "error_type": error_type.__name__,
        "reason": "template_unreadable",
    }


def test_audit_normalizes_path_resolution_oserror(tmp_path, monkeypatch):
    source = tmp_path / "resolution_failure.pscx"

    def fail_resolve(*args, **kwargs):
        raise PermissionError("unbounded path resolution message")

    monkeypatch.setattr(Path, "resolve", fail_resolve)

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details == {
        "error_type": "PermissionError",
        "reason": "template_unreadable",
    }


def test_audit_wraps_unknown_xml_encoding_as_incompatible(tmp_path):
    source = tmp_path / "unknown_encoding.pscx"
    source.write_bytes(b'<?xml version="1.0" encoding="not-a-codec"?><project/>')

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details == {
        "error_type": "LookupError",
        "reason": "invalid_xml",
    }


def test_audit_rejects_duplicate_name_parameters_without_overwrite(tmp_path):
    source = tmp_path / "duplicate_name.pscx"
    source.write_text(
        '<project><component definition="model:LCC12PulseBridge"/>'
        '<component definition="master:ground" x="0" y="0"/>'
        '<component definition="master:ammeter" x="0" y="0"><paramlist>'
        '<param name="Name" value="ignored"/>'
        '<param name="Name" value="Ielectrode"/>'
        '</paramlist></component></project>',
        encoding="utf-8",
    )

    with pytest.raises(BackendError) as raised:
        audit_lcc_template(source)

    assert raised.value.code == "LCC_TEMPLATE_INCOMPATIBLE"
    assert raised.value.details == {
        "parameter": "Name",
        "reason": "duplicate_component_parameter",
    }
