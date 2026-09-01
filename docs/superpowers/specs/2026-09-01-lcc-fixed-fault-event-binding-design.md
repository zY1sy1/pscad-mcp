# Fixed LCC Fault/Event Binding Design

**Date:** 2026-09-01

**Scope:** Preflight and planning contract for fixed LCC inverter AC disturbance

**Goal:** Make the fixed LCC fault/event capability explicit and fail closed until a complete, auditable event binding exists in the blueprint and live PSCAD inventory.

## Current Gap

The fixed LCC companion currently exposes converter controls and enable signals but no fault timer, three-phase fault shunt, event output, or dynamic fault channel. The official template contains `master:tfault` and `master:tpflt`, but its protected definition body cannot be copied into the repository-authored companion. The builder therefore must not claim WP1C dynamic capability from the existing no-fault topology.

## Design

Add a pure `fault_event.py` module with:

- `FixedLccFaultEvent` immutable request data for event kind, target bus, EMTDC time, duration, and phase mask.
- `validate_fixed_lcc_fault_event()` enforcing positive finite timing, a three-phase mask, the canonical `inverter_ac_bus` target, and an explicit event kind.
- `inspect_fixed_lcc_fault_capability()` that accepts the parsed blueprint, catalog, and live definition inventory and returns a structured `PASS` or `INCOMPLETE_ANALYSIS` result. It requires exactly one `master:tfault`-compatible timer, one `master:tpflt`/equivalent three-phase shunt, a connected inverter AC bus, and a required `Fault/LCC Fault Active` output declaration. Missing or ambiguous bindings are reported by reason and never inferred.

The planner will call this gate only for a future `wp1c_dynamic` verification profile. Existing `wp1b_smoke` and `full_acceptance` behavior remains unchanged. No component or net is added until the gate can be satisfied by live PSCAD inventory and a reviewed topology design.

## Testing

- Validate accepted/rejected event timing, phase masks, target names, and event kinds.
- Confirm the current fixed blueprint returns `INCOMPLETE_ANALYSIS` with explicit missing-binding reasons.
- Confirm a synthetic complete inventory passes the preflight without touching files or PSCAD.
- Confirm the planner rejects `wp1c_dynamic` when the gate is incomplete and does not alter existing profiles.

## Exclusions

- No copying of official `tfault`/`tpflt` definition bodies.
- No licensed simulation or golden generation.
- No promotion of baseline status.
- No electrical topology mutation in this step.
