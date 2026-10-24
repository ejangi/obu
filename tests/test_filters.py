"""Verify generic cache filters against local files, with no cloud access."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.test_cli import ROOT


class GenericFilterTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("rclone"), "local filter verification requires rclone")
    def test_cache_patterns_match_at_any_depth_and_keep_persistent_data(self):
        plan_result = subprocess.run(
            [sys.executable, "-m", "obu", "--config", str(ROOT / "config.example.toml"),
             "backup", "primary", "--print-command"],
            env=os.environ | {"PYTHONPATH": str(ROOT / "src")},
            capture_output=True, text=True, check=True,
        )
        plan = json.loads(plan_result.stdout)
        filters = []
        for i, value in enumerate(plan["command"]):
            if value == "--filter":
                filters.extend(["--filter", plan["command"][i + 1]])
        excluded = [
            "GPUCache/data", "DawnGraphiteCache/data", "Code Cache/item", "folderCache.json", "user/.config/example-client/GPUCache/data",
            "user/.var/app/example-client/config/profile/DawnGraphiteCache/data",
            "user/.config/other-client/DawnWebGPUCache/data",
            "user/profile/Cache/item", "user/profile/Code Cache/item",
            "user/client/htmlcache/item", "user/client/folderCache.json",
        ]
        retained = [
            "user/.config/example-client/IndexedDB/data",
            "user/.config/example-client/Local Storage/data",
            "user/.config/example-client/sql/db.sqlite",
            "user/mail/inbox", "user/settings.json", "user/GPUCache-backup/data",
            "user/CacheNotes/document.txt",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in excluded + retained:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test data")
            result = subprocess.run(
                ["rclone", "lsf", str(root), "--config", os.devnull,
                 "--recursive", "--files-only", *filters],
                capture_output=True, text=True, check=True,
            )
        self.assertEqual(set(result.stdout.splitlines()), set(retained))

    @unittest.skipUnless(shutil.which("rclone"), "local filter verification requires rclone")
    def test_brace_consolidation_keeps_file_and_directory_exclusions_scoped(self):
        old_rules = [
            "- **/.config/example-client/**/Preferences",
            "- **/.config/example-client/**/Cookies",
            "- **/.config/example-client/**/IndexedDB/**",
            "- **/.config/example-client/**/Local Storage/**",
            "- .assets/textures/**", "- .assets/models/**",
        ]
        combined_rules = [
            "- **/.config/example-client/**/{Preferences,Cookies}",
            "- **/.config/example-client/**/{IndexedDB,Local Storage}/**",
            "- .assets/{textures,models}/**",
        ]
        excluded = [
            "user/.config/example-client/profile/Preferences",
            "user/.config/example-client/profile/Cookies",
            "user/.config/example-client/profile/IndexedDB/data",
            "user/.config/example-client/profile/Local Storage/data",
            "user/.assets/textures/file", "user/.assets/models/file",
        ]
        retained = [
            "user/.config/other-client/profile/Preferences",
            "user/.config/other-client/profile/IndexedDB/data",
            "user/.config/example-client/Preferences",
            "user/.config/example-client/profile/bookmarks",
            "user/.assets/documents/file",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in excluded + retained:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            for rules in (old_rules, combined_rules):
                flags = [part for rule in rules for part in ("--filter", rule)]
                result = subprocess.run(
                    ["rclone", "lsf", str(root), "--config", os.devnull,
                     "--recursive", "--files-only", *flags],
                    capture_output=True, text=True, check=True,
                )
                self.assertEqual(set(result.stdout.splitlines()), set(retained))
