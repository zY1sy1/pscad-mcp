import asyncio
import time
from pathlib import Path

from pscad_mcp.core.path_policy import PathPolicy
from pscad_mcp.core.service import PscadService


def test_output_discovery_matches_pscad_normalized_gf_directory(tmp_path: Path) -> None:
    project = tmp_path / "MMC_CASE_pwm__pwm-0.pscx"
    project.write_text("<project />", encoding="ascii")
    generated = tmp_path / "MMC_CASE_pwm__pwm_0.gf42"
    generated.mkdir()
    output = generated / "MMC_CASE_pwm__pwm_0_01.out"
    output.write_bytes(b"waveform")
    stamp = time.time() - 1.0
    output.touch()

    service = PscadService(
        lambda: object(),
        path_policy=PathPolicy(workspace_root=str(tmp_path)),
    )
    discovered = asyncio.run(
        service.discover_output_files(
            str(project),
            started_after=stamp,
            max_files=10,
        )
    )

    assert discovered == [str(output.resolve())]
