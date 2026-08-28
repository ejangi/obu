"""The stable OBU command-line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .backup import AlreadyRunning, BackupError, backup_lock, check_command, copy_command, execute, persist_run, restore_command, run_id, validate_source
from .config import ConfigError, Settings, Source, load_settings
from .notify import send


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Safe rclone-crypt backup orchestration")
    result.add_argument("--config", type=Path, default=Path("config.toml"), help="TOML configuration file")
    commands = result.add_subparsers(dest="action", required=True)
    backup = commands.add_parser("backup", help="back up one configured source")
    backup.add_argument("source")
    backup.add_argument("--dry-run", action="store_true", help="ask rclone to simulate the copy")
    backup.add_argument("--print-command", action="store_true", help="print the command plan without running rclone")
    all_sources = commands.add_parser("all", help="back up every configured source")
    all_sources.add_argument("--dry-run", action="store_true")
    all_sources.add_argument("--print-command", action="store_true")
    restore = commands.add_parser("restore", help="restore a source's current backup to TARGET")
    restore.add_argument("source")
    restore.add_argument("target", type=Path)
    restore.add_argument("--dry-run", action="store_true")
    restore.add_argument("--print-command", action="store_true")
    commands.add_parser("status", help="show the latest recorded results")
    return result


def selected(settings: Settings, name: str) -> Source:
    try:
        return settings.sources[name]
    except KeyError as error:
        raise ConfigError(f"unknown source {name!r}; choose one of: {', '.join(sorted(settings.sources))}") from error


def print_plan(command: list[str]) -> None:
    print(json.dumps({"command": command}))


def run_backup(settings: Settings, sources: list[Source], *, dry_run: bool, print_command: bool) -> int:
    identifier = run_id()
    commands = [(source, copy_command(settings, source, identifier, dry_run)) for source in sources]
    if print_command:
        for source, command in commands:
            print(json.dumps({"source": source.name, "command": command}))
        return 0
    try:
        with backup_lock(settings.state_dir):
            for source, command in commands:
                validate_source(source)
                result = execute(command)
                persist_run(settings.state_dir, identifier, source, command, result)
                if result.returncode:
                    send("Backup failed", f"{source.name}: {result.stderr[-500:]}", urgent=True)
                    return result.returncode
                if settings.verify and not dry_run:
                    verification = execute(check_command(settings, source))
                    persist_run(settings.state_dir, identifier + "-check", source, check_command(settings, source), verification)
                    if verification.returncode:
                        send("Backup verification failed", f"{source.name}: {verification.stderr[-500:]}", urgent=True)
                        return verification.returncode
    except AlreadyRunning as error:
        send("Backup skipped", str(error))
        print(error, file=sys.stderr)
        return 75
    except BackupError as error:
        send("Backup could not start", str(error), urgent=True)
        print(error, file=sys.stderr)
        return 2
    send("Backup complete", ", ".join(source.name for source in sources))
    return 0


def show_status(settings: Settings) -> int:
    runs = settings.state_dir / "runs"
    if not runs.exists():
        print("No completed or failed backup runs have been recorded.")
        return 0
    for filename in sorted(runs.glob("*.json"), reverse=True)[:10]:
        record = json.loads(filename.read_text())
        print(f"{record['finished_at']}  {record['source']:<12} exit={record['returncode']}  {filename}")
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        settings = load_settings(arguments.config)
        if arguments.action == "status":
            return show_status(settings)
        if arguments.action == "restore":
            source = selected(settings, arguments.source)
            command = restore_command(settings, source, arguments.target, arguments.dry_run)
            if arguments.print_command:
                print_plan(command)
                return 0
            if not arguments.target.is_dir():
                raise ConfigError(f"restore target must be an existing directory: {arguments.target}")
            if any(arguments.target.iterdir()):
                raise ConfigError(f"restore target must be empty: {arguments.target}")
            result = execute(command)
            if result.returncode:
                send("Restore failed", result.stderr[-500:], urgent=True)
            return result.returncode
        sources = list(settings.sources.values()) if arguments.action == "all" else [selected(settings, arguments.source)]
        return run_backup(settings, sources, dry_run=arguments.dry_run, print_command=arguments.print_command)
    except ConfigError as error:
        print(f"obu-backup: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
