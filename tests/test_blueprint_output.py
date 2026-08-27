from __future__ import annotations

from pathlib import Path

import pytest

from pscad_mcp.builders.blueprint.output import discover_output_dataset, parse_inf, read_output_dataset
from pscad_mcp.core.backend.base import BackendError


def write_dataset(root: Path, *, channels: int = 12) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base = root / "BuiltCase"
    base.with_suffix(".inf").write_text(
        "\n".join(
            f'PGB({index}) Output Desc="C{index}" Group="Main" Max=100 Min=-100 Units="kV"'
            for index in range(1, channels + 1)
        )
        + "\n",
        encoding="utf-8",
    )
    rows = [[0.0, *range(1, channels + 1)], [0.1, *range(101, 101 + channels)], [0.2, *range(201, 201 + channels)]]
    for segment, start in enumerate(range(0, channels, 10), start=1):
        lines = []
        for row in rows:
            lines.append(" ".join(str(value) for value in [row[0], *row[start + 1 : min(start + 11, channels + 1)]]))
        Path(f"{base}_{segment:02d}.out").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return base.with_suffix(".inf")


def test_parse_inf_returns_ordered_exact_channel_metadata(tmp_path):
    inf = write_dataset(tmp_path, channels=2)

    metadata = parse_inf(inf)

    assert metadata == (
        {"call_id": 1, "path": "Main/C1", "units": "kV", "minimum": -100.0, "maximum": 100.0},
        {"call_id": 2, "path": "Main/C2", "units": "kV", "minimum": -100.0, "maximum": 100.0},
    )


def test_read_output_dataset_combines_column_segments_with_shared_domain(tmp_path):
    inf = write_dataset(tmp_path)

    dataset = read_output_dataset(inf)

    assert list(dataset["channels"]) == [f"Main/C{index}" for index in range(1, 13)]
    assert dataset["channels"]["Main/C1"]["domain"] == [0.0, 0.1, 0.2]
    assert dataset["channels"]["Main/C1"]["values"] == [1.0, 101.0, 201.0]
    assert dataset["channels"]["Main/C12"]["values"] == [12.0, 112.0, 212.0]
    assert dataset["segments"] == ["BuiltCase_01.out", "BuiltCase_02.out"]


@pytest.mark.parametrize("drift", ["missing_segment", "time", "columns", "nan", "duplicate_metadata"])
def test_read_output_dataset_rejects_incomplete_or_non_finite_evidence(tmp_path, drift):
    inf = write_dataset(tmp_path)
    first = tmp_path / "BuiltCase_01.out"
    second = tmp_path / "BuiltCase_02.out"
    if drift == "missing_segment":
        second.unlink()
    elif drift == "time":
        second.write_text("0.0 11 12\n0.15 111 112\n0.2 211 212\n", encoding="utf-8")
    elif drift == "columns":
        first.write_text("0.0 1 2\n0.1 101 102\n", encoding="utf-8")
    elif drift == "nan":
        first.write_text(first.read_text(encoding="utf-8").replace("101", "nan"), encoding="utf-8")
    else:
        inf.write_text(inf.read_text(encoding="utf-8") + 'PGB(1) Output Desc="OTHER" Group="Main" Max=1 Min=0 Units="kV"\n', encoding="utf-8")

    with pytest.raises(BackendError) as raised:
        read_output_dataset(inf)

    assert raised.value.code == "BLUEPRINT_OUTPUT_INVALID"


def test_discover_output_dataset_requires_one_workspace_contained_dataset(tmp_path):
    write_dataset(tmp_path, channels=1)
    dataset = discover_output_dataset(tmp_path)
    assert dataset["metadata_file"].endswith("BuiltCase.inf")

    write_dataset(tmp_path / "other", channels=1)
    with pytest.raises(BackendError) as raised:
        discover_output_dataset(tmp_path)
    assert raised.value.code == "BLUEPRINT_OUTPUT_AMBIGUOUS"
