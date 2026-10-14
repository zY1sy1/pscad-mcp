# Native overhead-line MMC AVM

User requested implementation on 2026-10-14 after selecting this next scope.
Work is isolated on `codex/mmc-overhead-avm` from `a8fce2d`.

The request parser supports `overhead_line`, but the public native AVM engine
rejects it and its producer, loss planning and receipt assume a coax cable.

1. Reproduce that rejection with a public-planner regression.
2. Audit the installed two-conductor DCTL geometry. Generate fresh native
   frequency-dependent phase constants for the requested total length, bind
   immutable inputs and validate coefficient, fitting and output evidence.
3. Connect a four-terminal overhead module using verified Master interfaces.
   Preserve the existing converter, control, protection and physical criteria.
4. Route public planning and execution by the requested medium. Use actual
   bundle DC resistance without rating scaling and native phase capacitance.
5. Verify focused regressions, source immutability, portable constants and
   clean frozen revisions. Run the opt-in normal/four-fault/independent-reload
   suite on a 200 km, 640 kV, 1000 MW, 60 Hz full-bridge request, then the
   matching 500 kV/750 MW/+100 MVAr and 800 kV/1200 MW/−120 MVAr/50 Hz matrix.
6. Record exact accepted requests, revisions and reports. Preserve earlier
   failures and keep electrical scope boundaries explicit.

PSCAD 5.x, detailed PWM, arbitrary tower geometries, intrinsic blocking without
external isolation, device stress and individual cell balance are outside
this task. Existing license opt-ins and physical thresholds remain required.
