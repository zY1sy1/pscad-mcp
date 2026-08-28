# PSCAD MCP Horizontal Hardening Design

**Status:** Approved for implementation planning on 2026-08-27.

## Goal

Harden the PSCAD MCP delivery pipeline, tool contracts, runtime lifecycle,
documentation access, and large-result behavior without changing the names,
default parameters, or default result shapes of the existing 83 tools.

This work is horizontal infrastructure. It does not implement Blueprint
Builder, unified topology diagnostics, MMC dual-engine modeling, breaker model
construction, or licensed PSCAD acceptance already owned by other worktrees.

## Compatibility Contract

- All existing 83 tool names remain registered when no profile setting is
  present.
- Existing parameters retain their names and defaults.
- Existing calls made without new pagination parameters retain their result
  types and contents.
- Existing error payloads retain the top-level `error` envelope and stable
  backend fields.
- `get_pscad_capabilities` is additive, read-only, and always registered. The
  current full inventory therefore becomes 84 tools.
- `PSCAD_MCP_TOOL_PROFILE` is opt-in. Unset and `full` both select all groups.
- The work does not merge, push, publish, deploy, or run licensed acceptance.

## Architecture

### Canonical Tool Catalog

Add `pscad_mcp/tools/catalog.py` as the single source of truth for public MCP
tool metadata. An immutable `ToolSpec` records:

- stable tool name;
- group (`core`, `hvdc`, `lcc`, `parametric_lcc`, or `learning`);
- concise model-facing description;
- read-only, destructive, idempotent, and open-world annotations;
- backend support classification and a bounded limitation code where needed.

`register_tool` resolves the function name in the catalog and passes the
description and annotations to FastMCP. Registration fails during server
construction if a primary tool is absent from the catalog or a catalog entry
is registered twice. Tests compare exact name sets rather than copying numeric
counts into scripts.

Complex legacy `dict[str, Any]` inputs keep their runtime acceptance behavior.
Their tool and parameter descriptions document nested structure and examples.
Schema validation becomes stricter only where the existing service parser
already rejects the same invalid shape, so metadata cannot introduce a new
compatibility failure.

### Tool Profiles And Capability Discovery

`PSCAD_MCP_TOOL_PROFILE` accepts:

- no value or `full`, selecting every catalog group;
- `core`, selecting the original generic tools;
- a comma-separated set such as `core,hvdc,lcc`.

Whitespace is normalized, duplicate groups collapse, and unknown or empty
explicit selections raise a fixed `INVALID_TOOL_PROFILE` configuration error.
The error names only `PSCAD_MCP_TOOL_PROFILE`; it never echoes the supplied
value. `get_pscad_capabilities` remains registered for every profile.

The capability response is bounded and JSON-safe. It contains:

- selected profile and registered groups;
- registered and inactive tool names grouped deterministically;
- connection state, backend name, and PSCAD version when known;
- per-capability state: `supported`, `unavailable`, or `unknown`;
- stable limitation codes, never raw vendor objects or exception text.

Disconnected backend-dependent capabilities report `unknown`, not a guessed
success or failure. Static read-only server capabilities may report
`supported` without a PSCAD connection.

### Runtime Lifespan

Create a FastMCP lifespan that owns process-local runtime cleanup. Shutdown is
idempotent and follows this order:

1. stop accepting new domain jobs;
2. ask HVDC and builder services to mark active records `interrupted`;
3. cancel and await tracked asyncio tasks within a fixed deadline;
4. allow already submitted COM operations to reach their existing settlement
   boundary before releasing application-wide ownership;
5. close the lazy learning SQLite service;
6. disconnect the PSCAD backend, terminating PSCAD only when the backend
   already records that the server owns the process;
7. shut down the shared executor.

Every cleanup action is attempted even if an earlier action fails. Failures
are logged to stderr as bounded type names and stable operation labels.
Shutdown never returns a successful PSCAD acceptance claim.

Domain services expose small `shutdown()` methods rather than allowing
`main.py` to inspect private task dictionaries. A service with no initialized
instance performs no work.

### Documentation Storage And Resources

`DocumentationManager` becomes lazy and performs no filesystem writes in its
constructor or at module import. The default generated-document root is
`%LOCALAPPDATA%/pscad-mcp/docs`; an absolute
`PSCAD_MCP_DOCUMENTATION_DIR` override is supported. Invalid overrides produce
a fixed setting-name error without exposing the raw value.

Documentation synchronization runs through `asyncio.to_thread`. Generated
Markdown identifies the module and installed package version but omits source
file paths. Atomic replacement prevents partially written documents.

The 62 generated files under `docs/raw` and `docs/md` are removed from the Git
index and those directories are ignored. They remain recoverable from Git
history and regenerable from a locally installed PSCAD automation package.
`NOTICE` continues to state that generated vendor documentation is governed by
third-party terms.

Expose generated Markdown through the resource template
`pscad-docs://modules/{module_name}`. Existing `sync_documentation`,
`list_documentation`, and `read_documentation` tools remain public and retain
their no-new-argument behavior.

### Compatible Result Bounds

The following list tools gain optional `offset: int = 0` and
`limit: int | None = None` parameters while retaining list results:

- `list_projects`;
- `find_components`;
- `get_project_definitions`;
- `list_canvas_components`;
- `list_documentation`.

The service obtains the existing deterministic full result, validates
`offset >= 0` and `1 <= limit <= 1000` when supplied, then returns the selected
slice. Omitting both parameters returns the complete original list.

`read_documentation` gains `offset: int = 0` and
`max_chars: int | None = None`, preserving a string result. Explicit
`max_chars` is limited to `1..100000`. Invalid bounds use the stable
`INVALID_ARGUMENT` error contract. Resource clients use URI query parameters
for equivalent bounded reads.

## Delivery And Repository Hygiene

Keep one Windows GitHub Actions workflow. Its base dependency matrix covers
Python 3.10, 3.11, 3.12, 3.13, and 3.14 without installing licensed vendor
packages. The workflow runs:

- the full non-licensed pytest suite;
- isolated wheel build and install verification;
- exact catalog/server name-set comparison;
- `compileall`;
- `pip check`;
- a narrow Ruff correctness gate covering syntax errors, undefined names, and
  invalid control flow;
- a tracked-artifact check for bytecode, caches, generated documentation, and
  temporary work directories.

Remove the 14 currently tracked `.pyc` files from the index. Ignore rules stay
in place, and the artifact test prevents regression. Package verification
imports the canonical catalog and never embeds `77`, `83`, `84`, or another
inventory count.

Update English and Chinese documentation plus the Unreleased changelog. Do
not choose a formal release version while active feature branches remain
unintegrated.

## Error Handling

New stable codes are limited to:

- `INVALID_TOOL_PROFILE` for startup profile parsing;
- `DOCUMENTATION_CONFIG_INVALID` for documentation-root configuration;
- `SHUTDOWN_INCOMPLETE` for a bounded cleanup summary when invoked through a
  testable runtime lifecycle API.

Tool argument failures continue to use `INVALID_ARGUMENT`. Capability results
use status records rather than exceptions for expected backend absence.
Unexpected errors pass through the existing bounded `error_payload` path.

## Test Strategy

Each reproduced root cause follows an independent red-green cycle and commit:

1. package verification reproduces the `77` versus current inventory drift;
2. repository tests detect duplicate workflows and tracked bytecode;
3. catalog tests detect missing descriptions, duplicate names, and absent
   safety annotations;
4. profile tests prove full-default compatibility and fixed invalid-setting
   errors;
5. capability tests cover disconnected, legacy, and modern states without
   vendor objects;
6. lifespan tests prove cleanup order, idempotence, bounded cancellation, and
   ownership preservation;
7. documentation tests prove no import-time writes, local-state defaults,
   path redaction, atomic generation, resource reads, and async dispatch;
8. pagination tests prove unchanged defaults, deterministic slices, and bound
   rejection;
9. CI and packaging tests prove one workflow and installed-wheel catalog
   parity.

Final verification runs the complete non-licensed suite, package verification,
Ruff correctness rules, `compileall`, `pip check`, `git diff --check`, and a
clean tracked-artifact check. Licensed PSCAD tests remain skipped unless their
existing explicit opt-in variables are set.

## Integration Order

The hardening branch starts from current `main` and commits one root cause at
a time. Before integration, regenerate the catalog against the merged
Blueprint Builder, topology, and MMC tool modules and resolve metadata entries
without changing their domain behavior. Large backend-file decomposition is
deferred until those feature branches are integrated because doing it now
would create avoidable cross-worktree conflicts.

## Deferred Evidence

Real PSCAD 5.x end-to-end acceptance remains `needs_evidence`. The current
machine does not provide a licensed 5.x environment, so this work neither
creates a speculative acceptance runner nor changes the documented
contract-tested-only status.
