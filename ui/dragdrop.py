from __future__ import annotations

"""Windows-only drag-and-drop bridge for the Tk desktop UI."""

import ctypes
import os
from ctypes import wintypes
from typing import Callable
import tkinter as tk


class WindowsFileDrop:
    """Register a native WM_DROPFILES handler for a Tk widget."""

    WM_DROPFILES = 0x0233
    GWL_WNDPROC = -4

    def __init__(self, widget: tk.Misc, on_drop: Callable[[list[str]], None]):
        """Install the native window procedure hook and forward dropped paths."""

        self.widget = widget
        self.on_drop = on_drop
        self._old_proc = None
        if os.name != "nt":
            return

        self._hwnd = wintypes.HWND(self.widget.winfo_id())
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32

        lresult = ctypes.c_ssize_t
        wndproc_t = ctypes.WINFUNCTYPE(
            lresult,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        if hasattr(user32, "SetWindowLongPtrW"):
            self._set_wndproc = user32.SetWindowLongPtrW
            self._set_wndproc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            self._set_wndproc.restype = ctypes.c_void_p
        else:
            self._set_wndproc = user32.SetWindowLongW
            self._set_wndproc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            self._set_wndproc.restype = ctypes.c_long

        self._call_wndproc = user32.CallWindowProcW
        self._call_wndproc.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._call_wndproc.restype = lresult

        self._drag_query = shell32.DragQueryFileW
        self._drag_query.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_wchar_p,
            ctypes.c_uint,
        ]
        self._drag_query.restype = ctypes.c_uint

        self._drag_finish = shell32.DragFinish
        self._drag_finish.argtypes = [ctypes.c_void_p]
        self._drag_finish.restype = None

        @wndproc_t
        def _wndproc(hwnd_arg, msg, wparam, lparam):
            if msg == self.WM_DROPFILES:
                hdrop = ctypes.c_void_p(wparam)
                file_count = self._drag_query(hdrop, 0xFFFFFFFF, None, 0)
                paths: list[str] = []
                for index in range(file_count):
                    path_length = self._drag_query(hdrop, index, None, 0)
                    buffer = ctypes.create_unicode_buffer(path_length + 1)
                    self._drag_query(hdrop, index, buffer, path_length + 1)
                    paths.append(buffer.value)
                self._drag_finish(hdrop)
                if paths:
                    self.on_drop(paths)
                return 0
            return self._call_wndproc(
                ctypes.c_void_p(self._old_proc),
                hwnd_arg,
                msg,
                wparam,
                lparam,
            )

        self._new_proc = _wndproc
        self._old_proc = self._set_wndproc(
            self._hwnd,
            self.GWL_WNDPROC,
            ctypes.cast(self._new_proc, ctypes.c_void_p),
        )
        shell32.DragAcceptFiles(self._hwnd, True)
        self.widget.bind("<Destroy>", self._on_destroy, add="+")

    def _on_destroy(self, _event) -> None:
        """Restore the original window procedure when the widget is destroyed."""

        if os.name != "nt" or not self._old_proc:
            return
        try:
            self._set_wndproc(
                self._hwnd,
                self.GWL_WNDPROC,
                ctypes.c_void_p(self._old_proc),
            )
        except Exception:
            pass
