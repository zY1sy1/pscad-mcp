import json
from dataclasses import asdict

from pscad_mcp.hvdc.scanner import scan_project


def test_evidence_is_stably_json_serializable():
    fixture = "tests/fixtures/hvdc/difforder_new.pscx"
    payload = asdict(scan_project(fixture))
    encoded = json.dumps(payload, sort_keys=True)
    assert "difforder_new.pscx" in encoded
    assert "RectCC" in encoded
