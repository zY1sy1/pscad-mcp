import json
from pathlib import Path

from pscad_mcp.hvdc.builders.lcc.schema import parse_blueprint


def test_duplicate_measurements_require_explicit_derived_signal_metadata():
    path = Path("pscad_mcp/assets/lcc/cigre_lcc_monopole_v1/blueprint.json")
    value = json.loads(path.read_text(encoding="utf-8"))
    measurements = {item["logical_id"]: item for item in value["measurements"]}
    assert measurements["mu_measurement"]["derived_from"] == "alpha_measurement"
    assert measurements["vac_rect_measurement"]["derived_from"] == "p_rect_measurement"
    parsed = parse_blueprint(value)
    assert len(parsed.measurements) == len(value["measurements"])
