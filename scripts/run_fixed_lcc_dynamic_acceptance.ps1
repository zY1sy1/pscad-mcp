param(
    [Parameter(Mandatory = $true)]
    [string]$WorkspaceRoot,
    [Parameter(Mandatory = $true)]
    [string]$MasterPath,
    [Parameter(Mandatory = $true)]
    [string]$CompilerConfiguration,
    [Parameter(Mandatory = $true)]
    [string]$CompilerExecutable,
    [Parameter(Mandatory = $true)]
    [string]$ProjectName,
    [string]$Report
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ExitCode = 1

if ($env:PSCAD_MCP_ACCEPTANCE -ne '1') {
    throw 'Set PSCAD_MCP_ACCEPTANCE=1 to run licensed PSCAD acceptance.'
}

Push-Location $RepositoryRoot
try {
    $Dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $Dirty) {
        throw 'WP1C dynamic acceptance requires a clean checkout.'
    }
    $Branch = (git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $Branch) {
        throw 'WP1C dynamic acceptance requires a named branch.'
    }
    $Commit = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $Commit -notmatch '^[0-9a-f]{40}$') {
        throw 'Unable to resolve an exact checkout HEAD.'
    }
    if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PSCAD*' }).Count -ne 0) {
        throw 'Close PSCAD processes before running licensed dynamic acceptance.'
    }
    $RunRoot = Join-Path (Resolve-Path $WorkspaceRoot).Path ("run-" + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
    if (-not $Report) {
        $Report = Join-Path $RunRoot 'fixed-lcc-dynamic-report.json'
    }
    $Python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw 'The repository Python environment is unavailable.'
    }
    & $Python -m pscad_mcp.hvdc.builders.lcc.dynamic_acceptance_cli run `
        --repository-root $RepositoryRoot `
        --workspace-root $RunRoot `
        --master-path $MasterPath `
        --compiler-configuration $CompilerConfiguration `
        --compiler-executable $CompilerExecutable `
        --report $Report `
        --commit $Commit `
        --branch $Branch `
        --project-name $ProjectName `
        --simulation-duration 1.5 `
        --output-step 0.00005
    $ExitCode = $LASTEXITCODE

    if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PSCAD*' }).Count -ne 0) {
        throw 'PSCAD process remained after licensed dynamic acceptance.'
    }
    if (Test-Path -LiteralPath $Report -PathType Leaf) {
        $Payload = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
        $Hash = (Get-FileHash -LiteralPath $Report -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Output ("FIXED_LCC_DYNAMIC_REPORT=" + (Resolve-Path $Report).Path)
        Write-Output ("FIXED_LCC_DYNAMIC_REPORT_SHA256=" + $Hash)
        Write-Output ("FIXED_LCC_DYNAMIC_ENGINEERING_VERDICT=" + $Payload.engineering_verdict)
        Write-Output ("FIXED_LCC_DYNAMIC_STATUS=" + $Payload.status)
    }
}
finally {
    Pop-Location
}
exit $ExitCode
