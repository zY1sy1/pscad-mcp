[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Source,

    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [string]$Label = "acceptance"
)

$ErrorActionPreference = "Stop"

$allowedSourceRoot = [System.IO.Path]::GetFullPath(
    "C:\Users\Public\Documents\PSCAD\4.6\Examples"
).TrimEnd('\')
$allowedDestinationRoot = [System.IO.Path]::GetFullPath(
    "D:\PSCAD-Workspace\acceptance"
).TrimEnd('\')

$sourceItem = Get-Item -LiteralPath $Source -Force
$sourcePath = [System.IO.Path]::GetFullPath($sourceItem.FullName)
$destinationPath = [System.IO.Path]::GetFullPath($Destination).TrimEnd('\')

if (-not $sourcePath.StartsWith(
    $allowedSourceRoot + '\',
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Source must be below $allowedSourceRoot"
}

$destinationAllowed = $destinationPath.Equals(
    $allowedDestinationRoot,
    [System.StringComparison]::OrdinalIgnoreCase
) -or $destinationPath.StartsWith(
    $allowedDestinationRoot + '\',
    [System.StringComparison]::OrdinalIgnoreCase
)
if (-not $destinationAllowed) {
    throw "Destination must be $allowedDestinationRoot or one of its children."
}

$safeLabel = ($Label -replace '[^A-Za-z0-9_-]', '-').Trim('-')
if (-not $safeLabel) {
    $safeLabel = "acceptance"
}
$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$runDirectory = Join-Path $destinationPath "codex-$stamp-$safeLabel"
if (Test-Path -LiteralPath $runDirectory) {
    throw "Refusing to overwrite existing acceptance directory: $runDirectory"
}

New-Item -ItemType Directory -Path $runDirectory -Force:$false | Out-Null
if ($sourceItem.PSIsContainer) {
    Get-ChildItem -LiteralPath $sourcePath -Force |
        Copy-Item -Destination $runDirectory -Recurse
} else {
    Copy-Item -LiteralPath $sourcePath -Destination $runDirectory
}

$projects = @(Get-ChildItem -LiteralPath $runDirectory -Recurse -File -Filter '*.pscx')
if ($projects.Count -ne 1) {
    throw "Expected exactly one .pscx project in $runDirectory; found $($projects.Count)."
}

Write-Output "ACCEPTANCE_PROJECT=$($projects[0].FullName)"
