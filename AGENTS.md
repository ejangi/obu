# OBU agent guide

## Purpose

Maintain Linux backup and restore tooling for this computer. Data is stored in the configured Onidel bucket only through an rclone `crypt` remote. Rclone owns cloud credentials, crypt passwords, and salts; this repository must never read, print, or store them.

## Layout

- `src/obu/`: standard-library Python CLI, backup planning/execution, notifications, and TOML parsing.
- `config.example.toml`: source-drive and crypt-remote shape. A real `config.toml` is local-only.
- `[filters.*]` in `config.toml`: persistent, reviewed backup blacklist. `common` applies to both drives; drive groups hold source-specific exclusions.
- `systemd/` and `scripts/install_user_timer.py`: user-level scheduled execution.
- `tests/`: public-CLI regression tests. `make check` is the required local verification.

## Safety invariants

- Require a remote ending in `-crypt:`; never silently use `onidel:` or another plain remote.
- Keep backup operations copy-only. Do not introduce automatic remote deletion or pruning without an explicit retention design and user approval.
- Preserve `--backup-dir` history for replacements and retain post-copy `rclone check --one-way` verification.
- Exclusion changes are data-loss-affecting: make them explicit in the named TOML filter groups, document their reason in a comment when non-obvious, and test the generated command plan.
- Scheduled work must lock so overlapping runs fail safely, record output in the local state directory, and notify the desktop on actionable failures.

## Change workflow

Treat the CLI command plan as the test seam. Add or adjust a `unittest` regression first for each safety behavior, implement the smallest matching change, then run `make check`. Use `--print-command` before any live rclone operation. Keep README concise and update it when setup, recovery, configuration, or scheduling changes.
