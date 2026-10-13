import math

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.workflows.sweep.analysis import compare, rank, read_legacy, summarize


def dataset(root, *, channels=12, count=101):
    root.joinpath("case.inf").write_text(
        "\n".join(
            f'PGB({i}) Output Desc="V{i}" Group="Main" Units="kV" Min=-100 Max=100'
            for i in range(1, channels + 1)
        )
    )
    for part in range((channels + 9) // 10):
        start, stop = part * 10 + 1, min((part + 1) * 10, channels) + 1
        root.joinpath(f"case_{part + 1:02d}.out").write_text(
            "\n".join(
                " ".join(
                    map(str, [i / 100, *[column * i for column in range(start, stop)]])
                )
                for i in range(count)
            )
        )


def test_segmented_out_uses_exact_selectors_and_bounded_endpoint_samples(tmp_path):
    dataset(tmp_path)
    data = read_legacy(tmp_path, "case_01.out", ("Main/V1", "Main/V12"), 5)
    stats = summarize(data, ("Main/V1", "Main/V12"), 5)
    assert [c["values"] for c in data["channels"]] == [
        [0, 25, 50, 75, 100],
        [0, 300, 600, 900, 1200],
    ]
    assert stats[1]["statistics"]["mean"] == 600
    assert stats[0]["statistics"]["rms"] == pytest.approx(math.sqrt(3750))
    assert stats[1]["statistics_scope"] == "bounded_sample"
    assert stats[1]["total_samples"] == 101
    assert stats[1]["units"] == "kV"


def test_native_empty_groups_and_undeclared_units_are_preserved(tmp_path):
    dataset(tmp_path, channels=1, count=5)
    metadata = tmp_path / "case.inf"
    metadata.write_text(
        metadata.read_text()
        .replace('Group="Main"', 'Group=""')
        .replace('Units="kV"', 'Units=""')
    )
    payload = read_legacy(tmp_path, "case_01.out", ("V1",), 10)
    channel = summarize(payload, ("V1",), 10)[0]
    assert channel["path"] == "V1"
    assert channel["units"] is None


def test_native_out_description_header_does_not_hide_numeric_data_errors(tmp_path):
    dataset(tmp_path, channels=1, count=5)
    part = tmp_path / "case_01.out"
    part.write_text("PSCAD example output\n" + part.read_text())
    payload = read_legacy(tmp_path, "case_01.out", ("Main/V1",), 10)
    assert payload["channels"][0]["values"] == [0, 1, 2, 3, 4]
    part.write_text("PSCAD example output\n0 corrupted\n0.01 1\n")
    with pytest.raises(BackendError):
        read_legacy(tmp_path, "case_01.out", ("Main/V1",), 10)


@pytest.mark.parametrize(
    "mutation", ["time", "missing", "unexpected", "nonfinite", "width"]
)
def test_segmented_out_rejects_inconsistent_or_malformed_evidence(tmp_path, mutation):
    dataset(tmp_path)
    part = tmp_path / "case_02.out"
    if mutation == "missing":
        part.unlink()
    elif mutation == "unexpected":
        tmp_path.joinpath("case_03.out").write_text("0 1")
    elif mutation == "time":
        part.write_text(part.read_text().replace("0.01 11 12", "0.015 11 12"))
    elif mutation == "nonfinite":
        part.write_text(part.read_text().replace("11 12", "nan 12"))
    else:
        part.write_text(part.read_text().replace("11 12", "11 12 13"))
    with pytest.raises(BackendError):
        read_legacy(tmp_path, "case_01.out", ("Main/V1",), 5)


@pytest.mark.parametrize(
    "values,domain",
    [([], []), ([True], [0]), ([math.nan], [0]), ([1], []), ([1, 2], [1, 1])],
)
def test_invalid_samples_are_not_reported_as_zero(values, domain):
    with pytest.raises(BackendError):
        summarize(
            {"channels": [{"path": "x", "values": values, "domain": domain}]}, ("x",), 5
        )


def test_zero_baseline_and_failed_baseline_are_explicit():
    outputs = [
        {
            "path": "case.psout",
            "channels": [
                {
                    "path": "x",
                    "statistics": {
                        "count": 2,
                        "min": 0,
                        "max": 0,
                        "mean": 0,
                        "first": 0,
                        "last": 0,
                        "rms": 0,
                        "peak_abs": 0,
                    },
                }
            ],
        }
    ]
    report = {"scenarios": [{"name": "base", "state": "succeeded", "outputs": outputs}]}
    channel = compare(report, "base")["scenarios"][0]["outputs"][0]["channels"][0]
    assert channel["comparison"]["mean"]["relative_delta"] is None
    assert "zero_baseline:mean" in channel["comparison_warnings"]
    report["scenarios"][0]["state"] = "failed"
    result = compare(report, "base")
    assert not result["baseline_available"]
    assert result["scenarios"][0]["outputs"][0]["channels"][0]["comparison"] == {}


@pytest.mark.parametrize("bad", [[], "nan", True, math.inf])
def test_constraint_values_do_not_accept_code_or_nonfinite_numbers(bad):
    metric = {
        "output_path": "x",
        "channel": "y",
        "statistic": "mean",
        "operator": "<=",
        "value": bad,
    }
    with pytest.raises(BackendError):
        rank({"scenarios": []}, constraints=[metric])
