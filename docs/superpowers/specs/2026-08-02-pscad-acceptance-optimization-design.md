# PSCAD Acceptance Optimization Design

## Goal

Reduce misleading PSCAD 4.6.2 acceptance noise while preserving the existing
fallback behavior and safety guarantees.

## Scope

This change covers two observed behaviors from the real 4.6.2 acceptance:

1. `get_component_ports` invokes the legacy `get-port-location` command before
   using static definition metadata, even when the vendor command is known to
   return an unsuccessful response for the component. The fallback succeeds,
   but the vendor library prints repeated failure diagnostics.
2. `mhrc.automation` waits five seconds inside its own `quit()` implementation
   and may force-terminate PSCAD. The repository must verify the resulting
   process state and expose a clear cleanup outcome without modifying the
   installed vendor package.

The PSCAD 4.6.2 launch-only limitation and its unsupported layer-based disable
capability are not changed by this work.

## Design

For legacy port lookup, resolve definition metadata before querying the vendor
port-location command whenever the component has a usable scoped definition.
Use static port offsets plus the saved/live component orientation and location
as the primary path. Retain `get-port-location` as a fallback only when static
metadata is unavailable, so components with incomplete library metadata keep
their current compatibility behavior. Preserve the existing normalized
`PortInfo` output and skip only ports whose location cannot be resolved.

For legacy shutdown, keep `app.quit()` as the only vendor shutdown call. After
it returns, check the application/process liveness when the proxy exposes a
safe liveness method, and retain the existing ownership cleanup in
`disconnect()`. Do not access or mutate private vendor process state and do not
hide unrelated vendor exceptions. Tests will verify that a successful quit is
reported as cleaned up and that disconnect still clears ownership metadata.

## Error Handling

Static metadata failures remain non-fatal and continue to the vendor lookup
path. Vendor lookup failures remain non-fatal only when the existing static
fallback can resolve the port. Shutdown exceptions continue to propagate so a
real cleanup failure cannot be reported as success.

## Verification

- Add a regression test proving static port metadata avoids the legacy vendor
  command when orientation and location are available.
- Add a regression test proving legacy quit clears the backend connection and
  ownership state after the vendor quit call.
- Run the full unittest suite, compile check, dependency check, and 53-tool
  registration check.
- Run the licensed PSCAD 4.6.2 acceptance script and require
  `ACCEPTANCE_COMPLETE=PASS` and `ACCEPTANCE_FINAL_PROCESS_COUNT=0`.

## Non-Goals

- No direct attachment support for PSCAD 4.6.x.
- No attempt to force-enable disabled-layer commands rejected by the vendor
  Automation Library.
- No edits inside `.venv` or the installed vendor packages.
