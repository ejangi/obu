from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from obu.config import load_settings
from obu.install import install_timer


ROOT = Path(__file__).parents[1]


def write_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(
        """remote = "obu-crypt:"
host = "test-host"
state_dir = "{state}"

[sources.primary]
path = "/data/primary"
filters = ["common", "primary"]

[filters.common]
rules = ["- **/.cache/**", "- **/*.tmp"]

[filters.primary]
rules = [
    "- /Downloads/rebuildable/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/Cache/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/Code Cache/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/GPUCache/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/DawnGraphiteCache/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/DawnWebGPUCache/**",
    "- **/.config/BraveSoftware/Brave-Browser/Safe Browsing/**",
    "- **/.config/Element/Cache/**",
    "- **/.config/Element/GPUCache/**",
    "- **/.var/app/org.signal.Signal/config/Signal/GPUCache/**",
    "- **/.var/app/org.signal.Signal/config/Signal/DawnGraphiteCache/**",
    "- **/.var/app/org.signal.Signal/config/Signal/DawnWebGPUCache/**",
    "- **/.var/app/org.signal.Signal/config/Signal/sql/db.sqlite-shm",
    "- **/.config/t3code/**/Cache/**",
    "- **/.config/t3code/**/Code Cache/**",
    "- **/.config/t3code/**/GPUCache/**",
    "- **/.config/t3code/**/DawnGraphiteCache/**",
    "- **/.config/t3code/**/DawnWebGPUCache/**",
    "- **/.config/t3code/**/DIPS-wal",
    "- **/.local/share/gvfs-metadata/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/IndexedDB/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/Local Extension Settings/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/Local Storage/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/Session Storage/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/Sessions/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/Sync Data/**",
    "- **/.config/BraveSoftware/Brave-Browser/**/WebStorage/**",
    "- **/.config/t3code/Cache/**",
    "- **/.config/t3code/GPUCache/**",
    "- **/.config/t3code/DawnGraphiteCache/**",
    "- **/.config/t3code/DawnWebGPUCache/**",
    "- **/.config/t3code/DIPS-wal",
]
""".format(state=tmp_path / "state")
    )
    return config


class BackupCliTests(unittest.TestCase):
    """The CLI's print plan is the supported seam for reviewing a backup."""

    def run_cli(self, config: Path, *command: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ | {"PYTHONPATH": str(ROOT / "src")}
        return subprocess.run(
        [sys.executable, "-m", "obu", "--config", str(config), *(command or ("backup", "primary", "--print-command"))],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        )

    def run_root_cli(self, *command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(ROOT / "obu"), *command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_help_aliases_use_the_specific_command_documentation(self) -> None:
        for help_option in ("--help", "-h", "-?"):
            with self.subTest(help_option=help_option):
                root_help = self.run_root_cli(help_option)
                logs_help = self.run_root_cli("logs", help_option)

                self.assertEqual(root_help.returncode, 0, root_help.stderr)
                self.assertIn("{backup,all,sync,restore,status,logs,install}", root_help.stdout)
                self.assertEqual(logs_help.returncode, 0, logs_help.stderr)
                self.assertIn("Show completed rclone output or follow a live run log.", logs_help.stdout)
                self.assertIn("--source", logs_help.stdout)
                self.assertIn("--tail", logs_help.stdout)
                self.assertNotIn("back up one configured source", logs_help.stdout)

    def test_backup_help_describes_the_source_names_and_optional_path(self) -> None:
        result = self.run_root_cli("backup", "--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SOURCE [PATH]", result.stdout)
        self.assertIn("configured source name", result.stdout)

    def test_restore_help_describes_its_uppercase_positional_arguments(self) -> None:
        result = self.run_root_cli("restore", "--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SOURCE TARGET", result.stdout)
        self.assertIn("configured source name", result.stdout)
        self.assertIn("existing empty directory", result.stdout)

    def test_backup_prints_a_copy_plan_without_obu_managed_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            result = self.run_cli(config)

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        command = plan["command"]
        self.assertEqual(command[:3], ["rclone", "copy", "/data/primary"])
        self.assertEqual(command[3], "obu-crypt:hosts/test-host/primary/current")
        self.assertNotIn("--backup-dir", command)
        self.assertIn("--links", command)
        self.assertEqual(command[command.index("--log-level") + 1], "ERROR")
        self.assertEqual(command[command.index("--stats") + 1], "30s")
        self.assertIn("--stats-one-line", command)
        self.assertEqual(command[command.index("--stats-log-level") + 1], "ERROR")
        self.assertEqual(plan["verification_command"][:2], ["rclone", "cryptcheck"])
        self.assertIn("--one-way", plan["verification_command"])
        self.assertEqual(plan["verification_command"][plan["verification_command"].index("--stats") + 1], "30s")
        self.assertNotIn("--filter-from", command)
        self.assertEqual(
            [command[index + 1] for index, item in enumerate(command) if item == "--filter"],
            [
                "- **/.cache/**",
                "- **/*.tmp",
                "- /Downloads/rebuildable/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/Cache/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/Code Cache/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/GPUCache/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/DawnGraphiteCache/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/DawnWebGPUCache/**",
                "- **/.config/BraveSoftware/Brave-Browser/Safe Browsing/**",
                "- **/.config/Element/Cache/**",
                "- **/.config/Element/GPUCache/**",
                "- **/.var/app/org.signal.Signal/config/Signal/GPUCache/**",
                "- **/.var/app/org.signal.Signal/config/Signal/DawnGraphiteCache/**",
                "- **/.var/app/org.signal.Signal/config/Signal/DawnWebGPUCache/**",
                "- **/.var/app/org.signal.Signal/config/Signal/sql/db.sqlite-shm",
                "- **/.config/t3code/**/Cache/**",
                "- **/.config/t3code/**/Code Cache/**",
                "- **/.config/t3code/**/GPUCache/**",
                "- **/.config/t3code/**/DawnGraphiteCache/**",
                "- **/.config/t3code/**/DawnWebGPUCache/**",
                "- **/.config/t3code/**/DIPS-wal",
                "- **/.local/share/gvfs-metadata/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/IndexedDB/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/Local Extension Settings/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/Local Storage/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/Session Storage/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/Sessions/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/Sync Data/**",
                "- **/.config/BraveSoftware/Brave-Browser/**/WebStorage/**",
                "- **/.config/t3code/Cache/**",
                "- **/.config/t3code/GPUCache/**",
                "- **/.config/t3code/DawnGraphiteCache/**",
                "- **/.config/t3code/DawnWebGPUCache/**",
                "- **/.config/t3code/DIPS-wal",
            ],
        )

    def test_sync_plan_deletes_currently_excluded_destination_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            result = self.run_cli(config, "sync", "primary", "--print-command")

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        command = plan["command"]
        self.assertEqual(command[:4], ["rclone", "sync", "/data/primary", "obu-crypt:hosts/test-host/primary/current"])
        self.assertIn("--delete-excluded", command)
        self.assertNotIn("--backup-dir", command)
        self.assertIn("- /Downloads/rebuildable/**", command)
        self.assertEqual(plan["verification_command"][:2], ["rclone", "cryptcheck"])
        self.assertIn("--one-way", plan["verification_command"])

    def test_runtime_state_exclusions_apply_to_copy_and_cryptcheck(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            result = self.run_cli(config)

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        copy_filters = [plan["command"][index + 1] for index, item in enumerate(plan["command"]) if item == "--filter"]
        check_filters = [
            plan["verification_command"][index + 1]
            for index, item in enumerate(plan["verification_command"])
            if item == "--filter"
        ]
        expected = {
            "- **/.config/BraveSoftware/Brave-Browser/**/IndexedDB/**",
            "- **/.config/BraveSoftware/Brave-Browser/**/Local Extension Settings/**",
            "- **/.config/BraveSoftware/Brave-Browser/**/Local Storage/**",
            "- **/.config/BraveSoftware/Brave-Browser/**/Session Storage/**",
            "- **/.config/BraveSoftware/Brave-Browser/**/Sessions/**",
            "- **/.config/BraveSoftware/Brave-Browser/**/Sync Data/**",
            "- **/.config/BraveSoftware/Brave-Browser/**/WebStorage/**",
            "- **/.config/t3code/Cache/**",
            "- **/.config/t3code/GPUCache/**",
            "- **/.config/t3code/DawnGraphiteCache/**",
            "- **/.config/t3code/DawnWebGPUCache/**",
            "- **/.config/t3code/DIPS-wal",
        }
        self.assertTrue(expected.issubset(copy_filters))
        self.assertTrue(expected.issubset(check_filters))

    def test_sync_runs_with_a_standard_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            source.mkdir()
            config = write_config(temporary)
            config.write_text(config.read_text().replace('path = "/data/primary"', f'path = "{source}"'))
            executable = temporary / "rclone"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            environment = os.environ | {"PYTHONPATH": str(ROOT / "src"), "PATH": f"{temporary}:{os.environ['PATH']}"}
            result = subprocess.run(
                [sys.executable, "-m", "obu", "--config", str(config), "sync", "primary"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tertiary_photo_library_source_excludes_its_live_container_from_secondary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = write_config(temporary)
            config.write_text(
                config.read_text().replace(
                    "[filters.primary]",
                    """[sources.secondary]
path = "/mnt/storage"
filters = ["common", "secondary"]

[sources.tertiary]
path = "/mnt/Photos"
filters = ["common", "tertiary"]

[filters.primary]""",
                )
                + """

[filters.secondary]
rules = ["- /Photos/photo-library.luks"]

[filters.tertiary]
rules = [
    "- /lost+found/**",
    "- /immich/model-cache/**",
    "- /immich/postgres/**",
]
"""
            )
            secondary = self.run_cli(config, "backup", "secondary", "--print-command")
            tertiary = self.run_cli(config, "backup", "tertiary", "--print-command")

        self.assertEqual(secondary.returncode, 0, secondary.stderr)
        secondary_plan = json.loads(secondary.stdout)
        self.assertEqual(secondary_plan["command"][2:4], ["/mnt/storage", "obu-crypt:hosts/test-host/secondary/current"])
        self.assertIn("- /Photos/photo-library.luks", secondary_plan["command"])
        self.assertIn("- /Photos/photo-library.luks", secondary_plan["verification_command"])

        self.assertEqual(tertiary.returncode, 0, tertiary.stderr)
        tertiary_plan = json.loads(tertiary.stdout)
        self.assertEqual(tertiary_plan["command"][2:4], ["/mnt/Photos", "obu-crypt:hosts/test-host/tertiary/current"])
        self.assertNotIn("- /Photos/photo-library.luks", tertiary_plan["command"])
        self.assertEqual(
            [tertiary_plan["command"][index + 1] for index, item in enumerate(tertiary_plan["command"]) if item == "--filter"][-3:],
            [
                "- /lost+found/**",
                "- /immich/model-cache/**",
                "- /immich/postgres/**",
            ],
        )

    def test_example_config_excludes_obu_live_state(self) -> None:
        example = (ROOT / "config.example.toml").read_text()

        self.assertIn('"- **/.local/state/obu/**"', example)

    def test_scoped_backup_preserves_the_path_below_the_drive_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            result = self.run_cli(
                config,
                "backup",
                "primary",
                "/data/primary/Wallpapers",
                "--print-command",
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["command"][2:4], ["/data/primary/Wallpapers", "obu-crypt:hosts/test-host/primary/current/Wallpapers"])
        self.assertNotIn("--backup-dir", plan["command"])

    def test_progress_requests_rclone_live_progress_for_copy_and_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            result = self.run_cli(config, "backup", "primary", "--progress", "--print-command")

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertIn("--progress", plan["command"])
        self.assertIn("--progress", plan["verification_command"])


    def test_plain_remote_is_rejected_before_a_backup_can_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            config.write_text(config.read_text().replace("obu-crypt:", "onidel:"))
            result = self.run_cli(config)

        self.assertEqual(result.returncode, 2)
        self.assertIn("crypt remote", result.stderr)

    def test_restore_plan_reads_only_from_the_crypt_current_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            target = Path(directory) / "recovery"
            target.mkdir()
            environment = os.environ | {"PYTHONPATH": str(ROOT / "src")}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "obu",
                    "--config",
                    str(config),
                    "restore",
                    "primary",
                    str(target),
                    "--print-command",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["command"][:3], ["rclone", "copy", "obu-crypt:hosts/test-host/primary/current"])

    def test_scoped_restore_reads_from_the_matching_backup_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            target = Path(directory) / "recovery"
            target.mkdir()
            environment = os.environ | {"PYTHONPATH": str(ROOT / "src")}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "obu",
                    "--config",
                    str(config),
                    "restore",
                    "primary",
                    str(target),
                    "--path",
                    "/data/primary/Wallpapers",
                    "--print-command",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["command"][:3],
            ["rclone", "copy", "obu-crypt:hosts/test-host/primary/current/Wallpapers"],
        )

    def test_logs_tails_the_latest_completed_run_for_a_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = write_config(temporary)
            runs = temporary / "state" / "runs"
            runs.mkdir(parents=True)
            (runs / "20260101T010101000000Z-primary.json").write_text(
                json.dumps(
                    {
                        "finished_at": "2026-01-01T01:01:01+00:00",
                        "source": "primary",
                        "returncode": 1,
                        "stderr": "first line\nsecond line\nlast line\n",
                    }
                )
            )
            result = self.run_cli(config, "logs", "--source", "primary", "--tail", "2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source=primary", result.stdout)
        self.assertNotIn("first line", result.stdout)
        self.assertIn("second line", result.stdout)
        self.assertIn("last line", result.stdout)

    def test_logs_watch_tails_the_latest_matching_live_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = write_config(temporary)
            runs = temporary / "state" / "runs"
            runs.mkdir(parents=True)
            (runs / "20260101T010101000000Z-primary.log").write_text("first line\nsecond line\nlast line\n")
            environment = os.environ | {"PYTHONPATH": str(ROOT / "src")}
            result = subprocess.run(
                ["timeout", "0.2s", sys.executable, "-m", "obu", "--config", str(config), "logs", "--watch", "--source", "primary", "--tail", "2"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertNotIn("first line", result.stdout)
        self.assertIn("second line", result.stdout)
        self.assertIn("last line", result.stdout)

    def test_status_reports_the_active_rclone_run_and_latest_statistic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = write_config(temporary)
            runs = temporary / "state" / "runs"
            runs.mkdir(parents=True)
            log = runs / "20260101T010101000000Z-primary.log"
            log.write_text("Transferred:  1 GiB / 2 GiB, 50%, 10 MiB/s, ETA 1m\n")
            (runs / "active.json").write_text(
                json.dumps(
                    {
                        "id": "20260101T010101000000Z",
                        "source": "primary",
                        "phase": "copy",
                        "pid": os.getpid(),
                        "started_at": "2026-01-01T01:01:01+00:00",
                        "log": str(log),
                    }
                )
            )
            result = self.run_cli(config, "status")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Active: primary (copy)", result.stdout)
        self.assertIn("Transferred:  1 GiB / 2 GiB, 50%, 10 MiB/s, ETA 1m", result.stdout)

    def test_status_flags_a_stale_active_run_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = write_config(temporary)
            runs = temporary / "state" / "runs"
            runs.mkdir(parents=True)
            (runs / "active.json").write_text(
                json.dumps(
                    {
                        "id": "20260101T010101000000Z",
                        "source": "primary",
                        "phase": "copy",
                        "pid": 99999999,
                        "started_at": "2026-01-01T01:01:01+00:00",
                    }
                )
            )
            result = self.run_cli(config, "status")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Stale active run marker", result.stdout)

    def test_status_treats_a_zombie_rclone_as_a_stale_active_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = write_config(temporary)
            runs = temporary / "state" / "runs"
            runs.mkdir(parents=True)
            child_pid = os.fork()
            if child_pid == 0:
                os._exit(0)
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    state = Path(f"/proc/{child_pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                    if state == "Z":
                        break
                    time.sleep(0.05)
                else:
                    self.fail("test child did not become a zombie")
                (runs / "active.json").write_text(json.dumps({"id": "crashed-run", "pid": child_pid}))
                result = self.run_cli(config, "status")
            finally:
                os.waitpid(child_pid, 0)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Stale active run marker", result.stdout)
        self.assertNotIn("Active: primary", result.stdout)

    def test_backup_archives_a_stale_active_run_marker_before_starting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            source.mkdir()
            config = write_config(temporary)
            config.write_text(config.read_text().replace('path = "/data/primary"', f'path = "{source}"'))
            runs = temporary / "state" / "runs"
            runs.mkdir(parents=True)
            (runs / "active.json").write_text(json.dumps({"id": "crashed-run", "pid": 99999999}))
            executable = temporary / "rclone"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o700)
            environment = os.environ | {"PYTHONPATH": str(ROOT / "src"), "PATH": f"{temporary}:{os.environ['PATH']}"}
            result = subprocess.run(
                [sys.executable, "-m", "obu", "--config", str(config), "backup", "primary", "--dry-run"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            archived = runs / "crashed-run.stale"
            self.assertTrue(archived.is_file())
            self.assertFalse((runs / "active.json").exists())

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_backup_notification_is_concise_and_keeps_details_in_the_run_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            source.mkdir()
            config = write_config(temporary)
            config.write_text(config.read_text().replace('path = "/data/primary"', f'path = "{source}"'))
            notification = temporary / "notification"
            rclone = temporary / "rclone"
            rclone.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' 'rclone: opaque, unpleasant transfer error details' >&2\n"
                "exit 7\n"
            )
            rclone.chmod(0o700)
            notify_send = temporary / "notify-send"
            notify_send.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$OBU_TEST_NOTIFICATION\"\n")
            notify_send.chmod(0o700)
            environment = os.environ | {
                "PYTHONPATH": str(ROOT / "src"),
                "PATH": f"{temporary}:{os.environ['PATH']}",
                "OBU_TEST_NOTIFICATION": str(notification),
            }
            result = subprocess.run(
                [sys.executable, "-m", "obu", "--config", str(config), "backup", "primary"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            records = list((temporary / "state" / "runs").glob("*-primary.json"))
            self.assertEqual(len(records), 1)
            record = json.loads(records[0].read_text())
            notification_text = notification.read_text()

        self.assertEqual(result.returncode, 7)
        self.assertEqual(
            notification_text.splitlines(),
            [
                "--app-name",
                "OBU Backup",
                "--urgency",
                "critical",
                "Backup completed with errors",
                "primary: See obu logs for details.",
            ],
        )
        self.assertIn("opaque, unpleasant transfer error details", record["stderr"])

    def test_failed_verification_notification_is_concise_and_keeps_details_in_the_run_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            source.mkdir()
            config = write_config(temporary)
            config.write_text(config.read_text().replace('path = "/data/primary"', f'path = "{source}"'))
            notification = temporary / "notification"
            rclone = temporary / "rclone"
            rclone.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = cryptcheck ]; then\n"
                "  printf '%s\\n' 'rclone: opaque, unpleasant verification error details' >&2\n"
                "  exit 8\n"
                "fi\n"
            )
            rclone.chmod(0o700)
            notify_send = temporary / "notify-send"
            notify_send.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$OBU_TEST_NOTIFICATION\"\n")
            notify_send.chmod(0o700)
            environment = os.environ | {
                "PYTHONPATH": str(ROOT / "src"),
                "PATH": f"{temporary}:{os.environ['PATH']}",
                "OBU_TEST_NOTIFICATION": str(notification),
            }
            result = subprocess.run(
                [sys.executable, "-m", "obu", "--config", str(config), "backup", "primary"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            records = list((temporary / "state" / "runs").glob("*-check-primary.json"))
            self.assertEqual(len(records), 1)
            record = json.loads(records[0].read_text())
            notification_text = notification.read_text()

        self.assertEqual(result.returncode, 8)
        self.assertEqual(
            notification_text.splitlines(),
            [
                "--app-name",
                "OBU Backup",
                "--urgency",
                "critical",
                "Backup completed with errors",
                "primary: See obu logs for details.",
            ],
        )
        self.assertIn("opaque, unpleasant verification error details", record["stderr"])

    def test_ctrl_c_records_a_cancelled_run_and_reaps_rclone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            source.mkdir()
            config = write_config(temporary)
            config.write_text(config.read_text().replace('path = "/data/primary"', f'path = "{source}"'))
            started = temporary / "rclone-started"
            cancelled = temporary / "rclone-cancelled"
            child_pid = temporary / "rclone-pid"
            executable = temporary / "rclone"
            executable.write_text(
                "#!/bin/sh\n"
                "echo $$ > \"$OBU_TEST_CHILD_PID\"\n"
                "trap 'touch \"$OBU_TEST_CANCELLED\"; exit 130' INT TERM\n"
                "touch \"$OBU_TEST_STARTED\"\n"
                "while :; do :; done\n"
            )
            executable.chmod(0o700)
            environment = os.environ | {
                "PYTHONPATH": str(ROOT / "src"),
                "PATH": f"{temporary}:{os.environ['PATH']}",
                "OBU_TEST_STARTED": str(started),
                "OBU_TEST_CANCELLED": str(cancelled),
                "OBU_TEST_CHILD_PID": str(child_pid),
            }
            process = subprocess.Popen(
                [sys.executable, "-m", "obu", "--config", str(config), "backup", "primary", "--progress"],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(started.exists(), "fake rclone did not start")

                process.send_signal(signal.SIGINT)
                _, stderr = process.communicate(timeout=10)

                self.assertEqual(process.returncode, 130, stderr)
                self.assertIn("cancelled by user", stderr)
                self.assertTrue(cancelled.exists(), "rclone did not receive a termination signal")
                self.assertFalse((temporary / "state" / "runs" / "active.json").exists())
                records = list((temporary / "state" / "runs").glob("*-primary.json"))
                self.assertEqual(len(records), 1)
                record = json.loads(records[0].read_text())
                self.assertEqual(record["returncode"], 130)
                self.assertTrue(record["cancelled"])
                self.assertEqual(record["signal"], "SIGINT")
                self.assertEqual(record["phase"], "copy")
                self.assertIn("cancelled by user", record["stderr"])
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(child_pid.read_text()), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if child_pid.exists():
                    try:
                        os.kill(int(child_pid.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_progress_finishes_when_rclone_exits_but_a_descendant_keeps_the_pty_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            source = temporary / "source"
            source.mkdir()
            config = write_config(temporary)
            config.write_text(config.read_text().replace('path = "/data/primary"', f'path = "{source}"'))
            rclone_pid = temporary / "rclone-pid"
            executable = temporary / "rclone"
            executable.write_text(
                "#!/bin/sh\n"
                "echo $$ > \"$OBU_TEST_RCLONE_PID\"\n"
                "sleep 30 &\n"
                "exit 0\n"
            )
            executable.chmod(0o700)
            environment = os.environ | {
                "PYTHONPATH": str(ROOT / "src"),
                "PATH": f"{temporary}:{os.environ['PATH']}",
                "OBU_TEST_RCLONE_PID": str(rclone_pid),
            }
            process = subprocess.Popen(
                [sys.executable, "-m", "obu", "--config", str(config), "backup", "primary", "--progress"],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertTrue(rclone_pid.exists(), "fake rclone did not start")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if rclone_pid.exists():
                    try:
                        os.killpg(int(rclone_pid.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_install_prints_the_user_timer_setup_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            result = self.run_cli(config, "install", "--print-command")

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["service"], str(ROOT / "systemd" / "obu-backup.service.in"))
        self.assertEqual(plan["timer"], str(ROOT / "systemd" / "obu-backup.timer"))
        self.assertEqual(plan["schedule"], "*-*-* 02:30:00")
        self.assertEqual(
            plan["commands"],
            [
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", "obu-backup.timer"],
            ],
        )

    def test_install_writes_the_schedule_from_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = write_config(temporary)
            state_line = f'state_dir = "{temporary / "state"}"'
            config.write_text(
                config.read_text().replace(
                    state_line,
                    f'{state_line}\nschedule = "Mon..Fri *-*-* 01:15:00"',
                )
            )
            user_units = temporary / "user-units"

            with patch("obu.install.subprocess.run") as systemctl:
                install_timer(ROOT, load_settings(config).schedule, user_units=user_units)

            timer = (user_units / "obu-backup.timer").read_text()

        self.assertIn("OnCalendar=Mon..Fri *-*-* 01:15:00", timer)
        self.assertNotIn("@@SCHEDULE@@", timer)
        self.assertEqual(systemctl.call_count, 2)
