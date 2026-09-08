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
$PreflightComplete = $false
$LocationPushed = $false

try {
    if ($env:PSCAD_MCP_ACCEPTANCE -ne '1') {
        throw 'Set PSCAD_MCP_ACCEPTANCE=1 to run licensed PSCAD acceptance.'
    }

    Push-Location $RepositoryRoot
    $LocationPushed = $true
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
    if ($env:PSCAD_MCP_ACCEPTANCE_CONCURRENT -ne '1' -and @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PSCAD*' }).Count -ne 0) {
        throw 'Close PSCAD processes before running licensed dynamic acceptance.'
    }
    $RunRoot = Join-Path (Resolve-Path $WorkspaceRoot).Path ("run-" + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
    if (-not $Report) {
        $Report = Join-Path $RunRoot 'fixed-lcc-dynamic-report.json'
    }
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
    $PreflightComplete = $true
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

    if ($env:PSCAD_MCP_ACCEPTANCE_CONCURRENT -ne '1' -and @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'PSCAD*' }).Count -ne 0) {
        throw 'PSCAD process remained after licensed dynamic acceptance.'
    }
    if (Test-Path -LiteralPath $Report -PathType Leaf) {
        $Payload = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
        if ($env:PSCAD_MCP_ACCEPTANCE_CONCURRENT -eq '1') {
            if (-not ($Payload.runtime.managed_pid -gt 0)) {
                throw 'Concurrent acceptance did not record its managed PSCAD PID.'
            }
            if (Get-Process -Id $Payload.runtime.managed_pid -ErrorAction SilentlyContinue) {
                throw 'The owned PSCAD process remained after dynamic acceptance.'
            }
        }
        $Hash = (Get-FileHash -LiteralPath $Report -Algorithm SHA256).Hash.ToLowerInvariant()
        Write-Output ("FIXED_LCC_DYNAMIC_REPORT=" + (Resolve-Path $Report).Path)
        Write-Output ("FIXED_LCC_DYNAMIC_REPORT_SHA256=" + $Hash)
        Write-Output ("FIXED_LCC_DYNAMIC_ENGINEERING_VERDICT=" + $Payload.engineering_verdict)
        Write-Output ("FIXED_LCC_DYNAMIC_STATUS=" + $Payload.status)
    } else {
        Write-Output ("FIXED_LCC_DYNAMIC_REPORT=" + $Report)
        Write-Output 'FIXED_LCC_DYNAMIC_REPORT_SHA256='
        Write-Output 'FIXED_LCC_DYNAMIC_ENGINEERING_VERDICT=FAIL'
        Write-Output 'FIXED_LCC_DYNAMIC_STATUS=FAIL'
    }
}
catch {
    if (-not $PreflightComplete) {
        $ExitCode = 2
    } else {
        $ExitCode = 1
    }
    Write-Error $_ -ErrorAction Continue
}
finally {
    if ($LocationPushed) {
        Pop-Location
    }
}
exit $ExitCode
