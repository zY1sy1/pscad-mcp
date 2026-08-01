[CmdletBinding()]
param(
    [string]$Workspace = "D:\PSCAD-Workspace\acceptance",
    [string]$Version = "4.6.2",
    [switch]$X64,
    [string]$Source = "C:\Users\Public\Documents\PSCAD\4.6\Examples\tutorial\vdiv.pscx"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$prepare = Join-Path $PSScriptRoot "prepare_acceptance_workspace.ps1"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual-environment Python was not found: $python"
}
if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Acceptance source project was not found: $Source"
}

$existing = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like 'PSCAD*' })
if ($existing.Count -gt 0) {
    $summary = ($existing | ForEach-Object { "$($_.Id):$($_.ProcessName)" }) -join ', '
    throw "Close existing PSCAD processes before acceptance. Found: $summary"
}

function New-AcceptanceProject([string]$Label) {
    $line = & $prepare -Source $Source -Destination $Workspace -Label $Label |
        Select-Object -Last 1
    if (-not $line.StartsWith("ACCEPTANCE_PROJECT=")) {
        throw "Workspace preparation returned an unexpected result: $line"
    }
    return $line.Substring("ACCEPTANCE_PROJECT=".Length)
}

$readOnlyProject = New-AcceptanceProject "read-only"
$mutationProject = New-AcceptanceProject "mutation"
$buildProject = New-AcceptanceProject "build"
$simulationProject = New-AcceptanceProject "simulation"
$resultFile = Get-ChildItem -LiteralPath (Join-Path $repoRoot ".venv") `
    -Recurse -File -Filter '*.psout' | Select-Object -First 1
if ($null -eq $resultFile) {
    throw "No .psout acceptance sample was found under the D-drive virtual environment."
}

$environmentNames = @(
    "PSCAD_MCP_ACCEPTANCE",
    "PSCAD_MCP_ACCEPTANCE_VERSION",
    "PSCAD_MCP_ACCEPTANCE_X64",
    "PSCAD_MCP_ACCEPTANCE_READONLY_PROJECT",
    "PSCAD_MCP_ACCEPTANCE_MUTATION_PROJECT",
    "PSCAD_MCP_ACCEPTANCE_BUILD_PROJECT",
    "PSCAD_MCP_ACCEPTANCE_SIMULATION_PROJECT",
    "PSCAD_MCP_ACCEPTANCE_RESULT_FILE"
)

$acceptanceFailure = $null
try {
    $env:PSCAD_MCP_ACCEPTANCE = "1"
    $env:PSCAD_MCP_ACCEPTANCE_VERSION = $Version
    $env:PSCAD_MCP_ACCEPTANCE_X64 = if ($X64) { "true" } else { "false" }
    $env:PSCAD_MCP_ACCEPTANCE_READONLY_PROJECT = $readOnlyProject
    $env:PSCAD_MCP_ACCEPTANCE_MUTATION_PROJECT = $mutationProject
    $env:PSCAD_MCP_ACCEPTANCE_BUILD_PROJECT = $buildProject
    $env:PSCAD_MCP_ACCEPTANCE_SIMULATION_PROJECT = $simulationProject
    $env:PSCAD_MCP_ACCEPTANCE_RESULT_FILE = $resultFile.FullName

    Write-Output "ACCEPTANCE_WORKSPACE=$Workspace"
    Write-Output "READONLY_PROJECT=$readOnlyProject"
    Write-Output "MUTATION_PROJECT=$mutationProject"
    Write-Output "BUILD_PROJECT=$buildProject"
    Write-Output "SIMULATION_PROJECT=$simulationProject"
    Write-Output "RESULT_FILE=$($resultFile.FullName)"

    Push-Location $repoRoot
    try {
        & $python -m unittest tests.test_legacy_acceptance -v
        if ($LASTEXITCODE -ne 0) {
            $acceptanceFailure = "Legacy acceptance failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $environmentNames) {
        Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
    }
}

$remaining = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like 'PSCAD*' })
if ($remaining.Count -gt 0) {
    $summary = ($remaining | ForEach-Object { "$($_.Id):$($_.ProcessName):$($_.Path)" }) -join ', '
    throw "Acceptance left PSCAD processes running; they were not terminated automatically: $summary"
}

if ($null -ne $acceptanceFailure) {
    throw $acceptanceFailure
}

Write-Output "ACCEPTANCE_COMPLETE=PASS"
