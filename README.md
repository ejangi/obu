# Orchestrated Back Up

OBU runs conservative, encrypted backups of your computer's drives. It uses an S3-compatible bucket only through an rclone **crypt** remote; rclone keeps all cloud credentials and encryption secrets.

## First setup

1. Confirm the configured storage remote works:

   ```bash
   rclone lsd <provider>:<bucket>
   ```

2. Run `rclone config` and create a new remote with this shape. The storage choice is labelled **Encrypt/Decrypt a remote**; enter `crypt` at the `Storage>` prompt if it is not visible in the list.

   ```text
   name> obu-crypt
   Storage> crypt
   remote> <provider>:<bucket>
   filename_encryption> standard
   directory_name_encryption> true
   ```

   Set a strong or generated crypt password and a generated salt. Save both in a password manager: they are required to restore the data on another machine. They must never be committed or copied into `config.toml`. Rclone stores them in lightly obscured form in its local configuration, so protect that file and consider setting an rclone configuration password.

3. Confirm the new crypt remote opens successfully:

   ```bash
   rclone lsd obu-crypt:
   ```

   Always use `obu-crypt:` for backups and restores; using `<provider>:` directly bypasses encryption. This bucket is dedicated to this computer; OBU keeps each drive separately under its encrypted `hosts/<host>/<drive>/` layout.

4. Copy `config.example.toml` to `config.toml`, replace the configured source paths, and optionally set a stable hostname.
5. Review the `[filters.*]` sections in `config.toml`. They are the persistent blacklist and use native rclone filter syntax. Keep only files that can be safely recreated; a leading `-` excludes a pattern. Each source selects its ordered groups with `filters = ["common", "primary"]`.
6. Review the planned commands, then simulate the transfer:

   ```bash
   ./obu all --print-command
   ./obu all --dry-run
   ```

7. Set `schedule` in `config.toml` if the default 02:30 daily run does not suit, then enable the systemd user timer:

   ```bash
   ./obu install
   ```

The timer uses the `schedule` systemd `OnCalendar` expression from `config.toml`, adds a randomized delay of up to 30 minutes, and catches up after downtime. After changing `schedule`, rerun `./obu install` to regenerate and reload the timer. Inspect the setup without changing user units with `./obu install --print-command`.

## Operations

Run one configured source with `./obu backup primary`; this checkout also uses `secondary` for `/mnt/storage` and `tertiary` for the unlocked `/mnt/Photos` filesystem. `secondary` explicitly excludes `/Photos/photo-library.luks`, so the live encrypted container is not copied while Immich uses it. Run `./obu status` to read the last recorded runs in `~/.local/state/obu/runs/`.

While OBU has started rclone itself, `status` also reports the active source, phase (`copy` or `cryptcheck`), PID, start time, and the latest one-line rclone statistic from its private live log. Statistics update every 30 seconds. If a crash leaves an active marker for a dead process, `status` flags it; the next safely locked backup archives that marker as a `.stale` record before starting.

Use `./obu --help` (or `-h` or `-?`) for the current command list, and `./obu <command> --help` for that command's options. These screens are generated from the command modules, so they stay aligned with the CLI.

For a foreground run, add `--progress` to see rclone's live byte count, percentage, rate, ETA, and active transfers. It remains opt-in, so scheduled backups stay quiet:

```bash
./obu backup primary --progress
./obu all --progress
```

The same flag works with `restore`. It also displays the subsequent `cryptcheck` progress. Run it from a terminal; closing that terminal stops the foreground backup.

Each completed copy or verification run has a private JSON record there. Rclone output is capped at 16 KiB per record. To inspect the last lines of the most recent completed run, use:

```bash
./obu logs --tail 50
./obu logs --source primary --tail 100
./obu logs --watch --source primary
```

`logs` reads a completed record by default. Add `--watch` to follow the newest matching private run log, like `tail -F`; it switches to a newer run when one starts. Press Ctrl-C to stop watching without interrupting the backup. Foreground runs started with `--progress` provide live transfer statistics; quiet scheduled runs append rclone output and errors.

To back up one file or directory before running a full drive backup, pass it as the optional second positional argument. The first argument is a configured source name. OBU preserves the path below that source's encrypted backup root:

```bash
./obu backup secondary /mnt/storage/Wallpapers --dry-run
./obu backup secondary /mnt/storage/Wallpapers
```

The target path must remain inside the selected source; a scoped backup of `Wallpapers` is stored below `secondary/current/Wallpapers` and will be reused by a later full secondary backup.

To exercise decryption and a checksum comparison without touching the original data, run the opt-in Wallpapers integration test after its scoped backup exists:

```bash
make integration-wallpapers
```

It restores only that encrypted subtree to a newly-created `/tmp/obu-restore-*` directory, runs `rclone check --one-way --links` against `/mnt/storage/Wallpapers`, and removes the temporary directory afterwards. Run `python3 tests/integration_restore_check.py --keep-temp` when inspection is needed.

Backups use `rclone copy`, never automatic remote deletion. Symlinks are preserved without following their targets. A successful transfer is followed by `rclone cryptcheck --one-way`; failures are persisted as private local records with at most 16 KiB of rclone output. When `notify-send` is available, the desktop notification simply says that the backup completed with errors and directs you to `obu logs` for the details.

To make a remote current tree match a source and remove paths now excluded by its filters, use the explicit `sync` command. It uses `rclone sync --delete-excluded`, so always review the plan and dry run before performing it:

```bash
./obu sync secondary --print-command
./obu sync secondary --dry-run
./obu sync secondary --progress
```

`sync` also runs `cryptcheck` after a successful transfer.

Restore a full current drive backup into an existing empty destination with:

```bash
mkdir /tmp/obu-primary-restore
./obu restore primary /tmp/obu-primary-restore --dry-run
./obu restore primary /tmp/obu-primary-restore
```

Restore one folder or one file by adding `--path`. Paths are relative to the configured drive root (absolute paths within that drive also work):

```bash
mkdir /tmp/obu-wallpapers-restore
./obu restore secondary /tmp/obu-wallpapers-restore --path Wallpapers

mkdir /tmp/obu-file-restore
./obu restore secondary /tmp/obu-file-restore --path Wallpapers/example.jpg
```

The target must exist and be empty, protecting it from accidental overwrite. A scoped restore reads only the matching encrypted backup subtree; it does not require a whole-drive restore.

## Development

Run `make check`. The standard-library test suite covers the public CLI plan: encryption guardrails, copy and sync semantics, and filters. No test or script reads rclone configuration or credentials.
