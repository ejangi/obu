"""Show completed rclone output or follow a live run log."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .config import Settings


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", help="limit records to one configured source")
    parser.add_argument("--tail", type=positive_int, default=50, help="number of output lines to show (default: 50)")
    parser.add_argument("--watch", action="store_true", help="follow the latest matching live run log")


def run(settings: Settings, arguments: argparse.Namespace, project_root: Path | None = None) -> int:
    if arguments.watch:
        return watch(settings, source=arguments.source, tail=arguments.tail)
    runs = settings.state_dir / "runs"
    records: list[tuple[Path, dict[str, object]]] = []
    if runs.exists():
        for filename in runs.glob("*.json"):
            try:
                record = json.loads(filename.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if arguments.source is None or record.get("source") == arguments.source:
                records.append((filename, record))
    if not records:
        selector = f" for source {arguments.source!r}" if arguments.source else ""
        print(f"No completed run output has been recorded{selector}.")
        return 0
    filename, record = max(records, key=lambda item: item[0].stat().st_mtime)
    print(
        f"{record.get('finished_at', 'unknown time')}  "
        f"source={record.get('source', 'unknown')}  "
        f"exit={record.get('returncode', 'unknown')}  {filename}"
    )
    lines = str(record.get("stderr", "")).splitlines()
    if lines:
        print("\n".join(lines[-arguments.tail:]))
    else:
        print("No rclone output was recorded for this run.")
    return 0


def watch(settings: Settings, *, source: str | None, tail: int) -> int:
    """Follow the newest matching log, switching when a new run starts."""
    runs = settings.state_dir / "runs"
    followed: Path | None = None
    offset = 0
    try:
        while True:
            filename = newest_log(runs, source)
            if filename is not None and filename != followed:
                followed = filename
                content = filename.read_text(errors="replace")
                lines = content.splitlines()
                if lines:
                    print("\n".join(lines[-tail:]), flush=True)
                offset = filename.stat().st_size
            elif followed is not None:
                size = followed.stat().st_size
                if size < offset:
                    offset = 0
                if size > offset:
                    with followed.open("rb") as handle:
                        handle.seek(offset)
                        chunk = handle.read()
                    sys.stdout.write(chunk.decode(errors="replace"))
                    sys.stdout.flush()
                    offset = size
            time.sleep(0.1)
    except KeyboardInterrupt:
        return 0


def newest_log(runs: Path, source: str | None) -> Path | None:
    if not runs.exists():
        return None
    files = [
        filename
        for filename in runs.glob("*.log")
        if source is None or filename.name.endswith(f"-{source}.log")
    ]
    return max(files, key=lambda filename: filename.stat().st_mtime, default=None)


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number
