"""Configuration loading; credentials intentionally remain in rclone."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import socket
import tomllib


class ConfigError(ValueError):
    """A safe-to-show configuration error."""


@dataclass(frozen=True)
class Source:
    name: str
    path: Path
    filter_rules: tuple[str, ...]
    relative_path: Path = Path(".")
    vm_image_extensions: tuple[str, ...] = ()
    skipped_vm_images: tuple[str, ...] = ()
    skip_transfer: bool = False


@dataclass(frozen=True)
class Settings:
    remote: str
    host: str
    state_dir: Path
    sources: dict[str, Source]
    verify: bool
    schedule: str


def load_settings(filename: Path) -> Settings:
    try:
        with filename.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(f"configuration file not found: {filename}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {filename}: {error}") from error

    remote = raw.get("remote")
    if not isinstance(remote, str) or not remote.endswith("-crypt:"):
        raise ConfigError("remote must name this project's rclone crypt remote (for example, obu-crypt:)")

    source_table = raw.get("sources")
    if not isinstance(source_table, dict) or not source_table:
        raise ConfigError("[sources] must define at least one drive")

    filter_table = raw.get("filters", {})
    if not isinstance(filter_table, dict):
        raise ConfigError("[filters] must contain named filter groups")
    filter_groups: dict[str, tuple[str, ...]] = {}
    image_extensions: dict[str, tuple[str, ...]] = {}
    for name, values in filter_table.items():
        if not isinstance(values, dict):
            raise ConfigError(f"filters.{name} must be a table with a rules list")
        rules = values.get("rules")
        if not isinstance(rules, list) or not all(isinstance(rule, str) and rule for rule in rules):
            raise ConfigError(f"filters.{name}.rules must be a list of non-empty rclone filter rules")
        if "unless_vm_stopped" in values:
            raise ConfigError(f"filters.{name}: replace VM-name conditions with vm_image_extensions")
        extensions = values.get("vm_image_extensions", [])
        if not isinstance(extensions, list) or not all(
            isinstance(extension, str) and extension.startswith(".")
            and extension[1:].isalnum() for extension in extensions
        ):
            raise ConfigError(f"filters.{name}.vm_image_extensions must be a list of extensions such as .qcow2")
        image_extensions[name] = tuple(extension.lower() for extension in extensions)
        filter_groups[name] = tuple(rules)

    sources: dict[str, Source] = {}
    for name, values in source_table.items():
        if not isinstance(values, dict) or not isinstance(values.get("path"), str):
            raise ConfigError(f"sources.{name}.path must be a string")
        filters = values.get("filters", [])
        if not isinstance(filters, list) or not all(isinstance(item, str) for item in filters):
            raise ConfigError(f"sources.{name}.filters must be a list of filter group names")
        unknown = [item for item in filters if item not in filter_groups]
        if unknown:
            raise ConfigError(f"sources.{name} refers to unknown filter groups: {', '.join(unknown)}")
        sources[name] = Source(
            name=name,
            path=Path(values["path"]).expanduser(),
            filter_rules=tuple(rule for group in filters for rule in filter_groups[group]),
            vm_image_extensions=tuple(dict.fromkeys(extension for group in filters for extension in image_extensions[group])),
        )

    state_value = raw.get("state_dir", "~/.local/state/obu")
    if not isinstance(state_value, str):
        raise ConfigError("state_dir must be a path string")
    host = raw.get("host") or socket.gethostname()
    if not isinstance(host, str) or not host:
        raise ConfigError("host must be a non-empty string")
    verify = raw.get("verify", True)
    if not isinstance(verify, bool):
        raise ConfigError("verify must be true or false")
    schedule = raw.get("schedule", "*-*-* 02:30:00")
    if not isinstance(schedule, str) or not schedule.strip() or "\n" in schedule or "\r" in schedule:
        raise ConfigError("schedule must be a non-empty systemd OnCalendar expression on one line")
    return Settings(
        remote=remote,
        host=host,
        state_dir=Path(state_value).expanduser(),
        sources=sources,
        verify=verify,
        schedule=schedule.strip(),
    )
