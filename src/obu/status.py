"""List the most recent completed or failed OBU runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .activity import process_is_running, read_active_run
from .config import Settings


def configure(parser: argparse.ArgumentParser) -> None:
    return None


def run(settings: Settings, arguments: argparse.Namespace, project_root: Path | None = None) -> int:
    runs = settings.state_dir / "runs"
    active = read_active_run(settings.state_dir)
    if active:
        if process_is_running(active):
            show_active_run(active)
        else:
            print("Stale active run marker detected; the next OBU backup will archive it before starting.")
    if not runs.exists():
        print("No completed or failed backup runs have been recorded.")
        return 0
    for filename in sorted((file for file in runs.glob("*.json") if file.name != "active.json"), reverse=True)[:10]:
        record = json.loads(filename.read_text())
        print(f"{record['finished_at']}  {record['source']:<12} exit={record['returncode']}  {filename}")
    return 0


def show_active_run(record: dict[str, object]) -> None:
    print(
        f"Active: {record.get('source', 'unknown')} ({record.get('phase', 'unknown')})  "
        f"pid={record.get('pid', 'unknown')}  started={record.get('started_at', 'unknown')}"
    )
    log_value = record.get("log")
    if isinstance(log_value, str):
        latest = latest_log_line(Path(log_value))
        if latest:
            print(f"Latest rclone statistic: {latest}")


def latest_log_line(filename: Path) -> str | None:
    try:
        lines = filename.read_text(errors="replace").splitlines()
    except OSError:
        return None
    return next((line for line in reversed(lines) if line.strip()), None)
