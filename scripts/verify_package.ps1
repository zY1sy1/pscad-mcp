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

installed = metadata.version('pscad-mcp')
assert installed == pscad_mcp.__version__, (installed, pscad_mcp.__version__)
tools = create_server()._tool_manager.list_tools()
assert len(tools) == 73
assert len({tool.name for tool in tools}) == 73
print(f'{installed} {len(tools)}')
"@

    $previousPythonPath = $env:PYTHONPATH
    $previousNoUserSite = $env:PYTHONNOUSERSITE
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
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
    }
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
