"""Best-effort desktop notifications; logging remains the source of truth."""

from __future__ import annotations

import shutil
import subprocess


def send(summary: str, body: str, *, urgent: bool = False) -> None:
    executable = shutil.which("notify-send")
    if executable is None:
        return
    command = [executable, "--app-name", "OBU Backup"]
    if urgent:
        command.extend(["--urgency", "critical"])
    command.extend([summary, body])
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
