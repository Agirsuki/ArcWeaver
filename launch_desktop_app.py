from __future__ import annotations

import os
from pathlib import Path
import sys

def _configure_frozen_tcl_tk() -> None:
    """Point frozen GUI builds at bundled Tcl/Tk data directories."""

    if not getattr(sys, "frozen", False):
        return

    candidate_roots: list[Path] = []

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        candidate_roots.extend((base, base / "_internal"))

    exe_dir = Path(sys.executable).resolve().parent
    candidate_roots.extend((exe_dir, exe_dir / "_internal"))

    seen: set[Path] = set()
    for root in candidate_roots:
        if root in seen:
            continue
        seen.add(root)

        tcl_dir = root / "_tcl_data"
        tk_dir = root / "_tk_data"
        if tcl_dir.is_dir():
            os.environ.setdefault("TCL_LIBRARY", str(tcl_dir))
        if tk_dir.is_dir():
            os.environ.setdefault("TK_LIBRARY", str(tk_dir))
        if os.environ.get("TCL_LIBRARY") and os.environ.get("TK_LIBRARY"):
            return


_configure_frozen_tcl_tk()

from ui.desktop_app import main


if __name__ == "__main__":
    main()
