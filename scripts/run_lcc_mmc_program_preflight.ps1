[CmdletBinding()]
param(
    [string]$Workspace = 'D:\PSCAD-Workspace\lcc-mmc-program-preflight',
    [string]$MasterLibrary = 'C:\Program Files (x86)\PSCAD46\master.pslx',
    [string]$CompilerConfiguration = 'C:\Program Files (x86)\PSCAD46\fortran_compilers.xml',
    [string]$CompilerExecutable = 'C:\Program Files (x86)\GFortran\4.6\bin\gfortran.exe',
    [string[]]$ReadOnlySource = @(
        'D:\pscad-mcp-example-inspection-20260829\cigre_lcc_bidirectional\Cigre_LCC_Bidirectional.pscx',
        'C:\Users\Public\Documents\PSCAD\4.6\Examples\ModelsInProgress\H_MMC_Mono_DC.pscx',
        'C:\Users\Public\Documents\PSCAD\4.6\Examples\ModelsInProgress\intermediate.pslx'
    ),
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not $Python) {
    $localPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    $commonDirectory = (& git -C $repoRoot rev-parse --path-format=absolute --git-common-dir).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to resolve the Git common directory.'
    }
    $commonPython = Join-Path (Split-Path -Parent $commonDirectory) '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $Python = $localPython
    } elseif (Test-Path -LiteralPath $commonPython -PathType Leaf) {
        $Python = $commonPython
    } else {
        throw 'Virtual-environment Python was not found in this checkout or the Git common root.'
    }
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python was not found: $Python"
}
if (-not (Test-Path -LiteralPath $MasterLibrary -PathType Leaf)) {
    throw "Master Library was not found: $MasterLibrary"
}
if (-not (Test-Path -LiteralPath $CompilerConfiguration -PathType Leaf)) {
    throw "Compiler configuration was not found: $CompilerConfiguration"
}
if (-not (Test-Path -LiteralPath $CompilerExecutable -PathType Leaf)) {
    throw "Compiler executable was not found: $CompilerExecutable"
}
foreach ($source in $ReadOnlySource) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Read-only source was not found: $source"
    }
}

$commit = (& git -C $repoRoot rev-parse HEAD).Trim()
$branch = (& git -C $repoRoot branch --show-current).Trim()
if (-not $branch) {
    throw 'Program preflight requires a named branch.'
}
$dirty = @(& git -C $repoRoot status --porcelain)
if ($dirty.Count -ne 0) {
    throw 'Commit or remove repository changes before licensed preflight.'
}
$processes = @(
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object ProcessName -Like 'PSCAD*'
)
if ($processes.Count -gt 0) {
    throw 'Close existing PSCAD processes before preflight.'
}

$null = New-Item -ItemType Directory -Path $Workspace -Force
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runRoot = Join-Path $Workspace "preflight-$stamp"
New-Item -ItemType Directory -Path $runRoot -Force:$false | Out-Null
$report = Join-Path $runRoot 'program-preflight-report.json'

$hadProgramPreflight = Test-Path Env:PSCAD_MCP_PROGRAM_PREFLIGHT
$previousProgramPreflight = $env:PSCAD_MCP_PROGRAM_PREFLIGHT
$hadWorkspace = Test-Path Env:PSCAD_MCP_WORKSPACE
$previousWorkspace = $env:PSCAD_MCP_WORKSPACE
$env:PSCAD_MCP_PROGRAM_PREFLIGHT = '1'
$env:PSCAD_MCP_WORKSPACE = $Workspace
try {
    Push-Location $repoRoot
    try {
        $preflightArguments = @(
            '-m', 'pscad_mcp.acceptance.preflight_cli',
            '--repository-root', $repoRoot,
            '--workspace-root', $Workspace,
            '--master-path', $MasterLibrary,
            '--compiler-configuration', $CompilerConfiguration,
            '--compiler-executable', $CompilerExecutable,
            '--expected-commit', $commit,
            '--expected-branch', $branch,
            '--output', $report
        )
        foreach ($source in $ReadOnlySource) {
            $preflightArguments += @('--read-only-source', $source)
        }
        & $Python @preflightArguments
        $preflightExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    if ($hadProgramPreflight) {
        $env:PSCAD_MCP_PROGRAM_PREFLIGHT = $previousProgramPreflight
    } else {
        Remove-Item Env:PSCAD_MCP_PROGRAM_PREFLIGHT -ErrorAction SilentlyContinue
    }
    if ($hadWorkspace) {
        $env:PSCAD_MCP_WORKSPACE = $previousWorkspace
    } else {
        Remove-Item Env:PSCAD_MCP_WORKSPACE -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
    throw "Licensed preflight did not write its report: $report"
}
$payload = Get-Content -Raw -LiteralPath $report | ConvertFrom-Json
if ($preflightExitCode -ne 0 -or $payload.status -ne 'PASS') {
    throw "Licensed program preflight failed; inspect $report"
}
if ($payload.commit -ne $commit) {
    throw "Licensed program preflight reported a different commit: $report"
}

$remaining = @(
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object ProcessName -Like 'PSCAD*'
)
if ($remaining.Count -ne 0) {
    throw 'Licensed program preflight left PSCAD processes running.'
}
$projectFiles = @(
    Get-ChildItem -LiteralPath $runRoot -Recurse -File |
        Where-Object { $_.Extension -in '.pscx', '.pslx', '.pswx' }
)
if ($projectFiles.Count -ne 0) {
    throw "Licensed program preflight created a PSCAD project under $runRoot"
}

$reportHash = (
    Get-FileHash -LiteralPath $report -Algorithm SHA256
).Hash.ToLowerInvariant()
Write-Output 'PROGRAM_PREFLIGHT=PASS'
Write-Output "PROGRAM_PREFLIGHT_DIRECTORY=$runRoot"
Write-Output "PROGRAM_PREFLIGHT_REPORT=$report"
Write-Output "PROGRAM_PREFLIGHT_SHA256=$reportHash"
Write-Output "PROGRAM_PREFLIGHT_COMMIT=$commit"
