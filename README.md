# OBU backup

OBU runs conservative, encrypted backups of this computer's primary 1 TB and secondary 2 TB drives. It uses the existing `onidel:ejangi-nix` bucket only through an rclone **crypt** remote; rclone keeps all cloud credentials and encryption secrets.

## First setup

1. Confirm the configured storage remote works:

   ```bash
   rclone lsd onidel:ejangi-nix
   ```

2. Run `rclone config` and create a new remote with this shape. The storage choice is labelled **Encrypt/Decrypt a remote**; enter `crypt` at the `Storage>` prompt if it is not visible in the list.

   ```text
   name> obu-crypt
   Storage> crypt
   remote> onidel:ejangi-nix
   filename_encryption> standard
   directory_name_encryption> true
   ```

   Set a strong or generated crypt password and a generated salt. Save both in a password manager: they are required to restore the data on another machine. They must never be committed or copied into `config.toml`. Rclone stores them in lightly obscured form in its local configuration, so protect that file and consider setting an rclone configuration password.

3. Confirm the new crypt remote opens successfully:

   ```bash
   rclone lsd obu-crypt:
   ```

   Always use `obu-crypt:` for backups and restores; using `onidel:` directly bypasses encryption. This bucket is dedicated to this computer; OBU keeps each drive separately under its encrypted `hosts/<host>/<drive>/` layout.

4. Copy `config.example.toml` to `config.toml`, replace both mounted-drive paths, and optionally set a stable hostname.
5. Review the `[filters.common]`, `[filters.primary]`, and `[filters.secondary]` sections in `config.toml`. They are the persistent blacklist and use native rclone filter syntax. Keep only files that can be safely recreated; a leading `-` excludes a pattern. Each drive selects its ordered groups with `filters = ["common", "primary"]` (or `secondary`).
6. Review the planned commands, then simulate the transfer:

   ```bash
   python3 scripts/backup.py all --print-command
   python3 scripts/backup.py all --dry-run
   ```

7. Enable the nightly systemd user timer:

   ```bash
   python3 scripts/install_user_timer.py
   ```

The timer runs at 02:30 with a randomized delay of up to 30 minutes and catches up after downtime. Change `systemd/obu-backup.timer` and rerun the installer to alter that schedule.

## Operations

Run one drive with `python3 scripts/backup.py backup primary`; use `secondary` for the 2 TB drive. Run `python3 scripts/backup.py status` to read the last recorded runs in `~/.local/state/obu/runs/`.

Backups use `rclone copy`, never automatic remote deletion. If an existing remote object is replaced, its earlier version moves to `hosts/<host>/<drive>/history/<timestamp>` in the crypt remote. This protects against conflicts and makes manual recovery possible. A successful transfer is followed by `rclone check --one-way`; failures are persisted locally and raise a desktop notification when `notify-send` is available.

Restore the current version into an existing empty destination with:

```bash
python3 scripts/backup.py restore primary /path/to/restore --dry-run
python3 scripts/backup.py restore primary /path/to/restore
```

For an older version, list and copy the encrypted `history/` path with rclone after first using `rclone lsd obu-crypt:hosts/<host>/primary/history`.

## Development

Run `make check`. The standard-library test suite covers the public CLI plan: encryption guardrails, safe copy semantics, history, and filters. No test or script reads rclone configuration or credentials.
