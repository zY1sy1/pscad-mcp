# PSCAD MCP v2 Design

**Date:** 2026-08-01

## Goal

Turn the existing PSCAD MCP repository into a Codex-compatible, Windows-first MCP server that is safe to install, uses the current `mhi-pscad`/`mhi-psout` APIs, and exposes a small set of reliable core operations before expanding coverage.

## Scope

This iteration keeps the repository's existing FastMCP tool organization and documentation snapshots, but introduces a single PSCAD adapter boundary. The adapter owns connection health, API-version-sensitive calls, result serialization, and file/path validation. Tool modules call the adapter rather than reaching into `mhi.pscad` directly.

The first reliable tool set is:

- connect/status/disconnect;
- load/list projects;
- run/status/pause/stop a project;
- find/read/update component parameters with real range validation;
- list/run/add tasks to simulation sets through the `PSCAD` object;
- read project output;
- read `.psout` traces through `mhi.psout.File`.

Canvas and project-creation tools remain registered, but their existing API calls are preserved only where the installed API contract matches. Destructive operations continue to require explicit user intent in the caller workflow; the server adds path validation and clear operation names.

## Compatibility

- Pin `mcp` to the 1.x API used by `mcp.server.fastmcp`.
- Support `mhi-pscad` 3.x and `mhi-psout` 1.x.
- Make missing PSCAD packages a startup-safe condition, with actionable runtime errors.
- Use the Codex stdio transport configuration documented in the repository.

## Safety and reliability

- All PSCAD calls go through one serialized executor.
- Timeouts return an error and mark the connection unhealthy; later calls attempt a clean reconnect rather than silently queueing behind a stuck call.
- Project and output file paths are normalized and restricted to an explicitly configured workspace root when one is set.
- PSOUT reads cap the number of returned samples to avoid flooding the MCP response.
- Tool responses are plain JSON-compatible values.

## Non-goals

- No automatic installation or modification of the user's global Codex configuration.
- No claim of end-to-end PSCAD validation without a licensed PSCAD installation.
- No rewrite of every canvas helper in this iteration.
