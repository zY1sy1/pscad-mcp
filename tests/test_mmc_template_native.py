from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.models import SubmoduleTopology
from pscad_mcp.hvdc.builders.mmc.template_native import (
    evaluate_template_native_dc_fault,
    inspect_template_native_controls,
    materialize_template_native_scenario,
)


def _template(path: Path) -> Path:
    path.write_text(
        """<project name='case' version='4.6.2'>
          <paramlist name='Settings'>
            <param name='PlotType' value='1'/>
            <param name='output_filename' value='case.out'/>
          </paramlist>
          <definitions>
            <Definition name='Main'>
              <schematic>
                <User classid='UserCmp' id='11' defn='master:time-sig'/>
                <User classid='UserCmp' id='12' defn='master:tfaultn'>
                  <param name='TF' value='Flt_time'/>
                  <param name='DF' value='0.01'/>
                </User>
                <User classid='UserCmp' id='13' defn='master:var'>
                  <param name='Name' value='Fault Time'/>
                  <param name='Value' value='2.5'/>
                </User>
                <User classid='UserCmp' id='14' defn='master:var_switch'>
                  <param name='Name' value='AC Fault type'/>
                  <param name='Value' value='0'/>
                </User>
              </schematic>
            </Definition>
            <Definition name='Station'>
              <schematic>
                <Wire><User classid='UserCmp' id='15' defn='case:Main'>
                  <param name='TFlt' value='10'/>
                  <param name='FltDur' value='0.5'/>
                </User></Wire>
              </schematic>
            </Definition>
          </definitions>
        </project>""",
        encoding="ascii",
    )
    return path


def test_materialize_template_native_scenario_changes_only_derived_copy(
    tmp_path: Path,
) -> None:
    source = _template(tmp_path / "source.pscx")
    destination = tmp_path / "scenario.pscx"
    before = source.read_bytes()

    result = materialize_template_native_scenario(
        source,
        destination,
        fault_time_s=0.25,
        fault_duration_s=0.10,
        ac_fault_type=1,
    )

    assert source.read_bytes() == before
    assert result["timing_basis"] == "template_embedded_emt"
    assert result["bindings"] == [
        {"owner": "13", "name": "Fault Time", "parameter": "Value", "value": "0.25"},
        {"owner": "14", "name": "AC Fault type", "parameter": "Value", "value": "1"},
        {"owner": "12", "name": "Fault Duration", "parameter": "DF", "value": "0.1"},
    ]
    controls = inspect_template_native_controls(destination)
    assert controls["components"]["Fault Time"]["value"] == "0.25"
    assert controls["components"]["AC Fault type"]["value"] == "1"


def test_materialize_rejects_unknown_native_control(tmp_path: Path) -> None:
    source = _template(tmp_path / "source.pscx")

    with pytest.raises(BackendError) as raised:
        materialize_template_native_scenario(
            source,
            tmp_path / "scenario.pscx",
            controls={"Unknown": 1},
        )

    assert raised.value.code == "MMC_TEMPLATE_NATIVE_BINDING_MISSING"


def test_materialize_rejects_overwriting_source(tmp_path: Path) -> None:
    source = _template(tmp_path / "source.pscx")

    with pytest.raises(BackendError) as raised:
        materialize_template_native_scenario(source, source, fault_time_s=0.2)

    assert raised.value.code == "MMC_BUILD_CONFLICT"


def test_native_fault_evidence_stays_incomplete_without_explicit_inserted_voltage(
    ) -> None:
    result = evaluate_template_native_dc_fault(
        {
            "channels": [
                {
                    "description": "Fault mode",
                    "units": "1",
                    "domain": [0.0, 0.2, 0.4],
                    "values": [0.0, 1.0, 0.0],
                },
                {
                    "description": "DC fault current",
                    "units": "kA",
                    "domain": [0.0, 0.2, 0.4],
                    "values": [0.0, 1.0, 0.0],
                },
                {
                    "description": "De-blocking T1",
                    "units": "1",
                    "domain": [0.0, 0.2, 0.4],
                    "values": [1.0, 0.0, 1.0],
                },
            ]
        },
        fault_current_limit_ka=2.0,
    )

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert result["checks"]["negative_voltage_inserted"] is False
    assert result["missing_channels"] == ["negative_voltage_inserted"]


def test_native_fault_evidence_can_pass_only_with_all_explicit_channels() -> None:
    result = evaluate_template_native_dc_fault(
        {
            "channels": [
                {
                    "description": "Fault mode",
                    "units": "1",
                    "domain": [0.0, 0.2, 0.4],
                    "values": [0.0, 1.0, 0.0],
                },
                {
                    "description": "DC fault current",
                    "units": "kA",
                    "domain": [0.0, 0.2, 0.4],
                    "values": [0.0, 1.0, 0.0],
                },
                {
                    "description": "De-blocking T1",
                    "units": "1",
                    "domain": [0.0, 0.2, 0.4],
                    "values": [1.0, 0.0, 1.0],
                },
                {
                    "description": "V_inserted",
                    "units": "kV",
                    "domain": [0.0, 0.2, 0.4],
                    "values": [0.0, -10.0, 0.0],
                },
            ]
        },
        fault_current_limit_ka=2.0,
    )

    assert result["verdict"] == "PASS"
    assert result["checks"] == {
        "fault_applied": True,
        "negative_voltage_inserted": True,
        "blocked": True,
        "recovered": True,
        "bounded_fault_current": True,
    }


def test_native_fault_evidence_does_not_reuse_full_bridge_acceptance_for_half_bridge() -> None:
    result = evaluate_template_native_dc_fault(
        {
            "channels": [
                {"description": "Fault mode", "units": "1", "domain": [0.0, 0.2, 0.4], "values": [0.0, 1.0, 0.0]},
                {"description": "DC fault current", "units": "kA", "domain": [0.0, 0.2, 0.4], "values": [0.0, 1.0, 0.0]},
                {"description": "De-blocking T1", "units": "1", "domain": [0.0, 0.2, 0.4], "values": [1.0, 0.0, 1.0]},
                {"description": "V_inserted", "units": "kV", "domain": [0.0, 0.2, 0.4], "values": [0.0, -10.0, 0.0]},
            ]
        },
        fault_current_limit_ka=2.0,
        topology=SubmoduleTopology.HALF_BRIDGE,
    )

    assert result["verdict"] == "NOT_APPLICABLE"
    assert result["capabilities"]["intrinsic_dc_fault_blocking"] is False


def test_dc_fault_time_uses_the_template_fault_timer(tmp_path: Path) -> None:
    source = _template(tmp_path / "source.pscx")
    destination = tmp_path / "dc.pscx"

    result = materialize_template_native_scenario(
        source,
        destination,
        dc_fault_time_s=0.8,
        fault_duration_s=0.1,
    )

    assert result["bindings"][0] == {
        "owner": "13",
        "name": "Fault Time",
        "parameter": "Value",
        "value": "0.8",
    }


def test_native_fault_duration_binds_main_timer_not_unused_station(tmp_path: Path) -> None:
    source = _template(tmp_path / "source.pscx")
    destination = tmp_path / "scenario.pscx"

    materialize_template_native_scenario(
        source, destination, dc_fault_time_s=0.3, fault_duration_s=0.2
    )

    root = ET.parse(destination).getroot()
    assert root.find(".//User[@id='12']/param[@name='DF']").get("value") == "0.2"
    assert root.find(".//User[@id='15']/param[@name='FltDur']").get("value") == "0.5"
    assert root.find(".//User[@id='15']/param[@name='TFlt']").get("value") == "10"


@pytest.mark.parametrize("mode", ["missing", "ambiguous", "wrong_signal"])
def test_native_fault_duration_requires_unique_bound_main_timer(tmp_path: Path, mode: str) -> None:
    source = _template(tmp_path / "source.pscx")
    root = ET.parse(source).getroot()
    main = root.find(".//Definition[@name='Main']/schematic")
    timer = main.find("User[@id='12']")
    if mode == "missing":
        main.remove(timer)
    elif mode == "ambiguous":
        duplicate = ET.fromstring(ET.tostring(timer))
        duplicate.set("id", "16")
        main.append(duplicate)
    else:
        timer.find("param[@name='TF']").set("value", "unrelated_timer")
    ET.ElementTree(root).write(source)
    before = source.read_bytes()
    destination = tmp_path / "scenario.pscx"

    with pytest.raises(BackendError) as raised:
        materialize_template_native_scenario(
            source, destination, dc_fault_time_s=0.3, fault_duration_s=0.2
        )

    assert raised.value.code == (
        "MMC_TEMPLATE_NATIVE_BINDING_AMBIGUOUS"
        if mode == "ambiguous"
        else "MMC_TEMPLATE_NATIVE_BINDING_MISSING"
    )
    assert source.read_bytes() == before
    assert not destination.exists()


@pytest.mark.parametrize(
    "timing",
    [
        {"dc_fault_time_s": -1.0},
        {"fault_time_s": float("nan")},
        {"fault_duration_s": 0.0},
        {"fault_duration_s": -0.1},
        {"fault_duration_s": float("inf")},
        {"fault_duration_s": True},
    ],
)
def test_native_fault_rejects_invalid_timing_before_writing(tmp_path: Path, timing: dict) -> None:
    source = _template(tmp_path / "source.pscx")
    destination = tmp_path / "scenario.pscx"

    with pytest.raises(BackendError) as raised:
        materialize_template_native_scenario(source, destination, **timing)

    assert raised.value.code == "MMC_TEMPLATE_NATIVE_BINDING_INVALID"
    assert not destination.exists()


def test_native_fault_evidence_prefers_an_active_duplicate_fault_channel() -> None:
    base = [0.0, 0.3, 0.5]
    result = evaluate_template_native_dc_fault(
        {
            "channels": [
                {"description": "Fault mode", "domain": base, "values": [0.0, 0.0, 0.0]},
                {"description": "Fault mode_1", "domain": base, "values": [0.0, 1.0, 0.0]},
                {"description": "DC fault current", "domain": base, "values": [0.0, 1.0, 0.0]},
                {"description": "De-blocking T1", "domain": base, "values": [1.0, 0.0, 1.0]},
            ]
        },
        fault_current_limit_ka=2.0,
    )

    assert result["evidence"]["fault_time_s"] == 0.3
    assert result["checks"]["fault_applied"] is True


def _explicit_fault_samples() -> dict:
    domain = [0.0, 0.2, 0.4]
    return {
        "channels": [
            {"path": "Main/DC fault active", "description": "DC fault active", "units": "1", "domain": domain, "values": [0.0, 1.0, 0.0]},
            {"path": "Main/DC fault current", "description": "DC fault current", "units": "kA", "domain": domain, "values": [0.0, 1.0, 0.0]},
            {"path": "Main/Block status T1", "description": "Block status T1", "units": "1", "domain": domain, "values": [0.0, 1.0, 0.0]},
            {"path": "Main/V_inserted", "description": "V_inserted", "units": "kV", "domain": domain, "values": [0.0, -10.0, 0.0]},
        ]
    }


def test_native_fault_block_status_uses_active_high_polarity() -> None:
    result = evaluate_template_native_dc_fault(_explicit_fault_samples(), fault_current_limit_ka=2.0)

    assert result["verdict"] == "PASS"
    assert result["evidence"]["blocking_active_value"] == 1


def test_native_fault_does_not_treat_deblocking_as_active_high_blocking() -> None:
    samples = _explicit_fault_samples()
    samples["channels"][2]["values"] = [1.0, 0.0, 1.0]

    result = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=2.0)

    assert result["verdict"] == "FAIL"
    assert result["checks"]["blocked"] is False


def test_native_fault_current_converts_amperes_before_comparing_ka_limit() -> None:
    samples = _explicit_fault_samples()
    samples["channels"][1].update(units="A", values=[0.0, 1000.0, 0.0])

    result = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=2.0)

    assert result["verdict"] == "PASS"
    assert result["evidence"]["fault_current_peak_ka"] == 1.0


@pytest.mark.parametrize("units", ["", "V", "pu", None, []])
def test_native_fault_current_requires_declared_current_units(units) -> None:
    samples = _explicit_fault_samples()
    samples["channels"][1]["units"] = units

    result = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=2.0)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert "units:fault_current" in result["invalid_evidence"]
    assert "fault_current_peak_ka" not in result["evidence"]


def test_native_fault_ambiguous_station_blocking_requires_exact_selector() -> None:
    samples = _explicit_fault_samples()
    samples["channels"].append({**samples["channels"][2], "path": "Main/Block status T2", "description": "Block status T2", "values": [0.0, 0.0, 0.0]})

    result = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=2.0)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert "ambiguous:blocked" in result["invalid_evidence"]


def test_native_fault_exact_selector_records_station_identity() -> None:
    samples = _explicit_fault_samples()
    samples["channels"].insert(0, {**samples["channels"][2], "path": "Main/Block status T2", "description": "Block status T2", "values": [0.0, 0.0, 0.0]})

    result = evaluate_template_native_dc_fault(
        samples, fault_current_limit_ka=2.0,
        channel_selectors={"blocked": "Main/Block status T1"},
    )

    assert result["verdict"] == "PASS"
    assert result["evidence"]["selected_channels"]["blocked"]["path"] == "Main/Block status T1"


def test_native_fault_missing_exact_selector_does_not_fall_back_to_alias() -> None:
    result = evaluate_template_native_dc_fault(
        _explicit_fault_samples(), fault_current_limit_ka=2.0,
        channel_selectors={"blocked": "Main/Block status T9"},
    )

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert "blocked" in result["missing_channels"]


def test_native_fault_boolean_current_limit_cannot_pass() -> None:
    result = evaluate_template_native_dc_fault(_explicit_fault_samples(), fault_current_limit_ka=True)

    assert result["verdict"] != "PASS"
    assert result["checks"]["bounded_fault_current"] is False


def test_native_fault_voltage_units_preserve_physical_epsilon() -> None:
    samples = _explicit_fault_samples()
    samples["channels"][3].update(units="V", values=[0.0, -1e-8, 0.0])

    result = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=2.0)

    assert result["verdict"] == "FAIL"
    assert result["checks"]["negative_voltage_inserted"] is False


def test_native_fault_malformed_voltage_units_remain_incomplete() -> None:
    samples = _explicit_fault_samples()
    samples["channels"][3]["units"] = []

    result = evaluate_template_native_dc_fault(samples, fault_current_limit_ka=2.0)

    assert result["verdict"] == "INCOMPLETE_ANALYSIS"
    assert "units:negative_voltage_inserted" in result["invalid_evidence"]
