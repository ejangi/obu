#!/usr/bin/env python3
"""Install the repository's systemd user timer without embedding a stale path."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
USER_UNITS = Path.home() / ".config" / "systemd" / "user"


def main() -> int:
    config = ROOT / "config.toml"
    if not config.is_file():
        print(f"Create and configure {config} before enabling the timer.", file=sys.stderr)
        return 2
    USER_UNITS.mkdir(parents=True, exist_ok=True)
    service_template = (ROOT / "systemd" / "obu-backup.service.in").read_text()
    (USER_UNITS / "obu-backup.service").write_text(service_template.replace("@@PROJECT_ROOT@@", str(ROOT)) + "\n")
    shutil.copyfile(ROOT / "systemd" / "obu-backup.timer", USER_UNITS / "obu-backup.timer")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "obu-backup.timer"], check=True)
    print("Enabled obu-backup.timer. Inspect it with: systemctl --user list-timers obu-backup.timer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
