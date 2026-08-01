# PSCAD Multi-Version COM Connection Design

> Superseded by `2026-08-01-pscad-dual-backend-design.zh-CN.md`. Real acceptance confirmed that PSCAD 4.6.2 requires the legacy `mhrc.automation` backend rather than the modern `mhi.pscad` launch protocol.

**Date:** 2026-08-01

## Goal

Make the PSCAD MCP connection path work with the locally installed PSCAD 4.6.2 while preserving PSCAD 5.x compatibility. The server must keep PSCAD calls serialized, retain bounded timeouts, and avoid leaving automation processes behind after failed acceptance tests.

## Confirmed failures

The current `PscadAdapter.attach_local()` calls `mhi.pscad.application()` through `RobustExecutor`. On Windows, that worker thread has no initialized COM apartment, so the WMI lookup used by `mhi.pscad` fails before connection or launch.

When the same call is made on the main thread, `mhi-pscad` 3.1.2 detects PSCAD 4.6.2 but refuses to launch it because the library's default minimum version is 5.0. Explicitly launching version 4.6.2 opens the application, confirming that version selection rather than installation is the second connection failure.

## Architecture

### COM-aware serialized executor

`RobustExecutor` remains the single boundary for PSCAD calls. Its one worker thread initializes Windows COM before executing PSCAD or WMI operations. Calls remain serialized because PSCAD automation proxies are not treated as generally thread-safe.

COM support is optional at import time so unit tests and non-Windows documentation workflows still start normally. If `pythoncom` is available, the worker initializes COM exactly once for its lifetime. Resetting an unhealthy executor creates a fresh initialized worker.

### Version-aware PSCAD adapter

`PscadAdapter` owns connection selection instead of delegating it to the version-dependent defaults of `mhi.pscad.application()`.

The adapter follows this order:

1. Try `mhi.pscad.connect()` to reuse an available automation-enabled instance.
2. If no instance is available, call `mhi.pscad.versions()`.
3. Apply optional configuration filters.
4. Select the highest installed version, preferring 64-bit when both architectures exist.
5. Call `mhi.pscad.launch()` with explicit `version`, `x64`, and `minimum` arguments.

This supports PSCAD 4.6.2 and 5.x without relying on the MHI package's changing default minimum version.

## Configuration

The connection layer recognizes these optional environment variables:

- `PSCAD_MCP_VERSION`: exact installed PSCAD version, such as `4.6.2` or `5.0.2`.
- `PSCAD_MCP_X64`: `true` or `false`; when omitted, 64-bit is preferred.
- `PSCAD_MCP_LAUNCH_TIMEOUT`: positive launch timeout in seconds.

Invalid values fail with an actionable configuration error. A requested version or architecture that is not installed reports the detected alternatives instead of silently choosing another installation.

## Ownership and cleanup

The adapter records whether it connected to an existing instance or launched a new one. Disconnecting the MCP clears proxies and resets an unhealthy executor, but it does not terminate PSCAD. The existing explicit `quit_pscad` tool remains the only normal operation that requests application termination.

Acceptance probes must close only instances they launch. On failure, test cleanup identifies processes by executable path and automation startup arguments before terminating them.

## Error handling

Connection failures distinguish among:

- missing `mhi-pscad`;
- invalid environment configuration;
- requested version not installed;
- no installed PSCAD version;
- existing-instance connection failure followed by launch failure;
- executor timeout or unhealthy state.

Errors retain the original exception as their cause while presenting a concise MCP-facing message.

## Testing

Automated tests use injected fake MHI and COM modules to cover:

- COM initialization before a worker executes its first call;
- COM initialization after executor reset;
- connecting to an existing instance before launching;
- automatic highest-version selection with 64-bit preference;
- explicit 4.6.2 selection;
- PSCAD 5.x selection;
- invalid configuration and unavailable requested versions;
- launch arguments including the selected version and minimum version.

After unit and registration tests pass, a bounded real-environment acceptance test invokes the MCP `get_local_pscad` path against PSCAD 4.6.2, reads health, license, projects, settings, and simulation-set names, then explicitly quits the test-launched instance. Process checks confirm no acceptance PSCAD or Python process remains.

## Non-goals

- No network transport or remote-host authentication changes.
- No project loading, building, saving, or simulation during this connection repair.
- No new modeling or analysis tools.
- No claim of PSCAD 5.x end-to-end validation when a 5.x installation is unavailable; its compatibility is contract-tested with fakes.
