"""Private active-run state shared by backup execution and status."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path

from .config import Source


def active_run_file(state_dir: Path) -> Path:
    return state_dir / "runs" / "active.json"


def read_active_run(state_dir: Path) -> dict[str, object] | None:
    try:
        record = json.loads(active_run_file(state_dir).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def record_active_run(state_dir: Path, identifier: str, source: Source, phase: str, pid: int, log_path: Path) -> None:
    runs = state_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True, mode=0o700)
    runs.chmod(0o700)
    active = active_run_file(state_dir)
    temporary = active.with_name(f".{active.name}.{pid}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "id": identifier,
                "source": source.name,
                "phase": phase,
                "pid": pid,
                "process_start": process_start(pid),
                "started_at": datetime.now(UTC).isoformat(),
                "log": str(log_path),
            }
        )
        + "\n"
    )
    temporary.chmod(0o600)
    temporary.replace(active)


def clear_active_run(state_dir: Path) -> None:
    active_run_file(state_dir).unlink(missing_ok=True)


def recover_stale_active_run(state_dir: Path) -> Path | None:
    record = read_active_run(state_dir)
    if record is None or process_is_running(record):
        return None
    active = active_run_file(state_dir)
    identifier = str(record.get("id", "unknown")).replace("/", "_")
    archived = active.with_name(f"{identifier}.stale")
    active.replace(archived)
    archived.chmod(0o600)
    return archived


def process_is_running(record: dict[str, object]) -> bool:
    pid = record.get("pid")
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if process_state(pid) == "Z":
        return False
    expected_start = record.get("process_start")
    return not isinstance(expected_start, str) or process_start(pid) == expected_start


def process_start(pid: int) -> str | None:
    """Return Linux's process-start tick value, stable across PID reuse."""
    fields = process_stat_fields(pid)
    return fields[19] if fields is not None and len(fields) > 19 else None


def process_state(pid: int) -> str | None:
    """Return Linux's single-letter process state, such as ``Z`` for a zombie."""
    fields = process_stat_fields(pid)
    return fields[0] if fields else None


def process_stat_fields(pid: int) -> list[str] | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except (IndexError, OSError):
        return None
