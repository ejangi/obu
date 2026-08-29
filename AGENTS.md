# OBU agent guide

## Purpose

Maintain Linux backup and restore tooling for this computer. Data is stored in the configured Onidel bucket only through an rclone `crypt` remote. Rclone owns cloud credentials, crypt passwords, and salts; this repository must never read, print, or store them.

## Layout

- `./obu`: supported repository-local CLI; it selects this checkout's local `config.toml` and provides backup, restore, status, logs, and `install`.
- `src/obu/`: standard-library implementation. Each top-level `./obu` command has a matching command module with `configure` and `run`; `cli.py` only parses and dispatches. Supporting modules own rclone execution, configuration, source scoping, and notifications.
- `config.example.toml`: source-drive and crypt-remote shape. A real `config.toml` is local-only.
- `[filters.*]` in `config.toml`: persistent, reviewed backup blacklist. `common` applies to both drives; drive groups hold source-specific exclusions.
- `systemd/`: versioned user-service and timer templates. `./obu install` substitutes this checkout path, installs them into the user's systemd directory, reloads systemd, and enables the timer.
- `tests/`: public-CLI regression tests and opt-in integration scripts. Keep all test code here; `make check` is the required local verification.

## Safety invariants

- Require a remote ending in `-crypt:`; never silently use `onidel:` or another plain remote.
- Keep backup operations copy-only. Do not introduce automatic remote deletion or pruning without an explicit retention design and user approval.
- Preserve `--backup-dir` history for replacements and retain post-copy `rclone cryptcheck --one-way` verification.
- Exclusion changes are data-loss-affecting: make them explicit in the named TOML filter groups, document their reason in a comment when non-obvious, and test the generated command plan.
- Scheduled work must lock so overlapping runs fail safely, record output in the local state directory, and notify the desktop on actionable failures.

## Change workflow

Treat the CLI command plan as the test seam. Add or adjust a `unittest` regression first for each safety behavior, implement the smallest matching change, then run `make check`. Use `--print-command` before any live rclone operation. Keep README concise and update it when setup, recovery, configuration, or scheduling changes.
