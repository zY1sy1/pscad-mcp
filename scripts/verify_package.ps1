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
$targetDir = Join-Path $tempRoot "target"
$probeDir = Join-Path $tempRoot "probe"

New-Item -ItemType Directory -Path $wheelDir, $targetDir, $probeDir | Out-Null

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

    & $python -m pip install --no-deps --target $targetDir $wheel.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed with exit code $LASTEXITCODE."
    }

    $probe = @"
import importlib.metadata as metadata
import pscad_mcp
from pscad_mcp.main import create_server

installed = metadata.version('pscad-mcp')
assert installed == pscad_mcp.__version__ == '0.2.0', (installed, pscad_mcp.__version__)
tools = create_server()._tool_manager.list_tools()
assert len(tools) == 60
assert len({tool.name for tool in tools}) == 60
print(f'{installed} {len(tools)}')
"@

    $previousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = $targetDir
    try {
        Push-Location $probeDir
        & $python -c $probe
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
    }
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
