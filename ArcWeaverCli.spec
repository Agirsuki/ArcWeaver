# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.win32 import winmanifest, winresource


def _skip_windows_resource_update(*_args, **_kwargs):
    return None


winresource.remove_all_resources = _skip_windows_resource_update
winmanifest.write_manifest_to_executable = _skip_windows_resource_update


a = Analysis(
    ['launch_cli.py'],
    pathex=[],
    binaries=[],
    datas=[('core\\config\\multipart_scoring.json', 'core\\config'), ('7z', '7z')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ArcWeaverCli',
    debug=False,
    bootloader_ignore_signals=False,
    icon='NONE',
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
