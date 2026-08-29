#!/usr/bin/env python3
"""Restore a scoped backup into /tmp and verify it against its live source.

This is an opt-in integration test. It reads the encrypted remote and the
source, writes only a newly-created temporary directory, and removes that
directory afterwards unless --keep-temp is supplied.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path("/mnt/storage/Wallpapers")
DEFAULT_DRIVE = "secondary"


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore and checksum-check one OBU scoped backup in /tmp")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="original directory within the configured drive")
    parser.add_argument("--drive", default=DEFAULT_DRIVE, help="configured OBU source name")
    parser.add_argument("--keep-temp", action="store_true", help="keep the temporary restore directory for inspection")
    arguments = parser.parse_args(argv)

    source = arguments.source.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"source must be an existing directory: {source}")

    work = Path(tempfile.mkdtemp(prefix="obu-restore-", dir=tempfile.gettempdir()))
    restore_target = work / "restore"
    restore_target.mkdir()
    try:
        run([
            str(ROOT / "obu"),
            "restore",
            arguments.drive,
            str(restore_target),
            "--path",
            str(source),
        ])
        run([
            "rclone", "check", str(source), str(restore_target),
            "--one-way", "--links", "--log-level", "ERROR",
        ])
        print(f"restore checksum integration test passed: {source}")
        return 0
    finally:
        if arguments.keep_temp:
            print(f"temporary restore retained at: {work}")
        else:
            shutil.rmtree(work)


if __name__ == "__main__":
    raise SystemExit(main())
