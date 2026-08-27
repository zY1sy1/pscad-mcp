from pathlib import Path


ROOT = Path(__file__).parents[1]
RUNNER = ROOT / "scripts" / "prepare_topology_truth.ps1"


def test_runner_declares_isolated_paths_and_only_owned_process_cleanup():
    text = RUNNER.read_text(encoding="utf-8")
    assert "topology-sources" in text
    assert "topology-truth.json" in text
    assert "Get-Process" in text
    assert "PSCAD*" in text
    assert "Stop-Process" not in text
    assert "normalize_topology_truth.py" in text
    assert "topology_truth.py" in text
    assert "ACCEPTANCE_PID" in text
