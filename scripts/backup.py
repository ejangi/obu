#!/usr/bin/env python3
"""Repository-local launcher used by the systemd user service."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from obu.cli import main  # noqa: E402


raise SystemExit(main(["--config", str(ROOT / "config.toml"), *sys.argv[1:]]))
