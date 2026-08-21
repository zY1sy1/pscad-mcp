from pathlib import Path

from pscad_mcp.hvdc.service import HvdcDomainService

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hvdc" / "lcc_earth_return"

def test_validate_lcc_earth_return_accepts_verified_fixture():
    result = HvdcDomainService().validate_project(str(FIXTURE_DIR / "bipolar_earth_return.pscx"), profile="lcc_bipolar_earth_return_v1")
    assert result["valid"] is True
    assert result["topology"]["return_mode"] == "earth_return"
    assert result["topology"]["return_path_status"] == "verified"

def test_validate_lcc_earth_return_reports_unresolved_path():
    result = HvdcDomainService().validate_project(str(FIXTURE_DIR / "incomplete_return_path.pscx"), profile="lcc_bipolar_earth_return_v1")
    assert result["valid"] is False
    assert any(error["code"] == "HVDC_RETURN_PATH_UNRESOLVED" for error in result["errors"])
