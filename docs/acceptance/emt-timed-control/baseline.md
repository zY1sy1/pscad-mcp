# EMTDC Timed Control Baseline

- Worktree: `D:/pscad-mcp/.worktrees/emt-timed-control`
- Branch: `codex/emt-timed-control`
- Baseline: `45069e213fb4f4895599d5269711c57b409db33f`
- Interpreter: `D:/pscad-mcp/.venv/Scripts/python.exe`
- `git merge-base --is-ancestor db65d74 HEAD`: exit 0.
- Initial focused suite: 38 passed in 1.54 s.
- Added contract regression RED: 22 failed, 7 passed. Failures exposed
  unverified/wall-clock capability acceptance, negative/invalid intervals,
  mismatched native acknowledgements, and the missing embedded adapter.
- Backend provider RED: 2 failed, 4 passed, exposing method-name-only proof.
- Polling interval/late-write/native restoration ACK RED: 3 failed, 17 passed.
- A2 focused suite: 67 passed in 0.94 s. Licensed verification remains pending.

## Immutable Inputs

| Input | SHA-256 |
| --- | --- |
| `C:/Program Files (x86)/PSCAD46/master.pslx` | `062a614e68d8b18541f42b6bac95e0777d4de6f923fdf3d558ca8ff40255d939` |
| `C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress/H_MMC_Mono_DC.pscx` | `1900be93877400fba228b1808a5310980d801b0260d7df998df6c5a2f6a035dd` |
| `C:/Users/Public/Documents/PSCAD/4.6/Examples/ModelsInProgress/intermediate.pslx` | `08466778704e547d7d9d80af99a48c09292dd3a51056ac26216c3913d5cc3a1b` |
| `D:/pscad-mcp/.venv/Lib/site-packages/mhrc/automation/project.py` | `bea9222bf249e1c59fcf732da5efa800399d2d69580e093547ec1967d9af7b1d` |

## Provider Evidence And Scope

Installed `mhrc.automation.project.ProjectCommands` has no
`schedule_timed_controls` or `get_simulation_time`. `run` delegates to
`execute_build_run_cmd`, and `get_run_status` posts an undocumented callback;
it is not a clock measured in seconds. Native scheduling therefore remains
unavailable. The backend now requires explicit verified EMTDC/seconds metadata
from a provider rather than inferring semantics from method names.

The embedded adapter initially supports only Main-page, orientation-0,
`master:const` and `master:var` scalar `Value` signals with a unique unconditional
Real OUT port. It uses the existing definition metadata parser. The original
instance/coordinates/output net remain, while an isolated definition supplies
the scheduled value from EMTDC TIME. A `master:pgb` Signl port is attached at
that exact OUT point. Definition and PGB owners are allocated before mutation
and are included in the schedule hash. Saved scripts, ports, parameters and
settings are reparsed and compared.

Official `Pref2`, Main owner `450184592`, is `master:var`, orientation 0,
initial `Value=-900`, with OUT at `(36, 0)` and scalar Real semantics. This
is suitable for command-waveform evidence. Converter parameters, power
reversal, AC/DC fault-type switches and shared nested modules remain unsupported
by this adapter. Their physical acceptance is not implied by timing evidence.

Polling accepts explicit point actions only. Interval input is rejected before
any write, and both native restore values and post-write clock/readback are
validated. A registered schedule alone is not evidence of a measured event.
