"""Probe configured image extensions without depending on VM names or locations."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
from typing import Iterator

from .config import Source


def image_paths(source: Source) -> Iterator[Path]:
    if source.path.is_file():
        candidates = iter((source.path,))
    else:
        candidates = (
            Path(directory) / name
            for directory, _, names in os.walk(source.path, followlinks=False)
            for name in names
        )
    for path in candidates:
        # --links backs up symlinks as metadata, never their target contents.
        if not path.is_symlink() and path.suffix.lower() in source.vm_image_extensions:
            yield path


def literal_filter(path: str) -> str:
    return "- /" + "".join("\\" + char if char in "\\*?[]{}" else char for char in path)


def resolve_filters(source: Source) -> Source:
    if not source.vm_image_extensions:
        return source
    rules = []
    skipped = []
    skip_transfer = False
    for path in image_paths(source):
        # Do not use --force-share: its purpose is to bypass active QEMU locks.
        command = ["qemu-img", "info", "--output=json", str(path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10,
                                    env=os.environ | {"LC_ALL": "C"})
            available = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            available = False
        if not available:
            relative = path.relative_to(source.path) if source.path.is_dir() else Path(".")
            original = source.relative_path / relative
            skipped.append(original.as_posix())
            if relative == Path("."):
                skip_transfer = True
            else:
                rules.append(literal_filter(relative.as_posix()))
    # Temporary exclusions must precede include rules, and stay fixed for verification.
    return replace(source, filter_rules=tuple(sorted(rules)) + source.filter_rules,
                   skipped_vm_images=tuple(sorted(skipped)), skip_transfer=skip_transfer)
