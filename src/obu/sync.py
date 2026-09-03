"""Synchronize one configured source, removing excluded remote paths."""

from __future__ import annotations

import argparse
from pathlib import Path

from .backup import LIVE_STATS_FLAGS, destination, run_transfer
from .config import Settings, Source
from .sources import selected


def sync_command(settings: Settings, source: Source, dry_run: bool = False, progress: bool = False) -> list[str]:
    command = [
        "rclone", "sync", str(source.path), destination(settings, source), "--delete-excluded",
        "--create-empty-src-dirs", "--links", "--log-level", "ERROR", *LIVE_STATS_FLAGS,
    ]
    for rule in source.filter_rules:
        command.extend(["--filter", rule])
    if dry_run:
        command.append("--dry-run")
    if progress:
        command.append("--progress")
    return command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", metavar="SOURCE", help="configured source name")
    parser.add_argument("--dry-run", action="store_true", help="show what would be deleted or copied")
    parser.add_argument("--progress", action="store_true", help="show rclone transfer progress in this terminal")
    parser.add_argument("--print-command", action="store_true", help="print the command plan without running rclone")


def run(settings: Settings, arguments: argparse.Namespace, project_root: Path | None = None) -> int:
    return run_transfer(
        settings,
        [selected(settings, arguments.source)],
        command_builder=sync_command,
        phase="sync",
        operation="Sync",
        dry_run=arguments.dry_run,
        progress=arguments.progress,
        print_command=arguments.print_command,
    )
