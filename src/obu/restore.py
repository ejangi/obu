"""Restore one source's current backup into an empty target directory."""

from __future__ import annotations

import argparse
from pathlib import Path

from .backup import destination, execute
from .config import ConfigError, Settings, Source
from .notify import send
from .sources import scoped, selected


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", metavar="SOURCE", help="configured source name")
    parser.add_argument("target", type=Path, metavar="TARGET", help="existing empty directory that receives restored files")
    parser.add_argument("--path", type=Path, help="optional file or directory inside SOURCE")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--progress", action="store_true", help="show rclone transfer progress in this terminal")
    parser.add_argument("--print-command", action="store_true")


def run(settings: Settings, arguments: argparse.Namespace, project_root: Path | None = None) -> int:
    source = selected(settings, arguments.source)
    if arguments.path:
        source = scoped(source, arguments.path)
    command = restore_command(settings, source, arguments.target, arguments.dry_run, arguments.progress)
    if arguments.print_command:
        print_plan(command)
        return 0
    if not arguments.target.is_dir():
        raise ConfigError(f"restore target must be an existing directory: {arguments.target}")
    if any(arguments.target.iterdir()):
        raise ConfigError(f"restore target must be empty: {arguments.target}")
    result = execute(command, progress=arguments.progress)
    if result.returncode:
        send("Restore failed", result.stderr[-500:], urgent=True)
    return result.returncode


def print_plan(command: list[str]) -> None:
    import json

    print(json.dumps({"command": command}))


def restore_command(settings: Settings, source: Source, target: Path, dry_run: bool = False, progress: bool = False) -> list[str]:
    command = ["rclone", "copy", destination(settings, source), str(target), "--links", "--log-level", "ERROR"]
    if dry_run:
        command.append("--dry-run")
    if progress:
        command.append("--progress")
    return command
