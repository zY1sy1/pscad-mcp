function Invoke-AcceptanceTestCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Acceptance executable was not found: $Executable"
    }
    $previousPreference = $ErrorActionPreference
    $captured = @()
    try {
        # Windows PowerShell 5.1 represents normal native stderr as ErrorRecords.
        # Keep those records as evidence and use the native exit code as verdict.
        $ErrorActionPreference = 'Continue'
        & $Executable @ArgumentList 2>&1 |
            Tee-Object -Variable captured |
            ForEach-Object { Write-Host ([string]$_) }
        $nativeExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    [pscustomobject]@{
        ExitCode = $nativeExitCode
        Output = @($captured | ForEach-Object { [string]$_ })
    }
}
