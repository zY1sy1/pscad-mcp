# Open-source Licensing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a complete MIT license and a clear attribution notice for the public fork without licensing third-party PSCAD material.

**Architecture:** Keep the legal metadata in root-level `LICENSE` and `NOTICE` files so GitHub users can find it immediately. Keep the README summary short and link to those authoritative files; explicitly separate contributor-licensed project material from third-party PSCAD documentation and trademarks.

**Tech Stack:** Markdown/plain-text legal metadata, Git, PowerShell verification

---

### Task 1: Add the MIT license and attribution notice

**Files:**
- Create: `LICENSE`
- Create: `NOTICE`

- [ ] **Step 1: Confirm the legal files do not already exist**

Run:

```powershell
if (Test-Path -LiteralPath .\LICENSE) { throw 'LICENSE already exists' }
if (Test-Path -LiteralPath .\NOTICE) { throw 'NOTICE already exists' }
```

Expected: command exits successfully with no output.

- [ ] **Step 2: Create the standard MIT license**

Create `LICENSE` with this exact content:

```text
MIT License

Copyright (c) 2026 pscad-mcp contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: Create the attribution and third-party notice**

Create `NOTICE` with this exact content:

```text
PSCAD MCP Notice

This repository is a modified fork of the pscad-mcp project maintained at:
https://github.com/SecchiAlessandro/pscad-mcp

The upstream package metadata identifies LL0pez20 as an author and declares
the project as MIT-licensed. Modifications in this fork are contributed by
zY1sy1 and other contributors. The Git history records the detailed provenance
of the upstream work and subsequent modifications.

The MIT License in LICENSE applies only to material for which the relevant
contributors have authority to grant those rights. It does not grant rights in
third-party software, documentation, trademarks, or other materials.

The directories docs/raw and docs/md contain API reference snapshots generated
from locally installed PSCAD automation libraries. Those snapshots are not
covered by this project's MIT License and remain subject to the applicable
third-party terms.

PSCAD is a trademark of Manitoba Hydro International Ltd. (MHI). This is an
independent community project and is not affiliated with, endorsed by, or
sponsored by MHI. All third-party names and trademarks belong to their
respective owners.
```

- [ ] **Step 4: Verify the new legal files**

Run:

```powershell
$license = Get-Content -LiteralPath .\LICENSE -Raw
$notice = Get-Content -LiteralPath .\NOTICE -Raw
if ($license -notmatch '^MIT License') { throw 'MIT heading missing' }
if ($license -notmatch 'pscad-mcp contributors') { throw 'collective copyright missing' }
if ($license -notmatch 'permission notice shall be included') { throw 'MIT preservation condition missing' }
if ($notice -notmatch 'SecchiAlessandro/pscad-mcp') { throw 'upstream attribution missing' }
if ($notice -notmatch 'docs/raw and docs/md') { throw 'third-party documentation boundary missing' }
if ($notice -notmatch 'not affiliated with, endorsed by, or') { throw 'non-affiliation disclaimer missing' }
```

Expected: command exits successfully with no output.

- [ ] **Step 5: Commit the legal files**

```powershell
git add -- LICENSE NOTICE
git commit -m "docs: add MIT license and attribution notice"
```

### Task 2: Link the legal files from the README

**Files:**
- Modify: `README.md:429`

- [ ] **Step 1: Replace the existing one-line license statement**

Replace:

```markdown
## License

MIT
```

with:

```markdown
## License and attribution

Project material contributed under this repository is available under the
[MIT License](LICENSE). This repository is a modified fork of
[`SecchiAlessandro/pscad-mcp`](https://github.com/SecchiAlessandro/pscad-mcp).

See [NOTICE](NOTICE) for upstream attribution, third-party material boundaries,
and the PSCAD/MHI non-affiliation statement.
```

- [ ] **Step 2: Verify both README links resolve**

Run:

```powershell
$readme = Get-Content -LiteralPath .\README.md -Raw
if ($readme -notmatch '\[MIT License\]\(LICENSE\)') { throw 'README LICENSE link missing' }
if ($readme -notmatch '\[NOTICE\]\(NOTICE\)') { throw 'README NOTICE link missing' }
if (-not (Test-Path -LiteralPath .\LICENSE)) { throw 'LICENSE link target missing' }
if (-not (Test-Path -LiteralPath .\NOTICE)) { throw 'NOTICE link target missing' }
```

Expected: command exits successfully with no output.

- [ ] **Step 3: Commit the README update**

```powershell
git add -- README.md
git commit -m "docs: link license and attribution notice"
```

### Task 3: Run final repository verification

**Files:**
- Verify: `LICENSE`
- Verify: `NOTICE`
- Verify: `README.md`

- [ ] **Step 1: Check whitespace and inspect the scoped diff**

Run:

```powershell
git diff --check HEAD~2..HEAD
git diff --stat HEAD~2..HEAD
git diff HEAD~2..HEAD -- LICENSE NOTICE README.md
```

Expected: `git diff --check` exits successfully; the diff contains only the two
new legal files and the README license-section update.

- [ ] **Step 2: Run the repository test suite**

Run:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass; licensed PSCAD acceptance tests may remain skipped by
their existing environment gates.

- [ ] **Step 3: Confirm the working tree is clean**

Run:

```powershell
git status --short --branch
```

Expected: no modified or untracked files; `main` is ahead of `origin/main` by
the new local commits.

