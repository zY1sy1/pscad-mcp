"""Acceptance rejects wrong current signs, missing storage and false blocking."""

from __future__ import annotations

import importlib
import os
import time
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from pscad_mcp.hvdc.builders.mmc.avm_companion import AverageArmParameters


@pytest.fixture(scope="module")
def runner():
    name = "scripts.run_mmc_average_arm_acceptance"
    assert importlib.util.find_spec(name) is not None, (
        "Native arm acceptance runner is missing"
    )
    return importlib.import_module(name)


def _physical_trace():
    parameters = AverageArmParameters()
    trace = {
        name: []
        for name in (
            "time",
            "M",
            "BLOCK",
            "CURRENT_COMMAND",
            "I_ARM",
            "I_CAP",
            "I_NORMAL",
            "I_CLAMP",
            "I_BYPASS",
            "V_CAP_TOTAL",
            "V_CAP_EQ",
            "ENERGY",
            "V_INSERTED",
            "V_ARM",
            "P_NONOHMIC",
        )
    }
    step, vcap, previous_cap_current = 2e-5, 0.0, 0.0
    for index in range(9501):
        time = index * step
        if time < 0.01:
            current, derivative = 20 * time, 20.0
        elif time < 0.06:
            current, derivative = 0.2, 0.0
        elif time < 0.07:
            current, derivative = 0.2 - 40 * (time - 0.06), -40.0
        elif time < 0.09:
            current, derivative = -0.2, 0.0
        elif time < 0.10:
            current, derivative = -0.2 + 40 * (time - 0.09), 40.0
        elif time < 0.14:
            current, derivative = 0.2, 0.0
        elif time < 0.15:
            current, derivative = 0.2 - 40 * (time - 0.14), -40.0
        else:
            current, derivative = -0.2, 0.0
        blocked = time >= 0.095
        ratio = (1.0 if current > 0 else 0.0) if blocked else 0.5
        cap_current = ratio * current
        if index:
            vcap += (
                0.5
                * (previous_cap_current + cap_current)
                * step
                / (parameters.C_eq_F / 4)
            )
        previous_cap_current = cap_current
        inserted = ratio * vcap + parameters.R_on_ohm * current
        row = {
            "time": time,
            "M": 0.5,
            "BLOCK": float(blocked),
            "CURRENT_COMMAND": current,
            "I_ARM": current,
            "I_CAP": cap_current,
            "I_NORMAL": 0.0 if blocked else current,
            "I_CLAMP": max(current, 0.0) if blocked else 0.0,
            "I_BYPASS": max(-current, 0.0) if blocked else 0.0,
            "V_CAP_TOTAL": vcap,
            "V_CAP_EQ": vcap / 2,
            "ENERGY": parameters.C_eq_F * vcap**2 / 8,
            "V_INSERTED": inserted,
            "V_ARM": inserted
            + parameters.R_arm_ohm * current
            + parameters.L_arm_H * derivative,
            "P_NONOHMIC": 0.0,
        }
        for name, value in row.items():
            trace[name].append(value)
    return trace


def test_physical_reference_trace_satisfies_all_component_checks(runner):
    result = runner.analyze_arm_trace(_physical_trace(), AverageArmParameters())
    assert result["status"] == "PASS"
    assert result["measurement_complete"] is True
    assert set(result["windows"]) == {
        "charge",
        "discharge",
        "blocked_charge",
        "blocked_bypass",
    }
    assert result["windows"]["discharge"]["energy_change_mj"] < 0
    assert result["windows"]["blocked_charge"]["mean_clamp_current_ka"] > 0
    assert result["windows"]["blocked_bypass"]["mean_bypass_current_ka"] > 0


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_storage_sign",
        "all_branches_open",
        "fake_capacitor_waveform",
        "double_voltage_normalization",
        "missing_capacitor_current",
        "wrong_arm_resistance",
        "wrong_arm_inductance",
        "time_gap",
        "nonfinite",
    ],
)
def test_physical_defects_cannot_pass_the_gate(runner, mutation):
    trace = deepcopy(_physical_trace())
    if mutation == "wrong_storage_sign":
        trace["I_CAP"] = [-value for value in trace["I_CAP"]]
    elif mutation == "all_branches_open":
        trace["I_CLAMP"] = [0.0] * len(trace["time"])
        trace["I_BYPASS"] = [0.0] * len(trace["time"])
    elif mutation == "fake_capacitor_waveform":
        trace["ENERGY"] = [0.01] * len(trace["time"])
    elif mutation == "double_voltage_normalization":
        trace["V_CAP_EQ"] = trace["V_CAP_TOTAL"][:]
    elif mutation == "missing_capacitor_current":
        del trace["I_CAP"]
    elif mutation == "wrong_arm_resistance":
        trace["V_ARM"] = [
            value - 0.1 * current
            for value, current in zip(trace["V_ARM"], trace["I_ARM"])
        ]
    elif mutation == "wrong_arm_inductance":
        trace["V_ARM"][:500] = [value - 0.4 for value in trace["V_ARM"][:500]]
    elif mutation == "time_gap":
        trace["time"][100] += 0.01
    else:
        trace["V_CAP_TOTAL"][100] = float("nan")
    assert runner.analyze_arm_trace(trace, AverageArmParameters())["status"] == "FAIL"


def test_both_optins_are_required_before_runtime_or_workspace(
    runner, tmp_path, monkeypatch
):
    monkeypatch.setenv("PSCAD_MCP_ACCEPTANCE", "1")
    monkeypatch.delenv("PSCAD_MCP_AVERAGE_ARM_ACCEPTANCE", raising=False)
    target = tmp_path / "not_created"
    assert (
        runner.main(
            ["--workspace-root", str(target)],
            service_factory=lambda _: pytest.fail(
                "Runtime was started without both opt-ins"
            ),
        )
        == 2
    )
    assert not target.exists()


def test_dead_zero_state_is_a_physical_failure_not_an_analysis_crash(runner):
    trace = _physical_trace()
    for name in ("ENERGY", "V_CAP_TOTAL", "V_CAP_EQ", "I_CAP"):
        trace[name] = [0.0] * len(trace["time"])
    assert runner.analyze_arm_trace(trace, AverageArmParameters())["status"] == "FAIL"


@pytest.fixture
def native_output_pair(runner, tmp_path):
    names = list(runner.CHANNEL_UNITS)
    owners = {name: str(1000 + index) for index, name in enumerate(names)}
    inf = tmp_path / "fixture.inf"
    inf.write_text(
        "\n".join(
            f'PGB({index + 1}) Desc="{name}" Group="" Units="{runner.CHANNEL_UNITS[name]}"'
            for index, name in enumerate(names)
        ),
        encoding="utf-8",
    )
    root = ET.Element("EMTDC")
    ET.SubElement(root, "Domain", {"name": "Time", "unit": "s"})
    analogs = ET.SubElement(root, "List")
    for index, name in enumerate(names):
        ET.SubElement(
            analogs,
            "Analog",
            {
                "index": str(index),
                "dim": "1",
                "name": "Main:" + name,
                "id": owners[name],
                "unit": runner.CHANNEL_UNITS[name],
            },
        )
    infx = tmp_path / "fixture.infx"
    infx.write_bytes(ET.tostring(root))
    parts = []
    for index in range(0, len(names), 10):
        part = tmp_path / f"fixture_{index // 10 + 1:02}.out"
        part.write_text(
            "\n".join(
                " ".join(
                    str(value)
                    for value in [
                        instant,
                        *range(index + 1, min(index + 11, len(names) + 1)),
                    ]
                )
                for instant in (0.0, 0.00002)
            ),
            encoding="ascii",
        )
        parts.append(part)
    return {"inf": inf, "infx": infx, "parts": parts}, owners


def test_native_output_columns_are_bound_to_saved_physical_probe_owners(
    runner, native_output_pair
):
    files, owners = native_output_pair
    result = runner.read_arm_trace(files, owners)
    assert result["samples"]["time"] == [0.0, 0.00002]
    for index, name in enumerate(runner.CHANNEL_UNITS, start=1):
        assert result["samples"][name] == [index, index]
        assert result["channel_sources"][index]["infx"]["owner"] == owners[name]


@pytest.mark.parametrize("mutation", ["owner", "unit", "domain", "missing_part", "nan"])
def test_native_output_metadata_and_numeric_corruption_is_rejected(
    runner, native_output_pair, mutation
):
    files, owners = native_output_pair
    if mutation in {"owner", "unit"}:
        root = ET.parse(files["infx"])
        root.find("./List/Analog").set(
            "id" if mutation == "owner" else "unit", "invalid"
        )
        root.write(files["infx"])
    elif mutation == "missing_part":
        files["parts"].pop()
    else:
        part = files["parts"][-1]
        payload = part.read_text(encoding="ascii")
        part.write_text(
            payload.replace("2e-05", "0.00003")
            if mutation == "domain"
            else payload.replace("11", "NaN"),
            encoding="ascii",
        )
    with pytest.raises((ValueError, IndexError)):
        runner.read_arm_trace(files, owners)


def test_fresh_executable_requires_single_new_nonempty_owned_artifact(runner, tmp_path):
    project = tmp_path / "fixture.pscx"
    project.write_text("fixture", encoding="ascii")
    build = tmp_path / "fixture.gf46"
    build.mkdir()
    executable = build / "fixture.exe"
    executable.write_bytes(b"MZ fixture binary contract")
    started = time.time() - 1
    proof = runner.fresh_project_executable(project, started)
    assert proof["path"] == str(executable.resolve())
    assert proof["bytes"] == executable.stat().st_size
    os.utime(executable, (started - 10, started - 10))
    with pytest.raises(ValueError, match="fresh"):
        runner.fresh_project_executable(project, started)


def test_finalized_parameter_or_wire_change_invalidates_hash_contract(runner, tmp_path):
    path = tmp_path / "fixture.pscx"
    path.write_text('<project><param name="R" value="0.1"/></project>', encoding="ascii")
    before = {str(path): runner._sha256(path)}
    assert runner.require_finalized_hashes(before) == before
    path.write_text('<project><param name="R" value="0.2"/></project>', encoding="ascii")
    with pytest.raises(ValueError, match="finalized"):
        runner.require_finalized_hashes(before)


@pytest.mark.parametrize("mutation", ["parameter", "wire", "script"])
def test_native_normalization_rejects_electrical_and_control_drift(runner, tmp_path, mutation):
    path = tmp_path / "fixture.pscx"
    path.write_text('<project name="fixture" version="4.6.2" Target="EMTDC"><paramlist name="Settings"><param name="revisor" value="0,0"/></paramlist><definitions><Definition name="Main" classid="UserCmpDefn" date="0" crc="0"><schematic><paramlist><param name="auto_sequence" value="1"/></paramlist><User id="1" defn="master:resistor" x="0" y="0" z="1"><paramlist><param name="R" value="0.1"/></paramlist></User><Wire id="2" x="0" y="0" w="36" h="0"><vertex x="0" y="0"/><vertex x="36" y="0"/></Wire></schematic><script><segment name="Fortran">$OUT = $IN</segment></script></Definition></definitions></project>', encoding="ascii")
    before = runner.snapshot_model_inputs((path,))
    root = ET.parse(path)
    if mutation == "parameter":
        root.find(".//User/paramlist/param").set("value", "0.2")
    elif mutation == "wire":
        root.findall(".//Wire/vertex")[-1].set("x", "72")
    else:
        root.find(".//segment").text = "$OUT = -$IN"
    root.write(path)
    with pytest.raises(ValueError, match="semantic"):
        runner.verify_model_normalization(before)
