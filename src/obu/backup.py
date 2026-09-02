"""Back up one configured source, optionally scoped to a file or folder."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
from shutil import get_terminal_size
import struct
import subprocess
import sys
import tempfile
import termios
from typing import BinaryIO, Callable, Iterator

from .activity import clear_active_run, record_active_run, recover_stale_active_run
from .config import Settings, Source
from .notify import send
from .sources import scoped, selected


class BackupError(RuntimeError):
    pass


class AlreadyRunning(BackupError):
    pass


class RunCancelled(BackupError):
    def __init__(self, result: subprocess.CompletedProcess[str]) -> None:
        super().__init__("backup cancelled by user")
        self.result = result


MAX_RECORDED_OUTPUT_BYTES = 16 * 1024
LIVE_STATS_FLAGS = ["--stats", "30s", "--stats-one-line", "--stats-log-level", "ERROR"]
CANCELLED_RETURN_CODE = 130
CANCELLED_SIGNAL = "SIGINT"
PTY_POLL_SECONDS = 0.25


def run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def destination(settings: Settings, source: Source) -> str:
    return destination_root(settings, source) + remote_suffix(source.relative_path)


def history_destination(settings: Settings, source: Source, identifier: str) -> str:
    return f"{settings.remote}hosts/{settings.host}/{source.name}/history/{identifier}" + remote_suffix(source.relative_path)


def destination_root(settings: Settings, source: Source) -> str:
    return f"{settings.remote}hosts/{settings.host}/{source.name}/current"


def remote_suffix(relative_path: Path) -> str:
    return "" if relative_path == Path(".") else f"/{relative_path.as_posix()}"


def copy_command(settings: Settings, source: Source, identifier: str, dry_run: bool = False, progress: bool = False) -> list[str]:
    command = [
        "rclone", "copy", str(source.path), destination(settings, source),
        "--backup-dir", history_destination(settings, source, identifier),
        "--create-empty-src-dirs", "--links", "--log-level", "ERROR", *LIVE_STATS_FLAGS,
    ]
    for rule in source.filter_rules:
        command.extend(["--filter", rule])
    if dry_run:
        command.append("--dry-run")
    if progress:
        command.append("--progress")
    return command


def check_command(settings: Settings, source: Source, progress: bool = False) -> list[str]:
    command = [
        "rclone", "cryptcheck", str(source.path), destination(settings, source), "--one-way", "--links", "--log-level", "ERROR",
        *LIVE_STATS_FLAGS,
    ]
    for rule in source.filter_rules:
        command.extend(["--filter", rule])
    if progress:
        command.append("--progress")
    return command


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", metavar="SOURCE", help="configured source name: 'primary' or 'secondary'")
    parser.add_argument("path", type=Path, nargs="?", metavar="PATH", help="optional file or directory inside SOURCE")
    parser.add_argument("--dry-run", action="store_true", help="ask rclone to simulate the copy")
    parser.add_argument("--progress", action="store_true", help="show rclone transfer progress in this terminal")
    parser.add_argument("--print-command", action="store_true", help="print the command plan without running rclone")


def run(settings: Settings, arguments: argparse.Namespace, project_root: Path | None = None) -> int:
    source = selected(settings, arguments.source)
    return run_backup(
        settings,
        [scoped(source, arguments.path) if arguments.path else source],
        dry_run=arguments.dry_run,
        progress=arguments.progress,
        print_command=arguments.print_command,
    )


@contextmanager
def backup_lock(state_dir: Path) -> Iterator[None]:
    ensure_private_directory(state_dir)
    lock_file = (state_dir / "backup.lock").open("w")
    (state_dir / "backup.lock").chmod(0o600)
    try:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AlreadyRunning("another OBU backup is already running") from error
        recover_stale_active_run(state_dir)
        yield
    finally:
        lock_file.close()


def validate_source(source: Source) -> None:
    if not source.path.is_dir():
        raise BackupError(f"source is not an available directory: {source.path}")


def print_plan(command: list[str], verification_command: list[str] | None = None) -> None:
    plan: dict[str, list[str]] = {"command": command}
    if verification_command is not None:
        plan["verification_command"] = verification_command
    print(json.dumps(plan))


def run_backup(settings: Settings, sources: list[Source], *, dry_run: bool, progress: bool, print_command: bool) -> int:
    identifier = run_id()
    commands = [
        (source, copy_command(settings, source, identifier, dry_run, progress), check_command(settings, source, progress))
        for source in sources
    ]
    if print_command:
        for source, command, verification_command in commands:
            print(json.dumps({"source": source.name, "command": command, "verification_command": verification_command}))
        return 0
    try:
        with backup_lock(settings.state_dir):
            for source, command, verification_command in commands:
                validate_source(source)
                copy_log = run_log_path(settings.state_dir, identifier, source)
                try:
                    result = execute(
                        command,
                        progress=progress,
                        log_path=copy_log,
                        on_started=lambda pid: record_active_run(settings.state_dir, identifier, source, "copy", pid, copy_log),
                    )
                except RunCancelled as cancellation:
                    persist_run(settings.state_dir, identifier, source, command, cancellation.result, phase="copy", cancelled=True)
                    print("Backup cancelled by user.", file=sys.stderr)
                    return CANCELLED_RETURN_CODE
                finally:
                    clear_active_run(settings.state_dir)
                persist_run(settings.state_dir, identifier, source, command, result, phase="copy")
                if result.returncode:
                    send("Backup completed with errors", f"{source.name}: See obu logs for details.", urgent=True)
                    return result.returncode
                if settings.verify and not dry_run:
                    verification_id = identifier + "-check"
                    verification_log = run_log_path(settings.state_dir, verification_id, source)
                    try:
                        verification = execute(
                            verification_command,
                            progress=progress,
                            log_path=verification_log,
                            on_started=lambda pid: record_active_run(
                                settings.state_dir, verification_id, source, "cryptcheck", pid, verification_log
                            ),
                        )
                    except RunCancelled as cancellation:
                        persist_run(
                            settings.state_dir,
                            verification_id,
                            source,
                            verification_command,
                            cancellation.result,
                            phase="cryptcheck",
                            cancelled=True,
                        )
                        print("Backup cancelled by user.", file=sys.stderr)
                        return CANCELLED_RETURN_CODE
                    finally:
                        clear_active_run(settings.state_dir)
                    persist_run(settings.state_dir, verification_id, source, verification_command, verification, phase="cryptcheck")
                    if verification.returncode:
                        send("Backup completed with errors", f"{source.name}: See obu logs for details.", urgent=True)
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


def persist_run(
    state_dir: Path,
    identifier: str,
    source: Source,
    command: list[str],
    result: subprocess.CompletedProcess[str],
    *,
    phase: str,
    cancelled: bool = False,
) -> Path:
    runs = state_dir / "runs"
    ensure_private_directory(runs)
    record = {
        "id": identifier,
        "source": source.name,
        "phase": phase,
        "finished_at": datetime.now(UTC).isoformat(),
        "returncode": result.returncode,
        "command": command,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if cancelled:
        record.update({"cancelled": True, "signal": CANCELLED_SIGNAL})
    filename = runs / f"{identifier}-{source.name}.json"
    filename.write_text(json.dumps(record, indent=2) + "\n")
    filename.chmod(0o600)
    return filename


def run_log_path(state_dir: Path, identifier: str, source: Source) -> Path:
    runs = state_dir / "runs"
    ensure_private_directory(runs)
    filename = runs / f"{identifier}-{source.name}.log"
    filename.touch()
    filename.chmod(0o600)
    return filename


def ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    except OSError as error:
        raise BackupError(f"cannot secure OBU state directory {path}: {error}") from error


def recorded_output(error_output: BinaryIO) -> str:
    """Return only the final bounded portion of rclone's output."""
    output_size = error_output.tell()
    error_output.seek(max(0, output_size - MAX_RECORDED_OUTPUT_BYTES))
    stderr = error_output.read().decode(errors="replace")
    if output_size > MAX_RECORDED_OUTPUT_BYTES:
        return f"[recorded final {MAX_RECORDED_OUTPUT_BYTES} bytes of rclone output]\n{stderr}"
    return stderr


def execute(
    command: list[str],
    *,
    progress: bool = False,
    log_path: Path | None = None,
    on_started: Callable[[int], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        with tempfile.TemporaryFile() as error_output:
            if progress:
                with log_path.open("ab") if log_path else null_binary_output() as live_log:
                    return execute_with_progress(command, error_output, live_log, on_started)
            if log_path:
                with log_path.open("ab") as live_log:
                    return execute_with_log(command, error_output, live_log, on_started)
            return execute_with_log(command, error_output, None, on_started)
    except FileNotFoundError as error:
        raise BackupError("rclone is not installed or is not available on PATH") from error


def execute_with_log(
    command: list[str], error_output: BinaryIO, live_log: BinaryIO | None, on_started: Callable[[int], None] | None
) -> subprocess.CompletedProcess[str]:
    """Capture rclone output while appending it to a live private log."""
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    try:
        if on_started:
            on_started(process.pid)
        assert process.stderr is not None
        while chunk := os.read(process.stderr.fileno(), 8192):
            record_chunk(error_output, live_log, chunk)
        returncode = process.wait()
        return subprocess.CompletedProcess(command, returncode, stdout="", stderr=recorded_output(error_output))
    except KeyboardInterrupt:
        stop_process(process, signal.SIGINT)
        drain_pipe(process.stderr, error_output, live_log)
        raise RunCancelled(cancelled_result(command, error_output, live_log))
    except BaseException:
        stop_process(process, signal.SIGTERM)
        raise


def execute_with_progress(
    command: list[str],
    error_output: BinaryIO,
    live_log: BinaryIO | None = None,
    on_started: Callable[[int], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Give rclone a terminal and relay its progress while retaining output."""
    master_fd, slave_fd = pty.openpty()
    size = get_terminal_size(fallback=(80, 24))
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", size.lines, size.columns, 0, 0))
    try:
        process = subprocess.Popen(command, stdout=slave_fd, stderr=slave_fd, start_new_session=True)
        if on_started:
            on_started(process.pid)
    except Exception:
        os.close(master_fd)
        raise
    finally:
        os.close(slave_fd)
    try:
        while process.poll() is None:
            readable, _, _ = select.select([master_fd], [], [], PTY_POLL_SECONDS)
            if not readable:
                continue
            chunk = read_pty(master_fd)
            if chunk is None:
                break
            record_chunk(error_output, live_log, chunk)
            sys.stderr.buffer.write(chunk)
            sys.stderr.buffer.flush()
        returncode = process.wait()
        drain_available_pty(master_fd, error_output, live_log)
    except KeyboardInterrupt:
        stop_process(process, signal.SIGINT)
        drain_pty(master_fd, error_output, live_log)
        raise RunCancelled(cancelled_result(command, error_output, live_log))
    except BaseException:
        stop_process(process, signal.SIGTERM)
        raise
    finally:
        os.close(master_fd)
    return subprocess.CompletedProcess(command, returncode, stdout="", stderr=recorded_output(error_output))


@contextmanager
def null_binary_output() -> Iterator[None]:
    yield None


def record_chunk(error_output: BinaryIO, live_log: BinaryIO | None, chunk: bytes) -> None:
    error_output.write(chunk)
    if live_log is not None:
        live_log.write(chunk)
        live_log.flush()


def stop_process(process: subprocess.Popen[bytes], signum: signal.Signals) -> None:
    """Signal rclone and any descendants, then reap the child process."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def drain_pipe(error_pipe: BinaryIO | None, error_output: BinaryIO, live_log: BinaryIO | None) -> None:
    if error_pipe is None:
        return
    while chunk := os.read(error_pipe.fileno(), 8192):
        record_chunk(error_output, live_log, chunk)


def drain_pty(master_fd: int, error_output: BinaryIO, live_log: BinaryIO | None) -> None:
    while True:
        chunk = read_pty(master_fd)
        if chunk is None:
            return
        record_chunk(error_output, live_log, chunk)


def drain_available_pty(master_fd: int, error_output: BinaryIO, live_log: BinaryIO | None) -> None:
    """Record buffered PTY output without waiting for lingering descendants."""
    while select.select([master_fd], [], [], 0)[0]:
        chunk = read_pty(master_fd)
        if chunk is None:
            return
        record_chunk(error_output, live_log, chunk)


def read_pty(master_fd: int) -> bytes | None:
    """Read one PTY chunk, treating its Linux hangup signal as end of output."""
    try:
        chunk = os.read(master_fd, 8192)
    except OSError as error:
        if error.errno == errno.EIO:
            return None
        raise
    return chunk or None


def cancelled_result(
    command: list[str], error_output: BinaryIO, live_log: BinaryIO | None
) -> subprocess.CompletedProcess[str]:
    record_chunk(error_output, live_log, b"OBU: cancelled by user (SIGINT); rclone child process exited.\n")
    return subprocess.CompletedProcess(command, CANCELLED_RETURN_CODE, stdout="", stderr=recorded_output(error_output))
