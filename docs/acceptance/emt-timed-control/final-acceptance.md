# Independent EMTDC Timing Acceptance

Producer revision: `216c18ba187f0b86194c4f91dfd3c19d1b281714`.
Branch: `codex/emt-timed-control`; baseline:
`45069e213fb4f4895599d5269711c57b409db33f`.

The independent timing scope is accepted. Joint MMC fault-physics acceptance
remains a separate integration task. The verified official-template channel is
`Pref2`, role `control_command`; it is not a fault-active channel.

## Final Gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Full offline suite | 2517 passed, 50 skipped; 50.68 s | `python -m pytest -q --tb=short` at producer revision |
| Original minimum case | PASS; 14.94 s including independent reload | [acceptance.json](D:/PSCAD-Workspace/emt-timed-control/minimal-5314c22dd448410880833837817c4736/acceptance.json) |
| Official PWM command | PASS; 36.92 s including independent reload | [acceptance.json](D:/PSCAD-Workspace/emt-timed-control/pwm-67d0ec55df634e95958e4af7bdbab6f3/acceptance.json) |
| Independent specification and quality review | PASS | Final review of producer revision, including owned-attach failure handling |
| Targeted Ruff and diff check | PASS | New adapter/tests/timing lint and `git diff --check` |

All four actual runs contain 5001 samples over `[0, 0.05]` seconds, with the
two measured edges at 0.02 and 0.03 seconds. Both edge errors are zero against
the predeclared 20 us maximum. The integration and output steps are 10 us.
The high/active interval contains 1000 samples. The minimum command is
`0 -> 1 -> 0`; the official Pref2 command is `-900 -> -800 -> -900 MW`.

| Case | Python PID | Owned PSCAD PID | Owned Processes Remaining |
| --- | --- | --- | --- |
| Minimum initial | 32664 | 37344 | none |
| Minimum saved-project reload | 43916 | 11752 | none |
| PWM initial | 12704 | 2124 | none |
| PWM saved-project reload | 45444 | 20040 | none |

Each reloaded case starts from a byte-identical copy of the first run's saved
project, with a separate Python process, PSCAD instance, compiler output
directory, and output evidence. The first saved project remains unchanged.
Both native-capability inspection and the public non-embedded scenario path
record `HVDC_TIMED_CONTROL_UNAVAILABLE`; no native API capability is fabricated.

## Handoff And Indexes

The canonical [schedule-handoff.json](schedule-handoff.json) contains all
original input and compiler-support hashes, scenario-source identity, planned
targets/ports, saved readback, and actual INF/INFX bindings and output hashes.
Its schedule SHA-256 is
`5f799315640b6760c86f345b3ce791d77301ab2b6cc832a96ca25ad036f5e917`.

- [Minimum first output index](D:/PSCAD-Workspace/emt-timed-control/minimal-5314c22dd448410880833837817c4736/output-index.json)
- [Minimum reload output index](D:/PSCAD-Workspace/emt-timed-control/minimal-5314c22dd448410880833837817c4736/reload/output-index.json)
- [PWM first output index](D:/PSCAD-Workspace/emt-timed-control/pwm-67d0ec55df634e95958e4af7bdbab6f3/output-index.json)
- [PWM reload output index](D:/PSCAD-Workspace/emt-timed-control/pwm-67d0ec55df634e95958e4af7bdbab6f3/reload/output-index.json)

The original Master, project, library and six declared compiler libraries
retain their planned hashes. OUT freshness, complete part sets, INFX
owner/instance/part/index/dimension/units, INF correspondence, shared time
domains and hashes before/after reading are validated. Source and derived
native names are isolated before loading; unknown or unsupported sequences
fail closed.

Licensed commands used the repository interpreter
`D:/pscad-mcp/.venv/Scripts/python.exe`, process-local
`PSCAD_MCP_ACCEPTANCE=1`, `PSCAD_MCP_ACCEPTANCE_CONCURRENT=1`, and
`PSCAD_MCP_WORKSPACE=D:/PSCAD-Workspace/emt-timed-control`. The PWM command also
set `PSCAD_MCP_MMC_ACCEPTANCE=1`. Minimum and PWM tests ran in separate Python
processes with `-k minimal` and `-k official`, respectively.

The prior failed and intermediate successful attempts remain in the evidence
workspace. They are diagnostic history, not substituted for these final
producer-revision gates. No main-branch merge, push, LCC model change, or B
fault-physics acceptance is implied by this delivery.
