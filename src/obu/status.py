"""Summarize full-source transfers, verification, and actionable failures."""

from __future__ import annotations

from collections import deque
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
    records = read_records(runs)
    for name, source in settings.sources.items():
        destination = f"{settings.remote}hosts/{settings.host}/{name}/current"
        matching = [
            (path, record) for path, record in records
            if record.get("source") == name
            and (record["phase"] == "preflight" or record["command"][2:4] == [str(source.path), destination])
        ]
        print(f"{name} ({source.path})")
        transfers = [item for item in matching if item[1]["phase"] in ("copy", "sync")]
        checks = [item for item in matching if item[1]["phase"] == "cryptcheck"]
        latest_transfer = transfers[0][1] if transfers else None
        latest_check = checks[0][1] if checks else None
        if latest_transfer:
            label = "Copy" if latest_transfer["phase"] == "copy" else "Sync"
            print(f"  {label}: {outcome(latest_transfer)} at {latest_transfer['finished_at']}")
        else:
            print("  Copy: never recorded")
        if latest_check and (not latest_transfer or latest_check["finished_at"] >= latest_transfer["finished_at"]):
            print(f"  Verification: {outcome(latest_check)} at {latest_check['finished_at']}")
        else:
            print("  Verification: not completed for latest copy")
        verified = next((record for _, record in checks if record["returncode"] == 0 and not record.get("skipped_vms") and not record.get("skipped_vm_images")), None)
        print(f"  Last verified full backup: {verified['finished_at'] if verified else 'never'}")
        if matching:
            skipped = matching[0][1].get("skipped_vm_images", matching[0][1].get("skipped_vms", []))
            if skipped:
                print(f"  VM images skipped: {', '.join(skipped)}")
        if matching and matching[0][1]["returncode"]:
            path, latest = matching[0]
            for line in failure_lines(path, latest):
                print(f"  Error: {line}")
            print(f"  Details: ./obu logs --source {name}")
    if not records:
        print("No completed or failed backup runs have been recorded.")
    return 0


def read_records(runs: Path) -> list[tuple[Path, dict]]:
    records = []
    for path in runs.glob("*.json"):
        if path.name == "active.json":
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        command = record.get("command")
        if not isinstance(command, list) or len(command) < 4:
            continue
        # Older records may predate the phase field.
        record.setdefault("phase", command[1])
        if not isinstance(record.get("finished_at"), str) or not isinstance(record.get("returncode"), int):
            continue
        records.append((path, record))
    return sorted(records, key=lambda item: item[1]["finished_at"], reverse=True)


def outcome(record: dict) -> str:
    return "succeeded" if record["returncode"] == 0 else f"failed (exit={record['returncode']})"


def failure_lines(path: Path, record: dict) -> list[str]:
    """Read the full log when available; capped records may contain only stats."""
    def select(lines) -> list[str]:
        errors: deque[str] = deque(maxlen=3)
        for line in lines:
            line = line.strip()
            if not line or (" / " in line and "ETA" in line):
                continue
            if line not in errors:
                errors.append(line)
        return list(errors)

    try:
        with path.with_suffix(".log").open(errors="replace") as handle:
            return select(handle)
    except OSError:
        return select(str(record.get("stderr", "")).splitlines())


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
