[CmdletBinding()]
param(
    [string]$SourceRoot = 'D:\PSCAD-Workspace\topology-sources',
    [string]$Manifest = 'D:\PSCAD-Workspace\topology-truth.json',
    [string]$Version = '4.6.2',
    [switch]$X64
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
$seed = Join-Path $repositoryRoot 'pscad_mcp\assets\templates\empty_case.pscx'
$truthScript = Join-Path $PSScriptRoot 'topology_truth.py'
$normalizer = Join-Path $PSScriptRoot 'normalize_topology_truth.py'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Repository Python is missing: $python"
}
if ($Version -ne '4.6.2') {
    throw "Topology truth preparation requires PSCAD 4.6.2."
}
if (-not $X64) {
    throw "Topology truth preparation requires PSCAD 4.6.2 x64."
}
if (-not [System.IO.Path]::IsPathFullyQualified($SourceRoot)) {
    throw "SourceRoot must be absolute."
}
if (-not [System.IO.Path]::IsPathFullyQualified($Manifest)) {
    throw "Manifest must be absolute."
}
if (Test-Path -LiteralPath $SourceRoot) {
    throw "Refusing existing topology-sources: $SourceRoot"
}
if (Test-Path -LiteralPath $Manifest) {
    throw "Refusing existing topology-truth.json: $Manifest"
}

$existingPscad = @(
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -like 'PSCAD*' }
)
if ($existingPscad.Count -gt 0) {
    throw "Close all PSCAD processes before topology truth preparation."
}

$sourceParent = Split-Path -Parent $SourceRoot
if (-not (Test-Path -LiteralPath $sourceParent -PathType Container)) {
    throw "Source parent directory is missing: $sourceParent"
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$staging = Join-Path $sourceParent "topology-staging-$stamp"
if (Test-Path -LiteralPath $staging) {
    throw "Refusing existing staging directory: $staging"
}
New-Item -ItemType Directory -Path $staging | Out-Null

$completed = $false
try {
    & $python $truthScript build `
        --seed $seed `
        --destination (Join-Path $staging 'generated') `
        --cases 'ordinary,seeded-defects,custom-library,hierarchy-uncertain,scale-500,scale-2000'
    if ($LASTEXITCODE -ne 0) {
        throw "Topology project generation failed."
    }

    $generated = Join-Path $staging 'generated'
    $projectsJson = Join-Path $generated 'projects.json'
    $normalizationOutput = @(
        & $python $normalizer `
            --projects-json $projectsJson `
            --version $Version `
            --x64 2>&1
    )
    $normalizationExit = $LASTEXITCODE
    $normalizationOutput | ForEach-Object { Write-Output $_ }
    if ($normalizationExit -ne 0) {
        throw "Topology project normalization failed."
    }
    $ownedPids = @(
        $normalizationOutput |
            ForEach-Object {
                if ([string]$_ -match '^ACCEPTANCE_PID=(\d+)$') {
                    [int]$Matches[1]
                }
            }
    )
    if ($ownedPids.Count -ne 2) {
        throw "Expected two ACCEPTANCE_PID records."
    }
    $remainingOwned = @(
        $ownedPids |
            ForEach-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
    )
    if ($remainingOwned.Count -gt 0) {
        throw "An owned PSCAD process did not exit."
    }

    & $python $truthScript probe --directory $generated
    if ($LASTEXITCODE -ne 0) {
        throw "Topology semantic probe failed."
    }
    & $python $truthScript audit --directory $generated
    if ($LASTEXITCODE -ne 0) {
        throw "Topology truth audit failed."
    }

    & $python $truthScript publish `
        --staging $generated `
        --sources $SourceRoot `
        --manifest $Manifest `
        --version $Version `
        --x64 `
        --owned-pids ($ownedPids -join ',')
    if ($LASTEXITCODE -ne 0) {
        throw "Topology truth publication failed."
    }
    $completed = $true

    Get-ChildItem -LiteralPath $SourceRoot -Recurse -Filter '*.pscx' |
        Sort-Object FullName |
        ForEach-Object {
            $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
            Write-Output "TOPOLOGY_SOURCE_SHA256=$($hash.Hash) $($_.FullName)"
        }
    $manifestHash = Get-FileHash -LiteralPath $Manifest -Algorithm SHA256
    Write-Output "TOPOLOGY_MANIFEST_SHA256=$($manifestHash.Hash) $Manifest"
    Write-Output 'TOPOLOGY_TRUTH_PREPARATION=PASS'
}
finally {
    if (-not $completed) {
        $marker = Join-Path $staging 'INCOMPLETE'
        if (-not (Test-Path -LiteralPath $marker)) {
            New-Item -ItemType File -Path $marker | Out-Null
        }
        Write-Warning "Incomplete topology evidence preserved at $staging"
    }
}
