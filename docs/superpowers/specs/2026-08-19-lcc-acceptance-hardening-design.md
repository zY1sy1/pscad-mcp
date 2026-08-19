# LCC Acceptance Hardening Design

**Date:** 2026-08-19

## Goal

Make the fixed LCC build path fail closed unless its outputs, live PSCAD
definitions, measurement contract, reference waveforms, companion library,
and final publication semantics are all explicitly verified. Preserve the
existing generic and HVDC tool contracts where they are unrelated.

## Scope

The work is split into three independently testable units:

1. **Runtime contract:** add output-channel creation, live definition
   inventory, and canonical/derived measurement validation.
2. **Evidence assets:** add production-asset validators that reject
   placeholder golden data or unverified companion libraries and require
   manifest/provenance evidence.
3. **Publication gate:** publish only from a staging directory. If the
   configured vendor save-as API cannot prove no-replace and TOCTOU safety,
   return `PUBLISH_REQUIRES_VERIFIED_ATOMIC_MOVE` and leave the candidate in
   evidence staging; never overwrite the final destination.

The licensed PSCAD 4.6.2 run remains an opt-in acceptance test. Missing
`mhrc.automation`, a missing license, or a missing PSCAD installation must
produce a structured capability result and must never be represented as a
successful accepted run.

## Runtime contract

`PscadBackend` gains these JSON-safe operations:

- `create_output_channel(project_name, channel)` creates exactly one declared
  channel and returns the normalized channel record after read-back.
- `get_definition_inventory(project_name)` returns a live snapshot containing
  scoped definition name, ports, parameter ranges/enums, and a SHA-256 hash of
  the canonical snapshot. A backend that cannot obtain this from the connected
  PSCAD instance raises `CAPABILITY_UNAVAILABLE`.

`PscadService` exposes corresponding wrappers with input validation and no
vendor objects. Existing `get_output_channels` remains inspection-only.

Output-channel records use the fields `canonical`, `path`, `call_id`, `units`,
`description`, and optional `source`. Canonical names must be unique. A
derived signal must additionally declare `sources`, `expression`, `units`,
and `time_domain`; it is not treated as an observed PSCAD channel.

## Evidence and asset gates

The production asset loader validates:

- blueprint selectors map one-to-one to canonical observed or derived signals;
- catalog identity and live inventory identity are recorded separately;
- `golden.json` contains non-placeholder samples, units, windows, and source
  hashes;
- the companion library has a provenance record, content hash, and an
  explicit licensed-load/compile/reference-run evidence record.

Asset validation can succeed for planning only when live evidence is absent,
but the acceptance/publish path must return `INCOMPLETE_ANALYSIS` with a
bounded list of missing evidence instead of treating packaged files as live
proof.

## Safe publication

The executor writes all generated files below a unique staging directory and
verifies the candidate before publication. Publication must first reserve the
final identity without replacing an existing file. Because the current public
vendor API does not prove that property, the default result is a structured
safe rejection. No code path may delete or overwrite an existing final
destination as a fallback.

## Error semantics

The following stable codes are required:

- `CAPABILITY_UNAVAILABLE`: vendor/runtime capability is not exposed or
  cannot be verified;
- `DEFINITION_INVENTORY_REQUIRED`: acceptance was requested without a live
  inventory snapshot;
- `MEASUREMENT_CONTRACT_INVALID`: duplicate or underspecified measurement;
- `ASSET_EVIDENCE_MISSING`: golden/library/provenance evidence is absent or
  placeholder;
- `PUBLISH_REQUIRES_VERIFIED_ATOMIC_MOVE`: staging succeeded but final
  no-replace publication cannot be proven.

## Compatibility

Existing planning, fake-service, and unlicensed unit tests remain usable.
Only the `accepted` and `publish` paths become stricter. Existing callers that
use duplicate result canonicals or expect an existing final path to be
overwritten must update their inputs and handle the new safe-rejection code.

## Verification strategy

Each unit follows TDD:

1. Add a focused failing regression test for the missing contract or unsafe
   behavior.
2. Implement the smallest backend/service/validator change.
3. Run focused tests, then the full nonlicensed suite.
4. Run licensed acceptance only when its explicit environment gate is
   present; otherwise report it as skipped/unverified.

