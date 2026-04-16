from __future__ import annotations

"""Filesystem deletion helpers with recycle-bin support on Windows."""

import ctypes
import os
import shutil
from ctypes import wintypes

try:
    from send2trash import send2trash
except ImportError:  # pragma: no cover
    send2trash = None


if os.name == "nt":
    FO_DELETE = 0x0003
    FOF_SILENT = 0x0004
    FOF_NOCONFIRMATION = 0x0010
    FOF_ALLOWUNDO = 0x0040
    FOF_NOERRORUI = 0x0400

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]


def safe_remove(
    path: str,
    *,
    use_recycle_bin: bool,
    error_callback=None,
) -> bool:
    """Remove a file or directory, optionally preferring the Windows recycle bin."""

    try:
        if not os.path.exists(path):
            return False
        if use_recycle_bin:
            recycled, recycle_error = _move_to_windows_recycle_bin(path)
            if recycled:
                return True
            if send2trash is not None:
                try:
                    send2trash(path)
                    return True
                except Exception as exc:  # pragma: no cover
                    recycle_error = f"{recycle_error}; send2trash failed: {exc}"
            if error_callback is not None and recycle_error:
                error_callback(recycle_error)
            return False
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True
    except Exception as exc:  # pragma: no cover - platform dependent
        action = "move to Windows recycle bin" if use_recycle_bin else "delete"
        if error_callback is not None:
            error_callback(f"{action} failed: {path}. reason: {exc}")
        return False


def _move_to_windows_recycle_bin(path: str) -> tuple[bool, str]:
    """Try the native Windows recycle bin API first."""

    if os.name != "nt":
        return False, "Windows recycle bin is only available on Windows."

    abs_path = os.path.abspath(path)
    operation = SHFILEOPSTRUCTW()
    operation.wFunc = FO_DELETE
    operation.pFrom = f"{abs_path}\0\0"
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        return False, f"Windows recycle bin operation failed: {abs_path}. code: {result}"
    if operation.fAnyOperationsAborted:
        return False, f"Windows recycle bin operation was canceled: {abs_path}"
    return True, ""
