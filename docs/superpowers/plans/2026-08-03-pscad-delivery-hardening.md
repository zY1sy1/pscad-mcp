# PSCAD MCP Delivery Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Prepare the verified PSCAD 4.6.2/60-tool implementation for reviewable remote delivery, reproducible Windows CI, portable installation, and a versioned release candidate without claiming PSCAD 5.x real acceptance.

**Architecture:** Keep production behavior unchanged. Add delivery-only metadata and automation around the existing package: a CI workflow invokes the same test and static checks used locally; a checked-in Codex TOML template documents portable paths; README files reference the template rather than a machine-specific configuration; version and changelog describe the current 0.2.0 release candidate. Cleanup is performed only after validating exact detached worktree paths.

**Tech Stack:** Python 3.10–3.12, pytest, setuptools/pyproject.toml, GitHub Actions on \`windows-latest\`, Codex TOML, PowerShell, Git.

---

### Task 1: Add reproducible development dependencies

**Files:**
- Modify: \`pyproject.toml\`
- Test: \`tests/test_packaging_metadata.py\`

- [ ] **Step 1: Inspect existing metadata and test conventions**

Run:

\`\`\`powershell
Get-Content pyproject.toml -Raw
rg -n "pyproject|project\\.version|optional-dependencies|pytest" tests pscad_mcp
\`\`\`

Expected: the project has base and Windows optional dependencies, no \`dev\` extra, and the current version is \`0.1.0\`.

- [ ] **Step 2: Write a failing metadata test**

Add \`tests/test_packaging_metadata.py\` with a test that parses \`pyproject.toml\` using \`tomllib\` and asserts:

\`\`\`python
assert project["version"] == "0.2.0"
assert "pytest" in project["optional-dependencies"]["dev"]
\`\`\`

Run:

\`\`\`powershell
& .\\.venv\\Scripts\\python.exe -m pytest tests/test_packaging_metadata.py -q
\`\`\`

Expected: FAIL because the version and \`dev\` extra are not yet present.

- [ ] **Step 3: Update package metadata**

In \`pyproject.toml\`, change \`version = "0.1.0"\` to \`version = "0.2.0"\` and add:

\`\`\`toml
dev = [
    "pytest>=8,<9",
]
\`\`\`

Keep the existing \`windows\` extra unchanged.

- [ ] **Step 4: Run the focused test**

Run:

\`\`\`powershell
& .\\.venv\\Scripts\\python.exe -m pytest tests/test_packaging_metadata.py -q
\`\`\`

Expected: PASS.

- [ ] **Step 5: Commit the metadata change**

\`\`\`powershell
git add pyproject.toml tests/test_packaging_metadata.py
git commit -m "build: prepare 0.2.0 development metadata"
\`\`\`

### Task 2: Add portable Codex configuration and installation documentation

**Files:**
- Create: \`config.example.toml\`
- Modify: \`README.md\`
- Modify: \`docs/zh-CN/README.md\`
- Test: \`tests/test_config_example.py\`

- [ ] **Step 1: Write a failing config-template test**

Create \`tests/test_config_example.py\` that parses \`config.example.toml\` with \`tomllib\` and asserts:

\`\`\`python
server = config["mcp_servers"]["pscad"]
assert server["type"] == "stdio"
assert server["args"] == ["-m", "pscad_mcp.main"]
assert "PSCAD_MCP_BACKEND" in server["env"]
assert "D:\\pscad-mcp" not in path_text
assert "D:\\PSCAD-Workspace" not in path_text
\`\`\`

Run:

\`\`\`powershell
& .\\.venv\\Scripts\\python.exe -m pytest tests/test_config_example.py -q
\`\`\`

Expected: FAIL because the template does not exist.

- [ ] **Step 2: Add a path-neutral TOML template**

Create \`config.example.toml\` with a generic Windows path such as \`C:/path/to/pscad-mcp/.venv/Scripts/python.exe\`, \`type = 'stdio'\`, \`args = ['-m', 'pscad_mcp.main']\`, timeouts, and the environment keys \`PSCAD_MCP_BACKEND\`, \`PSCAD_MCP_VERSION\`, \`PSCAD_MCP_X64\`, \`PSCAD_MCP_LAUNCH_TIMEOUT\`, and \`PSCAD_MCP_WORKSPACE\`. The template must not contain the maintainer's \`D:\\pscad-mcp\` or \`D:\\PSCAD-Workspace\` paths.

- [ ] **Step 3: Update English installation instructions**

In \`README.md\`:

- replace the \`Install this MCP server on D:\` heading with a path-neutral Windows installation heading;
- use \`<repo-root>\` and \`$venvPath\` PowerShell variables in commands;
- add a “Codex configuration template” subsection pointing to \`config.example.toml\`;
- state that the user must replace the interpreter and workspace paths;
- state that a new Codex task is required after config changes;
- retain the explicit note that PSCAD 5.x is contract-tested only.

- [ ] **Step 4: Update Chinese installation instructions**

In \`docs/zh-CN/README.md\`, mirror the same path-neutral workflow, point to \`config.example.toml\`, explain the two paths that users must replace, and retain the accurate 4.6.2-real/5.x-contract-only distinction.

- [ ] **Step 5: Run focused documentation/config checks**

Run:

\`\`\`powershell
& .\\.venv\\Scripts\\python.exe -m pytest tests/test_config_example.py -q
git diff --check
\`\`\`

Expected: PASS and no whitespace errors.

- [ ] **Step 6: Commit the configuration documentation**

\`\`\`powershell
git add config.example.toml README.md docs/zh-CN/README.md tests/test_config_example.py
git commit -m "docs: add portable Codex configuration template"
\`\`\`

### Task 3: Add versioned change history

**Files:**
- Create: \`CHANGELOG.md\`
- Test: \`tests/test_changelog.py\`

- [ ] **Step 1: Write a failing changelog test**

Create \`tests/test_changelog.py\` asserting that \`CHANGELOG.md\` contains \`## [0.2.0]\`, “60”, “simulation set”, “PSCAD 4.6.2”, and an explicit “PSCAD 5.x” contract-test limitation.

Run:

\`\`\`powershell
& .\\.venv\\Scripts\\python.exe -m pytest tests/test_changelog.py -q
\`\`\`

Expected: FAIL because the changelog does not exist.

- [ ] **Step 2: Write the 0.2.0 changelog**

Add a Keep a Changelog-style file with an \`[Unreleased]\` section and a \`[0.2.0] - 2026-08-03\` section. Record the seven simulation-set tools, 60-tool total, confirmation and postcondition safety behavior, 4.6.2 real acceptance, Modern contract-only status, CI/config improvements, and the fact that PSCAD 5.x real acceptance is not included.

- [ ] **Step 3: Run the focused test and commit**

\`\`\`powershell
& .\\.venv\\Scripts\\python.exe -m pytest tests/test_changelog.py -q
git add CHANGELOG.md tests/test_changelog.py
git commit -m "docs: add 0.2.0 changelog"
\`\`\`

Expected: PASS, then a clean commit.

### Task 4: Add Windows CI and tool-count smoke coverage

**Files:**
- Create: \`.github/workflows/windows-ci.yml\`
- Create: \`tests/test_tool_inventory.py\`

- [ ] **Step 1: Add a local tool-inventory regression test**

Create \`tests/test_tool_inventory.py\` that obtains the server tool list using the public server factory, awaits it when necessary, and asserts exactly 60 unique tool names. Keep the test independent of PSCAD vendor packages.

Run:

\`\`\`powershell
& .\\.venv\\Scripts\\python.exe -m pytest tests/test_tool_inventory.py -q
\`\`\`

Expected: PASS on the current implementation.

- [ ] **Step 2: Add the Windows workflow**

Create \`.github/workflows/windows-ci.yml\` triggered by pushes and pull requests. Use \`windows-latest\` and a matrix for Python \`3.10\`, \`3.11\`, and \`3.12\`. The workflow must:

1. check out the repository;
2. install the requested Python version;
3. upgrade pip;
4. install \`.[dev]\`;
5. run \`python -m pytest -q\`;
6. run \`python -m pip check\`;
7. run \`python -m compileall -q pscad_mcp tests\`;
8. run the tool-inventory test explicitly.

Do not install \`mhrc.automation\`, launch PSCAD, or claim live acceptance in CI.

- [ ] **Step 3: Validate workflow syntax and local equivalents**

Run:

\`\`\`powershell
& .\\.venv\\Scripts\\python.exe -m pytest tests/test_tool_inventory.py -q
& .\\.venv\\Scripts\\python.exe -m pip check
& .\\.venv\\Scripts\\python.exe -m compileall -q pscad_mcp tests
\`\`\`

Review the YAML manually for valid GitHub Actions keys and ensure no secret or local path is included.

- [ ] **Step 4: Commit CI changes**

\`\`\`powershell
git add .github/workflows/windows-ci.yml tests/test_tool_inventory.py
git commit -m "ci: add Windows test matrix and tool inventory check"
\`\`\`

### Task 5: Run final local verification and create the delivery commit

**Files:**
- Modify: none beyond Tasks 1–4

- [ ] **Step 1: Run the complete verification suite**

\`\`\`powershell
$ErrorActionPreference = 'Stop'
& .\\.venv\\Scripts\\python.exe -m pytest -q
& .\\.venv\\Scripts\\python.exe -m pip check
& .\\.venv\\Scripts\\python.exe -m compileall -q pscad_mcp tests
git diff --check
& .\\.venv\\Scripts\\python.exe -c "import asyncio; from pscad_mcp.main import create_server; s=create_server(); x=s.list_tools(); tools=asyncio.run(x) if hasattr(x, '__await__') else x; assert len(tools)==60 and len({t.name for t in tools})==60; print('TOOLS=60 UNIQUE=60')"
\`\`\`

Expected: zero command failures and \`TOOLS=60 UNIQUE=60\`.

- [ ] **Step 2: Audit release metadata and path portability**

\`\`\`powershell
rg -n "0\\.2\\.0|60|PSCAD 5\\.x|D:\\\\pscad-mcp|D:\\\\PSCAD-Workspace|TBD|TODO|占位" pyproject.toml CHANGELOG.md README.md docs/zh-CN/README.md config.example.toml
\`\`\`

Expected: version and capability statements are consistent; only explicit historical/local examples may contain local paths, and \`config.example.toml\` contains neither real local path.

- [ ] **Step 3: Review the complete diff and status**

\`\`\`powershell
git diff origin/main...HEAD --stat
git diff origin/main...HEAD -- .github/workflows/windows-ci.yml config.example.toml pyproject.toml CHANGELOG.md README.md docs/zh-CN/README.md tests
git status --short --branch
\`\`\`

Expected: only delivery-hardening files changed; no generated artifacts or local secrets.

- [ ] **Step 4: Commit any final corrections**

\`\`\`powershell
git add .
git commit -m "chore: finalize delivery hardening"
\`\`\`

Run the complete verification suite again if this step creates a commit.

### Task 6: Clean exact detached verification worktrees

**Files:**
- Modify: Git worktree metadata only

- [ ] **Step 1: Verify exact cleanup targets and cleanliness**

\`\`\`powershell
git worktree list --porcelain
git -C 'C:\\Users\\335\\.codex\\worktrees\\50f8\\pscad-mcp' status --short --branch
git -C 'C:\\Users\\335\\.codex\\worktrees\\bcf0\\pscad-mcp' status --short --branch
\`\`\`

Expected: both paths exist, are detached verification worktrees, and have no uncommitted changes.

- [ ] **Step 2: Remove only the two verified detached worktrees**

\`\`\`powershell
git worktree remove 'C:\\Users\\335\\.codex\\worktrees\\50f8\\pscad-mcp'
git worktree remove 'C:\\Users\\335\\.codex\\worktrees\\bcf0\\pscad-mcp'
git worktree prune
\`\`\`

Do not remove \`D:\\pscad-mcp\`, the current delivery worktree, or \`D:\\pscad-mcp\\.worktrees\\codex-pscad-simulation-set-management\`.

- [ ] **Step 3: Verify the retained worktrees**

\`\`\`powershell
git worktree list
git status --short --branch
\`\`\`

Expected: the main checkout, delivery worktree, and original feature worktree remain; the two detached verification paths are absent.

### Task 7: Push the branch and create a Draft PR

**Files:**
- Modify: remote Git refs and GitHub PR metadata only

- [ ] **Step 1: Confirm branch and clean state before push**

\`\`\`powershell
git branch --show-current
git status --short --branch
git log --oneline --decorate -6
\`\`\`

Expected: branch is \`codex/pscad-delivery-hardening\`, status is clean, and all commits are present.

- [ ] **Step 2: Push the branch**

\`\`\`powershell
git push -u origin codex/pscad-delivery-hardening
\`\`\`

Expected: remote branch is created or fast-forwarded without force push.

- [ ] **Step 3: Create the Draft PR**

Use the GitHub connector for repository \`zY1sy1/pscad-mcp\`, base \`main\`, head \`codex/pscad-delivery-hardening\`, and \`draft=true\`. The PR body must include:

- summary of CI, config template, version/changelog, and worktree cleanup;
- local verification output;
- explicit statement that PSCAD 5.x real acceptance is intentionally not included;
- review checklist for workflow, portable paths, and release metadata.

- [ ] **Step 4: Verify remote delivery**

\`\`\`powershell
git ls-remote --heads origin codex/pscad-delivery-hardening
\`\`\`

Use the GitHub connector to read the created PR and confirm it is open and draft.
