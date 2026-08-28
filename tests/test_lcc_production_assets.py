from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pscad_mcp.hvdc.builders.lcc.assets import load_asset_set
from pscad_mcp.hvdc.builders.lcc.validator import validate_companion_library


ASSET_ROOT = Path(__file__).parents[1] / "pscad_mcp" / "assets" / "lcc" / "cigre_lcc_monopole_v1"


def test_production_asset_set_has_fixed_identity_and_complete_contract():
    asset_set = load_asset_set(ASSET_ROOT)

    assert asset_set.name == "cigre_lcc_monopole_v1"
    assert asset_set.pscad_version == "4.6.2"
    assert asset_set.blueprint.poles == 1
    assert asset_set.blueprint.terminals == 2
    assert sum(component.definition == "cigre_lcc_v1:LCC12PulseBridge" for component in asset_set.blueprint.components) == 2
    assert len(asset_set.blueprint.outputs) == 11
    assert {output.path for output in asset_set.blueprint.outputs} == {
        "Main/VDC_RECT", "Main/VDC_INV", "Main/IDC", "Main/P_RECT", "Main/Q_RECT",
        "Main/P_INV", "Main/Q_INV", "Main/ALPHA_RECT", "Main/GAMMA_INV", "Main/MU_RECT", "Main/VAC_RECT_A",
    }
    assert len(asset_set.acceptance["physical_checks"]) >= 8
    assert len(asset_set.golden["channels"]) == 11
    assert set(asset_set.hashes) == {
        "PROVENANCE.md", "acceptance.json", "blueprint.json", "catalog-pscad-4.6.2.json", "golden.json", "library/cigre_lcc_v1.pslx",
    }
    assert "Szechtman" in asset_set.provenance
    assert validate_companion_library(ASSET_ROOT / asset_set.companion_library)["valid"] is True


def test_confirmed_golden_generator_is_the_only_writer(tmp_path):
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"channels": {"Main/VDC_RECT": {"units": "kV", "time": [0, 1], "values": [1, 1]}}}), encoding="utf-8")
    blueprint = tmp_path / "blueprint.json"
    blueprint.write_text(
        json.dumps(
            {
                "settings": {"time_step_s": 0.001, "output_step_s": 0.001},
                "outputs": [{"path": "Main/VDC_RECT", "units": "kV"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "acceptance.json").write_text(
        json.dumps(
            {
                "golden": {
                    "comparison_window": [0, 1],
                    "alignment": {"channel": "Main/VDC_RECT", "rule": "positive_zero_crossing", "frequency_hz": 50.0, "max_cycles": 1.0},
                }
            }
        ),
        encoding="utf-8",
    )
    library = tmp_path / "library.pslx"
    library.write_text("library", encoding="utf-8")
    compiler = tmp_path / "compiler.exe"
    compiler.write_text("compiler", encoding="utf-8")
    golden = tmp_path / "golden.json"
    golden.write_text("original", encoding="utf-8")

    without_confirmation = subprocess.run(
        [
            sys.executable,
            "scripts/generate_lcc_golden.py",
            "--reference-output", str(reference),
            "--blueprint", str(blueprint),
            "--library", str(library),
            "--compiler", str(compiler),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )
    assert without_confirmation.returncode != 0
    assert golden.read_text(encoding="utf-8") == "original"

    confirmed = subprocess.run(
        [
            sys.executable,
            "scripts/generate_lcc_golden.py",
            "--reference-output", str(reference),
            "--blueprint", str(blueprint),
            "--library", str(library),
            "--compiler", str(compiler),
            "--confirm",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )
    assert confirmed.returncode == 0, confirmed.stderr
    payload = json.loads(golden.read_text(encoding="utf-8"))
    assert payload["channels"]["Main/VDC_RECT"]["values"] == [1, 1]
    assert payload["channels"]["Main/VDC_RECT"]["time"] == [0, 1]
    assert payload["source"]["compiler"] == "compiler.exe"
    assert not Path(payload["source"]["compiler"]).is_absolute()
    assert payload["source"]["emtdc_time_step_s"] == 0.001
    assert payload["source"]["output_step_s"] == 0.001
    assert payload["source"]["alignment_channel"] == "Main/VDC_RECT"
    assert payload["source"]["generated_at_utc"].endswith("Z")


def test_golden_generator_rejects_input_mutation_before_replacing_output(tmp_path, monkeypatch):
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"channels": {"Main/VDC_RECT": {"units": "kV", "time": [0, 1], "values": [1, 1]}}}), encoding="utf-8")
    blueprint = tmp_path / "blueprint.json"
    blueprint_value = {
        "settings": {"time_step_s": 0.001, "output_step_s": 0.001},
        "outputs": [{"path": "Main/VDC_RECT", "units": "kV"}],
    }
    blueprint.write_text(json.dumps(blueprint_value), encoding="utf-8")
    (tmp_path / "acceptance.json").write_text(
        json.dumps(
            {
                "golden": {
                    "comparison_window": [0, 1],
                    "alignment": {"channel": "Main/VDC_RECT", "rule": "positive_zero_crossing", "frequency_hz": 50.0, "max_cycles": 1.0},
                }
            }
        ),
        encoding="utf-8",
    )
    library = tmp_path / "library.pslx"
    library.write_text("library", encoding="utf-8")
    compiler = tmp_path / "compiler.exe"
    compiler.write_text("compiler", encoding="utf-8")
    golden = tmp_path / "golden.json"
    golden.write_text("original", encoding="utf-8")

    import scripts.generate_lcc_golden as generator

    original_hash = generator._sha256
    mutated = False

    def hash_with_mutation(path: Path) -> str:
        nonlocal mutated
        observed = original_hash(path)
        if path.resolve() == library.resolve() and not mutated:
            mutated = True
            blueprint.write_text(json.dumps({**blueprint_value, "settings": {"time_step_s": 0.002, "output_step_s": 0.001}}), encoding="utf-8")
        return observed

    monkeypatch.setattr(generator, "_sha256", hash_with_mutation)
    with pytest.raises(ValueError, match="changed"):
        generator.generate(reference, blueprint, library, compiler)
    assert golden.read_text(encoding="utf-8") == "original"


def test_golden_generator_rejects_units_and_window_contract_drift(tmp_path):
    reference = tmp_path / "reference.json"
    reference.write_text(
        json.dumps({"channels": {"Main/VDC_RECT": {"units": "V", "time": [0, 1, 2], "values": [1, 1, 1]}}}),
        encoding="utf-8",
    )
    blueprint = tmp_path / "blueprint.json"
    blueprint.write_text(
        json.dumps(
            {
                "settings": {"time_step_s": 0.001, "output_step_s": 0.001},
                "outputs": [{"path": "Main/VDC_RECT", "units": "kV"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "acceptance.json").write_text(
        json.dumps(
            {
                "golden": {
                    "comparison_window": [0, 3],
                    "alignment": {"channel": "Main/VDC_RECT", "rule": "positive_zero_crossing", "frequency_hz": 50.0, "max_cycles": 1.0},
                }
            }
        ),
        encoding="utf-8",
    )
    library = tmp_path / "library.pslx"
    library.write_text("library", encoding="utf-8")
    compiler = tmp_path / "compiler.exe"
    compiler.write_text("compiler", encoding="utf-8")
    golden = tmp_path / "golden.json"
    golden.write_text("original", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_lcc_golden.py",
            "--reference-output", str(reference),
            "--blueprint", str(blueprint),
            "--library", str(library),
            "--compiler", str(compiler),
            "--confirm",
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert golden.read_text(encoding="utf-8") == "original"
