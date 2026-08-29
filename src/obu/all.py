"""Back up every configured source."""

from __future__ import annotations

import argparse
from pathlib import Path

from .backup import run_backup
from .config import Settings


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--progress", action="store_true", help="show rclone transfer progress in this terminal")
    parser.add_argument("--print-command", action="store_true")


def run(settings: Settings, arguments: argparse.Namespace, project_root: Path | None = None) -> int:
    return run_backup(
        settings,
        list(settings.sources.values()),
        dry_run=arguments.dry_run,
        progress=arguments.progress,
        print_command=arguments.print_command,
    )
