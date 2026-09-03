"""Run conservative, encrypted rclone backups and restores."""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path
import sys

from . import all as all_command
from . import backup, install, logs, restore, status, sync
from .config import ConfigError, load_settings
from .install import InstallError


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=description_for(sys.modules[__name__]), add_help=False)
    add_help_option(result)
    result.add_argument("--config", type=Path, default=Path("config.toml"), help="TOML configuration file")
    commands = result.add_subparsers(dest="action", required=True)
    add_command(commands, "backup", backup)
    add_command(commands, "all", all_command)
    add_command(commands, "sync", sync)
    add_command(commands, "restore", restore)
    add_command(commands, "status", status)
    add_command(commands, "logs", logs)
    add_command(commands, "install", install)
    return result


def add_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    command: object,
) -> None:
    description = description_for(command)
    command_parser = commands.add_parser(name, help=description.splitlines()[0], description=description, add_help=False)
    add_help_option(command_parser)
    command.configure(command_parser)
    command_parser.set_defaults(handler=command.run)


def add_help_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-h", "--help", "-?", action="help", help="show this help message and exit")


def description_for(source: object) -> str:
    return inspect.getdoc(source) or "OBU command."


def main(argv: list[str] | None = None, *, project_root: Path | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        settings = load_settings(arguments.config)
        return arguments.handler(settings, arguments, project_root)
    except (ConfigError, InstallError) as error:
        print(f"obu-backup: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
