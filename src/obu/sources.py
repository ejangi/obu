"""Select and safely scope configured backup sources."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .config import ConfigError, Settings, Source


def selected(settings: Settings, name: str) -> Source:
    try:
        return settings.sources[name]
    except KeyError as error:
        raise ConfigError(f"unknown source {name!r}; choose one of: {', '.join(sorted(settings.sources))}") from error


def scoped(source: Source, path: Path) -> Source:
    root = source.path.resolve()
    candidate = path.expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative_path = resolved.relative_to(root)
    except ValueError as error:
        raise ConfigError(f"path must be inside {source.path}: {path}") from error
    if relative_path == Path("."):
        return source
    return replace(source, path=resolved, relative_path=relative_path)
