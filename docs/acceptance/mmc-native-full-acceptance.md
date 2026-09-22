# Native MMC full physical acceptance

The native half-bridge AVM gate runs one normal operating sequence, four
electrical fault scenarios, and an independent portable reload. A complete
suite returns `model_accepted=true` only when every required gate passes for
the same engineering request, derived parameters, producer hashes and revision.
Individual assembly/component reports continue to return `model_accepted=false`.

Run from a clean frozen checkout on the licensed PSCAD 4.6.2 host:

```powershell
$env:PSCAD_MCP_ACCEPTANCE='1'
$env:PSCAD_MCP_NATIVE_AVM_FULL_ACCEPTANCE='1'
& D:/pscad-mcp/.venv/Scripts/python.exe scripts/run_mmc_native_avm_full_acceptance.py --workspace-root D:/PSCAD-Workspace/mmc-native-full
```

Use `--request-json <absolute-path>` for a complete parameterized request.
The default request is 640 kV, 1000 MW, 60 Hz, zero reactive power and a 100 km
two-pole cable. Native planning derives valve modulation, arm storage and DC
control from the physical grid, transformer, cable and neutral network.
Inadequate explicit storage overrides are rejected rather than changed.

The suite runs each licensed case sequentially in its own Python process,
PSCAD instance and workspace. It confirms cleanup before starting another case.
It never attaches to or stops another task's PSCAD process. The subprocess
environment enables only the case opt-ins required by this explicitly requested
suite; no machine-wide environment setting is written.

Required cases are:

1. Measured blocked precharge and active conditioning, forward power, a
   commanded one-second reversal and reverse steady operation.
2. AC three-phase fault.
3. AC single-line-to-ground fault.
4. DC pole-to-pole fault.
5. DC pole-to-ground fault.
6. Fresh compilation and repeated physical checks in an independently loaded
   copy of the normal project, companion library and declared cable constants.

Normal acceptance includes DC and AC quantities, network identities, every
arm's energy/capacitance consistency, ripple and balance, circulating current,
PLL/dq tracking, integrators, insertion margin, saturation, startup readiness
and reversal dynamics. Fault acceptance additionally requires real shunt
current and voltage collapse, measured protection and contact actions,
bounded currents/capacitor voltages, symmetric pole recovery and restoration
of power/control within 0.5 seconds. Fault extrema are retained at every
EMTDC step so the OUT sampling interval cannot hide a short peak.

The half-bridge valves have **no intrinsic DC fault blocking capability**.
External AC/DC contacts, DC reactors, preinsertion resistors and native ZnO
arresters provide isolation. A damped neutral reactor network restores the
pole midpoint after ground faults. Device switching stress, switching
harmonics, individual submodule balance and thermal behavior are not modeled.

Each child keeps its immutable report, complete trace and native outputs.
Failed attempts remain evidence for diagnosis; they are never overwritten by
a later PASS. The suite report lists all child report hashes and, on PASS,
the accepted project/library paths and their final verified hashes.

The independent copy contains only declared model files and constants. It
copies no executable or prior solver output. Cable file references are rebound
to the copy's verified constants, with exact relocation records. The original
project, library, constants and reports retain their hashes.

The final native full-suite runner is distinct from the existing public
assembly diagnostic runner. A public build whose record is still `built`
must not be described as physically accepted or promoted by its parent.
