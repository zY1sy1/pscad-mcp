[CmdletBinding()]
param(
    [string]$Workspace = 'D:\PSCAD-Workspace\lcc-wp1a-native-acceptance',
    [string]$Template = 'D:\pscad-mcp-example-inspection-20260829\cigre_lcc_bidirectional\Cigre_LCC_Bidirectional.pscx',
    [string]$MasterLibrary = 'C:\Program Files (x86)\PSCAD46\master.pslx',
    [string]$CompilerConfiguration = 'C:\Program Files (x86)\PSCAD46\fortran_compilers.xml',
    [string]$CompilerExecutable = 'C:\Program Files (x86)\GFortran\4.6\bin\gfortran.exe',
    [string]$ProjectName = 'WP1A_NATIVE_LCC',
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Python) {
    $localPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    $commonDirectory = (& git -C $repoRoot rev-parse --path-format=absolute --git-common-dir).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Unable to resolve Git common directory.' }
    $commonPython = Join-Path (Split-Path -Parent $commonDirectory) '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $localPython -PathType Leaf) {
        $Python = $localPython
    } elseif (Test-Path -LiteralPath $commonPython -PathType Leaf) {
        $Python = $commonPython
    } else {
        throw 'Virtual-environment Python was not found.'
    }
}
foreach ($path in @($Python, $Template, $MasterLibrary, $CompilerConfiguration, $CompilerExecutable)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required file was not found: $path"
    }
}
$commit = (& git -C $repoRoot rev-parse HEAD).Trim()
$branch = (& git -C $repoRoot branch --show-current).Trim()
if (-not $branch) { throw 'Native acceptance requires a named branch.' }
if (@(& git -C $repoRoot status --porcelain).Count -ne 0) {
    throw 'Commit or remove repository changes before native acceptance.'
}
if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object ProcessName -Like 'PSCAD*').Count -ne 0) {
    throw 'Close existing PSCAD processes before native acceptance.'
}
$null = New-Item -ItemType Directory -Path $Workspace -Force
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$runRoot = Join-Path $Workspace "native-lcc-$stamp"
New-Item -ItemType Directory -Path $runRoot -Force:$false | Out-Null
$report = Join-Path $runRoot 'native-lcc-acceptance-report.json'

Push-Location $repoRoot
try {
    $arguments = @(
        '-m', 'pscad_mcp.hvdc.builders.lcc.native_acceptance_cli',
        'run',
        '--repository-root', $repoRoot,
        '--workspace-root', $runRoot,
        '--template-path', $Template,
        '--master-path', $MasterLibrary,
        '--compiler-configuration', $CompilerConfiguration,
        '--compiler-executable', $CompilerExecutable,
        '--report', $report,
        '--project-name', $ProjectName,
        '--commit', $commit,
        '--branch', $branch
    )
    & $Python @arguments
    $nativeExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
    throw "Native LCC report was not written: $report"
}
$payload = Get-Content -Raw -LiteralPath $report | ConvertFrom-Json
if ($nativeExitCode -ne 0 -or $payload.status -ne 'PASS') {
    throw "Native LCC acceptance failed; inspect $report"
}
if ($payload.commit -ne $commit -or $payload.capability_state -ne 'simulated') {
    throw 'Native LCC report commit or capability is invalid.'
}
foreach ($name in @('disturbance', 'failure_indication', 'bounded_dc_response', 'recovered')) {
    if ($payload.acceptance.checks.$name -ne $true) {
        throw "Native LCC check failed: $name"
    }
}
if (
    $payload.sources.template.before -ne $payload.sources.template.after -or
    $payload.sources.master.before -ne $payload.sources.master.after
) {
    throw 'Native LCC source_after evidence differs from source_before.'
}
if (@(Get-Process -ErrorAction SilentlyContinue | Where-Object ProcessName -Like 'PSCAD*').Count -ne 0) {
    throw 'Native LCC acceptance left PSCAD processes running.'
}
$reportHash = (Get-FileHash -LiteralPath $report -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output 'NATIVE_LCC_ACCEPTANCE=PASS'
Write-Output "NATIVE_LCC_REPORT=$report"
Write-Output "NATIVE_LCC_REPORT_SHA256=$reportHash"
Write-Output "NATIVE_LCC_COMMIT=$commit"
