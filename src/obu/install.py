"""Install and enable OBU's user-level systemd timer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from .config import Settings


class InstallError(RuntimeError):
    """A safe-to-show systemd installation error."""


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--print-command", action="store_true", help="print the systemd setup plan without changing user units")


def run(settings: Settings, arguments: argparse.Namespace, project_root: Path | None = None) -> int:
    install_timer(project_root or Path.cwd(), print_command=arguments.print_command)
    return 0


def install_timer(project_root: Path, *, print_command: bool = False) -> None:
    """Install and enable the timer, or print its side-effect plan."""
    service_template = project_root / "systemd" / "obu-backup.service.in"
    timer_template = project_root / "systemd" / "obu-backup.timer"
    if not service_template.is_file() or not timer_template.is_file():
        raise InstallError(f"systemd unit templates are missing from {project_root}")
    user_units = Path.home() / ".config" / "systemd" / "user"
    commands = [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "obu-backup.timer"],
    ]
    if print_command:
        print(json.dumps({"service": str(service_template), "timer": str(timer_template), "commands": commands}))
        return
    try:
        user_units.mkdir(parents=True, exist_ok=True)
        service = service_template.read_text().replace("@@PROJECT_ROOT@@", str(project_root))
        (user_units / "obu-backup.service").write_text(service + "\n")
        shutil.copyfile(timer_template, user_units / "obu-backup.timer")
        for command in commands:
            subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise InstallError(f"could not enable obu-backup.timer: {error}") from error
    print("Enabled obu-backup.timer. Inspect it with: systemctl --user list-timers obu-backup.timer")
