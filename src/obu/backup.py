"""Plans and executes backups without touching rclone's credential store."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
import subprocess
from typing import Iterator

from .config import Settings, Source


class BackupError(RuntimeError):
    pass


class AlreadyRunning(BackupError):
    pass


def run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def destination(settings: Settings, source: Source) -> str:
    return f"{settings.remote}hosts/{settings.host}/{source.name}/current"


def history_destination(settings: Settings, source: Source, identifier: str) -> str:
    return f"{settings.remote}hosts/{settings.host}/{source.name}/history/{identifier}"


def copy_command(settings: Settings, source: Source, identifier: str, dry_run: bool = False) -> list[str]:
    command = [
        "rclone", "copy", str(source.path), destination(settings, source),
        "--backup-dir", history_destination(settings, source, identifier),
        "--create-empty-src-dirs", "--log-level", "INFO", "--stats-one-line",
    ]
    for rule in source.filter_rules:
        command.extend(["--filter", rule])
    if dry_run:
        command.append("--dry-run")
    return command


def check_command(settings: Settings, source: Source) -> list[str]:
    command = ["rclone", "check", str(source.path), destination(settings, source), "--one-way", "--log-level", "INFO"]
    for rule in source.filter_rules:
        command.extend(["--filter", rule])
    return command


def restore_command(settings: Settings, source: Source, target: Path, dry_run: bool = False) -> list[str]:
    command = ["rclone", "copy", destination(settings, source), str(target), "--log-level", "INFO", "--stats-one-line"]
    if dry_run:
        command.append("--dry-run")
    return command


@contextmanager
def backup_lock(state_dir: Path) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_file = (state_dir / "backup.lock").open("w")
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AlreadyRunning("another OBU backup is already running") from error
        yield
    finally:
        lock_file.close()


def validate_source(source: Source) -> None:
    if not source.path.is_dir():
        raise BackupError(f"source is not an available directory: {source.path}")


def persist_run(state_dir: Path, identifier: str, source: Source, command: list[str], result: subprocess.CompletedProcess[str]) -> Path:
    runs = state_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    record = {
        "id": identifier,
        "source": source.name,
        "finished_at": datetime.now(UTC).isoformat(),
        "returncode": result.returncode,
        "command": command,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    filename = runs / f"{identifier}-{source.name}.json"
    filename.write_text(json.dumps(record, indent=2) + "\n")
    return filename


def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, text=True, capture_output=True, check=False)
    except FileNotFoundError as error:
        raise BackupError("rclone is not installed or is not available on PATH") from error
