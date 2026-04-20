param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Get-ProjectVersion {
    $pyprojectPath = Join-Path $projectRoot "pyproject.toml"
    $content = Get-Content -LiteralPath $pyprojectPath -Raw -Encoding UTF8
    $match = [regex]::Match($content, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Failed to read version from pyproject.toml"
    }
    return $match.Groups[1].Value
}

function New-ReleaseZip {
    param(
        [string]$SourceDirectory,
        [string]$DestinationPath
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $lastError = $null
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            if (Test-Path -LiteralPath $DestinationPath) {
                Remove-Item -LiteralPath $DestinationPath -Force
            }

            [System.IO.Compression.ZipFile]::CreateFromDirectory(
                $SourceDirectory,
                $DestinationPath,
                [System.IO.Compression.CompressionLevel]::Optimal,
                $true
            )
            return
        }
        catch {
            $lastError = $_
            Start-Sleep -Milliseconds (300 * $attempt)
        }
    }

    throw $lastError
}

$version = Get-ProjectVersion
$distRoot = Join-Path $projectRoot "dist"
$builtAppDir = Join-Path $distRoot "ArcWeaver"
$releaseRoot = Join-Path $projectRoot "release"
$releaseFolderName = "ArcWeaver-v$version-windows-x64"
$stageDir = Join-Path $releaseRoot $releaseFolderName
$zipPath = Join-Path $releaseRoot "$releaseFolderName.zip"

if (-not $SkipBuild) {
    & (Join-Path $projectRoot "build_exe.ps1")
}

if (-not (Test-Path -LiteralPath $builtAppDir)) {
    throw "Built application directory not found: $builtAppDir"
}

if (Test-Path -LiteralPath $stageDir) {
    Remove-Item -LiteralPath $stageDir -Recurse -Force
}
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
Copy-Item -LiteralPath $builtAppDir -Destination $stageDir -Recurse -Force

$releaseDocs = @(
    "README.md",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "CHANGELOG.md"
)

foreach ($name in $releaseDocs) {
    $sourcePath = Join-Path $projectRoot $name
    if (Test-Path -LiteralPath $sourcePath) {
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $stageDir $name) -Force
    }
}

New-ReleaseZip -SourceDirectory $stageDir -DestinationPath $zipPath

Write-Output "RELEASE_DIR: $stageDir"
Write-Output "RELEASE_ZIP: $zipPath"
