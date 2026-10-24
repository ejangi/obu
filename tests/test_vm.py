"""Generic image detection through the public CLI command plan and run records."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_cli import ROOT, write_config, stub_rclone_environment


class VMBackupTests(unittest.TestCase):
    def configure_images(self, temporary):
        config = write_config(temporary)
        config.write_text(config.read_text().replace('path = "/data/primary"', f'path = "{temporary}"')
                          .replace('filters = ["common", "primary"]', 'filters = ["common", "primary", "vm_images"]') + '''
[filters.vm_images]
# Skip only images whose lock/access check fails for this run.
vm_image_extensions = [".qcow", ".qcow2", ".vmdk", ".vdi", ".vhd", ".vhdx", ".img", ".raw"]
rules = []
''')
        return config

    def test_generic_images_are_skipped_independently_and_other_files_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = self.configure_images(temporary)
            images = temporary / "arbitrary folder"
            images.mkdir()
            for name in ("busy.QCOW2", "offline.qcow2", "busy.vmdk", "offline.vdi", "offline.vhd", "offline.vhdx", "busy.img", "offline.raw", "notes.txt"):
                (images / name).touch()
            environment = stub_rclone_environment(temporary, "exit 0\n")
            probe = temporary / "qemu-img"
            probe.write_text('#!/bin/sh\ncase "$3" in */busy.*) echo "image is in use" >&2; exit 1;; esac\necho \'{"format":"raw"}\'\n')
            probe.chmod(0o700)
            def cli(*args):
                return subprocess.run([sys.executable, "-m", "obu", "--config", str(config), *args],
                                      cwd=ROOT, env=environment, capture_output=True, text=True)
            expected = ["arbitrary folder/busy.QCOW2", "arbitrary folder/busy.img", "arbitrary folder/busy.vmdk"]
            for operation in ("backup", "sync"):
                result = cli(operation, "primary", "--print-command")
                self.assertEqual(result.returncode, 0, result.stderr)
                plan = json.loads(result.stdout)
                self.assertEqual(plan["skipped_vm_images"], expected)
                for key in ("command", "verification_command"):
                    command = plan[key]
                    for path in expected:
                        self.assertIn("- /" + path, command)
                    self.assertFalse(any("offline" in argument for argument in command))
                if operation == "sync":
                    self.assertNotIn("--delete-excluded", plan["command"])
            result = cli("backup", "primary")
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [json.loads(p.read_text()) for p in (temporary / "state" / "runs").glob("*.json")]
            self.assertEqual({r["phase"] for r in records}, {"copy", "cryptcheck"})
            self.assertTrue(all(r["skipped_vm_images"] == expected for r in records))
            status = cli("status")
            self.assertIn("VM images skipped:", status.stdout)
            self.assertIn("Last verified full backup: never", status.stdout)
            # A directly selected busy image is skipped, and directory scoping rebases rules.
            scoped = cli("backup", "primary", "arbitrary folder/busy.QCOW2", "--print-command")
            self.assertTrue(json.loads(scoped.stdout)["skip_transfer"])
            scoped = cli("backup", "primary", "arbitrary folder", "--print-command")
            self.assertIn("- /busy.QCOW2", json.loads(scoped.stdout)["command"])
            self.assertEqual(cli("backup", "primary", "arbitrary folder/busy.QCOW2").returncode, 0)

    def test_missing_probe_skips_images_but_not_the_rest_of_the_source(self):
        from unittest.mock import patch
        from obu.config import Source
        from obu.vm import resolve_filters
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "disk.qcow2").touch()
            (path / "document.txt").touch()
            with patch("obu.vm.subprocess.run", side_effect=FileNotFoundError("qemu-img")):
                source = resolve_filters(Source("primary", path, (), vm_image_extensions=(".qcow2",)))
            self.assertEqual(source.skipped_vm_images, ("disk.qcow2",))
            self.assertIn("- /disk.qcow2", source.filter_rules)
            self.assertFalse(source.skip_transfer)

    def test_invalid_image_extensions_are_rejected(self):
        from obu.config import ConfigError, load_settings
        for extensions in ('".qcow2"', '["qcow2"]', '[".*"]', '[".qcow2/path"]'):
            with self.subTest(extensions=extensions), tempfile.TemporaryDirectory() as directory:
                config = write_config(Path(directory))
                with config.open("a") as handle:
                    handle.write('\n[filters.vm_images]\nrules = []\nvm_image_extensions = ' + extensions + '\n')
                with self.assertRaises(ConfigError):
                    load_settings(config)

    def test_special_names_are_escaped_and_symlinks_are_not_probed(self):
        from unittest.mock import patch
        from obu.config import Source
        from obu.vm import resolve_filters
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "disk[1].qcow2").touch()
            (path / "link.qcow2").symlink_to(path / "disk[1].qcow2")
            with patch("obu.vm.subprocess.run", return_value=subprocess.CompletedProcess([], 1)) as probe:
                source = resolve_filters(Source("primary", path, (), vm_image_extensions=(".qcow2",)))
            self.assertEqual(probe.call_count, 1)
            self.assertIn(r"- /disk\[1\].qcow2", source.filter_rules)

    def test_real_qemu_lock_skips_busy_image_and_includes_it_after_release(self):
        import shutil
        import select
        from obu.config import Source
        from obu.vm import resolve_filters
        if not shutil.which("qemu-img") or not shutil.which("qemu-io"):
            self.skipTest("QEMU utilities unavailable")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            image = path / "disk.qcow2"
            subprocess.run(["qemu-img", "create", "-f", "qcow2", str(image), "1M"],
                           check=True, capture_output=True)
            source = Source("primary", path, (), vm_image_extensions=(".qcow2",))
            self.assertFalse(resolve_filters(source).skipped_vm_images)
            holder = subprocess.Popen(["qemu-io", "-f", "qcow2", str(image)],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                # Wait for qemu-io to open the image before starting a competing probe.
                holder.stdin.write(b"info\n")
                holder.stdin.flush()
                ready, _, _ = select.select([holder.stdout], [], [], 3)
                self.assertTrue(ready, "qemu-io did not report image information")
                self.assertIn(b"qcow2", holder.stdout.readline())
                result = resolve_filters(source)
                self.assertEqual(result.skipped_vm_images, ("disk.qcow2",))
                self.assertIn("- /disk.qcow2", result.filter_rules)
            finally:
                try:
                    holder.communicate(b"quit\n", timeout=3)
                except subprocess.TimeoutExpired:
                    holder.kill()
                    holder.communicate()
            self.assertFalse(resolve_filters(source).skipped_vm_images)
