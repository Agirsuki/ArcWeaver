from __future__ import annotations

"""Desktop session log writer."""

from datetime import datetime
from pathlib import Path
from tkinter import END


class SessionLogWriter:
    """Write UI log lines to both the widget and the session log file."""

    def __init__(self, log_widget, session_log_path: Path):
        self._log_widget = log_widget
        self._session_log_path = session_log_path

    def write(self, message: str) -> None:
        """Append one message to the live log and the persisted log file."""

        self._log_widget.insert(END, f"{message}\n")
        self._log_widget.see(END)
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._session_log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass

    def clear(self) -> None:
        """Clear the live log widget without deleting the persisted session file."""

        self._log_widget.delete("1.0", END)
