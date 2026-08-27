[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [Parameter(Mandatory = $true)]
    [string]$Manifest,
    [string]$Version = "4.6.2",
    [switch]$X64
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$virtualEnvironment = Join-Path $repoRoot ".venv"
$python = Join-Path $virtualEnvironment "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $commonGitDirectory = (& git -C $repoRoot rev-parse --git-common-dir).Trim()
    if ($LASTEXITCODE -eq 0) {
        if (-not [System.IO.Path]::IsPathRooted($commonGitDirectory)) {
            $commonGitDirectory = Join-Path $repoRoot $commonGitDirectory
        }
        $commonRepository = Split-Path -Parent (
            [System.IO.Path]::GetFullPath($commonGitDirectory)
        )
        $virtualEnvironment = Join-Path $commonRepository ".venv"
        $python = Join-Path $virtualEnvironment "Scripts\python.exe"
    }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual-environment Python was not found: $python"
}
if ($Version -ne "4.6.2") {
    throw "Topology acceptance supports only PSCAD 4.6.2. Requested: $Version"
}
if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
    throw "Topology truth manifest was not found: $Manifest"
}

$manifestPath = (Resolve-Path -LiteralPath $Manifest).Path
if (-not [System.IO.Path]::IsPathRooted($manifestPath)) {
    throw "Topology truth manifest must resolve to an absolute path: $manifestPath"
}
$manifestPayload = Get-Content -LiteralPath $manifestPath -Raw |
    ConvertFrom-Json
$manifestCases = @($manifestPayload.cases)
if ($manifestCases.Count -eq 0) {
    throw "Topology truth manifest contains no cases: $manifestPath"
}

if (-not (Test-Path -LiteralPath $Workspace -PathType Container)) {
    New-Item -ItemType Directory -Path $Workspace -Force | Out-Null
}
$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$workspacePrefix = $workspacePath.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar

$sourcePaths = @()
for ($index = 0; $index -lt $manifestCases.Count; $index++) {
    $rawSource = [string]$manifestCases[$index].source_project
    if ([string]::IsNullOrWhiteSpace($rawSource)) {
        throw "Manifest case $index is missing source_project."
    }
    if (-not [System.IO.Path]::IsPathRooted($rawSource)) {
        throw "Manifest source_project must be absolute: $rawSource"
    }
    if (-not (Test-Path -LiteralPath $rawSource -PathType Leaf)) {
        throw "Manifest source project was not found: $rawSource"
    }
    $sourcePath = (Resolve-Path -LiteralPath $rawSource).Path
    if ([System.IO.Path]::GetExtension($sourcePath) -ine ".pscx") {
        throw "Manifest source project must be a .pscx file: $sourcePath"
    }
    if ($sourcePath.StartsWith(
        $workspacePrefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Acceptance workspace must not contain a source project: $sourcePath"
    }
    $sourcePaths += $sourcePath
}

$existing = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like "PSCAD*" })
if ($existing.Count -gt 0) {
    $summary = ($existing | ForEach-Object {
        "$($_.Id):$($_.ProcessName)"
    }) -join ", "
    throw "Close existing PSCAD processes before acceptance. Found: $summary"
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fffffff"
$runDirectory = Join-Path $workspacePath "topology-acceptance-$stamp"
New-Item -ItemType Directory -Path $runDirectory | Out-Null
for ($index = 0; $index -lt $sourcePaths.Count; $index++) {
    $caseDirectory = Join-Path $runDirectory ("case-{0:D3}" -f $index)
    New-Item -ItemType Directory -Path $caseDirectory | Out-Null
    Copy-Item -LiteralPath $sourcePaths[$index] -Destination (
        Join-Path $caseDirectory ([System.IO.Path]::GetFileName($sourcePaths[$index]))
    )
}

$reportPath = Join-Path $runDirectory "topology-acceptance-report.json"
$environmentValues = @{
    PSCAD_MCP_TOPOLOGY_ACCEPTANCE = "1"
    PSCAD_MCP_TOPOLOGY_ACCEPTANCE_MANIFEST = $manifestPath
    PSCAD_MCP_TOPOLOGY_ACCEPTANCE_WORKSPACE = $runDirectory
    PSCAD_MCP_TOPOLOGY_ACCEPTANCE_REPORT = $reportPath
    PSCAD_MCP_TOPOLOGY_ACCEPTANCE_VERSION = $Version
    PSCAD_MCP_TOPOLOGY_ACCEPTANCE_X64 = if ($X64) { "true" } else { "false" }
}
$previousEnvironment = @{}
foreach ($name in $environmentValues.Keys) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable(
        $name,
        [EnvironmentVariableTarget]::Process
    )
}

$capturedOutput = @()
$pytestExitCode = -1
try {
    foreach ($name in $environmentValues.Keys) {
        Set-Item -Path "Env:$name" -Value $environmentValues[$name]
    }
    Write-Output "TOPOLOGY_ACCEPTANCE_WORKSPACE=$runDirectory"
    Write-Output "TOPOLOGY_ACCEPTANCE_MANIFEST=$manifestPath"

    Push-Location $repoRoot
    try {
        & $python -m pytest tests/test_topology_real_acceptance.py -q -s 2>&1 |
            Tee-Object -Variable capturedOutput
        $pytestExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $environmentValues.Keys) {
        $previous = $previousEnvironment[$name]
        if ($null -eq $previous) {
            Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path "Env:$name" -Value $previous
        }
    }
}

$ownedPids = [System.Collections.Generic.HashSet[int]]::new()
foreach ($line in $capturedOutput) {
    if ([string]$line -match "ACCEPTANCE_PID=(\d+)") {
        [void]$ownedPids.Add([int]$Matches[1])
    }
}
$remainingOwned = @()
foreach ($processId in $ownedPids) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        $remainingOwned += "$processId`:$($process.ProcessName)"
    }
}
if ($remainingOwned.Count -gt 0) {
    throw (
        "Topology acceptance left owned PSCAD processes running; they were " +
        "not terminated automatically: $($remainingOwned -join ', ')"
    )
}
Write-Output "TOPOLOGY_ACCEPTANCE_OWNED_PROCESS_COUNT=0"

if ($pytestExitCode -ne 0) {
    throw "Topology acceptance failed with exit code $pytestExitCode."
}
if ($ownedPids.Count -eq 0) {
    throw "Topology acceptance passed without recording an owned PSCAD PID."
}
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw "Topology acceptance did not publish a report: $reportPath"
}

$validationCommand = @"
import json
import pathlib
import sys
from pscad_mcp.topology.acceptance import validate_acceptance_report

validate_acceptance_report(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")))
"@
& $python -c $validationCommand $reportPath
if ($LASTEXITCODE -ne 0) {
    throw "Topology acceptance report validation failed."
}

$reportHash = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "TOPOLOGY_ACCEPTANCE_REPORT=$reportPath"
Write-Output "TOPOLOGY_ACCEPTANCE_REPORT_SHA256=$reportHash"
Write-Output "TOPOLOGY_ACCEPTANCE_COMPLETE=PASS"
