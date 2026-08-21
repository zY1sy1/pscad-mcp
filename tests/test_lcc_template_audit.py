from pathlib import Path

from pscad_mcp.hvdc.builders.lcc.template_audit import audit_lcc_template


def test_audit_reports_exact_roles_without_mutation(tmp_path):
    source = tmp_path / "template.pscx"
    original = '<project><component definition="cigre_lcc_v1:LCC12PulseBridge"/><component definition="master:ground"/></project>'
    source.write_text(original, encoding="utf-8")
    report = audit_lcc_template(source)
    assert report.compatible is True
    assert report.roles["rectifier_valve_group"]["definition"] == "cigre_lcc_v1:LCC12PulseBridge"
    assert source.read_text(encoding="utf-8") == original
