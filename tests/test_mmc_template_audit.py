import os
from pathlib import Path

import pytest

from pscad_mcp.core.backend.base import BackendError
from pscad_mcp.hvdc.builders.mmc.template_audit import (
    audit_mmc_template,
    discover_official_mmc_template,
)
from tests.mmc_parametric_fakes import make_synthetic_official_shape, sha256


def test_audit_reports_sources_roles_and_absolute_paths_without_writes(tmp_path: Path) -> None:
    project, library = make_synthetic_official_shape(tmp_path)
    before = (project.read_bytes(), library.read_bytes())
    report = audit_mmc_template(project, library)
    assert report["compatible"] is True
    assert report["pscad_version"] == "4.6.2"
    assert report["model_fidelity"] == "detailed_pwm"
    assert report["source_hashes"] == {
        "project": sha256(project),
        "library": sha256(library),
    }
    assert {item["kind"] for item in report["absolute_paths"]} == {
        "startup_snapshot",
        "line_database",
        "line_constants",
    }
    assert before == (project.read_bytes(), library.read_bytes())


def test_discovery_is_bounded_to_public_pscad_46_example_tree(tmp_path: Path) -> None:
    directory = tmp_path / "Documents" / "PSCAD" / "4.6" / "Examples" / "ModelsInProgress"
    project, library = make_synthetic_official_shape(directory)
    assert discover_official_mmc_template(tmp_path) == (project.resolve(), library.resolve())


def test_audit_rejects_partial_template_pair(tmp_path: Path) -> None:
    project, _ = make_synthetic_official_shape(tmp_path)
    with pytest.raises(BackendError) as raised:
        audit_mmc_template(project, None)
    assert raised.value.code == "MMC_TEMPLATE_PAIR_INVALID"


def test_installed_example_contract_is_read_only() -> None:
    try:
        project, library = discover_official_mmc_template()
    except BackendError as error:
        if error.code == "MMC_TEMPLATE_NOT_FOUND":
            pytest.skip("PSCAD 4.6 MMC example is not installed")
        raise
    before = (sha256(project), sha256(library))
    report = audit_mmc_template(project, library)
    assert report["source_hashes"] == {"project": before[0], "library": before[1]}
    assert before == (sha256(project), sha256(library))
    if os.environ.get("PSCAD_MCP_MMC_ACCEPTANCE") == "1":
        assert report["pscad_version"] == "4.6.2"


def test_installed_example_exposes_station_and_pwm_hierarchy_roles() -> None:
    try:
        project, library = discover_official_mmc_template()
    except BackendError as error:
        if error.code == "MMC_TEMPLATE_NOT_FOUND":
            pytest.skip("PSCAD 4.6 MMC example is not installed")
        raise
    report = audit_mmc_template(project, library)
    roles = {item["role"] for item in report["role_bindings"]}
    assert report["compatible"] is True
    assert {"station_p", "station_vdc"} <= roles
    assert len([role for role in roles if role.startswith("pwm_converter_")]) >= 2
