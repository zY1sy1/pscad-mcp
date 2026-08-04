# Changelog

## [0.2.0] - 2026-08-04

- Delivery hardening: aligned package metadata, added development dependencies,
  portable configuration, release notes, and a Windows Python 3.10-3.12 CI matrix.
- Error-contract consistency: unlicensed simulation attempts now use the
  structured `NOT_LICENSED` MCP error payload.
- Runtime reliability: serialized service-level mutation workflows, added
  executor reset/retirement diagnostics, and exposed PSOUT skipped-channel
  warnings while preserving successful channels.
- PSCAD 4.6.2 workflow capabilities: added structured project messages,
  focused bounded PSOUT analysis, and a validated minimal parameter-grid path.
  Legacy layer limitations and launch-only semantics remain explicit.
