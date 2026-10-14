"""An idle API result with partially flushed OUT files is not completion."""

import os
import time

from pscad_mcp.hvdc.builders.mmc import pwm_runtime


def output(tmp_path, *, final_time=1.2, second=True):
    folder = tmp_path / "PWM.gf42"
    folder.mkdir()
    (folder / "PWM.inf").write_text(
        'PGB(11) Output Desc="last" Group="x" Max=1 Min=0 Units="1"\n'
    )
    (folder / "PWM_01.out").write_text(f"0 1\n{final_time} 1\n")
    if second:
        (folder / "PWM_02.out").write_text(f"0 1\n{final_time} 1\n")
    return folder


def completed(tmp_path):
    return pwm_runtime.complete_output_paths(
        tmp_path,
        "PWM",
        started_after=time.time() - 10,
        duration_s=1.2,
        output_step_s=0.00005,
    )


def test_fresh_partial_output_does_not_complete_an_idle_run(tmp_path):
    output(tmp_path, final_time=0.3)
    assert completed(tmp_path) == []


def test_missing_final_part_does_not_complete_an_idle_run(tmp_path):
    output(tmp_path, second=False)
    assert completed(tmp_path) == []


def test_every_output_part_reaches_the_requested_final_domain(tmp_path):
    output(tmp_path)
    assert len(completed(tmp_path)) == 2


def test_compile_metadata_can_precede_the_solver_start(tmp_path):
    folder = output(tmp_path)
    os.utime(folder / "PWM.inf", (1, 1))
    assert len(completed(tmp_path)) == 2
