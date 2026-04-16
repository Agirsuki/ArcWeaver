# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.win32 import winmanifest, winresource


project_root = (
    Path(__file__).resolve().parent
    if "__file__" in globals()
    else Path.cwd().resolve()
)


def _skip_windows_resource_update(*_args, **_kwargs):
    return None


winresource.remove_all_resources = _skip_windows_resource_update
winmanifest.write_manifest_to_executable = _skip_windows_resource_update

datas = [
    (str(project_root / "core" / "config" / "multipart_scoring.json"), "core/config"),
    (str(project_root / "7z"), "7z"),
]

hiddenimports = [
    "send2trash",
]


def _find_script_entry(scripts, filename: str):
    expected = str((project_root / filename).resolve()).lower()
    for entry in scripts:
        script_path = str(Path(entry[1]).resolve()).lower()
        if script_path == expected:
            return entry
    raise RuntimeError(f"Script entry not found for {filename}")


a = Analysis(
    [
        str(project_root / "launch_desktop_app.py"),
        str(project_root / "launch_cli.py"),
    ],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

gui_exe = EXE(
    pyz,
    [_find_script_entry(a.scripts, "launch_desktop_app.py")],
    [],
    exclude_binaries=True,
    name="ArcWeaver",
    debug=False,
    bootloader_ignore_signals=False,
    icon="NONE",
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

cli_exe = EXE(
    pyz,
    [_find_script_entry(a.scripts, "launch_cli.py")],
    [],
    exclude_binaries=True,
    name="ArcWeaverCli",
    debug=False,
    bootloader_ignore_signals=False,
    icon="NONE",
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    gui_exe,
    cli_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ArcWeaver",
)
