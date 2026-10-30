# HVDC timeout classification correction — 2026-10-31

The [Python 3.11 CI job](https://github.com/zY1sy1/pscad-mcp/actions/runs/41091069465/job/124184773356) at `f73f8ce5158f577f5e548320ecd1a71e847d92af` reported one failed test, 4044 passed and 190 skipped. Python 3.10 and 3.12–3.14 passed. The failed case was `test_clock_failure_stops_only_its_project_and_releases_scenario[timeout]`: it expected `timed_out` but received `failed`.

The polling liveness timer raised a generic timing-contract error when it expired before the scenario worker's asyncio deadline. The same deadline crossing therefore produced a different status depending on timer ordering. A deterministic reproduction advances only the dispatcher's monotonic clock, leaving the worker deadline pending. Before the fix, both new regression cases fail; project-scoped stopping and reservation release succeed before the classification assertion fails.

The dispatcher now raises `asyncio.TimeoutError` for its elapsed liveness deadline. The existing scenario timeout handler records `HVDC_SCENARIO_TIMEOUT`, stops the target project and releases its reservation when containment is confirmed. Stalled/backward simulation clocks remain timing-contract failures, and event timing bounds are unchanged.

Local validation on Python 3.13: all 105 tests across `test_hvdc_timing.py`, `test_hvdc_scenario_strict.py`, `test_hvdc_scenario_containment.py`, `test_hvdc_scenarios.py` and `test_hvdc_backend_timing_providers.py` pass. Ruff correctness checks pass. Cross-version Windows CI is attached to the fix commit.

This is an orchestration-status correction. No PSCAD model inputs, physical thresholds, acceptance verdicts or historic evidence records are rewritten, and these offline checks do not constitute a new licensed model acceptance.
