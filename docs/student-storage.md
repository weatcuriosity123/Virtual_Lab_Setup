# Student storage: subscriptions and hard quotas

This is a single-host pilot. Verified Cloudflare identity, classroom enrollment,
`PERSISTENT_HOME_TEMPLATES` approval and an active student storage subscription are
required for a saved home. Everyone else uses the template's temporary `/config`
tmpfs (300 MiB for the original Linux template; 512 MiB in the CSE pilot).

The dashboard assigns persistence, optional expiry and a requested allowance
(64–16384 MiB, default 1024 MiB) to 1–500 enrolled emails at a time. Assignments are
college-scoped, atomic and audited. Payments are not integrated. Expiry, revocation
and allowance changes apply at the NEXT session; they do not modify a running home.
Disabling enrollment blocks access independently of storage subscriptions.

## Storage modes

- `PERSISTENT_STORAGE_BACKEND=legacy`: ordinary named Docker volumes, with no hard
  disk limit. The dashboard explicitly marks requested allowances as pending.
- `PERSISTENT_STORAGE_BACKEND=quota`: host service provisions an ext4 project for
  each home, sets and verifies a kernel hard block limit, and mounts only that home
  into the student container. Provisioning failure never falls back to temporary
  or unlimited storage. A 100,000-inode hard ceiling also applies per home.

Homes are keyed by college, classroom, template, verified subject and email. Changing
identity/template IDs requires migration; it does not adopt another student's home.
Files, editor settings and stored credentials under `/config` persist. Unsaved edits,
processes and files outside `/config` do not. The quota covers the HOME, not the entire
container writable layer or `/tmp`; whole-container disk containment remains future
isolation work. Keep the one-student pilot until container-level acceptance passes.

## Install the quota backend on the Pi

The maintainer verified hard project-quota enforcement on a disposable ext4 image.
The root ext4 filesystem lacks the project/quota features. This installer does NOT
change root features, partitions or fstab. It preallocates a separate filesystem
image and installs a systemd mount plus a root-only Unix-socket storage service.
The loop-backed image is a pilot design; a dedicated SSD/EBS filesystem is preferable
for production, with a separately reviewed setup and capacity plan.

1. Export needed work; end all labs. Deploy current API with
   `bash scripts/install-classrooms.sh ~/linux-lab/backend`.
2. Install missing host prerequisites (quota tools were already present on this Pi):
   `sudo apt-get install -y rsync quota e2fsprogs util-linux`.
3. From the source checkout run:
   `sudo bash scripts/install-quota-storage.sh "$HOME/linux-lab/backend" 8`.
   This reserves **8 GiB** of host disk. It refuses insufficient space (at least
   5 GiB must remain outside the pool), live sessions, a custom Compose override,
   custom COMPOSE_FILE, and ambiguous/unidentified existing pool files.
4. In `/admin`, assign Persistent and **1024 MiB** to your test email/classroom.
5. Start a new lab. The first launch copies an existing legacy home into its project,
   preserves ownership and symlinks, and checksum-verifies copied content before
   marking it ready. Devices and special files are not migrated. The original Docker
   volume is retained as a migration backup. If the old home is larger than its
   allowance, provisioning fails; raise the allowance and retry. No originals are
   deleted by migration.

The installer writes an app-owned `docker-compose.override.yml` to mount only the
service socket directory into the API. Student containers do not receive this socket
or extra privileges. It backs up `.env`, enables quota mode and recreates the API.
A successful image is reused on reruns, not reformatted or resized. Rerunning with
another size does NOT resize an existing pool. Stop labs before rerunning/upgrading
the host service. Pool expansion is not automated in this version.

## Capacity and lifecycle

The service reserves requested allowances against 90% of filesystem capacity, leaving
headroom; there is no overcommit of saved-home allowances. Expired subscriptions retain
their allocation/data until the home is deleted. A reduced allowance below actual usage
is rejected at next launch. The remaining pool budget may be lower than the image size
because filesystem metadata also occupies space. App settings/extension caches count
against the student's allowance.

A root-owned registry is kept in `/var/lib/linux-lab-storage/homes.db`. The pool image
and saved UUID are in the same directory; homes mount beneath
`/srv/linux-lab-storage/pool`. Each request checks the expected filesystem UUID and
quota mount. A missing pool/service blocks saved-home starts. Systemd reattaches the
image after reboot; no ephemeral `/dev/loopN` device number is saved in the API.
Run one API worker and one storage service; API locks are process-local.

The lab banner reports kernel-accounted used bytes / enforced limit, refreshed about
every 30 seconds. Admin Saved student homes shows the same current limit. Student
subscription rows show the requested NEXT-start allowance. File managers/`df` may
show the whole pool capacity instead of the project allowance; the banner is the
quota display. Existing pre-update sessions need a fresh start to record their mount.

## Permanent deletion

In `/admin` → Saved student homes, select the correct classroom/student/template/home
and type `DELETE student@email`. Running AND stopped container references block deletion.
API authorization, typed confirmation and audit apply to both storage backends.
Quota deletion removes the Docker bind-volume record and the home directory through
the host service. A durable tombstone prevents a later session from restoring the old
migration backup. The subscription remains enabled; next launch makes a fresh home.
Only that selected home is deleted. Original migration copies and separately maintained
backups are explicitly retained; secure media erasure is not promised. Backup removal
requires a separate host-operator retention process. There is no dashboard undo.

Unrecognized external volumes are refused. A new app registry records homes even when
session startup fails; old known homes are discovered from session history. Preserve
both databases. No automatic retention/deletion schedule is implemented.

## Required acceptance on the Pi

1. Confirm the old `Documents/persistence-test.txt` survives migration and usage appears.
2. With only the test lab open, write a disposable file until the assigned home quota
   rejects further writes with `Disk quota exceeded`, then immediately remove it.
   Test as the desktop student, not host root. The allowance includes existing files.
3. End/relaunch; verify persistence, owner isolation and expiry fallback to temporary.
4. End labs; reboot the Pi; verify the service/pool and saved-home launch recover.
5. Use a disposable test home to validate deletion, restart, and creation of an empty
   home without restoring its retained old backup.
6. Verify a storage-service outage prevents a persistent launch instead of falling back.

Development checks mock privileged operations. They test migration verification,
original preservation, interrupted-state behavior, shrink protection, ownership,
subscription expiry, deletion tombstones, usage authorization and unavailable-service
handling. The full installer, mount lifecycle and container write test need real-host
validation; passing unit tests is not a production-readiness claim.

## Troubleshooting and recovery

- `sudo systemctl status linux-lab-storage.service --no-pager`
- `sudo journalctl -u linux-lab-storage.service -n 60 --no-pager`
- `findmnt /srv/linux-lab-storage/pool`
- `docker volume ls --filter label=linux-lab.storage=home-v1` (retained originals)
- `docker volume ls --filter label=linux-lab.storage=quota-v1` (quota mounts)

Do not volume-prune retained originals. Do not switch back to legacy mode after new
work has been saved in the pool: that would expose an outdated original, not the latest
home. Restore service health instead. SQLite backups alone do not back up student files.
A complete backup must include the pool data, host registry/UUID, application database
and configuration while writes are stopped. Tested backup/restore and disk-failure
recovery remain the next work item. An image and its original copy on one SD card do
not protect against SD card failure.

## Backup and recovery

See [backup-recovery.md](backup-recovery.md) for a cold pool backup and isolated
read-only recovery drill. Keep the registry, application database and pool from
the same backup together. Reboot persistence and in-lab quota enforcement have
passed on the pilot Pi; backup/recovery host acceptance remains required.
