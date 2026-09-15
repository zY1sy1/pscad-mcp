from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.master_bindings import (
    audit_mmc_master_bindings,
    load_mmc_master_registry,
    normalize_mmc_master_parameters,
)


_MASTER = Path("C:/Program Files (x86)/PSCAD46/master.pslx")


def test_mmc_direct_registry_uses_real_names_and_exact_ports() -> None:
    registry = load_mmc_master_registry()
    records = registry.by_logical_name

    assert records["master:dc_bus"].physical_definition == "nodelabel"
    assert records["master:transformer"].physical_definition == "xfmr-3p2w"
    assert records["master:pi_controller"].physical_definition == "pi_ctlr"
    assert {
        port.logical: (port.physical, port.dimension)
        for port in records["master:source3"].ports
    } == {"AC": ("N3", 3), "NEUTRAL": ("N", 1)}
    assert {port.logical for port in records["master:transformer"].ports} == {
        "AC",
        "VALVE",
        "NEUTRAL",
    }
    phase_breakout = records["master:phase_breakout"]
    assert phase_breakout.physical_definition == "breakout"
    assert {
        port.logical: (port.physical, port.dimension, port.occurrence)
        for port in phase_breakout.ports
    } == {
        "AC": ("N", 3, 0),
        "A": ("N1", 1, 0),
        "B": ("N2", 1, 0),
        "C": ("N3", 1, 0),
    }
    assert "master:dc_cable" not in records


def test_source_impedance_normalization_preserves_requested_rx() -> None:
    parameters = normalize_mmc_master_parameters(
        "master:source3",
        {
            "Name": "STATION_P_AC",
            "Amplitude": 230.0,
            "Frequency": 60.0,
            "GridR": 3.0,
            "GridX": 4.0,
        },
    )

    assert parameters["GridMagnitude"] == 5.0
    assert parameters["GridAngle"] == pytest.approx(53.13010235415598)
    assert parameters["GridR"] == 3.0
    assert parameters["GridX"] == 4.0
    assert parameters["OperatingVoltage_kV"] == 230.0
    assert parameters["OperatingFrequency_Hz"] == 60.0


@pytest.mark.parametrize(
    "change",
    [
        {"GridR": 0},
        {"GridX": -1},
        {"Frequency": float("nan")},
        {"Amplitude": True},
        {"GridMagnitude": 5.0},
    ],
)
def test_source_normalization_rejects_invalid_or_forged_inputs(change: dict) -> None:
    parameters = {
        "Name": "SOURCE",
        "Amplitude": 230.0,
        "Frequency": 60.0,
        "GridR": 3.0,
        "GridX": 4.0,
        **change,
    }

    with pytest.raises(BackendError) as raised:
        normalize_mmc_master_parameters("master:source3", parameters)

    assert raised.value.code == "MMC_PARAMETER_MISMATCH"


@pytest.mark.parametrize("name", ["", " ", "1NODE", "NODE.ONE", "NODE TWO"])
def test_dc_node_names_require_explicit_valid_identifiers(name: str) -> None:
    with pytest.raises(BackendError):
        normalize_mmc_master_parameters("master:dc_bus", {"Name": name})


def test_registry_data_is_a_packaged_resource() -> None:
    registry = load_mmc_master_registry()
    assert registry.pscad_version == "4.6.2"
    assert len(registry.sha256) == 64
    assert Path("pscad_mcp/assets/mmc/master_bindings/pscad-4.6.2.json").is_file()


@pytest.mark.skipif(
    not _MASTER.is_file(), reason="Requires installed static PSCAD 4.6.2 Master XML"
)
def test_installed_phase_breakout_has_exact_scalar_phase_contract() -> None:
    resolved = audit_mmc_master_bindings(_MASTER).resolve_component(
        "master:phase_breakout", {}
    )

    assert resolved.physical_parameters == {"Com": 0, "Dis": 0}
    assert {
        name: (port["model"], port["dimension"], port["occurrence"])
        for name, port in resolved.selected_ports.items()
    } == {
        "AC": ("Natural", 3, 0),
        "A": ("Natural", 1, 0),
        "B": ("Natural", 1, 0),
        "C": ("Natural", 1, 0),
    }


@pytest.mark.skipif(
    not _MASTER.is_file(), reason="Requires installed static PSCAD 4.6.2 Master XML"
)
def test_installed_source_binding_resolves_preserved_rx_and_actual_values() -> None:
    context = audit_mmc_master_bindings(_MASTER)
    resolved = context.resolve_component(
        "master:source3",
        {
            "Name": "SOURCE",
            "Amplitude": 230.0,
            "Frequency": 60.0,
            "GridR": 3.0,
            "GridX": 4.0,
        },
    )

    assert resolved.physical_parameters["Z1"] == 5.0
    assert resolved.physical_parameters["Phi1"] == pytest.approx(53.13010235415598)
    assert dict(resolved.evidence_parameters) == {"GridR": 3.0, "GridX": 4.0}


@pytest.mark.skipif(
    not _MASTER.is_file(), reason="Requires installed static PSCAD 4.6.2 Master XML"
)
def test_installed_parameter_minimum_is_checked_before_placement() -> None:
    context = audit_mmc_master_bindings(_MASTER)

    with pytest.raises(BackendError) as raised:
        context.resolve_component(
            "master:source3",
            {
                "Name": "SOURCE",
                "Amplitude": 230.0,
                "Frequency": 0.0001,
                "GridR": 3.0,
                "GridX": 4.0,
            },
        )

    assert raised.value.code == "MASTER_PARAMETER_MISMATCH"
    assert raised.value.details["physical_parameter"] == "F"


@pytest.mark.skipif(
    not _MASTER.is_file(), reason="Requires installed static PSCAD 4.6.2 Master XML"
)
def test_transformer_binding_keeps_finite_winding_resistance() -> None:
    resolved = audit_mmc_master_bindings(_MASTER).resolve_component(
        "master:transformer",
        {
            "Name": "MMC_XFMR",
            "RatedPower_MVA": 1200.0,
            "Primary_kV": 230.0,
            "Secondary_kV": 230.0,
            "Frequency": 60.0,
            "Leakage_pu": 0.15,
        },
    )

    assert resolved.physical_parameters["CuL"] == pytest.approx(0.005)
    assert resolved.physical_parameters["CuL"] > 0


@pytest.mark.skipif(
    not _MASTER.is_file(), reason="Requires installed static PSCAD 4.6.2 Master XML"
)
def test_nondefault_source_request_sets_operating_values_and_neutral() -> None:
    resolved = audit_mmc_master_bindings(_MASTER).resolve_component(
        "master:source3",
        {
            "Name": "SOURCE",
            "Amplitude": 400.0,
            "Frequency": 50.0,
            "GridR": 3.0,
            "GridX": 4.0,
        },
    )

    assert (
        resolved.physical_parameters["Vm"]
        == resolved.physical_parameters["Es"]
        == 400.0
    )
    assert (
        resolved.physical_parameters["F"] == resolved.physical_parameters["F0"] == 50.0
    )
    assert resolved.physical_parameters["Term"] == 0
    assert resolved.selected_ports["NEUTRAL"]["occurrence"] == 1
