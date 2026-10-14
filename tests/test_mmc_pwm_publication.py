"""A published PWM library needs its actual relative compiler dependencies."""

import asyncio
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from pscad_mcp.hvdc.builders.mmc.engines.pwm import (
    _copy_library_support,
    library_support_files,
)
from tests.mmc_parametric_fakes import make_parametric_service


def test_publication_keeps_relative_native_library_dependencies(tmp_path):
    original = Path("C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress/intermediate.pslx")
    if not original.is_file():
        pytest.skip("The immutable library fixture is unavailable")
    support = library_support_files(original)
    stage = tmp_path / "candidate"
    stage.mkdir()
    library = stage / original.name
    shutil.copy2(original, library)
    _copy_library_support(original, stage)
    project = stage / "PWM.pscx"
    project.write_text('<project name="PWM" version="4.6.2"/>')
    service = make_parametric_service(tmp_path)

    async def native_linker(project_name):
        for item in support:
            dependency = tmp_path / item["relative_path"]
            assert dependency.is_file(), "Unresolved native link input: " + str(dependency)
            assert hashlib.sha256(dependency.read_bytes()).hexdigest() == item["sha256"]

    service.pscad_service.build_project = native_linker
    plan = SimpleNamespace(
        engine="detailed_pwm", source_paths={"library": str(original)},
        source_hashes={"library": hashlib.sha256(original.read_bytes()).hexdigest()},
        asset_hashes={item["path"]: item["sha256"] for item in support},
    )
    record = {
        "engine": "detailed_pwm", "final_path": str(tmp_path / "PWM.pscx"),
        "candidate_result": {"project_path": str(project), "library_path": str(library)},
    }
    assert asyncio.run(service._publish([record], [plan])) == [str(tmp_path / "PWM.pscx")]
