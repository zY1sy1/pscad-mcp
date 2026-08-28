# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Changed

- Horizontal hardening preserves the 83-tool compatibility surface while adding
  one always-on capability discovery tool, complete tool annotations, opt-in
  tool profiles, and compatible pagination.
- Runtime lifecycle cleanup is now idempotent and bounded across repeated MCP
  lifespan entry, executor work, background tasks, and shutdown.
- Local documentation is generated lazily in user state, can be served through
  MCP resources, and is no longer tracked as generated repository output.

- Parameterized LCC execution now carries reviewed real-template selectors through
  deterministic plans, validates bindings before acquiring a workspace lease,
  stages PSCX changes atomically, and records bounded source/staging/read-back
  evidence. The PSCAD lifecycle remains fail-closed without licensed compile,
  run, and output evidence; no real parameterized `PASS` is claimed here.
- Added bounded parameterized LCC acceptance gates for compile/project hashes,
  `.out`/`.psout` hashes, exact Gamma/Alpha, pole voltage/current, neutral and
  return-current selectors, units, and derived-parameter evidence. Operating-mode
  copies receive independent evidence directories and strict EMTDC-time switching
  remains required.

- Added parameterized LCC foundation records, deterministic rating derivation,
  monopole/bipole topology contracts, operating-mode schedule validation,
  read-only template auditing, lifecycle service composition, and six guarded
  parametric LCC MCP tools. Licensed PSCAD acceptance remains opt-in.

- Added four fixed CIGRE LCC builder tools for deterministic planning,
  staged construction, structural validation, and acceptance reporting. The
  first release is limited to the single-pole PSCAD 4.6.2 benchmark and does
  not claim licensed autonomous acceptance until the real opt-in test passes.
- LCC planning now fails closed without live PSCAD definition inventory;
  output-channel creation, final-project identity, waveform ownership, asset
  fingerprints, and acceptance-report evidence are checked explicitly.
- The compatibility inventory is 83 compatibility tools: 60 generic tools,
  two topology tools, ten HVDC tools, three learning tools, four fixed LCC tools,
  and six parametric LCC tools. With the always-on
  `get_pscad_capabilities` discovery tool, the current total is 86.

- HVDC strict control now supports explicit backend timing and output-channel
  provider hooks, bounded simulation-clock polling, stalled-clock detection,
  stable event IDs, and duplicate-event rejection.
- Expanded VSC 2-level and MMC profiles with explicit v2 result selectors,
  unit-aware metric roles, and read-only control boundaries.

- Legacy PSCAD 4.6.x now launches a visible managed automation window by
  default, rejects pre-existing external PSCAD processes before launch, and
  reports bounded owned-session diagnostics.
- Application-wide pause/stop commands now require the requested case to be
  the sole active case. Legacy pause is command-tracked because the 4.6.2 GUI
  displays `Paused.` while its status API still reports `running`; stop retains
  terminal-state verification. Modern stop prefers the vendor
  `stop_single_project` entry point.
- Component enable/disable behavior is unchanged; the tested PSCAD 4.6.2 layer
  limitation remains explicit.
- File operations now fail closed with `WORKSPACE_NOT_CONFIGURED` unless
  `PSCAD_MCP_WORKSPACE` is configured.
- Added the explicit development-only `PSCAD_MCP_ALLOW_UNSCOPED_PATHS` escape
  hatch and a built-package installation smoke test.
- Added silent learning with scalar local evidence, generated
  `improvement-backlog.md`, three learning tools, narrowly defined critical
  reminders, privacy exclusions for parameters, results, paths, prompts,
  exception text, details, and tracebacks, and a 73-tool inventory
  (`60` generic + `10` HVDC + `3` learning).
- Added a separate ten-tool HVDC domain layer with read-only XML evidence
  scanning, deterministic LCC/VSC/MMC classification, profile mappings,
  confirmed scenario orchestration, bounded PSOUT metrics, and Breaker-family
  regression fixtures. The original 60 generic tool names remain unchanged.

### Planned

- Real PSCAD 5.x end-to-end acceptance after a licensed 5.x environment is available.

## [0.2.0] - 2026-08-03

### Added

- Seven simulation set tools for workspace-level create, inspect, task
  listing, task removal, parameter reads, parameter writes, and set removal.
- A stable 60-tool MCP inventory with backend contract coverage.
- Portable Codex configuration template and Windows installation guidance.
- Windows CI coverage for Python 3.10, 3.11, and 3.12.

### Changed

- Destructive simulation-set operations require explicit confirmation.
- Simulation-set mutations verify vendor responses and read back postconditions.
- Task parameter writes use the PSCAD 4.6.2 allowlist and bounded restoration.
- Package metadata is versioned as 0.2.0.
- Delivery hardening aligned package metadata, added development dependencies,
  portable configuration, release notes, and a Windows Python 3.10-3.12 CI matrix.
- Unlicensed simulation attempts use the structured `NOT_LICENSED` MCP error
  payload.
- Runtime reliability includes serialized service mutations, executor reset and
  retirement diagnostics, and PSOUT skipped-channel warnings.
- PSCAD 4.6.2 workflow capabilities include structured project messages,
  bounded PSOUT analysis, and a validated minimal parameter-grid path.

### Verified

- PSCAD 4.6.2 x64 real acceptance passed on the licensed Windows installation.
- Modern PSCAD 5.x remains contract-tested only; this release does not claim
  real PSCAD 5.x end-to-end acceptance.
