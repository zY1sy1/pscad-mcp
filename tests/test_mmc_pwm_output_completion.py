"""An idle API response cannot finalize partially written EMTDC output."""

from pscad_mcp.hvdc.builders.mmc import pwm_runtime


def test_idle_output_requires_every_part_to_reach_the_requested_end(tmp_path):
    first, second = tmp_path / "PWM_01.out", tmp_path / "PWM_02.out"
    first.write_text("0 1\n3.2 2\n")
    second.write_text("0 1\n0.2 2\n")
    assert not pwm_runtime.outputs_cover_duration([first, second], 3.2, 0.00005)
    second.write_text("0 1\n3.2 2\n")
    assert pwm_runtime.outputs_cover_duration([first, second], 3.2, 0.00005)
    assert not pwm_runtime.outputs_cover_duration([], 3.2, 0.00005)
