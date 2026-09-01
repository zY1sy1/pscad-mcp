param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,
    [string]$MasterPath = 'C:\Program Files (x86)\PSCAD46\master.pslx',
    [Parameter(Mandatory = $true)]
    [string]$CompilerConfiguration,
    [Parameter(Mandatory = $true)]
    [string]$CompilerExecutable,
    [string]$ProjectName = 'WP1B_FIXED_LCC'
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepositoryRoot
try {
    $Dirty = git status --porcelain
}
finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0 -or $Dirty) {
    throw 'WP1B licensed run requires a clean named checkout.'
}
$Commit = git -C $RepositoryRoot rev-parse HEAD
$Branch = git -C $RepositoryRoot branch --show-current
if ($LASTEXITCODE -ne 0 -or -not $Branch) {
    throw 'WP1B licensed run requires a named branch.'
}
$Existing = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like 'PSCAD*' })
if ($Existing.Count -ne 0) {
    throw 'Close external PSCAD processes before the WP1B run.'
}
$Stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')
$RunRoot = Join-Path $WorkspaceRoot "fixed-lcc-$Stamp"
$Report = Join-Path $RunRoot 'fixed-lcc-acceptance-report.json'
$Python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    $CommonGitDir = git -C $RepositoryRoot rev-parse --path-format=absolute --git-common-dir
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to locate the repository Python environment.'
    }
    $CommonRoot = Split-Path -Parent $CommonGitDir
    $Python = Join-Path $CommonRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'The repository Python environment is unavailable.'
}
& $Python -m pscad_mcp.hvdc.builders.lcc.fixed_acceptance_cli 'run' `
    --repository-root $RepositoryRoot `
    --workspace-root $RunRoot `
    --master-path $MasterPath `
    --compiler-configuration $CompilerConfiguration `
    --compiler-executable $CompilerExecutable `
    --report $Report `
    --commit $Commit `
    --branch $Branch `
    --project-name $ProjectName
if ($LASTEXITCODE -ne 0) {
    throw "WP1B fixed smoke failed; inspect $Report"
}
$Remaining = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like 'PSCAD*' })
if ($Remaining.Count -ne 0) {
    throw 'WP1B report cannot pass with remaining PSCAD processes.'
}
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Report).Hash.ToLowerInvariant()
Write-Output "FIXED_LCC_REPORT=$Report"
Write-Output "FIXED_LCC_REPORT_SHA256=$Hash"
