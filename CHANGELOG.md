# Changelog

All notable changes to this project are documented here.

## [Unreleased]

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

### Verified

- PSCAD 4.6.2 x64 real acceptance passed on the licensed Windows installation.
- Modern PSCAD 5.x remains contract-tested only; this release does not claim
  real PSCAD 5.x end-to-end acceptance.
