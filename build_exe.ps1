param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

function Invoke-PyInstaller {
    param(
        [string[]]$Arguments
    )

    $poetry = Get-Command poetry -ErrorAction SilentlyContinue
    if ($null -ne $poetry) {
        & $poetry.Source run pyinstaller @Arguments
        return
    }

    & python -m PyInstaller @Arguments
}

if ($OneFile) {
    Invoke-PyInstaller @(
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--icon",
        "NONE",
        "--name",
        "ArcWeaver",
        "--add-data",
        "core\config\multipart_scoring.json;core\config",
        "--add-data",
        "7z;7z",
        "launch_desktop_app.py"
    )

    Invoke-PyInstaller @(
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--icon",
        "NONE",
        "--name",
        "ArcWeaverCli",
        "--add-data",
        "core\config\multipart_scoring.json;core\config",
        "--add-data",
        "7z;7z",
        "launch_cli.py"
    )
    exit 0
}

Invoke-PyInstaller @(
    "--noconfirm",
    "--clean",
    "ArcWeaver.spec"
)
