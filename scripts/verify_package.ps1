$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = if ($env:PSCAD_MCP_PYTHON) {
    (Resolve-Path $env:PSCAD_MCP_PYTHON).Path
} else {
    (Get-Command python -ErrorAction Stop).Source
}
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    "pscad-mcp-package-" + [Guid]::NewGuid().ToString("N")
)
$wheelDir = Join-Path $tempRoot "wheel"
$venvDir = Join-Path $tempRoot "venv"
$probeDir = Join-Path $tempRoot "probe"

New-Item -ItemType Directory -Path $wheelDir, $probeDir | Out-Null

try {
    & $python -m pip wheel $repoRoot --no-deps --wheel-dir $wheelDir
    if ($LASTEXITCODE -ne 0) {
        throw "pip wheel failed with exit code $LASTEXITCODE."
    }

    $wheel = Get-ChildItem -LiteralPath $wheelDir -Filter "*.whl" -File |
        Select-Object -First 1
    if ($null -eq $wheel) {
        throw "No wheel was produced in '$wheelDir'."
    }

    & $python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw "python -m venv failed with exit code $LASTEXITCODE."
    }

    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Virtual environment Python was not created at '$venvPython'."
    }

    & $venvPython -m pip install $wheel.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed with exit code $LASTEXITCODE."
    }

    $probe = @"
import importlib.metadata as metadata
import pscad_mcp
from pscad_mcp.main import create_server
from pscad_mcp.tools.catalog import FULL_TOOL_NAMES
from pscad_mcp.hvdc.builders.lcc.assets import load_packaged_asset_set

installed = metadata.version('pscad-mcp')
if installed != pscad_mcp.__version__:
    raise RuntimeError(f'Installed version mismatch: {installed!r} != {pscad_mcp.__version__!r}')
tools = create_server()._tool_manager.list_tools()
if {tool.name for tool in tools} != FULL_TOOL_NAMES:
    raise RuntimeError('Installed tool inventory does not match FULL_TOOL_NAMES')
assets = load_packaged_asset_set()
if assets.name != 'cigre_lcc_monopole_v1':
    raise RuntimeError(f'Unexpected packaged asset set: {assets.name!r}')
if not assets.pscad_version.startswith('4.'):
    raise RuntimeError(f'Unexpected packaged asset PSCAD version: {assets.pscad_version!r}')
print(f'{installed} {len(FULL_TOOL_NAMES)} {len(assets.hashes)}')
"@

    $previousPythonPath = $env:PYTHONPATH
    $previousNoUserSite = $env:PYTHONNOUSERSITE
    $previousToolProfile = $env:PSCAD_MCP_TOOL_PROFILE
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PSCAD_MCP_TOOL_PROFILE -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE = "1"
    try {
        Push-Location $probeDir
        & $venvPython -c $probe
        if ($LASTEXITCODE -ne 0) {
            throw "Installed package probe failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
        if ($null -eq $previousPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONPATH = $previousPythonPath
        }
        if ($null -eq $previousNoUserSite) {
            Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONNOUSERSITE = $previousNoUserSite
        }
        if ($null -eq $previousToolProfile) {
            Remove-Item Env:PSCAD_MCP_TOOL_PROFILE -ErrorAction SilentlyContinue
        } else {
            $env:PSCAD_MCP_TOOL_PROFILE = $previousToolProfile
        }
    }
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
