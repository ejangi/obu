from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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
rules = ["- /Downloads/rebuildable/**"]
""".format(state=tmp_path / "state")
    )
    return config


class BackupCliTests(unittest.TestCase):
    """The CLI's print plan is the supported seam for reviewing a backup."""

    def run_cli(self, config: Path) -> subprocess.CompletedProcess[str]:
        environment = os.environ | {"PYTHONPATH": str(ROOT / "src")}
        return subprocess.run(
        [
            sys.executable,
            "-m",
            "obu",
            "--config",
            str(config),
            "backup",
            "primary",
            "--print-command",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        )

    def test_backup_prints_a_copy_plan_with_version_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = write_config(Path(directory))
            result = self.run_cli(config)

        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        command = plan["command"]
        self.assertEqual(command[:3], ["rclone", "copy", "/data/primary"])
        self.assertEqual(command[3], "obu-crypt:hosts/test-host/primary/current")
        self.assertIn("--backup-dir", command)
        self.assertIn("obu-crypt:hosts/test-host/primary/history/", command[command.index("--backup-dir") + 1])
        self.assertNotIn("--filter-from", command)
        self.assertEqual(
            [command[index + 1] for index, item in enumerate(command) if item == "--filter"],
            ["- **/.cache/**", "- **/*.tmp", "- /Downloads/rebuildable/**"],
        )


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
