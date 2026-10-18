# Quota storage backup and recovery drill

This is a maintenance-window backup for the single-host quota-storage pilot.
End all labs first. The script stops the API and storage broker, unmounts the
pool, copies it, verifies checksums and SQLite integrity, then restarts services
in dependency order. The website API is unavailable during this operation.
Do not run deployments, start containers manually, or reboot during backup.

## What is included

- The complete unmounted ext4 pool image: student files, ownership, project IDs,
  quota metadata and filesystem UUID.
- `homes.db` registry including deletion tombstones and any SQLite sidecars.
- Deployed backend Python, Dockerfile, requirements, Compose files, `.env`,
  frontend, nginx configuration and the complete application data directory.
- The installed storage agent and a SHA-256 manifest.

It does **not** include Docker images, legacy Docker home volumes (including
migration backups), Cloudflare tunnel credentials/configuration, or the host OS.
All registered student homes must first have a ready/deleted quota registry
entry; incomplete or unmigrated homes cause refusal. Reproducible image builds
or a private image registry remain necessary for whole-host recovery.

Backups contain private student data and secrets. The destination is root-only.
Use only trusted backup directories; checksums detect corruption, not malicious
replacement of both files and manifest. Symlink targets are recorded without
following them. Do not upload backups to GitHub or a public download link.

## Create and test

Run from the source checkout. No API/image rebuild is needed for these scripts.
The example uses the SD card for initial validation, not disaster protection.
Each operation needs at least the pool's logical size plus 1 GiB free (9 GiB for
an 8 GiB pool). Backup and drill retain separate copies. External mounted storage
is preferable; verify its mount before using a path on it. No automatic deletion
or retention job is installed.

```bash
sudo python3 scripts/storage-backup.py backup \
  "$HOME/linux-lab/backend" /var/backups/linux-lab/first-quota-backup

sudo python3 scripts/storage-backup.py drill \
  /var/backups/linux-lab/first-quota-backup \
  /var/backups/linux-lab/first-recovery-test

systemctl is-active linux-lab-storage.service
findmnt /srv/linux-lab-storage/pool
```

Use a new directory name for subsequent runs; existing destinations are refused.
A failed backup may leave an incomplete directory for inspection. A directory
without a valid manifest is not a completed backup. On an ordinary error the
script attempts to restore services. If restart fails, inspect systemd logs and
restore the pool and broker before restarting the API. Power loss/SIGKILL cannot
run cleanup; check services after boot. Never format the existing pool to repair
an interrupted backup.

The drill copies the backup to a separate directory, checks the copies' hashes
and database integrity, runs `e2fsck -fn`, mounts only the copied image read-only
with journal replay disabled, and checks registered homes and project IDs. It
unmounts the test image afterward. It never launches desktops or points the live
broker at restored data. This verifies recoverability of the image and registry;
a complete replacement-host/application recovery rehearsal is still required.

Afterward, start a normal lab and verify a known file and the usage banner.
Send the PASS messages and service status; do not send `.env` or database files.
Keep the successful backup and transfer a private copy off the SD card. To verify
an off-host copy on a trusted Linux machine with Python:

```bash
sudo python3 scripts/storage-backup.py verify /path/to/copied-backup
```

## Replacement-host recovery plan (operator runbook)

Do this on a replacement/test host first; automated live overwrite is deliberately
not provided. Do not combine a registry/database from one backup with another
pool image. Do not run two brokers against the same pool.

1. Verify the trusted backup and complete the isolated drill. Prepare the same
   architecture, Docker/Compose, quota utilities, Python and required lab images.
2. Keep API, storage service and pool mount stopped. Preserve any existing state
   separately. Restore the backup's backend directory, `homes.db` (and sidecars),
   `pool.img`, and `pool.uuid` to their original paths. Preserve ownership/modes.
3. Restore the matching storage agent/source version. Use the mount/service unit
   definitions in `scripts/install-quota-storage.sh` to configure the existing
   pool, without formatting it. Do not run the installer blindly: it expects a
   running API for preflight. Reload systemd and start the mount then broker.
4. Verify the UUID, `prjquota`, broker health and registry. Restore the application's
   Compose environment and start the API/proxy. Provision tunnel configuration
   separately; use a test hostname until acceptance passes.
5. Launch the same student/classroom/template. The broker recreates named Docker
   bind volumes from the restored registry as needed. Check saved file contents,
   ownership, quota enforcement, subscriptions, deleted-home behavior and access
   separation. Only then switch production traffic.

Production follow-ups: encrypted off-host backups, retention aligned with student
privacy requirements, scheduled monitoring, tested whole-host recovery, and an
agreed maximum data-loss window/recovery time. Admin home deletion does not erase
historical backup copies; their retention must be handled separately.
