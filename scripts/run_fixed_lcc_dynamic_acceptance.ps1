param(
    [Parameter(Mandatory = $true)]
    [string]$Samples,
    [Parameter(Mandatory = $true)]
    [string]$Golden,
    [Parameter(Mandatory = $true)]
    [string]$Contract,
    [Parameter(Mandatory = $true)]
    [string]$Report,
    [string]$Commit,
    [string]$Branch,
    [string]$EventKind = 'inverter_ac_disturbance',
    [double]$EventTime = 0.8,
    [double]$EventDuration = 0.1,
    [double]$RecoveryWindow = 0.5
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepositoryRoot
try {
    $Dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $Dirty) {
        throw 'WP1C dynamic evidence requires a clean checkout.'
    }
    if (-not $Branch) {
        $Branch = git branch --show-current
    }
    if (-not $Branch) {
        throw 'WP1C dynamic evidence requires a named branch.'
    }
    if (-not $Commit) {
        $Commit = git rev-parse HEAD
    }
    if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PSCAD*' }).Count -ne 0) {
        throw 'Close PSCAD processes before evaluating dynamic evidence.'
    }
    $Python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw 'The repository Python environment is unavailable.'
    }
    & $Python -m pscad_mcp.hvdc.builders.lcc.dynamic_acceptance_cli evaluate `
        --samples $Samples `
        --golden $Golden `
        --contract $Contract `
        --report $Report `
        --commit $Commit `
        --branch $Branch `
        --event-kind $EventKind `
        --event-time $EventTime `
        --event-duration $EventDuration `
        --recovery-window $RecoveryWindow
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $ExitCode
